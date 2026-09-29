"""Originator registration, employment posture, the two computed reads, plan
assignment and the reconciliation run."""
from flask import Blueprint, g

import serializers
from db import create, db, touch
from errors import ApiError
from middleware import ALL_ROLES, endpoint
from response import created, ok, paginated
from routes.common import (filters, gate, get_or_404, get_referenced, listing,
                           matches)
from services import audit, authority, calc, ce
from util import fmt_dt
from validators import (Body, STATE_RE, NMLS_RE, body_fk, query_enum, query_int,
                        query_iso, raw_body)

bp = Blueprint("originators", __name__)

EMPLOYMENT_STATUSES = ("EMPLOYED", "SUSPENDED", "TERMINATED")


@bp.route("/originators", methods=["POST"])
@endpoint("LicensingAnalyst")
def register_originator():
    body = Body(raw_body())
    nmls_unique_id = body.string("nmls_unique_id", pattern=NMLS_RE)
    legal_name = body.string("legal_name", min_len=1, max_len=120)
    hire_date = body.datetime("hire_date")
    employment_status = body.enum("employment_status", EMPLOYMENT_STATUSES,
                                 required=False, default="EMPLOYED")
    for row in db.originators.values():
        if row["nmls_unique_id"] == nmls_unique_id:
            raise ApiError("ERR_DUPLICATE_KEY")
    row = create(db.originators, {
        "nmls_unique_id": nmls_unique_id,
        "legal_name": legal_name,
        "hire_date": hire_date,
        "employment_status": employment_status,
        "compensation_plan_id": None,
        "monitoring_status": "STANDARD",
        "exposure_score": 0,
    })
    return created(serializers.originator(row))


@bp.route("/originators", methods=["GET"])
@endpoint(*ALL_ROLES)
def list_originators():
    active = filters("employment_status", "monitoring_status", "compensation_plan_id")
    rows = listing(db.originators, lambda r: matches(r, active))
    return paginated(rows, serializers.originator)


@bp.route("/originators/<row_id>", methods=["GET"])
@endpoint(*ALL_ROLES)
def get_originator(row_id):
    row = get_or_404(db.originators, row_id)
    return ok(serializers.originator(row))


@bp.route("/originators/<row_id>", methods=["PATCH"])
@endpoint("LicensingAnalyst")
def patch_originator(row_id):
    row = get_or_404(db.originators, row_id)
    body = Body(raw_body())
    employment_status = body.enum("employment_status", EMPLOYMENT_STATUSES)
    row["employment_status"] = employment_status
    # authorized_state_codes is derived, so it re-reads employment immediately.
    touch(row)
    return ok(serializers.originator(row))


@bp.route("/originators/<row_id>/authority", methods=["GET"])
@endpoint(*ALL_ROLES)
def get_authority(row_id):
    row = get_or_404(db.originators, row_id)
    as_of = query_iso("as_of_iso8601", db.clock)
    return ok({
        "originator_id": row["id"],
        "as_of": fmt_dt(as_of),
        "authorized_state_codes": authority.authorized_state_codes(row, as_of),
        "employment_status": row["employment_status"],
    })


@bp.route("/originators/<row_id>/ce-compliance", methods=["GET"])
@endpoint(*ALL_ROLES)
def get_ce_compliance(row_id):
    row = get_or_404(db.originators, row_id)
    variant = query_enum("attribution_variant", calc.ATTRIBUTION_VARIANTS,
                         calc.MAKEUP_ATTRIBUTION)
    reporting_year = query_int("reporting_year", None)
    if reporting_year is None:
        reporting_year = ce.default_reporting_year(row["id"])
    total, federal, ethics, nontraditional = calc.ce_aggregate(
        row["id"], reporting_year, variant)
    required = ce.default_required_hours(row["id"])
    return ok({
        "originator_id": row["id"],
        "reporting_year": reporting_year,
        "attribution_variant": variant,
        "total_hours": total,
        "federal_law_hours": federal,
        "ethics_hours": ethics,
        "nontraditional_hours": nontraditional,
        "ce_satisfied": calc.ce_satisfied(total, federal, ethics, nontraditional, required),
    })


@bp.route("/originators/<row_id>/compensation-plan-assignments", methods=["POST"])
@endpoint("ComplianceOfficer")
def assign_plan(row_id):
    originator = get_or_404(db.originators, row_id)
    raw = raw_body()
    plan_ref = body_fk(raw, "compensation_plan_id")
    plan = None
    if plan_ref is not None:
        plan = get_referenced(db.compensation_plans, plan_ref)
    body = Body(raw)
    body.string("compensation_plan_id")
    effective_from = body.datetime("effective_from")
    effective_to = body.datetime("effective_to")
    expected_version = body.integer("expected_originator_version")

    # Priority 10: the stale-version guard runs before any state precondition.
    if expected_version != originator["version"]:
        raise ApiError("ERR_STALE_ORIGINATOR_VERSION")

    if plan["status"] != "ACTIVE":
        raise ApiError("ERR_PLAN_NOT_ACTIVE")

    # Closed intervals on both ends: adjacency deliberately IS a collision.
    for other in db.compensation_plans.values():
        if other["assigned_originator_id"] != originator["id"]:
            continue
        if other["status"] not in ("ACTIVE", "SUPERSEDED"):
            continue
        if other["assignment_effective_to"] is None or other["assignment_effective_from"] is None:
            continue
        if (other["assignment_effective_to"] >= effective_from
                and other["assignment_effective_from"] <= effective_to):
            raise ApiError("ERR_PLAN_PERIOD_OVERLAP")

    if not effective_to > effective_from:
        raise ApiError("ERR_INVALID_DATE_RANGE")

    previous = [p for p in db.compensation_plans.values()
                if p["assigned_originator_id"] == originator["id"]
                and p["status"] == "ACTIVE" and p["id"] != plan["id"]]

    plan["assigned_originator_id"] = originator["id"]
    plan["assignment_effective_from"] = effective_from
    plan["assignment_effective_to"] = effective_to
    touch(plan)

    for old in previous:
        old["status"] = "SUPERSEDED"
        touch(old)
        audit.append("CompensationPlan", old["id"], "PLAN_APPROVED",
                     {"superseded_by_compensation_plan_id": plan["id"],
                      "assigned_originator_id": originator["id"],
                      "reason": "SUPERSEDED_BY_NEW_ASSIGNMENT"})

    originator["compensation_plan_id"] = plan["id"]
    touch(originator)
    # An assignment brings no new record into existence; it returns the updated
    # originator record, so PRD 4's default of HTTP 200 applies.
    return ok(serializers.originator(originator))


@bp.route("/originators/<row_id>/compensation-reconciliations", methods=["POST"])
@endpoint("ComplianceOfficer")
def reconcile(row_id):
    originator = get_or_404(db.originators, row_id)
    eligible = [l for l in db.loan_applications.values()
                if l["originator_id"] == originator["id"]
                and l["status"] in calc.CLOSED_STATUSES
                and l["compensation_status"] == "ACCRUED"]
    eligible.sort(key=lambda l: (l["funded_at"], l["created_at"], l["_seq"]))

    units = calc.final_units(originator["id"])
    record_ids = []
    total_final = 0
    total_before = 0
    for loan in eligible:
        record = None
        for row in db.compensation_records.values():
            if row["loan_application_id"] == loan["id"] and row["status"] == "ACCRUED":
                record = row
                break
        if record is None:
            continue
        plan = db.compensation_plans.get(record["compensation_plan_id"])
        if plan is None:
            continue
        tier, base, impact, accrued = calc.accrual_line(
            plan, loan, loan["funded_amount_cents"], units)
        total_before += record["accrued_cents"] or 0
        record["variant"] = "FINAL"
        record["tier_bps_adder"] = tier
        record["base_comp_cents"] = base
        record["comp_impact_cents"] = impact
        record["accrued_cents"] = accrued
        record["paid_cents"] = accrued
        record["status"] = "RECONCILED"
        record["reconciled_at"] = db.clock
        touch(record)
        loan["compensation_status"] = "RECONCILED"
        touch(loan)
        record_ids.append(record["id"])
        total_final += accrued
        audit.append("CompensationRecord", record["id"], "COMP_RECONCILED",
                     {"loan_application_id": loan["id"],
                      "variant": "FINAL",
                      "accrued_cents": accrued})

    calc.recompute_exposure(originator)
    touch(originator)
    return ok({
        "originator_id": originator["id"],
        "reconciled_count": len(record_ids),
        "total_final_cents": total_final,
        "total_delta_cents": total_final - total_before,
        "compensation_record_ids": record_ids,
    })
