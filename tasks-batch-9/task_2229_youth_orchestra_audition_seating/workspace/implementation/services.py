"""Lookups, serializers, derived counters and every declared cascade."""

from datetime import timedelta
from decimal import Decimal

from flask import g

import calc
from errors import ApiError
from store import base_row, clock_now, db, iso3, now_utc, order_key

# --------------------------------------------------------------------- helpers


def _touched():
    bucket = getattr(g, "_touched_rows", None)
    if bucket is None:
        bucket = set()
        g._touched_rows = bucket
    return bucket


def touch(row):
    """Refresh updated_at and bump version at most once per HTTP request."""
    if row is None or "version" not in row:
        return
    bucket = _touched()
    key = id(row)
    if key in bucket:
        return
    bucket.add(key)
    row["version"] += 1
    row["updated_at"] = now_utc()


def new_row(with_version=True):
    row = base_row(with_version=with_version)
    if with_version:
        # A freshly created row is already at version 1 for this request.
        _touched().add(id(row))
    return row


def ordered(rows):
    return sorted(rows, key=order_key)


def fail(error_id, message=None):
    raise ApiError(error_id, message)


# ------------------------------------------------------------------- resolvers
def _resolve(table, row_id, error_id):
    if not isinstance(row_id, str):
        fail(error_id)
    row = table.get(row_id)
    if row is None:
        fail(error_id)
    return row


def season_or_404(sid):
    return _resolve(db.seasons, sid, "ERR_SEASON_NOT_FOUND")


def ensemble_or_404(eid):
    return _resolve(db.ensembles, eid, "ERR_ENSEMBLE_NOT_FOUND")


def quota_or_404(qid):
    return _resolve(db.section_quotas, qid, "ERR_SECTION_QUOTA_NOT_FOUND")


def member_or_404(mid):
    return _resolve(db.members, mid, "ERR_MEMBER_NOT_FOUND")


def panelist_or_404(pid):
    return _resolve(db.panelists, pid, "ERR_PANELIST_NOT_FOUND")


def slot_or_404(sid):
    return _resolve(db.audition_slots, sid, "ERR_AUDITION_SLOT_NOT_FOUND")


def audition_or_404(aid):
    return _resolve(db.auditions, aid, "ERR_AUDITION_NOT_FOUND")


def score_or_404(sid):
    return _resolve(db.panel_scores, sid, "ERR_PANEL_SCORE_NOT_FOUND")


def placement_or_404(pid):
    return _resolve(db.placements, pid, "ERR_PLACEMENT_NOT_FOUND")


def seat_or_404(sid):
    return _resolve(db.seat_assignments, sid, "ERR_SEAT_ASSIGNMENT_NOT_FOUND")


def account_or_404(aid):
    return _resolve(db.tuition_accounts, aid, "ERR_TUITION_ACCOUNT_NOT_FOUND")


def event_or_404(eid):
    return _resolve(db.ensemble_events, eid, "ERR_ENSEMBLE_EVENT_NOT_FOUND")


def participation_or_404(pid):
    return _resolve(db.event_participations, pid, "ERR_PARTICIPATION_NOT_FOUND")


# --------------------------------------------------------------- reverse walks
def ensembles_of_season(season_id):
    return [e for e in db.ensembles.values() if e["season_id"] == season_id]


def quotas_of_ensemble(ensemble_id):
    return ordered([q for q in db.section_quotas.values()
                    if q["ensemble_id"] == ensemble_id])


def quota_for(ensemble_id, instrument):
    for quota in quotas_of_ensemble(ensemble_id):
        if quota["instrument"] == instrument:
            return quota
    return None


def active_seats_of_quota(quota_id):
    return ordered([s for s in db.seat_assignments.values()
                    if s["section_quota_id"] == quota_id and s["status"] == "ACTIVE"])


def active_seats_of_member(member_id):
    return ordered([s for s in db.seat_assignments.values()
                    if s["member_id"] == member_id and s["status"] == "ACTIVE"])


def placements_of_ensemble(ensemble_id):
    return ordered([p for p in db.placements.values()
                    if p["ensemble_id"] == ensemble_id])


def accounts_of_member(member_id):
    return ordered([a for a in db.tuition_accounts.values()
                    if a["member_id"] == member_id])


def accounts_of_season(season_id):
    return ordered([a for a in db.tuition_accounts.values()
                    if a["season_id"] == season_id])


def participations_of_member(member_id):
    return ordered([p for p in db.event_participations.values()
                    if p["member_id"] == member_id])


def participations_of_event(event_id):
    return ordered([p for p in db.event_participations.values()
                    if p["event_id"] == event_id])


def scores_of_round(audition):
    return ordered([s for s in db.panel_scores.values()
                    if s["audition_id"] == audition["id"]
                    and s["revision_round"] == audition["revision_round"]])


def events_of_ensemble(ensemble_id):
    return ordered([e for e in db.ensemble_events.values()
                    if e["ensemble_id"] == ensemble_id])


def season_of_ensemble(ensemble):
    return db.seasons.get(ensemble["season_id"])


def ensemble_of_quota(quota):
    return db.ensembles[quota["ensemble_id"]]


# --------------------------------------------------------- derived counters
def filled_count(quota):
    return len(active_seats_of_quota(quota["id"]))


def seated_count(ensemble):
    return sum(filled_count(q) for q in quotas_of_ensemble(ensemble["id"]))


def offered_count(ensemble):
    return len([p for p in db.placements.values()
                if p["ensemble_id"] == ensemble["id"] and p["status"] == "OFFERED"])


def ensemble_count(season):
    return len(ensembles_of_season(season["id"]))


def seated_ensemble_count(season):
    return len([e for e in ensembles_of_season(season["id"])
                if e["roster_state"] == "SEATED"])


def booked_count(slot):
    booked_states = ("SCHEDULED", "SCORED", "REVISION_REQUESTED", "ADJUDICATED")
    return len([a for a in db.auditions.values()
                if a["slot_id"] == slot["id"] and a["status"] in booked_states])


def slot_status(slot):
    return "OPEN" if booked_count(slot) < slot["capacity"] else "FULL"


def submitted_score_count(audition):
    return len(scores_of_round(audition))


def participation_count(event):
    return len(participations_of_event(event["id"]))


def unexcused_absence_count(member):
    return len([p for p in db.event_participations.values()
                if p["member_id"] == member["id"]
                and p["attendance_status"] == "UNEXCUSED_ABSENT"])


def tardy_count(member):
    return len([p for p in db.event_participations.values()
                if p["member_id"] == member["id"]
                and p["attendance_status"] == "TARDY"])


def effective_unexcused_count(member):
    return calc.effective_unexcused(unexcused_absence_count(member),
                                    tardy_count(member))


def probation_due(member):
    return (effective_unexcused_count(member) - member["probation_baseline_count"]
            ) >= calc.UNEXCUSED_PROBATION_THRESHOLD


def fundraising_shortfall(participation, credited=None):
    event = db.ensemble_events[participation["event_id"]]
    if credited is None:
        credited = participation["fundraising_credited_cents"]
    return max(0, event["tour_cost_share_cents"] - credited)


# ----------------------------------------------------------------- serializers
def _num(value):
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return value


def _common(row, data):
    data["id"] = row["id"]
    data["created_at"] = iso3(row["created_at"])
    if "version" in row:
        data["updated_at"] = iso3(row["updated_at"])
        data["version"] = row["version"]
    return data


def season_json(row):
    committed = row["aid_committed_cents"]
    return _common(row, {
        "name": row["name"],
        "year_label": row["year_label"],
        "status": row["status"],
        "audition_window_start": iso3(row["audition_window_start"]),
        "audition_window_end": iso3(row["audition_window_end"]),
        "tuition_base_cents": row["tuition_base_cents"],
        "tuition_due_at": iso3(row["tuition_due_at"]),
        "aid_budget_cents": row["aid_budget_cents"],
        "aid_committed_cents": committed,
        "aid_available_cents": row["aid_budget_cents"] - committed,
        "ensemble_count": ensemble_count(row),
        "seated_ensemble_count": seated_ensemble_count(row),
    })


def ensemble_json(row):
    return _common(row, {
        "season_id": row["season_id"],
        "name": row["name"],
        "tier": row["tier"],
        "min_total_size": row["min_total_size"],
        "max_total_size": row["max_total_size"],
        "rehearsal_weekday": row["rehearsal_weekday"],
        "roster_state": row["roster_state"],
        "seated_count": seated_count(row),
        "offered_count": offered_count(row),
    })


def quota_json(row):
    return _common(row, {
        "ensemble_id": row["ensemble_id"],
        "instrument": row["instrument"],
        "min_count": row["min_count"],
        "target_count": row["target_count"],
        "max_count": row["max_count"],
        "principal_required": row["principal_required"],
        "rotation_policy": row["rotation_policy"],
        "filled_count": filled_count(row),
        "balance_state": row["balance_state"],
        "rotation_cycle_index": row["rotation_cycle_index"],
    })


def member_json(row):
    return _common(row, {
        "legal_name": row["legal_name"],
        "primary_instrument": row["primary_instrument"],
        "instrument_class": row["instrument_class"],
        "grade_level": row["grade_level"],
        "graduation_year": row["graduation_year"],
        "years_in_org": row["years_in_org"],
        "household_income_band": row["household_income_band"],
        "sibling_enrolled": row["sibling_enrolled"],
        "alumni_engagement_opt_in": row["alumni_engagement_opt_in"],
        "enrollment_status": row["enrollment_status"],
        "standing_status": row["standing_status"],
        "unexcused_absence_count": unexcused_absence_count(row),
        "tardy_count": tardy_count(row),
        "effective_unexcused_count": effective_unexcused_count(row),
        "probation_baseline_count": row["probation_baseline_count"],
    })


def panelist_json(row):
    return _common(row, {
        "display_name": row["display_name"],
        "instrument_expertise": row["instrument_expertise"],
        "panel_role": row["panel_role"],
        "conflict_member_ids": list(row["conflict_member_ids"]),
        "available_for_panels": row["available_for_panels"],
    })


def slot_json(row):
    return _common(row, {
        "season_id": row["season_id"],
        "room_code": row["room_code"],
        "start_at": iso3(row["start_at"]),
        "end_at": iso3(row["end_at"]),
        "panelist_ids": list(row["panelist_ids"]),
        "instrument_focus": row["instrument_focus"],
        "required_excerpt_codes": list(row["required_excerpt_codes"]),
        "quorum_required": row["quorum_required"],
        "capacity": row["capacity"],
        "booked_count": booked_count(row),
        "status": slot_status(row),
    })


def audition_json(row):
    return _common(row, {
        "member_id": row["member_id"],
        "season_id": row["season_id"],
        "slot_id": row["slot_id"],
        "declared_program": row["declared_program"],
        "excerpt_ids": list(row["excerpt_ids"]),
        "scale_attested": row["scale_attested"],
        "blind_code": row["blind_code"],
        "status": row["status"],
        "revision_round": row["revision_round"],
        "submitted_score_count": submitted_score_count(row),
        "composite_provisional_score": _num(row["composite_provisional_score"]),
        "composite_final_score": _num(row["composite_final_score"]),
        "tier_recommendation": row["tier_recommendation"],
    })


def score_json(row):
    return _common(row, {
        "audition_id": row["audition_id"],
        "panelist_id": row["panelist_id"],
        "revision_round": row["revision_round"],
        "tone_score": row["tone_score"],
        "rhythm_score": row["rhythm_score"],
        "intonation_score": row["intonation_score"],
        "sight_reading_score": row["sight_reading_score"],
        "weighted_total": _num(row["weighted_total"]),
        "blind": row["blind"],
    })


def placement_json(row):
    return _common(row, {
        "audition_id": row["audition_id"],
        "member_id": row["member_id"],
        "ensemble_id": row["ensemble_id"],
        "offer_kind": row["offer_kind"],
        "status": row["status"],
        "waitlist_rank": row["waitlist_rank"],
        "offer_expires_at": iso3(row["offer_expires_at"]),
        "accepted_at": iso3(row["accepted_at"]),
        "instrument_loan_requested": row["instrument_loan_requested"],
        "instrument_class_loaned": row["instrument_class_loaned"],
    })


def seat_json(row):
    return _common(row, {
        "placement_id": row["placement_id"],
        "section_quota_id": row["section_quota_id"],
        "member_id": row["member_id"],
        "predecessor_assignment_id": row["predecessor_assignment_id"],
        "chair_number": row["chair_number"],
        "is_principal": row["is_principal"],
        "ranking_score": _num(row["ranking_score"]),
        "rotation_cycle_index": row["rotation_cycle_index"],
        "status": row["status"],
    })


def account_json(row):
    return _common(row, {
        "member_id": row["member_id"],
        "season_id": row["season_id"],
        "ensemble_tier": row["ensemble_tier"],
        "assessment_variant": row["assessment_variant"],
        "assessed_cents": row["assessed_cents"],
        "sibling_discount_cents": row["sibling_discount_cents"],
        "loyalty_credit_cents": row["loyalty_credit_cents"],
        "aid_requested_cents": row["aid_requested_cents"],
        "aid_awarded_cents": row["aid_awarded_cents"],
        "aid_effective_cents": row["aid_effective_cents"],
        "instrument_loan_fee_cents": row["instrument_loan_fee_cents"],
        "payments_total_cents": row["payments_total_cents"],
        "balance_cents": row["balance_cents"],
        "billing_status": row["billing_status"],
        "aid_status": row["aid_status"],
        "aid_need_score": row["aid_need_score"],
        "aid_reviewed_by_user_id": row["aid_reviewed_by_user_id"],
        "aid_awarded_by_user_id": row["aid_awarded_by_user_id"],
        "aid_denial_reason": row["aid_denial_reason"],
    })


def event_json(row):
    return _common(row, {
        "ensemble_id": row["ensemble_id"],
        "kind": row["kind"],
        "start_at": iso3(row["start_at"]),
        "end_at": iso3(row["end_at"]),
        "venue_code": row["venue_code"],
        "is_dress_rehearsal": row["is_dress_rehearsal"],
        "dress_rehearsal_required": row["dress_rehearsal_required"],
        "eligibility_window_start": iso3(row["eligibility_window_start"]),
        "soloist_selection_mode": row["soloist_selection_mode"],
        "soloist_member_id": row["soloist_member_id"],
        "guest_artist_name": row["guest_artist_name"],
        "guest_artist_fee_cents": row["guest_artist_fee_cents"],
        "programming_state": row["programming_state"],
        "tour_cost_share_cents": row["tour_cost_share_cents"],
        "chaperone_required": row["chaperone_required"],
        "participation_count": participation_count(row),
    })


def participation_json(row):
    return _common(row, {
        "event_id": row["event_id"],
        "member_id": row["member_id"],
        "attendance_status": row["attendance_status"],
        "excuse_reason_code": row["excuse_reason_code"],
        "excuse_documentation_ref": row["excuse_documentation_ref"],
        "excuse_decided_by_user_id": row["excuse_decided_by_user_id"],
        "performance_eligibility": row["performance_eligibility"],
        "ineligibility_reason": row["ineligibility_reason"],
        "attendance_index": _num(row["attendance_index"]),
        "fundraising_credited_cents": row["fundraising_credited_cents"],
        "fundraising_shortfall_cents": row["fundraising_shortfall_cents"],
        "chaperone_name": row["chaperone_name"],
        "chaperone_background_check_ref": row["chaperone_background_check_ref"],
        "chaperone_confirmed": row["chaperone_confirmed"],
        "tour_status": row["tour_status"],
    })


# ------------------------------------------------------------------ list utils
def _filter_repr(value):
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, Decimal):
        return str(value)
    return str(value)


def apply_filters(rows, args, fields):
    out = rows
    for field in fields:
        if field in args:
            wanted = (args.get(field) or "").strip()
            out = [r for r in out if _filter_repr(r.get(field)) == wanted]
    return out


def paginate(rows, limit, offset):
    return rows[offset:offset + limit]


# ------------------------------------------------------- section / roster math
def recompute_quota_balance(quota):
    count = filled_count(quota)
    if count < quota["min_count"]:
        state = "UNDERFILLED"
    elif count < quota["target_count"]:
        state = "BALANCED"
    else:
        state = "FULL"
    if state != quota["balance_state"]:
        quota["balance_state"] = state
        touch(quota)


def recompute_ensemble_roster(ensemble):
    if ensemble["roster_state"] == "CLOSED":
        return
    quotas = quotas_of_ensemble(ensemble["id"])
    all_full = bool(quotas) and all(q["balance_state"] == "FULL" for q in quotas)
    if ensemble["roster_state"] == "FORMING":
        if all_full and seated_count(ensemble) >= ensemble["min_total_size"]:
            ensemble["roster_state"] = "SEATED"
            touch(ensemble)
            recompute_season_seating(season_of_ensemble(ensemble))
    elif ensemble["roster_state"] == "SEATED":
        if not all_full:
            ensemble["roster_state"] = "FORMING"
            touch(ensemble)
            recompute_season_seating(season_of_ensemble(ensemble))


def recompute_season_seating(season):
    if season is None:
        return
    touch(season)
    if season["status"] == "PLACEMENT":
        total = ensemble_count(season)
        if total >= 1 and seated_ensemble_count(season) == total:
            season["status"] = "IN_SEASON"


def rank_chairs(quota):
    """Derives chair_number / is_principal over the section's ACTIVE chairs."""
    seats = active_seats_of_quota(quota["id"])
    order = sorted(
        seats,
        key=lambda s: (
            -Decimal(s["ranking_score"] if s["ranking_score"] is not None else 0),
            -int(db.members[s["member_id"]]["years_in_org"] or 0),
            s["created_at"],
            s["_seq"],
        ),
    )
    for index, seat in enumerate(order):
        number = index + 1
        principal = bool(number == 1 and quota["principal_required"])
        if seat["chair_number"] != number or seat["is_principal"] != principal:
            seat["chair_number"] = number
            seat["is_principal"] = principal
            touch(seat)


# ------------------------------------------------------------- tuition account
def ensure_tuition_account(member_id, season_id, tier):
    for account in db.tuition_accounts.values():
        if account["member_id"] == member_id and account["season_id"] == season_id:
            return account
    row = new_row()
    row.update({
        "member_id": member_id,
        "season_id": season_id,
        "ensemble_tier": tier,
        "assessment_variant": "PRELIMINARY",
        "assessed_cents": 0,
        "sibling_discount_cents": 0,
        "loyalty_credit_cents": 0,
        "aid_requested_cents": 0,
        "aid_awarded_cents": 0,
        "aid_effective_cents": 0,
        "instrument_loan_fee_cents": 0,
        "payments_total_cents": 0,
        "balance_cents": 0,
        "billing_status": "PENDING_ASSESSMENT",
        "aid_status": "NONE",
        "aid_need_score": 0,
        "aid_reviewed_by_user_id": None,
        "aid_awarded_by_user_id": None,
        "aid_denial_reason": "NONE",
    })
    db.tuition_accounts[row["id"]] = row
    return row


def account_for(member_id, season_id):
    for account in db.tuition_accounts.values():
        if account["member_id"] == member_id and account["season_id"] == season_id:
            return account
    return None


def recompute_balance(account):
    account["balance_cents"] = (account["assessed_cents"]
                                - account["aid_effective_cents"]
                                + account["instrument_loan_fee_cents"]
                                - account["payments_total_cents"])


def apply_billing_status(account):
    """Applies the declared billing transitions after a balance recomputation."""
    season = db.seasons[account["season_id"]]
    current = account["billing_status"]
    balance = account["balance_cents"]
    past_due = clock_now() >= season["tuition_due_at"]
    target = current
    if current == "PENDING_ASSESSMENT":
        if account["assessed_cents"] > 0:
            target = "CURRENT"
    elif balance <= 0:
        if current in ("CURRENT", "DELINQUENT"):
            target = "PAID_IN_FULL"
    else:
        if past_due:
            if current in ("CURRENT", "PAID_IN_FULL"):
                target = "DELINQUENT"
        else:
            if current in ("DELINQUENT", "PAID_IN_FULL"):
                target = "CURRENT"
    if target != current:
        account["billing_status"] = target
        touch(account)
        reevaluate_standing(db.members[account["member_id"]])


def reevaluate_standing(member):
    """FINANCIAL_HOLD above ATTENDANCE_PROBATION above CLEAR."""
    delinquent = any(a["billing_status"] == "DELINQUENT"
                     for a in accounts_of_member(member["id"]))
    current = member["standing_status"]
    if delinquent:
        if current != "FINANCIAL_HOLD":
            member["standing_status"] = "FINANCIAL_HOLD"
            touch(member)
        return
    if current == "FINANCIAL_HOLD":
        member["standing_status"] = ("ATTENDANCE_PROBATION" if probation_due(member)
                                     else "CLEAR")
        touch(member)


def preliminary_assessment(account, placement):
    season = db.seasons[account["season_id"]]
    member = db.members[account["member_id"]]
    gross = calc.gross_cents(season["tuition_base_cents"], account["ensemble_tier"])
    account["assessment_variant"] = "PRELIMINARY"
    account["sibling_discount_cents"] = 0
    account["loyalty_credit_cents"] = 0
    account["assessed_cents"] = gross
    account["instrument_loan_fee_cents"] = calc.loan_fee(
        placement["instrument_class_loaned"] if placement["instrument_loan_requested"]
        else None)
    recompute_balance(account)
    touch(account)
    apply_billing_status(account)
    reevaluate_standing(member)


# ---------------------------------------------------------- waitlist promotion
def waitlist_promotion(ensemble, instrument):
    """Re-ranks the section's waitlist and promotes its head when a seat is free."""
    quota = quota_for(ensemble["id"], instrument)
    if quota is None:
        return 0
    queue = [p for p in db.placements.values()
             if p["ensemble_id"] == ensemble["id"]
             and p["status"] == "WAITLISTED"
             and db.members[p["member_id"]]["primary_instrument"] == instrument]

    def sort_key(placement):
        audition = db.auditions.get(placement["audition_id"]) or {}
        score = audition.get("composite_final_score")
        return (-Decimal(score if score is not None else 0),
                placement["created_at"], placement["_seq"])

    queue = sorted(queue, key=sort_key)
    promoted = 0
    if queue and (filled_count(quota) + offered_count(ensemble)) < quota["max_count"]:
        head = queue[0]
        head["status"] = "OFFERED"
        head["offer_expires_at"] = clock_now() + timedelta(hours=calc.OFFER_TTL_HOURS)
        head["waitlist_rank"] = None
        touch(head)
        touch(ensemble)
        ensure_tuition_account(head["member_id"], ensemble["season_id"],
                               ensemble["tier"])
        queue = queue[1:]
        promoted = 1
    for index, placement in enumerate(queue):
        rank = index + 1
        if placement["waitlist_rank"] != rank:
            placement["waitlist_rank"] = rank
            touch(placement)
    return promoted


def rerank_waitlist(ensemble, instrument):
    queue = [p for p in db.placements.values()
             if p["ensemble_id"] == ensemble["id"]
             and p["status"] == "WAITLISTED"
             and db.members[p["member_id"]]["primary_instrument"] == instrument]

    def sort_key(placement):
        audition = db.auditions.get(placement["audition_id"]) or {}
        score = audition.get("composite_final_score")
        return (-Decimal(score if score is not None else 0),
                placement["created_at"], placement["_seq"])

    for index, placement in enumerate(sorted(queue, key=sort_key)):
        rank = index + 1
        if placement["waitlist_rank"] != rank:
            placement["waitlist_rank"] = rank
            touch(placement)


# ------------------------------------------------------------- vacate cascade
def vacate_seat(seat):
    quota = db.section_quotas[seat["section_quota_id"]]
    ensemble = ensemble_of_quota(quota)
    placement = db.placements.get(seat["placement_id"])
    seat["status"] = "VACATED"
    touch(seat)
    if placement is not None and placement["status"] == "ACCEPTED":
        placement["status"] = "RELEASED"
        touch(placement)
    touch(quota)
    rank_chairs(quota)
    recompute_quota_balance(quota)
    touch(ensemble)
    recompute_ensemble_roster(ensemble)
    waitlist_promotion(ensemble, quota["instrument"])


def withdraw_open_placements(member_id, season_id=None):
    for placement in ordered(list(db.placements.values())):
        if placement["member_id"] != member_id:
            continue
        if placement["status"] not in ("OFFERED", "WAITLISTED"):
            continue
        ensemble = db.ensembles[placement["ensemble_id"]]
        if season_id is not None and ensemble["season_id"] != season_id:
            continue
        was_waitlisted = placement["status"] == "WAITLISTED"
        placement["status"] = "WITHDRAWN"
        placement["waitlist_rank"] = None
        touch(placement)
        touch(ensemble)
        # A WITHDRAWN row frees no seat, so no promotion runs (PRD 3.5); the
        # remaining waitlist is simply renumbered densely from 1.
        if was_waitlisted:
            rerank_waitlist(ensemble, db.members[member_id]["primary_instrument"])


# ---------------------------------------------------------- probation cascade
def revoke_future_performance_eligibility(member):
    now = clock_now()
    for participation in participations_of_member(member["id"]):
        event = db.ensemble_events[participation["event_id"]]
        if event["kind"] not in ("CONCERT", "TOUR_PERFORMANCE", "FESTIVAL"):
            continue
        if not event["start_at"] > now:
            continue
        if participation["performance_eligibility"] == "INELIGIBLE":
            continue
        participation["performance_eligibility"] = "INELIGIBLE"
        participation["ineligibility_reason"] = "MEMBER_ON_PROBATION"
        if participation["tour_status"] == "READY":
            participation["tour_status"] = "PENDING"
        touch(participation)
    # Fourth hop: every event this musician headlined loses its soloist. This is
    # deliberately a separate sweep - it does not depend on a participation row
    # existing for the event.
    for event in ordered(list(db.ensemble_events.values())):
        if (event["soloist_member_id"] == member["id"]
                and event["programming_state"] == "PROGRAMMED"):
            event["programming_state"] = "SOLOIST_VACANT"
            event["soloist_member_id"] = None
            touch(event)


def attendance_cascade(member):
    """Counter recomputation plus the probation cascade it may trigger."""
    touch(member)
    if member["standing_status"] == "CLEAR" and probation_due(member):
        member["standing_status"] = "ATTENDANCE_PROBATION"
        revoke_future_performance_eligibility(member)


# ------------------------------------------------------------ soloist selection
def soloist_candidates(event):
    ensemble = db.ensembles[event["ensemble_id"]]
    quota_ids = set(q["id"] for q in quotas_of_ensemble(ensemble["id"]))
    taken = set()
    for other in events_of_ensemble(ensemble["id"]):
        if other["id"] == event["id"]:
            continue
        if other["programming_state"] == "PROGRAMMED" and other["soloist_member_id"]:
            taken.add(other["soloist_member_id"])
    pool = []
    for seat in ordered(list(db.seat_assignments.values())):
        if seat["status"] != "ACTIVE" or seat["section_quota_id"] not in quota_ids:
            continue
        member = db.members[seat["member_id"]]
        if member["standing_status"] != "CLEAR":
            continue
        if member["id"] in taken:
            continue
        participation = None
        for row in participations_of_event(event["id"]):
            if row["member_id"] == member["id"]:
                participation = row
                break
        if participation is None or participation["performance_eligibility"] != "ELIGIBLE":
            continue
        pool.append((seat, member, participation))

    def sort_key(entry):
        seat, member, participation = entry
        index = participation["attendance_index"]
        return (
            0 if seat["is_principal"] else 1,
            -Decimal(seat["ranking_score"] if seat["ranking_score"] is not None else 0),
            -int(member["years_in_org"] or 0),
            -Decimal(index if index is not None else 0),
            seat["created_at"],
            seat["_seq"],
        )

    return sorted(pool, key=sort_key)


# --------------------------------------------------------- attendance index
def compute_attendance_index(participation, event):
    ensemble_id = event["ensemble_id"]
    window_start = event["eligibility_window_start"]
    rehearsals = []
    for candidate in events_of_ensemble(ensemble_id):
        if candidate["kind"] != "REHEARSAL":
            continue
        if window_start is not None and candidate["start_at"] < window_start:
            continue
        if not candidate["start_at"] < event["start_at"]:
            continue
        rehearsals.append(candidate)
    rehearsal_ids = set(r["id"] for r in rehearsals)
    statuses = []
    for row in participations_of_member(participation["member_id"]):
        if row["event_id"] in rehearsal_ids and row["attendance_status"] != "NOT_RECORDED":
            statuses.append(row["attendance_status"])
    index = calc.attendance_index(statuses)
    dress_ok = True
    if event["dress_rehearsal_required"]:
        dress = [r for r in rehearsals if r["is_dress_rehearsal"]]
        dress_ok = False
        if dress:
            latest = sorted(dress, key=lambda r: (r["start_at"], r["_seq"]))[-1]
            for row in participations_of_member(participation["member_id"]):
                if row["event_id"] == latest["id"] and row["attendance_status"] == "PRESENT":
                    dress_ok = True
                    break
    return index, dress_ok


# ------------------------------------------------------------------ blind code
def mint_blind_code(instrument):
    nxt = db.blind_seq.get(instrument, 0) + 1
    db.blind_seq[instrument] = nxt
    return "%s-%03d" % (instrument, nxt)
