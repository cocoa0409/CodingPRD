"""Infection-case opening, review, adjudication, reopen cycle, and the
repeat-infection-timeframe block (PRD §2.5, §3.4, §3.5)."""
from test_helpers import (
    ApiErrorId,
    assert_infection_case,
    assert_instant_equal,
    begin_review,
    create_adjudicated_clabsi,
    create_case_under_review,
    create_device_episode,
    create_infection_case,
    create_monthly_summary,
    create_patient,
    get_case,
    get_summary,
    remove_device_episode,
    reopen_case,
    setup_facility_unit,
    setup_unit_with_patient,
    setup_unit_with_patient_and_episode,
    submit_summary,
    validate_error,
    validate_success,
)


def test_case_create_computes_window_and_unit(api, ip_headers):
    """PRD §3.4: "The case's `unit_id` is taken from the patient's
    `current_unit_id` (it may later be re-attributed at adjudication). The
    case's `status` starts at `SUSPECTED`. And the system computes the
    **infection window period**: `infection_window_start` is the calendar date
    of `first_positive_specimen_at` minus three calendar days, at `00:00:00Z`,
    and `infection_window_end` is the calendar date of
    `first_positive_specimen_at` plus three calendar days, at `23:59:59Z` — a
    closed seven-calendar-day window, inclusive at both ends."

    Design: Corner/entities/infection_case_create_computes_iwp_and_unit
    """
    ctx = setup_unit_with_patient_and_episode()
    case = create_infection_case(
        ctx["patient"]["id"],
        case_type="CLABSI",
        suspected_organism="Serratia marcescens",
        first_positive_specimen_at="2026-08-10T10:00:00Z",
        linked_device_episode_id=ctx["episode"]["id"],
    )
    assert_infection_case(case)
    assert case["status"] == "SUSPECTED"
    assert case["unit_id"] == ctx["unit"]["id"]
    assert_instant_equal(
        case["infection_window_start"], "2026-08-07T00:00:00Z", "infection_window_start"
    )
    assert_instant_equal(
        case["infection_window_end"], "2026-08-13T23:59:59Z", "infection_window_end"
    )
    assert case["date_of_event"] is None
    assert case["rit_blocked_until"] is None


def test_schema_invalid_enum_and_conditional_required(api, ip_headers):
    """PRD §2.5: "Missing required fields, invalid enum values, integer range
    violations (such as a value that must be at least 0 or at least 1), string
    minimum-length violations, and violated conditional-required pairings all
    yield `ERR_INVALID_REQUEST` (HTTP 400)."
    PRD §2.5: "The conditional pairings are: `surgical_procedure_id` is required
    if and only if the case's `case_type` is `SSI`; `linked_device_episode_id`
    is required if and only if `case_type` is `CLABSI` or `CAUTI`;
    `date_of_event` is required if and only if the adjudication `outcome` is
    `ADJUDICATED_HAI`; and `ssi_depth` is required if and only if an SSI case is
    being adjudicated to `ADJUDICATED_HAI`."

    Design: Corner/validations/schema_invalid_enum_and_conditional_required
    """
    ctx = setup_unit_with_patient()
    resp_enum = api.create_infection_case(
        {
            "patient_id": ctx["patient"]["id"],
            "case_type": "VAP",
            "suspected_organism": "E. coli",
            "first_positive_specimen_at": "2026-08-04T10:00:00Z",
        },
        ip_headers,
    )
    validate_error(resp_enum, ApiErrorId.ERR_INVALID_REQUEST)

    resp_missing_ref = api.create_infection_case(
        {
            "patient_id": ctx["patient"]["id"],
            "case_type": "SSI",
            "suspected_organism": "E. coli",
            "first_positive_specimen_at": "2026-08-04T10:00:00Z",
        },
        ip_headers,
    )
    validate_error(resp_missing_ref, ApiErrorId.ERR_INVALID_REQUEST)


def test_episode_patient_mismatch_pure_referential(api, ip_headers):
    """PRD §3.4: "When present, each reference must also point at a row belonging
    to the same patient — a device episode of a different patient yields
    `ERR_EPISODE_PATIENT_MISMATCH`, and a procedure of a different patient
    yields `ERR_PROCEDURE_PATIENT_MISMATCH`."

    Design: Corner/validations/episode_patient_mismatch_pure_referential
    """
    facility, unit = setup_facility_unit()
    patient_1 = create_patient(unit["id"])
    patient_2 = create_patient(unit["id"])
    foreign_episode = create_device_episode(patient_2["id"])
    resp = api.create_infection_case(
        {
            "patient_id": patient_1["id"],
            "case_type": "CLABSI",
            "suspected_organism": "E. coli",
            "first_positive_specimen_at": "2026-08-06T09:00:00Z",
            "linked_device_episode_id": foreign_episode["id"],
        },
        ip_headers,
    )
    validate_error(resp, ApiErrorId.ERR_EPISODE_PATIENT_MISMATCH)


def test_adjudicate_from_suspected_returns_case_not_adjudicatable(api, ip_headers):
    """PRD §3.5: "An `InfectionPreventionist` adjudicates an `UNDER_REVIEW`
    case — anything else yields `ERR_CASE_NOT_ADJUDICATABLE` — with an
    `outcome`, a free-text `rationale` of at least ten characters (stored on the
    case as `adjudication_rationale`), and, when the outcome is
    `ADJUDICATED_HAI`, a `date_of_event` plus (for SSI cases) an `ssi_depth` of
    `SURFACE`, `DEEP`, or `ORGAN_SPACE`."

    Design: Corner/state_machines/adjudicate_from_suspected_returns_case_not_adjudicatable
    """
    ctx = setup_unit_with_patient_and_episode()
    case = create_infection_case(
        ctx["patient"]["id"],
        case_type="CLABSI",
        suspected_organism="E. coli",
        first_positive_specimen_at="2026-08-04T10:00:00Z",
        linked_device_episode_id=ctx["episode"]["id"],
    )
    resp = api.adjudicate_case(
        case["id"],
        {
            "outcome": "ADJUDICATED_HAI",
            "date_of_event": "2026-08-04T00:00:00Z",
            "rationale": "skip review attempt here",
        },
        ip_headers,
    )
    validate_error(resp, ApiErrorId.ERR_CASE_NOT_ADJUDICATABLE)
    assert get_case(case["id"])["status"] == "SUSPECTED"


def test_reopen_from_under_review_returns_case_not_reopenable(api, ip_headers):
    """PRD §3.5: "A reopen, carrying a `reason` of at least ten characters,
    requires the case to be `ADJUDICATED_HAI` or `RULED_OUT`
    (`ERR_CASE_NOT_REOPENABLE` otherwise) and is blocked by a locked covering
    summary — located by the month of `date_of_event` for an adjudicated case,
    or by the month of `first_positive_specimen_at` for a ruled-out one — with
    `ERR_SUMMARY_LOCKED`."

    Design: Corner/state_machines/reopen_from_under_review_returns_case_not_reopenable
    """
    ctx = setup_unit_with_patient_and_episode()
    case = create_case_under_review(
        ctx["patient"]["id"], linked_device_episode_id=ctx["episode"]["id"]
    )
    resp = api.reopen_case(case["id"], {"reason": "premature reopen try"}, ip_headers)
    validate_error(resp, ApiErrorId.ERR_CASE_NOT_REOPENABLE)
    assert get_case(case["id"])["status"] == "UNDER_REVIEW"


def test_begin_review_twice_and_resubmit_while_submitted(api, ip_headers):
    """PRD §3.5: "Beginning review moves a case from `SUSPECTED` — or from
    `REOPENED`, since the machine is cyclic — into `UNDER_REVIEW`. Any other
    starting state is rejected with `ERR_CASE_NOT_REVIEWABLE`."
    PRD §3.7: "Submission — from `OPEN`, `REJECTED`, or `UNDER_AMENDMENT`,
    anything else rejected with `ERR_SUMMARY_NOT_SUBMITTABLE` — records
    `submitted_by_user_id` from the acting user's header, cascades every
    denominator row for the unit and month into `LOCKED`, and is refused
    outright with `ERR_OUTBREAK_POSTURE_BLOCKS_SUBMISSION` when the unit's
    `surveillance_posture` is `OUTBREAK`."

    Design: Corner/validations/begin_review_twice_and_resubmit_while_submitted
    """
    ctx = setup_unit_with_patient_and_episode()
    case = create_case_under_review(
        ctx["patient"]["id"],
        linked_device_episode_id=ctx["episode"]["id"],
        first_positive_specimen_at="2026-08-04T10:00:00Z",
    )
    summary = create_monthly_summary(ctx["unit"]["id"], "2026-08")
    submit_summary(summary["id"])

    resp1 = api.begin_review(case["id"], ip_headers)
    validate_error(resp1, ApiErrorId.ERR_CASE_NOT_REVIEWABLE)

    resp2 = api.submit_summary(summary["id"], ip_headers)
    validate_error(resp2, ApiErrorId.ERR_SUMMARY_NOT_SUBMITTABLE)


def test_rit_boundary_last_blocked_day_vs_first_free_day(api, ip_headers):
    """PRD §3.4: "If the same patient already has an `ADJUDICATED_HAI` case of
    the same `case_type` whose `date_of_event` calendar date, extended thirteen
    calendar days forward, contains the new case's specimen calendar date —
    that is, the new specimen date falls anywhere from the earlier case's date
    of event through thirteen days after it, inclusive — creation is rejected
    with `ERR_REPEAT_INFECTION_TIMEFRAME`."

    Design: Corner/calculations/rit_boundary_last_blocked_day_vs_first_free_day
    """
    ctx = setup_unit_with_patient_and_episode()
    patient_id = ctx["patient"]["id"]
    episode_1 = ctx["episode"]
    create_adjudicated_clabsi(
        patient_id, episode_1["id"], "E. coli",
        "2026-08-05T09:00:00Z", "2026-08-05T00:00:00Z",
    )
    remove_device_episode(episode_1["id"], "2026-08-10T10:00:00Z")
    episode_2 = create_device_episode(patient_id, placed_at="2026-08-10T10:00:01Z")

    resp_blocked = api.create_infection_case(
        {
            "patient_id": patient_id,
            "case_type": "CLABSI",
            "suspected_organism": "E. coli",
            "first_positive_specimen_at": "2026-08-18T09:00:00Z",
            "linked_device_episode_id": episode_2["id"],
        },
        ip_headers,
    )
    validate_error(resp_blocked, ApiErrorId.ERR_REPEAT_INFECTION_TIMEFRAME)

    resp_free = api.create_infection_case(
        {
            "patient_id": patient_id,
            "case_type": "CLABSI",
            "suspected_organism": "E. coli",
            "first_positive_specimen_at": "2026-08-19T09:00:00Z",
            "linked_device_episode_id": episode_2["id"],
        },
        ip_headers,
    )
    case_2 = validate_success(resp_free, 201)
    assert case_2["status"] == "SUSPECTED"


def _setup_adjudicated_case_with_summary(api):
    """Adjudicated CLABSI (DOE 2026-08-04) with an OPEN 2026-08 summary that
    recorded clabsi_count 1 at creation."""
    ctx = setup_unit_with_patient_and_episode()
    case = create_adjudicated_clabsi(
        ctx["patient"]["id"], ctx["episode"]["id"], "Pseudomonas aeruginosa",
        "2026-08-04T10:00:00Z", "2026-08-04T00:00:00Z",
    )
    summary = create_monthly_summary(ctx["unit"]["id"], "2026-08")
    assert summary["clabsi_count"] == 1, (
        f"summary must credit the adjudicated case at creation, got {summary['clabsi_count']}"
    )
    ctx.update({"case": case, "summary": summary})
    return ctx


def test_reopen_clears_fields_and_recomputes_summary(api, ip_headers):
    """PRD §3.5: "Reopening clears `date_of_event`, `is_hai`, and
    `rit_blocked_until` to null, lands the case in `REOPENED`, and recomputes
    the covering summary's counts, SIRs, and `sir_flag` when mutable."

    Design: Difficulty/non_linear_state_machine/infection_case_cyclic_reopen_adjudicate_loop
    """
    ctx = _setup_adjudicated_case_with_summary(api)
    reopened = reopen_case(ctx["case"]["id"], reason="new serology contradicts")
    assert reopened["status"] == "REOPENED"
    assert reopened["date_of_event"] is None
    assert reopened["is_hai"] is None
    assert reopened["rit_blocked_until"] is None

    summary = get_summary(ctx["summary"]["id"])
    assert summary["clabsi_count"] == 0, (
        f"reopen must restore the aggregate to 0, got {summary['clabsi_count']}"
    )


def test_reopened_case_cycles_to_ruled_out(api, ip_headers):
    """PRD §3.5: "Ruling the case out requires only the `outcome` and
    `rationale`: it records `adjudicated_by_user_id` and
    `adjudication_rationale`, sets `is_hai` to false, leaves `date_of_event` and
    `rit_blocked_until` null, and lands the case in `RULED_OUT`."
    PRD §3.5: "Beginning review moves a case from `SUSPECTED` — or from
    `REOPENED`, since the machine is cyclic — into `UNDER_REVIEW`."

    Design: Difficulty/non_linear_state_machine/infection_case_cyclic_reopen_adjudicate_loop
    """
    ctx = _setup_adjudicated_case_with_summary(api)
    reopen_case(ctx["case"]["id"], reason="new serology contradicts")
    reviewed = begin_review(ctx["case"]["id"])
    assert reviewed["status"] == "UNDER_REVIEW"

    resp = api.adjudicate_case(
        ctx["case"]["id"],
        {"outcome": "RULED_OUT", "rationale": "contaminant on repeat culture"},
        ip_headers,
    )
    ruled_out = validate_success(resp)
    assert ruled_out["status"] == "RULED_OUT"
    assert ruled_out["is_hai"] is False
    assert ruled_out["date_of_event"] is None
    assert ruled_out["rit_blocked_until"] is None

    summary = get_summary(ctx["summary"]["id"])
    assert summary["clabsi_count"] == 0, (
        f"cyclic loop must leave the aggregate at 0, got {summary['clabsi_count']}"
    )


def _setup_patient_in_rit_with_foreign_episode(api):
    """P1 with an ADJUDICATED_HAI CLABSI (DOE 2026-08-05; RIT covers
    2026-08-05..2026-08-18); P2 with his own CENTRAL_LINE episode E2."""
    facility, unit = setup_facility_unit()
    patient_1 = create_patient(unit["id"])
    patient_2 = create_patient(unit["id"])
    episode_1 = create_device_episode(patient_1["id"])
    episode_2 = create_device_episode(patient_2["id"])
    create_adjudicated_clabsi(
        patient_1["id"], episode_1["id"], "Escherichia coli",
        "2026-08-05T09:00:00Z", "2026-08-05T00:00:00Z",
    )
    return {
        "facility": facility,
        "unit": unit,
        "patient_1": patient_1,
        "patient_2": patient_2,
        "episode_2": episode_2,
    }


def test_temporal_beats_referential_on_case_create_inside_rit(api, ip_headers):
    """PRD §2.5: "When a single request violates more than one rule, the error
    it receives is determined by a fixed priority order, evaluated top-down; the
    request reports the violation with the lowest priority number."
    PRD §2.5: "**Temporal window rules.** Evaluated in a pinned sub-order: first
    the repeat-infection-timeframe block on case creation
    (`ERR_REPEAT_INFECTION_TIMEFRAME`), then the date-of-event placement inside
    the infection window period (`ERR_DOE_OUTSIDE_IWP`), then the
    healthcare-associated day rule (`ERR_DOE_NOT_HAI_DAY_RULE`), then the SSI
    surveillance window (`ERR_SSI_WINDOW_EXPIRED`), then the device-day rule
    (`ERR_DEVICE_DAY_RULE_NOT_MET`), then the exposure draw windows
    (`ERR_BASELINE_WINDOW_MISSED`, `ERR_DRAW_OUTSIDE_WINDOW`), and finally the
    lost-to-followup overdue threshold (`ERR_EXPOSURE_NOT_OVERDUE`)."
    PRD §2.5: "**Cross-entity referential coherence.** A linked device episode
    belonging to a different patient yields `ERR_EPISODE_PATIENT_MISMATCH`; a
    linked surgical procedure belonging to a different patient yields
    `ERR_PROCEDURE_PATIENT_MISMATCH`; an invalid corrective-action source
    reference yields `ERR_CAP_SOURCE_INVALID` (all HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/temporal_beats_referential_on_case_create_in_rit
    """
    ctx = _setup_patient_in_rit_with_foreign_episode(api)
    resp = api.create_infection_case(
        {
            "patient_id": ctx["patient_1"]["id"],
            "case_type": "CLABSI",
            "suspected_organism": "Enterococcus faecalis",
            "first_positive_specimen_at": "2026-08-15T09:00:00Z",
            "linked_device_episode_id": ctx["episode_2"]["id"],
        },
        ip_headers,
    )
    validate_error(resp, ApiErrorId.ERR_REPEAT_INFECTION_TIMEFRAME)
    assert resp.status_code == 422


def test_temporal_shadows_referential_at_last_blocked_day(api, ip_headers):
    """PRD §3.4: "If the same patient already has an `ADJUDICATED_HAI` case of
    the same `case_type` whose `date_of_event` calendar date, extended thirteen
    calendar days forward, contains the new case's specimen calendar date —
    that is, the new specimen date falls anywhere from the earlier case's date
    of event through thirteen days after it, inclusive — creation is rejected
    with `ERR_REPEAT_INFECTION_TIMEFRAME`."
    PRD §2.5: "When a single request violates more than one rule, the error it
    receives is determined by a fixed priority order, evaluated top-down; the
    request reports the violation with the lowest priority number."

    Design: Difficulty/priority_pair_validation_conflict/temporal_beats_referential_on_case_create_in_rit
    """
    ctx = _setup_patient_in_rit_with_foreign_episode(api)
    resp = api.create_infection_case(
        {
            "patient_id": ctx["patient_1"]["id"],
            "case_type": "CLABSI",
            "suspected_organism": "Enterococcus faecalis",
            "first_positive_specimen_at": "2026-08-18T09:00:00Z",
            "linked_device_episode_id": ctx["episode_2"]["id"],
        },
        ip_headers,
    )
    validate_error(resp, ApiErrorId.ERR_REPEAT_INFECTION_TIMEFRAME)
