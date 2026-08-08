"""Role authorization, the entity-backed identity rung, and optimistic concurrency."""

from test_helpers import (
    ApiErrorId,
    assert_same_instant,
    auth_version,
    build_battery,
    build_signed_evaluation,
    coverage_version,
    create_claim_payload,
    create_plan_payload,
    create_session_payload,
    deliver_session,
    get_success_data,
    log_home_session,
    make_billing_specialist_headers,
    make_headers,
    make_front_desk_headers,
    make_optometrist_headers,
    make_patient_user_headers,
    make_vision_therapist_headers,
    new_patient,
    new_therapist,
    npc_measurement_payload,
    plan_version,
    read_assessment,
    read_authorization,
    read_patient,
    read_plan,
    read_session,
    schedule_session,
    set_clock,
    setup_active_plan,
    validate_error,
    validate_paginated,
    validate_success,
)


# --------------------------------------------------------------------------
# Rung 1 and rung 2
# --------------------------------------------------------------------------


def test_a_vision_therapist_may_not_sign_a_battery(api):
    """PRD §2.1: "An **`Optometrist`** is a licensed optometrist and is the only role
    that may sign an assessment, author, revise, suspend, resume or activate a therapy
    plan, append phases to a plan, prescribe or taper occlusion, and discharge a
    patient."
    PRD §2.1: "If both headers are well formed but the named role is not authorized
    for the endpoint being called, the request is refused with `ERR_UNAUTHORIZED`
    (HTTP 403)."
    PRD §2.1: "A **`VisionTherapist`** is a certified vision therapist who runs
    sessions without supervision and records the instrument battery, but may not sign
    it."

    Design: Corner/rbac/vision_therapist_cannot_sign_an_assessment
    """
    set_clock("2026-06-01T00:00:00Z")
    patient = new_patient(date_of_birth="2016-06-01")
    optometrist = new_therapist(full_name="Dr Lee", credential="OPTOMETRIST")
    therapist = new_therapist(full_name="Kim CVT", credential="CERTIFIED_VISION_THERAPIST")
    battery = build_battery(
        patient["id"],
        optometrist["id"],
        measurements=[npc_measurement_payload(12.0, 16.0)],
        finalize_it=True,
    )

    response = api.sign_assessment(
        battery["id"], make_vision_therapist_headers(therapist["id"])
    )

    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value, 403)
    stored = read_assessment(battery["id"])
    assert stored["status"] == "FINALIZED"
    assert stored["signed_by_therapist_id"] is None
    assert read_patient(patient["id"])["clinical_status"] == "INTAKE"


def test_a_billing_specialist_may_not_author_a_therapy_plan(api):
    """PRD §3.4: "Only an optometrist authors a therapy plan, and only from a battery
    that has been signed."
    PRD §2.1: "If both headers are well formed but the named role is not authorized
    for the endpoint being called, the request is refused with `ERR_UNAUTHORIZED`
    (HTTP 403)."
    PRD §2.1: "A **`BillingSpecialist`** is the revenue-cycle operator, owning
    coverages, authorizations and the entire claim lifecycle."

    Design: Corner/rbac/billing_specialist_cannot_create_a_therapy_plan
    """
    set_clock("2026-06-01T00:00:00Z")
    patient = new_patient(date_of_birth="2016-06-01")
    optometrist = new_therapist(full_name="Dr Lee", credential="OPTOMETRIST")
    evaluation = build_signed_evaluation(
        patient["id"], optometrist["id"], measurements=[npc_measurement_payload(12.0, 16.0)]
    )

    response = api.create_therapy_plan(
        create_plan_payload(patient["id"], evaluation["id"]),
        make_billing_specialist_headers(),
    )

    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value, 403)
    rows, meta = validate_paginated(
        api.list_therapy_plans(
            make_front_desk_headers(), {"patient_id": patient["id"], "limit": 10, "offset": 0}
        )
    )
    assert meta["total_count"] == 0 and rows == []


def test_a_patient_user_may_not_attest_another_patients_session(api):
    """PRD §2.1: "When `X-User-Role` is `PatientUser`, `X-User-ID` is the `id` of the
    acting `Patient`; a `PatientUser` may only act on rows whose `patient_id` equals
    `X-User-ID`, and acting on another patient's row is refused with
    `ERR_UNAUTHORIZED`."
    PRD §3.6: "Attestation is again a `PatientUser` operation, requires `X-User-ID` to
    equal the session's `patient_id`, takes a free-text `attestation_statement`, and
    moves the session `LOGGED → ATTESTED` with `attested_at` stamped from the clock
    and the session's `version` bumped."

    Design: Corner/rbac/patient_user_cannot_attest_another_patients_session
    """
    scn = setup_active_plan()
    other_patient = new_patient(
        full_name="Ben Sole", date_of_birth="2015-04-02", diagnosis_category="AMBLYOPIA"
    )
    assert other_patient["id"] != scn["pt"], "The two patients must be distinct identities"
    logged = log_home_session(scn, "2026-05-28T18:00:00Z", 20)

    response = api.attest_session(
        logged["id"],
        {"attestation_statement": "Done"},
        make_patient_user_headers(other_patient["id"]),
    )

    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value, 403)
    stored = read_session(logged["id"])
    assert stored["schedule_status"] == "LOGGED"
    assert stored["attested_at"] is None
    assert read_plan(scn["plan"])["cumulative_therapy_minutes"] == 0.0


def test_marking_a_no_show_is_reserved_to_reception(api):
    """PRD §2.1: "Marking a session as a no-show is the one operation reserved to
    `FrontDesk` alone."
    PRD §3.5: "A no-show, by contrast, is reception's operation alone, applies only to
    an in-office session still in `SCHEDULED`, and is permitted only once the logical
    clock has reached or passed the session's `scheduled_start_at`."

    Design: Corner/rbac/vision_therapist_cannot_mark_a_no_show
    """
    scn = setup_active_plan()
    session = schedule_session(scn)
    set_clock("2026-06-10T09:30:00Z")

    response = api.no_show_session(session["id"], scn["hdr_cvt1"])

    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value, 403)
    assert read_session(session["id"])["schedule_status"] == "SCHEDULED"
    pool = read_authorization(scn["auth"])
    assert pool["visits_consumed"] == 1 and pool["visits_released"] == 0


def test_an_unrecognised_role_name_is_refused_before_authorization(api):
    """PRD §2.1: "Every request to every endpoint must carry two headers:
    `X-User-ID`, identifying the caller, and `X-User-Role`, naming the caller's role.
    If either header is absent, or if `X-User-Role` is any string other than one of
    the seven role names below, the request is refused with `ERR_UNAUTHENTICATED`
    (HTTP 401)."
    PRD §2.1: "The seven roles are `ClinicAdmin`, `Optometrist`, `VisionTherapist`,
    `TherapyAssistant`, `BillingSpecialist`, `FrontDesk` and `PatientUser`, spelled
    exactly as shown."

    Design: Corner/rbac/unknown_role_header_returns_unauthenticated
    """
    set_clock("2026-06-01T00:00:00Z")
    patient = new_patient()

    response = api.get_patient(patient["id"], make_headers("Auditor", "auditor-1"))
    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)

    allowed = validate_success(api.get_patient(patient["id"], make_front_desk_headers()), 200)
    assert allowed["id"] == patient["id"]


# --------------------------------------------------------------------------
# Optimistic concurrency (PRD §2.9)
# --------------------------------------------------------------------------


def test_a_stale_authorization_version_refuses_the_booking(api):
    """PRD §2.9: "Scheduling an in-office session must carry
    `expected_authorization_version`, holding the client's last observed `version` of
    the `Authorization` bound to the plan."
    PRD §2.9: "In each case a value that does not equal the parent's current `version`
    is rejected at rung 13 with `ERR_STALE_VERSION` and HTTP 412."
    PRD §2.9: "Scheduling draws one unit out of that pool; a caller whose pinned
    version no longer matches is reasoning from a stale view of the pool, because some
    other writer has drawn, released or reauthorized units since the caller last read
    it, and the draw is refused."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_authorization_version_on_session_create
    """
    scn = setup_active_plan()
    schedule_session(scn, expected_authorization_version=scn["auth_v1"])

    stale = api.create_session(
        scn["plan"],
        create_session_payload(
            scn["od2"],
            scn["room_b"],
            "2026-06-11T09:00:00Z",
            "2026-06-11T10:00:00Z",
            scn["auth_v1"],
        ),
        scn["hdr_front"],
    )
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION.value, 412)

    fresh = validate_success(
        api.create_session(
            scn["plan"],
            create_session_payload(
                scn["od2"],
                scn["room_b"],
                "2026-06-11T09:00:00Z",
                "2026-06-11T10:00:00Z",
                auth_version(scn["auth"]),
            ),
            scn["hdr_front"],
        ),
        201,
    )
    assert fresh["schedule_status"] == "SCHEDULED"

    pool = read_authorization(scn["auth"])
    assert pool["visits_consumed"] == 2
    assert pool["visits_remaining"] == 10


def test_a_stale_plan_version_refuses_the_revision(api):
    """PRD §2.9: "Opening a plan revision must carry `expected_plan_version`, holding
    the client's last observed `version` of the `TherapyPlan` named in the path."
    PRD §2.9: "A revision legitimately supersedes the plan's prior prescription, so a
    second revision against the same observed version is a perfectly valid product
    operation rather than an illegal state change; it is refused purely because
    `expected_plan_version` is stale relative to the plan's current `version`."
    PRD §3.4: "An optometrist may revise a plan whose `status` is `ACTIVE` or
    `SUSPENDED`, supplying `expected_plan_version` equal to the plan's current
    `version` — a stale value is refused with `ERR_STALE_VERSION` (HTTP 412) — and may
    attach a free-text `revision_reason`."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_plan_version_on_revise
    """
    scn = setup_active_plan()
    get_success_data(
        api.revise_plan(
            scn["plan"],
            {
                "expected_plan_version": scn["plan_v"],
                "revision_reason": "First revision",
                "prescribed_home_sessions_per_week": 2,
            },
            scn["hdr_od1"],
        )
    )
    get_success_data(
        api.activate_plan(scn["plan"], {"authorization_id": scn["auth"]}, scn["hdr_od1"])
    )

    stale = api.revise_plan(
        scn["plan"],
        {"expected_plan_version": scn["plan_v"], "revision_reason": "Second revision"},
        scn["hdr_od1"],
    )
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION.value, 412)

    fresh = validate_success(
        api.revise_plan(
            scn["plan"],
            {
                "expected_plan_version": plan_version(scn["plan"]),
                "revision_reason": "Second revision",
                "prescribed_home_sessions_per_week": 3,
            },
            scn["hdr_od1"],
        ),
        200,
    )
    assert fresh["status"] == "UNDER_REVISION"
    assert fresh["revision_count"] == 2
    assert fresh["previous_prescribed_home_sessions_per_week"] == 2


def test_a_stale_coverage_version_refuses_the_claim(api):
    """PRD §2.9: "Creating a claim must carry `expected_coverage_version`, holding the
    client's last observed `version` of the `Coverage` named in `coverage_id`."
    PRD §2.9: "If the coverage's `version` has advanced since the biller read it, the
    accumulators the biller reasoned about are no longer the ones adjudication will
    consume, and the create is refused."
    PRD §3.10: "A `THERAPY_SESSION` claim copies the session's `procedure_code` and
    takes `units` from the session's `billable_units`; an `EVALUATION` claim fixes
    `procedure_code` to `EVALUATION_ENCOUNTER` and `units` to 1."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_coverage_version_on_claim_create
    """
    scn = setup_active_plan()
    session = deliver_session(scn)
    observed_version = coverage_version(scn["cov_med"])
    get_success_data(
        api.create_claim(
            create_claim_payload(
                scn["pt"],
                scn["cov_med"],
                "THERAPY_SESSION",
                "2026-06-10",
                observed_version,
                session_id=session["id"],
            ),
            scn["hdr_biller"],
        )
    )

    stale = api.create_claim(
        create_claim_payload(
            scn["pt"],
            scn["cov_med"],
            "EVALUATION",
            "2026-06-01",
            observed_version,
            assessment_id=scn["ev1"],
        ),
        scn["hdr_biller"],
    )
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION.value, 412)

    fresh = validate_success(
        api.create_claim(
            create_claim_payload(
                scn["pt"],
                scn["cov_med"],
                "EVALUATION",
                "2026-06-01",
                coverage_version(scn["cov_med"]),
                assessment_id=scn["ev1"],
            ),
            scn["hdr_biller"],
        ),
        201,
    )
    assert fresh["procedure_code"] == "EVALUATION_ENCOUNTER"
    assert fresh["units"] == 1
    assert float(fresh["billed_amount"]) == 210.00

    rows, meta = validate_paginated(
        api.list_claims(scn["hdr_biller"], {"patient_id": scn["pt"], "limit": 10, "offset": 0})
    )
    assert meta["total_count"] == 2 and len(rows) == 2


def test_every_mutation_advances_the_version_counter_by_exactly_one(api):
    """PRD §2.4: "Most resources additionally carry `updated_at`, in the same ISO 8601
    UTC format with three fractional digits, and `version`, an integer that begins at
    1 when the row is created and increments by exactly 1 on every mutation of that
    row."
    PRD §3.2: "The transition is `DRAFT → FINALIZED`, and it bumps the battery's
    `version`."
    PRD §3.2: "The signature stamps `signed_by_therapist_id` with the acting
    `X-User-ID` and `signed_at` with the current clock instant, and bumps `version`."

    Design: Corner/cross_cutting_complexity_layers/version_increments_by_one_on_every_mutation
    """
    set_clock("2026-06-01T00:00:00Z")
    patient = new_patient(date_of_birth="2016-06-01")
    optometrist = new_therapist(full_name="Dr Lee", credential="OPTOMETRIST")
    headers = make_optometrist_headers(optometrist["id"])
    created = build_battery(
        patient["id"],
        optometrist["id"],
        measurements=[npc_measurement_payload(12.0, 16.0)],
        finalize_it=False,
    )
    assert created["version"] == 1

    finalized = validate_success(api.finalize_assessment(created["id"], headers), 200)
    assert finalized["version"] == 2

    signed = validate_success(api.sign_assessment(created["id"], headers), 200)
    assert signed["version"] == 3

    assert_same_instant(signed["created_at"], created["created_at"], "Assessment.created_at")
