"""Financing decision: DTI boundary, DTI gate, and principal gate."""
from test_helpers import (
    api_client as _ac,
    get_success_data, validate_success, validate_error,
    ApiErrorId,
    bootstrap_actors, create_baselined_project, THREE_LINE_ESTIMATE,
)


class TestDtiBoundary:
    def test_dti_at_exact_threshold_approves(self, api):
        """PRD §3.11: "Two gates decide the outcome, both compared on the rounded
        ratio. The application is declined with `ERR_DTI_EXCEEDED` (HTTP 422) when the
        `dti_ratio` is strictly greater than the DTI maximum of 0.43; it is approved
        when the ratio is at or below 0.43."

        Design: Difficulty/boundary_precision_check/boundary_dti_at_exact_threshold_approves
        """
        actors = bootstrap_actors(with_finance=True,
                                  annual_income_cents=4217525, monthly_debt_cents=139000)
        proj, est, line_map, _ = create_baselined_project(
            actors=actors, line_items=THREE_LINE_ESTIMATE(),
            measurement_overrides={"gross_wall_sqft": 2000, "opening_sqft": 200})
        fa = get_success_data(_ac.create_financing_application(
            {"project_id": proj["id"], "client_id": actors["client_id"],
             "requested_amount_cents": 1000000, "term_months": 120}, actors["client_h"]))
        decided = validate_success(_ac.decide_financing_application(fa["id"], actors["fin_h"]))
        assert decided["monthly_payment_cents"] == 12128, \
            f"monthly_payment expected 12128, got {decided['monthly_payment_cents']}"
        assert decided["dti_ratio"] == 0.43, \
            f"dti_ratio expected exactly 0.43 at boundary, got {decided['dti_ratio']}"
        assert decided["status"] == "APPROVED", \
            f"dti==0.43 is inclusive and must APPROVE, got {decided['status']}"

    def test_dti_at_boundary_status_approved(self, api):
        """PRD §3.11: "it is approved when the ratio is at or below 0.43."

        Design: Difficulty/boundary_precision_check/boundary_dti_at_exact_threshold_approves
        """
        actors = bootstrap_actors(with_finance=True,
                                  annual_income_cents=4217525, monthly_debt_cents=139000)
        proj, est, line_map, _ = create_baselined_project(
            actors=actors, line_items=THREE_LINE_ESTIMATE(),
            measurement_overrides={"gross_wall_sqft": 2000, "opening_sqft": 200})
        fa = get_success_data(_ac.create_financing_application(
            {"project_id": proj["id"], "client_id": actors["client_id"],
             "requested_amount_cents": 1000000, "term_months": 120}, actors["client_h"]))
        decided = validate_success(_ac.decide_financing_application(fa["id"], actors["fin_h"]))
        assert decided["dti_ratio"] == 0.43
        assert decided["status"] == "APPROVED"


class TestDtiGate:
    def test_dti_exceeded_declines(self, api):
        """PRD §3.11: "The application is declined with `ERR_DTI_EXCEEDED` (HTTP 422)
        when the `dti_ratio` is strictly greater than the DTI maximum of 0.43."

        Design: Corner/calculations/financing_dti_exceeded_declines
        """
        actors = bootstrap_actors(with_finance=True,
                                  annual_income_cents=3000000, monthly_debt_cents=200000)
        proj, est, line_map, _ = create_baselined_project(
            actors=actors, line_items=THREE_LINE_ESTIMATE(),
            measurement_overrides={"gross_wall_sqft": 2000, "opening_sqft": 200})
        fa = get_success_data(_ac.create_financing_application(
            {"project_id": proj["id"], "client_id": actors["client_id"],
             "requested_amount_cents": 1000000, "term_months": 120}, actors["client_h"]))
        resp = _ac.decide_financing_application(fa["id"], actors["fin_h"])
        validate_error(resp, ApiErrorId.ERR_DTI_EXCEEDED.value)
        # The decision exposes the computed (declining) ratio.
        refetched = validate_success(_ac.get_financing_application(fa["id"], actors["fin_h"]))
        assert refetched["dti_ratio"] == 0.8485, \
            f"dti_ratio expected 0.8485, got {refetched['dti_ratio']}"


class TestPrincipalGate:
    def test_principal_exceeds_contract_declines(self, api):
        """PRD §3.11: "Independently, the application is declined with
        `ERR_PRINCIPAL_EXCEEDS_CONTRACT` (HTTP 422) when the `requested_amount_cents`
        exceeds the project's `contract_total_cents`."

        Design: Corner/calculations/financing_principal_exceeds_contract_declines
        """
        # Single SIDING line 1000@1000c -> contract 1190750.
        actors = bootstrap_actors(with_finance=True)
        proj, est, line_map, _ = create_baselined_project(actors=actors)
        fa = get_success_data(_ac.create_financing_application(
            {"project_id": proj["id"], "client_id": actors["client_id"],
             "requested_amount_cents": 2000000, "term_months": 60}, actors["client_h"]))
        resp = _ac.decide_financing_application(fa["id"], actors["fin_h"])
        validate_error(resp, ApiErrorId.ERR_PRINCIPAL_EXCEEDS_CONTRACT.value)
