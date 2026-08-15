"""Auth headers, validation ordering, request shape, and member notices (PRD §2.1, §2.8, §2.11, §3.8)."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    NO_AUTH_HEADERS,
    TEST_USERS,
    create_case,
    create_member,
    factories,
    find_notice,
    set_clock,
    setup_case_with_lien,
    validate_error,
    validate_paginated,
    validate_success,
)

SPEC = TEST_USERS["specialist_headers"]


class TestAuthAndOrdering:
    def test_request_without_user_headers_rejected(self, api):
        """PRD §2.1: "A request with a missing or malformed `X-User-ID` or `X-User-Role` header is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/validations/request_missing_header_returns_400
        """
        resp = api.create_member(
            {"medicaid_id": "M-AU-1", "full_name": "No Head", "state_code": "CA"},
            NO_AUTH_HEADERS,
        )
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)

    def test_role_check_runs_before_existence_check(self, api):
        """PRD §2.8: "Validation failures are reported against a fixed evaluation order, so the error a client receives is always the earliest applicable check rather than an arbitrary one."
        PRD §2.8: "2. Role authorization for the endpoint — failure is `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)." and "4. Existence of the resources named in the path, validated left to right — failure is `ERR_NOT_FOUND` (HTTP 404)."

        Design: Corner/validations/role_check_beats_not_found_priority
        """
        # RecoverySpecialist lacks accept permission; the settlement id does
        # not exist. Role authorization (step 2) reports before existence (4).
        resp = api.accept_settlement(NON_EXISTENT_UUID, SPEC)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)


class TestRequestShape:
    def test_expense_claim_zero_amount_rejected(self, api):
        """PRD §3.2: "A `RecoverySpecialist` adds each claim with its `service_date`, the `paid_amount_cents` Medicaid paid (which must be greater than zero), and the external `claim_reference` from the MMIS feed."
        PRD §2.8: "Request-body shape: required fields present, enum values valid, amounts positive where the workflow requires a positive amount, and fee fractions inside their allowed interval — failure is `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/validations/expense_claim_zero_amount_returns_invalid_request
        """
        member = create_member(state_code="CA", medicaid_id="M-ZA-1")
        case = create_case(member["id"], injury_date="2026-01-01")
        resp = api.add_expense_claim(
            case["id"],
            factories.expense_claim_payload(
                service_date="2026-01-10", paid_amount_cents=0,
                claim_reference="CL-0",
            ),
            SPEC,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        data, meta = validate_paginated(api.list_expense_claims(case["id"], SPEC))
        assert data == [] and meta["total_count"] == 0


class TestNoticeDelivery:
    def test_failed_notice_retry_delivers(self, api):
        """PRD §3.8: "From `QUEUED`, a `DELIVERED` outcome moves the notice to `DELIVERED` and a `FAILED` outcome moves it to `FAILED`; from `FAILED`, a retry with `DELIVERED` completes delivery while a retry with `FAILED` leaves the notice in `FAILED`. Each attempt stamps `sent_at` from the logical clock and recomputes `is_late` as true exactly when the sent calendar date falls after the `due_date`, so a retry updates both fields to reflect the latest attempt."

        Design: Corner/state_machines/notice_send_failed_then_retry_delivered
        """
        ctx = setup_case_with_lien(claims=[("2026-01-10", 150000)])
        notice = find_notice("LIEN_FILED_NOTICE", case_id=ctx["case"]["id"])
        failed = validate_success(
            api.send_notice(notice["id"], "FAILED", SPEC), 200
        )
        assert failed["status"] == "FAILED"
        assert failed["sent_at"] is not None
        # Sent at the default clock 2026-08-01, due 2026-08-31: not late.
        assert failed["is_late"] is False
        delivered = validate_success(
            api.send_notice(notice["id"], "DELIVERED", SPEC), 200
        )
        assert delivered["status"] == "DELIVERED"
        assert delivered["is_late"] is False

    def test_notice_sent_after_due_date_marked_late(self, api):
        """PRD §2.11: "Each notice is created in `QUEUED` status, and its `due_date` is the creation calendar date plus thirty days — the member-communication deadline."
        PRD §2.11: "Delivery is attempted by a `RecoverySpecialist`; each attempt records `sent_at` from the logical clock and computes `is_late`, which is true when the sent calendar date falls after the `due_date`."

        Design: Corner/endpoints/notice_send_marks_late_after_due_date
        """
        ctx = setup_case_with_lien(claims=[("2026-01-10", 150000)])
        notice = find_notice("LIEN_FILED_NOTICE", case_id=ctx["case"]["id"])
        # Created at the default clock 2026-08-01; due 2026-08-31.
        set_clock("2026-09-01T00:00:00Z")
        delivered = validate_success(
            api.send_notice(notice["id"], "DELIVERED", SPEC), 200
        )
        assert delivered["status"] == "DELIVERED"
        assert delivered["due_date"] == "2026-08-31"
        assert delivered["is_late"] is True, (
            "Sent 2026-09-01 is after the 2026-08-31 deadline"
        )
