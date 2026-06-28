"""Client registration and reads (PRD §3.2)."""
from flask import Blueprint, request

import db
from middleware import get_auth, require_roles
from response import object_response, array_response
from services.common import (
    init_full, serialize, get_body,
    require_str, require_int, paginate, parse_iso,
)
from services.lookups import get_or_404, get_fk_or_404

bp = Blueprint("clients", __name__)


@bp.post("/clients")
def create_client():
    # PRD §3.2 / §4: FrontDesk or PracticeAdmin.
    _, role = get_auth()
    require_roles(role, {"FrontDesk", "PracticeAdmin"})
    body = get_body()
    practice_id = require_str(body, "practice_id")
    full_name = require_str(body, "full_name")
    infant_dob = require_str(body, "infant_dob")
    household_income_cents = require_int(body, "household_income_cents")
    package_id = body.get("package_id")

    # Priority 4: referenced FK existence (practice_id, optional package_id).
    get_fk_or_404(db.practices, practice_id)
    package = None
    if package_id is not None:
        package = get_fk_or_404(db.service_packages, package_id)

    # Priority 5: well-formedness — infant_dob must be a valid ISO8601 datetime.
    parse_iso(infant_dob)

    # Credit accounting (PRD §3.2): when a package is supplied, total =
    # included_visits, remaining = same, consumed = 0; otherwise all 0.
    if package is not None:
        credits_total = package["included_visits"]
    else:
        credits_total = 0

    record = {
        "practice_id": practice_id,
        "full_name": full_name,
        "infant_dob": infant_dob,
        "household_income_cents": household_income_cents,
        "package_id": package_id,
        "package_credits_total": credits_total,
        "package_credits_consumed": 0,
        "package_credits_remaining": credits_total,
        "reimbursement_ledger_cents": 0,
        "no_show_strikes": 0,
        # Every newly registered client starts ACTIVE (PRD §3.2).
        "status": "ACTIVE",
    }
    init_full(record)
    db.clients[record["id"]] = record
    return object_response(serialize(record), 201)


@bp.get("/clients/<rid>")
def get_client(rid):
    _, role = get_auth()
    require_roles(role, {"PracticeAdmin", "BillingSpecialist", "Consultant",
                         "FrontDesk", "Client"})
    record = get_or_404(db.clients, rid)
    return object_response(serialize(record), 200)


@bp.get("/clients")
def list_clients():
    _, role = get_auth()
    require_roles(role, {"PracticeAdmin", "BillingSpecialist", "Consultant",
                         "FrontDesk"})
    practice_id = request.args.get("practice_id")
    package_id = request.args.get("package_id")
    records = []
    for r in db.clients.values():
        if practice_id is not None and r["practice_id"] != practice_id:
            continue
        if package_id is not None and r.get("package_id") != package_id:
            continue
        records.append(r)
    items, limit, offset, total = paginate(records)
    return array_response(items, limit, offset, total, 200)
