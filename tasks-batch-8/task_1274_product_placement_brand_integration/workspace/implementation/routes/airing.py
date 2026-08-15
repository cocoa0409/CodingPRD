"""AiringReport / MakeGoodCredit endpoints."""
from flask import Blueprint

import db
import errors
import middleware
import response
import util
from services import calc, cascade

bp = Blueprint("airing", __name__)


def report_view(r):
    return {k: r[k] for k in ("id", "episode_id", "contract_id",
                              "measured_segments_seconds", "measured_verbal_mentions",
                              "measured_seconds", "measured_value_cents",
                              "filed_by_user_id", "status",
                              "created_at", "updated_at", "version")}


def credit_view(c):
    return {k: c[k] for k in ("id", "contract_id", "amount_cents", "reason", "status",
                              "created_at", "updated_at", "version")}


@bp.route("/episodes/<eid>/airing-reports", methods=["POST"])
def file_report(eid):
    user_id, _ = middleware.require_roles("VerificationAnalyst")
    body = middleware.get_json_body()
    contract_id = body.get("contract_id")
    if not isinstance(contract_id, str):
        raise errors.invalid_request("Field 'contract_id' is required and must be a string")
    segments = util.req_segment_list(body, "measured_segments_seconds")
    verbal = util.req_int(body, "measured_verbal_mentions", minimum=0)
    e = db.episodes.get(eid)
    if e is None:
        raise errors.not_found("Episode not found")
    c = db.contracts.get(contract_id)
    if c is None:
        raise errors.not_found("Contract not found")
    if c["episode_id"] != eid:
        raise errors.not_found("Contract does not belong to this episode")
    if e["status"] not in ("AIRED", "VERIFIED"):
        raise errors.ApiError(errors.ERR_EPISODE_NOT_AIRED, 409,
                              "Airing report filing requires episode status AIRED or VERIFIED")
    if c["status"] == "TERMINATED":
        raise errors.already_terminal("Contract is TERMINATED")
    if c["status"] != "ACTIVE":
        raise errors.invalid_state("Contract is not ACTIVE")
    measured_seconds, measured_value = calc.measured_exposure(segments)
    ent = util.new_entity()
    ent.update({"episode_id": eid, "contract_id": contract_id,
                "measured_segments_seconds": segments,
                "measured_verbal_mentions": verbal,
                "measured_seconds": measured_seconds,
                "measured_value_cents": measured_value,
                "filed_by_user_id": user_id, "status": "FILED"})
    db.airing_reports[ent["id"]] = ent
    c["status"] = "UNDER_VERIFICATION"
    util.touch(c)
    return response.success_object(report_view(ent), 201)


@bp.route("/episodes/<eid>/airing-reports", methods=["GET"])
def list_episode_reports(eid):
    middleware.require_roles("AgencyAdmin", "IntegrationManager", "BrandRep",
                             "ProductionRep", "NetworkStandardsReviewer",
                             "VerificationAnalyst")
    e = db.episodes.get(eid)
    if e is None:
        raise errors.not_found("Episode not found")
    limit, offset = util.pagination_params()
    items = [x for x in db.airing_reports.values() if x["episode_id"] == eid]
    items = util.sort_created(util.status_filter(items))
    page, total = util.paginate(items, limit, offset)
    return response.success_list([report_view(x) for x in page], limit, offset, total)


@bp.route("/contracts/<cid>/airing-reports", methods=["GET"])
def list_contract_reports(cid):
    middleware.require_roles("AgencyAdmin", "IntegrationManager", "BrandRep",
                             "ProductionRep", "NetworkStandardsReviewer",
                             "VerificationAnalyst")
    c = db.contracts.get(cid)
    if c is None:
        raise errors.not_found("Contract not found")
    limit, offset = util.pagination_params()
    items = [x for x in db.airing_reports.values() if x["contract_id"] == cid]
    items = util.sort_created(util.status_filter(items))
    page, total = util.paginate(items, limit, offset)
    return response.success_list([report_view(x) for x in page], limit, offset, total)


@bp.route("/airing-reports/<rid>/verify", methods=["POST"])
def verify_report(rid):
    user_id, _ = middleware.require_roles("VerificationAnalyst")
    middleware.get_json_body(required=False)
    r = db.airing_reports.get(rid)
    if r is None:
        raise errors.not_found("Airing report not found")
    if r["status"] not in ("FILED", "RE_MEASURED"):
        raise errors.invalid_state("Report is not FILED or RE_MEASURED")
    if user_id == r["filed_by_user_id"]:
        raise errors.segregation_of_duties("Verifier must differ from the report filer")
    c = db.contracts.get(r["contract_id"])
    acknowledged = any(
        d["contract_id"] == r["contract_id"] and d["status"] == "ACKNOWLEDGED"
        for d in db.disclosures.values())
    if not acknowledged:
        raise errors.disclosure_not_acknowledged()
    r["status"] = "VERIFIED"
    util.touch(r)
    if c is not None and c["status"] == "UNDER_VERIFICATION":
        bonus = calc.compute_bonus(c["base_fee_cents"], c["guaranteed_seconds"],
                                   c["rate_cents_per_second"], r["measured_seconds"])
        c["bonus_cents"] = bonus
        amount, reason = calc.compute_makegood(c, r["measured_seconds"],
                                               r["measured_verbal_mentions"])
        if amount == 0:
            c["status"] = "SETTLED"
            c["outstanding_balance_cents"] = c["base_fee_cents"] + bonus
            c["final_settlement_cents"] = c["base_fee_cents"] + bonus
        else:
            credit = util.new_entity()
            credit.update({"contract_id": c["id"], "amount_cents": amount,
                           "reason": reason, "status": "PENDING"})
            db.makegood_credits[credit["id"]] = credit
            c["status"] = "MAKEGOOD_REQUIRED"
            # cascade link 2: bump cross-promo owed
            for obl in db.cross_promos.values():
                if obl["contract_id"] == c["id"]:
                    obl["owed_count"] += calc.MAKEGOOD_PROMO_PENALTY
                    if obl["status"] == "FULFILLED":
                        obl["status"] = "PARTIALLY_FULFILLED"
                    util.touch(obl)
                    break
            c["makegood_total_cents"] = sum(
                x["amount_cents"] for x in db.makegood_credits.values()
                if x["contract_id"] == c["id"] and x["status"] == "PENDING")
            c["outstanding_balance_cents"] = (
                c["base_fee_cents"] + bonus - c["makegood_total_cents"])
        util.touch(c)
        cascade.evaluate_episode_bubbleup(c["episode_id"])
    return response.success_object(report_view(r))


@bp.route("/airing-reports/<rid>/dispute", methods=["POST"])
def dispute_report(rid):
    user_id, _ = middleware.require_roles("BrandRep")
    middleware.get_json_body(required=False)
    r = db.airing_reports.get(rid)
    if r is None:
        raise errors.not_found("Airing report not found")
    c = db.contracts.get(r["contract_id"])
    brand = cascade.contract_brand(c) if c is not None else None
    if brand is None or user_id != brand["id"]:
        raise errors.forbidden_ownership(
            "BrandRep may only dispute reports on their own brand's contracts")
    if r["status"] != "VERIFIED":
        raise errors.invalid_state("Report is not VERIFIED")
    r["status"] = "DISPUTED"
    util.touch(r)
    if c is not None and c["status"] == "SETTLED":
        c["status"] = "UNDER_VERIFICATION"
        c["final_settlement_cents"] = None
        c["outstanding_balance_cents"] = c["base_fee_cents"]
        c["bonus_cents"] = 0
        util.touch(c)
    return response.success_object(report_view(r))


@bp.route("/airing-reports/<rid>/remeasure", methods=["POST"])
def remeasure_report(rid):
    middleware.require_roles("VerificationAnalyst")
    body = middleware.get_json_body()
    segments = util.req_segment_list(body, "measured_segments_seconds")
    verbal = util.req_int(body, "measured_verbal_mentions", minimum=0)
    r = db.airing_reports.get(rid)
    if r is None:
        raise errors.not_found("Airing report not found")
    if r["status"] != "DISPUTED":
        raise errors.invalid_state("Report is not DISPUTED")
    r["measured_segments_seconds"] = segments
    r["measured_verbal_mentions"] = verbal
    measured_seconds, measured_value = calc.measured_exposure(segments)
    r["measured_seconds"] = measured_seconds
    r["measured_value_cents"] = measured_value
    r["status"] = "RE_MEASURED"
    util.touch(r)
    return response.success_object(report_view(r))


@bp.route("/contracts/<cid>/makegood-credits", methods=["GET"])
def list_makegood_credits(cid):
    middleware.require_roles("AgencyAdmin", "IntegrationManager", "BrandRep",
                             "VerificationAnalyst")
    c = db.contracts.get(cid)
    if c is None:
        raise errors.not_found("Contract not found")
    limit, offset = util.pagination_params()
    items = [x for x in db.makegood_credits.values() if x["contract_id"] == cid]
    items = util.sort_created(util.status_filter(items))
    page, total = util.paginate(items, limit, offset)
    return response.success_list([credit_view(x) for x in page], limit, offset, total)


@bp.route("/makegood-credits/<mid>/waive", methods=["POST"])
def waive_credit(mid):
    middleware.require_roles("IntegrationManager")
    middleware.get_json_body(required=False)
    m = db.makegood_credits.get(mid)
    if m is None:
        raise errors.not_found("MakeGoodCredit not found")
    if m["status"] == "WAIVED":
        raise errors.already_terminal("MakeGoodCredit is WAIVED")
    if m["status"] != "PENDING":
        raise errors.invalid_state("MakeGoodCredit is not PENDING")
    m["status"] = "WAIVED"
    util.touch(m)
    c = db.contracts.get(m["contract_id"])
    if c is not None:
        c["outstanding_balance_cents"] += m["amount_cents"]
        c["makegood_total_cents"] -= m["amount_cents"]
        pending_left = any(
            x["contract_id"] == c["id"] and x["status"] == "PENDING"
            for x in db.makegood_credits.values())
        if not pending_left and c["status"] == "MAKEGOOD_REQUIRED":
            c["status"] = "SETTLED"
            c["final_settlement_cents"] = c["base_fee_cents"] + c["bonus_cents"]
        util.touch(c)
        cascade.evaluate_episode_bubbleup(c["episode_id"])
    return response.success_object(credit_view(m))
