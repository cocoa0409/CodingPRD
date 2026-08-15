"""Purchase agreement routes (PRD §3.4) — execute pins the underwriting
model, computes the diligence clock, and auto-creates the eight milestones;
amend is OCC-guarded and cascades LTV-invalidated financing to WITHDRAWN."""

from datetime import timedelta

from flask import Blueprint

import db
from errors import ApiError
from middleware import bump, require_role
from response import created, ok, ok_list
from routes.common import body, req_int
from services import domain

bp = Blueprint("psas", __name__)

ALL_ROLES = ("AcquisitionsAnalyst", "UnderwritingCommittee", "DueDiligenceOfficer",
             "CapitalMarketsOfficer", "EscrowOfficer", "AssetManager", "PlatformAdmin")


def _earnest_sufficient(earnest_money_cents, psa_price_cents):
    # earnest >= 1% of price, boundary inclusive, integer math.
    return earnest_money_cents * 100 >= domain.EARNEST_MIN_PCT * psa_price_cents


@bp.route("/acquisition-deals/deals/<deal_id>/purchase-agreements", methods=["POST"])
def create_psa(deal_id):
    require_role("AcquisitionsAnalyst")
    deal = domain.get_deal(deal_id)
    if deal["status"] != "PSA_PENDING":
        raise ApiError("ERR_DEAL_INVALID_STATE",
                       "A PSA can be drafted only while the deal is PSA_PENDING", 409)
    data = body()
    psa_price = req_int(data, "psa_price_cents")
    earnest = req_int(data, "earnest_money_cents")
    dd_days = req_int(data, "dd_period_days")
    if dd_days < domain.DD_PERIOD_MIN or dd_days > domain.DD_PERIOD_MAX:
        raise ApiError("ERR_FIELD_CONSTRAINT_VIOLATION",
                       "dd_period_days must be within [15, 120]", 400)
    fc_days = req_int(data, "financing_contingency_days")
    if fc_days < 0 or fc_days > dd_days + domain.FINANCING_CONTINGENCY_SLACK:
        raise ApiError("ERR_FIELD_CONSTRAINT_VIOLATION",
                       "financing_contingency_days must be within [0, dd_period_days + 30]", 400)
    psa = db.make_record({
        "deal_id": deal["id"],
        "psa_price_cents": psa_price,
        "earnest_money_cents": earnest,
        "dd_period_days": dd_days,
        "financing_contingency_days": fc_days,
        "executed_at": None,
        "amendment_count": 0,
        "status": "DRAFT",
    })
    db.stores["psas"][psa["id"]] = psa
    return created(db.pub(psa))


@bp.route("/acquisition-deals/deals/<deal_id>/purchase-agreements", methods=["GET"])
def list_psas(deal_id):
    require_role(*ALL_ROLES)
    deal = domain.get_deal(deal_id)
    return ok_list(domain.psas_of(deal["id"]))


@bp.route("/acquisition-deals/deals/<deal_id>/purchase-agreements/<psa_id>", methods=["GET"])
def get_psa(deal_id, psa_id):
    require_role(*ALL_ROLES)
    deal = domain.get_deal(deal_id)
    return ok(db.pub(domain.get_psa_scoped(deal, psa_id)))


@bp.route("/acquisition-deals/deals/<deal_id>/purchase-agreements/<psa_id>/execute", methods=["POST"])
def execute_psa(deal_id, psa_id):
    require_role("AcquisitionsAnalyst")
    deal = domain.get_deal(deal_id)
    psa = domain.get_psa_scoped(deal, psa_id)
    if psa["status"] != "DRAFT":
        raise ApiError("ERR_PSA_NOT_EXECUTABLE",
                       "PSA must be in DRAFT to execute", 409)
    if deal["status"] != "PSA_PENDING":
        raise ApiError("ERR_DEAL_INVALID_STATE",
                       "Deal must be in PSA_PENDING to execute a PSA", 409)
    if psa["psa_price_cents"] != deal["purchase_price_cents"]:
        raise ApiError("ERR_PRICE_MISMATCH",
                       "psa_price_cents must equal deal.purchase_price_cents at execution", 409)
    if not _earnest_sufficient(psa["earnest_money_cents"], psa["psa_price_cents"]):
        raise ApiError("ERR_EARNEST_MONEY_INSUFFICIENT",
                       "earnest_money_cents must be at least 1% of psa_price_cents", 422)
    now = db.clock_now()
    psa["status"] = "EXECUTED"
    psa["executed_at"] = db.render_dt(now)
    bump(psa)
    deal["dd_period_end"] = db.render_dt(now + timedelta(days=psa["dd_period_days"]))
    deal["financing_contingency_end"] = db.render_dt(now + timedelta(days=psa["financing_contingency_days"]))
    # Version pinning: capture the latest APPROVED model at this instant.
    latest = domain.latest_approved_model(deal["id"])
    deal["pinned_underwriting_model_id"] = latest["id"] if latest else None
    deal["status"] = "PSA_EXECUTED"
    deal["posture"] = "DD_OPEN"
    bump(deal)
    # Auto-create the eight diligence milestones in the same atomic step.
    for mtype in domain.MILESTONE_TYPES:
        waived = (mtype == "FINANCING_COMMITMENT" and psa["financing_contingency_days"] == 0)
        milestone = db.make_record({
            "deal_id": deal["id"],
            "milestone_type": mtype,
            "due_date": deal["dd_period_end"],
            "completed_at": None,
            "waived": waived,
            "status": "WAIVED" if waived else "PENDING",
        })
        db.stores["milestones"][milestone["id"]] = milestone
    return ok(db.pub(psa))


@bp.route("/acquisition-deals/deals/<deal_id>/purchase-agreements/<psa_id>/amend", methods=["POST"])
def amend_psa(deal_id, psa_id):
    require_role("AcquisitionsAnalyst")
    deal = domain.get_deal(deal_id)
    psa = domain.get_psa_scoped(deal, psa_id)
    if psa["status"] not in ("EXECUTED", "AMENDED"):
        raise ApiError("ERR_PSA_NOT_EXECUTABLE",
                       "PSA must be in EXECUTED or AMENDED to amend", 409)
    data = body()
    expected = req_int(data, "expected_psa_version")
    if expected != psa["version"]:
        raise ApiError("ERR_STALE_PSA_VERSION",
                       "expected_psa_version does not match the PSA's current version", 412)
    new_price = req_int(data, "psa_price_cents")
    new_earnest = req_int(data, "earnest_money_cents")
    if not _earnest_sufficient(new_earnest, new_price):
        raise ApiError("ERR_EARNEST_MONEY_INSUFFICIENT",
                       "earnest_money_cents must be at least 1% of the new psa_price_cents", 422)
    psa["psa_price_cents"] = new_price
    psa["earnest_money_cents"] = new_earnest
    psa["amendment_count"] += 1
    psa["status"] = "AMENDED"
    bump(psa)
    # Retrade updates the deal price atomically and re-pins the model.
    deal["purchase_price_cents"] = new_price
    latest = domain.latest_approved_model(deal["id"])
    if latest is not None:
        deal["pinned_underwriting_model_id"] = latest["id"]
    bump(deal)
    # LTV cascade: a SUBMITTED application whose loan now exceeds 65% of the
    # new price is withdrawn in the same request.
    for f in domain.financing_of(deal["id"]):
        if f["status"] == "SUBMITTED" and f["loan_amount_cents"] * 100 > domain.MAX_LTV_PCT * new_price:
            f["status"] = "WITHDRAWN"
            bump(f)
    return ok(db.pub(psa))
