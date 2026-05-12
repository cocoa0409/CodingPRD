"""Bill calculation: per-line totals, package discount, deposit, insurance.

Implements PRD §2.8 / §3.9 with strict integer-cent + half-up rounding.
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List


def round_half_up(d: Decimal) -> int:
    """Round a Decimal to integer cents using ROUND_HALF_UP."""
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def package_tier_pct(package_code: str | None, gross_cents: int) -> int:
    """Tier-by-gross discount table; tier is keyed on PRE-discount gross."""
    if package_code == "DENTAL_PKG":
        if gross_cents >= 50_000:
            return 15
        if gross_cents >= 20_000:
            return 10
        return 5
    if package_code == "SURGERY_PKG":
        if gross_cents >= 150_000:
            return 20
        return 12
    return 0


def per_line_total_cents(qty: int, unit_price_cents: int) -> int:
    return round_half_up(Decimal(qty) * Decimal(unit_price_cents))


def compute_phases(line_items: List[Dict[str, Any]],
                   package_code: str | None,
                   deposit_applied_cents: int,
                   insurance_term_cents: int) -> Dict[str, int]:
    # Phase 1 — line totals (already integer cents).
    gross_cents = 0
    for li in line_items:
        gross_cents += int(li["line_total_cents"])
    # Phase 2 — sum is gross.
    # Phase 3 — package discount keyed on pre-discount gross.
    tier_pct = package_tier_pct(package_code, gross_cents)
    pkg_discount_cents = round_half_up(
        Decimal(gross_cents) * Decimal(tier_pct) / Decimal(100)
    )
    gross_after_discount = gross_cents - pkg_discount_cents
    # Phase 4 — deposit subtracted (already locked at issue).
    base_after_deposit = gross_after_discount - deposit_applied_cents
    # Phase 5 — insurance applied = min(insurance_term, base_after_deposit) but >= 0
    insurance_used = min(
        max(0, insurance_term_cents),
        max(0, base_after_deposit),
    )
    total = base_after_deposit - insurance_used
    if total < 0:
        total = 0
    return {
        "gross_cents": gross_cents,
        "pkg_discount_cents": pkg_discount_cents,
        "gross_after_discount": gross_after_discount,
        "insurance_used_cents": insurance_used,
        "total_cents": total,
    }


def recompute_provisional(bill: Dict[str, Any]) -> int:
    res = compute_phases(
        bill.get("line_items", []),
        bill.get("package_code"),
        int(bill.get("deposit_applied_cents", 0) or 0),
        int(bill.get("insurance_estimate_cents", 0) or 0),
    )
    bill["provisional_total_cents"] = res["total_cents"]
    return res["total_cents"]


def recompute_final(bill: Dict[str, Any]) -> int:
    res = compute_phases(
        bill.get("line_items", []),
        bill.get("package_code"),
        int(bill.get("deposit_applied_cents", 0) or 0),
        int(bill.get("insurance_actual_cents", 0) or 0),
    )
    bill["final_total_cents"] = res["total_cents"]
    return res["total_cents"]


def gross_after_discount(bill: Dict[str, Any]) -> int:
    res = compute_phases(
        bill.get("line_items", []),
        bill.get("package_code"),
        int(bill.get("deposit_applied_cents", 0) or 0),
        int(bill.get("insurance_estimate_cents", 0) or 0),
    )
    return res["gross_after_discount"]


def gross_pre_discount(bill: Dict[str, Any]) -> int:
    return sum(int(li["line_total_cents"]) for li in bill.get("line_items", []))


# Default unit prices for cascade-driven line items (PRD does not pin
# concrete cents per kind; these match the cascade emitters in routes/).
CONSULT_UNIT_PRICE_CENTS = 5_000
LAB_UNIT_PRICE_CENTS = 3_000
DRUG_UNIT_PRICE_CENTS = 100
HOSPITAL_DAY_UNIT_PRICE_CENTS = 4_000


def aggregate_lines_from_visit_children(bill: Dict[str, Any]) -> None:
    """PRD §3.9: 'The line items contributing to the bill are aggregated
    from the visit's children with statuses pinned exactly: only finalized
    treatment records contribute CONSULT lines, only finalized lab reports
    contribute LAB lines, only dispensed prescriptions contribute DRUG
    lines, and only discharged hospitalizations contribute HOSPITAL_DAY
    lines. Treatment records still in draft, amended treatment records,
    cancelled lab reports, and cancelled prescriptions do not contribute.'

    Rebuilds bill['line_items'] in place. Existing line_items are replaced
    by the freshly aggregated set so the recompute is idempotent.
    """
    import db  # local import to avoid cycle at module load
    visit_id = bill.get("visit_id")
    if not visit_id:
        return
    new_lines: List[Dict[str, Any]] = []
    # CONSULT — only FINALIZED TRs (AMENDED do not contribute per PRD §3.9).
    for tr in db.treatment_records_for_visit(visit_id):
        if tr.get("status") == "FINALIZED":
            qty = 1
            unit = CONSULT_UNIT_PRICE_CENTS
            new_lines.append({
                "kind": "CONSULT",
                "ref_id": tr["id"],
                "qty": qty,
                "unit_price_cents": unit,
                "line_total_cents": per_line_total_cents(qty, unit),
            })
    # LAB — only FINALIZED lab reports.
    for lr in db.lab_reports_for_visit(visit_id):
        if lr.get("status") == "FINALIZED":
            qty = 1
            unit = LAB_UNIT_PRICE_CENTS
            new_lines.append({
                "kind": "LAB",
                "ref_id": lr["id"],
                "qty": qty,
                "unit_price_cents": unit,
                "line_total_cents": per_line_total_cents(qty, unit),
            })
    # DRUG — only DISPENSED prescriptions; one line per item.
    for rx in db.prescriptions_for_visit(visit_id):
        if rx.get("status") == "DISPENSED":
            for it in rx.get("items", []):
                qty = int(it.get("units", 0))
                unit = DRUG_UNIT_PRICE_CENTS
                new_lines.append({
                    "kind": "DRUG",
                    "ref_id": rx["id"],
                    "qty": qty,
                    "unit_price_cents": unit,
                    "line_total_cents": per_line_total_cents(qty, unit),
                })
    # HOSPITAL_DAY — only DISCHARGED hospitalizations; one line per spanned day.
    from datetime import datetime, timezone
    for h in db.hospitalizations_for_visit(visit_id):
        if h.get("status") == "DISCHARGED":
            adm = h.get("admitted_at")
            dis = h.get("discharged_at")
            if adm and dis:
                try:
                    a = datetime.fromisoformat(adm.replace("Z", "+00:00")).astimezone(timezone.utc)
                    d = datetime.fromisoformat(dis.replace("Z", "+00:00")).astimezone(timezone.utc)
                    days = (d.date() - a.date()).days
                    if days < 1:
                        days = 1
                except Exception:
                    days = 1
            else:
                days = 1
            for _ in range(days):
                qty = 1
                unit = HOSPITAL_DAY_UNIT_PRICE_CENTS
                new_lines.append({
                    "kind": "HOSPITAL_DAY",
                    "ref_id": h["id"],
                    "qty": qty,
                    "unit_price_cents": unit,
                    "line_total_cents": per_line_total_cents(qty, unit),
                })
    bill["line_items"] = new_lines
