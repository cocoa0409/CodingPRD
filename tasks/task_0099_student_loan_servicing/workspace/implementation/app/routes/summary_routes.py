"""Risk score and collections summary."""
from __future__ import annotations

from datetime import timedelta

from flask import Flask, request

from ..auth import require_auth
from ..clock import days_between, now_dt, parse_iso
from ..errors import ApiError
from ..services import calculations as calc
from ..store import get_store
from ._helpers import get_borrower_or_404, ok


def register(app: Flask) -> None:
    @app.route("/borrowers/<borrower_id>/risk-score", methods=["GET"])
    @require_auth("ServicerAdmin", "ServicerCertifier", "CollectionsOfficer")
    def risk_score(borrower_id):
        b = get_borrower_or_404(borrower_id)
        loans = [l for l in get_store().loans.values() if l.get("borrower_id") == borrower_id]
        # cumulative FORBEARANCE_GENERAL days
        cum = 0
        for r in get_store().hardship_requests.values():
            if (
                r.get("borrower_id") == borrower_id
                and r.get("kind") == "FORBEARANCE_GENERAL"
                and r.get("status") == "APPROVED"
            ):
                try:
                    rf = parse_iso(r["requested_from"])
                    rt = parse_iso(r["requested_to"])
                except Exception:
                    continue
                cum += max(0, days_between(rt, rf))
        # days since AGI cert
        agi_at = b.get("agi_certified_at")
        if not agi_at:
            days_since = 9999
        else:
            try:
                days_since = max(0, days_between(now_dt(), parse_iso(agi_at)))
            except Exception:
                days_since = 9999
        score = calc.compute_risk_score(b, loans, cum, days_since)
        return ok({
            "borrower_id": borrower_id,
            "score": score,
            "delinquency_subscore": min(100, max((int(l.get("days_past_due", 0)) for l in loans), default=0)),
            "forbearance_burden_subscore": min(100, int((cum / 1095) * 100)) if cum else 0,
            "recertification_overdue_subscore": min(100, int((max(0, days_since - 365) / 365) * 100)),
            "cumulative_forbearance_days": cum,
            "days_since_agi_cert": days_since,
        })

    @app.route("/borrowers/<borrower_id>/collections-summary", methods=["GET"])
    @require_auth("CollectionsOfficer", "ServicerAdmin")
    def collections_summary(borrower_id):
        get_borrower_or_404(borrower_id)
        start = request.args.get("start")
        end = request.args.get("end")
        try:
            start_dt = parse_iso(start) if start else None
            end_dt = parse_iso(end) if end else None
        except Exception:
            raise ApiError("ERR_BAD_DATE_WINDOW", "Invalid start/end")
        if start_dt and end_dt and end_dt < start_dt:
            raise ApiError("ERR_BAD_DATE_WINDOW", "end must be >= start.")
        actions = [
            a for a in get_store().collections_actions.values()
            if a.get("borrower_id") == borrower_id
        ]
        # sort by occurred_at ASC, then by insertion order (created_at)
        actions.sort(key=lambda a: (a.get("occurred_at", ""), a.get("created_at", "")))
        total_garnished = 0
        total_offset = 0
        for a in actions:
            try:
                oa = parse_iso(a["occurred_at"])
            except Exception:
                continue
            if start_dt and oa < start_dt:
                continue
            if end_dt and oa > end_dt:
                continue
            if a["kind"] == "WAGE_GARNISHMENT_ORDER":
                total_garnished += int(a.get("amount_cents", 0))
            elif a["kind"] == "TREASURY_OFFSET_APPLIED":
                total_offset += int(a.get("amount_cents", 0))
        # Rehab payments in last ~10 months from now (304 days)
        window_start = now_dt() - timedelta(days=304)
        rehab_count = 0
        for a in actions:
            if a["kind"] != "REHAB_PAYMENT_RECORDED":
                continue
            try:
                oa = parse_iso(a["occurred_at"])
            except Exception:
                continue
            if oa >= window_start:
                rehab_count += 1
        return ok({
            "borrower_id": borrower_id,
            "start": start,
            "end": end,
            "total_garnished_cents": total_garnished,
            "total_offset_cents": total_offset,
            "rehab_payments_last_10mo": rehab_count,
        })
