"""Investigator registration, suspension, training records, eligibility."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    make_manager_headers, make_investigator_headers,
    create_adjuster, create_investigator, create_claim, create_referral,
    triage_referral, accept_referral, open_case, create_investigator_payload,
    create_training_record_payload,
)
from test_helpers.api_client import api_client


class TestInvestigatorDefaults:
    def test_new_investigator_defaults_to_active_with_zero_cases(self, api):
        """PRD §3.3: "A new investigator starts `ACTIVE` with `active_case_count`
        at zero and `training_current_through` null."

        Design: Corner/entities/investigator_active_case_count_defaults_to_zero
        """
        mh = make_manager_headers()
        resp = api_client.create_investigator(create_investigator_payload(), mh)
        data = validate_success(resp, expected_status=201)
        assert data["active_case_count"] == 0
        assert data["status"] == "ACTIVE"
        assert data.get("training_current_through") is None


class TestInvestigatorEligibility:
    def test_assign_to_suspended_investigator_rejected(self, api):
        """PRD §3.3: "the investigator must be `ACTIVE`, their
        `state_certifications` must contain the claim's `state_code`, and their
        `active_case_count` must be below `max_active_cases`; any failure is
        `ERR_INVESTIGATOR_INELIGIBLE`."
        PRD §3.3: "a suspended or `TERMINATED` investigator fails every eligibility
        check"

        Design: Corner/errors/err_investigator_ineligible_on_suspended
        """
        mh = make_manager_headers()
        adj, ah = create_adjuster(manager_headers=mh)
        inv, _ = create_investigator(manager_headers=mh)
        # Suspend
        resp = api_client.suspend_investigator(inv["id"], {"reason": "pending review"}, mh)
        validate_success(resp)
        # Prepare open case
        claim = create_claim(adj, claimed_amount_cents=100)
        ref = create_referral(claim, headers=ah)
        triage_referral(ref, manager_headers=mh)
        case = accept_referral(ref, manager_headers=mh)
        case = open_case(case, manager_headers=mh)
        # Attempt assignment to suspended investigator
        resp2 = api_client.create_assignment(
            case["id"],
            {"investigator_id": inv["id"], "expected_case_version": case["version"]},
            mh)
        validate_error(resp2, ApiErrorId.ERR_INVESTIGATOR_INELIGIBLE)


class TestTrainingRecords:
    def test_training_record_with_invalid_window_rejected(self, api):
        """PRD §3.9: "The record is rejected with `ERR_TRAINING_WINDOW_INVALID`
        when `valid_until` is not later than `completed_at` or when `credit_hours`
        is below 1."

        Design: Corner/errors/err_training_window_invalid_trigger
        """
        mh = make_manager_headers()
        inv, ih = create_investigator(manager_headers=mh)
        resp = api_client.create_training_record(
            inv["id"],
            create_training_record_payload(completed_at="2026-08-10T00:00:00Z",
                                           valid_until="2026-08-09T00:00:00Z"),
            ih)
        validate_error(resp, ApiErrorId.ERR_TRAINING_WINDOW_INVALID)
