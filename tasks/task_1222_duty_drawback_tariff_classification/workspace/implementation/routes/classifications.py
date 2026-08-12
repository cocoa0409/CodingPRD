"""HTS classification endpoints: create, review loop, supersede (PRD §3.2)."""
from flask import Blueprint, request

from calc import mint_entity, touch
from db import STORE
from errors import (
    ERR_ALREADY_TERMINAL,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_STALE_VERSION,
    raise_err,
)
from middleware import (
    authenticate,
    get_body,
    opt_bool,
    opt_int,
    req_enum,
    req_int,
    req_str,
    require_client_scope,
    require_role,
)
from response import paginate, success_object
from serializers import serialize, sorted_by_creation

bp = Blueprint("classifications", __name__)

ALL_ROLES = {"FirmAdmin", "Analyst", "LicensedBroker", "ComplianceManager", "ClientContact"}
STATUSES = {"DRAFT", "IN_REVIEW", "CERTIFIED", "SUPERSEDED"}


def get_classification_or_404(classification_id):
    cls = STORE["classifications"].get(classification_id)
    if cls is None:
        raise_err(ERR_NOT_FOUND, f"Classification {classification_id} not found")
    return cls


def _derive_first_sale(cls):
    price = cls["first_sale_price_cents"]
    cls["first_sale_eligible"] = (
        cls["bona_fide_sale"]
        and cls["arms_length"]
        and cls["clearly_destined_us"]
        and price is not None
        and price < cls["declared_unit_value_cents"]
    )
    cls["appraised_unit_value_cents"] = (
        price if cls["first_sale_eligible"] else cls["declared_unit_value_cents"]
    )


def _read_classification_fields(body):
    """Shared field parsing for create and supersede payloads."""
    fields = {
        "product_sku": req_str(body, "product_sku"),
        "hts_code": req_str(body, "hts_code"),
        "country_of_origin": req_str(body, "country_of_origin"),
        "duty_rate_bps": req_int(body, "duty_rate_bps", minimum=0),
        "declared_unit_value_cents": req_int(body, "declared_unit_value_cents", minimum=1),
        "first_sale_price_cents": opt_int(body, "first_sale_price_cents", minimum=1),
        "bona_fide_sale": opt_bool(body, "bona_fide_sale"),
        "arms_length": opt_bool(body, "arms_length"),
        "clearly_destined_us": opt_bool(body, "clearly_destined_us"),
    }
    return fields


@bp.route("/customs/classifications", methods=["POST"])
def create_classification():
    _, role = authenticate()
    require_role(role, {"Analyst"})
    body = get_body()
    client_id = req_str(body, "client_id")
    fields = _read_classification_fields(body)
    client = STORE["clients"].get(client_id)
    if client is None:
        raise_err(ERR_NOT_FOUND, f"Client {client_id} not found")
    cls = mint_entity()
    cls.update(fields)
    cls.update({
        "client_id": client_id,
        "supersedes_id": None,
        "status": "DRAFT",
        "submitted_by_user_id": None,
        "certified_by_user_id": None,
    })
    _derive_first_sale(cls)
    STORE["classifications"][cls["id"]] = cls
    return success_object(serialize(cls), 201)


@bp.route("/customs/classifications/<classification_id>", methods=["GET"])
def get_classification(classification_id):
    user_id, role = authenticate()
    require_role(role, ALL_ROLES)
    cls = get_classification_or_404(classification_id)
    require_client_scope(user_id, role, cls["client_id"])
    return success_object(serialize(cls))


@bp.route("/customs/classifications", methods=["GET"])
def list_classifications():
    user_id, role = authenticate()
    require_role(role, ALL_ROLES)
    items = sorted_by_creation(STORE["classifications"].values())
    if role == "ClientContact":
        items = [c for c in items if c["client_id"] == user_id]
    client_id = request.args.get("client_id")
    if client_id is not None:
        items = [c for c in items if c["client_id"] == client_id]
    supersedes_id = request.args.get("supersedes_id")
    if supersedes_id is not None:
        items = [c for c in items if c["supersedes_id"] == supersedes_id]
    status = request.args.get("status")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    return paginate([serialize(c) for c in items])


@bp.route("/customs/classifications/<classification_id>/submit", methods=["POST"])
def submit_classification(classification_id):
    user_id, role = authenticate()
    require_role(role, {"Analyst"})
    cls = get_classification_or_404(classification_id)
    if cls["status"] == "SUPERSEDED":
        raise_err(ERR_ALREADY_TERMINAL, "Classification is SUPERSEDED (terminal)")
    if cls["status"] != "DRAFT":
        raise_err(ERR_INVALID_STATE, f"Cannot submit from {cls['status']}")
    cls["status"] = "IN_REVIEW"
    cls["submitted_by_user_id"] = user_id
    touch(cls)
    return success_object(serialize(cls))


@bp.route("/customs/classifications/<classification_id>/review-decision", methods=["POST"])
def review_decision(classification_id):
    user_id, role = authenticate()
    require_role(role, {"LicensedBroker"})
    cls = get_classification_or_404(classification_id)
    body = get_body()
    decision = req_enum(body, "decision", {"CERTIFY", "REWORK"})
    if cls["status"] == "SUPERSEDED":
        raise_err(ERR_ALREADY_TERMINAL, "Classification is SUPERSEDED (terminal)")
    if cls["status"] != "IN_REVIEW":
        raise_err(ERR_INVALID_STATE, f"Cannot review from {cls['status']}")
    if decision == "CERTIFY":
        if user_id == cls["submitted_by_user_id"]:
            raise_err(
                ERR_SEGREGATION_OF_DUTIES,
                "Certifier must differ from the submitter",
            )
        cls["status"] = "CERTIFIED"
        cls["certified_by_user_id"] = user_id
    else:  # REWORK
        cls["status"] = "DRAFT"
    touch(cls)
    return success_object(serialize(cls))


@bp.route("/customs/classifications/<classification_id>/supersede", methods=["POST"])
def supersede_classification(classification_id):
    _, role = authenticate()
    require_role(role, {"Analyst"})
    cls = get_classification_or_404(classification_id)
    body = get_body()
    fields = _read_classification_fields(body)
    if "expected_classification_version" not in body or body["expected_classification_version"] is None:
        raise_err(ERR_INVALID_REQUEST, "Missing required field: expected_classification_version")
    expected = body["expected_classification_version"]
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise_err(ERR_INVALID_REQUEST, "expected_classification_version must be an integer")
    if expected != cls["version"]:
        raise_err(ERR_STALE_VERSION, "expected_classification_version does not match current version")
    if cls["status"] == "SUPERSEDED":
        raise_err(ERR_ALREADY_TERMINAL, "Classification is SUPERSEDED (terminal)")
    if cls["status"] != "CERTIFIED":
        raise_err(ERR_INVALID_STATE, f"Only a CERTIFIED classification may be superseded (got {cls['status']})")

    cls["status"] = "SUPERSEDED"
    touch(cls)

    successor = mint_entity()
    successor.update(fields)
    successor.update({
        "client_id": cls["client_id"],
        "supersedes_id": cls["id"],
        "status": "DRAFT",
        "submitted_by_user_id": None,
        "certified_by_user_id": None,
    })
    _derive_first_sale(successor)
    STORE["classifications"][successor["id"]] = successor
    return success_object(serialize(successor), 201)
