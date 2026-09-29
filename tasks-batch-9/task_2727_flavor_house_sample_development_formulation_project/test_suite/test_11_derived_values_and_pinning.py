"""Derived claim profiles, forecast constants, packet pinning and minted numbers."""

from prd_bench_local_runner.testing import get_success_data

from test_helpers.fixtures import (
    add_material_line,
    assemble_packet,
    build_approved_formula,
    build_released_lot,
    compound_lot,
    cost_formula,
    create_accepted_brief,
    create_formula,
    create_material,
    create_rig,
    create_shipment,
    create_submitted_brief,
    create_verified_certificate,
    documents_of,
    publish_forecast,
    read_formula,
    read_lot,
    read_material,
    read_substantiation_record,
    record_application_test_result,
    schedule_application_test,
    set_clock,
    start_application_test,
)
from test_helpers.assertions import assert_instant_equals
from test_helpers.constants import INITIAL_CLOCK
from test_helpers.factories import brief_clarification_payload
from test_helpers.test_users import TECHNICAL_DIRECTOR


def test_claim_profile_excludes_a_certificate_that_expired_before_the_clock(api):
    """Costing after the clock passes valid_until reports the claim as ineligible.

    Section 3.4: "a leaf material substantiates a claim when it holds a
    certificate for that claim type whose status is `VERIFIED` and whose
    `valid_until` is at or after the current logical clock", and §3.2 says
    `verified_claim_types` lists only records "whose `valid_until` is at or
    after the logical clock".  Section 2.4 adds that moving the clock "changes
    what computed fields report ... but moving the clock never fires a
    state-machine transition on its own", so the certificate stays `VERIFIED`
    and the material stays `CLEAR`.

    Design: Corner/calculations/claim_profile_excludes_a_certificate_that_expired_before_the_clock
    """
    material = create_material(api, material_code="GUM-BASE")
    certificate = create_verified_certificate(
        api, material["id"], "KOSHER", issuing_body="OU Kosher",
        document_ref="K-11", valid_until="2027-06-30T00:00:00Z")
    brief = create_accepted_brief(api, brief_code="BRF-0001", kosher_required=True)

    early = create_formula(api, brief["id"], name="Vanilla Cream F1")
    add_material_line(api, early["id"], material["id"], 100.0)
    assert cost_formula(api, early["id"])["kosher_eligible"] is True

    later = create_formula(api, brief["id"], name="Vanilla Cream F2")
    add_material_line(api, later["id"], material["id"], 100.0)
    set_clock(api, "2028-01-01T00:00:00Z")

    costed = cost_formula(api, later["id"])

    assert costed["kosher_eligible"] is False
    assert costed["bench_cost_per_kg_cents"] == 2000
    assert costed["status"] == "COSTED"

    unchanged = read_substantiation_record(api, certificate["id"])
    assert unchanged["status"] == "VERIFIED"
    assert unchanged["is_expired"] is True

    observed = read_material(api, material["id"])
    assert observed["verified_claim_types"] == []
    assert observed["claim_status"] == "CLEAR"


def test_forecast_uses_the_clarification_stage_probability_constant(api):
    """A brief awaiting answers values at the 0.10 stage probability.

    Section 3.9: `stage_probability` is "0.45 when the brief is `ACCEPTED`,
    0.20 when it is `SUBMITTED`, and 0.10 when it is
    `CLARIFICATION_REQUESTED`", with `technical_factor` at "0.55 when there is
    not even an approved formula", and "The new forecast is created in `ACTIVE`
    with `pinned_brief_version` holding the validated version value".  So
    500 x 10000 x 0.10 x 0.55 = 275000.

    Design: Corner/calculations/forecast_uses_the_clarification_stage_probability_constant
    """
    brief = create_submitted_brief(api, brief_code="BRF-0001")
    sent_back = get_success_data(
        api.request_brief_clarification(
            brief["id"], brief_clarification_payload("restate the top note"),
            TECHNICAL_DIRECTOR), 200)
    assert sent_back["status"] == "CLARIFICATION_REQUESTED"

    forecast = publish_forecast(api, brief["id"], sent_back["version"],
                                annual_volume_kg=500,
                                unit_price_cents_per_kg=10000)

    assert forecast["variant_applied"] == "RISK_WEIGHTED"
    assert float(forecast["stage_probability"]) == 0.10
    assert float(forecast["technical_factor"]) == 0.55
    assert forecast["weighted_annual_value_cents"] == 275000
    assert forecast["pinned_brief_version"] == sent_back["version"]
    assert forecast["status"] == "ACTIVE"


def test_packet_pins_the_earliest_expiring_of_two_candidate_certificates(api):
    """Of two live allergen certificates the sooner-expiring one binds the packet.

    Section 3.8: "Candidates are ranked by `valid_until` ascending, so the
    certificate that expires soonest is the one that binds the packet", the
    non-certificate-backed types keep "their `substantiation_id`,
    `pinned_substantiation_version` and `pinned_valid_until` ... null", and
    "the shipment's `packet_valid_until` is set to the earliest
    `pinned_valid_until` across the certificate-backed documents".  A US
    shipment of a TIER_1_STANDARD formula under a brief with no claim flags
    requires only "`SDS` and `ALLERGEN_STATEMENT`".

    Design: Corner/calculations/packet_pins_the_earliest_expiring_of_two_candidate_certificates
    """
    material = create_material(api, material_code="GUM-BASE")
    create_verified_certificate(
        api, material["id"], "ALLERGEN_FREE_STATEMENT",
        issuing_body="Givaudan QA", document_ref="AL-LATE",
        valid_until="2027-09-30T00:00:00Z")
    early = create_verified_certificate(
        api, material["id"], "ALLERGEN_FREE_STATEMENT",
        issuing_body="Givaudan QA", document_ref="AL-EARLY",
        valid_until="2027-03-31T00:00:00Z")
    brief = create_accepted_brief(api, brief_code="BRF-0001")
    formula = build_approved_formula(api, brief["id"], material["id"], 100.0)
    lot = build_released_lot(api, formula["id"], batch_size_g=500)
    shipment = create_shipment(api, lot["id"], shipped_g=120,
                               destination_country="US")

    assembled = assemble_packet(api, shipment["id"])

    assert assembled["status"] == "PACKET_ASSEMBLED"
    assert assembled["required_document_types"] == ["SDS", "ALLERGEN_STATEMENT"]
    assert_instant_equals(assembled["packet_valid_until"],
                          "2027-03-31T00:00:00Z", "packet_valid_until")

    documents = documents_of(api, shipment["id"])
    assert len(documents) == 2
    by_type = {document["doc_type"]: document for document in documents}

    allergen = by_type["ALLERGEN_STATEMENT"]
    assert allergen["substantiation_id"] == early["id"]
    assert_instant_equals(allergen["pinned_valid_until"],
                          "2027-03-31T00:00:00Z", "pinned_valid_until")
    assert allergen["pinned_substantiation_version"] == early["version"]
    assert allergen["status"] == "PINNED"

    sds = by_type["SDS"]
    assert sds["substantiation_id"] is None
    assert sds["pinned_valid_until"] is None


def test_panel_score_rounds_half_up_once_on_the_weighted_sum(api):
    """60.0 / 60.0 / 60.1 weights to 60.025 and rounds once to 60.03.

    Section 3.7: the composite "is the aroma score multiplied by 0.40, plus the
    taste score multiplied by 0.35, plus the stability score multiplied by
    0.25, with a single round-half-up to two decimal places applied to that
    weighted sum and to nothing else", "anything below 70.00 drives
    `IN_PROGRESS → FAILED`", the failure pushes the formula "to
    `REWORK_REQUIRED` with `rework_reason` `APPLICATION_TEST_FAILURE`", and
    "that formula's `RELEASED` sample lots return to `HELD`".

    Design: Corner/calculations/panel_score_rounds_half_up_once_on_the_weighted_sum
    """
    material = create_material(api, material_code="GUM-BASE")
    brief = create_accepted_brief(api, brief_code="BRF-0001")
    formula = build_approved_formula(api, brief["id"], material["id"], 100.0)
    lot = build_released_lot(api, formula["id"], batch_size_g=500)
    rig = create_rig(api, rig_code="RIG-01", matrix_type="DAIRY_YOGURT",
                     cleanout_buffer_minutes=30)
    test = schedule_application_test(api, lot["id"], rig["id"], dosage_pct=1.0,
                                     consumed_g=50,
                                     window_start="2026-08-02T09:00:00Z",
                                     window_end="2026-08-02T11:00:00Z")
    start_application_test(api, test["id"])

    recorded = record_application_test_result(api, test["id"], 60.0, 60.0, 60.1)

    assert float(recorded["panel_score"]) == 60.03
    assert recorded["status"] == "FAILED"
    assert_instant_equals(recorded["verdict_recorded_at"], INITIAL_CLOCK,
                          "verdict_recorded_at")

    reworked = read_formula(api, formula["id"])
    assert reworked["status"] == "REWORK_REQUIRED"
    assert reworked["rework_reason"] == "APPLICATION_TEST_FAILURE"
    assert read_lot(api, lot["id"])["disposition_status"] == "HELD"


def test_lot_numbers_are_minted_in_creation_order_per_formula(api):
    """The second lot of one formula takes the L002 suffix and its own grams.

    Section 3.6: "Its sequence position is one more than the number of lots
    already recorded against the same formula with an earlier creation
    timestamp", the number concatenating "the brief's `brief_code`, then a
    literal `-I` followed by the formula's iteration number zero-padded to two
    digits, then a literal `-L` followed by that sequence position zero-padded
    to three digits", while "The lot also snapshots the formula's iteration
    number into `formula_iteration_no`" and starts "with `qc_status` at
    `PENDING`, `disposition_status` at `HELD` ... and `available_g` equal to its
    `batch_size_g`".

    Design: Corner/calculations/lot_numbers_are_minted_in_creation_order_per_formula
    """
    material = create_material(api, material_code="GUM-BASE")
    brief = create_accepted_brief(api, brief_code="BRF-0001")
    formula = build_approved_formula(api, brief["id"], material["id"], 100.0)
    first = compound_lot(api, formula["id"], batch_size_g=500)
    assert first["lot_number"] == "BRF-0001-I01-L001"

    second = compound_lot(api, formula["id"], batch_size_g=250)

    assert second["lot_number"] == "BRF-0001-I01-L002"
    assert second["formula_iteration_no"] == 1
    assert second["available_g"] == 250
    assert second["qc_status"] == "PENDING"
    assert second["disposition_status"] == "HELD"
