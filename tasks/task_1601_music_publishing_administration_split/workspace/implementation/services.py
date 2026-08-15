"""Business logic: record lifecycle, rollups, calculations, cascades."""
from db import STORE, RECOUP_LEDGER
import db
from errors import ApiError, ERR_NOT_FOUND

WRITER_POOL_BP = 5000
MIN_PAYOUT_CENTS = 2500


# ---------------------------------------------------------------------------
# generic record helpers
# ---------------------------------------------------------------------------

def new_record():
    ts = db.tick()
    return {"id": db.new_id(), "created_at": ts, "updated_at": ts, "version": 1}


def touch(rec):
    rec["version"] += 1
    rec["updated_at"] = db.tick()


def get_or_404(collection, rid, label=None):
    rec = STORE[collection].get(rid)
    if rec is None:
        raise ApiError(ERR_NOT_FOUND, 404, "%s not found" % (label or collection))
    return rec


def sorted_all(collection):
    return sorted(STORE[collection].values(), key=lambda r: (r["created_at"], r["id"]))


# ---------------------------------------------------------------------------
# lazy derivations (PRD section 2.5)
# ---------------------------------------------------------------------------

def agreement_status(ag):
    if ag["status"] == "ACTIVE" and db.clock_now() >= ag["effective_to"]:
        return "EXPIRED"
    return ag["status"]


def claim_status(claim):
    stored = claim["status"]
    if stored == "TRACKING":
        now = db.clock_now()
        if now > claim["window_close_date"]:
            return "LAPSED"
        if now >= claim["window_open_date"]:
            return "NOTICE_WINDOW_OPEN"
        return "TRACKING"
    return stored


# ---------------------------------------------------------------------------
# rollups (PRD section 2.9 / 3.5 / 3.7)
# ---------------------------------------------------------------------------

def recompute_work_rollup(work):
    collected = 0
    distributed = 0
    for line in STORE["statement_lines"].values():
        if line["work_id"] != work["id"]:
            continue
        st = STORE["royalty_statements"][line["statement_id"]]
        if st["status"] in ("FINALIZED", "DISTRIBUTED"):
            collected += line["gross_cents"]
        if st["status"] == "DISTRIBUTED":
            distributed += line["gross_cents"]
    work["total_collected_cents"] = collected
    work["total_distributed_cents"] = distributed
    touch(work)


def recompute_writer_rollups(writer):
    outstanding = sum(
        a["outstanding_cents"]
        for a in STORE["advances"].values()
        if a["writer_id"] == writer["id"] and a["status"] in ("PAID", "RECOUPING")
    )
    earned = sum(
        al["final_amount_cents"] or 0
        for al in STORE["allocation_lines"].values()
        if al["writer_id"] == writer["id"] and al["status"] == "FINAL"
    )
    writer["advance_outstanding_cents"] = outstanding
    writer["lifetime_earned_cents"] = earned
    touch(writer)


# ---------------------------------------------------------------------------
# split sets
# ---------------------------------------------------------------------------

def confirmed_split_set(work_id):
    for ss in STORE["split_sets"].values():
        if ss["work_id"] == work_id and ss["status"] == "CONFIRMED":
            return ss
    return None


def split_lines_of(split_set_id):
    return sorted(
        [sl for sl in STORE["split_lines"].values()
         if sl["split_set_id"] == split_set_id],
        key=lambda r: (r["created_at"], r["id"]),
    )


def terminate_work_rights(work):
    """Cascade for copyright_status -> TERMINATED (PRD section 3.10)."""
    work["copyright_status"] = "TERMINATED"
    touch(work)
    for ss in STORE["split_sets"].values():
        if ss["work_id"] != work["id"]:
            continue
        if ss["status"] in ("DRAFT", "PENDING_CONFIRMATIONS", "DISPUTED"):
            ss["status"] = "CANCELLED"
            touch(ss)
            for line in split_lines_of(ss["id"]):
                if line["confirmation_status"] == "PENDING":
                    line["confirmation_status"] = "REJECTED"
                    line["rejection_reason"] = "WORK_RIGHTS_TERMINATED"
                    touch(line)


# ---------------------------------------------------------------------------
# statement matching
# ---------------------------------------------------------------------------

def statement_lines_of(statement_id):
    return sorted(
        [l for l in STORE["statement_lines"].values()
         if l["statement_id"] == statement_id],
        key=lambda r: (r["created_at"], r["id"]),
    )


def auto_match_line(line):
    candidates = []  # (is_iswc_match, created_at, work)
    for work in STORE["works"].values():
        if work["registration_status"] != "REGISTERED":
            continue
        is_iswc = (
            line["reported_iswc"] is not None
            and work["iswc"] is not None
            and work["iswc"] == line["reported_iswc"]
        )
        is_code = (
            line["reported_work_code"] is not None
            and work["work_code"] == line["reported_work_code"]
        )
        if is_iswc or is_code:
            candidates.append((0 if is_iswc else 1, work["created_at"], work))
    if not candidates:
        return
    candidates.sort(key=lambda c: (c[0], c[1], c[2]["id"]))
    best = candidates[0][2]
    line["work_id"] = best["id"]
    line["match_status"] = "AUTO_MATCHED"
    touch(line)


# ---------------------------------------------------------------------------
# allocation calculations (PRD section 3.5)
# ---------------------------------------------------------------------------

def select_sub_publishing_agreement(stmt):
    """Deterministic selector; at most one ACTIVE agreement can cover."""
    found = None
    for ag in sorted_all("sub_publishing_agreements"):
        if agreement_status(ag) != "ACTIVE":
            continue
        if stmt["territory_code"] not in ag["territory_codes"]:
            continue
        if stmt["income_type"] not in ag["income_types"]:
            continue
        if ag["effective_from"] <= stmt["period_end"] < ag["effective_to"]:
            found = ag
            break
    return found


def _pool_amounts(pool, pool_lines):
    """floor per line, then remainder one cent at a time by share_bp DESC,
    tie-break SplitLine.created_at ASC; at most one cent per line per pass."""
    amounts = {sl["id"]: (pool * sl["share_bp"]) // 10000 for sl in pool_lines}
    remainder = pool - sum(amounts.values())
    order = sorted(pool_lines, key=lambda sl: (-sl["share_bp"], sl["created_at"], sl["id"]))
    idx = 0
    while remainder > 0 and order:
        amounts[order[idx % len(order)]["id"]] += 1
        remainder -= 1
        idx += 1
    return amounts


def compute_allocations(stmt, stage, pinned_split_lines=None):
    """Compute per-(statement_line, split_line) amounts.

    stage: "provisional" (allocate; unmatched spread applies) or
           "final" (finalize; E = gross, unmatched goes to suspense).
    pinned_split_lines: optional {statement_line_id: [split_line, ...]} used at
           finalize to keep allocation pinned to the SplitSet CONFIRMED at
           allocation time.
    Returns (rows, retained_total, unmatched_total) where rows is a list of
    dicts {statement_line, split_line, amount} in pinned creation order.
    """
    lines = statement_lines_of(stmt["id"])
    matched = [l for l in lines if l["match_status"] in ("AUTO_MATCHED", "MANUAL_MATCHED")]
    unmatched = [l for l in lines if l["match_status"] == "UNMATCHED"]
    unmatched_total = sum(l["gross_cents"] for l in unmatched)
    matched_total = sum(l["gross_cents"] for l in matched)

    # provisional unmatched spread
    spreads = {l["id"]: 0 for l in matched}
    if stage == "provisional" and unmatched_total > 0 and matched_total > 0:
        remainder = unmatched_total
        for l in matched:
            add = (unmatched_total * l["gross_cents"]) // matched_total
            spreads[l["id"]] = add
            remainder -= add
        order = sorted(matched, key=lambda l: (-l["gross_cents"], l["created_at"], l["id"]))
        idx = 0
        while remainder > 0 and order:
            spreads[order[idx % len(order)]["id"]] += 1
            remainder -= 1
            idx += 1

    agreement = select_sub_publishing_agreement(stmt)
    rows = []
    retained_total = 0
    for line in matched:
        E = line["gross_cents"] + (spreads[line["id"]] if stage == "provisional" else 0)
        R = (E * agreement["retention_bp"]) // 10000 if agreement else 0
        retained_total += R
        net = E - R
        writer_pool = (net * WRITER_POOL_BP) // 10000
        publisher_pool = net - writer_pool  # odd remainder cent to publisher pool

        if pinned_split_lines is not None:
            slines = pinned_split_lines[line["id"]]
        else:
            sset = confirmed_split_set(line["work_id"])
            slines = split_lines_of(sset["id"])
        wlines = [sl for sl in slines if sl["participant_type"] == "WRITER"]
        plines = [sl for sl in slines if sl["participant_type"] == "PUBLISHER"]
        w_amounts = _pool_amounts(writer_pool, wlines)
        p_amounts = _pool_amounts(publisher_pool, plines)
        # pinned creation order: WRITER rows first (created_at ASC), then PUBLISHER
        for sl in wlines:
            rows.append({"statement_line": line, "split_line": sl,
                         "amount": w_amounts[sl["id"]]})
        for sl in plines:
            rows.append({"statement_line": line, "split_line": sl,
                         "amount": p_amounts[sl["id"]]})
    return rows, retained_total, unmatched_total


# ---------------------------------------------------------------------------
# recoupment waterfall (PRD section 3.7) and reversal (PRD section 3.6)
# ---------------------------------------------------------------------------

def apply_recoupment(allocation_row):
    """Run the waterfall for one FINAL WRITER allocation row. Returns the
    affected writer (or None for publisher rows)."""
    writer_id = allocation_row["writer_id"]
    if writer_id is None:
        allocation_row["advance_applied_cents"] = 0
        allocation_row["net_payable_cents"] = 0
        return None
    remaining = allocation_row["final_amount_cents"]
    advances = sorted(
        [a for a in STORE["advances"].values()
         if a["writer_id"] == writer_id and a["status"] in ("PAID", "RECOUPING")],
        key=lambda a: (a["paid_at"] or a["created_at"], a["created_at"], a["id"]),
    )
    for adv in advances:
        if remaining == 0:
            break
        budget = (remaining * adv["recoup_rate_bp"]) // 10000
        applied = min(budget, adv["outstanding_cents"])
        if applied <= 0:
            continue
        adv["recouped_cents"] += applied
        adv["outstanding_cents"] -= applied
        remaining -= applied
        if adv["outstanding_cents"] == 0:
            adv["status"] = "RECOUPED"
        elif adv["status"] == "PAID":
            adv["status"] = "RECOUPING"
        touch(adv)
        RECOUP_LEDGER.append({
            "seq": db.next_ledger_seq(),
            "statement_id": allocation_row["statement_id"],
            "allocation_line_id": allocation_row["id"],
            "advance_id": adv["id"],
            "amount": applied,
        })
    allocation_row["advance_applied_cents"] = allocation_row["final_amount_cents"] - remaining
    allocation_row["net_payable_cents"] = remaining
    writer = STORE["writers"][writer_id]
    writer["payable_balance_cents"] += remaining
    return writer


def supersede_statement(target):
    """FINALIZED -> SUPERSEDED with full financial reversal (PRD 3.6)."""
    target["status"] = "SUPERSEDED"
    touch(target)

    # reverse recoupment applications in reverse chronological order
    entries = [e for e in RECOUP_LEDGER if e["statement_id"] == target["id"]]
    entries.sort(key=lambda e: e["seq"], reverse=True)
    for e in entries:
        adv = STORE["advances"].get(e["advance_id"])
        if adv is None:
            continue
        adv["recouped_cents"] -= e["amount"]
        adv["outstanding_cents"] += e["amount"]
        if adv["status"] == "RECOUPED" and adv["recouped_cents"] > 0:
            adv["status"] = "RECOUPING"
        elif adv["status"] == "RECOUPING" and adv["recouped_cents"] == 0:
            adv["status"] = "PAID"
        touch(adv)

    affected_writers = {}
    for row in STORE["allocation_lines"].values():
        if row["statement_id"] == target["id"] and row["status"] == "FINAL":
            row["status"] = "REVERSED"
            touch(row)
            if row["writer_id"] is not None:
                writer = STORE["writers"][row["writer_id"]]
                writer["payable_balance_cents"] -= row["net_payable_cents"]
                affected_writers[writer["id"]] = writer
    for writer in affected_writers.values():
        recompute_writer_rollups(writer)

    work_ids = set()
    for line in statement_lines_of(target["id"]):
        if line["work_id"] is not None:
            work_ids.add(line["work_id"])
    for wid in work_ids:
        work = STORE["works"].get(wid)
        if work is not None:
            recompute_work_rollup(work)
