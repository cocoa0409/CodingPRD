"""CustodyTransfer endpoints: list per movement, get, certify, dispute,
resolve, void."""
from flask import Blueprint

from db import STORE
from errors import err
from middleware import require_roles, current_user
from response import success_object, success_list
from serializers import custody_transfer_view
from services import calc, lifecycle
from services.common import touch, get_movement_or_404
from validation import sort_and_page

bp = Blueprint("custody", __name__)


@bp.get("/movements/<movementId>/custody-transfers")
def list_custody_transfers(movementId):
    current_user()
    get_movement_or_404(movementId)
    rows = [ct for ct in STORE.custody_transfers.values()
            if ct["movement_id"] == movementId]
    page, total, limit, offset = sort_and_page(rows)
    return success_list([custody_transfer_view(ct) for ct in page], total, limit, offset)


def _get_ct_or_404(ct_id):
    ct = STORE.custody_transfers.get(ct_id)
    if ct is None:
        raise err("ERR_CUSTODY_TRANSFER_NOT_FOUND",
                  "Custody transfer %s not found" % ct_id)
    return ct


@bp.get("/custody-transfers/<ctId>")
def get_custody_transfer(ctId):
    current_user()
    ct = _get_ct_or_404(ctId)
    return success_object(custody_transfer_view(ct))


@bp.post("/custody-transfers/<ctId>/certify")
def certify(ctId):
    user_id, _ = require_roles("TerminalManager")
    ct = _get_ct_or_404(ctId)
    if ct["status"] != "PROVISIONAL":
        raise err("ERR_INVALID_STATE",
                  "Custody transfer %s is %s; certify requires PROVISIONAL"
                  % (ctId, ct["status"]))
    movement = get_movement_or_404(ct["movement_id"])

    # Segregation of duties (priority 13): certifier != gauge recorder.
    opening, closing = lifecycle.gauge_pair(movement["id"])
    gauge_recorders = {g["recorded_by_user_id"] for g in (opening, closing) if g}
    if user_id in gauge_recorders:
        raise err("ERR_SEGREGATION_OF_DUTIES",
                  "The gauge recorder may not certify this custody transfer")

    # Quality gate (priority 16): exactly one PASSED sample is required.
    sample = lifecycle.passed_sample(movement["id"])
    if sample is None:
        raise err("ERR_QUALITY_NOT_PASSED",
                  "Certify requires a QualitySample with lab_result PASSED")

    lease = STORE.leases.get(movement["lease_id"])

    certified = calc.certified_volume(movement, opening, closing, sample)
    ct["certified_volume_bbl"] = certified
    loss = calc.compute_loss_fields(movement, lease, certified)
    ct["shrinkage_bbl"] = loss["shrinkage_bbl"]
    ct["allowed_loss_bbl"] = loss["allowed_loss_bbl"]
    ct["excess_loss_bbl"] = loss["excess_loss_bbl"]
    ct["excess_loss_charge"] = loss["excess_loss_charge"]
    ct["certified_by_user_id"] = user_id
    ct["status"] = "CERTIFIED"
    touch(ct)

    # Cascade: tank inventory + posture, OPEN statement recompute, loss control.
    lifecycle.custody_cascade(ct, suspend_check=True)
    return success_object(custody_transfer_view(ct))


@bp.post("/custody-transfers/<ctId>/dispute")
def dispute(ctId):
    user_id, _ = require_roles("CustomerRep")
    ct = _get_ct_or_404(ctId)
    # Ownership (priority 3): caller must be the lease's customer.
    movement = STORE.movements.get(ct["movement_id"])
    lease = STORE.leases.get(movement["lease_id"]) if movement else None
    if lease is None or lease["customer_id"] != user_id:
        raise err("ERR_FORBIDDEN_OWNERSHIP",
                  "Only the owning customer may dispute this custody transfer")
    if ct["status"] != "CERTIFIED":
        raise err("ERR_INVALID_STATE",
                  "Custody transfer %s is %s; dispute requires CERTIFIED"
                  % (ctId, ct["status"]))
    ct["status"] = "DISPUTED"
    touch(ct)
    # Inventory contribution unchanged: DISPUTED still counts at certified volume.
    return success_object(custody_transfer_view(ct))


@bp.post("/custody-transfers/<ctId>/resolve")
def resolve(ctId):
    require_roles("TerminalManager")
    ct = _get_ct_or_404(ctId)
    if ct["status"] != "DISPUTED":
        raise err("ERR_INVALID_STATE",
                  "Custody transfer %s is %s; resolve requires DISPUTED"
                  % (ctId, ct["status"]))
    ct["status"] = "CERTIFIED"
    touch(ct)
    lifecycle.custody_cascade(ct, suspend_check=True)
    return success_object(custody_transfer_view(ct))


@bp.post("/custody-transfers/<ctId>/void")
def void(ctId):
    require_roles("TerminalManager")
    ct = _get_ct_or_404(ctId)
    if ct["status"] not in ("CERTIFIED", "DISPUTED"):
        raise err("ERR_INVALID_STATE",
                  "Custody transfer %s is %s; void requires CERTIFIED or DISPUTED"
                  % (ctId, ct["status"]))
    ct["status"] = "VOID"
    touch(ct)
    # Compensating action: excluded from inventory projection and statement
    # input sets. The lease is NOT auto-reactivated even if excess loss
    # subsides (PRD 3.7).
    lifecycle.custody_cascade(ct, suspend_check=True)
    return success_object(custody_transfer_view(ct))
