"""Dispatch gating: break-must-be-isolated, crew window overlap with the
60-minute travel buffer, selector ranking, empty pool, and crew ownership."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    complete_work_order,
    confirm_break,
    create_break,
    create_crew,
    get_break,
    get_crew,
    isolate_break,
    make_crew_lead_headers,
    set_clock,
    setup_confirmed_break,
    setup_dispatched_work_order,
    validate_error,
    validate_success,
)
from test_helpers import api_client as _api
from test_helpers import create_work_order_payload

DISPATCHER = TEST_USERS["dispatcher_headers"]


# ---------------------------------------------------------------------------
# Difficulty: dispatch_gated_on_break_isolated (2 tests)
# ---------------------------------------------------------------------------

def _oak_confirmed_with_crew_and_draft():
    """Segment + valve + LIGHT crew 6000 + CIRCUMFERENTIAL break CONFIRMED
    (not isolated) + DRAFT work order."""
    ctx = setup_confirmed_break(
        segment_ref="MAIN-8-OAK", diameter_inches=8, install_year=1978,
        break_type="CIRCUMFERENTIAL", severity="MEDIUM",
        location_description="400 Oak St",
    )
    crew = create_crew(crew_name="Crew Oak", crew_size=3,
                       equipment_class="LIGHT", hourly_rate_cents=6000)
    wo = validate_success(
        _api.create_work_order(
            create_work_order_payload(break_report_id=ctx["break"]["id"],
                                      est_pipe_length_ft=4),
            DISPATCHER,
        ),
        201,
    )
    ctx.update({"crew": crew, "work_order": wo})
    return ctx


def test_dispatch_rejected_while_break_not_isolated(api):
    """PRD §3.4: "A `Dispatcher` dispatches a `DRAFT` work order, optionally
    naming a `crew_id`; the parent break must be `ISOLATED` at that moment,
    otherwise `ERR_BREAK_NOT_ISOLATED`."

    Design: Difficulty/cross_entity_state_dependency/dispatch_gated_on_break_isolated
    """
    ctx = _oak_confirmed_with_crew_and_draft()
    wo, crew = ctx["work_order"], ctx["crew"]
    resp = _api.dispatch_work_order(wo["id"], {"crew_id": crew["id"]}, DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_BREAK_NOT_ISOLATED)
    after = validate_success(_api.get_work_order(wo["id"], DISPATCHER), 200)
    assert after["work_status"] == "DRAFT", (
        f"rejected dispatch must leave the order DRAFT, got {after['work_status']!r}"
    )


def test_dispatch_succeeds_after_isolation_execute(api):
    """PRD §3.4: "A `Dispatcher` dispatches a `DRAFT` work order, optionally
    naming a `crew_id`; the parent break must be `ISOLATED` at that moment,
    otherwise `ERR_BREAK_NOT_ISOLATED`."
    PRD §3.3: "The computed extent is copied onto the break's
    `customers_out_of_service`, and the break itself moves from `CONFIRMED` (or
    `REPAIRED`, in the rework loop) to `ISOLATED`."

    Design: Difficulty/cross_entity_state_dependency/dispatch_gated_on_break_isolated
    """
    ctx = _oak_confirmed_with_crew_and_draft()
    br, wo, crew = ctx["break"], ctx["work_order"], ctx["crew"]
    # Gate fails first while merely CONFIRMED.
    resp = _api.dispatch_work_order(wo["id"], {"crew_id": crew["id"]}, DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_BREAK_NOT_ISOLATED)
    # Isolate, then the identical dispatch succeeds.
    isolate_break(br["id"], [ctx["valves"][0]["id"]])
    assert get_break(br["id"])["break_status"] == "ISOLATED"
    dispatched = validate_success(
        _api.dispatch_work_order(wo["id"], {"crew_id": crew["id"]}, DISPATCHER), 200
    )
    assert dispatched["work_status"] == "DISPATCHED"
    assert dispatched["crew_id"] == crew["id"]


# ---------------------------------------------------------------------------
# Difficulty: crew_window_buffer_overlap_semantics (2 tests)
# ---------------------------------------------------------------------------

def _two_breaks_one_crew():
    """Segment with v1/Z1 + v2/Z2; Crew Oak; break A isolated with v1 and its
    work order dispatched to Crew Oak at 2026-08-01T00:00:00Z (CIRCUMFERENTIAL
    -> window [00:00, 04:00]); break B isolated with v2, work order DRAFT."""
    ctx = setup_confirmed_break(
        segment_ref="MAIN-8-OAK", diameter_inches=8, install_year=1978,
        valve_specs=[
            {"valve_code": "V-OAK-1", "coverage_zone": "Z1", "customers_served": 100},
            {"valve_code": "V-OAK-2", "coverage_zone": "Z2", "customers_served": 100},
        ],
        break_type="CIRCUMFERENTIAL", severity="MEDIUM",
        location_description="400 Oak St",
    )
    crew = create_crew(crew_name="Crew Oak", crew_size=3,
                       equipment_class="LIGHT", hourly_rate_cents=6000)
    br_a = ctx["break"]
    isolate_break(br_a["id"], [ctx["valves"][0]["id"]])
    wo_a = validate_success(
        _api.create_work_order(
            create_work_order_payload(break_report_id=br_a["id"], est_pipe_length_ft=4),
            DISPATCHER,
        ),
        201,
    )
    wo_a = validate_success(
        _api.dispatch_work_order(wo_a["id"], {"crew_id": crew["id"]}, DISPATCHER), 200
    )

    br_b = create_break(location_description="975 Oak St", source="CUSTOMER_CALL")
    br_b = confirm_break(br_b["id"], ctx["segment"]["id"],
                         break_type="CIRCUMFERENTIAL", severity="LOW")
    isolate_break(br_b["id"], [ctx["valves"][1]["id"]])
    wo_b = validate_success(
        _api.create_work_order(
            create_work_order_payload(break_report_id=br_b["id"], est_pipe_length_ft=4),
            DISPATCHER,
        ),
        201,
    )
    return {"segment": ctx["segment"], "valves": ctx["valves"], "crew": crew,
            "break_a": br_a, "wo_a": wo_a, "break_b": br_b, "wo_b": wo_b}


def test_dispatch_inside_travel_buffer_double_booked(api):
    """PRD §3.4: "A crew's occupied window runs from an existing
    dispatched-or-on-site work order's `dispatch_window_start` through its
    `dispatch_window_end` plus a 60-minute travel buffer: a new dispatch at
    clock time T is rejected with `ERR_CREW_DOUBLE_BOOKED` when T falls at or
    after `dispatch_window_start` and strictly before `dispatch_window_end`
    plus 60 minutes; at T exactly equal to `dispatch_window_end` plus 60
    minutes the crew is available again."

    Design: Difficulty/resource_temporal_overlap/crew_window_buffer_overlap_semantics
    """
    ctx = _two_breaks_one_crew()
    set_clock("2026-08-01T04:30:00Z")
    resp = _api.dispatch_work_order(
        ctx["wo_b"]["id"], {"crew_id": ctx["crew"]["id"]}, DISPATCHER
    )
    validate_error(resp, ApiErrorId.ERR_CREW_DOUBLE_BOOKED)
    after = validate_success(_api.get_work_order(ctx["wo_b"]["id"], DISPATCHER), 200)
    assert after["work_status"] == "DRAFT"


# NOTE: test_dispatch_at_buffer_end_boundary_accepted was deleted. PRD §3.4
# states both "Eligibility requires `crew_status` `AVAILABLE`" (with the crew
# staying `DISPATCHED` until completion/cancel) and "at T exactly equal to
# `dispatch_window_end` plus 60 minutes the crew is available again." At
# T = window_end + 60 with the earlier order still DISPATCHED these clauses
# collide, and PRD does not state which yields: a faithful implementer may
# gate on the stored crew_status (reject) or treat the boundary clause as
# restoring overall eligibility (accept). Two-reader collapse; the scaffold's
# resolution (Difficulty/resource_temporal_overlap/
# crew_window_buffer_overlap_semantics: "dispatch exactly at window_end+60min
# is accepted") never appears in PRD prose.


# ---------------------------------------------------------------------------
# Corner: crew_selector_empty_pool_error
# ---------------------------------------------------------------------------

def test_crew_selector_empty_pool_error(api):
    """PRD §3.4: "When the selector runs, eligible crews are ranked by
    `completed_job_count` ascending and then by `created_at` ascending, so the
    least-experienced eligible crew — earliest-registered on ties — wins; an
    empty pool yields `ERR_NO_CREW_AVAILABLE`."

    Design: Corner/calculations/crew_selector_empty_pool_error
    """
    ctx = _two_breaks_one_crew()
    # Sole crew is occupied by break A's dispatch (clock still 2026-08-01T00:00:00Z).
    resp = _api.dispatch_work_order(ctx["wo_b"]["id"], {}, DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_NO_CREW_AVAILABLE)


# ---------------------------------------------------------------------------
# Corner: crew_selector_ranking_prefers_fewer_completed
# ---------------------------------------------------------------------------

def test_crew_selector_ranking_prefers_fewer_completed(api):
    """PRD §3.4: "When the selector runs, eligible crews are ranked by
    `completed_job_count` ascending and then by `created_at` ascending, so the
    least-experienced eligible crew — earliest-registered on ties — wins; an
    empty pool yields `ERR_NO_CREW_AVAILABLE`. Crew ids are never used for
    ranking or tie-breaking."

    Design: Corner/calculations/crew_selector_ranking_prefers_fewer_completed
    """
    ctx = setup_confirmed_break(
        segment_ref="MAIN-8-OAK", diameter_inches=8, install_year=1978,
        break_type="CIRCUMFERENTIAL", severity="MEDIUM",
        location_description="400 Oak St",
    )
    br, valve = ctx["break"], ctx["valves"][0]
    crew_old = create_crew(crew_name="Crew Old", crew_size=3,
                           equipment_class="LIGHT", hourly_rate_cents=6000)
    # First job: completed by Crew Old -> completed_job_count 1.
    isolate_break(br["id"], [valve["id"]])
    wo1 = validate_success(
        _api.create_work_order(
            create_work_order_payload(break_report_id=br["id"], est_pipe_length_ft=4),
            DISPATCHER,
        ),
        201,
    )
    validate_success(
        _api.dispatch_work_order(wo1["id"], {"crew_id": crew_old["id"]}, DISPATCHER),
        200,
    )
    validate_success(
        _api.arrive_work_order(wo1["id"], make_crew_lead_headers(crew_old["id"])), 200
    )
    complete_work_order(wo1["id"], crew_old["id"], actual_pipe_length_ft=4,
                        labor_hours=1, materials_used=[])
    assert get_crew(crew_old["id"])["completed_job_count"] == 1

    crew_new = create_crew(crew_name="Crew New", crew_size=3,
                           equipment_class="LIGHT", hourly_rate_cents=6000)
    # Rework re-isolation (break is REPAIRED), then a second draft order.
    isolate_break(br["id"], [valve["id"]])
    wo2 = validate_success(
        _api.create_work_order(
            create_work_order_payload(break_report_id=br["id"], est_pipe_length_ft=4),
            DISPATCHER,
        ),
        201,
    )
    dispatched = validate_success(
        _api.dispatch_work_order(wo2["id"], {}, DISPATCHER), 200
    )
    assert dispatched["crew_id"] == crew_new["id"], (
        f"selector must prefer 0 completed jobs over 1; got crew {dispatched['crew_id']}"
    )


# ---------------------------------------------------------------------------
# Corner: crew_lead_ownership_forbidden
# ---------------------------------------------------------------------------

def test_crew_lead_ownership_forbidden(api):
    """PRD §3.4: "A `CrewLead` marks arrival, moving the work order from
    `DISPATCHED` to `ON_SITE`; the acting user's `X-User-ID` must equal the
    work order's `crew_id` (otherwise `ERR_FORBIDDEN_ROLE`)."
    PRD §2.1: "When `X-User-Role` is `CrewLead`, `X-User-ID` is the `id` of the
    acting `Crew`; ownership checks on the crew-ownership actions compare the
    work order's `crew_id` field to `X-User-ID`."

    Design: Corner/rbac/crew_lead_ownership_forbidden
    """
    ctx = setup_dispatched_work_order(
        segment_ref="MAIN-8-OAK", diameter_inches=8, install_year=1978,
        break_type="CIRCUMFERENTIAL", severity="MEDIUM",
        location_description="400 Oak St",
        crew_name="Crew Oak", crew_rate=6000,
    )
    crew_birch = create_crew(crew_name="Crew Birch", crew_size=3,
                             equipment_class="LIGHT", hourly_rate_cents=6000)
    resp = _api.arrive_work_order(
        ctx["work_order"]["id"], make_crew_lead_headers(crew_birch["id"])
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
    after = validate_success(
        _api.get_work_order(ctx["work_order"]["id"], DISPATCHER), 200
    )
    assert after["work_status"] == "DISPATCHED", (
        f"rejected arrival must leave the order DISPATCHED, got {after['work_status']!r}"
    )
