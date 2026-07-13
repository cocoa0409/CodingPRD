"""Crew dispatch: tiered labor cost, committed-minutes invariant, the buffered
crew-window conflict, validation precedence, OCC, and lookups."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    set_clock, make_asset, make_crew, make_work_order, schedule_work_order, reserve_crew,
    dispatcher_headers,
)

CLOCK = "2026-06-01T00:00:00Z"
DISP = dispatcher_headers()


def _crew_version(api, crew_id):
    return get_success_data(api.get_crew(crew_id, DISP))["version"]


# --- Difficulty: tiered labor cost (overtime) ---------------------------

def test_labor_overtime_tiered_cost(api):
    """PRD §3.5: "The regular portion is the lesser of `labor_hours` and an overtime threshold of 8 hours; the overtime portion is any hours beyond 8 (and zero when `labor_hours` does not exceed 8)."
    PRD §3.5: "The `labor_cost_cents` is the regular hours multiplied by the crew's `hourly_rate_cents`, plus the overtime hours multiplied by the crew's `hourly_rate_cents` multiplied by an overtime multiplier of 1.5, with the full sum rounded half up to whole cents."

    Design: Difficulty/combinatorial_formula/labor_overtime_tiered_min_max
    """
    set_clock(api, CLOCK)
    asset = make_asset(api, gis_segment_id="SEG-3")
    crew = make_crew(api, name="Paving B", hourly_rate_cents=6000)
    wo = make_work_order(api, asset["id"])
    schedule_work_order(api, wo["id"])
    dispatch = reserve_crew(api, wo["id"], crew["id"], "2026-06-02T08:00:00Z", "2026-06-02T18:00:00Z", labor_hours=10)
    assert dispatch["labor_cost_cents"] == 66000, f"expected 66000, got {dispatch['labor_cost_cents']}"


def test_labor_dispatch_commits_window_minutes(api):
    """PRD §3.5: "the crew's `committed_minutes` is increased by the whole number of minutes in the `[window_start, window_end)` window, and `Crew.version` is incremented."

    Design: Difficulty/combinatorial_formula/labor_overtime_tiered_min_max
    """
    set_clock(api, CLOCK)
    asset = make_asset(api, gis_segment_id="SEG-3")
    crew = make_crew(api, name="Paving B", hourly_rate_cents=6000)
    wo = make_work_order(api, asset["id"])
    schedule_work_order(api, wo["id"])
    reserve_crew(api, wo["id"], crew["id"], "2026-06-02T08:00:00Z", "2026-06-02T18:00:00Z", labor_hours=10)
    c = get_success_data(api.get_crew(crew["id"], DISP))
    assert c["committed_minutes"] == 600, f"expected 600 committed minutes, got {c['committed_minutes']}"


# --- Difficulty: reserve then cancel conserves crew minutes -------------

def _crew_with_reserved_dispatch(api):
    set_clock(api, CLOCK)
    asset = make_asset(api, gis_segment_id="SEG-16")
    crew = make_crew(api, name="Paving H")
    wo = make_work_order(api, asset["id"])
    schedule_work_order(api, wo["id"])
    dispatch = reserve_crew(api, wo["id"], crew["id"], "2026-06-02T08:00:00Z", "2026-06-02T12:00:00Z", labor_hours=4)
    return crew, dispatch


def test_dispatch_cancel_returns_committed_minutes(api):
    """PRD §3.5: "Cancellation returns the crew's committed time: the crew's `committed_minutes` is decreased by that window's minutes, the crew's `status` returns to `AVAILABLE` when it has no remaining `RESERVED` or `ACTIVE` dispatch, and `Crew.version` is incremented (as is the dispatch's own `version`)."

    Design: Difficulty/compensating_invariant/dispatch_reserve_then_cancel_conserves_crew_minutes
    """
    crew, dispatch = _crew_with_reserved_dispatch(api)
    validate_success(api.cancel_dispatch(dispatch["id"], DISP))
    c = get_success_data(api.get_crew(crew["id"], DISP))
    assert c["committed_minutes"] == 0, f"expected committed_minutes 0, got {c['committed_minutes']}"


def test_dispatch_cancel_returns_crew_to_available(api):
    """PRD §3.5: "Cancellation returns the crew's committed time: the crew's `committed_minutes` is decreased by that window's minutes, the crew's `status` returns to `AVAILABLE` when it has no remaining `RESERVED` or `ACTIVE` dispatch, and `Crew.version` is incremented (as is the dispatch's own `version`)."

    Design: Difficulty/compensating_invariant/dispatch_reserve_then_cancel_conserves_crew_minutes
    """
    crew, dispatch = _crew_with_reserved_dispatch(api)
    validate_success(api.cancel_dispatch(dispatch["id"], DISP))
    c = get_success_data(api.get_crew(crew["id"], DISP))
    assert c["status"] == "AVAILABLE", f"expected AVAILABLE, got {c['status']}"


# --- Difficulty: buffered crew-window conflict --------------------------

def test_crew_window_within_buffer_conflict_rejected(api):
    """PRD §3.5: "The half-open window `[window_start, window_end)` — extended by a mobilization buffer of 30 minutes on each side — must not overlap any existing `RESERVED` or `ACTIVE` dispatch window on the same crew; a collision is rejected with `ERR_CREW_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/crew_window_halfopen_buffer_conflict
    """
    set_clock(api, CLOCK)
    asset = make_asset(api, gis_segment_id="SEG-14")
    crew = make_crew(api, name="Paving G")
    wo_a = make_work_order(api, asset["id"]); schedule_work_order(api, wo_a["id"])
    reserve_crew(api, wo_a["id"], crew["id"], "2026-06-02T08:00:00Z", "2026-06-02T12:00:00Z", labor_hours=4)
    wo_b = make_work_order(api, asset["id"]); schedule_work_order(api, wo_b["id"])
    payload = {
        "work_order_id": wo_b["id"], "crew_id": crew["id"],
        "window_start": "2026-06-02T12:20:00Z", "window_end": "2026-06-02T14:00:00Z",
        "labor_hours": 2, "expected_crew_version": _crew_version(api, crew["id"]),
    }
    validate_error(api.create_dispatch(payload, DISP), ApiErrorId.ERR_CREW_WINDOW_CONFLICT)


def test_crew_window_clear_of_buffer_succeeds(api):
    """PRD §3.5: "A crew may legitimately hold multiple dispatches across non-overlapping (buffer-separated) windows."

    Design: Difficulty/resource_temporal_overlap/crew_window_halfopen_buffer_conflict
    """
    set_clock(api, CLOCK)
    asset = make_asset(api, gis_segment_id="SEG-14")
    crew = make_crew(api, name="Paving G")
    wo_a = make_work_order(api, asset["id"]); schedule_work_order(api, wo_a["id"])
    reserve_crew(api, wo_a["id"], crew["id"], "2026-06-02T08:00:00Z", "2026-06-02T12:00:00Z", labor_hours=4)
    wo_b = make_work_order(api, asset["id"]); schedule_work_order(api, wo_b["id"])
    payload = {
        "work_order_id": wo_b["id"], "crew_id": crew["id"],
        "window_start": "2026-06-02T13:00:00Z", "window_end": "2026-06-02T15:00:00Z",
        "labor_hours": 2, "expected_crew_version": _crew_version(api, crew["id"]),
    }
    dispatch = validate_success(api.create_dispatch(payload, DISP), expected_status=201)
    assert dispatch["status"] == "RESERVED", f"expected RESERVED, got {dispatch['status']}"


# --- Difficulty: validation precedence (state beats window conflict) ----

def test_dispatch_state_error_beats_window_conflict(api):
    """PRD §3.5: "The referenced work order must be `SCHEDULED`, and `window_end` must be strictly after `window_start`."
    PRD §2.6: "The practical consequence of this ordering is that a stale-state or terminal-state problem is reported before any of the deeper business checks, and authentication/authorization always win over everything else."

    Design: Difficulty/priority_pair_validation_conflict/dispatch_state_error_beats_window_conflict
    """
    set_clock(api, CLOCK)
    asset = make_asset(api, gis_segment_id="SEG-9")
    crew = make_crew(api, name="Paving E")
    wo_other = make_work_order(api, asset["id"]); schedule_work_order(api, wo_other["id"])
    reserve_crew(api, wo_other["id"], crew["id"], "2026-06-02T08:00:00Z", "2026-06-02T12:00:00Z", labor_hours=4)
    wo_target = make_work_order(api, asset["id"])  # left DRAFT
    payload = {
        "work_order_id": wo_target["id"], "crew_id": crew["id"],
        "window_start": "2026-06-02T09:00:00Z", "window_end": "2026-06-02T11:00:00Z",
        "labor_hours": 2, "expected_crew_version": _crew_version(api, crew["id"]),
    }
    validate_error(api.create_dispatch(payload, DISP), ApiErrorId.ERR_INVALID_STATE)


def test_dispatch_against_draft_workorder_invalid_state_isolated(api):
    """PRD §3.5: "The referenced work order must be `SCHEDULED`, and `window_end` must be strictly after `window_start`."
    PRD §2.6: "Legal state — the target resource is in a state from which the requested transition is defined, else `ERR_INVALID_STATE` (409)."

    Design: Difficulty/priority_pair_validation_conflict/dispatch_state_error_beats_window_conflict
    """
    set_clock(api, CLOCK)
    asset = make_asset(api, gis_segment_id="SEG-9")
    crew = make_crew(api, name="Paving E2")
    wo_target = make_work_order(api, asset["id"])  # DRAFT, no window conflict possible
    payload = {
        "work_order_id": wo_target["id"], "crew_id": crew["id"],
        "window_start": "2026-06-02T09:00:00Z", "window_end": "2026-06-02T11:00:00Z",
        "labor_hours": 2, "expected_crew_version": crew["version"],
    }
    validate_error(api.create_dispatch(payload, DISP), ApiErrorId.ERR_INVALID_STATE)


# --- Corner: labor at threshold, not-found, OCC -------------------------

def test_labor_at_eight_hours_no_overtime(api):
    """PRD §3.5: "The regular portion is the lesser of `labor_hours` and an overtime threshold of 8 hours; the overtime portion is any hours beyond 8 (and zero when `labor_hours` does not exceed 8)."

    Design: Corner/calculations/labor_cost_at_regular_threshold_no_overtime
    """
    set_clock(api, CLOCK)
    asset = make_asset(api, gis_segment_id="SEG-B4")
    crew = make_crew(api, name="Paving Y", hourly_rate_cents=6000)
    wo = make_work_order(api, asset["id"])
    schedule_work_order(api, wo["id"])
    dispatch = reserve_crew(api, wo["id"], crew["id"], "2026-06-02T08:00:00Z", "2026-06-02T16:00:00Z", labor_hours=8)
    assert dispatch["labor_cost_cents"] == 48000, f"expected 48000, got {dispatch['labor_cost_cents']}"


def test_dispatch_get_unknown_id_returns_not_found(api):
    """PRD §2.6: "Existence — every path `id` ... exists ... a miss yields the resource-specific not-found error (see §5) at HTTP 404."
    PRD §5 lists `ERR_DISPATCH_NOT_FOUND` at HTTP 404.

    Design: Corner/errors/dispatch_get_not_found_returns_404
    """
    resp = api.get_dispatch("00000000-0000-0000-0000-0000000000bb", DISP)
    validate_error(resp, ApiErrorId.ERR_DISPATCH_NOT_FOUND)


def test_stale_crew_version_rejected(api):
    """PRD §2.5: "When a `Dispatcher` reserves a crew (creating a `Dispatch`), the request body must include `expected_crew_version`, carrying the client's last-observed `version` of the target `Crew`. If that value does not equal the crew's current `version` ... the reservation is rejected with `ERR_STALE_CREW_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_crew_version_rejected
    """
    set_clock(api, CLOCK)
    asset = make_asset(api, gis_segment_id="SEG-C6")
    crew = make_crew(api, name="Paving Q")  # version 1
    wo = make_work_order(api, asset["id"])
    schedule_work_order(api, wo["id"])
    dispatch = reserve_crew(api, wo["id"], crew["id"], "2026-06-02T08:00:00Z", "2026-06-02T12:00:00Z", labor_hours=4)
    validate_success(api.cancel_dispatch(dispatch["id"], DISP))  # crew version advances past 1
    stale = {
        "work_order_id": wo["id"], "crew_id": crew["id"],
        "window_start": "2026-06-02T13:00:00Z", "window_end": "2026-06-02T15:00:00Z",
        "labor_hours": 2, "expected_crew_version": crew["version"],  # stale 1
    }
    validate_error(api.create_dispatch(stale, DISP), ApiErrorId.ERR_STALE_CREW_VERSION)
