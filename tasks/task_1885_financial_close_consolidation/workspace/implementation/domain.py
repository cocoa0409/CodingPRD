"""Domain logic: fetch helpers, serializers, recomputes, calculations, events."""
import json
from datetime import datetime, timedelta
from decimal import Decimal

from core import (
    STORE, ApiError, base_record, bump, dec, fmt_ts, logical_now, new_id,
    next_seq, rhu, rhu2, wall_now,
)

RECON_TOLERANCE = 500
ELIM_TOLERANCE = 500
FLUX_PCT_THRESHOLD = Decimal("10.00")
MONETARY_FRACTION = Decimal("1.0")
DAY_SECONDS = 86400

CURRENCIES = ("USD", "EUR", "GBP", "JPY")


# ---------------------------------------------------------------------------
# Fetch helpers (404 on missing)
# ---------------------------------------------------------------------------
def _get(coll, rid):
    rec = STORE[coll].get(rid)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Resource %s not found" % rid)
    return rec


def get_period(rid):
    return _get("periods", rid)


def get_entity(rid):
    return _get("entities", rid)


def get_ep(rid):
    return _get("entity_periods", rid)


def get_task(rid):
    return _get("tasks", rid)


def get_cutoff(rid):
    return _get("cutoffs", rid)


def get_accrual(rid):
    return _get("accruals", rid)


def get_je(rid):
    return _get("journal_entries", rid)


def get_doc(rid):
    return _get("documents", rid)


def get_recon(rid):
    return _get("reconciliations", rid)


def get_item(rid):
    return _get("recon_items", rid)


def get_elim(rid):
    return _get("elim_pairs", rid)


def get_flux(rid):
    return _get("fluxes", rid)


def period_of_ep(ep):
    return STORE["periods"].get(ep["close_period_id"])


def entity_of_ep(ep):
    return STORE["entities"].get(ep["entity_id"])


def eps_of_period(period_id):
    return [e for e in STORE["entity_periods"].values()
            if e["close_period_id"] == period_id]


# ---------------------------------------------------------------------------
# Serializers (whitelist; internal keys are "_" prefixed and never emitted)
# ---------------------------------------------------------------------------
PERIOD_FIELDS = ("id", "fiscal_year", "fiscal_period", "period_start",
                 "period_end", "close_posture", "reporting_currency",
                 "materiality_threshold_minor", "status", "locked_entity_count",
                 "total_entity_count", "reopened_reason", "created_at",
                 "updated_at", "version")
ENTITY_FIELDS = ("id", "entity_code", "name", "functional_currency",
                 "parent_entity_id", "ownership_pct", "translation_method",
                 "consolidation_tier", "is_elimination_counterparty",
                 "created_at", "updated_at", "version")
EP_FIELDS = ("id", "close_period_id", "entity_id", "status",
             "trial_balance_minor", "translated_balance_minor", "cta_minor",
             "nci_share_minor", "unreconciled_count", "aged_over_30_count",
             "open_task_count", "remeasurement_minor", "created_at",
             "updated_at", "version")
TASK_FIELDS = ("id", "close_period_id", "entity_period_id", "task_key",
               "title", "depends_on_task_ids", "assignee_user_id",
               "due_offset_hours", "status", "is_late", "completed_at",
               "created_at", "updated_at", "version")
CUTOFF_FIELDS = ("id", "entity_period_id", "subledger", "cutoff_at",
                 "cutoff_rule", "status", "pre_cutoff_total_minor",
                 "boundary_transaction_count", "created_at", "updated_at",
                 "version")
ACCRUAL_FIELDS = ("id", "entity_period_id", "subledger_cutoff_id",
                  "account_code", "basis", "provisional_amount_minor",
                  "final_amount_minor", "true_up_delta_minor", "status",
                  "created_at", "updated_at", "version")
JE_FIELDS = ("id", "entity_period_id", "je_type", "entry_date",
             "preparer_user_id", "approver_user_id", "debit_total_minor",
             "credit_total_minor", "functional_currency", "status", "doc_state",
             "rejection_reason", "posted_at", "created_at", "updated_at",
             "version")
LINE_FIELDS = ("id", "journal_entry_id", "line_no", "account_code",
               "direction", "amount_minor", "counterparty_entity_id", "memo",
               "created_at", "updated_at", "version")
DOC_FIELDS = ("id", "journal_entry_id", "file_name", "content_hash",
              "doc_category", "uploaded_by_user_id", "verified_by_user_id",
              "status", "created_at", "updated_at", "version")
RECON_FIELDS = ("id", "entity_period_id", "account_code", "recon_type",
                "gl_balance_minor", "subledger_balance_minor",
                "difference_minor", "is_within_tolerance", "status",
                "cleared_by_user_id", "reviewed_by_user_id", "created_at",
                "updated_at", "version")
ITEM_FIELDS = ("id", "reconciliation_id", "description", "amount_minor",
               "item_date", "aging_bucket", "status", "resolved_at",
               "created_at", "updated_at", "version")
ELIM_FIELDS = ("id", "close_period_id", "entity_period_id_a",
               "entity_period_id_b", "account_code", "amount_a_minor",
               "amount_b_minor", "eliminated_amount_minor", "residual_minor",
               "status", "created_at", "updated_at", "version")
FLUX_FIELDS = ("id", "entity_period_id", "account_code", "prior_balance_minor",
               "current_balance_minor", "variance_minor", "variance_pct",
               "requires_explanation", "explanation_text", "reconciliation_id",
               "status", "created_at", "updated_at", "version")
FX_FIELDS = ("id", "close_period_id", "from_currency", "to_currency",
             "rate_kind", "rate", "effective_at", "created_at", "updated_at",
             "version")
EVENT_FIELDS = ("id", "created_at", "close_period_id", "entity_period_id",
                "event_kind", "actor_user_id", "detail")


def serialize(rec, fields):
    out = {}
    for f in fields:
        v = rec.get(f)
        if isinstance(v, datetime):
            out[f] = fmt_ts(v)
        elif isinstance(v, Decimal):
            out[f] = float(v)
        else:
            out[f] = v
    return out


def ser_period(r):
    return serialize(r, PERIOD_FIELDS)


def ser_entity(r):
    return serialize(r, ENTITY_FIELDS)


def ser_ep(r):
    return serialize(r, EP_FIELDS)


def ser_task(r):
    return serialize(r, TASK_FIELDS)


def ser_cutoff(r):
    return serialize(r, CUTOFF_FIELDS)


def ser_accrual(r):
    return serialize(r, ACCRUAL_FIELDS)


def ser_je(r):
    return serialize(r, JE_FIELDS)


def ser_line(r):
    return serialize(r, LINE_FIELDS)


def ser_doc(r):
    return serialize(r, DOC_FIELDS)


def ser_recon(r):
    return serialize(r, RECON_FIELDS)


def ser_item(r):
    return serialize(r, ITEM_FIELDS)


def ser_elim(r):
    return serialize(r, ELIM_FIELDS)


def ser_flux(r):
    return serialize(r, FLUX_FIELDS)


def ser_fx(r):
    return serialize(r, FX_FIELDS)


def ser_event(r):
    return serialize(r, EVENT_FIELDS)


# ---------------------------------------------------------------------------
# Mutation plumbing
# ---------------------------------------------------------------------------
def touch_ep(ep, period_too=True):
    """An EntityPeriod write bumps its own version and its period's version."""
    bump(ep)
    if period_too:
        p = period_of_ep(ep)
        if p is not None:
            bump(p)


def lock_gate_ep(ep, child_creation=False):
    """PRD §2.10 immutability gates for mutations under an entity-period."""
    period = period_of_ep(ep)
    if period is not None and period["status"] == "FINALIZED":
        raise ApiError("ERR_PERIOD_LOCKED", 409,
                       "Period is FINALIZED; no further mutations allowed")
    if ep["status"] == "HARD_LOCKED":
        if child_creation:
            raise ApiError("ERR_PERIOD_HARD_LOCKED", 409,
                           "Entity-period is HARD_LOCKED and immutable")
        raise ApiError("ERR_PERIOD_LOCKED", 409,
                       "Entity-period is HARD_LOCKED and immutable")
    if ep["status"] == "SOFT_LOCKED":
        raise ApiError("ERR_PERIOD_LOCKED", 409,
                       "Entity-period is SOFT_LOCKED")


def add_event(period_id, ep_id, kind, actor, detail):
    rec = {
        "id": new_id(),
        "created_at": wall_now(),
        "_seq": next_seq(),
        "close_period_id": period_id,
        "entity_period_id": ep_id,
        "event_kind": kind,
        "actor_user_id": actor,
        "detail": detail,
    }
    STORE["events"][rec["id"]] = rec
    return rec


# ---------------------------------------------------------------------------
# Derived-field recomputes
# ---------------------------------------------------------------------------
def recompute_trial_balance(ep):
    total = 0
    for je in STORE["journal_entries"].values():
        if je["entity_period_id"] == ep["id"] and je["status"] == "POSTED":
            total += je["debit_total_minor"] - je["credit_total_minor"]
    ep["trial_balance_minor"] = total


def recompute_unreconciled_count(ep, period_too=True):
    n = sum(1 for r in STORE["reconciliations"].values()
            if r["entity_period_id"] == ep["id"] and r["status"] != "CLEARED")
    if n != ep["unreconciled_count"]:
        ep["unreconciled_count"] = n
        touch_ep(ep, period_too)


def recompute_open_task_count(ep, period_too=True):
    n = sum(1 for t in STORE["tasks"].values()
            if t["entity_period_id"] == ep["id"]
            and t["status"] not in ("DONE", "WAIVED"))
    if n != ep["open_task_count"]:
        ep["open_task_count"] = n
        touch_ep(ep, period_too)


def recompute_aged_over_30(ep, period_too=True):
    n = 0
    for item in STORE["recon_items"].values():
        if item["status"] != "OPEN":
            continue
        if item["aging_bucket"] not in ("AGE_31_60", "AGE_61_90", "AGE_OVER_90"):
            continue
        recon = STORE["reconciliations"].get(item["reconciliation_id"])
        if recon is not None and recon["entity_period_id"] == ep["id"]:
            n += 1
    if n != ep["aged_over_30_count"]:
        ep["aged_over_30_count"] = n
        touch_ep(ep, period_too)


def recompute_period_counts(period):
    eps = eps_of_period(period["id"])
    period["total_entity_count"] = len(eps)
    period["locked_entity_count"] = sum(
        1 for e in eps if e["status"] == "HARD_LOCKED")


def recompute_doc_state(je):
    docs = [d for d in STORE["documents"].values()
            if d["journal_entry_id"] == je["id"] and d["status"] != "REJECTED"]
    if not docs:
        state = "DOC_MISSING"
    elif all(d["status"] == "VERIFIED" for d in docs):
        state = "DOC_VERIFIED"
    else:
        state = "DOC_ATTACHED"
    if state != je["doc_state"]:
        je["doc_state"] = state
        bump(je)


def recompute_recon_difference(recon):
    open_sum = sum(i["amount_minor"] for i in STORE["recon_items"].values()
                   if i["reconciliation_id"] == recon["id"]
                   and i["status"] == "OPEN")
    diff = recon["gl_balance_minor"] - recon["subledger_balance_minor"] - open_sum
    within = abs(diff) <= RECON_TOLERANCE
    if diff != recon["difference_minor"] or within != recon["is_within_tolerance"]:
        recon["difference_minor"] = diff
        recon["is_within_tolerance"] = within
        bump(recon)


# ---------------------------------------------------------------------------
# recon_aging (PRD §3.6)
# ---------------------------------------------------------------------------
def compute_bucket(item, period, now):
    eval_instant = now
    if item["status"] != "OPEN" and item.get("resolved_at") is not None:
        eval_instant = min(now, item["resolved_at"])
    days_past = int((eval_instant - period["period_end"]).total_seconds()
                    // DAY_SECONDS)
    if days_past <= 0:
        return "CURRENT"
    if days_past <= 30:
        return "AGE_1_30"
    if days_past <= 60:
        return "AGE_31_60"
    if days_past <= 90:
        return "AGE_61_90"
    return "AGE_OVER_90"


def recompute_item_bucket(item, now):
    recon = STORE["reconciliations"].get(item["reconciliation_id"])
    if recon is None:
        return
    ep = STORE["entity_periods"].get(recon["entity_period_id"])
    if ep is None:
        return
    period = period_of_ep(ep)
    bucket = compute_bucket(item, period, now)
    if bucket != item["aging_bucket"]:
        item["aging_bucket"] = bucket
        bump(item)


# ---------------------------------------------------------------------------
# CloseTask helpers
# ---------------------------------------------------------------------------
def task_due_instant(task):
    period = STORE["periods"].get(task["close_period_id"])
    return period["period_start"] + timedelta(hours=task["due_offset_hours"])


def recompute_task_is_late(task, now):
    due = task_due_instant(task)
    if task["status"] == "DONE":
        late = task["completed_at"] is not None and task["completed_at"] > due
    elif task["status"] == "WAIVED":
        late = bool(task["is_late"])
    else:
        late = now > due
    if late != task["is_late"]:
        task["is_late"] = late
        bump(task)


def unblock_dependents(finished_task):
    for t in STORE["tasks"].values():
        if t["close_period_id"] != finished_task["close_period_id"]:
            continue
        if t["status"] != "BLOCKED":
            continue
        if finished_task["id"] not in t["depends_on_task_ids"]:
            continue
        deps = [STORE["tasks"].get(d) for d in t["depends_on_task_ids"]]
        if all(d is not None and d["status"] in ("DONE", "WAIVED") for d in deps):
            t["status"] = "READY"
            bump(t)


# ---------------------------------------------------------------------------
# FX + currency_translation (PRD §3.7)
# ---------------------------------------------------------------------------
def find_rate(period_id, frm, to, kind, before=None):
    best = None
    for r in STORE["fx_rates"].values():
        if r["close_period_id"] != period_id:
            continue
        if r["from_currency"] != frm or r["to_currency"] != to:
            continue
        if r["rate_kind"] != kind:
            continue
        if before is not None and r["effective_at"] > before:
            continue
        if best is None or r["effective_at"] > best["effective_at"]:
            best = r
    if best is None:
        return None
    return dec(best["rate"])


def compute_translation(ep, period, entity):
    """Return (translated, cta, remeasurement); raise ERR_FX_RATE_MISSING."""
    rep = period["reporting_currency"]
    func = entity["functional_currency"]
    tb = ep["trial_balance_minor"]
    if func == rep:
        if entity["translation_method"] == "TEMPORAL":
            return tb, 0, 0
        return tb, 0, None
    pe = find_rate(period["id"], func, rep, "PERIOD_END")
    if pe is None:
        raise ApiError("ERR_FX_RATE_MISSING", 409,
                       "Missing PERIOD_END FX rate %s->%s" % (func, rep))
    translated_end = rhu(dec(tb) * pe)
    if entity["translation_method"] == "CURRENT_RATE":
        avg = find_rate(period["id"], func, rep, "AVERAGE")
        if avg is None:
            raise ApiError("ERR_FX_RATE_MISSING", 409,
                           "Missing AVERAGE FX rate %s->%s" % (func, rep))
        cta = translated_end - rhu(dec(tb) * avg)
        return translated_end, cta, None
    # TEMPORAL
    hist = find_rate(period["id"], func, rep, "HISTORICAL",
                     before=period["period_end"])
    if hist is None:
        raise ApiError("ERR_FX_RATE_MISSING", 409,
                       "Missing HISTORICAL FX rate %s->%s" % (func, rep))
    monetary = rhu(dec(tb) * MONETARY_FRACTION)
    nonmonetary = tb - monetary
    translated = rhu(dec(monetary) * pe) + rhu(dec(nonmonetary) * hist)
    remeasurement = translated_end - translated
    return translated, 0, remeasurement


def run_translation(ep, period, entity):
    translated, cta, remeasure = compute_translation(ep, period, entity)
    ep["translated_balance_minor"] = translated
    ep["cta_minor"] = cta
    ep["remeasurement_minor"] = remeasure
    ep["_translation_run"] = True
    ep["_translation_stale"] = False


# ---------------------------------------------------------------------------
# minority_interest (PRD §3.7)
# ---------------------------------------------------------------------------
def compute_nci(ep, entity):
    own = dec(entity["ownership_pct"])
    if own == 100:
        return 0
    translated = ep["translated_balance_minor"]
    if translated is None:
        return 0
    return rhu(dec(translated) * (dec(100) - own) / dec(100))


# ---------------------------------------------------------------------------
# accrual_estimation (PRD §3.4)
# ---------------------------------------------------------------------------
def posted_net_for_account(ep_id, account_code):
    net = 0
    for je in STORE["journal_entries"].values():
        if je["entity_period_id"] != ep_id or je["status"] != "POSTED":
            continue
        for ln in STORE["je_lines"].values():
            if ln["journal_entry_id"] == je["id"] \
                    and ln["account_code"] == account_code:
                if ln["direction"] == "DEBIT":
                    net += ln["amount_minor"]
                else:
                    net -= ln["amount_minor"]
    return net


def _prior_periods(period):
    others = [p for p in STORE["periods"].values()
              if (p["fiscal_year"], p["fiscal_period"])
              < (period["fiscal_year"], period["fiscal_period"])]
    others.sort(key=lambda p: (p["fiscal_year"], p["fiscal_period"]))
    return others


def _ep_for(period_id, entity_id):
    for e in STORE["entity_periods"].values():
        if e["close_period_id"] == period_id and e["entity_id"] == entity_id:
            return e
    return None


def compute_provisional(accr):
    ep = get_ep(accr["entity_period_id"])
    period = period_of_ep(ep)
    basis = accr["basis"]
    if basis in ("PRIOR_3M_AVG", "PRIOR_PERIOD"):
        priors = _prior_periods(period)
        amounts = []
        for p in priors:
            pep = _ep_for(p["id"], ep["entity_id"])
            amounts.append(
                posted_net_for_account(pep["id"], accr["account_code"])
                if pep is not None else 0)
        if basis == "PRIOR_3M_AVG" and len(priors) >= 3:
            return rhu(Decimal(sum(amounts[-3:])) / Decimal(3))
        if not amounts:
            return 0
        return amounts[-1]
    # DAYS_OUTSTANDING
    cutoff = STORE["cutoffs"].get(accr["subledger_cutoff_id"])
    if cutoff is None:
        return 0
    elapsed = int((cutoff["cutoff_at"] - period["period_start"]).total_seconds()
                  // DAY_SECONDS)
    remaining = int((period["period_end"] - cutoff["cutoff_at"]).total_seconds()
                    // DAY_SECONDS)
    if elapsed <= 0:
        return 0
    return rhu(Decimal(cutoff["pre_cutoff_total_minor"]) * Decimal(remaining)
               / Decimal(elapsed))


# ---------------------------------------------------------------------------
# intercompany_elimination (PRD §3.8): translate each side, round, then MIN
# ---------------------------------------------------------------------------
def compute_elim_amounts(pair, period, strict_fx):
    ep_a = get_ep(pair["entity_period_id_a"])
    ep_b = get_ep(pair["entity_period_id_b"])
    ent_a = entity_of_ep(ep_a)
    ent_b = entity_of_ep(ep_b)
    rep = period["reporting_currency"]

    def side(entity, amount):
        if entity["functional_currency"] == rep:
            return abs(amount)
        rate = find_rate(period["id"], entity["functional_currency"], rep,
                         "PERIOD_END")
        if rate is None:
            if strict_fx:
                raise ApiError(
                    "ERR_FX_RATE_MISSING", 409,
                    "Missing PERIOD_END FX rate %s->%s"
                    % (entity["functional_currency"], rep))
            return None
        return rhu(dec(abs(amount)) * rate)

    a_rep = side(ent_a, pair["amount_a_minor"])
    b_rep = side(ent_b, pair["amount_b_minor"])
    if a_rep is None or b_rep is None:
        return None, None
    return min(a_rep, b_rep), a_rep - b_rep


# ---------------------------------------------------------------------------
# Logical-clock re-evaluation (PRD §2.5): recon staleness + task lateness
# ---------------------------------------------------------------------------
def reevaluate_clock(now):
    for recon in list(STORE["reconciliations"].values()):
        if recon["status"] != "OPEN":
            continue
        ep = STORE["entity_periods"].get(recon["entity_period_id"])
        if ep is None:
            continue
        period = period_of_ep(ep)
        if now > period["period_end"] + timedelta(days=30):
            recon["status"] = "STALE"
            bump(recon)
    # Re-age open items at the new instant.
    affected_eps = set()
    for item in list(STORE["recon_items"].values()):
        if item["status"] != "OPEN":
            continue
        before = item["aging_bucket"]
        recompute_item_bucket(item, now)
        if item["aging_bucket"] != before:
            recon = STORE["reconciliations"].get(item["reconciliation_id"])
            if recon is not None:
                affected_eps.add(recon["entity_period_id"])
    for ep_id in affected_eps:
        ep = STORE["entity_periods"].get(ep_id)
        if ep is not None:
            recompute_aged_over_30(ep, period_too=False)
    for ep in list(STORE["entity_periods"].values()):
        recompute_aged_over_30(ep, period_too=False)
    # Task lateness against the new instant (resource-local bumps only).
    for task in list(STORE["tasks"].values()):
        recompute_task_is_late(task, now)


# ---------------------------------------------------------------------------
# translation_chain consolidation (PRD §3.7)
# ---------------------------------------------------------------------------
def run_consolidation(period):
    participating = ("RECONCILED", "READY_FOR_CONSOL", "SOFT_LOCKED",
                     "HARD_LOCKED")
    eps = [e for e in eps_of_period(period["id"])
           if e["status"] in participating]
    # Pinned evaluation order: tier ASC, ties by Entity.created_at ASC.
    eps.sort(key=lambda e: (entity_of_ep(e)["consolidation_tier"],
                            entity_of_ep(e)["created_at"],
                            entity_of_ep(e)["_seq"]))
    # Pass 1: per-entity-period translation (validates rates; may raise).
    results = {}
    for ep in eps:
        results[ep["id"]] = compute_translation(ep, period, entity_of_ep(ep))
    # Pass 2: hop-by-hop aggregation in functional currencies — children
    # always before their parents, so iterate deepest tier first.
    ep_by_entity = {}
    for ep in eps:
        ep_by_entity[entity_of_ep(ep)["id"]] = ep
    agg = {}
    for ep in reversed(eps):
        ent = entity_of_ep(ep)
        total = dec(ep["trial_balance_minor"])
        children = [c for c in STORE["entities"].values()
                    if c["parent_entity_id"] == ent["id"]]
        children.sort(key=lambda c: (c["created_at"], c["_seq"]))
        for child in children:
            cep = ep_by_entity.get(child["id"])
            if cep is None:
                continue
            ctotal = agg[child["id"]]
            own = dec(child["ownership_pct"])
            if own == 100:
                nci_part = Decimal(0)
            else:
                nci_part = Decimal(rhu(ctotal * (dec(100) - own) / dec(100)))
            pshare = ctotal - nci_part
            if child["functional_currency"] == ent["functional_currency"]:
                moved = pshare
            else:
                rate = find_rate(period["id"], child["functional_currency"],
                                 ent["functional_currency"], "PERIOD_END")
                if rate is None:
                    raise ApiError(
                        "ERR_FX_RATE_MISSING", 409,
                        "Missing PERIOD_END FX rate %s->%s"
                        % (child["functional_currency"],
                           ent["functional_currency"]))
                moved = Decimal(rhu(pshare * rate))
            total += moved
        agg[ent["id"]] = total
    rep = period["reporting_currency"]
    consolidated = 0
    for ep in eps:
        ent = entity_of_ep(ep)
        if ent["parent_entity_id"] and \
                ep_by_entity.get(ent["parent_entity_id"]) is not None:
            continue  # non-root: contributed upward through the chain
        if ent["functional_currency"] == rep:
            consolidated += int(agg[ent["id"]])
        else:
            rate = find_rate(period["id"], ent["functional_currency"], rep,
                             "PERIOD_END")
            if rate is None:
                raise ApiError(
                    "ERR_FX_RATE_MISSING", 409,
                    "Missing PERIOD_END FX rate %s->%s"
                    % (ent["functional_currency"], rep))
            consolidated += rhu(agg[ent["id"]] * rate)
    # Pass 3: write back per-entity-period results.
    nci_total = 0
    cta_total = 0
    for ep in eps:
        translated, cta, remeasure = results[ep["id"]]
        ep["translated_balance_minor"] = translated
        ep["cta_minor"] = cta
        ep["remeasurement_minor"] = remeasure
        nci = compute_nci(ep, entity_of_ep(ep))
        ep["nci_share_minor"] = nci
        ep["_translation_run"] = True
        ep["_translation_stale"] = False
        nci_total += nci
        cta_total += cta
        bump(ep)
    if eps:
        bump(period)
    tiers = len({entity_of_ep(ep)["consolidation_tier"] for ep in eps})
    return {
        "consolidated_balance_minor": consolidated,
        "consolidated_nci_minor": nci_total,
        "consolidated_cta_minor": cta_total,
        "tiers_processed": tiers,
    }


# ---------------------------------------------------------------------------
# close_metrics (PRD §3.9)
# ---------------------------------------------------------------------------
def compute_close_metrics(period, now):
    days_to_close = int((now - period["period_end"]).total_seconds()
                        // DAY_SECONDS)
    tasks = [t for t in STORE["tasks"].values()
             if t["close_period_id"] == period["id"]]
    for t in tasks:
        recompute_task_is_late(t, now)
    late = sum(1 for t in tasks if t["is_late"])
    done_waived = sum(1 for t in tasks if t["status"] in ("DONE", "WAIVED"))
    if tasks:
        pct = float(rhu2(Decimal(done_waived) * Decimal(100)
                         / Decimal(len(tasks))))
    else:
        pct = 0.0
    eps = eps_of_period(period["id"])
    aged = sum(e["aged_over_30_count"] for e in eps)
    ep_ids = {e["id"] for e in eps}
    open_value = 0
    for item in STORE["recon_items"].values():
        if item["status"] != "OPEN":
            continue
        recon = STORE["reconciliations"].get(item["reconciliation_id"])
        if recon is not None and recon["entity_period_id"] in ep_ids:
            open_value += item["amount_minor"]
    return {
        "days_to_close": days_to_close,
        "late_task_count": late,
        "task_completion_pct": pct,
        "aged_item_count": aged,
        "open_item_value_minor": open_value,
    }


def json_detail(obj):
    return json.dumps(obj, sort_keys=True)


# ---------------------------------------------------------------------------
# System-generated journal entries (accrual balancing, write-off, elimination)
# ---------------------------------------------------------------------------
def create_je(ep, je_type, entry_date, lines_spec, preparer_user_id,
              approver_user_id=None, status="DRAFT"):
    """Create a JournalEntry with inline lines on an entity-period.

    lines_spec: list of dicts with account_code, direction, amount_minor and
    optional counterparty_entity_id / memo. Totals are computed from lines.
    """
    entity = entity_of_ep(ep)
    debit_total = sum(l["amount_minor"] for l in lines_spec
                      if l["direction"] == "DEBIT")
    credit_total = sum(l["amount_minor"] for l in lines_spec
                       if l["direction"] == "CREDIT")
    je = base_record()
    je.update({
        "entity_period_id": ep["id"],
        "je_type": je_type,
        "entry_date": entry_date,
        "preparer_user_id": preparer_user_id,
        "approver_user_id": approver_user_id,
        "debit_total_minor": debit_total,
        "credit_total_minor": credit_total,
        "functional_currency": entity["functional_currency"],
        "status": status,
        "doc_state": "DOC_MISSING",
        "rejection_reason": None,
        "posted_at": None,
    })
    STORE["journal_entries"][je["id"]] = je
    for idx, spec in enumerate(lines_spec, start=1):
        line = base_record()
        line.update({
            "journal_entry_id": je["id"],
            "line_no": spec.get("line_no", idx),
            "account_code": spec["account_code"],
            "direction": spec["direction"],
            "amount_minor": spec["amount_minor"],
            "counterparty_entity_id": spec.get("counterparty_entity_id"),
            "memo": spec.get("memo"),
        })
        STORE["je_lines"][line["id"]] = line
    return je
