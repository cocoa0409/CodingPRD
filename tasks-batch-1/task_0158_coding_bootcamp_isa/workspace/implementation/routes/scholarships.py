"""Scholarship application with OCC on Enrollment.version (PRD §3.7, §2.9)."""
from decimal import Decimal

from flask import Blueprint, request

import errors
from db import db, stamp_create, touch
from middleware import require_role
from response import success
from services import serialize
from services.calc import round_half_up_cents
from services.common import (
    get_json_body, parse_pagination, sort_by_created, paginate, lookup,
    require_fields, as_enum, as_number, as_int,
)
from services.derive import recompute_isa_ledger

bp = Blueprint("scholarships", __name__)

KINDS = {"DEI", "MERIT", "NEED"}


@bp.post("/scholarships")
def create_scholarship():
    require_role("AdmissionsOfficer")
    body = get_json_body()
    require_fields(body, ["enrollment_id", "kind", "cap_reduction_pct",
                          "expected_enrollment_version"])
    enrollment_id = body["enrollment_id"]
    if not isinstance(enrollment_id, str):
        raise errors.invalid_request("enrollment_id must be a string")
    e = lookup(db.enrollments, enrollment_id)  # existence first

    kind = as_enum(body, "kind", KINDS)
    cap_reduction = as_number(body, "cap_reduction_pct", gt=0, le=1)
    expected_version = as_int(body, "expected_enrollment_version")

    # OCC check (priority 6, after existence/shape/state per §2.8)
    if expected_version != e["version"]:
        raise errors.stale_version()

    # supersede prior APPLIED scholarship on this enrollment
    for s in db.scholarships.values():
        if s["enrollment_id"] == enrollment_id and s["status"] == "APPLIED":
            s["status"] = "SUPERSEDED"
            touch(s)

    sch = {
        "enrollment_id": enrollment_id,
        "kind": kind,
        "cap_reduction_pct": cap_reduction,
        "status": "APPLIED",
    }
    stamp_create(sch)
    db.scholarships[sch["id"]] = sch

    # recompute linked ISA cap from the original base cap; newest award governs
    contract = next((c for c in db.isa_contracts.values()
                     if c["enrollment_id"] == enrollment_id), None)
    if contract is not None:
        base = contract.get("_base_cap_cents", contract["cap_cents"])
        new_cap = round_half_up_cents(Decimal(base) * (Decimal("1") - Decimal(str(cap_reduction))))
        contract["cap_cents"] = new_cap
        recompute_isa_ledger(contract)
        touch(contract)

    # enrollment version += 1
    touch(e)

    return success(serialize.scholarship_view(sch), status=201)


@bp.get("/scholarships/<sid>")
def get_scholarship(sid):
    require_role("AdmissionsOfficer", "ComplianceOfficer")
    s = lookup(db.scholarships, sid)
    return success(serialize.scholarship_view(s))


@bp.get("/scholarships")
def list_scholarships():
    require_role("AdmissionsOfficer", "ComplianceOfficer")
    limit, offset = parse_pagination()
    enrollment_id = request.args.get("enrollment_id")
    status = request.args.get("status")
    rows = list(db.scholarships.values())
    if enrollment_id is not None:
        rows = [s for s in rows if s["enrollment_id"] == enrollment_id]
    if status is not None:
        rows = [s for s in rows if s["status"] == status]
    rows = sort_by_created(rows)
    window, pg = paginate(rows, limit, offset)
    return success([serialize.scholarship_view(s) for s in window], pagination=pg)
