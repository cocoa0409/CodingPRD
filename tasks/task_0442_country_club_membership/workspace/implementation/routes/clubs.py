"""Club config + ops endpoints (PRD §3.1, §3.6, §3.7, §3.8)."""
from flask import Blueprint

import db
import errors
import common
import billing
from middleware import get_auth, require_roles
from response import success_object, success_array
from serializers import club_out, statement_out
from timeutil import parse_iso

bp = Blueprint("clubs", __name__)


@bp.post("/clubs")
def create_club():
    role, _ = get_auth()
    require_roles(role, ["ClubManager"])
    body = common.get_body()
    name = common.require_string(body, "name")
    fb_carryover = common.optional_bool(body, "fb_minimum_carryover_allowed", False)
    refund_pct = common.optional_int(body, "resignation_refund_pct", 80)
    if refund_pct < 0 or refund_pct > 100:
        raise errors.invalid_request("resignation_refund_pct must be in 0..100")
    guest_cap = common.optional_int(body, "guest_visits_cap_per_period", 4)
    if guest_cap < 0:
        raise errors.invalid_request("guest_visits_cap_per_period must be non-negative")

    rec = db.base_record(common_fields=True)
    rec.update(
        {
            "name": name,
            "billing_period_index": 0,
            "closed_through_period_index": -1,
            "fb_minimum_carryover_allowed": fb_carryover,
            "resignation_refund_pct": refund_pct,
            "guest_visits_cap_per_period": guest_cap,
        }
    )
    db.clubs[rec["id"]] = rec
    return success_object(club_out(rec), status=201)


@bp.get("/clubs/<cid>")
def get_club(cid):
    role, _ = get_auth()
    require_roles(role, ["ClubManager", "BillingClerk", "Member"])
    rec = common.get_club(cid)
    return success_object(club_out(rec), status=200)


@bp.post("/clubs/<cid>/close-period")
def close_period(cid):
    role, _ = get_auth()
    require_roles(role, ["ClubManager"])
    club = common.get_club(cid)
    body = common.get_body()
    # OCC on the club itself (PRD §3.7).
    expected = body.get("expected_club_version")
    if expected is not None and expected != club["version"]:
        raise errors.stale_version("expected_club_version does not match")
    billing.close_period(club)
    return success_object(club_out(club), status=200)


@bp.post("/clubs/<cid>/open-statements")
def open_statements(cid):
    role, _ = get_auth()
    require_roles(role, ["ClubManager", "BillingClerk"])
    club = common.get_club(cid)
    stmts = billing.open_statements(club)
    limit, offset = len(stmts) if stmts else 1, 0
    # open-statements returns the list of OPEN statements; no pagination params
    # are declared, return them all in array envelope.
    data = [statement_out(s) for s in stmts]
    return success_array(data, limit=len(data) if data else 0, offset=0, total_count=len(data))


@bp.post("/_clock/set_current_utc")
def set_clock():
    role, _ = get_auth()
    require_roles(role, ["ClubManager"])
    body = common.get_body()
    common.require_fields(body, ["to_iso8601"])
    # Validate it parses as an ISO 8601 instant.
    parse_iso(body["to_iso8601"], err=errors.invalid_request)
    db.LOGICAL_CLOCK[0] = body["to_iso8601"]
    return success_object({}, status=200)
