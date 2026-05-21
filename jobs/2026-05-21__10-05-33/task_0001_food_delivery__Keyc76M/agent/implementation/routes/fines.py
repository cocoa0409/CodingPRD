"""Fine endpoints: read, list, waive."""

from flask import Blueprint, request

import auth
import envelope
import projection
import state
import validators
from services import fines as fines_svc


bp = Blueprint("fines", __name__)


_VIEWER_ROLES = ("PlatformAdmin", "CustomerService", "Rider", "Restaurant",
                 "Customer")


def _self_role_subject_type(role):
    return {
        "Rider": "RIDER",
        "Restaurant": "RESTAURANT",
        "Customer": "CUSTOMER",
    }.get(role)


@bp.route("/api/fines/<fid>", methods=["GET"])
def get_fine(fid):
    user_id, role = auth.headers()
    if not user_id:
        return envelope.auth_required()
    if role not in _VIEWER_ROLES:
        return envelope.forbidden()
    with state.lock():
        f = state.STORE.fines.get(fid)
        if f is None:
            return envelope.not_found("Fine not found.")
        # Subjects can only read their own fine.
        st = _self_role_subject_type(role)
        if st is not None:
            if f["subject_type"] != st or f["subject_id"] != user_id:
                return envelope.forbidden()
        return envelope.success(projection.render(f))


@bp.route("/api/fines", methods=["GET"])
def list_fines():
    user_id, role = auth.headers()
    if not user_id:
        return envelope.auth_required()
    if role not in _VIEWER_ROLES:
        return envelope.forbidden()

    page, perr = validators.pagination_params(request.args)
    if perr:
        return perr
    limit, offset = page

    subject_type = request.args.get("subject_type")
    subject_id = request.args.get("subject_id")
    settlement_status = request.args.get("settlement_status")

    with state.lock():
        st = _self_role_subject_type(role)
        if st is not None:
            # Subject roles must match their own id; pin filters.
            if subject_type is not None and subject_type != st:
                return envelope.forbidden()
            if subject_id is not None and subject_id != user_id:
                return envelope.forbidden()
            subject_type = st
            subject_id = user_id

        fines = list(state.STORE.fines.values())
        if subject_type:
            fines = [f for f in fines if f["subject_type"] == subject_type]
        if subject_id:
            fines = [f for f in fines if f["subject_id"] == subject_id]
        if settlement_status:
            fines = [f for f in fines
                     if f["settlement_status"] == settlement_status]
        fines.sort(key=lambda f: f["created_at"])
        total = len(fines)
        window = fines[offset : offset + limit]
        return envelope.list_response(
            [projection.render(f) for f in window], limit, offset, total,
        )


@bp.route("/api/fines/<fid>/waive", methods=["POST"])
def waive(fid):
    user_id, role = auth.headers()
    if not user_id:
        return envelope.auth_required()
    if role not in ("CustomerService", "PlatformAdmin"):
        return envelope.forbidden()
    with state.lock():
        f = state.STORE.fines.get(fid)
        if f is None:
            return envelope.not_found("Fine not found.")
        if f["settlement_status"] != "PENDING":
            return envelope.invalid_state(
                "Only PENDING fines can be waived."
            )
        fines_svc.waive(f)
        return envelope.success(projection.render(f))
