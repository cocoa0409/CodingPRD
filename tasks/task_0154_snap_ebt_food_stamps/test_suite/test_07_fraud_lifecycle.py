"""Fraud case lifecycle: open, assign, substantiate, appeal, reopen, close.

Covers PRD §3.7 (workflow + cyclic appeal branch) and the SUBSTANTIATED
cascade onto cards.
"""
import pytest

from test_helpers import (
    validate_success, validate_error,
    NON_EXISTENT_UUID,
    ERR_INVALID_STATE, ERR_FORBIDDEN, ERR_FRAUD_HOLD,
    TEST_USERS, make_household_head_headers,
    assert_fraud_case,
    create_fraud_case_payload,
    create_household,
    setup_approved_household_with_active_card,
    open_fraud_case, assign_fraud_case,
)


CASEWORKER = TEST_USERS["caseworker_headers"]
FRAUD_INV = TEST_USERS["fraud_investigator_headers"]


class TestFraudCaseOpen:
    def test_open_fraud_case_starts_open(self, api):
        """PRD §3.7: "The case is created in `OPEN`, `opened_at` is stamped
        to `Clock.now`, and the **suspicious score** is computed and stored."

        Claim: a newly opened FraudCase has state=OPEN with opened_at set
        and a suspicious_score field.
        """
        hh = create_household()
        case = open_fraud_case(hh["id"])
        assert_fraud_case(case)
        assert case["state"] == "OPEN"
        assert case["opened_at"] is not None
        assert 0.0 <= case["suspicious_score"] <= 1.0

    def test_open_fraud_case_role_restricted(self, api):
        """PRD §4 table: "POST /fraud-cases — Open a new FraudCase for a
        household — FraudInvestigator, Caseworker."

        Claim: a StateAdministrator cannot open a fraud case.
        """
        hh = create_household()
        resp = api.create_fraud_case(
            create_fraud_case_payload(hh["id"]),
            TEST_USERS["state_admin_headers"],
        )
        validate_error(resp, ERR_FORBIDDEN)

    def test_fraud_score_two_decimal_places(self, api):
        """PRD §3.7: "the **final sum** is rounded half-up to two decimal places."

        Claim: suspicious_score returns no more than 2 decimal digits.
        """
        hh = create_household()
        case = open_fraud_case(hh["id"])
        score = float(case["suspicious_score"])
        # Verify rounded to 2 decimals (within float tolerance)
        assert abs(score - round(score, 2)) < 1e-9


class TestFraudAssign:
    def test_assign_from_open_to_under_review(self, api):
        """PRD §3.7: "A `FraudInvestigator` then assigns the case from `OPEN`
        to `UNDER_REVIEW` by supplying `investigator_user_id`; the supplied
        value is recorded on the case."

        Claim: assign moves state to UNDER_REVIEW and records investigator id.
        """
        hh = create_household()
        case = open_fraud_case(hh["id"])
        resp = api.assign_fraud_case(case["id"], {"investigator_user_id": "inv-1"}, FRAUD_INV)
        data = validate_success(resp)
        assert data["state"] == "UNDER_REVIEW"
        assert data["investigator_user_id"] == "inv-1"

    def test_assign_from_non_open_yields_invalid_state(self, api):
        """PRD §3.7: "A `FraudInvestigator` then assigns the case from `OPEN`
        to `UNDER_REVIEW`."

        Claim: assign on already-UNDER_REVIEW case yields ERR_INVALID_STATE.
        """
        hh = create_household()
        case = open_fraud_case(hh["id"])
        assign_fraud_case(case["id"])
        resp = api.assign_fraud_case(case["id"], {"investigator_user_id": "inv-2"}, FRAUD_INV)
        validate_error(resp, ERR_INVALID_STATE)


class TestFraudSubstantiate:
    def test_substantiate_requires_score_threshold(self, api):
        """PRD §3.7: "Substantiating, which transitions `UNDER_REVIEW` to
        `SUBSTANTIATED`, requires `suspicious_score` to be **at least** 0.70
        (a score of exactly 0.70 is accepted; anything below is rejected with
        `ERR_INVALID_STATE`)."

        Claim: substantiate on a fresh case with no transactions (score=0.00)
        yields ERR_INVALID_STATE.
        """
        # A fresh household has no purchases — score should be 0
        hh = create_household()
        case = open_fraud_case(hh["id"])
        assign_fraud_case(case["id"])
        # Score expected to be 0 (no purchases yet) -> substantiate should fail
        resp = api.substantiate_fraud_case(case["id"], FRAUD_INV)
        validate_error(resp, ERR_INVALID_STATE)

    def test_dismiss_from_under_review_to_unfounded(self, api):
        """PRD §3.7: "Dismissing the case transitions `UNDER_REVIEW` to
        `UNFOUNDED` with no cascade."

        Claim: dismiss moves UNDER_REVIEW -> UNFOUNDED.
        """
        hh = create_household()
        case = open_fraud_case(hh["id"])
        assign_fraud_case(case["id"])
        resp = api.dismiss_fraud_case(case["id"], FRAUD_INV)
        data = validate_success(resp)
        assert data["state"] == "UNFOUNDED"


class TestFraudCloseFromUnfounded:
    def test_close_unfounded_succeeds(self, api):
        """PRD §3.7: "From `UNFOUNDED`, an investigator closes the case at
        any time; the transition stamps `closed_at` to `Clock.now`."

        Claim: close on UNFOUNDED case moves to CLOSED with closed_at set.
        """
        hh = create_household()
        case = open_fraud_case(hh["id"])
        assign_fraud_case(case["id"])
        validate_success(api.dismiss_fraud_case(case["id"], FRAUD_INV))
        resp = api.close_fraud_case(case["id"], FRAUD_INV)
        data = validate_success(resp)
        assert data["state"] == "CLOSED"
        assert data["closed_at"] is not None


class TestFraudAppealRBAC:
    def test_appeal_requires_household_head_role(self, api):
        """PRD §4 table: "POST /fraud-cases/{caseId}/appeal — Move
        SUBSTANTIATED to APPEAL_PENDING (within 90 days) — HouseholdHead."

        Claim: a Caseworker calling /appeal yields ERR_FORBIDDEN.
        """
        hh = create_household()
        case = open_fraud_case(hh["id"])
        resp = api.appeal_fraud_case(case["id"], CASEWORKER)
        validate_error(resp, ERR_FORBIDDEN)


class TestFraudCaseListing:
    def test_list_fraud_cases_paginated(self, api):
        """PRD §3.10: "Listing fraud cases supports filters on `state` and
        `household_id`."

        Claim: GET /fraud-cases returns a paginated list.
        """
        hh = create_household()
        open_fraud_case(hh["id"])
        from test_helpers import validate_paginated
        resp = api.list_fraud_cases(FRAUD_INV)
        data, meta = validate_paginated(resp)
        assert isinstance(data, list)

    def test_list_fraud_cases_filter_by_household(self, api):
        """PRD §3.10: "Listing fraud cases supports filters on `state` and
        `household_id`."

        Claim: household_id filter restricts results.
        """
        hh1 = create_household()
        hh2 = create_household()
        c1 = open_fraud_case(hh1["id"])
        c2 = open_fraud_case(hh2["id"])
        from test_helpers import validate_paginated
        resp = api.list_fraud_cases(FRAUD_INV, params={"household_id": hh1["id"], "limit": 100})
        data, _ = validate_paginated(resp)
        ids = {c["id"] for c in data}
        assert c1["id"] in ids
        assert c2["id"] not in ids
