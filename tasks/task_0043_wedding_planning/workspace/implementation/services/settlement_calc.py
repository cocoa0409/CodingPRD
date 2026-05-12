"""Settlement calculations: provisional preview vs final committed."""
import db


def approved_change_orders_for(contract_id: str) -> list:
    """Return all approved change orders for a contract."""
    return [co for co in db.change_orders.values()
            if co["contract_id"] == contract_id and co["status"] == "APPROVED"]


def approval_audit_created_at(co_id: str) -> str:
    """Look up the AuditEntry(CHANGE_ORDER_APPROVED) for this change order."""
    for ae in db.audit_entries.values():
        if (ae["event_kind"] == "CHANGE_ORDER_APPROVED"
                and ae["subject_type"] == "CHANGE_ORDER"
                and ae["subject_id"] == co_id):
            return ae["created_at"]
    return ""


def compute_provisional_preview(contract: dict, settlement: dict) -> int:
    """Provisional estimate variant — applies deltas DESCENDING by approval time,
    NO per-step clamp. Then deducts breach + refund. (Result is informational; may
    be negative — but the field is integer cents, we still return as-is per spec
    since spec only clamps in the final variant. Our spec says result MAY DIFFER.)

    Per PRD §3.4, the preview applies deltas in descending order of their approval
    time (so the latest revisions dominate first) WITHOUT the per-step clamp at
    zero, then deducts breach_deduction_cents and refund_cents.

    The PRD does not explicitly clamp the preview at zero, so we don't either —
    the preview is allowed to differ from the final. (Spec text: "Result may
    differ from final_amount_cents when intermediate sums would go negative.")
    """
    base = int(contract["pinned_amount_cents"])
    cos = approved_change_orders_for(contract["id"])
    cos.sort(key=lambda co: approval_audit_created_at(co["id"]), reverse=True)
    for co in cos:
        base = base + int(co["delta_amount_cents"])
    base -= int(settlement.get("breach_deduction_cents", 0))
    base -= int(settlement.get("refund_cents", 0))
    return base


def compute_final_committed(contract: dict, settlement: dict) -> tuple:
    """Final committed variant — applies deltas ASCENDING by approval time,
    WITH per-step max(0, ...) clamp. Then deducts breach + refund and clamps
    final at zero.

    Returns (provisional_total_cents, final_amount_cents).
    """
    base = int(contract["pinned_amount_cents"])
    cos = approved_change_orders_for(contract["id"])
    cos.sort(key=lambda co: approval_audit_created_at(co["id"]))
    for co in cos:
        base = max(0, base + int(co["delta_amount_cents"]))
    provisional_total = base
    final_amount = max(
        0,
        provisional_total
        - int(settlement.get("breach_deduction_cents", 0))
        - int(settlement.get("refund_cents", 0)),
    )
    return provisional_total, final_amount


def settlement_view(contract: dict, settlement: dict) -> dict:
    """Serialize a settlement, computing the provisional preview field for
    DRAFT/VENDOR_CONFIRMED state, and using the persisted final value for
    FINALIZED."""
    out = dict(settlement)
    if settlement["status"] == "FINALIZED":
        # final_amount_cents and provisional_total_cents are persisted
        return out
    # DRAFT or VENDOR_CONFIRMED — show provisional preview in final_amount_cents
    out["final_amount_cents"] = compute_provisional_preview(contract, settlement)
    # provisional_total_cents on a DRAFT settlement is the sum of pinned + approved deltas
    out["provisional_total_cents"] = int(contract["pinned_amount_cents"]) + sum(
        int(co["delta_amount_cents"]) for co in approved_change_orders_for(contract["id"])
    )
    return out


def vendor_recompute_avg_rating(vendor_id: str) -> None:
    """Recompute Vendor.avg_performance_rating and rating_count.
    Includes ratings whose linked Settlement is currently FINALIZED."""
    vendor = db.vendors.get(vendor_id)
    if not vendor:
        return
    scores = []
    for r in db.performance_ratings.values():
        if r["vendor_id"] != vendor_id:
            continue
        s = db.settlements.get(r["settlement_id"])
        if s is None:
            continue
        if s["status"] != "FINALIZED":
            continue
        scores.append(int(r["score"]))
    if not scores:
        vendor["avg_performance_rating"] = None
        vendor["rating_count"] = 0
    else:
        from decimal import Decimal, ROUND_HALF_UP
        mean = Decimal(sum(scores)) / Decimal(len(scores))
        rounded = mean.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        vendor["avg_performance_rating"] = float(rounded)
        vendor["rating_count"] = len(scores)
    db.bump(vendor)
