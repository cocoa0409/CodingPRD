"""Conflict/credential screening: duplicates, credential gate, waiver, request lifecycle."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    assert_conflict_check, assert_engagement_request, ApiErrorId,
    create_expert, create_case, open_request, screen_candidate,
    create_conflict_check_payload, create_draft_engagement,
    TEST_USERS,
)

ADMIN = TEST_USERS["platform_admin_headers"]
CM = TEST_USERS["case_manager_headers"]
CONFLICT = TEST_USERS["conflict_analyst_headers"]
CREDENTIAL = TEST_USERS["credential_analyst_headers"]


class TestDuplicateScreening:

    def test_second_conflict_check_same_pair_rejected(self, api):
        """PRD §3.2: "Each (request, expert) pair supports exactly one conflict check and
        exactly one credential review: a second of either for the same pair is rejected
        with `ERR_DUPLICATE_SCREENING` — the rule guards both screening-opening operations."

        Design: Corner/validations/duplicate_screening_rejected
        """
        expert = create_expert(full_name="Dup Don")
        case = create_case()
        request = open_request(case["id"])
        first = validate_success(
            api.create_conflict_check(request["id"], create_conflict_check_payload(expert["id"]), CONFLICT),
            201)
        assert first["status"] == "PENDING"

        res = api.create_conflict_check(request["id"], create_conflict_check_payload(expert["id"]), CONFLICT)
        validate_error(res, ApiErrorId.ERR_DUPLICATE_SCREENING)


class TestCredentialGate:

    def test_failed_review_blocks_engagement_creation(self, api):
        """PRD §3.3: "then credential passage — the review must be `PASSED` or
        `PASSED_WITH_CONDITIONS`, else `ERR_CREDENTIAL_NOT_PASSED`".
        PRD §3.2: "a pass or conditional pass re-evaluates the predicate, while a failed
        review records the outcome without promoting the request."

        Design: Corner/validations/credential_not_passed_blocks_engagement
        """
        expert = create_expert(full_name="Cred Cid")
        case = create_case()
        request = open_request(case["id"])
        cc, cr = screen_candidate(request["id"], expert["id"],
                                  conflict_outcome="CLEARED",
                                  credential_outcome="FAILED",
                                  credential_daubert_notes="excluded twice recently")
        assert cr["status"] == "FAILED"

        res = api.create_engagement(
            {"engagement_request_id": request["id"], "expert_id": expert["id"],
             "hourly_rate_cents": 40000, "retainer_cents": 0, "expense_cap_cents": 0},
            CM)
        validate_error(res, ApiErrorId.ERR_CREDENTIAL_NOT_PASSED)

        # The failed review recorded the outcome without promoting the request.
        req_after = validate_success(api.get_engagement_request(request["id"], CM), 200)
        assert req_after["status"] == "SCREENING"


class TestConflictWaiver:

    def test_admin_waive_satisfies_ready_predicate(self, api):
        """PRD §3.2: "A flagged check may later be waived (`FLAGGED` → `WAIVED`), but
        waiver is reserved to a `PlatformAdmin`" and "A candidate is fully qualified for a
        request when that expert holds a conflict check under the request in `CLEARED` or
        `WAIVED` and a credential review under the same request in `PASSED` or
        `PASSED_WITH_CONDITIONS`."

        Design: Corner/state_machines/conflict_check_waive_by_admin
        """
        expert = create_expert(full_name="Waive Wes")
        case = create_case()
        request = open_request(case["id"])
        cc, cr = screen_candidate(request["id"], expert["id"],
                                  conflict_outcome="FLAGGED",
                                  conflict_rationale="prior adverse engagement",
                                  credential_outcome="PASSED",
                                  adverse_parties=["OpCo"])
        assert cc["status"] == "FLAGGED"

        waived = validate_success(
            api.resolve_conflict_check(cc["id"], {"outcome": "WAIVED",
                                                  "rationale": "parties consented in writing"}, ADMIN),
            200)
        assert_conflict_check(waived)
        assert waived["status"] == "WAIVED"

        req_after = validate_success(api.get_engagement_request(request["id"], CM), 200)
        assert req_after["status"] == "READY", "WAIVED + PASSED must satisfy the READY predicate"

    def test_conflict_analyst_cannot_waive_forbidden(self, api):
        """PRD §3.2: "A flagged check may later be waived (`FLAGGED` → `WAIVED`), but
        waiver is reserved to a `PlatformAdmin` — a `ConflictAnalyst` attempting the
        `WAIVED` outcome is rejected with `ERR_FORBIDDEN` — and the waiver also records its
        `resolution_rationale`."

        Design: Corner/roles/conflict_analyst_cannot_waive_forbidden
        """
        expert = create_expert(full_name="Sod Sam")
        case = create_case()
        request = open_request(case["id"])
        cc = get_success_data(api.create_conflict_check(
            request["id"], create_conflict_check_payload(expert["id"], adverse_parties=["OpCo"]),
            CONFLICT))
        cc = get_success_data(api.resolve_conflict_check(
            cc["id"], {"outcome": "FLAGGED", "rationale": "adverse history"}, CONFLICT))

        res = api.resolve_conflict_check(
            cc["id"], {"outcome": "WAIVED", "rationale": "analyst self-waiver attempt"}, CONFLICT)
        validate_error(res, ApiErrorId.ERR_FORBIDDEN, expected_status=403)

        checks = validate_success(api.list_request_conflict_checks(request["id"], CONFLICT), 200)
        flagged = [c for c in checks if c["id"] == cc["id"]]
        assert flagged and flagged[0]["status"] == "FLAGGED", "check must remain FLAGGED"


class TestRequestLifecycle:

    def test_request_auto_transitions_open_screening_ready_filled(self, api):
        """PRD §3.2: "The request's `status` starts at `OPEN`" and "The first check or
        review opened under a request moves it `OPEN` → `SCREENING`."
        PRD §3.2: "The first time any candidate satisfies this predicate, the request moves
        `SCREENING` → `READY`" and "A request reaches `FILLED` when an engagement is created
        from it (`READY` → `FILLED`)."

        Design: Corner/state_machines/request_lifecycle_auto_transitions
        """
        expert = create_expert(full_name="Auto Ann")
        case = create_case()
        request = open_request(case["id"])
        assert request["status"] == "OPEN"

        cc, cr = screen_candidate(request["id"], expert["id"])
        req_ready = validate_success(api.get_engagement_request(request["id"], CM), 200)
        assert req_ready["status"] == "READY", "CLEARED check + PASSED review must promote to READY"

        engagement = create_draft_engagement(request["id"], expert["id"])
        assert engagement["status"] == "DRAFT"
        req_filled = validate_success(api.get_engagement_request(request["id"], CM), 200)
        assert req_filled["status"] == "FILLED", "engagement creation must move READY → FILLED"
