"""Ownership, body-shape, and notice-type compatibility corners
(PRD 2.9, 2.7, 3.2)."""
from test_helpers import (
    ApiErrorId,
    CLERK_A,
    create_case_payload,
    create_landlord_payload,
    create_tenancy_payload,
    create_unit_payload,
    get_case,
    make_landlord_headers,
    set_clock,
    setup_case_draft,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS, api_client


class TestLandlordCannotTouchOtherLandlordsCase:
    """Corner instance: landlord B writing to landlord A's case is rejected
    even with a correct OCC version."""

    def test_notice_by_non_owner_rejected(self, api):
        """PRD 2.9: "on every write performed in the Landlord role, the
        X-User-ID presented must equal the landlord_id of the aggregate chain
        being mutated — the case, notice, filing package, judgment, tenancy,
        or unit the write touches; a mismatch is rejected with ERR_NOT_OWNER
        (HTTP 403)."

        Design: Corner/validations/landlord_cannot_touch_other_landlords_case
        """
        ctx_a = setup_case_draft("CA")
        landlord_b = validate_success(api.create_landlord(
            create_landlord_payload(legal_name="B LLC", contact_email="b@x.com"),
            TEST_USERS["admin_headers"]), 201)
        set_clock("2026-05-02T08:00:00Z")
        case = get_case(ctx_a["case"]["id"])
        resp = api.create_notice(
            case["id"],
            {"notice_type": "PAY_OR_QUIT", "served_on": "2026-05-02",
             "claimed_rent_owed_cents": 100000,
             "expected_case_version": case["version"]},
            make_landlord_headers(landlord_b["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_NOT_OWNER, 403)


class TestPayOrQuitRequiresClaimedAmount:
    """Corner instance: PAY_OR_QUIT without claimed_rent_owed_cents fails
    shape validation."""

    def test_missing_claimed_amount_rejected(self, api):
        """PRD 3.2: "claimed_rent_owed_cents, a positive amount required
        exactly for PAY_OR_QUIT ... violating these conditional requirements
        is an ERR_VALIDATION failure."

        Design: Corner/validations/pay_or_quit_requires_claimed_amount
        """
        ctx = setup_case_draft("CA")
        set_clock("2026-05-02T08:00:00Z")
        ll = make_landlord_headers(ctx["landlord"]["id"])
        case = get_case(ctx["case"]["id"])
        resp = api.create_notice(
            case["id"],
            {"notice_type": "PAY_OR_QUIT", "served_on": "2026-05-02",
             "expected_case_version": case["version"]},
            ll,
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION, 400)


class TestNoticeTypeMustMatchReason:
    """Corner instance: notice type must be compatible with the case
    reason."""

    def test_mismatched_type_rejected_matching_succeeds(self, api):
        """PRD 3.2: "The notice's notice_type must be compatible with the
        case reason: PAY_OR_QUIT is lawful only for NONPAYMENT, CURE_OR_QUIT
        only for LEASE_VIOLATION, and UNCONDITIONAL_QUIT only for SEVERE; an
        incompatible pairing is rejected with ERR_NOTICE_TYPE_MISMATCH
        (HTTP 422)."

        Design: Corner/validations/notice_type_must_match_reason
        """
        ctx = setup_case_draft("CA", case_reason="LEASE_VIOLATION")
        set_clock("2026-05-02T08:00:00Z")
        ll = make_landlord_headers(ctx["landlord"]["id"])
        case = get_case(ctx["case"]["id"])

        resp = api.create_notice(
            case["id"],
            {"notice_type": "PAY_OR_QUIT", "served_on": "2026-05-02",
             "claimed_rent_owed_cents": 50000,
             "expected_case_version": case["version"]},
            ll,
        )
        validate_error(resp, ApiErrorId.ERR_NOTICE_TYPE_MISMATCH, 422)

        # The failed attempt left the version untouched, so the same
        # expected_case_version still passes for the lawful pairing.
        ok = api.create_notice(
            case["id"],
            {"notice_type": "CURE_OR_QUIT", "served_on": "2026-05-02",
             "violation_description": "pet",
             "expected_case_version": case["version"]},
            ll,
        )
        assert validate_success(ok, 201)["status"] == "PENDING"
