"""The revocation and failed-test cascades, and the dispatch rule ordering."""

from prd_bench_local_runner.testing import validate_error

from test_helpers.api_errors import ApiErrorId
from test_helpers.factories import dispatch_shipment_payload
from test_helpers.fixtures import (
    assemble_packet,
    build_approved_formula,
    build_released_lot,
    citrus_released_lot,
    create_accepted_brief,
    create_rig,
    create_shipment,
    create_verified_certificate,
    documents_of,
    error_id_of,
    gum_base_material,
    kosher_chain,
    publish_forecast,
    read_application_test,
    read_brief,
    read_forecast,
    read_formula,
    read_lot,
    read_material,
    read_shipment,
    read_substantiation_record,
    record_application_test_result,
    revoke_certificate,
    schedule_application_test,
    start_application_test,
)
from test_helpers.test_users import LAB_COMPOUNDER, REGULATORY_AFFAIRS

PANEL_WINDOW_START = "2026-08-10T08:00:00Z"
PANEL_WINDOW_END = "2026-08-10T10:00:00Z"
DAIRY_WINDOW_START = "2026-08-12T09:00:00Z"
DAIRY_WINDOW_END = "2026-08-12T11:00:00Z"


def _kosher_shipment(api, shipped_g=150):
    """The kosher chain carried as far as a PACKET_ASSEMBLED shipment."""
    scenario = kosher_chain(api, batch_size_g=500)
    shipment = create_shipment(api, scenario["lot"]["id"], shipped_g, "US")
    scenario["shipment"] = assemble_packet(api, shipment["id"])
    return scenario


def _forecast_after_approval(api, brief_id):
    brief = read_brief(api, brief_id)
    return publish_forecast(api, brief_id, brief["version"],
                            annual_volume_kg=1200, unit_price_cents_per_kg=4200)


def test_revoking_the_kosher_certificate_restricts_the_material_and_reworks_the_formula(api):
    """Links 1 and 2: the leaf material goes RESTRICTED and the formula to rework.

    The PRD says of revocation that "the owning material's `claim_status`
    becomes `RESTRICTED` and the revoked `claim_type` is removed from its
    `verified_claim_types`", and that a
    formula in `APPROVED` whose brief requires a claim the material can no
    longer support is pushed to `REWORK_REQUIRED` with `rework_reason`
    `SUBSTANTIATION_REVOKED`.

    Design: Difficulty/transitive_cascade/kosher_certificate_revocation_four_link_compliance_cascade
    """
    scenario = _kosher_shipment(api)
    assert read_formula(api, scenario["formula"]["id"])["kosher_eligible"] is True

    revoke_certificate(api, scenario["kosher_certificate"]["id"],
                       "Certifying council suspended the plant audit")

    record = read_substantiation_record(api, scenario["kosher_certificate"]["id"])
    assert record["status"] == "REVOKED"
    assert record["revocation_reason"] is not None

    material = read_material(api, scenario["material"]["id"])
    assert material["claim_status"] == "RESTRICTED"
    assert "KOSHER" not in material["verified_claim_types"]

    formula = read_formula(api, scenario["formula"]["id"])
    assert formula["status"] == "REWORK_REQUIRED"
    assert formula["rework_reason"] == "SUBSTANTIATION_REVOKED"
    assert formula["kosher_eligible"] is False


def test_the_revocation_holds_the_lot_and_blocks_its_shipment(api):
    """Links 3 and 4: the released lot returns to HELD and the shipment is BLOCKED.

    The PRD says a formula leaving `APPROVED` sends "that formula's `RELEASED`
    sample lots ... back to `HELD`" and makes "the shipments of those newly
    held lots ... `BLOCKED`", the block reason being `LOT_HELD`.

    Design: Difficulty/transitive_cascade/kosher_certificate_revocation_four_link_compliance_cascade
    """
    scenario = _kosher_shipment(api)

    revoke_certificate(api, scenario["kosher_certificate"]["id"],
                       "Certifying council suspended the plant audit")

    lot = read_lot(api, scenario["lot"]["id"])
    assert lot["disposition_status"] == "HELD"
    assert lot["qc_status"] == "PASSED"

    shipment = read_shipment(api, scenario["shipment"]["id"])
    assert shipment["status"] == "BLOCKED"
    assert shipment["block_reason"] == "LOT_HELD"


def test_only_the_document_pinned_to_the_revoked_record_goes_stale(api):
    """The kosher document goes STALE while SDS and the allergen statement stay PINNED.

    The PRD stales exactly the documents of the certificate that moved: "every
    regulatory document pinned to the revoked certificate that was `PINNED`
    becomes `STALE`", which reaches only the document backed by the revoked
    certificate.  The shipment's `packet_valid_until` is "set to the earliest
    `pinned_valid_until` across the certificate-backed documents", here the
    allergen certificate's 2027-06-30.

    Design: Difficulty/transitive_cascade/kosher_certificate_revocation_four_link_compliance_cascade
    """
    scenario = _kosher_shipment(api)
    assert scenario["shipment"]["packet_valid_until"].startswith("2027-06-30")

    before = {doc["doc_type"]: doc["status"] for doc in
              documents_of(api, scenario["shipment"]["id"])}
    assert before["KOSHER_CERT"] == "PINNED"

    revoke_certificate(api, scenario["kosher_certificate"]["id"],
                       "Certifying council suspended the plant audit")

    after = {doc["doc_type"]: doc["status"] for doc in
             documents_of(api, scenario["shipment"]["id"])}
    assert after["KOSHER_CERT"] == "STALE"
    assert after["ALLERGEN_STATEMENT"] == "PINNED"
    assert after["SDS"] == "PINNED"


def test_the_compliance_cascade_moves_states_and_never_grams(api):
    """The shipment keeps its 150 g and the lot keeps 350 g available.

    The PRD returns grams only on explicit compensating moves — cancellation
    and withdrawal — so a state cascade must leave the gram ledger of §3.6
    exactly where it was.

    Design: Difficulty/transitive_cascade/kosher_certificate_revocation_four_link_compliance_cascade
    """
    scenario = _kosher_shipment(api)

    revoke_certificate(api, scenario["kosher_certificate"]["id"],
                       "Certifying council suspended the plant audit")

    assert read_shipment(api, scenario["shipment"]["id"])["shipped_g"] == 150
    lot = read_lot(api, scenario["lot"]["id"])
    assert lot["available_g"] == 350
    assert lot["allocated_g"] == 150


def test_starting_a_test_is_refused_once_the_cascade_holds_its_lot(api):
    """The test's own SCHEDULED state is valid; the held lot blocks the start.

    The PRD requires at start that "its `disposition_status` must be
    `RELEASED`, else `ERR_LOT_NOT_RELEASED`", a cross-entity guard §2.11
    places ahead of the test's own-state guard `ERR_TEST_STATE_INVALID`.

    Design: Difficulty/cross_entity_state_dependency/test_start_requires_its_lot_to_still_be_released
    """
    scenario = kosher_chain(api, batch_size_g=500)
    assert scenario["lot"]["disposition_status"] == "RELEASED"

    rig = create_rig(api, rig_code="RIG-DAI-01", matrix_type="DAIRY_YOGURT",
                     cleanout_buffer_minutes=30)
    test = schedule_application_test(api, scenario["lot"]["id"], rig["id"],
                                     dosage_pct=1.0, consumed_g=100,
                                     window_start=DAIRY_WINDOW_START,
                                     window_end=DAIRY_WINDOW_END)
    assert test["status"] == "SCHEDULED"

    revoke_certificate(api, scenario["kosher_certificate"]["id"],
                       "Certifying council suspended the plant audit")
    held = read_lot(api, scenario["lot"]["id"])
    assert held["disposition_status"] == "HELD"
    assert held["qc_status"] == "PASSED"

    response = api.start_application_test(test["id"], LAB_COMPOUNDER)
    validate_error(response, ApiErrorId.ERR_LOT_NOT_RELEASED.value)
    assert error_id_of(response) != "ERR_TEST_STATE_INVALID"


def test_the_refused_start_keeps_the_test_scheduled_and_its_grams_allocated(api):
    """The booking still holds 100 g and records no panel score.

    The PRD says "scheduling immediately raises the lot's `allocated_g` by
    `consumed_g` and lowers `available_g`" and that "a test never returns its
    grams", so a refused start changes nothing.

    Design: Difficulty/cross_entity_state_dependency/test_start_requires_its_lot_to_still_be_released
    """
    scenario = kosher_chain(api, batch_size_g=500)
    rig = create_rig(api, rig_code="RIG-DAI-01", matrix_type="DAIRY_YOGURT",
                     cleanout_buffer_minutes=30)
    test = schedule_application_test(api, scenario["lot"]["id"], rig["id"],
                                     dosage_pct=1.0, consumed_g=100,
                                     window_start=DAIRY_WINDOW_START,
                                     window_end=DAIRY_WINDOW_END)
    revoke_certificate(api, scenario["kosher_certificate"]["id"],
                       "Certifying council suspended the plant audit")

    validate_error(api.start_application_test(test["id"], LAB_COMPOUNDER),
                   ApiErrorId.ERR_LOT_NOT_RELEASED.value)

    unchanged = read_application_test(api, test["id"])
    assert unchanged["status"] == "SCHEDULED"
    assert unchanged["panel_score"] is None

    lot = read_lot(api, scenario["lot"]["id"])
    assert lot["allocated_g"] == 100
    assert lot["available_g"] == 400


def test_a_failed_panel_verdict_reworks_the_formula_and_derates_the_forecast(api):
    """Three links from a laboratory verdict: 63.25 FAILED, rework, AT_RISK 1247400.

    The PRD weights 60 / 55 / 80 to 63.25 and says "anything below 70.00
    drives `IN_PROGRESS → FAILED`", then "the lot's formula — if it was
    `APPROVED` — is pushed to `REWORK_REQUIRED` with `rework_reason`
    `APPLICATION_TEST_FAILURE`" and "the brief's `ACTIVE` commercialization
    forecast moves to `AT_RISK` and its `weighted_annual_value_cents` is
    recomputed with a `technical_factor` of 0.55".

    Design: Difficulty/transitive_cascade/failed_application_test_three_link_forecast_cascade
    """
    scenario = citrus_released_lot(api, batch_size_g=500)
    forecast = _forecast_after_approval(api, scenario["brief"]["id"])
    assert forecast["weighted_annual_value_cents"] == 1814400
    assert float(forecast["technical_factor"]) == 0.80

    rig = create_rig(api, rig_code="RIG-BEV-01", matrix_type="BEVERAGE_STILL",
                     cleanout_buffer_minutes=30)
    test = schedule_application_test(api, scenario["lot"]["id"], rig["id"],
                                     dosage_pct=2.5, consumed_g=100,
                                     window_start=PANEL_WINDOW_START,
                                     window_end=PANEL_WINDOW_END)
    start_application_test(api, test["id"])

    failed = record_application_test_result(api, test["id"], 60, 55, 80)
    assert float(failed["panel_score"]) == 63.25
    assert failed["status"] == "FAILED"

    formula = read_formula(api, scenario["formula"]["id"])
    assert formula["status"] == "REWORK_REQUIRED"
    assert formula["rework_reason"] == "APPLICATION_TEST_FAILURE"

    derated = read_forecast(api, forecast["id"])
    assert derated["status"] == "AT_RISK"
    assert float(derated["technical_factor"]) == 0.55
    assert float(derated["stage_probability"]) == 0.45
    assert derated["weighted_annual_value_cents"] == 1247400


def test_the_failed_test_holds_the_lot_but_keeps_its_grams_and_the_brief(api):
    """The fan-out holds the lot at 100 g allocated and leaves the brief ACCEPTED.

    The PRD says the demotion sends "that formula's `RELEASED` sample lots
    return to `HELD`" while "a test never returns its grams, not even when it
    fails", and nothing in the chain touches the brief.

    Design: Difficulty/transitive_cascade/failed_application_test_three_link_forecast_cascade
    """
    scenario = citrus_released_lot(api, batch_size_g=500)
    _forecast_after_approval(api, scenario["brief"]["id"])
    rig = create_rig(api, rig_code="RIG-BEV-01", matrix_type="BEVERAGE_STILL",
                     cleanout_buffer_minutes=30)
    test = schedule_application_test(api, scenario["lot"]["id"], rig["id"],
                                     dosage_pct=2.5, consumed_g=100,
                                     window_start=PANEL_WINDOW_START,
                                     window_end=PANEL_WINDOW_END)
    start_application_test(api, test["id"])
    record_application_test_result(api, test["id"], 60, 55, 80)

    lot = read_lot(api, scenario["lot"]["id"])
    assert lot["disposition_status"] == "HELD"
    assert lot["qc_status"] == "PASSED"
    assert lot["allocated_g"] == 100
    assert lot["available_g"] == 400

    assert read_brief(api, scenario["brief"]["id"])["status"] == "ACCEPTED"


def test_dispatch_reports_the_revoked_certificate_rather_than_the_stale_pin(api):
    """Both rules are violated; the safety rule with the lower priority number wins.

    Revoking the pinned allergen certificate makes the document STALE and also
    leaves it backed by a non-`VERIFIED` record.  The PRD orders dispatch's
    checks so the substantiation rule is evaluated before the document-pin
    rule, so the answer is `ERR_SUBSTANTIATION_REVOKED` at 422 rather than
    `ERR_PINNED_DOC_STALE`.

    Design: Difficulty/priority_pair_validation_conflict/dispatch_revoked_certificate_outranks_stale_document_pin
    """
    material = gum_base_material(api)
    certificate = create_verified_certificate(
        api, material["id"], "ALLERGEN_FREE_STATEMENT",
        issuing_body="Nordic Lab Services", document_ref="AF-2026-118",
        valid_until="2027-06-30T00:00:00Z")
    brief = create_accepted_brief(api, brief_code="BRF-0003",
                                  customer_name="Baltic Dairy",
                                  natural_claim_required=False,
                                  kosher_required=False, halal_required=False)
    formula = build_approved_formula(api, brief["id"], material["id"], 100.0)
    lot = build_released_lot(api, formula["id"], 500)
    shipment = assemble_packet(api, create_shipment(api, lot["id"], 150, "US")["id"])
    assert shipment["status"] == "PACKET_ASSEMBLED"

    revoke_certificate(api, certificate["id"],
                       "Laboratory withdrew the allergen-free attestation")
    assert read_formula(api, formula["id"])["status"] == "APPROVED"

    documents = {doc["doc_type"]: doc for doc in documents_of(api, shipment["id"])}
    assert documents["ALLERGEN_STATEMENT"]["status"] == "STALE"
    assert read_substantiation_record(api, certificate["id"])["status"] == "REVOKED"

    response = api.dispatch_shipment(
        shipment["id"], dispatch_shipment_payload("TRK-77121"), REGULATORY_AFFAIRS)
    validate_error(response, ApiErrorId.ERR_SUBSTANTIATION_REVOKED.value)
    assert error_id_of(response) != "ERR_PINNED_DOC_STALE"


def test_the_refused_dispatch_leaves_the_shipment_assembled_and_untracked(api):
    """No tracking reference is written and the packet stays assembled.

    The PRD writes `tracking_reference` and moves `PACKET_ASSEMBLED →
    DISPATCHED` only on a successful dispatch, so a refusal leaves both
    exactly as they were.

    Design: Difficulty/priority_pair_validation_conflict/dispatch_revoked_certificate_outranks_stale_document_pin
    """
    material = gum_base_material(api)
    certificate = create_verified_certificate(
        api, material["id"], "ALLERGEN_FREE_STATEMENT",
        issuing_body="Nordic Lab Services", document_ref="AF-2026-118",
        valid_until="2027-06-30T00:00:00Z")
    brief = create_accepted_brief(api, brief_code="BRF-0003",
                                  customer_name="Baltic Dairy",
                                  natural_claim_required=False,
                                  kosher_required=False, halal_required=False)
    formula = build_approved_formula(api, brief["id"], material["id"], 100.0)
    lot = build_released_lot(api, formula["id"], 500)
    shipment = assemble_packet(api, create_shipment(api, lot["id"], 150, "US")["id"])
    revoke_certificate(api, certificate["id"],
                       "Laboratory withdrew the allergen-free attestation")

    validate_error(
        api.dispatch_shipment(shipment["id"],
                              dispatch_shipment_payload("TRK-77121"),
                              REGULATORY_AFFAIRS),
        ApiErrorId.ERR_SUBSTANTIATION_REVOKED.value)

    unchanged = read_shipment(api, shipment["id"])
    assert unchanged["status"] == "PACKET_ASSEMBLED"
    assert unchanged["tracking_reference"] is None
