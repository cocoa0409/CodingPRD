"""Survey-window lifecycle corners: the month-clamping prediction, the
command-center lead time, the hospital-wide lock cascade of OPEN_SURVEY, and the
follow-up survey that reopens a CLOSED window."""

from test_helpers import (
    ApiErrorId,
    create_survey_window,
    create_unit,
    read_finding,
    read_unit,
    schedule_tracer,
    set_clock,
    setup_active_survey,
    setup_closed_survey_condition_level_finding,
    setup_mapped_chapter,
    validate_error,
    validate_success,
    window_action,
)

CYCLE_2026_ANCHOR = "2025-03-15T00:00:00Z"


# ---------------------------------------------------------------------------
# Private setup chains this file needs and test_helpers does not provide.
# ---------------------------------------------------------------------------


def _eligible_window_with_activated_command_center(cycle_label="CYCLE-2026"):
    """CYCLE-2026 swept to ELIGIBLE at 2026-09-20 with the command center up."""
    window = create_survey_window(cycle_label, CYCLE_2026_ANCHOR)
    set_clock("2026-09-20T00:00:00Z")
    return window_action(window["id"], "ACTIVATE_COMMAND_CENTER")


def _closed_survey_without_findings():
    """A survey opened 2026-09-20 and closed 2026-09-25 carrying no findings at
    all, so the close leaves `follow_up_required` false."""
    built = setup_active_survey("CYCLE-2026", CYCLE_2026_ANCHOR, "2026-09-20T00:00:00Z")
    set_clock("2026-09-25T00:00:00Z")
    built["window"] = window_action(built["window"]["id"], "CLOSE_SURVEY")
    return built


# ===========================================================================
# Corner/state_machines
# ===========================================================================


def test_open_survey_locks_every_unit_and_aborts_scheduled_tracers(
    api, director_headers
):
    """PRD §3.6: "On success — identically for both entry points — `survey_opened_at` is stamped with the current logical clock and every hospital unit is driven to `LOCKED_FOR_SURVEY`, each such move aborting that unit's `SCHEDULED` tracers with `abort_reason` `SURVEY_ACTIVE`, zeroing its `scheduled_tracer_count` and recomputing its `readiness_score` and `readiness_band`."

    PRD §3.3: "When a survey opens, every unit in `OPEN` or in `RESTRICTED` moves to `LOCKED_FOR_SURVEY`, and each such move aborts that unit's `SCHEDULED` tracers with `abort_reason` set to `SURVEY_ACTIVE`, zeroes `scheduled_tracer_count` and recomputes the score and band — identical cascade shape from both source postures."

    PRD §3.3: "If no chapter participates, the computation stops immediately with `readiness_score` 0.00 and `readiness_band` `NOT_ASSESSED`, and the penalty is **not** applied — an unassessed unit is not punished for its open deficiencies."

    Design: Corner/state_machines/open_survey_locks_units_and_aborts_scheduled_tracers
    """
    built = setup_mapped_chapter(
        code="EC",
        name="Environment of Care",
        weight_pct=100,
        evidence_min_count=1,
        standard_code="EC.02.06.01",
        title="Safe environment",
        risk_tier="DIRECT_IMPACT",
    )
    traced_unit = create_unit("ICU-5", "ICU", 14)
    untraced_unit = create_unit("MED-6", "MED_SURG", 28)
    tracer = schedule_tracer(
        traced_unit["id"],
        built["chapter"]["id"],
        "2026-09-25T08:00:00Z",
        "2026-09-25T10:00:00Z",
        tracer_type="SYSTEM",
    )
    window = _eligible_window_with_activated_command_center()

    assert window["command_center_state"] == "ACTIVATED"
    assert window["window_state"] == "ELIGIBLE"

    opened = window_action(window["id"], "OPEN_SURVEY")

    assert opened["window_state"] == "ACTIVE_SURVEY"
    assert opened["survey_opened_at"] == "2026-09-20T00:00:00.000Z"

    assert read_unit(traced_unit["id"])["posture"] == "LOCKED_FOR_SURVEY"
    assert read_unit(untraced_unit["id"])["posture"] == "LOCKED_FOR_SURVEY"

    aborted = validate_success(api.get_mock_tracer(tracer["id"], director_headers))

    assert aborted["state"] == "ABORTED"
    assert aborted["abort_reason"] == "SURVEY_ACTIVE"

    locked = read_unit(traced_unit["id"])

    assert locked["scheduled_tracer_count"] == 0
    assert locked["readiness_band"] == "NOT_ASSESSED"


def test_open_survey_without_activated_command_center_rejected(api, director_headers):
    """PRD §2.11: "`OPEN_SURVEY` requires `command_center_state` to be `ACTIVATED` — `ERR_COMMAND_CENTER_NOT_ACTIVATED`, 409, on `POST /accreditation/survey-windows/{id}/transition`."

    PRD §3.6: "Both entry points require `command_center_state` to be `ACTIVATED`, else `ERR_COMMAND_CENTER_NOT_ACTIVATED`, and both require that no deficiency ticket anywhere in the hospital sits in `ESCALATED` with `severity` `IMMEDIATE_THREAT`, else `ERR_IMMEDIATE_THREAT_ACTIVE`."

    PRD §2.4: "`expired_evidence_count` is the number of evidence items expired by the sweep and `eligible_window_count` is the number of windows that became eligible."

    Design: Corner/state_machines/open_survey_without_activated_command_center_rejected
    """
    unit = create_unit("MED-7", "MED_SURG", 20)
    window = create_survey_window("CYCLE-2026", CYCLE_2026_ANCHOR)

    swept = set_clock("2026-09-20T00:00:00Z")

    assert swept["eligible_window_count"] == 1

    before = validate_success(api.get_survey_window(window["id"], director_headers))

    assert before["window_state"] == "ELIGIBLE"
    assert before["command_center_state"] == "STANDBY"

    rejected = api.transition_survey_window(
        window["id"], {"action": "OPEN_SURVEY"}, director_headers
    )

    validate_error(rejected, ApiErrorId.ERR_COMMAND_CENTER_NOT_ACTIVATED)

    after = validate_success(api.get_survey_window(window["id"], director_headers))

    assert after["window_state"] == "ELIGIBLE"
    assert after["survey_opened_at"] is None
    assert read_unit(unit["id"])["posture"] == "OPEN"


def test_closed_survey_window_reopens_for_follow_up_survey(api, director_headers):
    """PRD §3.6: "It has two declared entry points: `ELIGIBLE → ACTIVE_SURVEY` for the initial survey and `CLOSED → ACTIVE_SURVEY` for a follow-up survey, making the survey dimension cyclic too."

    PRD §3.6: "It stamps `survey_closed_at` with the current logical clock."

    PRD §3.6: "Every finding of this window still in `DRAFT` moves to `RESPONSE_PENDING`, and each gets both `initial_response_due_at` and `response_due_at` set to `survey_closed_at` plus that finding's own `response_deadline_days` days, counted as exact twenty-four-hour multiples."

    PRD §3.6: "`follow_up_required` is then set according to whether the window's `condition_level_finding_count` is at least one."

    PRD §3.6: "When it is, `follow_up_due_at` is set to `survey_closed_at` plus sixty days and `command_center_state` deliberately stays `ACTIVATED`, because the command center must survive to run the follow-up; when it is not, `command_center_state` moves `ACTIVATED → DEMOBILIZED` in the same request."

    PRD §3.7: "`condition_level` is true when either the `risk_level` came out as `IMMEDIATE_THREAT`, or the `classification` came out as `WIDESPREAD` while the referenced standard's `risk_tier` is `DIRECT_IMPACT` — the second branch is what catches a hospital-wide failure of a high-impact standard even when no harm was observed."

    PRD §3.6: "On success — identically for both entry points — `survey_opened_at` is stamped with the current logical clock and every hospital unit is driven to `LOCKED_FOR_SURVEY`, each such move aborting that unit's `SCHEDULED` tracers with `abort_reason` `SURVEY_ACTIVE`, zeroing its `scheduled_tracer_count` and recomputing its `readiness_score` and `readiness_band`."

    Design: Corner/state_machines/closed_survey_window_reopens_for_follow_up_survey
    """
    built = setup_closed_survey_condition_level_finding(
        chapter_code="LS",
        chapter_name="Life Safety",
        weight_pct=25,
        standard_code="LS.01.01.01",
        standard_title="Egress protection",
        unit_name="OR-4",
        unit_type="OR",
        bed_count=6,
    )
    closed = built["window"]

    assert closed["window_state"] == "CLOSED"
    assert closed["survey_closed_at"] == "2026-09-25T00:00:00.000Z"
    assert closed["follow_up_required"] is True
    assert closed["follow_up_due_at"] == "2026-11-24T00:00:00.000Z"
    assert closed["command_center_state"] == "ACTIVATED"

    finding = read_finding(built["finding"]["id"])

    assert finding["condition_level"] is True
    assert finding["state"] == "RESPONSE_PENDING"

    set_clock("2026-10-05T00:00:00Z")
    reopened = window_action(closed["id"], "OPEN_SURVEY")

    assert reopened["window_state"] == "ACTIVE_SURVEY"
    assert reopened["survey_opened_at"] == "2026-10-05T00:00:00.000Z"
    assert read_unit(built["unit"]["id"])["posture"] == "LOCKED_FOR_SURVEY"


# ===========================================================================
# Corner/calculations
# ===========================================================================


def test_survey_window_prediction_clamps_to_end_of_month(api, director_headers):
    """PRD §3.6: "The prediction uses month arithmetic that lands on the same day-of-month in the target month, clamping to the last day of that month when the day does not exist there and preserving the time of day — so an anchor of 31 August 2025 shifted eighteen months forward lands on 28 February 2027."

    PRD §3.6: "`predicted_open_date` is the anchor shifted eighteen months forward, the earliest an unannounced survey may arrive."

    PRD §3.6: "`predicted_close_date` is the anchor shifted thirty-six months forward, the latest it may arrive."

    PRD §3.6: "`command_center_activation_allowed_from` is thirty days before `predicted_open_date`, counted as exact twenty-four-hour multiples — the lead time within which the hospital is permitted to stand up its survey command center."

    PRD §3.6: "The survey dimension, `window_state`, takes `PROJECTED`, `ELIGIBLE`, `ACTIVE_SURVEY` and `CLOSED`, and starts at `PROJECTED`."

    PRD §3.6: "The command-center dimension, `command_center_state`, takes `STANDBY`, `ACTIVATED` and `DEMOBILIZED`, and starts at `STANDBY`."

    Design: Corner/calculations/survey_window_prediction_clamps_to_end_of_month
    """
    window = validate_success(
        api.create_survey_window(
            {
                "cycle_label": "CYCLE-2027",
                "prior_survey_end_date": "2025-08-31T00:00:00Z",
            },
            director_headers,
        ),
        201,
    )

    assert window["predicted_open_date"] == "2027-02-28T00:00:00.000Z"
    assert window["predicted_close_date"] == "2028-08-31T00:00:00.000Z"
    assert window["command_center_activation_allowed_from"] == "2027-01-29T00:00:00.000Z"
    assert window["window_state"] == "PROJECTED"
    assert window["command_center_state"] == "STANDBY"


# ===========================================================================
# Corner/validations
# ===========================================================================


def test_activate_command_center_before_lead_window_rejected(api, director_headers):
    """PRD §2.11: "`ACTIVATE_COMMAND_CENTER` requires the logical clock to be at or after `command_center_activation_allowed_from` — `ERR_COMMAND_CENTER_WINDOW_NOT_OPEN`, 409, on `POST /accreditation/survey-windows/{id}/transition`."

    PRD §3.6: "`ACTIVATE_COMMAND_CENTER` has two declared entry points, `STANDBY → ACTIVATED` and `DEMOBILIZED → ACTIVATED`, both requiring the logical clock to be at or after `command_center_activation_allowed_from` and both refused with `ERR_COMMAND_CENTER_WINDOW_NOT_OPEN` when it is earlier."

    PRD §3.6: "`command_center_activation_allowed_from` is thirty days before `predicted_open_date`, counted as exact twenty-four-hour multiples — the lead time within which the hospital is permitted to stand up its survey command center."

    PRD §3.6: "Activation deliberately does **not** touch `window_state`, which may perfectly well still be `PROJECTED` — the whole point of the thirty-day lead is that the command center stands up before the window opens."

    Design: Corner/validations/activate_command_center_before_lead_window_rejected
    """
    window = create_survey_window("CYCLE-2026", CYCLE_2026_ANCHOR)

    assert window["predicted_open_date"] == "2026-09-15T00:00:00.000Z"
    assert window["command_center_activation_allowed_from"] == "2026-08-16T00:00:00.000Z"

    too_early = api.transition_survey_window(
        window["id"], {"action": "ACTIVATE_COMMAND_CENTER"}, director_headers
    )

    validate_error(too_early, ApiErrorId.ERR_COMMAND_CENTER_WINDOW_NOT_OPEN)

    swept = set_clock("2026-08-16T00:00:00Z")

    assert swept["eligible_window_count"] == 0

    activated = window_action(window["id"], "ACTIVATE_COMMAND_CENTER")

    assert activated["command_center_state"] == "ACTIVATED"
    assert activated["window_state"] == "PROJECTED"


def test_open_survey_on_projected_window_returns_not_eligible(api, director_headers):
    """PRD §2.11: "`OPEN_SURVEY` requires `window_state` to be `ELIGIBLE` or `CLOSED`; `PROJECTED` and `ACTIVE_SURVEY` are rejected here with `ERR_SURVEY_WINDOW_NOT_ELIGIBLE`, 409, on `POST /accreditation/survey-windows/{id}/transition`."

    PRD §3.6: "From `PROJECTED` or from `ACTIVE_SURVEY` the action is refused with `ERR_SURVEY_WINDOW_NOT_ELIGIBLE`."

    PRD §3.6: "Activation deliberately does **not** touch `window_state`, which may perfectly well still be `PROJECTED` — the whole point of the thirty-day lead is that the command center stands up before the window opens."

    Design: Corner/validations/open_survey_on_projected_window_returns_not_eligible
    """
    window = create_survey_window("CYCLE-2026", CYCLE_2026_ANCHOR)
    set_clock("2026-08-20T00:00:00Z")
    activated = window_action(window["id"], "ACTIVATE_COMMAND_CENTER")

    assert activated["command_center_state"] == "ACTIVATED"
    assert activated["window_state"] == "PROJECTED"

    rejected = api.transition_survey_window(
        window["id"], {"action": "OPEN_SURVEY"}, director_headers
    )

    validate_error(rejected, ApiErrorId.ERR_SURVEY_WINDOW_NOT_ELIGIBLE)

    after = validate_success(api.get_survey_window(window["id"], director_headers))

    assert after["survey_opened_at"] is None


def test_follow_up_open_without_follow_up_required_rejected(api, director_headers):
    """PRD §2.11: "A follow-up `OPEN_SURVEY` requires `follow_up_required` to be true, rejecting otherwise with `ERR_FOLLOW_UP_NOT_REQUIRED`, and requires the logical clock to be at or before `follow_up_due_at`, rejecting otherwise with `ERR_FOLLOW_UP_WINDOW_EXPIRED` — both 409, on `POST /accreditation/survey-windows/{id}/transition`."

    PRD §2.11: "Rung 17 runs before rung 32, so an attempt to reopen a `CLOSED` window that needs no follow-up surfaces as `ERR_FOLLOW_UP_NOT_REQUIRED` rather than as a state-eligibility error."

    PRD §3.6: "`follow_up_required` is then set according to whether the window's `condition_level_finding_count` is at least one."

    PRD §3.6: "When it is, `follow_up_due_at` is set to `survey_closed_at` plus sixty days and `command_center_state` deliberately stays `ACTIVATED`, because the command center must survive to run the follow-up; when it is not, `command_center_state` moves `ACTIVATED → DEMOBILIZED` in the same request."

    PRD §2.11: "`OPEN_SURVEY` requires `window_state` to be `ELIGIBLE` or `CLOSED`; `PROJECTED` and `ACTIVE_SURVEY` are rejected here with `ERR_SURVEY_WINDOW_NOT_ELIGIBLE`, 409, on `POST /accreditation/survey-windows/{id}/transition`. Whether a `CLOSED` window actually requires a follow-up, and whether the follow-up deadline has passed, is checked later at rung 32 — so a `CLOSED` window always reaches this rung successfully regardless of its `follow_up_required` flag."

    PRD §3.6: "`ACTIVATE_COMMAND_CENTER` has two declared entry points, `STANDBY → ACTIVATED` and `DEMOBILIZED → ACTIVATED`, both requiring the logical clock to be at or after `command_center_activation_allowed_from` and both refused with `ERR_COMMAND_CENTER_WINDOW_NOT_OPEN` when it is earlier."

    Design: Corner/validations/follow_up_open_without_follow_up_required_rejected
    """
    built = _closed_survey_without_findings()
    closed = built["window"]

    assert closed["window_state"] == "CLOSED"
    assert closed["follow_up_required"] is False
    assert closed["follow_up_due_at"] is None
    assert closed["command_center_state"] == "DEMOBILIZED"

    # The command centre is brought back up so the reopen attempt reaches the
    # follow-up flag check rather than stopping at the earlier activation rung.
    reactivated = window_action(closed["id"], "ACTIVATE_COMMAND_CENTER")

    assert reactivated["command_center_state"] == "ACTIVATED"
    assert reactivated["window_state"] == "CLOSED"
    assert reactivated["follow_up_required"] is False

    rejected = api.transition_survey_window(
        closed["id"], {"action": "OPEN_SURVEY"}, director_headers
    )

    validate_error(rejected, ApiErrorId.ERR_FOLLOW_UP_NOT_REQUIRED)

    after = validate_success(api.get_survey_window(closed["id"], director_headers))

    assert after["window_state"] == "CLOSED"
    assert after["survey_opened_at"] == "2026-09-20T00:00:00.000Z"


def test_follow_up_open_after_due_at_returns_window_expired(api, director_headers):
    """PRD §2.11: "A follow-up `OPEN_SURVEY` requires `follow_up_required` to be true, rejecting otherwise with `ERR_FOLLOW_UP_NOT_REQUIRED`, and requires the logical clock to be at or before `follow_up_due_at`, rejecting otherwise with `ERR_FOLLOW_UP_WINDOW_EXPIRED` — both 409, on `POST /accreditation/survey-windows/{id}/transition`."

    PRD §3.6: "The follow-up entry point adds two temporal conditions checked after the eligibility rung: `follow_up_required` must be true, else `ERR_FOLLOW_UP_NOT_REQUIRED`, and the logical clock must be at or before `follow_up_due_at`, else `ERR_FOLLOW_UP_WINDOW_EXPIRED`."

    PRD §3.6: "When it is, `follow_up_due_at` is set to `survey_closed_at` plus sixty days and `command_center_state` deliberately stays `ACTIVATED`, because the command center must survive to run the follow-up; when it is not, `command_center_state` moves `ACTIVATED → DEMOBILIZED` in the same request."

    PRD §3.7: "When `condition_level` came out true, the window's `condition_level_finding_count` increases by one — which is exactly the counter that decides, at survey close, whether a follow-up survey will be required."

    PRD §3.6: "Every hospital unit then leaves `LOCKED_FOR_SURVEY` for `OPEN` or `RESTRICTED` according to its own penalty ledger, recomputing readiness as it goes."

    Design: Corner/validations/follow_up_open_after_due_at_returns_window_expired
    """
    built = setup_closed_survey_condition_level_finding(
        standard_title="Egress protection",
        unit_name="OR-11",
        unit_type="OR",
        bed_count=5,
    )
    closed = built["window"]

    assert built["finding"]["condition_level"] is True
    assert closed["condition_level_finding_count"] == 1
    assert closed["follow_up_required"] is True
    assert closed["follow_up_due_at"] == "2026-11-24T00:00:00.000Z"

    set_clock("2026-11-25T00:00:00Z")

    rejected = api.transition_survey_window(
        closed["id"], {"action": "OPEN_SURVEY"}, director_headers
    )

    validate_error(rejected, ApiErrorId.ERR_FOLLOW_UP_WINDOW_EXPIRED)

    after = validate_success(api.get_survey_window(closed["id"], director_headers))

    assert after["window_state"] == "CLOSED"
    assert read_unit(built["unit"]["id"])["posture"] != "LOCKED_FOR_SURVEY"


# ===========================================================================
# Corner/cross_cutting_complexity_layers
# ===========================================================================


def test_window_eligibility_flips_at_exact_predicted_open_date(api, director_headers):
    """PRD §2.4: "Second, the **survey eligibility re-evaluation**: every survey window whose `window_state` is `PROJECTED` and whose `predicted_open_date` is at or before the new clock while its `predicted_close_date` is at or after the new clock moves to `window_state` `ELIGIBLE`."

    PRD §2.4: "`expired_evidence_count` is the number of evidence items expired by the sweep and `eligible_window_count` is the number of windows that became eligible."

    PRD §3.6: "`predicted_open_date` is the anchor shifted eighteen months forward, the earliest an unannounced survey may arrive."

    Design: Corner/cross_cutting_complexity_layers/scheduled_action_eligibility_flips_at_exact_predicted_open_date
    """
    window = create_survey_window("CYCLE-2026", CYCLE_2026_ANCHOR)

    assert window["predicted_open_date"] == "2026-09-15T00:00:00.000Z"

    before = set_clock("2026-09-14T23:59:59Z")

    assert before["eligible_window_count"] == 0
    assert (
        validate_success(api.get_survey_window(window["id"], director_headers))[
            "window_state"
        ]
        == "PROJECTED"
    )

    boundary = set_clock("2026-09-15T00:00:00Z")

    assert boundary["eligible_window_count"] == 1
    assert (
        validate_success(api.get_survey_window(window["id"], director_headers))[
            "window_state"
        ]
        == "ELIGIBLE"
    )

    after = set_clock("2026-09-16T00:00:00Z")

    assert after["eligible_window_count"] == 0
    assert (
        validate_success(api.get_survey_window(window["id"], director_headers))[
            "window_state"
        ]
        == "ELIGIBLE"
    )
