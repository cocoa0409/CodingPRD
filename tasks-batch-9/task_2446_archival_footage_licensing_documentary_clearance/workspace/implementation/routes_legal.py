"""Fair-use analyses, opinion letters and the withdrawal cascade."""
from flask import Blueprint, g, request

from calc import (FAIR_USE_ACCEPT_THRESHOLD_SCALED, fair_use_strength_scaled, scaled_to_score)
from core import (ROLE_CLEARANCE_SUPERVISOR, ROLE_LEGAL_COUNSEL, ROLE_PRODUCTION_ADMIN, body,
                  created, db, fail, guard, new_row, ok, ok_list, opt_str, pagination, public,
                  req_enum, req_int, req_str, touch)
from domain import (analyses_of_asset, cascade_blocked_posture, get_analysis, get_asset,
                    get_letter, get_production, letters_of_analysis, recompute_production,
                    rollup_asset)

bp = Blueprint("legal", __name__)

ANALYSIS_STATUSES = ("DRAFT", "SUBMITTED", "ACCEPTED", "REJECTED")
LETTER_STATUSES = ("DRAFT", "ISSUED", "WITHDRAWN")
RISK_RATINGS = ("LOW", "MODERATE", "HIGH")
VARIANT_FOR_PURPOSE = {
    "CRITICAL_COMMENTARY": "TRANSFORMATIVE_WEIGHTED",
    "ILLUSTRATIVE_BACKGROUND": "MARKET_HARM_WEIGHTED",
}
WITHDRAWAL_RATIONALE = "AUTO: supporting opinion letter withdrawn"


@bp.post("/assets/<aid>/fair-use-analyses")
@guard(ROLE_LEGAL_COUNSEL)
def create_analysis(aid):
    asset = get_asset(aid)
    data = body()
    scores = {}
    for key in ("transformative_score", "nature_score", "amount_used_score",
                "market_harm_score"):
        scores[key] = req_int(data, key, minimum=0, maximum=100)

    production = get_production(asset["production_id"])
    if production["status"] not in ("DEVELOPMENT", "CLEARANCE"):
        fail("ERR_PRODUCTION_NOT_IN_CLEARANCE",
             "A %s production accepts no new fair-use analyses." % production["status"])

    variant = VARIANT_FOR_PURPOSE[asset["usage_purpose"]]
    scaled = fair_use_strength_scaled(variant, scores["transformative_score"],
                                      scores["nature_score"], scores["amount_used_score"],
                                      scores["market_harm_score"])
    row = new_row()
    row.update({
        "asset_id": aid,
        "transformative_score": scores["transformative_score"],
        "nature_score": scores["nature_score"],
        "amount_used_score": scores["amount_used_score"],
        "market_harm_score": scores["market_harm_score"],
        "weighting_variant": variant,
        "strength_score": scaled_to_score(scaled),
        "status": "DRAFT",
        "decision_rationale": None,
        "_strength_scaled": scaled,
    })
    db.fair_use_analyses[row["id"]] = row
    return created(public(row))


@bp.get("/fair-use-analyses/<fid>")
@guard(ROLE_LEGAL_COUNSEL, ROLE_CLEARANCE_SUPERVISOR, ROLE_PRODUCTION_ADMIN)
def read_analysis(fid):
    return ok(public(get_analysis(fid)))


@bp.get("/assets/<aid>/fair-use-analyses")
@guard(ROLE_LEGAL_COUNSEL, ROLE_CLEARANCE_SUPERVISOR, ROLE_PRODUCTION_ADMIN)
def list_analyses(aid):
    get_asset(aid)
    limit, offset = pagination()
    rows = analyses_of_asset(aid)
    status = request.args.get("status")
    if status:
        rows = [r for r in rows if r["status"] == status]
    return ok_list([public(r) for r in rows], limit, offset)


@bp.post("/fair-use-analyses/<fid>/state")
@guard(ROLE_LEGAL_COUNSEL, ROLE_CLEARANCE_SUPERVISOR)
def analysis_state(fid):
    analysis = get_analysis(fid)
    data = body()
    to_status = req_enum(data, "to_status", ANALYSIS_STATUSES)
    rationale = opt_str(data, "decision_rationale")

    asset = get_asset(analysis["asset_id"])
    production = get_production(asset["production_id"])
    current = analysis["status"]
    allowed = {("DRAFT", "SUBMITTED"), ("SUBMITTED", "ACCEPTED"), ("SUBMITTED", "REJECTED"),
               ("REJECTED", "DRAFT")}
    if (current, to_status) not in allowed:
        fail("ERR_INVALID_STATE_TRANSITION",
             "A fair-use analysis in %s cannot move to %s." % (current, to_status))

    if to_status == "ACCEPTED":
        # rung 22 is consulted before rung 42
        if not any(l["status"] == "ISSUED" for l in letters_of_analysis(fid)):
            fail("ERR_NO_ISSUED_OPINION_LETTER",
                 "An analysis needs at least one ISSUED opinion letter before acceptance.")
        if analysis["_strength_scaled"] < FAIR_USE_ACCEPT_THRESHOLD_SCALED:
            fail("ERR_FAIR_USE_SCORE_INSUFFICIENT",
                 "strength_score %s is below the 0.6000 acceptance threshold."
                 % analysis["strength_score"])

    analysis["status"] = to_status
    if to_status in ("ACCEPTED", "REJECTED"):
        analysis["decision_rationale"] = rationale
    touch(analysis)

    changed = rollup_asset(asset)
    recompute_production(production)
    if changed:
        touch(production)
    return ok(public(analysis))


# --- opinion letters --------------------------------------------------------
@bp.post("/fair-use-analyses/<fid>/opinion-letters")
@guard(ROLE_LEGAL_COUNSEL)
def create_letter(fid):
    get_analysis(fid)
    data = body()
    row = new_row()
    row.update({
        "fair_use_analysis_id": fid,
        "counsel_firm": req_str(data, "counsel_firm"),
        "letter_reference": req_str(data, "letter_reference"),
        "risk_rating": req_enum(data, "risk_rating", RISK_RATINGS),
        "issued_by_user_id": g.user_id,
        "status": "DRAFT",
        "withdrawal_reason": None,
    })
    db.opinion_letters[row["id"]] = row
    return created(public(row))


@bp.get("/fair-use-analyses/<fid>/opinion-letters")
@guard(ROLE_LEGAL_COUNSEL, ROLE_CLEARANCE_SUPERVISOR, ROLE_PRODUCTION_ADMIN)
def list_letters(fid):
    get_analysis(fid)
    limit, offset = pagination()
    rows = letters_of_analysis(fid)
    status = request.args.get("status")
    if status:
        rows = [r for r in rows if r["status"] == status]
    return ok_list([public(r) for r in rows], limit, offset)


@bp.post("/opinion-letters/<oid>/state")
@guard(ROLE_LEGAL_COUNSEL)
def letter_state(oid):
    letter = get_letter(oid)
    data = body()
    to_status = req_enum(data, "to_status", LETTER_STATUSES)
    reason = opt_str(data, "withdrawal_reason")

    analysis = get_analysis(letter["fair_use_analysis_id"])
    current = letter["status"]
    if (current, to_status) == ("DRAFT", "ISSUED"):
        if analysis["status"] != "SUBMITTED":
            fail("ERR_INVALID_STATE_TRANSITION",
                 "A letter may only be issued against a SUBMITTED analysis.")
        letter["status"] = "ISSUED"
        touch(letter)
        return ok(public(letter))

    if (current, to_status) != ("ISSUED", "WITHDRAWN"):
        fail("ERR_INVALID_STATE_TRANSITION",
             "An opinion letter in %s cannot move to %s." % (current, to_status))

    letter["status"] = "WITHDRAWN"
    letter["withdrawal_reason"] = reason
    touch(letter)

    # hop 1 — the analysis loses its last supporting letter
    remaining = [l for l in letters_of_analysis(analysis["id"]) if l["status"] == "ISSUED"]
    if remaining or analysis["status"] != "ACCEPTED":
        return ok(public(letter))

    analysis["status"] = "REJECTED"
    analysis["decision_rationale"] = WITHDRAWAL_RATIONALE
    touch(analysis)

    # hops 2 & 3 — the asset re-rolls, the production's counters and posture follow
    asset = get_asset(analysis["asset_id"])
    production = get_production(asset["production_id"])
    rollup_asset(asset)
    recompute_production(production)

    # hops 4 & 5 — delivered packages and bound cover
    cascade_blocked_posture(
        production, "AUTO: production posture BLOCKED after opinion letter withdrawal")
    touch(production)
    return ok(public(letter))
