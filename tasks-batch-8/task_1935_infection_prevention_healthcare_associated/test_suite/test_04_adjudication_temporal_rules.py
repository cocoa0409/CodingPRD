"""Adjudication temporal rules: infection window placement, HAI day rule,
device-day rule, SSI surveillance windows, and transfer-day attribution
(PRD §3.4, §3.5)."""
from test_helpers import (
    ApiErrorId,
    adjudicate_hai,
    assert_instant_equal,
    begin_review,
    create_case_under_review,
    create_device_episode,
    create_infection_case,
    create_patient,
    create_surgical_procedure,
    create_unit,
    create_facility,
    setup_facility_unit,
    transfer_patient,
    validate_error,
    validate_success,
)


def test_doe_outside_iwp_rejected_one_day_before_window(api, ip_headers):
    """PRD §3.5: "The supplied `date_of_event` must fall inside that window,
    inclusive — otherwise `ERR_DOE_OUTSIDE_IWP`."
    PRD §3.4: "`infection_window_start` is the calendar date of
    `first_positive_specimen_at` minus three calendar days, at `00:00:00Z`, and
    `infection_window_end` is the calendar date of `first_positive_specimen_at`
    plus three calendar days, at `23:59:59Z` — a closed seven-calendar-day
    window, inclusive at both ends."

    Design: Corner/calculations/doe_outside_iwp_rejected_both_sides
    """
    facility, unit = setup_facility_unit()
    patient_1 = create_patient(unit["id"])
    patient_2 = create_patient(unit["id"])
    episode_1 = create_device_episode(patient_1["id"])
    episode_2 = create_device_episode(patient_2["id"])
    case_1 = create_case_under_review(
        patient_1["id"],
        linked_device_episode_id=episode_1["id"],
        suspected_organism="E. coli",
        first_positive_specimen_at="2026-08-10T10:00:00Z",
    )
    case_2 = create_case_under_review(
        patient_2["id"],
        linked_device_episode_id=episode_2["id"],
        suspected_organism="E. coli",
        first_positive_specimen_at="2026-08-10T10:00:00Z",
    )

    resp_before = api.adjudicate_case(
        case_1["id"],
        {
            "outcome": "ADJUDICATED_HAI",
            "date_of_event": "2026-08-06T23:59:59Z",
            "rationale": "symptom just before window",
        },
        ip_headers,
    )
    validate_error(resp_before, ApiErrorId.ERR_DOE_OUTSIDE_IWP)

    resp_first_day = api.adjudicate_case(
        case_2["id"],
        {
            "outcome": "ADJUDICATED_HAI",
            "date_of_event": "2026-08-07T00:00:00Z",
            "rationale": "symptom at window start ok",
        },
        ip_headers,
    )
    adjudicated = validate_success(resp_first_day)
    assert adjudicated["status"] == "ADJUDICATED_HAI"


def test_hai_day_rule_admit_plus_one_fails_plus_two_passes(api, ip_headers):
    """PRD §3.5: "The healthcare-associated day rule: the calendar date of
    `date_of_event` must be at least two calendar days after the calendar date
    of the patient's `admitted_at`, remembering that the admission date itself
    is day 1 — otherwise `ERR_DOE_NOT_HAI_DAY_RULE`."
    PRD §2.5: "**Temporal window rules.** Evaluated in a pinned sub-order: first
    the repeat-infection-timeframe block on case creation
    (`ERR_REPEAT_INFECTION_TIMEFRAME`), then the date-of-event placement inside
    the infection window period (`ERR_DOE_OUTSIDE_IWP`), then the
    healthcare-associated day rule (`ERR_DOE_NOT_HAI_DAY_RULE`), then the SSI
    surveillance window (`ERR_SSI_WINDOW_EXPIRED`), then the device-day rule
    (`ERR_DEVICE_DAY_RULE_NOT_MET`), then the exposure draw windows
    (`ERR_BASELINE_WINDOW_MISSED`, `ERR_DRAW_OUTSIDE_WINDOW`), and finally the
    lost-to-followup overdue threshold (`ERR_EXPOSURE_NOT_OVERDUE`)."

    Design: Corner/calculations/hai_day_rule_admit_plus_one_fails_plus_two_passes
    """
    facility, unit = setup_facility_unit()
    patient_1 = create_patient(unit["id"], admitted_at="2026-08-01T08:00:00Z")
    patient_2 = create_patient(unit["id"], admitted_at="2026-08-01T08:00:00Z")
    episode_1 = create_device_episode(patient_1["id"], placed_at="2026-08-01T06:00:00Z")
    episode_2 = create_device_episode(patient_2["id"], placed_at="2026-08-01T06:00:00Z")
    case_1 = create_case_under_review(
        patient_1["id"],
        linked_device_episode_id=episode_1["id"],
        suspected_organism="E. coli",
        first_positive_specimen_at="2026-08-03T09:00:00Z",
    )
    case_2 = create_case_under_review(
        patient_2["id"],
        linked_device_episode_id=episode_2["id"],
        suspected_organism="E. coli",
        first_positive_specimen_at="2026-08-04T09:00:00Z",
    )

    resp_day2 = api.adjudicate_case(
        case_1["id"],
        {
            "outcome": "ADJUDICATED_HAI",
            "date_of_event": "2026-08-02T00:00:00Z",
            "rationale": "DOE on hospital day two xx",
        },
        ip_headers,
    )
    validate_error(resp_day2, ApiErrorId.ERR_DOE_NOT_HAI_DAY_RULE)

    resp_day3 = api.adjudicate_case(
        case_2["id"],
        {
            "outcome": "ADJUDICATED_HAI",
            "date_of_event": "2026-08-03T00:00:00Z",
            "rationale": "DOE on hospital day three x",
        },
        ip_headers,
    )
    adjudicated = validate_success(resp_day3)
    assert adjudicated["status"] == "ADJUDICATED_HAI"
    assert adjudicated["is_hai"] is True


def test_device_day_rule_two_full_days_required(api, ip_headers):
    """PRD §3.5: "For a CLABSI or CAUTI case, the device-day rule: the linked
    episode must have been placed at least two calendar days before the date of
    event, and the episode must cover the date of event — `placed_at` no later
    than `date_of_event`, and either `removed_at` still null or `removed_at` no
    earlier than `date_of_event` — otherwise `ERR_DEVICE_DAY_RULE_NOT_MET`."

    Design: Corner/calculations/device_day_rule_two_full_days_required
    """
    facility, unit = setup_facility_unit()
    patient_1 = create_patient(unit["id"])
    patient_2 = create_patient(unit["id"])
    episode_1 = create_device_episode(patient_1["id"], placed_at="2026-08-03T23:00:00Z")
    episode_2 = create_device_episode(patient_2["id"], placed_at="2026-08-04T00:30:00Z")
    case_1 = create_case_under_review(
        patient_1["id"],
        linked_device_episode_id=episode_1["id"],
        suspected_organism="E. coli",
        first_positive_specimen_at="2026-08-05T09:00:00Z",
    )
    case_2 = create_case_under_review(
        patient_2["id"],
        linked_device_episode_id=episode_2["id"],
        suspected_organism="E. coli",
        first_positive_specimen_at="2026-08-05T09:00:00Z",
    )

    resp_ok = api.adjudicate_case(
        case_1["id"],
        {
            "outcome": "ADJUDICATED_HAI",
            "date_of_event": "2026-08-05T00:00:00Z",
            "rationale": "placed exactly two days prior",
        },
        ip_headers,
    )
    assert validate_success(resp_ok)["status"] == "ADJUDICATED_HAI"

    resp_short = api.adjudicate_case(
        case_2["id"],
        {
            "outcome": "ADJUDICATED_HAI",
            "date_of_event": "2026-08-05T00:00:00Z",
            "rationale": "placed only one day prior x",
        },
        ip_headers,
    )
    validate_error(resp_short, ApiErrorId.ERR_DEVICE_DAY_RULE_NOT_MET)


def test_ssi_window_30_vs_90_implant_distinction(api, ip_headers):
    """PRD §3.5: "For an SSI case, the surveillance window: the calendar date of
    `date_of_event` must be no later than the calendar date of the linked
    procedure's `performed_at` plus twenty-nine days when the procedure had no
    implant (a thirty-day window counting the procedure date as the first day),
    or plus eighty-nine days when `implant` is true (a ninety-day window) —
    otherwise `ERR_SSI_WINDOW_EXPIRED`."

    Design: Corner/calculations/ssi_window_30_vs_90_implant_distinction
    """
    facility, unit = setup_facility_unit(unit_type="OR")
    patient_1 = create_patient(unit["id"])
    patient_2 = create_patient(unit["id"])
    proc_1 = create_surgical_procedure(
        patient_1["id"], procedure_code="COLO", performed_at="2026-08-03T09:00:00Z",
        duration_minutes=60, asa_score=2, wound_class="CLEAN", implant=False,
    )
    proc_2 = create_surgical_procedure(
        patient_2["id"], procedure_code="HPRO", performed_at="2026-08-03T09:00:00Z",
        duration_minutes=60, asa_score=2, wound_class="CLEAN", implant=True,
    )
    case_1 = create_case_under_review(
        patient_1["id"],
        case_type="SSI",
        suspected_organism="S. aureus",
        first_positive_specimen_at="2026-09-02T09:00:00Z",
        surgical_procedure_id=proc_1["id"],
    )
    case_2 = create_case_under_review(
        patient_2["id"],
        case_type="SSI",
        suspected_organism="S. aureus",
        first_positive_specimen_at="2026-09-02T09:00:00Z",
        surgical_procedure_id=proc_2["id"],
    )

    resp_expired = api.adjudicate_case(
        case_1["id"],
        {
            "outcome": "ADJUDICATED_HAI",
            "date_of_event": "2026-09-02T00:00:00Z",
            "ssi_depth": "DEEP",
            "rationale": "day 31 post non-implant",
        },
        ip_headers,
    )
    validate_error(resp_expired, ApiErrorId.ERR_SSI_WINDOW_EXPIRED)

    resp_implant = api.adjudicate_case(
        case_2["id"],
        {
            "outcome": "ADJUDICATED_HAI",
            "date_of_event": "2026-09-02T00:00:00Z",
            "ssi_depth": "DEEP",
            "rationale": "day 31 post implant ok",
        },
        ip_headers,
    )
    assert validate_success(resp_implant)["status"] == "ADJUDICATED_HAI"


def test_doe_transfer_day_attributes_to_transferring_unit(api, ip_headers):
    """PRD §3.5: "Attribution then decides which unit owns the case, under the
    **transfer-out rule**. The system finds the patient's stay covering the date
    of event — the stay whose `arrived_at` is no later than the date of event
    and whose `departed_at` is either null or strictly after it. When the date
    of event's calendar date equals that covering stay's arrival calendar date,
    and an earlier stay exists whose departure calendar date equals the date of
    event's calendar date, the case is attributed to that earlier stay's
    unit — the unit the patient transferred out of on the day the infection
    declared. In every other case the case is attributed to the covering stay's
    unit. The case's `unit_id` is rewritten to the attributed unit."
    PRD §3.4: "The case's `unit_id` is taken from the patient's
    `current_unit_id` (it may later be re-attributed at adjudication)."

    Design: Corner/calculations/doe_transfer_day_attributes_to_transferring_unit
    """
    facility = create_facility()
    unit_1 = create_unit(facility["id"], name="ICU-T1")
    unit_2 = create_unit(facility["id"], name="WARD-T2", unit_type="WARD")
    patient = create_patient(unit_1["id"])
    episode = create_device_episode(patient["id"], placed_at="2026-08-02T10:00:00Z")
    transfer_patient(patient["id"], unit_2["id"], "2026-08-05T09:00:00Z")

    case = create_infection_case(
        patient["id"],
        case_type="CLABSI",
        suspected_organism="E. coli",
        first_positive_specimen_at="2026-08-05T14:00:00Z",
        linked_device_episode_id=episode["id"],
    )
    assert case["unit_id"] == unit_2["id"], (
        "at creation the case takes the patient's current unit"
    )
    begin_review(case["id"])
    adjudicated = adjudicate_hai(
        case["id"], "2026-08-05T00:00:00Z", rationale="DOE equals transfer day ok"
    )
    assert adjudicated["unit_id"] == unit_1["id"], (
        f"transfer-day DOE must attribute to the transferring unit, "
        f"got {adjudicated['unit_id']}"
    )


def _setup_case_at_doe_boundary(api):
    """Patient admitted 2026-08-06T08:00 (admit+2 = 08-08), CENTRAL_LINE placed
    2026-08-06T10:00, CLABSI specimen 2026-08-10T10:00, UNDER_REVIEW."""
    facility, unit = setup_facility_unit()
    patient = create_patient(unit["id"], admitted_at="2026-08-06T08:00:00Z")
    episode = create_device_episode(patient["id"], placed_at="2026-08-06T10:00:00Z")
    case = create_case_under_review(
        patient["id"],
        linked_device_episode_id=episode["id"],
        suspected_organism="Klebsiella pneumoniae",
        first_positive_specimen_at="2026-08-10T10:00:00Z",
    )
    return {"facility": facility, "unit": unit, "patient": patient,
            "episode": episode, "case": case}


def test_doe_chain_window_and_boundary_adjudication(api, ip_headers):
    """PRD §3.4: "`infection_window_start` is the calendar date of
    `first_positive_specimen_at` minus three calendar days, at `00:00:00Z`, and
    `infection_window_end` is the calendar date of `first_positive_specimen_at`
    plus three calendar days, at `23:59:59Z` — a closed seven-calendar-day
    window, inclusive at both ends."
    PRD §3.5: "Adjudicating to `ADJUDICATED_HAI` runs a fixed evaluation
    sequence, and each step consumes only the results of earlier steps:"
    PRD §3.5: "The healthcare-associated day rule: the calendar date of
    `date_of_event` must be at least two calendar days after the calendar date
    of the patient's `admitted_at`, remembering that the admission date itself
    is day 1 — otherwise `ERR_DOE_NOT_HAI_DAY_RULE`."

    Design: Difficulty/combinatorial_formula/date_of_event_chain_pinned_evaluation_order
    """
    ctx = _setup_case_at_doe_boundary(api)
    case = validate_success(api.get_infection_case(ctx["case"]["id"], ip_headers))
    assert_instant_equal(
        case["infection_window_start"], "2026-08-07T00:00:00Z", "infection_window_start"
    )
    assert_instant_equal(
        case["infection_window_end"], "2026-08-13T23:59:59Z", "infection_window_end"
    )

    adjudicated = adjudicate_hai(
        ctx["case"]["id"], "2026-08-08T00:00:00Z",
        rationale="fever onset documented 08-08",
    )
    assert adjudicated["status"] == "ADJUDICATED_HAI"
    assert adjudicated["is_hai"] is True
    assert_instant_equal(
        adjudicated["date_of_event"], "2026-08-08T00:00:00Z", "date_of_event"
    )


def test_doe_chain_rit_computed_from_doe_not_specimen(api, ip_headers):
    """PRD §3.5: "With the date of event validated, `is_hai` is set true, and
    the system sets `rit_blocked_until` to the date-of-event calendar date plus
    thirteen calendar days at `23:59:59Z` — a fourteen-day inclusive window that
    powers the repeat-infection block above."
    PRD §3.5: "Adjudicating to `ADJUDICATED_HAI` runs a fixed evaluation
    sequence, and each step consumes only the results of earlier steps:"

    Design: Difficulty/combinatorial_formula/date_of_event_chain_pinned_evaluation_order
    """
    ctx = _setup_case_at_doe_boundary(api)
    adjudicated = adjudicate_hai(
        ctx["case"]["id"], "2026-08-08T00:00:00Z",
        rationale="fever onset documented 08-08",
    )
    # Specimen was 2026-08-10; RIT must be derived from the DOE (08-08 + 13d),
    # not from the specimen date (which would land on 08-23).
    assert_instant_equal(
        adjudicated["rit_blocked_until"], "2026-08-21T23:59:59Z", "rit_blocked_until"
    )
    assert adjudicated["adjudicated_by_user_id"]
    assert adjudicated["adjudication_rationale"] == "fever onset documented 08-08"
