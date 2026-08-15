"""Delegated credentialing agreements (closed-interval overlap discipline)."""
from flask import Blueprint, request

from db import base_fields, store, touch
from errors import ApiError, ERR_AGREEMENT_OVERLAP, invalid_request, invalid_state, not_found
from middleware import ALL_ROLES, require_roles
from response import list_response, success_object
from serializers import pub
from validate import body, req_date, req_str

bp = Blueprint("agreements", __name__)


def _get_agreement(aid):
    ag = store.agreements.get(aid)
    if ag is None:
        raise not_found("DelegatedCredentialingAgreement")
    return ag


@bp.post("/api/delegation-agreements")
@require_roles("ComplianceOfficer")
def create_agreement():
    b = body()
    # Existence (tier 3) of body FKs before schema (tier 4).
    gid_raw = b.get("practice_group_id")
    yid_raw = b.get("payer_id")
    if isinstance(gid_raw, str) and gid_raw not in store.practice_groups:
        raise not_found("PracticeGroup")
    if isinstance(yid_raw, str) and yid_raw not in store.payers:
        raise not_found("Payer")
    gid = req_str(b, "practice_group_id")
    yid = req_str(b, "payer_id")
    eff = req_date(b, "effective_date")
    exp = req_date(b, "expiry_date")
    if not exp > eff:
        raise invalid_request("expiry_date must be strictly later than effective_date")
    # Closed-interval overlap: sharing even one boundary date counts; only
    # non-TERMINATED agreements block.
    for ag in store.agreements.values():
        if (
            ag["practice_group_id"] == gid
            and ag["payer_id"] == yid
            and ag["status"] != "TERMINATED"
            and eff <= ag["expiry_date"]
            and ag["effective_date"] <= exp
        ):
            raise ApiError(
                ERR_AGREEMENT_OVERLAP,
                409,
                "The agreement interval overlaps an existing agreement for this group and payer",
            )
    ag = base_fields()
    ag.update(
        {
            "practice_group_id": gid,
            "payer_id": yid,
            "effective_date": eff,
            "expiry_date": exp,
            "status": "ACTIVE",
        }
    )
    store.agreements[ag["id"]] = ag
    return success_object(pub(ag), 201)


@bp.get("/api/delegation-agreements/<aid>")
@require_roles(*ALL_ROLES)
def get_agreement(aid):
    return success_object(pub(_get_agreement(aid)))


@bp.get("/api/delegation-agreements")
@require_roles(*ALL_ROLES)
def list_agreements():
    payer_id = request.args.get("payer_id")
    practice_group_id = request.args.get("practice_group_id")
    status = request.args.get("status")
    items = [
        a for a in store.agreements.values()
        if (payer_id is None or a["payer_id"] == payer_id)
        and (practice_group_id is None or a["practice_group_id"] == practice_group_id)
        and (status is None or a["status"] == status)
    ]
    return list_response(items, pub)


@bp.post("/api/delegation-agreements/<aid>/terminate")
@require_roles("ComplianceOfficer")
def terminate_agreement(aid):
    ag = _get_agreement(aid)
    if ag["status"] != "ACTIVE":
        raise invalid_state("Only an ACTIVE agreement can be terminated")
    ag["status"] = "TERMINATED"
    touch(ag)
    return success_object(pub(ag))
