"""Contracts and catalog items (PRD section 3.1)."""

from decimal import Decimal

from flask import Blueprint

from db import db, ordered
from enums import CONTRACT_ITEM_STATUSES, CONTRACT_STATUSES, SHARE_BASES, UOMS
from errors import ApiError
from middleware import ALL_ROLES, COMPLIANCE_ANALYST, CONTRACT_MANAGER, authenticate
from response import list_response, object_response
from services.calc import contract_has_convert_endorsement, derive_default_tier_code
from services.ladders import parse_holdback_ladder, parse_tier_ladder
from services.lookup import get_contract, get_contract_item
from validation import (
    bad,
    body_json,
    field_bool,
    field_date,
    field_decimal,
    field_enum,
    field_int,
    field_string,
    paginate,
    pagination,
    query_enum,
    query_string,
)

contracts_bp = Blueprint("contracts", __name__)


@contracts_bp.route("/gpo/contracts", methods=["POST"])
def create_contract():
    authenticate((CONTRACT_MANAGER,))
    body = body_json()
    contract_code = field_string(body, "contract_code", 1, 40)
    supplier_name = field_string(body, "supplier_name", 1, 120)
    category_code = field_string(body, "category_code", 1, 40)
    effective_from = field_date(body, "effective_from")
    effective_to = field_date(body, "effective_to")
    admin_fee_bps = field_int(body, "admin_fee_bps", 0, 500)
    member_share_bps = field_int(body, "member_share_bps", 0, 10000)
    requires_clinical_review = field_bool(
        body, "requires_clinical_review", required=False, default=True
    )
    share_basis = field_enum(
        body, "share_basis", SHARE_BASES, required=False, default="COLLECTED"
    )
    threshold = field_decimal(
        body,
        "leakage_alert_threshold_pct",
        minimum=Decimal("0.00"),
        maximum=Decimal("100.00"),
        scale=2,
        required=False,
        default=Decimal("15.00"),
    )
    if effective_to <= effective_from:
        raise bad("effective_to must be strictly after effective_from.")
    for existing in db.contracts.values():
        if existing["contract_code"] == contract_code:
            raise bad("contract_code must be globally unique.")
    tiers = parse_tier_ladder(body)
    holdback_tiers = parse_holdback_ladder(body)

    row = db.new_row()
    row.update(
        {
            "contract_code": contract_code,
            "supplier_name": supplier_name,
            "category_code": category_code,
            "effective_from": effective_from,
            "effective_to": effective_to,
            "requires_clinical_review": requires_clinical_review,
            "admin_fee_bps": admin_fee_bps,
            "member_share_bps": member_share_bps,
            "share_basis": share_basis,
            "leakage_alert_threshold_pct": threshold,
            "tiers": tiers,
            "holdback_tiers": holdback_tiers,
            "default_tier_code": derive_default_tier_code(tiers),
            "status": "DRAFT",
            "evidence_endorsed": False,
            "active_commitment_count": 0,
        }
    )
    db.contracts[row["id"]] = row
    return object_response(row, 201)


@contracts_bp.route("/gpo/contracts/<contract_id>", methods=["GET"])
def read_contract(contract_id):
    authenticate(ALL_ROLES)
    return object_response(get_contract(contract_id))


@contracts_bp.route("/gpo/contracts", methods=["GET"])
def list_contracts():
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    status = query_enum("status", CONTRACT_STATUSES)
    category_code = query_string("category_code")
    rows = [
        row
        for row in ordered(db.contracts.values())
        if (status is None or row["status"] == status)
        and (category_code is None or row["category_code"] == category_code)
    ]
    page, total = paginate(rows, limit, offset)
    return list_response(page, limit, offset, total)


@contracts_bp.route("/gpo/contracts/<contract_id>/tiers", methods=["PATCH"])
def replace_tiers(contract_id):
    authenticate((CONTRACT_MANAGER,))
    contract = get_contract(contract_id)
    body = body_json()
    tiers = parse_tier_ladder(body)
    if contract["status"] not in ("DRAFT", "ACTIVE"):
        raise ApiError(
            "ERR_CONTRACT_NOT_ACTIVE",
            "A suspended contract's tier ladder can no longer be replaced.",
        )
    if contract["status"] == "ACTIVE" and not contract_has_convert_endorsement(contract):
        raise ApiError(
            "ERR_CLINICAL_REVIEW_NOT_ENDORSED",
            "A category conversion requires an ENDORSED review recommending CONVERT.",
        )
    contract["tiers"] = tiers
    contract["default_tier_code"] = derive_default_tier_code(tiers)
    db.touch(contract)
    return object_response(contract)


@contracts_bp.route("/gpo/contracts/<contract_id>/activate", methods=["POST"])
def activate_contract(contract_id):
    authenticate((CONTRACT_MANAGER,))
    contract = get_contract(contract_id)
    if contract["status"] != "DRAFT":
        raise ApiError("ERR_CONTRACT_NOT_ACTIVE", "Only a DRAFT contract can be activated.")
    if contract["requires_clinical_review"]:
        if not contract["evidence_endorsed"] or not contract_has_convert_endorsement(contract):
            raise ApiError(
                "ERR_CLINICAL_REVIEW_NOT_ENDORSED",
                "Activation requires an ENDORSED review recommending CONVERT.",
            )
    contract["status"] = "ACTIVE"
    db.touch(contract)
    return object_response(contract)


@contracts_bp.route("/gpo/contracts/<contract_id>/suspend", methods=["POST"])
def suspend_contract(contract_id):
    authenticate((COMPLIANCE_ANALYST,))
    contract = get_contract(contract_id)
    body = body_json()
    field_string(body, "reason", 0, None, required=False, default=None)
    if contract["status"] != "ACTIVE":
        raise ApiError("ERR_CONTRACT_NOT_ACTIVE", "Only an ACTIVE contract can be suspended.")
    contract["status"] = "SUSPENDED"
    db.touch(contract)
    return object_response(contract)


# -- catalog items -----------------------------------------------------------


@contracts_bp.route("/gpo/contracts/<contract_id>/items", methods=["POST"])
def create_contract_item(contract_id):
    authenticate((CONTRACT_MANAGER,))
    contract = get_contract(contract_id)
    body = body_json()
    vendor_item_number = field_string(body, "vendor_item_number", 1, 40)
    item_description = field_string(body, "item_description", 1, 200)
    uom = field_enum(body, "uom", UOMS)
    units_per_uom = field_int(body, "units_per_uom", minimum=1)
    base_price_cents = field_int(body, "base_price_cents", minimum=1)
    floor_price_cents = field_int(body, "floor_price_cents", minimum=0)
    requires_evidence = field_bool(body, "requires_evidence", required=False, default=False)
    if floor_price_cents > base_price_cents:
        raise bad("floor_price_cents must not exceed base_price_cents.")
    for existing in db.contract_items.values():
        if (
            existing["contract_id"] == contract["id"]
            and existing["vendor_item_number"] == vendor_item_number
        ):
            raise bad("vendor_item_number must be unique within the contract.")

    row = db.new_row()
    row.update(
        {
            "contract_id": contract["id"],
            "vendor_item_number": vendor_item_number,
            "item_description": item_description,
            "uom": uom,
            "units_per_uom": units_per_uom,
            "base_price_cents": base_price_cents,
            "floor_price_cents": floor_price_cents,
            "requires_evidence": requires_evidence,
            "status": "ACTIVE",
            "active_activation_count": 0,
        }
    )
    db.contract_items[row["id"]] = row
    return object_response(row, 201)


@contracts_bp.route("/gpo/contract-items", methods=["GET"])
def list_contract_items():
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    status = query_enum("status", CONTRACT_ITEM_STATUSES)
    contract_id = query_string("contract_id")
    rows = [
        row
        for row in ordered(db.contract_items.values())
        if (status is None or row["status"] == status)
        and (contract_id is None or row["contract_id"] == contract_id)
    ]
    page, total = paginate(rows, limit, offset)
    return list_response(page, limit, offset, total)


@contracts_bp.route("/gpo/contract-items/<contract_item_id>", methods=["GET"])
def read_contract_item(contract_item_id):
    authenticate(ALL_ROLES)
    return object_response(get_contract_item(contract_item_id))


@contracts_bp.route("/gpo/contract-items/<contract_item_id>/base-price", methods=["PATCH"])
def reprice_contract_item(contract_item_id):
    authenticate((CONTRACT_MANAGER,))
    item = get_contract_item(contract_item_id)
    body = body_json()
    base_price_cents = field_int(body, "base_price_cents")
    expected_contract_version = field_int(body, "expected_contract_version")
    contract = db.contracts.get(item["contract_id"])
    if contract is None or expected_contract_version != contract["version"]:
        raise ApiError(
            "ERR_STALE_CONTRACT_VERSION",
            "expected_contract_version does not match the contract's current version.",
        )
    if base_price_cents <= 0 or base_price_cents < item["floor_price_cents"]:
        raise ApiError(
            "ERR_BASE_PRICE_BELOW_FLOOR",
            "base_price_cents must be a positive integer not below floor_price_cents.",
        )
    item["base_price_cents"] = base_price_cents
    db.touch(item)
    db.touch(contract)
    return object_response(item)


@contracts_bp.route("/gpo/contract-items/<contract_item_id>/delist", methods=["POST"])
def delist_contract_item(contract_item_id):
    authenticate((CONTRACT_MANAGER,))
    item = get_contract_item(contract_item_id)
    body = body_json()
    field_string(body, "reason", 0, None, required=False, default=None)
    if item["status"] != "ACTIVE":
        raise ApiError(
            "ERR_CONTRACT_ITEM_NOT_ACTIVE", "Only an ACTIVE catalog item can be delisted."
        )
    item["status"] = "DELISTED"
    db.touch(item)
    return object_response(item)
