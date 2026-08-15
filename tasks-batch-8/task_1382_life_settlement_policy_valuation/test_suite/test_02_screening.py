"""Eligibility screening: lifecycle, boundaries, failure ordering (PRD §3.1)."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, TEST_USERS, make_broker_headers,
    create_license_payload, create_broker_payload, create_insured_payload,
    create_policy_payload,
    setup_broker_insured_policy, create_case_for, submit_case, run_screening,
    setup_case_in_underwriting, order_and_deliver_le,
)

ADMIN = TEST_USERS["admin_headers"]
CM = TEST_USERS["case_manager_headers"]
UW = TEST_USERS["underwriter_headers"]


def _screenings_of(api, case_id):
    data, _meta = validate_paginated(api.list_screenings(case_id, CM))
    return data


class TestScreeningLifecycle:
    def test_case_initial_state_is_draft(self, api):
        """PRD §3.1: "A broker originates a case by naming a `policy_id`; the new
        `PolicyCase` is created in `DRAFT` with its `broker_id` set from the
        caller's `X-User-ID`, its `hold_status` `CLEAR`, its
        `screening_failure_reasons` empty"
        PRD §2.4: "All entities except `EligibilityScreening` additionally carry
        `updated_at` and an integer `version` that starts at 1 and increments by 1
        on every mutation of that entity."

        Design: Corner/state_machines/case_initial_state_is_draft
        """
        broker, insured, policy = setup_broker_insured_policy(with_license=False)
        case = validate_success(
            api.create_case({"policy_id": policy["id"]}, make_broker_headers(broker["id"])),
            expected_status=201,
        )
        assert case["status"] == "DRAFT"
        assert case["hold_status"] == "CLEAR"
        assert case["version"] == 1
        assert case["broker_id"] == broker["id"]

    def test_resubmit_rejected_when_not_draft(self, api):
        """PRD §3.1: "Submission by the owning broker moves the case from `DRAFT` to
        `SCREENING`"
        PRD §2.7: "7. From-state validity for the attempted trigger
        (`ERR_INVALID_STATE_TRANSITION`, HTTP 409, and its domain variants
        `ERR_CASE_NOT_MARKETED`, `ERR_CASE_HAS_ACTIVE_CLOSING`,
        `ERR_ESCROW_NOT_FUNDED`, `ERR_POLICY_NOT_ACQUIRED`)."

        Design: Corner/state_machines/resubmit_rejected_when_not_draft
        """
        broker, insured, policy, case = None, None, None, None
        broker, insured, policy = setup_broker_insured_policy()
        case = create_case_for(broker, policy)
        submit_case(broker, case)
        resp = api.submit_case(case["id"], make_broker_headers(broker["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

    def test_declined_case_is_terminal(self, api):
        """PRD §3.2: "When the decision is to decline, the case moves from
        `UNDERWRITING` to `UW_DECLINED`; all non-terminal offers on the case become
        `EXPIRED`, while non-terminal life-expectancy reports are left unchanged."
        PRD §2.7: "Terminal-state guard on the target resource: an action aimed at
        a resource already in a terminal state — countering an `EXPIRED` offer,
        paying a `PAID` payment, approving a `CLOSED` package — is rejected with
        `ERR_ALREADY_TERMINAL` (HTTP 409)."

        Design: Corner/state_machines/declined_case_is_terminal
        """
        broker, insured, policy, case = setup_case_in_underwriting()
        order_and_deliver_le(case)
        declined = validate_success(api.uw_decision(case["id"], {"decision": "DECLINE"}, UW))
        assert declined["status"] == "UW_DECLINED"
        resp = api.withdraw_case(case["id"], make_broker_headers(broker["id"]))
        validate_error(resp, ApiErrorId.ERR_ALREADY_TERMINAL)


class TestScreeningBoundaries:
    def test_face_amount_exact_minimum_boundary(self, api):
        """PRD §3.1: "The face check requires the policy's `face_amount_cents` to be
        at least 10000000 — one hundred thousand dollars, inclusive."
        PRD §3.1: "A `FAILED` result moves the case from `SCREENING` to
        `SCREEN_FAILED` and copies the record's `failure_reasons` onto the case's
        `screening_failure_reasons` in the same order."

        Design: Difficulty/boundary_precision_check/face_amount_exact_minimum_boundary
        """
        validate_success(api.create_license(create_license_payload(), ADMIN), expected_status=201)
        broker = validate_success(api.create_broker(create_broker_payload(name="Broker One"), ADMIN),
                                  expected_status=201)
        bh = make_broker_headers(broker["id"])
        insured = validate_success(api.create_insured(
            create_insured_payload(full_name="Pat Doe", date_of_birth="1960-01-01",
                                   state_code="TX"), bh), expected_status=201)
        policy_a = validate_success(api.create_policy(
            create_policy_payload(insured["id"], policy_number="P-A",
                                  face_amount_cents=10000000), bh), expected_status=201)
        policy_b = validate_success(api.create_policy(
            create_policy_payload(insured["id"], policy_number="P-B",
                                  face_amount_cents=9999999), bh), expected_status=201)
        case_a = validate_success(api.create_case({"policy_id": policy_a["id"]}, bh),
                                  expected_status=201)
        validate_success(api.submit_case(case_a["id"], bh))
        case_b = validate_success(api.create_case({"policy_id": policy_b["id"]}, bh),
                                  expected_status=201)
        validate_success(api.submit_case(case_b["id"], bh))

        screening_a = validate_success(api.create_screening(case_a["id"], CM), expected_status=201)
        assert screening_a["result"] == "PASSED", "face 10000000 >= 10000000 inclusive passes"
        case_a_after = validate_success(api.get_case(case_a["id"], CM))
        assert case_a_after["status"] == "UNDERWRITING"

        screening_b = validate_success(api.create_screening(case_b["id"], CM), expected_status=201)
        assert screening_b["result"] == "FAILED"
        assert screening_b["checks"]["face_ok"] is False
        assert screening_b["failure_reasons"] == ["FACE"]
        case_b_after = validate_success(api.get_case(case_b["id"], CM))
        assert case_b_after["status"] == "SCREEN_FAILED"
        assert case_b_after["screening_failure_reasons"] == ["FACE"]

    def test_face_amount_one_cent_below_minimum_fails(self, api):
        """PRD §3.1: "The face check requires the policy's `face_amount_cents` to be
        at least 10000000 — one hundred thousand dollars, inclusive."
        PRD §3.1: "A `PASSED` result moves the case from `SCREENING` to
        `UNDERWRITING` and clears `screening_failure_reasons` to an empty list."

        Design: Difficulty/boundary_precision_check/face_amount_exact_minimum_boundary
        """
        validate_success(api.create_license(create_license_payload(), ADMIN), expected_status=201)
        broker = validate_success(api.create_broker(create_broker_payload(name="Broker One"), ADMIN),
                                  expected_status=201)
        bh = make_broker_headers(broker["id"])
        insured = validate_success(api.create_insured(
            create_insured_payload(full_name="Pat Doe", date_of_birth="1960-01-01",
                                   state_code="TX"), bh), expected_status=201)
        policy = validate_success(api.create_policy(
            create_policy_payload(insured["id"], policy_number="P-1",
                                  face_amount_cents=9999999), bh), expected_status=201)
        case = validate_success(api.create_case({"policy_id": policy["id"]}, bh),
                                expected_status=201)
        validate_success(api.submit_case(case["id"], bh))
        screening = validate_success(api.create_screening(case["id"], CM), expected_status=201)
        assert screening["result"] == "FAILED"
        assert screening["checks"]["face_ok"] is False
        assert screening["checks"]["license_ok"] is True
        assert screening["checks"]["age_ok"] is True
        assert screening["checks"]["contestability_ok"] is True
        assert screening["checks"]["type_ok"] is True
        case_after = validate_success(api.get_case(case["id"], CM))
        assert case_after["status"] == "SCREEN_FAILED"
        assert case_after["screening_failure_reasons"] == ["FACE"]

    def test_screening_failure_reasons_fixed_order(self, api):
        """PRD §3.1: "The record's `failure_reasons` lists the failed check codes in
        the fixed order LICENSE, FACE, AGE, CONTESTABILITY, TYPE."

        Design: Corner/calculations/screening_failure_reasons_fixed_order
        """
        broker = validate_success(api.create_broker(
            create_broker_payload(name="B", state_code="NV"), ADMIN), expected_status=201)
        bh = make_broker_headers(broker["id"])
        insured = validate_success(api.create_insured(
            create_insured_payload(full_name="P", date_of_birth="1990-01-01", state_code="NV",
                                   smoker_status="TOBACCO"), bh), expected_status=201)
        policy = validate_success(api.create_policy(
            create_policy_payload(insured["id"], policy_number="P-1",
                                  face_amount_cents=9999999, policy_type="TERM_NONCONVERTIBLE",
                                  issue_date="2025-08-01"), bh), expected_status=201)
        case = validate_success(api.create_case({"policy_id": policy["id"]}, bh),
                                expected_status=201)
        validate_success(api.submit_case(case["id"], bh))

        screening = validate_success(api.create_screening(case["id"], CM), expected_status=201)
        assert screening["result"] == "FAILED"
        assert screening["failure_reasons"] == ["LICENSE", "FACE", "AGE", "CONTESTABILITY", "TYPE"]
        case_after = validate_success(api.get_case(case["id"], CM))
        assert case_after["screening_failure_reasons"] == ["LICENSE", "FACE", "AGE",
                                                           "CONTESTABILITY", "TYPE"]

    def test_screening_rerun_after_policy_fix(self, api):
        """PRD §3.1: "A rerun from `SCREEN_FAILED` re-enters `SCREENING` and resolves
        within the same request, creating a fresh `EligibilityScreening` row each
        time; the older rows remain as an immutable audit trail."
        PRD §3.1: "While a case is `SCREENING` (first run) or `SCREEN_FAILED`
        (rerun after the broker amends policy data), a case manager runs an
        eligibility screening."

        Design: Corner/state_machines/screening_rerun_after_policy_fix
        """
        validate_success(api.create_license(create_license_payload(), ADMIN), expected_status=201)
        broker = validate_success(api.create_broker(create_broker_payload(name="B"), ADMIN),
                                  expected_status=201)
        bh = make_broker_headers(broker["id"])
        insured = validate_success(api.create_insured(
            create_insured_payload(full_name="P", date_of_birth="1960-01-01", state_code="TX",
                                   smoker_status="UNKNOWN"), bh), expected_status=201)
        policy = validate_success(api.create_policy(
            create_policy_payload(insured["id"], policy_number="P-1",
                                  face_amount_cents=9999999), bh), expected_status=201)
        case = validate_success(api.create_case({"policy_id": policy["id"]}, bh),
                                expected_status=201)
        validate_success(api.submit_case(case["id"], bh))
        first = validate_success(api.create_screening(case["id"], CM), expected_status=201)
        assert first["result"] == "FAILED"

        # Policy amendment is allowed: SCREEN_FAILED is not a locking state (PRD §2.9).
        validate_success(api.patch_policy(policy["id"], {"face_amount_cents": 10000000}, bh))
        second = validate_success(api.create_screening(case["id"], CM), expected_status=201)
        assert second["result"] == "PASSED"
        case_after = validate_success(api.get_case(case["id"], CM))
        assert case_after["status"] == "UNDERWRITING"
        rows = _screenings_of(api, case["id"])
        assert len(rows) == 2, "each run creates a fresh immutable EligibilityScreening row"
        assert rows[0]["id"] != rows[1]["id"]
