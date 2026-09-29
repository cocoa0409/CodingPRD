"""Provider selection, service-order creation and territory overlap detection."""

from datetime import timedelta

import db
from errors import ApiError
from services import deposits, enums
from services.lookup import orders_of_move


def eligible_pairs(utility_type, address, move_date):
    """(provider, territory) pairs whose coverage includes the address and date."""
    out = []
    for territory in db.db.territories.values():
        provider = db.db.utility_providers.get(territory["provider_id"])
        if provider is None:
            continue
        if provider["provider_status"] != "ACTIVE":
            continue
        if provider["utility_type"] != utility_type:
            continue
        if territory["postal_code"] != address["postal_code"]:
            continue
        if territory["state_code"] != address["state_code"]:
            continue
        effective_from = db.parse_date(territory["effective_from"])
        effective_to = db.parse_date(territory["effective_to"]) if territory["effective_to"] else None
        if move_date < effective_from:
            continue
        if effective_to is not None and move_date > effective_to:
            continue
        out.append((provider, territory))
    return out


def pick_winner(pairs):
    """is_default_carrier DESC, priority_rank ASC, effective_from DESC, created_at ASC."""
    if not pairs:
        return None
    rows = list(pairs)
    rows.sort(key=lambda pt: db.order_key(pt[1]))
    rows.sort(key=lambda pt: pt[1]["effective_from"], reverse=True)
    rows.sort(key=lambda pt: pt[1]["priority_rank"])
    rows.sort(key=lambda pt: 0 if pt[1]["is_default_carrier"] else 1)
    return rows[0]


def has_live_order(move_id, utility_type, order_kind):
    for order in orders_of_move(move_id):
        if order["utility_type"] != utility_type:
            continue
        if order["order_kind"] != order_kind:
            continue
        if order["provision_status"] in enums.MAPPED_LIVE_PROVISION:
            return True
    return False


def create_order(move, provider, territory, address, order_kind, utility_type):
    order = db.base_record()
    order.update(
        {
            "move_id": move["id"],
            "provider_id": provider["id"],
            "service_address_id": address["id"],
            "territory_id": territory["id"],
            "order_kind": order_kind,
            "utility_type": utility_type,
            "provision_status": "DRAFT",
            "credit_status": "PENDING_CHECK"
            if provider["credit_check_required"]
            else "NOT_REQUIRED",
            "account_data": {},
            "requested_service_date": None,
            "scheduled_window_start": None,
            "scheduled_window_end": None,
            "deposit_estimate_cents": deposits.deposit_estimate(provider),
            "deposit_amount_cents": 0,
            "deposit_paid_cents": 0,
            "readiness_snapshot": None,
            "confirmation_code": None,
            "cancellation_reason": None,
            "failure_reason": None,
            "waiver_reason": None,
        }
    )
    db.db.orders[order["id"]] = order
    return order


def check_territory_overlap(provider, postal_code, effective_from):
    """A new default-carrier row must begin at least one full clear day after the
    inclusive effective_to of every existing default-carrier row for the same
    postal code and utility type."""
    for territory in db.db.territories.values():
        if not territory["is_default_carrier"]:
            continue
        if territory["postal_code"] != postal_code:
            continue
        other = db.db.utility_providers.get(territory["provider_id"])
        if other is None or other["utility_type"] != provider["utility_type"]:
            continue
        existing_to = db.parse_date(territory["effective_to"]) if territory["effective_to"] else None
        if existing_to is None:
            raise ApiError(
                "ERR_TERRITORY_OVERLAP",
                "An open-ended default-carrier territory already covers this postal code.",
            )
        if effective_from <= existing_to + timedelta(days=1):
            raise ApiError(
                "ERR_TERRITORY_OVERLAP",
                "A clear day must separate consecutive default-carrier territories.",
            )
