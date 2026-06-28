"""Claim settlement arithmetic: replacement-cost vs actual-cash-value by
occupancy, the round-per-bucket-then-sum rounding order, the ICC cap, and the
below-deductible floor.

Covers difficulty queue A (dual_variant_calc claim instance, combinatorial_formula
claim instance) and corner queue B (calculations, endpoints sections for claims).
"""
from test_helpers import (
    validate_success,
    setup_active_policy,
    file_claim,
    open_review,
    file_proof_of_loss,
    accept_proof_of_loss,
    approve_claim,
    assert_claim,
    make_policy_holder_headers,
)


def _build_approved_claim(api, owner_id, flood_zone, occupancy, has_active_mortgage,
                          claim_overrides, proof_overrides):
    """Local helper: ACTIVE lender RR2 policy (clock 2026-03-01) -> claim ->
    open-review -> proof -> accept -> approve. Returns the approved claim."""
    community, prop, active = setup_active_policy(
        bind_clock="2026-03-01T00:00:00Z", owner_id=owner_id,
        flood_zone=flood_zone, occupancy=occupancy,
        base_flood_elevation_ft=8.0 if flood_zone == "AE" else 10.0,
        lowest_floor_elevation_ft=10.0 if flood_zone == "AE" else 11.0,
        has_active_mortgage=has_active_mortgage, crs_class=5 if flood_zone == "AE" else 10,
        is_lender_required=True,
        building_coverage=250000, contents_coverage=100000,
        building_deductible=2000, contents_deductible=1000,
        quote_as_underwriter=True,
    )
    claim = file_claim(active["id"], owner_id, "2026-04-10T00:00:00Z", **claim_overrides)
    claim = open_review(claim["id"])
    proof = file_proof_of_loss(claim["id"], owner_id, **proof_overrides)
    accept_proof_of_loss(proof["id"])
    return approve_claim(claim["id"], claim["version"])


def test_settlement_primary_residence_uses_replacement_cost(api):
    """PRD §3.10: "for a `PRIMARY_RESIDENCE` the building is settled at full
    replacement cost with no depreciation, so the adjusted building loss equals
    the reported `building_loss`"
    PRD §3.10: "The `building_payable` is the smaller of the adjusted building
    loss and the `building_coverage`, minus the `building_deductible`, with the
    result floored at 0."

    Design: Difficulty/dual_variant_calc/claim_settlement_rcv_primary_vs_acv_nonprimary
    """
    approved = _build_approved_claim(
        api, owner_id="holder-2", flood_zone="AE", occupancy="PRIMARY_RESIDENCE",
        has_active_mortgage=True,
        claim_overrides={
            "building_loss": 120000, "contents_loss": 30000,
            "depreciation_pct": 0.20, "substantial_damage": True,
            "icc_eligible_cost": 40000,
        },
        proof_overrides={"documented_building_loss": 120000, "documented_contents_loss": 30000},
    )
    assert_claim(approved)
    assert approved["building_payable"] == 118000, approved["building_payable"]
    assert approved["contents_payable"] == 23000, approved["contents_payable"]
    assert approved["icc_payable"] == 30000, approved["icc_payable"]
    assert approved["settlement_total"] == 171000, approved["settlement_total"]


def test_settlement_non_primary_building_depreciated_to_acv(api):
    """PRD §3.10: "for a `NON_PRIMARY` structure the building is depreciated to
    actual cash value, so the adjusted building loss is the reported
    `building_loss` multiplied by one minus `depreciation_pct`, rounded to whole
    dollars — which yields a strictly lower building figure for the same loss."
    PRD §3.10: "Contents are always settled at actual cash value: the adjusted
    contents figure is the reported `contents_loss` multiplied by one minus
    `depreciation_pct`, rounded to whole dollars."

    Design: Difficulty/dual_variant_calc/claim_settlement_rcv_primary_vs_acv_nonprimary
    """
    approved = _build_approved_claim(
        api, owner_id="holder-4", flood_zone="AE", occupancy="NON_PRIMARY",
        has_active_mortgage=True,
        claim_overrides={
            "building_loss": 120000, "contents_loss": 30000,
            "depreciation_pct": 0.20, "substantial_damage": False,
            "icc_eligible_cost": 0,
        },
        proof_overrides={"documented_building_loss": 120000, "documented_contents_loss": 30000},
    )
    assert approved["building_payable"] == 94000, approved["building_payable"]
    assert approved["contents_payable"] == 23000, approved["contents_payable"]
    assert approved["icc_payable"] == 0, approved["icc_payable"]
    assert approved["settlement_total"] == 117000, approved["settlement_total"]


def test_settlement_rounds_each_bucket_before_deductible(api):
    """PRD §3.10: "The settlement is computed building-and-contents separately,
    each net of its own deductible, with each bucket rounded before its
    deductible is subtracted."

    Design: Difficulty/combinatorial_formula/claim_settlement_round_per_bucket_then_sum
    """
    approved = _build_approved_claim(
        api, owner_id="holder-4b", flood_zone="AE", occupancy="NON_PRIMARY",
        has_active_mortgage=True,
        claim_overrides={
            "building_loss": 120000, "contents_loss": 30000,
            "depreciation_pct": 0.20, "substantial_damage": False,
            "icc_eligible_cost": 0,
        },
        proof_overrides={"documented_building_loss": 120000, "documented_contents_loss": 30000},
    )
    # contents 30000 * 0.80 = 24000 (rounded), then net 1000 deductible -> 23000
    assert approved["contents_payable"] == 23000, approved["contents_payable"]
    assert approved["building_payable"] == 94000, approved["building_payable"]
    assert approved["settlement_total"] == 117000, approved["settlement_total"]


def test_icc_payable_capped_at_30000(api):
    """PRD §3.10: "When `substantial_damage` is true, the `icc_payable` is the
    smaller of the reported `icc_eligible_cost` and the ICC coverage cap of 30000
    dollars"

    Design: Corner/calculations/icc_payable_capped_at_30000
    """
    approved = _build_approved_claim(
        api, owner_id="h-ic", flood_zone="X", occupancy="PRIMARY_RESIDENCE",
        has_active_mortgage=False,
        claim_overrides={
            "building_loss": 0, "contents_loss": 0,
            "substantial_damage": True, "icc_eligible_cost": 40000,
        },
        proof_overrides={"documented_building_loss": 0, "documented_contents_loss": 0},
    )
    assert approved["icc_payable"] == 30000, approved["icc_payable"]
    assert approved["settlement_total"] == 30000, approved["settlement_total"]


def test_loss_below_deductible_yields_zero_payable(api):
    """PRD §3.10: "The `building_payable` is the smaller of the adjusted building
    loss and the `building_coverage`, minus the `building_deductible`, with the
    result floored at 0. The `contents_payable` is the smaller of the adjusted
    contents figure and the `contents_coverage`, minus the `contents_deductible`,
    with the result floored at 0."

    Design: Corner/calculations/claim_loss_below_deductible_yields_zero_payable
    """
    approved = _build_approved_claim(
        api, owner_id="h-bd", flood_zone="X", occupancy="PRIMARY_RESIDENCE",
        has_active_mortgage=False,
        claim_overrides={"building_loss": 1500, "contents_loss": 500},
        proof_overrides={"documented_building_loss": 1500, "documented_contents_loss": 500},
    )
    assert approved["building_payable"] == 0, approved["building_payable"]
    assert approved["contents_payable"] == 0, approved["contents_payable"]
    assert approved["settlement_total"] == 0, approved["settlement_total"]


def test_get_approved_claim_returns_computed_settlement(api):
    """PRD §3.10: "The `settlement_total` is the sum of `building_payable`,
    `contents_payable`, and `icc_payable`."

    Design: Corner/endpoints/get_claim_computed_settlement_read
    """
    community, prop, active = setup_active_policy(
        bind_clock="2026-03-01T00:00:00Z", owner_id="h-rd",
        flood_zone="X", base_flood_elevation_ft=10.0, lowest_floor_elevation_ft=11.0,
        crs_class=10, is_lender_required=True,
        building_coverage=100000, contents_coverage=40000, building_deductible=2000,
        quote_as_underwriter=True,
    )
    claim = file_claim(active["id"], "h-rd", "2026-04-10T00:00:00Z", building_loss=5000)
    claim = open_review(claim["id"])
    proof = file_proof_of_loss(claim["id"], "h-rd", documented_building_loss=5000)
    accept_proof_of_loss(proof["id"])
    approve_claim(claim["id"], claim["version"])

    fetched = validate_success(
        api.get_claim(claim["id"], make_policy_holder_headers("h-rd"))
    )
    assert fetched["status"] == "APPROVED", fetched["status"]
    assert fetched["settlement_total"] == 3000, fetched["settlement_total"]
