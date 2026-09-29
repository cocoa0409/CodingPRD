"""Network segments (the scope forest) and the system component inventory."""

from flask import Blueprint

import middleware as mw
from db import db, ordered
from errors import ApiError
from response import collection, single
from services import derive, serialize

bp = Blueprint("segments", __name__)

SEGMENT_CLASSES = ("CDE", "CONNECTED", "OUT_OF_SCOPE")
TEST_METHODS = ("PEN_TEST", "CONFIG_REVIEW", "TRAFFIC_ANALYSIS")
OUTCOMES = ("PASS", "FAIL")
COMPONENT_TYPES = ("SERVER", "NETWORK_DEVICE", "POS_TERMINAL", "APPLICATION", "DATABASE")
FUNCTION_CLASSES = ("PAYMENT_APPLICATION", "DATA_STORE", "SECURITY_SERVICE",
                    "CONNECTED_SUPPORT", "SEGMENTATION_CONTROL")
FACILITY_TYPES = ("DATA_CENTER", "CALL_CENTER", "RETAIL_STORE", "OFFICE")


# --------------------------------------------------------------------------- #
# declaration and reads
# --------------------------------------------------------------------------- #
@bp.post("/engagements/<engagement_id>/network-segments")
def declare_segment(engagement_id):
    mw.authenticate((mw.ROLE_LEAD, mw.ROLE_ASSESSOR))
    body = mw.json_body()
    name = mw.v_str(body, "name", allow_empty=False)
    segment_class = mw.v_enum(body, "segment_class", SEGMENT_CLASSES)
    parent_segment_id = mw.v_id_ref(body, "parent_segment_id", required=False)

    engagement = mw.fetch(db.engagements, engagement_id, "ERR_ENGAGEMENT_NOT_FOUND")

    parent = None
    if parent_segment_id is not None:
        parent = mw.fetch(db.network_segments, parent_segment_id, "ERR_SEGMENT_NOT_FOUND")
        if parent.get("engagement_id") != engagement_id:
            raise ApiError("ERR_CROSS_ENGAGEMENT_REFERENCE")

    derive.guard_frozen(engagement)

    for existing in derive.segments_of(engagement_id):
        if existing.get("name") == name:
            raise ApiError("ERR_DUPLICATE_SEGMENT_NAME")

    row = {
        "engagement_id": engagement_id,
        "name": name,
        "segment_class": segment_class,
        "parent_segment_id": parent_segment_id,
        "segmentation_status": "DECLARED",
        "test_method": None,
        "planned_date": None,
        "effective_class": segment_class,
        "scope_expanded_by_failure": False,
        "revalidation_round": 0,
        "last_validated_at": None,
    }
    db.stamp_new(row)
    db.network_segments[row["id"]] = row
    row["effective_class"] = derive.effective_class_for(row)
    return single(serialize.network_segment(row), 201)


@bp.get("/network-segments")
def list_segments():
    mw.authenticate(mw.ALL_ROLES)
    limit, offset = mw.pagination()
    payload = [serialize.network_segment(row) for row in ordered(db.network_segments.values())]
    payload = mw.apply_filters(payload, {
        "engagement_id": ("engagement_id", "str"),
        "parent_segment_id": ("parent_segment_id", "str"),
        "segmentation_status": ("segmentation_status", "str"),
        "segment_class": ("segment_class", "str"),
        "effective_class": ("effective_class", "str"),
    })
    return collection(mw.page(payload, limit, offset), limit, offset, len(payload))


@bp.get("/network-segments/<row_id>")
def get_segment(row_id):
    mw.authenticate(mw.ALL_ROLES)
    row = mw.fetch(db.network_segments, row_id, "ERR_SEGMENT_NOT_FOUND")
    return single(serialize.network_segment(row))


# --------------------------------------------------------------------------- #
# re-parenting
# --------------------------------------------------------------------------- #
@bp.patch("/network-segments/<row_id>")
def reparent_segment(row_id):
    user_id, _role = mw.authenticate((mw.ROLE_LEAD,))
    body = mw.json_body()
    has_parent_key = "parent_segment_id" in body
    parent_segment_id = mw.v_id_ref(body, "parent_segment_id", required=False)

    segment = mw.fetch(db.network_segments, row_id, "ERR_SEGMENT_NOT_FOUND")
    engagement = db.engagements.get(segment.get("engagement_id"))

    parent = None
    if parent_segment_id is not None:
        parent = mw.fetch(db.network_segments, parent_segment_id, "ERR_SEGMENT_NOT_FOUND")

    mw.require_lead(engagement, user_id)

    if parent is not None:
        if parent.get("engagement_id") != segment.get("engagement_id"):
            raise ApiError("ERR_CROSS_ENGAGEMENT_REFERENCE")
        # The proposed parent is the first step of the upward walk, so a row that
        # names itself is caught here too.
        chain = derive.ancestor_chain(parent)
        if any(node["id"] == segment["id"] for node in chain):
            raise ApiError("ERR_SEGMENT_CYCLE")

    derive.guard_frozen(engagement)

    if segment.get("segmentation_status") != "DECLARED":
        raise ApiError("ERR_INVALID_SEGMENT_STATE")
    if parent is not None:
        for node in derive.ancestor_chain(parent):
            if node.get("segmentation_status") == "FAILED":
                raise ApiError("ERR_INVALID_SEGMENT_STATE")

    if has_parent_key:
        segment["parent_segment_id"] = parent_segment_id
    db.touch(segment)
    return single(serialize.network_segment(segment))


# --------------------------------------------------------------------------- #
# segmentation test plan
# --------------------------------------------------------------------------- #
@bp.post("/network-segments/<row_id>/segmentation-test-plan")
def plan_segmentation_test(row_id):
    mw.authenticate((mw.ROLE_LEAD, mw.ROLE_ASSESSOR))
    body = mw.json_body()
    test_method = mw.v_enum(body, "test_method", TEST_METHODS)
    planned_raw, _planned_day = mw.v_day(body, "planned_date")

    segment = mw.fetch(db.network_segments, row_id, "ERR_SEGMENT_NOT_FOUND")
    engagement = db.engagements.get(segment.get("engagement_id"))
    derive.guard_frozen(engagement)

    if segment.get("segmentation_status") != "DECLARED":
        raise ApiError("ERR_INVALID_SEGMENT_STATE")

    segment["test_method"] = test_method
    segment["planned_date"] = planned_raw
    segment["segmentation_status"] = "TEST_PLANNED"
    db.touch(segment)
    return single(serialize.network_segment(segment))


# --------------------------------------------------------------------------- #
# verdict
# --------------------------------------------------------------------------- #
@bp.post("/network-segments/<row_id>/validation-result")
def record_validation_result(row_id):
    mw.authenticate((mw.ROLE_LEAD, mw.ROLE_ASSESSOR))
    body = mw.json_body()
    outcome = mw.v_enum(body, "outcome", OUTCOMES)
    mw.v_str(body, "note", required=False)

    segment = mw.fetch(db.network_segments, row_id, "ERR_SEGMENT_NOT_FOUND")
    engagement = db.engagements.get(segment.get("engagement_id"))
    derive.guard_frozen(engagement)

    if segment.get("segmentation_status") != "TEST_PLANNED":
        raise ApiError("ERR_INVALID_SEGMENT_STATE")

    engagement_id = segment.get("engagement_id")
    if outcome == "FAIL":
        segment["segmentation_status"] = "FAILED"
        segment["scope_expanded_by_failure"] = True
        db.touch(segment)
        derive.recompute_scope_partition(engagement_id)
        derive.mark_latest_plan_stale(engagement_id)
        db.touch(engagement)
    else:
        was_expanded = segment.get("scope_expanded_by_failure") is True
        segment["segmentation_status"] = "VALIDATED"
        segment["last_validated_at"] = db.now_iso()
        if was_expanded:
            segment["scope_expanded_by_failure"] = False
        db.touch(segment)
        derive.recompute_scope_partition(engagement_id)
        if was_expanded:
            derive.mark_latest_plan_stale(engagement_id)
        db.touch(engagement)
    return single(serialize.network_segment(segment))


# --------------------------------------------------------------------------- #
# re-plan after failure
# --------------------------------------------------------------------------- #
@bp.post("/network-segments/<row_id>/remediation-revalidation")
def replan_segmentation(row_id):
    user_id, _role = mw.authenticate((mw.ROLE_LEAD,))
    body = mw.json_body()
    test_method = mw.v_enum(body, "test_method", TEST_METHODS)
    planned_raw, _planned_day = mw.v_day(body, "planned_date")

    segment = mw.fetch(db.network_segments, row_id, "ERR_SEGMENT_NOT_FOUND")
    engagement = db.engagements.get(segment.get("engagement_id"))
    mw.require_lead(engagement, user_id)
    derive.guard_frozen(engagement)

    if segment.get("segmentation_status") != "FAILED":
        raise ApiError("ERR_INVALID_SEGMENT_STATE")

    segment["test_method"] = test_method
    segment["planned_date"] = planned_raw
    segment["segmentation_status"] = "TEST_PLANNED"
    segment["revalidation_round"] = int(segment.get("revalidation_round") or 0) + 1
    db.touch(segment)
    return single(serialize.network_segment(segment))


# --------------------------------------------------------------------------- #
# withdrawal
# --------------------------------------------------------------------------- #
@bp.post("/network-segments/<row_id>/withdraw")
def withdraw_segment(row_id):
    user_id, _role = mw.authenticate((mw.ROLE_LEAD,))
    body = mw.json_body()
    mw.v_str(body, "reason", allow_empty=False)

    segment = mw.fetch(db.network_segments, row_id, "ERR_SEGMENT_NOT_FOUND")
    engagement = db.engagements.get(segment.get("engagement_id"))
    mw.require_lead(engagement, user_id)
    derive.guard_frozen(engagement)

    if segment.get("segmentation_status") != "DECLARED":
        raise ApiError("ERR_INVALID_SEGMENT_STATE")

    attached_components = any(
        component.get("segment_id") == segment["id"]
        for component in derive.components_of(segment.get("engagement_id"))
    )
    attached_children = any(
        child.get("parent_segment_id") == segment["id"]
        for child in derive.segments_of(segment.get("engagement_id"))
    )
    if attached_components or attached_children:
        raise ApiError("ERR_SEGMENT_HAS_COMPONENTS")

    segment["segmentation_status"] = "WITHDRAWN"
    db.touch(segment)
    db.touch(engagement)
    return single(serialize.network_segment(segment))


# --------------------------------------------------------------------------- #
# component inventory
# --------------------------------------------------------------------------- #
@bp.post("/engagements/<engagement_id>/system-components")
def inventory_component(engagement_id):
    mw.authenticate((mw.ROLE_LEAD, mw.ROLE_ASSESSOR))
    body = mw.json_body()
    hostname = mw.v_str(body, "hostname", allow_empty=False)
    component_type = mw.v_enum(body, "component_type", COMPONENT_TYPES)
    function_class = mw.v_enum(body, "function_class", FUNCTION_CLASSES)
    stores_chd = mw.v_bool(body, "stores_chd")
    facility_name = mw.v_str(body, "facility_name", allow_empty=False)
    facility_type = mw.v_enum(body, "facility_type", FACILITY_TYPES)
    segment_id = mw.v_id_ref(body, "segment_id")

    engagement = mw.fetch(db.engagements, engagement_id, "ERR_ENGAGEMENT_NOT_FOUND")
    segment = mw.fetch(db.network_segments, segment_id, "ERR_SEGMENT_NOT_FOUND")
    if segment.get("engagement_id") != engagement_id:
        raise ApiError("ERR_CROSS_ENGAGEMENT_REFERENCE")

    derive.guard_frozen(engagement)

    siblings = derive.components_of(engagement_id)
    for existing in siblings:
        if existing.get("hostname") == hostname:
            raise ApiError("ERR_DUPLICATE_HOSTNAME")
    for existing in siblings:
        if (existing.get("facility_name") == facility_name
                and existing.get("facility_type") != facility_type):
            raise ApiError("ERR_FACILITY_TYPE_CONFLICT")

    scope_class = segment.get("effective_class")
    row = {
        "engagement_id": engagement_id,
        "segment_id": segment_id,
        "hostname": hostname,
        "component_type": component_type,
        "function_class": function_class,
        "stores_chd": stores_chd,
        "facility_name": facility_name,
        "facility_type": facility_type,
        "declared_scope_class": segment.get("segment_class"),
        "scope_class": scope_class,
        "sampling_stratum": component_type if scope_class in ("CDE", "CONNECTED") else None,
        "in_sample": False,
    }
    db.stamp_new(row)
    db.system_components[row["id"]] = row
    return single(serialize.system_component(row), 201)


@bp.get("/system-components")
def list_components():
    mw.authenticate(mw.ALL_ROLES)
    limit, offset = mw.pagination()
    payload = [serialize.system_component(row) for row in ordered(db.system_components.values())]
    payload = mw.apply_filters(payload, {
        "engagement_id": ("engagement_id", "str"),
        "segment_id": ("segment_id", "str"),
        "scope_class": ("scope_class", "str"),
        "declared_scope_class": ("declared_scope_class", "str"),
        "component_type": ("component_type", "str"),
        "in_sample": ("in_sample", "bool"),
        "facility_name": ("facility_name", "str"),
    })
    return collection(mw.page(payload, limit, offset), limit, offset, len(payload))


@bp.get("/system-components/<row_id>")
def get_component(row_id):
    mw.authenticate(mw.ALL_ROLES)
    row = mw.fetch(db.system_components, row_id, "ERR_COMPONENT_NOT_FOUND")
    return single(serialize.system_component(row))
