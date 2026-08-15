"""Routes: performances, score sheets, deductions, appeals, bids, sessions,
ticket orders, warm-up assignments."""
from datetime import timedelta
from decimal import Decimal

from flask import g, request

import calc
import errors
from bidding import (division_complete, initial_allocation, reevaluate,
                     reoffer_slot)
from bp import bp
from envelope import ok, ok_list
from helpers import (body, get_or_404, opt_int, own_team, req_enum, req_int,
                     req_str, require_roles, req_datetime_field)
from store import by_created, db, now, set_fields, stamp, touch

DEDUCTION_RATES = {
    "SAFETY": "safety_deduction_points",
    "TIME": "time_deduction_per_second",
    "BOUNDARY": "boundary_deduction_points",
}


def _perf_or_404(performance_id):
    return get_or_404(db.performances, performance_id, "Performance")


def _perf_context(perf):
    division = db.divisions.get(perf["division_id"])
    team = db.teams.get(perf["team_id"])
    event = db.events.get(division["event_id"]) if division else None
    return division, team, event


def _create_deduction(perf, division, dtype, quantity, skill_tier, source,
                      applier_id):
    rate = division[DEDUCTION_RATES[dtype]]
    rec = stamp({
        "performance_id": perf["id"],
        "type": dtype,
        "quantity": quantity,
        "skill_tier": skill_tier,
        "rate_applied": rate,
        "points": calc.deduction_points(quantity, rate),
        "source": source,
        "applied_by_judge_id": applier_id,
        "status": "APPLIED",
    })
    db.deductions[rec["id"]] = rec
    calc.recompute_provisional(perf)
    return rec


# ---------------------------------------------------------------------------
# Performances
# ---------------------------------------------------------------------------

@bp.get("/api/performances/<performance_id>")
@require_roles("EventDirector", "TeamCoach", "Judge", "HeadJudge", "SafetyJudge")
def get_performance(performance_id):
    return ok(_perf_or_404(performance_id))


@bp.post("/api/performances/<performance_id>/mark-performed")
@require_roles("SafetyJudge")
def mark_performed(performance_id):
    perf = _perf_or_404(performance_id)
    b = body()
    duration = req_int(b, "actual_duration_seconds", lo=0)
    boundary_violations = opt_int(b, "boundary_violations", 0, lo=0)
    division, team, event = _perf_context(perf)
    if event is not None and event["status"] != "LIVE":
        raise errors.conflict("ERR_EVENT_NOT_LIVE",
                              "mark-performed requires the event to be LIVE")
    if team is not None and team["reg_status"] != "CHECKED_IN":
        raise errors.conflict("ERR_TEAM_NOT_CHECKED_IN",
                              "mark-performed requires the team CHECKED_IN")
    if perf["status"] != "SCHEDULED":
        raise errors.conflict(
            "ERR_INVALID_STATE",
            f"mark-performed requires status SCHEDULED, got {perf['status']}")
    set_fields(perf, status="PERFORMED", actual_duration_seconds=duration,
               boundary_violations=boundary_violations)
    if division is not None:
        over = duration - division["routine_time_limit_seconds"]
        if over > 0:
            _create_deduction(perf, division, "TIME", over, None, "SYSTEM", None)
        if boundary_violations > 0:
            _create_deduction(perf, division, "BOUNDARY", boundary_violations,
                              None, "SYSTEM", None)
    calc.recompute_provisional(perf)
    return ok(perf)


@bp.post("/api/performances/<performance_id>/confirm-official")
@require_roles("HeadJudge")
def confirm_official(performance_id):
    perf = _perf_or_404(performance_id)
    if perf["status"] == "SCHEDULED":
        raise errors.conflict("ERR_PERFORMANCE_NOT_PERFORMED",
                              "Performance has not been performed yet")
    if perf["status"] in ("OFFICIAL", "EXCLUDED", "CANCELLED"):
        raise errors.conflict(
            "ERR_PERFORMANCE_INVALID_STATE",
            f"confirm-official not allowed from {perf['status']}")
    if perf["status"] == "PERFORMED":
        raise errors.unprocessable("ERR_QUORUM_NOT_MET",
                                   "Panel quorum is incomplete")
    # SCORED
    for d in db.deductions.values():
        if d["performance_id"] == perf["id"] and d["status"] == "UNDER_APPEAL":
            raise errors.unprocessable(
                "ERR_PENDING_APPEALS",
                "A deduction of this performance is UNDER_APPEAL")
    division, team, event = _perf_context(perf)
    official = calc.final_score(perf["id"], "OFFICIAL")
    # Single mutation event: status + official_score (+1 version).
    set_fields(perf, status="OFFICIAL", official_score=official)
    calc.recompute_ranking(perf["division_id"])
    for s in db.score_sheets.values():
        if s["performance_id"] == perf["id"] and s["status"] == "SUBMITTED":
            set_fields(s, status="LOCKED")
    if team is not None and team["reg_status"] == "CHECKED_IN":
        set_fields(team, reg_status="COMPETED")
    if division is not None and division_complete(division):
        initial_allocation(division)
    return ok(perf)


# ---------------------------------------------------------------------------
# Score sheets
# ---------------------------------------------------------------------------

@bp.post("/api/performances/<performance_id>/score-sheets")
@require_roles("Judge")
def create_score_sheet(performance_id):
    perf = _perf_or_404(performance_id)
    b = body()
    scores = {cat: calc.Decimal(str(_req_score(b, cat))) for cat in
              calc.CATEGORIES}
    if perf["status"] == "SCHEDULED":
        raise errors.conflict("ERR_PERFORMANCE_NOT_PERFORMED",
                              "Sheet creation requires PERFORMED or SCORED")
    if perf["status"] in ("OFFICIAL", "EXCLUDED", "CANCELLED"):
        raise errors.conflict(
            "ERR_PERFORMANCE_INVALID_STATE",
            f"Sheet creation forbidden on {perf['status']} performance")
    division, team, event = _perf_context(perf)
    judge = db.judges.get(g.user_id)
    # Certification check (priority 11) precedes panel membership (12).
    if judge is not None and division is not None \
            and division["level"] not in judge["certified_levels"]:
        raise errors.unprocessable(
            "ERR_JUDGE_NOT_CERTIFIED",
            "Judge is not certified for this division's level")
    if division is not None and g.user_id not in division["judge_ids"]:
        raise errors.unprocessable("ERR_JUDGE_NOT_ON_PANEL",
                                   "Acting judge is not on the division panel")
    for s in db.score_sheets.values():
        if s["performance_id"] == perf["id"] and s["judge_id"] == g.user_id:
            raise errors.unprocessable(
                "ERR_DUPLICATE_SCORE_SHEET",
                "Judge already has a score sheet for this performance")
    rec = stamp({
        "performance_id": perf["id"],
        "judge_id": g.user_id,
        "building_difficulty": scores["building_difficulty"],
        "building_execution": scores["building_execution"],
        "tumbling_difficulty": scores["tumbling_difficulty"],
        "overall_impression": scores["overall_impression"],
        "status": "DRAFT",
        "submitted_at": None,
    })
    db.score_sheets[rec["id"]] = rec
    return ok(rec, 201)


def _req_score(b, field):
    v = b.get(field)
    if v is None or isinstance(v, bool) or not isinstance(v, (int, float)):
        raise errors.invalid_input(
            f"Field '{field}' is required and must be a number")
    if not (0 <= v <= 10):
        raise errors.invalid_input(f"Field '{field}' must be within 0..10")
    return v


def _sheet_or_404(sheet_id):
    return get_or_404(db.score_sheets, sheet_id, "ScoreSheet")


def _own_sheet(sheet):
    if sheet["judge_id"] != g.user_id:
        raise errors.forbidden("Only the sheet's authoring judge may modify it")


def _sheet_perf_div(sheet):
    perf = db.performances.get(sheet["performance_id"])
    division = db.divisions.get(perf["division_id"]) if perf else None
    return perf, division


@bp.get("/api/score-sheets/<sheet_id>")
@require_roles("EventDirector", "Judge", "HeadJudge")
def get_score_sheet(sheet_id):
    return ok(_sheet_or_404(sheet_id))


@bp.patch("/api/score-sheets/<sheet_id>")
@require_roles("Judge")
def patch_score_sheet(sheet_id):
    sheet = _sheet_or_404(sheet_id)
    _own_sheet(sheet)
    b = body()
    updates = {}
    for cat in calc.CATEGORIES:
        if cat in b and b[cat] is not None:
            updates[cat] = Decimal(str(_req_score(b, cat)))
    perf, division = _sheet_perf_div(sheet)
    if sheet["status"] == "LOCKED" or (perf is not None
                                       and perf["status"] == "OFFICIAL"):
        raise errors.conflict("ERR_SCORE_SHEET_LOCKED",
                              "Score sheet is LOCKED (performance OFFICIAL)")
    was_submitted = sheet["status"] == "SUBMITTED"
    if updates:
        sheet.update(updates)
    if was_submitted:
        sheet["status"] = "DRAFT"
    if updates or was_submitted:
        touch(sheet)
    if was_submitted and perf is not None:
        # Quorum-loss cascade: SCORED -> PERFORMED, provisional recomputed.
        if perf["status"] == "SCORED":
            set_fields(perf, status="PERFORMED")
        calc.recompute_provisional(perf)
    return ok(sheet)


@bp.post("/api/score-sheets/<sheet_id>/submit")
@require_roles("Judge")
def submit_score_sheet(sheet_id):
    sheet = _sheet_or_404(sheet_id)
    _own_sheet(sheet)
    perf, division = _sheet_perf_div(sheet)
    if sheet["status"] == "LOCKED" or (perf is not None
                                       and perf["status"] == "OFFICIAL"):
        raise errors.conflict("ERR_SCORE_SHEET_LOCKED",
                              "Score sheet is LOCKED (performance OFFICIAL)")
    if sheet["status"] != "DRAFT":
        raise errors.conflict("ERR_INVALID_STATE",
                              "submit requires the sheet to be DRAFT")
    if perf is not None and perf["status"] == "SCHEDULED":
        raise errors.conflict("ERR_PERFORMANCE_NOT_PERFORMED",
                              "Submit requires PERFORMED or SCORED")
    if perf is not None and perf["status"] in ("EXCLUDED", "CANCELLED"):
        raise errors.conflict(
            "ERR_PERFORMANCE_INVALID_STATE",
            f"Submit forbidden on {perf['status']} performance")
    # Certification re-check at submission.
    judge = db.judges.get(g.user_id)
    if judge is not None and division is not None \
            and division["level"] not in judge["certified_levels"]:
        raise errors.unprocessable(
            "ERR_JUDGE_NOT_CERTIFIED",
            "Judge is not certified for this division's level")
    set_fields(sheet, status="SUBMITTED", submitted_at=now())
    if perf is not None and division is not None:
        # Quorum completion: every panel judge holds a SUBMITTED sheet.
        submitted_judges = {s["judge_id"] for s in db.score_sheets.values()
                            if s["performance_id"] == perf["id"]
                            and s["status"] == "SUBMITTED"}
        if all(j in submitted_judges for j in division["judge_ids"]) \
                and perf["status"] == "PERFORMED":
            set_fields(perf, status="SCORED")
        # Provisional recompute on every submission once >= 2 SUBMITTED
        # sheets exist (null while fewer than 2 remain).
        calc.recompute_provisional(perf)
    return ok(sheet)


@bp.get("/api/performances/<performance_id>/score-sheets")
@require_roles("EventDirector", "Judge", "HeadJudge")
def list_performance_sheets(performance_id):
    _perf_or_404(performance_id)
    return ok_list(by_created([s for s in db.score_sheets.values()
                               if s["performance_id"] == performance_id]))


# ---------------------------------------------------------------------------
# Deductions
# ---------------------------------------------------------------------------

@bp.post("/api/performances/<performance_id>/deductions")
@require_roles("SafetyJudge")
def create_deduction(performance_id):
    perf = _perf_or_404(performance_id)
    b = body()
    dtype = req_enum(b, "type", ("SAFETY",))  # manual endpoint: SAFETY only
    quantity = req_int(b, "quantity", lo=1)
    skill_tier = req_int(b, "skill_tier", lo=1, hi=6)
    if perf["status"] == "SCHEDULED":
        raise errors.conflict("ERR_PERFORMANCE_NOT_PERFORMED",
                              "Deduction create requires PERFORMED or SCORED")
    if perf["status"] in ("OFFICIAL", "EXCLUDED", "CANCELLED"):
        raise errors.conflict(
            "ERR_PERFORMANCE_INVALID_STATE",
            f"Deduction create forbidden on {perf['status']} performance")
    division, team, event = _perf_context(perf)
    if division is not None and skill_tier <= division["level"]:
        raise errors.unprocessable(
            "ERR_SKILL_WITHIN_LEGAL_LIMIT",
            "Cited skill_tier is legal at this division level")
    rec = _create_deduction(perf, division, dtype, quantity, skill_tier,
                            "MANUAL", g.user_id)
    return ok(rec, 201)


@bp.get("/api/deductions/<deduction_id>")
@require_roles("EventDirector", "TeamCoach", "HeadJudge", "SafetyJudge")
def get_deduction(deduction_id):
    return ok(get_or_404(db.deductions, deduction_id, "Deduction"))


@bp.get("/api/deductions")
@require_roles("EventDirector", "HeadJudge", "SafetyJudge")
def list_deductions():
    applier = request.args.get("applied_by_judge_id")
    items = db.deductions.values()
    if applier is not None:
        items = [d for d in items if d["applied_by_judge_id"] == applier]
    return ok_list(by_created(list(items)))


@bp.patch("/api/deductions/<deduction_id>")
@require_roles("SafetyJudge")
def patch_deduction(deduction_id):
    ded = get_or_404(db.deductions, deduction_id, "Deduction")
    b = body()
    expected = req_int(b, "expected_deduction_version")
    quantity = opt_int(b, "quantity", None, lo=1)
    skill_tier = opt_int(b, "skill_tier", None, lo=1, hi=6)
    if expected != ded["version"]:
        raise errors.stale_version(
            "expected_deduction_version does not match the deduction's version")
    if ded["status"] != "APPLIED":
        raise errors.conflict("ERR_DEDUCTION_NOT_APPLIED",
                              "Amendment requires Deduction.status APPLIED")
    updates = {}
    if quantity is not None:
        updates["quantity"] = quantity
    if skill_tier is not None:
        updates["skill_tier"] = skill_tier
    if updates:
        new_qty = updates.get("quantity", ded["quantity"])
        updates["points"] = calc.deduction_points(new_qty, ded["rate_applied"])
        for k, v in updates.items():
            ded[k] = v
        touch(ded)
        perf = db.performances.get(ded["performance_id"])
        if perf is not None:
            calc.recompute_provisional(perf)
    return ok(ded)


@bp.post("/api/deductions/<deduction_id>/void")
@require_roles("HeadJudge")
def void_deduction(deduction_id):
    ded = get_or_404(db.deductions, deduction_id, "Deduction")
    perf = db.performances.get(ded["performance_id"])
    if perf is not None and perf["status"] == "OFFICIAL":
        raise errors.conflict(
            "ERR_PERFORMANCE_INVALID_STATE",
            "Void is forbidden once the performance is OFFICIAL")
    if ded["status"] != "APPLIED":
        raise errors.conflict("ERR_DEDUCTION_NOT_APPLIED",
                              "Void requires Deduction.status APPLIED")
    if ded["applied_by_judge_id"] is not None \
            and g.user_id == ded["applied_by_judge_id"]:
        raise errors.unprocessable(
            "ERR_SELF_VOID_FORBIDDEN",
            "A head judge cannot void a deduction they applied")
    set_fields(ded, status="VOIDED")
    if perf is not None:
        calc.recompute_provisional(perf)
    return ok(ded)


# ---------------------------------------------------------------------------
# Appeals
# ---------------------------------------------------------------------------

def _deduction_chain(ded):
    perf = db.performances.get(ded["performance_id"])
    team = db.teams.get(perf["team_id"]) if perf else None
    division = db.divisions.get(perf["division_id"]) if perf else None
    return perf, team, division


def _appeal_window_check(ded):
    if now() > ded["created_at"] + timedelta(
            minutes=calc.APPEAL_WINDOW_MINUTES):
        raise errors.unprocessable(
            "ERR_APPEAL_WINDOW_CLOSED",
            "Appeal window (45 minutes from deduction creation) is closed")


@bp.post("/api/deductions/<deduction_id>/appeals")
@require_roles("TeamCoach")
def create_appeal(deduction_id):
    ded = get_or_404(db.deductions, deduction_id, "Deduction")
    perf, team, division = _deduction_chain(ded)
    if team is not None:
        own_team(team)
    b = body()
    note = req_str(b, "note")
    video_ref = req_str(b, "video_ref")
    if ded["status"] != "APPLIED":
        raise errors.conflict("ERR_DEDUCTION_NOT_APPLIED",
                              "Appeal requires Deduction.status APPLIED")
    _appeal_window_check(ded)
    rec = stamp({
        "deduction_id": ded["id"],
        "round": 1,
        "note": note,
        "video_ref": video_ref,
        "status": "SUBMITTED",
        "decided_by_judge_id": None,
    })
    db.appeals[rec["id"]] = rec
    set_fields(ded, status="UNDER_APPEAL")
    if perf is not None:
        calc.recompute_provisional(perf)
    return ok(rec, 201)


@bp.get("/api/appeals/<appeal_id>")
@require_roles("EventDirector", "TeamCoach", "HeadJudge")
def get_appeal(appeal_id):
    return ok(get_or_404(db.appeals, appeal_id, "Appeal"))


@bp.get("/api/appeals")
@require_roles("EventDirector", "HeadJudge")
def list_appeals():
    decider = request.args.get("decided_by_judge_id")
    items = db.appeals.values()
    if decider is not None:
        items = [a for a in items if a["decided_by_judge_id"] == decider]
    return ok_list(by_created(list(items)))


@bp.get("/api/deductions/<deduction_id>/appeals")
@require_roles("EventDirector", "TeamCoach", "HeadJudge")
def list_deduction_appeals(deduction_id):
    get_or_404(db.deductions, deduction_id, "Deduction")
    return ok_list(by_created([a for a in db.appeals.values()
                               if a["deduction_id"] == deduction_id]))


@bp.get("/api/performances/<performance_id>/deductions")
@require_roles("EventDirector", "TeamCoach", "HeadJudge", "SafetyJudge")
def list_performance_deductions(performance_id):
    _perf_or_404(performance_id)
    return ok_list(by_created([d for d in db.deductions.values()
                               if d["performance_id"] == performance_id]))


@bp.post("/api/appeals/<appeal_id>/resolve")
@require_roles("HeadJudge")
def resolve_appeal(appeal_id):
    appeal = get_or_404(db.appeals, appeal_id, "Appeal")
    b = body()
    decision = req_enum(b, "decision", ("ACCEPTED", "REJECTED"))
    if appeal["status"] != "SUBMITTED":
        raise errors.conflict("ERR_INVALID_STATE",
                              "Resolve requires a SUBMITTED appeal")
    ded = db.deductions.get(appeal["deduction_id"])
    perf, team, division = _deduction_chain(ded) if ded else (None, None, None)
    # Segregation of duties: no authored sheet on this performance, and not
    # the deduction's applier.
    if perf is not None:
        for s in db.score_sheets.values():
            if s["performance_id"] == perf["id"] \
                    and s["judge_id"] == g.user_id:
                raise errors.unprocessable(
                    "ERR_REVIEWER_CONFLICT",
                    "Reviewer authored a score sheet on this performance")
    if ded is not None and ded["applied_by_judge_id"] is not None \
            and ded["applied_by_judge_id"] == g.user_id:
        raise errors.unprocessable(
            "ERR_REVIEWER_CONFLICT",
            "Reviewer applied the deduction under appeal")
    set_fields(appeal, status=decision, decided_by_judge_id=g.user_id)
    if decision == "REJECTED":
        if ded is not None:
            set_fields(ded, status="UPHELD")
    else:  # ACCEPTED -> deduction OVERTURNED, deep cascade
        if ded is not None:
            set_fields(ded, status="OVERTURNED")
        if perf is not None:
            calc.recompute_provisional(perf)
            if perf["status"] == "OFFICIAL":
                official = calc.final_score(perf["id"], "OFFICIAL")
                set_fields(perf, official_score=official)
                calc.recompute_ranking(perf["division_id"])
                if division is not None:
                    reevaluate(division)
    return ok(appeal)


@bp.post("/api/appeals/<appeal_id>/resubmit")
@require_roles("TeamCoach")
def resubmit_appeal(appeal_id):
    appeal = get_or_404(db.appeals, appeal_id, "Appeal")
    ded = db.deductions.get(appeal["deduction_id"])
    perf, team, division = _deduction_chain(ded) if ded else (None, None, None)
    if team is not None:
        own_team(team)
    b = body()
    note = req_str(b, "note")
    video_ref = req_str(b, "video_ref")
    if appeal["status"] != "REJECTED":
        raise errors.conflict("ERR_INVALID_STATE",
                              "Resubmit requires a REJECTED appeal")
    if appeal["round"] != 1:
        raise errors.unprocessable(
            "ERR_APPEAL_NOT_RESUBMITTABLE",
            "Only a round-1 appeal may be resubmitted (round cap 2)")
    _appeal_window_check(ded)
    if ded is not None and ded["status"] != "UPHELD":
        raise errors.conflict("ERR_DEDUCTION_NOT_APPLIED",
                              "Resubmit requires the deduction to be UPHELD")
    rec = stamp({
        "deduction_id": ded["id"],
        "round": appeal["round"] + 1,
        "note": note,
        "video_ref": video_ref,
        "status": "SUBMITTED",
        "decided_by_judge_id": None,
    })
    db.appeals[rec["id"]] = rec
    set_fields(ded, status="UNDER_APPEAL")
    if perf is not None:
        calc.recompute_provisional(perf)
    return ok(rec, 201)


# ---------------------------------------------------------------------------
# Bids
# ---------------------------------------------------------------------------

@bp.get("/api/bids/<bid_id>")
@require_roles("EventDirector", "TeamCoach")
def get_bid(bid_id):
    return ok(get_or_404(db.bids, bid_id, "Bid"))


def _bid_chain(bid):
    team = db.teams.get(bid["team_id"])
    division = db.divisions.get(bid["division_id"])
    return team, division


@bp.post("/api/bids/<bid_id>/accept")
@require_roles("TeamCoach")
def accept_bid(bid_id):
    bid = get_or_404(db.bids, bid_id, "Bid")
    team, division = _bid_chain(bid)
    if team is not None:
        own_team(team)
    if bid["status"] != "OFFERED":
        raise errors.conflict("ERR_BID_NOT_OFFERED",
                              "Bid accept requires status OFFERED")
    if team is not None and team["reg_status"] in ("WITHDRAWN", "DISQUALIFIED"):
        raise errors.conflict(
            "ERR_INVALID_STATE",
            "Withdrawn/disqualified teams cannot accept bids")
    if now() > bid["acceptance_deadline"]:
        raise errors.unprocessable("ERR_BID_ACCEPTANCE_CLOSED",
                                   "Bid acceptance deadline has passed")
    set_fields(bid, status="ACCEPTED")
    return ok(bid)


@bp.post("/api/bids/<bid_id>/decline")
@require_roles("TeamCoach")
def decline_bid(bid_id):
    bid = get_or_404(db.bids, bid_id, "Bid")
    team, division = _bid_chain(bid)
    if team is not None:
        own_team(team)
    if bid["status"] != "OFFERED":
        raise errors.conflict("ERR_BID_NOT_OFFERED",
                              "Bid decline requires status OFFERED")
    set_fields(bid, status="DECLINED")
    if division is not None:
        division["bid_pool_available"] += 1
        touch(division)
        reoffer_slot(division, bid["kind"], freed_team_id=bid["team_id"])
    return ok(bid)


# ---------------------------------------------------------------------------
# Sessions & ticket orders
# ---------------------------------------------------------------------------

@bp.post("/api/sessions")
@require_roles("EventDirector")
def create_session():
    b = body()
    event_id = req_str(b, "event_id")
    name = req_str(b, "name")
    starts_at = req_datetime_field(b, "starts_at")
    ends_at = req_datetime_field(b, "ends_at")
    capacity = req_int(b, "capacity", lo=1)
    if ends_at <= starts_at:
        raise errors.invalid_input("ends_at must be strictly after starts_at")
    get_or_404(db.events, event_id, "Event")
    rec = stamp({
        "event_id": event_id,
        "name": name,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "capacity": capacity,
        "seats_held": 0,
        "seats_sold": 0,
        "seats_available": capacity,
    })
    db.sessions[rec["id"]] = rec
    return ok(rec, 201)


@bp.get("/api/sessions/<session_id>")
@require_roles("EventDirector", "TeamCoach", "Spectator")
def get_session(session_id):
    return ok(get_or_404(db.sessions, session_id, "Session"))


@bp.get("/api/sessions/<session_id>/ticket-orders")
@require_roles("EventDirector")
def list_session_orders(session_id):
    get_or_404(db.sessions, session_id, "Session")
    return ok_list(by_created([o for o in db.ticket_orders.values()
                               if o["session_id"] == session_id]))


@bp.post("/api/ticket-orders")
@require_roles("Spectator")
def create_ticket_order():
    b = body()
    session_id = req_str(b, "session_id")
    quantity = req_int(b, "quantity", lo=1, hi=calc.MAX_PER_ORDER)
    session = get_or_404(db.sessions, session_id, "Session")
    event = db.events.get(session["event_id"])
    if event is not None and event["status"] not in (
            "REGISTRATION_OPEN", "REGISTRATION_CLOSED", "SCHEDULED", "LIVE"):
        raise errors.conflict(
            "ERR_EVENT_INVALID_STATE",
            "Ticket sales are closed in the event's current status")
    if session["seats_available"] < quantity:
        raise errors.conflict("ERR_SESSION_SOLD_OUT",
                              "Requested quantity exceeds seats_available")
    tier, unit, discount, total = calc.ticket_pricing(event, quantity, now())
    rec = stamp({
        "session_id": session_id,
        "purchaser_user_id": g.user_id,
        "quantity": quantity,
        "tier": tier,
        "unit_price_cents": unit,
        "discount_cents": discount,
        "total_cents": total,
        "status": "HELD",
        "hold_expires_at": now() + timedelta(minutes=calc.HOLD_MINUTES),
    })
    db.ticket_orders[rec["id"]] = rec
    session["seats_held"] += quantity
    session["seats_available"] = (session["capacity"] - session["seats_held"]
                                  - session["seats_sold"])
    touch(session)
    return ok(rec, 201)


def _order_or_404(order_id):
    return get_or_404(db.ticket_orders, order_id, "TicketOrder")


def _own_order(order):
    if g.user_id != order["purchaser_user_id"]:
        raise errors.forbidden("Only the purchasing spectator may do this")


def _bump_session(order, delta_held=0, delta_sold=0):
    session = db.sessions.get(order["session_id"])
    if session is not None:
        session["seats_held"] += delta_held
        session["seats_sold"] += delta_sold
        session["seats_available"] = (session["capacity"]
                                      - session["seats_held"]
                                      - session["seats_sold"])
        touch(session)


@bp.get("/api/ticket-orders/<order_id>")
@require_roles("EventDirector", "Spectator")
def get_ticket_order(order_id):
    return ok(_order_or_404(order_id))


@bp.post("/api/ticket-orders/<order_id>/pay")
@require_roles("Spectator")
def pay_ticket_order(order_id):
    order = _order_or_404(order_id)
    _own_order(order)
    if order["status"] != "HELD":
        raise errors.conflict("ERR_ORDER_INVALID_STATE",
                              "pay requires status HELD")
    if now() > order["hold_expires_at"]:
        raise errors.unprocessable("ERR_ORDER_HOLD_EXPIRED",
                                   "The order hold has expired")
    set_fields(order, status="PAID")
    _bump_session(order, delta_held=-order["quantity"],
                  delta_sold=order["quantity"])
    return ok(order)


@bp.post("/api/ticket-orders/<order_id>/cancel")
@require_roles("Spectator")
def cancel_ticket_order(order_id):
    order = _order_or_404(order_id)
    _own_order(order)
    if order["status"] == "HELD":
        set_fields(order, status="CANCELLED")
        _bump_session(order, delta_held=-order["quantity"])
    elif order["status"] == "PAID":
        set_fields(order, status="REFUNDED")
        _bump_session(order, delta_sold=-order["quantity"])
    else:
        raise errors.conflict("ERR_ORDER_INVALID_STATE",
                              "cancel requires status HELD or PAID")
    return ok(order)


# ---------------------------------------------------------------------------
# Warm-up assignments
# ---------------------------------------------------------------------------

@bp.post("/api/warm-up-assignments")
@require_roles("TeamCoach")
def create_warm_up_assignment():
    b = body()
    event_id = req_str(b, "event_id")
    team_id = req_str(b, "team_id")
    mat = req_str(b, "mat")
    starts_at = req_datetime_field(b, "starts_at")
    ends_at = req_datetime_field(b, "ends_at")
    if ends_at <= starts_at:
        raise errors.invalid_input("ends_at must be strictly after starts_at")
    get_or_404(db.events, event_id, "Event")
    team = get_or_404(db.teams, team_id, "Team")
    own_team(team)
    for w in db.warmup_assignments.values():
        if w["event_id"] == event_id and w["mat"] == mat \
                and w["status"] == "BOOKED" and calc.intervals_overlap(
                    starts_at, ends_at, w["starts_at"], w["ends_at"]):
            raise errors.conflict(
                "ERR_WARM_UP_OVERLAP",
                "Window overlaps a BOOKED assignment on the same mat")
    # Rest rule against the team's SCHEDULED performance.
    perf = next((p for p in db.performances.values()
                 if p["team_id"] == team_id and p["status"] == "SCHEDULED"),
                None)
    if perf is not None and ends_at + timedelta(
            seconds=calc.REST_S) > perf["scheduled_start"]:
        raise errors.unprocessable(
            "ERR_MIN_REST_VIOLATION",
            "Warm-up must end at least 600s before the scheduled start")
    rec = stamp({
        "event_id": event_id,
        "team_id": team_id,
        "mat": mat,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "source": "MANUAL",
        "status": "BOOKED",
    })
    db.warmup_assignments[rec["id"]] = rec
    return ok(rec, 201)


@bp.get("/api/warm-up-assignments/<assignment_id>")
@require_roles("EventDirector", "TeamCoach")
def get_warm_up_assignment(assignment_id):
    return ok(get_or_404(db.warmup_assignments, assignment_id,
                         "WarmUpAssignment"))


@bp.post("/api/warm-up-assignments/<assignment_id>/release")
@require_roles("TeamCoach")
def release_warm_up_assignment(assignment_id):
    warm = get_or_404(db.warmup_assignments, assignment_id, "WarmUpAssignment")
    team = db.teams.get(warm["team_id"])
    if team is not None:
        own_team(team)
    if warm["status"] != "BOOKED":
        raise errors.conflict("ERR_INVALID_STATE",
                              "release requires status BOOKED")
    set_fields(warm, status="RELEASED")
    return ok(warm)
