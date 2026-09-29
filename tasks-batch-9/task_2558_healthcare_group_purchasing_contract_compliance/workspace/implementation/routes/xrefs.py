"""Item cross-references (PRD section 3.5)."""

from decimal import Decimal

from flask import Blueprint

from db import db, ordered
from enums import MATCH_TYPES, XREF_STATUSES
from errors import ApiError
from middleware import (
    ALL_ROLES,
    CONTRACT_MANAGER,
    MEMBER_MATERIALS_MANAGER,
    authenticate,
    require_member_scope,
)
from response import list_response, object_response
from services.lookup import get_xref, resolve_body_fks
from validation import (
    bad,
    body_json,
    field_decimal,
    field_enum,
    field_string,
    paginate,
    pagination,
    query_enum,
    query_string,
)

xrefs_bp = Blueprint("xrefs", __name__)


def _duplicate_guard(member_id, contract_item_id, member_item_number, ignore_id=None):
    """No member may hold two APPROVED mappings on either side of the pair."""
    for existing in db.xrefs.values():
        if existing["status"] != "APPROVED":
            continue
        if ignore_id is not None and existing["id"] == ignore_id:
            continue
        if existing["member_id"] != member_id:
            continue
        if (
            existing["contract_item_id"] == contract_item_id
            or existing["member_item_number"] == member_item_number
        ):
            raise ApiError(
                "ERR_DUPLICATE_XREF",
                "An APPROVED cross-reference already covers this pairing.",
            )


@xrefs_bp.route("/gpo/item-cross-references", methods=["POST"])
def create_xref():
    acting_user_id, _ = authenticate((MEMBER_MATERIALS_MANAGER,))
    body = body_json()
    declared_member_id = body.get("member_id")
    if isinstance(declared_member_id, str) and declared_member_id:
        require_member_scope(acting_user_id, declared_member_id)

    resolved = resolve_body_fks(body, ("member_id", "contract_item_id"))
    member = resolved["member_id"]
    item = resolved["contract_item_id"]
    if member is None:
        raise bad("Field 'member_id' is required.")
    if item is None:
        raise bad("Field 'contract_item_id' is required.")

    member_item_number = field_string(body, "member_item_number", 1, 40)
    match_type = field_enum(body, "match_type", MATCH_TYPES)
    conversion_factor = field_decimal(
        body, "conversion_factor", minimum=None, maximum=None, scale=4
    )
    if conversion_factor <= Decimal("0"):
        raise bad("conversion_factor must be greater than zero.")

    contract = db.contracts.get(item["contract_id"])
    if contract is None or contract["status"] != "ACTIVE":
        raise ApiError(
            "ERR_CONTRACT_NOT_ACTIVE",
            "Cross-references may only be proposed on an ACTIVE contract.",
        )
    if item["status"] != "ACTIVE":
        raise ApiError(
            "ERR_CONTRACT_ITEM_NOT_ACTIVE",
            "A delisted catalog item cannot be cross-referenced.",
        )
    if not any(
        entry["member_item_number"] == member_item_number
        for entry in member["item_master"]
    ):
        raise ApiError(
            "ERR_MEMBER_ITEM_NOT_IN_MASTER",
            "member_item_number is not in the member's current item master.",
        )
    _duplicate_guard(member["id"], item["id"], member_item_number)

    row = db.new_row()
    row.update(
        {
            "member_id": member["id"],
            "contract_item_id": item["id"],
            "member_item_number": member_item_number,
            "match_type": match_type,
            "conversion_factor": conversion_factor,
            "status": "PROPOSED",
            "approved_by_user_id": None,
            "reject_note": None,
        }
    )
    db.xrefs[row["id"]] = row
    return object_response(row, 201)


@xrefs_bp.route("/gpo/item-cross-references/<xref_id>", methods=["GET"])
def read_xref(xref_id):
    authenticate(ALL_ROLES)
    return object_response(get_xref(xref_id))


@xrefs_bp.route("/gpo/item-cross-references", methods=["GET"])
def list_xrefs():
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    member_id = query_string("member_id")
    contract_item_id = query_string("contract_item_id")
    status = query_enum("status", XREF_STATUSES)
    rows = [
        row
        for row in ordered(db.xrefs.values())
        if (member_id is None or row["member_id"] == member_id)
        and (contract_item_id is None or row["contract_item_id"] == contract_item_id)
        and (status is None or row["status"] == status)
    ]
    page, total = paginate(rows, limit, offset)
    return list_response(page, limit, offset, total)


@xrefs_bp.route("/gpo/item-cross-references/<xref_id>/approve", methods=["POST"])
def approve_xref(xref_id):
    acting_user_id, _ = authenticate((CONTRACT_MANAGER,))
    xref = get_xref(xref_id)
    if xref["status"] != "PROPOSED":
        raise ApiError("ERR_XREF_NOT_PROPOSED", "Only a PROPOSED cross-reference can be approved.")
    # The two-sided uniqueness test is re-evaluated at approval time.
    _duplicate_guard(
        xref["member_id"],
        xref["contract_item_id"],
        xref["member_item_number"],
        ignore_id=xref["id"],
    )
    xref["status"] = "APPROVED"
    xref["approved_by_user_id"] = acting_user_id
    db.touch(xref)
    return object_response(xref)


@xrefs_bp.route("/gpo/item-cross-references/<xref_id>/reject", methods=["POST"])
def reject_xref(xref_id):
    authenticate((CONTRACT_MANAGER,))
    xref = get_xref(xref_id)
    body = body_json()
    reason = field_string(body, "reason", 0, None, required=False, default=None)
    if xref["status"] != "PROPOSED":
        raise ApiError("ERR_XREF_NOT_PROPOSED", "Only a PROPOSED cross-reference can be rejected.")
    xref["status"] = "REJECTED"
    xref["reject_note"] = reason
    db.touch(xref)
    return object_response(xref)
