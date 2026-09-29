"""Lookups, derived-field recomputation and cascades."""

from datetime import timedelta

from flask import g

from db import (
    clock_now,
    db,
    dt_of,
    insert,
    iso,
    now_iso,
    set_fields,
    sorted_rows,
    touch,
)
from services import calc

TERMINAL_AUDIT_STATES = ("COMPLETE", "TERMINATED")
PENDING_ROUND_STATES = ("SELECTED", "TALLYING", "REVIEW_REQUIRED")
# A tally contributes to the round / audit error ledgers from the moment it is
# submitted; passing through board adjudication does not withdraw its counts
# (PRD 3.7: an adjudication "re-derives the round counters and the audit
# measure exactly as a submission would").
LIVE_TALLY_STATES = ("SUBMITTED", "PENDING_ADJUDICATION", "CERTIFIED")
TERMINAL_RECOUNT_STATES = ("COMPLETED", "WITHDRAWN", "DENIED")
CONTEST_WINDOW_DAYS = 10


# ---------------------------------------------------------------------------
# lookups
# ---------------------------------------------------------------------------


def contests_of_election(election):
    return [c for c in db.contests.values() if c["election_id"] == election["id"]]


def batches_of_contest(contest):
    return [b for b in db.ballot_batches.values() if b["contest_id"] == contest["id"]]


def audits_of_contest(contest):
    return [a for a in db.audits.values() if a["contest_id"] == contest["id"]]


def audits_of_election(election):
    out = []
    for contest in contests_of_election(election):
        out.extend(audits_of_contest(contest))
    return out


def recounts_of_contest(contest):
    return [r for r in db.recounts.values() if r["contest_id"] == contest["id"]]


def rounds_of_audit(audit):
    rounds = [r for r in db.audit_rounds.values() if r["audit_id"] == audit["id"]]
    return sorted(rounds, key=lambda r: (r["round_number"], r.get("_seq", 0)))


def audit_batches_of_round(rnd):
    batches = [
        ab for ab in db.audit_batches.values() if ab["audit_round_id"] == rnd["id"]
    ]
    return sorted(batches, key=lambda ab: (ab["selection_index"], ab.get("_seq", 0)))


def audit_batches_of_audit(audit):
    out = []
    for rnd in rounds_of_audit(audit):
        out.extend(audit_batches_of_round(rnd))
    return out


def tallies_of_audit_batch(audit_batch):
    return [
        t
        for t in db.manual_tallies.values()
        if t["audit_batch_id"] == audit_batch["id"]
    ]


def tallies_of_round(rnd):
    out = []
    for audit_batch in audit_batches_of_round(rnd):
        out.extend(tallies_of_audit_batch(audit_batch))
    return out


def tallies_of_audit(audit):
    out = []
    for rnd in rounds_of_audit(audit):
        out.extend(tallies_of_round(rnd))
    return out


def tallies_of_ballot_batch(ballot_batch):
    audit_batch_ids = set(
        ab["id"]
        for ab in db.audit_batches.values()
        if ab["ballot_batch_id"] == ballot_batch["id"]
    )
    return [
        t for t in db.manual_tallies.values() if t["audit_batch_id"] in audit_batch_ids
    ]


def tallies_of_team(team):
    return [
        t for t in db.manual_tallies.values() if t["tally_team_id"] == team["id"]
    ]


def discrepancies_of_tally(tally):
    return [
        d for d in db.discrepancies.values() if d["manual_tally_id"] == tally["id"]
    ]


def interpretations_of_tally(tally):
    return [
        i
        for i in db.ballot_interpretations.values()
        if i["manual_tally_id"] == tally["id"]
    ]


def actions_of_discrepancy(discrepancy):
    return [
        a
        for a in db.corrective_actions.values()
        if a["discrepancy_id"] == discrepancy["id"]
    ]


def credentials_of_election(election):
    return [
        c
        for c in db.observer_credentials.values()
        if c["election_id"] == election["id"]
    ]


def custody_events_of_batch(ballot_batch):
    events = [
        e
        for e in db.custody_events.values()
        if e["ballot_batch_id"] == ballot_batch["id"]
    ]
    return sorted(events, key=lambda e: e["sequence_no"])


def tally_chain(tally):
    audit_batch = db.audit_batches.get(tally["audit_batch_id"])
    rnd = db.audit_rounds.get(audit_batch["audit_round_id"])
    audit = db.audits.get(rnd["audit_id"])
    contest = db.contests.get(audit["contest_id"])
    election = db.elections.get(contest["election_id"])
    return audit_batch, rnd, audit, contest, election


def audit_batch_chain(audit_batch):
    rnd = db.audit_rounds.get(audit_batch["audit_round_id"])
    audit = db.audits.get(rnd["audit_id"])
    contest = db.contests.get(audit["contest_id"])
    election = db.elections.get(contest["election_id"])
    return rnd, audit, contest, election


def audit_chain(audit):
    contest = db.contests.get(audit["contest_id"])
    election = db.elections.get(contest["election_id"]) if contest else None
    return contest, election


def discrepancy_chain(discrepancy):
    tally = db.manual_tallies.get(discrepancy["manual_tally_id"])
    return (tally,) + tally_chain(tally)


def election_of_ballot_batch(ballot_batch):
    return db.elections.get(ballot_batch["election_id"])


# ---------------------------------------------------------------------------
# custody events
# ---------------------------------------------------------------------------


def append_custody_event(ballot_batch, event_type, seal_before, seal_after, note=None,
                         actor_user_id=None, actor_role=None):
    seq = db.custody_seq.get(ballot_batch["id"], 0) + 1
    db.custody_seq[ballot_batch["id"]] = seq
    return insert(
        "custody_events",
        {
            "sequence_no": seq,
            "ballot_batch_id": ballot_batch["id"],
            "event_type": event_type,
            "actor_user_id": actor_user_id
            if actor_user_id is not None
            else getattr(g, "user_id", None),
            "actor_role": actor_role
            if actor_role is not None
            else getattr(g, "role", None),
            "seal_number_before": seal_before,
            "seal_number_after": seal_after,
            "occurred_at": now_iso(),
            "note": note,
        },
        common=False,
    )


# ---------------------------------------------------------------------------
# contest derived fields
# ---------------------------------------------------------------------------


def recompute_contest_margin(contest):
    """Derive winner / runner-up / margins / automatic recount flag."""
    votes = contest.get("reported_votes")
    if not votes:
        return False
    result = calc.contest_margin(
        contest["candidate_names"], votes, contest["ballots_cast"]
    )
    return set_fields(
        contest,
        {
            "winner_name": result["winner_name"],
            "runner_up_name": result["runner_up_name"],
            "margin_votes": result["margin_votes"],
            "margin_pct": calc.fnum(result["margin_pct"]),
            "automatic_recount_required": calc.automatic_recount_required(
                contest["contest_type"], result["margin_pct"]
            ),
        },
    )


def recompute_contest_counts(contest):
    open_recounts = sum(
        1
        for r in recounts_of_contest(contest)
        if r["status"] not in TERMINAL_RECOUNT_STATES
    )
    if set_fields(contest, {"open_recount_count": open_recounts}):
        touch(contest)
        return True
    return False


# ---------------------------------------------------------------------------
# audit ledgers
# ---------------------------------------------------------------------------


def _tally_ledger(tallies):
    counted_ballots = 0
    net_error = 0
    taints = []
    for tally in tallies:
        if tally["status"] not in LIVE_TALLY_STATES:
            continue
        audit_batch = db.audit_batches.get(tally["audit_batch_id"])
        counted_ballots += audit_batch["ballot_count"] if audit_batch else 0
        net_error += tally["net_error_votes"] or 0
        if tally["relative_taint"] is not None:
            taints.append(tally["relative_taint"])
    return counted_ballots, net_error, taints


def recompute_round_ledger(rnd, audit):
    tallies = tallies_of_round(rnd)
    counted_ballots, net_error, taints = _tally_ledger(tallies)
    tally_ids = set(t["id"] for t in tallies)
    discrepancy_count = sum(
        1
        for d in db.discrepancies.values()
        if d["manual_tally_id"] in tally_ids and d["status"] != "VOIDED"
    )
    measure = calc.discrepancy_measure(
        audit["measure_variant"], counted_ballots, net_error, taints
    )
    changed = set_fields(
        rnd,
        {
            "counted_ballots": counted_ballots,
            "cumulative_net_error_votes": net_error,
            "discrepancy_count": discrepancy_count,
            "round_measure": calc.fnum(measure),
        },
    )
    if changed:
        touch(rnd)
    return measure


def recompute_audit_ledger(audit):
    all_rounds = rounds_of_audit(audit)
    live_rounds = [r for r in all_rounds if r["status"] != "SUPERSEDED"]
    tallies = []
    for rnd in live_rounds:
        tallies.extend(tallies_of_round(rnd))
    counted_ballots, net_error, taints = _tally_ledger(tallies)
    measure = calc.discrepancy_measure(
        audit["measure_variant"], counted_ballots, net_error, taints
    )
    sampled = sum(len(audit_batches_of_round(r)) for r in live_rounds)
    changed = set_fields(
        audit,
        {
            "counted_ballots": counted_ballots,
            "cumulative_net_error_votes": net_error,
            "discrepancy_measure": calc.fnum(measure),
            "cumulative_sampled_batches": sampled,
        },
    )
    if changed:
        touch(audit)
    return measure


def recompute_planned_sample_size(audit, contest):
    total_batches = len(batches_of_contest(contest))
    planned = calc.planned_sample_size(
        audit, contest.get("margin_votes"), contest.get("ballots_cast"), total_batches
    )
    return set_fields(audit, {"planned_sample_size": planned})


# ---------------------------------------------------------------------------
# timeline projection (calculation 8)
# ---------------------------------------------------------------------------


def project_audit_timeline(audit):
    contest, election = audit_chain(audit)
    if election is None:
        return False
    rounds = rounds_of_audit(audit)
    pending = [r for r in rounds if r["status"] in PENDING_ROUND_STATES]

    hand_count_ballots = 0
    for rnd in pending:
        if not rnd.get("is_full_hand_count"):
            continue
        for audit_batch in audit_batches_of_round(rnd):
            if audit_batch["tally_status"] == "COUNTED":
                continue
            ballot_batch = db.ballot_batches.get(audit_batch["ballot_batch_id"])
            hand_count_ballots += (
                ballot_batch["ballot_count"] if ballot_batch else audit_batch["ballot_count"]
            )

    ballot_hours = calc.hand_count_hours(hand_count_ballots)
    round_hours = calc.ROUND_OVERHEAD_HOURS * len(pending)
    remaining_work_hours = ballot_hours + round_hours

    projected = clock_now() + timedelta(hours=remaining_work_hours)
    deadline = dt_of(election["certification_deadline_at"])
    slack_hours = calc.hours_between(deadline, projected)
    extension_days = calc.extension_days_for(slack_hours)
    effective_deadline = deadline + timedelta(days=extension_days)
    effective_slack = calc.hours_between(effective_deadline, projected)
    status = calc.timeline_status_for(effective_slack)

    changed = set_fields(
        audit,
        {
            "projected_completion_at": iso(projected),
            "slack_hours": calc.fnum(slack_hours),
            "extension_days_granted": extension_days,
            "effective_certification_deadline_at": iso(effective_deadline),
            "effective_slack_hours": calc.fnum(effective_slack),
            "timeline_status": status,
        },
    )
    if changed:
        touch(audit)
    return changed


# ---------------------------------------------------------------------------
# election roll-ups
# ---------------------------------------------------------------------------


def election_derived(election):
    """Return the derived roll-up values without writing them."""
    contests = contests_of_election(election)
    audits = []
    for contest in contests:
        audits.extend(audits_of_contest(contest))
    max_extension = 0
    for audit in audits:
        max_extension = max(max_extension, audit.get("extension_days_granted") or 0)
    deadline = dt_of(election["certification_deadline_at"])
    effective = deadline + timedelta(days=max_extension)
    window_end = effective + timedelta(days=CONTEST_WINDOW_DAYS)
    timeline = calc.worst_timeline(
        [a.get("timeline_status") or "ON_TRACK" for a in audits]
    )
    risk = any(
        a["status"] in ("DISCREPANCY_REVIEW", "ESCALATED_FULL_HAND_COUNT")
        for a in audits
    ) or any(a.get("timeline_status") == "BREACHED" for a in audits)
    open_audits = sum(1 for a in audits if a["status"] not in TERMINAL_AUDIT_STATES)
    open_recounts = 0
    for contest in contests:
        open_recounts += sum(
            1
            for r in recounts_of_contest(contest)
            if r["status"] not in TERMINAL_RECOUNT_STATES
        )
    return {
        "effective_certification_deadline_at": iso(effective),
        "contest_window_ends_at": iso(window_end),
        "timeline_status": timeline,
        "certification_risk_flag": risk,
        "open_audit_count": open_audits,
        "open_recount_count": open_recounts,
    }


def recompute_election(election):
    if election is None or election.get("status") == "CERTIFIED":
        return False
    changed = set_fields(election, election_derived(election))
    if changed:
        touch(election)
    return changed


def recompute_election_status(election):
    """OPEN -> CANVASSED once every contest of the election is canvassed."""
    contests = contests_of_election(election)
    if not contests:
        return False
    if election["status"] != "OPEN":
        return False
    if all(c["status"] in ("CANVASSED", "CERTIFIED") for c in contests):
        election["status"] = "CANVASSED"
        touch(election)
        return True
    return False


# ---------------------------------------------------------------------------
# round / audit escalation cascade
# ---------------------------------------------------------------------------


def cascade_round(rnd, audit, discrepancy_created=False):
    measure = recompute_round_ledger(rnd, audit)
    variant = audit["measure_variant"]
    if (
        rnd["status"] == "TALLYING"
        and discrepancy_created
        and calc.escalates(variant, measure)
    ):
        rnd["status"] = "REVIEW_REQUIRED"
        touch(rnd)
        if audit["status"] == "TALLYING":
            audit["status"] = "DISCREPANCY_REVIEW"
            touch(audit)
    elif rnd["status"] == "REVIEW_REQUIRED" and not calc.escalates(variant, measure):
        rnd["status"] = "TALLYING"
        touch(rnd)
        if audit["status"] == "DISCREPANCY_REVIEW":
            audit["status"] = "TALLYING"
            touch(audit)
    recompute_audit_ledger(audit)
    project_audit_timeline(audit)
    contest, election = audit_chain(audit)
    recompute_election(election)


def latest_live_round(audit):
    live = [r for r in rounds_of_audit(audit) if r["status"] != "SUPERSEDED"]
    return live[-1] if live else None


def report_round(audit):
    """The round whose selection sequence the public report exposes."""
    rounds = rounds_of_audit(audit)
    if not rounds:
        return None
    live = [r for r in rounds if r["status"] != "SUPERSEDED"]
    return live[-1] if live else rounds[-1]


def eligible_pool(audit, contest):
    """Batches of the contest neither quarantined nor already drawn live."""
    drawn = set()
    for rnd in rounds_of_audit(audit):
        if rnd["status"] == "SUPERSEDED":
            continue
        for audit_batch in audit_batches_of_round(rnd):
            drawn.add(audit_batch["ballot_batch_id"])
    pool = [
        b
        for b in batches_of_contest(contest)
        if b["custody_status"] != "QUARANTINED" and b["id"] not in drawn
    ]
    return sorted(pool, key=lambda b: b["batch_label"])


def create_round(audit, contest, pool, sample_size, is_full_hand_count,
                 previous_round):
    round_number = (previous_round["round_number"] + 1) if previous_round else 1
    if is_full_hand_count:
        drawn = list(pool)
    else:
        drawn = calc.draw_batches(
            pool, audit["random_seed"], round_number, sample_size
        )

    rnd = insert(
        "audit_rounds",
        {
            "audit_id": audit["id"],
            "previous_round_id": previous_round["id"] if previous_round else None,
            "round_number": round_number,
            "is_full_hand_count": bool(is_full_hand_count),
            "sample_size_batches": len(drawn),
            "selection_sequence": [b["batch_label"] for b in drawn],
            "counted_ballots": 0,
            "discrepancy_count": 0,
            "cumulative_net_error_votes": 0,
            "round_measure": 0.0,
            "status": "SELECTED",
        },
    )

    for index, ballot_batch in enumerate(drawn):
        insert(
            "audit_batches",
            {
                "audit_round_id": rnd["id"],
                "ballot_batch_id": ballot_batch["id"],
                "selection_index": index,
                "ballot_count": ballot_batch["ballot_count"],
                "retrieval_status": "PENDING_RETRIEVAL",
                "tally_status": "NOT_STARTED",
            },
        )
        ballot_batch["retrieval_authorized_at"] = now_iso()
        touch(ballot_batch)
        append_custody_event(
            ballot_batch,
            "AUTHORIZED",
            ballot_batch["current_seal_number"],
            ballot_batch["current_seal_number"],
        )

    if previous_round is not None and previous_round["status"] != "SUPERSEDED":
        previous_round["status"] = "SUPERSEDED"
        touch(previous_round)
    return rnd


def revoke_retrieval_authorizations(audit):
    for audit_batch in audit_batches_of_audit(audit):
        if audit_batch["retrieval_status"] != "PENDING_RETRIEVAL":
            continue
        ballot_batch = db.ballot_batches.get(audit_batch["ballot_batch_id"])
        if ballot_batch is None or ballot_batch["retrieval_authorized_at"] is None:
            continue
        if _other_audit_holds(audit, ballot_batch):
            continue
        ballot_batch["retrieval_authorized_at"] = None
        touch(ballot_batch)


def _other_audit_holds(audit, ballot_batch):
    for other in db.audits.values():
        if other["id"] == audit["id"]:
            continue
        if other["status"] in TERMINAL_AUDIT_STATES:
            continue
        for audit_batch in audit_batches_of_audit(other):
            if (
                audit_batch["ballot_batch_id"] == ballot_batch["id"]
                and audit_batch["retrieval_status"] == "PENDING_RETRIEVAL"
            ):
                return True
    return False


def terminate_audit(audit, reason):
    audit["status"] = "TERMINATED"
    audit["terminated_reason"] = reason
    audit["public_report_published"] = True
    touch(audit)
    for rnd in rounds_of_audit(audit):
        if rnd["status"] not in ("COMPLETE", "SUPERSEDED"):
            rnd["status"] = "SUPERSEDED"
            touch(rnd)
    revoke_retrieval_authorizations(audit)
    recompute_audit_ledger(audit)
    contest, election = audit_chain(audit)
    recompute_election(election)


def machine_margin_of(contest, ballot_batch):
    winner = contest.get("winner_name")
    runner_up = contest.get("runner_up_name")
    machine = ballot_batch.get("machine_votes") or {}
    if winner is None:
        return 0
    return int(machine.get(winner, 0)) - int(machine.get(runner_up, 0))


def recompute_tally_figures(tally, contest, audit_batch, ballot_batch):
    """Derive the machine/manual margins, net error and relative taint."""
    winner = contest.get("winner_name")
    runner_up = contest.get("runner_up_name")
    counted = tally.get("counted_votes") or {}
    machine_margin = machine_margin_of(contest, ballot_batch)
    if winner is None:
        manual_margin = 0
    else:
        manual_margin = int(counted.get(winner, 0)) - int(counted.get(runner_up, 0))
    net_error = machine_margin - manual_margin
    taint = calc.relative_taint(
        net_error, contest.get("margin_votes"), audit_batch["ballot_count"]
    )
    tally["machine_margin_votes"] = machine_margin
    tally["manual_margin_votes"] = manual_margin
    tally["net_error_votes"] = net_error
    tally["relative_taint"] = calc.fnum(taint)


def sync_discrepancy_for_tally(tally, contest, audit_batch):
    """Create / update / void the tally's discrepancy after a recount of votes.

    Returns True when a brand-new discrepancy row was created.
    """
    counted = tally.get("counted_votes") or {}
    ballot_batch = db.ballot_batches.get(audit_batch["ballot_batch_id"])
    machine = (ballot_batch or {}).get("machine_votes") or {}
    counted_sum = sum(counted.values())
    machine_sum = sum(machine.values())
    net = tally.get("net_error_votes") or 0

    needed = net != 0 or counted_sum != machine_sum
    existing = [
        d
        for d in discrepancies_of_tally(tally)
        if d["status"] in ("OPEN", "DOCUMENTED")
    ]

    if not needed:
        for row in existing:
            row["status"] = "VOIDED"
            touch(row)
        return False

    if net > 0:
        dtype = "OVERSTATEMENT"
    elif net < 0:
        dtype = "UNDERSTATEMENT"
    else:
        dtype = "BALLOT_COUNT_MISMATCH"
    magnitude = abs(net) if net != 0 else abs(counted_sum - machine_sum)

    if existing:
        row = sorted_rows(existing)[0]
        if set_fields(
            row,
            {
                "discrepancy_type": dtype,
                "magnitude_votes": magnitude,
                "relative_taint": tally["relative_taint"],
            },
        ):
            touch(row)
        return False

    insert(
        "discrepancies",
        {
            "manual_tally_id": tally["id"],
            "discrepancy_type": dtype,
            "magnitude_votes": magnitude,
            "relative_taint": tally["relative_taint"],
            "status": "OPEN",
            "documentation_note": None,
            "escalation_reason": None,
            "resolution_note": None,
            "resolved_at": None,
        },
    )
    return True
