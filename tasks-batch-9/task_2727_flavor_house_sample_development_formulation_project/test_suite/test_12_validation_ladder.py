"""Shape, uniqueness, safety, capacity and temporal validation outcomes."""

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_instant_equals
from test_helpers.factories import (
    create_application_test_payload,
    create_customer_brief_payload,
    create_retention_sample_payload,
    create_shipment_payload,
    dispatch_shipment_payload,
    raw_material_component_payload,
)
from test_helpers.fixtures import (
    add_material_line,
    assemble_packet,
    build_approved_formula,
    build_released_lot,
    cost_formula,
    create_accepted_brief,
    create_brief,
    create_cabinet,
    create_formula,
    create_material,
    create_rig,
    create_shipment,
    create_verified_certificate,
    list_data,
    read_cabinet,
    read_formula,
    read_lot,
    read_shipment,
    read_substantiation_record,
    set_clock,
    store_retention_sample,
    submit_formula,
)
from test_helpers.test_users import (
    ACCOUNT_MANAGER,
    FLAVORIST,
    FLAVORIST_SUBMITTER_ID,
    LAB_COMPOUNDER,
    REGULATORY_AFFAIRS,
)


def test_duplicate_brief_code_rejected(api):
    """The second brief carrying BRF-0001 is a code collision.

    Section 3.1: "a `brief_code` already in use — compared case-sensitively —
    is an `ERR_DUPLICATE_CODE`", which §2.11 step 5 reports with HTTP 409.

    Design: Corner/validations/duplicate_brief_code_rejected
    """
    create_brief(api, brief_code="BRF-0001")

    response = api.create_customer_brief(
        create_customer_brief_payload(brief_code="BRF-0001",
                                      customer_name="Alpine Snacks",
                                      matrix_type="BAKERY_SWEET",
                                      target_profile="RED_FRUIT",
                                      dosage_pct=0.5, annual_volume_kg=200,
                                      cost_in_use_cap_cents_per_tonne=90000),
        ACCOUNT_MANAGER)
    validate_error(response, ApiErrorId.ERR_DUPLICATE_CODE.value, 409)

    assert list_data(api, api.list_customer_briefs)["meta"]["total_count"] == 1


def test_component_at_the_max_use_ceiling_admitted_then_next_increment_rejected(api):
    """A 20000 ppm material admits 2.0000 percent and refuses 2.0001.

    Section 3.3: "the ceiling in weight-percent terms is the material's
    `max_use_ppm` divided by 10000, and the line's `weight_pct` must not exceed
    it.  Equality is permitted; exceeding it is `ERR_MAX_USE_EXCEEDED`", and
    the server "assigns each new line a `sequence_no` equal to one more than the
    number of lines already on that formula".

    Design: Corner/validations/component_at_the_max_use_ceiling_admitted_then_next_increment_rejected
    """
    material = create_material(api, material_code="HI-VANILLIN",
                               name="Vanillin Crystals", cost_per_kg_cents=4500,
                               potency_class="HIGH_IMPACT", max_use_ppm=20000)
    brief = create_accepted_brief(api, brief_code="BRF-0001")
    formula = create_formula(api, brief["id"], name="Vanilla Cream F1")

    admitted = add_material_line(api, formula["id"], material["id"], 2.0)
    assert float(admitted["weight_pct"]) == 2.0
    assert admitted["sequence_no"] == 1

    response = api.add_formula_component(
        formula["id"], raw_material_component_payload(material["id"], 2.0001),
        FLAVORIST)
    validate_error(response, ApiErrorId.ERR_MAX_USE_EXCEEDED.value, 422)

    unchanged = read_formula(api, formula["id"])
    assert unchanged["component_count"] == 1
    assert float(unchanged["total_weight_pct"]) == 2.0


def test_component_type_raw_material_with_sub_formula_id_rejected(api):
    """A RAW_MATERIAL line may not also carry sub_formula_id.

    Section 3.3: "a `RAW_MATERIAL` line must supply `raw_material_id` and must
    leave `sub_formula_id` absent ... Supplying both references, supplying
    neither, or supplying the one that does not match the declared type is
    rejected with `ERR_COMPONENT_TYPE_MISMATCH`."

    Design: Corner/validations/component_type_raw_material_with_sub_formula_id_rejected
    """
    material = create_material(api, material_code="GUM-BASE")
    brief = create_accepted_brief(api, brief_code="BRF-0001")
    sub = create_formula(api, brief["id"], name="Vanilla Base SF")
    add_material_line(api, sub["id"], material["id"], 100.0)
    cost_formula(api, sub["id"])
    formula = create_formula(api, brief["id"], name="Vanilla Cream F1")

    response = api.add_formula_component(
        formula["id"],
        raw_material_component_payload(material["id"], 10.0,
                                       sub_formula_id=sub["id"]),
        FLAVORIST)
    validate_error(response, ApiErrorId.ERR_COMPONENT_TYPE_MISMATCH.value, 422)

    assert read_formula(api, formula["id"])["component_count"] == 0


def test_costing_a_formula_below_one_hundred_percent_rejected(api):
    """Sixty percent of a formula cannot be costed.

    Section 3.4: "Its `total_weight_pct` must equal 100.0000 exactly — not
    merely be at or under it, as the incremental rule of §3.3 requires — and
    any other total is `ERR_WEIGHT_SUM_INVALID`."

    Design: Corner/validations/costing_a_formula_below_one_hundred_percent_rejected
    """
    material = create_material(api, material_code="GUM-BASE")
    brief = create_accepted_brief(api, brief_code="BRF-0001")
    formula = create_formula(api, brief["id"], name="Vanilla Cream F1")
    add_material_line(api, formula["id"], material["id"], 60.0)

    response = api.cost_formula(formula["id"], FLAVORIST)
    validate_error(response, ApiErrorId.ERR_WEIGHT_SUM_INVALID.value, 422)

    unchanged = read_formula(api, formula["id"])
    assert unchanged["status"] == "DRAFT"
    assert float(unchanged["total_weight_pct"]) == 60.0
    assert unchanged["bench_cost_per_kg_cents"] is None


def test_submit_with_an_excluded_allergen_rejected(api):
    """A MILK-bearing formula cannot be submitted against a MILK exclusion.

    Section 3.4: "The formula's transitive `allergen_codes` must have no code in
    common with the brief's `allergen_exclusions`; any overlap at all is
    `ERR_ALLERGEN_EXCLUSION_BREACH`", and only "A successful submission ...
    records the caller's `X-User-ID` into `submitted_by_user_id`".

    Design: Corner/validations/submit_with_an_excluded_allergen_rejected
    """
    material = create_material(api, material_code="CREAM-DIST",
                               name="Cream Distillate", natural_status="NATURAL",
                               allergen_codes=["MILK"])
    brief = create_accepted_brief(api, brief_code="BRF-0001",
                                  allergen_exclusions=["MILK"])
    formula = create_formula(api, brief["id"], name="Vanilla Cream F1")
    add_material_line(api, formula["id"], material["id"], 100.0)
    costed = cost_formula(api, formula["id"])
    assert costed["allergen_codes"] == ["MILK"]

    response = api.submit_formula(formula["id"], FLAVORIST)
    validate_error(response, ApiErrorId.ERR_ALLERGEN_EXCLUSION_BREACH.value, 422)

    unchanged = read_formula(api, formula["id"])
    assert unchanged["status"] == "COSTED"
    assert unchanged["submitted_by_user_id"] is None


def test_required_kosher_claim_gate_applies_only_when_the_brief_asks_for_it(api):
    """The unsubstantiated material blocks the kosher brief and passes the other.

    Section 3.4: "Every claim the brief demands must have its matching
    eligibility flag true — ... one with `kosher_required` needs
    `kosher_eligible` ... and any shortfall is `ERR_CLAIM_UNSUBSTANTIATED`", so
    a brief that never asked has no gate to fail, and the successful submission
    "records the caller's `X-User-ID` into `submitted_by_user_id`".

    Design: Corner/validations/required_kosher_claim_gate_applies_only_when_the_brief_asks_for_it
    """
    material = create_material(api, material_code="GUM-BASE")

    demanding = create_accepted_brief(api, brief_code="BRF-0001",
                                      kosher_required=True)
    gated = create_formula(api, demanding["id"], name="Vanilla Cream F1")
    add_material_line(api, gated["id"], material["id"], 100.0)
    assert cost_formula(api, gated["id"])["kosher_eligible"] is False

    indifferent = create_accepted_brief(api, brief_code="BRF-0002")
    ungated = create_formula(api, indifferent["id"], name="Vanilla Cream F2")
    add_material_line(api, ungated["id"], material["id"], 100.0)
    cost_formula(api, ungated["id"])

    validate_error(api.submit_formula(gated["id"], FLAVORIST),
                   ApiErrorId.ERR_CLAIM_UNSUBSTANTIATED.value, 422)
    assert read_formula(api, gated["id"])["status"] == "COSTED"

    submitted = submit_formula(api, ungated["id"])
    assert submitted["status"] == "SUBMITTED"
    assert submitted["submitted_by_user_id"] == FLAVORIST_SUBMITTER_ID


def test_retention_interval_well_formedness_outranks_the_minimum_period(api):
    """An inverted interval reports the interval error, a short one the period error.

    Section 3.6: the interval "must be well-formed, with `stored_from` strictly
    earlier than `stored_until`, else `ERR_INVALID_INTERVAL`.  It must also
    honour the retention policy minimum: the span ... must be at least 90 days",
    and §2.11 step 16 orders "interval well-formedness (`ERR_INVALID_INTERVAL`),
    then the minimum retention period (`ERR_RETENTION_PERIOD_TOO_SHORT`)".  A
    100 gram aliquot occupies ceil(100/50) = 2 of the cabinet's 10 slots.

    Design: Corner/validations/retention_interval_well_formedness_outranks_the_minimum_period
    """
    material = create_material(api, material_code="GUM-BASE")
    brief = create_accepted_brief(api, brief_code="BRF-0001")
    formula = build_approved_formula(api, brief["id"], material["id"], 100.0)
    lot = build_released_lot(api, formula["id"], batch_size_g=500)
    cabinet = create_cabinet(api, cabinet_code="CAB-01", capacity_slots=10,
                             storage_temp_c=4.0)

    stored = store_retention_sample(api, lot["id"], cabinet["id"], quantity_g=100,
                                    stored_from="2026-08-01T00:00:00Z",
                                    stored_until="2026-10-30T00:00:00Z")
    assert stored["slot_count"] == 2
    assert stored["status"] == "STORED"

    inverted = api.create_retention_sample(
        create_retention_sample_payload(lot["id"], cabinet["id"], 100,
                                        "2026-11-01T00:00:00Z",
                                        "2026-10-01T00:00:00Z"),
        LAB_COMPOUNDER)
    validate_error(inverted, ApiErrorId.ERR_INVALID_INTERVAL.value, 422)

    too_short = api.create_retention_sample(
        create_retention_sample_payload(lot["id"], cabinet["id"], 100,
                                        "2026-08-01T00:00:00Z",
                                        "2026-10-29T00:00:00Z"),
        LAB_COMPOUNDER)
    validate_error(too_short, ApiErrorId.ERR_RETENTION_PERIOD_TOO_SHORT.value, 422)

    body = list_data(api, api.list_retention_samples, LAB_COMPOUNDER,
                     cabinet_id=cabinet["id"])
    assert body["meta"]["total_count"] == 1
    assert read_cabinet(api, cabinet["id"])["slots_available"] == 8
    assert read_lot(api, lot["id"])["available_g"] == 400


def test_rig_matrix_mismatch_outranks_dosage_mismatch(api):
    """The wrong rig reports the matrix error even though the dosage is wrong too.

    Section 3.7 requires that "the rig's `matrix_type` must equal the
    `matrix_type` of the brief reached through the lot's formula, and a mismatch
    is `ERR_RIG_MATRIX_MISMATCH`" and that "the test's `dosage_pct` must equal
    the brief's `dosage_pct` exactly, and any other value is
    `ERR_DOSAGE_MISMATCH`"; §2.11 step 17 orders "rig matrix mismatch ... then
    dosage mismatch".

    Design: Corner/validations/rig_matrix_mismatch_outranks_dosage_mismatch
    """
    material = create_material(api, material_code="GUM-BASE")
    brief = create_accepted_brief(api, brief_code="BRF-0001")
    formula = build_approved_formula(api, brief["id"], material["id"], 100.0)
    lot = build_released_lot(api, formula["id"], batch_size_g=500)
    bakery_rig = create_rig(api, rig_code="RIG-BK", matrix_type="BAKERY_SWEET",
                            cleanout_buffer_minutes=30)
    dairy_rig = create_rig(api, rig_code="RIG-DY", matrix_type="DAIRY_YOGURT",
                           cleanout_buffer_minutes=30)

    wrong_matrix = api.create_application_test(
        create_application_test_payload(lot["id"], bakery_rig["id"],
                                        "2026-08-02T09:00:00Z",
                                        "2026-08-02T11:00:00Z", 2.0, 50),
        LAB_COMPOUNDER)
    validate_error(wrong_matrix, ApiErrorId.ERR_RIG_MATRIX_MISMATCH.value, 422)

    wrong_dosage = api.create_application_test(
        create_application_test_payload(lot["id"], dairy_rig["id"],
                                        "2026-08-02T09:00:00Z",
                                        "2026-08-02T11:00:00Z", 2.0, 50),
        LAB_COMPOUNDER)
    validate_error(wrong_dosage, ApiErrorId.ERR_DOSAGE_MISMATCH.value, 422)

    body = list_data(api, api.list_application_tests, LAB_COMPOUNDER,
                     sample_lot_id=lot["id"])
    assert body["meta"]["total_count"] == 0
    assert read_lot(api, lot["id"])["available_g"] == 500


def test_shipment_mass_equality_admits_and_overdraw_rejected(api):
    """101 grams overdraws the last 100; exactly 100 consumes the lot.

    Section 3.6: "Any operation asking for more grams than `available_g`
    currently offers is refused with `ERR_INSUFFICIENT_SAMPLE_MASS`; asking for
    exactly `available_g` is permitted and is what drives the lot to
    `CONSUMED`", and §3.8 lands the shipment "in `DRAFT`".

    Design: Corner/validations/shipment_mass_equality_admits_and_overdraw_rejected
    """
    material = create_material(api, material_code="GUM-BASE")
    brief = create_accepted_brief(api, brief_code="BRF-0001")
    formula = build_approved_formula(api, brief["id"], material["id"], 100.0)
    lot = build_released_lot(api, formula["id"], batch_size_g=500)
    create_shipment(api, lot["id"], shipped_g=400, destination_country="US")

    overdraw = api.create_shipment(
        create_shipment_payload(lot["id"], 101, "US"), ACCOUNT_MANAGER)
    validate_error(overdraw, ApiErrorId.ERR_INSUFFICIENT_SAMPLE_MASS.value, 422)

    exact = create_shipment(api, lot["id"], shipped_g=100,
                            destination_country="US")
    assert exact["shipped_g"] == 100
    assert exact["status"] == "DRAFT"

    emptied = read_lot(api, lot["id"])
    assert emptied["allocated_g"] == 500
    assert emptied["available_g"] == 0
    assert emptied["disposition_status"] == "CONSUMED"
    assert emptied["qc_status"] == "PASSED"


def test_dispatch_at_packet_expiry_equality_admits_then_one_second_later_rejected(api):
    """A clock equal to packet_valid_until dispatches; one second later expires.

    Section 3.8: "The packet must not have expired: `packet_valid_until` must be
    at or after the current logical clock, with equality still dispatching, and
    an earlier value is `ERR_PACKET_EXPIRED`", and dispatch "stores the
    `tracking_reference`, stamps `dispatched_at` with the logical clock".

    Design: Corner/validations/dispatch_at_packet_expiry_equality_admits_then_one_second_later_rejected
    """
    material = create_material(api, material_code="GUM-BASE")
    certificate = create_verified_certificate(
        api, material["id"], "ALLERGEN_FREE_STATEMENT",
        issuing_body="Givaudan QA", document_ref="AL-01",
        valid_until="2026-09-01T00:00:00Z")
    brief = create_accepted_brief(api, brief_code="BRF-0001")
    formula = build_approved_formula(api, brief["id"], material["id"], 100.0)
    lot = build_released_lot(api, formula["id"], batch_size_g=500)
    first = create_shipment(api, lot["id"], shipped_g=120, destination_country="US")
    second = create_shipment(api, lot["id"], shipped_g=120, destination_country="US")

    assembled = assemble_packet(api, first["id"])
    assert_instant_equals(assembled["packet_valid_until"], "2026-09-01T00:00:00Z",
                          "packet_valid_until")
    assemble_packet(api, second["id"])

    set_clock(api, "2026-09-01T00:00:00Z")
    dispatched = get_success_data(
        api.dispatch_shipment(first["id"], dispatch_shipment_payload("TRK-AAA"),
                              REGULATORY_AFFAIRS), 200)
    assert dispatched["status"] == "DISPATCHED"
    assert dispatched["tracking_reference"] == "TRK-AAA"
    assert_instant_equals(dispatched["dispatched_at"], "2026-09-01T00:00:00Z",
                          "dispatched_at")

    set_clock(api, "2026-09-01T00:00:01Z")
    expired = api.dispatch_shipment(second["id"],
                                    dispatch_shipment_payload("TRK-BBB"),
                                    REGULATORY_AFFAIRS)
    validate_error(expired, ApiErrorId.ERR_PACKET_EXPIRED.value, 422)

    untouched = read_shipment(api, second["id"])
    assert untouched["status"] == "PACKET_ASSEMBLED"
    assert untouched["tracking_reference"] is None
    assert read_substantiation_record(api, certificate["id"])["status"] == "VERIFIED"


def test_packet_assembly_without_any_allergen_certificate_rejected(api):
    """No allergen certificate anywhere means no packet and no documents.

    Section 3.8: "If a certificate-backed required document type has no
    candidate at all — that is, if some transitive leaf material of the formula
    holds no unexpired `VERIFIED` certificate for the mapped claim — the entire
    assembly is refused with `ERR_DOC_PACKET_INCOMPLETE` and no document is
    created or re-pinned."

    Design: Corner/validations/packet_assembly_without_any_allergen_certificate_rejected
    """
    material = create_material(api, material_code="GUM-BASE")
    brief = create_accepted_brief(api, brief_code="BRF-0001")
    formula = build_approved_formula(api, brief["id"], material["id"], 100.0)
    lot = build_released_lot(api, formula["id"], batch_size_g=500)
    shipment = create_shipment(api, lot["id"], shipped_g=120,
                               destination_country="US")

    response = api.assemble_shipment_packet(shipment["id"], REGULATORY_AFFAIRS)
    validate_error(response, ApiErrorId.ERR_DOC_PACKET_INCOMPLETE.value, 422)

    unchanged = read_shipment(api, shipment["id"])
    assert unchanged["status"] == "DRAFT"
    assert unchanged["packet_valid_until"] is None

    body = list_data(api, api.list_regulatory_documents, REGULATORY_AFFAIRS,
                     shipment_id=shipment["id"])
    assert body["meta"]["total_count"] == 0
