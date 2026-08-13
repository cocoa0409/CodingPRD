"""MaterialDistribution endpoints (PRD §3.3)."""

from __future__ import annotations

from flask import Blueprint, request

import db
from errors import (
    raise_err,
    ERR_DISTRIBUTION_NOT_ACTIVE,
    ERR_DISTRIBUTION_NOT_FOUND,
    ERR_INVALID_MEETING_STATE,
    ERR_MEETING_NOT_FOUND,
)
from middleware import require_roles
from response import success_object, success_list
from services.householding import build_packages
from services.serializers import serialize, serialize_list
from util import (
    apply_filters,
    get_json_body,
    paginate,
    parse_pagination,
    require_enum,
    require_field,
    sort_by_created_at,
)

bp = Blueprint("distributions", __name__)

DELIVERY_OUTCOMES = {"DELIVERED", "BOUNCED"}


def get_distribution_or_404(package_id: str) -> dict:
    package = db.distributions.get(package_id)
    if package is None:
        raise_err(ERR_DISTRIBUTION_NOT_FOUND, "MaterialDistribution id does not exist")
    return package


@bp.route("/proxy/material-distributions/generate", methods=["POST"])
@require_roles("ProxyAdministrator")
def generate_distributions(_user_id: str, _role: str):
    body = get_json_body()
    meeting_id = require_field(body, "meeting_id")
    meeting = db.meetings.get(meeting_id)
    if meeting is None:
        raise_err(ERR_MEETING_NOT_FOUND, "Meeting id does not exist")
    if meeting["status"] not in ("RECORD_DATE_LOCKED", "MATERIALS_DISTRIBUTED"):
        raise_err(
            ERR_INVALID_MEETING_STATE,
            "Material generation requires meeting RECORD_DATE_LOCKED or MATERIALS_DISTRIBUTED",
        )

    first_generation = meeting["status"] == "RECORD_DATE_LOCKED"
    if first_generation:
        # The first generation is a lifecycle event and requires an agenda.
        if not any(p["meeting_id"] == meeting_id for p in db.proposals.values()):
            raise_err(
                ERR_INVALID_MEETING_STATE,
                "Material generation requires at least one proposal for the meeting",
            )

    # Regeneration supersedes every package that is not already SUPERSEDED.
    for package in db.distributions.values():
        if package["meeting_id"] == meeting_id and package["status"] != "SUPERSEDED":
            package["status"] = "SUPERSEDED"
            db.touch(package)

    packages = build_packages(meeting)

    if first_generation:
        meeting["status"] = "MATERIALS_DISTRIBUTED"
        # First generation activates every DRAFT proposal of the meeting.
        for proposal in db.proposals.values():
            if proposal["meeting_id"] == meeting_id and proposal["status"] == "DRAFT":
                proposal["status"] = "ACTIVE"
                db.touch(proposal)
    db.touch(meeting)

    return success_list(
        serialize_list(packages), len(packages), 0, len(packages), 201
    )


@bp.route("/proxy/material-distributions", methods=["GET"])
@require_roles("ProxyAdministrator", "TransferAgent", "InspectorOfElection")
def list_distributions(_user_id: str, _role: str):
    limit, offset = parse_pagination()
    items = sort_by_created_at(list(db.distributions.values()))
    items = apply_filters(items, ["meeting_id", "status", "channel", "representative_account_id"])
    covered = request.args.get("covered_account_ids")
    if covered is not None and covered != "":
        items = [p for p in items if covered in (p.get("covered_account_ids") or [])]
    page, total = paginate(items, limit, offset)
    return success_list(serialize_list(page), limit, offset, total)


@bp.route("/proxy/material-distributions/<package_id>", methods=["GET"])
@require_roles("ProxyAdministrator", "TransferAgent", "InspectorOfElection")
def get_distribution(package_id: str, _user_id: str, _role: str):
    return success_object(serialize(get_distribution_or_404(package_id)))


@bp.route("/proxy/material-distributions/<package_id>", methods=["PATCH"])
@require_roles("ProxyAdministrator")
def record_delivery_outcome(package_id: str, _user_id: str, _role: str):
    package = get_distribution_or_404(package_id)
    if package["status"] != "ACTIVE":
        raise_err(
            ERR_DISTRIBUTION_NOT_ACTIVE,
            "Delivery outcome may only be recorded on an ACTIVE package",
        )
    body = get_json_body()
    outcome = require_enum(body, "delivery_outcome", DELIVERY_OUTCOMES)
    package["status"] = outcome
    db.touch(package)
    return success_object(serialize(package))
