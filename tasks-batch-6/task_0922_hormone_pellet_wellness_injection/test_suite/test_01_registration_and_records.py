"""Registration, record identity, immutable protocols, listing and lookup."""

import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    assert_envelope_meta,
    assert_patient,
    assert_protocol,
    assert_same_instant,
    is_valid_uuid,
    new_patient,
    new_physician,
    new_standing_order,
    publish_protocol,
    record_consult,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["clinic_admin_headers"]
FRONT_DESK = TEST_USERS["front_desk_headers"]


def test_patient_registration_returns_201_with_clear_eligibility(api):
    """PRD §3.1: "The server initialises the rest: `clinical_hold` and `financial_hold`
    both start false, `eligibility_status` starts at `CLEAR`, `cumulative_mg_testosterone`
    and `cumulative_mg_estradiol` both start at 0, `last_insertion_at` and
    `last_insertion_hormone_type` both start null, and `open_notification_count` starts at 0."
    PRD §2.5: "Every persisted record carries a server-minted `id` that is a UUID string
    with no type prefix, and a `created_at` timestamp."

    Design: Corner/entities/patient_create_returns_201_with_system_fields_and_clear_eligibility
    """
    response = api.create_patient(
        {
            "full_name": "Corner One",
            "date_of_birth": "1980-01-01",
            "email": "c1@example.com",
            "sex_at_birth": "MALE",
        },
        ADMIN,
    )
    data = validate_success(response, 201)
    assert_envelope_meta(response.json())
    assert response.json()["response_type"] == "object"

    assert is_valid_uuid(data["id"]), f"id must be a bare UUID with no prefix: {data['id']!r}"
    assert data["version"] == 1, f"A new record starts at version 1, got {data['version']}"
    assert data["clinical_hold"] is False
    assert data["financial_hold"] is False
    assert data["eligibility_status"] == "CLEAR"
    assert data["cumulative_mg_testosterone"] == 0
    assert data["cumulative_mg_estradiol"] == 0
    assert data["last_insertion_at"] is None
    assert data["last_insertion_hormone_type"] is None
    assert data["open_notification_count"] == 0
    assert_patient(data)


NOT_FOUND_LOOKUPS = [
    ("providers", ApiErrorId.ERR_PROVIDER_NOT_FOUND),
    ("protocols", ApiErrorId.ERR_PROTOCOL_NOT_FOUND),
    ("consents", ApiErrorId.ERR_CONSENT_NOT_FOUND),
    ("consults", ApiErrorId.ERR_CONSULT_NOT_FOUND),
    ("lab-panels", ApiErrorId.ERR_LAB_PANEL_NOT_FOUND),
    ("pellet-lots", ApiErrorId.ERR_LOT_NOT_FOUND),
    ("standing-orders", ApiErrorId.ERR_STANDING_ORDER_NOT_FOUND),
    ("procedures", ApiErrorId.ERR_PROCEDURE_NOT_FOUND),
    ("injection-visits", ApiErrorId.ERR_INJECTION_VISIT_NOT_FOUND),
    ("memberships", ApiErrorId.ERR_MEMBERSHIP_NOT_FOUND),
    ("series-packs", ApiErrorId.ERR_SERIES_PACK_NOT_FOUND),
    ("adverse-events", ApiErrorId.ERR_ADVERSE_EVENT_NOT_FOUND),
    ("financing-plans", ApiErrorId.ERR_FINANCING_PLAN_NOT_FOUND),
    ("patient-notifications", ApiErrorId.ERR_NOTIFICATION_NOT_FOUND),
]


@pytest.mark.parametrize("collection,expected_error", NOT_FOUND_LOOKUPS)
def test_each_collection_answers_with_its_own_not_found_code(api, collection, expected_error):
    """PRD §2.9: "**Rung 6** — every path-segment resource id resolves, validated left to
    right, on every endpoint that has a path parameter. The code is the per-entity one:
    `ERR_PATIENT_NOT_FOUND`, `ERR_PROVIDER_NOT_FOUND`, `ERR_PROTOCOL_NOT_FOUND`,
    `ERR_CONSENT_NOT_FOUND`, `ERR_CONSULT_NOT_FOUND`, `ERR_LAB_PANEL_NOT_FOUND`,
    `ERR_LOT_NOT_FOUND`, `ERR_STANDING_ORDER_NOT_FOUND`, `ERR_PROCEDURE_NOT_FOUND`,
    `ERR_INJECTION_VISIT_NOT_FOUND`, `ERR_MEMBERSHIP_NOT_FOUND`, `ERR_SERIES_PACK_NOT_FOUND`,
    `ERR_ADVERSE_EVENT_NOT_FOUND`, `ERR_FINANCING_PLAN_NOT_FOUND` or
    `ERR_NOTIFICATION_NOT_FOUND`, each at HTTP 404."

    Design: Corner/entities/every_addressable_entity_has_its_own_not_found_code
    """
    response = api._request(
        "GET", f"/clinic/{collection}/{NON_EXISTENT_UUID}", headers=ADMIN
    )
    validate_error(response, expected_error.value)
    assert response.status_code == 404


def test_patient_lookup_by_unknown_id_reports_patient_not_found(api):
    """PRD §2.9: "**Rung 6** — every path-segment resource id resolves, validated left to
    right, on every endpoint that has a path parameter. The code is the per-entity one:
    `ERR_PATIENT_NOT_FOUND`, `ERR_PROVIDER_NOT_FOUND`, `ERR_PROTOCOL_NOT_FOUND`,
    `ERR_CONSENT_NOT_FOUND`, `ERR_CONSULT_NOT_FOUND`, `ERR_LAB_PANEL_NOT_FOUND`,
    `ERR_LOT_NOT_FOUND`, `ERR_STANDING_ORDER_NOT_FOUND`, `ERR_PROCEDURE_NOT_FOUND`,
    `ERR_INJECTION_VISIT_NOT_FOUND`, `ERR_MEMBERSHIP_NOT_FOUND`, `ERR_SERIES_PACK_NOT_FOUND`,
    `ERR_ADVERSE_EVENT_NOT_FOUND`, `ERR_FINANCING_PLAN_NOT_FOUND` or
    `ERR_NOTIFICATION_NOT_FOUND`, each at HTTP 404."
    PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies the
    specific error."

    Design: Corner/entities/patient_get_non_existent_returns_not_found
    """
    response = api.get_patient(NON_EXISTENT_UUID, ADMIN)
    validate_error(response, ApiErrorId.ERR_PATIENT_NOT_FOUND.value)
    assert response.status_code == 404
    assert response.json()["response_type"] == "error"


def test_patient_registration_without_sex_at_birth_is_a_request_shape_violation(api):
    """PRD §2.9: "**Rung 4** — every required input field for the endpoint is present, of
    the declared type, and within its declared numeric bounds, on every endpoint."
    PRD §3.1: "A `ClinicAdmin` or a `FrontDesk` operator supplies the patient's `full_name`,
    their `date_of_birth` as an ISO calendar date in year-month-day form, an `email` that
    must be unique across all patients, and a `sex_at_birth` of either `MALE` or `FEMALE`."

    Design: Corner/entities/patient_create_missing_required_field_returns_invalid_request
    """
    response = api.create_patient(
        {"full_name": "Corner Two", "date_of_birth": "1980-01-01", "email": "c2@example.com"},
        ADMIN,
    )
    validate_error(response, ApiErrorId.ERR_VALIDATION.value)
    assert response.status_code == 400

    # The email is unique across all patients, so a complete registration reusing it
    # can only succeed if the rejected request persisted nothing.
    retry = api.create_patient(
        {
            "full_name": "Corner Two",
            "date_of_birth": "1980-01-01",
            "email": "c2@example.com",
            "sex_at_birth": "MALE",
        },
        ADMIN,
    )
    validate_success(retry, 201)


def test_provider_type_outside_the_declared_members_reports_invalid_enum(api):
    """PRD §2.9: "**Rung 5** — every enum-valued input field carries a declared member. The
    fields routed here are exhaustively: `sex_at_birth` on a patient; `provider_type` on a
    provider; `hormone_type` on a protocol, on a consent, on a consult and on a pellet lot;"
    PRD §2.9: "No other field routes here — an out-of-range integer or a malformed datetime
    is `ERR_VALIDATION` at rung 4, never `ERR_INVALID_ENUM`. Otherwise `ERR_INVALID_ENUM` (400)."

    Design: Corner/entities/provider_invalid_enum_provider_type_returns_invalid_enum
    """
    response = api.create_provider(
        {"full_name": "Corner Three", "provider_type": "SURGEON", "npi": "9000000001"}, ADMIN
    )
    validate_error(response, ApiErrorId.ERR_INVALID_ENUM.value)
    assert response.status_code == 400


def test_published_protocol_carries_no_updated_at_and_no_version(api):
    """PRD §2.5: "The `Protocol` record is immutable once published: it carries only `id` and
    `created_at`, and neither `updated_at` nor `version` appears on it at all."
    PRD §3.2: "`effective_at` is stamped from the logical clock at publication."
    PRD §2.4: "The server holds a **logical UTC clock** whose value at startup is exactly
    `2026-05-01T00:00:00Z`, and it must never fall back to real time."

    Design: Corner/entities/protocol_is_immutable_and_carries_no_version_field
    """
    physician = new_physician(api)
    published = publish_protocol(api, physician["id"], "ESTRADIOL", "E2 pellet protocol v1")

    data = validate_success(api.get_protocol(published["id"], ADMIN), 200)
    assert data["protocol_version"] == 1
    assert_same_instant(data["effective_at"], "2026-05-01T00:00:00Z", "Protocol.effective_at")
    assert "updated_at" not in data, "A published Protocol must carry no updated_at"
    assert "version" not in data, "A published Protocol must carry no version"
    assert_protocol(data)


def test_protocol_versions_are_numbered_independently_per_hormone(api):
    """PRD §3.2: "The server assigns `protocol_version` as one more than the highest version
    already published for that same hormone type, so the first testosterone protocol is
    version 1, the second is version 2, and estradiol numbers independently."

    Design: Corner/entities/protocol_version_increments_per_hormone_type_independently
    """
    physician = new_physician(api)
    publish_protocol(api, physician["id"], "TESTOSTERONE", "T v1")

    second_testosterone = publish_protocol(api, physician["id"], "TESTOSTERONE", "T v2")
    first_estradiol = publish_protocol(api, physician["id"], "ESTRADIOL", "E2 v1")

    assert second_testosterone["protocol_version"] == 2
    assert first_estradiol["protocol_version"] == 1, (
        "Estradiol numbers independently of testosterone"
    )


def test_procedure_listing_reports_the_pagination_window(api):
    """PRD §2.3: "The `meta` block of a list response carries `limit` and `offset` echoing the
    effective values used, `total_count` giving the number of rows matching the filters
    before the window was applied, and `has_more` set true when rows remain beyond the
    current window."

    Design: Corner/entities/procedures_list_returns_pagination_envelope
    """
    physician = new_physician(api)
    patient = new_patient(api, "Corner Five", "c5@example.com")
    consult = record_consult(api, patient["id"], physician["id"])
    order = new_standing_order(api, physician["id"])

    from test_helpers import book_procedure

    for room, start in (
        ("RM30", "2026-06-08T09:00:00Z"),
        ("RM31", "2026-06-08T11:00:00Z"),
        ("RM32", "2026-06-08T13:00:00Z"),
    ):
        book_procedure(
            api, patient["id"], physician["id"], consult["id"], order["id"],
            room_code=room, scheduled_start=start,
        )

    response = api.list_procedures(
        FRONT_DESK, {"patient_id": patient["id"], "limit": 2, "offset": 0}
    )
    rows, meta = validate_paginated(response)
    assert response.json()["response_type"] == "array"
    assert len(rows) == 2, f"A limit of 2 must return 2 rows, got {len(rows)}"
    assert meta["total_count"] == 3
    assert meta["has_more"] is True
    assert meta["limit"] == 2
    assert meta["offset"] == 0


def test_consults_filter_narrows_to_one_patient(api):
    """PRD §2.3: "Every list endpoint also accepts the filters named in its description; a
    filter that is supplied narrows the result set by exact match on the named field, and
    filters combine conjunctively."
    PRD §2.3: "List results are ordered by `created_at` ascending unless a specific narrative
    below says otherwise."

    Design: Corner/entities/consults_filtered_by_patient_id_reverse_reachability
    """
    physician = new_physician(api)
    first = new_patient(api, "Corner Six", "c6@example.com")
    second = new_patient(api, "Corner Seven", "c7@example.com", date_of_birth="1980-01-02")
    first_consult = record_consult(api, first["id"], physician["id"], indication="Six")
    record_consult(api, second["id"], physician["id"], indication="Seven")

    response = api.list_consults(FRONT_DESK, {"patient_id": first["id"]})
    rows, meta = validate_paginated(response)
    assert response.json()["response_type"] == "array"
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [first_consult["id"]]


def test_body_foreign_keys_resolve_patient_before_physician(api):
    """PRD §2.9: "**Rung 7** — every non-null foreign key in the request body resolves, on
    every endpoint that accepts foreign keys, checked in this fixed order: `patient_id`
    first; then the provider-shaped keys `provider_id`, `physician_id`,
    `published_by_provider_id` and `reported_by_provider_id`; then `consult_id`; then
    `standing_order_id`; then `consent_record_id`; then `lab_panel_id`; then `lot_id`; then
    `procedure_id`; then `injection_visit_id`; then `series_pack_id`; then `membership_id`.
    The codes are the same per-entity not-found set as rung 6, at HTTP 404."

    Design: Corner/entities/consult_body_fk_to_missing_provider_returns_provider_not_found
    """
    from test_helpers import make_physician_headers

    physician = new_physician(api)
    patient = new_patient(api, "Corner Eight", "c8@example.com")

    response = api.create_consult(
        {
            "patient_id": patient["id"],
            "physician_id": NON_EXISTENT_UUID,
            "hormone_type": "TESTOSTERONE",
            "prescribed_dose_mg": 1000,
            "symptom_score": 55,
            "indication": "Ghost doctor",
        },
        make_physician_headers(physician["id"]),
    )
    validate_error(response, ApiErrorId.ERR_PROVIDER_NOT_FOUND.value)
    assert response.status_code == 404

    rows, meta = validate_paginated(api.list_consults(FRONT_DESK, {"patient_id": patient["id"]}))
    assert meta["total_count"] == 0, "A rejected consult must not be persisted"
