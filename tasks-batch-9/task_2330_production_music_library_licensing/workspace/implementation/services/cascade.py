"""Mutation helpers, the logical-clock sweep and the named cascades (PRD §3)."""

from datetime import timedelta as _timedelta
from decimal import Decimal

from flask import g

from db import DB, add_months, date_only, fmt_ts, parse_ts, sort_rows
from services import calc

_ONE_DAY = _timedelta(days=1)
_GRACE = _timedelta(days=calc.REPORT_GRACE_DAYS)
from services.derive import (
    composition_licenses,
    open_claim_count,
    report_sheets,
    report_usage_totals,
    rows,
)


# ---------------------------------------------------------------------------
# version bookkeeping
# ---------------------------------------------------------------------------
def bump(row):
    """Refresh updated_at and advance version by exactly 1."""
    if "version" not in row:
        return row
    row["updated_at"] = DB.now_iso
    row["version"] = row["version"] + 1
    return row


def bump_once(row):
    """Advance a row's version at most once per HTTP request (PRD §2.4)."""
    if row is None or "version" not in row:
        return row
    seen = getattr(g, "_bumped", None)
    if seen is None:
        seen = set()
        g._bumped = seen
    key = id(row)
    if key in seen:
        return row
    seen.add(key)
    return bump(row)


# ---------------------------------------------------------------------------
# ledger
# ---------------------------------------------------------------------------
def append_ledger(composer_id, source_type, source_ref_id, amount_cents, memo,
                  cash=True, bump_composer=True):
    row = DB.new_row(versioned=False)
    row.update(
        {
            "composer_id": composer_id,
            "statement_id": None,
            "source_type": source_type,
            "source_ref_id": source_ref_id,
            "amount_cents": int(amount_cents),
            "accrual_recognized_at": DB.now_iso,
            "cash_recognized_at": DB.now_iso if cash else None,
            "memo": memo,
        }
    )
    DB.ledger[row["id"]] = row
    if bump_composer:
        composer = DB.composers.get(composer_id)
        if composer is not None:
            bump(composer)
    return row


def sheet_entries(sheet_id, source_type):
    return [
        e for e in rows("ledger")
        if e["source_ref_id"] == sheet_id and e["source_type"] == source_type
    ]


# ---------------------------------------------------------------------------
# lookups used by several cascades
# ---------------------------------------------------------------------------
def composition_agreement(composition):
    return DB.agreements.get(composition["agreement_id"])


def writer_share(agreement):
    if agreement is None:
        return Decimal("0")
    return agreement["_writer_share_pct"]


# ---------------------------------------------------------------------------
# cadence periods (blanket reporting compliance)
# ---------------------------------------------------------------------------
def cadence_months(blanket):
    return 1 if blanket["reporting_cadence"] == "MONTHLY" else 3


def cadence_periods(blanket):
    """Enumerate [period_start, period_end] pairs derived from coverage_start."""
    step = cadence_months(blanket)
    start = blanket["_coverage_start_dt"]
    end = blanket["_coverage_end_dt"]
    periods = []
    index = 0
    while True:
        p_start = add_months(start, index * step)
        if p_start >= end:
            break
        p_end = add_months(p_start, step) - _ONE_DAY
        periods.append((p_start, p_end))
        index += 1
        if index > 600:                       # defensive bound, never reached
            break
    return periods


def period_covered(blanket, period_start):
    for report in rows("usage_reports"):
        if report["blanket_agreement_id"] != blanket["id"]:
            continue
        if report["_period_start_dt"] != period_start:
            continue
        if report["status"] in ("SUBMITTED", "ACCEPTED"):
            return True
    return False


def overdue_periods(blanket, at=None):
    moment = at or DB.now
    late = []
    for p_start, p_end in cadence_periods(blanket):
        if moment > p_end + _GRACE and not period_covered(blanket, p_start):
            late.append(p_start)
    return late


def refresh_reporting_status(blanket):
    """Called after a submission: DELINQUENT → COMPLIANT once nothing is overdue."""
    if blanket["reporting_status"] != "DELINQUENT":
        return False
    if overdue_periods(blanket):
        return False
    blanket["reporting_status"] = "COMPLIANT"
    blanket["delinquent_since"] = None
    bump_once(blanket)
    return True


# ---------------------------------------------------------------------------
# logical clock
# ---------------------------------------------------------------------------
def clock_advance(target):
    """Move the clock forward and run the three documented sweeps in order."""
    DB.clock = target
    today = date_only(target)

    expired_license_ids = []
    for lic in sort_rows(list(DB.licenses.values())):
        if lic["status"] not in ("ISSUED", "ACTIVE"):
            continue
        if today > lic["_term_end_dt"]:
            lic["status"] = "EXPIRED"
            bump(lic)
            expired_license_ids.append(lic["id"])
            bump_once(DB.licensees.get(lic["licensee_id"]))
            bump_once(DB.compositions.get(lic["composition_id"]))

    expired_blanket_ids = []
    for blanket in sort_rows(list(DB.blankets.values())):
        if blanket["coverage_status"] != "ACTIVE":
            continue
        if today >= blanket["_coverage_end_dt"]:
            blanket["coverage_status"] = "EXPIRED"
            bump_once(blanket)
            expired_blanket_ids.append(blanket["id"])

    delinquent_ids = []
    for blanket in sort_rows(list(DB.blankets.values())):
        if blanket["coverage_status"] != "ACTIVE":
            continue
        if blanket["reporting_status"] == "DELINQUENT":
            continue
        if overdue_periods(blanket, target):
            blanket["reporting_status"] = "DELINQUENT"
            blanket["delinquent_since"] = DB.now_iso
            bump_once(blanket)
            delinquent_ids.append(blanket["id"])

    return {
        "current_utc": DB.now_iso,
        "expired_license_ids": expired_license_ids,
        "expired_blanket_agreement_ids": expired_blanket_ids,
        "delinquent_blanket_agreement_ids": delinquent_ids,
    }


# ---------------------------------------------------------------------------
# agreement termination cascade (4 steps)
# ---------------------------------------------------------------------------
def terminate_agreement(agreement, reason):
    agreement["pending_writer_share_pct"] = None
    agreement["_pending_writer_share_pct"] = None
    agreement["pending_publisher_share_pct"] = None
    agreement["_pending_publisher_share_pct"] = None
    agreement["pending_sync_fee_share_pct"] = None
    agreement["_pending_sync_fee_share_pct"] = None
    agreement["pending_holdback_days"] = None
    agreement["status"] = "TERMINATED"
    agreement["terminated_at"] = DB.now_iso
    agreement["termination_reason"] = reason
    bump_once(agreement)

    # step 2 — governed compositions are withdrawn, created_at ASC
    withdrawn = []
    for comp in rows("compositions"):
        if comp["agreement_id"] != agreement["id"]:
            continue
        if comp["availability_status"] in ("AVAILABLE", "RESTRICTED"):
            comp["availability_status"] = "WITHDRAWN"
            bump_once(comp)
            withdrawn.append(comp["id"])

    # step 3 — their open sync requests are declined, created_at ASC
    touched_licensees = []
    for req in rows("sync_requests"):
        if req["composition_id"] not in withdrawn:
            continue
        if req["status"] not in ("SUBMITTED", "UNDER_REVIEW", "QUOTED", "REVISION_REQUESTED"):
            continue
        was_reserving = req["status"] == "QUOTED" and req["license_id"] is None
        req["status"] = "DECLINED"
        req["decline_reason"] = "CATALOG_WITHDRAWN"
        bump_once(req)
        if was_reserving and req["licensee_id"] not in touched_licensees:
            touched_licensees.append(req["licensee_id"])

    # step 4 — one version bump per affected licensee
    for licensee_id in touched_licensees:
        bump_once(DB.licensees.get(licensee_id))
    return agreement


# ---------------------------------------------------------------------------
# usage-report acceptance cascade (5 steps)
# ---------------------------------------------------------------------------
def accept_usage_report(report):
    blanket = DB.blankets[report["blanket_agreement_id"]]

    minutes_before = sum(
        r["reported_minutes_total"]
        for r in rows("usage_reports")
        if r["blanket_agreement_id"] == blanket["id"] and r["status"] == "ACCEPTED"
    )
    overage_before = max(0, minutes_before - blanket["usage_cap_minutes"]) \
        * calc.OVERAGE_RATE_CENTS_PER_MINUTE

    # step 1 — accept and freeze the reported totals
    minutes, credits = report_usage_totals(report["id"])
    report["status"] = "ACCEPTED"
    report["accepted_at"] = DB.now_iso
    report["reported_minutes_total"] = minutes
    report["_reported_credits_total"] = credits

    # steps 2 & 3 — blanket ytd and overage move
    minutes_after = minutes_before + minutes
    overage_after = max(0, minutes_after - blanket["usage_cap_minutes"]) \
        * calc.OVERAGE_RATE_CENTS_PER_MINUTE
    overage_increment = overage_after - overage_before

    # step 4 — this period's pool
    pool, admin, distributable = calc.pool_figures(
        blanket["annual_fee_cents"],
        blanket["_pool_share_pct"],
        blanket["reporting_cadence"],
        overage_increment,
    )
    works = {}
    for sheet in report_sheets(report["id"]):
        if sheet["status"] not in ("REGISTERED", "ACCEPTED_BY_SOCIETY"):
            continue
        for composition_id, credit in sheet["_credits_by_composition"].items():
            comp = DB.compositions.get(composition_id)
            if comp is None:
                continue
            agreement = composition_agreement(comp)
            if agreement is None or not agreement["blanket_opt_in"]:
                continue
            works[composition_id] = works.get(composition_id, Decimal("0")) + credit
    work_tuples = [
        (composition_id, credit, DB.compositions[composition_id]["created_at"])
        for composition_id, credit in works.items()
    ]
    allocations = calc.allocate_pool(distributable, work_tuples)
    report["pool_cents"] = pool
    report["pool_admin_fee_cents"] = admin
    report["pool_distributable_cents"] = distributable
    report["pool_allocations"] = allocations
    bump_once(report)
    bump_once(blanket)

    # step 5 — one BLANKET_POOL entry per allocation, in allocation order
    for allocation in allocations:
        comp = DB.compositions[allocation["composition_id"]]
        agreement = composition_agreement(comp)
        amount = calc.cents(
            Decimal(allocation["allocation_cents"]) * writer_share(agreement) / Decimal(100)
        )
        append_ledger(
            comp["composer_id"],
            "BLANKET_POOL",
            report["id"],
            amount,
            "BLANKET_POOL_DISTRIBUTION",
            cash=True,
        )
    return report


# ---------------------------------------------------------------------------
# cue-sheet registration and society reversal
# ---------------------------------------------------------------------------
def _composer_credits(sheet):
    """Credited composer -> summed credits, restricted to ACTIVE agreements."""
    per_composer = {}
    for composition_id, credit in sheet["_credits_by_composition"].items():
        comp = DB.compositions.get(composition_id)
        if comp is None:
            continue
        agreement = composition_agreement(comp)
        if agreement is None or agreement["status"] != "ACTIVE":
            continue
        composer = DB.composers.get(comp["composer_id"])
        if composer is None or composer["pro_affiliation"] == "NONE":
            continue
        bucket = per_composer.setdefault(
            comp["composer_id"], {"credits": Decimal("0"), "agreement": agreement}
        )
        bucket["credits"] += credit
    return per_composer


def register_cue_sheet(sheet, society_reference):
    sheet["status"] = "REGISTERED"
    sheet["society_reference"] = society_reference
    sheet["registered_at"] = DB.now_iso
    sheet["registration_round"] = sheet["registration_round"] + 1
    sheet["rejection_reason"] = None
    bump_once(sheet)

    for composition_id in sheet["_credits_by_composition"]:
        bump_once(DB.compositions.get(composition_id))

    per_composer = _composer_credits(sheet)
    ordered = sorted(
        per_composer.items(),
        key=lambda item: (
            DB.composers[item[0]]["created_at"],
            DB.composers[item[0]]["_seq"],
        ),
    )
    for composer_id, bucket in ordered:
        gross, writer = calc.performance_amounts(
            calc.dp2(bucket["credits"]), bucket["agreement"]["_writer_share_pct"]
        )
        append_ledger(
            composer_id,
            "PERFORMANCE",
            sheet["id"],
            writer,
            "PERFORMANCE_REGISTRATION",
            cash=False,
        )
    return sheet


def accept_cue_sheet(sheet):
    sheet["status"] = "ACCEPTED_BY_SOCIETY"
    bump_once(sheet)
    stamp = DB.now_iso
    for entry in sheet_entries(sheet["id"], "PERFORMANCE"):
        if entry["cash_recognized_at"] is None:
            entry["cash_recognized_at"] = stamp
    return sheet


def reject_cue_sheet(sheet, rejection_reason):
    sheet["status"] = "REJECTED_BY_SOCIETY"
    sheet["rejection_reason"] = rejection_reason
    bump_once(sheet)
    for composition_id in sheet["_credits_by_composition"]:
        bump_once(DB.compositions.get(composition_id))

    outstanding = {}
    order = []
    for entry in sheet_entries(sheet["id"], "PERFORMANCE") + sheet_entries(
        sheet["id"], "PERFORMANCE_REVERSAL"
    ):
        if entry["composer_id"] not in outstanding:
            outstanding[entry["composer_id"]] = 0
            order.append(entry["composer_id"])
        outstanding[entry["composer_id"]] += entry["amount_cents"]
    order.sort(
        key=lambda cid: (DB.composers[cid]["created_at"], DB.composers[cid]["_seq"])
        if cid in DB.composers
        else ("", 0)
    )
    for composer_id in order:
        net = outstanding[composer_id]
        if net == 0:
            continue
        append_ledger(
            composer_id,
            "PERFORMANCE_REVERSAL",
            sheet["id"],
            -net,
            "SOCIETY_REJECTION_REVERSAL",
            cash=False,
        )
    return sheet


# ---------------------------------------------------------------------------
# licence lifecycle helpers
# ---------------------------------------------------------------------------
def revoke_license(license_row, reason):
    license_row["status"] = "REVOKED"
    license_row["revoke_reason"] = reason
    bump_once(license_row)
    bump_once(DB.licensees.get(license_row["licensee_id"]))
    bump_once(DB.compositions.get(license_row["composition_id"]))

    share = license_row["composer_sync_share_cents"]
    if share:
        original = None
        for entry in sheet_entries(license_row["id"], "SYNC_FEE"):
            original = entry
        composition = DB.compositions.get(license_row["composition_id"])
        composer_id = composition["composer_id"] if composition else None
        if original is not None:
            composer_id = original["composer_id"]
        append_ledger(
            composer_id,
            "SYNC_FEE_REVERSAL",
            license_row["id"],
            -share,
            "LICENSE_REVOCATION_REVERSAL",
            cash=bool(original is not None and original["cash_recognized_at"]),
        )
    return license_row


# ---------------------------------------------------------------------------
# statement sweep (shared by the preview and the create endpoint)
# ---------------------------------------------------------------------------
def sweep_set(composer_id, start_dt, end_dt, basis):
    field = "accrual_recognized_at" if basis == "ACCRUAL" else "cash_recognized_at"
    window_end = end_dt + _timedelta(hours=23, minutes=59, seconds=59, milliseconds=999)
    swept = []
    for entry in rows("ledger"):
        if entry["composer_id"] != composer_id:
            continue
        if entry["statement_id"] is not None:
            continue
        if entry["source_type"] in ("ADVANCE", "ADVANCE_RECOUP"):
            continue
        stamp = entry[field]
        if stamp is None:
            continue
        moment = parse_ts(stamp)
        if moment is None or moment < start_dt or moment > window_end:
            continue
        swept.append(entry)
    return swept


def unblock_composition(claim):
    """Return a work to AVAILABLE once no claim on it is NOTICED or DISPUTED."""
    comp = DB.compositions.get(claim["composition_id"])
    if comp is None:
        return
    if comp["availability_status"] != "RESTRICTED":
        return
    if open_claim_count(comp["id"]) == 0:
        comp["availability_status"] = "AVAILABLE"
        bump_once(comp)


def license_count_for_composition(composition_id):
    return len(composition_licenses(composition_id))


def iso(dt):
    return fmt_ts(dt)
