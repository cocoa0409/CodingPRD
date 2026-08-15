"""Deal lifecycle routes (PRD §3.1, §3.4, §3.10)."""

from datetime import timedelta

from flask import Blueprint, request

import db
from errors import ApiError
from middleware import bump, require_role
from response import created, ok, ok_list
from routes.common import (body, opt_enum, req_dt, req_enum, req_int, req_str)
from services import domain

bp = Blueprint("deals", __name__)

ALL_ROLES = ("AcquisitionsAnalyst", "UnderwritingCommittee", "DueDiligenceOfficer",
             "CapitalMarketsOfficer", "EscrowOfficer", "AssetManager", "PlatformAdmin")

DEAL_TYPES = {"SINGLE_TENANT", "MULTI_TENANT", "SALE_LEASEBACK", "PORTFOLIO"}
SOURCING_CHANNELS = {"BROKER", "OFF_MARKET", "AUCTION", "DIRECT"}


@bp.route("/acquisition-deals/deals", methods=["POST"])
def create_deal():
    require_role("AcquisitionsAnalyst")
    data = body()
    deal_name = req_str(data, "deal_name")
    deal_type = req_enum(data, "deal_type", DEAL_TYPES)
    sourcing_channel = opt_enum(data, "sourcing_channel", SOURCING_CHANNELS, "BROKER")
    target_close_date = req_dt(data, "target_close_date")
    earnest = req_int(data, "earnest_money_cents")
    price = req_int(data, "purchase_price_cents")
    # target_close_date must fall at least 30 days after the creation date.
    earliest = db.clock_now() + timedelta(days=30)
    if db.parse_dt(target_close_date) < earliest:
        raise ApiError("ERR_FIELD_CONSTRAINT_VIOLATION",
                       "target_close_date must be at least 30 days after deal creation", 400)
    deal = db.make_record({
        "deal_name": deal_name,
        "deal_type": deal_type,
        "sourcing_channel": sourcing_channel,
        "target_close_date": target_close_date,
        "earnest_money_cents": earnest,
        "purchase_price_cents": price,
        "posture": "SOURCING",
        "dd_period_end": None,
        "financing_contingency_end": None,
        "earnest_money_released": False,
        "pinned_underwriting_model_id": None,
        "closing_statement_id": None,
        "status": "SOURCING",
    })
    db.stores["deals"][deal["id"]] = deal
    return created(db.pub(deal))


@bp.route("/acquisition-deals/deals", methods=["GET"])
def list_deals():
    require_role(*ALL_ROLES)
    items = list(db.stores["deals"].values())
    for param in ("status", "posture", "pinned_underwriting_model_id", "closing_statement_id"):
        v = request.args.get(param)
        if v is not None:
            items = [d for d in items if str(d.get(param)) == v]
    return ok_list(items)


@bp.route("/acquisition-deals/deals/<deal_id>", methods=["GET"])
def get_deal(deal_id):
    require_role(*ALL_ROLES)
    return ok(db.pub(domain.get_deal(deal_id)))


@bp.route("/acquisition-deals/deals/<deal_id>/submit-for-psa", methods=["POST"])
def submit_for_psa(deal_id):
    require_role("AcquisitionsAnalyst")
    deal = domain.get_deal(deal_id)
    if deal["status"] != "SOURCING":
        raise ApiError("ERR_DEAL_INVALID_STATE",
                       "Deal must be in SOURCING to submit for PSA", 409)
    if not domain.properties_of(deal["id"]):
        raise ApiError("ERR_DEAL_NO_PROPERTY",
                       "submit-for-psa requires at least one property", 422)
    if domain.latest_approved_model(deal["id"]) is None:
        raise ApiError("ERR_NO_APPROVED_UNDERWRITING",
                       "submit-for-psa requires an APPROVED underwriting model", 422)
    deal["status"] = "PSA_PENDING"
    bump(deal)
    domain.recompute_posture(deal)  # -> UNDER_REVIEW
    return ok(db.pub(deal))


@bp.route("/acquisition-deals/deals/<deal_id>/certify-clear-to-close", methods=["POST"])
def certify_clear_to_close(deal_id):
    require_role("UnderwritingCommittee")
    deal = domain.get_deal(deal_id)
    if deal["status"] not in ("PSA_EXECUTED", "DUE_DILIGENCE"):
        raise ApiError("ERR_DEAL_INVALID_STATE",
                       "Deal must be under diligence to certify clear-to-close", 409)
    # Seven gates in pinned sub-order (validation priority 23).
    for m in domain.milestones_of(deal["id"]):
        if m["status"] not in ("SATISFIED", "WAIVED"):
            raise ApiError("ERR_MILESTONES_OUTSTANDING",
                           f"Milestone {m['milestone_type']} is not satisfied or waived", 422)
    for ex in domain.exceptions_of_deal(deal["id"]):
        if ex["severity"] == "FATAL" and ex["status"] in ("OPEN", "CURE_PROPOSED"):
            raise ApiError("ERR_FATAL_TITLE_EXCEPTION",
                           "An unresolved FATAL title exception blocks certification", 422)
    for ea in domain.eas_of(deal["id"]):
        if ea["status"] not in ("CLEARED", "CONDITIONAL"):
            raise ApiError("ERR_ENVIRONMENTAL_UNRESOLVED",
                           "An environmental assessment is not cleared or conditional", 422)
    for e in _latest_per_lease(domain.estoppels_of(deal["id"])):
        if e["status"] != "CERTIFIED":
            raise ApiError("ERR_ESTOPPEL_INCOMPLETE",
                           "A required estoppel certificate is not CERTIFIED", 422)
    for s in _latest_per_lease(domain.sndas_of(deal["id"])):
        if s["status"] != "CERTIFIED":
            raise ApiError("ERR_SNDA_INCOMPLETE",
                           "A required SNDA is not CERTIFIED", 422)
    psa = domain.active_psa(deal["id"])
    if psa is not None and psa["financing_contingency_days"] > 0:
        fin = domain.latest_committed_financing(deal["id"])
        ok_fin = False
        if fin is not None and fin.get("committed_at") and deal.get("financing_contingency_end"):
            ok_fin = db.parse_dt(fin["committed_at"]) <= db.parse_dt(deal["financing_contingency_end"])
        if not ok_fin:
            raise ApiError("ERR_FINANCING_NOT_COMMITTED",
                           "Financing is required but no application is COMMITTED in window", 422)
    latest = domain.latest_approved_model(deal["id"])
    if latest is None or deal.get("pinned_underwriting_model_id") != latest["id"]:
        raise ApiError("ERR_STALE_UNDERWRITING_MODEL",
                       "Pinned underwriting model is no longer the latest APPROVED model", 422)
    deal["status"] = "CLEAR_TO_CLOSE"
    deal["posture"] = "CLEAR_TO_CLOSE"
    # Issue the provisional closing statement in DRAFT (PRD §3.10).
    existing = domain.statements_of(deal["id"])
    stmt = db.make_record({
        "deal_id": deal["id"],
        "statement_version": (max((s["statement_version"] for s in existing), default=0) + 1),
        "closing_date": None,
        "total_prorations_cents": 0,
        "cash_to_close_cents": 0,
        "provisional": True,
        "status": "DRAFT",
        "_issued_by": None,
        "_proration_inputs": None,
    })
    db.stores["statements"][stmt["id"]] = stmt
    deal["closing_statement_id"] = stmt["id"]
    bump(deal)
    return ok(db.pub(deal))


def _latest_per_lease(records):
    latest = {}
    for r in records:
        cur = latest.get(r["lease_id"])
        if cur is None or r["_seq"] > cur["_seq"]:
            latest[r["lease_id"]] = r
    return latest.values()


@bp.route("/acquisition-deals/deals/<deal_id>/close", methods=["POST"])
def close_deal(deal_id):
    require_role("EscrowOfficer")
    deal = domain.get_deal(deal_id)
    if deal.get("posture") != "CLEAR_TO_CLOSE":
        raise ApiError("ERR_NOT_CLEAR_TO_CLOSE",
                       "close requires deal posture CLEAR_TO_CLOSE", 422)
    stmt = db.stores["statements"].get(deal.get("closing_statement_id") or "")
    if stmt is None or stmt["status"] != "ACKNOWLEDGED":
        raise ApiError("ERR_CLOSING_STATEMENT_NOT_ACKNOWLEDGED",
                       "close requires the closing statement to be ISSUED and ACKNOWLEDGED", 422)
    deal["status"] = "CLOSED"
    deal["posture"] = "CLOSED"
    deal["earnest_money_released"] = True
    bump(deal)
    psa = domain.active_psa(deal["id"])
    if psa is not None and psa["status"] in ("EXECUTED", "AMENDED"):
        psa["status"] = "CLOSED"
        bump(psa)
    return ok(db.pub(deal))


@bp.route("/acquisition-deals/deals/<deal_id>/terminate", methods=["POST"])
def terminate_deal(deal_id):
    require_role("AcquisitionsAnalyst")
    deal = domain.get_deal(deal_id)
    if deal["status"] not in ("PSA_EXECUTED", "DUE_DILIGENCE", "CLEAR_TO_CLOSE"):
        raise ApiError("ERR_DEAL_INVALID_STATE",
                       "terminate is available from PSA_EXECUTED, DUE_DILIGENCE or CLEAR_TO_CLOSE", 409)
    data = body()
    termination_reason = req_str(data, "termination_reason")
    deal["status"] = "TERMINATED"
    deal["posture"] = "TERMINATED"
    if termination_reason == "BUYER_DEFAULT":
        deal["earnest_money_released"] = True  # forfeit to seller
    bump(deal)
    for psa in domain.psas_of(deal["id"]):
        if psa["status"] in ("DRAFT", "EXECUTED", "AMENDED"):
            psa["status"] = "TERMINATED"
            bump(psa)
    for m in domain.milestones_of(deal["id"]):
        if m["status"] in ("PENDING", "IN_PROGRESS"):
            m["status"] = "WAIVED"
            m["waived"] = True
            bump(m)
    for f in domain.financing_of(deal["id"]):
        if f["status"] in ("DRAFT", "SUBMITTED"):
            f["status"] = "WITHDRAWN"
            bump(f)
    return ok(db.pub(deal))
