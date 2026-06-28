"""Dispatch validation, routing fork, visit lifecycle, abort compensation, and OCC.

Translates difficulty rules: priority_pair_validation_conflict (zone vs skill),
resource_temporal_overlap (on-site half-open), transitive_cascade (abort),
compensating_invariant (abort), plus corner state_machines / errors / cross-cutting
dispatch instances.
"""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    make_customer_headers, make_mechanic_headers,
    set_clock, create_customer, create_mechanic, create_service_request,
    send_quote, approve_quote, dispatch, _sr_version,
    setup_approved_request, setup_dispatched_request,
    create_dispatch_payload,
)
from test_helpers.test_users import TEST_USERS

DISPATCHER = TEST_USERS["dispatcher_headers"]


# ── Difficulty: zone mismatch (priority 7) beats skill tier (priority 8) ──

def test_zone_mismatch_beats_skill_tier_on_dispatch(api):
    """PRD §3.4: "the mechanic's `zone_code` must equal the request's `zone_code`; a
    territory mismatch is rejected with `ERR_ZONE_MISMATCH` (HTTP 409). Then, when the
    chosen routing is `TOW_TO_SHOP`, the mechanic's `skill_tier` must be exactly
    `TIER3`, since only that tier coordinates tows; a lesser tier is rejected with
    `ERR_INSUFFICIENT_SKILL_TIER` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/zone_mismatch_beats_skill_tier_on_dispatch
    """
    set_clock()
    customer = create_customer(home_zone_code="Z1", email="m9@x.com")
    mechanic = create_mechanic(zone_code="Z2", skill_tier="TIER1",
                               labor_rate_cents_per_hour=9000)
    sr = create_service_request(customer["id"], vehicle_vin="1HGCM82633A004360",
                                severity="URGENT")
    quote = send_quote(sr["id"], mechanic["id"], estimated_labor_hours=1.0,
                       estimated_parts_cents=0, labor_rate_cents_per_hour=9000,
                       tow_fee_cents=15000)
    approve_quote(quote["id"], customer["id"], sr["id"])

    version = _sr_version(sr["id"])
    res = api.dispatch(sr["id"], create_dispatch_payload(
        mechanic["id"], version, routing_mode="TOW_TO_SHOP",
        scheduled_start_utc="2026-04-02T09:00:00Z",
        scheduled_end_utc="2026-04-02T11:00:00Z"), DISPATCHER)
    validate_error(res, "ERR_ZONE_MISMATCH", expected_status=409)
    sr_after = validate_success(api.get_service_request(sr["id"], DISPATCHER), 200)
    assert sr_after["status"] == "APPROVED"


def test_dispatch_zone_match_skill_insufficient_then_isolated_skill_error(api):
    """PRD §3.4: "when the chosen routing is `TOW_TO_SHOP`, the mechanic's `skill_tier`
    must be exactly `TIER3`, since only that tier coordinates tows; a lesser tier is
    rejected with `ERR_INSUFFICIENT_SKILL_TIER` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/zone_mismatch_beats_skill_tier_on_dispatch
    """
    # Zones matched so the zone check passes; the next-priority skill check then fires.
    ctx = setup_approved_request(home_zone_code="Z1", mechanic_zone="Z1",
                                 mechanic_tier="TIER1", tow_fee_cents=15000,
                                 email="m9b@x.com")
    sr, mechanic = ctx["service_request"], ctx["mechanic"]
    version = _sr_version(sr["id"])
    res = api.dispatch(sr["id"], create_dispatch_payload(
        mechanic["id"], version, routing_mode="TOW_TO_SHOP",
        scheduled_start_utc="2026-04-02T09:00:00Z",
        scheduled_end_utc="2026-04-02T11:00:00Z"), DISPATCHER)
    validate_error(res, "ERR_INSUFFICIENT_SKILL_TIER", expected_status=409)


# ── Corner: insufficient skill tier (isolated, zones matched) ──

def test_insufficient_skill_tier_pure(api):
    """PRD §3.4: "when the chosen routing is `TOW_TO_SHOP`, the mechanic's `skill_tier`
    must be exactly `TIER3`, since only that tier coordinates tows; a lesser tier is
    rejected with `ERR_INSUFFICIENT_SKILL_TIER` (HTTP 409)."

    Design: Corner/errors/insufficient_skill_tier_pure_excluded
    """
    ctx = setup_approved_request(home_zone_code="Z1", mechanic_zone="Z1",
                                 mechanic_tier="TIER1", tow_fee_cents=15000,
                                 email="c20@x.com")
    sr, mechanic = ctx["service_request"], ctx["mechanic"]
    version = _sr_version(sr["id"])
    res = api.dispatch(sr["id"], create_dispatch_payload(
        mechanic["id"], version, routing_mode="TOW_TO_SHOP",
        scheduled_start_utc="2026-04-02T09:00:00Z",
        scheduled_end_utc="2026-04-02T11:00:00Z"), DISPATCHER)
    validate_error(res, "ERR_INSUFFICIENT_SKILL_TIER", expected_status=409)
    sr_after = validate_success(api.get_service_request(sr["id"], DISPATCHER), 200)
    assert sr_after["status"] == "APPROVED"


# ── Difficulty: on-site half-open overlap rejected ──

def test_onsite_dispatch_overlap_rejected(api):
    """PRD §3.4: "the proposed visit interval must not overlap any existing non-terminal
    on-site visit already booked for that same mechanic. The interval is treated as
    half-open, spanning from the start instant up to but not including the end instant,
    so two visits that merely touch at a boundary do not conflict; a genuine overlap is
    rejected with `ERR_VISIT_OVERLAP` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/onsite_dispatch_half_open_overlap_rejected
    """
    set_clock()
    mechanic = create_mechanic(zone_code="Z1", skill_tier="TIER2",
                               labor_rate_cents_per_hour=9000)
    cust_a = create_customer(home_zone_code="Z1", email="m15a@x.com", full_name="M15a")
    cust_b = create_customer(home_zone_code="Z1", email="m15b@x.com", full_name="M15b")

    sr_a = create_service_request(cust_a["id"], vehicle_vin="1HGCM82633A004366")
    qa = send_quote(sr_a["id"], mechanic["id"])
    approve_quote(qa["id"], cust_a["id"], sr_a["id"])
    dispatch(sr_a["id"], mechanic["id"], routing_mode="ON_SITE",
             scheduled_start_utc="2026-04-02T09:00:00Z",
             scheduled_end_utc="2026-04-02T11:00:00Z")

    sr_b = create_service_request(cust_b["id"], vehicle_vin="1HGCM82633A004367")
    qb = send_quote(sr_b["id"], mechanic["id"])
    approve_quote(qb["id"], cust_b["id"], sr_b["id"])

    version_b = _sr_version(sr_b["id"])
    res = api.dispatch(sr_b["id"], create_dispatch_payload(
        mechanic["id"], version_b, routing_mode="ON_SITE",
        scheduled_start_utc="2026-04-02T10:00:00Z",
        scheduled_end_utc="2026-04-02T12:00:00Z"), DISPATCHER)
    validate_error(res, "ERR_VISIT_OVERLAP", expected_status=409)
    sr_b_after = validate_success(api.get_service_request(sr_b["id"], DISPATCHER), 200)
    assert sr_b_after["status"] == "APPROVED"


def test_onsite_dispatch_abutting_boundary_allowed(api):
    """PRD §3.4: "The interval is treated as half-open, spanning from the start instant
    up to but not including the end instant, so two visits that merely touch at a
    boundary do not conflict".

    Design: Difficulty/resource_temporal_overlap/onsite_dispatch_half_open_overlap_rejected
    """
    set_clock()
    mechanic = create_mechanic(zone_code="Z1", skill_tier="TIER2",
                               labor_rate_cents_per_hour=9000)
    cust_a = create_customer(home_zone_code="Z1", email="m15c@x.com", full_name="M15c")
    cust_b = create_customer(home_zone_code="Z1", email="m15d@x.com", full_name="M15d")

    sr_a = create_service_request(cust_a["id"], vehicle_vin="1HGCM82633A004376")
    qa = send_quote(sr_a["id"], mechanic["id"])
    approve_quote(qa["id"], cust_a["id"], sr_a["id"])
    dispatch(sr_a["id"], mechanic["id"], routing_mode="ON_SITE",
             scheduled_start_utc="2026-04-02T09:00:00Z",
             scheduled_end_utc="2026-04-02T11:00:00Z")

    sr_b = create_service_request(cust_b["id"], vehicle_vin="1HGCM82633A004377")
    qb = send_quote(sr_b["id"], mechanic["id"])
    approve_quote(qb["id"], cust_b["id"], sr_b["id"])

    version_b = _sr_version(sr_b["id"])
    # 11:00-12:00 abuts the prior [09:00,11:00) at the boundary — must be allowed.
    res = api.dispatch(sr_b["id"], create_dispatch_payload(
        mechanic["id"], version_b, routing_mode="ON_SITE",
        scheduled_start_utc="2026-04-02T11:00:00Z",
        scheduled_end_utc="2026-04-02T12:00:00Z"), DISPATCHER)
    jv = validate_success(res, 201)
    assert jv["visit_status"] == "SCHEDULED"


# ── Corner: dispatch from INTAKE is an invalid state ──

def test_dispatch_from_intake_invalid_state(api):
    """PRD §3.4: "Once a request is `APPROVED`, a dispatcher assigns a mechanic and
    chooses how the work will be delivered."
    PRD §3.4: "The request must be in `APPROVED` status and the selected mechanic must be
    `AVAILABLE`, else the move is rejected as an invalid state."

    Design: Corner/state_machines/dispatch_from_intake_invalid_state
    """
    set_clock()
    customer = create_customer(home_zone_code="Z1", email="c9@x.com")
    mechanic = create_mechanic(zone_code="Z1", skill_tier="TIER2",
                               labor_rate_cents_per_hour=9000)
    sr = create_service_request(customer["id"], vehicle_vin="1HGCM82633A100010")
    version = _sr_version(sr["id"])
    res = api.dispatch(sr["id"], create_dispatch_payload(
        mechanic["id"], version, routing_mode="ON_SITE"), DISPATCHER)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)
    sr_after = validate_success(api.get_service_request(sr["id"], DISPATCHER), 200)
    assert sr_after["status"] == "INTAKE"


# ── Corner: TOW branch start-work reaches AT_SHOP ──

def test_tow_branch_start_work_reaches_at_shop(api):
    """PRD §3.5: "starting an `ON_SITE` visit moves it `EN_ROUTE → ON_SITE_WORKING`, while
    starting a `TOW_TO_SHOP` visit moves it `EN_ROUTE → AT_SHOP`. In both cases starting
    work also drives the parent request `DISPATCHED → IN_PROGRESS`".

    Design: Corner/state_machines/tow_branch_start_work_reaches_at_shop
    """
    ctx = setup_dispatched_request(routing_mode="TOW_TO_SHOP", mechanic_tier="TIER3",
                                   mechanic_rate=12000, tow_fee_cents=15000,
                                   scheduled_start_utc="2026-04-02T09:00:00Z",
                                   scheduled_end_utc="2026-04-02T12:00:00Z",
                                   email="c12@x.com")
    mech_headers = make_mechanic_headers(ctx["mechanic"]["id"])
    jv_id = ctx["job_visit"]["id"]
    get_success_data(api.depart(jv_id, mech_headers))
    res = api.start_work(jv_id, mech_headers)
    jv = validate_success(res, 200)
    assert jv["visit_status"] == "AT_SHOP"
    sr_after = validate_success(api.get_service_request(ctx["service_request"]["id"],
                                                        DISPATCHER), 200)
    assert sr_after["status"] == "IN_PROGRESS"


# ── Difficulty: abort cascade (visit -> request revert) ──

def test_abort_cascade_visit_to_request_revert(api):
    """PRD §3.5: "Aborting moves the visit to `ABORTED`, and as a compensation it unwinds
    the dispatch: the parent request reverts `DISPATCHED → APPROVED` so it can be
    dispatched afresh, and the request's `routing_mode` is reset to null."

    Design: Difficulty/transitive_cascade/abort_cascade_visit_to_request_revert
    """
    ctx = setup_dispatched_request(routing_mode="ON_SITE", email="m8@x.com")
    jv_id = ctx["job_visit"]["id"]
    res = api.abort(jv_id, DISPATCHER)
    jv = validate_success(res, 200)
    assert jv["visit_status"] == "ABORTED"
    sr_after = validate_success(api.get_service_request(ctx["service_request"]["id"],
                                                        DISPATCHER), 200)
    assert sr_after["status"] == "APPROVED"
    assert sr_after["routing_mode"] is None


def test_abort_allows_redispatch_to_same_mechanic(api):
    """PRD §3.5: "the parent request reverts `DISPATCHED → APPROVED` so it can be
    dispatched afresh, and the request's `routing_mode` is reset to null."

    Design: Difficulty/transitive_cascade/abort_cascade_visit_to_request_revert
    """
    ctx = setup_dispatched_request(routing_mode="ON_SITE", email="m8b@x.com")
    sr, mechanic, jv = ctx["service_request"], ctx["mechanic"], ctx["job_visit"]
    get_success_data(api.abort(jv["id"], DISPATCHER))
    # The reverted request is APPROVED again and accepts a fresh dispatch.
    version = _sr_version(sr["id"])
    res = api.dispatch(sr["id"], create_dispatch_payload(
        mechanic["id"], version, routing_mode="ON_SITE",
        scheduled_start_utc="2026-04-03T09:00:00Z",
        scheduled_end_utc="2026-04-03T10:00:00Z"), DISPATCHER)
    jv2 = validate_success(res, 201)
    assert jv2["visit_status"] == "SCHEDULED"


# ── Difficulty: abort conserves request re-dispatchability ──

def test_abort_conserves_request_redispatchability(api):
    """PRD §2.8: "Aborting a scheduled or en-route visit not only terminates that visit
    but also unwinds the dispatch that created it, returning the service request to a
    re-dispatchable state and clearing the routing choice."
    PRD §3.5: "the parent request reverts `DISPATCHED → APPROVED` so it can be dispatched
    afresh, and the request's `routing_mode` is reset to null."

    Design: Difficulty/compensating_invariant/abort_conserves_request_redispatchability
    """
    ctx = setup_approved_request(email="m18@x.com")
    sr = ctx["service_request"]
    # Pre-dispatch tuple recorded from a fresh APPROVED request.
    pre = validate_success(api.get_service_request(sr["id"], DISPATCHER), 200)
    assert pre["status"] == "APPROVED"
    assert pre["routing_mode"] is None

    jv = dispatch(sr["id"], ctx["mechanic"]["id"], routing_mode="ON_SITE")
    dispatched = validate_success(api.get_service_request(sr["id"], DISPATCHER), 200)
    assert dispatched["status"] == "DISPATCHED"
    assert dispatched["routing_mode"] == "ON_SITE"

    abort_res = api.abort(jv["id"], DISPATCHER)
    aborted_visit = validate_success(abort_res, 200)
    assert aborted_visit["visit_status"] == "ABORTED"
    post = validate_success(api.get_service_request(sr["id"], DISPATCHER), 200)
    assert post["status"] == "APPROVED"
    assert post["routing_mode"] is None


def test_abort_restores_exact_predispatch_tuple_from_en_route(api):
    """PRD §2.8: "Aborting a scheduled or en-route visit not only terminates that visit
    but also unwinds the dispatch that created it, returning the service request to a
    re-dispatchable state and clearing the routing choice."

    Design: Difficulty/compensating_invariant/abort_conserves_request_redispatchability
    """
    ctx = setup_dispatched_request(routing_mode="ON_SITE", email="m18b@x.com")
    sr, mechanic, jv = ctx["service_request"], ctx["mechanic"], ctx["job_visit"]
    # Advance the visit to EN_ROUTE, then abort from there (abort is allowed SCHEDULED|EN_ROUTE).
    get_success_data(api.depart(jv["id"], make_mechanic_headers(mechanic["id"])))
    aborted = validate_success(api.abort(jv["id"], DISPATCHER), 200)
    assert aborted["visit_status"] == "ABORTED"
    post = validate_success(api.get_service_request(sr["id"], DISPATCHER), 200)
    assert post["status"] == "APPROVED"
    assert post["routing_mode"] is None


# ── Difficulty / Corner: OCC stale dispatch rejected ──

def test_occ_dispatch_stale_version_rejected(api):
    """PRD §2.11: "A dispatch attempt carrying a service-request version older than the
    request's current `version` is rejected on stale version, leaving the dispatcher
    free to retry against the current request."

    Design: Corner/cross_cutting_complexity_layers/occ_dispatch_stale_version_rejected
    """
    ctx = setup_approved_request(email="c26@x.com")
    sr, mechanic = ctx["service_request"], ctx["mechanic"]
    stale_version = _sr_version(sr["id"])
    # First dispatch with the captured version, then abort (which bumps SR version).
    jv = get_success_data(api.dispatch(sr["id"], create_dispatch_payload(
        mechanic["id"], stale_version, routing_mode="ON_SITE",
        scheduled_start_utc="2026-04-02T09:00:00Z",
        scheduled_end_utc="2026-04-02T10:00:00Z"), DISPATCHER))
    get_success_data(api.abort(jv["id"], DISPATCHER))

    # The stale_version no longer matches; a dispatch carrying it is rejected.
    res = api.dispatch(sr["id"], create_dispatch_payload(
        mechanic["id"], stale_version, routing_mode="ON_SITE",
        scheduled_start_utc="2026-04-03T09:00:00Z",
        scheduled_end_utc="2026-04-03T10:00:00Z"), DISPATCHER)
    validate_error(res, "ERR_STALE_VERSION", expected_status=412)
    sr_after = validate_success(api.get_service_request(sr["id"], DISPATCHER), 200)
    assert sr_after["status"] == "APPROVED"
