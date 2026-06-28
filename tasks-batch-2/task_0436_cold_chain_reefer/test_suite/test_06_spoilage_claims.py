"""Spoilage claim filing, payout snapshot, settlement, and adjudication branches.

Translates difficulty instances (dual_variant_calc spoilage payout, combinatorial
spoilage rounding, non_linear_state_machine claim branch, cross_entity_state_dependency
claim posture) and corner calculation / validation instances.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    ApiErrorId,
    fixtures as fx,
    factories as F,
)

CO = fx.TEST_USERS["compliance_officer_headers"]


def _delivered_frozen_with_lots(api, temp_readings, lots, carrier_op, shipper_op,
                                liability_cap_cents=None):
    """Build a DELIVERED FROZEN FOOD shipment with the given TEMP series and lots.

    `temp_readings` is a list of (offset_min, temp_c) applied to the one compartment.
    `lots` is a list of (sku, pallet_count, declared_value_cents).
    Returns the context dict (carrier, carrier_headers, unit, shipment, compartments).
    """
    ctx = fx.setup_delivered_with_temp_series(
        temp_readings=temp_readings, num_compartments=1, lots=lots, cargo_class="FOOD",
        lane_kind="FROZEN", liability_cap_cents=liability_cap_cents, carrier_op=carrier_op,
        shipper_op=shipper_op,
    )
    return ctx


def test_spoilage_payout_eligible_snapshot_uncapped(api):
    """PRD §3.8: "The lots' per-lot payouts are then summed in that pinned walk order to give `claimed_value_cents`."

    Design: Difficulty/dual_variant_calc/spoilage_payout_eligible_vs_settled_diverge_on_claim
    """
    # FROZEN tol 30; (0,-10),(60,-20) -> deg 300 -> TOTAL_LOSS factor 1.0. Lots
    # 1000000 + 750001 = 1750001 eligible (pre-cap).
    ctx = _delivered_frozen_with_lots(
        api, [(0, -10), (60, -20)],
        [("BEEF-A", 4, 1000000), ("BEEF-B", 4, 750001)],
        carrier_op="carrier-op-2", shipper_op="shipper-op-2", liability_cap_cents=1500000,
    )
    claim = get_success_data(api.create_claim(F.claim_payload(ctx["shipment"]["id"]),
                                              fx.make_shipper_headers("shipper-op-2")))
    assert claim["claimed_value_cents"] == 1750001, \
        f"eligible (pre-cap) claimed_value_cents must be 1750001, got {claim['claimed_value_cents']}"


def test_spoilage_payout_settled_applies_liability_cap(api):
    """PRD §3.8: "on approval the platform sets `approved_payout_cents` to the lesser of the snapshotted `claimed_value_cents` and the carrier's `liability_cap_cents` (the cap can only shrink the figure, never raise it)".

    Design: Difficulty/dual_variant_calc/spoilage_payout_eligible_vs_settled_diverge_on_claim
    """
    # eligible 1750001, cap 1500000 -> settled = min = 1500000, != eligible.
    ctx = _delivered_frozen_with_lots(
        api, [(0, -10), (60, -20)],
        [("BEEF-A", 4, 1000000), ("BEEF-B", 4, 750001)],
        carrier_op="carrier-op-2b", shipper_op="shipper-op-2b", liability_cap_cents=1500000,
    )
    claim = get_success_data(api.create_claim(F.claim_payload(ctx["shipment"]["id"]),
                                              fx.make_shipper_headers("shipper-op-2b")))
    get_success_data(api.review_claim(claim["id"], CO))
    approved = validate_success(api.approve_claim(claim["id"], CO))
    assert approved["claimed_value_cents"] == 1750001
    assert approved["approved_payout_cents"] == 1500000, \
        "approved payout must be capped to liability_cap_cents 1500000"
    assert approved["approved_payout_cents"] != approved["claimed_value_cents"], \
        "carrier cap must bind the SETTLED figure below the eligible figure"


def test_spoilage_payout_rounds_per_lot_then_sums(api):
    """PRD §3.8: "Each lot's eligible payout is its `declared_value_cents` multiplied by its factor, rounded half up to whole cents per lot. The lots' per-lot payouts are then summed in that pinned walk order to give `claimed_value_cents`. Rounding is applied per lot before the summation, not to the total."

    Design: Difficulty/combinatorial_formula/spoilage_payout_round_per_lot_then_sum_mode_b
    """
    # FROZEN tol 30; (0,-20),(60,-12),(80,-20) -> deg 60 (60->80 dur 20 * mag 3) ->
    # PARTIAL factor 0.5. Lots 333333*0.5=166666.5 -> 166667; 100001*0.5=50000.5 ->
    # 50001. Sum 216668 (NOT sum-then-round 216667).
    ctx = _delivered_frozen_with_lots(
        api, [(0, -20), (60, -12), (80, -20)],
        [("LOT-X", 2, 333333), ("LOT-Y", 2, 100001)],
        carrier_op="carrier-op-4", shipper_op="shipper-op-4", liability_cap_cents=100000000,
    )
    comp = ctx["compartments"][0]
    final_comp = validate_success(api.get_compartment(comp["id"], ctx["carrier_headers"]))
    assert final_comp["degree_minutes_out"] == pytest.approx(60, abs=0.01)
    claim = get_success_data(api.create_claim(F.claim_payload(ctx["shipment"]["id"]),
                                              fx.make_shipper_headers("shipper-op-4")))
    assert claim["claimed_value_cents"] == 216668, \
        f"round-per-lot-then-sum must give 216668, not 216667; got {claim['claimed_value_cents']}"


def test_spoilage_payout_per_lot_round_half_up_single_lot(api):
    """PRD §3.8: "Each lot's eligible payout is its `declared_value_cents` multiplied by its factor, rounded half up to whole cents per lot."
    PRD §2.10: "the rounding method is round-half-up to whole cents."

    Design: Difficulty/combinatorial_formula/spoilage_payout_round_per_lot_then_sum_mode_b
    """
    # PARTIAL deg 60 -> factor 0.5. Single lot 100001 * 0.5 = 50000.5 -> round_half_up
    # = 50001.
    ctx = _delivered_frozen_with_lots(
        api, [(0, -20), (60, -12), (80, -20)],
        [("ODD-LOT", 1, 100001)],
        carrier_op="carrier-op-4b", shipper_op="shipper-op-4b", liability_cap_cents=100000000,
    )
    claim = get_success_data(api.create_claim(F.claim_payload(ctx["shipment"]["id"]),
                                              fx.make_shipper_headers("shipper-op-4b")))
    assert claim["claimed_value_cents"] == 50001, \
        f"per-lot round_half_up of 50000.5 must be 50001, got {claim['claimed_value_cents']}"


def test_claim_approve_branch_sets_status_and_capped_payout(api):
    """PRD §3.8: "on approval the platform sets `approved_payout_cents` to the lesser of the snapshotted `claimed_value_cents` and the carrier's `liability_cap_cents` (the cap can only shrink the figure, never raise it), moves the claim `UNDER_REVIEW → APPROVED`".

    Design: Difficulty/non_linear_state_machine/spoilage_claim_branch_review_to_approved_or_denied
    """
    # COMPROMISED (deg 600, factor 1.0), single lot 500000, default cap 5,000,000 (no
    # bind) -> approved payout == eligible 500000. The approve fork sets a non-zero
    # payout, diverging from the deny fork's 0.
    ctx = _delivered_frozen_with_lots(
        api, [(0, -5), (60, -20)],
        [("LOT-Z", 2, 500000)],
        carrier_op="carrier-op-5b", shipper_op="shipper-op-5b",
    )
    claim = get_success_data(api.create_claim(F.claim_payload(ctx["shipment"]["id"]),
                                              fx.make_shipper_headers("shipper-op-5b")))
    get_success_data(api.review_claim(claim["id"], CO))
    approved = validate_success(api.approve_claim(claim["id"], CO))
    assert approved["status"] == "APPROVED"
    assert approved["approved_payout_cents"] == 500000, \
        "approve fork must set approved_payout_cents = min(eligible 500000, cap 5,000,000)"


def test_claim_deny_branch_status_denied_and_payout_zero(api):
    """PRD §3.8: "Denial moves the claim `UNDER_REVIEW → DENIED` and leaves `approved_payout_cents` at 0."

    Design: Difficulty/non_linear_state_machine/spoilage_claim_branch_review_to_approved_or_denied
    """
    # COMPROMISED deg 600 so the shipment is claimable; we deny and confirm the deny
    # branch produces DENIED with a 0 payout. (PRD §3.2/§3.8 leave the post-filing lot
    # spoilage_status under-specified for the deny path, so it is not asserted here.)
    ctx = _delivered_frozen_with_lots(
        api, [(0, -5), (60, -20)],
        [("LOT-Z", 2, 500000)],
        carrier_op="carrier-op-5", shipper_op="shipper-op-5",
    )
    claim = get_success_data(api.create_claim(F.claim_payload(ctx["shipment"]["id"]),
                                              fx.make_shipper_headers("shipper-op-5")))
    get_success_data(api.review_claim(claim["id"], CO))
    denied = validate_success(api.deny_claim(claim["id"], CO))
    assert denied["status"] == "DENIED"
    assert denied["approved_payout_cents"] == 0


def test_claim_approval_succeeds_on_at_risk_posture(api):
    """PRD §3.8: "Approval is permitted only when the related shipment's `load_integrity_posture` is `AT_RISK` or `COMPROMISED".

    Design: Difficulty/cross_entity_state_dependency/claim_approval_depends_on_shipment_posture
    """
    # (0,-12),(20,-20),(60,-20) -> 0->20 dur 20 * mag 3 = 60 -> PARTIAL -> AT_RISK.
    ctx = _delivered_frozen_with_lots(
        api, [(0, -12), (20, -20), (60, -20)],
        [("LOT-P", 1, 400000)],
        carrier_op="carrier-op-14", shipper_op="shipper-op-14",
    )
    delivered = validate_success(api.get_shipment(ctx["shipment"]["id"], ctx["carrier_headers"]))
    assert delivered["load_integrity_posture"] == "AT_RISK"
    claim = get_success_data(api.create_claim(F.claim_payload(ctx["shipment"]["id"]),
                                              fx.make_shipper_headers("shipper-op-14")))
    get_success_data(api.review_claim(claim["id"], CO))
    approved = validate_success(api.approve_claim(claim["id"], CO))
    assert approved["status"] == "APPROVED", \
        "approve gate must pass when the related shipment posture is AT_RISK"


def test_claim_approval_on_at_risk_sets_lot_spoilage_status_impaired(api):
    """PRD §3.8: "Approval is permitted only when the related shipment's `load_integrity_posture` is `AT_RISK` or `COMPROMISED ... and sets each impaired or spoiled lot's `spoilage_status` accordingly — `IMPAIRED` for a partially-impaired lot and `SPOILED` for a total-loss lot."

    Design: Difficulty/cross_entity_state_dependency/claim_approval_depends_on_shipment_posture
    """
    # PARTIAL deg 60 -> AT_RISK posture, lot factor 0.5 (impaired). Approve must set the
    # lot's spoilage_status to IMPAIRED (the approve gate read the AT_RISK posture).
    ctx = _delivered_frozen_with_lots(
        api, [(0, -12), (20, -20), (60, -20)],
        [("LOT-P", 1, 400000)],
        carrier_op="carrier-op-14b", shipper_op="shipper-op-14b",
    )
    lots, _ = validate_paginated(
        api.list_lots(ctx["carrier_headers"], params={"compartment_id": ctx["compartments"][0]["id"]})
    )
    the_lot = lots[0]
    claim = get_success_data(api.create_claim(F.claim_payload(ctx["shipment"]["id"]),
                                              fx.make_shipper_headers("shipper-op-14b")))
    get_success_data(api.review_claim(claim["id"], CO))
    validate_success(api.approve_claim(claim["id"], CO))
    lot_after = validate_success(api.get_lot(the_lot["id"], ctx["carrier_headers"]))
    assert lot_after["spoilage_status"] == "IMPAIRED", \
        "approve on an AT_RISK shipment must set the partial lot's spoilage_status to IMPAIRED"


def test_file_claim_on_intact_shipment_returns_not_eligible(api):
    """PRD §3.8: "A claim that targets a shipment that is not delivered, or whose posture is `INTACT`, or that would be a second concurrent open claim, is rejected with `ERR_CLAIM_NOT_ELIGIBLE`."

    Design: Corner/validations/file_claim_on_intact_shipment_returns_not_eligible
    """
    # In-band the whole trip -> INTACT.
    ctx = _delivered_frozen_with_lots(
        api, [(0, -20), (60, -18)],
        [("OK-LOT", 1, 100000)],
        carrier_op="carrier-c19", shipper_op="shipper-c19",
    )
    delivered = validate_success(api.get_shipment(ctx["shipment"]["id"], ctx["carrier_headers"]))
    assert delivered["load_integrity_posture"] == "INTACT"
    resp = api.create_claim(F.claim_payload(ctx["shipment"]["id"]),
                            fx.make_shipper_headers("shipper-c19"))
    validate_error(resp, ApiErrorId.ERR_CLAIM_NOT_ELIGIBLE.value)


def test_integrity_report_score_within_door_free_allowance(api):
    """PRD §3.7: "For door activity, 5 points are deducted for each door-open event beyond a free allowance of 2 — that is, the deduction applies to the number of `door_open_events` minus 2 when that difference is positive, and is zero otherwise."
    PRD §3.7: "The shipment's `load_integrity_score` is the minimum of the per-compartment scores — the worst compartment — rounded half up to a whole integer."

    Design: Corner/calculations/integrity_report_score_within_door_free_allowance
    """
    # Precool ok, in-band TEMP series (deg 0), 1 door-open (<= free 2) -> score 100.
    fx.set_clock("2026-03-01T00:00:00Z")
    ctx = fx.setup_in_transit(num_compartments=1, carrier_op="carrier-c15",
                              shipper_op="shipper-c15", clock="2026-03-01T00:00:00Z")
    comp = ctx["compartments"][0]
    fx.add_temp_readings(comp["id"], [(0, -20)])
    get_success_data(api.create_reading(comp["id"], F.create_reading_payload("DOOR_OPEN", 30), fx.DRIVER))
    fx.add_temp_readings(comp["id"], [(60, -20)])
    validate_success(api.deliver_shipment(ctx["shipment"]["id"], fx.DRIVER))
    report = validate_success(api.get_integrity_report(ctx["shipment"]["id"],
                                                       fx.make_shipper_headers("shipper-c15")))
    assert report["load_integrity_score"] == 100, \
        f"intact shipment with 1 door (<= free 2) and zero degree-minutes must score 100, got {report['load_integrity_score']}"
    assert report["load_integrity_posture"] == "INTACT"
