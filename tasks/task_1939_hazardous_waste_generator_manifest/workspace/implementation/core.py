"""Core domain services: cascade logic, category, OCC, clock sweep, fees."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from db import clock, store, iso_utc, _parse_iso
from errors import (
    ApiError,
    ERR_ACCUMULATION_LIMIT_EXCEEDED,
    ERR_AUDIT_COVERAGE_OVERLAP,
    ERR_AUDIT_WINDOW_REGRESSIVE,
    ERR_CONTAINER_NOT_LABELED,
    ERR_CONTAINER_NOT_STAGED,
    ERR_CROSS_SITE_REFERENCE,
    ERR_DUPLICATE_EPA_ID,
    ERR_DUPLICATE_TRACKING_NUMBER,
    ERR_INSPECTION_OVERDUE,
    ERR_INVALID_STATE,
    ERR_LABEL_MISSING_HAZARD_TEXT,
    ERR_LABEL_START_DATE_MISMATCH,
    ERR_LDR_NOTICE_MISSING,
    ERR_LINE_CONTAINER_MISMATCH,
    ERR_MANIFEST_NOT_DRAFT,
    ERR_OPEN_EXCEPTION_BLOCKS_MANIFEST,
    ERR_PARTNER_AUDIT_STALE,
    ERR_PARTNER_NOT_APPROVED,
    ERR_PARTNER_TYPE_MISMATCH,
    ERR_REPORT_PERIOD_OVERLAP,
    ERR_REPORT_YEAR_NOT_ODD,
    ERR_SOD_MANIFEST_SELF_SIGN,
    ERR_SOD_PARTNER_SELF_APPROVE,
    ERR_SOD_SELF_INSPECTION,
    ERR_STALE_VERSION,
    ERR_STREAM_HAS_OPEN_CONTAINERS,
    ERR_STREAM_NOT_ACTIVE,
    ERR_STREAM_NOT_HAZARDOUS,
    already_terminal,
    invalid_request,
    invalid_state,
    not_found,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def new_id() -> str:
    return str(uuid.uuid4())


def now_iso() -> str:
    return iso_utc(clock.now())


def bump(entity: dict) -> None:
    """Common mutation: refresh updated_at, increment version."""
    entity["updated_at"] = now_iso()
    entity["version"] = entity.get("version", 0) + 1


def base_entity() -> dict:
    n = now_iso()
    return {"id": new_id(), "created_at": n, "updated_at": n, "version": 0}


# ---------------------------------------------------------------------------
# Category / month-total cascade
# ---------------------------------------------------------------------------


def compute_category(kg: float) -> str:
    if kg >= 1000.0:
        return "LQG"
    if kg > 100.0:
        return "SQG"
    return "VSQG"


def _month_key(dt: datetime) -> str:
    return dt.strftime("%Y-%m")


def recompute_category_and_reports(site: dict) -> None:
    """Hop 2: re-evaluate generator_category; on flip hop 3 recomputes DRAFT report fees."""
    new_cat = compute_category(site["current_month_generated_kg"])
    if new_cat != site["generator_category"]:
        site["generator_category"] = new_cat
        bump(site)
        # Hop 3: recompute provisional fee on every DRAFT report of this site
        for rep in store.reports.values():
            if rep["site_id"] == site["id"] and rep["status"] == "DRAFT":
                recompute_report_provisional(rep)


def refresh_container_flags(container: dict) -> None:
    """Recompute is_accumulation_overdue and is_inspection_overdue against current clock."""
    now = clock.now()
    status = container["status"]
    if status in ("IN_CENTRAL_ACCUMULATION", "STAGED_FOR_SHIPMENT"):
        deadline_at = container.get("accumulation_deadline_at")
        if deadline_at:
            container["is_accumulation_overdue"] = now > _parse_iso(deadline_at)
        else:
            container["is_accumulation_overdue"] = False

        baseline_iso = container.get("last_inspected_at") or container.get("accumulation_start_date")
        if baseline_iso:
            baseline = _parse_iso(baseline_iso)
            container["is_inspection_overdue"] = (now - baseline) > timedelta(days=7)
        else:
            container["is_inspection_overdue"] = False
    else:
        container["is_accumulation_overdue"] = False
        container["is_inspection_overdue"] = False


def refresh_partner_audit_flag(partner: dict) -> None:
    end = partner.get("audit_coverage_end")
    if end is None:
        partner["is_audit_current"] = False
    else:
        partner["is_audit_current"] = clock.now() < _parse_iso(end)


# ---------------------------------------------------------------------------
# Biennial report fee
# ---------------------------------------------------------------------------

_BASE_FEE_CENTS = {"LQG": 250000, "SQG": 100000, "VSQG": 25000}
_LATE_PER_DAY = 5000
_LATE_CAP = 150000

_PROVISIONAL_STATUSES = {
    "IN_TRANSIT",
    "DELIVERED",
    "DISCREPANCY_RAISED",
    "RETURNED",
    "EXCEPTION_REQUIRED",
    "EXCEPTION_REPORT_FILED",
}


def _manifest_set(site_id: str, period_start_iso: str, period_end_iso: str, statuses: set) -> list:
    start = _parse_iso(period_start_iso)
    end = _parse_iso(period_end_iso)
    out = []
    for m in store.manifests.values():
        if m["site_id"] != site_id:
            continue
        shipped = m.get("shipped_at")
        if not shipped:
            continue
        sdt = _parse_iso(shipped)
        if not (start <= sdt < end):
            continue
        if m["status"] not in statuses:
            continue
        out.append(m)
    return out


def compute_provisional_fee_cents(site: dict, report: dict) -> tuple[str, float, int]:
    """Returns (category_snapshot, provisional_shipped_kg, provisional_fee_cents)."""
    category = site["generator_category"]
    base = _BASE_FEE_CENTS[category]
    included = _manifest_set(site["id"], report["period_start"], report["period_end"], _PROVISIONAL_STATUSES)
    total_kg = sum(m["total_quantity_kg"] for m in included)
    tonnage = sum(m["tonnage_fee_cents"] for m in included)
    return category, total_kg, base + tonnage


def recompute_report_provisional(report: dict) -> None:
    site = store.sites.get(report["site_id"])
    if site is None:
        return
    cat, kg, fee = compute_provisional_fee_cents(site, report)
    changed = False
    if report.get("category_snapshot") != cat:
        report["category_snapshot"] = cat
        changed = True
    if report.get("provisional_shipped_kg") != kg:
        report["provisional_shipped_kg"] = kg
        changed = True
    if report.get("provisional_fee_cents") != fee:
        report["provisional_fee_cents"] = fee
        changed = True
    if changed:
        bump(report)


def compute_final_fee(report: dict) -> tuple[str, float, int, bool, int]:
    """Returns (category_snapshot, final_shipped_kg, final_fee_cents, is_late, days_late)."""
    site = store.sites[report["site_id"]]
    category = site["generator_category"]
    base = _BASE_FEE_CENTS[category]
    included = _manifest_set(site["id"], report["period_start"], report["period_end"], {"RETURNED"})
    total_kg = sum(m["total_quantity_kg"] for m in included)
    tonnage = sum(m["tonnage_fee_cents"] for m in included)
    submitted_at = _parse_iso(report["submitted_at"])
    due_at = _parse_iso(report["due_at"])
    is_late = submitted_at > due_at
    days_late = 0
    late = 0
    if is_late:
        delta = submitted_at - due_at
        days_late = delta.days
        late = min(_LATE_CAP, _LATE_PER_DAY * days_late)
    return category, total_kg, base + tonnage + late, is_late, days_late


# ---------------------------------------------------------------------------
# Clock sweep
# ---------------------------------------------------------------------------


def run_clock_sweep() -> None:
    now = clock.now()
    new_month_key = _month_key(now)

    # 1. Month rollover per site
    for site in store.sites.values():
        if site["current_month_key"] != new_month_key:
            site["current_month_key"] = new_month_key
            site["current_month_generated_kg"] = 0
            bump(site)
            recompute_category_and_reports(site)

    # 2. Manifest exception sweep
    for manifest in list(store.manifests.values()):
        if manifest["status"] in ("IN_TRANSIT", "DELIVERED", "DISCREPANCY_RAISED"):
            due = manifest.get("return_due_at")
            if due and now > _parse_iso(due):
                manifest["status"] = "EXCEPTION_REQUIRED"
                bump(manifest)
                site = store.sites.get(manifest["site_id"])
                if site:
                    site["open_exception_count"] = site.get("open_exception_count", 0) + 1
                    bump(site)

    # 3. Container overdue flags
    for container in store.containers.values():
        old_acc = container.get("is_accumulation_overdue")
        old_insp = container.get("is_inspection_overdue")
        refresh_container_flags(container)
        if (old_acc != container.get("is_accumulation_overdue")) or (
            old_insp != container.get("is_inspection_overdue")
        ):
            bump(container)

    # 4. Partner audit currency flags
    for partner in store.partners.values():
        old = partner.get("is_audit_current")
        refresh_partner_audit_flag(partner)
        if old != partner.get("is_audit_current"):
            bump(partner)


# ---------------------------------------------------------------------------
# Tonnage fee calculation
# ---------------------------------------------------------------------------

_RATE_CENTS_PER_KG = Decimal("10.5")


def compute_tonnage_fee_cents(line_items: list[dict]) -> int:
    """Round each line first (half-up), then sum."""
    total = 0
    for line in line_items:
        qty = Decimal(str(line["quantity_kg"]))
        cents = (qty * _RATE_CENTS_PER_KG).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        total += int(cents)
    return total
