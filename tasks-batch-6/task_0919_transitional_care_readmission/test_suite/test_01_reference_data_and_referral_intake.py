"""Programme reference data and the ordered discharge-referral intake gauntlet."""
from test_helpers import (
    ADMIN,
    INTAKE,
    ApiErrorId,
    add_navigator,
    assert_navigator,
    assert_patient,
    assert_payer,
    assert_referral,
    assert_same_instant,
    create_patient_payload,
    create_referral,
    create_referral_payload,
    read_navigator,
    read_patient,
    set_clock,
    setup_episode,
    setup_program,
    setup_program_with_episode,
    validate_error,
    validate_paginated,
    validate_success,
)

UNKNOWN_UUID = "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2"


def test_register_patient_returns_created_resource_with_zeroed_counters(api):
    """PRD §4: "Endpoints that bring a brand-new resource into existence respond
    with HTTP 201; every other successful call responds with HTTP 200."
    PRD §3.1: "A freshly registered patient starts with all three of its rolling
    counters at 0: `open_episode_count`, which counts that patient's care
    episodes in `INTAKE`, `ACTIVE` or `SERVICE_PERIOD_CLOSED`;
    `lifetime_episode_count`, which counts every care episode the patient has
    ever had in any status; and `lifetime_readmission_count`, which counts the
    recorded readmission events across all of the patient's episodes that count
    toward the readmission rate."
    PRD §2.5: "`version` is an integer that starts at 1 when the row is created
    and increments by exactly 1 on every mutation of that row."

    Design: Corner/entities/create_patient_returns_201_with_all_declared_fields
    """
    set_clock("2026-05-01T16:00:00Z")
    payload = create_patient_payload(
        external_mrn="MRN-E101",
        full_name="Ana Beck",
        date_of_birth="1950-01-01",
        primary_language="PT",
    )
    resp = api.create_patient(payload, ADMIN)
    data = validate_success(resp, 201)
    assert_patient(data)
    assert data["external_mrn"] == "MRN-E101"
    assert data["full_name"] == "Ana Beck"
    assert data["date_of_birth"] == "1950-01-01"
    assert data["primary_language"] == "PT"
    assert data["open_episode_count"] == 0
    assert data["lifetime_episode_count"] == 0
    assert data["lifetime_readmission_count"] == 0
    assert data["version"] == 1
    body = resp.json()
    assert body["response_type"] == "object"
    assert str(body["meta"]["api_request_id"]).startswith("req_")
    assert body["meta"]["api_request_timestamp"]


def test_patient_primary_language_defaults_to_en(api):
    """PRD §3.1: "An optional `primary_language` holds the ISO-639-1 code used
    for outreach and defaults to `EN` when omitted."

    Design: Corner/entities/patient_primary_language_defaults_to_en_when_omitted
    """
    set_clock("2026-05-01T16:00:00Z")
    payload = {
        "external_mrn": "MRN-E102",
        "full_name": "Bo Chen",
        "date_of_birth": "1951-02-02",
    }
    data = validate_success(api.create_patient(payload, ADMIN), 201)
    assert data["primary_language"] == "EN"


def test_payer_and_navigator_defaults_are_applied(api):
    """PRD §3.1: "a `tcm_rate_multiplier`, which must be greater than 0 and at
    most 2.0 and defaults to 1.0; a `coinsurance_rate` between 0 and 0.5
    inclusive, defaulting to 0.2; and a `contact_deadline_basis` of either
    `BUSINESS_DAYS` or `CALENDAR_HOURS`, defaulting to `BUSINESS_DAYS`."
    PRD §3.1: "Registering a transitional-care navigator captures a `full_name`,
    an `active_episode_cap` which is an integer between 1 and 40 inclusive and
    defaults to 5, and a `cap_policy` of either `COUNT` or `WEIGHTED`,
    defaulting to `COUNT`. A new navigator starts with `active_episode_count`
    and `workload_score` at 0 and `availability_status` at `AVAILABLE`;
    `availability_status` reads `AVAILABLE` while `workload_score` is strictly
    less than `active_episode_cap` and `AT_CAP` otherwise, and it is recomputed
    every time the navigator's caseload moves."

    Design: Corner/entities/payer_and_navigator_defaults_applied_when_omitted
    """
    set_clock("2026-05-01T16:00:00Z")
    payer = validate_success(
        api.create_payer({"name": "Bare Plan", "tcm_covered": True}, ADMIN), 201
    )
    assert_payer(payer)
    assert float(payer["tcm_rate_multiplier"]) == 1.0
    assert float(payer["coinsurance_rate"]) == 0.2
    assert payer["contact_deadline_basis"] == "BUSINESS_DAYS"

    navigator = validate_success(
        api.create_navigator({"full_name": "Bare Nav"}, ADMIN), 201
    )
    assert_navigator(navigator)
    assert navigator["active_episode_cap"] == 5
    assert navigator["cap_policy"] == "COUNT"
    assert navigator["active_episode_count"] == 0
    assert float(navigator["workload_score"]) == 0
    assert navigator["availability_status"] == "AVAILABLE"


def test_referral_is_stamped_from_the_logical_clock_and_opens_in_received(api):
    """PRD §3.1: "The referral is stamped with a `referred_at` reading of the
    logical clock and enters `RECEIVED`; `closure_reason_code` and
    `created_episode_id` are both null at this point."

    Design: Corner/entities/referral_system_fields_are_server_stamped
    """
    ctx = setup_program(clock="2026-05-02T08:30:00Z")
    patient = validate_success(
        api.create_patient(
            create_patient_payload(
                external_mrn="MRN-E104", full_name="Dee Vale", date_of_birth="1953-04-04"
            ),
            ADMIN,
        ),
        201,
    )
    payload = create_referral_payload(patient["id"], ctx["facility_id"], ctx["payer_id"])
    referral = validate_success(api.create_referral(payload, INTAKE), 201)
    assert_referral(referral)
    assert_same_instant(
        referral["referred_at"], "2026-05-02T08:30:00.000Z", "referred_at"
    )
    assert referral["status"] == "RECEIVED"
    assert referral["closure_reason_code"] is None
    assert referral["created_episode_id"] is None


def test_unknown_episode_id_reports_the_episode_specific_not_found(api):
    """PRD §2.5: "The `{episode_id}` segment is special-cased: whenever a path
    contains it, failure to resolve it to an existing `CareEpisode` is reported
    as `ERR_EPISODE_NOT_FOUND` with HTTP 404, and that check runs before any
    other identifier is examined."

    Design: Corner/entities/get_episode_with_unknown_uuid_returns_episode_not_found
    """
    set_clock("2026-05-01T16:00:00Z")
    resp = api.get_episode(UNKNOWN_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_EPISODE_NOT_FOUND.value)
    assert resp.json()["response_type"] == "error"


def test_unknown_navigator_id_reports_the_generic_not_found(api):
    """PRD §2.5: "Every other identifier — whether it arrives as a path segment
    or as a foreign key in the request body — is reported as
    `ERR_RESOURCE_NOT_FOUND` with HTTP 404, and those identifiers are examined
    left to right through the path and then in body-field declaration order:
    `patient_id`, `facility_id`, `payer_id`, `navigator_id`, `referral_id`,
    `risk_assessment_id`, `contact_attempt_id`, `visit_id`,
    `med_reconciliation_id`, `discrepancy_id`, `barrier_id`, `red_flag_id`,
    `readmission_id`, `claim_id`, `handoff_id`, `to_navigator_id`."

    Design: Corner/entities/get_navigator_with_unknown_uuid_returns_resource_not_found
    """
    set_clock("2026-05-01T16:00:00Z")
    validate_error(
        api.get_navigator(UNKNOWN_UUID, ADMIN), ApiErrorId.ERR_RESOURCE_NOT_FOUND.value
    )


def test_referral_without_admission_acuity_fails_request_validation(api):
    """PRD §2.10: "Every required body field is present, carries the declared
    JSON type, and satisfies its numeric, format or ordering constraint —
    otherwise `ERR_VALIDATION` (400)."

    Design: Corner/entities/referral_missing_required_field_returns_invalid_request
    """
    ctx = setup_program()
    patient = validate_success(
        api.create_patient(create_patient_payload(external_mrn="MRN-E105"), ADMIN), 201
    )
    payload = create_referral_payload(patient["id"], ctx["facility_id"], ctx["payer_id"])
    payload.pop("admission_acuity")
    validate_error(api.create_referral(payload, INTAKE), ApiErrorId.ERR_VALIDATION.value)
    rows, meta = validate_paginated(
        api.list_referrals(ADMIN, params={"patient_id": patient["id"]})
    )
    assert meta["total_count"] == 0
    assert rows == []


def test_observation_referral_without_length_of_stay_hours_is_invalid(api):
    """PRD §2.10: "This rung also covers the conditional requiredness on
    referral creation (`length_of_stay_days` is required when `stay_type` is
    `INPATIENT`; `length_of_stay_hours` is required when `stay_type` is
    `OBSERVATION`) and the requirement that `scheduled_end` be strictly after
    `scheduled_start`."
    PRD §3.1: "an observation referral requires `length_of_stay_hours`, a whole
    number of hours between 0 and 240 inclusive, and ignores
    `length_of_stay_days`."

    Design: Corner/entities/observation_referral_missing_length_of_stay_hours_returns_invalid_request
    """
    ctx = setup_program()
    patient = validate_success(
        api.create_patient(create_patient_payload(external_mrn="MRN-E106"), ADMIN), 201
    )
    payload = create_referral_payload(
        patient["id"], ctx["facility_id"], ctx["payer_id"], stay_type="OBSERVATION"
    )
    payload.pop("length_of_stay_days", None)
    payload.pop("length_of_stay_hours", None)
    validate_error(api.create_referral(payload, INTAKE), ApiErrorId.ERR_VALIDATION.value)


def test_unknown_barrier_type_routes_to_the_enum_error(api):
    """PRD §2.10: "Every supplied enum-typed body field carries a declared
    member value — otherwise `ERR_INVALID_ENUM` (400). The complete set of body
    fields that route to this error is: `discharge_disposition`, `stay_type` and
    `admission_acuity` on referral creation; `outcome` on referral closure, on
    visit encounter closure and on barrier closure; `facility_type` and
    `network_status` on facility registration; `contact_deadline_basis` on payer
    registration; `cap_policy` on navigator registration; `modality` on logging
    a contact attempt; `outcome` on recording a contact-attempt disposition; the
    members of `documented_elements` on visit completion and on visit
    amendment; `discrepancy_type` and `severity` on appending a discrepancy;
    `disposition` on dispositioning a discrepancy; `barrier_type` on raising a
    barrier; `category` and `initial_tier` on raising a red flag;
    `resolution_outcome` on resolving a red flag; `classification` on recording
    a readmission; `handoff_type` on proposing a handoff; `response` on
    responding to a handoff; and `outcome` and `denial_reason_code` on claim
    adjudication. No other field routes to this error."

    Design: Corner/entities/invalid_enum_value_on_barrier_type_returns_invalid_enum
    """
    ctx, ep = setup_program_with_episode()
    validate_error(
        api.raise_barrier(
            ep["episode_id"],
            {"barrier_type": "CHILDCARE", "description": "unlisted barrier type"},
            ep["nav_headers"],
        ),
        ApiErrorId.ERR_INVALID_ENUM.value,
    )
    _, meta = validate_paginated(
        api.list_barriers(ADMIN, params={"episode_id": ep["episode_id"]})
    )
    assert meta["total_count"] == 0


def test_episode_listing_paginates_and_filters_by_navigator(api):
    """PRD §2.3: "The `meta` block of a list response carries `limit` and
    `offset` echoing the effective values used, `total_count` giving the number
    of rows matching the filters before pagination was applied, and `has_more`
    set to true when rows remain beyond the current page."
    PRD §3.1: "Care episodes may be read individually, exposing every derived
    field, both status axes and all four readmission counters, or listed with
    filters on `patient_id`, `navigator_id`, `referral_id`, `payer_id`,
    `facility_id` and `status`."

    Design: Corner/entities/list_episodes_paginates_and_filters_by_navigator
    """
    ctx = setup_program()
    nav2, _ = add_navigator(ctx, full_name="Owen Park")
    setup_episode(ctx)
    setup_episode(ctx)
    setup_episode(ctx, navigator_id=nav2["id"])

    rows, meta = validate_paginated(
        api.list_episodes(ADMIN, params={"navigator_id": ctx["navigator_id"], "limit": 1, "offset": 0})
    )
    assert len(rows) == 1
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert meta["limit"] == 1
    assert meta["offset"] == 0
    assert all(row["navigator_id"] == ctx["navigator_id"] for row in rows)

    all_rows, all_meta = validate_paginated(
        api.list_episodes(ADMIN, params={"limit": 10, "offset": 0})
    )
    assert len(all_rows) == 3
    assert all_meta["total_count"] == 3
    assert all_meta["has_more"] is False


def test_hospice_disposition_fails_the_first_gauntlet_rung(api):
    """PRD §3.1: "The four ineligible dispositions — `HOSPICE`, `LTACH`,
    `EXPIRED` and `AMA` — are rejected with `ERR_DISPOSITION_INELIGIBLE`."

    Design: Corner/validations/intake_rung1_ineligible_disposition_rejected
    """
    ctx = setup_program()
    referral = create_referral(ctx, discharge_disposition="HOSPICE")
    validate_error(
        api.accept_referral(
            referral["id"], {"navigator_id": ctx["navigator_id"]}, INTAKE
        ),
        ApiErrorId.ERR_DISPOSITION_INELIGIBLE.value,
    )
    after = validate_success(api.get_referral(referral["id"], ADMIN))
    assert after["status"] == "RECEIVED"
    assert after["created_episode_id"] is None


def test_uncovered_payer_is_reported_before_out_of_network_facility(api):
    """PRD §3.1: "All of the screening happens when an `IntakeCoordinator`
    accepts the referral, and it happens as an **ordered gauntlet** whose
    sequence is observable: the first failing rung decides the response, so a
    referral that fails several rungs always reports the earliest one."
    PRD §3.1: "Fourth, the payer must have `tcm_covered` true, or the acceptance
    is rejected with `ERR_PAYER_NOT_COVERED`."

    Design: Corner/validations/intake_rung4_payer_not_covered_preempts_rung5_out_of_network
    """
    ctx = setup_program(
        facility_overrides={
            "name": "Rural Annex",
            "facility_type": "CRITICAL_ACCESS",
            "network_status": "OUT_OF_NETWORK",
        },
        payer_overrides={"name": "No TCM Plan", "tcm_covered": False},
    )
    referral = create_referral(ctx)
    validate_error(
        api.accept_referral(
            referral["id"], {"navigator_id": ctx["navigator_id"]}, INTAKE
        ),
        ApiErrorId.ERR_PAYER_NOT_COVERED.value,
    )


def test_out_of_network_facility_fails_the_last_gauntlet_rung(api):
    """PRD §3.1: "Fifth and last, the facility's `network_status` must read
    `IN_NETWORK`, or the acceptance is rejected with
    `ERR_FACILITY_OUT_OF_NETWORK`."

    Design: Corner/validations/intake_rung5_out_of_network_facility_rejected
    """
    ctx = setup_program(
        facility_overrides={
            "name": "Rural Annex",
            "facility_type": "CRITICAL_ACCESS",
            "network_status": "OUT_OF_NETWORK",
        }
    )
    referral = create_referral(ctx)
    validate_error(
        api.accept_referral(
            referral["id"], {"navigator_id": ctx["navigator_id"]}, INTAKE
        ),
        ApiErrorId.ERR_FACILITY_OUT_OF_NETWORK.value,
    )


def test_second_in_window_referral_for_an_enrolled_patient_is_rejected(api):
    """PRD §3.1: "Third, the patient must have no open episode — an
    `open_episode_count` of exactly 0 — since a patient already in `INTAKE`,
    `ACTIVE` or `SERVICE_PERIOD_CLOSED` cannot be enrolled twice; a duplicate
    enrolment is rejected with `ERR_EPISODE_ALREADY_OPEN`."

    Design: Corner/validations/intake_rung3_episode_already_open_within_window
    """
    ctx, ep = setup_program_with_episode()
    second = create_referral(ctx, patient_id=ep["patient_id"])
    validate_error(
        api.accept_referral(second["id"], {"navigator_id": ctx["navigator_id"]}, INTAKE),
        ApiErrorId.ERR_EPISODE_ALREADY_OPEN.value,
    )
    assert read_patient(ctx, ep["patient_id"])["open_episode_count"] == 1
    assert read_navigator(ctx, ctx["navigator_id"])["active_episode_count"] == 1


def test_intake_window_error_preempts_the_already_open_error(api):
    """PRD §2.10: "When a single request would fail more than one rule, the rule
    with the **lowest rung number** below decides the response. This ordering is
    normative: an implementation that reports a later rung's error where an
    earlier rung also failed is wrong, even if both conditions genuinely hold."
    PRD §3.1: "Second, the referral must be timely: the calendar date on which
    it was recorded must fall on or before the discharge date plus two days, so
    a discharge on 2026-05-01 admits referrals dated 2026-05-01, 2026-05-02 or
    2026-05-03, and anything later is rejected with `ERR_INTAKE_WINDOW_EXPIRED`."

    Design: Difficulty/priority_pair_validation_conflict/intake_window_preempts_episode_already_open
    """
    ctx, ep = setup_program_with_episode()
    set_clock("2026-05-10T10:00:00Z")
    late = create_referral(ctx, patient_id=ep["patient_id"])
    validate_error(
        api.accept_referral(late["id"], {"navigator_id": ctx["navigator_id"]}, INTAKE),
        ApiErrorId.ERR_INTAKE_WINDOW_EXPIRED.value,
    )


def test_gauntlet_rejection_leaves_the_referral_and_every_counter_untouched(api):
    """PRD §3.1: "Second, the referral must be timely: the calendar date on
    which it was recorded must fall on or before the discharge date plus two
    days, so a discharge on 2026-05-01 admits referrals dated 2026-05-01,
    2026-05-02 or 2026-05-03, and anything later is rejected with
    `ERR_INTAKE_WINDOW_EXPIRED`."
    PRD §3.1: "The patient's `open_episode_count` and `lifetime_episode_count`
    each increase by 1."

    Design: Difficulty/priority_pair_validation_conflict/intake_window_preempts_episode_already_open
    """
    ctx, ep = setup_program_with_episode()
    set_clock("2026-05-10T10:00:00Z")
    late = create_referral(ctx, patient_id=ep["patient_id"])
    validate_error(
        api.accept_referral(late["id"], {"navigator_id": ctx["navigator_id"]}, INTAKE),
        ApiErrorId.ERR_INTAKE_WINDOW_EXPIRED.value,
    )
    after = validate_success(api.get_referral(late["id"], ADMIN))
    assert after["status"] == "RECEIVED"
    assert after["created_episode_id"] is None
    patient = read_patient(ctx, ep["patient_id"])
    assert patient["open_episode_count"] == 1
    assert patient["lifetime_episode_count"] == 1


def test_denied_referral_is_terminal_and_mints_no_episode(api):
    """PRD §3.1: "Closure takes an `outcome` of either `DENIED` or `WITHDRAWN`
    and a `closure_reason_code` of `NOT_ELIGIBLE`, `DUPLICATE`,
    `PATIENT_DECLINED` or `OTHER`."
    PRD §3.1: "Acceptance is legal only from `RECEIVED`; attempting it on a
    referral that has already been accepted, denied or withdrawn is an
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/referral_closed_as_denied_is_terminal
    """
    ctx = setup_program()
    referral = create_referral(ctx)
    closed = validate_success(
        api.close_referral(
            referral["id"],
            {"outcome": "DENIED", "closure_reason_code": "PATIENT_DECLINED"},
            INTAKE,
        )
    )
    assert closed["status"] == "DENIED"
    assert closed["closure_reason_code"] == "PATIENT_DECLINED"
    assert closed["created_episode_id"] is None

    validate_error(
        api.accept_referral(
            referral["id"], {"navigator_id": ctx["navigator_id"]}, INTAKE
        ),
        ApiErrorId.ERR_INVALID_STATE.value,
    )
    assert read_patient(ctx, referral["_patient_id"])["open_episode_count"] == 0
    assert read_patient(ctx, referral["_patient_id"])["lifetime_episode_count"] == 0
    assert read_navigator(ctx, ctx["navigator_id"])["active_episode_count"] == 0


def test_acceptance_returns_every_derived_field_and_counter_immediately(api):
    """PRD §3.1: "The episode's `service_period_end_date` is set to
    `discharge_date` plus 29 days and its `readmission_window_end_date` to
    `discharge_date` plus 30 days. The patient's `open_episode_count` and
    `lifetime_episode_count` each increase by 1. The navigator's
    `active_episode_count` increases by 1, and their `workload_score` and
    `availability_status` are recomputed."
    PRD §3.2: "A score of 45 or more is `SEVERE`; a score from 32 through 44 is
    `HIGH`; a score from 18 through 31 is `MODERATE`; anything below 18 is
    `LOW`."

    Design: Corner/consistency_model/accept_returns_every_derived_field_in_the_same_request
    """
    ctx, ep = setup_program_with_episode()
    episode = validate_success(api.get_episode(ep["episode_id"], INTAKE))
    assert episode["risk_score"] == 44
    assert episode["risk_tier"] == "HIGH"
    assert episode["contact_sla_business_days"] == 2
    assert_same_instant(
        episode["contact_deadline_at"], "2026-05-05T23:59:59.999Z", "contact_deadline_at"
    )
    assert episode["visit_due_date"] == "2026-05-08"
    assert episode["service_period_end_date"] == "2026-05-30"
    assert episode["readmission_window_end_date"] == "2026-05-31"

    patient = read_patient(ctx, ep["patient_id"])
    assert patient["open_episode_count"] == 1
    assert patient["lifetime_episode_count"] == 1
    navigator = read_navigator(ctx, ctx["navigator_id"])
    assert navigator["active_episode_count"] == 1
    assert float(navigator["workload_score"]) == 1
    assert navigator["availability_status"] == "AVAILABLE"

    rows, meta = validate_paginated(
        api.list_risk_assessments(ADMIN, params={"episode_id": ep["episode_id"]})
    )
    assert meta["total_count"] == 1
    assert rows[0]["is_current"] is True
    assert rows[0]["supersedes_id"] is None


def test_acceptance_creates_the_episode_in_intake_with_open_records(api):
    """PRD §3.1: "A new `CareEpisode` is created in `status` `INTAKE` with
    `record_posture` `OPEN`, copying `patient_id`, `payer_id`, `facility_id`,
    `discharge_date` and `discharge_datetime` from the referral and taking the
    supplied `navigator_id`; the referral's `created_episode_id` is set to the
    new episode's `id`, and the episode's `referral_id` points back."
    PRD §3.3: "The episode tracks this on its own axis, `contact_status`, which
    begins at `NOT_STARTED`, moves to `IN_PROGRESS` as soon as the first
    outreach attempt is logged, and ends at either `SUCCESSFUL` or `REFUSED`."

    Design: Corner/entities/episode_computed_fields_ignore_client_supplied_values
    """
    ctx, ep = setup_program_with_episode()
    episode = validate_success(api.get_episode(ep["episode_id"], ADMIN))
    assert episode["status"] == "INTAKE"
    assert episode["record_posture"] == "OPEN"
    assert episode["risk_score"] == 44
    assert episode["risk_tier"] == "HIGH"
    assert episode["patient_id"] == ep["patient_id"]
    assert episode["payer_id"] == ctx["payer_id"]
    assert episode["facility_id"] == ctx["facility_id"]
    assert episode["referral_id"] == ep["referral_id"]
    assert episode["contact_status"] == "NOT_STARTED"
    assert episode["contact_attempt_count"] == 0
    assert episode["contact_timely"] is False
    assert episode["medrec_complete"] is False
    assert episode["billing_eligible"] is True
    assert episode["service_period_end_date"] == "2026-05-30"
    assert episode["readmission_window_end_date"] == "2026-05-31"
    referral = validate_success(api.get_referral(ep["referral_id"], ADMIN))
    assert referral["status"] == "ACCEPTED"
    assert referral["created_episode_id"] == ep["episode_id"]
