"""CustomerBundleEnrollment endpoints (PRD 3.7)."""

from flask import Blueprint

from db import STORE
from errors import (
    ApiError,
    ERR_BUNDLE_NOT_FOUND,
    ERR_ENROLLMENT_INVALID_STATE,
    not_found,
)
from middleware import get_body, paginate, query_enum, require_roles
from response import ok_object
from serialize import serialize, serialize_many
from services.rates import (
    combined_relationship_balance,
    refresh_customer_enrollments,
)
from utils import bump, req_enum, req_str, stamp_new

bp = Blueprint("enrollments", __name__)

ENROLLMENT_STATUSES = ("ENROLLED", "SUSPENDED", "EXITED")
ENROLLMENT_ACTIONS = ("SUSPEND", "REINSTATE", "EXIT")


def _get_or_404(enrollment_id):
    row = STORE["enrollments"].get(enrollment_id)
    if row is None:
        raise not_found("Bundle enrollment not found")
    return row


@bp.post("/bundle-enrollments")
@require_roles("OperationsAdmin")
def create_enrollment():
    data = get_body()
    bundle_id = req_str(data, "bundle_id")
    customer_ref = req_str(data, "customer_ref")
    bundle = STORE["bundles"].get(bundle_id)
    if bundle is None:
        raise ApiError(ERR_BUNDLE_NOT_FOUND, 422, "Referenced bundle_id does not exist")
    row = {
        "bundle_id": bundle_id,
        "customer_ref": customer_ref,
        "qualifying_balance_cents": combined_relationship_balance(customer_ref, bundle),
        "status": "ENROLLED",
    }
    stamp_new(row)
    STORE["enrollments"][row["id"]] = row
    # When qualified, the bonus lands on the customer's eligible OPEN accounts.
    refresh_customer_enrollments(customer_ref, skip_bump_ids=(row["id"],))
    return ok_object(serialize("enrollments", row), 201)


@bp.get("/bundle-enrollments")
@require_roles("OperationsAdmin", "BranchBanker")
def list_enrollments():
    from flask import request
    bundle_id = request.args.get("bundle_id")
    customer_ref = request.args.get("customer_ref")
    status = query_enum("status", ENROLLMENT_STATUSES)
    rows = list(STORE["enrollments"].values())
    if bundle_id is not None:
        rows = [r for r in rows if r["bundle_id"] == bundle_id]
    if customer_ref is not None:
        rows = [r for r in rows if r["customer_ref"] == customer_ref]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return paginate(serialize_many("enrollments", rows))


@bp.get("/bundle-enrollments/<enrollment_id>")
@require_roles("OperationsAdmin", "BranchBanker")
def get_enrollment(enrollment_id):
    return ok_object(serialize("enrollments", _get_or_404(enrollment_id)))


@bp.post("/bundle-enrollments/<enrollment_id>/transition")
@require_roles("OperationsAdmin")
def transition_enrollment(enrollment_id):
    data = get_body()
    action = req_enum(data, "action", ENROLLMENT_ACTIONS)
    row = _get_or_404(enrollment_id)
    if action == "SUSPEND":
        if row["status"] != "ENROLLED":
            raise ApiError(ERR_ENROLLMENT_INVALID_STATE, 409,
                           f"Cannot SUSPEND an enrollment in {row['status']}")
        row["status"] = "SUSPENDED"
    elif action == "REINSTATE":
        if row["status"] != "SUSPENDED":
            raise ApiError(ERR_ENROLLMENT_INVALID_STATE, 409,
                           f"Cannot REINSTATE an enrollment in {row['status']}")
        row["status"] = "ENROLLED"
    else:  # EXIT
        if row["status"] not in ("ENROLLED", "SUSPENDED"):
            raise ApiError(ERR_ENROLLMENT_INVALID_STATE, 409,
                           f"Cannot EXIT an enrollment in {row['status']}")
        row["status"] = "EXITED"
    bump(row)
    # Bonus effects: refresh qualifying balances and re-evaluate the customer's
    # eligible OPEN accounts (helper bumps versions only where values change).
    refresh_customer_enrollments(row["customer_ref"])
    return ok_object(serialize("enrollments", row))
