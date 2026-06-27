"""Trust score, the status gate, incident adjudication, and review moderation.

Translates difficulty queue (dual_variant trust_score, non_linear trust_gate cycle,
transitive_cascade incident-dismiss depth2, compensating_invariant trust_score) and
corner queue (calculations.avg_rating, state_machines.review hide/restore cycle, errors
duplicate/not-completed, entities.review rating range).
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    create_review_payload, create_incident_payload, create_complete_payload,
    TEST_USERS, make_client_headers, make_tasker_headers,
    setup_catalog, create_completed_booking, create_offered_booking,
    setup_completed_and_reviewed, file_incident,
)

DISP = TEST_USERS["dispatcher_headers"]
TSO = TEST_USERS["trust_safety_headers"]


def test_trust_score_counts_open_excludes_dismissed(api):
    """PRD §3.7: "The tasker's incident_penalty_total is the sum of penalty_points across that
    tasker's incidents whose status is OPEN or UPHELD; dismissed incidents are excluded."
    PRD §3.7: "The trust_score is 100 minus that penalty total, floored at 0 so it never goes
    below zero."
    PRD §3.7: "a score from 40 through 69 inclusive sets the tasker `RESTRICTED`; a score of 70
    or more sets the tasker `ACTIVE`."

    Design: Difficulty/dual_variant_calc/trust_score_penalty_included_vs_dismissed_excluded_on_tasker
    """
    get_success_data(api.set_clock("2026-06-25T08:00:00Z", TSO))
    tk = get_success_data(api.create_tasker({"full_name": "Ray Risk", "hourly_rate_cents": 5000}, DISP))
    inc = file_incident(tk["id"], severity="HIGH")

    open_view = validate_success(api.get_tasker(tk["id"], DISP), 200)
    assert open_view["trust_score"] == 65
    assert open_view["status"] == "RESTRICTED"

    get_success_data(api.dismiss_incident(inc["id"], TSO))

    dismissed_view = validate_success(api.get_tasker(tk["id"], DISP), 200)
    assert dismissed_view["trust_score"] == 100
    assert dismissed_view["status"] == "ACTIVE"

    inc_after = validate_success(api.get_incident(inc["id"], TSO), 200)
    assert inc_after["penalty_points"] == 0


def test_trust_gate_cycles_active_suspended_active(api):
    """PRD §3.7: "a score below 40 sets the tasker SUSPENDED".
    PRD §3.7: "Because dismissing an incident raises the score, it can bubble a tasker back
    upward — from SUSPENDED to RESTRICTED to ACTIVE — as the score crosses each boundary."

    Design: Difficulty/non_linear_state_machine/tasker_trust_gate_cycles_active_restricted_suspended
    """
    get_success_data(api.set_clock("2026-06-25T08:00:00Z", TSO))
    tk = get_success_data(api.create_tasker({"full_name": "Sam Suspend", "hourly_rate_cents": 5000}, DISP))
    inc1 = file_incident(tk["id"], severity="HIGH")
    inc2 = file_incident(tk["id"], severity="HIGH")

    suspended = validate_success(api.get_tasker(tk["id"], DISP), 200)
    assert suspended["trust_score"] == 30
    assert suspended["status"] == "SUSPENDED"

    get_success_data(api.dismiss_incident(inc1["id"], TSO))
    get_success_data(api.dismiss_incident(inc2["id"], TSO))

    restored = validate_success(api.get_tasker(tk["id"], DISP), 200)
    assert restored["trust_score"] == 100
    assert restored["status"] == "ACTIVE"


def test_incident_dismiss_cascades_score_then_status(api):
    """PRD §3.7: "dismiss it from OPEN (or on a granted appeal from UPHELD), moving it to
    DISMISSED and setting its penalty_points to zero so the penalty is removed."
    PRD §3.7: "a score from 40 through 69 inclusive sets the tasker `RESTRICTED`; a score of 70
    or more sets the tasker `ACTIVE`."

    Design: Difficulty/transitive_cascade/incident_dismiss_cascades_to_score_then_status_depth2
    """
    get_success_data(api.set_clock("2026-06-25T08:00:00Z", TSO))
    tk = get_success_data(api.create_tasker({"full_name": "Rita Restricted", "hourly_rate_cents": 5000}, DISP))
    inc = file_incident(tk["id"], severity="HIGH")

    before = validate_success(api.get_tasker(tk["id"], DISP), 200)
    assert before["status"] == "RESTRICTED"
    assert before["trust_score"] == 65

    get_success_data(api.dismiss_incident(inc["id"], TSO))

    after = validate_success(api.get_tasker(tk["id"], DISP), 200)
    assert after["trust_score"] == 100
    assert after["status"] == "ACTIVE"


def test_file_then_dismiss_conserves_trust_score(api):
    """PRD §3.7: "carrying `penalty_points` of 5, 15, and 35 respectively while the incident
    counts against the tasker."
    PRD §3.7: "moving it to DISMISSED and setting its penalty_points to zero so the penalty is
    removed."

    Design: Difficulty/compensating_invariant/file_then_dismiss_incident_conserves_tasker_trust_score
    """
    get_success_data(api.set_clock("2026-06-25T08:00:00Z", TSO))
    tk = get_success_data(api.create_tasker({"full_name": "Tina Trust", "hourly_rate_cents": 5000}, DISP))
    inc = file_incident(tk["id"], severity="MEDIUM")

    after_file = validate_success(api.get_tasker(tk["id"], DISP), 200)
    assert after_file["trust_score"] == 85
    assert after_file["status"] == "ACTIVE"

    get_success_data(api.dismiss_incident(inc["id"], TSO))

    after_dismiss = validate_success(api.get_tasker(tk["id"], DISP), 200)
    assert after_dismiss["trust_score"] == 100
    assert after_dismiss["status"] == "ACTIVE"


def test_avg_rating_two_reviews_round_half_up(api):
    """PRD §3.7: "the avg_rating is the mean of the rating_value over those published reviews,
    expressed to two decimal places using round-half-up, and reported as 0.0 when the tasker
    has no published reviews."

    Design: Corner/calculations/avg_rating_two_reviews_round_half_up
    """
    ctx = setup_catalog(
        clock="2026-06-25T08:00:00Z",
        category_overrides={"name": "TwoRev Cat", "default_hourly_rate_cents": 4000,
                            "default_duration_minutes": 60, "requires_vetting": False},
        tasker_overrides={"full_name": "TwoRev Tasker", "hourly_rate_cents": 4000},
        window=("2026-06-25T09:00:00Z", "2026-06-25T18:00:00Z"),
    )
    cl, tk = ctx["client"]["id"], ctx["tasker"]["id"]
    bk1 = create_completed_booking(cl, ctx["category"]["id"], tk, "2026-06-25T10:00:00Z",
                                   estimated_hours=1.0)
    get_success_data(api.create_review(create_review_payload(bk1["id"], 5), make_client_headers(cl)))

    bk2 = create_completed_booking(cl, ctx["category"]["id"], tk, "2026-06-25T13:00:00Z",
                                   estimated_hours=1.0)
    get_success_data(api.create_review(create_review_payload(bk2["id"], 4), make_client_headers(cl)))

    tasker = validate_success(api.get_tasker(tk, DISP), 200)
    assert tasker["rating_count"] == 2
    assert tasker["avg_rating"] == 4.50


def test_review_hide_then_restore_recomputes_avg(api):
    """PRD §3.7: "Hiding or removing a review that was published decrements the count and
    recomputes the average; restoring a hidden review increments the count and recomputes the
    average."
    PRD §3.7: "reported as 0.0 when the tasker has no published reviews."

    Design: Corner/state_machines/review_hide_then_restore_cycle_recomputes_avg
    """
    scn = setup_completed_and_reviewed(rating_value=5)
    tk = scn["tasker"]["id"]
    rv = scn["review"]["id"]

    get_success_data(api.hide_review(rv, TSO))
    hidden = validate_success(api.get_tasker(tk, DISP), 200)
    assert hidden["avg_rating"] == 0.0
    assert hidden["rating_count"] == 0

    get_success_data(api.restore_review(rv, TSO))
    restored = validate_success(api.get_tasker(tk, DISP), 200)
    assert restored["avg_rating"] == 5.0
    assert restored["rating_count"] == 1


def test_review_rating_out_of_range_rejected(api):
    """PRD §3.7: "a rating_value from 1 to 5 inclusive".
    PRD §2.9: "field-domain validation — enum membership, numeric ranges, and the like —
    failing with ERR_INVALID_REQUEST."

    Design: Corner/entities/review_rating_out_of_range_returns_invalid_request
    """
    scn = setup_completed_and_reviewed(rating_value=5)
    # The completed booking already has a review; create a second completed booking to review.
    ctx_cl = scn["client"]["id"]
    # Re-use a fresh completed booking on the same tasker.
    bk = create_completed_booking(ctx_cl, scn["category"]["id"], scn["tasker"]["id"],
                                  "2026-06-25T12:00:00Z", estimated_hours=1.0)
    res = api.create_review(create_review_payload(bk["id"], 6), make_client_headers(ctx_cl))
    validate_error(res, "ERR_INVALID_REQUEST")


def test_duplicate_review_rejected(api):
    """PRD §3.7: "only one review may exist per booking, a second attempt failing with
    ERR_DUPLICATE_REVIEW."

    Design: Corner/errors/duplicate_review_returns_conflict
    """
    scn = setup_completed_and_reviewed(rating_value=5)
    res = api.create_review(create_review_payload(scn["booking"]["id"], 3),
                            make_client_headers(scn["client"]["id"]))
    validate_error(res, "ERR_DUPLICATE_REVIEW")


def test_review_uncompleted_booking_rejected(api):
    """PRD §3.7: "The review may only reference a COMPLETED booking — otherwise
    ERR_BOOKING_NOT_COMPLETED".

    Design: Corner/errors/review_uncompleted_booking_returns_not_completed
    """
    ctx = setup_catalog(
        clock="2026-06-25T08:00:00Z",
        category_overrides={"name": "NotComp Cat", "default_hourly_rate_cents": 4000,
                            "default_duration_minutes": 60, "requires_vetting": False},
    )
    cl = ctx["client"]["id"]
    bk = create_offered_booking(cl, ctx["category"]["id"], "2026-06-26T10:00:00Z",
                                estimated_hours=1.0)
    res = api.create_review(create_review_payload(bk["id"], 4), make_client_headers(cl))
    validate_error(res, "ERR_BOOKING_NOT_COMPLETED")
