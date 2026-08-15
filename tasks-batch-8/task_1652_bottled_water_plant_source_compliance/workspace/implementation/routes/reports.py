"""Community water reports: draft, publish (with finalization gate), supersede."""
from flask import Blueprint, request

from db import store, new_resource, touch, by_creation, fmt_ts
from errors import ApiError, err_invalid_state
from middleware import auth, ALL_ROLES
from response import ok_object, ok_list
from services import (
    as_int,
    compute_report_volumes,
    get_body,
    get_or_404,
    raise_shape,
    report_json,
)

bp = Blueprint("reports", __name__)

CO = ["ComplianceOfficer"]


def _apply_volumes(report):
    total_g, total_af, breakdown = compute_report_volumes(
        report["plant_id"], report["period_year"], report["period_month"]
    )
    report["total_withdrawn_gallons"] = total_g
    report["total_acre_feet"] = total_af
    report["per_source_breakdown"] = breakdown


@bp.post("/api/plants/<plant_id>/community-reports")
@auth(CO)
def create_report(plant_id):
    plant = get_or_404(store.plants, plant_id, "plant")
    body = get_body()
    year, ok_y = as_int(body.get("period_year"))
    month, ok_m = as_int(body.get("period_month"))

    # Rung 9 — one non-SUPERSEDED report per plant + period.
    if ok_y and ok_m:
        dup = any(
            r["plant_id"] == plant["id"]
            and r["period_year"] == year
            and r["period_month"] == month
            and r["status"] != "SUPERSEDED"
            for r in store.reports.values()
        )
        if dup:
            raise ApiError(
                "ERR_DUPLICATE_REPORT_PERIOD",
                "a non-SUPERSEDED report already exists for this plant and period",
                409,
            )

    # Rung 11 — input shape.
    errs = []
    if not ok_y:
        errs.append("period_year must be an integer")
    if not ok_m or month < 1 or month > 12:
        errs.append("period_month must be an integer between 1 and 12")
    raise_shape(errs)

    report = new_resource(
        {
            "plant_id": plant["id"],
            "period_year": year,
            "period_month": month,
            "status": "DRAFT",
            "total_withdrawn_gallons": 0,
            "total_acre_feet": 0.0,
            "per_source_breakdown": [],
            "addendum_of_report_id": None,
            "published_at": None,
        }
    )
    _apply_volumes(report)
    store.reports[report["id"]] = report
    return ok_object(report_json(report), 201)


@bp.get("/api/community-reports")
@auth(ALL_ROLES)
def list_reports():
    items = list(store.reports.values())
    plant_id = request.args.get("plant_id")
    addendum = request.args.get("addendum_of_report_id")
    status = request.args.get("status")
    if plant_id is not None:
        items = [r for r in items if r["plant_id"] == plant_id]
    if addendum is not None:
        items = [r for r in items if r.get("addendum_of_report_id") == addendum]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    return ok_list([report_json(r) for r in by_creation(items)])


@bp.get("/api/community-reports/<report_id>")
@auth(ALL_ROLES)
def get_report(report_id):
    report = get_or_404(store.reports, report_id, "community water report")
    return ok_object(report_json(report))


@bp.post("/api/community-reports/<report_id>/publish")
@auth(CO)
def publish_report(report_id):
    report = get_or_404(store.reports, report_id, "community water report")
    if report["status"] != "DRAFT":
        raise err_invalid_state("only a DRAFT report can be published")

    # Rung 8 — no RECORDED (unfinalized) withdrawal may exist in the period.
    permit_ids = {
        p["id"] for p in store.permits.values() if p["plant_id"] == report["plant_id"]
    }
    period = (report["period_year"], report["period_month"])
    unfinalized = any(
        e["permit_id"] in permit_ids
        and e["status"] == "RECORDED"
        and (e["_date"].year, e["_date"].month) == period
        for e in store.withdrawal_events.values()
    )
    if unfinalized:
        raise ApiError(
            "ERR_UNFINALIZED_WITHDRAWALS",
            "RECORDED withdrawal events exist in the report period",
            409,
        )

    _apply_volumes(report)
    report["published_at"] = fmt_ts(store.clock)
    report["status"] = "PUBLISHED"
    touch(report)
    return ok_object(report_json(report))


@bp.post("/api/community-reports/<report_id>/supersede")
@auth(CO)
def supersede_report(report_id):
    report = get_or_404(store.reports, report_id, "community water report")
    if report["status"] != "PUBLISHED":
        raise err_invalid_state("only a PUBLISHED report can be superseded")
    report["status"] = "SUPERSEDED"
    touch(report)

    successor = new_resource(
        {
            "plant_id": report["plant_id"],
            "period_year": report["period_year"],
            "period_month": report["period_month"],
            "status": "DRAFT",
            "total_withdrawn_gallons": 0,
            "total_acre_feet": 0.0,
            "per_source_breakdown": [],
            "addendum_of_report_id": report["id"],
            "published_at": None,
        }
    )
    _apply_volumes(successor)
    store.reports[successor["id"]] = successor
    return ok_object(report_json(successor))
