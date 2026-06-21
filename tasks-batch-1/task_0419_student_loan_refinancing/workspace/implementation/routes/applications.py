"""Application routes and the prequalify/approve/decline/withdraw/fund workflows.

PRD §3.2 (intake & prequal), §3.5 (underwriting), §3.6 (withdrawal/expiry),
§3.7 (funding & pool selection).
"""
from decimal import Decimal
from datetime import timedelta

from flask import Blueprint, request

import calc
import db
import serialize
from auth import authorize
from constants import (
    BAND_ORDER,
    FICO_BANDS,
    MAX_DTI_RATIO,
    OFFER_TTL_HOURS,
    RATE_TYPES,
    TERM_MONTHS,
)
import clock
from errors import err
from response import object_response, array_response
from store_helpers import get_or_404, sorted_by_created, paginate, append_audit
from timeutil import iso_z, parse_iso
from validate import (
    get_json_body,
    require_str,
    require_enum,
    require_positive_int,
    require_int,
    parse_pagination,
)

bp = Blueprint("applications", __name__)


def _cosigner_for_application(application_id):
    """Return the single Cosigner attached to an application, if any."""
    for c in db.cosigners.values():
        if c["application_id"] == application_id:
            return c
    return None


def _offers_for_application(application_id):
    return [o for o in db.offers.values() if o["application_id"] == application_id]


# ---- Create / read / list ----
@bp.route("/applications", methods=["POST"])
def create_application():
    authorize(("POST", "/applications"))
    body = get_json_body()
    borrower_id = require_str(body, "borrower_id")
    requested_principal_cents = require_positive_int(body, "requested_principal_cents")
    requested_term_months = require_int(body, "requested_term_months")
    if requested_term_months not in TERM_MONTHS:
        raise err("ERR_INVALID_REQUEST", "requested_term_months invalid")
    requested_rate_type = require_enum(body, "requested_rate_type", RATE_TYPES)

    with db.lock():
        # FK borrower_id must resolve (PRD §2.5).
        get_or_404(db.borrowers, borrower_id)
        record = {
            "borrower_id": borrower_id,
            "requested_principal_cents": requested_principal_cents,
            "requested_term_months": requested_term_months,
            "requested_rate_type": requested_rate_type,
            "soft_pull_fico_band": None,
            "dti_ratio": None,
            "status": "DRAFT",
            "approved_underwriter_id": None,
        }
        db.stamp_create(record)
        db.applications[record["id"]] = record
    return object_response(serialize.application(record), 201)


@bp.route("/applications/<rid>", methods=["GET"])
def get_application(rid):
    authorize(("GET", "/applications/{id}"))
    record = get_or_404(db.applications, rid)
    return object_response(serialize.application(record), 200)


@bp.route("/applications", methods=["GET"])
def list_applications():
    authorize(("GET", "/applications"))
    limit, offset = parse_pagination()
    f_borrower = request.args.get("borrower_id")
    f_status = request.args.get("status")
    records = list(db.applications.values())
    if f_borrower is not None:
        records = [r for r in records if r["borrower_id"] == f_borrower]
    if f_status is not None:
        records = [r for r in records if r["status"] == f_status]
    records = sorted_by_created(records)
    page, total = paginate(records, limit, offset)
    return array_response([serialize.application(r) for r in page], limit, offset, total)


# ---- Prequalify ----
@bp.route("/applications/<rid>/prequalify", methods=["POST"])
def prequalify(rid):
    user_id, role = authorize(("POST", "/applications/{id}/prequalify"))
    with db.lock():
        app = get_or_404(db.applications, rid)
        # Defined only from DRAFT (PRD §3.2).
        if app["status"] != "DRAFT":
            raise err("ERR_INVALID_STATE", "prequalify only from DRAFT")
        borrower = get_or_404(db.borrowers, app["borrower_id"])

        # 1. Soft-credit pull.
        soft_band = calc.soft_pull(borrower["fico_band"])
        app["soft_pull_fico_band"] = soft_band

        # 2. DTI (borrower-only variant at prequal).
        ratio = calc.dti_ratio(
            app["requested_principal_cents"],
            app["requested_term_months"],
            borrower["annual_income_cents"],
        )
        app["dti_ratio"] = float(ratio)

        # 3. Offer grid: find every matching RateGridEntry.
        soft_idx = BAND_ORDER.index(soft_band)
        matches = []
        for cell in db.rate_grid_entries.values():
            if cell["rate_type"] != app["requested_rate_type"]:
                continue
            if cell["term_months"] != app["requested_term_months"]:
                continue
            # min_fico_band no stricter than soft band (row band <= borrower band).
            if BAND_ORDER.index(cell["min_fico_band"]) > soft_idx:
                continue
            matches.append(cell)

        if not matches:
            # No offers created; prequalify rejected (PRD §3.2).
            raise err("ERR_NO_MATCHING_RATE", "no matching rate grid entry")

        # Create one Offer per matching row, in creation order of the grid cells.
        matches = sorted_by_created(matches)
        expires_dt = clock.now() + timedelta(hours=OFFER_TTL_HOURS)
        for cell in matches:
            est = calc.estimated_apr_bps(
                cell["base_apr_bps"],
                cell["index_apr_bps"],
                app["requested_rate_type"],
                soft_band,
            )
            offer = {
                "application_id": app["id"],
                "rate_grid_entry_index": cell["id"],
                "term_months": cell["term_months"],
                "rate_type": app["requested_rate_type"],
                "estimated_apr_bps": est,
                "locked_apr_bps": None,
                "autopay_elected": False,
                "status": "PRESENTED",
                "expires_at_dt": expires_dt,
                "expires_at": iso_z(expires_dt),
            }
            db.stamp_create(offer)
            db.offers[offer["id"]] = offer

        app["status"] = "PREQUALIFIED"
        db.touch(app)
        append_audit("APPLICATION", app["id"], "APPLICATION_PREQUALIFIED", role, user_id)
    return object_response(serialize.application(app), 200)


# ---- Approve ----
@bp.route("/applications/<rid>/approve", methods=["POST"])
def approve(rid):
    user_id, role = authorize(("POST", "/applications/{id}/approve"))
    with db.lock():
        app = get_or_404(db.applications, rid)
        if app["status"] != "UNDER_REVIEW":
            raise err("ERR_INVALID_STATE", "approve only from UNDER_REVIEW")
        # Business guards in order (PRD §3.5): exactly one LOCKED offer, then DTI.
        locked = [o for o in _offers_for_application(app["id"]) if o["status"] == "LOCKED"]
        if len(locked) != 1:
            raise err("ERR_NO_LOCKED_OFFER", "exactly one LOCKED offer required")
        if app["dti_ratio"] is None or Decimal(str(app["dti_ratio"])) > Decimal(MAX_DTI_RATIO):
            raise err("ERR_DTI_EXCEEDED", "dti_ratio exceeds limit")
        app["status"] = "APPROVED"
        app["approved_underwriter_id"] = user_id
        db.touch(app)
        append_audit("APPLICATION", app["id"], "APPLICATION_APPROVED", role, user_id)
    return object_response(serialize.application(app), 200)


# ---- Decline ----
@bp.route("/applications/<rid>/decline", methods=["POST"])
def decline(rid):
    user_id, role = authorize(("POST", "/applications/{id}/decline"))
    with db.lock():
        app = get_or_404(db.applications, rid)
        if app["status"] != "UNDER_REVIEW":
            raise err("ERR_INVALID_STATE", "decline only from UNDER_REVIEW")
        for o in _offers_for_application(app["id"]):
            if o["status"] == "LOCKED":
                o["status"] = "SUPERSEDED"
                db.touch(o)
        app["status"] = "DECLINED"
        db.touch(app)
        append_audit("APPLICATION", app["id"], "APPLICATION_DECLINED", role, user_id)
    return object_response(serialize.application(app), 200)


# ---- Withdraw ----
@bp.route("/applications/<rid>/withdraw", methods=["POST"])
def withdraw(rid):
    user_id, role = authorize(("POST", "/applications/{id}/withdraw"))
    with db.lock():
        app = get_or_404(db.applications, rid)
        if app["status"] not in {"DRAFT", "PREQUALIFIED", "UNDER_REVIEW"}:
            raise err("ERR_INVALID_STATE", "withdraw only from DRAFT/PREQUALIFIED/UNDER_REVIEW")
        # Expire every non-terminal offer by setting it to SUPERSEDED (PRD §3.6).
        for o in _offers_for_application(app["id"]):
            if o["status"] in {"PRESENTED", "LOCKED"}:
                o["status"] = "SUPERSEDED"
                db.touch(o)
        app["status"] = "WITHDRAWN"
        db.touch(app)
        append_audit("APPLICATION", app["id"], "APPLICATION_WITHDRAWN", role, user_id)
    return object_response(serialize.application(app), 200)


# ---- Expire offers sweep ----
@bp.route("/applications/<rid>/expire-offers", methods=["POST"])
def expire_offers(rid):
    user_id, role = authorize(("POST", "/applications/{id}/expire-offers"))
    with db.lock():
        app = get_or_404(db.applications, rid)
        # Defined only from PREQUALIFIED (PRD §3.6).
        if app["status"] != "PREQUALIFIED":
            raise err("ERR_INVALID_STATE", "expire-offers only from PREQUALIFIED")
        offers = _offers_for_application(app["id"])
        now = clock.now()
        # Only when every offer has expires_at at or before the current clock.
        if not all(o["expires_at_dt"] <= now for o in offers):
            raise err("ERR_INVALID_STATE", "some offers are still live")
        for o in offers:
            if o["status"] == "PRESENTED":
                o["status"] = "EXPIRED"
                db.touch(o)
        app["status"] = "EXPIRED"
        db.touch(app)
        append_audit("APPLICATION", app["id"], "APPLICATION_EXPIRED", role, user_id)
    return object_response(serialize.application(app), 200)


# ---- Fund ----
def _select_pool(app, locked_offer):
    """Best-fit ABS pool selection (PRD §3.7). Returns the chosen pool or raises."""
    soft_idx = BAND_ORDER.index(app["soft_pull_fico_band"])
    requested = app["requested_principal_cents"]
    rate_type = locked_offer["rate_type"]
    candidates = []
    for pool in db.abs_pools.values():
        if pool["status"] != "OPEN":
            continue
        if BAND_ORDER.index(pool["min_fico_band"]) > soft_idx:
            continue
        if pool["allowed_rate_type"] != "ANY" and pool["allowed_rate_type"] != rate_type:
            continue
        if pool["committed_principal_cents"] + requested > pool["max_principal_cents"]:
            continue
        candidates.append(pool)
    if not candidates:
        raise err("ERR_NO_ELIGIBLE_POOL", "no eligible ABS pool")
    # Best fit: smallest remaining capacity; tie-break earliest created_at.
    def remaining(p):
        return p["max_principal_cents"] - p["committed_principal_cents"]
    candidates.sort(key=lambda p: (remaining(p), p["created_at"], p.get("_seq", 0)))
    return candidates[0]


@bp.route("/applications/<rid>/fund", methods=["POST"])
def fund(rid):
    user_id, role = authorize(("POST", "/applications/{id}/fund"))
    with db.lock():
        app = get_or_404(db.applications, rid)
        # Funding is against an APPROVED application (PRD §3.7).
        if app["status"] != "APPROVED":
            raise err("ERR_INVALID_STATE", "fund only from APPROVED")
        locked = [o for o in _offers_for_application(app["id"]) if o["status"] == "LOCKED"]
        # Exactly one LOCKED offer was required at approval; use it.
        locked_offer = locked[0]

        pool = _select_pool(app, locked_offer)

        borrower = db.borrowers[app["borrower_id"]]
        cosigner = _cosigner_for_application(app["id"])
        release_status = "PENDING" if (cosigner and cosigner["consent_status"] == "CONSENTED") else "NOT_APPLICABLE"

        principal = app["requested_principal_cents"]
        now = clock.now()
        loan = {
            "application_id": app["id"],
            "offer_id": locked_offer["id"],
            "abs_pool_id": pool["id"],
            "original_principal_cents": principal,
            "principal_balance_cents": principal,
            "accrued_interest_cents": 0,
            "last_accrual_at_dt": now,
            "last_accrual_at": iso_z(now),
            "locked_apr_bps": locked_offer["locked_apr_bps"],
            "term_months": locked_offer["term_months"],
            "repayment_status": "CURRENT",
            "cosigner_release_status": release_status,
        }
        db.stamp_create(loan)
        db.loans[loan["id"]] = loan

        # pool.committed_principal_cents += original principal.
        pool["committed_principal_cents"] += principal
        db.touch(pool)

        # Member benefit: upgrade NONE -> SILVER; higher tiers untouched.
        if borrower["member_tier"] == "NONE":
            borrower["member_tier"] = "SILVER"
            db.touch(borrower)

        append_audit("LOAN", loan["id"], "LOAN_FUNDED", role, user_id)
    return object_response(serialize.loan(loan), 201)
