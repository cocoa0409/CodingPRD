"""Domain logic: serializers, edition ledger reconciliation, score aggregates,
replacement/promotion cascades, logical-clock sweeps, and the IRV tally."""

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from store import DB
from util import fmt_ts, new_id, now

# ------------------------------------------------------------------ constants
CATEGORIES = ["NARRATIVE_FEATURE", "DOCUMENTARY_FEATURE", "SHORT_FILM", "EPISODIC"]
PREMIERE_REQUIREMENTS = ["WORLD_REQUIRED", "NORTH_AMERICA_REQUIRED", "US_REQUIRED", "NONE"]
PREMIERE_STATUSES = ["WORLD", "INTERNATIONAL", "NORTH_AMERICA", "US", "REGIONAL", "NONE"]
FORMATS = ["DCP_2K", "DCP_4K", "FILM_35MM", "PRORES_4444"]
SENIORITIES = ["STAFF", "SENIOR", "LEAD"]
RECOMMENDATIONS = ["STRONG_ADVOCATE", "ADVOCATE", "NEUTRAL", "PASS", "STRONG_PASS"]
SECTIONS = ["US_DRAMATIC", "US_DOCUMENTARY", "WORLD_CINEMA_DRAMATIC", "NEXT",
            "PREMIERES", "MIDNIGHT", "SHORTS"]
SLOT_TYPES = ["PREMIERE", "PUBLIC", "PRESS_INDUSTRY", "AWARDS_ENCORE"]
RIGHTS_SCOPES = ["FESTIVAL_WORLD", "FESTIVAL_NORTH_AMERICA", "FESTIVAL_US"]
EDITION_STATUSES = ["SETUP", "INTAKE_OPEN", "INTAKE_CLOSED", "SCREENING",
                    "DELIBERATION", "SLATE_LOCKED", "NOTIFICATION", "SCHEDULING",
                    "FESTIVAL_LIVE", "AWARDS_NIGHT", "CLOSED"]

WEIGHTS = {"STAFF": Decimal("1.0"), "SENIOR": Decimal("1.5"), "LEAD": Decimal("2.0")}
SLATE_COMPOSITE_THRESHOLD = Decimal("7.500")
QA_MINUTES = 15
STUDENT_DISCOUNT_PCT = Decimal("0.25")
MEMBER_DISCOUNT_PCT = Decimal("0.10")
FULL_REFUND_WINDOW_HOURS = 48
WITHDRAWAL_REFUND_PCT = Decimal("0.50")
DOMESTIC_BASE_CENTS = 50000
INTERNATIONAL_BASE_CENTS = 150000
PER_EXTRA_DELEGATE_CENTS = 20000
MAX_DELEGATES_COVERED = 2
PER_FILM_CAP_CENTS = 200000
CANCELLATION_PENALTY_PCT = Decimal("0.25")

PREMIERE_SATISFACTION = {
    "WORLD_REQUIRED": {"WORLD"},
    "NORTH_AMERICA_REQUIRED": {"WORLD", "INTERNATIONAL", "NORTH_AMERICA"},
    "US_REQUIRED": {"WORLD", "INTERNATIONAL", "NORTH_AMERICA", "US"},
    "NONE": {"WORLD", "INTERNATIONAL", "NORTH_AMERICA", "US", "REGIONAL", "NONE"},
}


def round_half_up_cents(value):
    """Decimal -> whole cents, ROUND_HALF_UP, returned as int."""
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ------------------------------------------------------------------- helpers
def new_rec(fields):
    """Create a record with system common fields (§2.6)."""
    rec = dict(fields)
    rec["id"] = new_id()
    ts = now()
    rec["created_at"] = ts
    rec["updated_at"] = ts
    rec["version"] = 1
    rec["_seq"] = DB.next_seq()
    return rec


def new_ballot(fields):
    """JuryVote carries only id and created_at — immutable once cast (§2.6)."""
    rec = dict(fields)
    rec["id"] = new_id()
    ts = now()
    rec["created_at"] = ts
    rec["submitted_at"] = ts
    rec["_seq"] = DB.next_seq()
    return rec


def touch(rec):
    rec["updated_at"] = now()
    rec["version"] += 1


# --------------------------------------------------------------- serializers
def ser_edition(e):
    return {
        "id": e["id"], "year": e["year"],
        "host_country_code": e["host_country_code"],
        "intake_open_at": fmt_ts(e["intake_open_at"]),
        "early_deadline_at": fmt_ts(e["early_deadline_at"]),
        "regular_deadline_at": fmt_ts(e["regular_deadline_at"]),
        "late_deadline_at": fmt_ts(e["late_deadline_at"]),
        "rsvp_window_days": e["rsvp_window_days"],
        "festival_start_at": fmt_ts(e["festival_start_at"]),
        "festival_end_at": fmt_ts(e["festival_end_at"]),
        "hotel_nights_pool": e["hotel_nights_pool"],
        "travel_budget_cents": e["travel_budget_cents"],
        "prize_pool_cents": e["prize_pool_cents"],
        "status": e["status"],
        "total_fees_collected_cents": e["total_fees_collected_cents"],
        "total_refunded_cents": e["total_refunded_cents"],
        "hotel_nights_allocated": e["hotel_nights_allocated"],
        "hotel_nights_remaining": e["hotel_nights_remaining"],
        "travel_committed_cents": e["travel_committed_cents"],
        "travel_penalty_sink_cents": e["travel_penalty_sink_cents"],
        "travel_budget_remaining": e["travel_budget_remaining"],
        "prize_committed_cents": e["prize_committed_cents"],
        "prize_disbursed_cents": e["prize_disbursed_cents"],
        "created_at": fmt_ts(e["created_at"]),
        "updated_at": fmt_ts(e["updated_at"]),
        "version": e["version"],
    }


def ser_category_config(c):
    return {
        "id": c["id"], "edition_id": c["edition_id"], "category": c["category"],
        "min_runtime_minutes": c["min_runtime_minutes"],
        "max_runtime_minutes": c["max_runtime_minutes"],
        "premiere_requirement": c["premiere_requirement"],
        "completion_cutoff": c["completion_cutoff"].isoformat(),
        "early_fee_cents": c["early_fee_cents"],
        "regular_fee_cents": c["regular_fee_cents"],
        "late_fee_cents": c["late_fee_cents"],
        "screener_count_required": c["screener_count_required"],
        "created_at": fmt_ts(c["created_at"]),
        "updated_at": fmt_ts(c["updated_at"]),
        "version": c["version"],
    }


def ser_submitter(s):
    return {
        "id": s["id"], "legal_name": s["legal_name"], "email": s["email"],
        "country_of_residence": s["country_of_residence"],
        "is_student": s["is_student"], "is_member": s["is_member"],
        "created_at": fmt_ts(s["created_at"]),
        "updated_at": fmt_ts(s["updated_at"]),
        "version": s["version"],
    }


def ser_programmer(p):
    return {
        "id": p["id"], "display_name": p["display_name"], "email": p["email"],
        "seniority": p["seniority"],
        "categories_covered": list(p["categories_covered"]),
        "coi_production_companies": list(p["coi_production_companies"]),
        "max_active_assignments": p["max_active_assignments"],
        "active": p["active"],
        "active_assignment_count": active_assignment_count(p["id"]),
        "created_at": fmt_ts(p["created_at"]),
        "updated_at": fmt_ts(p["updated_at"]),
        "version": p["version"],
    }


def ser_submission(s):
    return {
        "id": s["id"], "edition_id": s["edition_id"],
        "submitter_id": s["submitter_id"], "category": s["category"],
        "title": s["title"], "runtime_minutes": s["runtime_minutes"],
        "completion_date": s["completion_date"].isoformat(),
        "premiere_status": s["premiere_status"],
        "production_company": s["production_company"],
        "format": s["format"], "status": s["status"],
        "payment_status": s["payment_status"],
        "needs_info_resolved": s["needs_info_resolved"],
        "provisional_score": (float(s["provisional_score"])
                              if s["provisional_score"] is not None else None),
        "composite_score": (float(s["composite_score"])
                            if s["composite_score"] is not None else None),
        "award_names": list(s["award_names"]),
        "created_at": fmt_ts(s["created_at"]),
        "updated_at": fmt_ts(s["updated_at"]),
        "version": s["version"],
    }


def ser_payment(p):
    return {
        "id": p["id"], "submission_id": p["submission_id"],
        "tier_applied": p["tier_applied"], "base_fee_cents": p["base_fee_cents"],
        "student_discount_applied": p["student_discount_applied"],
        "member_discount_applied": p["member_discount_applied"],
        "student_discount_cents": p["student_discount_cents"],
        "member_discount_cents": p["member_discount_cents"],
        "amount_cents": p["amount_cents"], "status": p["status"],
        "paid_at": fmt_ts(p["paid_at"]),
        "refunded_amount_cents": p["refunded_amount_cents"],
        "created_at": fmt_ts(p["created_at"]),
        "updated_at": fmt_ts(p["updated_at"]),
        "version": p["version"],
    }


def ser_assignment(a):
    return {
        "id": a["id"], "submission_id": a["submission_id"],
        "programmer_id": a["programmer_id"], "due_at": fmt_ts(a["due_at"]),
        "status": a["status"],
        "replaced_by_assignment_id": a["replaced_by_assignment_id"],
        "created_at": fmt_ts(a["created_at"]),
        "updated_at": fmt_ts(a["updated_at"]),
        "version": a["version"],
    }


def ser_score(s):
    return {
        "id": s["id"], "assignment_id": s["assignment_id"],
        "originality": s["originality"], "craft": s["craft"],
        "story": s["story"], "overall": s["overall"],
        "recommendation": s["recommendation"], "locked": s["locked"],
        "created_at": fmt_ts(s["created_at"]),
        "updated_at": fmt_ts(s["updated_at"]),
        "version": s["version"],
    }


def ser_slate(s):
    return {
        "id": s["id"], "edition_id": s["edition_id"], "section": s["section"],
        "capacity_slots": s["capacity_slots"], "status": s["status"],
        "last_entry_added_by": s["last_entry_added_by"],
        "entry_count": entry_count(s["id"]),
        "locked_at": fmt_ts(s["locked_at"]),
        "created_at": fmt_ts(s["created_at"]),
        "updated_at": fmt_ts(s["updated_at"]),
        "version": s["version"],
    }


def ser_entry(e):
    return {
        "id": e["id"], "slate_id": e["slate_id"],
        "submission_id": e["submission_id"],
        "rank_position": e["rank_position"], "lane": e["lane"],
        "status": e["status"],
        "rsvp_deadline_at": fmt_ts(e["rsvp_deadline_at"]),
        "locked_composite_score": (float(e["locked_composite_score"])
                                   if e["locked_composite_score"] is not None
                                   else None),
        "created_at": fmt_ts(e["created_at"]),
        "updated_at": fmt_ts(e["updated_at"]),
        "version": e["version"],
    }


def ser_venue(v):
    return {
        "id": v["id"], "edition_id": v["edition_id"], "name": v["name"],
        "seat_capacity": v["seat_capacity"],
        "formats_supported": list(v["formats_supported"]),
        "turnover_minutes": v["turnover_minutes"],
        "created_at": fmt_ts(v["created_at"]),
        "updated_at": fmt_ts(v["updated_at"]),
        "version": v["version"],
    }


def ser_slot(s):
    return {
        "id": s["id"], "venue_id": s["venue_id"],
        "slate_entry_id": s["slate_entry_id"], "slot_type": s["slot_type"],
        "start_at": fmt_ts(s["start_at"]), "end_at": fmt_ts(s["end_at"]),
        "status": s["status"],
        "created_at": fmt_ts(s["created_at"]),
        "updated_at": fmt_ts(s["updated_at"]),
        "version": s["version"],
    }


def ser_package(p):
    return {
        "id": p["id"], "submission_id": p["submission_id"],
        "edition_id": p["edition_id"], "delegate_count": p["delegate_count"],
        "origin_country_code": p["origin_country_code"],
        "is_international": p["is_international"],
        "hotel_nights_requested": p["hotel_nights_requested"],
        "hotel_nights_allocated": p["hotel_nights_allocated"],
        "raw_stipend_cents": p["raw_stipend_cents"],
        "stipend_cents": p["stipend_cents"],
        "penalty_cents": p["penalty_cents"], "status": p["status"],
        "created_at": fmt_ts(p["created_at"]),
        "updated_at": fmt_ts(p["updated_at"]),
        "version": p["version"],
    }


def ser_agreement(a):
    return {
        "id": a["id"], "submission_id": a["submission_id"],
        "slate_entry_id": a["slate_entry_id"], "rights_scope": a["rights_scope"],
        "licensed_screening_count": a["licensed_screening_count"],
        "used_screening_count": a["used_screening_count"],
        "exclusivity_until": fmt_ts(a["exclusivity_until"]),
        "revenue_share_pct": a["revenue_share_pct"],
        "submission_version_at_signing": a["submission_version_at_signing"],
        "status": a["status"],
        "created_at": fmt_ts(a["created_at"]),
        "updated_at": fmt_ts(a["updated_at"]),
        "version": a["version"],
    }


def ser_juror(j):
    return {
        "id": j["id"], "edition_id": j["edition_id"],
        "display_name": j["display_name"],
        "coi_production_companies": list(j["coi_production_companies"]),
        "created_at": fmt_ts(j["created_at"]),
        "updated_at": fmt_ts(j["updated_at"]),
        "version": j["version"],
    }


def ser_award(a):
    return {
        "id": a["id"], "edition_id": a["edition_id"], "name": a["name"],
        "section": a["section"], "prize_cents": a["prize_cents"],
        "assigned_juror_ids": list(a["assigned_juror_ids"]),
        "status": a["status"],
        "winner_submission_id": a["winner_submission_id"],
        "rounds_log": list(a["rounds_log"]),
        "disbursed_amount_cents": a["disbursed_amount_cents"],
        "created_at": fmt_ts(a["created_at"]),
        "updated_at": fmt_ts(a["updated_at"]),
        "version": a["version"],
    }


def ser_ballot(b):
    return {
        "id": b["id"], "award_id": b["award_id"], "juror_id": b["juror_id"],
        "ranked_submission_ids": list(b["ranked_submission_ids"]),
        "submitted_at": fmt_ts(b["submitted_at"]),
        "created_at": fmt_ts(b["created_at"]),
    }


# --------------------------------------------------------- computed counters
def active_assignment_count(programmer_id):
    return sum(1 for a in DB.assignments.values()
               if a["programmer_id"] == programmer_id and a["status"] == "ASSIGNED")


def entry_count(slate_id):
    return sum(1 for e in DB.entries.values()
               if e["slate_id"] == slate_id and e["status"] != "DROPPED")


def category_config_for(edition_id, category):
    for c in DB.category_configs.values():
        if c["edition_id"] == edition_id and c["category"] == category:
            return c
    return None


def submission_edition(submission):
    return DB.editions.get(submission["edition_id"])


def entry_submission(entry):
    return DB.submissions.get(entry["submission_id"])


def entry_slate(entry):
    return DB.slates.get(entry["slate_id"])


def package_submission(package):
    return DB.submissions.get(package["submission_id"])


def agreement_for_submission(submission_id):
    for a in DB.agreements.values():
        if a["submission_id"] == submission_id:
            return a
    return None


def entries_of_submission(submission_id):
    return [e for e in DB.entries.values() if e["submission_id"] == submission_id]


# ----------------------------------------------------- edition ledger (§2.8)
def recompute_edition_ledger(edition):
    """Derived ledger: recomputed immediately on any FeePayment,
    TravelPackage, or Award mutation; every recomputation mutates the edition
    (updated_at refreshed, version incremented per §2.6/§2.8)."""
    edition_id = edition["id"]
    sub_ids = {s["id"] for s in DB.submissions.values()
               if s["edition_id"] == edition_id}
    payments = [p for p in DB.fee_payments.values()
                if p["submission_id"] in sub_ids]
    edition["total_fees_collected_cents"] = sum(
        p["amount_cents"] for p in payments
        if p["status"] in ("SUCCEEDED", "PARTIALLY_REFUNDED"))
    edition["total_refunded_cents"] = sum(
        p["refunded_amount_cents"] for p in payments)

    packages = [p for p in DB.packages.values()
                if p["edition_id"] == edition_id]
    edition["travel_committed_cents"] = sum(
        p["stipend_cents"] for p in packages
        if p["status"] in ("APPROVED", "BOOKED", "RECONCILED"))
    edition["travel_penalty_sink_cents"] = sum(
        p["penalty_cents"] for p in packages if p["status"] == "CANCELLED")
    edition["hotel_nights_allocated"] = sum(
        p["hotel_nights_allocated"] for p in packages
        if p["status"] in ("APPROVED", "BOOKED", "RECONCILED"))
    edition["hotel_nights_remaining"] = (
        edition["hotel_nights_pool"] - edition["hotel_nights_allocated"])
    edition["travel_budget_remaining"] = (
        edition["travel_budget_cents"] - edition["travel_committed_cents"]
        - edition["travel_penalty_sink_cents"])

    awards = [a for a in DB.awards.values() if a["edition_id"] == edition_id]
    edition["prize_committed_cents"] = sum(
        a["prize_cents"] for a in awards
        if a["status"] in ("SETUP", "VOTING_OPEN", "TALLIED", "ANNOUNCED",
                           "DISBURSED"))
    edition["prize_disbursed_cents"] = sum(
        a["disbursed_amount_cents"] for a in awards if a["status"] == "DISBURSED")
    touch(edition)


# -------------------------------------------------------- score aggregates
def recompute_submission_scores(submission):
    """provisional = simple mean of overall over SCORED assignments (3 dp,
    half-up, null when zero scores); composite = seniority-weighted mean,
    null until SCORED count >= category.screener_count_required."""
    config = category_config_for(submission["edition_id"], submission["category"])
    scored = []
    for a in DB.assignments.values():
        if a["submission_id"] != submission["id"] or a["status"] != "SCORED":
            continue
        score = next((s for s in DB.scores.values()
                      if s["assignment_id"] == a["id"]), None)
        prog = DB.programmers.get(a["programmer_id"])
        if score is not None and prog is not None:
            scored.append((score, prog))
    if not scored:
        submission["provisional_score"] = None
        submission["composite_score"] = None
        return
    total = sum(Decimal(s["overall"]) for s, _ in scored)
    count = Decimal(len(scored))
    submission["provisional_score"] = (total / count).quantize(
        Decimal("0.001"), rounding=ROUND_HALF_UP)
    required = config["screener_count_required"] if config else 3
    if len(scored) >= required:
        wsum = sum(Decimal(s["overall"]) * WEIGHTS[p["seniority"]]
                   for s, p in scored)
        wtotal = sum(WEIGHTS[p["seniority"]] for _, p in scored)
        submission["composite_score"] = (wsum / wtotal).quantize(
            Decimal("0.001"), rounding=ROUND_HALF_UP)
    else:
        submission["composite_score"] = None


# ------------------------------------------- replacement selector (§3.4)
def replacement_cascade(submission, retired_assignment):
    """Pick a replacement programmer for the same submission: active, covers
    the category, no COI, under cap, never held any assignment for this
    submission; ranked by active_assignment_count ASC then created_at ASC.
    Empty pool => no replacement (replaced_by_assignment_id stays null)."""
    pool = []
    for p in DB.programmers.values():
        if not p["active"]:
            continue
        if submission["category"] not in p["categories_covered"]:
            continue
        if submission["production_company"] in p["coi_production_companies"]:
            continue
        if active_assignment_count(p["id"]) >= p["max_active_assignments"]:
            continue
        if any(a["submission_id"] == submission["id"]
               and a["programmer_id"] == p["id"]
               for a in DB.assignments.values()):
            continue
        pool.append(p)
    if not pool:
        return None
    pool.sort(key=lambda p: (active_assignment_count(p["id"]),
                             p["created_at"], p["_seq"]))
    chosen = pool[0]
    rec = new_rec({
        "submission_id": submission["id"],
        "programmer_id": chosen["id"],
        "due_at": retired_assignment["due_at"],
        "status": "ASSIGNED",
        "replaced_by_assignment_id": None,
    })
    DB.assignments[rec["id"]] = rec
    retired_assignment["replaced_by_assignment_id"] = rec["id"]
    return rec


# ------------------------------------------- promotion cascade (§3.6)
def promotion_cascade(slate):
    """Promote the smallest-rank NOMINATED entry in the WAITLIST lane of the
    same slate to MAIN/INVITED with a fresh RSVP deadline; its submission
    moves WAITLISTED -> INVITED. Empty pool => nothing happens."""
    edition = DB.editions.get(slate["edition_id"])
    waiting = [e for e in DB.entries.values()
               if e["slate_id"] == slate["id"] and e["status"] == "NOMINATED"
               and e["lane"] == "WAITLIST"]
    if not waiting:
        return None
    pick = min(waiting, key=lambda e: (e["rank_position"], e["_seq"]))
    pick["lane"] = "MAIN"
    pick["status"] = "INVITED"
    pick["rsvp_deadline_at"] = now() + timedelta(days=edition["rsvp_window_days"])
    touch(pick)
    sub = DB.submissions.get(pick["submission_id"])
    if sub is not None and sub["status"] in ("WAITLISTED", "ADVANCED"):
        sub["status"] = "INVITED"
        touch(sub)
    return pick


# ------------------------------------------------------- clock sweeps (§2.4)
def run_sweeps():
    """Deferred actions fired by advancing the logical clock: intake
    auto-close, assignment expiry (+replacement), invitation expiry
    (+promotion)."""
    current = now()
    for edition in sorted(DB.editions.values(), key=lambda e: e["_seq"]):
        if edition["status"] == "INTAKE_OPEN" and current > edition["late_deadline_at"]:
            edition["status"] = "INTAKE_CLOSED"
            touch(edition)
    for a in sorted(DB.assignments.values(), key=lambda x: x["_seq"]):
        if a["status"] == "ASSIGNED" and current > a["due_at"]:
            a["status"] = "EXPIRED"
            touch(a)
            sub = DB.submissions.get(a["submission_id"])
            if sub is not None:
                replacement_cascade(sub, a)
    for e in sorted(DB.entries.values(), key=lambda x: x["_seq"]):
        if (e["status"] == "INVITED" and e["rsvp_deadline_at"] is not None
                and current > e["rsvp_deadline_at"]):
            e["status"] = "EXPIRED"
            touch(e)
            sub = DB.submissions.get(e["submission_id"])
            if sub is not None and sub["status"] == "INVITED":
                sub["status"] = "EXPIRED"
                touch(sub)
            slate = DB.slates.get(e["slate_id"])
            if slate is not None:
                promotion_cascade(slate)


# ------------------------------------------------------------- IRV tally
def award_candidates(award):
    """PROGRAMMED submissions of the edition whose slate's section equals the
    award's section."""
    out = []
    for s in DB.submissions.values():
        if s["edition_id"] != award["edition_id"] or s["status"] != "PROGRAMMED":
            continue
        entry = next((e for e in DB.entries.values()
                      if e["submission_id"] == s["id"]
                      and e["status"] not in ("DROPPED", "RELEASED")), None)
        if entry is None:
            continue
        slate = DB.slates.get(entry["slate_id"])
        if slate is not None and slate["section"] == award["section"]:
            out.append(s)
    out.sort(key=lambda s: (s["created_at"], s["_seq"]))
    return out


def irv_tally(award):
    """Instant-runoff tally per §3.9. Returns (winner_submission_id|None,
    rounds_log)."""
    ballots = sorted(
        [b for b in DB.ballots.values() if b["award_id"] == award["id"]],
        key=lambda b: (b["submitted_at"], b["created_at"], b["_seq"]))
    candidates = award_candidates(award)
    active_candidates = {c["id"] for c in candidates}
    sub_by_id = {c["id"]: c for c in candidates}
    active_ballots = list(ballots)
    rounds_log = []
    if not active_candidates:
        return None, rounds_log
    round_no = 0
    while True:
        counts = {cid: 0 for cid in active_candidates}
        first_pref = {cid: [] for cid in active_candidates}
        for b in active_ballots:
            for sid in b["ranked_submission_ids"]:
                if sid in active_candidates:
                    counts[sid] += 1
                    first_pref[sid].append(b)
                    break
        n = len(active_ballots)
        winners = [cid for cid, k in counts.items() if 2 * k > n]
        if winners:
            return winners[0], rounds_log
        if len(active_candidates) == 1:
            return next(iter(active_candidates)), rounds_log
        min_count = min(counts.values())
        tied = [cid for cid in active_candidates if counts[cid] == min_count]
        eliminated = None
        if len(tied) == 1:
            eliminated = tied[0]
        elif min_count > 0:
            # Tied for fewest: eliminate the one whose EARLIEST current
            # first-preference ballot (submitted_at, then created_at) is LATEST.
            def earliest_key(cid):
                b = min(first_pref[cid],
                        key=lambda x: (x["submitted_at"], x["created_at"],
                                       x["_seq"]))
                return (b["submitted_at"], b["created_at"], b["_seq"])
            eliminated = max(tied, key=earliest_key)
        else:
            # Still tied: fewest total mentions across all ballots loses.
            def mentions(cid):
                return sum(1 for b in ballots if cid in b["ranked_submission_ids"])
            min_mentions = min(mentions(cid) for cid in tied)
            tied2 = [cid for cid in tied if mentions(cid) == min_mentions]
            # Final fallback: earliest-created submission is eliminated.
            eliminated = min(
                tied2,
                key=lambda cid: (sub_by_id[cid]["created_at"],
                                 sub_by_id[cid]["_seq"]))
        round_no += 1
        rounds_log.append({
            "round": round_no,
            "counts": {cid: counts[cid] for cid in sorted(counts)},
            "eliminated": eliminated,
        })
        active_candidates.discard(eliminated)
        active_ballots = [
            b for b in active_ballots
            if any(sid in active_candidates for sid in b["ranked_submission_ids"])
        ]
