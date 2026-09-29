"""The party roster: identification, notice, election and orphaning."""

from decimal import Decimal

from flask import Blueprint

import constants as K
import derive
import serialize
import shape
import store
import txn
from authz import require
from errors import ApiError
from routes import common

bp = Blueprint("prps", __name__)

ZERO = Decimal("0.00")


@bp.post("/sites/<site_id>/prps")
def create_prp(site_id):
    require(K.ROLE_RPM)
    body = shape.get_body()
    legal_name = shape.str_field(body, "legal_name")
    party_type = shape.enum_field(body, "party_type", K.PARTY_TYPES)
    viability = shape.int_field(body, "viability_score", lo=0, hi=100)
    site = common.get_site(site_id)
    common.deny_deleted(site)

    prp = common.new_record(
        {
            "site_id": site["id"],
            "legal_name": legal_name,
            "party_type": party_type,
            "viability_score": viability,
            "status": "IDENTIFIED",
            "notice_reference": None,
            "submitted_volume_tons": ZERO,
            "verified_volume_tons": ZERO,
            "max_toxicity_class": None,
            "volumetric_share_pct": ZERO,
            "ownership_days_total": 0,
            "de_minimis_eligible": False,
            "contribution_protection": False,
        }
    )
    store.prps[prp["id"]] = prp
    return common.respond(prp, serialize.prp, 201)


@bp.post("/prps/<prp_id>/notice")
def issue_notice(prp_id):
    require(K.ROLE_RPM)
    body = shape.get_body()
    reference = shape.str_field(body, "notice_reference")
    prp = common.get_prp(prp_id)
    site = store.sites[prp["site_id"]]
    common.state(prp["status"] == "IDENTIFIED")
    # Only while the site is past proposal and not yet deleted from the docket.
    if site["listing_status"] in ("PROPOSED", "DELETED_FROM_NPL"):
        raise ApiError("ERR_SITE_PHASE_INVALID")

    txn.watch(prp)
    prp["status"] = "NOTIFIED"
    prp["notice_reference"] = reference
    return common.respond(prp, serialize.prp)


@bp.post("/prps/<prp_id>/response")
def record_election(prp_id):
    actor = require(K.ROLE_PRP)
    body = shape.get_body()
    election = shape.enum_field(body, "election", K.ELECTIONS)
    shape.str_field(body, "response_note", required=False)
    prp = common.get_prp(prp_id)
    common.identity(actor, prp["id"])
    site = store.sites[prp["site_id"]]

    if election == "PARTICIPATE":
        common.state(prp["status"] in ("NOTIFIED", "RECALCITRANT"))
        target = "PARTICIPATING"
    else:
        common.state(prp["status"] in ("NOTIFIED", "PARTICIPATING"))
        # One brake on withdrawal: a commitment already before the court.
        if prp["status"] == "PARTICIPATING":
            for decree in derive.site_decrees(site["id"]):
                if decree["legal_status"] in ("LODGED", "ENTERED") and prp[
                    "id"
                ] in decree["party_prp_ids"]:
                    raise ApiError("ERR_INVALID_STATE_TRANSITION")
        target = "RECALCITRANT"
    common.deny_deleted(site)

    txn.watch(prp)
    prp["status"] = target
    return common.respond(prp, serialize.prp)


@bp.post("/prps/<prp_id>/defunct")
def record_defunct(prp_id):
    require(K.ROLE_RPM)
    body = shape.get_body()
    shape.str_field(body, "defunct_reason")
    prp = common.get_prp(prp_id)
    site = store.sites[prp["site_id"]]
    common.state(prp["status"] in ("NOTIFIED", "PARTICIPATING", "RECALCITRANT"))
    common.deny_deleted(site)

    txn.watch(prp)
    prp["status"] = "ORPHAN"
    derive.defunct_cascade(site, prp)
    return common.respond(prp, serialize.prp)
