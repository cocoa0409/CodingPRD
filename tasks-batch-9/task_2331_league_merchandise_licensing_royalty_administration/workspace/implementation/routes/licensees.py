"""Licensee onboarding, lifecycle, risk index and authorization requests (PRD 3.2, 3.6)."""

import re

from flask import Blueprint, request

import constants as K
import db
import middleware as mw
import response
import serializers
import validate as V
from db import S, apply_changes, touch
from errors import ApiError
from middleware import (ROLE_COMPLIANCE, ROLE_FINANCE, ROLE_AUDITOR, ROLE_LICENSEE,
                        ROLE_MANAGER, guard, paginate, pagination)
from services import domain, retailers

bp = Blueprint("licensees", __name__)

COUNTRY_RE = re.compile(r"^[A-Z]{2}$")

READ_ROLES = [ROLE_MANAGER, ROLE_COMPLIANCE, ROLE_FINANCE, ROLE_AUDITOR]


def _bad(message):
    raise ApiError("ERR_VALIDATION", message)


def _find(licensee_id):
    row = S.licensees.get(licensee_id)
    if row is None:
        raise ApiError("ERR_LICENSEE_NOT_FOUND")
    return row


# --------------------------------------------------------------------------- #
# creation and reads                                                          #
# --------------------------------------------------------------------------- #

@bp.post("/licensing/licensees")
def create_licensee():
    ctx = guard([ROLE_MANAGER])
    body = ctx.body
    legal_name = V.req_string(body, "legal_name", 1, 200)
    email = V.req_string(body, "contact_email", 1, 320)
    if "@" not in email:
        _bad("contact_email must contain an at-sign.")
    country = V.req_string(body, "home_country_code", 2, 2)
    if not COUNTRY_RE.match(country):
        _bad("home_country_code must be exactly two uppercase letters.")
    if V.present(body, "vendor_compliance_certified"):
        V.req_bool(body, "vendor_compliance_certified")

    folded = legal_name.casefold()
    for existing in S.licensees.values():
        if existing["legal_name"].casefold() == folded:
            _bad("legal_name must be unique.")

    row = db.base_row()
    row.update({
        "legal_name": legal_name,
        "contact_email": email,
        "home_country_code": country,
        "status": "PROSPECT",
        "vendor_compliance_certified": False,
        "compliance_risk_index": 0,
        "risk_index_as_of_quarter": None,
        "outstanding_recovery_cents": 0,
        "agreement_count": 0,
        "suspension_reason": None,
    })
    S.licensees[row["id"]] = row
    return response.created(serializers.dump("Licensee", row))


@bp.get("/licensing/licensees")
def list_licensees():
    guard(READ_ROLES)
    limit, offset = pagination()
    status = mw.filter_enum("status", K.LICENSEE_STATUSES)
    country = mw.filter_str("home_country_code")
    rows = list(S.licensees.values())
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if country is not None:
        rows = [r for r in rows if r["home_country_code"] == country]
    page, total = paginate(rows, limit, offset)
    return response.ok_list(serializers.dump_all("Licensee", page), limit, offset, total)


@bp.get("/licensing/licensees/<licensee_id>")
def get_licensee(licensee_id):
    ctx = guard(READ_ROLES + [ROLE_LICENSEE])
    mw.scope_licensee(ctx, licensee_id)
    return response.ok(serializers.dump("Licensee", _find(licensee_id)))


@bp.get("/licensing/licensees/<licensee_id>/risk-index")
def get_risk_index(licensee_id):
    guard(READ_ROLES)
    licensee = _find(licensee_id)
    variant = request.args.get("variant")
    if variant is None:
        variant = "ROLLING_MONITOR"
    elif variant not in K.RISK_VARIANTS:
        _bad("variant must be ROLLING_MONITOR or STRICT_ASSESSMENT.")
    as_of = request.args.get("as_of_quarter")
    if as_of is None:
        as_of = db.current_quarter()
    elif not db.is_quarter(as_of):
        _bad("as_of_quarter must be a fiscal quarter label such as 2026Q2.")

    result = domain.compute_risk_index(licensee["id"], as_of, variant)
    return response.ok({
        "licensee_id": licensee["id"],
        "as_of_quarter": as_of,
        "variant": variant,
        "index": result["index"],
        "posture_band": result["posture_band"],
        "factor_count": result["factor_count"],
        "raw_weighted_total_milli": result["raw_weighted_total_milli"],
    })


# --------------------------------------------------------------------------- #
# lifecycle                                                                   #
# --------------------------------------------------------------------------- #

def _suspend_cascade(licensee, reason):
    licensee["status"] = "SUSPENDED"
    licensee["suspension_reason"] = reason
    touch(licensee)
    for agreement in domain.agreements_of(licensee["id"]):
        if agreement["contract_status"] != "ACTIVE":
            continue
        agreement["contract_status"] = "SUSPENDED"
        agreement["suspension_reason"] = "LICENSEE_SUSPENDED"
        touch(agreement)
        for sub in domain.submissions_of(agreement["id"]):
            if sub["status"] in domain.HELD_SUBMISSION_STATES and not sub["review_hold"]:
                sub["review_hold"] = True
                touch(sub)


def _reinstate_cascade(licensee):
    licensee["status"] = "ACTIVE"
    licensee["suspension_reason"] = None
    touch(licensee)
    for agreement in domain.agreements_of(licensee["id"]):
        if agreement["contract_status"] != "SUSPENDED":
            continue
        if agreement["suspension_reason"] != "LICENSEE_SUSPENDED":
            continue
        agreement["contract_status"] = "ACTIVE"
        agreement["suspension_reason"] = None
        touch(agreement)
        if agreement["compliance_posture"] in ("PROBATION", "FROZEN"):
            continue
        for sub in domain.submissions_of(agreement["id"]):
            if sub["review_hold"]:
                sub["review_hold"] = False
                touch(sub)


def _terminate_cascade(licensee):
    licensee["status"] = "TERMINATED"
    touch(licensee)
    for agreement in domain.agreements_of(licensee["id"]):
        if agreement["contract_status"] in ("EXPIRED", "TERMINATED"):
            continue
        agreement["contract_status"] = "TERMINATED"
        agreement["termination_reason"] = "LICENSEE_TERMINATED"
        touch(agreement)
        for sub in domain.submissions_of(agreement["id"]):
            if sub["status"] == "APPROVED":
                sub["status"] = "REVOKED"
                sub["revocation_reason"] = "LICENSEE_TERMINATED"
                touch(sub)
    for auth in domain.authorizations_of(licensee["id"]):
        if auth["status"] in ("PENDING", "AUTHORIZED", "SUSPENDED"):
            auth["status"] = "REVOKED"
            touch(auth)
    for agreement in domain.agreements_of(licensee["id"]):
        domain.refresh_agreement_aggregates(agreement)
    domain.refresh_agreement_count(licensee)


@bp.post("/licensing/licensees/<licensee_id>/status")
def licensee_status(licensee_id):
    ctx = guard([ROLE_MANAGER, ROLE_COMPLIANCE])
    licensee = _find(licensee_id)
    body = ctx.body
    action = V.req_enum(body, "action", ("ACTIVATE", "SUSPEND", "REINSTATE", "TERMINATE"))

    if action == "ACTIVATE":
        certified = V.req_bool(body, "vendor_compliance_certified")
        if certified is not True:
            _bad("vendor_compliance_certified must be true to activate a licensee.")
        if licensee["status"] != "PROSPECT":
            raise ApiError("ERR_INVALID_STATE")
        licensee["status"] = "ACTIVE"
        licensee["vendor_compliance_certified"] = True
        touch(licensee)
    elif action == "SUSPEND":
        reason = V.req_string(body, "reason", 1)
        if licensee["status"] != "ACTIVE":
            raise ApiError("ERR_INVALID_STATE")
        _suspend_cascade(licensee, reason)
    elif action == "REINSTATE":
        if licensee["status"] != "SUSPENDED":
            raise ApiError("ERR_INVALID_STATE")
        _reinstate_cascade(licensee)
    else:
        if licensee["status"] not in ("ACTIVE", "SUSPENDED"):
            raise ApiError("ERR_INVALID_STATE")
        _terminate_cascade(licensee)

    return response.ok(serializers.dump("Licensee", licensee))


# --------------------------------------------------------------------------- #
# retailer authorization requests                                             #
# --------------------------------------------------------------------------- #

@bp.post("/licensing/licensees/<licensee_id>/retailer-authorizations")
def create_authorization(licensee_id):
    ctx = guard([ROLE_MANAGER, ROLE_LICENSEE])
    mw.scope_licensee(ctx, licensee_id)
    licensee = _find(licensee_id)
    body = ctx.body

    retailer_name = V.req_string(body, "retailer_name", 1, 120)
    channel_class = V.req_enum(body, "channel_class", K.AUTH_CHANNEL_CLASSES)
    sku_classes = V.req_string_list(body, "sku_classes", 1, 5)
    for sku in sku_classes:
        if sku not in K.SKU_CLASSES:
            _bad("sku_classes entries must name a SKU class.")
    start = V.req_date(body, "authorized_from")
    end = V.req_date(body, "authorized_to")
    closeout_allowed = V.opt_bool(body, "closeout_allowed", False)
    expected = V.req_int(body, "expected_licensee_version")

    if expected != licensee["version"]:
        raise ApiError("ERR_STALE_LICENSEE_VERSION")
    if licensee["status"] != "ACTIVE":
        raise ApiError("ERR_LICENSEE_NOT_ACTIVE")

    retailers.check_off_price_capacity(licensee_id, channel_class, start, end)
    retailers.check_window_rule(licensee_id, retailer_name, channel_class, start, end)

    row = db.base_row()
    row.update({
        "licensee_id": licensee_id,
        "retailer_name": retailer_name,
        "channel_class": channel_class,
        "sku_classes": sku_classes,
        "authorized_from": body["authorized_from"],
        "authorized_to": body["authorized_to"],
        "closeout_allowed": closeout_allowed,
        "status": "PENDING",
        "suspension_reason": None,
        "suspended_at": None,
        "approved_by_user_id": None,
    })
    S.authorizations[row["id"]] = row
    touch(licensee)
    return response.created(serializers.dump("RetailerAuthorization", row))
