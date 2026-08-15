"""Estoppel certificate routes (PRD §3.8) including the deficiency loop:
a failed certification is recorded DEFICIENT with a reason for audit while
the request itself is rejected with the corresponding 422, and the lease
falls back from ESTOPPEL_PENDING to VERIFIED so a new certificate can be
requested."""

from decimal import Decimal
from flask import Blueprint, request

import db
from errors import ApiError
from middleware import bump, require_role
from response import created, ok, ok_list
from routes.common import body, ref_not_found, req_bool, req_int, req_str
from services import domain

bp = Blueprint("estoppels", __name__)

READ_ROLES = ("AcquisitionsAnalyst", "UnderwritingCommittee", "DueDiligenceOfficer",
              "PlatformAdmin")


def _check_lease_in_deal(deal, lease_id):
    lease = db.stores["leases"].get(lease_id)
    if lease is None:
        ref_not_found("lease_id references a non-existent lease")
    prop = db.stores["properties"].get(lease["property_id"])
    if prop is None or prop["deal_id"] != deal["id"]:
        ref_not_found("lease_id references a lease outside this deal")
    return lease


@bp.route("/acquisition-deals/deals/<deal_id>/estoppels", methods=["POST"])
def create_estoppel(deal_id):
    require_role("DueDiligenceOfficer")
    deal = domain.get_deal(deal_id)
    data = body()
    lease_id = req_str(data, "lease_id")
    tenant_id = req_str(data, "tenant_id")
    _check_lease_in_deal(deal, lease_id)
    if tenant_id not in db.stores["tenants"]:
        ref_not_found("tenant_id references a non-existent tenant")
    rent_confirmed = req_int(data, "rent_confirmed_cents")
    default_confirmed = req_bool(data, "default_confirmed")
    estoppel = db.make_record({
        "deal_id": deal["id"],
        "lease_id": lease_id,
        "tenant_id": tenant_id,
        "rent_confirmed_cents": rent_confirmed,
        "default_confirmed": default_confirmed,
        "deficiency_reason": None,
        "status": "REQUESTED",
    })
    db.stores["estoppels"][estoppel["id"]] = estoppel
    return created(db.pub(estoppel))


@bp.route("/acquisition-deals/deals/<deal_id>/estoppels", methods=["GET"])
def list_estoppels(deal_id):
    require_role(*READ_ROLES)
    deal = domain.get_deal(deal_id)
    items = domain.estoppels_of(deal["id"])
    for param in ("status", "lease_id", "tenant_id"):
        v = request.args.get(param)
        if v is not None:
            items = [e for e in items if str(e.get(param)) == v]
    return ok_list(items)


@bp.route("/acquisition-deals/deals/<deal_id>/estoppels/<estoppel_id>", methods=["GET"])
def get_estoppel(deal_id, estoppel_id):
    require_role(*READ_ROLES)
    deal = domain.get_deal(deal_id)
    return ok(db.pub(domain.get_estoppel_scoped(deal, estoppel_id)))


@bp.route("/acquisition-deals/deals/<deal_id>/estoppels/<estoppel_id>/receive", methods=["POST"])
def receive_estoppel(deal_id, estoppel_id):
    require_role("DueDiligenceOfficer")
    deal = domain.get_deal(deal_id)
    estoppel = domain.get_estoppel_scoped(deal, estoppel_id)
    if estoppel["status"] != "REQUESTED":
        raise ApiError("ERR_ESTOPPEL_INVALID_STATE",
                       "receive requires status REQUESTED", 409)
    estoppel["status"] = "RECEIVED"
    bump(estoppel)
    # Receipt pulls the lease into ESTOPPEL_PENDING — from VERIFIED on the
    # first round, or from ESTOPPELED on a re-confirmation round.
    lease = db.stores["leases"].get(estoppel["lease_id"])
    if lease is not None and lease["status"] in ("VERIFIED", "ESTOPPELED"):
        lease["status"] = "ESTOPPEL_PENDING"
        bump(lease)
    return ok(db.pub(estoppel))


@bp.route("/acquisition-deals/deals/<deal_id>/estoppels/<estoppel_id>/certify", methods=["POST"])
def certify_estoppel(deal_id, estoppel_id):
    require_role("DueDiligenceOfficer")
    deal = domain.get_deal(deal_id)
    estoppel = domain.get_estoppel_scoped(deal, estoppel_id)
    if estoppel["status"] != "RECEIVED":
        raise ApiError("ERR_ESTOPPEL_INVALID_STATE",
                       "certify requires status RECEIVED", 409)
    lease = db.stores["leases"].get(estoppel["lease_id"])

    def _deficient(reason, error_id, message):
        """Failed certification: recorded DEFICIENT for audit, lease falls
        back to VERIFIED, and the request is rejected with the error."""
        estoppel["status"] = "DEFICIENT"
        estoppel["deficiency_reason"] = reason
        bump(estoppel)
        if lease is not None and lease["status"] == "ESTOPPEL_PENDING":
            lease["status"] = "VERIFIED"
            bump(lease)
        raise ApiError(error_id, message, 422)

    if not estoppel["default_confirmed"]:
        _deficient("tenant disclosed a landlord default",
                   "ERR_ESTOPPEL_DEFAULT_DISCLOSED",
                   "Estoppel discloses a landlord default (default_confirmed is false)")
    rent = lease["annual_base_rent_cents"] if lease else 0
    # Tolerance gate (scaffold): |confirmed - rent| * 10000 <= rent * 50,
    # boundary inclusive — a deviation of exactly 50 bps passes, anything
    # fractionally wider fails.
    within = (Decimal(abs(estoppel["rent_confirmed_cents"] - rent)) * Decimal(10000)
              <= Decimal(rent) * Decimal(domain.ESTOPPEL_TOLERANCE_BPS))
    if not within:
        _deficient("confirmed rent deviates beyond 50 bps tolerance",
                   "ERR_ESTOPPEL_RENT_MISMATCH",
                   "Confirmed rent deviates from the lease rent by more than 50 bps")
    estoppel["status"] = "CERTIFIED"
    bump(estoppel)
    if lease is not None and lease["status"] == "ESTOPPEL_PENDING":
        lease["status"] = "ESTOPPELED"
        bump(lease)
    domain.recheck_estoppel_collection(deal)
    domain.recompute_posture(deal)
    return ok(db.pub(estoppel))
