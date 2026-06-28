"""Business validation rejections at activation, bundling, claim-line, and approve.

Translates corner-design validations and errors instances.
"""
from test_helpers import (
    TEST_USERS,
    validate_error,
    ApiErrorId,
    create_coverage_plan_payload,
    create_contract_payload,
    create_ancillary_product_payload,
    create_claim_line_payload,
)
from test_helpers.fixtures import (
    create_pool,
    create_active_plan,
    setup_active_contract,
    setup_pending_contract,
    setup_under_review_claim,
)

ADMIN = TEST_USERS["admin_underwriter_headers"]
CONTRACT_ADMIN = TEST_USERS["contract_admin_headers"]
ADJUSTER = TEST_USERS["claims_adjuster_headers"]


def test_invalid_cession_pct_on_plan_activate(api):
    """PRD §2.6: "A plan's `reinsurance_cession_pct` is a fraction that must lie
    between 0.0 and 1.0 inclusive; a value outside that closed interval is rejected
    with `ERR_INVALID_CESSION_PCT` (HTTP 422)." The cession range is a generic input
    validation, so supplying 1.5 at plan creation is rejected.

    Design: Corner/validations/invalid_cession_pct_on_plan_activate
    """
    resp = api.create_coverage_plan(
        create_coverage_plan_payload(name="Bad", tier="POWERTRAIN", reinsurance_cession_pct=1.5), ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_CESSION_PCT)


def test_vehicle_ineligible_by_odometer_at_activation(api):
    """PRD §3.2: "the contract's `odometer_at_sale` must be at most the plan's
    `max_odometer_at_sale`; a vehicle failing either bound is rejected with
    `ERR_VEHICLE_INELIGIBLE` (HTTP 422)."

    Design: Corner/validations/vehicle_ineligible_by_odometer_at_activation
    """
    base = setup_pending_contract(
        pool_name="Pool VI",
        contract_overrides={"vin": "VINVI00001", "odometer_at_sale": 90000},
    )
    resp = api.activate_contract(base["contract"]["id"], CONTRACT_ADMIN)
    validate_error(resp, ApiErrorId.ERR_VEHICLE_INELIGIBLE)


def test_finance_term_required_when_financed(api):
    """PRD §3.2: "if the contract is financed, its `finance_term_months` must be at
    least 1, or the activation is rejected with `ERR_FINANCE_TERM_REQUIRED` (HTTP 422)."

    Design: Corner/validations/finance_term_required_when_financed
    """
    base = setup_pending_contract(
        pool_name="Pool FT",
        contract_overrides={"vin": "VINFT00001", "financed": True, "finance_term_months": 0},
    )
    resp = api.activate_contract(base["contract"]["id"], CONTRACT_ADMIN)
    validate_error(resp, ApiErrorId.ERR_FINANCE_TERM_REQUIRED)


def test_invalid_claim_line_part_missing_part_number(api):
    """PRD §3.4: "A `PART` line must include a `part_number` and a `LABOR` line must
    include `labor_hours` greater than 0; a line violating either requirement is
    rejected with `ERR_INVALID_CLAIM_LINE` (HTTP 422)."

    Design: Corner/validations/invalid_claim_line_part_missing_part_number
    """
    base = setup_active_contract(pool_name="Pool CL", contract_overrides={"vin": "VINCL00001"}, with_facility=True)
    from test_helpers.fixtures import api_client
    claim = api_client.create_claim(
        {"contract_id": base["contract"]["id"], "repair_facility_id": base["facility"]["id"],
         "odometer_at_claim": 40000, "claim_date": "2026-02-01T00:00:00Z", "complaint": "part"},
        ADJUSTER,
    ).json()["data"]
    resp = api.create_claim_line(
        claim["id"], create_claim_line_payload(line_type="PART", requested_amount_cents=5000, covered=True), ADJUSTER,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_CLAIM_LINE)


def test_bundle_too_late_after_activation(api):
    """PRD §3.3: "Bundling is only permitted while the parent contract is in
    `PENDING` status; attempting to bundle an ancillary onto a non-`PENDING`
    contract — in particular adding GAP after activation — is rejected with
    `ERR_BUNDLE_TOO_LATE` (HTTP 422)."

    Design: Corner/errors/bundle_too_late_after_activation
    """
    base = setup_active_contract(pool_name="Pool BL", contract_overrides={"vin": "VINBL00001"})
    resp = api.create_ancillary_product(
        create_ancillary_product_payload(base["contract"]["id"], product_type="GAP",
                                         premium_cents=30000, gap_cap_cents=500000),
        CONTRACT_ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_BUNDLE_TOO_LATE)


def test_nothing_covered_on_approve(api):
    """PRD §3.4: "an attempt to approve when nothing is covered (the adjudicated
    amount is exactly 0) is rejected with `ERR_NOTHING_COVERED` (HTTP 422)."

    Design: Corner/errors/nothing_covered_on_approve
    """
    base = setup_under_review_claim(
        claim_overrides={"complaint": "uncovered"},
        claim_lines=[{"line_type": "PART", "part_number": "U-9", "requested_amount_cents": 50000, "covered": False}],
        pool_name="Pool NC",
        contract_overrides={"vin": "VINNC00001"},
    )
    resp = api.approve_claim(base["claim"]["id"], ADJUSTER)
    validate_error(resp, ApiErrorId.ERR_NOTHING_COVERED)
