"""Business logic for the ACH ODFI Origination API.

Implements the scaffold §1.2 state machines' side effects and §1.3
calculations: banking-day arithmetic, outstanding exposure, file fees,
unauthorized return rates, window assignment, batch dispatch/settle with GL
postings, and the originator suspension/termination cascades.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

import db
from db import touch, stamp_new, stamp_new_light, now_logical_iso, parse_iso
from util import sort_by_created_at, hhmm_to_minutes, round_half_up_int


# ---------------------------------------------------------------------------
# Constants (scaffold §1.3)
# ---------------------------------------------------------------------------

SEC_CODES = {"PPD", "CCD", "WEB", "TEL"}
WINDOW_KINDS = {"SAME_DAY_1", "SAME_DAY_2", "SAME_DAY_3", "NEXT_DAY"}
SAME_DAY_KINDS = {"SAME_DAY_1", "SAME_DAY_2", "SAME_DAY_3"}
RETURN_CODES = {"R01", "R02", "R05", "R07", "R10"}
UNAUTH_CODES = {"R05", "R07", "R10"}
NOC_CODES = {"C01", "C02", "C03"}
REVERSAL_REASONS = {"DUPLICATE_ENTRY", "WRONG_AMOUNT", "WRONG_ACCOUNT"}
RESOLUTION_ACTIONS = {"SUSPEND", "WATCH", "REINSTATE", "TERMINATE", "DISMISS"}

UNAUTH_THRESHOLD_BPS = 50
TRAILING_WINDOW_DAYS = 60
LARGE_ENTRY_THRESHOLD_CENTS = 10000000      # $100,000.00; strictly greater triggers surcharge
SAME_DAY_MAX_ENTRY_CENTS = 100000000        # $1,000,000.00; strictly greater is ineligible
REPRESENTMENT_CAP = 2


# ---------------------------------------------------------------------------
# Banking-day calendar (PRD §2.4; calculation banking_day_add)
# ---------------------------------------------------------------------------


def is_banking_day(d: date) -> bool:
    """Banking days are Monday-Friday; there is no holiday table."""
    return d.weekday() < 5


def banking_day_add(d: date, n: int) -> date:
    """Advance one calendar day at a time, counting only Mon-Fri days."""
    cur = d
    counted = 0
    while counted < n:
        cur += timedelta(days=1)
        if is_banking_day(cur):
            counted += 1
    return cur


def today_logical() -> date:
    return db.clock().date()


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------


def entries_of_file(file_id: str) -> list[dict]:
    return sort_by_created_at(
        [e for e in db.ach_entries.values() if e["file_id"] == file_id]
    )


def file_of_entry(entry: dict) -> dict:
    return db.ach_files[entry["file_id"]]


def originator_id_of_entry(entry: dict) -> str:
    return file_of_entry(entry)["originator_id"]


def window_by_kind(kind: str) -> dict | None:
    for w in db.cutoff_windows.values():
        if w["window_kind"] == kind:
            return w
    return None


# ---------------------------------------------------------------------------
# Outstanding exposure (calculation outstanding_exposure)
# ---------------------------------------------------------------------------


def compute_exposure(originator_id: str) -> tuple[int, int]:
    """Sum amount_cents over the originator's entries in WAREHOUSED/TRANSMITTED.

    Returns (gross_cents, debit_only_cents). Integer cents, no rounding.
    """
    gross = 0
    debit = 0
    for e in db.ach_entries.values():
        if e["status"] not in ("WAREHOUSED", "TRANSMITTED"):
            continue
        if originator_id_of_entry(e) != originator_id:
            continue
        gross += e["amount_cents"]
        if e["direction"] == "DEBIT":
            debit += e["amount_cents"]
    return gross, debit


def recompute_exposure(originator_id: str) -> None:
    """Refresh an originator's exposure fields; touch only on real change."""
    o = db.originators.get(originator_id)
    if o is None:
        return
    gross, debit = compute_exposure(originator_id)
    if (
        o["outstanding_exposure_gross_cents"] != gross
        or o["outstanding_exposure_debit_cents"] != debit
    ):
        o["outstanding_exposure_gross_cents"] = gross
        o["outstanding_exposure_debit_cents"] = debit
        touch(o)


# ---------------------------------------------------------------------------
# File fee (calculation file_fee)
# ---------------------------------------------------------------------------


def discounted_entry_fee(per_entry_fee: int, fee_discount_bps: int) -> int:
    """round_half_up(per_entry_fee * (10000 - bps) / 10000) — per entry, then summed."""
    raw = Decimal(per_entry_fee) * Decimal(10000 - fee_discount_bps) / Decimal(10000)
    return round_half_up_int(raw)


def compute_file_fee(file: dict, window: dict, originator: dict) -> int:
    """file_fee_cents (never discounted) + sum of discounted per-entry fees.

    Per-entry fee = per_entry_fee_cents + large_entry_surcharge_cents when the
    entry amount is strictly greater than LARGE_ENTRY_THRESHOLD_CENTS.
    """
    fee = window["file_fee_cents"]
    for e in entries_of_file(file["id"]):
        per = window["per_entry_fee_cents"]
        if e["amount_cents"] > LARGE_ENTRY_THRESHOLD_CENTS:
            per += window["large_entry_surcharge_cents"]
        fee += discounted_entry_fee(per, originator["fee_discount_bps"])
    return fee


def recompute_file_totals(file: dict) -> None:
    """entry_count / total_amount_cents over ALL entries of the file (never decremented)."""
    entries = entries_of_file(file["id"])
    file["entry_count"] = len(entries)
    file["total_amount_cents"] = sum(e["amount_cents"] for e in entries)


# ---------------------------------------------------------------------------
# Unauthorized return rate (calculation unauthorized_return_rate)
# ---------------------------------------------------------------------------


def compute_rates(originator_id: str, computed_at: datetime) -> dict:
    """Two variants: trailing-60d half-open window; MTD closed window.

    trailing: (computed_at - 60d, computed_at]  — exactly 60 days old EXCLUDED
    mtd:      [month_start 00:00:00.000Z, computed_at] — both ends inclusive
    rate = 0 when denominator == 0, else round_half_up(10000 * num / den).
    """
    trailing_start = computed_at - timedelta(days=TRAILING_WINDOW_DAYS)
    month_start = computed_at.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    unauth_60d = debits_60d = unauth_mtd = debits_mtd = 0

    for rc in db.return_cases.values():
        if not rc["is_unauthorized"]:
            continue
        entry = db.ach_entries[rc["entry_id"]]
        if entry["direction"] != "DEBIT":
            continue
        if originator_id_of_entry(entry) != originator_id:
            continue
        received = parse_iso(rc["received_at"])
        if trailing_start < received <= computed_at:
            unauth_60d += 1
        if month_start <= received <= computed_at:
            unauth_mtd += 1

    for e in db.ach_entries.values():
        if e["direction"] != "DEBIT":
            continue
        if originator_id_of_entry(e) != originator_id:
            continue
        ft = e["first_transmitted_at"]
        if ft is None:
            continue
        ftd = parse_iso(ft)
        if trailing_start < ftd <= computed_at:
            debits_60d += 1
        if month_start <= ftd <= computed_at:
            debits_mtd += 1

    rate_60d = (
        0
        if debits_60d == 0
        else round_half_up_int(Decimal(10000 * unauth_60d) / Decimal(debits_60d))
    )
    rate_mtd = (
        0
        if debits_mtd == 0
        else round_half_up_int(Decimal(10000 * unauth_mtd) / Decimal(debits_mtd))
    )
    # Strictly greater-than: exactly UNAUTH_THRESHOLD_BPS does NOT breach.
    breach = rate_60d > UNAUTH_THRESHOLD_BPS or rate_mtd > UNAUTH_THRESHOLD_BPS
    return {
        "unauth_returns_60d": unauth_60d,
        "debits_60d": debits_60d,
        "unauth_returns_mtd": unauth_mtd,
        "debits_mtd": debits_mtd,
        "rate_bps_trailing_60d": rate_60d,
        "rate_bps_mtd": rate_mtd,
        "breach": breach,
    }


def refresh_originator_rates(originator_id: str, computed_at: datetime) -> dict:
    """Recompute both rate variants and write them onto the originator.

    Returns the computed rates dict (for breach evaluation).
    """
    rates = compute_rates(originator_id, computed_at)
    o = db.originators[originator_id]
    if (
        o["unauth_rate_bps_trailing"] != rates["rate_bps_trailing_60d"]
        or o["unauth_rate_bps_mtd"] != rates["rate_bps_mtd"]
    ):
        o["unauth_rate_bps_trailing"] = rates["rate_bps_trailing_60d"]
        o["unauth_rate_bps_mtd"] = rates["rate_bps_mtd"]
        touch(o)
    return rates


def maybe_auto_open_rate_breach_case(originator_id: str) -> dict | None:
    """Open a RiskCase (OPEN, RATE_BREACH) iff none is OPEN for the originator."""
    for rc in db.risk_cases.values():
        if (
            rc["originator_id"] == originator_id
            and rc["source"] == "RATE_BREACH"
            and rc["status"] == "OPEN"
        ):
            return None
    case = {
        "originator_id": originator_id,
        "source": "RATE_BREACH",
        "status": "OPEN",
        "resolution_action": None,
        "resolved_by_user_id": None,
    }
    stamp_new(case)
    db.risk_cases[case["id"]] = case
    return case


# ---------------------------------------------------------------------------
# NOC overdue sweep (PRD §2.4 side effect of clock set)
# ---------------------------------------------------------------------------


def noc_overdue_sweep() -> None:
    """RECEIVED NocRecords whose due_date is strictly before the current
    banking day transition to OVERDUE."""
    today = today_logical().isoformat()
    for noc in db.noc_records.values():
        if noc["status"] == "RECEIVED" and noc["due_date"] < today:
            noc["status"] = "OVERDUE"
            touch(noc)


# ---------------------------------------------------------------------------
# GL postings (PRD §3.5 ledger rules)
# ---------------------------------------------------------------------------


def post_gl(batch_id: str, account_code: str, debit_cents: int, credit_cents: int, memo: str) -> dict:
    """Append one balanced leg. Exactly one of debit/credit is > 0."""
    row = {
        "settlement_batch_id": batch_id,
        "account_code": account_code,
        "debit_cents": debit_cents,
        "credit_cents": credit_cents,
        "memo": memo,
        "posted_at": now_logical_iso(),
    }
    stamp_new_light(row)
    db.gl_postings[row["id"]] = row
    return row


def post_settlement_pair(batch_id: str, entry: dict) -> None:
    """DEBIT entry credits ORIGINATOR_RECEIVABLE; CREDIT entry debits it;
    SETTLEMENT_CLEARING takes the opposite leg."""
    amount = entry["amount_cents"]
    if entry["direction"] == "DEBIT":
        post_gl(batch_id, "ORIGINATOR_RECEIVABLE", 0, amount, f"entry:{entry['id']} settlement")
        post_gl(batch_id, "SETTLEMENT_CLEARING", amount, 0, f"entry:{entry['id']} settlement")
    else:
        post_gl(batch_id, "ORIGINATOR_RECEIVABLE", amount, 0, f"entry:{entry['id']} settlement")
        post_gl(batch_id, "SETTLEMENT_CLEARING", 0, amount, f"entry:{entry['id']} settlement")


def post_inverse_pair(batch_id: str, entry: dict, memo: str) -> None:
    """Exact inverse of the entry's settlement pair (returns / reversals)."""
    amount = entry["amount_cents"]
    if entry["direction"] == "DEBIT":
        post_gl(batch_id, "ORIGINATOR_RECEIVABLE", amount, 0, memo)
        post_gl(batch_id, "SETTLEMENT_CLEARING", 0, amount, memo)
    else:
        post_gl(batch_id, "ORIGINATOR_RECEIVABLE", 0, amount, memo)
        post_gl(batch_id, "SETTLEMENT_CLEARING", amount, 0, memo)


# ---------------------------------------------------------------------------
# Re-flow sweep set (batch_settlement_net step 3 / settle side effect)
# ---------------------------------------------------------------------------


def sweep_set_for_originator(originator_id: str, exclude_entry_ids: set[str]) -> dict:
    """The originator-scoped re-flow sweep set as it exists right now.

    - unposted ReturnCases (gl_posted == false)
    - re-presented entries (TRANSMITTED, representment_count >= 1, not in the
      current dispatch set)
    - TRANSMITTED ReversalRequests
    """
    unposted_returns = sort_by_created_at(
        [
            rc
            for rc in db.return_cases.values()
            if not rc["gl_posted"]
            and originator_id_of_entry(db.ach_entries[rc["entry_id"]]) == originator_id
        ]
    )
    represented_entries = sort_by_created_at(
        [
            e
            for e in db.ach_entries.values()
            if e["status"] == "TRANSMITTED"
            and e["representment_count"] >= 1
            and e["id"] not in exclude_entry_ids
            and originator_id_of_entry(e) == originator_id
        ]
    )
    transmitted_reversals = sort_by_created_at(
        [
            rr
            for rr in db.reversal_requests.values()
            if rr["status"] == "TRANSMITTED"
            and originator_id_of_entry(db.ach_entries[rr["entry_id"]]) == originator_id
        ]
    )
    return {
        "returns": unposted_returns,
        "represented": represented_entries,
        "reversals": transmitted_reversals,
    }


def reflow_amount(sweep: dict) -> int:
    """Signed re-flow adjustment over a sweep set (integer cents)."""
    total = 0
    for rc in sweep["returns"]:
        entry = db.ach_entries[rc["entry_id"]]
        total += -entry["amount_cents"] if entry["direction"] == "DEBIT" else entry["amount_cents"]
    for e in sweep["represented"]:
        total += e["amount_cents"] if e["direction"] == "DEBIT" else -e["amount_cents"]
    for rr in sweep["reversals"]:
        entry = db.ach_entries[rr["entry_id"]]
        total += -entry["amount_cents"] if entry["direction"] == "DEBIT" else entry["amount_cents"]
    return total


# ---------------------------------------------------------------------------
# Batch lifecycle (SettlementBatch machine + batch_settlement_net)
# ---------------------------------------------------------------------------


def find_or_create_batch(window_kind: str, settlement_date: str) -> dict:
    """Find-or-create the OPEN SettlementBatch keyed on (window_kind, settlement_date)."""
    for b in db.settlement_batches.values():
        if (
            b["window_kind"] == window_kind
            and b["settlement_date"] == settlement_date
            and b["status"] == "OPEN"
        ):
            return b
    batch = {
        "window_kind": window_kind,
        "settlement_date": settlement_date,
        "status": "OPEN",
        "expected_net_cents": None,
        "posted_net_cents": None,
        "recon_variance_cents": None,
        "dispatched_by_user_id": None,
        "reconciled_by_user_id": None,
    }
    stamp_new(batch)
    db.settlement_batches[batch["id"]] = batch
    return batch


def batch_files(batch: dict, statuses: tuple[str, ...] | None = None) -> list[dict]:
    files = [
        f for f in db.ach_files.values() if f["settlement_batch_id"] == batch["id"]
    ]
    if statuses is not None:
        files = [f for f in files if f["status"] in statuses]
    return sort_by_created_at(files)


def dispatch_batch(batch: dict, user_id: str) -> None:
    """OPEN -> DISPATCHED: files RELEASED -> DISPATCHED, entries -> TRANSMITTED,
    expected_net_cents computed in pinned evaluation order (dispatch snapshot)."""
    files = batch_files(batch, ("RELEASED",))
    dispatched_entries: list[dict] = []
    dispatched_entry_ids: list[str] = []
    affected_originators: list[str] = []

    for f in files:
        f["status"] = "DISPATCHED"
        touch(f)
        for e in entries_of_file(f["id"]):
            if e["status"] != "WAREHOUSED":
                continue
            e["status"] = "TRANSMITTED"
            if e["first_transmitted_at"] is None:
                e["first_transmitted_at"] = now_logical_iso()
            touch(e)
            dispatched_entries.append(e)
            dispatched_entry_ids.append(e["id"])
            oid = f["originator_id"]
            if oid not in affected_originators:
                affected_originators.append(oid)

    db.dispatch_sets[batch["id"]] = dispatched_entry_ids

    # step 1: principal net over this batch's dispatched entries
    principal_net = 0
    for e in dispatched_entries:
        principal_net += e["amount_cents"] if e["direction"] == "DEBIT" else -e["amount_cents"]
    # step 2: fee total over this batch's dispatched files (per-file assessed fee)
    fee_total = sum(f["assessed_fee_cents"] or 0 for f in files)
    # step 3: re-flow adjustment over the dispatch-time sweep set
    dispatch_id_set = set(dispatched_entry_ids)
    reflow = 0
    for oid in affected_originators:
        reflow += reflow_amount(sweep_set_for_originator(oid, dispatch_id_set))
    # step 4
    batch["expected_net_cents"] = principal_net - fee_total + reflow

    batch["dispatched_by_user_id"] = user_id
    batch["status"] = "DISPATCHED"
    touch(batch)


def settle_batch(batch: dict) -> None:
    """DISPATCHED -> SETTLED: entries settle, GL pairs post (settlement + fees
    + originator-scoped re-flow sweep as it exists AT SETTLE), posted net computed."""
    batch_id = batch["id"]
    dispatch_id_set = set(db.dispatch_sets.get(batch_id, []))

    # This batch's TRANSMITTED entries (the dispatch set).
    own_entries = sort_by_created_at(
        [
            e
            for e in db.ach_entries.values()
            if e["id"] in dispatch_id_set and e["status"] == "TRANSMITTED"
        ]
    )
    affected_originators: list[str] = []
    for e in own_entries:
        oid = originator_id_of_entry(e)
        if oid not in affected_originators:
            affected_originators.append(oid)

    # 1. settle this batch's entries; settlement pair per entry
    for e in own_entries:
        e["status"] = "SETTLED"
        e["settled_at"] = now_logical_iso()
        touch(e)
        post_settlement_pair(batch_id, e)

    # 2. settled files DISPATCHED -> SETTLED; fee pair per file
    for f in batch_files(batch, ("DISPATCHED",)):
        f["status"] = "SETTLED"
        touch(f)
        fee = f["assessed_fee_cents"] or 0
        if fee > 0:
            post_gl(batch_id, "ORIGINATOR_RECEIVABLE", fee, 0, f"file:{f['id']} fee")
            post_gl(batch_id, "FEE_INCOME", 0, fee, f"file:{f['id']} fee")

    # 3. originator-scoped re-flow sweep, evaluated as it exists AT SETTLE
    for oid in affected_originators:
        sweep = sweep_set_for_originator(oid, dispatch_id_set)
        # (a) re-presented entries settle here with settlement pairs
        for e in sweep["represented"]:
            e["status"] = "SETTLED"
            e["settled_at"] = now_logical_iso()
            touch(e)
            post_settlement_pair(batch_id, e)
        # (b) unposted return cases post reversing pairs, marked gl_posted
        for rc in sweep["returns"]:
            entry = db.ach_entries[rc["entry_id"]]
            post_inverse_pair(batch_id, entry, f"return:{rc['id']}")
            rc["gl_posted"] = True
            touch(rc)
        # (c) transmitted reversals settle with the exact inverse pair
        for rr in sweep["reversals"]:
            entry = db.ach_entries[rr["entry_id"]]
            post_inverse_pair(batch_id, entry, f"reversal:{rr['id']}")
            rr["status"] = "SETTLED"
            touch(rr)

    # posted net: signed sum of this batch's ORIGINATOR_RECEIVABLE rows
    posted = 0
    for row in db.gl_postings.values():
        if row["settlement_batch_id"] != batch_id:
            continue
        if row["account_code"] != "ORIGINATOR_RECEIVABLE":
            continue
        posted += row["credit_cents"] - row["debit_cents"]
    batch["posted_net_cents"] = posted
    batch["status"] = "SETTLED"
    touch(batch)

    # exposure recompute for every affected originator
    for oid in affected_originators:
        recompute_exposure(oid)


# ---------------------------------------------------------------------------
# Originator suspension/termination cascade (PRD §2.9 / §3.8)
# ---------------------------------------------------------------------------


def cascade_reject_warehoused_files(originator_id: str) -> None:
    """WAREHOUSED files -> REJECTED; their WAREHOUSED entries -> CANCELLED."""
    files = sort_by_created_at(
        [
            f
            for f in db.ach_files.values()
            if f["originator_id"] == originator_id and f["status"] == "WAREHOUSED"
        ]
    )
    for f in files:
        f["status"] = "REJECTED"
        touch(f)
        for e in entries_of_file(f["id"]):
            if e["status"] == "WAREHOUSED":
                e["status"] = "CANCELLED"
                touch(e)
    recompute_exposure(originator_id)


def cancel_file(file: dict) -> None:
    """WAREHOUSED -> CANCELLED; WAREHOUSED entries -> CANCELLED; exposure recompute."""
    file["status"] = "CANCELLED"
    touch(file)
    for e in entries_of_file(file["id"]):
        if e["status"] == "WAREHOUSED":
            e["status"] = "CANCELLED"
            touch(e)
    recompute_exposure(file["originator_id"])


# ---------------------------------------------------------------------------
# Window assignment at release (PRD §3.4)
# ---------------------------------------------------------------------------


def window_close_dt(window: dict, day: date) -> datetime:
    minutes = hhmm_to_minutes(window["closes_at_utc"])
    return datetime.combine(
        day, time(minutes // 60, minutes % 60), tzinfo=timezone.utc
    )


def assign_window(requested_kind: str, now: datetime) -> dict | None:
    """Fixed fallback: requested if its close is still later than now; else the
    open same-day window with the earliest close; else NEXT_DAY.

    Returns the assigned CutoffWindow row, or None when no row exists for the
    assigned kind (caller maps to ERR_NO_ELIGIBLE_WINDOW).
    """
    today = now.date()
    requested = window_by_kind(requested_kind)
    if requested is None:
        return None
    if window_close_dt(requested, today) > now:
        return requested
    open_same_day = [
        w
        for w in db.cutoff_windows.values()
        if w["window_kind"] in SAME_DAY_KINDS and window_close_dt(w, today) > now
    ]
    if open_same_day:
        return min(open_same_day, key=lambda w: hhmm_to_minutes(w["closes_at_utc"]))
    return window_by_kind("NEXT_DAY")
