"""Panels and seating: the seat → SERVING transition gated by trial readiness, the
panel-version OCC, the compound FORMING dismiss cascade, the seat/excuse
conservation invariant, capacity rejection, and the term-close gate.

Translates difficulty-design instances `cross_entity_state_dependency /
seat_requires_trial_ready`, `cross_entity_state_dependency /
term_close_blocked_by_reporting_summons`, `non_linear_state_machine /
panel_compound_forming_seated_dismiss_revert`, `transitive_cascade /
panel_dismiss_revert_summons_depth2`, `compensating_invariant /
panel_seat_then_excuse_conserves_seated_count`, and `resource_temporal_overlap /
panel_seat_capacity_overlap_rejected` (queue A), plus corner-design instances from
§1.9 sections `errors`, `cross_cutting_complexity_layers`, and `consistency_model`
(queue B).
"""
from test_helpers import (
    validate_success, validate_error, validate_error_is_one_of,
    ApiErrorId,
    seat_payload,
    TEST_USERS,
    set_clock, create_term, add_juror, admin_qualify, open_term, draw,
    submit_qualifying_questionnaire, check_in, create_ready_trial, create_panel,
    seat, get_panel, get_summons, get_term,
    create_trial_payload, create_panel_payload,
    setup_reporting, setup_reporting_with_forming_panel, setup_seated,
)

_ADMIN = TEST_USERS["jury_administrator_headers"]
_CLERK = TEST_USERS["court_clerk_headers"]
_JUDGE = TEST_USERS["judge_headers"]


def _reporting_summons(clock, term_name, report_date="2026-07-01T00:00:00Z",
                       service_date=None, required_jurors=1, on_floor_hours=8.0):
    """Term OPEN + one REPORTING summons. Returns dict(term, juror, summons)."""
    s = setup_reporting(report_date=report_date, clock=clock,
                        first_service_date=service_date or report_date,
                        on_floor_hours=on_floor_hours,
                        term_overrides={"name": term_name})
    return s


# ─── Difficulty: seat requires Trial READY ─────────────────────────────

def test_seat_into_scheduled_trial_rejected(api):
    """PRD §3.7: "The panel's trial must be in `READY`, or the seat is rejected with
    `ERR_TRIAL_NOT_READY` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/seat_requires_trial_ready
    """
    s = _reporting_summons("2026-07-14T08:00:00Z", "TI", service_date="2026-07-14T00:00:00Z")
    trial = validate_success(
        api.create_trial(s["term"]["id"], create_trial_payload(caption="State v. V", required_jurors=1), _JUDGE),
        201,
    )
    # Trial left SCHEDULED (not readied).
    panel = validate_success(api.create_panel(trial["id"], create_panel_payload(target_size=1), _JUDGE), 201)
    resp = api.seat(panel["id"], seat_payload(s["summons"]["id"], panel["version"]), _JUDGE)
    validate_error(resp, ApiErrorId.ERR_TRIAL_NOT_READY.value)
    assert get_summons(s["summons"]["id"])["status"] == "REPORTING", "summons must stay REPORTING"


def test_seat_succeeds_after_trial_readied(api):
    """PRD §3.7: "A `Judge` readies a trial for seating, advancing it from
    `SCHEDULED` to `READY` ... it is the cross-entity gate that lets panels under
    that trial begin seating jurors."
    PRD §3.7: "the seated summons advances from `REPORTING` to `SERVING`."

    Design: Difficulty/cross_entity_state_dependency/seat_requires_trial_ready
    """
    s = _reporting_summons("2026-07-14T08:00:00Z", "TI2", service_date="2026-07-14T00:00:00Z")
    trial = create_ready_trial(s["term"]["id"], required_jurors=1, caption="State v. V")
    panel = create_panel(trial["id"], target_size=1)
    validate_success(api.seat(panel["id"], seat_payload(s["summons"]["id"], panel["version"]), _JUDGE), 201)
    assert get_summons(s["summons"]["id"])["status"] == "SERVING"
    assert get_panel(panel["id"])["seated_count"] == 1


# ─── Difficulty: term close blocked by REPORTING summons ───────────────

def test_close_blocked_while_summons_reporting(api):
    """PRD §3.1: "A term may be closed only while it is `OPEN`, only when no summons
    in the term remains in `REPORTING` or `SERVING` ... and only when no panel in
    the term is still `FORMING`."

    Design: Difficulty/cross_entity_state_dependency/term_close_blocked_by_reporting_summons
    """
    s = _reporting_summons("2026-07-15T08:00:00Z", "TJ", service_date="2026-07-15T00:00:00Z")
    resp = api.close_service_term(s["term"]["id"], _ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    assert get_term(s["term"]["id"])["status"] == "OPEN"


def test_close_succeeds_after_reporting_summons_released(api):
    """PRD §3.1: "Closing the term advances it from `OPEN` to `CLOSED`, a terminal
    state that locks the term against any further draw, summons issuance, or
    check-in."
    PRD §3.9: "A `REPORTING` juror who never took a seat — one holding no `SEATED`
    panel assignment — may also be released directly."

    Design: Difficulty/cross_entity_state_dependency/term_close_blocked_by_reporting_summons
    """
    s = _reporting_summons("2026-07-15T08:00:00Z", "TJ2", service_date="2026-07-15T00:00:00Z")
    validate_success(api.release_summons(s["summons"]["id"], _CLERK))
    validate_success(api.close_service_term(s["term"]["id"], _ADMIN))
    assert get_term(s["term"]["id"])["status"] == "CLOSED"


# ─── Difficulty: compound panel dismiss (FORMING→DISMISSED reverts) ────

def test_forming_panel_dismiss_sets_dismissed_and_resets_seated_count(api):
    """PRD §3.9: "Dismissing a `FORMING` panel also moves it to `DISMISSED`, but
    here the system cascades: every `SEATED` panel assignment on it is set to
    `EXCUSED_FROM_PANEL`, each occupying summons reverts from `SERVING` back to
    `REPORTING`, the panel's `seated_count` resets to zero, and the panel's
    `version` increments by one."

    Design: Difficulty/non_linear_state_machine/panel_compound_forming_seated_dismiss_revert
    """
    s = setup_seated(target_size=2, required_jurors=2, clock="2026-07-10T08:00:00Z",
                     service_date="2026-07-10T00:00:00Z")
    validate_success(api.dismiss_panel(s["panel"]["id"], _JUDGE))
    panel = get_panel(s["panel"]["id"])
    assert panel["status"] == "DISMISSED"
    assert panel["seated_count"] == 0


def test_forming_panel_dismiss_reverts_summons_and_excuses_assignment(api):
    """PRD §3.9: "every `SEATED` panel assignment on it is set to
    `EXCUSED_FROM_PANEL`, each occupying summons reverts from `SERVING` back to
    `REPORTING`."

    Design: Difficulty/non_linear_state_machine/panel_compound_forming_seated_dismiss_revert
    """
    s = setup_seated(target_size=2, required_jurors=2, clock="2026-07-10T08:00:00Z",
                     service_date="2026-07-10T00:00:00Z")
    validate_success(api.dismiss_panel(s["panel"]["id"], _JUDGE))
    assert get_summons(s["summons"]["id"])["status"] == "REPORTING"
    assignment = validate_success(api.get_panel_assignment(s["assignment"]["id"], _JUDGE))
    assert assignment["status"] == "EXCUSED_FROM_PANEL"


# ─── Difficulty: depth-2 cascade from panel dismiss ────────────────────

def test_dismiss_cascade_hop1_assignment_excused(api):
    """PRD §3.9: "every `SEATED` panel assignment on it is set to
    `EXCUSED_FROM_PANEL`."

    Design: Difficulty/transitive_cascade/panel_dismiss_revert_summons_depth2
    """
    s = setup_seated(target_size=2, required_jurors=2, clock="2026-07-11T08:00:00Z",
                     service_date="2026-07-11T00:00:00Z")
    validate_success(api.dismiss_panel(s["panel"]["id"], _JUDGE))
    assignment = validate_success(api.get_panel_assignment(s["assignment"]["id"], _JUDGE))
    assert assignment["status"] == "EXCUSED_FROM_PANEL"


def test_dismiss_cascade_hop2_summons_reverts_to_reporting(api):
    """PRD §3.9: "each occupying summons reverts from `SERVING` back to
    `REPORTING`."

    Design: Difficulty/transitive_cascade/panel_dismiss_revert_summons_depth2
    """
    s = setup_seated(target_size=2, required_jurors=2, clock="2026-07-11T08:00:00Z",
                     service_date="2026-07-11T00:00:00Z")
    validate_success(api.dismiss_panel(s["panel"]["id"], _JUDGE))
    assert get_summons(s["summons"]["id"])["status"] == "REPORTING"


# ─── Difficulty: seat-then-excuse conserves seated_count ───────────────

def test_excuse_from_panel_restores_seated_count(api):
    """PRD §3.9: "It sets the assignment's `status` to `EXCUSED_FROM_PANEL`, which
    frees the seat: the panel's `seated_count` decrements, the panel's `version`
    increments by one, and the juror returns to the reporting hall in `REPORTING`."

    Design: Difficulty/compensating_invariant/panel_seat_then_excuse_conserves_seated_count
    """
    s = setup_seated(target_size=2, required_jurors=2, clock="2026-07-18T08:00:00Z",
                     service_date="2026-07-18T00:00:00Z")
    assert get_panel(s["panel"]["id"])["seated_count"] == 1, "seated_count is 1 after the seat"
    validate_success(api.excuse_from_panel(s["assignment"]["id"], _JUDGE))
    assert get_panel(s["panel"]["id"])["seated_count"] == 0, "excuse-from-panel restores seated_count to 0"


def test_excuse_from_panel_reverts_summons_to_reporting(api):
    """PRD §3.9: "an excuse-from-panel action that moves the summons from `SERVING`
    back to `REPORTING`."

    Design: Difficulty/compensating_invariant/panel_seat_then_excuse_conserves_seated_count
    """
    s = setup_seated(target_size=2, required_jurors=2, clock="2026-07-18T08:00:00Z",
                     service_date="2026-07-18T00:00:00Z")
    validate_success(api.excuse_from_panel(s["assignment"]["id"], _JUDGE))
    assert get_summons(s["summons"]["id"])["status"] == "REPORTING"


# ─── Difficulty: capacity overlap rejected (1-seat panel) ──────────────

def _two_reporting_summonses(clock, term_name):
    set_clock(clock)
    term = create_term(name=term_name, report_date="2026-07-01T00:00:00Z")
    j1 = add_juror(term["id"], full_name="Oda J")
    j2 = add_juror(term["id"], full_name="Pat J")
    admin_qualify(j1["id"])
    admin_qualify(j2["id"])
    open_v = open_term(term["id"])["version"]
    summonses = draw(term["id"], open_v, count=2)
    s1, s2 = summonses[0], summonses[1]
    submit_qualifying_questionnaire(s1["id"], s1["juror_id"])
    submit_qualifying_questionnaire(s2["id"], s2["juror_id"])
    service_date = clock.split("T")[0] + "T00:00:00Z"
    check_in(s1["id"], service_date, 8.0)
    check_in(s2["id"], service_date, 8.0)
    return term, s1, s2


def test_seat_second_summons_into_full_one_seat_panel_rejected(api):
    """PRD §3.7: "The panel must still be `FORMING` with `seated_count` below
    `target_size`; an attempt to seat when `seated_count` already equals
    `target_size` is rejected with `ERR_PANEL_FULL` (HTTP 409)."
    PRD §3.7: "When that increment brings `seated_count` up to `target_size`, the
    panel fills: it auto-transitions from `FORMING` to `SEATED`."
    PRD §3.1: "a transition requested from a state in which it is not defined yields
    `ERR_INVALID_STATE` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/panel_seat_capacity_overlap_rejected
    """
    term, s1, s2 = _two_reporting_summonses("2026-07-17T08:00:00Z", "TL")
    trial = create_ready_trial(term["id"], required_jurors=1, caption="State v. U")
    panel = create_panel(trial["id"], target_size=1)
    seat(panel["id"], s1["id"], panel["version"])  # fills the 1-seat panel → auto SEATED
    panel_after = get_panel(panel["id"])
    # A 1-seat panel leaves FORMING on the first seat; the second seat is rejected
    # either by capacity (ERR_PANEL_FULL) or by the state precondition (panel no
    # longer FORMING). PRD does not pin which fires first, so accept either.
    resp = api.seat(panel["id"], seat_payload(s2["id"], panel_after["version"]), _JUDGE)
    validate_error_is_one_of(resp, [ApiErrorId.ERR_PANEL_FULL.value, ApiErrorId.ERR_INVALID_STATE.value])


def test_one_seat_panel_auto_seats_on_first_seat(api):
    """PRD §3.7: "When that increment brings `seated_count` up to `target_size`, the
    panel fills: it auto-transitions from `FORMING` to `SEATED`, its trial advances
    from `READY` to `IN_TRIAL`."

    Design: Difficulty/resource_temporal_overlap/panel_seat_capacity_overlap_rejected
    """
    term, s1, s2 = _two_reporting_summonses("2026-07-17T08:00:00Z", "TL2")
    trial = create_ready_trial(term["id"], required_jurors=1, caption="State v. U")
    panel = create_panel(trial["id"], target_size=1)
    seat(panel["id"], s1["id"], panel["version"])
    panel_after = get_panel(panel["id"])
    assert panel_after["status"] == "SEATED", f"1-seat panel must auto-SEAT, got {panel_after['status']}"
    assert panel_after["seated_count"] == 1


# ─── Corner: panel version increments on each seat ─────────────────────

def test_panel_version_increments_by_one_on_seat(api):
    """PRD §3.7: "the panel's `seated_count` increments, the panel's `version`
    increments by one, and the seated summons advances from `REPORTING` to
    `SERVING`."
    PRD §2.4: "The `version` field is an integer that starts at its initial value on
    creation and increments by one on every mutation of the resource."

    Design: Corner/cross_cutting_complexity_layers/panel_version_increments_on_each_seat
    """
    s = setup_reporting_with_forming_panel(target_size=2, required_jurors=2,
                                           clock="2026-07-22T08:00:00Z",
                                           service_date="2026-07-22T00:00:00Z")
    assert s["panel"]["version"] == 1, "panel starts at version 1 on create"
    seat(s["panel"]["id"], s["summons"]["id"], s["panel_version"])
    panel_after = get_panel(s["panel"]["id"])
    assert panel_after["version"] == 2, f"version must be 2 after the first seat, got {panel_after['version']}"
    assert panel_after["seated_count"] == 1
    assert panel_after["status"] == "FORMING", "a 2-seat panel stays FORMING after one seat"


# ─── Corner: seat side effects visible immediately ─────────────────────

def test_seat_side_effects_visible_immediately(api):
    """PRD §2.5: "The system maintains immediate consistency across its resource
    hierarchy."
    PRD §3.7: "the panel's `seated_count` increments ... and the seated summons
    advances from `REPORTING` to `SERVING`."

    Design: Corner/consistency_model/seat_side_effects_visible_immediately
    """
    s = setup_reporting_with_forming_panel(target_size=2, required_jurors=2,
                                           clock="2026-07-23T08:00:00Z",
                                           service_date="2026-07-23T00:00:00Z")
    seat(s["panel"]["id"], s["summons"]["id"], s["panel_version"])
    assert get_panel(s["panel"]["id"])["seated_count"] == 1
    assert get_summons(s["summons"]["id"])["status"] == "SERVING"


# ─── Corner: stale panel version on second seat ────────────────────────

def test_stale_panel_version_on_second_seat_rejected(api):
    """PRD §2.6: "Seating increments the panel's `version` by one; if
    `expected_panel_version` does not equal the panel's current `version`, the seat
    request is rejected with `ERR_STALE_PANEL_VERSION` (HTTP 412)."

    Design: Corner/errors/stale_panel_version_on_second_seat
    """
    term, s1, s2 = _two_reporting_summonses("2026-07-21T08:00:00Z", "ER2")
    trial = create_ready_trial(term["id"], required_jurors=2, caption="State v. ER2")
    panel = create_panel(trial["id"], target_size=2)
    panel_v0 = panel["version"]
    seat(panel["id"], s1["id"], panel_v0)  # advances panel version
    # Second seat carries the stale pre-first-seat version.
    resp = api.seat(panel["id"], seat_payload(s2["id"], panel_v0), _JUDGE)
    validate_error(resp, ApiErrorId.ERR_STALE_PANEL_VERSION.value)
    assert get_panel(panel["id"])["seated_count"] == 1
    assert get_summons(s2["id"])["status"] == "REPORTING"
