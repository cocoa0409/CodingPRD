"""Herd-health protocol charges, their cost split and the review machine."""

from test_helpers import (
    ApiErrorId,
    assert_health_treatment,
    assert_settlement_waterfall,
    draft_settlement,
    make_cattle_owner_headers,
    make_grazier_headers,
    record_treatment,
    review_treatment_as_grazier,
    review_treatment_as_owner,
    set_logical_clock,
    setup_north_bench_lot_on_feed,
    treatment_payload,
    validate_error,
    validate_success,
    weigh_out_lot,
)

ROUTINE_A = {
    "protocol_code": "BRD-A", "classification": "ROUTINE_PROTOCOL",
    "treatment_date": "2026-08-20", "withdrawal_days": 21, "head_treated": 12,
    "drug_cost_cents": 1250, "labor_cost_cents": 375,
}
ROUTINE_B = {
    "protocol_code": "BRD-A", "classification": "ROUTINE_PROTOCOL",
    "treatment_date": "2026-09-02", "withdrawal_days": 21, "head_treated": 9,
    "drug_cost_cents": 900, "labor_cost_cents": 350,
}
THERAPEUTIC = {
    "protocol_code": "PINK-EYE", "classification": "THERAPEUTIC",
    "treatment_date": "2026-09-20", "withdrawal_days": 14, "head_treated": 4,
    "drug_cost_cents": 4500, "labor_cost_cents": 1200,
}


def test_each_treatment_row_is_rounded_on_the_owner_side_when_it_is_recorded(api):
    """PRD 3.5: "The system computes `total_cost_cents` as drug cost plus labor cost,
    then computes `owner_share_cents` as the total multiplied by the owner's percentage
    divided by 100 and rounded half up to a whole cent. `grazier_share_cents` is then
    the total less the owner's share — meaning the owner's side is the rounded side and
    the grazier absorbs the residual cent. A recorded treatment lands in `status`
    `RECORDED`."
    PRD 3.5: "A `ROUTINE_PROTOCOL` treatment — the branding-shot, the pour-on, the
    things every calf gets — is split per the contract: the owner's share is 100 percent
    less the contract's `treatment_cost_split_pct`."

    Design: Difficulty/combinatorial_formula/treatment_charge_round_per_row_then_sum_mode_b
    """
    world = setup_north_bench_lot_on_feed()

    first = validate_success(
        api.create_treatment(
            world.lot_id, treatment_payload(**ROUTINE_A),
            make_grazier_headers(world.grazier_id),
        ),
        201,
    )
    assert_health_treatment(first)
    assert first["total_cost_cents"] == 1625
    assert first["owner_share_cents"] == 1089
    assert first["grazier_share_cents"] == 536
    assert first["status"] == "RECORDED"

    second = validate_success(
        api.create_treatment(
            world.lot_id, treatment_payload(**ROUTINE_B),
            make_grazier_headers(world.grazier_id),
        ),
        201,
    )
    assert second["total_cost_cents"] == 1250
    assert second["owner_share_cents"] == 838
    assert second["grazier_share_cents"] == 412

    third = validate_success(
        api.create_treatment(
            world.lot_id, treatment_payload(**THERAPEUTIC),
            make_grazier_headers(world.grazier_id),
        ),
        201,
    )
    assert third["total_cost_cents"] == 5700
    assert third["owner_share_cents"] == 5700, "A therapeutic charge is the owner's in full"
    assert third["grazier_share_cents"] == 0


def test_the_settlement_sums_the_already_rounded_owner_shares(api):
    """PRD 3.5: "That rounding happens once per treatment row, and the settlement later
    sums the already-rounded owner shares rather than re-deriving them from a summed
    total. The difference is real: on a contract splitting routine costs at 33 percent,
    three rows of 1625, 1250 and 5700 cents — the first two `ROUTINE_PROTOCOL`, the
    third `THERAPEUTIC` — produce owner shares of 1089, 838 and 5700, totalling 7627
    cents. Summing the routine rows first and rounding once would give 7626, one cent
    low, and that answer is wrong."
    PRD 3.9: "After the base charge, `treatment_charge_cents` is the sum of the owner
    shares of the lot's `APPROVED` treatments, each already rounded when it was
    recorded, as §3.5 requires."

    Design: Difficulty/combinatorial_formula/treatment_charge_round_per_row_then_sum_mode_b
    """
    world = setup_north_bench_lot_on_feed()
    for terms in (ROUTINE_A, ROUTINE_B, THERAPEUTIC):
        row = record_treatment(world.lot_id, world.grazier_id, **terms)
        review_treatment_as_owner(row["id"], world.owner_id, "APPROVE")

    weigh_out_lot(world.lot_id, world.grazier_id)
    set_logical_clock("2026-11-12T00:00:00Z")
    settlement = draft_settlement(world.contract_id, world.lot_id, world.grazier_id)

    assert settlement["treatment_charge_cents"] == 7627, (
        "Summing the routine rows before rounding would have produced 7626"
    )
    assert settlement["shrunk_gain_lbs"] == 13456
    assert settlement["base_charge_cents"] == 1143760
    assert settlement["subtotal_cents"] == 1151387
    assert settlement["volume_rebate_cents"] == 11514
    assert settlement["total_due_cents"] == 1139873
    assert_settlement_waterfall(settlement)


def test_a_preventive_emergency_treatment_is_wholly_the_graziers_cost(api):
    """PRD 3.5: "A `PREVENTIVE_EMERGENCY` treatment, undertaken by the grazier on their
    own initiative to head off a wreck, is the grazier's cost entirely and the owner's
    share is 0 percent."
    PRD 3.5: "The system computes `total_cost_cents` as drug cost plus labor cost, then
    computes `owner_share_cents` as the total multiplied by the owner's percentage
    divided by 100 and rounded half up to a whole cent."

    Design: Corner/calculations/preventive_emergency_treatment_is_wholly_the_graziers_cost
    """
    world = setup_north_bench_lot_on_feed()

    resp = api.create_treatment(
        world.lot_id,
        treatment_payload(
            protocol_code="HEAT-EMERG", classification="PREVENTIVE_EMERGENCY",
            treatment_date="2026-08-25", withdrawal_days=0, head_treated=30,
            drug_cost_cents=2400, labor_cost_cents=600,
        ),
        make_grazier_headers(world.grazier_id),
    )
    treatment = validate_success(resp, 201)
    assert_health_treatment(treatment)

    assert treatment["total_cost_cents"] == 3000
    assert treatment["owner_share_cents"] == 0, (
        "The contract's 33 percent routine split is ignored for a preventive emergency"
    )
    assert treatment["grazier_share_cents"] == 3000
    assert treatment["status"] == "RECORDED"


def test_a_voided_treatment_leaves_the_settlement_charge_basis(api):
    """PRD 3.5: "Only `APPROVED` rows contribute their `owner_share_cents` to the
    settlement's treatment charge; `RECORDED`, `DISPUTED` and `VOIDED` rows contribute
    nothing."
    PRD 3.5: "Voiding a treatment removes it from both sets at once: it stops being a
    charge and it stops blocking the scale."

    Design: Corner/calculations/voided_treatment_drops_out_of_the_settlement_charge_basis
    """
    world = setup_north_bench_lot_on_feed()
    approved = record_treatment(world.lot_id, world.grazier_id, **ROUTINE_A)
    voided = record_treatment(world.lot_id, world.grazier_id, **ROUTINE_B)
    review_treatment_as_owner(approved["id"], world.owner_id, "APPROVE")
    voided = review_treatment_as_grazier(
        voided["id"], world.grazier_id, "VOID", note="Billed to the wrong lot"
    )
    assert voided["status"] == "VOIDED"

    weigh_out_lot(world.lot_id, world.grazier_id)
    settlement = draft_settlement(world.contract_id, world.lot_id, world.grazier_id)

    assert settlement["treatment_charge_cents"] == 1089, (
        "Only the approved row's 1089 cents counts, never the voided 838"
    )
    assert settlement["subtotal_cents"] == 1144849
    assert settlement["volume_rebate_cents"] == 11448
    assert settlement["total_due_cents"] == 1133401


def test_approving_an_already_approved_treatment_is_refused(api):
    """PRD 3.5: "A `decision` naming an outcome the treatment's current `status` does
    not permit — voiding an already-approved row, for instance, since `APPROVED` and
    `VOIDED` are both terminal — is rejected with `ERR_TREATMENT_INVALID_STATE`."

    Design: Corner/errors/approving_an_already_approved_treatment_returns_treatment_invalid_state
    """
    world = setup_north_bench_lot_on_feed()
    treatment = record_treatment(world.lot_id, world.grazier_id, **ROUTINE_A)
    review_treatment_as_owner(treatment["id"], world.owner_id, "APPROVE")

    resp = api.review_treatment(
        treatment["id"], {"decision": "APPROVE"},
        make_cattle_owner_headers(world.owner_id),
    )
    validate_error(resp, ApiErrorId.ERR_TREATMENT_INVALID_STATE.value, 409)

    listed = validate_success(
        api.list_treatments(world.lot_id, make_grazier_headers(world.grazier_id))
    )
    row = next(t for t in listed if t["id"] == treatment["id"])
    assert row["status"] == "APPROVED"
    assert row["owner_share_cents"] == 1089
