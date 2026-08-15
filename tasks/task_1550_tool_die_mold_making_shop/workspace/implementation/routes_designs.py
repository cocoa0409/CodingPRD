"""Tool design endpoints: create, submit, review, revise (PRD §3.2)."""
from flask import Blueprint, request

from store import STORE
from helpers import (ApiError, endpoint, get_body, validate_payload, ok, created,
                     ok_list, paginate, filter_eq, sort_created, not_found,
                     stamp_new, bump)
from domain import ser_design, TOOL_TYPES, DIE_CLASSES

bp = Blueprint("designs", __name__)


@bp.route("/tool-designs", methods=["POST"])
@endpoint(roles=["Customer"])
def create_design(uid, role):
    data = validate_payload(get_body(), [
        ("customer_id", "str", True),
        ("part_number", "str", True),
        ("tool_type", "enum", True, {"values": TOOL_TYPES}),
        ("die_class", "enum", True, {"values": DIE_CLASSES}),
        ("cavity_count", "int", True, {"min": 1, "max": 64}),
        ("design_complexity_score", "int", True, {"min": 1, "max": 20}),
    ])
    cust = STORE.customers.get(data["customer_id"])
    if cust is None:
        not_found("CUSTOMER")
    if data["customer_id"] != uid:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403,
                       "Customer caller may only create designs for themselves")
    design = stamp_new({
        "customer_id": data["customer_id"],
        "part_number": data["part_number"],
        "tool_type": data["tool_type"],
        "die_class": data["die_class"],
        "cavity_count": data["cavity_count"],
        "design_complexity_score": data["design_complexity_score"],
        "revision_number": 1,
        "supersedes_design_id": None,
        "quoted_count": 0,
        "status": "DRAFT",
    })
    STORE.designs[design["id"]] = design
    return created(ser_design(design))


@bp.route("/tool-designs", methods=["GET"])
@endpoint(roles=None)
def list_designs(uid, role):
    items = sort_created(list(STORE.designs.values()))
    items = filter_eq(items, "customer_id", request.args.get("customer_id"))
    items = filter_eq(items, "status", request.args.get("status"))
    items = filter_eq(items, "part_number", request.args.get("part_number"))
    page, meta = paginate(items)
    return ok_list([ser_design(d) for d in page], meta)


@bp.route("/tool-designs/<designId>", methods=["GET"])
@endpoint(roles=None)
def get_design(uid, role, designId):
    design = STORE.designs.get(designId)
    if design is None:
        not_found("TOOL_DESIGN")
    return ok(ser_design(design))


@bp.route("/tool-designs/<designId>/submit", methods=["POST"])
@endpoint(roles=["Customer"])
def submit_design(uid, role, designId):
    validate_payload(get_body(), [])
    design = STORE.designs.get(designId)
    if design is None:
        not_found("TOOL_DESIGN")
    if design["customer_id"] != uid:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403,
                       "Only the owning customer may submit the design")
    if design["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Design must be DRAFT to submit")
    design["status"] = "SUBMITTED"
    bump(design)
    return ok(ser_design(design))


@bp.route("/tool-designs/<designId>/review", methods=["POST"])
@endpoint(roles=["ToolingEngineer"])
def review_design(uid, role, designId):
    data = validate_payload(get_body(), [
        ("decision", "enum", True, {"values": {"RELEASED", "REJECTED"}}),
        ("review_note", "str", False),
    ])
    design = STORE.designs.get(designId)
    if design is None:
        not_found("TOOL_DESIGN")
    if design["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Design must be SUBMITTED to review")
    if data["decision"] == "REJECTED":
        design["status"] = "DRAFT"
        bump(design)
        return ok(ser_design(design))
    # RELEASED: at most one live revision per (customer_id, part_number).
    for other in STORE.designs.values():
        if (other["id"] != design["id"]
                and other["customer_id"] == design["customer_id"]
                and other["part_number"] == design["part_number"]
                and other["status"] == "RELEASED"
                and other["id"] != design["supersedes_design_id"]):
            raise ApiError("ERR_DUPLICATE_RELEASED_DESIGN", 409,
                           "Another design for this part is already RELEASED")
    # Revision-chain cascade: the superseded design leaves RELEASED.
    if design["supersedes_design_id"]:
        prev = STORE.designs.get(design["supersedes_design_id"])
        if prev is not None and prev["status"] == "RELEASED":
            prev["status"] = "SUPERSEDED"
            bump(prev)
    design["status"] = "RELEASED"
    bump(design)
    return ok(ser_design(design))


@bp.route("/tool-designs/<designId>/revise", methods=["POST"])
@endpoint(roles=["ToolingEngineer"])
def revise_design(uid, role, designId):
    data = validate_payload(get_body(), [
        ("cavity_count", "int", False, {"min": 1, "max": 64}),
        ("design_complexity_score", "int", False, {"min": 1, "max": 20}),
        ("die_class", "enum", False, {"values": DIE_CLASSES}),
        ("tool_type", "enum", False, {"values": TOOL_TYPES}),
    ])
    design = STORE.designs.get(designId)
    if design is None:
        not_found("TOOL_DESIGN")
    if design["status"] not in ("RELEASED", "SUBMITTED"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only a RELEASED or SUBMITTED design may be revised")
    revision = stamp_new({
        "customer_id": design["customer_id"],
        "part_number": design["part_number"],
        "tool_type": data.get("tool_type", design["tool_type"]),
        "die_class": data.get("die_class", design["die_class"]),
        "cavity_count": data.get("cavity_count", design["cavity_count"]),
        "design_complexity_score": data.get("design_complexity_score",
                                            design["design_complexity_score"]),
        "revision_number": design["revision_number"] + 1,
        "supersedes_design_id": design["id"],
        "quoted_count": 0,
        "status": "DRAFT",
    })
    STORE.designs[revision["id"]] = revision
    return created(ser_design(revision))
