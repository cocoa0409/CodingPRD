"""Claimant routes."""

from __future__ import annotations

from flask import Blueprint, request

from app.envelope import success_response
from app.routes._helpers import (
    assert_claimant_self_access,
    fetch_claimant,
    get_json_body,
    with_auth,
)
from app.serializers import serialize_claimant
from app.services import claimants as service


bp = Blueprint("claimants", __name__)


@bp.route("/claimants", methods=["POST"])
@with_auth("Claimant", "PlatformAdmin")
def register_claimant(caller):
    body = get_json_body()
    record = service.register_claimant(body)
    return success_response(serialize_claimant(record), status=201)


@bp.route("/claimants/<claimant_id>", methods=["GET"])
@with_auth("Claimant", "DDS_Examiner", "ALJ", "AppealsCouncil", "CDR_Reviewer", "PlatformAdmin")
def get_claimant(caller, claimant_id: str):
    # Self-access enforced for Claimant role before existence check (per priority 4 in scaffold).
    assert_claimant_self_access(caller, claimant_id)
    record = fetch_claimant(claimant_id)
    return success_response(serialize_claimant(record))


@bp.route("/claimants/<claimant_id>", methods=["PATCH"])
@with_auth("Claimant", "PlatformAdmin")
def patch_claimant(caller, claimant_id: str):
    assert_claimant_self_access(caller, claimant_id)
    body = get_json_body()
    record = service.patch_claimant(claimant_id, body)
    return success_response(serialize_claimant(record))
