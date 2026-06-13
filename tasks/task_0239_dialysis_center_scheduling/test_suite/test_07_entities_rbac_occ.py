"""Entity creation defaults, system fields, listing/pagination, computed-field
initialization, type/required validation, RBAC enforcement, and optimistic
concurrency on patient-version-guarded creates.

Corner queue (B): entities, endpoints (filtered list), rbac,
cross_cutting_complexity_layers (OCC).
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated, get_success_data,
    is_valid_uuid, is_iso8601_timestamp,
    setup_clinic_inventory, reserve_standing_slot, setup_bookable_scenario,
    book_session,
    create_clinic_payload, create_patient_payload, create_order_payload,
    create_machine_payload, create_standing_slot_payload, create_transport_trip_payload,
    create_session_payload,
    TEST_USERS, build_user_headers,
)

ADMIN = TEST_USERS["clinic_admin_headers"]
SCHED = TEST_USERS["scheduler_headers"]
NEPH = TEST_USERS["nephrologist_headers"]
BILL = TEST_USERS["billing_clerk_headers"]


# ─── Corner: entities / create_clinic_returns_201_with_defaults ───────────
def test_create_clinic_defaults(api):
    """PRD §3.1: "The reuse limit defaults to 12 and caps how many times a single
    dialyzer may be reused on a machine before mandatory retirement"
    PRD §3.1: "A freshly created clinic opens in `status` `OPEN`."
    PRD §2.4: "The `version` begins at 1 when the resource is created"

    Design: Corner/entities/create_clinic_returns_201_with_defaults
    """
    clinic = validate_success(api.create_clinic(create_clinic_payload(name="Solo Clinic"), ADMIN), 201)
    assert clinic["status"] == "OPEN"
    assert clinic["dialyzer_reuse_limit"] == 12
    assert clinic["version"] == 1


# ─── Corner: entities / get_clinic_not_found ──────────────────────────────
def test_get_unknown_clinic_not_found(api):
    """PRD §2.4: "for any endpoint whose URL names a resource id, the named
    resource must exist or the request fails with that resource's not-found error
    (for example `ERR_CLINIC_NOT_FOUND` ...)"

    Design: Corner/entities/get_clinic_not_found
    """
    res = api.get_clinic("00000000-0000-0000-0000-000000000000", ADMIN)
    validate_error(res, "ERR_CLINIC_NOT_FOUND")


# ─── Corner: entities / create_order_missing_required_modality ────────────
def test_create_order_missing_modality_rejected(api):
    """PRD §3.4: "A `Nephrologist` creates an order against a `patient_id`, with a
    `modality` (one of `HEMODIALYSIS`, `HEMODIAFILTRATION`, or `PERITONEAL`), an
    `effective_from_date`"
    PRD §2.9: "(16) request-body field-level validation, else `ERR_INVALID_REQUEST`"

    Design: Corner/entities/create_order_missing_required_modality
    """
    clinic = get_success_data(api.create_clinic({"name": "ReqClinic"}, ADMIN))
    patient = get_success_data(api.create_patient(
        create_patient_payload(clinic["id"], mrn="RQ1", full_name="Req One"), SCHED))
    res = api.create_order(
        {"patient_id": patient["id"], "effective_from_date": "2026-06-01"}, NEPH)
    validate_error(res, "ERR_INVALID_REQUEST")


# ─── Corner: entities / create_patient_default_kind_and_payer ─────────────
def test_create_patient_applies_defaults(api):
    """PRD §3.3: "The `patient_kind` is either `RESIDENT` (the default ...) or
    `TRANSIENT` ... The `payer_class` is either `STANDARD` (the default ...) or
    `CONTRACTED`"
    PRD §3.3: "A newly created patient starts with `adherence_status`
    `GOOD_STANDING`, an `account_balance_cents` of 0, and a `no_show_count_window`
    of 0."

    Design: Corner/entities/create_patient_default_kind_and_payer
    """
    clinic = get_success_data(api.create_clinic({"name": "DefClinic"}, ADMIN))
    patient = validate_success(api.create_patient(
        create_patient_payload(clinic["id"], mrn="DEF1", full_name="Def One"), SCHED), 201)
    assert patient["patient_kind"] == "RESIDENT"
    assert patient["payer_class"] == "STANDARD"
    assert patient["account_balance_cents"] == 0
    assert patient["adherence_status"] == "GOOD_STANDING"


# ─── Corner: entities / system_fields_generated_on_create ─────────────────
def test_system_fields_minted_on_create(api):
    """PRD §2.4: "Every resource is assigned a server-minted `id`, which is a UUID
    string carrying no type prefix. Every resource also records a `created_at`
    timestamp at creation."
    PRD §2.4: "All timestamps are ISO 8601 in UTC with three fractional digits."
    PRD §3.1: "A freshly created clinic opens in `status` `OPEN`."

    Design: Corner/entities/system_fields_generated_on_create
    """
    clinic = validate_success(api.create_clinic({"name": "SysClinic"}, ADMIN), 201)
    assert is_valid_uuid(clinic["id"])
    assert is_iso8601_timestamp(clinic["created_at"])
    assert clinic["status"] == "OPEN"


# ─── Corner: entities / list_patients_pagination_envelope ─────────────────
def test_list_patients_pagination_envelope(api):
    """PRD §2.3: "The `meta` block of a list response carries `limit`, `offset`,
    `total_count` (the total number of matching records before pagination), and
    `has_more` (a boolean that is true when records remain beyond the current
    page)."

    Design: Corner/entities/list_patients_pagination_envelope
    """
    clinic = get_success_data(api.create_clinic({"name": "ListClinic"}, ADMIN))
    get_success_data(api.create_patient(
        create_patient_payload(clinic["id"], mrn="L1", full_name="List One"), SCHED))
    data, meta = validate_paginated(api.list_patients(
        SCHED, params={"clinic_id": clinic["id"], "limit": 10, "offset": 0}))
    assert meta["total_count"] == 1
    assert meta["has_more"] is False


# ─── Corner: entities / computed_dialyzer_reuse_count_initial_zero ────────
def test_machine_reuse_count_initial_zero(api):
    """PRD §3.1: "Each machine tracks a `dialyzer_reuse_count`, which begins at 0"
    PRD §3.1: "A machine starts `AVAILABLE`"

    Design: Corner/entities/computed_dialyzer_reuse_count_initial_zero
    """
    clinic = get_success_data(api.create_clinic({"name": "MachClinic"}, ADMIN))
    machine = validate_success(api.create_machine(
        create_machine_payload(clinic["id"], asset_tag="MX1", model="Test"), ADMIN), 201)
    assert machine["dialyzer_reuse_count"] == 0
    assert machine["status"] == "AVAILABLE"


# ─── Corner: entities / create_order_bad_modality_enum ────────────────────
def test_create_order_invalid_modality_enum_rejected(api):
    """PRD §3.4: "a `modality` (one of `HEMODIALYSIS`, `HEMODIAFILTRATION`, or
    `PERITONEAL`)"
    PRD §2.9: "(16) request-body field-level validation, else `ERR_INVALID_REQUEST`"

    Design: Corner/entities/create_order_bad_modality_enum
    """
    clinic = get_success_data(api.create_clinic({"name": "EnumClinic"}, ADMIN))
    patient = get_success_data(api.create_patient(
        create_patient_payload(clinic["id"], mrn="EN1", full_name="Enum One"), SCHED))
    res = api.create_order(
        {"patient_id": patient["id"], "modality": "PLASMA",
         "effective_from_date": "2026-06-01"}, NEPH)
    validate_error(res, "ERR_INVALID_REQUEST")


# ─── Corner: endpoints / transport_filtered_list_by_session ───────────────
def test_list_transport_trips_filtered_by_session(api):
    """PRD §3.8: "A `Scheduler` requests a transport trip for a session by
    supplying the `session_id`"
    PRD §2.3: "Where a list endpoint also accepts domain filters (for example a
    `clinic_id` or `patient_id` filter), those filters narrow the matching set
    before pagination is applied."

    Design: Corner/endpoints/transport_filtered_list_by_session
    """
    scenario = setup_bookable_scenario(dialyzer_reuse_limit=99, coinsurance_pct=0.0)
    session = book_session(scenario)
    trip = get_success_data(api.create_transport_trip(
        create_transport_trip_payload(session["id"], direction="INBOUND", miles=5), SCHED))
    data, meta = validate_paginated(api.list_transport_trips(
        SCHED, params={"session_id": session["id"]}))
    assert len(data) == 1
    assert data[0]["id"] == trip["id"]


# ─── Corner: rbac / scheduler_cannot_create_order ─────────────────────────
def test_scheduler_cannot_create_order(api):
    """PRD §3.4: "A `Nephrologist` creates an order against a `patient_id`"
    PRD §2.1: "If the headers are present but the role named in `X-User-Role` is
    not permitted to perform the requested operation, the request is rejected with
    `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/scheduler_cannot_create_order
    """
    clinic = get_success_data(api.create_clinic({"name": "RbClinic"}, ADMIN))
    patient = get_success_data(api.create_patient(
        create_patient_payload(clinic["id"], mrn="RB1", full_name="Rb One"), SCHED))
    res = api.create_order(create_order_payload(patient["id"]), SCHED)
    validate_error(res, "ERR_FORBIDDEN_ROLE")


# ─── Corner: rbac / nephrologist_cannot_create_clinic ─────────────────────
def test_nephrologist_cannot_create_clinic(api):
    """PRD §4: the POST `/clinics` row names `ClinicAdmin` as the only authorized
    role.
    PRD §2.1: "If the headers are present but the role named in `X-User-Role` is
    not permitted to perform the requested operation, the request is rejected with
    `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/nephrologist_cannot_create_clinic
    """
    res = api.create_clinic({"name": "Nope"}, NEPH)
    validate_error(res, "ERR_FORBIDDEN_ROLE")


# ─── Corner: rbac / missing_user_context_header ───────────────────────────
def test_missing_user_context_rejected(api):
    """PRD §2.1: "Every request must carry two headers identifying the caller:
    `X-User-ID` and `X-User-Role`. If either header is missing or malformed, the
    request is rejected with `ERR_MISSING_USER_CONTEXT` (HTTP 400) before any
    other processing."

    Design: Corner/rbac/missing_user_context_header
    """
    res = api.list_clinics(headers={})
    validate_error(res, "ERR_MISSING_USER_CONTEXT")


# ─── Corner: rbac / billing_clerk_can_share_get_reads ─────────────────────
def test_billing_clerk_shared_get_read_succeeds(api):
    """PRD §2.1: "All four roles may perform every read (`GET`) operation in the
    system."

    Design: Corner/rbac/billing_clerk_can_share_get_reads
    """
    clinic = get_success_data(api.create_clinic({"name": "ShareClinic"}, ADMIN))
    fetched = validate_success(api.get_clinic(clinic["id"], BILL), 200)
    assert fetched["status"] == "OPEN"


# ─── Corner: cross_cutting / occ_standing_slot_stale_version_conflict ─────
def test_standing_slot_stale_version_rejected(api):
    """PRD §2.7: "A request to reserve a standing chair/shift slot must include a
    non-optional `expected_patient_version` field carrying the `version` of the
    patient that the client last observed. If that value does not equal the
    patient's current `version`, the reservation is rejected with
    `ERR_STALE_PATIENT_VERSION` (HTTP 412)"
    PRD §2.7: "A successful standing-slot reservation increments the patient's
    `version` by 1, so a second create still carrying the previously observed
    version will be caught as stale."

    Design: Corner/cross_cutting_complexity_layers/occ_standing_slot_stale_version_conflict
    """
    clinic = get_success_data(api.create_clinic({"name": "OccClinic"}, ADMIN))
    machine = get_success_data(api.create_machine(
        create_machine_payload(clinic["id"], asset_tag="OC1", model="T"), ADMIN))
    s1 = get_success_data(api.create_station(
        {"clinic_id": clinic["id"], "chair_label": "OC1", "machine_id": machine["id"]}, ADMIN))
    s2 = get_success_data(api.create_station(
        {"clinic_id": clinic["id"], "chair_label": "OC2", "machine_id": machine["id"]}, ADMIN))
    sh1 = get_success_data(api.create_shift(
        {"clinic_id": clinic["id"], "code": "AM", "day_pattern": "MWF",
         "start_minute": 360, "end_minute": 600}, ADMIN))
    sh2 = get_success_data(api.create_shift(
        {"clinic_id": clinic["id"], "code": "PM", "day_pattern": "MWF",
         "start_minute": 660, "end_minute": 900}, ADMIN))
    patient = get_success_data(api.create_patient(
        create_patient_payload(clinic["id"], mrn="OC1", full_name="Occ One",
                               patient_kind="RESIDENT"), SCHED))
    order = get_success_data(api.create_order(create_order_payload(patient["id"]), NEPH))
    api.activate_order(order["id"], NEPH)
    pv0 = patient["version"]
    api.create_standing_slot(create_standing_slot_payload(
        patient["id"], sh1["id"], s1["id"], pv0), SCHED)  # advances version
    res = api.create_standing_slot(create_standing_slot_payload(
        patient["id"], sh2["id"], s2["id"], pv0), SCHED)  # stale pv0
    validate_error(res, "ERR_STALE_PATIENT_VERSION")


def test_standing_slot_fresh_version_succeeds(api):
    """PRD §2.7: "A successful standing-slot reservation increments the patient's
    `version` by 1"
    PRD §3.5: "A standing slot is created in `RESERVED`"

    Design: Corner/cross_cutting_complexity_layers/occ_standing_slot_correct_version_succeeds
    """
    clinic = get_success_data(api.create_clinic({"name": "OccOk"}, ADMIN))
    machine = get_success_data(api.create_machine(
        create_machine_payload(clinic["id"], asset_tag="OK1", model="T"), ADMIN))
    s1 = get_success_data(api.create_station(
        {"clinic_id": clinic["id"], "chair_label": "OK1", "machine_id": machine["id"]}, ADMIN))
    s2 = get_success_data(api.create_station(
        {"clinic_id": clinic["id"], "chair_label": "OK2", "machine_id": machine["id"]}, ADMIN))
    sh1 = get_success_data(api.create_shift(
        {"clinic_id": clinic["id"], "code": "AM", "day_pattern": "MWF",
         "start_minute": 360, "end_minute": 600}, ADMIN))
    sh2 = get_success_data(api.create_shift(
        {"clinic_id": clinic["id"], "code": "PM", "day_pattern": "MWF",
         "start_minute": 660, "end_minute": 900}, ADMIN))
    patient = get_success_data(api.create_patient(
        create_patient_payload(clinic["id"], mrn="OK1", full_name="Ok One",
                               patient_kind="RESIDENT"), SCHED))
    order = get_success_data(api.create_order(create_order_payload(patient["id"]), NEPH))
    api.activate_order(order["id"], NEPH)
    api.create_standing_slot(create_standing_slot_payload(
        patient["id"], sh1["id"], s1["id"], patient["version"]), SCHED)
    pv1 = get_success_data(api.get_patient(patient["id"], SCHED))["version"]
    slot2 = validate_success(api.create_standing_slot(create_standing_slot_payload(
        patient["id"], sh2["id"], s2["id"], pv1), SCHED), 201)
    assert slot2["status"] == "RESERVED"
