"""Declarant subsidy ledger: posting, reversal (CASCADE-2) and reads."""
from flask import Blueprint

import auth
import calc
import cascades
import constants
import response
import validation as v
from db import db, new_record, ordered, serialize, serialize_list, touch
from errors import ApiError
from routes import common

bp = Blueprint("subsidy_entries", __name__)


@bp.get("/hoa/subsidy-entries/<entry_id>")
def read_entry(entry_id):
    auth.require_roles(*constants.ALL_ROLES)
    entry = common.subsidy_entry_or_404(entry_id, scoped=True)
    return response.object_response(serialize(entry))


@bp.get("/hoa/subsidy-entries")
def list_entries():
    auth.require_roles(*constants.ALL_ROLES)
    records = ordered(list(db.subsidy_entries.values()))
    for field in ("association_id", "reverses_entry_id", "direction", "status"):
        value = v.query_filter(field)
        if value is not None:
            records = [r for r in records if r[field] == value]
    window, pagination = response.paginate(records)
    return response.array_response(serialize_list(window), pagination)


@bp.post("/hoa/subsidy-entries")
def create_entry():
    auth.require_roles(constants.ROLE_DECLARANT)
    body = v.body()

    association = common.body_association_or_404(v.get_fk(body, "association_id"))
    if association is None:
        raise ApiError("ERR_INVALID_REQUEST", "association_id is required.")

    direction = v.get_enum(body, "direction", constants.SUBSIDY_DIRECTIONS_INPUT)
    amount = v.get_int(body, "amount_cents", minimum=1)
    period_month = v.get_period_month(body, "period_month")

    cascades.require_not_settled_locked(association["id"])

    entry = new_record({
        "association_id": association["id"],
        "direction": direction,
        "amount_cents": amount,
        "period_month": period_month,
        "reverses_entry_id": None,
        "posted_by_user_id": auth.current_user_id(),
        "status": "POSTED",
    })
    db.subsidy_entries[entry["id"]] = entry

    calc.apply_subsidy_receivable(association)
    touch(association)
    cascades.refresh_issued_engagements(association)

    return response.object_response(serialize(entry), 201)


@bp.post("/hoa/subsidy-entries/<entry_id>/reverse")
def reverse_entry(entry_id):
    auth.require_roles(constants.ROLE_DECLARANT)
    entry = common.subsidy_entry_or_404(entry_id, scoped=True)
    body = v.body()
    v.get_str(body, "reason", min_len=1, max_len=400)

    cascades.require_not_settled_locked(entry["association_id"])

    if (
        entry["status"] != "POSTED"
        or entry["direction"] not in constants.SUBSIDY_DIRECTIONS_INPUT
        or entry["reverses_entry_id"] is not None
    ):
        raise ApiError("ERR_SUBSIDY_ENTRY_ALREADY_REVERSED")

    # ---- CASCADE-2 hop A ----
    entry["status"] = "REVERSED"
    touch(entry)
    mirror = new_record({
        "association_id": entry["association_id"],
        "direction": "REVERSAL",
        "amount_cents": entry["amount_cents"],
        "period_month": entry["period_month"],
        "reverses_entry_id": entry["id"],
        "posted_by_user_id": auth.current_user_id(),
        "status": "POSTED",
    })
    db.subsidy_entries[mirror["id"]] = mirror

    # ---- CASCADE-2 hops B, C and D ----
    association = db.associations.get(entry["association_id"])
    if association is not None:
        calc.apply_subsidy_receivable(association)
        touch(association)
        cascades.refresh_issued_engagements(association)

    return response.object_response(serialize(entry))
