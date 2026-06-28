"""CRUD, defaults, computed-field initialization, required-field and FK validation,
pagination, and RBAC denial — the breadth coverage on catalog and access control.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    is_valid_uuid,
    assert_menu_item, assert_membership, assert_patient, assert_lounge,
    create_menu_item_payload, create_membership_payload, create_patient_payload,
    create_lounge_payload, create_appointment_payload, create_nurse_payload,
    TEST_USERS, make_nurse_headers,
    setup_screen_pending_appointment, set_clock, create_menu_item, create_lounge,
    create_patient,
)
from test_helpers.constants import MISSING_UUID

ADMIN = TEST_USERS["clinic_admin_headers"]


def test_create_menu_item_returns_201_with_echoed_and_system_fields(api):
    """PRD §3.1: "A drip menu item is created with a display `name` (such as "Myers
    Cocktail"), a `tier` that is one of `MYERS`, `NAD`, or `IMMUNITY`, and a
    `base_price_cents` cash list price that must be zero or greater."
    PRD §2.4: "an integer `version` that begins at its initial value on creation and
    increments by one on each mutation."

    Design: Corner/entities/create_menu_item_returns_201_with_fields
    """
    res = api.create_menu_item(
        create_menu_item_payload(name="Myers", tier="MYERS", base_price_cents=17500),
        ADMIN)
    item = validate_success(res, 201)
    assert_menu_item(item)
    assert item["tier"] == "MYERS"
    assert item["base_price_cents"] == 17500
    assert item["version"] == 1


def test_menu_item_defaults_applied_when_omitted(api):
    """PRD §3.1: "`requires_standing_order`, which defaults to true" ... "`g6pd_sensitive`,
    which defaults to false" ... "A menu item also carries an `active` flag (default true)".

    Design: Corner/entities/menu_item_defaults_applied_when_omitted
    """
    res = api.create_menu_item(
        create_menu_item_payload(name="NAD", tier="NAD", base_price_cents=65000), ADMIN)
    item = validate_success(res, 201)
    assert item["requires_standing_order"] is True
    assert item["g6pd_sensitive"] is False
    assert item["active"] is True


def test_membership_remaining_credits_initialized_from_total(api):
    """PRD §3.2: "At creation, the computed `drip_credits_remaining` is initialized to
    equal `drip_credits_total` and the computed `addon_credits_remaining` is initialized
    to equal `addon_credits_total`. A membership's computed `status` is one of `ACTIVE`
    or `SUSPENDED` and starts `ACTIVE`."

    Design: Corner/entities/membership_remaining_credits_initialized_from_total
    """
    res = api.create_membership(
        create_membership_payload(tier="GOLD", covered_drip_tier="MYERS",
                                  drip_credits_total=4, addon_credits_total=6), ADMIN)
    mem = validate_success(res, 201)
    assert_membership(mem)
    assert mem["drip_credits_remaining"] == 4
    assert mem["addon_credits_remaining"] == 6
    assert mem["status"] == "ACTIVE"


def test_patient_open_adverse_event_count_defaults_zero(api):
    """PRD §3.1: "Each patient also exposes the computed `open_adverse_event_count`,
    which begins at 0 and reflects the number of that patient's adverse events whose
    status is either `REPORTED` or `UNDER_REVIEW`".

    Design: Corner/entities/patient_open_adverse_event_count_defaults_zero
    """
    res = api.create_patient(create_patient_payload(full_name="Pat"), ADMIN)
    patient = validate_success(res, 201)
    assert_patient(patient)
    assert patient["open_adverse_event_count"] == 0


def test_system_fields_generated_on_create(api):
    """PRD §2.4: "Every persisted resource carries a server-minted `id` formatted as a
    UUID with no type prefix" ... "an integer `version` that begins at its initial value
    on creation and increments by one on each mutation."

    Design: Corner/entities/system_fields_generated_on_create
    """
    res = api.create_lounge(create_lounge_payload(name="L1", bay_count=3), ADMIN)
    lounge = validate_success(res, 201)
    assert_lounge(lounge)
    assert lounge["version"] == 1
    assert is_valid_uuid(lounge["id"]), "id must be a UUID with no type prefix"
    assert "_" not in lounge["id"], "id must carry no type prefix"


def test_missing_required_field_rejected(api):
    """PRD §3.4 / §2.6: the request body must be well-formed — "required fields present,
    enum values valid, integers in range" — and a violation "is rejected with
    `ERR_INVALID_REQUEST` (HTTP 422)". base_price_cents is a required input for a menu item.

    Design: Corner/entities/missing_required_field_rejected
    """
    res = api.create_menu_item({"name": "Myers", "tier": "MYERS"}, ADMIN)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=422)


def test_invalid_enum_value_rejected(api):
    """PRD §3.4: the body must be well-formed with "enum values valid", else "is rejected
    with `ERR_INVALID_REQUEST` (HTTP 422)". tier must be one of MYERS/NAD/IMMUNITY (§3.1).

    Design: Corner/entities/invalid_enum_value_rejected
    """
    res = api.create_menu_item({"name": "X", "tier": "SUPER", "base_price_cents": 100}, ADMIN)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=422)


def test_appointment_lounge_id_required_for_lounge(api):
    """PRD §3.4: "`lounge_id` must be present when `location_type` is `LOUNGE` and must be
    absent when `location_type` is `MOBILE`; a violation of any of these ... is rejected
    with `ERR_INVALID_REQUEST` (HTTP 422)."

    Design: Corner/entities/appointment_lounge_id_required_for_lounge
    """
    menu_item = create_menu_item(requires_standing_order=False)
    patient = create_patient()
    res = api.create_appointment(
        {"patient_id": patient["id"], "menu_item_id": menu_item["id"],
         "location_type": "LOUNGE", "start_at": "2026-06-23T09:00:00Z"}, ADMIN)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=422)


def test_get_menu_item_not_found(api):
    """PRD §2.6: "existence of every path-referenced and foreign-key-referenced resource
    validated left to right (`ERR_NOT_FOUND`)". A read for a non-existent id returns
    `ERR_NOT_FOUND` (HTTP 404).

    Design: Corner/entities/get_menu_item_not_found
    """
    res = api.get_menu_item(MISSING_UUID, ADMIN)
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)


def test_appointment_fk_patient_not_found(api):
    """PRD §2.6: "then existence of every path-referenced and foreign-key-referenced
    resource validated left to right (`ERR_NOT_FOUND`)." A non-existent patient_id FK on
    appointment creation returns `ERR_NOT_FOUND` (404).

    Design: Corner/entities/appointment_fk_patient_not_found
    """
    menu_item = create_menu_item(requires_standing_order=False)
    lounge = create_lounge(bay_count=2)
    res = api.create_appointment(
        create_appointment_payload(MISSING_UUID, menu_item["id"], lounge_id=lounge["id"]),
        ADMIN)
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)


def test_list_appointments_paginated(api):
    """PRD §2.3: "List responses carry the pagination fields `limit`, `offset`,
    `total_count`, and `has_more` inside the `meta` object of the envelope." With two
    appointments and limit=1, total_count is 2 and has_more is true.

    Design: Corner/endpoints/list_appointments_paginated
    """
    set_clock("2026-06-22T00:00:00Z")
    menu_item = create_menu_item(requires_standing_order=False)
    lounge = create_lounge(bay_count=3)
    for start in ("2026-06-23T09:00:00Z", "2026-06-23T11:00:00Z"):
        patient = create_patient()
        api.create_appointment(
            create_appointment_payload(patient["id"], menu_item["id"],
                                       lounge_id=lounge["id"], start_at=start), ADMIN)
    data, meta = validate_paginated(api.list_appointments(ADMIN, params={"limit": 1, "offset": 0}))
    assert meta["total_count"] == 2, f"expected total_count 2, got {meta['total_count']}"
    assert meta["has_more"] is True
    assert len(data) == 1


def test_pagination_limit_out_of_bounds_rejected(api):
    """PRD §2.3: "A `limit` or `offset` outside these bounds, or any unrecognized filter
    value, is rejected with `ERR_VALIDATION_PARAM` (HTTP 400)." limit must be at least 1.

    Design: Corner/endpoints/pagination_limit_out_of_bounds_rejected
    """
    res = api.list_appointments(ADMIN, params={"limit": 0})
    validate_error(res, "ERR_VALIDATION_PARAM", expected_status=400)


def test_reverse_lookup_consents_for_appointment(api):
    """PRD §3.6: "Consents can be read individually and retrieved for an appointment as a
    reverse lookup." A screened+consented appointment yields exactly one SIGNED consent.

    Design: Corner/endpoints/reverse_lookup_consents_for_appointment
    """
    ctx = setup_screen_pending_appointment(menu_overrides={"requires_standing_order": False})
    res = api.list_appointment_consents(ctx["appointment"]["id"], ADMIN)
    data, _meta = validate_paginated(res)
    assert len(data) == 1, f"expected exactly 1 consent, got {len(data)}"
    assert data[0]["id"] == ctx["consent"]["id"]
    assert data[0]["status"] == "SIGNED"


def test_nurse_cannot_create_menu_item(api):
    """PRD §2.1: "When the headers are valid but the role is not permitted to invoke the
    requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    Creating a menu item is a ClinicAdmin-only operation (§4).

    Design: Corner/rbac/nurse_cannot_create_menu_item
    """
    nurse = validate_success(api.create_nurse(create_nurse_payload(), ADMIN), 201)
    res = api.create_menu_item({"name": "X", "tier": "MYERS", "base_price_cents": 100},
                               make_nurse_headers(nurse["id"]))
    validate_error(res, "ERR_FORBIDDEN_ROLE", expected_status=403)


def test_unauthenticated_missing_headers(api):
    """PRD §2.1: "If either header is missing or blank, or if `X-User-Role` carries a
    value that is not one of these four recognized roles, the request is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/unauthenticated_missing_headers
    """
    res = api.list_appointments(headers={})
    validate_error(res, "ERR_UNAUTHENTICATED", expected_status=401)


def test_intake_nurse_cannot_md_approve(api):
    """PRD §2.1: "When the headers are valid but the role is not permitted to invoke the
    requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §2.6: role authorization "then role authorization for the endpoint
    (`ERR_FORBIDDEN_ROLE`)" precedes the state check. md-approve is MedicalDirector-only
    (§4), so an IntakeNurse caller is rejected with ERR_FORBIDDEN_ROLE (403).

    Design: Corner/rbac/intake_nurse_cannot_md_approve
    """
    set_clock("2026-06-22T00:00:00Z")
    myers = create_menu_item(tier="MYERS", base_price_cents=17500, requires_standing_order=False)
    lounge = create_lounge(bay_count=2)
    patient = create_patient(date_of_birth="1950-01-01T00:00:00Z")
    appt = validate_success(api.create_appointment(
        create_appointment_payload(patient["id"], myers["id"], lounge_id=lounge["id"],
                                   start_at="2026-06-23T09:00:00Z"), ADMIN), 201)
    api.intake_appointment(appt["id"], {"author_user_id": "intake-1", "pregnancy": True},
                           TEST_USERS["intake_nurse_headers"])
    api.create_consent({"appointment_id": appt["id"], "signed_by_patient": True,
                        "witness_user_id": "wit-1"}, ADMIN)
    cur = validate_success(api.get_appointment(appt["id"], ADMIN), 200)
    api.schedule_appointment(appt["id"], {"expected_appointment_version": cur["version"]}, ADMIN)
    after = validate_success(api.get_appointment(appt["id"], ADMIN), 200)
    res = api.md_approve_appointment(
        appt["id"], {"expected_appointment_version": after["version"]},
        TEST_USERS["intake_nurse_headers"])
    validate_error(res, "ERR_FORBIDDEN_ROLE", expected_status=403)
