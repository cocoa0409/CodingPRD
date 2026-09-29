"""
Entity lifecycle tests for the Urology Practice & In-Office Procedure Suite API.

These tests exercise the plain record-keeping surface of the contract: what a
create returns, what a read returns, which inputs are required, which fields the
service defaults or computes for itself, how the four common properties behave
across successive mutations, and how each collection read paginates and filters.

Every test builds its own practice from scratch through the API, because the
service under test is restarted with an empty database before each test.
"""

import re
from typing import Any, Dict

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_DUPLICATE_MRN,
    ERR_INVALID_REQUEST,
    ERR_PATIENT_NOT_FOUND,
    ERR_SCOPE_NOT_FOUND,
)
from test_helpers.assertions import (
    assert_ascending_created_at,
    assert_fields,
    assert_freshly_created,
    assert_ids_in_order,
    assert_lot_counters,
    assert_no_fields,
    assert_null_fields,
    assert_pagination_meta,
)
from test_helpers.constants import (
    AGENT_AUTO,
    AGENT_CIPROFLOXACIN,
    ALLERGY_SULFA,
    ANTIBIOTIC_ORDERED,
    BILLING_PROVISIONAL,
    BILLING_STATUS_CONSIGNED,
    CASE_DRAFT,
    CHAIN_COLLECTED,
    CLEANUP_HIGH,
    CLEANUP_LOW,
    CLEARANCE_DECISION_CLEAR,
    CLEARANCE_PENDING_PREP,
    CREDENTIAL_ACTIVE,
    DEVICE_CLASS_BIOPSY_NEEDLE,
    DEVICE_CLASS_URODYNAMICS_CATHETER_KIT,
    DEVICE_STATE_NONE,
    LOG_OPEN,
    NOTIFY_NOT_REQUIRED,
    ROLE_TYPE_RN,
    ROLE_TYPE_SCHEDULER,
    ROLE_TYPE_TECH,
    ROLE_TYPE_UROLOGIST,
    ROOM_STATUS_OPEN,
    ROOM_TYPE_CYSTO_SUITE,
    ROOM_TYPE_IMAGING_BAY,
    SCOPE_AVAILABLE,
    SPECIMEN_PROSTATE_CORE,
    STAGE_PRECLEAN,
    TYPE_CYSTOSCOPY,
    TYPE_OFFICE_ULTRASOUND,
    TYPE_PROSTATE_BIOPSY,
)
from test_helpers.test_users import (
    make_procedure_nurse_headers,
    make_scheduler_headers,
    make_sterile_processing_tech_headers,
    make_urologist_headers,
)

# A well-formed UUID that names no row in any collection.
UNKNOWN_UUID = "00000000-0000-4000-8000-000000000000"
UNKNOWN_PATIENT_UUID = "00000000-0000-4000-8000-0000000000aa"

_INSTANT_PATTERN = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}(?:Z|\+00:00)$"
)


def _normalise_instant(value: Any) -> Any:
    """Render an instant in the single canonical UTC form for comparison."""
    if isinstance(value, str):
        return value.replace("+00:00", "Z")
    return value


def assert_instant_equals(actual: Any, expected: str, field: str) -> None:
    """Assert an instant field holds exactly the expected UTC instant."""
    assert _normalise_instant(actual) == _normalise_instant(expected), (
        f"{field}: expected {expected!r}, got {actual!r}"
    )


def assert_millisecond_instant(value: Any, field: str) -> None:
    """Assert a timestamp is UTC with exactly three fractional-second digits."""
    assert isinstance(value, str) and _INSTANT_PATTERN.match(value), (
        f"{field} must be an ISO 8601 UTC instant with exactly three "
        f"fractional-second digits, got {value!r}"
    )


def assert_envelope_meta(response, response_type: str) -> Dict[str, Any]:
    """Assert the standard success envelope and return its ``meta`` object."""
    body = response.json()
    assert body.get("response_type") == response_type, (
        f"response_type: expected {response_type!r}, got {body.get('response_type')!r}"
    )
    meta = body["meta"]
    assert isinstance(meta.get("api_request_id"), str) and meta[
        "api_request_id"
    ].startswith("req_"), (
        f"api_request_id must start with 'req_', got {meta.get('api_request_id')!r}"
    )
    assert_millisecond_instant(meta.get("api_request_timestamp"), "api_request_timestamp")
    return meta


def register_provider(api, admin_headers, role_type: str, full_name: str, npi: str, **kwargs):
    """Put one clinician or staff member on the roster and return the row."""
    response = api.create_provider(
        f.provider_payload(
            role_type=role_type, full_name=full_name, npi=npi, **kwargs
        ),
        admin_headers,
    )
    return validate_success(response, 201)


# ───────────────────────── Creating a provider ──────────────────────────────
def test_provider_registration_echoes_every_input_and_defaults_credential_status(
    api, admin_headers
):
    """PRD 3.1: "Registering a clinician or staff member records their `full_name` and their `npi`, the ten-character national provider identifier that must be unique across the roster, together with the `role_type` that governs which header role they may subsequently authenticate as — one of `UROLOGIST`, `RN`, `TECH`, `SCHEDULER`, `PATHOLOGY_LIAISON` or `PELVIC_COORDINATOR`."
    PRD 3.1: "`credential_status` is never supplied at registration; it always begins as `ACTIVE`, its only other value being `SUSPENDED`."
    PRD 2.4: "`version` is an integer that starts at 1 when the row is created and increases by exactly 1 on every mutation of that row."

    Design: Corner/entities/entity_creation_provider_full_payload
    """
    response = api.create_provider(
        f.provider_payload(
            role_type=ROLE_TYPE_UROLOGIST,
            full_name="Dr Ada Nour",
            npi="1000000001",
            hld_certified=False,
            ultrasound_accreditation_expires_on="2027-03-31",
        ),
        admin_headers,
    )
    provider = validate_success(response, 201)
    assert_envelope_meta(response, "object")

    assert_fields(
        provider,
        full_name="Dr Ada Nour",
        npi="1000000001",
        role_type=ROLE_TYPE_UROLOGIST,
        hld_certified=False,
        ultrasound_accreditation_expires_on="2027-03-31",
        credential_status=CREDENTIAL_ACTIVE,
    )
    assert_freshly_created(provider)
    assert_millisecond_instant(provider["created_at"], "created_at")
    assert_millisecond_instant(provider["updated_at"], "updated_at")
    assert "-" in provider["id"] and ":" not in provider["id"], (
        f"id must be a bare UUID with no type prefix, got {provider['id']!r}"
    )


# ───────────────────────── Reading a patient back ───────────────────────────
def test_patient_read_returns_the_stored_row_with_both_counters_at_zero(
    api, admin_headers
):
    """PRD 3.1: "Each patient also exposes two derived counters that the service maintains and the client never writes: `outstanding_recall_count`, the number of that patient's surveillance recalls whose `status` is either `SCHEDULED_DUE` or `OVERDUE`, and `open_notification_count`, the number of specimens belonging to that patient's cases whose `notification_status` is `PENDING`, `ATTEMPTED` or `ESCALATED`. Both initialise to 0."
    PRD 2.4: "`version` is an integer that starts at 1 when the row is created and increases by exactly 1 on every mutation of that row."

    Design: Corner/entities/entity_retrieval_patient_round_trip
    """
    urologist = register_provider(
        api, admin_headers, ROLE_TYPE_UROLOGIST, "Dr Ada Nour", "1000000001"
    )

    created = validate_success(
        api.create_patient(
            f.patient_payload(
                primary_urologist_id=urologist["id"],
                mrn="MRN-5001",
                full_name="Jonas Peil",
                date_of_birth="1964-04-14",
                egfr=72,
                anticoagulant_flag=True,
                antibiotic_allergy_class=ALLERGY_SULFA,
            ),
            admin_headers,
        ),
        201,
    )

    fetched = validate_success(api.get_patient(created["id"], admin_headers))

    assert fetched["id"] == created["id"], (
        f"read returned a different row: expected {created['id']}, got {fetched['id']}"
    )
    assert_fields(
        fetched,
        mrn="MRN-5001",
        full_name="Jonas Peil",
        date_of_birth="1964-04-14",
        egfr=72,
        anticoagulant_flag=True,
        antibiotic_allergy_class=ALLERGY_SULFA,
        primary_urologist_id=urologist["id"],
        outstanding_recall_count=0,
        open_notification_count=0,
    )
    assert fetched["version"] == created["version"] == 1, (
        "a read is not a mutation, so version must still be 1, got "
        f"{fetched['version']} after reading a row created at "
        f"version {created['version']}"
    )


# ───────────────────────── Unknown identifiers ──────────────────────────────
def test_reading_an_unknown_scope_asset_answers_scope_not_found(api, admin_headers):
    """PRD 2.8: "Path parameters resolve to their declared entity, evaluated strictly left to right. The error is the not-found code of the first path segment that fails to resolve, chosen from `ERR_PATIENT_NOT_FOUND`, `ERR_PROVIDER_NOT_FOUND`, `ERR_ROOM_NOT_FOUND`, `ERR_PROCEDURE_TYPE_NOT_FOUND`, `ERR_CASE_NOT_FOUND`, `ERR_SCOPE_NOT_FOUND`, `ERR_REPROCESSING_LOG_NOT_FOUND`, `ERR_SPECIMEN_NOT_FOUND`, `ERR_RECALL_NOT_FOUND`, `ERR_REFERRAL_NOT_FOUND`, `ERR_LOT_NOT_FOUND` or `ERR_ANTIBIOTIC_ORDER_NOT_FOUND`, all HTTP 404."
    PRD 2.2: "The `error_id` is a unique, machine-readable string that identifies the specific error."

    Design: Corner/entities/entity_not_found_scope_asset_unknown_id
    """
    tech = register_provider(
        api, admin_headers, ROLE_TYPE_TECH, "Omar Diaz", "1000000004"
    )
    tech_headers = make_sterile_processing_tech_headers(tech["id"])

    response = api.get_scope_asset(UNKNOWN_UUID, tech_headers)
    error = validate_error(response, ERR_SCOPE_NOT_FOUND)

    assert response.json().get("response_type") == "error", (
        f"expected the error envelope, got response_type "
        f"{response.json().get('response_type')!r}"
    )
    assert isinstance(error.get("message"), str) and error["message"].strip(), (
        f"message must be a non-empty human-readable string, got {error.get('message')!r}"
    )
    assert_no_fields(error, "id", "serial_number", "status", "version", "created_at")


# ───────────────────────── Required inputs ──────────────────────────────────
def test_patient_registration_without_egfr_is_rejected_and_persists_nothing(
    api, admin_headers
):
    """PRD 3.1: "The payload carries `mrn` — the medical record number, unique across all patients, a duplicate drawing `ERR_DUPLICATE_MRN` — plus `full_name`, `date_of_birth` as an `YYYY-MM-DD` date, `primary_urologist_id` naming the Provider who will carry the patient, and `egfr`, the estimated glomerular filtration rate, which may not be negative."
    PRD 2.8: "The body parses; every required input field named for that operation in §3 is present; every enum-valued field carries a declared member; every integer field is a non-negative integer; every date and datetime field is ISO 8601; and `limit` and `offset` are integers satisfying the bounds of §2.3. Otherwise `ERR_INVALID_REQUEST`, HTTP 400."

    Design: Corner/entities/entity_required_fields_patient_missing_required_egfr
    """
    urologist = register_provider(
        api, admin_headers, ROLE_TYPE_UROLOGIST, "Dr Ada Nour", "1000000001"
    )

    payload = {
        "mrn": "MRN-5004",
        "full_name": "Nadia Ruhl",
        "date_of_birth": "1977-03-03",
        "primary_urologist_id": urologist["id"],
    }
    validate_error(api.create_patient(payload, admin_headers), ERR_INVALID_REQUEST)

    rows, meta = validate_paginated(api.list_patients(admin_headers))
    assert meta["total_count"] == 0, (
        f"a rejected registration must persist nothing, but {meta['total_count']} "
        "patient(s) exist"
    )
    assert rows == [], f"expected no patient rows, got {rows}"


# ───────────────────────── Closed enumerations ──────────────────────────────
def test_room_commissioned_with_an_undeclared_room_type_is_a_malformed_request(
    api, admin_headers
):
    """PRD 3.1: "Procedure rooms are commissioned with a `name` that must be unique across the suite — a collision is `ERR_DUPLICATE_ROOM_NAME` — and a `room_type` of `CYSTO_SUITE`, `URODYNAMICS_LAB` or `IMAGING_BAY`."
    PRD 2.8: "The body parses; every required input field named for that operation in §3 is present; every enum-valued field carries a declared member; every integer field is a non-negative integer; every date and datetime field is ISO 8601; and `limit` and `offset` are integers satisfying the bounds of §2.3. Otherwise `ERR_INVALID_REQUEST`, HTTP 400."

    Design: Corner/entities/entity_type_constraints_room_type_invalid_enum
    """
    response = api.create_procedure_room(
        {"name": "Endoscopy Annex", "room_type": "ENDOSCOPY_ANNEX"}, admin_headers
    )
    validate_error(response, ERR_INVALID_REQUEST)

    rows, meta = validate_paginated(api.list_procedure_rooms(admin_headers))
    assert meta["total_count"] == 0, (
        "an undeclared room_type must commission no room, but "
        f"{meta['total_count']} room(s) exist"
    )
    assert rows == [], f"expected no room rows, got {rows}"


# ───────────────────────── Natural-key uniqueness ───────────────────────────
def test_second_patient_claiming_the_same_mrn_is_a_conflict(api, admin_headers):
    """PRD 3.1: "The payload carries `mrn` — the medical record number, unique across all patients, a duplicate drawing `ERR_DUPLICATE_MRN` — plus `full_name`, `date_of_birth` as an `YYYY-MM-DD` date, `primary_urologist_id` naming the Provider who will carry the patient, and `egfr`, the estimated glomerular filtration rate, which may not be negative."
    PRD 2.8: "`Patient.mrn`, `ProcedureType.code`, `ProcedureRoom.name` and `ScopeAsset.serial_number` are unique globally, and `Specimen.container_label` is unique within a single `case_id`."

    Design: Corner/entities/entity_creation_duplicate_mrn_rejected
    """
    urologist = register_provider(
        api, admin_headers, ROLE_TYPE_UROLOGIST, "Dr Ada Nour", "1000000001"
    )
    first = validate_success(
        api.create_patient(
            f.patient_payload(
                primary_urologist_id=urologist["id"],
                mrn="MRN-5006",
                full_name="First Holder",
                date_of_birth="1960-01-01",
                egfr=60,
            ),
            admin_headers,
        ),
        201,
    )

    response = api.create_patient(
        f.patient_payload(
            primary_urologist_id=urologist["id"],
            mrn="MRN-5006",
            full_name="Second Claimant",
            date_of_birth="1988-08-08",
            egfr=90,
        ),
        admin_headers,
    )
    validate_error(response, ERR_DUPLICATE_MRN)

    rows, meta = validate_paginated(api.list_patients(admin_headers, mrn="MRN-5006"))
    assert meta["total_count"] == 1, (
        f"MRN-5006 must be held by exactly one patient, got {meta['total_count']}"
    )
    assert_ids_in_order(rows, [first["id"]])
    assert rows[0]["full_name"] == "First Holder", (
        "the incumbent patient must survive the rejected duplicate, got "
        f"{rows[0]['full_name']!r}"
    )


# ───────────────────────── Server-computed lot counters ─────────────────────
def test_received_consignment_lot_computes_its_unit_and_billing_counters(
    api, admin_headers
):
    """PRD 3.6: "On receipt `quantity_available` is set equal to `quantity_received` and `quantity_reserved`, `quantity_consumed`, `quantity_returned` and `quantity_wasted` all start at 0; `billed_amount_cents` starts at 0, `billing_basis` at `PROVISIONAL` and `billing_status` at `CONSIGNED`."
    PRD 2.10: "For a consignment lot, `quantity_received` is the conserved total: at every observable moment it equals the sum of `quantity_available`, `quantity_reserved`, `quantity_consumed`, `quantity_returned` and `quantity_wasted`."

    Design: Corner/entities/entity_computed_fields_lot_counters_at_creation
    """
    response = api.create_consignment_lot(
        f.consignment_lot_payload(
            supplier_name="Meridian Devices",
            sku="BX-NEEDLE-18G",
            device_class=DEVICE_CLASS_BIOPSY_NEEDLE,
            quantity_received=10,
            unit_price_cents=1999,
            lot_expires_on="2027-06-30",
        ),
        admin_headers,
    )
    lot = validate_success(response, 201)

    assert lot["quantity_received"] == 10, (
        f"quantity_received: expected 10, got {lot['quantity_received']}"
    )
    assert_lot_counters(lot, available=10, reserved=0, consumed=0, returned=0, wasted=0)
    assert_fields(
        lot,
        billed_amount_cents=0,
        billing_basis=BILLING_PROVISIONAL,
        billing_status=BILLING_STATUS_CONSIGNED,
    )
    assert_freshly_created(lot)


# ───────────────────────── The four common properties ───────────────────────
def test_room_version_advances_by_one_on_each_administrative_edit(api, admin_headers):
    """PRD 2.4: "`version` is an integer that starts at 1 when the row is created and increases by exactly 1 on every mutation of that row."
    PRD 3.1: "Administrative edits may change `room_status`, `turnover_minutes`, `accreditation_body` and `accreditation_expires_on`, each optional; any such edit increments the room's `version` — which is what invalidates a client's held `expected_room_version` — and, like the patient edit, does not retune the turnover already baked into cases sitting on that room's calendar."

    Design: Corner/entities/entity_system_fields_envelope_and_version
    """
    created = validate_success(
        api.create_procedure_room(
            f.procedure_room_payload(
                room_type=ROOM_TYPE_IMAGING_BAY, name="Imaging Bay 1"
            ),
            admin_headers,
        ),
        201,
    )
    assert created["version"] == 1, (
        f"a newly commissioned room starts at version 1, got {created['version']}"
    )

    after_first = validate_success(
        api.update_procedure_room(
            created["id"], {"turnover_minutes": 12}, admin_headers
        )
    )
    assert after_first["version"] == 2, (
        f"the first edit must take version to 2, got {after_first['version']}"
    )

    after_second = validate_success(
        api.update_procedure_room(
            created["id"],
            {"accreditation_body": "ACR", "accreditation_expires_on": "2027-05-31"},
            admin_headers,
        )
    )
    assert after_second["version"] == 3, (
        f"the second edit must take version to 3, got {after_second['version']}"
    )

    response = api.get_procedure_room(created["id"], admin_headers)
    fetched = validate_success(response)
    assert_envelope_meta(response, "object")

    assert_fields(
        fetched,
        name="Imaging Bay 1",
        room_type=ROOM_TYPE_IMAGING_BAY,
        turnover_minutes=12,
        accreditation_body="ACR",
        accreditation_expires_on="2027-05-31",
        version=3,
    )
    assert_instant_equals(fetched["created_at"], created["created_at"], "created_at")
    # PRD 2.4 says only that `updated_at` is "refreshed" on a mutation, and PRD 2.5
    # pins every timestamp to a logical clock that "must never fall back to real time"
    # and that only a PracticeAdmin advances. With the clock left at its opening
    # instant, a refresh legitimately reproduces `created_at`, so no strictly-later
    # `updated_at` is derivable from PRD prose. Only the rendering rule is asserted.
    assert_millisecond_instant(fetched["created_at"], "created_at")
    assert_millisecond_instant(fetched["updated_at"], "updated_at")


# ───────────────────────── Declared defaults ────────────────────────────────
def test_room_commissioned_with_only_a_name_and_type_takes_every_declared_default(
    api, admin_headers
):
    """PRD 3.1: "Three optional attributes may be supplied: `turnover_minutes`, the room's baseline cleaning allowance, which may not be negative and defaults to 10 minutes; `accreditation_body`, the accrediting organisation for in-office imaging and ultrasound work in that room, defaulting to null; and `accreditation_expires_on`, an `YYYY-MM-DD` date defaulting to null, where null means the room has never been accredited."
    PRD 3.1: "`room_status` is not an input: a newly commissioned room is `OPEN`, its only other value being `CLOSED`."
    PRD 3.1: "Each room also exposes `occupied_block_count`, a derived count of the cases naming that room whose `schedule_status` is `SCHEDULED`, `IN_ROOM` or `COMPLETED`; it initialises to 0."

    Design: Corner/entities/entity_defaults_room_and_case_defaults
    """
    room = validate_success(
        api.create_procedure_room(
            {"name": "Cysto Default", "room_type": ROOM_TYPE_CYSTO_SUITE},
            admin_headers,
        ),
        201,
    )

    assert_fields(
        room,
        name="Cysto Default",
        room_type=ROOM_TYPE_CYSTO_SUITE,
        room_status=ROOM_STATUS_OPEN,
        turnover_minutes=10,
        occupied_block_count=0,
    )
    assert_null_fields(room, "accreditation_body", "accreditation_expires_on")
    assert_freshly_created(room)


def test_bare_draft_case_takes_its_declared_defaults_and_derived_window(
    api, admin_headers
):
    """PRD 3.2: "The new case is created with `schedule_status` `DRAFT`, `clearance_status` `PENDING_PREP`, `device_state` `NONE` and `acknowledged_prep_codes` as the empty array."
    PRD 3.2: "First the room's own `turnover_minutes` is multiplied by a cleanup multiplier of 2 when the procedure type's `cleanup_class` is `HIGH` and by 1 when it is `LOW`."
    PRD 3.2: "`scheduled_end_at` is `scheduled_start_at` advanced by `procedure_minutes` minutes, and `block_end_at` is `scheduled_end_at` advanced by `turnover_minutes` minutes."

    Design: Corner/entities/entity_defaults_room_and_case_defaults
    """
    urologist = register_provider(
        api, admin_headers, ROLE_TYPE_UROLOGIST, "Dr Ada Nour", "1000000001"
    )
    scheduler = register_provider(
        api, admin_headers, ROLE_TYPE_SCHEDULER, "Sam Reyes", "1000000002"
    )
    scheduler_headers = make_scheduler_headers(scheduler["id"])

    patient = validate_success(
        api.create_patient(
            f.patient_payload(
                primary_urologist_id=urologist["id"],
                mrn="MRN-5005",
                full_name="Owen Vale",
                date_of_birth="1965-05-05",
                egfr=60,
            ),
            admin_headers,
        ),
        201,
    )
    procedure_type = validate_success(
        api.create_procedure_type(
            f.procedure_type_payload(
                code=TYPE_CYSTOSCOPY,
                base_minutes=20,
                cleanup_class=CLEANUP_HIGH,
                allowed_room_type=ROOM_TYPE_CYSTO_SUITE,
                required_prep_codes=[],
            ),
            admin_headers,
        ),
        201,
    )
    validate_success(api.set_clock("2026-09-14T07:00:00.000Z", admin_headers))

    # The room is commissioned with no turnover allowance of its own, so the
    # case's window must be derived from the declared 10-minute default.
    room = validate_success(
        api.create_procedure_room(
            {"name": "Cysto Default", "room_type": ROOM_TYPE_CYSTO_SUITE},
            admin_headers,
        ),
        201,
    )

    case = validate_success(
        api.create_procedure_case(
            f.procedure_case_payload(
                patient_id=patient["id"],
                procedure_type_id=procedure_type["id"],
                room_id=room["id"],
                primary_provider_id=urologist["id"],
                scheduled_start_at="2026-09-14T14:00:00.000Z",
            ),
            scheduler_headers,
        ),
        201,
    )

    assert_fields(
        case,
        schedule_status=CASE_DRAFT,
        clearance_status=CLEARANCE_PENDING_PREP,
        device_state=DEVICE_STATE_NONE,
        acknowledged_prep_codes=[],
        procedure_minutes=20,
        turnover_minutes=20,
    )
    assert_null_fields(
        case,
        "scope_asset_id",
        "checked_in_at",
        "completed_at",
        "clearance_block_reason",
        "cancel_reason_code",
        "indication_note",
    )
    assert_instant_equals(
        case["scheduled_start_at"], "2026-09-14T14:00:00.000Z", "scheduled_start_at"
    )
    assert_instant_equals(
        case["scheduled_end_at"], "2026-09-14T14:20:00.000Z", "scheduled_end_at"
    )
    assert_instant_equals(
        case["block_end_at"], "2026-09-14T14:40:00.000Z", "block_end_at"
    )
    assert_freshly_created(case)


def test_procedure_type_obligation_flags_and_device_sku_default_off(api, admin_headers):
    """PRD 3.1: "Four boolean obligations then declare what a case of this type needs before a patient may be brought in: `requires_scope`, `requires_specimen`, `requires_antibiotic` and `consignment_required`. All four are optional in the payload and all four default to `false`."
    PRD 3.1: "Where `consignment_required` is true, `single_use_device_sku` names the only catalogue number acceptable for that type's device reservation; it defaults to null."

    Design: Corner/entities/entity_defaults_room_and_case_defaults
    """
    created = validate_success(
        api.create_procedure_type(
            {
                "code": TYPE_CYSTOSCOPY,
                "base_minutes": 20,
                "cleanup_class": CLEANUP_HIGH,
                "allowed_room_type": ROOM_TYPE_CYSTO_SUITE,
                "required_prep_codes": [],
            },
            admin_headers,
        ),
        201,
    )

    fetched = validate_success(api.get_procedure_type(created["id"], admin_headers))
    assert_fields(
        fetched,
        code=TYPE_CYSTOSCOPY,
        base_minutes=20,
        cleanup_class=CLEANUP_HIGH,
        allowed_room_type=ROOM_TYPE_CYSTO_SUITE,
        requires_scope=False,
        requires_specimen=False,
        requires_antibiotic=False,
        consignment_required=False,
        required_prep_codes=[],
    )
    assert_null_fields(fetched, "single_use_device_sku")


# ───────────────────────── Body reference resolution ────────────────────────
def test_drafting_a_case_against_an_unknown_patient_names_the_patient_as_missing(
    api, admin_headers
):
    """PRD 3.2: "Those four references are resolved in exactly the order listed, so a payload naming both a non-existent patient and a non-existent room reports `ERR_PATIENT_NOT_FOUND`."
    PRD 2.8: "Foreign keys carried in the body resolve, evaluated in the order the fields are listed for that operation. On case drafting that order is `patient_id`, then `procedure_type_id`, then `room_id`, then `primary_provider_id`. The error is the matching not-found code for the first field that cannot be resolved, HTTP 404."

    Design: Corner/entities/entity_parent_relationships_case_unknown_patient_not_found
    """
    urologist = register_provider(
        api, admin_headers, ROLE_TYPE_UROLOGIST, "Dr Ada Nour", "1000000001"
    )
    scheduler = register_provider(
        api, admin_headers, ROLE_TYPE_SCHEDULER, "Sam Reyes", "1000000002"
    )
    scheduler_headers = make_scheduler_headers(scheduler["id"])

    room = validate_success(
        api.create_procedure_room(
            f.procedure_room_payload(
                room_type=ROOM_TYPE_CYSTO_SUITE, name="Cysto A", turnover_minutes=10
            ),
            admin_headers,
        ),
        201,
    )
    procedure_type = validate_success(
        api.create_procedure_type(
            f.procedure_type_payload(
                code=TYPE_CYSTOSCOPY,
                base_minutes=20,
                cleanup_class=CLEANUP_HIGH,
                allowed_room_type=ROOM_TYPE_CYSTO_SUITE,
                required_prep_codes=[],
            ),
            admin_headers,
        ),
        201,
    )
    validate_success(api.set_clock("2026-09-14T07:00:00.000Z", admin_headers))

    # Every reference except patient_id resolves, so only the patient can be
    # the missing parent.
    response = api.create_procedure_case(
        f.procedure_case_payload(
            patient_id=UNKNOWN_PATIENT_UUID,
            procedure_type_id=procedure_type["id"],
            room_id=room["id"],
            primary_provider_id=urologist["id"],
            scheduled_start_at="2026-09-14T14:00:00.000Z",
        ),
        scheduler_headers,
    )
    validate_error(response, ERR_PATIENT_NOT_FOUND)

    rows, meta = validate_paginated(api.list_procedure_cases(scheduler_headers))
    assert meta["total_count"] == 0, (
        "a case naming an unknown patient must not be drafted, but "
        f"{meta['total_count']} case(s) exist"
    )
    assert rows == [], f"expected no case rows, got {rows}"


def test_collected_specimen_is_reachable_by_filtering_the_collection_on_its_case(
    api, admin_headers
):
    """PRD 3.8: "The new specimen records `collected_at` at the logical clock instant, `chain_status` `COLLECTED`, `notification_status` `NOT_REQUIRED` and `notification_attempt_count` 0, with `accession_number`, `received_at`, `condition_on_receipt`, `pathology_result`, `result_at` and `escalation_due_at` all null."
    PRD 2.9: "Parent-child relationships are carried by reference fields on the child row, and every such reference is reverse-reachable through a filter on the parent's collection read."
    PRD 2.11: "Specimens may be filtered by `case_id`, `collected_by_provider_id`, `chain_status`, `notification_status` and `specimen_type`."

    Design: Corner/entities/entity_parent_relationships_specimen_reachable_from_case
    """
    urologist = register_provider(
        api, admin_headers, ROLE_TYPE_UROLOGIST, "Dr Ada Nour", "1000000001"
    )
    scheduler = register_provider(
        api, admin_headers, ROLE_TYPE_SCHEDULER, "Sam Reyes", "1000000002"
    )
    nurse = register_provider(api, admin_headers, ROLE_TYPE_RN, "Nina Park", "1000000003")
    urologist_headers = make_urologist_headers(urologist["id"])
    scheduler_headers = make_scheduler_headers(scheduler["id"])
    nurse_headers = make_procedure_nurse_headers(nurse["id"])

    patient = validate_success(
        api.create_patient(
            f.patient_payload(
                primary_urologist_id=urologist["id"],
                mrn="MRN-5007",
                full_name="Iris Vondel",
                date_of_birth="1958-09-09",
                egfr=60,
            ),
            admin_headers,
        ),
        201,
    )
    room = validate_success(
        api.create_procedure_room(
            f.procedure_room_payload(
                room_type=ROOM_TYPE_CYSTO_SUITE, name="Cysto A", turnover_minutes=10
            ),
            admin_headers,
        ),
        201,
    )
    procedure_type = validate_success(
        api.create_procedure_type(
            f.procedure_type_payload(
                code=TYPE_PROSTATE_BIOPSY,
                base_minutes=30,
                cleanup_class=CLEANUP_LOW,
                allowed_room_type=ROOM_TYPE_CYSTO_SUITE,
                requires_specimen=True,
                required_prep_codes=[],
            ),
            admin_headers,
        ),
        201,
    )
    validate_success(api.set_clock("2026-09-15T09:00:00.000Z", admin_headers))

    case = validate_success(
        api.create_procedure_case(
            f.procedure_case_payload(
                patient_id=patient["id"],
                procedure_type_id=procedure_type["id"],
                room_id=room["id"],
                primary_provider_id=urologist["id"],
                scheduled_start_at="2026-09-15T09:00:00.000Z",
            ),
            scheduler_headers,
        ),
        201,
    )
    validate_success(
        api.schedule_case(
            case["id"], f.schedule_payload(room["version"]), scheduler_headers
        )
    )
    validate_success(
        api.review_clearance(
            case["id"],
            f.clearance_review_payload(CLEARANCE_DECISION_CLEAR),
            nurse_headers,
        )
    )
    validate_success(api.check_in_case(case["id"], {}, nurse_headers))

    specimen = validate_success(
        api.create_specimen(
            f.specimen_payload(
                case_id=case["id"],
                collected_by_provider_id=urologist["id"],
                container_label="IV-CORE-01",
                specimen_type=SPECIMEN_PROSTATE_CORE,
                site_code="LEFT_BASE",
            ),
            urologist_headers,
        ),
        201,
    )

    assert_fields(
        specimen,
        case_id=case["id"],
        container_label="IV-CORE-01",
        specimen_type=SPECIMEN_PROSTATE_CORE,
        site_code="LEFT_BASE",
        collected_by_provider_id=urologist["id"],
        chain_status=CHAIN_COLLECTED,
        notification_status=NOTIFY_NOT_REQUIRED,
        notification_attempt_count=0,
    )
    assert_instant_equals(
        specimen["collected_at"], "2026-09-15T09:00:00.000Z", "collected_at"
    )
    assert_null_fields(
        specimen,
        "accession_number",
        "received_at",
        "condition_on_receipt",
        "pathology_result",
        "result_at",
        "escalation_due_at",
    )

    rows, meta = validate_paginated(
        api.list_specimens(admin_headers, case_id=case["id"])
    )
    assert meta["total_count"] == 1, (
        f"the case must own exactly one specimen, got {meta['total_count']}"
    )
    assert_ids_in_order(rows, [specimen["id"]])
    assert rows[0]["case_id"] == case["id"], (
        f"reverse lookup returned case_id {rows[0]['case_id']!r}, "
        f"expected {case['id']!r}"
    )


# ──────────────────────────── Collection reads ──────────────────────────────
def _build_case_book(api, admin_headers):
    """
    Two patients of one urologist and four drafted cases: three for the first
    patient, one for the second. Nothing is committed to the room calendar, so
    no two cases can contend for the room.
    """
    urologist = register_provider(
        api, admin_headers, ROLE_TYPE_UROLOGIST, "Dr Ada Nour", "1000000001"
    )
    scheduler = register_provider(
        api, admin_headers, ROLE_TYPE_SCHEDULER, "Sam Reyes", "1000000002"
    )
    scheduler_headers = make_scheduler_headers(scheduler["id"])

    patient_a = validate_success(
        api.create_patient(
            f.patient_payload(
                primary_urologist_id=urologist["id"],
                mrn="MRN-5002",
                full_name="Alma Reid",
                date_of_birth="1969-06-01",
                egfr=60,
            ),
            scheduler_headers,
        ),
        201,
    )
    patient_b = validate_success(
        api.create_patient(
            f.patient_payload(
                primary_urologist_id=urologist["id"],
                mrn="MRN-5003",
                full_name="Bram Ito",
                date_of_birth="1972-02-11",
                egfr=60,
            ),
            scheduler_headers,
        ),
        201,
    )
    room = validate_success(
        api.create_procedure_room(
            f.procedure_room_payload(
                room_type=ROOM_TYPE_CYSTO_SUITE, name="Cysto A", turnover_minutes=10
            ),
            admin_headers,
        ),
        201,
    )
    procedure_type = validate_success(
        api.create_procedure_type(
            f.procedure_type_payload(
                code=TYPE_CYSTOSCOPY,
                base_minutes=20,
                cleanup_class=CLEANUP_HIGH,
                allowed_room_type=ROOM_TYPE_CYSTO_SUITE,
                requires_scope=False,
                requires_antibiotic=False,
                required_prep_codes=[],
            ),
            admin_headers,
        ),
        201,
    )
    validate_success(api.set_clock("2026-09-14T07:00:00.000Z", admin_headers))

    def draft(patient, start_at):
        return validate_success(
            api.create_procedure_case(
                f.procedure_case_payload(
                    patient_id=patient["id"],
                    procedure_type_id=procedure_type["id"],
                    room_id=room["id"],
                    primary_provider_id=urologist["id"],
                    scheduled_start_at=start_at,
                ),
                scheduler_headers,
            ),
            201,
        )

    cases_a = [
        draft(patient_a, "2026-09-14T09:00:00.000Z"),
        draft(patient_a, "2026-09-14T11:00:00.000Z"),
        draft(patient_a, "2026-09-14T13:00:00.000Z"),
    ]
    case_b = draft(patient_b, "2026-09-14T15:00:00.000Z")
    return {
        "scheduler_headers": scheduler_headers,
        "patient_a": patient_a,
        "patient_b": patient_b,
        "cases_a": cases_a,
        "case_b": case_b,
    }


def test_case_book_filtered_by_patient_pages_through_that_patient_only(
    api, admin_headers
):
    """PRD 2.11: "Procedure cases may be filtered by `patient_id`, `procedure_type_id`, `room_id`, `primary_provider_id`, `scope_asset_id`, `device_lot_id`, `schedule_status` and `clearance_status`."
    PRD 2.3: "Collection reads are always returned in ascending `created_at` order. Every list response reports `limit`, `offset`, `total_count` and `has_more` inside `meta`, where `total_count` is the number of rows matching the filter before pagination is applied and `has_more` indicates whether any matching row remains beyond the current page."

    Design: Corner/entities/entity_listing_procedure_cases_filter_pagination
    """
    book = _build_case_book(api, admin_headers)
    headers = book["scheduler_headers"]
    patient_a = book["patient_a"]
    cases_a = book["cases_a"]

    response = api.list_procedure_cases(
        headers, patient_id=patient_a["id"], limit=2, offset=0
    )
    assert_envelope_meta(response, "array")
    first_page, meta = validate_paginated(response)
    assert_pagination_meta(meta, limit=2, offset=0, total_count=3, has_more=True)
    assert len(first_page) == 2, (
        f"a page of limit 2 must hold 2 rows, got {len(first_page)}"
    )
    for row in first_page:
        assert row["patient_id"] == patient_a["id"], (
            "the patient_id filter leaked a case of another patient: "
            f"{row['patient_id']!r}"
        )

    # total_count counts the filtered rows, not the rows on this page, so the
    # third case is still reachable one page further on.
    second_page, second_meta = validate_paginated(
        api.list_procedure_cases(
            headers, patient_id=patient_a["id"], limit=2, offset=2
        )
    )
    assert_pagination_meta(second_meta, limit=2, offset=2, total_count=3, has_more=False)
    assert len(second_page) == 1, (
        f"the last page of three filtered rows must hold 1 row, got {len(second_page)}"
    )
    paged_ids = [row["id"] for row in first_page + second_page]
    assert sorted(paged_ids) == sorted(case["id"] for case in cases_a), (
        "paging through the filter must yield each of the patient's three cases "
        f"exactly once, got {paged_ids}"
    )


def test_case_book_read_without_parameters_uses_the_declared_page_defaults(
    api, admin_headers
):
    """PRD 2.3: "`limit` controls page size: it defaults to 10, may not be smaller than 1, and may not be larger than 100."
    PRD 2.3: "`offset` controls the starting position: it defaults to 0 and may not be negative."

    Design: Corner/entities/entity_listing_procedure_cases_filter_pagination
    """
    book = _build_case_book(api, admin_headers)
    all_case_ids = [case["id"] for case in book["cases_a"]] + [book["case_b"]["id"]]

    rows, meta = validate_paginated(
        api.list_procedure_cases(book["scheduler_headers"])
    )
    assert_pagination_meta(meta, limit=10, offset=0, total_count=4, has_more=False)
    assert len(rows) == 4, (
        f"all four drafted cases must fit the default page, got {len(rows)}"
    )
    assert sorted(row["id"] for row in rows) == sorted(all_case_ids), (
        "the unfiltered page must hold every drafted case, got "
        f"{[row['id'] for row in rows]}"
    )
    assert_ascending_created_at(rows)


def _build_reference_practice(api, admin_headers):
    """
    A practice with something in every remaining collection: four staff, two
    rooms of different types, two catalogue entries, two scopes, two device
    lots, one patient, one drafted case with one open antibiotic order, and one
    reprocessing stage log still open on the first scope.
    """
    urologist = register_provider(
        api, admin_headers, ROLE_TYPE_UROLOGIST, "Dr Ada Nour", "1000000001"
    )
    scheduler = register_provider(
        api, admin_headers, ROLE_TYPE_SCHEDULER, "Sam Reyes", "1000000002"
    )
    nurse = register_provider(api, admin_headers, ROLE_TYPE_RN, "Nia Park", "1000000003")
    tech = register_provider(
        api,
        admin_headers,
        ROLE_TYPE_TECH,
        "Omar Diaz",
        "1000000004",
        hld_certified=True,
    )
    urologist_headers = make_urologist_headers(urologist["id"])
    scheduler_headers = make_scheduler_headers(scheduler["id"])
    tech_headers = make_sterile_processing_tech_headers(tech["id"])

    patient = validate_success(
        api.create_patient(
            f.patient_payload(
                primary_urologist_id=urologist["id"],
                mrn="MRN-5090",
                full_name="Yon Kell",
                date_of_birth="1965-06-25",
                egfr=66,
            ),
            scheduler_headers,
        ),
        201,
    )
    cysto_room = validate_success(
        api.create_procedure_room(
            f.procedure_room_payload(
                room_type=ROOM_TYPE_CYSTO_SUITE, name="Cysto A", turnover_minutes=10
            ),
            admin_headers,
        ),
        201,
    )
    imaging_room = validate_success(
        api.create_procedure_room(
            f.procedure_room_payload(
                room_type=ROOM_TYPE_IMAGING_BAY,
                name="Imaging 1",
                turnover_minutes=10,
                accreditation_body="ACR",
                accreditation_expires_on="2027-12-31",
            ),
            admin_headers,
        ),
        201,
    )
    cysto_type = validate_success(
        api.create_procedure_type(
            f.procedure_type_payload(
                code=TYPE_CYSTOSCOPY,
                base_minutes=20,
                cleanup_class=CLEANUP_HIGH,
                allowed_room_type=ROOM_TYPE_CYSTO_SUITE,
                requires_antibiotic=True,
                required_prep_codes=[],
            ),
            admin_headers,
        ),
        201,
    )
    ultrasound_type = validate_success(
        api.create_procedure_type(
            f.procedure_type_payload(
                code=TYPE_OFFICE_ULTRASOUND,
                base_minutes=15,
                cleanup_class=CLEANUP_LOW,
                allowed_room_type=ROOM_TYPE_IMAGING_BAY,
                required_prep_codes=[],
            ),
            admin_headers,
        ),
        201,
    )
    scope_f = validate_success(
        api.create_scope_asset(
            f.scope_asset_payload(
                serial_number="SN-F", scope_model="FlexCysto 200", channel_count=2
            ),
            tech_headers,
        ),
        201,
    )
    scope_g = validate_success(
        api.create_scope_asset(
            f.scope_asset_payload(
                serial_number="SN-G", scope_model="RigidCysto 40", channel_count=1
            ),
            tech_headers,
        ),
        201,
    )
    biopsy_lot = validate_success(
        api.create_consignment_lot(
            f.consignment_lot_payload(
                supplier_name="Medline",
                sku="BX-KIT-1",
                device_class=DEVICE_CLASS_BIOPSY_NEEDLE,
                quantity_received=10,
                unit_price_cents=4500,
                lot_expires_on="2027-06-30",
            ),
            admin_headers,
        ),
        201,
    )
    catheter_lot = validate_success(
        api.create_consignment_lot(
            f.consignment_lot_payload(
                supplier_name="Cardinal",
                sku="UD-CATH-1",
                device_class=DEVICE_CLASS_URODYNAMICS_CATHETER_KIT,
                quantity_received=6,
                unit_price_cents=2200,
                lot_expires_on="2027-09-30",
            ),
            admin_headers,
        ),
        201,
    )
    validate_success(api.set_clock("2026-09-14T07:00:00.000Z", admin_headers))

    case = validate_success(
        api.create_procedure_case(
            f.procedure_case_payload(
                patient_id=patient["id"],
                procedure_type_id=cysto_type["id"],
                room_id=cysto_room["id"],
                primary_provider_id=urologist["id"],
                scheduled_start_at="2026-09-14T09:00:00.000Z",
            ),
            scheduler_headers,
        ),
        201,
    )
    order = validate_success(
        api.create_antibiotic_order(
            f.antibiotic_order_payload(
                case_id=case["id"],
                ordered_by_provider_id=urologist["id"],
                requested_agent=AGENT_AUTO,
            ),
            urologist_headers,
        ),
        201,
    )
    log = validate_success(
        api.create_reprocessing_log(
            f.reprocessing_log_payload(
                scope_asset_id=scope_f["id"],
                stage=STAGE_PRECLEAN,
                performed_by_provider_id=tech["id"],
            ),
            tech_headers,
        ),
        201,
    )
    return {
        "urologist": urologist,
        "scheduler": scheduler,
        "nurse": nurse,
        "tech": tech,
        "urologist_headers": urologist_headers,
        "tech_headers": tech_headers,
        "patient": patient,
        "cysto_room": cysto_room,
        "imaging_room": imaging_room,
        "cysto_type": cysto_type,
        "ultrasound_type": ultrasound_type,
        "scope_f": scope_f,
        "scope_g": scope_g,
        "biopsy_lot": biopsy_lot,
        "catheter_lot": catheter_lot,
        "case": case,
        "order": order,
        "log": log,
    }


def test_roster_pages_one_row_at_a_time_and_the_last_page_still_carries_a_row(
    api, admin_headers
):
    """PRD 2.3: "Every list response reports `limit`, `offset`, `total_count` and `has_more` inside `meta`, where `total_count` is the number of rows matching the filter before pagination is applied and `has_more` indicates whether any matching row remains beyond the current page."

    Design: Corner/entities/entity_listing_remaining_collections_and_empty_page
    """
    practice = _build_reference_practice(api, admin_headers)
    roster_ids = {
        practice["urologist"]["id"],
        practice["scheduler"]["id"],
        practice["nurse"]["id"],
        practice["tech"]["id"],
    }

    first_page, first_meta = validate_paginated(api.list_providers(admin_headers, limit=1))
    assert_pagination_meta(first_meta, limit=1, offset=0, total_count=4, has_more=True)
    assert len(first_page) == 1, (
        f"a page of limit 1 must hold exactly 1 row, got {len(first_page)}"
    )

    # Offset 3 of 4 rows is the final page: it is not empty, but nothing is
    # left beyond it.
    last_page, last_meta = validate_paginated(
        api.list_providers(admin_headers, limit=1, offset=3)
    )
    assert_pagination_meta(last_meta, limit=1, offset=3, total_count=4, has_more=False)
    assert len(last_page) == 1, (
        f"the last page of four rows must still carry 1 row, got {len(last_page)}"
    )
    assert last_page[0]["id"] in roster_ids, (
        f"the last page returned an unknown provider {last_page[0]['id']!r}"
    )


def test_every_remaining_collection_honours_its_own_declared_filter(
    api, admin_headers
):
    """PRD 2.11: "The collection reads accept the following optional filters in addition to `limit` and `offset`, and a filter that is supplied restricts the result set to exact matches on that field."
    PRD 2.11: "Scope assets may be filtered by `status`, `leak_test_required` and `serial_number`."
    PRD 3.5: "The scope moves only when the log closes."

    Design: Corner/entities/entity_listing_remaining_collections_and_empty_page
    """
    practice = _build_reference_practice(api, admin_headers)
    tech_headers = practice["tech_headers"]

    rows, meta = validate_paginated(
        api.list_providers(admin_headers, role_type=ROLE_TYPE_TECH)
    )
    assert_pagination_meta(meta, limit=10, offset=0, total_count=1, has_more=False)
    assert_ids_in_order(rows, [practice["tech"]["id"]])
    assert_fields(rows[0], role_type=ROLE_TYPE_TECH, hld_certified=True)

    rows, meta = validate_paginated(
        api.list_procedure_rooms(admin_headers, room_type=ROOM_TYPE_IMAGING_BAY)
    )
    assert meta["total_count"] == 1, (
        f"only the imaging bay is of that room type, got {meta['total_count']} row(s)"
    )
    assert_ids_in_order(rows, [practice["imaging_room"]["id"]])
    assert_fields(rows[0], room_type=ROOM_TYPE_IMAGING_BAY)

    # The office ultrasound is bound to the imaging bay, so it must not appear.
    rows, meta = validate_paginated(
        api.list_procedure_types(admin_headers, allowed_room_type=ROOM_TYPE_CYSTO_SUITE)
    )
    assert meta["total_count"] == 1, (
        "only the cystoscopy entry allows the cysto suite, got "
        f"{meta['total_count']} row(s)"
    )
    assert_ids_in_order(rows, [practice["cysto_type"]["id"]])

    rows, meta = validate_paginated(
        api.list_scope_assets(tech_headers, status=SCOPE_AVAILABLE)
    )
    assert meta["total_count"] == 2, (
        "an open reprocessing log must leave both scopes available, got "
        f"{meta['total_count']} available scope(s)"
    )
    assert sorted(row["id"] for row in rows) == sorted(
        [practice["scope_f"]["id"], practice["scope_g"]["id"]]
    ), f"expected both registered scopes, got {[row['id'] for row in rows]}"

    rows, meta = validate_paginated(
        api.list_scope_assets(tech_headers, serial_number="SN-F")
    )
    assert meta["total_count"] == 1, (
        f"a serial number names one scope, got {meta['total_count']} row(s)"
    )
    assert_ids_in_order(rows, [practice["scope_f"]["id"]])

    rows, meta = validate_paginated(
        api.list_consignment_lots(
            admin_headers, device_class=DEVICE_CLASS_BIOPSY_NEEDLE
        )
    )
    assert meta["total_count"] == 1, (
        f"one lot carries that device class, got {meta['total_count']} row(s)"
    )
    assert_ids_in_order(rows, [practice["biopsy_lot"]["id"]])
    assert_fields(
        rows[0],
        sku="BX-KIT-1",
        device_class=DEVICE_CLASS_BIOPSY_NEEDLE,
        billing_status=BILLING_STATUS_CONSIGNED,
    )

    rows, meta = validate_paginated(
        api.list_antibiotic_orders(
            practice["urologist_headers"],
            status=ANTIBIOTIC_ORDERED,
            case_id=practice["case"]["id"],
        )
    )
    assert meta["total_count"] == 1, (
        f"the case holds one open order, got {meta['total_count']} row(s)"
    )
    assert_ids_in_order(rows, [practice["order"]["id"]])
    assert_fields(
        rows[0],
        case_id=practice["case"]["id"],
        agent=AGENT_CIPROFLOXACIN,
        status=ANTIBIOTIC_ORDERED,
    )

    rows, meta = validate_paginated(
        api.list_reprocessing_logs(
            tech_headers, log_status=LOG_OPEN, stage=STAGE_PRECLEAN
        )
    )
    assert meta["total_count"] == 1, (
        f"one stage log is open at that stage, got {meta['total_count']} row(s)"
    )
    assert_ids_in_order(rows, [practice["log"]["id"]])
    assert_fields(
        rows[0],
        scope_asset_id=practice["scope_f"]["id"],
        stage=STAGE_PRECLEAN,
        log_status=LOG_OPEN,
    )
    assert_null_fields(rows[0], "outcome")


def test_a_filter_that_matches_nothing_answers_an_empty_page_not_a_not_found(
    api, admin_headers
):
    """PRD 2.11: "The collection reads accept the following optional filters in addition to `limit` and `offset`, and a filter that is supplied restricts the result set to exact matches on that field."
    PRD 2.3: "Collection reads are always returned in ascending `created_at` order. Every list response reports `limit`, `offset`, `total_count` and `has_more` inside `meta`, where `total_count` is the number of rows matching the filter before pagination is applied and `has_more` indicates whether any matching row remains beyond the current page."

    Design: Corner/entities/entity_listing_remaining_collections_and_empty_page
    """
    practice = _build_reference_practice(api, admin_headers)

    # This patient has no pelvic health referral at all, which is an empty
    # result set rather than a missing resource.
    response = api.list_pelvic_health_referrals(
        admin_headers, patient_id=practice["patient"]["id"]
    )
    assert response.status_code == 200, (
        "an empty filtered collection is still a successful read, got HTTP "
        f"{response.status_code}"
    )
    assert_envelope_meta(response, "array")
    rows, meta = validate_paginated(response)
    assert_pagination_meta(meta, limit=10, offset=0, total_count=0, has_more=False)
    assert rows == [], f"expected an empty data array, got {rows}"

    # The second scope was never reprocessed, so its audit trail is empty even
    # though the collection itself holds a row for the first scope.
    rows, meta = validate_paginated(
        api.list_reprocessing_logs(
            practice["tech_headers"], scope_asset_id=practice["scope_g"]["id"]
        )
    )
    assert_pagination_meta(meta, limit=10, offset=0, total_count=0, has_more=False)
    assert rows == [], f"expected no stage log for the unused scope, got {rows}"
