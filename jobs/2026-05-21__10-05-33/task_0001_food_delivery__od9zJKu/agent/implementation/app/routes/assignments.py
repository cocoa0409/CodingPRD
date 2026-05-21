from __future__ import annotations

from flask import Blueprint, g

from .. import assignment_logic, projections, resolvers
from ..auth import require_role
from ..envelope import err_forbidden, success

bp = Blueprint("assignments", __name__)


def _serialize(a: dict) -> dict:
    return projections.assignment(a)


@bp.route("/api/assignments/<aid>", methods=["GET"])
def read_assignment(aid: str):
    require_role("PlatformAdmin", "Rider", "CustomerService")
    a = resolvers.assignment(aid)
    if g.user_role == "Rider" and g.user_id != a["rider_id"]:
        raise err_forbidden("Rider identity mismatch")
    return success(_serialize(a))


@bp.route("/api/assignments/<aid>/accept", methods=["POST"])
def accept(aid: str):
    require_role("Rider")
    a = resolvers.assignment(aid)
    if g.user_id != a["rider_id"]:
        raise err_forbidden("Rider identity mismatch")
    rider = resolvers.rider(a["rider_id"])
    assignment_logic.accept_assignment(rider, a)
    return success(_serialize(a))


@bp.route("/api/assignments/<aid>/reject", methods=["POST"])
def reject(aid: str):
    require_role("Rider")
    a = resolvers.assignment(aid)
    if g.user_id != a["rider_id"]:
        raise err_forbidden("Rider identity mismatch")
    rider = resolvers.rider(a["rider_id"])
    assignment_logic.reject_assignment(rider, a)
    return success(_serialize(a))


@bp.route("/api/assignments/<aid>/pickup", methods=["POST"])
def pickup(aid: str):
    require_role("Rider")
    a = resolvers.assignment(aid)
    if g.user_id != a["rider_id"]:
        raise err_forbidden("Rider identity mismatch")
    rider = resolvers.rider(a["rider_id"])
    assignment_logic.pickup_assignment(rider, a)
    return success(_serialize(a))


@bp.route("/api/assignments/<aid>/deliver", methods=["POST"])
def deliver(aid: str):
    require_role("Rider")
    a = resolvers.assignment(aid)
    if g.user_id != a["rider_id"]:
        raise err_forbidden("Rider identity mismatch")
    rider = resolvers.rider(a["rider_id"])
    assignment_logic.deliver_assignment(rider, a)
    return success(_serialize(a))


@bp.route("/api/assignments/<aid>/cancel", methods=["POST"])
def cancel(aid: str):
    require_role("Rider")
    a = resolvers.assignment(aid)
    if g.user_id != a["rider_id"]:
        raise err_forbidden("Rider identity mismatch")
    rider = resolvers.rider(a["rider_id"])
    assignment_logic.cancel_assignment_by_rider(rider, a)
    return success(_serialize(a))
