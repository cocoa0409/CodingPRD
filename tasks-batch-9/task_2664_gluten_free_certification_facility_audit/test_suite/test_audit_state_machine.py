"""The audit's own edges: the state a scheduled visit is born in, the start edge and
its clock guard, and the two ways a close can be refused.
"""

from test_helpers import (
    ApiErrorId,
    AuditType,
    make_admin_headers,
    make_auditor_headers,
    read_audit,
    read_facility,
    schedule_audit,
    set_clock,
    setup_applicant_with_facility,
    start_audit,
    validate_error,
    validate_paginated,
)

CLOCK_START = "2026-08-01T00:00:00Z"
WINDOW_OPENS = "2026-08-10T09:00:00Z"
WINDOW_CLOSES = "2026-08-10T17:00:00Z"
ONE_SECOND_EARLY = "2026-08-10T08:59:59Z"
DAY_AFTER = "2026-08-11T00:00:00Z"


def _a_scheduled_audit_on_an_unvalidated_site(api):
    """One applicant, one facility that has never had a sanitation validation
    recorded, and one INITIAL audit over [09:00, 17:00) on 2026-08-10.

    Nothing is validated and nothing is started, so every field read below is the
    creation state of the audit rather than the residue of a later transition.
    """
    context = setup_applicant_with_facility(api, clock=CLOCK_START)
    audit = schedule_audit(
        api,
        context.facility_id,
        audit_type=AuditType.INITIAL,
        onsite_start_at=WINDOW_OPENS,
        onsite_end_at=WINDOW_CLOSES,
    )
    return context, audit


def test_a_new_audit_opens_scheduled_with_every_outcome_field_still_empty(api):
    """Creation answers 201 with SCHEDULED, both finding counters at 0, both scores
    null and all three attribution fields null.

    PRD: "A scheduled audit opens with `status` of `SCHEDULED`, `finding_count` and
    `critical_finding_count` at 0, `provisional_score` and `final_score` null, and
    `lead_auditor_user_id`, `closed_by_user_id` and `closed_on` null."
    PRD: "Most resources additionally carry `updated_at`, refreshed to the current
    logical instant on every mutation that changes the row, and `version`, an integer
    that begins at 1 on creation and increases by exactly 1 on every mutation of that
    row."

    Design: Corner/state_machines/audit_creation_starts_in_scheduled_with_zeroed_finding_counters
    """
    context, audit = _a_scheduled_audit_on_an_unvalidated_site(api)

    assert audit["status"] == "SCHEDULED"
    assert audit["audit_type"] == AuditType.INITIAL
    assert audit["finding_count"] == 0
    assert audit["critical_finding_count"] == 0
    assert audit["provisional_score"] is None
    assert audit["final_score"] is None
    assert audit["lead_auditor_user_id"] is None
    assert audit["closed_by_user_id"] is None
    assert audit["closed_on"] is None
    assert audit["version"] == 1

    assert read_facility(api, context.facility_id)["last_closed_audit_outcome"] == "NONE"


def test_starting_the_audit_binds_the_acting_auditor_as_its_lead(api):
    """At exactly onsite_start_at the start is accepted, the audit reads IN_PROGRESS
    and the acting X-User-ID is recorded as the lead auditor.

    PRD: "An audit is started only once the logical clock has reached
    `onsite_start_at`; a premature attempt, or an attempt on an audit that is not
    `SCHEDULED`, is refused with `ERR_INVALID_AUDIT_STATE`. Starting moves `SCHEDULED →
    IN_PROGRESS` and records `lead_auditor_user_id` as the acting `X-User-ID`."

    Design: Corner/state_machines/audit_start_moves_scheduled_to_in_progress_and_binds_the_lead_auditor
    """
    context, audit = _a_scheduled_audit_on_an_unvalidated_site(api)

    set_clock(api, WINDOW_OPENS)
    started = start_audit(api, audit["id"], auditor_user_id="aud-1")

    assert started["status"] == "IN_PROGRESS"
    assert started["lead_auditor_user_id"] == "aud-1"
    assert started["provisional_score"] is None
    assert started["final_score"] is None
    assert started["closed_on"] is None

    assert read_facility(api, context.facility_id)["last_closed_audit_outcome"] == "NONE"

    _rows, meta = validate_paginated(
        api.list_audits(
            make_admin_headers(), facility_id=context.facility_id, status="IN_PROGRESS"
        )
    )
    assert meta["total_count"] == 1


def test_a_start_one_second_before_the_window_opens_is_refused(api):
    """One second short of onsite_start_at the audit is in the right state and still
    cannot start, and the refusal leaves no lead auditor behind.

    PRD: "**Audit state.** Starting an audit requires `status` of `SCHEDULED` and a
    logical clock that has reached `onsite_start_at`; closing one requires `status` of
    `IN_PROGRESS` and a logical clock that has reached `onsite_end_at`. A breach is
    `ERR_INVALID_AUDIT_STATE` (409)."

    Design: Corner/state_machines/audit_start_before_the_onsite_window_opens_is_rejected
    """
    _context, audit = _a_scheduled_audit_on_an_unvalidated_site(api)

    set_clock(api, ONE_SECOND_EARLY)
    response = api.start_audit(audit["id"], make_auditor_headers("aud-1"))
    validate_error(response, ApiErrorId.INVALID_AUDIT_STATE, 409)

    row = read_audit(api, audit["id"])
    assert row["status"] == "SCHEDULED"
    assert row["lead_auditor_user_id"] is None
    assert row["version"] == 1


def test_closing_an_audit_that_was_never_started_is_refused(api):
    """A validated site, a clock past onsite_end_at and all three attestations true
    still cannot close an audit sitting in SCHEDULED, and no score is written.

    PRD: "Closing an audit requires the clock to have reached `onsite_end_at` and the
    audit to be `IN_PROGRESS` (otherwise `ERR_INVALID_AUDIT_STATE`), and it requires the
    facility's `sanitation_validation_status` to read `VALIDATED` at that moment
    (otherwise `ERR_FACILITY_SANITATION_NOT_VALIDATED`)."
    PRD: "`last_closed_audit_outcome` is the `status` of the audit of this facility with
    the greatest `closed_on` among those whose `status` is `CLOSED_PASS`,
    `CLOSED_CONDITIONAL` or `CLOSED_FAIL`, with ties broken by taking the audit with the
    earlier `created_at`; it reads `NONE` while no audit has ever closed there."

    Design: Corner/state_machines/audit_close_from_scheduled_without_starting_is_rejected
    """
    context = setup_applicant_with_facility(
        api, clock=CLOCK_START, sanitation_validated_on=CLOCK_START, swab_ppm=3.0
    )
    assert context.facility["sanitation_validation_status"] == "VALIDATED"
    audit = schedule_audit(
        api,
        context.facility_id,
        audit_type=AuditType.INITIAL,
        onsite_start_at=WINDOW_OPENS,
        onsite_end_at=WINDOW_CLOSES,
    )

    set_clock(api, DAY_AFTER)
    response = api.close_audit(
        audit["id"],
        make_auditor_headers("aud-1"),
        shared_equipment_verified=True,
        air_handling_verified=True,
        sanitation_validation_reviewed=True,
    )
    validate_error(response, ApiErrorId.INVALID_AUDIT_STATE, 409)

    row = read_audit(api, audit["id"])
    assert row["status"] == "SCHEDULED"
    assert row["provisional_score"] is None
    assert row["final_score"] is None
    assert row["closed_by_user_id"] is None
    assert read_facility(api, context.facility_id)["last_closed_audit_outcome"] == "NONE"


def test_the_attestation_cannot_substitute_for_the_facilitys_own_record(api):
    """An IN_PROGRESS audit at exactly onsite_end_at, closed with
    sanitation_validation_reviewed true, is still refused 422 because the facility
    itself reads UNVALIDATED.

    PRD: "A new site begins with `sanitation_validation_status` of `UNVALIDATED`, with
    `sanitation_method`, `sanitation_swab_ppm`, `sanitation_validated_on` and
    `sanitation_expires_on` all null, and with `last_closed_audit_outcome` of `NONE` and
    `last_closed_audit_closed_on` null."
    PRD: "**Sanitation currently validated.** The relevant facility's
    `sanitation_validation_status` is `VALIDATED` at the instant of the call; both
    `UNVALIDATED` and `EXPIRED` fail with `ERR_FACILITY_SANITATION_NOT_VALIDATED`
    (422). Three operations are guarded: closing an audit, issuing a certificate and
    reinstating a certificate."

    Design: Corner/state_machines/audit_close_without_a_validated_sanitation_dimension_is_rejected
    """
    context, audit = _a_scheduled_audit_on_an_unvalidated_site(api)
    assert context.facility["sanitation_validation_status"] == "UNVALIDATED"

    set_clock(api, WINDOW_OPENS)
    start_audit(api, audit["id"], auditor_user_id="aud-1")
    set_clock(api, WINDOW_CLOSES)

    response = api.close_audit(
        audit["id"],
        make_auditor_headers("aud-1"),
        shared_equipment_verified=True,
        air_handling_verified=True,
        sanitation_validation_reviewed=True,
    )
    validate_error(response, ApiErrorId.FACILITY_SANITATION_NOT_VALIDATED, 422)

    row = read_audit(api, audit["id"])
    assert row["status"] == "IN_PROGRESS"
    assert row["provisional_score"] is None
    assert row["closed_on"] is None

    facility = read_facility(api, context.facility_id)
    assert facility["sanitation_validation_status"] == "UNVALIDATED"
    assert facility["last_closed_audit_outcome"] == "NONE"
