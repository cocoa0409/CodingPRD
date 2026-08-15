"""Supplemental material requests: segregation of duties and the fiscal
envelope on approval."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_budget_money_conservation,
    create_cycle,
    create_framework,
    create_supplemental_request,
    get_ledger,
    make_instructional_specialist_headers,
    post_appropriation,
    transition_supplemental_request,
    validate_error,
)


class TestSupplementalApproval:
    def test_supplemental_approve_segregation_of_duties(self, api):
        """PRD §3.8: "Segregation of duties forbids self-approval: the
        approver's identity must differ from the recorded `requester_user_id`,
        or the approval fails with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."
        PRD §3.8: "A successful approval stamps the request with the
        approver's identity as `approver_user_id` and the logical clock as
        `approved_at`, and commits the `estimated_cost` into the ledger's
        `encumbered_total`."

        Design: Corner/validations/supplemental_approve_segregation_of_duties
        """
        framework = create_framework()
        cycle = create_cycle(framework["id"])
        post_appropriation(cycle["id"], 1000)
        request = create_supplemental_request(cycle["id"], "t9",
                                              estimated_cost=200.00)
        transition_supplemental_request(request["id"], "VETTING",
                                        specialist_id="spec1")

        # The requesting user cannot approve their own request — even while
        # acting in the (correct) InstructionalSpecialist role.
        validate_error(
            api.transition_supplemental_request(
                request["id"], {"to_state": "APPROVED"},
                make_instructional_specialist_headers("t9")),
            ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

        # A different specialist approves fine.
        resp = api.transition_supplemental_request(
            request["id"], {"to_state": "APPROVED"},
            make_instructional_specialist_headers("spec1"))
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["status"] == "APPROVED"
        assert data["approver_user_id"] == "spec1"
        assert data["approved_at"], "approved_at is stamped"
        ledger = get_ledger(cycle["id"])
        assert ledger["encumbered_total"] == pytest.approx(200.00, abs=0.01)
        assert_budget_money_conservation(ledger)

    def test_supplemental_approve_budget_envelope(self, api):
        """PRD §3.8: "The fiscal envelope also applies: the cycle ledger's
        `available_balance` must be at least the `estimated_cost`, with an
        exactly equal balance passing and a shortfall rejected as
        `ERR_BUDGET_ENVELOPE_EXCEEDED`."

        Design: Corner/validations/supplemental_approve_budget_envelope
        """
        framework = create_framework()
        cycle = create_cycle(framework["id"])
        post_appropriation(cycle["id"], 500)
        big = create_supplemental_request(cycle["id"], "t1",
                                          estimated_cost=600.00,
                                          school_code="SCH-A")
        exact = create_supplemental_request(cycle["id"], "t2",
                                            estimated_cost=500.00,
                                            school_code="SCH-B")
        transition_supplemental_request(big["id"], "VETTING")
        transition_supplemental_request(exact["id"], "VETTING")

        # 600.00 > 500.00 available: rejected.
        validate_error(
            api.transition_supplemental_request(
                big["id"], {"to_state": "APPROVED"},
                make_instructional_specialist_headers("spec1")),
            ApiErrorId.ERR_BUDGET_ENVELOPE_EXCEEDED)

        # Exactly the available balance passes (inclusive boundary).
        resp = api.transition_supplemental_request(
            exact["id"], {"to_state": "APPROVED"},
            make_instructional_specialist_headers("spec1"))
        assert resp.status_code == 200
        ledger = get_ledger(cycle["id"])
        assert ledger["available_balance"] == pytest.approx(0.00, abs=0.01)
        assert ledger["encumbered_total"] == pytest.approx(500.00, abs=0.01)
        assert_budget_money_conservation(ledger)
