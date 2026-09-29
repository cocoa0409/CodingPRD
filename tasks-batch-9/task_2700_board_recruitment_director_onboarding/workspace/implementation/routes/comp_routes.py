"""Director compensation awards: the fee waterfall and the ownership test."""

from flask import Blueprint

from authz import (
    COMMITTEE_CHAIR,
    COMMITTEE_MEMBER,
    CORPORATE_SECRETARY,
    GOVERNANCE_STAFF,
    SEATED_DIRECTOR,
    require,
)
from calc import award_waterfall, require_policy
from derive import recompute_compliance
from errors import fail
from payload import body, check_interval_on_or_after, check_min, parse_date, required
from store import clock_instant, db, new_row, touch

from routes.common import apply_filters, by_field, emit, emit_list, need

bp = Blueprint("comp", __name__)

READ_ROLES = (GOVERNANCE_STAFF, CORPORATE_SECRETARY, COMMITTEE_CHAIR, COMMITTEE_MEMBER,
              SEATED_DIRECTOR)
PAYABLE_SERVICE = ("ONBOARDING", "SEATED", "RETIREMENT_NOTICED")


@bp.post("/directors/<director_id>/comp-awards")
def create_award(director_id):
    require(CORPORATE_SECRETARY)
    b = body()
    cycle_year = required(b, "cycle_year", "integer")
    service_start_on = required(b, "service_start_on", "string")
    service_end_on = required(b, "service_end_on", "string")
    share_price_cents = required(b, "share_price_cents", "integer")
    shares_held = required(b, "shares_held", "integer")
    check_min("cycle_year", cycle_year, 2000)
    check_min("share_price_cents", share_price_cents, 1)
    check_min("shares_held", shares_held, 0)
    start_date = parse_date(service_start_on, "service_start_on")
    end_date = parse_date(service_end_on, "service_end_on")
    check_interval_on_or_after(end_date, start_date,
                               "service_end_on must fall on or after service_start_on.")
    director = need("director", director_id)
    policy = require_policy()
    for row in db.comp_awards.values():
        if row["director_id"] == director_id and row["status"] != "VOIDED" \
                and row["cycle_year"] == cycle_year:
            fail("ERR_DUPLICATE_RESOURCE",
                 "This director already holds a live award for cycle %s." % cycle_year)

    fields = {
        "director_id": director_id,
        "cycle_year": cycle_year,
        "service_start_on": service_start_on,
        "service_end_on": service_end_on,
        "share_price_cents": share_price_cents,
        "shares_held": shares_held,
    }
    fields.update(award_waterfall(policy, director, start_date, end_date,
                                  share_price_cents, shares_held))
    fields.update({"status": "DRAFT", "finalized_at": None})
    row = new_row(fields)
    db.comp_awards[row["id"]] = row
    return emit(row, 201)


@bp.get("/directors/<director_id>/comp-awards")
def list_director_awards(director_id):
    require(*READ_ROLES)
    need("director", director_id)
    rows = [a for a in db.comp_awards.values() if a["director_id"] == director_id]
    rows = apply_filters(rows, {"status": ("status", "str"),
                                "cycle_year": ("cycle_year", "int")})
    return emit_list(by_field(rows, "cycle_year", reverse=True))


@bp.get("/comp-awards/<award_id>")
def read_award(award_id):
    require(*READ_ROLES)
    return emit(need("comp_award", award_id))


@bp.get("/comp-awards")
def list_awards():
    require(*READ_ROLES)
    rows = apply_filters(list(db.comp_awards.values()), {
        "director_id": ("director_id", "str"),
        "cycle_year": ("cycle_year", "int"),
        "status": ("status", "str"),
    })
    return emit_list(by_field(rows, "cycle_year", reverse=True))


@bp.post("/comp-awards/<award_id>/finalize")
def finalize_award(award_id):
    require(CORPORATE_SECRETARY)
    row = need("comp_award", award_id)
    if row["status"] != "DRAFT":
        fail("ERR_COMP_AWARD_STATE_INVALID",
             "Only a DRAFT award may be finalized; this one is %s." % row["status"])
    director = db.directors.get(row["director_id"])
    if director is None or director["service_status"] not in PAYABLE_SERVICE:
        fail("ERR_DIRECTOR_STATE_INVALID",
             "An award may only be finalized while the director is in active service.")
    row["status"] = "FINALIZED"
    row["finalized_at"] = clock_instant()
    touch(row)
    director["shares_held"] = row["shares_held"]
    touch(director)
    recompute_compliance(director)
    return emit(row)
