"""Retainer endpoints (PRD §3.10): read, list, replace."""

from flask import Blueprint, request

import errors
from db import db, lock
from helpers import (
    get_json_body, stamp_new, parse_pagination, sort_and_paginate, touch,
)
from lookups import get_or_404
from middleware import require_roles
from response import success, list_success
from serializers import public, public_list
from clock import clock, format_iso8601_ms

bp = Blueprint("retainers", __name__)

RETAINER_TYPES = {"HAWLEY", "CLEAR", "FIXED"}


@bp.get("/retainers/<retainer_id>")
@require_roles("Orthodontist", "ClinicAdmin", "Guardian")
def get_retainer(retainer_id):
    with lock:
        rec = get_or_404(db.retainers, retainer_id)
        _guardian_owns_retainer(rec)
        return success(public(rec), 200)


@bp.get("/retainers")
@require_roles("Orthodontist", "ClinicAdmin", "Guardian")
def list_retainers():
    from flask import g
    with lock:
        limit, offset = parse_pagination()
        plan_id = request.args.get("plan_id")
        records = list(db.retainers.values())
        if plan_id is not None:
            records = [r for r in records if r["plan_id"] == plan_id]
        if g.user_role == "Guardian":
            records = [r for r in records if _retainer_owned_by_guardian(r)]
        page, total = sort_and_paginate(records, limit, offset)
        return list_success(public_list(page), limit, offset, total, 200)


@bp.post("/retainers/<retainer_id>/replace")
@require_roles("Orthodontist")
def replace_retainer(retainer_id):
    body = get_json_body()
    retainer_type = body.get("retainer_type")
    with lock:
        old = get_or_404(db.retainers, retainer_id)
        if old["status"] != "ISSUED":
            raise errors.invalid_state()
        if retainer_type is None:
            retainer_type = old["retainer_type"]
        elif retainer_type not in RETAINER_TYPES:
            raise errors.invalid_request("retainer_type must be HAWLEY|CLEAR|FIXED")
        old["status"] = "REPLACED"
        touch(old)
        new_rec = {
            "plan_id": old["plan_id"],
            "retainer_type": retainer_type,
            "issued_at": format_iso8601_ms(clock.now()),
            "status": "ISSUED",
        }
        stamp_new(new_rec)
        db.retainers[new_rec["id"]] = new_rec
        # The endpoint returns the (now REPLACED) old retainer per the scaffold
        # output (output: Retainer; side effect creates the new one).
        return success(public(old), 200)


# -----------------------------------------------------------------------------
# Ownership helpers
# -----------------------------------------------------------------------------

def _retainer_owned_by_guardian(retainer):
    from lookups import family_of_patient, guardian_owns_family
    plan = db.treatment_plans.get(retainer["plan_id"])
    if not plan:
        return False
    pat = db.patients.get(plan["patient_id"])
    return pat is not None and guardian_owns_family(family_of_patient(pat))


def _guardian_owns_retainer(retainer):
    from flask import g
    if g.user_role == "Guardian" and not _retainer_owned_by_guardian(retainer):
        raise errors.forbidden()
