"""Demand-letter damages: pinned per-line rounding order (PRD §3.7)."""
import pytest

from test_helpers import (
    validate_success,
    ApiErrorId,
    create_registered_asset,
    create_asset_payload,
    create_demand_letter_payload,
    create_escalated_review_via_notice,
    make_ip_counsel_headers,
    TEST_USERS,
)

IP = TEST_USERS["ip_counsel_headers"]


def _setup_letter_scenario(api, exposure_cents=10001):
    """Departed-track employee (involuntary) with an ESCALATED review and an
    asset at the given exposure; returns (employee, review, asset)."""
    emp, review = create_escalated_review_via_notice(
        emp_overrides={
            "full_name": "Gail Departing", "email": "gail@x.com",
            "department": "SALES", "role_title": "AE",
            "access_clearance": "STANDARD", "hired_at": "2026-05-01T00:00:00Z",
        },
        exfil_indicator_count=2,
    )
    resp = api.create_asset(
        create_asset_payload(
            title="Pricing playbook", description="discount authority matrix",
            classification="CONFIDENTIAL", owner_department="SALES",
            exposure_estimate_cents=exposure_cents,
        ), IP
    )
    asset = validate_success(resp, expected_status=201)
    return emp, review, asset


class TestDemandLetterPerLineRounding:
    def test_per_line_rounding_then_sum(self, api):
        """PRD §3.7: "For each claim line, the referenced asset's
        `exposure_estimate_cents` is multiplied by the claim-type factor — 0.30
        for `CEASE_AND_DESIST`, 0.20 for `RETURN_OF_PROPERTY`, 0.15 for
        `PRESERVATION` — and that product is rounded half-up to whole cents
        first; the damages estimate is then the sum of the per-line rounded
        amounts, taken in request order."

        Design: Difficulty/combinatorial_formula/demand_letter_per_line_rounding
        """
        emp, review, asset = _setup_letter_scenario(api)
        resp = api.create_demand_letter(
            create_demand_letter_payload(
                review["id"],
                [
                    {"asset_id": asset["id"], "claim_type": "CEASE_AND_DESIST"},
                    {"asset_id": asset["id"], "claim_type": "RETURN_OF_PROPERTY"},
                    {"asset_id": asset["id"], "claim_type": "PRESERVATION"},
                ],
                response_deadline_days=14,
            ),
            make_ip_counsel_headers("counsel_1"),
        )
        data = validate_success(resp, expected_status=201)
        assert data["damages_estimate_cents"] == 6500, \
            f"per-line rounding: 3000 + 2000 + 1500 = 6500, got {data['damages_estimate_cents']}"

    def test_sum_then_round_alternative_rejected_and_letter_fields(self, api):
        """PRD §3.7: "The alternative order — summing raw products and rounding
        once — is explicitly not used: an asset with an exposure of 10,001 cents
        carrying all three claim types yields 3,000 plus 2,000 plus 1,500,
        totaling 6,500 cents, never the 6,501 that sum-then-round would produce."
        PRD §3.7: "the letter denormalizes its target `employee_id` from the
        review and stamps `drafted_by_user_id` from the caller."

        Design: Difficulty/combinatorial_formula/demand_letter_per_line_rounding
        """
        emp, review, asset = _setup_letter_scenario(api)
        resp = api.create_demand_letter(
            create_demand_letter_payload(
                review["id"],
                [
                    {"asset_id": asset["id"], "claim_type": "CEASE_AND_DESIST"},
                    {"asset_id": asset["id"], "claim_type": "RETURN_OF_PROPERTY"},
                    {"asset_id": asset["id"], "claim_type": "PRESERVATION"},
                ],
                response_deadline_days=14,
            ),
            make_ip_counsel_headers("counsel_1"),
        )
        data = validate_success(resp, expected_status=201)
        assert data["damages_estimate_cents"] != 6501
        assert data["status"] == "DRAFTED"
        assert data["employee_id"] == emp["id"]
