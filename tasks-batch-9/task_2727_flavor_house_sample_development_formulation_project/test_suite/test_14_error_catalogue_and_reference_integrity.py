"""The not-found families, the state-invalid families and two ordering codes."""

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_envelope_meta
from test_helpers.constants import UNKNOWN_UUIDS
from test_helpers.factories import (
    cancel_shipment_payload,
    create_application_test_payload,
    create_formula_payload,
    create_formula_revision_payload,
    create_retention_sample_payload,
    create_sample_lot_payload,
    create_substantiation_record_payload,
    reprice_raw_material_payload,
    revoke_substantiation_record_payload,
    sub_formula_component_payload,
    withdraw_retention_sample_payload,
)
from test_helpers.fixtures import (
    add_material_line,
    build_approved_formula,
    build_released_lot,
    cancel_shipment,
    cost_formula,
    create_accepted_brief,
    create_cabinet,
    create_formula,
    create_material,
    create_shipment,
    list_data,
    read_batch,
    read_cabinet,
    read_formula,
    read_lot,
    read_retention_sample,
    read_shipment,
    request_scale_up_batch,
    set_batch_tolerance,
    store_retention_sample,
    withdraw_retention_sample,
)
from test_helpers.test_users import (
    ACCOUNT_MANAGER,
    DIRECTOR_APPROVER,
    FLAVORIST,
    LAB_COMPOUNDER,
    LAB_TECH,
    PURCHASING_MANAGER,
    REGULATORY_AFFAIRS,
)

RETENTION_FROM = "2026-08-01T00:00:00Z"
RETENTION_UNTIL = "2026-10-30T00:00:00Z"


def test_every_path_parameter_family_reports_its_own_not_found_error_id(api):
    """Fifteen path identifiers answer fifteen distinct 404 codes on an empty database.

    Section 2.5 enumerates the path identifiers "`brief_id`, `material_id`,
    `record_id`, `formula_id`, `component_id`, `lot_id`, `cabinet_id`,
    `retention_id`, `rig_id`, `test_id`, `shipment_id`, `document_id`,
    `batch_id`, `forecast_id` and `grant_id`" and says "Each has its own
    not-found error, all reported with HTTP 404: `ERR_BRIEF_NOT_FOUND`,
    `ERR_MATERIAL_NOT_FOUND`, `ERR_SUBSTANTIATION_NOT_FOUND`,
    `ERR_FORMULA_NOT_FOUND`, `ERR_COMPONENT_NOT_FOUND`, `ERR_LOT_NOT_FOUND`,
    `ERR_CABINET_NOT_FOUND`, `ERR_RETENTION_NOT_FOUND`, `ERR_RIG_NOT_FOUND`,
    `ERR_TEST_NOT_FOUND`, `ERR_SHIPMENT_NOT_FOUND`, `ERR_DOCUMENT_NOT_FOUND`,
    `ERR_BATCH_NOT_FOUND`, `ERR_FORECAST_NOT_FOUND` and `ERR_GRANT_NOT_FOUND`
    respectively."  Every error body carries "`error_id`" and a "`message`"
    that "provides a human-readable explanation of what went wrong".

    Design: Corner/errors/every_path_parameter_family_reports_its_own_not_found_error_id
    """
    probes = [
        (ApiErrorId.ERR_BRIEF_NOT_FOUND,
         api.get_customer_brief(UNKNOWN_UUIDS["brief"], ACCOUNT_MANAGER)),
        (ApiErrorId.ERR_MATERIAL_NOT_FOUND,
         api.reprice_raw_material(UNKNOWN_UUIDS["material"],
                                  reprice_raw_material_payload(1500),
                                  PURCHASING_MANAGER)),
        (ApiErrorId.ERR_SUBSTANTIATION_NOT_FOUND,
         api.revoke_substantiation_record(UNKNOWN_UUIDS["record"],
                                          revoke_substantiation_record_payload(
                                              "audit finding"),
                                          REGULATORY_AFFAIRS)),
        (ApiErrorId.ERR_FORMULA_NOT_FOUND,
         api.get_formula(UNKNOWN_UUIDS["formula"], FLAVORIST)),
        (ApiErrorId.ERR_COMPONENT_NOT_FOUND,
         api.delete_formula_component(UNKNOWN_UUIDS["component"], FLAVORIST)),
        (ApiErrorId.ERR_LOT_NOT_FOUND,
         api.release_sample_lot(UNKNOWN_UUIDS["lot"], LAB_TECH)),
        (ApiErrorId.ERR_CABINET_NOT_FOUND,
         api.get_retention_cabinet(UNKNOWN_UUIDS["cabinet"], LAB_TECH)),
        (ApiErrorId.ERR_RETENTION_NOT_FOUND,
         api.withdraw_retention_sample(UNKNOWN_UUIDS["retention"],
                                       withdraw_retention_sample_payload(
                                           "customer request"),
                                       LAB_TECH)),
        (ApiErrorId.ERR_RIG_NOT_FOUND,
         api.get_application_rig(UNKNOWN_UUIDS["rig"], LAB_TECH)),
        (ApiErrorId.ERR_TEST_NOT_FOUND,
         api.start_application_test(UNKNOWN_UUIDS["test"], LAB_TECH)),
        (ApiErrorId.ERR_SHIPMENT_NOT_FOUND,
         api.cancel_shipment(UNKNOWN_UUIDS["shipment"],
                             cancel_shipment_payload("customer hold"),
                             ACCOUNT_MANAGER)),
        (ApiErrorId.ERR_DOCUMENT_NOT_FOUND,
         api.get_regulatory_document(UNKNOWN_UUIDS["document"],
                                     REGULATORY_AFFAIRS)),
        (ApiErrorId.ERR_BATCH_NOT_FOUND,
         api.set_batch_tolerance(UNKNOWN_UUIDS["batch"], DIRECTOR_APPROVER)),
        (ApiErrorId.ERR_FORECAST_NOT_FOUND,
         api.get_commercialization_forecast(UNKNOWN_UUIDS["forecast"],
                                            ACCOUNT_MANAGER)),
        (ApiErrorId.ERR_GRANT_NOT_FOUND,
         api.get_disclosure_grant(UNKNOWN_UUIDS["grant"], DIRECTOR_APPROVER)),
    ]

    assert len(probes) == 15
    for expected, response in probes:
        validate_error(response, expected.value, 404)
        body = response.json()
        assert_envelope_meta(body, "error")
        assert isinstance(body["data"]["message"], str)
        assert body["data"]["message"] != ""


def test_every_body_foreign_key_family_reports_its_own_not_found_error_id(api):
    """Seven dangling body and query references answer the expected entity's 404.

    Section 2.5: "The same not-found errors are used for identifiers supplied
    inside a request body or a query string rather than in the path.  Whenever a
    create or read operation names another record — `brief_id`,
    `raw_material_id`, `sub_formula_id`, `formula_id`, `sample_lot_id`,
    `cabinet_id`, `rig_id`, `grant_id`, `substantiation_id` or `shipment_id` —
    the referenced record must exist, and a dangling reference is reported with
    the not-found error of the entity type that was expected.  This applies to
    certificate filing, formula creation, component addition, sample-lot
    compounding, retention storage, application-test scheduling, shipment
    creation, scale-up requests, forecast publication, disclosure-grant issuance
    and composition reads."  A rejected call writes nothing, so the lot's gram
    ledger and the cabinet's occupancy are untouched.

    Design: Corner/errors/every_body_foreign_key_family_reports_its_own_not_found_error_id
    """
    material = create_material(api, material_code="GUM-BASE")
    brief = create_accepted_brief(api, brief_code="BRF-0001")
    formula = build_approved_formula(api, brief["id"], material["id"], 100.0)
    lot = build_released_lot(api, formula["id"], batch_size_g=500)
    cabinet = create_cabinet(api, cabinet_code="CAB-A", capacity_slots=10)

    probes = [
        (ApiErrorId.ERR_BRIEF_NOT_FOUND,
         api.create_formula(
             create_formula_payload(UNKNOWN_UUIDS["brief"],
                                    name="Orphan formula"),
             FLAVORIST)),
        (ApiErrorId.ERR_MATERIAL_NOT_FOUND,
         api.create_substantiation_record(
             create_substantiation_record_payload(UNKNOWN_UUIDS["material"],
                                                  "KOSHER"),
             REGULATORY_AFFAIRS)),
        (ApiErrorId.ERR_FORMULA_NOT_FOUND,
         api.create_sample_lot(
             create_sample_lot_payload(UNKNOWN_UUIDS["formula"], 100),
             LAB_COMPOUNDER)),
        (ApiErrorId.ERR_LOT_NOT_FOUND,
         api.create_retention_sample(
             create_retention_sample_payload(UNKNOWN_UUIDS["lot"], cabinet["id"],
                                             100, RETENTION_FROM,
                                             RETENTION_UNTIL),
             LAB_COMPOUNDER)),
        (ApiErrorId.ERR_CABINET_NOT_FOUND,
         api.create_retention_sample(
             create_retention_sample_payload(lot["id"], UNKNOWN_UUIDS["cabinet"],
                                             100, RETENTION_FROM,
                                             RETENTION_UNTIL),
             LAB_COMPOUNDER)),
        (ApiErrorId.ERR_RIG_NOT_FOUND,
         api.create_application_test(
             create_application_test_payload(lot["id"], UNKNOWN_UUIDS["rig"],
                                             "2026-08-02T08:00:00Z",
                                             "2026-08-02T10:00:00Z", 1.0, 20),
             LAB_COMPOUNDER)),
        (ApiErrorId.ERR_GRANT_NOT_FOUND,
         api.get_formula_composition(formula["id"], ACCOUNT_MANAGER,
                                     grant_id=UNKNOWN_UUIDS["grant"])),
    ]

    assert len(probes) == 7
    for expected, response in probes:
        validate_error(response, expected.value, 404)

    assert list_data(api, api.list_formulas, FLAVORIST)["meta"]["total_count"] == 1
    assert list_data(api, api.list_sample_lots,
                     LAB_COMPOUNDER)["meta"]["total_count"] == 1
    assert list_data(api, api.list_retention_samples,
                     LAB_COMPOUNDER)["meta"]["total_count"] == 0
    assert list_data(api, api.list_application_tests,
                     LAB_COMPOUNDER)["meta"]["total_count"] == 0
    assert list_data(api, api.list_substantiation_records,
                     REGULATORY_AFFAIRS)["meta"]["total_count"] == 0
    assert read_lot(api, lot["id"])["available_g"] == 500
    assert read_cabinet(api, cabinet["id"])["slots_available"] == 10


def test_repeating_a_terminal_action_reports_the_owning_entity_state_invalid_code(api):
    """A second withdrawal, a second cancellation and a second tolerance all 409.

    Section 3.6 says withdrawal "refuses with `ERR_RETENTION_STATE_INVALID` if
    the aliquot's `status` is already `WITHDRAWN`"; §3.8 says a cancellation
    "is accepted from `DRAFT`, `PACKET_ASSEMBLED` or `BLOCKED` and refused from
    `DISPATCHED` or `CANCELLED` as `ERR_SHIPMENT_STATE_INVALID`"; and §3.9 says
    setting tolerance "is
    accepted from `REQUESTED` and from `REJECTED` ... from any other status it is
    `ERR_BATCH_STATE_INVALID`".  A store-then-withdraw pair and a
    ship-then-cancel pair "each return `available_g` to precisely its prior
    value", and the refused repeats leave every stored reason as first written.

    Design: Corner/errors/repeating_a_terminal_action_reports_the_owning_entity_state_invalid_code
    """
    material = create_material(api, material_code="GUM-BASE")
    brief = create_accepted_brief(api, brief_code="BRF-0001")
    formula = build_approved_formula(api, brief["id"], material["id"], 100.0)
    lot = build_released_lot(api, formula["id"], batch_size_g=500)
    cabinet = create_cabinet(api, cabinet_code="CAB-A", capacity_slots=10)

    aliquot = store_retention_sample(api, lot["id"], cabinet["id"], quantity_g=100)
    withdraw_retention_sample(api, aliquot["id"], "customer request")
    shipment = create_shipment(api, lot["id"], shipped_g=100)
    cancel_shipment(api, shipment["id"], "customer hold")
    batch = request_scale_up_batch(api, formula["id"], target_kg=150)
    toleranced = set_batch_tolerance(api, batch["id"])
    assert toleranced["status"] == "TOLERANCE_SET"

    repeat_withdrawal = api.withdraw_retention_sample(
        aliquot["id"], withdraw_retention_sample_payload("second attempt"),
        LAB_COMPOUNDER)
    validate_error(repeat_withdrawal,
                   ApiErrorId.ERR_RETENTION_STATE_INVALID.value, 409)

    repeat_cancellation = api.cancel_shipment(
        shipment["id"], cancel_shipment_payload("second attempt"), ACCOUNT_MANAGER)
    validate_error(repeat_cancellation,
                   ApiErrorId.ERR_SHIPMENT_STATE_INVALID.value, 409)

    repeat_tolerance = api.set_batch_tolerance(batch["id"], DIRECTOR_APPROVER)
    validate_error(repeat_tolerance, ApiErrorId.ERR_BATCH_STATE_INVALID.value, 409)

    stored_aliquot = read_retention_sample(api, aliquot["id"])
    assert stored_aliquot["status"] == "WITHDRAWN"
    assert stored_aliquot["withdrawal_reason"] == "customer request"

    stored_shipment = read_shipment(api, shipment["id"])
    assert stored_shipment["status"] == "CANCELLED"
    assert stored_shipment["cancellation_reason"] == "customer hold"

    assert read_batch(api, batch["id"])["status"] == "TOLERANCE_SET"
    assert read_cabinet(api, cabinet["id"])["slots_available"] == 10
    assert read_lot(api, lot["id"])["available_g"] == 500


def test_revising_a_draft_formula_reports_not_revisable_even_with_the_current_version(api):
    """The version pin is right; the DRAFT status is what refuses the revision.

    Section 3.5 opens revisions only on a formula "that is either `APPROVED` or
    `REWORK_REQUIRED`; on a formula in any other status the request is refused
    with `ERR_FORMULA_NOT_REVISABLE`".  Section 2.11 puts own-state at step 9,
    ahead of any concurrency complaint, so a correct `expected_formula_version`
    cannot rescue a `DRAFT` formula and no successor row is created.

    Design: Corner/errors/revising_a_draft_formula_reports_not_revisable_even_with_the_current_version
    """
    material = create_material(api, material_code="GUM-BASE")
    brief = create_accepted_brief(api, brief_code="BRF-0001")
    formula = create_formula(api, brief["id"], name="Vanilla Cream F1")
    add_material_line(api, formula["id"], material["id"], 100.0)

    observed = read_formula(api, formula["id"])
    assert observed["status"] == "DRAFT"

    response = api.create_formula_revision(
        formula["id"],
        create_formula_revision_payload("Vanilla Cream F1 rev A",
                                        observed["version"]),
        FLAVORIST)
    validate_error(response, ApiErrorId.ERR_FORMULA_NOT_REVISABLE.value, 409)

    unchanged = read_formula(api, formula["id"])
    assert unchanged["status"] == "DRAFT"
    assert unchanged["version"] == observed["version"]
    assert list_data(api, api.list_formulas, FLAVORIST)["meta"]["total_count"] == 1


def test_costing_a_formula_whose_sub_formula_is_uncosted_rejected(api):
    """An uncosted child blocks the parent, and costing the child unblocks it.

    Section 3.4 requires of costing that "every sub-formula line must reference a
    formula whose own status is either `COSTED` or `APPROVED`, so that its cost
    is already known; referencing a sub-formula in any other status is
    `ERR_SUB_FORMULA_NOT_COSTED`", which §2.11 step 10 reports with HTTP 409.
    Once the child is costed the parent's own roll-up runs: 2000 x 50 / 100
    twice sums to 2000 cents per kilogram.

    Design: Corner/errors/costing_a_formula_whose_sub_formula_is_uncosted_rejected
    """
    material = create_material(api, material_code="GUM-BASE")
    brief = create_accepted_brief(api, brief_code="BRF-0001")

    child = create_formula(api, brief["id"], name="Vanilla Base SUB")
    add_material_line(api, child["id"], material["id"], 100.0)

    parent = create_formula(api, brief["id"], name="Vanilla Cream PARENT")
    api_response = api.add_formula_component(
        parent["id"], sub_formula_component_payload(child["id"], 50.0), FLAVORIST)
    get_success_data(api_response, 201)
    add_material_line(api, parent["id"], material["id"], 50.0)

    refused = api.cost_formula(parent["id"], FLAVORIST)
    validate_error(refused, ApiErrorId.ERR_SUB_FORMULA_NOT_COSTED.value, 409)

    blocked = read_formula(api, parent["id"])
    assert blocked["status"] == "DRAFT"
    assert blocked["component_count"] == 2
    assert float(blocked["total_weight_pct"]) == 100.0
    assert blocked["bench_cost_per_kg_cents"] is None

    still_draft_child = read_formula(api, child["id"])
    assert still_draft_child["status"] == "DRAFT"
    assert still_draft_child["bench_cost_per_kg_cents"] is None

    cost_formula(api, child["id"])
    costed_parent = cost_formula(api, parent["id"])
    assert costed_parent["bench_cost_per_kg_cents"] == 2000
