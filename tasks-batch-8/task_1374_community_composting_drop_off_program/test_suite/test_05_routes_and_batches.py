"""Routes, stops, batches: dispatch preconditions, half-open window overlap,
collect gating, batch-reject cascade."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_and_accept_drop,
    create_contamination_report_payload,
    create_drop_at_site,
    create_partner_payload,
    create_route_payload,
    create_stop_payload,
    get_site_version,
    get_success_data,
    make_processing_partner_headers,
    setup_closed_accepted_batch,
    setup_program_with_operational_site,
    setup_verified_participant_with_grant,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["program_admin_headers"]
OPERATOR = TEST_USERS["route_operator_headers"]
AUDITOR = TEST_USERS["municipal_auditor_headers"]


def _program_site_partner(api, program_overrides=None):
    ids = setup_program_with_operational_site(
        program_overrides=program_overrides)
    partner = validate_success(api.create_partner(
        ids["prog_id"], create_partner_payload(), ADMIN), expected_status=201)
    return ids, partner["id"]


def _planned_route_with_stop(api, prog_id, site_id, partner_id,
                             route_overrides=None):
    route = validate_success(api.create_route(
        prog_id, create_route_payload(partner_id, **(route_overrides or {})),
        OPERATOR), expected_status=201)
    stop = validate_success(api.create_stop(
        prog_id, route["id"],
        create_stop_payload(site_id, route["version"]), OPERATOR),
        expected_status=201)
    return route, stop


# ---------------------------------------------------------------------------
# Difficulty: boundary_precision_check /
#             route_dispatch_zero_stops_empty_set_boundary (2 tests)
# ---------------------------------------------------------------------------

def test_dispatch_with_zero_stops_rejected(api):
    """PRD §3.5: "Dispatching a route moves it from `PLANNED` to `DISPATCHED`
    and enforces four preconditions: at least one stop must be in `SCHEDULED`
    status, failing with `ERR_ROUTE_HAS_NO_STOPS` (HTTP 409)"

    Design: Difficulty/boundary_precision_check/route_dispatch_zero_stops_empty_set_boundary
    """
    ids, partner_id = _program_site_partner(api)
    route = validate_success(api.create_route(
        ids["prog_id"], create_route_payload(partner_id), OPERATOR),
        expected_status=201)

    resp = api.dispatch_route(ids["prog_id"], route["id"], OPERATOR)
    validate_error(resp, ApiErrorId.ERR_ROUTE_HAS_NO_STOPS)


def test_dispatch_with_exactly_one_stop_succeeds(api):
    """PRD §3.5: "Dispatching a route moves it from `PLANNED` to `DISPATCHED`
    and enforces four preconditions: at least one stop must be in `SCHEDULED`
    status, failing with `ERR_ROUTE_HAS_NO_STOPS` (HTTP 409)"

    Design: Difficulty/boundary_precision_check/route_dispatch_zero_stops_empty_set_boundary
    """
    ids, partner_id = _program_site_partner(api)
    route, _stop = _planned_route_with_stop(
        api, ids["prog_id"], ids["site_id"], partner_id)

    resp = api.dispatch_route(ids["prog_id"], route["id"], OPERATOR)
    dispatched = validate_success(resp)
    assert dispatched["status"] == "DISPATCHED"


# ---------------------------------------------------------------------------
# Difficulty: resource_temporal_overlap / route_partner_half_open_overlap (2 tests)
# ---------------------------------------------------------------------------

def _setup_three_routes(api):
    """R1 [08:00,12:00) DISPATCHED; R2 [12:00,16:00) adjacent; R3 [11:00,13:00)
    overlapping. Returns (prog_id, r2, r3)."""
    ids, partner_id = _program_site_partner(api)
    prog_id, site_id = ids["prog_id"], ids["site_id"]

    r1, _ = _planned_route_with_stop(api, prog_id, site_id, partner_id)
    get_success_data(api.dispatch_route(prog_id, r1["id"], OPERATOR))

    r2, _ = _planned_route_with_stop(
        api, prog_id, site_id, partner_id,
        route_overrides={"route_code": "R2",
                         "scheduled_start": "2026-08-02T12:00:00Z",
                         "scheduled_end": "2026-08-02T16:00:00Z"})
    r3, _ = _planned_route_with_stop(
        api, prog_id, site_id, partner_id,
        route_overrides={"route_code": "R3",
                         "scheduled_start": "2026-08-02T11:00:00Z",
                         "scheduled_end": "2026-08-02T13:00:00Z"})
    return prog_id, r2, r3


def test_adjacent_route_window_dispatches_successfully(api):
    """PRD §3.5: "Overlap follows the half-open rule of §2.6: windows conflict
    only when each route's start falls strictly before the other's end, so a
    route departing exactly when another returns — one's `scheduled_start`
    equal to the other's `scheduled_end` — is permitted."

    Design: Difficulty/resource_temporal_overlap/route_partner_half_open_overlap
    """
    prog_id, r2, _r3 = _setup_three_routes(api)

    resp = api.dispatch_route(prog_id, r2["id"], OPERATOR)
    dispatched = validate_success(resp)
    assert dispatched["status"] == "DISPATCHED"


def test_overlapping_route_window_rejected_double_booked(api):
    """PRD §3.5: "no other `DISPATCHED` route with the same partner may have a
    time window overlapping this one, failing with
    `ERR_PARTNER_DOUBLE_BOOKED` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/route_partner_half_open_overlap
    """
    prog_id, _r2, r3 = _setup_three_routes(api)

    resp = api.dispatch_route(prog_id, r3["id"], OPERATOR)
    validate_error(resp, ApiErrorId.ERR_PARTNER_DOUBLE_BOOKED)


# ---------------------------------------------------------------------------
# Corner: state_machines/route_stop_collect_requires_dispatched_route (1 test)
# ---------------------------------------------------------------------------

def test_collect_on_planned_route_rejected(api):
    """PRD §3.5: "Collecting a stop requires the parent route to be
    `DISPATCHED` — otherwise `ERR_ROUTE_NOT_DISPATCHED` (HTTP 409)"

    Design: Corner/state_machines/route_stop_collect_requires_dispatched_route
    """
    ids, partner_id = _program_site_partner(api)
    route, stop = _planned_route_with_stop(
        api, ids["prog_id"], ids["site_id"], partner_id)

    resp = api.collect_stop(ids["prog_id"], route["id"], stop["id"],
                            {"actual_pickup_kg": 10.00}, OPERATOR)
    validate_error(resp, ApiErrorId.ERR_ROUTE_NOT_DISPATCHED)


# ---------------------------------------------------------------------------
# Difficulty: transitive_cascade / batch_reject_cascade_depth3 (2 tests)
# ---------------------------------------------------------------------------

def _setup_batch_reject_scenario(api):
    """Program with posture_contam_threshold=1; one ACCEPTED drop (10 credits
    provisionally granted); route collected 10.00 kg; batch OPEN."""
    ids = setup_program_with_operational_site(
        program_overrides={"posture_contam_threshold": 1})
    prog_id, site_id, mat_id = ids["prog_id"], ids["site_id"], ids["mat_id"]
    part = setup_verified_participant_with_grant(prog_id, site_id)

    drop = create_and_accept_drop(prog_id, site_id, part["part_id"],
                                  part["grant_id"], mat_id,
                                  gross_weight_kg=10.00, contamination_kg=0.00)

    partner = validate_success(api.create_partner(
        prog_id, create_partner_payload(), ADMIN), expected_status=201)
    partner_id = partner["id"]
    route, stop = _planned_route_with_stop(api, prog_id, site_id, partner_id)
    get_success_data(api.dispatch_route(prog_id, route["id"], OPERATOR))
    get_success_data(api.collect_stop(prog_id, route["id"], stop["id"],
                                      {"actual_pickup_kg": 10.00}, OPERATOR))
    get_success_data(api.complete_route(prog_id, route["id"], OPERATOR))

    batches, _meta = validate_paginated(api.list_batches(
        prog_id, partner_id, ADMIN))
    batch_id = batches[0]["id"]
    return ids, part, drop, partner_id, batch_id


def test_batch_reject_flags_drops_and_reverses_credits(api):
    """PRD §3.5: "When `contamination_pct` is at or above the threshold, the
    batch instead closes as `CLOSED_REJECTED`: `finished_compost_kg` is 0,
    `closed_at` is stamped, and every drop linked to stops on the batch's
    route has its `verification_state` moved to `FLAGGED_CONTAMINATED` with a
    new `OPEN` `ContaminationReport` of severity `MAJOR`, its `drop_event_id`
    set, auto-created per drop; provisional credits are reversed."

    Design: Difficulty/transitive_cascade/batch_reject_cascade_depth3
    """
    ids, part, drop, partner_id, batch_id = _setup_batch_reject_scenario(api)
    prog_id, site_id = ids["prog_id"], ids["site_id"]

    # 3.00/10.00 = 30.00% >= 25.0% threshold -> CLOSED_REJECTED
    batch = validate_success(api.close_batch(
        prog_id, partner_id, batch_id, {"measured_contamination_kg": 3.00},
        make_processing_partner_headers(partner_id)))
    assert batch["status"] == "CLOSED_REJECTED"
    assert batch["finished_compost_kg"] == pytest.approx(0)

    got_drop = validate_success(api.get_drop(prog_id, site_id, drop["id"], ADMIN))
    assert got_drop["verification_state"] == "FLAGGED_CONTAMINATED"

    reports, _meta = validate_paginated(api.list_contamination_reports(
        prog_id, site_id, ADMIN))
    assert len(reports) >= 1
    auto = [r for r in reports if r.get("drop_event_id") == drop["id"]]
    assert auto, "an OPEN MAJOR report linked to the drop must be auto-created"
    assert auto[0]["status"] == "OPEN"
    assert auto[0]["severity"] == "MAJOR"

    participant = validate_success(api.get_participant(
        prog_id, part["part_id"], ADMIN))
    assert participant["bucket_credit_balance"] == 0, (
        f"10 provisional credits must be reversed, got "
        f"{participant['bucket_credit_balance']}")


def test_batch_reject_recomputes_site_posture_to_watch(api):
    """PRD §3.5: "every drop linked to stops on the batch's route has its
    `verification_state` moved to `FLAGGED_CONTAMINATED` with a new `OPEN`
    `ContaminationReport` of severity `MAJOR`, its `drop_event_id` set,
    auto-created per drop; provisional credits are reversed."
    PRD §2.7: "the count of open contamination reports at the site is at least
    the program's `posture_contam_threshold`"

    Design: Difficulty/transitive_cascade/batch_reject_cascade_depth3
    """
    ids, part, drop, partner_id, batch_id = _setup_batch_reject_scenario(api)
    prog_id, site_id = ids["prog_id"], ids["site_id"]

    validate_success(api.close_batch(
        prog_id, partner_id, batch_id, {"measured_contamination_kg": 3.00},
        make_processing_partner_headers(partner_id)))

    site = validate_success(api.get_site(prog_id, site_id, ADMIN))
    assert site["posture"] == "WATCH", (
        f"one OPEN MAJOR report with posture_contam_threshold=1 must give "
        f"WATCH, got {site['posture']}")
