"""Cascades settle inside the request: the write response already carries them."""

from prd_bench_local_runner.testing import get_success_data

from test_helpers.assertions import assert_envelope_meta
from test_helpers.factories import lot_qc_payload, reprice_raw_material_payload
from test_helpers.fixtures import (
    add_material_line,
    approve_formula,
    compound_lot,
    cost_formula,
    create_accepted_brief,
    create_formula,
    create_material,
    list_data,
    submit_formula,
)
from test_helpers.test_users import (
    FLAVORIST,
    FLAVORIST_SECOND,
    LAB_COMPOUNDER,
    LAB_QC,
    LAB_QC_ID,
    PURCHASING_MANAGER,
)


def test_computed_and_cross_dimension_values_appear_in_the_same_mutating_response(api):
    """The costing write and the QC write each return every derived field at once.

    Section 2.10 says the server "performs those secondary mutations
    synchronously, inside the same request, before it responds.  There is no
    deferred queue and no eventual convergence: when the response comes back,
    every dependent record has already been reconciled."  Section 3.4 fixes the
    figures: the bench roll-up gives 2000 x 100 / 100 = 2000 cents per kilogram
    and the bench cost-in-use "multiplied by the brief's `dosage_pct`,
    multiplied by 10" gives 20000, while the firm figure takes the "4 percent"
    break for an annual 500 kilograms and the 2.5 percent yield inflation —
    2000 x 0.96 = 1920, 1920 / 0.975 = 1969 — for 19690 per tonne.  Section 3.6
    supplies the cross-dimension write: a `FAILED` verdict "moves `PENDING →
    FAILED` and does reach across dimensions: the lot's `disposition_status`
    moves `HELD → SCRAPPED`", and "either verdict records the recorder into
    `qc_by_user_id`".

    Design: Corner/consistency_model/computed_and_cross_dimension_values_appear_in_the_same_mutating_response
    """
    material = create_material(api, material_code="GUM-BASE")
    brief = create_accepted_brief(api, brief_code="BRF-0001")

    first = create_formula(api, brief["id"], name="Vanilla Cream F1")
    add_material_line(api, first["id"], material["id"], 100.0)
    cost_formula(api, first["id"])
    submit_formula(api, first["id"])
    approve_formula(api, first["id"])
    lot = compound_lot(api, first["id"], batch_size_g=500)
    assert lot["qc_status"] == "PENDING"
    assert lot["disposition_status"] == "HELD"

    second = create_formula(api, brief["id"], name="Vanilla Cream F2")
    add_material_line(api, second["id"], material["id"], 100.0)
    uncosted = get_success_data(api.get_formula(second["id"], FLAVORIST), 200)
    assert uncosted["bench_cost_per_kg_cents"] is None

    costing = api.cost_formula(second["id"], FLAVORIST)
    assert costing.status_code == 200, costing.text
    costing_body = costing.json()
    assert_envelope_meta(costing_body, "object")
    written = costing_body["data"]
    assert written["bench_cost_per_kg_cents"] == 2000
    assert written["bench_cost_in_use_cents_per_tonne"] == 20000
    assert written["firm_cost_in_use_cents_per_tonne"] == 19690
    assert written["cost_stale"] is False
    assert written["kosher_eligible"] is False
    assert written["natural_claim_eligible"] is False
    assert written["halal_eligible"] is False
    assert written["allergen_codes"] == []
    assert written["status"] == "COSTED"
    assert written["version"] > uncosted["version"]

    read_back = api.get_formula(second["id"], FLAVORIST)
    read_body = read_back.json()
    assert_envelope_meta(read_body, "object")
    settled = get_success_data(read_back, 200)
    assert settled["bench_cost_per_kg_cents"] == 2000
    assert settled["bench_cost_in_use_cents_per_tonne"] == 20000
    assert settled["firm_cost_in_use_cents_per_tonne"] == 19690

    verdict = api.record_lot_qc(lot["id"],
                                lot_qc_payload("FAILED",
                                               qc_note="off-note in the top"),
                                LAB_QC)
    assert verdict.status_code == 200, verdict.text
    verdict_body = verdict.json()
    assert_envelope_meta(verdict_body, "object")
    scrapped = verdict_body["data"]
    assert scrapped["qc_status"] == "FAILED"
    assert scrapped["disposition_status"] == "SCRAPPED"

    lot_read = api.get_sample_lot(lot["id"], LAB_COMPOUNDER)
    lot_body = lot_read.json()
    assert_envelope_meta(lot_body, "object")
    stored_lot = get_success_data(lot_read, 200)
    assert stored_lot["qc_status"] == "FAILED"
    assert stored_lot["disposition_status"] == "SCRAPPED"
    assert stored_lot["qc_by_user_id"] == LAB_QC_ID


def test_reprice_fan_out_is_readable_on_the_very_next_call(api):
    """One PATCH re-costs two formulas and both are settled on the first read.

    Section 3.2 says of a reprice that "Every formula with status `COSTED`,
    `SUBMITTED` or `APPROVED` that transitively contains the repriced material is
    re-costed in place", that "A formula in `APPROVED` stays `APPROVED`, but its
    `cost_stale` flag is set to true ... and its `version` is incremented", and
    that "A formula in `SUBMITTED` is pushed `SUBMITTED → REWORK_REQUIRED` with
    `rework_reason` set to `RAW_MATERIAL_REPRICED`".  Section 2.10 forbids any
    lag: "There is no deferred queue and no eventual convergence: when the
    response comes back, every dependent record has already been reconciled."
    At 2500 cents FA rolls up to 2500, its bench cost-in-use to 25000, and its
    firm figure to 2500 x 0.96 = 2400, 2400 / 0.975 = 2462, 24620 per tonne;
    FB's two halves become 2500 x 50 / 100 = 1250 and 100 x 50 / 100 = 50, so
    its bench cost moves from 1050 to 1300.

    Design: Corner/consistency_model/reprice_fan_out_is_readable_on_the_very_next_call
    """
    gum_base = create_material(api, material_code="GUM-BASE")
    salt = create_material(api, material_code="SALT", name="Fine Salt",
                           cost_per_kg_cents=100, natural_status="NATURAL",
                           potency_class="STANDARD", max_use_ppm=1000000)
    brief = create_accepted_brief(api, brief_code="BRF-0001")

    first = create_formula(api, brief["id"], name="Vanilla Cream FA")
    add_material_line(api, first["id"], gum_base["id"], 100.0)
    cost_formula(api, first["id"])
    submit_formula(api, first["id"])
    approved = approve_formula(api, first["id"])
    assert approved["status"] == "APPROVED"
    assert approved["cost_stale"] is False

    second = create_formula(api, brief["id"], name="Vanilla Cream FB")
    add_material_line(api, second["id"], gum_base["id"], 50.0)
    add_material_line(api, second["id"], salt["id"], 50.0)
    costed = cost_formula(api, second["id"])
    assert costed["bench_cost_per_kg_cents"] == 1050
    submitted = submit_formula(api, second["id"], FLAVORIST_SECOND)
    assert submitted["status"] == "SUBMITTED"

    reprice = api.reprice_raw_material(gum_base["id"],
                                       reprice_raw_material_payload(2500),
                                       PURCHASING_MANAGER)
    assert reprice.status_code == 200, reprice.text
    assert reprice.json()["data"]["cost_per_kg_cents"] == 2500

    fa = get_success_data(api.get_formula(first["id"], FLAVORIST), 200)
    assert fa["bench_cost_per_kg_cents"] == 2500
    assert fa["status"] == "APPROVED"
    assert fa["cost_stale"] is True
    assert fa["bench_cost_in_use_cents_per_tonne"] == 25000
    assert fa["firm_cost_in_use_cents_per_tonne"] == 24620

    fb = get_success_data(api.get_formula(second["id"], FLAVORIST), 200)
    assert fb["bench_cost_per_kg_cents"] == 1300
    assert fb["status"] == "REWORK_REQUIRED"
    assert fb["rework_reason"] == "RAW_MATERIAL_REPRICED"

    body = list_data(api, api.list_formula_components, FLAVORIST,
                     formula_id=second["id"])
    lines = sorted(body["data"], key=lambda row: row["sequence_no"])
    assert [row["sequence_no"] for row in lines] == [1, 2]
    assert lines[0]["contribution_cents"] == 1250
    assert lines[1]["contribution_cents"] == 50
