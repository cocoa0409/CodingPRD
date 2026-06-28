"""Cross-entity cascades and waitlist promotion: discharge depth-3 chain, the
cyclic offer/decline/re-offer loop, and the empty-candidate-set boundary.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    TEST_USERS, make_evaluator_headers,
    set_clock, create_child, create_therapist, create_finalized_evaluation,
    create_active_plan, create_authorization, setup_active_care, setup_exhausted_authorization,
    create_child_with_active_plan_and_auth, add_waitlist_entry, book_appointment_ok,
    get_authorization, get_appointment, get_waitlist_entry,
)

ADMIN = TEST_USERS["clinic_admin_headers"]
COORDINATOR = TEST_USERS["scheduling_coordinator_headers"]


# ─── transitive_cascade / discharge_cancels_appt_releases_visit_promotes_waitlist ─

def _setup_discharge_depth3():
    """SLP therapist. Child-X: ACTIVE plan + authorized_visits=1 reserved by one
    SCHEDULED appointment (-> EXHAUSTED). Child-Y: WAITING on the therapist with
    an ACTIVE plan and an authorization with 1 available visit. Returns
    (therapist, x, appt_x, y, wl_y)."""
    set_clock("2026-06-05T12:00:00Z")
    th = create_therapist(discipline="SLP", max_caseload=9, weekly_visit_minutes_cap=600)
    x = create_child_with_active_plan_and_auth(th["id"], discipline="SLP",
                                               severity_score=50, authorized_visits=1,
                                               full_name="Child X")
    ctx_x = {"child": x["child"], "therapist": th, "auth": x["auth"], "plan": x["plan"]}
    appt_x = book_appointment_ok(ctx_x, "2026-06-10T09:00:00Z", "2026-06-10T09:45:00Z")
    y = create_child_with_active_plan_and_auth(th["id"], discipline="SLP",
                                               severity_score=80, authorized_visits=1,
                                               full_name="Child Y")
    wl_y = add_waitlist_entry(y["child"]["id"], th["id"], y["evaluation"]["id"],
                              discipline="SLP", requested_minutes=45)
    return th, x, appt_x, y, wl_y


def test_discharge_cascades_release_and_promotion(api):
    """PRD §3.3: "every one of the plan's `SCHEDULED` appointments is cancelled —
    each releasing its reserved authorization visit and firing waitlist
    promotion". PRD §3.6: "an authorization that was `EXHAUSTED` returns to
    `ACTIVE`".

    Design: Difficulty/transitive_cascade/discharge_cancels_appt_releases_visit_promotes_waitlist_depth3
    """
    th, x, appt_x, y, wl_y = _setup_discharge_depth3()
    assert get_authorization(x["auth"]["id"])["status"] == "EXHAUSTED"
    validate_success(api.discharge_plan_of_care(
        x["plan"]["id"], make_evaluator_headers(th["id"])), 200)

    assert get_appointment(appt_x["id"])["status"] == "CANCELLED"
    auth_x = get_authorization(x["auth"]["id"])
    assert auth_x["reserved_visits"] == 0, auth_x
    assert auth_x["available_visits"] == 1, auth_x
    assert auth_x["status"] == "ACTIVE", auth_x
    assert get_waitlist_entry(wl_y["id"])["status"] == "OFFERED"


def test_discharge_releases_visit_to_active_pool(api):
    """PRD §3.6: "Cancellation releases the held visit: the authorization's
    `reserved_visits` decreases by 1, `available_visits` rises, an authorization
    that was `EXHAUSTED` returns to `ACTIVE`". A second view of the depth-3 chain
    isolating link 1->link 2: the discharged plan's appointment cancellation flips
    its EXHAUSTED authorization back to ACTIVE.

    Design: Difficulty/transitive_cascade/discharge_cancels_appt_releases_visit_promotes_waitlist_depth3
    """
    th, x, appt_x, y, wl_y = _setup_discharge_depth3()
    validate_success(api.discharge_plan_of_care(
        x["plan"]["id"], make_evaluator_headers(th["id"])), 200)
    auth_x = get_authorization(x["auth"]["id"])
    assert auth_x["status"] == "ACTIVE", auth_x
    assert auth_x["available_visits"] == 1, auth_x


# ─── non_linear_state_machine / waitlist_entry_cyclic_offer_decline_reoffer ──

def _setup_two_waiting_children():
    """One SLP therapist. An occupier child with a SCHEDULED appointment; HIGH
    (sev 90) and LOW (sev 30) children both WAITING with ACTIVE plans and
    authorizations with available visits. Returns (th, appt_occ, wl_high, wl_low).
    """
    set_clock("2026-06-05T12:00:00Z")
    th = create_therapist(discipline="SLP", max_caseload=9, weekly_visit_minutes_cap=600)
    occ = create_child_with_active_plan_and_auth(th["id"], discipline="SLP",
                                                 severity_score=50, authorized_visits=3,
                                                 full_name="Occupier")
    ctx_occ = {"child": occ["child"], "therapist": th, "auth": occ["auth"], "plan": occ["plan"]}
    appt_occ = book_appointment_ok(ctx_occ, "2026-06-10T09:00:00Z", "2026-06-10T09:45:00Z")
    high = create_child_with_active_plan_and_auth(th["id"], discipline="SLP",
                                                  severity_score=90, authorized_visits=3,
                                                  full_name="High Need")
    low = create_child_with_active_plan_and_auth(th["id"], discipline="SLP",
                                                 severity_score=30, authorized_visits=3,
                                                 full_name="Low Need")
    wl_high = add_waitlist_entry(high["child"]["id"], th["id"], high["evaluation"]["id"],
                                 discipline="SLP", requested_minutes=45)
    wl_low = add_waitlist_entry(low["child"]["id"], th["id"], low["evaluation"]["id"],
                                discipline="SLP", requested_minutes=45)
    return th, appt_occ, wl_high, wl_low


def test_cancellation_offers_highest_priority_entry(api):
    """PRD §3.8: "Among the eligible candidates the system ranks by `priority_score`
    descending and then, as the tie-breaker, by `created_at` ascending so the
    earliest-waiting entry wins". PRD §3.6: "waitlist promotion runs for that
    therapist ... the highest-priority eligible waiting entry is offered the slot."

    Design: Difficulty/non_linear_state_machine/waitlist_entry_cyclic_offer_decline_reoffer
    """
    th, appt_occ, wl_high, wl_low = _setup_two_waiting_children()
    validate_success(api.cancel_appointment(appt_occ["id"], ADMIN), 200)
    assert get_waitlist_entry(wl_high["id"])["status"] == "OFFERED"
    assert get_waitlist_entry(wl_low["id"])["status"] == "WAITING"


def test_decline_reoffers_next_highest_entry(api):
    """PRD §3.8: "A `ClinicAdmin` or `SchedulingCoordinator` declines an `OFFERED`
    entry (otherwise `ERR_WAITLIST_NOT_OFFERED`), returning it to `WAITING` and
    re-running promotion so the next-highest-priority eligible entry is offered."

    Design: Difficulty/non_linear_state_machine/waitlist_entry_cyclic_offer_decline_reoffer
    """
    th, appt_occ, wl_high, wl_low = _setup_two_waiting_children()
    validate_success(api.cancel_appointment(appt_occ["id"], ADMIN), 200)
    assert get_waitlist_entry(wl_high["id"])["status"] == "OFFERED"
    # Decline the HIGH offer -> it returns to WAITING and LOW is re-offered.
    validate_success(api.decline_waitlist_entry(wl_high["id"], COORDINATOR), 200)
    assert get_waitlist_entry(wl_high["id"])["status"] == "WAITING"
    assert get_waitlist_entry(wl_low["id"])["status"] == "OFFERED"


# ─── boundary_precision_check / empty_waitlist_candidate_set_no_promotion_no_error ─

def test_cancel_with_empty_waitlist_no_promotion(api):
    """PRD §3.8: "If no candidate is eligible, no promotion happens and the slot
    simply remains free; this is not an error." PRD §3.6: "Cancellation releases
    the held visit: the authorization's `reserved_visits` decreases by 1,
    `available_visits` rises".

    Design: Difficulty/boundary_precision_check/empty_waitlist_candidate_set_no_promotion_no_error
    """
    ctx = setup_active_care(clock="2026-06-05T12:00:00Z", discipline="OT", authorized_visits=3)
    appt = book_appointment_ok(ctx, "2026-06-10T09:00:00Z", "2026-06-10T09:45:00Z")
    res = api.cancel_appointment(appt["id"], ADMIN)
    cancelled = validate_success(res, 200)
    assert cancelled["status"] == "CANCELLED"
    auth = get_authorization(ctx["auth"]["id"])
    assert auth["reserved_visits"] == 0, auth
    assert auth["available_visits"] == 3, auth


def test_cancel_with_no_waitlist_entries_succeeds_cleanly(api):
    """PRD §3.8: "If no candidate is eligible, no promotion happens and the slot
    simply remains free; this is not an error." PRD §3.6: "A `ClinicAdmin` or
    `SchedulingCoordinator` cancels a `SCHEDULED` appointment (otherwise
    `ERR_APPOINTMENT_NOT_SCHEDULED`), moving it to `CANCELLED`." With zero waitlist
    entries the cancellation simply returns 200 and the visit is released.

    Design: Difficulty/boundary_precision_check/empty_waitlist_candidate_set_no_promotion_no_error
    """
    ctx = setup_active_care(clock="2026-06-05T12:00:00Z", discipline="SLP", authorized_visits=2)
    appt = book_appointment_ok(ctx, "2026-06-10T09:00:00Z", "2026-06-10T09:45:00Z")
    before = get_authorization(ctx["auth"]["id"])
    assert before["reserved_visits"] == 1
    res = api.cancel_appointment(appt["id"], ADMIN)
    validate_success(res, 200)
    after = get_authorization(ctx["auth"]["id"])
    assert after["available_visits"] == 2, after
    assert after["reserved_visits"] == 0, after
