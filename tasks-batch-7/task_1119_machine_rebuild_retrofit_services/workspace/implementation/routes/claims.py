"""WarrantyClaim endpoints (PRD §3.8)."""

from flask import Blueprint, request

from calc import compute_drift
from db import bump, clock, new_record, sorted_records, store
from errors import (
    ApiError,
    ERR_CLAIM_ALREADY_OPEN,
    ERR_DRIFT_WITHIN_TOLERANCE,
    ERR_INVALID_STATE,
    ERR_PROJECT_NOT_IN_WARRANTY,
    ERR_WARRANTY_EXPIRED,
    not_found,
)
from middleware import forbidden, require_roles
from response import list_response, success
from serializers import serialize, serialize_list
from services import project_claims
from util import (
    get_body,
    opt_str,
    pagination_params,
    paginate,
    req_enum,
    req_number,
)
from routes.common import check_customer_ownership, customer_owns, get_or_404
from util import dec
import constants as C

bp = Blueprint("claims", __name__)

CLAIM_TYPES = ("ACCURACY_DRIFT", "MECHANICAL_DEFECT")


@bp.post("/api/projects/<pid>/warranty-claims")
@require_roles("Customer")
def file_claim(user_id, role, pid):
    body = get_body()
    # Gate 2 (ownership) before gate 3 (body shape) when the project exists.
    project = store.projects.get(pid)
    if project is not None and project["customer_id"] != user_id:
        raise forbidden("only the project's customer may file a warranty claim")
    claim_type = req_enum(body, "claim_type", CLAIM_TYPES)
    measured = None
    if claim_type == "ACCURACY_DRIFT":
        measured = req_number(body, "measured_positioning_microns", minimum=0)
    elif body.get("measured_positioning_microns") is not None:
        measured = req_number(body, "measured_positioning_microns", minimum=0)
    if project is None:
        raise not_found(f"project {pid} does not exist")
    if project["work_status"] != "WARRANTY_ACTIVE":
        raise ApiError(
            ERR_PROJECT_NOT_IN_WARRANTY,
            "project must be WARRANTY_ACTIVE to file a claim",
            409,
        )
    # Temporal gate first: filing must be no later than warranty_end.
    if project["_warranty_end_dt"] is not None and clock.now > project["_warranty_end_dt"]:
        raise ApiError(
            ERR_WARRANTY_EXPIRED,
            "the warranty period has ended",
            409,
        )
    for c in project_claims(pid):
        if c["status"] in ("FILED", "APPROVED"):
            raise ApiError(
                ERR_CLAIM_ALREADY_OPEN,
                "another claim of this project is FILED or APPROVED",
                409,
            )
    # Drift gate (only after the temporal gate has passed).
    drift = None
    if claim_type == "ACCURACY_DRIFT":
        drift = compute_drift(measured, project["accepted_positioning_microns"])
        if drift <= dec(C.DRIFT_TOL):
            raise ApiError(
                ERR_DRIFT_WITHIN_TOLERANCE,
                "accuracy drift must strictly exceed 15.0 microns",
                409,
            )
    rec = new_record(
        {
            "project_id": pid,
            "claim_type": claim_type,
            "measured_positioning_microns": measured,
            "drift_microns": drift,
            "filed_at": clock.iso(),
            "resolution_notes": None,
            "status": "FILED",
        }
    )
    store.claims[rec["id"]] = rec
    return success(serialize(rec), status=201)


@bp.get("/api/warranty-claims/<cid>")
@require_roles("Customer", "WarrantyAdministrator", "ProjectManager", "PlatformAdmin")
def get_claim(user_id, role, cid):
    rec = get_or_404(store.claims, cid, "warranty claim")
    check_customer_ownership(user_id, role, "claim", rec)
    return success(serialize(rec))


@bp.get("/api/warranty-claims")
@require_roles("Customer", "WarrantyAdministrator", "ProjectManager", "PlatformAdmin")
def list_claims(user_id, role):
    limit, offset = pagination_params()
    items = sorted_records(store.claims)
    project_filter = request.args.get("project_id")
    if project_filter is not None:
        items = [c for c in items if c["project_id"] == project_filter]
    if role == "Customer":
        items = [c for c in items if customer_owns(user_id, "claim", c)]
    page, meta = paginate(items, limit, offset)
    return list_response(serialize_list(page), meta)


def _adjudicate(cid, from_status, to_status):
    rec = get_or_404(store.claims, cid, "warranty claim")
    if rec["status"] != from_status:
        raise ApiError(
            ERR_INVALID_STATE,
            f"claim in status {rec['status']} cannot move to {to_status}",
            409,
        )
    notes = opt_str(get_body(), "resolution_notes")
    rec["status"] = to_status
    if notes is not None:
        rec["resolution_notes"] = notes
    bump(rec)
    return rec


@bp.post("/api/warranty-claims/<cid>/approve")
@require_roles("WarrantyAdministrator")
def approve_claim(user_id, role, cid):
    return success(serialize(_adjudicate(cid, "FILED", "APPROVED")))


@bp.post("/api/warranty-claims/<cid>/reject")
@require_roles("WarrantyAdministrator")
def reject_claim(user_id, role, cid):
    return success(serialize(_adjudicate(cid, "FILED", "REJECTED")))


@bp.post("/api/warranty-claims/<cid>/remediate")
@require_roles("WarrantyAdministrator")
def remediate_claim(user_id, role, cid):
    return success(serialize(_adjudicate(cid, "APPROVED", "CLOSED")))
