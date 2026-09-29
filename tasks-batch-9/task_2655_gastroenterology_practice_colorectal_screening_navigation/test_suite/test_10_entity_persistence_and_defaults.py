"""Persistence, defaults, derived fields and reference topology across the resource set."""
from test_helpers import (
    NON_EXISTENT_UUID,
    PATIENT_NAVIGATOR,
    PRACTICE_ADMIN,
    PATHOLOGIST,
    QUALITY_OFFICER,
    REFERRAL_COORDINATOR,
    api_client,
    apply_block_action,
    book_slot,
    check_in,
    complete_exam,
    confirm_prep,
    create_block,
    create_endoscopy_session_payload,
    create_patient_payload,
    create_procedure_booking_payload,
    create_screening_episode_payload,
    is_valid_uuid,
    list_blocks,
    list_coverage,
    list_episodes,
    list_patients,
    move_clock,
    open_episode,
    read_coverage,
    read_patient,
    register_anesthesia_clinician,
    register_endoscopist,
    register_patient,
    register_plan,
    release_coverage,
    specimen,
    staff_block,
    start_exam,
    validate_error,
    validate_paginated,
    validate_success,
)

FULL_PLAN_TERMS = {
    "plan_code": "P9",
    "payer_name": "Northline Benefit",
    "preventive_coverage_pct": 0.90,
    "diagnostic_coinsurance_pct": 0.30,
    "deductible_cents": 250000,
    "out_of_pocket_max_cents": 600000,
    "polypectomy_carveout": "PREVENTIVE_RETAINED",
    "modifier_33_honored": False,
    "anesthesia_bundled": True,
}


def test_insurance_plan_creation_echoes_every_supplied_term_in_the_success_envelope():
    """The `api_request_id` is a server-generated unique identifier for the request that starts
    with `req_`. The `response_type` is either "object" for a single resource or "array" for a
    list of resources. Every resource this API persists carries a server-minted `id` that is a
    UUID string with no type prefix, and a `created_at` timestamp recorded as an ISO 8601 UTC
    instant with three fractional digits. The `version` field starts at 1 when the resource is
    created and increases by exactly 1 on every mutation of that resource, whether the mutation
    was requested directly or applied as a side effect of an operation on a different resource.

    Design: Corner/entities/insurance_plan_creation_returns_full_row_and_envelope
    """
    move_clock("2026-09-01T00:00:00Z")
    response = api_client.create_insurance_plan(dict(FULL_PLAN_TERMS), PRACTICE_ADMIN)
    plan = validate_success(response, 201)
    body = response.json()

    assert body["response_type"] == "object"
    assert body["meta"]["api_request_id"].startswith("req_")
    assert body["meta"]["api_request_timestamp"]
    assert plan["plan_code"] == "P9"
    assert plan["payer_name"] == "Northline Benefit"
    assert plan["preventive_coverage_pct"] == 0.90
    assert plan["diagnostic_coinsurance_pct"] == 0.30
    assert plan["deductible_cents"] == 250000
    assert plan["out_of_pocket_max_cents"] == 600000
    assert plan["polypectomy_carveout"] == "PREVENTIVE_RETAINED"
    assert plan["modifier_33_honored"] is False
    assert plan["anesthesia_bundled"] is True
    assert plan["version"] == 1
    assert plan["created_at"] == "2026-09-01T00:00:00.000Z"
    assert is_valid_uuid(plan["id"])


def test_reading_a_patient_returns_the_stored_row_with_both_ledgers_at_zero():
    """Registration also seeds four bookkeeping fields that no client may set directly.
    `deductible_applied_cents` and `oop_applied_cents` are the patient's two running ledgers —
    the deductible consumed and the patient responsibility committed by claims that have
    reached a finalized state — and both start at 0. `open_episode_count` starts at 0 and is
    the count of that patient's screening episodes whose `clinical_status` is `OPEN`,
    `PROCEDURE_SCHEDULED`, or `PATHOLOGY_PENDING`. `navigation_priority` starts at `ROUTINE`
    and becomes `HIGH` whenever `open_episode_count` reaches two or more; it returns to
    `ROUTINE` whenever the count falls below two.

    Design: Corner/entities/patient_retrieval_returns_stored_row
    """
    move_clock("2026-09-01T00:00:00Z")
    plan = register_plan()
    created = register_patient(plan["id"], family_history_crc=True, asa_class=2)
    stored = read_patient(created["id"])

    assert stored["mrn"] == "MRN-0001"
    assert stored["risk_tier"] == "INCREASED"
    assert stored["deductible_applied_cents"] == 0
    assert stored["oop_applied_cents"] == 0
    assert stored["navigation_priority"] == "ROUTINE"
    assert stored["insurance_plan_id"] == plan["id"]
    assert stored["open_episode_count"] == 0


def test_patient_listing_paginates_the_filtered_set_rather_than_the_whole_roster():
    """The patient roster may be listed with optional `insurance_plan_id`, `risk_tier`, and
    `navigation_priority` filters alongside `limit` and `offset`. The `meta` object of a list
    response carries `limit` and `offset` as they were resolved for the request, `total_count`
    as the number of rows matching the filters before pagination is applied, and `has_more` as
    a boolean that is true when rows remain beyond the current page. Collections are returned
    in ascending `created_at` order — the oldest row first — unless a subsection of this
    document states otherwise for a specific resource.

    Design: Corner/entities/patient_listing_filters_and_paginates
    """
    plan = register_plan()
    patient_a = register_patient(plan["id"], mrn="MRN-0001", prior_crc_history=True)
    patient_b = register_patient(plan["id"], mrn="MRN-0002", birth_date="1972-06-22",
                                ibd_diagnosis=True)
    patient_c = register_patient(plan["id"], mrn="MRN-0003", birth_date="1970-02-14")

    first_rows, first_meta = validate_paginated(
        api_client.list_patients(PATIENT_NAVIGATOR,
                                 {"risk_tier": "HIGH", "limit": 1, "offset": 0})
    )
    second_rows, second_meta = validate_paginated(
        api_client.list_patients(PATIENT_NAVIGATOR,
                                 {"risk_tier": "HIGH", "limit": 1, "offset": 1})
    )

    assert first_meta["limit"] == 1
    assert first_meta["offset"] == 0
    assert first_meta["total_count"] == 2
    assert first_meta["has_more"] is True
    assert second_meta["limit"] == 1
    assert second_meta["offset"] == 1
    assert second_meta["total_count"] == 2
    assert second_meta["has_more"] is False
    assert [row["id"] for row in first_rows] == [patient_a["id"]]
    assert [row["id"] for row in second_rows] == [patient_b["id"]]
    assert patient_c["id"] not in (first_rows[0]["id"], second_rows[0]["id"])


def test_an_unmatched_booking_uuid_returns_the_booking_not_found_error():
    """The path parameters this API defines are `plan_id`, `patient_id`, `clinician_id`,
    `session_id`, `coverage_id`, `referral_id`, `episode_id`, `test_id`, `booking_id`,
    `report_id`, `recommendation_id`, `claim_id`, and `period_id`, and each maps to exactly one
    not-found error: `ERR_PLAN_NOT_FOUND`, `ERR_PATIENT_NOT_FOUND`, `ERR_CLINICIAN_NOT_FOUND`,
    `ERR_SESSION_NOT_FOUND`, `ERR_COVERAGE_NOT_FOUND`, `ERR_REFERRAL_NOT_FOUND`,
    `ERR_EPISODE_NOT_FOUND`, `ERR_TEST_NOT_FOUND`, `ERR_BOOKING_NOT_FOUND`,
    `ERR_PATHOLOGY_NOT_FOUND`, `ERR_RECOMMENDATION_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, and
    `ERR_QUALITY_PERIOD_NOT_FOUND`. The `error_id` is a unique, machine-readable string that
    identifies the specific error. The `message` provides a human-readable explanation of what
    went wrong.

    Design: Corner/entities/unknown_booking_id_returns_booking_not_found
    """
    response = api_client.get_procedure_booking(NON_EXISTENT_UUID, PRACTICE_ADMIN)
    error = validate_error(response, "ERR_BOOKING_NOT_FOUND")

    assert response.json()["response_type"] == "error"
    assert isinstance(error["message"], str) and error["message"]


def test_omitting_the_window_end_is_rejected_before_the_lead_endoscopist_reference():
    """Request-shape validation — `ERR_INVALID_REQUEST`. This covers missing required fields,
    unknown enum members, integers outside their declared bounds, calendar dates that are not
    in `YYYY-MM-DD` form, instants that are not ISO 8601 UTC, a `limit` outside 1 through 100,
    and a negative `offset`. A block is created with a `room_code` labelling the suite room, a
    `session_date` giving the calendar date of the block in `YYYY-MM-DD` form, a
    `window_start_utc` that is the inclusive start instant of the bookable window and a
    `window_end_utc` that is its exclusive end, and a `lead_endoscopist_id` naming the
    `Clinician` who leads it — who must be of type `ENDOSCOPIST`.

    Design: Corner/entities/session_create_missing_window_end_returns_invalid_request
    """
    payload = create_endoscopy_session_payload(NON_EXISTENT_UUID)
    payload.pop("window_end_utc")

    validate_error(api_client.create_endoscopy_session(payload, PRACTICE_ADMIN),
                   "ERR_INVALID_REQUEST")

    _, meta = list_blocks()
    assert meta["total_count"] == 0


def test_every_omitted_optional_field_falls_back_to_its_declared_default():
    """A new block is created in `status` `DRAFT` with `suspension_reason` null, and
    `capacity_minutes` is computed from the window as the whole number of minutes between
    `window_start_utc` and `window_end_utc`. Three optional block parameters follow, and each
    of them changes the arithmetic of the day: `anesthesia_mode` is either `MODERATE_SEDATION`
    or `MAC` and defaults to `MODERATE_SEDATION`; `turnover_minutes` is the number of minutes
    appended to every booking's slot to form its room occupancy interval, an integer from 0 to
    60 defaulting to 15; and `max_procedures` is the ceiling on how many non-cancelled bookings
    the block may hold, an integer from 1 to 20 defaulting to 8. A new window begins in
    `status` `OPEN` with `screening_colonoscopy_count` and `adenoma_positive_count` at 0,
    `remediation_required` false, and `adr_pct`, `benchmark_pct`, `benchmark_result`,
    `remediation_plan`, and `attesting_user_id` all empty.

    Design: Corner/entities/session_and_plan_defaults_applied_when_omitted
    """
    endoscopist = register_endoscopist()
    assert endoscopist["credential_status"] == "ACTIVE"
    assert endoscopist["adr_benchmark_pct"] == 0.25
    assert endoscopist["max_overlapping_rooms"] == 1

    block = create_block(endoscopist["id"])
    assert block["status"] == "DRAFT"
    assert block["capacity_minutes"] == 480
    assert block["booked_minutes"] == 0
    assert block["anesthesia_mode"] == "MODERATE_SEDATION"
    assert block["turnover_minutes"] == 15
    assert block["max_procedures"] == 8
    assert block["suspension_reason"] is None

    period = validate_success(
        api_client.create_quality_period(
            {"endoscopist_id": endoscopist["id"], "period_start_date": "2026-09-01",
             "period_end_date": "2026-09-30"},
            QUALITY_OFFICER,
        ),
        201,
    )
    assert period["attribution_basis"] == "PROCEDURE_DATE"
    assert period["status"] == "OPEN"
    assert period["screening_colonoscopy_count"] == 0
    assert period["adenoma_positive_count"] == 0
    assert period["remediation_required"] is False


def test_the_five_findings_fields_are_derived_from_the_specimen_histologies_alone():
    """`adenoma_count` is the number of specimens whose `histology` is `TUBULAR_ADENOMA` or
    `TUBULOVILLOUS_ADENOMA`. `sessile_serrated_count` is the number whose `histology` is
    `SESSILE_SERRATED_LESION`. `largest_adenoma_mm` is the greatest `size_mm` among the
    adenoma specimens — those two adenoma histologies only — and is 0 when there are none.
    `villous_component` is true when any specimen's `histology` is `TUBULOVILLOUS_ADENOMA`.
    `adenocarcinoma_present` is true when any specimen's `histology` is `ADENOCARCINOMA`.

    A new report is created in `status` `RECEIVED` with `amendment_count` at 0, `finalized_at`
    null, `routed_to_endoscopist_id` null, and `amendment_reason` null.

    Design: Corner/entities/pathology_report_findings_fields_are_computed_from_specimens
    """
    move_clock("2026-09-01T00:00:00Z")
    plan = register_plan(deductible_cents=150000, diagnostic_coinsurance_pct=0.20)
    endoscopist = register_endoscopist(adr_benchmark_pct=0.25)
    patient = register_patient(plan["id"])
    block = create_block(endoscopist["id"], anesthesia_mode="MODERATE_SEDATION",
                         turnover_minutes=15, max_procedures=8)
    apply_block_action(block["id"], "PUBLISH")
    episode = open_episode(patient["id"], "SCREENING_AVERAGE_RISK")
    booking = book_slot(block["id"], episode["id"], endoscopist["id"],
                        slot_start_utc="2026-09-15T13:00:00Z", duration_minutes=45)
    confirm_prep(episode["id"], patient["id"])
    check_in(booking["id"])
    start_exam(booking["id"], endoscopist["id"])
    complete_exam(booking["id"], endoscopist["id"], prep_quality_bbps=8,
                  polyps_removed_count=3, largest_polyp_mm=14, specimen_count=3)

    report = validate_success(
        api_client.create_pathology_report(
            booking["id"],
            {"accession_number": "ACC-0001",
             "specimens": [specimen("A", "TUBULOVILLOUS_ADENOMA", 9),
                           specimen("B", "HYPERPLASTIC", 14),
                           specimen("C", "SESSILE_SERRATED_LESION", 6)]},
            PATHOLOGIST,
        ),
        201,
    )

    assert report["status"] == "RECEIVED"
    assert report["adenoma_count"] == 1
    assert report["sessile_serrated_count"] == 1
    assert report["largest_adenoma_mm"] == 9
    assert report["villous_component"] is True
    assert report["adenocarcinoma_present"] is False
    assert report["high_grade_dysplasia"] is False
    assert report["amendment_count"] == 0
    assert report["finalized_at"] is None
    assert report["routed_to_endoscopist_id"] is None
    assert report["amendment_reason"] is None


def test_a_new_referral_is_born_with_its_system_fields_at_their_initial_values():
    """A new referral begins with `status` `SUBMITTED`, `info_request_rounds` at 0, and
    `risk_screen_result` at `PENDING`.

    A `ReferralCoordinator` records an inbound referral against an existing `patient_id`,
    capturing the `referring_provider_npi` of the outside provider, a `reason` drawn from
    `AVERAGE_RISK_SCREENING`, `FAMILY_HISTORY`, `POSITIVE_FIT`, `SURVEILLANCE`, or
    `SYMPTOMATIC_BLEEDING`, an `asa_class_reported` integer from 1 to 5 as stated on the
    referral, and an optional `anticoagulant_reported` boolean defaulting to false.

    Design: Corner/entities/referral_system_fields_ignore_client_supplied_values
    """
    plan = register_plan()
    patient = register_patient(plan["id"])

    referral = validate_success(
        api_client.create_referral(
            {"patient_id": patient["id"], "referring_provider_npi": "3000000001",
             "reason": "FAMILY_HISTORY", "asa_class_reported": 2},
            REFERRAL_COORDINATOR,
        ),
        201,
    )

    assert referral["status"] == "SUBMITTED"
    assert referral["info_request_rounds"] == 0
    assert referral["risk_screen_result"] == "PENDING"
    assert referral["version"] == 1
    assert referral["triage_decision_note"] is None
    assert referral["anticoagulant_reported"] is False
    assert is_valid_uuid(referral["id"])


def test_out_of_bound_integers_unknown_enum_members_and_bad_limits_all_collapse_to_one_error():
    """`asa_class` is the ASA physical status class used later by pre-procedure risk screening,
    an integer from 1 to 5 defaulting to 2.

    It is opened by a `ReferralCoordinator` or a `PatientNavigator` against a `patient_id` with
    an `indication` drawn from `SCREENING_AVERAGE_RISK`, `SCREENING_HIGH_RISK`, `SURVEILLANCE`,
    or `DIAGNOSTIC_FOLLOWUP`.

    `limit` controls page size; it defaults to 10, may be no smaller than 1, and may be no
    larger than 100. A `limit` outside the range 1 through 100 inclusive, or a negative
    `offset`, is a malformed request and is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

    Design: Corner/entities/enum_and_range_constraints_are_enforced
    """
    plan = register_plan()
    patient = register_patient(plan["id"])

    validate_error(
        api_client.create_patient(
            create_patient_payload(plan["id"], mrn="MRN-0002", birth_date="1972-06-22",
                                   asa_class=6),
            PRACTICE_ADMIN),
        "ERR_INVALID_REQUEST")
    validate_error(
        api_client.create_screening_episode(
            create_screening_episode_payload(patient["id"], "SCREENING_LOW_RISK"),
            REFERRAL_COORDINATOR),
        "ERR_INVALID_REQUEST")
    validate_error(
        api_client.list_patients(PRACTICE_ADMIN, {"limit": 101}),
        "ERR_INVALID_REQUEST")

    _, patient_meta = list_patients()
    _, episode_meta = list_episodes()
    assert patient_meta["total_count"] == 1
    assert episode_meta["total_count"] == 0


def test_an_unknown_parent_block_in_the_path_beats_the_body_reference_and_the_version_pin():
    """Path parameters are always resolved left to right: the parent identifier is validated
    first, and if it does not resolve, the parent's not-found error is returned without any
    attempt to resolve the child.

    And a booking request against a block whose headcount is already full, but which also
    carries a stale block version, reports `ERR_STALE_SESSION_VERSION`, because the
    concurrency check precedes every business rule on that endpoint.

    Design: Corner/entities/booking_requires_an_existing_parent_session_in_the_path
    """
    register_plan()
    endoscopist = register_endoscopist()

    payload = create_procedure_booking_payload(
        "00000000-0000-4000-8000-000000000001", endoscopist["id"], 99,
        slot_start_utc="2026-09-15T13:00:00Z", duration_minutes=45)

    validate_error(
        api_client.create_procedure_booking(NON_EXISTENT_UUID, payload, REFERRAL_COORDINATOR),
        "ERR_SESSION_NOT_FOUND")


def test_a_resolvable_preceding_episode_derives_surveillance_recall_and_an_unknown_one_404s():
    """It is `SURVEILLANCE_RECALL` when `preceding_episode_id` is set and `referral_id` is not.
    Foreign-key resolution for identifiers supplied in the request body, evaluated in the order
    the fields appear in the endpoint's input — the not-found error naming the unresolvable
    reference. A `preceding_episode_id` that does not resolve reports `ERR_EPISODE_NOT_FOUND`;
    an `insurance_plan_id` that does not resolve reports `ERR_PLAN_NOT_FOUND`; a
    `lead_endoscopist_id`, `anesthesia_clinician_id`, `performing_endoscopist_id`, or
    `endoscopist_id` that does not resolve reports `ERR_CLINICIAN_NOT_FOUND`; a
    `pathology_report_id` that does not resolve reports `ERR_PATHOLOGY_NOT_FOUND`.
    `navigation_priority` starts at `ROUTINE` and becomes `HIGH` whenever `open_episode_count`
    reaches two or more; it returns to `ROUTINE` whenever the count falls below two.

    Design: Corner/entities/self_referential_episode_edge_is_validated
    """
    move_clock("2026-09-01T00:00:00Z")
    plan = register_plan()
    patient = register_patient(plan["id"])
    first = open_episode(patient["id"], "SCREENING_AVERAGE_RISK")

    second = validate_success(
        api_client.create_screening_episode(
            create_screening_episode_payload(patient["id"], "SURVEILLANCE",
                                             preceding_episode_id=first["id"]),
            REFERRAL_COORDINATOR),
        201,
    )
    assert second["origin"] == "SURVEILLANCE_RECALL"
    assert second["eligibility_status"] == "ELIGIBLE"
    assert second["preceding_episode_id"] == first["id"]
    assert first["preceding_episode_id"] is None

    patient_row = read_patient(patient["id"])
    assert patient_row["open_episode_count"] == 2
    assert patient_row["navigation_priority"] == "HIGH"

    validate_error(
        api_client.create_screening_episode(
            create_screening_episode_payload(patient["id"], "SURVEILLANCE",
                                             preceding_episode_id=NON_EXISTENT_UUID),
            REFERRAL_COORDINATOR),
        "ERR_EPISODE_NOT_FOUND")


def test_coverage_rows_stay_listable_under_their_block_after_release():
    """A coverage row is created in `status` `ACTIVE`, and its `session_id` records the block
    it staffs. Coverage rows may be listed with optional `session_id`,
    `anesthesia_clinician_id`, and `status` filters. A coverage interval beginning exactly when
    another ends therefore adds no load. The inverse operation releases a coverage row: it sets
    that row's `status` to `RELEASED` so it stops counting toward its clinician's overlap
    ceiling, returns the released row as the response payload, moves the block
    `COVERAGE_CONFIRMED → PUBLISHED` when no `ACTIVE` fully covering row remains on it, and
    increments the block's `version` by 1.

    Design: Corner/entities/coverage_children_are_reachable_from_their_session
    """
    move_clock("2026-09-01T00:00:00Z")
    endoscopist = register_endoscopist()
    anesthetist = register_anesthesia_clinician(max_overlapping_rooms=1)
    first_block = create_block(endoscopist["id"], room_code="ENDO-1",
                               window_start_utc="2026-09-15T13:00:00Z",
                               window_end_utc="2026-09-15T17:00:00Z", anesthesia_mode="MAC")
    apply_block_action(first_block["id"], "PUBLISH")
    second_block = create_block(endoscopist["id"], room_code="ENDO-2",
                                window_start_utc="2026-09-15T17:00:00Z",
                                window_end_utc="2026-09-15T21:00:00Z", anesthesia_mode="MAC")
    apply_block_action(second_block["id"], "PUBLISH")
    first_coverage = staff_block(first_block["id"], anesthetist["id"],
                                 "2026-09-15T13:00:00Z", "2026-09-15T17:00:00Z")
    second_coverage = staff_block(second_block["id"], anesthetist["id"],
                                  "2026-09-15T17:00:00Z", "2026-09-15T21:00:00Z")

    rows, meta = list_coverage({"session_id": first_block["id"]})
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [first_coverage["id"]]
    assert rows[0]["session_id"] == first_block["id"]

    released = release_coverage(first_coverage["id"])
    assert released["id"] == first_coverage["id"]
    assert released["status"] == "RELEASED"

    released_rows, released_meta = list_coverage(
        {"anesthesia_clinician_id": anesthetist["id"], "status": "RELEASED"})
    assert released_meta["total_count"] == 1
    assert [row["id"] for row in released_rows] == [first_coverage["id"]]

    surviving = read_coverage(second_coverage["id"])
    assert surviving["status"] == "ACTIVE"
    assert surviving["session_id"] == second_block["id"]
