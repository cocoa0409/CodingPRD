"""ScorecardSnapshot endpoints (firm performance scorecard)."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint, request

import db
import errors
import helpers
import response as resp
from middleware import require_auth, ROLE_LEGAL_OPS, ROLE_FIRM_USER

bp = Blueprint("scorecards", __name__)


def _r2(value: Decimal) -> float:
    return float(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _window_start(clock: datetime) -> datetime:
    """Trailing 12-month window start. Month subtraction handles year rollover."""
    year = clock.year - 1
    month = clock.month
    day = min(clock.day, _days_in_month(year, month))
    return datetime(year, month, day, clock.hour, clock.minute, clock.second,
                    clock.microsecond, tzinfo=timezone.utc)


def _days_in_month(year, month):
    if month == 12:
        nxt = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        nxt = datetime(year, month + 1, 1, tzinfo=timezone.utc)
    cur = datetime(year, month, 1, tzinfo=timezone.utc)
    return (nxt - cur).days


def _next_month(py, pm):
    if pm == 12:
        return py + 1, 1
    return py, pm + 1


@bp.route("/legal-departments/<deptId>/panel-firms/<firmId>/scorecards/recompute", methods=["POST"])
def recompute_scorecard(deptId, firmId):
    require_auth([ROLE_LEGAL_OPS])
    dept, firm = helpers.resolve_firm(deptId, firmId)
    body = helpers.get_body()
    helpers.require_fields(body, ["period_year", "period_month"])
    py = int(body["period_year"])
    pm = int(body["period_month"])

    clock = db.get_clock()
    window_start = _window_start(clock)

    def in_window(rec):
        ts = db.parse_iso(rec.get("created_at"))
        return ts is not None and window_start <= ts <= clock

    # --- on_time_ack_pct: acks ACKNOWLEDGED on or before due date -----------
    acks = [a for a in db.guideline_acknowledgments.values()
            if a.get("panel_firm_id") == firmId and in_window(a)]
    ack_total = len(acks)
    ack_on_time = 0
    for a in acks:
        if a.get("status") != "ACKNOWLEDGED":
            continue
        gv = db.guideline_versions.get(a.get("guideline_version_id"))
        published_at = db.parse_iso(gv.get("published_at")) if gv else None
        acked_at = db.parse_iso(a.get("acknowledged_at"))
        if published_at is None or acked_at is None:
            continue
        due = published_at + timedelta(days=int(dept.get("acknowledgment_window_days", 0)))
        if acked_at <= due:
            ack_on_time += 1
    on_time_ack_pct = Decimal("0") if ack_total == 0 else Decimal(ack_on_time) / Decimal(ack_total) * Decimal("100")

    # --- rejection_rate_pct: reviewed lines ending REJECTED or UPHELD --------
    firm_invoice_ids = {inv["id"] for inv in db.invoices.values() if inv.get("panel_firm_id") == firmId}
    lines = [l for l in db.invoice_line_items.values()
             if l.get("invoice_id") in firm_invoice_ids and in_window(l)]
    reviewed = [l for l in lines if l.get("review_status") != "PENDING"]
    rej = sum(1 for l in reviewed if l.get("review_status") in ("REJECTED", "UPHELD"))
    rejection_rate_pct = Decimal("0") if len(reviewed) == 0 else Decimal(rej) / Decimal(len(reviewed)) * Decimal("100")

    # --- appeal_uphold_rate_pct: resolved appeals that were DENIED -----------
    firm_line_ids = {l["id"] for l in db.invoice_line_items.values() if l.get("invoice_id") in firm_invoice_ids}
    appeals = [a for a in db.appeals.values()
               if a.get("invoice_line_item_id") in firm_line_ids and in_window(a)]
    resolved = [a for a in appeals if a.get("status") in ("GRANTED", "DENIED")]
    denied = sum(1 for a in resolved if a.get("status") == "DENIED")
    appeal_uphold_rate_pct = Decimal("0") if len(resolved) == 0 else Decimal(denied) / Decimal(len(resolved)) * Decimal("100")

    # --- accrual_timeliness_pct: submitted on/before the 5th of next month ---
    firm_matter_ids = {m["id"] for m in db.matters.values() if m.get("panel_firm_id") == firmId}
    accruals = [a for a in db.accruals.values()
                if a.get("matter_id") in firm_matter_ids and in_window(a)]
    acc_total = len(accruals)
    acc_on_time = 0
    for a in accruals:
        created = db.parse_iso(a.get("created_at"))
        if created is None:
            continue
        ny, nm = _next_month(int(a.get("period_year", 0)), int(a.get("period_month", 0)))
        try:
            due = datetime(ny, nm, 5, 23, 59, 59, 999000, tzinfo=timezone.utc)
        except ValueError:
            continue
        if created <= due:
            acc_on_time += 1
    accrual_timeliness_pct = Decimal("0") if acc_total == 0 else Decimal(acc_on_time) / Decimal(acc_total) * Decimal("100")

    # Per-metric rounding (2dp, half-up) BEFORE weighting.
    m_ack = on_time_ack_pct.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    m_rej = rejection_rate_pct.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    m_app = appeal_uphold_rate_pct.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    m_acc = accrual_timeliness_pct.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    overall = (
        Decimal("0.30") * m_ack
        + Decimal("0.30") * (Decimal("100") - m_rej)
        + Decimal("0.20") * (Decimal("100") - m_app)
        + Decimal("0.20") * m_acc
    ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    snap = db.base_resource({
        "panel_firm_id": firmId,
        "period_year": py,
        "period_month": pm,
        "on_time_ack_pct": float(m_ack),
        "rejection_rate_pct": float(m_rej),
        "appeal_uphold_rate_pct": float(m_app),
        "accrual_timeliness_pct": float(m_acc),
        "overall_pct": float(overall),
    })
    db.scorecard_snapshots[snap["id"]] = snap

    # Refresh the firm's cached overall.
    firm["scorecard_overall_pct"] = float(overall)
    db.touch(firm)

    return resp.success_object(resp.public(snap), 201)


@bp.route("/legal-departments/<deptId>/panel-firms/<firmId>/scorecards/<snapshotId>", methods=["GET"])
def get_scorecard(deptId, firmId, snapshotId):
    require_auth([ROLE_LEGAL_OPS, ROLE_FIRM_USER])
    _, _, snap = helpers.resolve_scorecard(deptId, firmId, snapshotId)
    return resp.success_object(resp.public(snap))


@bp.route("/legal-departments/<deptId>/panel-firms/<firmId>/scorecards", methods=["GET"])
def list_scorecards(deptId, firmId):
    require_auth([ROLE_LEGAL_OPS, ROLE_FIRM_USER])
    helpers.resolve_firm(deptId, firmId)
    limit, offset = resp.parse_pagination(request.args)
    records = [s for s in db.scorecard_snapshots.values() if s.get("panel_firm_id") == firmId]
    records = helpers.apply_filters(records, request.args, ["period_year", "period_month"])
    items, total = resp.paginate(records, limit, offset)
    return resp.success_list(items, limit, offset, total)
