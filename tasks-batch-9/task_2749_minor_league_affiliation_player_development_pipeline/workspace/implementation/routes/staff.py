"""Staff member and staff allocation endpoints (PRD Section 3.4)."""
from flask import Blueprint

import auth
import common
import config
import derive
import envelope
import serialize
import store
import validate
from errors import ApiError

bp = Blueprint("staff", __name__)

TRANSITIONS = {
    "ACTIVATE": ("PROPOSED",),
    "RECALL": ("PROPOSED", "ACTIVE"),
    "END": ("ACTIVE",),
}


def _overlapping_total(member_id, start, end, exclude_id=None):
    total = 0
    for allocation in derive.allocations_of_member(member_id):
        if allocation["id"] == exclude_id or allocation["status"] != "ACTIVE":
            continue
        other_start = store.parse_date(allocation["effective_start"])
        other_end = store.parse_date(allocation["effective_end"])
        if other_start is None or other_end is None:
            continue
        if other_start < end and other_end > start:
            total += allocation["fte_pct"]
    return total


@bp.post("/staff-members")
def create_staff_member():
    auth.require(config.ROLE_FARM)
    body = validate.json_body()
    full_name = validate.str_field(body, "full_name", min_len=1, max_len=120)
    discipline = validate.enum_field(body, "discipline", config.DISCIPLINES)
    certified = validate.str_field(body, "curriculum_version_certified", min_len=1)
    expires = validate.date_field(body, "certification_expires_on")

    record = store.base_record()
    record.update({
        "full_name": full_name,
        "discipline": discipline,
        "curriculum_version_certified": certified,
        "certification_expires_on": expires,
        "total_committed_fte_pct": 0,
        "status": "ACTIVE",
    })
    store.staff_members[record["id"]] = record
    common.commit()
    return envelope.object_response(serialize.staff_member(record), 201)


@bp.get("/staff-members")
def list_staff_members():
    auth.require(config.ROLE_FARM, config.ROLE_COMPLIANCE)
    rows = list(store.staff_members.values())
    rows = common.apply_filters(rows, (
        ("discipline", "discipline"),
        ("curriculum_version_certified", "curriculum_version_certified")))
    return envelope.paginate(rows, serialize.staff_member)


@bp.get("/staff-members/<member_id>")
def read_staff_member(member_id):
    auth.require(config.ROLE_FARM, config.ROLE_COMPLIANCE)
    record = common.need("staff_members", member_id)
    return envelope.object_response(serialize.staff_member(record))


@bp.get("/staff-members/<member_id>/allocations")
def list_member_allocations(member_id):
    auth.require(config.ROLE_FARM, config.ROLE_COMPLIANCE)
    common.need("staff_members", member_id)
    rows = derive.allocations_of_member(member_id)
    rows = common.apply_filters(rows, (("status", "status"),))
    return envelope.paginate(rows, serialize.allocation)


@bp.get("/affiliates/<affiliate_id>/staff-allocations")
def list_affiliate_allocations(affiliate_id):
    auth.require(config.ROLE_FARM, config.ROLE_COMPLIANCE, config.ROLE_OPERATOR)
    common.need("affiliates", affiliate_id)
    rows = derive.allocations_of_affiliate(affiliate_id)
    rows = common.apply_filters(rows, (("staff_role", "staff_role"),
                                       ("status", "status")))
    return envelope.paginate(rows, serialize.allocation)


@bp.post("/staff-allocations")
def create_allocation():
    auth.require(config.ROLE_FARM)
    body = validate.json_body()
    member_id = validate.id_field(body, "staff_member_id")
    affiliate_id = validate.id_field(body, "affiliate_id")
    staff_role = validate.enum_field(body, "staff_role", config.STAFF_ROLES)
    fte_pct = validate.int_field(body, "fte_pct", lo=1, hi=100)
    start = validate.date_field(body, "effective_start")
    end = validate.date_field(body, "effective_end")
    curriculum = validate.str_field(body, "curriculum_version", min_len=1)
    expected = validate.int_field(body, "expected_affiliate_version")
    if store.parse_date(end) <= store.parse_date(start):
        raise validate.bad("effective_end must be strictly after effective_start.")

    member = common.need("staff_members", member_id)
    affiliate = common.need("affiliates", affiliate_id)

    if expected != affiliate["version"]:
        raise ApiError("ERR_STALE_AFFILIATE_VERSION")

    agreement = derive.gate_agreement(affiliate_id)
    if agreement is not None and agreement["posture"] == "FROZEN":
        raise ApiError("ERR_AGREEMENT_POSTURE_FROZEN")

    if curriculum != config.ORG_CURRICULUM_VERSION or \
            curriculum != member["curriculum_version_certified"]:
        raise ApiError("ERR_CURRICULUM_VERSION_MISMATCH")

    start_date = store.parse_date(start)
    end_date = store.parse_date(end)
    if _overlapping_total(member_id, start_date, end_date) + fte_pct > config.MAX_STAFF_FTE_PCT:
        raise ApiError("ERR_STAFF_FTE_OVERCOMMITTED")

    record = store.base_record()
    record.update({
        "staff_member_id": member_id,
        "affiliate_id": affiliate_id,
        "staff_role": staff_role,
        "fte_pct": fte_pct,
        "effective_start": start,
        "effective_end": end,
        "curriculum_version": curriculum,
        "status": "PROPOSED",
    })
    store.allocations[record["id"]] = record
    store.touch(affiliate)
    common.commit()
    return envelope.object_response(serialize.allocation(record), 201)


@bp.post("/staff-allocations/<allocation_id>/disposition")
def dispose_allocation(allocation_id):
    auth.require(config.ROLE_FARM)
    raw = auth.raw_body()
    auth.check_action_role(raw.get("action"), config.ROLE_FARM,
                           config.ALLOCATION_ACTION_ROLES)
    allocation = common.need("allocations", allocation_id)
    body = validate.json_body()
    action = auth.require_action(body, config.ALLOCATION_ACTION_ROLES)
    validate.str_field(body, "note", required=False, default=None, allow_blank=True)

    if allocation["status"] not in TRANSITIONS[action]:
        raise ApiError("ERR_INVALID_ALLOCATION_STATE",
                       "An allocation in status %s does not accept %s."
                       % (allocation["status"], action))

    if action == "ACTIVATE":
        if derive.active_agreement(allocation["affiliate_id"]) is None:
            raise ApiError("ERR_AGREEMENT_NOT_ACTIVE")
        member = store.staff_members.get(allocation["staff_member_id"])
        start_date = store.parse_date(allocation["effective_start"])
        end_date = store.parse_date(allocation["effective_end"])
        expires = store.parse_date(member["certification_expires_on"]) if member else None
        if expires is not None and expires < start_date:
            raise ApiError("ERR_CERTIFICATION_EXPIRED")
        total = _overlapping_total(allocation["staff_member_id"], start_date, end_date,
                                  exclude_id=allocation["id"])
        if total + allocation["fte_pct"] > config.MAX_STAFF_FTE_PCT:
            raise ApiError("ERR_STAFF_FTE_OVERCOMMITTED")

    store.touch(allocation)
    if action == "ACTIVATE":
        allocation["status"] = "ACTIVE"
    elif action == "RECALL":
        allocation["status"] = "RECALLED"
    elif action == "END":
        allocation["status"] = "ENDED"

    common.commit()
    return envelope.object_response(serialize.allocation(allocation))
