"""The control chain: ownership attribution, background checks, change of control (§3.2)."""

from flask import Blueprint

import calculations as calc
from db import base_row, db, serialize, touch
from errors import ApiError
from middleware import authorize, regulator_has_licensee_nexus, require_scope
from response import created, ok
from routes.common import filter_rows, get_control_person, get_licensee, paginate
from services import engine
from validators import get_body, pagination, q_enum, q_str, v_bool, v_enum, v_int, v_str

bp = Blueprint("control_persons", __name__)


def _chain_depth(parent):
    """Number of links from the root down to (and including) parent."""
    depth = 0
    seen = set()
    node = parent
    while node is not None:
        if node["id"] in seen:
            raise ApiError("ERR_CONTROL_CHAIN_CYCLE", "The control chain contains a cycle")
        seen.add(node["id"])
        depth += 1
        parent_id = node.get("parent_control_person_id")
        node = db.control_persons.get(parent_id) if parent_id else None
    return depth


@bp.post("/control-persons")
def create_control_person():
    authorize("LicensingManager")
    body = get_body()
    licensee_id = v_str(body, "licensee_id")
    full_name = v_str(body, "full_name")
    role_title = v_enum(body, "role_title", calc.ROLE_TITLES)
    direct_bps = v_int(body, "direct_ownership_bps", minimum=0, maximum=10000)
    parent_id = v_str(body, "parent_control_person_id", required=False, default=None)

    licensee = get_licensee(licensee_id)
    parent = get_control_person(parent_id) if parent_id else None

    if parent is not None and parent["licensee_id"] != licensee_id:
        raise ApiError(
            "ERR_CROSS_LICENSEE_REFERENCE",
            "Parent control person belongs to a different licensee",
        )

    if parent is not None and _chain_depth(parent) + 1 > calc.MAX_CHAIN_DEPTH:
        raise ApiError(
            "ERR_CONTROL_CHAIN_CYCLE",
            "The control chain may be at most %d links deep" % calc.MAX_CHAIN_DEPTH,
        )

    effective, attributed = calc.ownership_attribution(direct_bps, parent)
    determination = calc.control_determination(attributed, role_title)
    is_control = determination == "CONTROL"

    row = base_row()
    row.update(
        {
            "licensee_id": licensee_id,
            "parent_control_person_id": parent_id,
            "full_name": full_name,
            "role_title": role_title,
            "direct_ownership_bps": direct_bps,
            "effective_ownership_bps": effective,
            "attributed_ownership_bps": attributed,
            "control_determination": determination,
            "background_check_status": "PENDING" if is_control else "NOT_REQUIRED",
            "disqualifying_finding": False,
            "change_of_control_status": (
                "PENDING_APPROVAL"
                if is_control and licensee["active_license_count"] > 0
                else "NOT_REQUIRED"
            ),
            "approving_jurisdiction_ids": [],
            "required_approval_count": licensee["active_license_count"],
            "status": "PROPOSED",
        }
    )
    db.control_persons[row["id"]] = row
    engine.maybe_seat(row)
    engine.recompute_control_chain(licensee)
    return created(serialize(row))


@bp.get("/control-persons/<control_person_id>")
def get_one(control_person_id):
    authorize("LicensingManager", "StateRegulator")
    return ok(serialize(get_control_person(control_person_id)))


@bp.get("/control-persons")
def list_all():
    authorize("LicensingManager", "StateRegulator")
    limit, offset = pagination()
    licensee_id = q_str("licensee_id")
    parent_id = q_str("parent_control_person_id")
    status = q_enum("status", ("PROPOSED", "SEATED", "REMOVED"))
    determination = q_enum("control_determination", ("CONTROL", "NON_CONTROL"))
    rows = filter_rows(
        db.control_persons.values(),
        {
            "licensee_id": licensee_id,
            "parent_control_person_id": parent_id,
            "status": status,
            "control_determination": determination,
        },
    )
    return paginate(rows, limit, offset)


@bp.post("/control-persons/<control_person_id>/background-check-adjudication")
def adjudicate(control_person_id):
    user_id, _ = authorize("StateRegulator")
    body = get_body()
    outcome = v_enum(body, "outcome", ("CLEARED", "ADVERSE"))
    disqualifying = v_bool(body, "disqualifying_finding", required=False, default=False)

    row = get_control_person(control_person_id)
    licensee = get_licensee(row["licensee_id"])
    require_scope(
        regulator_has_licensee_nexus(user_id, row["licensee_id"]), user_id, "this licensee"
    )

    if row["status"] != "PROPOSED" or row["background_check_status"] != "PENDING":
        raise ApiError(
            "ERR_CONTROL_PERSON_INVALID_STATE",
            "Control person %s has no pending background check" % control_person_id,
        )

    if outcome == "CLEARED":
        row["background_check_status"] = "CLEARED"
        touch(row)
        engine.maybe_seat(row)
        engine.recompute_control_chain(licensee)
    else:
        row["background_check_status"] = "ADVERSE"
        if disqualifying:
            row["disqualifying_finding"] = True
            row["status"] = "REMOVED"
            touch(row)
            engine.recompute_descendants(row, remove=True)
            engine.force_control_chain_blocked(licensee)
        else:
            touch(row)
            engine.recompute_control_chain(licensee)
    return ok(serialize(row))


@bp.post("/control-persons/<control_person_id>/change-of-control-decisions")
def change_of_control(control_person_id):
    user_id, _ = authorize("StateRegulator")
    body = get_body()
    decision = v_enum(body, "decision", ("APPROVED", "DENIED"))
    v_str(body, "rationale", required=False, allow_empty=True, default=None)

    row = get_control_person(control_person_id)
    licensee = get_licensee(row["licensee_id"])
    require_scope(
        regulator_has_licensee_nexus(user_id, row["licensee_id"]), user_id, "this licensee"
    )

    if row["status"] != "PROPOSED" or row["change_of_control_status"] != "PENDING_APPROVAL":
        raise ApiError(
            "ERR_CONTROL_PERSON_INVALID_STATE",
            "Control person %s has no pending change-of-control filing" % control_person_id,
        )

    if user_id in row["approving_jurisdiction_ids"]:
        raise ApiError(
            "ERR_DUPLICATE_APPROVAL",
            "Jurisdiction %s has already decided on this control person" % user_id,
        )

    if decision == "APPROVED":
        row["approving_jurisdiction_ids"] = list(row["approving_jurisdiction_ids"]) + [user_id]
        if len(row["approving_jurisdiction_ids"]) >= row["required_approval_count"]:
            row["change_of_control_status"] = "APPROVED"
        touch(row)
        engine.maybe_seat(row)
    else:
        row["change_of_control_status"] = "DENIED"
        row["status"] = "REMOVED"
        touch(row)
        engine.recompute_descendants(row)
    engine.recompute_control_chain(licensee)
    return ok(serialize(row))
