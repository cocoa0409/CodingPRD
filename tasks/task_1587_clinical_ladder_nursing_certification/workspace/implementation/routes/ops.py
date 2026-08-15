"""Logical clock + ops-run sweep endpoints."""

from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint, request

from clock import clock, fiscal_year_of
from db import db
from errors import err_invalid_request
from middleware import require_roles
from response import success_object
from services.budget import calc_budget_forecast, recompute_budgets_for_unit
from services.calculations import (REVIEW_WINDOW_DAYS, TRACK_ORDER,
                                   nurse_level_requirement_track, record_risk_event,
                                   recompute_risk, subtract_months)
from util import parse_datetime, require_fields

bp = Blueprint("ops", __name__)


@bp.route("/clinical-ladder/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require_roles("ProgramAdmin")
    payload = request.get_json(silent=True)
    require_fields(payload, ["to_iso8601"])
    dt = parse_datetime(payload.get("to_iso8601"), "to_iso8601")
    clock.set(dt)
    return success_object({})


@bp.route("/clinical-ladder/_ops/run_cycle", methods=["POST"])
def run_cycle():
    require_roles("ProgramAdmin")
    now = clock.now()

    swept_certifications = 0
    expired_assignments = 0
    lapsed_reviews = 0
    closed_budget_lines = 0
    snapshots_captured = 0

    # 1. Lapse every CURRENT certification whose expiry has been reached
    for cert in list(db.certifications.values()):
        if cert["status"] == "CURRENT" and now >= cert["expires_on"]:
            cert["status"] = "LAPSED"
            cert["updated_at"] = now
            cert["version"] += 1
            swept_certifications += 1
            nurse = db.nurses.get(cert["nurse_id"])
            if nurse is None:
                continue
            record_risk_event(nurse["id"], "certification_lapse")
            recompute_risk(nurse["id"])
            # Cross-entity: when the lapsed credential was the holder's only remaining
            # CURRENT certification at or above the level requirement, open an
            # AnniversaryReview in OPEN outcome flagged for early maintenance check.
            requirement = nurse_level_requirement_track(nurse)
            still_covered = any(
                c["nurse_id"] == nurse["id"] and c["status"] == "CURRENT"
                and TRACK_ORDER[c["track"]] >= TRACK_ORDER[requirement]
                for c in db.certifications.values())
            if not still_covered:
                review = {
                    "id": db.new_id(),
                    "nurse_id": nurse["id"],
                    "review_year": now.year,
                    "maintenance_score": None,
                    "outcome": "OPEN",
                    "resolution_reason": "early maintenance check: certification lapsed",
                    "created_at": now,
                    "updated_at": now,
                    "version": 1,
                }
                db.anniversary_reviews[review["id"]] = review

    # 2. Expire every PENDING review assignment whose scoring window has closed
    from datetime import timedelta
    for asg in list(db.review_assignments.values()):
        if asg["status"] == "PENDING" and now > asg["created_at"] + timedelta(days=REVIEW_WINDOW_DAYS):
            asg["status"] = "EXPIRED"
            asg["updated_at"] = now
            asg["version"] += 1
            expired_assignments += 1

    # 3. Lapse every review still OPEN past December 31 of its review_year
    for review in list(db.anniversary_reviews.values()):
        if review["outcome"] != "OPEN":
            continue
        year_end = datetime(review["review_year"], 12, 31, 23, 59, 59, 999999, tzinfo=timezone.utc)
        if now > year_end:
            review["outcome"] = "LAPSE"
            if review["resolution_reason"] is None:
                review["resolution_reason"] = "review lapsed: open past review year end"
            review["updated_at"] = now
            review["version"] += 1
            lapsed_reviews += 1
            nurse = db.nurses.get(review["nurse_id"])
            if nurse is not None:
                nurse["differential_status"] = "TERMINATED"
                nurse["updated_at"] = now
                nurse["version"] += 1
                recompute_budgets_for_unit(nurse["home_unit"])
                recompute_risk(nurse["id"])

    # 4. Close budget lines whose fiscal year has ended: flip variant to FINAL
    for line in db.budget_lines.values():
        fy_end = datetime(line["fiscal_year"], 7, 1, tzinfo=timezone.utc)
        if line["forecast_variant"] == "PROVISIONAL" and now >= fy_end:
            line["forecast_variant"] = "FINAL"
            line["updated_at"] = now
            line["version"] += 1
            line["forecast_cents"] = calc_budget_forecast(line)
            closed_budget_lines += 1

    # 5. Capture one RetentionSnapshot per unit plus one hospital-wide ("ALL")
    units = sorted({n["home_unit"] for n in db.nurses.values()})
    for unit in units + ["ALL"]:
        if unit == "ALL":
            population = list(db.nurses.values())
        else:
            population = [n for n in db.nurses.values() if n["home_unit"] == unit]
        headcount = len(population)
        headcount_by_level = {"CN_I": 0, "CN_II": 0, "CN_III": 0, "CN_IV": 0}
        for n in population:
            headcount_by_level[n["current_level"]] += 1
        if headcount == 0:
            avg_risk = 0.0
            demotion_rate = 0.0
        else:
            mean = sum(n["retention_risk_score"] for n in population) / headcount
            avg_risk = float(Decimal(repr(mean)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
            window_start = subtract_months(now, 12)
            demotions = sum(
                1 for r in db.anniversary_reviews.values()
                if r["outcome"] == "DEMOTE" and window_start <= r["updated_at"] < now
                and (unit == "ALL" or (db.nurses.get(r["nurse_id"]) or {}).get("home_unit") == unit))
            demotion_rate = float(
                (Decimal(demotions) / Decimal(headcount)).quantize(
                    Decimal("0.0001"), rounding=ROUND_HALF_UP))
        snapshot = {
            "id": db.new_id(),
            "captured_at": now,
            "unit": unit,
            "headcount_by_level": headcount_by_level,
            "avg_retention_risk_score": avg_risk,
            "demotion_rate": demotion_rate,
            "created_at": now,
        }
        db.retention_snapshots[snapshot["id"]] = snapshot
        snapshots_captured += 1

    return success_object({
        "swept_certifications": swept_certifications,
        "expired_assignments": expired_assignments,
        "lapsed_reviews": lapsed_reviews,
        "closed_budget_lines": closed_budget_lines,
        "snapshots_captured": snapshots_captured,
    })
