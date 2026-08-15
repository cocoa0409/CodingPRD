"""Generators and offtakers."""
from decimal import Decimal

from flask import Blueprint

from common import (actor, as_str, as_str_list, body_dict, created, not_found,
                    ok, ok_list, paginate, ser)
from logic import new_record, sorted_items
from store import db

bp = Blueprint("orgs", __name__)


@bp.post("/api/generators")
def create_generator():
    actor({"BrokerOps"})
    body = body_dict()
    rec = new_record()
    rec["legal_name"] = as_str(body, "legal_name")
    rec["hq_state_code"] = as_str(body, "hq_state_code")
    rec["contact_email"] = as_str(body, "contact_email")
    rec["total_credits"] = Decimal("0")
    rec["credit_tier"] = "STANDARD"
    db.generators[rec["id"]] = rec
    return created(ser(rec))


@bp.get("/api/generators")
def list_generators():
    actor()
    page, meta = paginate(sorted_items(db.generators.values()))
    return ok_list([ser(r) for r in page], meta)


@bp.get("/api/generators/<gid>")
def get_generator(gid):
    actor()
    rec = db.generators.get(gid)
    if rec is None:
        not_found("Generator not found")
    return ok(ser(rec))


@bp.post("/api/offtakers")
def create_offtaker():
    actor({"BrokerOps"})
    body = body_dict()
    rec = new_record()
    rec["legal_name"] = as_str(body, "legal_name")
    rec["hq_state_code"] = as_str(body, "hq_state_code")
    rec["receiving_state_codes"] = as_str_list(body, "receiving_state_codes")
    db.offtakers[rec["id"]] = rec
    return created(ser(rec))


@bp.get("/api/offtakers")
def list_offtakers():
    actor()
    page, meta = paginate(sorted_items(db.offtakers.values()))
    return ok_list([ser(r) for r in page], meta)
