"""Billing calculation tests: the two billing variants, the forward-looking estimate vs the
chronological final invoice, and the non-linear / pinned-evaluation-order fee arithmetic.

Difficulty queue (A) instances for dual_variant_calc and combinatorial_formula, plus the
corner-queue (B) single-result calculation claims.
"""
from test_helpers import (
    validate_success, get_success_data,
    setup_resulted_order, setup_resulted_order_after_one_redraw, setup_catalog,
    api_client, TEST_USERS,
)

_PROVIDER = TEST_USERS["ordering_provider_headers"]
_BILLING = TEST_USERS["billing_agent_headers"]


# ---------------------------------------------------------------------------
# Queue A — dual_variant_calc
# ---------------------------------------------------------------------------

def test_self_pay_invoice_total_for_routine_three_tube_order(api):
    """PRD §3.10: "The convenience fee is a flat base of 3,500 cents plus a per-extra-tube
    surcharge of 500 cents, where the number of extra tubes is the panel's required_tube_count
    minus one but never below zero; so convenience_fee_cents equals 3,500 cents plus 500 cents
    times the greater of zero and required_tube_count minus one."
    PRD §3.10: "The self-pay total is the lab fee plus the convenience fee minus the waiver,
    floored at zero: total_cents equals the greater of zero and lab_fee_cents plus
    convenience_fee_cents minus redraw_waiver_cents."

    Design: Difficulty/dual_variant_calc/billing_mode_divergence_self_pay_vs_insurance
    """
    ctx = setup_resulted_order(billing_mode="SELF_PAY", priority="ROUTINE",
                               required_tube_count=3, base_lab_fee_cents=4000,
                               stat_surcharge_cents=1500)
    inv = validate_success(api.issue_invoice(ctx["invoice_id"], _BILLING))
    assert inv["lab_fee_cents"] == 4000, f"expected lab_fee 4000, got {inv['lab_fee_cents']}"
    assert inv["convenience_fee_cents"] == 4500, f"expected convenience 4500, got {inv['convenience_fee_cents']}"
    assert inv["redraw_waiver_cents"] == 0
    assert inv["total_cents"] == 8500, f"expected total 8500, got {inv['total_cents']}"
    assert inv["status"] == "ISSUED"


def test_insurance_invoice_total_excludes_lab_fee(api):
    """PRD §3.10: "The insurance convenience fee is a flat 2,500 cents regardless of tube count,
    because the insurer reimburses processing per panel rather than per tube; tube count is ignored."
    PRD §3.10: "The insurance patient total excludes the lab fee entirely: total_cents equals
    the greater of zero and convenience_fee_cents minus redraw_waiver_cents."

    Design: Difficulty/dual_variant_calc/billing_mode_divergence_self_pay_vs_insurance
    """
    ctx = setup_resulted_order(billing_mode="INSURANCE", priority="ROUTINE",
                               required_tube_count=3, base_lab_fee_cents=4000,
                               stat_surcharge_cents=1500, insurance_member_id="MEM-1")
    inv = validate_success(api.issue_invoice(ctx["invoice_id"], _BILLING))
    assert inv["lab_fee_cents"] == 4000, f"expected lab_fee 4000 (stored), got {inv['lab_fee_cents']}"
    assert inv["convenience_fee_cents"] == 2500, f"expected convenience 2500, got {inv['convenience_fee_cents']}"
    assert inv["redraw_waiver_cents"] == 0
    assert inv["total_cents"] == 2500, f"expected total 2500, got {inv['total_cents']}"
    assert inv["status"] == "ISSUED"


def test_order_estimate_stamped_at_creation_carries_no_waiver(api):
    """PRD §3.10: "They can diverge: the estimate is first stamped at order creation when
    redraw_count is zero (so it carries no redraw waiver), whereas the final invoice reflects
    whatever redraws actually accrued between order creation and issue."

    Design: Difficulty/dual_variant_calc/order_estimate_vs_final_after_redraw
    """
    panel, partner = setup_catalog(panel_code="CMP14", required_tube_count=3, base_lab_fee_cents=4000,
                                   accepted_panel_codes=["CMP14"], stat_surcharge_cents=1500)
    order = get_success_data(api.create_lab_order(
        {"patient_full_name": "Sam", "patient_territory_code": "SF_BAY", "panel_code": "CMP14",
         "lab_partner_id": partner["id"], "billing_mode": "SELF_PAY", "priority": "ROUTINE"},
        _PROVIDER,
    ))
    # SELF_PAY 3-tube base 4000, redraw_count 0: lab_fee 4000 + convenience 4500 - waiver 0 = 8500.
    assert order["total_due_cents"] == 8500, f"expected 8500 at creation, got {order['total_due_cents']}"
    assert order["redraw_count"] == 0
    assert order["status"] == "ORDERED"


def test_order_estimate_recomputed_after_redraw_applies_waiver(api):
    """PRD §3.9: "The order's total_due_cents is recomputed (see §3.10), now reflecting the
    accrued redraw."
    PRD §3.10: "After a QNS-driven redraw bumps the count, the estimate is recomputed and now
    reflects the accrued waiver, diverging from the at-creation estimate for the same panel and
    partner inputs."

    Design: Difficulty/dual_variant_calc/order_estimate_vs_final_after_redraw
    """
    # Drive a SELF_PAY 3-tube order through draw, manifest, pickup, then QNS-reject one specimen
    # so the DRAW_COMPLETED order moves to REDRAW_REQUIRED with redraw_count 1.
    from test_helpers import setup_draw_completed_with_in_transit_specimens
    ctx = setup_draw_completed_with_in_transit_specimens(
        billing_mode="SELF_PAY", panel_code="CMP14", required_tube_count=3,
        base_lab_fee_cents=4000, manifest_specimen_count=1,
    )
    get_success_data(api.reject_qns(ctx["specimens"][0]["id"], TEST_USERS["lab_ops_headers"]))
    order = validate_success(api.get_lab_order(ctx["order_id"], _PROVIDER))
    assert order["redraw_count"] == 1, f"expected redraw_count 1, got {order['redraw_count']}"
    assert order["status"] == "REDRAW_REQUIRED"
    # SELF_PAY: lab_fee 4000 + convenience 4500 - waiver min(4500, 1*1000)=1000 = 7500.
    assert order["total_due_cents"] == 7500, f"expected 7500 after redraw, got {order['total_due_cents']}"


# ---------------------------------------------------------------------------
# Queue A — combinatorial_formula
# ---------------------------------------------------------------------------

def test_self_pay_stat_three_tube_after_one_redraw_total(api):
    """PRD §3.10: "the lab_fee_cents is the panel's base_lab_fee_cents, plus the partner's
    stat_surcharge_cents when the order's priority is STAT, and nothing extra when the priority
    is ROUTINE."
    PRD §3.10: "The redraw waiver credits 1,000 cents per redraw, but the credit can never
    exceed the convenience fee: redraw_waiver_cents is the smaller of the convenience fee and
    1,000 cents times the order's redraw_count."

    Design: Difficulty/combinatorial_formula/self_pay_total_multi_input_nonlinear_mode_a
    """
    ctx = setup_resulted_order_after_one_redraw(
        billing_mode="SELF_PAY", priority="STAT", required_tube_count=3,
        base_lab_fee_cents=4000, stat_surcharge_cents=1500,
    )
    inv = validate_success(api.issue_invoice(ctx["invoice_id"], _BILLING))
    # lab_fee 4000 + STAT 1500 = 5500; convenience 3500 + 2*500 = 4500;
    # waiver min(4500, 1*1000) = 1000; total 5500 + 4500 - 1000 = 9000.
    assert inv["lab_fee_cents"] == 5500, f"expected lab_fee 5500, got {inv['lab_fee_cents']}"
    assert inv["convenience_fee_cents"] == 4500, f"expected convenience 4500, got {inv['convenience_fee_cents']}"
    assert inv["redraw_waiver_cents"] == 1000, f"expected waiver 1000, got {inv['redraw_waiver_cents']}"
    assert inv["total_cents"] == 9000, f"expected total 9000, got {inv['total_cents']}"


def test_insurance_stat_one_redraw_waiver_caps_and_floors_total_to_zero(api):
    """PRD §3.10: "The redraw waiver under insurance credits 2,500 cents per redraw, again
    capped at the convenience fee: redraw_waiver_cents is the smaller of the convenience fee
    and 2,500 cents times the order's redraw_count — which means a single redraw fully waives
    the insurance convenience fee."
    PRD §3.10: "The insurance patient total excludes the lab fee entirely: total_cents equals
    the greater of zero and convenience_fee_cents minus redraw_waiver_cents."

    Design: Difficulty/combinatorial_formula/redraw_waiver_eval_order_pin_mode_c
    """
    ctx = setup_resulted_order_after_one_redraw(
        billing_mode="INSURANCE", priority="STAT", required_tube_count=3,
        base_lab_fee_cents=4000, stat_surcharge_cents=1500, insurance_member_id="MEM-1",
    )
    inv = validate_success(api.issue_invoice(ctx["invoice_id"], _BILLING))
    # lab_fee 4000 + STAT 1500 = 5500 (stored, excluded); convenience 2500;
    # waiver min(2500, 1*2500) = 2500; total max(0, 2500 - 2500) = 0.
    assert inv["lab_fee_cents"] == 5500, f"expected lab_fee 5500, got {inv['lab_fee_cents']}"
    assert inv["convenience_fee_cents"] == 2500, f"expected convenience 2500, got {inv['convenience_fee_cents']}"
    assert inv["redraw_waiver_cents"] == 2500, f"expected waiver 2500, got {inv['redraw_waiver_cents']}"
    assert inv["total_cents"] == 0, f"expected total 0, got {inv['total_cents']}"


def test_self_pay_stat_redraw_total_components_sum_nonlinearly(api):
    """PRD §3.10: "The convenience fee is a flat base of 3,500 cents plus a per-extra-tube
    surcharge of 500 cents, where the number of extra tubes is the panel's required_tube_count
    minus one but never below zero; so convenience_fee_cents equals 3,500 cents plus 500 cents
    times the greater of zero and required_tube_count minus one."
    PRD §3.10: "The self-pay total is the lab fee plus the convenience fee minus the waiver,
    floored at zero: total_cents equals the greater of zero and lab_fee_cents plus
    convenience_fee_cents minus redraw_waiver_cents."

    Design: Difficulty/combinatorial_formula/self_pay_total_multi_input_nonlinear_mode_a
    """
    ctx = setup_resulted_order_after_one_redraw(
        billing_mode="SELF_PAY", priority="STAT", required_tube_count=3,
        base_lab_fee_cents=4000, stat_surcharge_cents=1500,
    )
    inv = validate_success(api.issue_invoice(ctx["invoice_id"], _BILLING))
    # The total is not reproducible by any single linear term: it is the sum of the STAT-branched
    # lab fee, the tiered convenience fee, minus the capped waiver.
    assert inv["total_cents"] == (
        inv["lab_fee_cents"] + inv["convenience_fee_cents"] - inv["redraw_waiver_cents"]
    ), "total must equal lab_fee + convenience - waiver"
    assert inv["total_cents"] == 9000, f"expected total 9000, got {inv['total_cents']}"
    assert inv["status"] == "ISSUED"


def test_insurance_redraw_waiver_capped_at_convenience_fee(api):
    """PRD §3.10: "The redraw waiver under insurance credits 2,500 cents per redraw, again capped
    at the convenience fee: redraw_waiver_cents is the smaller of the convenience fee and 2,500
    cents times the order's redraw_count — which means a single redraw fully waives the insurance
    convenience fee."

    Design: Difficulty/combinatorial_formula/redraw_waiver_eval_order_pin_mode_c
    """
    ctx = setup_resulted_order_after_one_redraw(
        billing_mode="INSURANCE", priority="STAT", required_tube_count=3,
        base_lab_fee_cents=4000, stat_surcharge_cents=1500, insurance_member_id="MEM-1",
    )
    inv = validate_success(api.issue_invoice(ctx["invoice_id"], _BILLING))
    # waiver == convenience fee (cap binds: min(2500, 1*2500) == 2500), so it never exceeds it.
    assert inv["redraw_waiver_cents"] == inv["convenience_fee_cents"], \
        "waiver must be capped at the convenience fee"
    assert inv["redraw_waiver_cents"] == 2500
    assert inv["total_cents"] == 0, f"expected total floored to 0, got {inv['total_cents']}"


# ---------------------------------------------------------------------------
# Queue B — calculations corner instances
# ---------------------------------------------------------------------------

def test_insurance_routine_no_redraw_total_is_2500(api):
    """PRD §3.10: "The insurance convenience fee is a flat 2,500 cents regardless of tube count,
    because the insurer reimburses processing per panel rather than per tube; tube count is ignored."
    PRD §3.10: "The insurance patient total excludes the lab fee entirely: total_cents equals
    the greater of zero and convenience_fee_cents minus redraw_waiver_cents."

    Design: Corner/calculations/insurance_routine_no_redraw_total_is_2500
    """
    ctx = setup_resulted_order(billing_mode="INSURANCE", priority="ROUTINE",
                               required_tube_count=3, base_lab_fee_cents=4000,
                               stat_surcharge_cents=1500, insurance_member_id="MEM-9")
    inv = validate_success(api.issue_invoice(ctx["invoice_id"], _BILLING))
    assert inv["lab_fee_cents"] == 4000, f"expected lab_fee 4000, got {inv['lab_fee_cents']}"
    assert inv["convenience_fee_cents"] == 2500
    assert inv["total_cents"] == 2500, f"expected total 2500, got {inv['total_cents']}"


def test_self_pay_single_tube_no_per_tube_surcharge(api):
    """PRD §3.10: "so convenience_fee_cents equals 3,500 cents plus 500 cents times the greater
    of zero and required_tube_count minus one."

    Design: Corner/calculations/self_pay_single_tube_no_per_tube_surcharge
    """
    ctx = setup_resulted_order(billing_mode="SELF_PAY", priority="ROUTINE",
                               panel_code="ONE", required_tube_count=1, base_lab_fee_cents=2000)
    inv = validate_success(api.issue_invoice(ctx["invoice_id"], _BILLING))
    # extra_tubes max(0, 1-1) = 0; convenience 3500 + 0 = 3500; lab_fee 2000; total 5500.
    assert inv["lab_fee_cents"] == 2000, f"expected lab_fee 2000, got {inv['lab_fee_cents']}"
    assert inv["convenience_fee_cents"] == 3500, f"expected convenience 3500, got {inv['convenience_fee_cents']}"
    assert inv["total_cents"] == 5500, f"expected total 5500, got {inv['total_cents']}"


def test_manifest_accession_due_is_pickup_plus_sla_hours(api):
    """PRD §3.8: "On a successful pickup, the manifest's picked_up_at_utc is set to the logical
    clock, the manifest moves from BUILDING to IN_TRANSIT, and the manifest's accession_due_utc
    is set to the pickup instant plus the partner's courier_sla_hours whole hours."

    Design: Corner/calculations/manifest_accession_due_sla_addition
    """
    from test_helpers import (
        setup_scheduled_appointment, drive_to_draw_completed, make_phlebotomist_headers,
        create_manifest_payload,
    )
    _DISPATCHER = TEST_USERS["dispatcher_headers"]
    ctx = setup_scheduled_appointment(
        panel_code="ONE", required_tube_count=1, base_lab_fee_cents=1000,
        service_date="2026-02-02",
        shift_start_utc="2026-02-02T06:00:00Z", shift_end_utc="2026-02-02T22:00:00Z",
        window_start_utc="2026-02-02T08:00:00Z", window_end_utc="2026-02-02T08:30:00Z",
    )
    drive_to_draw_completed(ctx)
    manifest = get_success_data(
        api.create_manifest(create_manifest_payload(ctx["partner_id"]), _DISPATCHER)
    )
    phleb_headers = make_phlebotomist_headers(ctx["phleb_id"])
    get_success_data(
        api.add_specimen_to_manifest(manifest["id"], {"specimen_id": ctx["specimens"][0]["id"]}, phleb_headers)
    )
    # Advance the logical clock to a known instant, then record pickup; partner SLA = 24h.
    get_success_data(api.set_clock("2026-02-02T10:00:00Z", _DISPATCHER))
    picked = validate_success(api.pickup_manifest(manifest["id"], _DISPATCHER))
    assert picked["status"] == "IN_TRANSIT"
    assert picked["picked_up_at_utc"] == "2026-02-02T10:00:00.000Z", \
        f"expected picked_up 2026-02-02T10:00:00.000Z, got {picked['picked_up_at_utc']}"
    assert picked["accession_due_utc"] == "2026-02-03T10:00:00.000Z", \
        f"expected accession_due 2026-02-03T10:00:00.000Z, got {picked['accession_due_utc']}"
