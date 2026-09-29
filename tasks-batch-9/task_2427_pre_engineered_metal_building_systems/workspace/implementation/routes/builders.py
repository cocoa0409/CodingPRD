"""PRD 3.2 -- onboarding, authorizing and suspending the builder network."""

from flask import Blueprint, request

import constants as C
import serializers as S
import validation as V
from errors import ApiError
from middleware import ANY, roles_required
from response import object_response, paginated
from services import domain
from store import db, new_row, now_iso, ordered, touch

bp = Blueprint("builders", __name__)


def _authorized_in_territory(territory_code):
    return [
        b
        for b in db.builders.values()
        if b["territory_code"] == territory_code and b["status"] == "AUTHORIZED"
    ]


@bp.route("/builders", methods=["POST"])
@roles_required("PlatformAdmin")
def create_builder():
    data = V.body()
    jurisdiction_id = V.get_string(data, "jurisdiction_id")
    name = V.get_string(data, "name", min_len=1)
    tier = V.get_enum(data, "tier", C.TIERS)
    credit_limit_cents = V.get_int(data, "credit_limit_cents", minimum=0)

    jurisdiction = domain.get_jurisdiction(jurisdiction_id)

    row = new_row(
        {
            "jurisdiction_id": jurisdiction["id"],
            "name": name,
            # The territory is a snapshot copied at creation, not a live lookup.
            "territory_code": jurisdiction["territory_code"],
            "tier": tier,
            "credit_limit_cents": credit_limit_cents,
            "credit_used_cents": 0,
            "status": "PENDING_AUTHORIZATION",
            "authorized_at": None,
        }
    )
    db.builders[row["id"]] = row
    return object_response(S.builder_out(row), 201)


@bp.route("/builders/<builder_id>", methods=["GET"])
@roles_required(ANY)
def read_builder(builder_id):
    return object_response(S.builder_out(domain.get_builder(builder_id)))


@bp.route("/builders", methods=["GET"])
@roles_required(ANY)
def list_builders():
    jurisdiction_id = request.args.get("jurisdiction_id")
    territory_code = request.args.get("territory_code")
    status = request.args.get("status")

    def predicate(row):
        if jurisdiction_id is not None and row["jurisdiction_id"] != jurisdiction_id:
            return False
        if territory_code is not None and row["territory_code"] != territory_code:
            return False
        if status is not None and row["status"] != status:
            return False
        return True

    return paginated(ordered(db.builders, predicate), S.builder_out)


@bp.route("/builders/<builder_id>/authorize", methods=["POST"])
@roles_required("PlatformAdmin")
def authorize_builder(builder_id):
    builder = domain.get_builder(builder_id)

    # Band 9: the transition is available from PENDING_AUTHORIZATION and SUSPENDED.
    if builder["status"] not in ("PENDING_AUTHORIZATION", "SUSPENDED"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    # Band 14: the territory cap. The count must be strictly below the cap.
    jurisdiction = db.jurisdictions.get(builder["jurisdiction_id"])
    cap = (
        jurisdiction["max_authorized_builders"]
        if jurisdiction is not None
        else C.DEFAULT_MAX_AUTHORIZED_BUILDERS
    )
    if len(_authorized_in_territory(builder["territory_code"])) >= cap:
        raise ApiError("ERR_TERRITORY_BUILDER_LIMIT")

    builder["status"] = "AUTHORIZED"
    builder["authorized_at"] = now_iso()
    touch(builder)

    # authorized_builder_count is derived at read time from this population, so
    # every jurisdiction sharing the territory sees the new count immediately.
    domain.cascade_builder_reauthorization(builder)
    return object_response(S.builder_out(builder))


@bp.route("/builders/<builder_id>/suspend", methods=["POST"])
@roles_required("PlatformAdmin")
def suspend_builder(builder_id):
    builder = domain.get_builder(builder_id)

    if builder["status"] != "AUTHORIZED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    builder["status"] = "SUSPENDED"
    touch(builder)

    # PRD 2.10 chain two -- three hops inside this request.
    domain.cascade_builder_suspension(builder)
    return object_response(S.builder_out(builder))
