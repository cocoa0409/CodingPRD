"""Capacity-release packets: the handover of a cage's racks to operations."""

from flask import Blueprint, g

import db
import validation as v
from constants import (
    ALL_ROLES,
    ROLE_COMMISSIONING_AGENT,
    ROLE_OPERATIONS_MANAGER,
)
from errors import ApiError
from middleware import caller_tenant_id, endpoint, is_tenant_caller
from output import created, filtered, listing, ok, require
from services import calc
from util import D

bp = Blueprint("release_packets", __name__)

READ_ROLES = list(ALL_ROLES)
CA = [ROLE_COMMISSIONING_AGENT]
OM = [ROLE_OPERATIONS_MANAGER]

# A packet whose claim on the cage is still live, and therefore superseded by a
# fresh one.  REJECTED and SUPERSEDED packets are left untouched (PRD 3.9).
LIVE_PACKET_STATUSES = ("SUBMITTED", "ACCEPTED", "SUSPENDED")


def packet_tenant_id(packet):
    cage = db.get("cages", packet["cage_id"])
    return cage["tenant_id"] if cage else None


@bp.post("/release-packets")
@endpoint(CA)
def create_packet():
    payload = v.body()
    hall_id = v.fk_field(payload, "hall_id")
    cage_id = v.fk_field(payload, "cage_id")
    drawing_ref = v.string_field(
        payload, "as_built_drawing_ref", min_len=1, max_len=64, allow_empty=False
    )
    expected = v.int_field(payload, "expected_cage_version")

    hall = require("halls", hall_id)
    cage = require("cages", cage_id)

    if cage["hall_id"] != hall["id"]:
        raise ApiError("ERR_HALL_MISMATCH")

    if expected != cage["version"]:
        raise ApiError("ERR_STALE_CAGE_VERSION")

    prior = None
    for row in db.ordered(db.where("packets", cage_id=cage["id"])):
        if row["status"] in LIVE_PACKET_STATUSES:
            prior = row

    packet = db.new_row(
        "packets",
        {
            "hall_id": hall["id"],
            "cage_id": cage["id"],
            "as_built_drawing_ref": drawing_ref,
            "status": "DRAFT",
            "released_kw": None,
            "rack_in_scope_count": 0,
            "asset_tag_completion_pct": None,
            "supersedes_packet_id": prior["id"] if prior else None,
            "accepted_by_user_id": None,
            "rejected_reason": None,
        },
    )
    calc.apply_packet_figures(packet)

    if prior is not None:
        prior["status"] = "SUPERSEDED"
        db.touch(prior)

    # Opening a packet is itself an event on the cage: the version moves so that
    # any other agent holding an older view is turned away by the OCC check.
    db.touch(cage)
    return created(packet)


@bp.get("/release-packets")
@endpoint(READ_ROLES)
def list_packets():
    rows = filtered(
        "packets",
        {"hall_id": "hall_id", "cage_id": "cage_id", "status": "status"},
    )
    if is_tenant_caller():
        mine = caller_tenant_id()
        rows = [r for r in rows if packet_tenant_id(r) == mine]
    return listing(rows)


@bp.get("/release-packets/<packet_id>")
@endpoint(READ_ROLES)
def read_packet(packet_id):
    packet = require("packets", packet_id)
    if is_tenant_caller() and packet_tenant_id(packet) != caller_tenant_id():
        raise ApiError("ERR_TENANT_SCOPE_VIOLATION")
    return ok(packet)


@bp.post("/release-packets/<packet_id>/submit")
@endpoint(CA)
def submit_packet(packet_id):
    packet = require("packets", packet_id)
    if packet["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE")

    # The figures are refreshed first: the gates judge current reality, not the
    # numbers that happened to be frozen at create time.
    calc.apply_packet_figures(packet)

    if packet["rack_in_scope_count"] < 1:
        raise ApiError("ERR_RELEASE_SCOPE_EMPTY")
    if D(packet["asset_tag_completion_pct"]) != D("100.00"):
        raise ApiError("ERR_ASSET_TAGS_INCOMPLETE")

    cage = db.get("cages", packet["cage_id"])
    if not calc.cage_floors_met(cage):
        raise ApiError("ERR_CAGE_COVERAGE_INSUFFICIENT")

    packet["status"] = "SUBMITTED"
    db.touch(packet)
    return ok(packet)


@bp.post("/release-packets/<packet_id>/accept")
@endpoint(OM, needs_user_id=True)
def accept_packet(packet_id):
    packet = require("packets", packet_id)
    if packet["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE")

    hall = db.get("halls", packet["hall_id"])
    if hall["status"] != "LIVE":
        raise ApiError("ERR_HALL_PHASE_INVALID")

    if hall["release_posture"] != "OPEN":
        raise ApiError("ERR_RELEASE_POSTURE_BLOCKED")

    cage = db.get("cages", packet["cage_id"])
    cage_racks = db.where("racks", cage_id=cage["id"])
    for rack in cage_racks:
        if rack["status"] != "POWERED":
            continue
        if rack["energized_feed_count"] != rack["required_feed_count"]:
            raise ApiError("ERR_RELEASE_POSTURE_BLOCKED")

    packet["status"] = "ACCEPTED"
    packet["accepted_by_user_id"] = g.user_id
    db.touch(packet)

    for rack in cage_racks:
        if rack["status"] == "POWERED":
            rack["status"] = "RELEASED"
            db.touch(rack)

    if cage["operational_status"] == "SECURED":
        cage["operational_status"] = "RELEASED"
    db.touch(cage)

    calc.apply_custody(hall)
    calc.apply_release_posture(hall)
    return ok(packet)


@bp.post("/release-packets/<packet_id>/reject")
@endpoint(OM)
def reject_packet(packet_id):
    payload = v.body()
    reason = v.string_field(payload, "rejected_reason", allow_empty=False)
    packet = require("packets", packet_id)

    if packet["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE")

    packet["status"] = "REJECTED"
    packet["rejected_reason"] = reason
    db.touch(packet)
    return ok(packet)
