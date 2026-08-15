"""Post-event closeout: reconciliation, captain debriefs, role adjustments
with optimistic concurrency, and the ops-run epoch sweep (PRD §3.9, §3.4).
"""
import pytest

from test_helpers import (
    api_client, ApiErrorId, C, TEST_USERS,
    make_captain_headers,
    validate_success, validate_error, validate_paginated,
    set_clock,
    setup_event_with_shift, setup_published_with_volunteers,
    setup_race_day_with_confirmed, setup_captain_on_shift,
    setup_debrief_open_with_captain, setup_acknowledged_debrief,
    create_debrief, submit_debrief, propose_adjustment,
    register_eligible_volunteer, enroll_and_pass,
    request_signup, approve_signup, create_confirmed_signup,
    create_debrief_report_payload, add_shift,
)

DIRECTOR = TEST_USERS["director_headers"]
COORDINATOR = TEST_USERS["coordinator_headers"]


# ---------------------------------------------------------------------------
# Reconciliation gate (PRD §3.9)
# ---------------------------------------------------------------------------

def test_shift_reconcile_blocked_with_unresolved_confirmed(api):
    """PRD §3.9: "A coordinator reconciles an `IN_PROGRESS` shift once the
    event is `COMPLETED` or `DEBRIEF_OPEN` (`ERR_INVALID_EVENT_STATE`
    otherwise), and only while no signup on the shift remains in `CONFIRMED`
    or `CHECKED_IN` status — unresolved seats reject with
    `ERR_SHIFT_HAS_UNRESOLVED_SIGNUPS`."

    Design: Corner/state_machines/shift_reconcile_blocked_with_unresolved_confirmed
    """
    ctx = setup_race_day_with_confirmed(
        [{"full_name": "V One", "date_of_birth": "2000-01-01"}],
        shift_overrides={"start_at": "2026-10-04T06:00:00Z",
                         "end_at": "2026-10-04T08:00:00Z",
                         "required_headcount": 1})
    # The CONFIRMED volunteer never checks in; the event can still complete
    # because nobody is CHECKED_IN.
    set_clock(C.EVENT_END)
    completed = validate_success(api_client.complete_event(ctx["event"]["id"], DIRECTOR))
    assert completed["status"] == "COMPLETED"
    resp = api_client.reconcile_shift(ctx["shift"]["id"], COORDINATOR)
    validate_error(resp, ApiErrorId.ERR_SHIFT_HAS_UNRESOLVED_SIGNUPS)
    shift = validate_success(api_client.get_shift(ctx["shift"]["id"], COORDINATOR))
    assert shift["status"] == "IN_PROGRESS"


# ---------------------------------------------------------------------------
# Debrief state guards and captain scoping (PRD §3.9)
# ---------------------------------------------------------------------------

def test_debrief_adjustment_state_guards_rejected(api):
    """PRD §3.9: "The author then submits it — `DRAFT` to `SUBMITTED`,
    requiring the event to be `DEBRIEF_OPEN` (`ERR_INVALID_EVENT_STATE`), the
    caller to be the author (`ERR_NOT_RESOURCE_OWNER`), and the report to be
    in `DRAFT` (`ERR_DEBRIEF_INVALID_STATE`)."
    PRD §3.9: "Application is a coordinator action on an `APPROVED`
    adjustment, again gated on the event being `DEBRIEF_OPEN`
    (`ERR_INVALID_EVENT_STATE`) and on the adjustment's state
    (`ERR_ADJUSTMENT_INVALID_STATE`)."

    Design: Corner/errors/debrief_adjustment_state_guards_rejected
    """
    ctx = setup_debrief_open_with_captain()
    debrief = create_debrief(ctx)
    submit_debrief(ctx, debrief["id"])
    double_submit = api_client.submit_debrief_report(
        debrief["id"], make_captain_headers(ctx["captain"]["id"]))
    validate_error(double_submit, ApiErrorId.ERR_DEBRIEF_INVALID_STATE)
    adj = propose_adjustment(ctx, debrief["id"], proposed_credit_weight=2.0)
    apply_proposed = api_client.apply_role_adjustment(
        adj["id"], ctx["role"]["version"], COORDINATOR)
    validate_error(apply_proposed, ApiErrorId.ERR_ADJUSTMENT_INVALID_STATE)


def test_captain_cannot_debrief_other_shift(api):
    """PRD §3.9: "The `author_volunteer_id` must equal `X-User-ID`, and the
    author must hold the captain signup on that shift; otherwise the creation
    is rejected with `ERR_NOT_RESOURCE_OWNER`."

    Design: Corner/rbac/captain_cannot_debrief_other_shift
    """
    ctx = setup_debrief_open_with_captain(
        shift_overrides={"start_at": "2026-10-04T06:00:00Z",
                         "end_at": "2026-10-04T10:00:00Z",
                         "required_headcount": 1})
    # A second shift the captain holds no signup on.
    other = add_shift(ctx["event"]["id"], ctx["role"]["id"], ctx["segment"]["id"],
                      start_at="2026-10-04T10:00:00Z", end_at="2026-10-04T12:00:00Z",
                      required_headcount=1)
    resp = api_client.create_debrief_report(
        create_debrief_report_payload(ctx["event"]["id"], other["id"],
                                      ctx["captain"]["id"],
                                      headcount_actual=0,
                                      role_effectiveness_rating=3),
        make_captain_headers(ctx["captain"]["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER)


# ---------------------------------------------------------------------------
# Adjustment approval gated on the debrief's state (PRD §3.9)
# ---------------------------------------------------------------------------

def _setup_adjustment_with_unacknowledged_debrief(api):
    """DEBRIEF_OPEN; captain-authored debrief SUBMITTED (never acknowledged);
    adjustment PROPOSED citing it (proposed_min_age_years 21)."""
    ctx = setup_debrief_open_with_captain()
    debrief = create_debrief(ctx, rating=4)
    submit_debrief(ctx, debrief["id"])
    adj = propose_adjustment(ctx, debrief["id"], proposed_min_age_years=21)
    return ctx, debrief, adj


def test_adjustment_approve_gated_by_debrief_state(api):
    """PRD §3.9: "The `EventDirector` approves or rejects it — both only from
    `PROPOSED` (`ERR_ADJUSTMENT_INVALID_STATE`) and only while the event
    remains `DEBRIEF_OPEN` (`ERR_INVALID_EVENT_STATE`) — and approval
    additionally requires the cited debrief to be `ACKNOWLEDGED`
    (`ERR_DEBRIEF_NOT_ACKNOWLEDGED`)."

    Design: Difficulty/cross_entity_state_dependency/adjustment_approve_gated_by_debrief_state
    """
    ctx, debrief, adj = _setup_adjustment_with_unacknowledged_debrief(api)
    resp = api_client.approve_role_adjustment(adj["id"], DIRECTOR)
    validate_error(resp, ApiErrorId.ERR_DEBRIEF_NOT_ACKNOWLEDGED)


def test_adjustment_remains_proposed_until_debrief_acknowledged(api):
    """PRD §3.9: "approval additionally requires the cited debrief to be
    `ACKNOWLEDGED` (`ERR_DEBRIEF_NOT_ACKNOWLEDGED`)."
    PRD §3.9: "A coordinator acknowledges a submitted report — `SUBMITTED` to
    terminal `ACKNOWLEDGED`, otherwise `ERR_DEBRIEF_INVALID_STATE`."

    Design: Difficulty/cross_entity_state_dependency/adjustment_approve_gated_by_debrief_state
    """
    ctx, debrief, adj = _setup_adjustment_with_unacknowledged_debrief(api)
    validate_error(api_client.approve_role_adjustment(adj["id"], DIRECTOR),
                   ApiErrorId.ERR_DEBRIEF_NOT_ACKNOWLEDGED)
    after = validate_success(api_client.get_role_adjustment(adj["id"], COORDINATOR))
    assert after["status"] == "PROPOSED", "the rejected approve leaves the adjustment untouched"
    validate_success(api_client.acknowledge_debrief_report(debrief["id"], COORDINATOR))
    approved = validate_success(api_client.approve_role_adjustment(adj["id"], DIRECTOR))
    assert approved["status"] == "APPROVED", \
        "once the cited debrief is ACKNOWLEDGED, the gate is satisfied"


# ---------------------------------------------------------------------------
# Adjustment application: OCC and forward-looking semantics (PRD §2.9, §3.9)
# ---------------------------------------------------------------------------

def test_occ_adjustment_apply_stale_role_rejected(api):
    """PRD §2.9: "Applying an approved role adjustment requires
    `expected_role_version`, holding the client's last observed `version` of
    the target role catalog entry. A mismatch with the entry's current
    `version` is rejected with `ERR_STALE_VERSION` (HTTP 412); since two
    approved adjustments on the same role could both legitimately apply, the
    later one must re-read the role before re-applying."

    Design: Corner/complexity_layers/occ_adjustment_apply_stale_role_rejected
    """
    ctx, debrief = setup_acknowledged_debrief()
    role_version = ctx["role"]["version"]
    adj1 = propose_adjustment(ctx, debrief["id"], proposed_min_age_years=21)
    adj2 = propose_adjustment(ctx, debrief["id"], proposed_credit_weight=2.5)
    validate_success(api_client.approve_role_adjustment(adj1["id"], DIRECTOR))
    validate_success(api_client.approve_role_adjustment(adj2["id"], DIRECTOR))
    applied = validate_success(api_client.apply_role_adjustment(
        adj1["id"], role_version, COORDINATOR))
    assert applied["status"] == "APPLIED"
    role = validate_success(api_client.get_role_catalog_entry(ctx["role"]["id"], COORDINATOR))
    assert role["min_age_years"] == 21
    assert role["version"] == role_version + 1
    stale = api_client.apply_role_adjustment(adj2["id"], role_version, COORDINATOR)
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION)
    adj2_after = validate_success(api_client.get_role_adjustment(adj2["id"], COORDINATOR))
    assert adj2_after["status"] == "APPROVED", "the rejected apply leaves ADJ2 in place"
    role_after = validate_success(api_client.get_role_catalog_entry(ctx["role"]["id"], COORDINATOR))
    assert role_after["credit_weight"] == 1.0, "the stale write must not partially apply"


def test_adjustment_apply_forward_looking_only(api):
    """PRD §3.9: "Applying writes every provided `proposed_*` value onto the
    role catalog entry — a true `proposed_retire` moves the entry to `RETIRED`
    — increments the entry's `version` by one, stamps `applied_at`, and is
    strictly forward-looking: existing signups are not re-validated against
    the new requirements."

    Design: Corner/consistency_model/adjustment_apply_forward_looking_only
    """
    # The captain is 17 on race day against a role whose min_age is 16.
    ctx, debrief = setup_acknowledged_debrief(
        volunteer_overrides={"full_name": "V Cap", "date_of_birth": "2009-10-04",
                             "is_returning": False})
    assert ctx["captain"]["age_years_on_event"] == 17
    adj = propose_adjustment(ctx, debrief["id"], proposed_min_age_years=21)
    validate_success(api_client.approve_role_adjustment(adj["id"], DIRECTOR))
    applied = validate_success(api_client.apply_role_adjustment(
        adj["id"], ctx["role"]["version"], COORDINATOR))
    assert applied["status"] == "APPLIED"
    assert applied["applied_at"] is not None
    role = validate_success(api_client.get_role_catalog_entry(ctx["role"]["id"], COORDINATOR))
    assert role["min_age_years"] == 21
    assert role["version"] == ctx["role"]["version"] + 1
    sg = validate_success(api_client.get_signup(ctx["captain_signup"]["id"], COORDINATOR))
    assert sg["status"] == "COMPLETED", \
        "the existing signup (volunteer now under the new min age) is never re-validated"


# ---------------------------------------------------------------------------
# The epoch sweep (PRD §3.9)
# ---------------------------------------------------------------------------

def test_epoch_sweep_confirm_timeout_and_autolock(api):
    """PRD §3.9: "Second, if the event is still `PUBLISHED` and the clock has
    reached `signup_closes_at`, the sweep auto-locks it exactly as a manual
    lock would, cascading the event's `OPEN` and `FULL` shifts to `LOCKED`.
    Third, the sweep cancels every `APPROVED` signup of the event whose
    `confirm_by_at` deadline has passed, each freed seat running the seat-open
    handling of §3.7."
    PRD §3.9: "the ops-run epoch sweep of a single event, which reports back
    `expired_training_record_ids`, `auto_locked`, and `timed_out_signup_ids`."

    Design: Corner/complexity_layers/epoch_sweep_confirm_timeout_and_autolock
    """
    ctx = setup_published_with_volunteers(
        [{"full_name": "V One", "date_of_birth": "2000-01-01"}])
    sg = request_signup(ctx["volunteers"][0]["id"], ctx["shift"]["id"])
    approve_signup(sg["id"])  # confirm_by_at lands 2026-08-22T00:00:00Z
    set_clock(C.AFTER_SIGNUP_CLOSES)  # 2026-09-28: past the deadline and the window
    sweep = validate_success(api_client.run_epoch_sweep(ctx["event"]["id"], DIRECTOR))
    assert sweep["auto_locked"] is True
    assert sg["id"] in sweep["timed_out_signup_ids"]
    sg_after = validate_success(api_client.get_signup(sg["id"], COORDINATOR))
    assert sg_after["status"] == "CANCELLED", "the confirm timeout cancels the signup"
    event = validate_success(api_client.get_event(ctx["event"]["id"], DIRECTOR))
    assert event["status"] == "LOCKED"
    shift = validate_success(api_client.get_shift(ctx["shift"]["id"], COORDINATOR))
    assert shift["status"] == "LOCKED"
    assert shift["confirmed_count"] == 0


# ---------------------------------------------------------------------------
# Training expiry cascade into waitlist promotion (PRD §3.4, §3.5)
# ---------------------------------------------------------------------------

def _setup_training_expiry_cascade(api):
    """Role MARSHAL gated on SAFETY_BRIEFING; shift 06:00-08:00 headcount 1.
    V1 passed at 2026-08-20 (valid thirty days, lapsing 2026-09-19) and is
    CONFIRMED (shift FULL). V2 (returning) passed at 2026-09-10 (valid until
    2026-10-10) and is WAITLISTED. Clock ends at 2026-09-20."""
    ctx = setup_event_with_shift(
        publish=True,
        role_overrides={"required_training_module": "SAFETY_BRIEFING"},
        shift_overrides={"start_at": "2026-10-04T06:00:00Z",
                         "end_at": "2026-10-04T08:00:00Z",
                         "required_headcount": 1})
    ev = ctx["event"]["id"]
    v1 = register_eligible_volunteer(ev, full_name="V One", date_of_birth="2000-01-01")
    tr1 = enroll_and_pass(ev, v1["id"], "SAFETY_BRIEFING")
    sg1 = create_confirmed_signup(v1["id"], ctx["shift"]["id"])
    set_clock("2026-09-10T00:00:00Z")
    v2 = register_eligible_volunteer(ev, full_name="V Two", date_of_birth="2000-01-02",
                                     is_returning=True)
    tr2 = enroll_and_pass(ev, v2["id"], "SAFETY_BRIEFING")
    sg2 = request_signup(v2["id"], ctx["shift"]["id"])
    assert sg2["status"] == "WAITLISTED"
    set_clock("2026-09-20T00:00:00Z")
    ctx.update({"v1": v1, "v2": v2, "tr1": tr1, "tr2": tr2, "sg1": sg1, "sg2": sg2})
    return ctx


def test_training_expiry_cascade_expires_and_cancels(api):
    """PRD §3.4: "The epoch sweep of §3.9 moves every `PASSED` record whose
    `valid_until` has passed into `EXPIRED`, and the expiry cascades: every
    signup of that volunteer in `APPROVED` or `CONFIRMED` status whose shift's
    role requires exactly the expired module is cancelled, each freed seat
    running the seat-open handling of §3.7."

    Design: Difficulty/transitive_cascade/training_expiry_waitlist_cascade
    """
    ctx = _setup_training_expiry_cascade(api)
    sweep = validate_success(api_client.run_epoch_sweep(ctx["event"]["id"], DIRECTOR))
    assert ctx["tr1"]["id"] in sweep["expired_training_record_ids"]
    tr1 = validate_success(api_client.get_training_record(ctx["tr1"]["id"], COORDINATOR))
    assert tr1["status"] == "EXPIRED", "valid_until 2026-09-19 lapsed by 2026-09-20"
    sg1 = validate_success(api_client.get_signup(ctx["sg1"]["id"], COORDINATOR))
    assert sg1["status"] == "CANCELLED", \
        "the training-gated role lost currency, cancelling the signup"
    tr2 = validate_success(api_client.get_training_record(ctx["tr2"]["id"], COORDINATOR))
    assert tr2["status"] == "PASSED", "valid until 2026-10-10, beyond the sweep instant"


def test_training_expiry_cascade_promotes_waitlist(api):
    """PRD §3.5: "While the event remains `PUBLISHED`, a seat that opens on a
    shift is offered to its waitlist. Eligible candidates are the `WAITLISTED`
    signups on that shift whose volunteer is `ELIGIBLE` and who still pass the
    age, skill, training, and overlap checks at promotion time."
    PRD §3.5: "The single top candidate is promoted to `APPROVED` with
    `origin` set to `WAITLIST_PROMOTION`"

    Design: Difficulty/transitive_cascade/training_expiry_waitlist_cascade
    """
    ctx = _setup_training_expiry_cascade(api)
    validate_success(api_client.run_epoch_sweep(ctx["event"]["id"], DIRECTOR))
    sg2 = validate_success(api_client.get_signup(ctx["sg2"]["id"], COORDINATOR))
    assert sg2["status"] == "APPROVED"
    assert sg2["origin"] == "WAITLIST_PROMOTION"
    shift = validate_success(api_client.get_shift(ctx["shift"]["id"], COORDINATOR))
    assert shift["confirmed_count"] == 1, "the seat is conserved through the cascade"
    assert shift["status"] == "FULL"
