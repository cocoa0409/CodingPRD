"""InstitutionSystem endpoints."""
from decimal import Decimal

from flask import Blueprint, request

from db import DB, new_id
from middleware import auth
from response import ok, ok_list
from services import get_or_404
from util import (
    as_enum,
    as_str,
    body,
    paginate,
    pagination,
    required,
    round_half_up_2,
    stamp_new,
)

bp = Blueprint("systems", __name__)

SYSTEM_TYPES = {"DISTRICT", "NETWORK", "SINGLE_SCHOOL"}


def system_view(s):
    return {k: v for k, v in s.items() if not k.startswith("_")}


@bp.post("/accreditation/systems")
def create_system():
    auth(["AccreditationOfficer"])
    data = body()
    name = as_str(required(data, "name"), "name")
    system_type = as_enum(required(data, "system_type"), "system_type", SYSTEM_TYPES)
    record = {
        "id": new_id(),
        "name": name,
        "system_type": system_type,
        "accreditation_status": "CANDIDATE",
        "current_term_id": None,
        "fee_credit_cents": 0,
    }
    stamp_new(record, with_version=True)
    DB["systems"][record["id"]] = record
    return ok(system_view(record), status=201)


@bp.get("/accreditation/systems")
def list_systems():
    auth(["AccreditationOfficer", "AccreditationCommission", "SystemBursar"])
    limit, offset = pagination()
    rows = sorted(DB["systems"].values(), key=lambda s: s["created_at"])
    status = request.args.get("accreditation_status")
    term_id = request.args.get("current_term_id")
    if status:
        rows = [r for r in rows if r["accreditation_status"] == status]
    if term_id:
        rows = [r for r in rows if r["current_term_id"] == term_id]
    page, total = paginate(rows, limit, offset)
    return ok_list([system_view(r) for r in page], total, limit, offset)


@bp.get("/accreditation/systems/<id>")
def get_system(id):
    auth(["AccreditationOfficer", "AccreditationCommission", "SchoolLeader", "SystemBursar"])
    row = get_or_404("systems", id, "InstitutionSystem")
    return ok(system_view(row))


@bp.get("/accreditation/systems/<id>/dashboard")
def system_dashboard(id):
    auth(["AccreditationOfficer", "AccreditationCommission"])
    system = get_or_404("systems", id, "InstitutionSystem")
    in_scope = [
        c for c in DB["campuses"].values()
        if c["system_id"] == id and c["campus_status"] == "IN_SCOPE"
    ]
    current_term_id = system["current_term_id"]
    finalized = []
    if current_term_id is not None:
        in_scope_ids = {c["id"] for c in in_scope}
        finalized = [
            r for r in DB["ratings"].values()
            if r["term_id"] == current_term_id
            and r["status"] == "FINALIZED"
            and r["campus_id"] in in_scope_ids
        ]
    if not finalized:
        projected = None
    else:
        numerator = Decimal(0)
        denominator = Decimal(0)
        for r in finalized:
            std = DB["standards"].get(r["standard_id"])
            if std is None:
                continue
            w = Decimal(std["weight_pct"])
            numerator += Decimal(r["rating"]) * w
            denominator += w
        if denominator == 0:
            projected = None
        else:
            raw = (numerator / denominator) * (Decimal(100) / Decimal(4))
            projected = round_half_up_2(raw)
    return ok(
        {
            "projected_index_pct": projected,
            "campus_count_in_scope": len(in_scope),
            "finalized_rating_count": len(finalized),
        }
    )
