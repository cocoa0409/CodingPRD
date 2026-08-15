"""Par-level policies and computed inventory valuation (PRD §3.9)."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error,
    ERR_POLICY_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_STALE_VERSION,
)
from middleware import require_roles, ALL_ROLES
from response import success_object
from services import domain
from validate import get_body, req_int, opt_int, MISSING

bp = Blueprint("policies", __name__)

ANY = ALL_ROLES


def get_policy_or_404(policy_id: str) -> dict:
    policy = db["policies"].get(policy_id)
    if policy is None:
        raise_error(ERR_POLICY_NOT_FOUND, f"par-level policy {policy_id} does not exist")
    return policy


def _active_policy_for(tissue_type: str):
    for p in db["policies"].values():
        if p["tissue_type"] == tissue_type and p["status"] == "ACTIVE":
            return p
    return None


@bp.route("/tissue-bank/par-level-policies", methods=["POST"])
def create_policy():
    require_roles({"SupplyChainAdmin"})
    body = get_body()
    # request shape
    tissue_type = body.get("tissue_type", MISSING)
    if not isinstance(tissue_type, str) or tissue_type not in domain.TISSUE_TYPES:
        raise_error(ERR_INVALID_REQUEST, f"tissue_type must be one of {sorted(domain.TISSUE_TYPES)}")
    par_quantity = req_int(body, "par_quantity", min_val=0)
    max_inventory_value_cents = req_int(body, "max_inventory_value_cents", min_val=0)
    expected = body.get("expected_current_policy_version", MISSING)
    if expected is not MISSING and (isinstance(expected, bool) or not isinstance(expected, int)):
        raise_error(ERR_INVALID_REQUEST, "expected_current_policy_version must be an integer")
    # OCC (rung 3.5): missing expected version is treated as 0, matching only
    # when no ACTIVE policy exists for the tissue_type
    incumbent = _active_policy_for(tissue_type)
    current_version = incumbent["version"] if incumbent is not None else 0
    expected_version = 0 if expected is MISSING else expected
    if expected_version != current_version:
        raise_error(ERR_STALE_VERSION, f"expected_current_policy_version {expected_version} does not match {current_version}")
    if incumbent is not None:
        incumbent["status"] = "SUPERSEDED"
        domain.touch(incumbent)  # supersession increments the incumbent's version by 1
    policy = {
        "tissue_type": tissue_type,
        "par_quantity": par_quantity,
        "max_inventory_value_cents": max_inventory_value_cents,
        "status": "ACTIVE",
    }
    domain.stamp_new(policy)
    db["policies"][policy["id"]] = policy
    return success_object(domain.policy_json(policy), status=201)


@bp.route("/tissue-bank/par-level-policies/<policy_id>", methods=["GET"])
def get_policy(policy_id):
    require_roles(ANY)
    return success_object(domain.policy_json(get_policy_or_404(policy_id)))


@bp.route("/tissue-bank/par-level-policies/<policy_id>", methods=["PUT"])
def update_policy(policy_id):
    require_roles({"SupplyChainAdmin"})
    policy = get_policy_or_404(policy_id)
    body = get_body()
    par_quantity = opt_int(body, "par_quantity", min_val=0)
    max_inventory_value_cents = opt_int(body, "max_inventory_value_cents", min_val=0)
    expected = body.get("expected_par_level_policy_version", MISSING)
    if expected is MISSING or isinstance(expected, bool) or not isinstance(expected, int):
        raise_error(ERR_INVALID_REQUEST, "expected_par_level_policy_version is required and must be an integer")
    # OCC before any business rule
    if expected != policy["version"]:
        raise_error(ERR_STALE_VERSION, f"expected_par_level_policy_version {expected} does not match current version {policy['version']}")
    if policy["status"] != "ACTIVE":
        raise_error(ERR_INVALID_REQUEST, "only an ACTIVE policy's thresholds can be updated")
    if par_quantity is not None:
        policy["par_quantity"] = par_quantity
    if max_inventory_value_cents is not None:
        policy["max_inventory_value_cents"] = max_inventory_value_cents
    domain.touch(policy)
    return success_object(domain.policy_json(policy))


@bp.route("/tissue-bank/inventory/valuation", methods=["GET"])
def inventory_valuation():
    require_roles(ANY)
    # parameters arrive as query parameters (a JSON body is accepted as fallback)
    tissue_type = request.args.get("tissue_type")
    method = request.args.get("method")
    if tissue_type is None or method is None:
        body = get_body()
        tissue_type = tissue_type if tissue_type is not None else body.get("tissue_type")
        method = method if method is not None else body.get("method")
    if not isinstance(tissue_type, str) or tissue_type not in domain.TISSUE_TYPES:
        raise_error(ERR_INVALID_REQUEST, f"tissue_type must be one of {sorted(domain.TISSUE_TYPES)}")
    if not isinstance(method, str) or method not in domain.VALUATION_METHODS:
        raise_error(ERR_INVALID_REQUEST, "method must be FIFO or WEIGHTED_AVERAGE")
    on_hand_count, total_value = domain.compute_valuation(tissue_type, method)
    return success_object({
        "tissue_type": tissue_type,
        "method": method,
        "on_hand_count": on_hand_count,
        "total_value": total_value,
    })
