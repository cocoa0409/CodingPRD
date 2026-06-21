"""CustodialParty, NoncustodialParty, Employer routes."""

from flask import Blueprint

import errors
import lookup
from common import (
    stamp_create, touch, get_body, as_str, as_enum, as_bool,
)
from db import store
from middleware import require_roles
from response import object_response
from services import serialize

bp = Blueprint("parties", __name__)

ASSISTANCE_STATES = {"NEVER_ASSISTED", "FORMERLY_ASSISTED", "CURRENTLY_ASSISTED"}
REMITTANCE_METHODS = {"EFT", "CHECK"}


# --- CustodialParty ----------------------------------------------------------
@bp.route("/custodial-parties", methods=["POST"])
@require_roles("CaseWorker")
def create_custodial_party(auth):
    body = get_body()
    full_name = as_str(body, "full_name")
    state_code = as_str(body, "state_code")
    assistance_status = as_enum(body, "assistance_status", ASSISTANCE_STATES,
                                required=False, default="NEVER_ASSISTED")
    rec = stamp_create({
        "full_name": full_name,
        "state_code": state_code,
        "assistance_status": assistance_status,
        "payee_status": "ACTIVE",
    })
    store.custodial_parties[rec["id"]] = rec
    return object_response(serialize.custodial_party(rec), 201)


@bp.route("/custodial-parties/<rid>", methods=["GET"])
@require_roles("CaseWorker", "FinanceOfficer", "CustodialParty")
def get_custodial_party(auth, rid):
    rec = lookup.custodial_party(rid)
    lookup.require(lookup.owns_custodial_party(auth, rec))
    return object_response(serialize.custodial_party(rec), 200)


@bp.route("/custodial-parties/<rid>/hold", methods=["POST"])
@require_roles("FinanceOfficer")
def hold_custodial_party(auth, rid):
    rec = lookup.custodial_party(rid)
    body = get_body()
    hold = as_bool(body, "hold")
    rec["payee_status"] = "HOLD" if hold else "ACTIVE"
    touch(rec)
    return object_response(serialize.custodial_party(rec), 200)


# --- NoncustodialParty -------------------------------------------------------
@bp.route("/noncustodial-parties", methods=["POST"])
@require_roles("CaseWorker")
def create_noncustodial_party(auth):
    body = get_body()
    full_name = as_str(body, "full_name")
    ssn_last4 = as_str(body, "ssn_last4")
    supports_second_family = as_bool(body, "supports_second_family",
                                     required=False, default=False)
    rec = stamp_create({
        "full_name": full_name,
        "ssn_last4": ssn_last4,
        "supports_second_family": supports_second_family,
    })
    store.noncustodial_parties[rec["id"]] = rec
    return object_response(serialize.noncustodial_party(rec), 201)


@bp.route("/noncustodial-parties/<rid>", methods=["GET"])
@require_roles("CaseWorker", "FinanceOfficer")
def get_noncustodial_party(auth, rid):
    rec = lookup.noncustodial_party(rid)
    return object_response(serialize.noncustodial_party(rec), 200)


# --- Employer ----------------------------------------------------------------
@bp.route("/employers", methods=["POST"])
@require_roles("CaseWorker")
def create_employer(auth):
    body = get_body()
    legal_name = as_str(body, "legal_name")
    fein = as_str(body, "fein")
    remittance_method = as_enum(body, "remittance_method", REMITTANCE_METHODS,
                                required=False, default="EFT")
    # Priority 6: fein unique across employers (after structural validity).
    for e in store.employers.values():
        if e["fein"] == fein:
            raise errors.duplicate_fein()
    rec = stamp_create({
        "legal_name": legal_name,
        "fein": fein,
        "remittance_method": remittance_method,
    })
    store.employers[rec["id"]] = rec
    return object_response(serialize.employer(rec), 201)


@bp.route("/employers/<rid>", methods=["GET"])
@require_roles("CaseWorker", "FinanceOfficer", "Employer")
def get_employer(auth, rid):
    rec = lookup.employer(rid)
    lookup.require(lookup.owns_employer(auth, rec))
    return object_response(serialize.employer(rec), 200)
