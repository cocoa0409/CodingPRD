"""Activity records and their review workflow (PRD 3.3)."""
from datetime import datetime, timezone
from decimal import Decimal

from flask import Blueprint, g, request

import calc
import domain
from envelope import ok, ok_list
from errors import err, invalid_state, not_found, sod
from http_util import (
    ANALYST,
    MANAGER,
    READ_ROLES,
    STEWARD,
    get_body,
    parse_pagination,
    require_roles,
    require_target_role,
    v_datetime,
    v_enum,
    v_num,
    v_str,
)
from store import db, new_entity, touch

bp = Blueprint("records", __name__, url_prefix="/sustainability")

RECORD_STATUSES = {"SUBMITTED", "UNDER_REVIEW", "APPROVED", "REJECTED", "VOIDED"}

# The single permitted actor per transition target (PRD §1.2 actor column).
RECORD_TARGET_ROLE = {
    "UNDER_REVIEW": STEWARD,
    "SUBMITTED": STEWARD,      # resubmit
    "APPROVED": ANALYST,
    "REJECTED": ANALYST,
    "VOIDED": MANAGER,
}

LEGAL_FROM = {
    "UNDER_REVIEW": {"SUBMITTED"},
    "APPROVED": {"UNDER_REVIEW"},
    "REJECTED": {"UNDER_REVIEW"},
    "SUBMITTED": {"REJECTED"},
    "VOIDED": {"APPROVED"},
}

TYPE_TO_CATEGORY = {
    "ELECTRICITY": "SCOPE2_GRID",
    "STATIONARY_FUEL": "SCOPE1_STATIONARY",
    "BUSINESS_TRAVEL": "SCOPE3_TRAVEL",
}

# Statuses whose half-open periods participate in the overlap rule.
OVERLAP_STATUSES = ("SUBMITTED", "UNDER_REVIEW", "APPROVED")

EVIDENCE_MANDATE_QTY = Decimal("1000")


def load_record(record_id):
    rec = db.records.get(record_id)
    if rec is None:
        raise not_found(f"ActivityRecord {record_id} not found")
    return rec


@bp.route("/activity-records", methods=["POST"])
@require_roles(STEWARD)
def create_record():
    body = get_body()
    # Priority 3: body-supplied foreign keys resolve, in input order.
    for key, table in (
        ("cycle_id", db.cycles),
        ("site_id", db.sites),
        ("factor_id", db.factors),
    ):
        v = body.get(key)
        if v is not None and (not isinstance(v, str) or v not in table):
            raise not_found(f"Field {key} does not resolve to an existing resource")
    # Priority 4: request shape. Client-supplied computed/system fields
    # (tco2e, factor_value_snapshot, status, ...) are ignored.
    cycle = db.cycles[v_str(body, "cycle_id")]
    site = db.sites[v_str(body, "site_id")]
    factor = db.factors[v_str(body, "factor_id")]
    activity_type = v_enum(body, "activity_type", set(TYPE_TO_CATEGORY))
    quantity = v_num(body, "quantity", gt=0)
    unit = v_str(body, "unit")
    ps_raw, ps = v_datetime(body, "period_start")
    pe_raw, pe = v_datetime(body, "period_end")
    # Priority 6: child-mutation cycle gate — record creation requires the
    # cycle to be in DATA_COLLECTION.
    if cycle["status"] != "DATA_COLLECTION":
        raise err(
            "ERR_CYCLE_NOT_COLLECTING",
            409,
            f"Cycle in status {cycle['status']} does not accept new activity records",
        )
    # Priority 9: activity period fully inside the cycle reporting year
    # [year-01-01T00:00:00Z, (year+1)-01-01T00:00:00Z).
    year_start = datetime(cycle["reporting_year"], 1, 1, tzinfo=timezone.utc)
    next_year_start = datetime(cycle["reporting_year"] + 1, 1, 1, tzinfo=timezone.utc)
    if not (ps >= year_start and pe <= next_year_start):
        raise err(
            "ERR_PERIOD_OUTSIDE_CYCLE_YEAR",
            422,
            "Activity period is not fully inside the cycle reporting year",
        )
    # Priority 10: half-open period overlap per (site_id, activity_type);
    # touching endpoints are allowed.
    for other in db.records.values():
        if (
            other["site_id"] == site["id"]
            and other["activity_type"] == activity_type
            and other["status"] in OVERLAP_STATUSES
            and ps < other["_pe"]
            and other["_ps"] < pe
        ):
            raise err(
                "ERR_PERIOD_OVERLAP",
                409,
                "Activity period overlaps another non-terminal record for the "
                "same site and activity type",
            )
    # Priority 12: unit consistency and activity_type/scope_category mapping.
    if unit != factor["unit"] or TYPE_TO_CATEGORY[activity_type] != factor["scope_category"]:
        raise err(
            "ERR_UNIT_MISMATCH",
            422,
            "Record unit or activity type does not agree with the referenced factor",
        )
    # Priority 16: referential freshness — site first, then factor.
    if site["status"] != "ACTIVE":
        raise err("ERR_SITE_INACTIVE", 422, "Referenced site is not ACTIVE")
    if not calc.factor_covers_period(factor, ps, pe):
        raise err(
            "ERR_FACTOR_NOT_PUBLISHED",
            422,
            "Referenced factor is not PUBLISHED or does not cover the record period",
        )
    rec = new_entity(
        {
            "cycle_id": cycle["id"],
            "site_id": site["id"],
            "factor_id": factor["id"],
            "activity_type": activity_type,
            "quantity": quantity,
            "unit": unit,
            "period_start": ps_raw,
            "period_end": pe_raw,
            "status": "SUBMITTED",
            "submitted_by_user_id": g.user_id,
            "reviewed_by_user_id": None,
            "reject_reason": None,
            "factor_value_snapshot": None,
            "tco2e": None,
            "_ps": ps,
            "_pe": pe,
        }
    )
    db.records[rec["id"]] = rec
    return ok(domain.ser_record(rec), status=201)


@bp.route("/activity-records/<record_id>", methods=["GET"])
@require_roles(*READ_ROLES)
def get_record(record_id):
    return ok(domain.ser_record(load_record(record_id)))


@bp.route("/activity-records", methods=["GET"])
@require_roles(*READ_ROLES)
def list_records():
    limit, offset = parse_pagination()
    items = sorted(db.records.values(), key=lambda x: x["_seq"])
    cycle_id = request.args.get("cycle_id")
    site_id = request.args.get("site_id")
    factor_id = request.args.get("factor_id")
    status = request.args.get("status")
    if cycle_id is not None:
        items = [r for r in items if r["cycle_id"] == cycle_id]
    if site_id is not None:
        items = [r for r in items if r["site_id"] == site_id]
    if factor_id is not None:
        items = [r for r in items if r["factor_id"] == factor_id]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    total = len(items)
    page = items[offset : offset + limit]
    return ok_list([domain.ser_record(r) for r in page], limit, offset, total)


@bp.route("/activity-records/<record_id>/transition", methods=["POST"])
@require_roles(STEWARD, ANALYST, MANAGER)
def record_transition(record_id):
    body = get_body()
    # Priority 2: authorization for the specific transition target.
    require_target_role(body, RECORD_TARGET_ROLE)
    # Priority 3: path existence.
    rec = load_record(record_id)
    # Priority 4: request shape (reason required and non-empty on REJECTED).
    to_state = v_enum(body, "to_state", RECORD_STATUSES)
    reason = None
    if to_state == "REJECTED":
        reason = v_str(body, "reason")
    # Priority 6: the record's own state permits the transition.
    if rec["status"] not in LEGAL_FROM[to_state]:
        raise invalid_state(
            f"ActivityRecord in status {rec['status']} cannot transition to {to_state}"
        )
    # Priority 6: parent-cycle gate for child mutations.
    cycle = db.cycles[rec["cycle_id"]]
    if cycle["status"] not in ("DATA_COLLECTION", "UNDER_REVIEW"):
        raise err(
            "ERR_CYCLE_NOT_COLLECTING",
            409,
            f"Cycle in status {cycle['status']} does not permit record workflow steps",
        )

    if to_state == "UNDER_REVIEW":
        pass
    elif to_state == "SUBMITTED":
        # Resubmit: cyclic revision loop REJECTED -> SUBMITTED.
        rec["reject_reason"] = None
    elif to_state == "REJECTED":
        # Priority 7: segregation of duties.
        if g.user_id == rec["submitted_by_user_id"]:
            raise sod("The rejecter must differ from the record submitter")
        rec["reject_reason"] = reason
        rec["reviewed_by_user_id"] = g.user_id
        calc.recompute_readiness(cycle)
    elif to_state == "APPROVED":
        # Priority 7: segregation of duties.
        if g.user_id == rec["submitted_by_user_id"]:
            raise sod("The approver must differ from the record submitter")
        # Priority 8: evidence mandate for large records.
        if calc.dec(rec["quantity"]) >= EVIDENCE_MANDATE_QTY:
            has_verified = any(
                e["activity_record_id"] == rec["id"] and e["status"] == "VERIFIED"
                for e in db.evidence.values()
            )
            if not has_verified:
                raise err(
                    "ERR_EVIDENCE_REQUIRED",
                    422,
                    "Approving a record with quantity >= 1000 requires at least "
                    "one VERIFIED evidence item",
                )
        # Priority 16: factor freshness re-checked at approval.
        factor = db.factors[rec["factor_id"]]
        if not calc.factor_covers_period(factor, rec["_ps"], rec["_pe"]):
            raise err(
                "ERR_FACTOR_NOT_PUBLISHED",
                422,
                "Referenced factor is no longer PUBLISHED or no longer covers "
                "the record period",
            )
        # Version-pinning on approval: snapshot the factor value, then compute.
        rec["factor_value_snapshot"] = factor["value_tco2e_per_unit"]
        rec["tco2e"] = float(
            calc.r4(calc.dec(rec["quantity"]) * calc.dec(factor["value_tco2e_per_unit"]))
        )
        rec["reviewed_by_user_id"] = g.user_id
        rec["status"] = "APPROVED"
        # Full three-link approval cascade + readiness recompute; both the
        # record's and the cycle's versions advance.
        calc.cascade_staleness(cycle)
        calc.recompute_readiness(cycle)
        touch(rec)
        touch(cycle)
        return ok(domain.ser_record(rec))
    elif to_state == "VOIDED":
        # Compensating reversal of the approval cascade.
        rec["status"] = "VOIDED"
        calc.cascade_staleness(cycle)
        calc.recompute_readiness(cycle)
        touch(rec)
        touch(cycle)
        return ok(domain.ser_record(rec))

    rec["status"] = to_state
    touch(rec)
    return ok(domain.ser_record(rec))
