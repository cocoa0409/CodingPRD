"""ReimbursementForm settlement and item helpers."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from db import STORE
from errors import APIError, ERR_NO_ACTIVE_STANDARD
from services.standards import find_standard_pinned
from utils import DECLARED_HOLIDAYS, parse_ts, round_money


def _coverage_window_for_item(item, form, app):
    """Determine the coverage window of an item for holiday-overlap detection.

    For LODGING/TRANSPORTATION: the matched segment's [start_at, end_at].
    For PER_DIEM: the trip's planned [planned_start, planned_end].
    For OTHER: the trip's planned range (best-effort).
    """
    if item["category"] in {"LODGING", "TRANSPORTATION"} and item.get("matched_segment_id"):
        seg = STORE.itinerary_segments.get(item["matched_segment_id"])
        if seg:
            return parse_ts(seg["start_at"]), parse_ts(seg["end_at"])
    return parse_ts(app["planned_start"]), parse_ts(app["planned_end"])


def _window_has_holiday(s_at, e_at) -> bool:
    d = s_at.date()
    end_d = e_at.date()
    while d <= end_d:
        if d.isoformat() in DECLARED_HOLIDAYS:
            return True
        d = d + timedelta(days=1)
    return False


def _cap_field_for_category(category: str) -> str | None:
    if category == "LODGING":
        return "lodging_daily_cap"
    if category == "PER_DIEM":
        return "per_diem_amount"
    if category == "TRANSPORTATION":
        return "transportation_daily_cap"
    return None  # OTHER


def recompute_totals(form: dict) -> None:
    """Final settlement: walk items in chronological order using the pinned standard.

    Items lacking invoice_date are sorted with None as the smallest. Tie break by
    item.created_at ASC.
    """
    app = STORE.travel_applications.get(form["application_id"])
    if not app:
        # Cannot settle without parent application
        form["total_claimed"] = Decimal("0.00")
        form["total_reimbursable"] = Decimal("0.00")
        form["total_self_paid"] = Decimal("0.00")
        form["requires_special_approval"] = False
        return
    pinned_version = app.get("standard_version_pinned")
    applicant = STORE.employees.get(app["applicant_id"])
    if not applicant or pinned_version is None:
        form["total_claimed"] = Decimal("0.00")
        form["total_reimbursable"] = Decimal("0.00")
        form["total_self_paid"] = Decimal("0.00")
        form["requires_special_approval"] = False
        return
    # OVERSEAS scope forces OVERSEAS tier
    tier = "OVERSEAS" if app["travel_scope"] == "OVERSEAS" else app["destination_tier"]
    level = applicant["employee_level"]
    standard = find_standard_pinned(version=pinned_version,
                                     city_tier=tier, employee_level=level)
    if standard is None:
        raise APIError(ERR_NO_ACTIVE_STANDARD,
                        f"Pinned ExpenseStandard ({pinned_version}, {tier}, {level}) missing",
                        422)
    holiday_mult = standard.get("holiday_multiplier") or Decimal("1.00")

    items = [i for i in STORE.reimbursement_items.values() if i["form_id"] == form["id"]]

    def _sort_key(item):
        inv = STORE.invoices.get(item["invoice_id"])
        inv_date_str = inv.get("invoice_date") if inv else None
        # Sort None last
        parsed = parse_ts(inv_date_str) if inv_date_str else None
        return (parsed is None, parsed, item["created_at"])

    items.sort(key=_sort_key)

    total_claimed = Decimal("0.00")
    total_reimbursable = Decimal("0.00")
    total_self_paid = Decimal("0.00")
    for item in items:
        claimed = item["claimed_amount"]
        cap_field = _cap_field_for_category(item["category"])
        if cap_field is None:
            # OTHER: no standard cap → fully reimbursable up to claimed
            standard_cap_applied = round_money(claimed)
        else:
            per_unit = standard[cap_field]
            s_at, e_at = _coverage_window_for_item(item, form, app)
            if _window_has_holiday(s_at, e_at):
                per_unit_eff = per_unit * holiday_mult
            else:
                per_unit_eff = per_unit
            raw = per_unit_eff * Decimal(item["covered_days"])
            standard_cap_applied = round_money(raw)
        item["standard_cap_applied"] = standard_cap_applied
        reimbursable = min(round_money(claimed), standard_cap_applied)
        reimbursable = round_money(reimbursable)
        self_paid = round_money(claimed) - standard_cap_applied
        if self_paid < 0:
            self_paid = Decimal("0.00")
        self_paid = round_money(self_paid)
        item["reimbursable_amount"] = reimbursable
        item["self_paid_amount"] = self_paid
        from utils import CLOCK as _C
        # don't bump item version here — totals recompute does not change item semantics
        total_claimed += round_money(claimed)
        total_reimbursable += reimbursable
        total_self_paid += self_paid

    form["total_claimed"] = round_money(total_claimed)
    form["total_reimbursable"] = round_money(total_reimbursable)
    form["total_self_paid"] = round_money(total_self_paid)
    form["requires_special_approval"] = (
        form["total_self_paid"] > 0 and not form.get("special_approval_granted", False)
    )


def recompute_totals_simple_sum(form: dict) -> None:
    """For DRAFT-time adds/removes: just sum claimed amounts and zero the others.

    The "final" settlement happens on submit; in DRAFT we only need to maintain
    a running total_claimed view (per item add/remove). The other totals are
    recomputed on submit. This keeps DRAFT behavior simple and consistent.
    """
    items = [i for i in STORE.reimbursement_items.values() if i["form_id"] == form["id"]]
    total_claimed = Decimal("0.00")
    for it in items:
        total_claimed += round_money(it["claimed_amount"])
    form["total_claimed"] = round_money(total_claimed)
    # Reset settlement results to zero in DRAFT
    form["total_reimbursable"] = Decimal("0.00")
    form["total_self_paid"] = Decimal("0.00")
    form["requires_special_approval"] = False
