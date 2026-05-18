"""Gap insurance rider endpoints — PRD §3.7."""
from __future__ import annotations

from flask import Blueprint, g

from config import (
    ROLE_CUSTOMER,
    ROLE_FINANCE_MANAGER,
)
from db import store
from errors import (
    err_customer_not_found,
    err_gap_claim_exceeds_gap,
    err_gap_rider_not_claimable,
    err_gap_rider_parent_terminal,
    err_invalid_request,
    err_rider_contract_ownership_mismatch,
)
from middleware import is_customer, require_auth
from response import success
from routes._helpers import (
    check_version,
    get_json,
    parse_version,
)
from services.calculations import gap_monthly_premium_cents
from services.engine import (
    cascade_auto_cancel_gap_riders_for_contract,
    get_customer_or_404,
    get_gap_rider_or_404,
    stamp_create,
    stamp_update,
)
from services.serializers import serialize_gap_rider

bp = Blueprint("gap_riders", __name__)


def _check_customer_ownership(customer_id: str):
    if is_customer() and g.user_id != customer_id:
        raise err_customer_not_found()


# ── POST /customers/{customerId}/gap-riders ────────────────────────────────


@bp.post("/customers/<customer_id>/gap-riders")
@require_auth([ROLE_FINANCE_MANAGER, ROLE_CUSTOMER])
def create_gap_rider(customer_id):
    customer = get_customer_or_404(customer_id)
    _check_customer_ownership(customer_id)
    body = get_json()
    contract_id = body.get("contract_id")
    if not isinstance(contract_id, str) or not contract_id:
        raise err_invalid_request("contract_id is required.")
    contract_type = body.get("contract_type")
    if contract_type not in {"LOAN", "LEASE"}:
        raise err_invalid_request("contract_type must be LOAN or LEASE.")

    if contract_type == "LOAN":
        parent = store.loan_contracts.get(contract_id)
        if parent is None:
            # Treat as ownership mismatch (priority 6, 422).
            raise err_rider_contract_ownership_mismatch(
                "Referenced loan contract not found for this customer."
            )
        if parent["customer_id"] != customer_id:
            raise err_rider_contract_ownership_mismatch()
        if parent["status"] != "ACTIVE":
            raise err_invalid_request(
                "Parent loan contract must be ACTIVE to attach a gap rider."
            )
        financed = parent["principal_cents"]
    else:
        parent = store.lease_contracts.get(contract_id)
        if parent is None:
            raise err_rider_contract_ownership_mismatch(
                "Referenced lease contract not found for this customer."
            )
        if parent["customer_id"] != customer_id:
            raise err_rider_contract_ownership_mismatch()
        if parent["status"] != "ACTIVE":
            raise err_invalid_request(
                "Parent lease contract must be ACTIVE to attach a gap rider."
            )
        financed = parent["capitalized_cost_cents"]

    with store.lock:
        rider = {
            "customer_id": customer_id,
            "contract_id": contract_id,
            "contract_type": contract_type,
            "monthly_premium_cents": gap_monthly_premium_cents(financed),
            "status": "ACTIVE",
            "claim_payout_cents": 0,
            "attached_day_index": customer["clock_day_index"],
        }
        stamp_create(rider)
        store.gap_riders[rider["id"]] = rider
    return success(serialize_gap_rider(rider), 201)


# ── GET /customers/{customerId}/gap-riders/{riderId} ───────────────────────


@bp.get("/customers/<customer_id>/gap-riders/<rider_id>")
@require_auth([ROLE_FINANCE_MANAGER, ROLE_CUSTOMER])
def get_rider(customer_id, rider_id):
    customer = get_customer_or_404(customer_id)
    _check_customer_ownership(customer_id)
    rider = get_gap_rider_or_404(customer_id, rider_id)
    return success(serialize_gap_rider(rider))


# ── POST /customers/{customerId}/gap-riders/{riderId}/cancel ───────────────


@bp.post("/customers/<customer_id>/gap-riders/<rider_id>/cancel")
@require_auth([ROLE_CUSTOMER])
def cancel_rider(customer_id, rider_id):
    customer = get_customer_or_404(customer_id)
    _check_customer_ownership(customer_id)
    rider = get_gap_rider_or_404(customer_id, rider_id)
    body = get_json()
    expected = parse_version(body)
    check_version(rider, expected)

    if rider["status"] != "ACTIVE":
        raise err_gap_rider_not_claimable("Gap rider is not in ACTIVE state.")

    with store.lock:
        rider["status"] = "CANCELLED"
        stamp_update(rider)
    return success(serialize_gap_rider(rider))


# ── POST /customers/{customerId}/gap-riders/{riderId}/claim ────────────────


@bp.post("/customers/<customer_id>/gap-riders/<rider_id>/claim")
@require_auth([ROLE_FINANCE_MANAGER])
def claim_rider(customer_id, rider_id):
    customer = get_customer_or_404(customer_id)
    rider = get_gap_rider_or_404(customer_id, rider_id)
    body = get_json()
    expected = parse_version(body)
    check_version(rider, expected)

    payout = body.get("payout_cents")
    if payout is None or isinstance(payout, bool) or not isinstance(payout, int):
        raise err_invalid_request("payout_cents must be an integer.")
    if payout < 0:
        raise err_invalid_request("payout_cents must be >= 0.")

    # State (priority 4): rider must be ACTIVE.
    if rider["status"] != "ACTIVE":
        raise err_gap_rider_not_claimable()

    # Locate parent contract.
    if rider["contract_type"] == "LOAN":
        parent = store.loan_contracts.get(rider["contract_id"])
        if parent is None:
            raise err_gap_rider_not_claimable("Parent loan not found.")
        parent_status = parent["status"]
        # Priority 5: parent must NOT be terminal (CLOSED, PAID_OFF, CHARGED_OFF).
        if parent_status in {"PAID_OFF", "CHARGED_OFF"}:
            raise err_gap_rider_parent_terminal()
        # Parent must be ACTIVE or DEFAULTED (state precondition from §3.7).
        if parent_status not in {"ACTIVE", "DEFAULTED"}:
            raise err_gap_rider_not_claimable(
                f"Parent contract status {parent_status} forbids claim."
            )
        gap = parent.get("remaining_principal_cents") or 0
        if payout > gap:
            raise err_gap_claim_exceeds_gap(
                f"payout_cents={payout} exceeds remaining_principal_cents={gap}."
            )
    else:
        parent = store.lease_contracts.get(rider["contract_id"])
        if parent is None:
            raise err_gap_rider_not_claimable("Parent lease not found.")
        parent_status = parent["status"]
        if parent_status in {"CLOSED", "PURCHASED", "RENEWED", "RETURNED"}:
            raise err_gap_rider_parent_terminal()
        if parent_status not in {"ACTIVE", "DEFAULTED"}:
            raise err_gap_rider_not_claimable(
                f"Parent contract status {parent_status} forbids claim."
            )
        gap = parent.get("residual_value_cents") or 0
        if payout > gap:
            raise err_gap_claim_exceeds_gap(
                f"payout_cents={payout} exceeds residual_value_cents={gap}."
            )

    with store.lock:
        rider["status"] = "CLAIMED"
        rider["claim_payout_cents"] = payout
        stamp_update(rider)
        # Decrement gap on parent.
        if rider["contract_type"] == "LOAN":
            parent["remaining_principal_cents"] -= payout
            stamp_update(parent)
            if parent["remaining_principal_cents"] == 0 and parent["status"] == "ACTIVE":
                parent["status"] = "PAID_OFF"
                stamp_update(parent)
                # The rider just CLAIMED — do not cascade-cancel it, but
                # cancel any other ACTIVE rider on the same contract.
                cascade_auto_cancel_gap_riders_for_contract(parent["id"])
        else:
            parent["residual_value_cents"] -= payout
            stamp_update(parent)
    return success(serialize_gap_rider(rider))
