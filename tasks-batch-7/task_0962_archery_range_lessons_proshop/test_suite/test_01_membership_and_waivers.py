"""Membership registration, minors/guardian consent, and waiver lifecycle."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_member,
    assert_waiver,
    create_member_payload,
    get_member,
    make_member_headers,
    register_member,
    set_clock,
    sign_waiver,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
ANONYMOUS = TEST_USERS["anonymous_headers"]
RANGE_OFFICER = TEST_USERS["range_officer_headers"]


class TestMemberRegistrationDefaults:
    def test_member_creation_applies_defaults(self, api):
        """PRD §3.1: "A new member starts with `status` `ACTIVE`,
        `safety_strikes` 0, and `wallet_balance_cents` 0."
        PRD §3.1: "a `tier` of `BASIC`, `PLUS`, or `ELITE` may be supplied and
        defaults to `BASIC`."
        PRD §2.5: "Before any operator intervention, the logical clock sits at
        exactly 2026-05-01T00:00:00Z."
        PRD §2.4: "The `created_at` timestamp records creation as an ISO 8601
        UTC timestamp with three fractional digits, and `updated_at` follows the
        same format and is refreshed on every mutation."

        Design: Corner/entities/member_creation_applies_defaults
        """
        # No clock call: startup default clock 2026-05-01T00:00:00Z applies.
        resp = api.create_member(
            create_member_payload(
                email="def@x.com", full_name="Default Member",
                date_of_birth="1990-01-01",
            ),
            ANONYMOUS,
        )
        member = validate_success(resp, 201)
        assert_member(member)
        assert member["tier"] == "BASIC"
        assert member["wallet_balance_cents"] == 0
        assert member["safety_strikes"] == 0
        assert member["status"] == "ACTIVE"
        assert isinstance(member["version"], int)
        assert member["created_at"] == "2026-05-01T00:00:00.000Z"

    def test_member_server_fields_input_ignored(self, api):
        """PRD §2.4: "Because every entity in this system shares these four
        properties, none of them are ever supplied by the client on creation."
        PRD §3.1: "A new member starts with `status` `ACTIVE`, `safety_strikes`
        0, and `wallet_balance_cents` 0."
        PRD §2.4: "The `id` is a server-minted UUID with no type prefix."

        Design: Corner/entities/member_server_fields_input_ignored
        """
        resp = api.create_member(
            {
                "email": "sneaky@x.com",
                "full_name": "Sneaky Member",
                "date_of_birth": "1990-01-01",
                "id": "11111111-1111-1111-1111-111111111111",
                "version": 99,
                "wallet_balance_cents": 9999,
            },
            ANONYMOUS,
        )
        member = validate_success(resp, 201)
        assert member["id"] != "11111111-1111-1111-1111-111111111111", (
            "id must be server-minted"
        )
        assert isinstance(member["version"], int) and member["version"] != 99
        assert member["wallet_balance_cents"] == 0


class TestMinorRegistration:
    def test_minor_registration_requires_adult_guardian(self, api):
        """PRD §3.1: "When the new member is a minor at registration time, a
        `guardian_id` referencing an existing adult member (one whose `is_minor`
        is false) is mandatory; omitting it is rejected with
        `ERR_MINOR_GUARDIAN_REQUIRED`, and pointing it at a minor is rejected
        with `ERR_GUARDIAN_NOT_ADULT`."

        Design: Corner/entities/member_minor_registration_without_guardian_rejected
        """
        set_clock("2026-05-01T00:00:00Z")
        guardian = register_member(
            "guard@x.com", full_name="Guard Ian", date_of_birth="1985-03-20"
        )

        err_resp = api.create_member(
            create_member_payload(
                email="kid@x.com", full_name="Kid Archer",
                date_of_birth="2012-06-15",
            ),
            ANONYMOUS,
        )
        validate_error(err_resp, ApiErrorId.ERR_MINOR_GUARDIAN_REQUIRED)

        ok_resp = api.create_member(
            create_member_payload(
                email="kid@x.com", full_name="Kid Archer",
                date_of_birth="2012-06-15", guardian_id=guardian["id"],
            ),
            ANONYMOUS,
        )
        kid = validate_success(ok_resp, 201)
        assert kid["is_minor"] is True
        assert kid["guardian_id"] == guardian["id"]

    def test_member_18th_birthday_boundary_is_adult(self, api):
        """PRD §3.1: "Registration computes `is_minor` against the logical
        clock: a member is a minor if and only if the current logical-clock date
        is earlier than the eighteenth anniversary of their `date_of_birth` — a
        member whose eighteenth birthday is exactly today is an adult."
        PRD §3.2: "Signing stamps `signed_at` from the logical clock, computes
        `valid_until` as the signed date plus 365 days (the waiver is valid
        through that date inclusive), and sets `status` to `ACTIVE`."

        Design: Corner/entities/member_18th_birthday_boundary_is_adult
        """
        set_clock("2026-04-30T12:00:00Z")
        err_resp = api.create_member(
            create_member_payload(
                email="bday@x.com", full_name="Birthday Archer",
                date_of_birth="2008-05-01",
            ),
            ANONYMOUS,
        )
        # One day before the 18th birthday: still a minor, guardian mandatory.
        validate_error(err_resp, ApiErrorId.ERR_MINOR_GUARDIAN_REQUIRED)

        set_clock("2026-05-01T00:00:00Z")
        ok_resp = api.create_member(
            create_member_payload(
                email="bday@x.com", full_name="Birthday Archer",
                date_of_birth="2008-05-01",
            ),
            ANONYMOUS,
        )
        member = validate_success(ok_resp, 201)
        assert member["is_minor"] is False, "18th birthday itself counts as adult"

        waiver_resp = api.sign_waiver(member["id"], make_member_headers(member["id"]))
        waiver = validate_success(waiver_resp, 201)
        assert waiver["signed_by_member_id"] == member["id"]
        assert waiver["status"] == "ACTIVE"
        assert waiver["valid_until"] == "2027-05-01"


class TestMemberLookup:
    def test_member_not_found_returns_404(self, api):
        """PRD §2.10: "the leftmost segment that does not resolve determines the
        not-found error — `ERR_MEMBER_NOT_FOUND`, ... each HTTP 404."

        Design: Corner/entities/member_not_found_returns_404
        """
        resp = api.get_member(
            "9b9b9b9b-1111-4222-8333-444444444444", ADMIN
        )
        validate_error(resp, ApiErrorId.ERR_MEMBER_NOT_FOUND)


class TestWaiverConsentAndRevocation:
    def test_minor_waiver_must_be_signed_by_guardian(self, api):
        """PRD §3.2: "For a minor, the waiver must be signed by their guardian
        — the signer's identity must equal the minor member's `guardian_id`, and
        that guardian must be an adult; a minor attempting to sign their own
        waiver is rejected with `ERR_MINOR_GUARDIAN_REQUIRED`, and a signer who
        is not the member's adult guardian with `ERR_GUARDIAN_NOT_ADULT`."
        PRD §3.2: "Signing stamps `signed_at` from the logical clock, computes
        `valid_until` as the signed date plus 365 days (the waiver is valid
        through that date inclusive), and sets `status` to `ACTIVE`."

        Design: Corner/validations/minor_waiver_must_be_signed_by_guardian
        """
        set_clock("2026-05-01T08:00:00Z")
        guardian = register_member(
            "gd@x.com", full_name="Guardian", date_of_birth="1985-03-20"
        )
        kid = register_member(
            "kd@x.com", full_name="Kid", date_of_birth="2012-06-15",
            guardian_id=guardian["id"],
        )

        self_sign = api.sign_waiver(kid["id"], make_member_headers(kid["id"]))
        validate_error(self_sign, ApiErrorId.ERR_MINOR_GUARDIAN_REQUIRED)

        guardian_sign = api.sign_waiver(
            kid["id"], make_member_headers(guardian["id"])
        )
        waiver = validate_success(guardian_sign, 201)
        assert_waiver(waiver)
        assert waiver["signed_by_member_id"] == guardian["id"]
        assert waiver["member_id"] == kid["id"]
        assert waiver["status"] == "ACTIVE"
        assert waiver["valid_until"] == "2027-05-01"

    def test_waiver_second_revoke_rejected(self, api):
        """PRD §3.2: "An `Admin` may revoke a waiver outright, moving it from
        either `ACTIVE` or `EXPIRED` to the terminal `REVOKED`; revoking an
        already `REVOKED` waiver is rejected with `ERR_WAIVER_NOT_REVOKABLE`."

        Design: Corner/state_machines/waiver_second_revoke_rejected
        """
        set_clock("2026-05-01T08:00:00Z")
        member = register_member(
            "rev@x.com", full_name="Revoke Tester", date_of_birth="1990-01-01"
        )
        waiver = sign_waiver(member["id"])

        first = api.revoke_waiver(waiver["id"], ADMIN)
        revoked = validate_success(first, 200)
        assert revoked["status"] == "REVOKED"

        second = api.revoke_waiver(waiver["id"], ADMIN)
        validate_error(second, ApiErrorId.ERR_WAIVER_NOT_REVOKABLE)
