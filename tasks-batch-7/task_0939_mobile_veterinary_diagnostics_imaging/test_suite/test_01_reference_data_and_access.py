"""Reference data, identity, envelopes, pagination and the access ladder."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_append_only_fields,
    assert_clinic,
    assert_same_instant,
    make_clinic_user_headers,
    make_field_tech_headers,
    make_headers,
    new_clinic,
    new_equipment,
    new_mobile_unit,
    new_referral,
    new_technician,
    new_calibrated_equipment,
    set_clock,
    setup_mobile_scene,
    setup_telerad_scene,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
SCHED = TEST_USERS["scheduler_headers"]


def test_clinic_registration_applies_the_declared_calendar_and_posture_defaults(api):
    """PRD §3.1: "A clinic's `status` is `ACTIVE` or `SUSPENDED`, defaulting to `ACTIVE`;
    a suspended clinic may not submit new referrals, have referrals accepted, or be
    given appointments, and each such attempt is refused with `ERR_CLINIC_INACTIVE`."
    PRD §3.1: "A clinic also carries a `billing_hold_status` of `CLEAR` or `HOLD`,
    initialised to `CLEAR` at registration and settable **only** by the
    `BillingAdmin`'s billing-hold capability, which takes a `billing_hold_status`
    value in the body and toggles gate G2 for that clinic."
    PRD §2.5: "`business_open_minute`, the minute of the UTC day at which its window
    opens, defaulting to 480 (that is, 08:00 UTC); `business_close_minute`, the minute
    at which the window closes, defaulting to 1020 (17:00 UTC); and `business_days`,
    the list of weekday indices on which the window is open at all, defaulting to
    Monday through Friday, where index 0 denotes Monday and index 6 denotes Sunday."

    Design: Corner/entities/clinic_creation_returns_defaults_and_system_fields
    """
    set_clock("2026-05-04T09:00:00Z")

    response = api.create_clinic({"name": "Default Vet", "address_zone": "ZD"}, ADMIN)
    clinic = validate_success(response, expected_status=201)

    assert_clinic(clinic)
    assert clinic["business_open_minute"] == 480
    assert clinic["business_close_minute"] == 1020
    assert clinic["business_days"] == [0, 1, 2, 3, 4]
    assert clinic["billing_hold_status"] == "CLEAR"
    assert clinic["status"] == "ACTIVE"


def test_clinic_registration_stamps_version_one_and_the_logical_clock(api):
    """PRD §2.4: "`version` begins at 1 when the record is created and increases by
    exactly 1 on every mutation of that record, including mutations produced
    indirectly by a cascade from some other resource."
    PRD §2.4: "Server-generated instants are rendered with exactly three
    fractional-second digits and a trailing `Z` — for example
    `2026-05-01T00:00:00.000Z`."

    Design: Corner/entities/clinic_creation_returns_defaults_and_system_fields
    """
    set_clock("2026-05-04T09:00:00Z")

    clinic = validate_success(
        api.create_clinic({"name": "Default Vet", "address_zone": "ZD"}, ADMIN),
        expected_status=201,
    )

    assert clinic["version"] == 1
    assert_same_instant(clinic["created_at"], "2026-05-04T09:00:00Z")
    assert_same_instant(clinic["updated_at"], "2026-05-04T09:00:00Z")


def test_clinic_retrieval_returns_the_overridden_business_calendar(api):
    """PRD §2.5: "Each `Clinic` publishes three calendar fields:
    `business_open_minute`, the minute of the UTC day at which its window opens,
    defaulting to 480 (that is, 08:00 UTC); `business_close_minute`, the minute at
    which the window closes, defaulting to 1020 (17:00 UTC); and `business_days`,
    the list of weekday indices on which the window is open at all, defaulting to
    Monday through Friday, where index 0 denotes Monday and index 6 denotes Sunday."

    Design: Corner/entities/clinic_retrieval_returns_the_stored_entity
    """
    set_clock("2026-05-04T09:00:00Z")
    created = new_clinic(
        "Early Bird Vet", "ZE",
        business_open_minute=420, business_close_minute=900,
        business_days=[0, 1, 2, 3, 4, 5],
    )

    fetched = validate_success(api.get_clinic(created["id"], SCHED))

    assert fetched["id"] == created["id"]
    assert fetched["business_open_minute"] == 420
    assert fetched["business_close_minute"] == 900
    assert fetched["business_days"] == [0, 1, 2, 3, 4, 5]


def test_equipment_listing_pages_with_total_count_and_has_more(api):
    """PRD §2.3: "The `meta` block of a list response carries `limit`, `offset`,
    `total_count` — the number of records matching the filters before pagination is
    applied — and `has_more`, which is true exactly when records remain beyond the
    current page."
    PRD §2.3: "List results are ordered by `created_at` ascending unless a specific
    endpoint narrative in §3 states otherwise."

    Design: Corner/entities/equipment_listing_paginates_with_total_count_and_has_more
    """
    set_clock("2026-05-04T09:00:00Z")
    unit = new_mobile_unit("Van List")
    # Distinct creation instants so created_at ascending is a total order here.
    first = new_equipment("RADIOGRAPHY", "L-1", assigned_unit_id=unit["id"])
    set_clock("2026-05-04T09:01:00Z")
    new_equipment("ULTRASOUND", "L-2", assigned_unit_id=unit["id"])
    set_clock("2026-05-04T09:02:00Z")
    new_equipment("CT", "L-3", assigned_unit_id=unit["id"])

    page_one, meta_one = validate_paginated(
        api.list_equipment(ADMIN, params={"assigned_unit_id": unit["id"], "limit": 2, "offset": 0})
    )
    assert len(page_one) == 2
    assert meta_one["total_count"] == 3
    assert meta_one["has_more"] is True
    assert page_one[0]["id"] == first["id"]

    page_two, meta_two = validate_paginated(
        api.list_equipment(ADMIN, params={"assigned_unit_id": unit["id"], "limit": 2, "offset": 2})
    )
    assert len(page_two) == 1
    assert meta_two["total_count"] == 3
    assert meta_two["has_more"] is False


def test_pagination_limit_above_one_hundred_is_a_request_shape_failure(api):
    """PRD §2.3: "`limit` defaults to 10, has a minimum of 1 and a maximum of 100.
    `offset` defaults to 0 and has a minimum of 0. A `limit` below 1 or above 100, or
    a negative `offset`, is a request-shape failure reported as `ERR_VALIDATION`
    (HTTP 400)."

    Design: Corner/validations/pagination_limit_above_the_maximum_returns_validation_error
    """
    set_clock("2026-05-04T09:00:00Z")
    clinic = new_clinic("Page Vet", "VE")
    new_referral(clinic["id"], patient_name="Iris", requested_modality="CT")

    response = api.list_referrals(SCHED, params={"clinic_id": clinic["id"], "limit": 101, "offset": 0})

    validate_error(response, ApiErrorId.ERR_VALIDATION.value)


def test_study_get_with_an_unknown_identifier_returns_the_study_not_found_code(api):
    """PRD §2.8 rung 4: "Path-parameter resources exist, validated left to right, and
    then body-referenced identifiers exist, validated in the order they appear in the
    endpoint's input list. Each entity has its own 404 code: `ERR_CLINIC_NOT_FOUND`,
    `ERR_CONTRACT_NOT_FOUND`, `ERR_EQUIPMENT_NOT_FOUND`, `ERR_SPECIALIST_NOT_FOUND`,
    `ERR_ROUTE_NOT_FOUND`, `ERR_STOP_NOT_FOUND`, `ERR_REFERRAL_NOT_FOUND`,
    `ERR_APPOINTMENT_NOT_FOUND`, `ERR_STUDY_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`,
    `ERR_REPORT_NOT_FOUND` and `ERR_INVOICE_NOT_FOUND`."

    Design: Corner/entities/study_get_with_unknown_uuid_returns_not_found
    """
    set_clock("2026-05-04T09:00:00Z")

    response = api.get_study("8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", SCHED)

    validate_error(response, ApiErrorId.ERR_STUDY_NOT_FOUND.value)
    assert response.json()["response_type"] == "error"


NOT_FOUND_PROBES = [
    ("get_clinic", "00000000-0000-4000-8000-000000000001", ApiErrorId.ERR_CLINIC_NOT_FOUND),
    ("get_contract", "00000000-0000-4000-8000-000000000002", ApiErrorId.ERR_CONTRACT_NOT_FOUND),
    ("get_equipment", "00000000-0000-4000-8000-000000000003", ApiErrorId.ERR_EQUIPMENT_NOT_FOUND),
    ("get_specialist", "00000000-0000-4000-8000-000000000004", ApiErrorId.ERR_SPECIALIST_NOT_FOUND),
    ("get_route", "00000000-0000-4000-8000-000000000005", ApiErrorId.ERR_ROUTE_NOT_FOUND),
    ("get_route_stop", "00000000-0000-4000-8000-000000000006", ApiErrorId.ERR_STOP_NOT_FOUND),
    ("get_referral", "00000000-0000-4000-8000-000000000007", ApiErrorId.ERR_REFERRAL_NOT_FOUND),
    ("get_appointment", "00000000-0000-4000-8000-000000000008", ApiErrorId.ERR_APPOINTMENT_NOT_FOUND),
    ("get_read_assignment", "00000000-0000-4000-8000-000000000009", ApiErrorId.ERR_ASSIGNMENT_NOT_FOUND),
    ("get_report", "00000000-0000-4000-8000-00000000000a", ApiErrorId.ERR_REPORT_NOT_FOUND),
    ("get_invoice", "00000000-0000-4000-8000-00000000000b", ApiErrorId.ERR_INVOICE_NOT_FOUND),
]

RECORD_NOT_FOUND_PROBES = [
    ("get_mobile_unit", "00000000-0000-4000-8000-00000000000c"),
    ("get_technician", "00000000-0000-4000-8000-00000000000d"),
    ("get_qc_check", "00000000-0000-4000-8000-00000000000e"),
    ("get_peer_review", "00000000-0000-4000-8000-00000000000f"),
    ("get_charge_line", "00000000-0000-4000-8000-000000000010"),
    ("get_block_ledger_entry", "00000000-0000-4000-8000-000000000011"),
    ("get_notification", "00000000-0000-4000-8000-000000000012"),
]


@pytest.mark.parametrize("method_name,identifier,expected", NOT_FOUND_PROBES)
def test_each_path_addressed_collection_has_its_own_not_found_code(api, method_name, identifier, expected):
    """PRD §2.8 rung 4: "Each entity has its own 404 code: `ERR_CLINIC_NOT_FOUND`,
    `ERR_CONTRACT_NOT_FOUND`, `ERR_EQUIPMENT_NOT_FOUND`, `ERR_SPECIALIST_NOT_FOUND`,
    `ERR_ROUTE_NOT_FOUND`, `ERR_STOP_NOT_FOUND`, `ERR_REFERRAL_NOT_FOUND`,
    `ERR_APPOINTMENT_NOT_FOUND`, `ERR_STUDY_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`,
    `ERR_REPORT_NOT_FOUND` and `ERR_INVOICE_NOT_FOUND`."

    Design: Corner/errors/not_found_sweep_returns_the_per_entity_code_for_every_collection
    """
    set_clock("2026-05-04T09:00:00Z")

    response = getattr(api, method_name)(identifier, ADMIN)

    validate_error(response, expected.value)
    assert response.json()["response_type"] == "error"


@pytest.mark.parametrize("method_name,identifier", RECORD_NOT_FOUND_PROBES)
def test_the_seven_collections_without_a_dedicated_code_use_record_not_found(api, method_name, identifier):
    """PRD §2.8 rung 4: "Seven record types have no dedicated code and use
    `ERR_RECORD_NOT_FOUND` instead: `MobileUnit`, `Technician`, `QcCheck`,
    `PeerReview`, `ChargeLine`, `BlockLedgerEntry` and `Notification`. All are HTTP
    404."

    Design: Corner/errors/not_found_sweep_returns_the_per_entity_code_for_every_collection
    """
    set_clock("2026-05-04T09:00:00Z")

    response = getattr(api, method_name)(identifier, ADMIN)

    validate_error(response, ApiErrorId.ERR_RECORD_NOT_FOUND.value)
    assert response.json()["response_type"] == "error"


def test_referral_without_the_required_species_field_is_rejected(api):
    """PRD §2.8 rung 5: "Every required input field of the endpoint is present and
    correctly typed; `limit` lies between 1 and 100 inclusive and `offset` is at least
    0; every minute-of-day field is an integer between 0 and 1440 inclusive; a
    peer-review score is an integer."
    PRD §3.2: "The payload names the `clinic_id`, the `patient_name` of the animal,
    its `species` — one of `CANINE`, `FELINE`, `EQUINE`, `BOVINE` or `EXOTIC` — and
    the `study_kind`, which is the pipeline discriminator and is either `MOBILE` (a
    travelling technician will acquire the images at a route stop) or `TELERAD` (the
    clinic will upload images it acquired itself)."

    Design: Corner/entities/referral_missing_required_species_returns_invalid_request
    """
    set_clock("2026-05-04T09:00:00Z")
    clinic = new_clinic("Shape Vet", "ZS")

    response = api.create_referral(
        {
            "clinic_id": clinic["id"],
            "patient_name": "Nameless",
            "study_kind": "TELERAD",
            "requested_modality": "RADIOGRAPHY",
        },
        make_clinic_user_headers(clinic["id"]),
    )

    validate_error(response, ApiErrorId.ERR_VALIDATION.value)
    rows, _ = validate_paginated(api.list_referrals(SCHED, params={"clinic_id": clinic["id"]}))
    assert rows == []


def test_specialist_privilege_outside_the_closed_modality_enum_is_rejected(api):
    """PRD §2.8 rung 6: "Closed-enum membership**, reported as `ERR_INVALID_ENUM` (400). This list is
    **exhaustive — no other field in the system routes to this code**: a clinic's
    `status`; a contract's `kind`; a mobile unit's `service_status`; an equipment
    record's `modality`; each member of a technician's `certified_modalities`; each
    member of a specialist's `modality_privileges`; each member of a specialist's
    `species_privileges`; a specialist's `status`; a route stop's `stop_priority`; a
    referral's `species`, `study_kind`, `requested_modality` and `priority`; a
    study's `modality`, `hold_reason` and `repeat_cause`; the `qc_result` body field
    on the image-QC verdict; the `billing_hold_status` body field; the `result` body
    field on an equipment QC check; and a report's `kind`."

    Design: Corner/entities/specialist_invalid_modality_privilege_enum_rejected
    """
    set_clock("2026-05-04T09:00:00Z")

    response = api.create_specialist(
        {
            "full_name": "Dr Wrong",
            "modality_privileges": ["MRI"],
            "species_privileges": ["CANINE"],
            "stat_eligible": False,
        },
        ADMIN,
    )

    validate_error(response, ApiErrorId.ERR_INVALID_ENUM.value)


def test_study_creation_against_an_unknown_appointment_is_a_not_found(api):
    """PRD §2.8 rung 4: "Only once all path variables resolve are body-referenced
    identifiers checked, and those are checked in the order the endpoint's input
    fields are listed."
    PRD §2.8 rung 4: "Each entity has its own 404 code: `ERR_CLINIC_NOT_FOUND`,
    `ERR_CONTRACT_NOT_FOUND`, `ERR_EQUIPMENT_NOT_FOUND`, `ERR_SPECIALIST_NOT_FOUND`,
    `ERR_ROUTE_NOT_FOUND`, `ERR_STOP_NOT_FOUND`, `ERR_REFERRAL_NOT_FOUND`,
    `ERR_APPOINTMENT_NOT_FOUND`, `ERR_STUDY_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`,
    `ERR_REPORT_NOT_FOUND` and `ERR_INVOICE_NOT_FOUND`."

    Design: Corner/entities/study_creation_against_unknown_appointment_returns_not_found
    """
    set_clock("2026-05-04T09:00:00Z")
    clinic = new_clinic("Orphan Vet", "ZO")

    response = api.create_study(
        {
            "appointment_id": "11111111-2222-4333-8444-555555555555",
            "modality": "CT",
            "body_region": "HEAD",
        },
        make_clinic_user_headers(clinic["id"]),
    )

    validate_error(response, ApiErrorId.ERR_APPOINTMENT_NOT_FOUND.value)


def test_study_copies_species_kind_and_priority_from_its_parent_referral(api):
    """PRD §3.5: "Three values are copied from the parent referral at creation and are
    not client-supplied: `study_kind`, which is immutable thereafter; `species`; and
    `priority`."
    PRD §3.5: "The study's `modality` need not equal the referral's
    `requested_modality` — a clinician may ask for radiography and get an ultrasound
    ordered instead."
    PRD §3.5: "A study also carries a `priority_source` of `NATIVE` or `UPGRADED`,
    initialised to `NATIVE`, meaning the priority was fixed at order time."

    Design: Corner/entities/study_computed_species_and_kind_copied_from_referral_not_from_input
    """
    set_clock("2026-05-04T09:00:00Z")
    scene = setup_telerad_scene(
        clinic_name="Copy Vet", address_zone="ZC",
        species="FELINE", referral_priority="STAT",
        requested_modality="RADIOGRAPHY", study_modality="ULTRASOUND",
        upload=False,
    )
    study = scene["studies"][0]

    fetched = validate_success(api.get_study(study["id"], SCHED))

    assert fetched["species"] == "FELINE"
    assert fetched["study_kind"] == "TELERAD"
    assert fetched["priority"] == "STAT"
    assert fetched["priority_source"] == "NATIVE"
    assert fetched["modality"] == "ULTRASOUND"


def test_a_newly_ordered_study_starts_on_all_four_axes_at_their_initial_values(api):
    """PRD §3.5: "`workflow_status` starts at `ORDERED` and ranges over `ORDERED`,
    `ACQUIRED`, `ASSIGNED`, `READ_IN_PROGRESS`, `PRELIM_REPORTED`, `FINALIZED`,
    `REPEAT_PENDING`, `CANCELLED` and `NOT_PERFORMED`, of which the last two are
    terminal. `qc_status` starts at `PENDING_QC` and ranges over `PENDING_QC`,
    `ACCEPTED`, `REPEAT_REQUIRED` and `NON_DIAGNOSTIC`, of which `NON_DIAGNOSTIC` is
    terminal on that axis. `tat_status` starts at `ACCRUING` and ranges over
    `ACCRUING`, `PAUSED`, `MET` and `BREACHED`, the last two terminal.
    `billing_status` starts at `UNBILLED` and ranges over `UNBILLED`, `POSTED`,
    `REVERSED` and `NON_BILLABLE`, the last terminal."
    PRD §3.5: "A newly ordered study has `image_count` 0, `acquired_at` null,
    `escalated_at` null, `repeat_count` 0, `read_attempt_count` 0,
    `repeat_of_study_id` null, `repeat_cause` null, `hold_reason` null,
    `cancel_reason` null, `equipment_id` and `technician_id` null, `price_basis` null,
    and every money field at 0."
    PRD §3.8: "A STAT study is given **60 minutes measured on the wall clock**, nights
    and weekends included."

    Design: Corner/entities/study_computed_species_and_kind_copied_from_referral_not_from_input
    """
    set_clock("2026-05-04T09:00:00Z")
    scene = setup_telerad_scene(
        clinic_name="Copy Vet", address_zone="ZC",
        species="FELINE", referral_priority="STAT",
        requested_modality="RADIOGRAPHY", study_modality="ULTRASOUND",
        upload=False,
    )

    study = validate_success(api.get_study(scene["studies"][0]["id"], SCHED))

    assert study["workflow_status"] == "ORDERED"
    assert study["qc_status"] == "PENDING_QC"
    assert study["tat_status"] == "ACCRUING"
    assert study["billing_status"] == "UNBILLED"
    assert study["equipment_id"] is None
    assert study["technician_id"] is None
    assert study["tat_target_minutes"] == 60


def test_equipment_qc_check_is_an_append_only_record_with_no_version(api):
    """PRD §2.4: "Three record types are append-only historical facts and therefore
    carry **only** `id` and `created_at` — they have no `updated_at` field and no
    `version` field at all: the equipment quality-control record `QcCheck`, the
    prepaid-block movement record `BlockLedgerEntry`, and the outbound
    `Notification`."
    PRD §3.6: "A `PASS` sets the unit's `last_passing_qc_at` to the logical clock and
    resets its `usage_count_since_qc` to 0. Its `affected_study_count` is always 0."

    Design: Corner/entities/qc_check_is_append_only_with_no_version_field
    """
    set_clock("2026-05-04T09:00:00Z")
    unit = new_mobile_unit("Van Imm")
    equipment = new_calibrated_equipment(unit["id"], "ULTRASOUND", "IMM-1")
    technician = new_technician("Ines Bo", ["ULTRASOUND"])

    response = api.create_qc_check(
        {
            "equipment_id": equipment["id"],
            "performed_by_technician_id": technician["id"],
            "result": "PASS",
            "note": "phantom within tolerance",
        },
        make_field_tech_headers(technician["id"]),
    )
    check = validate_success(response, expected_status=201)

    assert_append_only_fields(check)
    assert check["affected_study_count"] == 0
    assert_same_instant(check["performed_at"], "2026-05-04T09:00:00Z")

    refreshed = validate_success(api.get_equipment(equipment["id"], ADMIN))
    assert_same_instant(refreshed["last_passing_qc_at"], "2026-05-04T09:00:00Z")
    assert refreshed["usage_count_since_qc"] == 0


def test_the_logical_clock_starts_at_the_declared_default_instant(api):
    """PRD §2.5: "Before any client sets it, the logical clock reads exactly
    `2026-05-01T00:00:00Z` — a Friday — and it must never fall back to real wall-clock
    time."

    Design: Corner/endpoints/logical_clock_defaults_to_2026_05_01_before_any_set_call
    """
    clinic = validate_success(
        api.create_clinic({"name": "Zero Hour Vet", "address_zone": "E1"}, ADMIN),
        expected_status=201,
    )

    assert_same_instant(clinic["created_at"], "2026-05-01T00:00:00Z")
    assert_same_instant(clinic["updated_at"], "2026-05-01T00:00:00Z")


def test_setting_the_logical_clock_answers_with_the_new_value(api):
    """PRD §2.5: "An administrative test-driving capability sets the clock to a
    supplied instant, carried in a field named `to_iso8601`, and answers with the new
    value under the key `current_utc`."

    Design: Corner/endpoints/logical_clock_defaults_to_2026_05_01_before_any_set_call
    """
    validate_success(api.create_clinic({"name": "Zero Hour Vet", "address_zone": "E1"}, ADMIN),
                     expected_status=201)

    data = validate_success(api.set_clock("2026-06-01T12:00:00Z", ADMIN))

    assert_same_instant(data["current_utc"], "2026-06-01T12:00:00Z")


def test_a_role_outside_the_declared_six_is_rejected_before_anything_else(api):
    """PRD §2.1: "If either header is absent, or if `X-User-Role` is not one of the six
    role names declared below, the request is rejected with `ERR_UNAUTHENTICATED`
    (HTTP 401)."

    Design: Corner/rbac/unknown_role_header_returns_unauthenticated
    """
    response = api.create_clinic(
        {"name": "Ghost Vet", "address_zone": "R1"},
        make_headers("ghost-1", "RadiologyIntern"),
    )

    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED.value)


def test_a_clinic_user_may_not_acquire_images(api):
    """PRD §2.8 rung 2: "**Role authorization.** The acting role appears in the target endpoint's
    authorized-role list — otherwise `ERR_FORBIDDEN_ROLE` (403). Applies to every
    endpoint."
    PRD §3.5: "**Mobile acquisition.** The staffing technician acquires images on
    site, supplying the `equipment_id` used, the `technician_id` doing the work, and
    the `image_count` captured."

    Design: Corner/rbac/clinic_user_cannot_acquire_images_returns_forbidden_role
    """
    set_clock("2026-05-04T08:00:00Z")
    scene = setup_mobile_scene(clinic_name="Roleguard Vet", address_zone="R2",
                               unit_name="Van R2", equipment_serial="US-R2",
                               technician_name="T R2")
    study = scene["studies"][0]

    response = api.acquire_study(
        study["id"],
        {
            "equipment_id": scene["equipment"]["id"],
            "technician_id": scene["technician"]["id"],
            "image_count": 5,
        },
        make_clinic_user_headers(scene["clinic"]["id"]),
    )

    validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE.value)
    assert validate_success(api.get_study(study["id"], SCHED))["workflow_status"] == "ORDERED"
    assert validate_success(api.get_equipment(scene["equipment"]["id"], ADMIN))["usage_count_since_qc"] == 0


def test_a_clinic_may_not_cancel_another_clinics_study(api):
    """PRD §2.8 rung 3: "`ClinicUser`: `X-User-ID` must equal the `Clinic` identifier
    that owns the targeted referral, appointment or study — for a study, reached
    through its appointment to its referral's `clinic_id`."
    PRD §2.1: "Ownership scoping applies to **write** endpoints only, and only when
    the acting role is one of the three entity-backed roles."

    Design: Corner/rbac/clinic_user_cannot_cancel_another_clinics_study_returns_not_resource_owner
    """
    set_clock("2026-05-04T09:00:00Z")
    scene = setup_telerad_scene(clinic_name="Owner Vet A", address_zone="R3",
                                study_modality="CT", requested_modality="CT",
                                body_regions=("HEAD",), upload=False)
    intruder = new_clinic("Intruder Vet B", "R3")
    study = scene["studies"][0]

    response = api.cancel_study(
        study["id"], {"cancel_reason": "not my patient"},
        make_clinic_user_headers(intruder["id"]),
    )

    validate_error(response, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)
    after = validate_success(api.get_study(study["id"], SCHED))
    assert after["workflow_status"] == "ORDERED"
    assert after["cancellation_fee_cents"] == 0


def test_a_suspended_clinic_cannot_submit_a_new_referral(api):
    """PRD §2.8 rung 15: "Referring clinic is active.** The `Clinic`'s `status` must be `ACTIVE`, otherwise
    `ERR_CLINIC_INACTIVE` (409). Applies to `POST /referrals`, `POST
    /referrals/{referral_id}/accept` and `POST /appointments`."

    Design: Corner/validations/suspended_clinic_cannot_submit_a_new_referral
    """
    set_clock("2026-05-04T09:00:00Z")
    clinic = new_clinic("Suspended Vet", "VD", status="SUSPENDED")
    assert clinic["billing_hold_status"] == "CLEAR"

    response = api.create_referral(
        {
            "clinic_id": clinic["id"],
            "patient_name": "Nix",
            "species": "CANINE",
            "study_kind": "TELERAD",
            "requested_modality": "CT",
            "priority": "ROUTINE",
            "clinical_history": "seizures",
        },
        make_clinic_user_headers(clinic["id"]),
    )

    validate_error(response, ApiErrorId.ERR_CLINIC_INACTIVE.value)
    rows, _ = validate_paginated(api.list_referrals(SCHED, params={"clinic_id": clinic["id"]}))
    assert rows == []
