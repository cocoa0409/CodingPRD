"""Committee endpoints (PRD §3.5)."""
from flask import Blueprint

from errors import raise_error, ERR_COMMITTEE_NOT_FOUND, ERR_INVALID_INTERVAL
from middleware import authorized
from response import success_object
from routes.helpers import public, get_one
from services.core import new_record
from util import parse_dt, is_valid_dt
from validate import get_body, req_str, req_enum, req_datetime_str, opt_number, raw_str

bp = Blueprint("committees", __name__)

LEVELS = {"DEPARTMENT", "COLLEGE", "UNIVERSITY"}
PASS_RULES = {"STRICT_MAJORITY_OF_CAST", "SUPERMAJORITY_OF_ENTITLED"}


@bp.post("/committees")
def create_committee():
    authorized(["ProvostOfficer"])
    body = get_body()
    # Priority 9: interval sanity before generic shape failures (listed order).
    ts_raw = raw_str(body, "term_start")
    te_raw = raw_str(body, "term_end")
    if ts_raw is not None and te_raw is not None and is_valid_dt(ts_raw) and is_valid_dt(te_raw):
        if not (parse_dt(ts_raw) < parse_dt(te_raw)):
            raise_error(ERR_INVALID_INTERVAL, "term_start must be strictly before term_end")
    level = req_enum(body, "level", LEVELS)
    academic_unit = req_str(body, "academic_unit")
    term_start = req_datetime_str(body, "term_start")
    term_end = req_datetime_str(body, "term_end")
    quorum_fraction = opt_number(body, "quorum_fraction", 0.5)
    pass_rule = req_enum(body, "pass_rule", PASS_RULES)
    rec = new_record("committees", {
        "level": level,
        "academic_unit": academic_unit,
        "term_start": term_start,
        "term_end": term_end,
        "quorum_fraction": quorum_fraction,
        "pass_rule": pass_rule,
    })
    return success_object(public(rec), status=201)


@bp.get("/committees/<rid>")
def get_committee(rid):
    return get_one("committees", rid, ERR_COMMITTEE_NOT_FOUND)
