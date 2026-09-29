"""Multi-input formulas: the nested FMV clamp, the TI cost split and the invoice build."""
from test_helpers import (
    assert_invoice_breakdown,
    assert_line_split,
    assert_money_equals,
    assert_parking_counters,
    assert_project_rollups,
    assert_share_equals,
    expected_invoice_total,
    validate_paginated,
)
from test_helpers import fixtures as fx
from test_helpers.test_users import (
    COMPLIANCE_OFFICER,
    LEASING_AGENT,
    PROPERTY_MANAGER,
)


def _imaging_clamp_ladder(api):
    """A physician-owned radiology lease on an 8000 sf IMAGING suite, priced at 41.98."""
    ctx = fx.leasing_baseline(
        api,
        suite_overrides={"suite_number": "150", "floor": 1, "rentable_sf": 8000,
                         "suite_class": "IMAGING", "power_amps_available": 600,
                         "medical_gas_available": False, "shielding_certified": True,
                         "lead_thickness_mm": 2.5},
        tenant_overrides={"legal_name": "Clearview Imaging Partners",
                          "primary_specialty": "RADIOLOGY",
                          "is_physician_owned": True},
    )
    ctx["lease"] = fx.draft_lease(api, ctx["building"]["id"], ctx["suite"]["id"],
                                  ctx["tenant"]["id"], base_rent_psf_annual=41.98)
    ctx["appraisal"] = fx.qualified_appraisal_for(
        api, ctx["lease"]["id"], ctx["lease"]["version"], appraisal_date="2026-07-20",
        opinion_low_psf=38.00, opinion_high_psf=42.00)
    fx.submit_for_review(api, ctx["lease"]["id"])
    return ctx


def test_certified_band_takes_its_floor_from_the_appraisal_and_its_ceiling_from_the_rate_card(api):
    """The nested clamp resolves each end independently, so the two ends differ in source.

    PRD: "For a physician-owned tenant, the controlling appraisal supplies a second band —
    90% of `opinion_midpoint_psf` as its floor and 110% of that midpoint as its ceiling,
    each rounded half up to 2 decimal places — and the two bands are then intersected:
    `certified_fmv_floor_psf` is the **greater** of the appraisal floor and the published
    floor, and `certified_fmv_ceiling_psf` is the **lesser** of the appraisal ceiling and
    the published ceiling."

    Design: Difficulty/combinatorial_formula/fmv_band_nested_clamp_takes_floor_and_ceiling_from_different_sources
    """
    ctx = _imaging_clamp_ladder(api)

    lease = fx.certify(api, ctx["lease"]["id"])
    assert lease["status"] == "FMV_CERTIFIED"
    # The opinion of 38.00/42.00 has a midpoint of 40.00, so the appraisal band is
    # [36.00, 44.00]; the 30.00 rate card plus the 6.50 imaging premium publishes
    # [29.20, 41.98]. The clamp keeps 36.00 from the appraisal and 41.98 from the card.
    assert_money_equals(lease["certified_fmv_floor_psf"], 36.00, "certified_fmv_floor_psf")
    assert_money_equals(lease["certified_fmv_ceiling_psf"], 41.98, "certified_fmv_ceiling_psf")

    appraisals, _meta = validate_paginated(
        api.list_lease_appraisals(ctx["lease"]["id"], COMPLIANCE_OFFICER,
                                  {"status": "QUALIFIED"}))
    assert len(appraisals) == 1
    assert_money_equals(appraisals[0]["opinion_midpoint_psf"], 40.00, "opinion_midpoint_psf")
    assert appraisals[0]["is_controlling"] is True


def test_a_variance_one_ten_thousandth_above_the_threshold_opens_a_deviation_case(api):
    """Certifying at the clamped ceiling drives the variance past 0.1500 and opens a case.

    PRD: "One further consequence fires conditionally: when the **absolute value** of
    `fmv_variance_pct` is strictly greater than 0.1500, the system opens an `FMV_DEVIATION`
    compliance case against the tenant in status `OPEN`, measured under the rolling
    twelve-month variant, with `opened_by_user_id` recorded as the literal value `system`,
    and then re-evaluates that tenant's `compliance_watch_status`."

    Design: Difficulty/combinatorial_formula/fmv_band_nested_clamp_takes_floor_and_ceiling_from_different_sources
    """
    ctx = _imaging_clamp_ladder(api)

    lease = fx.certify(api, ctx["lease"]["id"])
    # 36.50 published psf on 8000 sf is 292000.00; 41.98 negotiated is 335840.00.
    assert_money_equals(lease["provisional_base_rent_annual"], 292000.00,
                        "provisional_base_rent_annual")
    assert_money_equals(lease["certified_base_rent_annual"], 335840.00,
                        "certified_base_rent_annual")
    assert_money_equals(lease["fmv_variance_annual"], 43840.00, "fmv_variance_annual")
    assert_share_equals(lease["fmv_variance_pct"], 0.1501, "fmv_variance_pct")

    cases, meta = validate_paginated(
        api.list_tenant_compliance_cases(ctx["tenant"]["id"], COMPLIANCE_OFFICER,
                                         {"case_type": "FMV_DEVIATION"}))
    assert meta["total_count"] == 1
    assert cases[0]["status"] == "OPEN"
    assert cases[0]["opened_by_user_id"] == "system"
    assert cases[0]["scoring_variant"] == "ROLLING_12M"


def _imaging_ti_project(api):
    """A DESIGN project targeting IMAGING with a 0.6000 default share and a 500000.00 allowance."""
    ctx = fx.drafted_lease(api)
    ctx["project"] = fx.open_ti_project(
        api, ctx["lease"]["id"], ctx["suite"]["id"], target_suite_class="IMAGING",
        lead_thickness_mm=2.5, power_amps_requested=150, medical_gas_requested=False,
        authorized_allowance_total=500000.00, landlord_share_pct=0.6000)
    return ctx


def test_ti_line_shares_are_rounded_per_line_before_any_summation(api):
    """Each line's landlord share is rounded first, and the tenant share is the remainder.

    PRD: "From the resolved share, `landlord_share_amount` is the line's `cost_amount`
    multiplied by `effective_share_pct`, rounded half up to 2 decimal places, and
    `tenant_share_amount` is the line's `cost_amount` **less** that rounded landlord amount."

    Design: Difficulty/combinatorial_formula/ti_cost_share_round_per_line_then_sum_pinned_order
    """
    ctx = _imaging_ti_project(api)
    project_id = ctx["project"]["id"]

    shielding = fx.add_line_item(api, project_id, ctx["project"]["version"],
                                 description="Lead shielding, walls and ceiling",
                                 category="SHIELDING", cost_amount=88000.00)
    power_one = fx.add_line_item(api, project_id, fx.read_project(api, project_id)["version"],
                                 description="Dedicated 3-phase feeder",
                                 category="POWER", cost_amount=12345.04)
    power_two = fx.add_line_item(api, project_id, fx.read_project(api, project_id)["version"],
                                 description="Panel upgrade and conduit",
                                 category="POWER", cost_amount=23456.09)
    finishes = fx.add_line_item(api, project_id, fx.read_project(api, project_id)["version"],
                               description="Flooring, casework and paint",
                               category="FINISHES", cost_amount=34567.14)

    # The category rule makes the landlord bear 100% of shielding on an imaging build-out.
    assert shielding["sequence_no"] == 1
    assert_line_split(shielding, 1.0000, 88000.00, 0.00)
    assert power_one["sequence_no"] == 2
    assert_line_split(power_one, 0.6000, 7407.02, 4938.02)
    assert power_two["sequence_no"] == 3
    assert_line_split(power_two, 0.6000, 14073.65, 9382.44)
    assert finishes["sequence_no"] == 4
    assert_line_split(finishes, 0.6000, 20740.28, 13826.86)


def test_project_totals_sum_the_already_rounded_line_figures(api):
    """The pinned order is worth one cent: the committed total is 130220.95, not 130220.96.

    PRD: "The project's totals are then sums of the **already-rounded** per-line figures,
    taken over the lines in `sequence_no` order: `landlord_committed_amount` sums the
    per-line landlord amounts, `tenant_committed_amount` sums the per-line tenant amounts,
    and `allowance_remaining` is `authorized_allowance_total` less
    `landlord_committed_amount`."

    Design: Difficulty/combinatorial_formula/ti_cost_share_round_per_line_then_sum_pinned_order
    """
    ctx = _imaging_ti_project(api)
    project_id = ctx["project"]["id"]

    for description, category, cost in (
            ("Lead shielding, walls and ceiling", "SHIELDING", 88000.00),
            ("Dedicated 3-phase feeder", "POWER", 12345.04),
            ("Panel upgrade and conduit", "POWER", 23456.09),
            ("Flooring, casework and paint", "FINISHES", 34567.14)):
        fx.add_line_item(api, project_id, fx.read_project(api, project_id)["version"],
                         description=description, category=category, cost_amount=cost)

    project = fx.read_project(api, project_id)
    assert_project_rollups(project, 130220.95, 28147.32, 369779.05, expected_line_count=4)

    lines, meta = validate_paginated(api.list_ti_line_items(project_id, LEASING_AGENT))
    assert meta["total_count"] == 4
    assert [line["sequence_no"] for line in lines] == [1, 2, 3, 4]


def test_invoice_waiver_tier_is_keyed_on_the_combined_pre_waiver_total(api):
    """Gross parking feeds the combined total that selects the tier applied back to parking.

    PRD: "The tier is keyed on `pre_waiver_total`, the **combined** figure from step 4, and
    not on the parking component alone."

    Design: Difficulty/combinatorial_formula/monthly_occupancy_charge_waiver_tier_keyed_on_combined_pre_waiver_total
    """
    ctx = fx.active_lease(api, lease_overrides={"base_rent_psf_annual": 32.00})
    building_id = ctx["building"]["id"]
    lease_id = ctx["lease"]["id"]

    fx.allocate_stalls(api, building_id, lease_id, "STAFF", 20)
    fx.allocate_stalls(api, building_id, lease_id, "PATIENT", 30)

    invoice = fx.issue_invoice(api, lease_id, "2026-09-01", "2026-09-30", "2026-09-05")

    # 160000.00 a year is 13333.33 a month, 9.60 psf on 5000 sf recovers 4000.00 and
    # 20 billable staff stalls gross 1000.00, for a combined 18333.33 in the 0.50 tier.
    assert_invoice_breakdown(invoice, expected_invoice_total(160000.00, 9.60, 5000,
                                                            staff_stalls=20,
                                                            patient_stalls=30))
    assert_money_equals(invoice["pre_waiver_total"], 18333.33, "pre_waiver_total")
    assert_share_equals(invoice["parking_waiver_tier_pct"], 0.50, "parking_waiver_tier_pct")
    assert_money_equals(invoice["parking_waiver_amount"], 500.00, "parking_waiver_amount")
    assert_money_equals(invoice["total_amount"], 17833.33, "total_amount")
    assert invoice["status"] == "ISSUED"


def test_patient_allocations_enter_the_input_set_but_are_priced_at_nothing(api):
    """Thirty patient stalls move the pool counters without adding to gross parking.

    PRD: "Staff stalls are billable at 50.00 per stall per month while patient stalls are
    free at 0.00 per stall per month, so patient allocations are counted in the input set
    but priced at nothing."

    Design: Difficulty/combinatorial_formula/monthly_occupancy_charge_waiver_tier_keyed_on_combined_pre_waiver_total
    """
    ctx = fx.active_lease(api, lease_overrides={"base_rent_psf_annual": 32.00})
    building_id = ctx["building"]["id"]
    lease_id = ctx["lease"]["id"]

    fx.allocate_stalls(api, building_id, lease_id, "STAFF", 20)
    fx.allocate_stalls(api, building_id, lease_id, "PATIENT", 30)

    building = fx.read_building(api, building_id, PROPERTY_MANAGER)
    assert_parking_counters(building, 20, 30, 350)

    invoice = fx.issue_invoice(api, lease_id, "2026-09-01", "2026-09-30", "2026-09-05")
    assert_money_equals(invoice["parking_fee_gross"], 1000.00, "parking_fee_gross")
