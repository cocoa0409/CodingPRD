"""Poundage calculations: planned-vs-distributed ledger divergence, planned
poundage from reserved (not requested), TEFAP-split waterfall, and the
fair-share cap floor formula.

Covers Difficulty queue rules dual_variant_calc and combinatorial_formula,
plus corner calculations instances.
"""
from prd_bench_local_runner.testing import (
    validate_success, validate_paginated, get_success_data,
)
from test_helpers import (
    api_client, TEST_USERS, fixtures, factories,
    make_agency_coordinator_headers,
)

MGR = TEST_USERS["allocation_manager_headers"]
OP = TEST_USERS["food_bank_operator_headers"]
AUD = TEST_USERS["compliance_auditor_headers"]


def _poundage_report(api, cycle_id):
    """Read the cycle's poundage report (the single-object endpoint)."""
    return validate_success(api.get_poundage_report(cycle_id, MGR))


def test_poundage_report_planned_counts_packed_distributed_excludes_unfinalized(api):
    """PRD §3.9: "The planned total, total_planned_lbs, is forward-looking: the
    sum of planned_lbs over every distribution event for this cycle's orders that
    has reached PACKED or FINALIZED, including events that are packed but not yet
    finalized."
    PRD §3.9: "a packed-but-unfinalized event contributes nothing to this total."
    PRD §3.9: "shrinkage_lbs is total_planned_lbs minus total_distributed_lbs"

    Design: Difficulty/dual_variant_calc/poundage_ledger_planned_vs_distributed_diverge
    """
    # Single line of 380 lbs, packed but not finalized.
    ctx = fixtures.setup_packed_event(requested_lbs=380, intake_lbs=1000)
    report = _poundage_report(api, ctx["cycle"]["id"])
    assert report["total_planned_lbs"] == 380.00, \
        f"planned should count the PACKED event's planned_lbs, got {report['total_planned_lbs']}"
    assert report["total_distributed_lbs"] == 0.00, \
        f"distributed should be 0 (no FINALIZED event), got {report['total_distributed_lbs']}"
    assert report["shrinkage_lbs"] == 380.00, \
        f"shrinkage = planned - distributed = 380, got {report['shrinkage_lbs']}"


def test_poundage_report_divergence_via_cycle_nested_endpoint(api):
    """PRD §3.9: "The distributed total, total_distributed_lbs, is chronological:
    the sum of actual_distributed_lbs over only the cycle's FINALIZED events"
    PRD §3.9: "The planned total, total_planned_lbs, is forward-looking: the sum
    of planned_lbs over every distribution event for this cycle's orders that has
    reached PACKED or FINALIZED, including events that are packed but not yet
    finalized."

    Design: Difficulty/dual_variant_calc/poundage_ledger_planned_vs_distributed_diverge
    """
    ctx = fixtures.setup_packed_event(requested_lbs=380, intake_lbs=1000)
    # Read via the cycle-nested 0-or-1 array endpoint (PRD §4).
    resp = api.get_cycle_poundage_report(ctx["cycle"]["id"], MGR)
    data, _meta = validate_paginated(resp)
    assert len(data) == 1, f"poundage report should be a 0-or-1 array of size 1, got {len(data)}"
    report = data[0]
    assert report["total_planned_lbs"] == 380.00
    assert report["total_distributed_lbs"] == 0.00
    assert report["shrinkage_lbs"] == 380.00


def test_pack_planned_lbs_uses_reserved_not_requested_on_short_line(api):
    """PRD §3.7: "its planned_lbs is set to the forward-looking planned poundage —
    the sum of reserved_lbs over the order's lines whose line_status is RESERVED at
    pack time, using what the FEFO run actually secured rather than what was
    requested, so a SHORT line contributes only its reserved amount and an
    already-PACKED line is excluded."
    PRD §3.5: "its line_status becomes RESERVED when its full request is met or
    SHORT when only part of it could be covered."

    Design: Difficulty/dual_variant_calc/event_planned_uses_reserved_not_requested_on_short_line
    """
    # Lot of 100 lbs; line requests 300 -> reserves 100, SHORT.
    unit = fixtures.create_cold_storage_unit(temp_zone="REFRIGERATED", capacity_lbs=5000)
    lot = fixtures.create_inventory_lot(unit["id"], food_category="PRODUCE",
                                        intake_lbs=100,
                                        expiration_date="2026-07-01T00:00:00.000Z")
    agency = fixtures.create_agency()
    cycle = fixtures.create_open_cycle()
    order = fixtures.submit_order(
        agency["id"], cycle["id"],
        lines=[{"food_category": "PRODUCE", "requested_lbs": 300}],
    )
    get_success_data(api.approve_agency_order(
        order["id"], {"expected_lot_version": lot["version"]}, MGR))
    hh = fixtures.certify_household(fixtures.create_household(agency["id"])["id"])
    event = get_success_data(api.create_distribution_event(
        factories.create_distribution_event_payload(order["id"], hh["id"]),
        make_agency_coordinator_headers(agency["id"])))

    packed = validate_success(api.pack_distribution_event(
        event["id"], make_agency_coordinator_headers(agency["id"])))
    assert packed["planned_lbs"] == 100.00, \
        f"planned should equal reserved 100, not requested 300, got {packed['planned_lbs']}"

    lines, _ = validate_paginated(api.list_order_lines(order["id"], MGR))
    assert len(lines) == 1
    assert lines[0]["reserved_lbs"] == 100.00, f"reserved_lbs should be 100, got {lines[0]['reserved_lbs']}"
    assert lines[0]["line_status"] == "SHORT", f"line should be SHORT, got {lines[0]['line_status']}"


def test_pack_short_line_reserved_lbs_recorded_on_line(api):
    """PRD §3.5: "its line_status becomes RESERVED when its full request is met or
    SHORT when only part of it could be covered."
    PRD §3.5: "As poundage is taken, the line's reserved_lbs accumulates"

    Design: Difficulty/dual_variant_calc/event_planned_uses_reserved_not_requested_on_short_line
    """
    unit = fixtures.create_cold_storage_unit(temp_zone="REFRIGERATED", capacity_lbs=5000)
    lot = fixtures.create_inventory_lot(unit["id"], food_category="PRODUCE",
                                        intake_lbs=100,
                                        expiration_date="2026-07-01T00:00:00.000Z")
    agency = fixtures.create_agency()
    cycle = fixtures.create_open_cycle()
    order = fixtures.submit_order(
        agency["id"], cycle["id"],
        lines=[{"food_category": "PRODUCE", "requested_lbs": 300}],
    )
    approved = validate_success(api.approve_agency_order(
        order["id"], {"expected_lot_version": lot["version"]}, MGR))
    assert approved["approved_lbs"] == 100.00, \
        f"order approved_lbs should equal the 100 reserved, got {approved['approved_lbs']}"
    lines, _ = validate_paginated(api.list_order_lines(order["id"], MGR))
    assert lines[0]["reserved_lbs"] == 100.00
    assert lines[0]["line_status"] == "SHORT"


def test_tefap_split_rounds_per_line_then_sums(api):
    """PRD §3.8: "if the line's reserved lot has source_type TEFAP, the amount
    allocated to that line is added to the event's tefap_lbs."
    PRD §3.8: "The attribution is a FEFO waterfall over the order's PACKED lines,
    walked in ascending order of their reserved lot's expiration_date"
    PRD §3.8: "Each line's allocation is rounded to two decimal places before being
    summed into tefap_lbs — the rounding is applied per line and then totaled,
    never the other way around."

    Design: Difficulty/combinatorial_formula/tefap_split_round_per_line_then_sum
    """
    # DONATION PRODUCE 100 (exp earlier) then TEFAP DRY_GOODS 50 (exp later).
    ctx = fixtures.setup_two_line_donation_tefap_order(donation_lbs=100, tefap_lbs=50)
    finalized = validate_success(api.finalize_distribution_event(
        ctx["event"]["id"], {"actual_distributed_lbs": 150},
        make_agency_coordinator_headers(ctx["agency"]["id"])))
    # FEFO waterfall: 100 to DONATION (earlier exp), then 50 to TEFAP line.
    assert finalized["tefap_lbs"] == 50.00, \
        f"tefap_lbs should be the 50 attributed to the TEFAP line, got {finalized['tefap_lbs']}"
    assert finalized["status"] == "FINALIZED"


def test_tefap_split_waterfall_stops_before_tefap_line_when_exhausted(api):
    """PRD §3.8: "The attribution is a FEFO waterfall over the order's PACKED lines,
    walked in ascending order of their reserved lot's expiration_date"
    PRD §3.8: "The walk stops once the remaining amount to attribute reaches 0."
    PRD §3.8: "Non-TEFAP lines still consume their share of the waterfall but
    contribute nothing to tefap_lbs."

    Design: Difficulty/combinatorial_formula/tefap_split_round_per_line_then_sum
    """
    # Finalize at exactly 100: the FEFO-earlier DONATION line absorbs all 100, the
    # waterfall reaches 0 before the later TEFAP line, so tefap_lbs is 0.
    ctx = fixtures.setup_two_line_donation_tefap_order(donation_lbs=100, tefap_lbs=50)
    finalized = validate_success(api.finalize_distribution_event(
        ctx["event"]["id"], {"actual_distributed_lbs": 100},
        make_agency_coordinator_headers(ctx["agency"]["id"])))
    assert finalized["tefap_lbs"] == 0.00, \
        f"DONATION line absorbs all 100; TEFAP line gets 0, got {finalized['tefap_lbs']}"
    assert finalized["status"] == "FINALIZED"


def test_tefap_split_partial_distribution_waterfall(api):
    """PRD §3.8: "Starting with the full actual_distributed_lbs as the amount
    remaining to attribute, the system visits each line in turn and allocates to it
    the smaller of the amount still remaining and that line's reserved_lbs; if the
    line's reserved lot has source_type TEFAP, the amount allocated to that line is
    added to the event's tefap_lbs."
    PRD §3.8: "The walk stops once the remaining amount to attribute reaches 0."

    Design: Corner/calculations/tefap_split_partial_distribution_waterfall_correct
    """
    # Finalize at 120 (< planned 150): 100 to DONATION (earlier), 20 to TEFAP.
    ctx = fixtures.setup_two_line_donation_tefap_order(donation_lbs=100, tefap_lbs=50)
    finalized = validate_success(api.finalize_distribution_event(
        ctx["event"]["id"], {"actual_distributed_lbs": 120},
        make_agency_coordinator_headers(ctx["agency"]["id"])))
    assert finalized["tefap_lbs"] == 20.00, \
        f"100 to DONATION then 20 to TEFAP -> tefap_lbs 20, got {finalized['tefap_lbs']}"


def test_fair_share_cap_floor_of_weighted_pool_share_at_cap(api):
    """PRD §3.4: "An agency's cap in whole pounds is the cycle's total_pool_lbs
    multiplied by the agency's share — its fair_share_weight divided by the cycle's
    frozen total_fair_share_weight — with that product rounded down to a whole
    number of pounds."
    PRD §3.4: "an order landing exactly at the cap is allowed."

    Design: Difficulty/combinatorial_formula/fair_share_cap_floor_of_weighted_pool_share
    """
    # A weight 3, B weight 1; pool 10000 -> A cap = floor(10000*3/4) = 7500.
    agency_a = fixtures.create_agency(name="Agency A", service_area="County-A", fair_share_weight=3)
    fixtures.create_agency(name="Agency B", service_area="County-B", fair_share_weight=1)
    unit = fixtures.create_cold_storage_unit(temp_zone="REFRIGERATED", capacity_lbs=20000)
    lot = fixtures.create_inventory_lot(unit["id"], food_category="PRODUCE",
                                        intake_lbs=8000,
                                        expiration_date="2026-09-01T00:00:00.000Z")
    cycle = fixtures.create_open_cycle(total_pool_lbs=10000)
    order = fixtures.submit_order(
        agency_a["id"], cycle["id"],
        lines=[{"food_category": "PRODUCE", "requested_lbs": 7500}],
    )
    approved = validate_success(api.approve_agency_order(
        order["id"], {"expected_lot_version": lot["version"]}, MGR))
    assert approved["status"] == "APPROVED", \
        f"7500 == cap should approve, got status {approved['status']}"
    assert approved["approved_lbs"] == 7500.00, \
        f"full reservation 7500 from the 8000-lb lot, got {approved['approved_lbs']}"


def test_fair_share_cap_total_weight_frozen_at_open(api):
    """PRD §3.4: "the open transition moves it from DRAFT to OPEN, freezes
    total_fair_share_weight as the sum of fair_share_weight over every agency that
    is ACTIVE at that instant"
    PRD §3.4: "with that product rounded down to a whole number of pounds."

    Design: Difficulty/combinatorial_formula/fair_share_cap_floor_of_weighted_pool_share
    """
    fixtures.create_agency(name="Agency A", service_area="County-A", fair_share_weight=3)
    fixtures.create_agency(name="Agency B", service_area="County-B", fair_share_weight=1)
    cycle = fixtures.create_open_cycle(total_pool_lbs=10000)
    assert cycle["total_fair_share_weight"] == 4, \
        f"weight frozen at 3+1=4 at open, got {cycle['total_fair_share_weight']}"
