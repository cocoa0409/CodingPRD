"""Executive recommendations, guarded by OCC on the agency request."""

from flask import Blueprint

import auth
import db
import response
from errors import fail
from services import calc
from services import constants as C
from services import core
from validators import (
    body_json,
    listing,
    peek_fk,
    query_enum,
    read_enum,
    read_id,
    read_id_list,
    read_int,
)

bp = Blueprint("executive_recommendations", __name__)


@bp.post("/fiscal/executive-recommendations")
def create_recommendation():
    actor = auth.authenticate((auth.BUDGET_ANALYST, auth.BUDGET_DIRECTOR))
    body = body_json()

    request_row = peek_fk(body, "agency_request_id", core.get_request)
    raw_ids = body.get("recommended_package_ids")
    if isinstance(raw_ids, list):
        for candidate in raw_ids:
            if isinstance(candidate, str) and candidate:
                core.get_package(candidate)

    read_id(body, "agency_request_id")
    recommended_base_cents = read_int(body, "recommended_base_cents")
    if recommended_base_cents < 0:
        fail("ERR_INVALID_REQUEST", "recommended_base_cents must be zero or positive.")
    package_ids = read_id_list(body, "recommended_package_ids")
    policy_priority = read_enum(body, "policy_priority", C.POLICY_PRIORITIES)
    expected_version = read_int(body, "expected_agency_request_version")

    if expected_version != request_row["version"]:
        fail(
            "ERR_STALE_VERSION",
            "Agency request version is %d, not %d."
            % (request_row["version"], expected_version),
        )

    cycle = core.get_cycle(request_row["budget_cycle_id"])
    core.require_not_closed(cycle)

    packages = [db.decision_packages[pid] for pid in package_ids]
    for package in packages:
        if package["status"] != "RECOMMENDED":
            fail(
                "ERR_PACKAGE_NOT_RECOMMENDED",
                "Package %s is %s, not RECOMMENDED." % (package["id"], package["status"]),
            )
    for package in packages:
        if package["agency_request_id"] != request_row["id"]:
            fail(
                "ERR_PACKAGE_REQUEST_MISMATCH",
                "Package %s belongs to a different agency request." % package["id"],
            )

    row = db.new_row()
    row.update(
        {
            "agency_request_id": request_row["id"],
            "recommended_base_cents": recommended_base_cents,
            "recommended_package_ids": list(package_ids),
            "policy_priority": policy_priority,
            "recommended_amount_cents": calc.recommendation_amount(
                recommended_base_cents, packages
            ),
            "prepared_by_user_id": actor.user_id,
            "approved_by_user_id": None,
            "status": "PREPARED",
        }
    )

    superseded_approved = False
    for prior in db.executive_recommendations.values():
        if prior["agency_request_id"] != request_row["id"]:
            continue
        if prior["status"] not in ("PREPARED", "APPROVED"):
            continue
        if prior["status"] == "APPROVED":
            superseded_approved = True
        db.apply_changes(prior, {"status": "SUPERSEDED"})

    db.executive_recommendations[row["id"]] = row
    db.touch(request_row)
    if superseded_approved:
        core.sync(cycle, cycle_extra={"balance_certified": False}, force_cycle=True)
    return response.created(db.serialize(row))


@bp.post("/fiscal/executive-recommendations/<recommendation_id>/approve")
def approve_recommendation(recommendation_id):
    actor = auth.authenticate((auth.BUDGET_DIRECTOR,))
    row = core.get_recommendation(recommendation_id)
    request_row = core.get_request(row["agency_request_id"])
    cycle = core.get_cycle(request_row["budget_cycle_id"])

    core.require_phase(cycle, ("EXECUTIVE_PREP",))
    if row["status"] != "PREPARED":
        fail("ERR_INVALID_STATE", "Only a PREPARED recommendation may be approved.")
    if request_row["status"] != "ACCEPTED":
        fail("ERR_INVALID_STATE", "The owning request is not ACCEPTED.")
    if actor.user_id == row["prepared_by_user_id"]:
        fail(
            "ERR_SEGREGATION_OF_DUTIES",
            "The preparer of a recommendation may not approve it.",
        )

    db.apply_changes(row, {"status": "APPROVED", "approved_by_user_id": actor.user_id})
    core.sync(cycle, cycle_extra={"balance_certified": False}, force_cycle=True)
    return response.ok(db.serialize(row))


@bp.get("/fiscal/agency-requests/<request_id>/executive-recommendations")
def list_request_recommendations(request_id):
    auth.authenticate(auth.ANY_ROLE)
    request_row = core.get_request(request_id)
    status = query_enum("status", C.RECOMMENDATION_STATUSES)
    rows = []
    for row in db.executive_recommendations.values():
        if row["agency_request_id"] != request_row["id"]:
            continue
        if status is not None and row["status"] != status:
            continue
        rows.append(row)
    data, meta = listing(rows)
    return response.ok_list(data, meta)
