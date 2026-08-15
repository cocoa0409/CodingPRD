"""RBAC ownership/role enforcement and the two optimistic-concurrency write
surfaces (scholarship policy, trip logistics)."""
from test_helpers import (
    ApiErrorId,
    create_approved_registration,
    create_participant,
    create_program,
    create_registration,
    create_trip,
    get_trip,
    make_chaperone_headers,
    make_director_headers,
    make_guardian_headers,
    make_leader_headers,
    make_reviewer_headers,
    make_treasurer_headers,
    setup_program_with_open_trip,
    validate_error,
    validate_success,
)

DIRECTOR = make_director_headers()
MISSING = "11111111-1111-4111-8111-111111111111"


class TestGuardianOwnershipScope:
    def test_guardian_ownership_scope_forbidden_on_others_resources(self, api):
        """PRD §2.1: "a `Guardian`'s ownership anchor is the stored
        `guardian_user_id` string on participant and registration records — a
        guardian may act only on resources whose `guardian_user_id` equals the
        presented `X-User-ID`; acting on another guardian's resource is rejected
        with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."
        PRD §2.8: "5. **Ownership and segregation of duties**" precedes
        "6. **State preconditions**" — the ownership error surfaces even where
        the payment's registration-state gate would also fail.

        Design: Corner/rbac/guardian_ownership_scope_forbidden_on_others_resources
        """
        program, trip = setup_program_with_open_trip()
        participant = create_participant(program["id"], "guardian-1")
        registration = create_registration(trip["id"], participant["id"],
                                           "guardian-1")
        intruder = make_guardian_headers("guardian-2")
        owner = make_guardian_headers("guardian-1")

        e_read = api.get_registration(registration["id"], intruder)
        validate_error(e_read, ApiErrorId.ERR_NOT_RESOURCE_OWNER, 403)

        e_write = api.create_consent_form(
            registration["id"],
            {"form_type": "PARENTAL_CONSENT", "signed_by_name": "Intruder",
             "signed_at": "2026-08-02T10:00:00Z"},
            intruder)
        validate_error(e_write, ApiErrorId.ERR_NOT_RESOURCE_OWNER, 403)

        # The registration is DRAFT, so the payment's state gate would also
        # fail — ownership (step 5) is evaluated first.
        e_pay = api.create_payment(
            registration["id"], {"amount_cents": 100, "method": "CASH"},
            intruder)
        validate_error(e_pay, ApiErrorId.ERR_NOT_RESOURCE_OWNER, 403)

        ok = api.get_registration(registration["id"], owner)
        assert validate_success(ok, 200)["id"] == registration["id"]


class TestCrossRoleExclusives:
    def test_cross_role_exclusive_operations_forbidden(self, api):
        """PRD §2.1: "If the role is valid but not listed among an endpoint's
        authorized roles, the request is rejected with `ERR_ROLE_FORBIDDEN`
        (HTTP 403)." Per §4: roster lock is ProgramDirector-only, registration
        review is ProgramDirector/TripLeader, donations are Treasurer-only, the
        clock is ProgramDirector-only, and trip creation is
        ProgramDirector-only.

        Design: Corner/rbac/cross_role_exclusive_operations_forbidden
        """
        program = create_program()
        trip = create_trip(program["id"], destination_type="IN_STATE",
                           start_date="2027-06-15", end_date="2027-06-16",
                           emergency_protocol_text="")

        probes = [
            ("Guardian locking a roster",
             api.lock_roster(trip["id"], make_guardian_headers("guardian-1"))),
            ("Treasurer reviewing a registration",
             api.review_registration(MISSING, {"decision": "APPROVE"},
                                     make_treasurer_headers())),
            ("ScholarshipReviewer recording a donation",
             api.create_donation(MISSING,
                                 {"donor_name": "D", "amount_cents": 100,
                                  "channel": "CASH"},
                                 make_reviewer_headers())),
            ("TripLeader advancing the clock",
             api.set_clock("2027-01-01T00:00:00Z", make_leader_headers())),
            ("Chaperone creating a trip",
             api.create_trip(
                 {"program_id": program["id"], "name": "X",
                  "destination_name": "Y", "destination_type": "IN_STATE",
                  "start_date": "2027-06-15", "end_date": "2027-06-16",
                  "capacity_youth": 5, "base_cost_cents": 100,
                  "deposit_cents": 50, "chaperone_ratio": 5,
                  "registration_open_at": "2026-08-01T00:00:00Z",
                  "registration_close_at": "2026-12-01T00:00:00Z",
                  "deposit_due_at": "2027-01-15T00:00:00Z",
                  "final_payment_due_at": "2027-05-01T00:00:00Z"},
                 make_chaperone_headers(MISSING))),
        ]
        for label, resp in probes:
            validate_error(resp, ApiErrorId.ERR_ROLE_FORBIDDEN, 403), label


class TestProgramPolicyOcc:
    def test_occ_program_policy_stale_version(self, api):
        """PRD §2.7: "A request to replace a program's scholarship policy must
        carry `expected_program_version` holding the `version` of the Program
        the client last observed. If the program's current `version` differs —
        because another operator changed the policy or closed the program in
        the meantime — the request is rejected with `ERR_STALE_PROGRAM_VERSION`
        (HTTP 412)." and "version ... increments by exactly 1 on every mutation"
        (§2.5).

        Design: Corner/cross_cutting_layers/occ_program_policy_stale_version
        """
        program = create_program(scholarship_fund_total_cents=1000)
        v0 = program["version"]

        first = api.put_scholarship_policy(
            program["id"],
            {"max_award_pct_bp": 6000, "per_registration_cap_cents": 90000,
             "expected_program_version": v0},
            DIRECTOR)
        data = validate_success(first, 200)
        assert data["max_award_pct_bp"] == 6000
        assert data["version"] == v0 + 1, "the winning write increments by 1"

        replay = api.put_scholarship_policy(
            program["id"],
            {"max_award_pct_bp": 7000, "per_registration_cap_cents": 80000,
             "expected_program_version": v0},
            DIRECTOR)
        validate_error(replay, ApiErrorId.ERR_STALE_PROGRAM_VERSION, 412)

        final = api.get_program(program["id"], DIRECTOR).json()["data"]
        assert final["max_award_pct_bp"] == 6000, (
            "the stale write applied nothing")


class TestTripPatchFloorAndOcc:
    def test_patch_trip_capacity_floor_and_occ_stale_version(self, api):
        """PRD §3.2: "`capacity_youth` may not drop below the trip's current
        `seats_taken` (`ERR_CAPACITY_FLOOR`, HTTP 409)".
        PRD §2.7: "A request to edit a trip's logistics fields must likewise
        carry `expected_trip_version` matching the trip's current `version`.
        Any lifecycle transition (opening registration, locking the roster,
        starting, cancelling) or earlier edit advances that version; an edit
        presented against an older version is rejected with
        `ERR_STALE_TRIP_VERSION` (HTTP 412)."

        Design: Corner/validations/patch_trip_capacity_floor_and_occ_stale_version
        """
        program, trip = setup_program_with_open_trip(
            destination_type="IN_STATE", capacity_youth=2,
            base_cost_cents=80000, deposit_cents=50000,
            start_date="2027-06-15", end_date="2027-06-16",
            emergency_protocol_text="")
        for i in (1, 2):
            create_approved_registration(
                trip["id"], f"guardian-{i}",
                participant_overrides={"family_key": f"fam-{i}"},
                registration_overrides={"insurance_tier": "NONE"})
        assert get_trip(trip["id"])["seats_taken"] == 2

        current = get_trip(trip["id"])
        tv = current["version"]

        # Capacity floor: below seats_taken at a CURRENT version.
        e_floor = api.patch_trip(trip["id"],
                                 {"capacity_youth": 1,
                                  "expected_trip_version": tv},
                                 DIRECTOR)
        validate_error(e_floor, ApiErrorId.ERR_CAPACITY_FLOOR, 409)

        # A clean edit at the current version succeeds and bumps it.
        renamed = api.patch_trip(trip["id"],
                                 {"name": "Tiny Renamed",
                                  "expected_trip_version": tv},
                                 DIRECTOR)
        after = validate_success(renamed, 200)
        assert after["name"] == "Tiny Renamed"
        assert after["version"] == tv + 1

        # Replaying the pre-edit version is the deterministic stale loser.
        e_stale = api.patch_trip(trip["id"],
                                 {"name": "Tiny Again",
                                  "expected_trip_version": tv},
                                 DIRECTOR)
        validate_error(e_stale, ApiErrorId.ERR_STALE_TRIP_VERSION, 412)
