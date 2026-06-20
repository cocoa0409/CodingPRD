"""Patient/referral/bed creation, defaults, type constraints, not-found,
filtered listings, and role-based access control.

Covers corner queue (B) entities, endpoints, and rbac instances.
"""

from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    create_patient,
    create_authorized_referral,
    create_fulfilled_dme_with_window,
    create_scored_study,
    create_patient_payload,
    create_referral_payload,
    create_bed_payload,
    create_study_order_payload,
    interpret_payload,
    TEST_USERS,
)

COORD = TEST_USERS["scheduling_coordinator_headers"]
TECH = TEST_USERS["sleep_technologist_headers"]
PHYS = TEST_USERS["physician_headers"]
DME = TEST_USERS["dme_coordinator_headers"]

PROBE_UUID = "00000000-0000-0000-0000-000000000000"


# ─── Patient creation ──────────────────────────────────────────────────────

def test_create_patient_minimal_fields(api):
    """PRD 3.1: "An optional baseline_epworth_score records the patient's
    pre-treatment Epworth Sleepiness Scale value, an integer from 0 to 24
    inclusive; when omitted it defaults to 0."
    PRD 2.4: "The version field is an integer that starts at 1 when the resource is
    created and increases by exactly 1 on every subsequent mutation."

    Design: Corner/entities/create_patient_minimal_required_fields
    """
    res = api.create_patient(
        create_patient_payload(full_name="Ada Test", date_of_birth="1990-01-01",
                               insurance_payer="Acme"),
        COORD,
    )
    patient = validate_success(res, 201)
    assert patient["version"] == 1
    assert patient["baseline_epworth_score"] == 0


def test_create_patient_missing_full_name_rejected(api):
    """PRD 3.1: "The coordinator supplies the patient's full_name, their
    date_of_birth as an ISO date in year-month-day form, and the insurance_payer
    whose name the prior-authorization gate later keys on."
    PRD 2.7: "fourth, the structural well-formedness of the request body — required
    fields present, enumerations valid, and numbers within their declared ranges,
    such as an Epworth score between 0 and 24 inclusive or a total recording time
    greater than zero (ERR_INVALID_REQUEST)."

    Design: Corner/entities/create_patient_missing_required_field
    """
    payload = create_patient_payload()
    del payload["full_name"]
    res = api.create_patient(payload, COORD)
    validate_error(res, "ERR_INVALID_REQUEST")


def test_create_patient_epworth_out_of_range_rejected(api):
    """PRD 3.1: "An optional baseline_epworth_score records the patient's
    pre-treatment Epworth Sleepiness Scale value, an integer from 0 to 24
    inclusive; when omitted it defaults to 0."
    PRD 2.7: "numbers within their declared ranges, such as an Epworth score
    between 0 and 24 inclusive or a total recording time greater than zero
    (ERR_INVALID_REQUEST)."

    baseline_epworth_score=25 exceeds the 0..24 range.

    Design: Corner/entities/create_patient_epworth_out_of_range
    """
    res = api.create_patient(
        create_patient_payload(baseline_epworth_score=25), COORD
    )
    validate_error(res, "ERR_INVALID_REQUEST")


def test_get_patient_not_found(api):
    """PRD 2.6: "the first identifier that fails to resolve determines the
    not-found error returned (ERR_REFERRAL_NOT_FOUND, ERR_PATIENT_NOT_FOUND,
    ERR_BED_NOT_FOUND, ERR_STUDY_NOT_FOUND, ERR_SCORING_REPORT_NOT_FOUND,
    ERR_DME_NOT_FOUND, ERR_COMPLIANCE_NOT_FOUND, or ERR_FOLLOWUP_NOT_FOUND)."

    Design: Corner/entities/get_patient_not_found
    """
    res = api.get_patient(PROBE_UUID, COORD)
    validate_error(res, "ERR_PATIENT_NOT_FOUND")


# ─── Referral defaults / constraints / FK ──────────────────────────────────

def test_referral_default_prior_auth_required_true(api):
    """PRD 3.1: "The creator may also set prior_auth_required, a boolean that
    declares whether the payer demands authorization before the study can proceed;
    when omitted it defaults to true."
    PRD 3.1: "A freshly created referral begins life in SUBMITTED status."

    Design: Corner/entities/referral_default_prior_auth_required_true
    """
    patient = create_patient()
    payload = create_referral_payload(patient["id"], requested_modality="HSAT")
    # Omit prior_auth_required to exercise the default.
    payload.pop("prior_auth_required", None)
    res = api.create_referral(payload, COORD)
    referral = validate_success(res, 201)
    assert referral["prior_auth_required"] is True
    assert referral["status"] == "SUBMITTED"
    assert referral["prior_auth_number"] is None


def test_referral_bad_modality_enum_rejected(api):
    """PRD 3.1: "the requested_modality the clinician wants — either IN_LAB_PSG for
    an attended in-lab polysomnogram or HSAT for a home sleep apnea test."
    PRD 2.7: "the structural well-formedness of the request body — required fields
    present, enumerations valid, and numbers within their declared ranges, such as
    an Epworth score between 0 and 24 inclusive or a total recording time greater
    than zero (ERR_INVALID_REQUEST)."

    Design: Corner/entities/referral_bad_modality_enum
    """
    patient = create_patient()
    res = api.create_referral(
        create_referral_payload(patient["id"], requested_modality="BOGUS"), COORD
    )
    validate_error(res, "ERR_INVALID_REQUEST")


def test_referral_unknown_patient_fk_rejected(api):
    """PRD 2.6: "existence is validated left to right — the referral first, then the
    study order, then the scoring report, DME order, or other downstream resource —
    and the first identifier that fails to resolve determines the not-found error
    returned (ERR_REFERRAL_NOT_FOUND, ERR_PATIENT_NOT_FOUND, ERR_BED_NOT_FOUND,
    ERR_STUDY_NOT_FOUND, ERR_SCORING_REPORT_NOT_FOUND, ERR_DME_NOT_FOUND,
    ERR_COMPLIANCE_NOT_FOUND, or ERR_FOLLOWUP_NOT_FOUND)."

    Design: Corner/entities/referral_unknown_patient_fk
    """
    res = api.create_referral(
        create_referral_payload(PROBE_UUID, requested_modality="HSAT",
                                prior_auth_required=False),
        COORD,
    )
    validate_error(res, "ERR_PATIENT_NOT_FOUND")


# ─── SleepBed system fields / defaults ─────────────────────────────────────

def test_bed_defaults_and_system_fields(api):
    """PRD 3.3: "A new bed starts in AVAILABLE status."
    PRD 3.3: "Each bed also carries a turnover_buffer_minutes value — the
    sanitation and turnover gap that must elapse after each booked night before the
    next night on that bed may begin — which must be zero or greater and defaults
    to 60 when omitted."
    PRD 2.4: "The version field is an integer that starts at 1 when the resource is
    created and increases by exactly 1 on every subsequent mutation."

    Design: Corner/entities/system_fields_ignored_on_create
    """
    res = api.create_bed(create_bed_payload(bed_label="Room-9-Bed-A"), COORD)
    bed = validate_success(res, 201)
    assert bed["status"] == "AVAILABLE"
    assert bed["turnover_buffer_minutes"] == 60
    assert bed["version"] == 1


# ─── Referral listing envelope ─────────────────────────────────────────────

def test_list_referrals_returns_paginated_array(api):
    """PRD 2.3: "The meta object of every list response carries the pagination
    fields limit, offset, total_count, and has_more."
    PRD 2.3: "A referral, study-order, DME-order, or bed list may be filtered by
    status; the referral list also accepts patient_id."

    Design: Corner/entities/list_referrals_pagination_envelope
    """
    patient = create_patient()
    api.create_referral(
        create_referral_payload(patient["id"], requested_modality="HSAT",
                                prior_auth_required=False),
        COORD,
    )
    res = api.list_referrals(COORD, params={"patient_id": patient["id"]})
    data, meta = validate_paginated(res)
    assert meta["total_count"] == 1


# ─── Endpoints: filtered list by referral ──────────────────────────────────

def test_study_orders_filtered_by_referral(api):
    """PRD 2.3: "the referral list also accepts patient_id; the study-order list
    accepts referral_id and bed_id."
    PRD 2.3: "These filters are optional and combine with limit and offset."

    Two studies under one referral; filtering by referral_id returns both.

    Design: Corner/endpoints/study_orders_filtered_list_by_referral
    """
    _, referral = create_authorized_referral(modality="HSAT", prior_auth_number="PA-EP1")
    s1 = get_success_data(
        api.create_study_order(
            create_study_order_payload(referral["id"], referral["version"], modality="HSAT"),
            COORD,
        )
    )
    ref_after = get_success_data(api.get_referral(referral["id"], COORD))
    get_success_data(
        api.create_study_order(
            create_study_order_payload(referral["id"], ref_after["version"], modality="HSAT"),
            COORD,
        )
    )
    data, meta = validate_paginated(
        api.list_study_orders(COORD, params={"referral_id": referral["id"]})
    )
    assert meta["total_count"] == 2


def test_compliance_records_reverse_reachable_by_dme(api):
    """PRD 2.6: "A handful of list endpoints are addressed under a parent
    identifier — the scoring reports of a study order, the follow-ups of a study
    order, and the compliance records of a DME order."

    GET /dme-orders/{id}/compliance-records returns the device's records.

    Design: Corner/endpoints/compliance_records_reverse_reachable_by_dme
    """
    _, dme, _ = create_fulfilled_dme_with_window(
        "2026-08-01T00:00:00Z", "2026-08-31T00:00:00Z",
        nights_used_4h_plus=21, total_usage_minutes=5040,
    )
    data, meta = validate_paginated(
        api.list_compliance_records_for_dme(dme["id"], DME)
    )
    assert meta["total_count"] == 1


# ─── RBAC ──────────────────────────────────────────────────────────────────

def test_technologist_cannot_create_referral(api):
    """PRD 2.1: "When the headers are present but the declared role is not permitted
    to perform the requested operation, the request is rejected with
    ERR_FORBIDDEN_ROLE."

    POST /referrals is SchedulingCoordinator-exclusive.

    Design: Corner/rbac/technologist_cannot_create_referral
    """
    patient = create_patient()
    res = api.create_referral(
        create_referral_payload(patient["id"], requested_modality="HSAT",
                                prior_auth_required=False),
        TECH,
    )
    validate_error(res, "ERR_FORBIDDEN_ROLE")


def test_coordinator_cannot_interpret(api):
    """PRD 2.1: "When the headers are present but the declared role is not permitted
    to perform the requested operation, the request is rejected with
    ERR_FORBIDDEN_ROLE."

    POST /scoring-reports/{id}/interpret is Physician-exclusive.

    Design: Corner/rbac/coordinator_cannot_interpret
    """
    _, _, study, report, _ = create_scored_study(modality="HSAT")
    res = api.interpret_scoring_report(
        report["id"], interpret_payload(interpretation_text="Bad actor"), COORD
    )
    validate_error(res, "ERR_FORBIDDEN_ROLE")


def test_missing_user_context_rejected(api):
    """PRD 2.1: "Every request to the API must be authenticated through two
    mandatory HTTP headers. The X-User-ID header identifies the acting user, and
    the X-User-Role header declares the operational capacity under which the
    request is made. If either header is missing or malformed, the request is
    rejected with ERR_MISSING_USER_CONTEXT."

    Design: Corner/rbac/missing_user_context_header
    """
    res = api.create_patient(create_patient_payload(), headers={})
    validate_error(res, "ERR_MISSING_USER_CONTEXT")
