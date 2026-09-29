"""Prospect households (PRD 3.3)."""

from flask import Blueprint

import auth
import validators
from envelope import created, ok
from helpers import get_prospect
from store import db

bp = Blueprint("prospects", __name__)


@bp.post("/prospects")
def create_prospect():
    auth.require(auth.MARKETING_MANAGER)
    data = validators.body()
    household_name = validators.string(data, "household_name", 1, 120)
    primary_age = validators.integer(data, "primary_age", 18, 99)
    income = validators.integer(data, "household_income_cents", 0)
    marital_status = validators.enum(data, "marital_status", ("MARRIED", "SINGLE"))

    now = db.now()
    prospect = {
        "id": db.new_id(),
        "_seq": db.next_seq(),
        "household_name": household_name,
        "primary_age": primary_age,
        "household_income_cents": income,
        "marital_status": marital_status,
        "is_existing_owner": False,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.prospects[prospect["id"]] = prospect
    return created(prospect)


@bp.get("/prospects/<prospect_id>")
def read_prospect(prospect_id):
    auth.require_any()
    return ok(get_prospect(prospect_id))
