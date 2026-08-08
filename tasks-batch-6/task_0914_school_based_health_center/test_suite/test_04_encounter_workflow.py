"""Scheduling, delivering and closing an encounter, and the two ladder rungs
that decide which refusal a caller sees."""

from test_helpers import (
    ADMIN,
    NO_AUTH_HEADERS,
    REGISTRAR,
    ApiErrorId,
    activate_enrollment,
    assert_visit,
    assert_visit_buckets,
    reinstate_school,
    set_clock,
    setup_enrolled_student,
    setup_visit_in_progress,
    setup_visit_scheduled,
    suspend_school,
    validate_error,
    validate_paginated,
    validate_success,
    visit_payload,
)


def test_completing_an_encounter_that_never_started_is_a_state_error(api):
    """PRD §3.5: "Completing the encounter moves it `IN_PROGRESS → COMPLETED` and
    requires a `disposition`, one of `TREATED_RETURNED_TO_CLASS`,
    `TREATED_SENT_HOME`, `REFERRED_OUT` or `NO_TREATMENT_NEEDED`."
    PRD §2.6 rung 17: "The target row is in a state from which the requested
    transition exists, on every action endpoint. Otherwise `ERR_INVALID_STATE`
    (409)."

    Design: Corner/state_machines/visit_complete_directly_from_scheduled_returns_invalid_state
    """
    ctx = setup_visit_scheduled()

    resp = api.complete_visit(
        ctx["visit"]["id"], {"disposition": "TREATED_RETURNED_TO_CLASS"}, ctx["clinician_headers"]
    )

    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)

    visit = validate_success(api.get_visit(ctx["visit"]["id"], REGISTRAR))
    assert visit["clinical_status"] == "SCHEDULED"
    assert visit["billing_status"] == "NOT_APPLICABLE"

    _charges, charge_meta = validate_paginated(
        api.list_charges(REGISTRAR, params={"visit_id": ctx["visit"]["id"]})
    )
    assert charge_meta["total_count"] == 0, "A refused completion mints no charges"

    _notifications, notification_meta = validate_paginated(
        api.list_notifications(ADMIN, params={"visit_id": ctx["visit"]["id"]})
    )
    assert notification_meta["total_count"] == 0, "A refused completion raises no notification"


def test_no_show_close_is_refused_before_the_grace_and_accepted_at_the_boundary(api):
    """PRD §3.5: "`NO_SHOW` is accepted only from `SCHEDULED`, and only once the
    current logical instant has reached `scheduled_start_at` plus 10 minutes — the
    boundary is inclusive, so exactly 10 minutes past the scheduled start is
    permitted while 9 minutes is refused with `ERR_NO_SHOW_TOO_EARLY`."

    Design: Corner/state_machines/visit_no_show_rejected_before_grace_accepted_at_exact_boundary
    """
    ctx = setup_visit_scheduled(scheduled_start_at="2026-05-04T10:00:00Z")

    set_clock("2026-05-04T10:09:59Z")
    early = api.close_visit_unfulfilled(
        ctx["visit"]["id"], {"outcome": "NO_SHOW"}, ctx["clinician_headers"]
    )
    validate_error(early, ApiErrorId.ERR_NO_SHOW_TOO_EARLY.value, 409)

    set_clock("2026-05-04T10:10:00Z")
    accepted = validate_success(
        api.close_visit_unfulfilled(
            ctx["visit"]["id"], {"outcome": "NO_SHOW"}, ctx["clinician_headers"]
        )
    )

    assert_visit(accepted)
    assert accepted["clinical_status"] == "NO_SHOW"
    assert accepted["billing_status"] == "NOT_APPLICABLE"

    _charges, meta = validate_paginated(
        api.list_charges(REGISTRAR, params={"visit_id": ctx["visit"]["id"]})
    )
    assert meta["total_count"] == 0, "A no-showed encounter mints no charges"


def test_behavioral_encounter_with_a_medical_clinician_is_refused(api):
    """PRD §3.1: "Discipline is a hard scope-of-practice boundary rather than a
    label: an acute encounter and a sports-physical encounter both require a
    `MEDICAL` clinician, a behavioral encounter requires a `BEHAVIORAL` clinician,
    and a dental encounter requires a `DENTAL` clinician. Scheduling an encounter
    with a clinician whose discipline does not match the mapping for the requested
    visit type is refused with `ERR_DISCIPLINE_MISMATCH`."

    Design: Corner/errors/error_discipline_mismatch_on_behavioral_visit_with_medical_clinician
    """
    ctx = setup_enrolled_student(discipline="MEDICAL", consents=("BEHAVIORAL_HEALTH",))

    resp = api.create_visit(
        visit_payload(
            ctx["student"]["id"],
            ctx["school"]["id"],
            ctx["clinician"]["id"],
            visit_type="BEHAVIORAL",
            scheduled_start_at="2026-05-04T10:00:00Z",
        ),
        ctx["clinician_headers"],
    )

    validate_error(resp, ApiErrorId.ERR_DISCIPLINE_MISMATCH.value, 409)

    _rows, meta = validate_paginated(
        api.list_visits(REGISTRAR, params={"student_id": ctx["student"]["id"]})
    )
    assert meta["total_count"] == 0, "A discipline mismatch must not store an encounter"


def test_registrar_may_not_schedule_an_encounter(api):
    """PRD §2.1: "A recognised role attempting an operation outside its permission
    set is refused with `ERR_ROLE_NOT_PERMITTED` and HTTP 403. Section 4 lists the
    authorized roles for each endpoint; that table is the authority."
    PRD §4: "| POST | `/sbhc/visits` | Schedule an encounter | `Clinician` |"

    Design: Corner/rbac/registrar_cannot_create_a_visit
    """
    ctx = setup_enrolled_student()

    resp = api.create_visit(
        visit_payload(
            ctx["student"]["id"],
            ctx["school"]["id"],
            ctx["clinician"]["id"],
            scheduled_start_at="2026-05-04T10:00:00Z",
        ),
        REGISTRAR,
    )

    validate_error(resp, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)

    _rows, meta = validate_paginated(
        api.list_visits(REGISTRAR, params={"student_id": ctx["student"]["id"]})
    )
    assert meta["total_count"] == 0, "A role refusal must not store an encounter"


def test_request_without_identity_headers_is_unauthenticated(api):
    """PRD §2.1: "Every request to the service — without exception, including list
    and read requests — must carry two headers: `X-User-ID`, identifying the acting
    principal, and `X-User-Role`, naming the role that principal is acting in. If
    either header is absent or present but empty, the request is refused with
    `ERR_UNAUTHENTICATED` and HTTP 401."

    Design: Corner/rbac/request_without_user_headers_returns_unauthenticated
    """
    set_clock("2026-05-04T09:00:00Z")

    resp = api.create_school(
        {
            "name": "Lincoln High",
            "site_code": "LHS",
            "sponsor_hospital_name": "Mercy Sponsor Hospital",
        },
        NO_AUTH_HEADERS,
    )

    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)


def test_completion_response_already_carries_the_recomputed_bucket_totals(api):
    """PRD §2.10: "Where that happens, this document enumerates every link of the
    cascade, and the implementation must apply all of them within the single
    request that triggered them — the consistency model is immediate, and there is
    no deferred or eventual reconciliation anywhere."
    PRD §3.10: "`gross_charge_total_cents` sums `gross_amount_cents` over charges
    that are not `REVERSED`."

    Design: Corner/consistency_model/visit_complete_response_already_carries_recomputed_bucket_totals
    """
    ctx = setup_visit_in_progress(
        setup_enrolled_student(
            financial={
                "household_income_annual_cents": 3_000_000,
                "household_size": 4,
                "payer_route": "SELF_PAY",
            }
        )
    )

    completed = validate_success(
        api.complete_visit(
            ctx["visit"]["id"],
            {"disposition": "TREATED_RETURNED_TO_CLASS"},
            ctx["clinician_headers"],
        )
    )

    assert_visit_buckets(
        completed,
        gross=12_000,
        no_charge=0,
        patient_responsibility=500,
        write_off=0,
        payer_billed=11_500,
    )
    assert completed["clinical_status"] == "COMPLETED"
    assert completed["billing_status"] == "PENDING_CHARGES"

    reread = validate_success(api.get_visit(ctx["visit"]["id"], REGISTRAR))
    for bucket in (
        "gross_charge_total_cents",
        "no_charge_total_cents",
        "patient_responsibility_total_cents",
        "write_off_total_cents",
        "payer_billed_total_cents",
    ):
        assert reread[bucket] == completed[bucket], (
            f"{bucket} must already be settled in the completion response: "
            f"{completed[bucket]} vs {reread[bucket]} on re-read"
        )


def _pending_enrollment_without_consent():
    """A student whose only enrollment is still PENDING and who has no consent
    row at all, so a scheduling attempt violates both rungs at once."""
    return setup_enrolled_student(activate=False, guardians=[], consents=())


def test_missing_enrollment_outranks_missing_consent_on_encounter_create(api):
    """PRD §2.6: "A student with no active enrollment *and* no consent on file
    produces `ERR_ENROLLMENT_NOT_ACTIVE`, not `ERR_CONSENT_REQUIRED` (rung 15
    precedes rung 18)."
    PRD §2.6 rung 15: "The student holds an enrollment in `ACTIVE` status for the
    current school year at the operation's site, on `POST /sbhc/visits`, `POST
    /sbhc/students/{id}/referrals` and `POST /sbhc/students/{id}/immunization-doses`.
    Otherwise `ERR_ENROLLMENT_NOT_ACTIVE` (409)."

    Design: Difficulty/priority_pair_validation_conflict/enrollment_referential_rung_beats_consent_safety_rung_on_visit_create
    """
    ctx = _pending_enrollment_without_consent()

    resp = api.create_visit(
        visit_payload(
            ctx["student"]["id"],
            ctx["school"]["id"],
            ctx["clinician"]["id"],
            scheduled_start_at="2026-05-04T10:00:00Z",
        ),
        ctx["clinician_headers"],
    )

    validate_error(resp, ApiErrorId.ERR_ENROLLMENT_NOT_ACTIVE.value, 409)

    _rows, meta = validate_paginated(
        api.list_visits(REGISTRAR, params={"student_id": ctx["student"]["id"]})
    )
    assert meta["total_count"] == 0, "Neither refusal may store an encounter"


def test_consent_rung_surfaces_once_the_enrollment_has_been_activated(api):
    """PRD §2.6 rung 18: "A consent of the category the visit type requires exists
    for the student with `ACTIVE` status and a current logical instant at or before
    its expiry, on `POST /sbhc/visits` and `POST /sbhc/visits/{id}/start`. Otherwise
    `ERR_CONSENT_REQUIRED` (409)."
    PRD §2.6: "A student with no active enrollment *and* no consent on file
    produces `ERR_ENROLLMENT_NOT_ACTIVE`, not `ERR_CONSENT_REQUIRED` (rung 15
    precedes rung 18)."

    Design: Difficulty/priority_pair_validation_conflict/enrollment_referential_rung_beats_consent_safety_rung_on_visit_create
    """
    ctx = _pending_enrollment_without_consent()
    payload = visit_payload(
        ctx["student"]["id"],
        ctx["school"]["id"],
        ctx["clinician"]["id"],
        scheduled_start_at="2026-05-04T10:00:00Z",
    )

    validate_error(
        api.create_visit(payload, ctx["clinician_headers"]),
        ApiErrorId.ERR_ENROLLMENT_NOT_ACTIVE.value,
        409,
    )

    activated = activate_enrollment(ctx["enrollment"]["id"])
    assert activated["status"] == "ACTIVE"

    second = api.create_visit(payload, ctx["clinician_headers"])
    validate_error(second, ApiErrorId.ERR_CONSENT_REQUIRED.value, 409)

    _rows, meta = validate_paginated(
        api.list_visits(REGISTRAR, params={"student_id": ctx["student"]["id"]})
    )
    assert meta["total_count"] == 0, "Neither refusal may store an encounter"


def test_encounter_is_refused_while_the_site_is_suspended(api):
    """PRD §2.9: "While a site is `SUSPENDED`, no enrollment may be created,
    activated or reinstated there, no encounter may be scheduled there, and no
    telehealth session may be booked there — every such attempt is refused with
    `ERR_SCHOOL_SUSPENDED`."
    PRD §3.1: "Supplying a `program_status` of `SUSPENDED` moves the site `ACTIVE →
    SUSPENDED`, which is permitted only when the site is currently `ACTIVE`; the
    transition increments `suspended_count` by 1 and increments the school's
    `version` by 1."

    Design: Difficulty/cross_entity_state_dependency/visit_create_gated_by_school_program_status
    """
    ctx = setup_enrolled_student()
    suspended = suspend_school(ctx["school"]["id"])
    assert suspended["program_status"] == "SUSPENDED"
    assert suspended["suspended_count"] == 1

    resp = api.create_visit(
        visit_payload(
            ctx["student"]["id"],
            ctx["school"]["id"],
            ctx["clinician"]["id"],
            scheduled_start_at="2026-05-04T10:00:00Z",
        ),
        ctx["clinician_headers"],
    )

    validate_error(resp, ApiErrorId.ERR_SCHOOL_SUSPENDED.value, 409)

    _rows, meta = validate_paginated(
        api.list_visits(REGISTRAR, params={"student_id": ctx["student"]["id"]})
    )
    assert meta["total_count"] == 0, "No encounter may be stored at a suspended site"


def test_identical_encounter_succeeds_once_the_site_is_reinstated(api):
    """PRD §3.1: "Supplying `ACTIVE` moves it back `SUSPENDED → ACTIVE`, permitted
    only when the site is currently `SUSPENDED`, and increments the school's
    `version` by 1 without touching `suspended_count`."
    PRD §3.5: "It resolves and stores `enrollment_id`, the identifier of the
    `ACTIVE` enrollment it matched; it resolves and stores `consent_id`, the
    identifier of the governing consent; and it computes `confidential`, which is
    true exactly when that governing consent was granted by the student themself
    and false otherwise."

    Design: Difficulty/cross_entity_state_dependency/visit_create_gated_by_school_program_status
    """
    ctx = setup_enrolled_student()
    suspend_school(ctx["school"]["id"])
    payload = visit_payload(
        ctx["student"]["id"],
        ctx["school"]["id"],
        ctx["clinician"]["id"],
        scheduled_start_at="2026-05-04T10:00:00Z",
    )
    validate_error(
        api.create_visit(payload, ctx["clinician_headers"]),
        ApiErrorId.ERR_SCHOOL_SUSPENDED.value,
        409,
    )

    reinstated = reinstate_school(ctx["school"]["id"])
    assert reinstated["program_status"] == "ACTIVE"
    assert reinstated["suspended_count"] == 1, "Reinstatement leaves suspended_count alone"

    visit = validate_success(api.create_visit(payload, ctx["clinician_headers"]), 201)

    assert_visit(visit)
    assert visit["clinical_status"] == "SCHEDULED"
    assert visit["enrollment_id"] == ctx["enrollment"]["id"]
    assert visit["consent_id"] == ctx["consents"]["GENERAL_TREATMENT"]["id"]
    assert visit["confidential"] is False
