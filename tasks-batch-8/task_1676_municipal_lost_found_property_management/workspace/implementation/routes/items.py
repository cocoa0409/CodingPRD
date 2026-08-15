"""Found-property items: intake, staff reads, public search, and item actions
(publish/unpublish/move/dispose/release/refer) — PRD 3.2, 3.3, 3.5, 3.6."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error, ERR_INVALID_STATE, ERR_PROGRAM_INACTIVE, ERR_LOCATION_INACTIVE,
    ERR_STORAGE_CAPACITY_EXCEEDED, ERR_SECURE_STORAGE_REQUIRED,
    ERR_NO_RETENTION_POLICY, ERR_DISPOSAL_METHOD_MISMATCH,
    ERR_IDENTIFICATION_NOT_LISTABLE, ERR_SEGREGATION_OF_DUTIES, ERR_NOT_FOUND,
)
from middleware import authorized, STAFF_ROLES
from response import success_object, success_list
from services import core
from util import parse_dt, fmt_auto, now_ms
from validate import (
    get_body, req_str, opt_str, req_int, req_enum, req_datetime,
    require_path, require_ref, pagination_params, opt_query_enum, opt_query_str,
    paginate,
)

bp = Blueprint("items", __name__)


# ---------------------------------------------------------------------------
# Intake
# ---------------------------------------------------------------------------

@bp.post("/items")
def create_item():
    body = get_body()
    program_id = req_str(body, "program_id")
    storage_location_id = req_str(body, "storage_location_id")
    category = req_enum(body, "category", core.CATEGORIES)
    declared_value_cents = req_int(body, "declared_value_cents", minimum=0)
    description = req_str(body, "description")
    found_at = req_datetime(body, "found_at")
    found_location = req_str(body, "found_location")
    external_ref = opt_str(body, "external_ref", None)
    # NB: any client-sent value_tier is ignored, not validated (PRD 3.2).
    caller = authorized({"IntakeOfficer"})
    program = require_ref("programs", program_id, "program_id")
    location = require_ref("storage_locations", storage_location_id, "storage_location_id")

    tier = core.value_tier_of(declared_value_cents)
    # Fixed intake check chain (PRD 3.2): program active -> location active ->
    # capacity -> secure storage -> retention policy.
    if not program["active"]:
        raise_error(ERR_PROGRAM_INACTIVE, "owning program is inactive")
    if not location["active"]:
        raise_error(ERR_LOCATION_INACTIVE, "storage location is inactive")
    if core.occupied_slots(location["id"]) + 1 > location["capacity_slots"]:
        raise_error(ERR_STORAGE_CAPACITY_EXCEEDED, "storage location is at capacity")
    if tier == "HIGH" and not location["supports_high_value"]:
        raise_error(ERR_SECURE_STORAGE_REQUIRED,
                    "HIGH-tier items require a secure storage location")
    policy = core.active_policy_for(program_id, category, tier)
    if policy is None:
        raise_error(ERR_NO_RETENTION_POLICY,
                    "no active retention policy for (program_id, category, value_tier)")
    deadline = core.compute_retention_deadline(
        found_at, policy["retention_days"], program["program_type"]
    )
    rec = core.new_record("items", {
        "program_id": program_id,
        "storage_location_id": storage_location_id,
        "category": category,
        "declared_value_cents": declared_value_cents,
        "value_tier": tier,
        "is_identification": category == "ID_DOCUMENT",
        "description": description,
        "found_at": fmt_auto(parse_dt(found_at)),
        "found_location": found_location,
        "external_ref": external_ref,
        "retention_policy_id": policy["id"],
        "retention_deadline": deadline,
        "status": "STORED",
        "unsold_count": 0,
        "pending_disposal_method": None,
        "intake_officer_id": caller.user_id,
    })
    return success_object(rec, 201)


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------

@bp.get("/items")
def list_items():
    limit, offset = pagination_params()
    program_id = opt_query_str("program_id")
    storage_location_id = opt_query_str("storage_location_id")
    retention_policy_id = opt_query_str("retention_policy_id")
    status = opt_query_enum("status", core.ITEM_STATUSES)
    category = opt_query_enum("category", core.CATEGORIES)
    value_tier = opt_query_enum("value_tier", core.VALUE_TIERS)
    authorized(STAFF_ROLES)
    recs = list(db["items"].values())
    if program_id is not None:
        recs = [r for r in recs if r["program_id"] == program_id]
    if storage_location_id is not None:
        recs = [r for r in recs if r["storage_location_id"] == storage_location_id]
    if retention_policy_id is not None:
        recs = [r for r in recs if r["retention_policy_id"] == retention_policy_id]
    if status is not None:
        recs = [r for r in recs if r["status"] == status]
    if category is not None:
        recs = [r for r in recs if r["category"] == category]
    if value_tier is not None:
        recs = [r for r in recs if r["value_tier"] == value_tier]
    page, total = paginate(recs, limit, offset)
    return success_list(page, total, limit, offset)


@bp.get("/items/<item_id>")
def get_item(item_id):
    authorized(STAFF_ROLES)
    rec = require_path("items", item_id)
    return success_object(rec)


@bp.get("/public/items")
def public_items():
    """Public searchable inventory (PRD 3.3): LISTED, non-identification only,
    narrow projection."""
    limit, offset = pagination_params()
    category = opt_query_enum("category", core.CATEGORIES)
    keyword = opt_query_str("keyword")
    program_id = opt_query_str("program_id")
    authorized({"PublicUser", "Claimant"})
    recs = [
        r for r in db["items"].values()
        if r["status"] == "LISTED" and not r["is_identification"]
    ]
    if category is not None:
        recs = [r for r in recs if r["category"] == category]
    if keyword is not None:
        kw = keyword.lower()
        recs = [r for r in recs if kw in r["description"].lower()]
    if program_id is not None:
        recs = [r for r in recs if r["program_id"] == program_id]
    page, total = paginate(recs, limit, offset)
    projection = [
        {k: r[k] for k in ("id", "category", "description", "found_at",
                           "found_location", "program_id")}
        for r in page
    ]
    return success_list(projection, total, limit, offset)


# ---------------------------------------------------------------------------
# Publish / unpublish
# ---------------------------------------------------------------------------

@bp.post("/items/<item_id>/publish")
def publish_item(item_id):
    authorized({"IntakeOfficer"})
    item = require_path("items", item_id)
    if item["status"] != "STORED":
        raise_error(ERR_INVALID_STATE, "only a STORED item can be published")
    if item["is_identification"]:
        raise_error(ERR_IDENTIFICATION_NOT_LISTABLE,
                    "identification items can never be publicly listed")
    program = db["programs"].get(item["program_id"])
    if program is None or not program["active"]:
        raise_error(ERR_PROGRAM_INACTIVE, "owning program is inactive")
    item["status"] = "LISTED"
    core.touch(item)
    return success_object(item)


@bp.post("/items/<item_id>/unpublish")
def unpublish_item(item_id):
    authorized({"IntakeOfficer"})
    item = require_path("items", item_id)
    if item["status"] != "LISTED":
        raise_error(ERR_INVALID_STATE, "only a LISTED item can be unpublished")
    item["status"] = "STORED"
    core.touch(item)
    return success_object(item)


# ---------------------------------------------------------------------------
# Move / dispose / release / refer
# ---------------------------------------------------------------------------

@bp.post("/items/<item_id>/move")
def move_item(item_id):
    body = get_body()
    dest_id = req_str(body, "storage_location_id")
    authorized({"PropertyCustodian"})
    item = require_path("items", item_id)
    dest = require_ref("storage_locations", dest_id, "storage_location_id")
    # Same trio of location checks as intake, in the same order (PRD 3.2).
    if not dest["active"]:
        raise_error(ERR_LOCATION_INACTIVE, "destination location is inactive")
    occupied = core.occupied_slots(dest["id"])
    if item["storage_location_id"] == dest["id"] and item["status"] in core.OCCUPYING_STATUSES:
        occupied -= 1  # the item's own slot is being vacated
    if occupied + 1 > dest["capacity_slots"]:
        raise_error(ERR_STORAGE_CAPACITY_EXCEEDED, "destination location is at capacity")
    if item["value_tier"] == "HIGH" and not dest["supports_high_value"]:
        raise_error(ERR_SECURE_STORAGE_REQUIRED,
                    "HIGH-tier items require a secure storage location")
    item["storage_location_id"] = dest["id"]
    core.touch(item)
    return success_object(item)


@bp.post("/items/<item_id>/dispose")
def dispose_item(item_id):
    body = get_body()
    method = req_enum(body, "method", core.DISPOSAL_METHODS)
    authorized({"PropertyCustodian"})
    item = require_path("items", item_id)
    if item["status"] != "DISPOSAL_PENDING":
        raise_error(ERR_INVALID_STATE, "only a DISPOSAL_PENDING item can be disposed")
    if method != item["pending_disposal_method"]:
        raise_error(ERR_DISPOSAL_METHOD_MISMATCH,
                    "method must equal the item's pending_disposal_method")
    item["status"] = "DISPOSED" if method == "DESTRUCTION" else "DONATED"
    core.touch(item)
    return success_object(item)


@bp.post("/items/<item_id>/release")
def release_item(item_id):
    body = get_body()
    handover_method = req_enum(body, "handover_method", core.HANDOVER_METHODS)
    id_document_ref = req_str(body, "id_document_ref")
    caller = authorized({"ReleaseOfficer"})
    item = require_path("items", item_id)
    if item["status"] != "RELEASE_PENDING":
        raise_error(ERR_INVALID_STATE, "only a RELEASE_PENDING item can be released")
    approved = next(
        (c for c in db["claims"].values()
         if c["item_id"] == item["id"] and c["status"] == "APPROVED"),
        None,
    )
    # Segregation of duties: releaser != intake officer and != approving examiner.
    if caller.user_id == item["intake_officer_id"]:
        raise_error(ERR_SEGREGATION_OF_DUTIES,
                    "release officer may not be the item's intake officer")
    if approved is not None and caller.user_id == approved["examiner_id"]:
        raise_error(ERR_SEGREGATION_OF_DUTIES,
                    "release officer may not be the approving examiner")
    core.new_record("release_records", {
        "item_id": item["id"],
        "claim_id": approved["id"] if approved is not None else None,
        "released_by": caller.user_id,
        "handover_method": handover_method,
        "id_document_ref": id_document_ref,
        "released_at": now_ms(),
    }, with_version=False)
    if approved is not None:
        approved["status"] = "RELEASED"
        core.touch(approved)
    item["status"] = "RELEASED"
    core.touch(item)
    return success_object(item)


@bp.post("/items/<item_id>/refer-to-law-enforcement")
def refer_item(item_id):
    body = get_body()
    agency_name = req_str(body, "agency_name")
    case_number = req_str(body, "case_number")
    caller = authorized({"PoliceLiaison"})
    item = require_path("items", item_id)
    if item["status"] not in ("STORED", "LISTED"):
        raise_error(ERR_INVALID_STATE,
                    "only a STORED or LISTED item can be referred to law enforcement")
    referral = core.new_record("referrals", {
        "item_id": item["id"],
        "agency_name": agency_name,
        "case_number": case_number,
        "status": "REFERRED",
        "referred_by": caller.user_id,
    })
    # Stay every open claim on the item, preserving its prior status (3.6).
    for claim in db["claims"].values():
        if claim["item_id"] == item["id"] and claim["status"] in (
            "SUBMITTED", "UNDER_REVIEW", "INFO_REQUESTED",
        ):
            claim["pre_stay_status"] = claim["status"]
            claim["status"] = "STAYED"
            core.touch(claim)
    item["status"] = "REFERRED_TO_LE"
    core.touch(item)
    return success_object(referral, 201)
