"""Annual report lifecycle, GROSS/NET surplus, and largest-remainder split."""
from test_helpers import (
    api_client, validate_success, validate_error, ApiErrorId, TEST_USERS,
    create_annual_report_payload, accept_report_payload,
    create_surplus_agreement_payload,
    setup_certified_district, setup_filed_report_scenario, capture_increment,
    add_surplus_agreement, create_and_file_report, accept_report_now,
    fund_version, get_fund,
)

ADMIN = TEST_USERS["municipal_admin_headers"]
ADMIN_2 = TEST_USERS["municipal_admin_2_headers"]
CLERK = TEST_USERS["county_clerk_headers"]
SINGLE = [("School", "SCHOOL", 0.05)]
TWO_BODIES = [("School", "SCHOOL", 0.05), ("County", "COUNTY", 0.02)]


def _dist_by_body(district_id):
    rows = validate_success(api_client.get_district_surplus_distributions(district_id, ADMIN))
    return {r["taxing_body_id"]: r for r in rows}


# ─── Difficulty: dual-variant — GROSS vs NET surplus determination ─────────

def test_gross_basis_reserves_near_term_debt_service():
    """PRD 3.5: "Under the `GROSS` basis the reserve covers only near-term senior
    debt service: for each such senior obligation, its `accrued_interest_cents` plus
    the smaller of its `principal_remaining_cents` and its per-year principal
    amortization, where the per-year amortization is the obligation's `principal_cents`
    divided by the number of tax years in its term".
    PRD 3.5: "The `surplus_declared_cents` is the `ending_balance_cents` minus the
    `obligation_reserve_cents`, or zero if that difference would be negative."

    Design: Difficulty/dual_variant_calc/annual_surplus_gross_vs_net
    """
    ctx = setup_filed_report_scenario(
        surplus_policy="GROSS", base_eav_cents=100_000_000, current_eav_cents=118_750_000,
        report_tax_year=2027, bond_principal=10_000_000, bond_maturity=2035)
    accepted = accept_report_now(ctx["report"]["id"], ctx["district"]["id"],
                                 expected_fund_version=ctx["fund_version"])
    assert accepted["surplus_basis"] == "GROSS"
    assert accepted["obligation_reserve_cents"] == 1_000_000
    assert accepted["surplus_declared_cents"] == 455_000


def test_net_basis_reserves_full_senior_outstanding():
    """PRD 3.5: "Under the `NET` basis the reserve is instead the full remaining
    senior exposure: the sum of `outstanding_balance_cents` across those same senior
    obligations."
    PRD 3.5: "The `surplus_declared_cents` is the `ending_balance_cents` minus the
    `obligation_reserve_cents`, or zero if that difference would be negative."

    Design: Difficulty/dual_variant_calc/annual_surplus_gross_vs_net
    """
    ctx = setup_filed_report_scenario(
        surplus_policy="NET", base_eav_cents=100_000_000, current_eav_cents=118_750_000,
        report_tax_year=2027, bond_principal=10_000_000, bond_maturity=2035)
    accepted = accept_report_now(ctx["report"]["id"], ctx["district"]["id"],
                                 expected_fund_version=ctx["fund_version"])
    assert accepted["surplus_basis"] == "NET"
    assert accepted["obligation_reserve_cents"] == 10_000_000
    assert accepted["surplus_declared_cents"] == 0


# ─── Difficulty: combinatorial formula — largest-remainder split ───────────

def test_surplus_split_largest_remainder_amounts():
    """PRD 3.6: "those leftover cents are handed out one at a time to the bodies
    ranked by the fractional part of their exact entitlement in descending order,
    breaking ties by `created_at` ascending."

    Design: Difficulty/combinatorial_formula/surplus_split_largest_remainder
    """
    ctx = setup_filed_report_scenario(
        surplus_policy="GROSS", base_eav_cents=100_000_000, current_eav_cents=112_500_013,
        report_tax_year=2027, bond_principal=None)  # fund 970,001, no reserve
    d_id = ctx["district"]["id"]
    school, county, city = [b["id"] for b in ctx["bodies"]]
    accepted = accept_report_now(ctx["report"]["id"], d_id,
                                 expected_fund_version=ctx["fund_version"])
    assert accepted["surplus_declared_cents"] == 970_001
    dist = _dist_by_body(d_id)
    assert dist[school]["amount_cents"] == 606_251
    assert dist[county]["amount_cents"] == 242_500
    assert dist[city]["amount_cents"] == 121_250


def test_surplus_split_reconciles_exactly():
    """PRD 3.6: "By construction the weights sum to one and the distributed cents sum
    exactly to the surplus amount."

    Design: Difficulty/combinatorial_formula/surplus_split_largest_remainder
    """
    ctx = setup_filed_report_scenario(
        surplus_policy="GROSS", base_eav_cents=100_000_000, current_eav_cents=112_500_013,
        report_tax_year=2027, bond_principal=None)
    d_id = ctx["district"]["id"]
    accepted = accept_report_now(ctx["report"]["id"], d_id,
                                 expected_fund_version=ctx["fund_version"])
    rows = validate_success(api_client.get_district_surplus_distributions(d_id, ADMIN))
    assert sum(r["amount_cents"] for r in rows) == accepted["surplus_declared_cents"] == 970_001


# ─── Difficulty: boundary — surplus zero when balance == reserve ───────────

def test_surplus_zero_when_balance_equals_reserve():
    """PRD 3.5: "The `surplus_declared_cents` is the `ending_balance_cents` minus the
    `obligation_reserve_cents`, or zero if that difference would be negative."

    Design: Difficulty/boundary_precision_check/surplus_zero_when_balance_equals_reserve
    """
    ctx = setup_filed_report_scenario(
        surplus_policy="GROSS", base_eav_cents=100_000_000, current_eav_cents=112_500_000,
        report_tax_year=2027, bond_principal=9_700_000, bond_maturity=2035)  # per-year 970,000
    accepted = accept_report_now(ctx["report"]["id"], ctx["district"]["id"],
                                 expected_fund_version=ctx["fund_version"])
    assert accepted["ending_balance_cents"] == 970_000
    assert accepted["obligation_reserve_cents"] == 970_000
    assert accepted["surplus_declared_cents"] == 0


def test_zero_surplus_creates_no_distributions_and_keeps_balance():
    """PRD 3.5: "When the declared surplus is zero, no distribution rows are created
    and the fund balance is unchanged, though the report still moves to `ACCEPTED`."

    Design: Difficulty/boundary_precision_check/surplus_zero_when_balance_equals_reserve
    """
    ctx = setup_filed_report_scenario(
        surplus_policy="GROSS", base_eav_cents=100_000_000, current_eav_cents=112_500_000,
        report_tax_year=2027, bond_principal=9_700_000, bond_maturity=2035)
    d_id = ctx["district"]["id"]
    accepted = accept_report_now(ctx["report"]["id"], d_id,
                                 expected_fund_version=ctx["fund_version"])
    assert accepted["status"] == "ACCEPTED"
    assert validate_success(api_client.get_district_surplus_distributions(d_id, ADMIN)) == []
    assert get_fund(d_id)["balance_cents"] == 970_000


# ─── Difficulty: validation priority — validation beats referential ────────

def test_malformed_window_and_foreign_body_returns_validation():
    """PRD 2.7: "4. Body well-formedness — the body is present with all required
    fields, valid enum values, and satisfied numeric constraints such as
    strictly-positive amounts and bounded ranges, else `ERR_VALIDATION` (422)."
    PRD 3.6: "the `end_tax_year` must be strictly greater than the `start_tax_year`."

    Design: Difficulty/priority_pair_validation_conflict/validation_beats_referential_on_surplus_agreement
    """
    ctx_a = setup_certified_district(bodies=[("School A", "SCHOOL", 0.05)],
                                     base_eav_cents=100_000_000)
    ctx_b = setup_certified_district(bodies=[("School B", "SCHOOL", 0.05)],
                                     base_eav_cents=100_000_000)
    tb_foreign = ctx_b["bodies"][0]["id"]
    resp = api_client.create_surplus_agreement(
        ctx_a["district"]["id"],
        create_surplus_agreement_payload(tb_foreign, 2030, 2028, 500_000),  # end < start
        ADMIN)
    validate_error(resp, ApiErrorId.ERR_VALIDATION, expected_status=422)


def test_wellformed_window_with_foreign_body_returns_referential():
    """PRD 2.7: "5. Referential integrity of body foreign keys — for example a
    `taxing_body_id` on a surplus agreement must belong to the path district, and an
    obligation's `developer_id` must resolve — else `ERR_TAXING_BODY_NOT_IN_DISTRICT`
    (409)."
    PRD 3.6: "The referenced `taxing_body_id` must belong to the path district, else
    the request is rejected with `ERR_TAXING_BODY_NOT_IN_DISTRICT`."

    Design: Difficulty/priority_pair_validation_conflict/validation_beats_referential_on_surplus_agreement
    """
    ctx_a = setup_certified_district(bodies=[("School A", "SCHOOL", 0.05)],
                                     base_eav_cents=100_000_000)
    ctx_b = setup_certified_district(bodies=[("School B", "SCHOOL", 0.05)],
                                     base_eav_cents=100_000_000)
    tb_foreign = ctx_b["bodies"][0]["id"]
    resp = api_client.create_surplus_agreement(
        ctx_a["district"]["id"],
        create_surplus_agreement_payload(tb_foreign, 2027, 2030, 500_000),  # valid window
        ADMIN)
    validate_error(resp, ApiErrorId.ERR_TAXING_BODY_NOT_IN_DISTRICT, expected_status=409)


# ─── Difficulty: temporal overlap — half-open agreement windows ────────────

def test_overlapping_agreement_window_rejected():
    """PRD 3.6: "Two agreements for the same body may not cover overlapping year
    windows — using half-open comparison, one window's start falling before another's
    end and vice versa — and an overlapping request is rejected with
    `ERR_AGREEMENT_PERIOD_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/surplus_agreement_halfopen_window_overlap
    """
    ctx = setup_certified_district(bodies=SINGLE, base_eav_cents=100_000_000)
    d_id = ctx["district"]["id"]
    tb_id = ctx["bodies"][0]["id"]
    add_surplus_agreement(d_id, tb_id, 2027, 2030, 400_000)
    resp = api_client.create_surplus_agreement(
        d_id, create_surplus_agreement_payload(tb_id, 2029, 2032, 300_000), ADMIN)
    validate_error(resp, ApiErrorId.ERR_AGREEMENT_PERIOD_OVERLAP, expected_status=409)


def test_adjacent_halfopen_agreement_window_allowed():
    """PRD 3.6: "The window is half-open, `[start_tax_year, end_tax_year)`: it
    includes the start year and excludes the end year, and the `end_tax_year` must be
    strictly greater than the `start_tax_year`."

    Design: Difficulty/resource_temporal_overlap/surplus_agreement_halfopen_window_overlap
    """
    ctx = setup_certified_district(bodies=SINGLE, base_eav_cents=100_000_000)
    d_id = ctx["district"]["id"]
    tb_id = ctx["bodies"][0]["id"]
    add_surplus_agreement(d_id, tb_id, 2027, 2030, 400_000)
    ok = validate_success(api_client.create_surplus_agreement(
        d_id, create_surplus_agreement_payload(tb_id, 2030, 2033, 300_000), ADMIN),
        expected_status=201)
    assert ok["start_tax_year"] == 2030


# ─── Corner: surplus split with override applied ───────────────────────────

def test_surplus_split_with_override_agreement():
    """PRD 3.6: "A body is in the override set for this distribution if it has an
    agreement whose half-open window covers the `report_tax_year`".
    PRD 3.6: "Each such overriding body's weight is its `surplus_share_ppm_override`
    divided by one million."
    PRD 3.6: "those leftover cents are handed out one at a time to the bodies ranked
    by the fractional part of their exact entitlement in descending order, breaking
    ties by `created_at` ascending."

    Design: Corner/calculations/surplus_split_override_applied
    """
    ctx = setup_certified_district(bodies=TWO_BODIES, surplus_policy="GROSS",
                                   base_eav_cents=100_000_000)
    d_id = ctx["district"]["id"]
    school, county = ctx["bodies"][0]["id"], ctx["bodies"][1]["id"]
    add_surplus_agreement(d_id, county, 2027, 2028, 500_000)
    capture_increment(d_id, 2026, 114_285_729)  # aggregate 0.07 -> captured 970,001
    report = create_and_file_report(d_id, 2027)
    accepted = accept_report_now(report["id"], d_id)
    assert accepted["surplus_declared_cents"] == 970_001
    dist = _dist_by_body(d_id)
    assert dist[school]["amount_cents"] == 485_001
    assert dist[county]["amount_cents"] == 485_000


# ─── Corner: report state machine ──────────────────────────────────────────

def test_accept_unfiled_report_returns_invalid_state():
    """PRD 3.5: "Acceptance advances the report from `FILED` to `ACCEPTED` and
    requires the report to be in `FILED`, else `ERR_REPORT_INVALID_STATE`".

    Design: Corner/state_machines/accept_unfiled_report_returns_invalid_state
    """
    ctx = setup_certified_district(bodies=SINGLE, base_eav_cents=100_000_000)
    d_id = ctx["district"]["id"]
    report = validate_success(api_client.create_annual_report(
        d_id, create_annual_report_payload(2027), CLERK), expected_status=201)
    resp = api_client.accept_report(
        report["id"], accept_report_payload(fund_version(d_id)), ADMIN_2)
    validate_error(resp, ApiErrorId.ERR_REPORT_INVALID_STATE, expected_status=409)


def test_report_return_cycle_ends_filed():
    """PRD 3.5: "Filing the report advances it from `DRAFT` to `FILED`".
    PRD 3.5: "Returning a filed report is the reverse escape hatch: a `MunicipalAdmin`
    may send a `FILED` report back to `DRAFT` for correction, which is permitted only
    from `FILED`".

    Design: Corner/state_machines/annual_report_return_cycle_valid
    """
    ctx = setup_certified_district(bodies=SINGLE, base_eav_cents=100_000_000)
    d_id = ctx["district"]["id"]
    report = create_and_file_report(d_id, 2027)
    validate_success(api_client.return_report(report["id"], ADMIN))     # FILED -> DRAFT
    refiled = validate_success(api_client.file_report(report["id"], CLERK))
    assert refiled["status"] == "FILED"
