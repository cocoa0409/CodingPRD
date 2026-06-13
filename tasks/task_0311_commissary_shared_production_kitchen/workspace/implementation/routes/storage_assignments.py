"""Storage assignments: waterfall allocation, capacity, quarantine, release."""
from flask import Blueprint, request

from db import db, LOCK
from errors import ApiError
from middleware import (
    get_identity, require_roles, require_owner, get_json_body, parse_pagination,
)
from response import success, paginated
from services.common import (
    stamp_new, touch, public, find_member, get_or_404, sorted_by_creation,
    paginate, require_fields, as_int,
)
from services.calculations import storage_fee

bp = Blueprint("storage_assignments", __name__)

TEMP_CLASSES = {"DRY", "COLD", "FROZEN"}


def _candidate_units(temp_class):
    """Same-class units, ascending created_at (insertion sequence) order."""
    units = [u for u in db.storage_units.values() if u["temp_class"] == temp_class]
    return sorted(units, key=lambda u: u["_seq"])


@bp.post("/members/<member_id>/storage-assignments")
def create_storage_assignment(member_id):
    user_id, role = get_identity()
    require_roles(role, {"MemberOperator"})
    require_owner(role, user_id, member_id)
    body = get_json_body()
    with LOCK:
        member = find_member(member_id)
        require_fields(body, ["temp_class", "requested_slots", "expected_member_version"])
        if body["temp_class"] not in TEMP_CLASSES:
            raise ApiError("ERR_INVALID_REQUEST")
        temp_class = body["temp_class"]
        requested_slots = as_int(body["requested_slots"])

        # OCC (priority 7).
        if body["expected_member_version"] != member["version"]:
            raise ApiError("ERR_STALE_VERSION")

        # Member active (priority 9).
        if member["status"] != "ACTIVE":
            raise ApiError("ERR_MEMBER_NOT_ACTIVE")

        # requested_slots >= 1 (priority 6 well-formedness in scaffold; checked
        # after the above per the ERR_INVALID_REQUEST body-shape rules).
        if requested_slots < 1:
            raise ApiError("ERR_INVALID_REQUEST")

        candidates = _candidate_units(temp_class)
        eligible = [u for u in candidates if u["compliance_status"] != "QUARANTINED"]
        quarantined_same_class = [u for u in candidates if u["compliance_status"] == "QUARANTINED"]

        # Free capacity available from healthy (non-quarantined) same-class units.
        healthy_free = sum(u["total_slots"] - u["used_slots"] for u in eligible)

        # Quarantine block (priority 10, before capacity priority 21): when the
        # healthy units cannot fully satisfy the request, the waterfall would
        # have to reach a same-class quarantined unit — refuse rather than
        # surface the capacity error.
        if healthy_free < requested_slots and quarantined_same_class:
            raise ApiError("ERR_UNIT_QUARANTINED")

        # Waterfall over non-quarantined same-class units (created_at ASC).
        remaining = requested_slots
        plan = []
        for unit in eligible:
            avail = unit["total_slots"] - unit["used_slots"]
            take = min(avail, remaining)
            if take > 0:
                plan.append({"storage_unit_id": unit["id"], "slots": take})
                remaining -= take
            if remaining == 0:
                break

        # Capacity (priority 21): no partial allocation.
        if remaining > 0:
            raise ApiError("ERR_STORAGE_CAPACITY_EXCEEDED")

        primary_unit_id = plan[0]["storage_unit_id"]
        monthly_fee = storage_fee(temp_class, requested_slots, member["plan_tier"])

        assignment = {
            "member_id": member_id,
            "storage_unit_id": primary_unit_id,
            "temp_class": temp_class,
            "requested_slots": requested_slots,
            "allocation_plan": plan,
            "monthly_fee_cents": monthly_fee,
            "status": "ACTIVE",
        }
        stamp_new(assignment)
        db.storage_assignments[assignment["id"]] = assignment

        # Cascade: increment each touched unit's used_slots (each a mutation).
        for entry in plan:
            unit = db.storage_units[entry["storage_unit_id"]]
            unit["used_slots"] += entry["slots"]
            touch(unit)

        # Storage-assignment create advances the member's version (guarded write).
        touch(member)

        return success(public(assignment), 201)


def _load_member_assignment(member_id, assignment_id):
    find_member(member_id)
    asn = get_or_404(db.storage_assignments, assignment_id)
    if asn["member_id"] != member_id:
        raise ApiError("ERR_NOT_FOUND")
    return asn


@bp.get("/members/<member_id>/storage-assignments")
def list_member_assignments(member_id):
    _, role = get_identity()
    require_roles(role, {"MemberOperator", "FacilityManager"})
    limit, offset = parse_pagination()
    status = request.args.get("status")
    with LOCK:
        find_member(member_id)
        records = [a for a in db.storage_assignments.values() if a["member_id"] == member_id]
        records = sorted_by_creation(records)
        if status:
            records = [a for a in records if a["status"] == status]
        items, total = paginate(records, limit, offset)
    return paginated(items, total, limit, offset)


@bp.get("/storage-units/<unit_id>/storage-assignments")
def list_unit_assignments(unit_id):
    _, role = get_identity()
    require_roles(role, {"MemberOperator", "FacilityManager", "ComplianceOfficer"})
    limit, offset = parse_pagination()
    status = request.args.get("status")
    with LOCK:
        get_or_404(db.storage_units, unit_id)
        records = [
            a for a in db.storage_assignments.values()
            if any(e["storage_unit_id"] == unit_id for e in a["allocation_plan"])
        ]
        records = sorted_by_creation(records)
        if status:
            records = [a for a in records if a["status"] == status]
        items, total = paginate(records, limit, offset)
    return paginated(items, total, limit, offset)


@bp.get("/members/<member_id>/storage-assignments/<assignment_id>")
def get_member_assignment(member_id, assignment_id):
    _, role = get_identity()
    require_roles(role, {"MemberOperator", "FacilityManager"})
    with LOCK:
        asn = _load_member_assignment(member_id, assignment_id)
        return success(public(asn))


@bp.post("/members/<member_id>/storage-assignments/<assignment_id>/release")
def release_assignment(member_id, assignment_id):
    user_id, role = get_identity()
    require_roles(role, {"MemberOperator"})
    require_owner(role, user_id, member_id)
    with LOCK:
        asn = _load_member_assignment(member_id, assignment_id)
        if asn["status"] != "ACTIVE":
            raise ApiError("ERR_INVALID_STATE")
        for entry in asn["allocation_plan"]:
            unit = db.storage_units.get(entry["storage_unit_id"])
            if unit is not None:
                unit["used_slots"] -= entry["slots"]
                touch(unit)
        asn["status"] = "RELEASED"
        touch(asn)
        return success(public(asn))


@bp.post("/members/<member_id>/storage-assignments/<assignment_id>/release-quarantine")
def release_quarantine(member_id, assignment_id):
    _, role = get_identity()
    require_roles(role, {"ComplianceOfficer"})
    with LOCK:
        asn = _load_member_assignment(member_id, assignment_id)
        if asn["status"] != "QUARANTINED":
            raise ApiError("ERR_INVALID_STATE")
        unit = db.storage_units.get(asn["storage_unit_id"])
        if unit is None or unit["compliance_status"] != "COMPLIANT":
            raise ApiError("ERR_UNIT_QUARANTINED")
        asn["status"] = "ACTIVE"
        touch(asn)
        return success(public(asn))
