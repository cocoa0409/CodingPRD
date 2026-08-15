"""Business logic: calculations, derived fields, cascades, clock sweep.

All arithmetic on scores uses Decimal with round-half-up at the pinned steps
(PRD 2.8, 3.6). All money is integer cents.
"""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP, localcontext

import audit
import clock
import store
from util import bump, new_record, new_child_record, round4, dec

# ---------------------------------------------------------------------------
# constants (scaffold calculations[].constants)
# ---------------------------------------------------------------------------
LATE_WINDOW_HOURS = 48
INVOICE_DUE_HOURS = 72
WITHDRAWAL_FEE_CENTS = 2500
MAX_MATERIAL_BYTES = 104857600  # 100 MiB
MAX_REVISIONS = 2
BARRED_THRESHOLD = 3
SCORING_ROUND_GAP_HOURS = 12
ROUND_BASE_WEIGHTS = {1: Decimal("0.20"), 2: Decimal("0.30"), 3: Decimal("0.50")}
ROUND_NAMES = {1: "SCREENING", 2: "SEMIFINAL", 3: "FINAL"}

# states counted by AwardSeason.active_entries_count: a draft was never
# counted (PRD 3.3); only WITHDRAWN/DISQUALIFIED leave the count once active.
_ACTIVE_ENTRY_STATES = {
    "SUBMITTED", "UNDER_REVIEW", "ELIGIBLE", "INELIGIBLE", "IN_JUDGING",
    "FINALIST", "NON_FINALIST", "WINNER", "NON_WINNER",
}

TERMINAL = {
    "season": {"ARCHIVED", "CANCELLED"},
    "category": {"RETIRED"},
    "entry": {"WINNER", "NON_WINNER", "WITHDRAWN", "DISQUALIFIED"},
    "invoice": {"PAID", "VOIDED", "REFUNDED"},
    "judge": {"DECLINED", "RETIRED"},
    "declaration": {"RESCINDED"},
    "assignment": {"RECUSED", "REMOVED", "COMPLETED"},
    "round": {"PUBLISHED", "VOIDED"},
    "score": {"LOCKED", "VOIDED"},
    "finalist": {"DECLINED", "REVOKED"},
    "ceremony": {"CONCLUDED", "ABORTED"},
    "announcement": {"ANNOUNCED", "RETRACTED"},
    "fulfillment": {"DELIVERED", "CANCELLED"},
    "appeal": {"UPHELD", "DENIED", "WITHDRAWN"},
}


def guard_transition(kind, rec, allowed_from):
    """Pipeline priorities 6/7: terminal-state guard, then state gate.

    FinalistRecord carries its lifecycle in notification_status instead of
    status; every other entity uses status.
    """
    from errors import raise_err, ERR_ALREADY_TERMINAL, ERR_INVALID_STATE
    field = "notification_status" if kind == "finalist" else "status"
    status = rec[field]
    if status in TERMINAL[kind] and status not in allowed_from:
        raise_err(ERR_ALREADY_TERMINAL,
                  "%s %s is in terminal state %s" % (kind, rec["id"], status))
    if status not in allowed_from:
        raise_err(ERR_INVALID_STATE,
                  "%s %s in state %s does not permit this transition (need %s)"
                  % (kind, rec["id"], status, " or ".join(sorted(allowed_from))))


# ---------------------------------------------------------------------------
# serializers (field lists from scaffold entities)
# ---------------------------------------------------------------------------
def serialize_season(r):
    return {
        "id": r["id"],
        "code": r["code"],
        "title": r["title"],
        "status": r["status"],
        "submission_opens_at": _ts(r["submission_opens_at"]),
        "early_fee_ends_at": _ts(r["early_fee_ends_at"]),
        "submission_closes_at": _ts(r["submission_closes_at"]),
        "eligibility_window_start": _ts(r["eligibility_window_start"]),
        "eligibility_window_end": _ts(r["eligibility_window_end"]),
        "ceremony_scheduled_at": _ts(r.get("ceremony_scheduled_at")),
        "embargo_lifts_at": _ts(r.get("embargo_lifts_at")),
        "ack_window_hours": r["ack_window_hours"],
        "go_live_lead_minutes": r["go_live_lead_minutes"],
        "max_appeals_per_entry": r["max_appeals_per_entry"],
        "refund_policy": r["refund_policy"],
        "active_entries_count": r["active_entries_count"],
        "integrity_flag": r["integrity_flag"],
        "created_at": _ts(r["created_at"]),
        "updated_at": _ts(r["updated_at"]),
        "version": r["version"],
    }


def serialize_category(r):
    return {
        "id": r["id"],
        "season_id": r["season_id"],
        "code": r["code"],
        "name": r["name"],
        "description": r.get("description"),
        "eligibility_rules_text": r.get("eligibility_rules_text"),
        "min_materials": r["min_materials"],
        "max_entries_per_entrant": r["max_entries_per_entrant"],
        "early_fee_cents": r["early_fee_cents"],
        "standard_fee_cents": r["standard_fee_cents"],
        "late_fee_cents": r["late_fee_cents"],
        "panel_size": r["panel_size"],
        "finalist_slots": r["finalist_slots"],
        "scoring_rubric": r["scoring_rubric"],
        "status": r["status"],
        "created_at": _ts(r["created_at"]),
        "updated_at": _ts(r["updated_at"]),
        "version": r["version"],
    }


def serialize_entrant(r):
    return {
        "id": r["id"],
        "legal_name": r["legal_name"],
        "contact_email": r["contact_email"],
        "country_code": r["country_code"],
        "standing": r["standing"],
        "delinquent_since": _ts(r.get("delinquent_since")),
        "lifetime_disqualifications": r["lifetime_disqualifications"],
        "created_at": _ts(r["created_at"]),
        "updated_at": _ts(r["updated_at"]),
        "version": r["version"],
    }


def serialize_entry(r, null_results=False):
    final_score = r.get("final_composite_score")
    final_rank = r.get("final_rank")
    if null_results:
        final_score = None
        final_rank = None
    return {
        "id": r["id"],
        "category_id": r["category_id"],
        "entrant_id": r["entrant_id"],
        "title": r["title"],
        "work_completed_at": _ts(r["work_completed_at"]),
        "status": r["status"],
        "payment_status": r["payment_status"],
        "revision_count": r["revision_count"],
        "fee_tier_applied": r.get("fee_tier_applied"),
        "fee_waived": r["fee_waived"],
        "final_composite_score": _num(final_score),
        "final_rank": final_rank,
        "disqualified_reason": r.get("disqualified_reason"),
        "created_at": _ts(r["created_at"]),
        "updated_at": _ts(r["updated_at"]),
        "version": r["version"],
    }


def serialize_material(r):
    return {
        "id": r["id"],
        "entry_id": r["entry_id"],
        "material_type": r["material_type"],
        "uri": r["uri"],
        "file_size_bytes": r["file_size_bytes"],
        "checksum_sha256": r["checksum_sha256"],
        "status": r["status"],
        "created_at": _ts(r["created_at"]),
    }


def serialize_invoice(r):
    return {
        "id": r["id"],
        "entry_id": r["entry_id"],
        "amount_cents": r["amount_cents"],
        "tier": r["tier"],
        "status": r["status"],
        "due_at": _ts(r["due_at"]),
        "paid_at": _ts(r.get("paid_at")),
        "refund_cents": r.get("refund_cents"),
        "retained_cents": r.get("retained_cents"),
        "created_at": _ts(r["created_at"]),
        "updated_at": _ts(r["updated_at"]),
        "version": r["version"],
    }


def serialize_judge(r):
    return {
        "id": r["id"],
        "full_name": r["full_name"],
        "email": r["email"],
        "expertise_tags": r["expertise_tags"],
        "affiliated_entrant_ids": r["affiliated_entrant_ids"],
        "status": r["status"],
        "reliability_score_bp": r["reliability_score_bp"],
        "created_at": _ts(r["created_at"]),
        "updated_at": _ts(r["updated_at"]),
        "version": r["version"],
    }


def serialize_declaration(r):
    return {
        "id": r["id"],
        "judge_id": r["judge_id"],
        "season_id": r.get("season_id"),
        "entrant_id": r.get("entrant_id"),
        "category_id": r.get("category_id"),
        "conflict_type": r["conflict_type"],
        "severity": r["severity"],
        "note": r.get("note"),
        "status": r["status"],
        "created_at": _ts(r["created_at"]),
    }


def serialize_assignment(r):
    return {
        "id": r["id"],
        "judge_id": r["judge_id"],
        "category_id": r["category_id"],
        "scoring_round_id": r["scoring_round_id"],
        "role": r["role"],
        "status": r["status"],
        "created_at": _ts(r["created_at"]),
        "updated_at": _ts(r["updated_at"]),
        "version": r["version"],
    }


def serialize_round(r):
    snap = r.get("normalization_snapshot")
    snap_out = None
    if snap is not None:
        snap_out = {jid: {k: _num(v) if k != "count" else v for k, v in stats.items()}
                    for jid, stats in snap.items()}
    return {
        "id": r["id"],
        "category_id": r["category_id"],
        "round_index": r["round_index"],
        "name": r["name"],
        "status": r["status"],
        "advance_count": r.get("advance_count"),
        "scoring_mode": r["scoring_mode"],
        "scheduled_window_start": _ts(r["scheduled_window_start"]),
        "scheduled_window_end": _ts(r["scheduled_window_end"]),
        "opened_at": _ts(r.get("opened_at")),
        "closed_at": _ts(r.get("closed_at")),
        "normalization_snapshot": snap_out,
        "created_at": _ts(r["created_at"]),
        "updated_at": _ts(r["updated_at"]),
        "version": r["version"],
    }


def serialize_score(r):
    return {
        "id": r["id"],
        "scoring_round_id": r["scoring_round_id"],
        "entry_id": r["entry_id"],
        "judge_id": r["judge_id"],
        "criterion_scores": r["criterion_scores"],
        "weighted_raw": _num(r.get("weighted_raw")),
        "z_intermediate": _num(r.get("z_intermediate")),
        "rank_among_judges_scores": _num(r.get("rank_among_judges_scores")),
        "normalized_score": _num(r.get("normalized_score")),
        "status": r["status"],
        "created_at": _ts(r["created_at"]),
    }


def serialize_finalist(r):
    return {
        "id": r["id"],
        "category_id": r["category_id"],
        "entry_id": r["entry_id"],
        "announced_rank": r["announced_rank"],
        "notification_status": r["notification_status"],
        "notified_at": _ts(r.get("notified_at")),
        "embargo_visible": r["embargo_visible"],
        "created_at": _ts(r["created_at"]),
        "updated_at": _ts(r["updated_at"]),
        "version": r["version"],
    }


def serialize_ceremony(r):
    return {
        "id": r["id"],
        "season_id": r["season_id"],
        "venue_name": r["venue_name"],
        "starts_at": _ts(r["starts_at"]),
        "ends_at": _ts(r["ends_at"]),
        "status": r["status"],
        "rundown": r["rundown"],
        "created_at": _ts(r["created_at"]),
        "updated_at": _ts(r["updated_at"]),
        "version": r["version"],
    }


def serialize_announcement(r):
    return {
        "id": r["id"],
        "category_id": r["category_id"],
        "ceremony_id": r["ceremony_id"],
        "winner_entry_id": r.get("winner_entry_id"),
        "status": r["status"],
        "announced_at": _ts(r.get("announced_at")),
        "retraction_reason": r.get("retraction_reason"),
        "created_at": _ts(r["created_at"]),
        "updated_at": _ts(r["updated_at"]),
        "version": r["version"],
    }


def serialize_fulfillment(r):
    return {
        "id": r["id"],
        "season_id": r["season_id"],
        "entry_id": r["entry_id"],
        "announcement_id": r["announcement_id"],
        "item_type": r["item_type"],
        "engraving_text": r.get("engraving_text"),
        "quantity": r["quantity"],
        "status": r["status"],
        "vendor_reference": r.get("vendor_reference"),
        "created_at": _ts(r["created_at"]),
        "updated_at": _ts(r["updated_at"]),
        "version": r["version"],
    }


def serialize_appeal(r):
    return {
        "id": r["id"],
        "entry_id": r["entry_id"],
        "filed_by_entrant_id": r["filed_by_entrant_id"],
        "grounds": r["grounds"],
        "narrative": r["narrative"],
        "status": r["status"],
        "decided_by": r.get("decided_by"),
        "decided_at": _ts(r.get("decided_at")),
        "remedy": r.get("remedy"),
        "created_at": _ts(r["created_at"]),
        "updated_at": _ts(r["updated_at"]),
        "version": r["version"],
    }


def serialize_audit(r):
    return {
        "id": r["id"],
        "season_id": r["season_id"],
        "actor_role": r["actor_role"],
        "actor_id": r["actor_id"],
        "action": r["action"],
        "target_type": r["target_type"],
        "target_id": r["target_id"],
        "detail": r["detail"],
        "hash_chain_prev": r["hash_chain_prev"],
        "hash_chain_self": r["hash_chain_self"],
        "created_at": _ts(r["created_at"]),
    }


def _ts(dt):
    from util import fmt_ts
    return fmt_ts(dt) if dt is not None else None


def _num(v):
    if v is None:
        return None
    if isinstance(v, Decimal):
        return float(v)
    return v


# ---------------------------------------------------------------------------
# lookups
# ---------------------------------------------------------------------------
def season_of_category(category):
    return store.seasons.get(category["season_id"])


def category_of_entry(entry):
    return store.categories.get(entry["category_id"])


def season_of_entry(entry):
    cat = category_of_entry(entry)
    return store.seasons.get(cat["season_id"]) if cat else None


def entries_of_season(season_id):
    return [e for e in store.entries.values()
            if (store.categories.get(e["category_id"]) or {}).get("season_id") == season_id]


def entries_of_category(category_id):
    return [e for e in store.entries.values() if e["category_id"] == category_id]


def invoices_of_entry(entry_id):
    return [i for i in store.invoices.values() if i["entry_id"] == entry_id]


def rounds_of_category(category_id, include_voided=True):
    rs = [r for r in store.rounds.values() if r["category_id"] == category_id]
    if not include_voided:
        rs = [r for r in rs if r["status"] != "VOIDED"]
    return rs


def assignments_of_round(round_id):
    return [a for a in store.assignments.values() if a["scoring_round_id"] == round_id]


def scores_of_round(round_id):
    return [s for s in store.scores.values() if s["scoring_round_id"] == round_id]


def finalists_of_category(category_id):
    return [f for f in store.finalists.values() if f["category_id"] == category_id]


# ---------------------------------------------------------------------------
# derived fields
# ---------------------------------------------------------------------------
def recompute_active_entries_count(season):
    n = sum(1 for e in entries_of_season(season["id"])
            if e["status"] in _ACTIVE_ENTRY_STATES)
    if season["active_entries_count"] != n:
        season["active_entries_count"] = n


def recompute_standing(entrant):
    """entrant_standing calculation (clock sweep + payment settlement)."""
    if entrant["lifetime_disqualifications"] >= BARRED_THRESHOLD:
        if entrant["standing"] != "BARRED":
            entrant["standing"] = "BARRED"
            bump(entrant)
        return
    now = clock.now()
    overdue = False
    for e in store.entries.values():
        if e["entrant_id"] != entrant["id"]:
            continue
        for inv in invoices_of_entry(e["id"]):
            if inv["status"] == "ISSUED" and now > inv["due_at"]:
                overdue = True
                break
        if overdue:
            break
    if overdue and entrant["standing"] == "GOOD":
        entrant["standing"] = "DELINQUENT"
        entrant["delinquent_since"] = now
        bump(entrant)
    elif not overdue and entrant["standing"] == "DELINQUENT":
        entrant["standing"] = "GOOD"
        entrant["delinquent_since"] = None
        bump(entrant)


def recompute_reliability(judge):
    """judge_reliability: completed / decided * 10000 bp, round-half-up."""
    completed = sum(1 for a in store.assignments.values()
                    if a["judge_id"] == judge["id"] and a["status"] == "COMPLETED")
    decided = completed + sum(1 for a in store.assignments.values()
                              if a["judge_id"] == judge["id"]
                              and a["status"] in ("REMOVED", "RECUSED"))
    if decided == 0:
        value = 10000
    else:
        value = int((Decimal(completed) / Decimal(decided) * 10000)
                    .quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    if judge["reliability_score_bp"] != value:
        judge["reliability_score_bp"] = value
        bump(judge)


# ---------------------------------------------------------------------------
# entry_fee calculation (threshold tiers; boundary pins per scaffold)
# ---------------------------------------------------------------------------
def compute_fee_tier(category, season, at):
    if at < season["early_fee_ends_at"]:
        return "EARLY", category["early_fee_cents"]
    if at <= season["submission_closes_at"]:
        return "STANDARD", category["standard_fee_cents"]
    return "LATE", category["late_fee_cents"]


def create_invoice(entry, category, season):
    now = clock.now()
    tier, amount = compute_fee_tier(category, season, now)
    rec = new_record()
    rec.update({
        "entry_id": entry["id"],
        "amount_cents": amount,
        "tier": tier,
        "status": "ISSUED",
        "due_at": now + timedelta(hours=INVOICE_DUE_HOURS),
        "paid_at": None,
        "refund_cents": None,
        "retained_cents": None,
    })
    store.invoices[rec["id"]] = rec
    entry["fee_tier_applied"] = tier
    return rec


# ---------------------------------------------------------------------------
# withdrawal_refund calculation (two policy variants)
# ---------------------------------------------------------------------------
def run_withdrawal_refund(invoice, season):
    amount = invoice["amount_cents"]
    if season["refund_policy"] == "FLAT_FEE":
        retained = WITHDRAWAL_FEE_CENTS
        refund = max(0, amount - WITHDRAWAL_FEE_CENTS)
    else:  # EARLY_BIRD_FREE
        if invoice["paid_at"] is not None and invoice["paid_at"] < season["early_fee_ends_at"]:
            retained = 0
            refund = amount
        else:
            retained = WITHDRAWAL_FEE_CENTS * 2
            refund = max(0, amount - retained)
    if refund == 0:
        retained = amount
    invoice["refund_cents"] = refund
    invoice["retained_cents"] = retained
    invoice["status"] = "REFUNDED"
    bump(invoice)


# ---------------------------------------------------------------------------
# composite_raw calculation (pinned rounding order: per-criterion 4dp first)
# ---------------------------------------------------------------------------
def compute_weighted_raw(criterion_scores, rubric):
    with localcontext() as ctx:
        ctx.prec = 50
        total = Decimal(0)
        for c in rubric:
            raw = dec(criterion_scores[c["criterion_code"]])
            contribution = ((raw / dec(c["max_score"])) * dec(c["weight_bp"])
                            / Decimal(100)).quantize(Decimal("0.0001"),
                                                     rounding=ROUND_HALF_UP)
            total += contribution
        return total.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# scoring: candidates, ballots, normalization, final composite
# ---------------------------------------------------------------------------
def non_voided_rounds(category_id):
    return sorted((r for r in store.rounds.values()
                   if r["category_id"] == category_id and r["status"] != "VOIDED"),
                  key=lambda r: (r["round_index"], r["_seq"]))


def preceding_round(rnd):
    prevs = [r for r in non_voided_rounds(rnd["category_id"])
             if r["round_index"] < rnd["round_index"]]
    return prevs[-1] if prevs else None


def voided_predecessor(rnd):
    voids = [r for r in store.rounds.values()
             if r["category_id"] == rnd["category_id"]
             and r["round_index"] == rnd["round_index"]
             and r["status"] == "VOIDED" and r["id"] != rnd["id"]]
    voids.sort(key=lambda r: r["_seq"])
    return voids[-1] if voids else None


def round_candidate_ids(rnd):
    """Candidate entry ids for a round.

    Lowest-indexed non-VOIDED round: all IN_JUDGING entries in the category.
    Later rounds: entries that advanced from the immediately preceding round.
    Replacement rounds (a VOIDED same-index round exists) reopen the voided
    round's scored population, minus DISQUALIFIED entries.
    """
    prev = preceding_round(rnd)
    if prev is not None:
        ids = list(prev.get("advanced_entry_ids") or [])
        return [eid for eid in ids
                if store.entries.get(eid) is not None
                and store.entries[eid]["status"] != "DISQUALIFIED"]
    in_judging = [e["id"] for e in entries_of_category(rnd["category_id"])
                  if e["status"] == "IN_JUDGING"]
    if in_judging:
        return in_judging
    vp = voided_predecessor(rnd)
    if vp is not None:
        seen = []
        for s in scores_of_round(vp["id"]):
            e = store.entries.get(s["entry_id"])
            if e is None or e["status"] == "DISQUALIFIED":
                continue
            if e["id"] not in seen:
                seen.append(e["id"])
        return seen
    return []


def active_panel_assignments(round_id):
    return [a for a in assignments_of_round(round_id) if a["status"] == "ACTIVE"]


def judge_conflicts_with_entrant(judge_id, entrant_id, season_id, category_id,
                                 severity=None):
    """Active (DECLARED/ACKNOWLEDGED) declarations covering this scope.

    A null category scope covers the whole season; a null season (seeded from
    affiliations) covers every season.
    """
    for d in store.declarations.values():
        if d["judge_id"] != judge_id:
            continue
        if d["status"] not in ("DECLARED", "ACKNOWLEDGED"):
            continue
        if d.get("entrant_id") != entrant_id:
            continue
        if severity is not None and d["severity"] != severity:
            continue
        if d.get("season_id") is not None and d["season_id"] != season_id:
            continue
        if d.get("category_id") is not None and d["category_id"] != category_id:
            continue
        return True
    return False


def eligible_or_in_judging_entrants(category_id):
    out = set()
    for e in entries_of_category(category_id):
        if e["status"] in ("ELIGIBLE", "IN_JUDGING"):
            out.add(e["entrant_id"])
    return out


def confirm_blocked_by_conflict(assignment):
    """HARD conflict bars outright; SOFT bars the CHAIR role only."""
    judge_id = assignment["judge_id"]
    cat = store.categories.get(assignment["category_id"])
    if cat is None:
        return False
    season_id = cat["season_id"]
    entrants = eligible_or_in_judging_entrants(assignment["category_id"])
    for d in store.declarations.values():
        if d["judge_id"] != judge_id:
            continue
        if d["status"] not in ("DECLARED", "ACKNOWLEDGED"):
            continue
        if d.get("season_id") is not None and d["season_id"] != season_id:
            continue
        if d.get("category_id") is not None and d["category_id"] != assignment["category_id"]:
            continue
        if d.get("entrant_id") is not None and d["entrant_id"] not in entrants:
            continue
        if d["severity"] == "HARD":
            return True
        if d["severity"] == "SOFT" and assignment["role"] == "CHAIR":
            return True
    return False


def demote_round_if_understaffed(rnd):
    cat = store.categories.get(rnd["category_id"])
    if cat is None:
        return
    if rnd["status"] == "PANEL_LOCKED":
        if len(active_panel_assignments(rnd["id"])) < cat["panel_size"]:
            rnd["status"] = "CONFIGURING"
            bump(rnd)


def run_normalization(rnd):
    """score_normalization (+ final_composite on the FINAL round).

    Input set: LOCKED scores in this round whose judge's PanelAssignment is
    ACTIVE at close (those assignments complete in this same transition).
    """
    cat = store.categories[rnd["category_id"]]
    active_judges = {a["judge_id"] for a in active_panel_assignments(rnd["id"])}
    locked = [s for s in scores_of_round(rnd["id"])
              if s["status"] == "LOCKED" and s["judge_id"] in active_judges]
    candidates = round_candidate_ids(rnd)
    candidate_set = set(candidates)
    locked = [s for s in locked if s["entry_id"] in candidate_set]

    vp = voided_predecessor(rnd)
    reuse_snapshot = vp.get("normalization_snapshot") if vp else None

    with localcontext() as ctx:
        ctx.prec = 50
        snapshot = {}
        if rnd["scoring_mode"] == "Z_SCORE":
            zmap = {}
            for jid in active_judges:
                jscores = [s for s in locked if s["judge_id"] == jid]
                if not jscores:
                    continue
                vals = [dec(s["weighted_raw"]) for s in jscores]
                # Replacement rounds reuse the voided round's frozen per-judge
                # statistics when that judge's scores remained LOCKED there.
                reused = None
                if reuse_snapshot and jid in reuse_snapshot:
                    prior_locked = [s for s in scores_of_round(vp["id"])
                                    if s["judge_id"] == jid and s["status"] == "LOCKED"]
                    if prior_locked:
                        reused = reuse_snapshot[jid]
                if reused is not None:
                    mean = dec(reused["mean"])
                    std = dec(reused["stddev"])
                else:
                    mean = sum(vals) / Decimal(len(vals))
                    var = sum((v - mean) ** 2 for v in vals) / Decimal(len(vals))
                    std = var.sqrt()
                snapshot[jid] = {
                    "mean": round4(mean), "stddev": round4(std),
                    "count": len(vals), "min": round4(min(vals)),
                    "max": round4(max(vals)),
                }
                for s in jscores:
                    z = (dec(s["weighted_raw"]) - mean) / std if std > 0 else Decimal(0)
                    zmap[s["id"]] = z
                    s["z_intermediate"] = z
                    s["rank_among_judges_scores"] = None
            if zmap:
                zmin = min(zmap.values())
                zmax = max(zmap.values())
                for s in locked:
                    z = zmap.get(s["id"])
                    if z is None:
                        continue
                    if zmax > zmin:
                        s["normalized_score"] = round4((z - zmin) / (zmax - zmin) * 100)
                    else:
                        s["normalized_score"] = Decimal("50.0000")
        else:  # RAW_RANK
            n_entries = len(candidate_set)
            for jid in active_judges:
                jscores = [s for s in locked if s["judge_id"] == jid]
                if not jscores:
                    continue
                vals = [dec(s["weighted_raw"]) for s in jscores]
                snapshot[jid] = {
                    "mean": round4(sum(vals) / Decimal(len(vals))),
                    "stddev": round4((sum((v - sum(vals) / Decimal(len(vals))) ** 2
                                          for v in vals) / Decimal(len(vals))).sqrt()),
                    "count": len(vals), "min": round4(min(vals)),
                    "max": round4(max(vals)),
                }
                # rank by weighted_raw DESC; ties share the average rank
                ordered = sorted(jscores, key=lambda s: (-dec(s["weighted_raw"]), s["_seq"]))
                i = 0
                while i < len(ordered):
                    j = i
                    while (j + 1 < len(ordered)
                           and dec(ordered[j + 1]["weighted_raw"]) == dec(ordered[i]["weighted_raw"])):
                        j += 1
                    avg_rank = Decimal(i + 1 + j + 1) / Decimal(2)
                    for k in range(i, j + 1):
                        ordered[k]["rank_among_judges_scores"] = avg_rank
                    i = j + 1
                for s in jscores:
                    s["z_intermediate"] = None
                    if n_entries > 1:
                        s["normalized_score"] = round4(
                            (Decimal(n_entries) - dec(s["rank_among_judges_scores"]))
                            / Decimal(n_entries - 1) * 100)
                    else:
                        s["normalized_score"] = Decimal("100.0000")

        # per-entry composite for this round: mean of normalized scores (4dp)
        composites = {}
        for eid in candidates:
            escores = [s for s in locked if s["entry_id"] == eid
                       and s.get("normalized_score") is not None]
            if escores:
                composites[eid] = round4(sum(dec(s["normalized_score"])
                                             for s in escores) / Decimal(len(escores)))
        rnd["entry_composites"] = composites
        rnd["normalization_snapshot"] = snapshot

        if rnd["round_index"] < 3:
            # mark top advance_count entries as advancing
            advance_count = rnd.get("advance_count") or 0
            ranked = sorted(candidates,
                            key=lambda eid: (-composites.get(eid, Decimal(0)),
                                             store.entries[eid]["created_at"],
                                             store.entries[eid]["_seq"]))
            rnd["advanced_entry_ids"] = [eid for eid in ranked[:advance_count]
                                         if eid in composites]
        else:
            # FINAL round: final_composite blend with proportional
            # redistribution of missing rounds' base weights.
            present = [r["round_index"] for r in non_voided_rounds(rnd["category_id"])]
            wsum = sum(ROUND_BASE_WEIGHTS[i] for i in present)
            comp_by_round = {}
            for r in non_voided_rounds(rnd["category_id"]):
                comp_by_round[r["round_index"]] = r.get("entry_composites") or {}
            final_weighted_raw = {}
            for eid in candidates:
                total = Decimal(0)
                for ri in present:
                    comp = comp_by_round.get(ri, {}).get(eid)
                    if comp is None:
                        continue
                    total += ROUND_BASE_WEIGHTS[ri] / wsum * comp
                e = store.entries[eid]
                e["final_composite_score"] = round4(total)
                final_weighted_raw[eid] = final_round_weighted_raw(rnd, eid)
            ranked = sorted(candidates,
                            key=lambda eid: (-dec(store.entries[eid]["final_composite_score"]),
                                             -final_weighted_raw.get(eid, Decimal(0)),
                                             store.entries[eid]["created_at"],
                                             store.entries[eid]["_seq"]))
            for idx, eid in enumerate(ranked, start=1):
                e = store.entries[eid]
                if e.get("final_rank") != idx:
                    e["final_rank"] = idx
                bump(e)
            # appeal-driven recomputation may displace acknowledged finalists
            for fr in finalists_of_category(rnd["category_id"]):
                if fr["notification_status"] != "ACKNOWLEDGED":
                    continue
                e = store.entries.get(fr["entry_id"])
                if e is None or e.get("final_rank") is None:
                    continue
                if e["final_rank"] > cat["finalist_slots"] and e["status"] == "FINALIST":
                    fr["notification_status"] = "REVOKED"
                    bump(fr)
                    e["status"] = "NON_FINALIST"
                    bump(e)
                    for fo in store.fulfillment_orders.values():
                        if (fo["entry_id"] == e["id"] and fo["item_type"] == "CERTIFICATE"
                                and fo["status"] in ("DRAFT", "QUEUED")):
                            fo["status"] = "CANCELLED"
                            bump(fo)

    # surviving ACTIVE assignments complete; reliability recomputed
    for a in active_panel_assignments(rnd["id"]):
        a["status"] = "COMPLETED"
        bump(a)
    judged = {a["judge_id"] for a in store.assignments.values()
              if a["scoring_round_id"] == rnd["id"]}
    for jid in judged:
        j = store.judges.get(jid)
        if j is not None:
            recompute_reliability(j)


def final_round_weighted_raw(final_round, entry_id):
    """Mean of the entry's LOCKED weighted_raw in the FINAL round (panel)."""
    vals = [dec(s["weighted_raw"]) for s in scores_of_round(final_round["id"])
            if s["entry_id"] == entry_id and s["status"] in ("LOCKED",)
            and s.get("weighted_raw") is not None]
    if not vals:
        return Decimal(0)
    return round4(sum(vals) / Decimal(len(vals)))


# ---------------------------------------------------------------------------
# cascades
# ---------------------------------------------------------------------------
def close_submissions(season, actor_role, actor_id):
    """OPEN -> SUBMISSION_CLOSED: late-Draft sweep + count recompute."""
    season["status"] = "SUBMISSION_CLOSED"
    bump(season)
    for e in entries_of_season(season["id"]):
        if e["status"] == "DRAFT":
            e["status"] = "WITHDRAWN"
            bump(e)
    recompute_active_entries_count(season)
    audit.append(season["id"], actor_role, actor_id,
                 "SEASON_CLOSE_SUBMISSIONS", "AwardSeason", season["id"],
                 {"before": {"status": "OPEN"},
                  "after": {"status": "SUBMISSION_CLOSED"}})


def promote_next_finalist(category, vacated_rank):
    """finalist_promotion_rank: highest-ranked NON_FINALIST takes the slot."""
    candidates = [e for e in entries_of_category(category["id"])
                  if e["status"] == "NON_FINALIST"
                  and e.get("final_composite_score") is not None]
    if not candidates:
        return None
    final_round = None
    for r in non_voided_rounds(category["id"]):
        if r["round_index"] == 3:
            final_round = r
    def sort_key(e):
        fr_comp = Decimal(0)
        if final_round is not None:
            fr_comp = dec((final_round.get("entry_composites") or {}).get(e["id"], 0))
        return (-dec(e["final_composite_score"]), -fr_comp, e["created_at"], e["_seq"])
    candidates.sort(key=sort_key)
    chosen = candidates[0]
    chosen["status"] = "FINALIST"
    bump(chosen)
    rec = new_record()
    rec.update({
        "category_id": category["id"],
        "entry_id": chosen["id"],
        "announced_rank": vacated_rank,
        "notification_status": "PENDING",
        "notified_at": None,
        "embargo_visible": False,
    })
    store.finalists[rec["id"]] = rec
    return rec


def decline_finalist_record(fr):
    """Shared by the decline endpoint and the ack-window clock sweep."""
    fr["notification_status"] = "DECLINED"
    bump(fr)
    e = store.entries.get(fr["entry_id"])
    cat = store.categories.get(fr["category_id"])
    if cat is None:
        return
    # promote first (the declining entry is not yet NON_FINALIST)
    promote_next_finalist(cat, fr["announced_rank"])
    if e is not None and e["status"] == "FINALIST":
        e["status"] = "NON_FINALIST"
        bump(e)


def recompute_embargo_visibility(season):
    """embargo_visible: clock >= embargo_lifts_at AND season in
    {CEREMONY_LIVE, PUBLISHED} (PRD 2.10)."""
    lift = season.get("embargo_lifts_at")
    visible = (lift is not None and clock.now() >= lift
               and season["status"] in ("CEREMONY_LIVE", "PUBLISHED"))
    for cat in [c for c in store.categories.values() if c["season_id"] == season["id"]]:
        for fr in finalists_of_category(cat["id"]):
            if fr["embargo_visible"] != visible:
                fr["embargo_visible"] = visible
                bump(fr)


def disqualify_entry(entry, reason):
    entry["status"] = "DISQUALIFIED"
    entry["disqualified_reason"] = reason
    bump(entry)
    entrant = store.entrants.get(entry["entrant_id"])
    if entrant is not None:
        entrant["lifetime_disqualifications"] += 1
        bump(entrant)
        if entrant["lifetime_disqualifications"] >= BARRED_THRESHOLD:
            entrant["standing"] = "BARRED"
            bump(entrant)
    for fo in store.fulfillment_orders.values():
        if fo["entry_id"] == entry["id"] and fo["status"] not in ("SHIPPED", "DELIVERED", "CANCELLED"):
            fo["status"] = "CANCELLED"
            bump(fo)
    season = season_of_entry(entry)
    if season is not None:
        recompute_active_entries_count(season)


def find_conflicted_judges(rnd, appealed_entry):
    """Identify the conflicted judge(s) of a CONFLICT_UNDECLARED appeal.

    Preference order: judges with an active declaration against the appealed
    entry's entrant covering this scope; then judges whose affiliation list
    names the entrant (undeclared affiliation); then the panelist whose LOCKED
    ballot most favoured the appealed entry (highest weighted_raw; ties break
    CHAIR first, then earliest assignment).
    """
    cat = store.categories.get(rnd["category_id"])
    season_id = cat["season_id"] if cat else None
    entrant_id = appealed_entry["entrant_id"]
    panel_judges = {a["judge_id"]: a for a in assignments_of_round(rnd["id"])}
    by_declaration = [jid for jid in panel_judges
                      if judge_conflicts_with_entrant(jid, entrant_id, season_id,
                                                      rnd["category_id"], severity="HARD")]
    if by_declaration:
        return by_declaration
    by_affiliation = []
    for jid in panel_judges:
        j = store.judges.get(jid)
        if j is not None and entrant_id in (j.get("affiliated_entrant_ids") or []):
            by_affiliation.append(jid)
    if by_affiliation:
        return by_affiliation
    best = None
    best_key = None
    for jid, a in panel_judges.items():
        for s in scores_of_round(rnd["id"]):
            if s["judge_id"] != jid or s["entry_id"] != appealed_entry["id"]:
                continue
            if s["status"] != "LOCKED":
                continue
            key = (dec(s["weighted_raw"] or 0),
                   1 if a["role"] == "CHAIR" else 0,
                   -a["_seq"])
            if best_key is None or key > best_key:
                best_key = key
                best = jid
    return [best] if best is not None else []


def void_round_for_rescore(rnd, appealed_entry, grounds):
    """NORMALIZED/PUBLISHED -> VOIDED on an upheld RESCORE appeal."""
    rnd["status"] = "VOIDED"
    bump(rnd)
    if grounds == "CONFLICT_UNDECLARED":
        for jid in find_conflicted_judges(rnd, appealed_entry):
            for s in scores_of_round(rnd["id"]):
                if s["judge_id"] == jid and s["status"] == "LOCKED":
                    s["status"] = "VOIDED"


# ---------------------------------------------------------------------------
# clock sweep (PRD 2.6): runs on every clock set
# ---------------------------------------------------------------------------
def run_clock_sweep(actor_role="system", actor_id="system"):
    now = clock.now()
    # 1. seasons past the late deadline auto-close submissions
    for season in list(store.seasons.values()):
        if season["status"] != "OPEN":
            continue
        late_deadline = season["submission_closes_at"] + timedelta(hours=LATE_WINDOW_HOURS)
        if now > late_deadline:
            close_submissions(season, actor_role, actor_id)
    # 2. entrant standing flips on crossed invoice due_at
    for entrant in list(store.entrants.values()):
        recompute_standing(entrant)
    # 3. finalist acknowledgement windows lapse -> auto-decline
    pending = [fr for fr in store.finalists.values()
               if fr["notification_status"] == "NOTIFIED"]
    pending.sort(key=lambda fr: (fr["created_at"], fr["_seq"]))
    for fr in pending:
        cat = store.categories.get(fr["category_id"])
        if cat is None:
            continue
        season = store.seasons.get(cat["season_id"])
        if season is None or fr.get("notified_at") is None:
            continue
        deadline = fr["notified_at"] + timedelta(hours=season["ack_window_hours"])
        if now > deadline:
            decline_finalist_record(fr)
    # 4. embargo visibility re-evaluation
    for season in list(store.seasons.values()):
        recompute_embargo_visibility(season)
