"""Cancellation fee tiers, the 24h boundary, and the late-cancel trust cascade.

Translates difficulty queue (combinatorial_formula cancellation, boundary_precision_check
24h, transitive_cascade late-cancel depth3, compensating_invariant active_booking_count)
and corner queue (state_machines.cancel_in_progress).
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    create_cancel_payload,
    TEST_USERS, make_client_headers, make_tasker_headers,
    setup_catalog, create_offered_booking, create_claimed_booking,
    create_in_progress_booking, claim_booking,
)

DISP = TEST_USERS["dispatcher_headers"]
TSO = TEST_USERS["trust_safety_headers"]


def test_cancellation_late_tier_at_three_hours(api):
    """PRD §3.6: "at least 2 hours but fewer than 24 is the `LATE` tier at twenty-five percent".
    PRD §3.6: "The fee is that tier's percentage applied to the booking's pinned
    estimated_labor_cents (the labor estimate, not the total), truncated down to whole cents."

    Design: Difficulty/combinatorial_formula/cancellation_fee_tier_branch_selection_mode_a
    """
    ctx = setup_catalog(
        clock="2026-06-25T08:00:00Z",
        category_overrides={"name": "Cancel Test", "default_hourly_rate_cents": 4000,
                            "default_duration_minutes": 60, "requires_vetting": False},
    )
    cl = ctx["client"]["id"]
    # 3 hours ahead of the 08:00 clock -> LATE tier.
    bk = create_offered_booking(cl, ctx["category"]["id"], "2026-06-25T11:00:00Z",
                                estimated_hours=2.0)
    assert bk["estimated_labor_cents"] == 8000

    cancelled = validate_success(api.cancel_booking(
        bk["id"], create_cancel_payload("CLIENT"), make_client_headers(cl)), 200)
    assert cancelled["status"] == "CANCELLED"

    c = validate_success(api.get_cancellation(bk["id"], DISP), 200)[0]
    assert c["fee_tier"] == "LATE"
    assert c["cancellation_fee_cents"] == 2000


def test_cancellation_24h_boundary_is_free(api):
    """PRD §3.6: "24 or more hours before start is the `FREE` tier with a zero percentage".

    Design: Difficulty/boundary_precision_check/cancellation_24h_boundary_free_vs_just_under_late
    """
    ctx = setup_catalog(
        clock="2026-06-25T10:00:00Z",
        category_overrides={"name": "Boundary Cat", "default_hourly_rate_cents": 4000,
                            "default_duration_minutes": 60, "requires_vetting": False},
    )
    cl = ctx["client"]["id"]
    # Exactly 24h ahead -> FREE (>= boundary, inclusive).
    bk = create_offered_booking(cl, ctx["category"]["id"], "2026-06-26T10:00:00Z",
                                estimated_hours=2.0)

    validate_success(api.cancel_booking(
        bk["id"], create_cancel_payload("CLIENT"), make_client_headers(cl)), 200)
    c = validate_success(api.get_cancellation(bk["id"], DISP), 200)[0]
    assert c["fee_tier"] == "FREE"
    assert c["cancellation_fee_cents"] == 0


def test_cancellation_just_under_24h_is_late(api):
    """PRD §3.6: "at least 2 hours but fewer than 24 is the `LATE` tier at twenty-five percent".

    Design: Difficulty/boundary_precision_check/cancellation_24h_boundary_free_vs_just_under_late
    """
    ctx = setup_catalog(
        clock="2026-06-25T10:01:00Z",
        category_overrides={"name": "Boundary Cat 2", "default_hourly_rate_cents": 4000,
                            "default_duration_minutes": 60, "requires_vetting": False},
    )
    cl = ctx["client"]["id"]
    # 23h59m ahead -> LATE; est_labor = floor(4000*2.0) = 8000 -> fee floor(8000*0.25) = 2000.
    bk = create_offered_booking(cl, ctx["category"]["id"], "2026-06-26T10:00:00Z",
                                estimated_hours=2.0)
    validate_success(api.cancel_booking(
        bk["id"], create_cancel_payload("CLIENT"), make_client_headers(cl)), 200)
    c = validate_success(api.get_cancellation(bk["id"], DISP), 200)[0]
    assert c["fee_tier"] == "LATE"
    assert c["cancellation_fee_cents"] == 2000


def test_tasker_late_cancel_cascades_to_incident_and_score(api):
    """PRD §3.6: "when the cancellation is initiated by the tasker and lands in the `LAST_MINUTE`
    tier, the system files a trust incident of `MEDIUM` severity against that tasker, which in
    turn recomputes the tasker's `trust_score` and re-evaluates the trust gate (§3.7)."
    PRD §3.6: "anything under 2 hours is the `LAST_MINUTE` tier at fifty percent."
    PRD §3.7: "carrying `penalty_points` of 5, 15, and 35 respectively while the incident counts against the tasker."

    Design: Difficulty/transitive_cascade/tasker_late_cancel_cascades_to_incident_score_status_depth3
    """
    ctx = setup_catalog(
        clock="2026-06-25T08:00:00Z",
        category_overrides={"name": "Late Cancel Cat", "default_hourly_rate_cents": 4000,
                            "default_duration_minutes": 60, "requires_vetting": False},
        tasker_overrides={"full_name": "Nate NoShow", "hourly_rate_cents": 4000},
        window=("2026-06-25T08:30:00Z", "2026-06-25T12:00:00Z"),
    )
    cl, tk = ctx["client"]["id"], ctx["tasker"]["id"]
    # SAME_DAY booking 1h ahead -> LAST_MINUTE on cancel.
    bk = create_claimed_booking(cl, ctx["category"]["id"], tk, "2026-06-25T09:00:00Z",
                                dispatch_mode="SAME_DAY", estimated_hours=1.0)

    validate_success(api.cancel_booking(
        bk["id"], create_cancel_payload("TASKER"), make_tasker_headers(tk)), 200)

    c = validate_success(api.get_cancellation(bk["id"], DISP), 200)[0]
    assert c["fee_tier"] == "LAST_MINUTE"
    assert c["cancellation_fee_cents"] == 2000

    incidents = validate_success(api.list_incidents(TSO, params={"tasker_id": tk}), 200)
    medium_open = [i for i in incidents if i["severity"] == "MEDIUM" and i["status"] == "OPEN"]
    assert len(medium_open) == 1

    tasker = validate_success(api.get_tasker(tk, DISP), 200)
    assert tasker["trust_score"] == 85
    assert tasker["status"] == "ACTIVE"


def test_claim_then_cancel_conserves_active_booking_count(api):
    """PRD §3.3: "the tasker's active_booking_count is recomputed upward to reflect the newly
    held job."
    PRD §3.6: "If a tasker was assigned to the cancelled booking, that tasker's
    active_booking_count is recomputed downward and the tasker's version is incremented by one."
    PRD §3.6: "24 or more hours before start is the `FREE` tier with a zero percentage".

    Design: Difficulty/compensating_invariant/claim_then_cancel_conserves_tasker_active_booking_count
    """
    ctx = setup_catalog(
        clock="2026-06-25T08:00:00Z",
        category_overrides={"name": "Conserve Cat", "default_hourly_rate_cents": 4000,
                            "default_duration_minutes": 60, "requires_vetting": False},
        tasker_overrides={"full_name": "Connor Conserve", "hourly_rate_cents": 4000},
        window=("2026-06-26T09:00:00Z", "2026-06-26T14:00:00Z"),
    )
    cl, tk = ctx["client"]["id"], ctx["tasker"]["id"]
    bk = create_claimed_booking(cl, ctx["category"]["id"], tk, "2026-06-26T10:00:00Z",
                                estimated_hours=1.0)

    after_claim = validate_success(api.get_tasker(tk, DISP), 200)
    assert after_claim["active_booking_count"] == 1

    validate_success(api.cancel_booking(
        bk["id"], create_cancel_payload("CLIENT"), make_client_headers(cl)), 200)

    after_cancel = validate_success(api.get_tasker(tk, DISP), 200)
    assert after_cancel["active_booking_count"] == 0

    c = validate_success(api.get_cancellation(bk["id"], DISP), 200)[0]
    assert c["fee_tier"] == "FREE"


def test_cancel_in_progress_booking_rejected(api):
    """PRD §3.3: "in particular, a booking in IN_PROGRESS cannot be cancelled and must run
    through to completion."
    PRD §3.6: "an IN_PROGRESS booking cannot be cancelled at all; an illegal cancellation is
    rejected with ERR_BOOKING_INVALID_STATE."

    Design: Corner/state_machines/cancel_in_progress_booking_rejected
    """
    ctx = setup_catalog(
        clock="2026-06-25T08:00:00Z",
        category_overrides={"name": "InProg Cat", "default_hourly_rate_cents": 4000,
                            "default_duration_minutes": 60, "requires_vetting": False},
        tasker_overrides={"full_name": "InProg Tasker", "hourly_rate_cents": 4000},
        window=("2026-06-25T09:00:00Z", "2026-06-25T14:00:00Z"),
    )
    cl, tk = ctx["client"]["id"], ctx["tasker"]["id"]
    bk = create_in_progress_booking(cl, ctx["category"]["id"], tk, "2026-06-25T10:00:00Z",
                                    estimated_hours=1.0)

    res = api.cancel_booking(bk["id"], create_cancel_payload("CLIENT"), make_client_headers(cl))
    validate_error(res, "ERR_BOOKING_INVALID_STATE")

    after = validate_success(api.get_booking(bk["id"], DISP), 200)
    assert after["status"] == "IN_PROGRESS"
