"""Domain services: census, waitlist, ledger, cascades, rankings."""
from datetime import timedelta

import calc
from store import (
    db, bump, clock, clock_iso, iso, dt_of, day_start, new_row, insert,
)


# ---------------------------------------------------------------------------
# collection helpers
# ---------------------------------------------------------------------------
def entries_of_tournament(tournament_id):
    return [e for e in db.entries.values() if e["tournament_id"] == tournament_id]


def entries_of_member(member_id):
    return [e for e in db.entries.values() if e["member_id"] == member_id]


def rounds_of_entry(entry_id):
    return [r for r in db.rounds.values() if r["entry_id"] == entry_id]


def rounds_of_tournament(tournament_id):
    return [r for r in db.rounds.values() if r["tournament_id"] == tournament_id]


def cases_of_round(round_id):
    return [c for c in db.rules_cases.values() if c["round_id"] == round_id]


def season_of(row):
    return db.seasons.get(row.get("season_id"))


def member_of_entry(entry):
    return db.members.get(entry["member_id"])


def tournament_of_entry(entry):
    return db.tournaments.get(entry["tournament_id"])


def grant_of_entry(entry):
    grant_id = entry.get("exemption_grant_id")
    return db.exemption_grants.get(grant_id) if grant_id else None


def application_of_entry(entry):
    app_id = entry.get("aid_application_id")
    return db.aid_applications.get(app_id) if app_id else None


# ---------------------------------------------------------------------------
# slot census and field quality
# ---------------------------------------------------------------------------
def recompute_census(tournament):
    rows = entries_of_tournament(tournament["id"])
    accepted = 0
    waitlisted = 0
    applied = 0
    closed = 0
    finished = 0
    for entry in rows:
        status = entry["entry_status"]
        if status in calc.SLOT_HOLDING_STATUSES:
            accepted += 1
        if status == "WAITLISTED":
            waitlisted += 1
        if status == "APPLIED":
            applied += 1
        if status in calc.CLOSED_STATUSES:
            closed += 1
        if status == "FINISHED":
            finished += 1
    tournament["entry_count"] = len(rows)
    tournament["accepted_count"] = accepted
    tournament["waitlist_count"] = waitlisted
    tournament["applied_count"] = applied
    tournament["closed_count"] = closed
    tournament["finished_count"] = finished
    tournament["open_slot_count"] = max(0, tournament["field_size_limit"] - accepted)
    return tournament


def recompute_field_quality(tournament):
    field = [
        e
        for e in entries_of_tournament(tournament["id"])
        if e["entry_status"] in calc.SLOT_HOLDING_STATUSES
    ]
    tournament["field_quality_factor"] = calc.field_quality_factor(field)
    return tournament


def renumber_waitlist(tournament):
    waiting = [
        e
        for e in entries_of_tournament(tournament["id"])
        if e["entry_status"] == "WAITLISTED"
    ]
    waiting.sort(
        key=lambda e: (
            e["waitlist_position"] if e["waitlist_position"] is not None else 10 ** 9,
            e["_seq"],
        )
    )
    position = 1
    for entry in waiting:
        if entry["waitlist_position"] != position:
            entry["waitlist_position"] = position
            bump(entry)
        position += 1


def consume_grant(entry):
    """ACTIVE -> CONSUMED at the moment the entry takes a playing slot."""
    grant = grant_of_entry(entry)
    if grant is None or grant["status"] != "ACTIVE":
        return
    expires = dt_of(grant["expires_at"])
    if expires is not None and clock() > expires:
        return
    grant["status"] = "CONSUMED"
    grant["consumed_by_entry_id"] = entry["id"]
    bump(grant)


def restore_grant(entry):
    """CONSUMED -> ACTIVE compensation (withdrawal / cancellation only)."""
    grant = grant_of_entry(entry)
    if grant is None or grant["status"] != "CONSUMED":
        return
    grant["status"] = "ACTIVE"
    grant["consumed_by_entry_id"] = None
    bump(grant)


def promote_from_waitlist(tournament):
    """Promote the lowest waitlist_position when a slot is free and FIELD_SET."""
    if tournament["status"] != "FIELD_SET":
        return None
    if tournament["open_slot_count"] < 1:
        return None
    waiting = [
        e
        for e in entries_of_tournament(tournament["id"])
        if e["entry_status"] == "WAITLISTED"
    ]
    if not waiting:
        return None
    waiting.sort(
        key=lambda e: (
            e["waitlist_position"] if e["waitlist_position"] is not None else 10 ** 9,
            e["_seq"],
        )
    )
    candidate = waiting[0]
    member = member_of_entry(candidate)
    if member is None or member["eligibility_status"] != "VERIFIED":
        return None
    candidate["entry_status"] = "ACCEPTED"
    candidate["waitlist_position"] = None
    bump(candidate)
    consume_grant(candidate)
    renumber_waitlist(tournament)
    recompute_census(tournament)
    recompute_field_quality(tournament)
    bump(tournament)
    return candidate


# ---------------------------------------------------------------------------
# the season assistance ledger
# ---------------------------------------------------------------------------
def settle_award(season, application, entry, award_cents):
    season["assistance_available_cents"] -= award_cents
    season["assistance_committed_cents"] += award_cents
    application["consumed_cents"] += award_cents
    bump(season)
    bump(application)


def release_award(entry):
    """Withdrawal / cancellation reversal: committed money returns to available."""
    award = entry.get("aid_award_cents") or 0
    if award <= 0:
        return
    tournament = tournament_of_entry(entry)
    season = db.seasons.get(tournament["season_id"]) if tournament else None
    application = application_of_entry(entry)
    if season is not None:
        season["assistance_available_cents"] += award
        season["assistance_committed_cents"] -= award
        bump(season)
    if application is not None:
        application["consumed_cents"] -= award
        bump(application)
    entry["aid_award_cents"] = 0


def disburse_award(entry):
    """Forfeiture / completion: committed money becomes disbursed for good."""
    award = entry.get("aid_award_cents") or 0
    if award <= 0:
        return
    tournament = tournament_of_entry(entry)
    season = db.seasons.get(tournament["season_id"]) if tournament else None
    if season is not None:
        season["assistance_committed_cents"] -= award
        season["assistance_disbursed_cents"] += award
        bump(season)


# ---------------------------------------------------------------------------
# round and entry derivations
# ---------------------------------------------------------------------------
def refresh_adjusted_gross(rnd):
    rnd["adjusted_gross"] = calc.adjusted_gross(
        rnd["gross_strokes"], rnd["pace_penalty_strokes"], rnd["rules_penalty_strokes"]
    )
    return rnd["adjusted_gross"]


def refresh_round_numbers(rnd, tournament):
    """Re-derive adjusted_gross and scoring_differential from scratch."""
    refresh_adjusted_gross(rnd)
    if rnd["adjusted_gross"] is None:
        rnd["scoring_differential"] = None
    else:
        rnd["scoring_differential"] = calc.scoring_differential(
            rnd["adjusted_gross"],
            tournament["course_rating"],
            tournament["slope_rating"],
        )
    return rnd


def recompute_entry_rollup(entry):
    certified = [
        r for r in rounds_of_entry(entry["id"]) if r["status"] == "CERTIFIED"
    ]
    certified.sort(key=lambda r: (r["round_number"], r["_seq"]))
    entry["certified_round_count"] = len(certified)
    entry["total_adjusted_strokes"] = sum(
        (r["adjusted_gross"] or 0) for r in certified
    )
    entry["avg_scoring_differential"] = calc.average_differential(
        [r["scoring_differential"] for r in certified]
    )
    return entry


def entry_certified_penalty_strokes(entry):
    return sum(
        r["rules_penalty_strokes"]
        for r in rounds_of_entry(entry["id"])
        if r["status"] == "CERTIFIED"
    )


def entry_has_no_card(entry):
    return any(r["status"] == "NO_CARD" for r in rounds_of_entry(entry["id"]))


# ---------------------------------------------------------------------------
# rankings
# ---------------------------------------------------------------------------
def ranking_pool(member):
    season = db.seasons.get(member["season_id"])
    window_start = season["ranking_window_start_date"] if season else None
    pool = []
    for entry in entries_of_member(member["id"]):
        if entry["entry_status"] != "FINISHED":
            continue
        if entry["event_points"] is None:
            continue
        tournament = tournament_of_entry(entry)
        if tournament is None or tournament["status"] != "COMPLETED":
            continue
        if window_start is not None and tournament["start_date"] < window_start:
            continue
        pool.append((entry, tournament))
    return pool


def recompute_provisional(member):
    pool = ranking_pool(member)
    points = calc.provisional_points([e["event_points"] for e, _ in pool])
    count = len(pool)
    if (
        member["provisional_ranking_points"] != points
        or member["provisional_counted_events"] != count
    ):
        member["provisional_ranking_points"] = points
        member["provisional_counted_events"] = count
        bump(member)
    return member


def run_ranking(season, as_of_date):
    members = [m for m in db.members.values() if m["season_id"] == season["id"]]
    members.sort(key=lambda m: (m["created_at"], m["_seq"]))
    epoch = season["ranking_epoch"] + 1

    with_pool = []
    for member in members:
        pool = ranking_pool(member)
        if not pool:
            if member["certified_rank_position"] is not None:
                member["certified_rank_position"] = None
                bump(member)
            continue
        pool.sort(
            key=lambda pair: (
                -calc.D(pair[0]["event_points"]),
                pair[1]["start_date"],
                pair[0]["created_at"],
                pair[0]["_seq"],
            )
        )
        best = pool[: calc.CERTIFIED_COUNTED_MIN_DIVISOR]
        points = calc.certified_points([e["event_points"] for e, _ in best])
        count = len(best)
        changed = (
            member["certified_ranking_points"] != points
            or member["certified_counted_events"] != count
        )
        member["certified_ranking_points"] = points
        member["certified_counted_events"] = count
        with_pool.append(member)
        if changed:
            bump(member)

    rankable = [
        m
        for m in with_pool
        if m["eligibility_status"] in ("VERIFIED", "SUSPENDED")
        and m["certified_counted_events"] >= 1
    ]
    rankable.sort(
        key=lambda m: (
            -calc.D(m["certified_ranking_points"]),
            -m["certified_counted_events"],
            m["created_at"],
            m["_seq"],
        )
    )
    ranked_ids = set()
    position = 1
    for member in rankable:
        member["certified_rank_position"] = position
        member["last_ranking_epoch"] = epoch
        ranked_ids.add(member["id"])
        bump(member)
        position += 1
    for member in with_pool:
        if member["id"] not in ranked_ids and member["certified_rank_position"] is not None:
            member["certified_rank_position"] = None
            bump(member)

    season["ranking_epoch"] = epoch
    season["last_ranking_run_at"] = clock_iso()
    season["last_ranking_as_of_date"] = as_of_date or clock().date().isoformat()
    season["ranked_member_count"] = len(ranked_ids)
    bump(season)
    return season


# ---------------------------------------------------------------------------
# finish order, event points and completion
# ---------------------------------------------------------------------------
def assign_finish_positions(tournament):
    rows = entries_of_tournament(tournament["id"])
    finishers = [
        e
        for e in rows
        if e["entry_status"] == "FINISHED" and not entry_has_no_card(e)
    ]
    finishers.sort(
        key=lambda e: (
            e["total_adjusted_strokes"],
            entry_certified_penalty_strokes(e),
            e["submitted_at"] or "",
            e["created_at"],
            e["_seq"],
        )
    )
    ranked = set()
    position = 1
    for entry in finishers:
        if entry["finish_position"] != position:
            entry["finish_position"] = position
            bump(entry)
        ranked.add(entry["id"])
        position += 1
    for entry in rows:
        if entry["id"] in ranked:
            continue
        if entry["finish_position"] is not None:
            entry["finish_position"] = None
            bump(entry)
    return finishers


def assign_event_points(tournament, finishers):
    factor = tournament["field_quality_factor"]
    if factor is None:
        factor = 1.00
    finisher_ids = set(e["id"] for e in finishers)
    for entry in entries_of_tournament(tournament["id"]):
        if entry["id"] in finisher_ids:
            points = calc.event_points(
                tournament["tier"],
                factor,
                entry["finish_position"],
                entry["avg_scoring_differential"],
            )
        elif entry["entry_status"] in ("DISQUALIFIED", "FINISHED"):
            points = 0.00
        else:
            continue
        if entry["event_points"] != points:
            entry["event_points"] = points
            bump(entry)


def mint_qualifier_grant(tournament, winner_entry):
    target_id = tournament.get("qualifies_into_tournament_id")
    if not target_id or winner_entry is None:
        return None
    target = db.tournaments.get(target_id)
    if target is None:
        return None
    grant = new_row()
    grant.update(
        {
            "member_id": winner_entry["member_id"],
            "tournament_id": target["id"],
            "source_tournament_id": tournament["id"],
            "category": "QUALIFIER_WINNER",
            "expires_at": target["entry_close_at"],
            "status": "ACTIVE",
            "consumed_by_entry_id": None,
        }
    )
    return insert("exemption_grants", grant)


def complete_tournament(tournament):
    """The fixed seven-step completion sequence."""
    # First: finish positions.
    finishers = assign_finish_positions(tournament)
    # Second: event points.
    assign_event_points(tournament, finishers)
    # The tournament is COMPLETED from here on, so the ranking pool sees it.
    tournament["status"] = "COMPLETED"
    # Third: live provisional rankings for every affected junior.
    seen = set()
    for entry in entries_of_tournament(tournament["id"]):
        if entry["member_id"] in seen:
            continue
        seen.add(entry["member_id"])
        member = member_of_entry(entry)
        if member is not None:
            recompute_provisional(member)
    # Fourth: the money.
    for entry in entries_of_tournament(tournament["id"]):
        if entry["entry_status"] == "FINISHED" and (entry["aid_award_cents"] or 0) > 0:
            disburse_award(entry)
    # Fifth: the winner.
    winner = None
    for entry in entries_of_tournament(tournament["id"]):
        if entry["finish_position"] == 1:
            winner = entry
            break
    tournament["winner_entry_id"] = winner["id"] if winner else None
    # Sixth: the qualifier chain.
    mint_qualifier_grant(tournament, winner)
    # Seventh: status, completed_at, version.
    tournament["completed_at"] = clock_iso()
    recompute_census(tournament)
    bump(tournament)
    return tournament


def maybe_complete_tournament(tournament):
    """Compound bubble-up: IN_PROGRESS -> COMPLETED when the field has settled."""
    if tournament["status"] != "IN_PROGRESS":
        return False
    if tournament["accepted_count"] < 1:
        return False
    for entry in entries_of_tournament(tournament["id"]):
        if entry["entry_status"] in ("ACCEPTED", "COMPETING"):
            return False
    complete_tournament(tournament)
    return True


# ---------------------------------------------------------------------------
# leaving the field
# ---------------------------------------------------------------------------
def refund_fee(entry):
    if entry["fee_status"] in ("PAID", "AID_COVERED", "AID_PARTIAL"):
        entry["fee_status"] = "REFUNDED"
        entry["refunded_cents"] = entry["amount_paid_cents"]
        entry["amount_paid_cents"] = 0
        return True
    return False


def forfeit_fee(entry):
    if entry["fee_status"] in ("PAID", "AID_COVERED", "AID_PARTIAL", "UNPAID"):
        entry["fee_status"] = "FORFEITED_FEE"
        entry["refunded_cents"] = 0
        entry["net_fee_due_cents"] = 0
        return True
    return False


def forfeit_entry(entry, tournament, charge_late_withdrawal):
    """ACCEPTED -> FORFEITED, with the less generous compensation."""
    entry["entry_status"] = "FORFEITED"
    entry["withdrawn_at"] = clock_iso()
    forfeit_fee(entry)
    disburse_award(entry)
    bump(entry)
    if charge_late_withdrawal:
        member = member_of_entry(entry)
        if member is not None:
            member["late_withdrawal_count"] += 1
            bump(member)
    recompute_census(tournament)
    recompute_field_quality(tournament)
    bump(tournament)
    promote_from_waitlist(tournament)
    return entry


def withdraw_entry(entry, tournament):
    """The withdrawal branch: full compensation of every reservation held."""
    previous_status = entry["entry_status"]
    entry["entry_status"] = "WITHDRAWN"
    entry["withdrawn_at"] = clock_iso()
    if refund_fee(entry):
        entry["net_fee_due_cents"] = 0
    if previous_status == "WAITLISTED":
        entry["waitlist_position"] = None
    release_award(entry)
    restore_grant(entry)
    bump(entry)
    if previous_status == "WAITLISTED":
        renumber_waitlist(tournament)
    recompute_census(tournament)
    recompute_field_quality(tournament)
    bump(tournament)
    if previous_status in ("ACCEPTED", "COMPETING"):
        promote_from_waitlist(tournament)
    return entry


def cancel_tournament(tournament, reason):
    live = [
        e
        for e in entries_of_tournament(tournament["id"])
        if e["entry_status"] in ("APPLIED", "WAITLISTED", "ACCEPTED", "COMPETING")
    ]
    live.sort(key=lambda e: (e["created_at"], e["_seq"]))
    for entry in live:
        entry["entry_status"] = "CANCELLED"
        refund_fee(entry)
        release_award(entry)
        restore_grant(entry)
        bump(entry)
    for rnd in rounds_of_tournament(tournament["id"]):
        if rnd["status"] == "SCHEDULED":
            rnd["status"] = "NO_CARD"
            bump(rnd)
    recompute_census(tournament)
    recompute_field_quality(tournament)
    tournament["status"] = "CANCELLED"
    tournament["cancellation_reason"] = reason
    bump(tournament)
    return tournament


def disqualify_entry_for_round(entry, tournament):
    previous = entry["entry_status"]
    if previous not in ("COMPETING", "FINISHED"):
        return entry
    entry["entry_status"] = "DISQUALIFIED"
    entry["event_points"] = 0.00
    if previous == "FINISHED":
        entry["finish_position"] = None
    bump(entry)
    recompute_census(tournament)
    bump(tournament)
    member = member_of_entry(entry)
    if member is not None:
        recompute_provisional(member)
    maybe_complete_tournament(tournament)
    return entry


# ---------------------------------------------------------------------------
# conduct cascades
# ---------------------------------------------------------------------------
def venue_ban(member, case):
    tournament = db.tournaments.get(case["tournament_id"])
    if tournament is None:
        return
    for entry in entries_of_tournament(tournament["id"]):
        if entry["member_id"] != member["id"]:
            continue
        if entry["entry_status"] != "ACCEPTED":
            continue
        forfeit_entry(entry, tournament, charge_late_withdrawal=False)


def suspend_member(member, cumulative_points):
    """The five-hop MEMBER_SUSPENSION cascade."""
    member["eligibility_status"] = "SUSPENDED"
    member["conduct_points"] = cumulative_points
    bump(member)

    rows = entries_of_member(member["id"])
    rows.sort(key=lambda e: (e["created_at"], e["_seq"]))

    touched_tournaments = {}
    for entry in rows:
        if entry["entry_status"] in ("APPLIED", "WAITLISTED"):
            was_waitlisted = entry["entry_status"] == "WAITLISTED"
            entry["entry_status"] = "REJECTED"
            entry["rejection_reason"] = "MEMBER_SUSPENDED"
            if was_waitlisted:
                entry["waitlist_position"] = None
            bump(entry)
            tournament = tournament_of_entry(entry)
            if tournament is not None:
                touched_tournaments[tournament["id"]] = tournament
                if was_waitlisted:
                    renumber_waitlist(tournament)

    for grant in list(db.exemption_grants.values()):
        if grant["member_id"] == member["id"] and grant["status"] == "ACTIVE":
            grant["status"] = "REVOKED"
            bump(grant)

    for entry in rows:
        if entry["entry_status"] != "ACCEPTED":
            continue
        tournament = tournament_of_entry(entry)
        if tournament is None or tournament["status"] != "FIELD_SET":
            continue
        touched_tournaments[tournament["id"]] = tournament
        forfeit_entry(entry, tournament, charge_late_withdrawal=False)

    for tournament in touched_tournaments.values():
        recompute_census(tournament)
        recompute_field_quality(tournament)
        bump(tournament)
    return member


def conduct_prior_points(member, exclude_case_id):
    window_start = clock() - timedelta(days=calc.CONDUCT_WINDOW_DAYS)
    total = 0
    for case in db.conduct_cases.values():
        if case["member_id"] != member["id"]:
            continue
        if case["id"] == exclude_case_id:
            continue
        if case["status"] != "SANCTIONED":
            continue
        decided = dt_of(case["decided_at"])
        if decided is None or decided < window_start:
            continue
        total += case["points_assessed"] or 0
    return total
