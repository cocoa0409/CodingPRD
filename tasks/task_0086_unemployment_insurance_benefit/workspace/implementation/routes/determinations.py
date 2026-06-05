"""Determination endpoints: issue, get, list-for-claim."""
from datetime import date, timedelta

from flask import Blueprint

import db
from clock import clock, parse_instant
from errors import err
from middleware import authenticate, require_role
from response import object_response, array_response
from validate import as_enum, as_string, get_json_body, paginate, serialize
from services import claim_logic

bp = Blueprint("determinations", __name__)

APPEAL_WINDOW_DAYS = 30

MONETARY_PENDING = "MONETARY_PENDING"
MONETARILY_ELIGIBLE = "MONETARILY_ELIGIBLE"
MONETARILY_INELIGIBLE = "MONETARILY_INELIGIBLE"


def _appeal_deadline_date(created_at_iso):
    """determination created_at date + APPEAL_WINDOW_DAYS (ISO date)."""
    created = parse_instant(created_at_iso).date()
    return (created + timedelta(days=APPEAL_WINDOW_DAYS)).isoformat()


@bp.route("/ui/determinations", methods=["POST"])
def create_determination():
    p = authenticate()
    require_role(p, {"Adjudicator"})
    body = get_json_body()
    claim_id = as_string(body, "claim_id")
    if claim_id not in db.claims:
        raise err("ERR_NOT_FOUND", "claim_id not found.")
    det_type = as_enum(body, "determination_type", {"MONETARY", "NONMONETARY"})
    claim = db.claims[claim_id]

    rec = {
        "claim_id": claim_id,
        "determination_type": det_type,
        "outcome": "PENDING",
        "issuing_adjudicator_id": p.user_id,
        "base_period_total_wages_cents": 0,
        "high_quarter_wages_cents": 0,
        "appeal_deadline_date": None,
        "is_appealable": True,
    }

    if det_type == "MONETARY":
        # state check: claim must be MONETARY_PENDING
        if claim["status"] != MONETARY_PENDING:
            raise err("ERR_INVALID_STATE",
                      "Claim is not MONETARY_PENDING for a monetary determination.")
        results = claim_logic.run_monetary(claim)
        if results["method"] != "NONE":
            # ALLOWED
            rec["outcome"] = "ALLOWED"
            rec["base_period_total_wages_cents"] = results["base_total"]
            rec["high_quarter_wages_cents"] = results["high_quarter"]
            claim["base_period_method"] = results["method"]
            claim["weekly_benefit_amount_cents"] = results["wba"]
            claim["maximum_benefit_amount_cents"] = results["base_mba"]
            claim["remaining_balance_cents"] = results["base_mba"]
            claim["status"] = MONETARILY_ELIGIBLE
        else:
            # DENIED
            rec["outcome"] = "DENIED"
            claim["base_period_method"] = "NONE"
            claim["weekly_benefit_amount_cents"] = 0
            claim["maximum_benefit_amount_cents"] = 0
            claim["remaining_balance_cents"] = 0
            claim["status"] = MONETARILY_INELIGIBLE
    else:
        # NONMONETARY determination: no claim monetary transition here.
        # outcome stays PENDING per scaffold (system sets ALLOWED/DENIED via
        # later workflow; PRD does not pin a monetary-style auto-decision for
        # nonmonetary). is_appealable stays true.
        rec["outcome"] = "PENDING"

    db.stamp_create(rec)
    rec["appeal_deadline_date"] = _appeal_deadline_date(rec["created_at"])
    db.determinations[rec["id"]] = rec

    if det_type == "MONETARY":
        db.touch(claim)

    return object_response(serialize(rec), 201)


@bp.route("/ui/determinations/<did>", methods=["GET"])
def get_determination(did):
    p = authenticate()
    require_role(p, {"ProgramAdmin", "Adjudicator", "Claimant", "Employer"})
    rec = db.determinations.get(did)
    if not rec:
        raise err("ERR_NOT_FOUND", "Determination not found.")
    return object_response(serialize(rec))


@bp.route("/ui/claims/<cid>/determinations", methods=["GET"])
def list_claim_determinations(cid):
    p = authenticate()
    require_role(p, {"ProgramAdmin", "Adjudicator", "Claimant"})
    if cid not in db.claims:
        raise err("ERR_NOT_FOUND", "Claim not found.")
    items = [d for d in db.determinations.values() if d["claim_id"] == cid]
    page, limit, offset, total = paginate(items)
    return array_response([serialize(r) for r in page], limit, offset, total)
