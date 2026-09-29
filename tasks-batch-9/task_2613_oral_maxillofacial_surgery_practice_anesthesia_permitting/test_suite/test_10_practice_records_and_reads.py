"""Practice-side records and reads: creation echoes, declared defaults, computed
fields, identity and validation errors, and every read family's single-row GET
and filtered list."""
from test_helpers import (
    ADMIN,
    BENEFITS,
    INVENTORY,
    SCHEDULER,
    ApiErrorId,
    CLOCK_STARTUP_DEFAULT,
    assert_adverse_event,
    assert_block_ledger_conserved,
    assert_determination,
    assert_drill,
    assert_evaluation,
    assert_imaging_study,
    assert_inspection,
    assert_lot_quantities_consistent,
    assert_pagination_meta,
    assert_patient,
    assert_permit,
    assert_practice,
    assert_reservation,
    assert_staff_member,
    assert_surgical_case,
    assert_write_once_fields,
    create_adverse_event_payload,
    create_block,
    create_case,
    create_drill_payload,
    create_evaluation_payload,
    create_imaging_study_payload,
    create_lot,
    create_patient,
    create_practice,
    create_staff,
    get_success_data,
    is_valid_uuid,
    log_drill,
    make_anesthesia_coordinator_headers,
    make_quality_reviewer_headers,
    make_surgeon_headers,
    open_determination,
    parse_iso,
    reserve_from_lot,
    schedule_inspection,
    service_line,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

UNKNOWN_ID = "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2"


def test_practice_creation_returns_every_declared_field(api):
    """PRD 3.1: "A newly registered practice has no permit, so
    `sedation_privilege_state` is stamped `UNPERMITTED`, `open_adverse_event_count`
    is 0, and `consignment_committed_cents` is 0."
    PRD 2.4: "`updated_at` is an ISO 8601 UTC timestamp with three fractional digits
    that is refreshed on every mutation of the row, and `version` is an integer that
    starts at 1 on creation and increments by exactly 1 on every mutation."
    PRD 2.4: "Every resource in the system is identified by `id`, a server-minted
    UUID."

    Design: Corner/entities/practice_creation_returns_every_declared_field
    """
    set_clock(CLOCK_STARTUP_DEFAULT)

    response = api.create_practice(
        {
            "name": "Northside OMS",
            "state_code": "OH",
            "recovery_bay_count": 3,
            "turnover_buffer_minutes": 20,
            "consignment_credit_limit_cents": 750000,
        },
        ADMIN,
    )
    data = validate_success(response, 201)
    body = response.json()

    assert body["response_type"] == "object", "a single resource answers response_type object"
    assert body["meta"]["api_request_id"].startswith("req_"), (
        f"api_request_id must start with req_, got {body['meta']['api_request_id']!r}"
    )

    assert_practice(data)
    assert data["name"] == "Northside OMS"
    assert data["state_code"] == "OH"
    assert data["recovery_bay_count"] == 3
    assert data["turnover_buffer_minutes"] == 20
    assert data["consignment_credit_limit_cents"] == 750000

    assert data["sedation_privilege_state"] == "UNPERMITTED"
    assert data["open_adverse_event_count"] == 0
    assert data["consignment_committed_cents"] == 0

    assert data["version"] == 1, "version starts at 1 on creation"
    assert is_valid_uuid(data["id"]), "the id is a bare UUID carrying no type prefix"


def test_practice_retrieval_returns_the_stored_row(api):
    """PRD 3.1: "`turnover_buffer_minutes`, the decontamination and turnover gap
    applied around every case sharing an operatory, defaults to 15 minutes, and
    `consignment_credit_limit_cents`, the ceiling on the practice's outstanding
    consignment liability, defaults to 500,000 cents — five thousand dollars of
    unpaid manufacturer stock."
    PRD 2.4: "`updated_at` is an ISO 8601 UTC timestamp with three fractional digits
    that is refreshed on every mutation of the row, and `version` is an integer that
    starts at 1 on creation and increments by exactly 1 on every mutation."

    Design: Corner/entities/practice_retrieval_returns_the_stored_row
    """
    set_clock(CLOCK_STARTUP_DEFAULT)
    practice = create_practice(
        name="Northside OMS", state_code="OH", recovery_bay_count=3,
        turnover_buffer_minutes=20,
    )

    data = validate_success(api.get_practice(practice["id"], SCHEDULER), 200)

    assert data["id"] == practice["id"]
    assert data["turnover_buffer_minutes"] == 20
    assert data["consignment_credit_limit_cents"] == 500000
    assert data["version"] == 1, "a read never mutates the row"


def test_practice_case_listing_filters_and_paginates(api):
    """PRD 2.3: "`limit` controls page size: it defaults to 10 when omitted, may not
    be smaller than 1, and may not be larger than 100."
    PRD 2.3: "`total_count` reports how many records matched the filter before the
    page window was applied, and `has_more` is true whenever records remain beyond
    the current page."
    PRD 3.4: "Cases may be listed with filters on `practice_id`, `patient_id`,
    `primary_surgeon_id`, `monitor_staff_id`, `block_id`, `prerequisite_case_id`,
    `scheduling_status`, and `clearance_status`, which is the reverse-reachability
    channel for all six of a case's foreign keys including the self-referential
    staged link."

    Design: Corner/entities/surgical_case_listing_filters_and_paginates
    """
    set_clock(CLOCK_STARTUP_DEFAULT)
    practice = create_practice(name="Northside OMS", state_code="OH", recovery_bay_count=2)
    surgeon = create_staff(practice["id"], "SURGEON", "Dr Alma Reyes")
    patient = create_patient(practice["id"], full_name="Pat List")
    for day, category in (("14", "THIRD_MOLAR"), ("15", "IMPLANT"), ("16", "PATHOLOGY")):
        create_case(
            practice["id"], patient["id"], surgeon["id"],
            f"2026-09-{day}T13:00:00Z", f"2026-09-{day}T14:00:00Z",
            planned_anesthesia_level="LOCAL_ONLY", procedure_category=category,
            total_charge_cents=50000,
        )

    query = {"practice_id": practice["id"], "scheduling_status": "DRAFT"}
    first = api.list_surgical_cases(SCHEDULER, params=dict(query, limit=2, offset=0))
    rows, meta = validate_paginated(first)

    assert first.json()["response_type"] == "array"
    assert len(rows) == 2, f"the first page holds 2 of the 3 matches, got {len(rows)}"
    assert_pagination_meta(meta, expected_limit=2, expected_offset=0,
                           expected_total=3, expected_has_more=True)

    second = api.list_surgical_cases(SCHEDULER, params=dict(query, limit=2, offset=2))
    rows_two, meta_two = validate_paginated(second)

    assert len(rows_two) == 1, f"the second page holds the remaining match, got {len(rows_two)}"
    assert_pagination_meta(meta_two, expected_offset=2, expected_total=3,
                           expected_has_more=False)

    for row in rows + rows_two:
        assert row["scheduling_status"] == "DRAFT"
        assert row["practice_id"] == practice["id"]


def test_practice_patient_read_with_unknown_id_returns_not_found(api):
    """PRD 2.6: "Third, resolution of every identifier embedded in the request path,
    failing which the answer is `ERR_RESOURCE_NOT_FOUND`."
    PRD 2.9: "those keys resolve at priority six with
    `ERR_REFERENCED_ENTITY_NOT_FOUND` (HTTP 404), which is a body-level failure and
    is deliberately distinguished from the path-level `ERR_RESOURCE_NOT_FOUND`."

    Design: Corner/entities/patient_read_with_unknown_id_returns_not_found
    """
    set_clock(CLOCK_STARTUP_DEFAULT)

    response = api.get_patient(UNKNOWN_ID, SCHEDULER)

    validate_error(response, ApiErrorId.ERR_RESOURCE_NOT_FOUND.value)
    assert response.json()["response_type"] == "error"


def test_practice_case_creation_missing_required_field_rejected(api):
    """PRD 2.6: "Fourth, on every write endpoint, structural validation of the body —
    well-formed JSON, all required fields present, no unknown fields, and a
    `service_lines` array that is neither empty nor longer than eight entries —
    failing which the answer is `ERR_INVALID_REQUEST`."
    PRD 3.4: "and `total_charge_cents`, the gross professional charge that the
    benefit machinery must later conserve exactly."

    Design: Corner/entities/surgical_case_creation_missing_required_field_rejected
    """
    set_clock(CLOCK_STARTUP_DEFAULT)
    practice = create_practice(name="Northside OMS", state_code="OH", recovery_bay_count=2)
    surgeon = create_staff(practice["id"], "SURGEON", "Dr Alma Reyes")
    patient = create_patient(practice["id"], full_name="Pat Required")

    response = api.create_surgical_case(
        {
            "practice_id": practice["id"],
            "patient_id": patient["id"],
            "primary_surgeon_id": surgeon["id"],
            "planned_anesthesia_level": "LOCAL_ONLY",
            "procedure_category": "THIRD_MOLAR",
            "planned_start": "2026-09-14T13:00:00Z",
            "planned_end": "2026-09-14T14:00:00Z",
        },
        SCHEDULER,
    )

    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)

    _, meta = validate_paginated(
        api.list_surgical_cases(SCHEDULER, params={"practice_id": practice["id"]})
    )
    assert meta["total_count"] == 0, "a rejected draft must not persist a case row"


def test_practice_optional_inputs_fall_back_to_declared_defaults(api):
    """PRD 3.1: "`turnover_buffer_minutes`, the decontamination and turnover gap
    applied around every case sharing an operatory, defaults to 15 minutes, and
    `consignment_credit_limit_cents`, the ceiling on the practice's outstanding
    consignment liability, defaults to 500,000 cents — five thousand dollars of
    unpaid manufacturer stock."
    PRD 3.1: "Two credential fields ride along: `monitoring_certified`, a boolean
    defaulting to false that records whether the member holds the
    anesthesia-assistant monitoring certificate, and `acls_expires_on`, the ISO 8601
    UTC expiry instant of the member's ACLS or PALS card, where a null means the
    member has never been certified at all."
    PRD 3.1: "Coverage is captured with three optional inputs: `medical_plan_active`
    and `dental_plan_active`, both booleans defaulting to false, and
    `dental_annual_remaining_cents`, the unspent dental annual maximum, defaulting to
    150,000 cents."

    Design: Corner/entities/optional_inputs_fall_back_to_declared_defaults
    """
    set_clock(CLOCK_STARTUP_DEFAULT)

    practice = validate_success(
        api.create_practice(
            {"name": "Defaults OMS", "state_code": "OH", "recovery_bay_count": 1}, ADMIN
        ),
        201,
    )
    assert practice["turnover_buffer_minutes"] == 15
    assert practice["consignment_credit_limit_cents"] == 500000

    monitor = validate_success(
        api.create_staff_member(
            {
                "practice_id": practice["id"],
                "full_name": "Mo Monitor",
                "role_type": "ANESTHESIA_MONITOR",
            },
            ADMIN,
        ),
        201,
    )
    assert monitor["monitoring_certified"] is False
    assert monitor["acls_expires_on"] is None, "an omitted ACLS card reads null"

    patient = validate_success(
        api.create_patient(
            {
                "practice_id": practice["id"],
                "full_name": "Pat Default",
                "date_of_birth": "1980-03-15T00:00:00Z",
                "asa_class": 2,
                "airway_class": 2,
                "weight_kg": 80,
            },
            SCHEDULER,
        ),
        201,
    )
    assert patient["medical_plan_active"] is False
    assert patient["dental_plan_active"] is False
    assert patient["dental_annual_remaining_cents"] == 150000


def test_practice_case_duration_and_recovery_minutes_are_computed(api):
    """PRD 3.4: "`duration_minutes` is the whole minutes from `planned_start` to
    `planned_end`."
    PRD 3.4: "`recovery_minutes_required` follows the anesthesia level: zero minutes
    for `LOCAL_ONLY`, 20 for `MINIMAL_SEDATION`, 45 for `MODERATE_SEDATION`, and 90
    for `DEEP_SEDATION_GENERAL`; this figure is what makes a case occupy a recovery
    bay."
    PRD 3.4: "`referral_coordination_status` starts at `PENDING` when the
    `procedure_category` is `THIRD_MOLAR` or `ORTHOGNATHIC` **and** a
    `referring_provider_npi` was supplied, and at `NOT_REQUIRED` in every other
    combination — a `TRAUMA` case with a referring NPI, or a `THIRD_MOLAR` case
    without one, are both `NOT_REQUIRED`."
    PRD 3.1: "The single derived patient field is `age_years`, the whole years
    elapsed from `date_of_birth` to the logical clock, floored."

    Design: Corner/entities/surgical_case_duration_and_recovery_minutes_are_computed
    """
    set_clock(CLOCK_STARTUP_DEFAULT)
    practice = create_practice(name="Computed OMS", state_code="OH", recovery_bay_count=2)
    surgeon = create_staff(practice["id"], "SURGEON", "Dr Alma Reyes")
    monitor = create_staff(
        practice["id"], "ANESTHESIA_MONITOR", "Mo Monitor", monitoring_certified=True
    )
    patient = create_patient(
        practice["id"], full_name="Pat Computed", date_of_birth="1980-03-15T00:00:00Z"
    )

    data = validate_success(
        api.create_surgical_case(
            {
                "practice_id": practice["id"],
                "patient_id": patient["id"],
                "primary_surgeon_id": surgeon["id"],
                "monitor_staff_id": monitor["id"],
                "planned_anesthesia_level": "MODERATE_SEDATION",
                "procedure_category": "PATHOLOGY",
                "planned_start": "2026-09-14T13:00:00Z",
                "planned_end": "2026-09-14T14:30:00Z",
                "total_charge_cents": 120000,
            },
            SCHEDULER,
        ),
        201,
    )

    assert_surgical_case(data)
    assert data["duration_minutes"] == 90
    assert data["recovery_minutes_required"] == 45
    assert data["scheduling_status"] == "DRAFT"
    assert data["clearance_status"] == "NOT_EVALUATED"
    assert data["referral_coordination_status"] == "NOT_REQUIRED", (
        "a PATHOLOGY case with no referring provider needs no coordination"
    )
    assert data["block_id"] is None

    read_patient = validate_success(api.get_patient(patient["id"], SCHEDULER), 200)
    assert read_patient["age_years"] == 46, (
        "a patient born 1980-03-15 is 46 whole years old at the 2026-08-01 clock"
    )


def test_practice_staff_member_system_fields_are_server_minted(api):
    """PRD 2.4: "Every resource in the system is identified by `id`, a server-minted
    UUID."
    PRD 2.4: "Every resource also carries `created_at`, an ISO 8601 UTC timestamp
    with three fractional digits recording the instant the row was written."
    PRD 2.4: "`updated_at` is an ISO 8601 UTC timestamp with three fractional digits
    that is refreshed on every mutation of the row, and `version` is an integer that
    starts at 1 on creation and increments by exactly 1 on every mutation."

    Design: Corner/entities/staff_member_system_fields_are_server_minted
    """
    set_clock(CLOCK_STARTUP_DEFAULT)
    practice = create_practice(name="System OMS", state_code="OH", recovery_bay_count=2)

    data = validate_success(
        api.create_staff_member(
            {
                "practice_id": practice["id"],
                "full_name": "Dr Alma Reyes",
                "role_type": "SURGEON",
                "acls_expires_on": "2027-06-30T00:00:00Z",
            },
            ADMIN,
        ),
        201,
    )

    assert_staff_member(data)
    assert data["version"] == 1
    assert is_valid_uuid(data["id"])

    read_back = validate_success(api.get_staff_member(data["id"], ADMIN), 200)
    assert read_back["id"] == data["id"]
    assert read_back["version"] == data["version"]


def test_practice_patient_asa_class_out_of_range_rejected(api):
    """PRD 2.6: "A patient's `asa_class` and `airway_class` are each an integer from 1
    to 4, `weight_kg` is greater than 0, and `dental_annual_remaining_cents` is at
    least 0."
    PRD 2.6: "A block's `room_code` is 1 to 16 characters, `release_deadline_hours`
    is at least 0 and at most 336, and `block_end` must be strictly later than
    `block_start`."
    PRD 2.6: "Violations of any of these — including `block_end` at or before
    `block_start` and `planned_end` at or before `planned_start` — return
    `ERR_INVALID_FIELD_VALUE` (HTTP 422)."

    Design: Corner/entities/patient_asa_class_out_of_range_rejected
    """
    set_clock(CLOCK_STARTUP_DEFAULT)
    practice = create_practice(name="Range OMS", state_code="OH", recovery_bay_count=2)
    surgeon = create_staff(practice["id"], "SURGEON", "Dr Alma Reyes")

    out_of_range = api.create_patient(
        {
            "practice_id": practice["id"],
            "full_name": "Pat Range",
            "date_of_birth": "1980-03-15T00:00:00Z",
            "asa_class": 5,
            "airway_class": 2,
            "weight_kg": 80,
        },
        SCHEDULER,
    )
    validate_error(out_of_range, ApiErrorId.ERR_INVALID_FIELD_VALUE.value)

    inverted_block = api.create_block_time(
        {
            "practice_id": practice["id"],
            "surgeon_id": surgeon["id"],
            "room_code": "OR-1",
            "block_start": "2026-09-14T17:00:00Z",
            "block_end": "2026-09-14T13:00:00Z",
        },
        SCHEDULER,
    )
    validate_error(inverted_block, ApiErrorId.ERR_INVALID_FIELD_VALUE.value)

    _, patient_meta = validate_paginated(
        api.list_patients(SCHEDULER, params={"practice_id": practice["id"]})
    )
    assert patient_meta["total_count"] == 0, "the rejected patient must not be persisted"
    _, block_meta = validate_paginated(
        api.list_block_times(SCHEDULER, params={"practice_id": practice["id"]})
    )
    assert block_meta["total_count"] == 0, "the rejected block must not be persisted"


def test_practice_emergency_drill_is_immutable_and_carries_no_version(api):
    """PRD 2.4: "An `EmergencyDrill` is a permanent log line: once written it is never
    edited, and a mistake is corrected by logging a fresh drill rather than by
    amending the old one."
    PRD 2.4: "Both of these carry only `id` and `created_at`; neither `updated_at` nor
    `version` exists on them, and neither appears in their responses."
    PRD 3.2: "The optional `deficiency_noted` boolean defaults to false and is the
    debrief's verdict: a drill that recorded an unresolved deficiency is excluded from
    compliance arithmetic entirely, so logging a failed rehearsal never improves the
    practice's standing."

    Design: Corner/entities/emergency_drill_is_immutable_and_carries_no_version
    """
    set_clock(CLOCK_STARTUP_DEFAULT)
    practice = create_practice(name="Immutable OMS", state_code="OH", recovery_bay_count=2)
    surgeon = create_staff(practice["id"], "SURGEON", "Dr Alma Reyes")
    monitor = create_staff(
        practice["id"], "ANESTHESIA_MONITOR", "Mo Monitor", monitoring_certified=True
    )
    drill = get_success_data(
        api.create_drill(
            create_drill_payload(
                practice["id"],
                "AIRWAY_OBSTRUCTION",
                "2026-07-01T09:00:00Z",
                [surgeon["id"], monitor["id"]],
            ),
            make_anesthesia_coordinator_headers(monitor["id"]),
        )
    )

    data = validate_success(api.get_drill(drill["id"], ADMIN), 200)

    assert data["id"] == drill["id"]
    assert_write_once_fields(data)
    assert_drill(data)
    assert "version" not in data, "an immutable drill exposes no version"
    assert "updated_at" not in data, "an immutable drill exposes no updated_at"
    assert data["deficiency_noted"] is False
    assert len(data["participant_staff_ids"]) == 2


def test_practice_imaging_study_with_unknown_patient_rejected(api):
    """PRD 2.6: "Sixth, on every write carrying a foreign key, resolution of that key
    to a live row, failing which the answer is `ERR_REFERENCED_ENTITY_NOT_FOUND`."
    PRD 2.6: "Third, resolution of every identifier embedded in the request path,
    failing which the answer is `ERR_RESOURCE_NOT_FOUND`."

    Design: Corner/entities/imaging_study_with_unknown_patient_rejected
    """
    set_clock(CLOCK_STARTUP_DEFAULT)

    response = api.create_imaging_study(
        create_imaging_study_payload(
            UNKNOWN_ID,
            modality="PANORAMIC",
            justification_code="THIRD_MOLAR_ASSESSMENT",
            acquired_at="2026-07-20T10:00:00Z",
            dose_mgy_cm2=80.0,
        ),
        ADMIN,
    )

    validate_error(response, ApiErrorId.ERR_REFERENCED_ENTITY_NOT_FOUND.value)


def test_practice_cross_practice_reference_rejected(api):
    """PRD 3.1: "Every clinical record belongs to exactly one practice, either
    directly through its own `practice_id` or transitively through the case, patient,
    or lot it hangs from, and cross-practice references are refused rather than
    silently ignored."
    PRD 3.1: "Any such mismatch is rejected with `ERR_PRACTICE_SCOPE_MISMATCH` (HTTP
    409)."

    Design: Corner/entities/flat_topology_cross_practice_reference_rejected
    """
    set_clock(CLOCK_STARTUP_DEFAULT)
    practice_a = create_practice(name="Practice A", state_code="OH", recovery_bay_count=2)
    practice_b = create_practice(name="Practice B", state_code="OH", recovery_bay_count=2)
    foreign_surgeon = create_staff(practice_b["id"], "SURGEON", "Dr Foreign")
    patient = create_patient(
        practice_a["id"], full_name="Pat Scope", date_of_birth="1980-03-15T00:00:00Z"
    )

    response = api.create_surgical_case(
        {
            "practice_id": practice_a["id"],
            "patient_id": patient["id"],
            "primary_surgeon_id": foreign_surgeon["id"],
            "planned_anesthesia_level": "LOCAL_ONLY",
            "procedure_category": "THIRD_MOLAR",
            "planned_start": "2026-09-14T13:00:00Z",
            "planned_end": "2026-09-14T14:00:00Z",
            "total_charge_cents": 50000,
        },
        SCHEDULER,
    )

    validate_error(response, ApiErrorId.ERR_PRACTICE_SCOPE_MISMATCH.value)

    _, meta = validate_paginated(
        api.list_surgical_cases(SCHEDULER, params={"practice_id": practice_a["id"]})
    )
    assert meta["total_count"] == 0, "a scope-mismatched draft leaves no case behind"


def test_practice_permit_inspection_drill_and_staff_reads(api):
    """PRD 3.2: "The new permit is stamped `status` `APPLIED`, and two derived fields
    are populated immediately: `required_drill_types`, fixed by the level applied for,
    and `drill_compliance_ratio`, computed from whatever drills the practice has
    already logged."
    PRD 3.2: "`issued_at`, `expires_at`, `remediation_deadline_at`, and
    `last_enforcement_reason` are all null on a fresh application, and
    `probation_count` is 0."
    PRD 3.2: "A permit's `status` moves through `APPLIED`, `INSPECTION_PENDING`,
    `ACTIVE`, `PROBATION`, and `SUSPENDED`, terminating in either `EXPIRED` or
    `REVOKED`; permits may be read individually or listed with `practice_id` and
    `status` filters."
    PRD 3.2: "The new inspection is stamped `status` `SCHEDULED`, with
    `inspection_score` and `outcome_recorded_at` both null and its three deficiency
    counters — `minor_deficiency_count`, `major_deficiency_count`, and
    `critical_deficiency_count` — defaulting to 0."
    PRD 3.2: "Inspections may be read individually or listed filtered by `permit_id`
    and `status`, oldest first by `created_at`."
    PRD 3.2: "Drills are immutable and carry no version of their own; they may be read
    individually or listed with `practice_id`, `drill_type`, and `deficiency_noted`
    filters, oldest first by `conducted_at` and then by `created_at`."
    PRD 3.1: "Staff may be listed with `practice_id` and `role_type` filters, which is
    how an operator answers the question the staffing matrix asks about recovery
    nurses."

    Design: Corner/entities/permit_inspection_drill_and_staff_reads
    """
    set_clock("2026-09-01T10:00:00Z")
    practice = create_practice(
        name="Compliance Read OMS", state_code="OH", recovery_bay_count=2
    )
    monitor = create_staff(
        practice["id"], "ANESTHESIA_MONITOR", "Mo Monitor", monitoring_certified=True
    )
    nurse = create_staff(practice["id"], "RECOVERY_NURSE", "Rhea Nurse")
    permit = get_success_data(
        api.create_permit(
            {
                "practice_id": practice["id"],
                "permit_level": "MODERATE_SEDATION",
                "applied_on": "2026-08-25T00:00:00Z",
            },
            ADMIN,
        )
    )
    log_drill(
        practice["id"],
        "AIRWAY_OBSTRUCTION",
        "2026-08-20T09:00:00Z",
        [monitor["id"], nurse["id"]],
    )
    log_drill(
        practice["id"],
        "LARYNGOSPASM",
        "2026-08-21T09:00:00Z",
        [monitor["id"], nurse["id"]],
    )

    permit_row = validate_success(api.get_permit(permit["id"], ADMIN), 200)
    assert_permit(permit_row)
    assert permit_row["permit_level"] == "MODERATE_SEDATION"
    assert permit_row["status"] == "APPLIED"
    assert permit_row["issued_at"] is None
    assert permit_row["expires_at"] is None
    assert float(permit_row["drill_compliance_ratio"]) == 0.50, (
        "two of the four MODERATE_SEDATION drill types are covered"
    )

    permit_rows, permit_meta = validate_paginated(
        api.list_permits(ADMIN, params={"practice_id": practice["id"], "status": "APPLIED"})
    )
    assert_pagination_meta(permit_meta, expected_total=1, expected_has_more=False)
    assert len(permit_rows) == 1 and permit_rows[0]["id"] == permit["id"]

    inspection = schedule_inspection(permit["id"], "2026-09-02T09:00:00Z")

    inspection_row = validate_success(api.get_inspection(inspection["id"], ADMIN), 200)
    assert_inspection(inspection_row)
    assert inspection_row["status"] == "SCHEDULED"
    assert inspection_row["inspection_score"] is None
    assert inspection_row["outcome_recorded_at"] is None
    assert inspection_row["minor_deficiency_count"] == 0
    assert inspection_row["major_deficiency_count"] == 0
    assert inspection_row["critical_deficiency_count"] == 0

    _, inspection_meta = validate_paginated(
        api.list_inspections(ADMIN, params={"permit_id": permit["id"]})
    )
    assert_pagination_meta(inspection_meta, expected_total=1)

    coordinator = make_anesthesia_coordinator_headers(monitor["id"])
    _, filtered_drill_meta = validate_paginated(
        api.list_drills(
            coordinator,
            params={"practice_id": practice["id"], "drill_type": "AIRWAY_OBSTRUCTION"},
        )
    )
    assert_pagination_meta(filtered_drill_meta, expected_total=1)
    _, all_drill_meta = validate_paginated(
        api.list_drills(coordinator, params={"practice_id": practice["id"]})
    )
    assert_pagination_meta(all_drill_meta, expected_total=2)

    nurse_rows, nurse_meta = validate_paginated(
        api.list_staff_members(
            ADMIN, params={"practice_id": practice["id"], "role_type": "RECOVERY_NURSE"}
        )
    )
    assert_pagination_meta(nurse_meta, expected_total=1)
    assert nurse_rows[0]["full_name"] == "Rhea Nurse"
    _, roster_meta = validate_paginated(
        api.list_staff_members(ADMIN, params={"practice_id": practice["id"]})
    )
    assert_pagination_meta(roster_meta, expected_total=2)


def test_practice_patient_block_and_evaluation_reads(api):
    """PRD 3.1: "The single derived patient field is `age_years`, the whole years
    elapsed from `date_of_birth` to the logical clock, floored."
    PRD 3.1: "Patients may be listed filtered by `practice_id`."
    PRD 3.3: "At creation the block is stamped `status` `RESERVED`, and its ledger is
    initialised: `block_duration_minutes` is the whole number of minutes from
    `block_start` to `block_end`, `committed_minutes` and `released_minutes` are both
    0, `open_minutes` equals `block_duration_minutes`, and `utilization_pct` is 0.00."
    PRD 3.3: "Blocks are readable individually and listable with `practice_id`,
    `surgeon_id`, and `status` filters."
    PRD 3.5: "The new row is stamped `status` `DRAFT` with its `provisional_risk_score`
    and `risk_band` computed immediately by the provisional variant of the risk score,
    while `final_risk_score`, `npo_solids_minutes`, `npo_clears_minutes`, `signed_at`,
    and `verified_at` are all null."
    PRD 3.5: "Start from the recorded ASA class: base points are ten times
    `asa_class_recorded`."
    PRD 3.5: "Those five contributions are added into a factor subtotal, which is then
    multiplied by the level multiplier of the case's `planned_anesthesia_level`: one
    half for `LOCAL_ONLY`, eight tenths for `MINIMAL_SEDATION`, exactly one for
    `MODERATE_SEDATION`, and one and three tenths for `DEEP_SEDATION_GENERAL`."
    PRD 3.5: "Evaluations may be read individually or listed with `case_id`,
    `evaluator_staff_id`, and `status` filters."

    Design: Corner/entities/patient_block_and_evaluation_reads
    """
    set_clock("2026-09-01T10:00:00Z")
    practice = create_practice(
        name="Scheduling Read OMS", state_code="OH", recovery_bay_count=2
    )
    surgeon = create_staff(practice["id"], "SURGEON", "Dr Alma Reyes")
    author = create_staff(practice["id"], "ANESTHESIA_MONITOR", "Nia Author")
    patient = create_patient(
        practice["id"],
        full_name="Pat Reader",
        date_of_birth="1980-03-15T00:00:00Z",
        medical_plan_active=True,
    )
    block = create_block(
        practice["id"],
        surgeon["id"],
        "2026-09-14T13:00:00Z",
        "2026-09-14T17:00:00Z",
        release_deadline_hours=48,
    )
    case = create_case(
        practice["id"],
        patient["id"],
        surgeon["id"],
        "2026-09-14T13:00:00Z",
        "2026-09-14T14:00:00Z",
        planned_anesthesia_level="LOCAL_ONLY",
        procedure_category="IMPLANT",
        total_charge_cents=90000,
    )
    coordinator = make_anesthesia_coordinator_headers(author["id"])
    evaluation = get_success_data(
        api.create_evaluation(
            case["id"],
            create_evaluation_payload(
                author["id"], case["version"], asa_class_recorded=2,
                airway_class_recorded=2, comorbidity_count=0,
            ),
            coordinator,
        )
    )

    patient_row = validate_success(api.get_patient(patient["id"], SCHEDULER), 200)
    assert_patient(patient_row)
    assert patient_row["age_years"] == 46
    assert patient_row["medical_plan_active"] is True
    assert patient_row["dental_plan_active"] is False
    assert patient_row["dental_annual_remaining_cents"] == 150000

    _, patient_meta = validate_paginated(
        api.list_patients(BENEFITS, params={"practice_id": practice["id"]})
    )
    assert_pagination_meta(patient_meta, expected_total=1, expected_has_more=False)

    block_rows, block_meta = validate_paginated(
        api.list_block_times(
            SCHEDULER, params={"practice_id": practice["id"], "status": "RESERVED"}
        )
    )
    assert_pagination_meta(block_meta, expected_total=1)
    block_row = block_rows[0]
    assert block_row["id"] == block["id"]
    assert block_row["block_duration_minutes"] == 240
    assert block_row["committed_minutes"] == 0
    assert block_row["released_minutes"] == 0
    assert block_row["open_minutes"] == 240
    assert float(block_row["utilization_pct"]) == 0.00
    assert_block_ledger_conserved(block_row)

    evaluation_row = validate_success(api.get_evaluation(evaluation["id"], coordinator), 200)
    assert_evaluation(evaluation_row)
    assert evaluation_row["status"] == "DRAFT"
    assert float(evaluation_row["provisional_risk_score"]) == 10.0, (
        "an ASA 2 factor subtotal of 20 scaled by the LOCAL_ONLY half multiplier is 10.00"
    )
    assert evaluation_row["risk_band"] == "LOW"
    assert evaluation_row["final_risk_score"] is None

    evaluation_rows, evaluation_meta = validate_paginated(
        api.list_evaluations(coordinator, params={"case_id": case["id"], "status": "DRAFT"})
    )
    assert_pagination_meta(evaluation_meta, expected_total=1)
    assert evaluation_rows[0]["id"] == evaluation["id"]


def test_practice_determination_inventory_event_and_imaging_reads(api):
    """PRD 3.6: "Opening a determination stamps `status` `DRAFT` and `submission_count`
    0, sets `dental_annual_remaining_snapshot_cents` from the patient's current
    `dental_annual_remaining_cents`, and immediately computes `route`, `primary_payer`,
    and the full allocation, so the specialist can see the split before committing to
    it."
    PRD 3.6: "When both `medical_plan_active` and `dental_plan_active` are true the
    `route` is `SPLIT`; when only `medical_plan_active` is true it is
    `MEDICAL_PRIMARY`; when only `dental_plan_active` is true it is `DENTAL_PRIMARY`;
    and when neither is true it is `SELF_PAY`."
    PRD 3.6: "Dental pays first on each line's full `charge_cents`: for each line in
    order, the want is fifty percent of the line charge rounded to whole cents, the
    amount paid is the smaller of that want and the remaining dental balance, the
    remaining balance is reduced by it, and it accumulates into `dental_allowed_cents`
    while also being remembered per line."
    PRD 3.6: "On the pure `DENTAL_PRIMARY` route `medical_allowed_cents` stays 0."
    PRD 3.6: "`patient_responsibility_cents` is then the case's `total_charge_cents`
    less `medical_allowed_cents` less `dental_allowed_cents`."
    PRD 3.7: "A received lot is stamped `status` `AVAILABLE`, with `quantity_reserved`
    at 0 and `available_quantity` equal to `quantity_on_hand`."
    PRD 3.7: "`line_subtotal_cents` is the lot's `unit_cost_cents` multiplied by the
    reservation's `quantity`."
    PRD 3.7: "`restocking_fee_cents` is `line_subtotal_cents` multiplied by that single
    rate, rounded half-up to whole cents."
    PRD 3.7: "While `HELD`, and still after it becomes `CONSUMED`, the liability is
    `line_subtotal_cents` less `consignment_credit_cents`."
    PRD 3.8: "Filing stamps `status` `REPORTED`, sets `regulator_notified` to false,
    records `reported_at` as the logical clock, and leaves `reviewer_staff_id` and
    `corrective_action_required` null."
    PRD 3.8: "`reporting_deadline_at` is `occurred_at` plus 24 hours for a `SENTINEL`
    event, plus 72 hours for a `SEVERE` one, plus 7 days for a `MODERATE` one, and plus
    30 days for a `MINOR` one."
    PRD 3.9: "`dose_flag` is `ABOVE_REFERENCE_LEVEL` when the recorded dose is strictly
    greater than its modality's reference level, and `WITHIN_PROTOCOL` otherwise;
    because the comparison is strict, a dose exactly at the reference level is
    `WITHIN_PROTOCOL`."
    PRD 3.9: "For a patient who was already 18 or older at acquisition,
    `retention_until` is that acquisition floor."
    PRD 3.9: "Studies are immutable, carry no `version`, and may be read individually
    or listed with `patient_id`, `case_id`, `modality`, and `dose_flag` filters."

    Design: Corner/entities/determination_inventory_event_and_imaging_reads
    """
    set_clock("2026-09-11T10:00:00Z")
    practice = create_practice(name="Ledger Read OMS", state_code="OH", recovery_bay_count=2)
    surgeon = create_staff(practice["id"], "SURGEON", "Dr Alma Reyes")
    patient = create_patient(
        practice["id"],
        full_name="Pat Dental",
        date_of_birth="1980-03-15T00:00:00Z",
        dental_plan_active=True,
        dental_annual_remaining_cents=150000,
    )
    case = create_case(
        practice["id"],
        patient["id"],
        surgeon["id"],
        "2026-09-20T13:00:00Z",
        "2026-09-20T14:00:00Z",
        planned_anesthesia_level="LOCAL_ONLY",
        procedure_category="IMPLANT",
        total_charge_cents=90000,
    )
    determination = open_determination(
        case["id"], [service_line("D6010", 90000, "DENTAL")]
    )
    lot = create_lot(
        practice["id"],
        manufacturer_code="NOBEL",
        catalog_reference="NB-4310",
        diameter_mm=4.3,
        length_mm=10.0,
        unit_cost_cents=20000,
        quantity_on_hand=5,
        expiry_date="2027-01-31T00:00:00Z",
        is_consignment=False,
    )
    reservation = reserve_from_lot(case["id"], lot["id"], 1)
    surgeon_headers = make_surgeon_headers(surgeon["id"])
    event = get_success_data(
        api.create_adverse_event(
            create_adverse_event_payload(
                case["id"],
                event_type="PROLONGED_RECOVERY",
                severity="MINOR",
                occurred_at="2026-09-11T09:00:00Z",
                narrative="Extended monitoring, no intervention.",
            ),
            surgeon_headers,
        )
    )
    study = get_success_data(
        api.create_imaging_study(
            create_imaging_study_payload(
                patient["id"],
                modality="PANORAMIC",
                justification_code="IMPLANT_PLANNING",
                acquired_at="2026-09-11T09:30:00Z",
                dose_mgy_cm2=90.0,
                case_id=case["id"],
            ),
            surgeon_headers,
        )
    )

    determination_row = validate_success(
        api.get_determination(determination["id"], BENEFITS), 200
    )
    assert_determination(determination_row)
    assert determination_row["route"] == "DENTAL_PRIMARY"
    assert determination_row["primary_payer"] == "DENTAL"
    assert determination_row["status"] == "DRAFT"
    assert determination_row["submission_count"] == 0
    assert determination_row["dental_allowed_cents"] == 45000
    assert determination_row["medical_allowed_cents"] == 0
    assert determination_row["patient_responsibility_cents"] == 45000

    _, determination_meta = validate_paginated(
        api.list_determinations(BENEFITS, params={"case_id": case["id"], "status": "DRAFT"})
    )
    assert_pagination_meta(determination_meta, expected_total=1)

    lot_rows, lot_meta = validate_paginated(
        api.list_implant_lots(
            INVENTORY, params={"practice_id": practice["id"], "is_consignment": "false"}
        )
    )
    assert_pagination_meta(lot_meta, expected_total=1)
    lot_row = lot_rows[0]
    assert lot_row["status"] == "AVAILABLE"
    assert lot_row["quantity_on_hand"] == 5
    assert lot_row["quantity_reserved"] == 1
    assert lot_row["available_quantity"] == 4
    assert_lot_quantities_consistent(lot_row)

    reservation_row = validate_success(
        api.get_reservation(reservation["id"], INVENTORY), 200
    )
    assert_reservation(reservation_row)
    assert reservation_row["selection_mode"] == "EXPLICIT"
    assert reservation_row["status"] == "HELD"
    assert reservation_row["line_subtotal_cents"] == 20000
    assert reservation_row["restocking_fee_cents"] == 3000
    assert reservation_row["consignment_credit_cents"] == 0
    assert reservation_row["consignment_liability_cents"] == 20000

    _, reservation_meta = validate_paginated(
        api.list_reservations(INVENTORY, params={"case_id": case["id"], "status": "HELD"})
    )
    assert_pagination_meta(reservation_meta, expected_total=1)

    reviewer_headers = make_quality_reviewer_headers(surgeon["id"])
    event_row = validate_success(api.get_adverse_event(event["id"], reviewer_headers), 200)
    assert_adverse_event(event_row)
    assert event_row["status"] == "REPORTED"
    assert event_row["regulator_notified"] is False
    assert event_row["reviewer_staff_id"] is None
    assert parse_iso(event_row["reporting_deadline_at"]) == parse_iso(
        "2026-10-11T09:00:00Z"
    ), "a MINOR event is due 30 days after it occurred"
    assert event_row["late_report"] is False

    _, event_meta = validate_paginated(
        api.list_adverse_events(
            reviewer_headers, params={"case_id": case["id"], "severity": "MINOR"}
        )
    )
    assert_pagination_meta(event_meta, expected_total=1)

    study_row = validate_success(api.get_imaging_study(study["id"], surgeon_headers), 200)
    assert_imaging_study(study_row)
    assert study_row["dose_flag"] == "WITHIN_PROTOCOL", (
        "90.0 does not exceed the 100.0 PANORAMIC reference level"
    )
    assert parse_iso(study_row["retention_until"]) == parse_iso("2033-09-11T09:30:00Z")
    assert "version" not in study_row, "an immutable study exposes no version"

    _, study_meta = validate_paginated(
        api.list_imaging_studies(surgeon_headers, params={"patient_id": patient["id"]})
    )
    assert_pagination_meta(study_meta, expected_total=1, expected_has_more=False)
