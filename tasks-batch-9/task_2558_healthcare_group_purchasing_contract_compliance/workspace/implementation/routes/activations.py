"""Price activations (PRD section 3.6)."""

from flask import Blueprint

from db import db, ordered
from enums import ACTIVATION_ORIGINS, ACTIVATION_STATUSES, ACTIVATION_TYPES
from errors import ApiError
from middleware import (
    ALL_ROLES,
    CONTRACT_MANAGER,
    MEMBER_MATERIALS_MANAGER,
    authenticate,
    require_member_scope,
)
from response import list_response, object_response
from services.calc import (
    approved_xref_for_item,
    closed_overlap,
    closed_within,
    contract_has_convert_endorsement,
    derive_activation_price,
    find_tier,
)
from services.cascade import recompute_item_activation_count
from services.lookup import get_activation, resolve_body_fks
from validation import (
    bad,
    body_json,
    field_date,
    field_enum,
    field_int,
    field_string,
    paginate,
    pagination,
    query_enum,
    query_string,
)

activations_bp = Blueprint("activations", __name__)

PRICEABLE_ELECTION_STATUSES = ("ELECTED", "ACTIVE", "REQUAL_REVIEW")
OVERLAP_STATUSES = ("DRAFT", "ENDORSED", "APPROVED", "ACTIVE")


@activations_bp.route("/gpo/price-activations", methods=["POST"])
def create_activation():
    acting_user_id, role = authenticate((CONTRACT_MANAGER, MEMBER_MATERIALS_MANAGER))
    body = body_json()
    resolved = resolve_body_fks(body, ("contract_item_id", "commitment_id"))
    item = resolved["contract_item_id"]
    commitment = resolved["commitment_id"]
    if item is None:
        raise bad("Field 'contract_item_id' is required.")
    if commitment is None:
        raise bad("Field 'commitment_id' is required.")

    activation_type = field_enum(body, "activation_type", ACTIVATION_TYPES)
    effective_from = field_date(body, "effective_from")
    effective_to = field_date(body, "effective_to")
    requested_price_cents = field_int(
        body, "requested_price_cents", minimum=1, required=False, default=None
    )

    # The track decides who may file the request at all.
    if activation_type == "TIER_PRICE" and role != CONTRACT_MANAGER:
        raise ApiError(
            "ERR_ROLE_NOT_PERMITTED", "Only a ContractManager may file a TIER_PRICE activation."
        )
    if activation_type == "LOCAL_EXCEPTION" and role != MEMBER_MATERIALS_MANAGER:
        raise ApiError(
            "ERR_ROLE_NOT_PERMITTED",
            "Only a MemberMaterialsManager may file a LOCAL_EXCEPTION activation.",
        )
    if activation_type == "LOCAL_EXCEPTION":
        require_member_scope(acting_user_id, commitment["member_id"])

    if commitment["election_status"] not in PRICEABLE_ELECTION_STATUSES:
        raise ApiError(
            "ERR_COMMITMENT_NOT_ACTIVE", "A TERMINATED commitment can never be priced."
        )
    if item["contract_id"] != commitment["contract_id"]:
        raise ApiError(
            "ERR_ITEM_CONTRACT_MISMATCH",
            "The catalog item belongs to a different contract than the commitment.",
        )
    contract = db.contracts.get(commitment["contract_id"])
    if contract is None or contract["status"] != "ACTIVE":
        raise ApiError(
            "ERR_CONTRACT_NOT_ACTIVE", "Prices can only be filed on an ACTIVE contract."
        )
    if item["status"] != "ACTIVE":
        raise ApiError(
            "ERR_CONTRACT_ITEM_NOT_ACTIVE", "A delisted catalog item cannot be priced."
        )

    tier_code = commitment["current_tier_code"] or contract["default_tier_code"]
    tier = find_tier(contract, tier_code)
    if tier is None:
        raise ApiError(
            "ERR_TIER_CODE_UNKNOWN",
            "The governing tier code names no entry of the contract's tier ladder.",
        )
    if effective_to < effective_from:
        raise ApiError(
            "ERR_EFFECTIVE_WINDOW_INVALID",
            "effective_to must not precede effective_from.",
        )
    if not closed_within(
        effective_from, effective_to, contract["effective_from"], contract["effective_to"]
    ):
        raise ApiError(
            "ERR_PERIOD_OUTSIDE_CONTRACT_TERM",
            "The price window must sit wholly inside the contract term.",
        )
    for existing in db.activations.values():
        if existing["commitment_id"] != commitment["id"]:
            continue
        if existing["contract_item_id"] != item["id"]:
            continue
        if existing["activation_type"] != activation_type:
            continue
        if existing["status"] not in OVERLAP_STATUSES:
            continue
        if closed_overlap(
            effective_from, effective_to, existing["effective_from"], existing["effective_to"]
        ):
            raise ApiError(
                "ERR_ACTIVATION_PERIOD_OVERLAP",
                "A live activation of the same type already covers part of this window.",
            )
    if activation_type == "LOCAL_EXCEPTION" and requested_price_cents is None:
        raise ApiError(
            "ERR_REQUESTED_PRICE_REQUIRED",
            "A LOCAL_EXCEPTION must carry requested_price_cents.",
        )
    if activation_type == "TIER_PRICE" and requested_price_cents is not None:
        raise ApiError(
            "ERR_REQUESTED_PRICE_NOT_ALLOWED",
            "A TIER_PRICE activation must not carry requested_price_cents.",
        )

    computed_price_cents, price_clamped = derive_activation_price(
        item, tier, activation_type, requested_price_cents
    )
    row = db.new_row()
    row.update(
        {
            "commitment_id": commitment["id"],
            "contract_item_id": item["id"],
            "activation_type": activation_type,
            "requested_price_cents": requested_price_cents,
            "effective_from": effective_from,
            "effective_to": effective_to,
            "tier_code_at_activation": tier_code,
            "computed_price_cents": computed_price_cents,
            "price_clamped": price_clamped,
            "status": "DRAFT",
            "endorsed_by_user_id": None,
            "approved_by_user_id": None,
            "superseded_by_activation_id": None,
            "replaces_activation_id": None,
            "origin": "REQUEST",
            "deny_note": None,
        }
    )
    db.activations[row["id"]] = row
    return object_response(row, 201)


@activations_bp.route("/gpo/price-activations/<activation_id>", methods=["GET"])
def read_activation(activation_id):
    authenticate(ALL_ROLES)
    return object_response(get_activation(activation_id))


@activations_bp.route("/gpo/price-activations", methods=["GET"])
def list_activations():
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    commitment_id = query_string("commitment_id")
    contract_item_id = query_string("contract_item_id")
    superseded_by = query_string("superseded_by_activation_id")
    replaces = query_string("replaces_activation_id")
    status = query_enum("status", ACTIVATION_STATUSES)
    activation_type = query_enum("activation_type", ACTIVATION_TYPES)
    origin = query_enum("origin", ACTIVATION_ORIGINS)
    rows = [
        row
        for row in ordered(db.activations.values())
        if (commitment_id is None or row["commitment_id"] == commitment_id)
        and (contract_item_id is None or row["contract_item_id"] == contract_item_id)
        and (superseded_by is None or row["superseded_by_activation_id"] == superseded_by)
        and (replaces is None or row["replaces_activation_id"] == replaces)
        and (status is None or row["status"] == status)
        and (activation_type is None or row["activation_type"] == activation_type)
        and (origin is None or row["origin"] == origin)
    ]
    page, total = paginate(rows, limit, offset)
    return list_response(page, limit, offset, total)


def _requalification_bar(activation):
    commitment = db.commitments.get(activation["commitment_id"])
    if commitment is not None and commitment["election_status"] == "REQUAL_REVIEW":
        raise ApiError(
            "ERR_REQUALIFICATION_IN_PROGRESS",
            "The commitment is in requalification review; the exception must wait.",
        )
    return commitment


@activations_bp.route("/gpo/price-activations/<activation_id>/endorse", methods=["POST"])
def endorse_activation(activation_id):
    acting_user_id, _ = authenticate((CONTRACT_MANAGER,))
    activation = get_activation(activation_id)
    if activation["status"] != "DRAFT" or activation["activation_type"] != "LOCAL_EXCEPTION":
        raise ApiError(
            "ERR_INVALID_ACTIVATION_STATE",
            "Only a DRAFT LOCAL_EXCEPTION activation can be endorsed.",
        )
    _requalification_bar(activation)
    activation["status"] = "ENDORSED"
    activation["endorsed_by_user_id"] = acting_user_id
    db.touch(activation)
    return object_response(activation)


@activations_bp.route("/gpo/price-activations/<activation_id>/approve", methods=["POST"])
def approve_activation(activation_id):
    acting_user_id, _ = authenticate((CONTRACT_MANAGER,))
    activation = get_activation(activation_id)
    if activation["status"] != "ENDORSED" or activation["activation_type"] != "LOCAL_EXCEPTION":
        raise ApiError(
            "ERR_INVALID_ACTIVATION_STATE",
            "Only an ENDORSED LOCAL_EXCEPTION activation can be approved.",
        )
    if str(acting_user_id) == str(activation["endorsed_by_user_id"]):
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            "The endorser of a local exception may not also approve it.",
        )
    _requalification_bar(activation)
    activation["status"] = "APPROVED"
    activation["approved_by_user_id"] = acting_user_id
    db.touch(activation)
    return object_response(activation)


@activations_bp.route("/gpo/price-activations/<activation_id>/activate", methods=["POST"])
def activate_activation(activation_id):
    authenticate((CONTRACT_MANAGER,))
    activation = get_activation(activation_id)
    is_tier_draft = (
        activation["activation_type"] == "TIER_PRICE" and activation["status"] == "DRAFT"
    )
    is_exception_approved = (
        activation["activation_type"] == "LOCAL_EXCEPTION"
        and activation["status"] == "APPROVED"
    )
    if not (is_tier_draft or is_exception_approved):
        raise ApiError(
            "ERR_INVALID_ACTIVATION_STATE",
            "A TIER_PRICE activates from DRAFT; a LOCAL_EXCEPTION activates from APPROVED.",
        )
    commitment = db.commitments.get(activation["commitment_id"])
    contract = (
        db.contracts.get(commitment["contract_id"]) if commitment is not None else None
    )
    if contract is None or contract["status"] != "ACTIVE":
        raise ApiError(
            "ERR_CONTRACT_NOT_ACTIVE", "The contract must still be ACTIVE to activate a price."
        )
    item = db.contract_items.get(activation["contract_item_id"])
    if item is not None and item["requires_evidence"]:
        if not contract_has_convert_endorsement(contract):
            raise ApiError(
                "ERR_CLINICAL_REVIEW_NOT_ENDORSED",
                "This item needs an ENDORSED review recommending CONVERT before pricing.",
            )
    if (
        approved_xref_for_item(commitment["member_id"], activation["contract_item_id"])
        is None
    ):
        raise ApiError(
            "ERR_XREF_NOT_APPROVED",
            "An APPROVED cross-reference must link the member to this catalog item.",
        )
    activation["status"] = "ACTIVE"
    db.touch(activation)
    if item is not None:
        recompute_item_activation_count(item)
    return object_response(activation)


@activations_bp.route("/gpo/price-activations/<activation_id>/deny", methods=["POST"])
def deny_activation(activation_id):
    authenticate((CONTRACT_MANAGER,))
    activation = get_activation(activation_id)
    body = body_json()
    reason = field_string(body, "reason", 0, None, required=False, default=None)
    if (
        activation["activation_type"] != "LOCAL_EXCEPTION"
        or activation["status"] not in ("DRAFT", "ENDORSED")
    ):
        raise ApiError(
            "ERR_INVALID_ACTIVATION_STATE",
            "Only a DRAFT or ENDORSED LOCAL_EXCEPTION activation can be denied.",
        )
    activation["status"] = "DENIED"
    activation["deny_note"] = reason
    db.touch(activation)
    return object_response(activation)
