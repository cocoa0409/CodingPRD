"""Dog registration, vaccination/license verification, and the resubmission
cycle."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    add_dog,
    assert_dog,
    create_dog_payload,
    make_member_headers,
    register_member,
    resubmit_dog_payload,
    set_clock,
    setup_active_member,
    validate_error,
    validate_paginated,
    validate_success,
    verify_dog,
    verify_dog_payload,
)

ADMIN = TEST_USERS["park_admin_headers"]


class TestDogRegistration:
    def test_create_dog_invalid_size_class_rejected(self, api):
        """PRD §3.2: "With an account in place, a member registers each dog
        under their own account — administrators may register on a member's
        behalf — by supplying the dog's `name`, a `size_class` of `SMALL` or
        `LARGE` that will later gate area admission, the municipal
        `license_number`, and the rabies `vaccination_expires_on` as an ISO
        date."
        PRD §2.7: "5. **Request shape** — required fields present, enum values
        valid, exactly one of `dog_id` and `guest_pass_id` supplied at check-in,
        `ends_at` strictly after `starts_at`, `peak_capacity` not exceeding
        `capacity`, pagination parameters within bounds: `ERR_INVALID_REQUEST`."

        Design: Corner/entities/create_dog_invalid_size_class_rejected
        """
        member = register_member(full_name="Own Er", email="owner@x.com")
        payload = create_dog_payload(size_class="MEDIUM")
        resp = api.create_dog(member["id"], payload,
                              make_member_headers(member["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_list_member_dogs_scoped_to_parent(self, api):
        """PRD §3.2: "Dogs are readable by their owner and by stewards and
        administrators, and listing a member's dogs follows the same self-only
        rule for the `Member` role."
        PRD §2.8: "Endpoints whose paths chain identifiers — a dog or
        membership beneath a member, a closure or waste station beneath an area
        — validate path identifiers from left to right"

        Design: Corner/entities/list_member_dogs_scoped_to_parent
        """
        m1 = register_member(full_name="M One", email="m1@x.com")
        d1 = add_dog(m1["id"], name="Pip", size_class="SMALL",
                     license_number="LIC-A")
        m2 = register_member(full_name="M Two", email="m2@x.com")
        d2 = add_dog(m2["id"], name="Gus", size_class="LARGE",
                     license_number="LIC-B")

        data, meta = validate_paginated(api.list_dogs(m1["id"], ADMIN))
        assert meta["total_count"] == 1
        assert [d["id"] for d in data] == [d1["id"]], (
            "the list contains exactly the member's own dog"
        )
        assert all(d["id"] != d2["id"] for d in data)


class TestVerificationResubmissionCycle:
    def test_dog_rejection_resubmission_cycle(self, api):
        """PRD §3.2: "Rejecting moves the dog `SUBMITTED → REJECTED` and
        records the request's `reason` into `rejection_reason`."
        PRD §3.2: "A dog in `REJECTED` or `EXPIRED` may be resubmitted by its
        owning member with refreshed `vaccination_expires_on` and
        `license_number`; the move `REJECTED → SUBMITTED` or `EXPIRED →
        SUBMITTED` clears `rejection_reason` to null and requires the new
        vaccination date to be on or after the current logical date, failing
        with `ERR_VACCINATION_EXPIRED` otherwise."
        PRD §3.2: "Verification of a `SUBMITTED` dog takes a `decision` of
        `VERIFIED` or `REJECTED`."

        Design: Difficulty/non_linear_state_machine/dog_verification_resubmission_cycle
        """
        set_clock("2026-08-01T00:00:00Z")
        member = register_member(full_name="Own Er", email="owner@x.com")
        dog = add_dog(member["id"])
        assert dog["verification_status"] == "SUBMITTED"

        rejected = validate_success(api.verify_dog(
            dog["id"],
            verify_dog_payload(decision="REJECTED", reason="illegible license"),
            ADMIN,
        ))
        assert rejected["verification_status"] == "REJECTED"
        assert rejected["rejection_reason"] == "illegible license"

        resubmitted = validate_success(api.resubmit_dog(
            dog["id"],
            resubmit_dog_payload(vaccination_expires_on="2027-06-01",
                                 license_number="LIC-77"),
            make_member_headers(member["id"]),
        ))
        assert resubmitted["verification_status"] == "SUBMITTED"
        assert resubmitted["rejection_reason"] is None, (
            "resubmission clears the rejection reason"
        )

        verified = verify_dog(dog["id"], decision="VERIFIED")
        assert verified["verification_status"] == "VERIFIED"

    def test_dog_resubmission_refreshes_documents_and_bumps_version(self, api):
        """PRD §3.2: "A dog in `REJECTED` or `EXPIRED` may be resubmitted by
        its owning member with refreshed `vaccination_expires_on` and
        `license_number`"
        PRD §3.2: "Either outcome increments the dog's `version`."
        PRD §2.5: "`version` (integer): begins at 1 when the resource is
        created and increments by exactly one on every mutation — including
        state transitions, derived-field recomputations, and changes driven by
        cascades or the nightly run."

        Design: Difficulty/non_linear_state_machine/dog_verification_resubmission_cycle
        """
        set_clock("2026-08-01T00:00:00Z")
        member = register_member(full_name="Own Er", email="owner2@x.com")
        dog = add_dog(member["id"], license_number="LIC-1")
        assert dog["version"] == 1, "a resource begins at version 1"

        rejected = validate_success(api.verify_dog(
            dog["id"],
            verify_dog_payload(decision="REJECTED", reason="bad paperwork"),
            ADMIN,
        ))
        assert rejected["version"] == 2

        resubmitted = validate_success(api.resubmit_dog(
            dog["id"],
            resubmit_dog_payload(vaccination_expires_on="2028-01-15",
                                 license_number="LIC-77"),
            make_member_headers(member["id"]),
        ))
        assert resubmitted["version"] == 3
        assert resubmitted["license_number"] == "LIC-77", (
            "resubmission refreshes the license number"
        )
        assert resubmitted["vaccination_expires_on"] == "2028-01-15"

        verified = verify_dog(dog["id"], decision="VERIFIED")
        assert verified["version"] == 4
        assert verified["verification_status"] == "VERIFIED"


class TestVerificationGuards:
    def test_verify_already_verified_dog_rejected(self, api):
        """PRD §3.2: "A verification attempt on a dog no longer in `SUBMITTED`
        is rejected with `ERR_DOG_NOT_VERIFIABLE`."

        Design: Corner/state_machines/verify_already_verified_dog_rejected
        """
        set_clock("2026-08-01T00:00:00Z")
        member = register_member(full_name="Own Er", email="owner3@x.com")
        dog = verify_dog(add_dog(member["id"])["id"])
        assert dog["verification_status"] == "VERIFIED"

        resp = api.verify_dog(dog["id"], verify_dog_payload("VERIFIED"), ADMIN)
        validate_error(resp, ApiErrorId.ERR_DOG_NOT_VERIFIABLE)

    def test_resubmit_submitted_dog_rejected(self, api):
        """PRD §3.2: "Resubmission from any other status is rejected with
        `ERR_DOG_NOT_RESUBMITTABLE`, and a member resubmitting another member's
        dog hears `ERR_NOT_OWNER`."

        Design: Corner/state_machines/resubmit_submitted_dog_rejected
        """
        set_clock("2026-08-01T00:00:00Z")
        member = register_member(full_name="Own Er", email="owner4@x.com")
        dog = add_dog(member["id"])
        assert dog["verification_status"] == "SUBMITTED"

        resp = api.resubmit_dog(
            dog["id"],
            resubmit_dog_payload(vaccination_expires_on="2027-06-01",
                                 license_number="LIC-9"),
            make_member_headers(member["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DOG_NOT_RESUBMITTABLE)

    def test_verify_dog_with_expired_vaccination_rejected(self, api):
        """PRD §3.2: "Approving moves the dog `SUBMITTED → VERIFIED`, but only
        when its `vaccination_expires_on` is on or after the current logical
        date — an expired rabies certificate cannot be approved and is rejected
        with `ERR_VACCINATION_EXPIRED` (HTTP 422)."

        Design: Corner/validations/verify_dog_expired_vaccination_rejected
        """
        set_clock("2026-08-01T00:00:00Z")
        member = register_member(full_name="Own Er", email="owner5@x.com")
        dog = add_dog(member["id"], vaccination_expires_on="2026-07-01")

        resp = api.verify_dog(dog["id"], verify_dog_payload("VERIFIED"), ADMIN)
        validate_error(resp, ApiErrorId.ERR_VACCINATION_EXPIRED)

        after = validate_success(api.get_dog(dog["id"], ADMIN))
        assert after["verification_status"] == "SUBMITTED", (
            "the rejected approval leaves the dog SUBMITTED"
        )

    def test_verify_unknown_dog_returns_404(self, api):
        """PRD §2.8: "The not-found family is `ERR_MEMBER_NOT_FOUND`,
        `ERR_DOG_NOT_FOUND`, `ERR_MEMBERSHIP_NOT_FOUND`,
        `ERR_GUEST_PASS_NOT_FOUND`, `ERR_AREA_NOT_FOUND`,
        `ERR_CLOSURE_NOT_FOUND`, `ERR_VISIT_NOT_FOUND`,
        `ERR_INCIDENT_NOT_FOUND`, and `ERR_WASTE_STATION_NOT_FOUND`."

        Design: Corner/errors/error_dog_not_found
        """
        resp = api.verify_dog(NON_EXISTENT_UUID,
                              verify_dog_payload("VERIFIED"), ADMIN)
        validate_error(resp, ApiErrorId.ERR_DOG_NOT_FOUND)


class TestVerificationRbac:
    def test_member_cannot_verify_dog(self, api):
        """PRD §2.1: "A request whose role is not listed among the endpoint's
        authorized roles is rejected with `ERR_INSUFFICIENT_PERMISSIONS`
        (HTTP 403)."
        PRD §4: "| POST | `/dog-park/dogs/{dogId}/verify` | Verify or reject a
        submitted dog's vaccination and license documents | ParkAdmin |"

        Design: Corner/rbac/member_cannot_verify_dog
        """
        set_clock("2026-08-01T00:00:00Z")
        member = register_member(full_name="Own Er", email="owner6@x.com")
        dog = add_dog(member["id"])

        resp = api.verify_dog(dog["id"], verify_dog_payload("VERIFIED"),
                              make_member_headers(member["id"]))
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

        after = validate_success(api.get_dog(dog["id"], ADMIN))
        assert after["verification_status"] == "SUBMITTED", (
            "the denied verification never mutates the dog"
        )
