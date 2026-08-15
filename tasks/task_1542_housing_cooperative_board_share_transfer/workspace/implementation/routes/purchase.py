"""Purchase applications and interviews (PRD §3.5 / §3.6)."""
from flask import request

import domain as D
from db import STORE
from errors import (
    ApiError,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_ALREADY_TERMINAL,
    ERR_STALE_COOP_VERSION,
    ERR_NOT_RESOURCE_OWNER,
    ERR_TEMPORAL_CONFLICT,
    ERR_CROSS_ENTITY_VIOLATION,
    ERR_BUSINESS_CONSTRAINT,
    ERR_SEPARATION_OF_DUTIES,
)
from middleware import ctx, require_role, ALL_ROLES
from response import ok
from util import get_body, req_str, req_int, req_enum, req_dt, req_str_array
from routes.core import bp, list_response

READ_ALL = list(ALL_ROLES)
READ_BOARD = ["PlatformAdmin", "BoardOfficer", "BoardMember", "ManagingAgent"]


def _get_app(cid, paid):
    D.get_coop(cid)
    return D.get_scoped("purchase_applications", paid, cid, "PurchaseApplication")


def _check_seller(app, uid):
    if uid != app["seller_shareholder_id"]:
        raise ApiError(ERR_NOT_RESOURCE_OWNER, "Caller is not the selling shareholder", 403)


def _check_not_terminal(app):
    if app["application_status"] in D.APP_TERMINAL:
        raise ApiError(
            ERR_ALREADY_TERMINAL,
            "Application is in terminal state %s" % app["application_status"],
            409,
        )


# ---------------------------------------------------------------------------
# Purchase applications
# ---------------------------------------------------------------------------

@bp.post("/cooperatives/<cid>/purchase-applications")
def create_purchase_application(cid):
    uid, role = ctx()
    require_role(role, ["Shareholder"])
    coop = D.get_coop(cid)
    body = get_body()
    unit_id = req_str(body, "unit_id")
    seller_id = req_str(body, "seller_shareholder_id")
    buyer_full_name = req_str(body, "buyer_full_name")
    buyer_email = req_str(body, "buyer_email")
    gross = req_int(body, "gross_sale_price_cents")
    financing = req_int(body, "financing_percent_bps")
    dti = req_int(body, "debt_to_income_bps")
    liquidity = req_int(body, "post_closing_liquidity_cents")
    if uid != seller_id:
        raise ApiError(ERR_NOT_RESOURCE_OWNER, "X-User-ID must equal seller_shareholder_id", 403)
    unit = STORE["units"].get(unit_id)
    if unit is None or unit["cooperative_id"] != cid:
        raise ApiError(ERR_CROSS_ENTITY_VIOLATION, "Referenced unit does not exist", 422)
    seller = STORE["shareholders"].get(seller_id)
    if seller is None or seller["cooperative_id"] != cid:
        raise ApiError(ERR_CROSS_ENTITY_VIOLATION, "Referenced seller does not exist", 422)
    if gross <= 0:
        raise ApiError(ERR_INVALID_REQUEST, "gross_sale_price_cents must be positive", 400)
    app = D.make(
        "purchase_applications", coop,
        cooperative_id=cid,
        unit_id=unit_id,
        seller_shareholder_id=seller_id,
        buyer_full_name=buyer_full_name,
        buyer_email=buyer_email,
        gross_sale_price_cents=gross,
        financing_percent_bps=financing,
        application_status="DRAFT",
        flip_tax_cents=None,
        debt_to_income_bps=dti,
        post_closing_liquidity_cents=liquidity,
        submitted_at=None,
        deciding_resolution_id=None,
        transferred_at=None,
        _certified_by=None,
    )
    return ok(D.ser(app), 201)


@bp.get("/cooperatives/<cid>/purchase-applications")
def list_purchase_applications(cid):
    uid, role = ctx()
    require_role(role, READ_ALL)
    D.get_coop(cid)
    return list_response("purchase_applications", cid, [
        ("unit_id", request.args.get("unit_id"), False),
        ("seller_shareholder_id", request.args.get("seller_shareholder_id"), False),
        ("application_status", request.args.get("application_status"), False),
    ])


@bp.get("/cooperatives/<cid>/purchase-applications/<paid>")
def get_purchase_application(cid, paid):
    uid, role = ctx()
    require_role(role, READ_ALL)
    app = _get_app(cid, paid)
    return ok(D.ser(app))


@bp.post("/cooperatives/<cid>/purchase-applications/<paid>/submit")
def submit_application(cid, paid):
    uid, role = ctx()
    require_role(role, ["Shareholder"])
    coop = D.get_coop(cid)
    app = D.get_scoped("purchase_applications", paid, cid, "PurchaseApplication")
    _check_seller(app, uid)
    _check_not_terminal(app)
    if app["application_status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, "Application is not DRAFT", 409)
    seller = STORE["shareholders"].get(app["seller_shareholder_id"])
    if seller is None or seller["standing"] != "GOOD_STANDING":
        raise ApiError(ERR_CROSS_ENTITY_VIOLATION, "Seller is not in GOOD_STANDING", 422)
    dup = any(
        a for a in STORE["purchase_applications"].values()
        if a["cooperative_id"] == cid
        and a["unit_id"] == app["unit_id"]
        and a["id"] != app["id"]
        and a["application_status"] in D.APP_IN_FLIGHT
    )
    if dup:
        raise ApiError(
            ERR_BUSINESS_CONSTRAINT,
            "Another purchase application for this unit is already in flight",
            422,
        )
    if app["financing_percent_bps"] > D.FINANCING_CAP_BPS:
        raise ApiError(ERR_BUSINESS_CONSTRAINT, "financing_percent_bps exceeds the 8000 bps cap", 422)
    if app["gross_sale_price_cents"] <= 0:
        raise ApiError(ERR_INVALID_REQUEST, "gross_sale_price_cents must be positive", 400)
    app["application_status"] = "SUBMITTED"
    app["submitted_at"] = coop["current_utc"]
    D.touch(app, coop)
    return ok(D.ser(app))


@bp.post("/cooperatives/<cid>/purchase-applications/<paid>/certify")
def certify_application(cid, paid):
    uid, role = ctx()
    require_role(role, ["ManagingAgent"])
    coop = D.get_coop(cid)
    app = D.get_scoped("purchase_applications", paid, cid, "PurchaseApplication")
    _check_not_terminal(app)
    if app["application_status"] != "SUBMITTED":
        raise ApiError(ERR_INVALID_STATE, "Application is not SUBMITTED", 409)
    app["application_status"] = "UNDER_REVIEW"
    app["_certified_by"] = uid
    D.touch(app, coop)
    D.bump_coop(coop)
    return ok(D.ser(app))


@bp.post("/cooperatives/<cid>/purchase-applications/<paid>/request-info")
def request_info(cid, paid):
    uid, role = ctx()
    require_role(role, ["BoardOfficer"])
    coop = D.get_coop(cid)
    app = D.get_scoped("purchase_applications", paid, cid, "PurchaseApplication")
    _check_not_terminal(app)
    if app["application_status"] != "UNDER_REVIEW":
        raise ApiError(ERR_INVALID_STATE, "Application is not UNDER_REVIEW", 409)
    app["application_status"] = "INFO_REQUESTED"
    D.touch(app, coop)
    return ok(D.ser(app))


@bp.post("/cooperatives/<cid>/purchase-applications/<paid>/submit-info")
def submit_info(cid, paid):
    uid, role = ctx()
    require_role(role, ["Shareholder"])
    coop = D.get_coop(cid)
    app = D.get_scoped("purchase_applications", paid, cid, "PurchaseApplication")
    _check_seller(app, uid)
    _check_not_terminal(app)
    if app["application_status"] != "INFO_REQUESTED":
        raise ApiError(ERR_INVALID_STATE, "Application is not INFO_REQUESTED", 409)
    app["application_status"] = "UNDER_REVIEW"
    D.touch(app, coop)
    return ok(D.ser(app))


@bp.post("/cooperatives/<cid>/purchase-applications/<paid>/schedule-interview")
def schedule_interview(cid, paid):
    uid, role = ctx()
    require_role(role, ["BoardOfficer"])
    coop = D.get_coop(cid)
    app = D.get_scoped("purchase_applications", paid, cid, "PurchaseApplication")
    body = get_body()
    scheduled_at = req_dt(body, "scheduled_at")
    panel = req_str_array(body, "panel_member_user_ids")
    _check_not_terminal(app)
    if app["application_status"] != "UNDER_REVIEW":
        raise ApiError(ERR_INVALID_STATE, "Application is not UNDER_REVIEW", 409)
    # Segregation of duties: the certifying managing agent may not sit on the panel.
    if app.get("_certified_by") is not None and app["_certified_by"] in panel:
        raise ApiError(
            ERR_SEPARATION_OF_DUTIES,
            "Panel may not include the ManagingAgent who certified the package",
            422,
        )
    if scheduled_at <= coop["current_utc"]:
        raise ApiError(ERR_TEMPORAL_CONFLICT, "scheduled_at must be in the future", 422)
    if len(set(panel)) < 2:
        raise ApiError(
            ERR_BUSINESS_CONSTRAINT,
            "panel_member_user_ids must contain at least 2 distinct BoardMember ids",
            422,
        )
    iv = D.make(
        "interviews", coop,
        cooperative_id=cid,
        application_id=paid,
        scheduled_at=scheduled_at,
        panel_member_user_ids=list(panel),
        interview_outcome="PENDING",
        interview_status="SCHEDULED",
        completed_at=None,
    )
    app["application_status"] = "INTERVIEW_SCHEDULED"
    D.touch(app, coop)
    return ok(D.ser(iv), 201)


@bp.post("/cooperatives/<cid>/purchase-applications/<paid>/record-transfer")
def record_transfer(cid, paid):
    uid, role = ctx()
    require_role(role, ["BoardOfficer"])
    coop = D.get_coop(cid)
    app = D.get_scoped("purchase_applications", paid, cid, "PurchaseApplication")
    body = get_body()
    expected = req_int(body, "expected_cooperative_version")
    _check_not_terminal(app)
    if app["application_status"] != "APPROVED":
        raise ApiError(ERR_INVALID_STATE, "Application is not APPROVED", 409)
    # OCC guard (§2.8): evaluated after all other checks.
    if expected != coop["version"]:
        raise ApiError(
            ERR_STALE_COOP_VERSION,
            "expected_cooperative_version %s does not match current version %s"
            % (expected, coop["version"]),
            412,
        )
    now = coop["current_utc"]
    unit = STORE["units"].get(app["unit_id"])
    # Flip tax is computed once, against the policy in force at this instant.
    app["flip_tax_cents"] = D.compute_flip_tax(coop, unit, app)
    app["transferred_at"] = now
    app["application_status"] = "TRANSFERRED"
    D.touch(app, coop)
    # Rewrite the share ledger: supersede the seller's ACTIVE entries for the unit.
    for e in STORE["share_ledger_entries"].values():
        if (
            e["cooperative_id"] == cid
            and e["unit_id"] == app["unit_id"]
            and e["entry_status"] == "ACTIVE"
        ):
            e["entry_status"] = "SUPERSEDED"
            D.touch(e, coop)
    # Find or create the buyer shareholder (matched by buyer_email).
    buyer = None
    for s in STORE["shareholders"].values():
        if s["cooperative_id"] == cid and s["email"] == app["buyer_email"]:
            buyer = s
            break
    if buyer is None:
        buyer = D.make(
            "shareholders", coop,
            cooperative_id=cid,
            full_name=app["buyer_full_name"],
            email=app["buyer_email"],
            standing="GOOD_STANDING",
            arrears_balance_cents=0,
        )
    D.make(
        "share_ledger_entries", coop,
        cooperative_id=cid,
        unit_id=app["unit_id"],
        shareholder_id=buyer["id"],
        shares_held=unit["shares_allocated"],
        entry_status="ACTIVE",
        effective_at=now,
    )
    D.recompute_all(coop)
    D.bump_coop(coop)
    return ok(D.ser(app))


@bp.post("/cooperatives/<cid>/purchase-applications/<paid>/withdraw")
def withdraw_application(cid, paid):
    uid, role = ctx()
    require_role(role, ["Shareholder"])
    coop = D.get_coop(cid)
    app = D.get_scoped("purchase_applications", paid, cid, "PurchaseApplication")
    _check_seller(app, uid)
    _check_not_terminal(app)
    was_interview_scheduled = app["application_status"] == "INTERVIEW_SCHEDULED"
    app["application_status"] = "WITHDRAWN"
    D.touch(app, coop)
    if was_interview_scheduled:
        iv = D.latest_interview(coop, app["id"])
        if iv is not None and iv["interview_status"] == "SCHEDULED":
            iv["interview_status"] = "CANCELLED"
            D.touch(iv, coop)
    return ok(D.ser(app))


# ---------------------------------------------------------------------------
# Interviews
# ---------------------------------------------------------------------------

@bp.get("/cooperatives/<cid>/interviews")
def list_interviews(cid):
    uid, role = ctx()
    require_role(role, READ_BOARD)
    D.get_coop(cid)
    return list_response("interviews", cid, [
        ("application_id", request.args.get("application_id"), False),
        ("interview_status", request.args.get("interview_status"), False),
    ])


@bp.get("/cooperatives/<cid>/interviews/<iid>")
def get_interview(cid, iid):
    uid, role = ctx()
    require_role(role, READ_BOARD)
    D.get_coop(cid)
    iv = D.get_scoped("interviews", iid, cid, "Interview")
    return ok(D.ser(iv))


@bp.post("/cooperatives/<cid>/interviews/<iid>/complete")
def complete_interview(cid, iid):
    uid, role = ctx()
    require_role(role, ["BoardMember"])
    coop = D.get_coop(cid)
    iv = D.get_scoped("interviews", iid, cid, "Interview")
    body = get_body()
    outcome = req_enum(body, "interview_outcome", ["FAVORABLE", "UNFAVORABLE"])
    # Only a panel member may record the outcome.
    if uid not in iv["panel_member_user_ids"]:
        raise ApiError(ERR_NOT_RESOURCE_OWNER, "Caller is not on the interview panel", 403)
    if iv["interview_status"] in ("COMPLETED", "CANCELLED", "NO_SHOW"):
        raise ApiError(ERR_ALREADY_TERMINAL, "Interview is in terminal state", 409)
    if iv["interview_status"] != "SCHEDULED":
        raise ApiError(ERR_INVALID_STATE, "Interview is not SCHEDULED", 409)
    if coop["current_utc"] < iv["scheduled_at"]:
        raise ApiError(ERR_TEMPORAL_CONFLICT, "Interview has not yet taken place", 422)
    iv["interview_status"] = "COMPLETED"
    iv["interview_outcome"] = outcome
    iv["completed_at"] = coop["current_utc"]
    D.touch(iv, coop)
    if outcome == "UNFAVORABLE":
        app = STORE["purchase_applications"].get(iv["application_id"])
        if app is not None and app["application_status"] == "INTERVIEW_SCHEDULED":
            app["application_status"] = "UNDER_REVIEW"
            D.touch(app, coop)
    return ok(D.ser(iv))


@bp.post("/cooperatives/<cid>/interviews/<iid>/cancel")
def cancel_interview(cid, iid):
    uid, role = ctx()
    require_role(role, ["BoardOfficer"])
    coop = D.get_coop(cid)
    iv = D.get_scoped("interviews", iid, cid, "Interview")
    if iv["interview_status"] in ("COMPLETED", "CANCELLED", "NO_SHOW"):
        raise ApiError(ERR_ALREADY_TERMINAL, "Interview is in terminal state", 409)
    if iv["interview_status"] != "SCHEDULED":
        raise ApiError(ERR_INVALID_STATE, "Interview is not SCHEDULED", 409)
    iv["interview_status"] = "CANCELLED"
    D.touch(iv, coop)
    app = STORE["purchase_applications"].get(iv["application_id"])
    if app is not None and app["application_status"] == "INTERVIEW_SCHEDULED":
        app["application_status"] = "UNDER_REVIEW"
        D.touch(app, coop)
    return ok(D.ser(iv))
