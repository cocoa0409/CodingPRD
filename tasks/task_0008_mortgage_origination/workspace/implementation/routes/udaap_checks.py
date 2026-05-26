"""UDAAPCheck routes — append-only audit entries (no version, no updated_at)."""
from __future__ import annotations

from flask import Blueprint, g, request

import db
import response
from errors import (
    ApiError,
    ERR_APPLICANT_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_UDAAP_REASONS_INVALID,
)
from middleware import require_auth
from services.common import (
    get_json_body,
    new_common_fields,
    paginate,
    parse_pagination,
    require_enum,
    require_str,
    sorted_by_created_at,
)
from services.lookup import get_subresource_or_404

bp = Blueprint("udaap_checks", __name__)

REVIEW_OUTCOMES = {"CLEARED", "FLAGGED"}
FLAGGED_REASON_VALUES = {"HIDDEN_FEES", "MISLEADING_RATE", "STEERING", "PRESSURE_TACTICS"}


def uc_to_dict(u: dict) -> dict:
    out = {
        "id": u["id"],
        "application_id": u["application_id"],
        "review_outcome": u["review_outcome"],
        "flagged_reasons": u.get("flagged_reasons"),
        "reviewer_user_id": u["reviewer_user_id"],
        "created_at": u["created_at"],
    }
    return out


@bp.post("/udaap-checks")
@require_auth(roles=["ComplianceOfficer"])
def create_udaap_check():
    body = get_json_body()
    application_id = require_str(body, "application_id")
    if application_id not in db.loan_applications:
        raise ApiError(ERR_APPLICANT_NOT_FOUND, "application_id does not refer to a known loan application.")
    review_outcome = require_enum(body, "review_outcome", REVIEW_OUTCOMES)
    flagged_reasons = body.get("flagged_reasons", None)

    # Symmetric validation of flagged_reasons.
    if review_outcome == "FLAGGED":
        if not isinstance(flagged_reasons, list) or len(flagged_reasons) == 0:
            raise ApiError(
                ERR_UDAAP_REASONS_INVALID,
                "flagged_reasons must be a non-empty array when review_outcome == FLAGGED.",
            )
        for r in flagged_reasons:
            if not isinstance(r, str) or r not in FLAGGED_REASON_VALUES:
                raise ApiError(
                    ERR_UDAAP_REASONS_INVALID,
                    f"Invalid flagged reason: {r!r}.",
                )
    else:  # CLEARED
        if flagged_reasons is not None and (not isinstance(flagged_reasons, list) or len(flagged_reasons) > 0):
            raise ApiError(
                ERR_UDAAP_REASONS_INVALID,
                "flagged_reasons must be omitted or empty when review_outcome == CLEARED.",
            )
        flagged_reasons = None

    with db.lock:
        # UDAAPCheck is append-only: id + created_at only (no updated_at, no version).
        common = new_common_fields(with_version=False)
        u = {
            **common,
            "application_id": application_id,
            "review_outcome": review_outcome,
            "flagged_reasons": list(flagged_reasons) if flagged_reasons else None,
            "reviewer_user_id": g.user_id,
        }
        db.udaap_checks[u["id"]] = u
    return response.ok(uc_to_dict(u), status=201)


@bp.get("/udaap-checks/<u_id>")
@require_auth(roles=["LoanOfficer", "Underwriter", "ComplianceOfficer"])
def read_udaap_check(u_id: str):
    u = get_subresource_or_404(db.udaap_checks, u_id)
    return response.ok(uc_to_dict(u))


@bp.get("/udaap-checks")
@require_auth(roles=["LoanOfficer", "Underwriter", "ComplianceOfficer"])
def list_udaap_checks():
    limit, offset = parse_pagination()
    application_id = request.args.get("application_id")
    review_outcome = request.args.get("review_outcome")
    items = list(db.udaap_checks.values())
    if application_id is not None:
        items = [x for x in items if x["application_id"] == application_id]
    if review_outcome is not None:
        items = [x for x in items if x["review_outcome"] == review_outcome]
    items = sorted_by_created_at(items)
    page, total = paginate(items, limit, offset)
    return response.list_ok([uc_to_dict(x) for x in page], limit, offset, total)
