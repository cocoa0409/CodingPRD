"""Payload factories — one per entity, input fields only.

Field names match the PRD verbatim. Only source: input fields appear here;
computed/system fields (is_footwear, lifecycle, totals, statuses, versions,
available_qty, etc.) are never sent in payloads.
"""

DEFAULTS = {
    "STORE_NAME": "Test Store",
    "STATE_CODE": "CA",
    "SKU_NAME": "Test SKU",
    "SPORT": "BASEBALL",
    "SIZE_LABEL": "M",
    "BASE_PRICE_CENTS": 5000,
    "CUSTOMER_FULL_NAME": "Test Customer",
    "HOME_STATE_CODE": "CA",
    "TEAM_NAME": "Test Team",
}


# ---- Store ----
def create_store_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["STORE_NAME"],
        "state_code": DEFAULTS["STATE_CODE"],
    }
    defaults.update(overrides)
    return defaults


# ---- SKU ----
def create_sku_payload(**overrides) -> dict:
    defaults = {
        "sport": DEFAULTS["SPORT"],
        "name": DEFAULTS["SKU_NAME"],
        "base_price_cents": DEFAULTS["BASE_PRICE_CENTS"],
        "size_label": DEFAULTS["SIZE_LABEL"],
    }
    defaults.update(overrides)
    return defaults


# ---- Customer ----
def create_customer_payload(**overrides) -> dict:
    defaults = {
        "email": "cust@example.com",
        "full_name": DEFAULTS["CUSTOMER_FULL_NAME"],
        "home_state_code": DEFAULTS["HOME_STATE_CODE"],
    }
    defaults.update(overrides)
    return defaults


# ---- StoreInventory ----
def create_store_inventory_payload(store_id: str, sku_id: str, **overrides) -> dict:
    defaults = {"store_id": store_id, "sku_id": sku_id}
    defaults.update(overrides)
    return defaults


def receive_payload(quantity: int, expected_store_inventory_version: int, **overrides) -> dict:
    defaults = {
        "quantity": quantity,
        "expected_store_inventory_version": expected_store_inventory_version,
    }
    defaults.update(overrides)
    return defaults


# ---- Order ----
def create_order_payload(customer_id: str, store_id: str, fulfillment_type: str = "BOPIS",
                         **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "store_id": store_id,
        "fulfillment_type": fulfillment_type,
    }
    defaults.update(overrides)
    return defaults


def create_order_line_payload(sku_id: str, quantity: int = 1, **overrides) -> dict:
    defaults = {"sku_id": sku_id, "quantity": quantity}
    defaults.update(overrides)
    return defaults


def fulfill_payload(expected_order_version: int, **overrides) -> dict:
    defaults = {"expected_order_version": expected_order_version}
    defaults.update(overrides)
    return defaults


# ---- ServiceTicket ----
def create_service_ticket_payload(customer_id: str, store_id: str, service_type: str,
                                  **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "store_id": store_id,
        "service_type": service_type,
    }
    defaults.update(overrides)
    return defaults


# ---- FishingLicense ----
def create_fishing_license_payload(customer_id: str, issuing_store_id: str, **overrides) -> dict:
    defaults = {"customer_id": customer_id, "issuing_store_id": issuing_store_id}
    defaults.update(overrides)
    return defaults


# ---- Markdown ----
def create_markdown_payload(sku_id: str, markdown_kind: str, percent_off: int,
                            effective_from: str, effective_until: str, **overrides) -> dict:
    defaults = {
        "sku_id": sku_id,
        "markdown_kind": markdown_kind,
        "percent_off": percent_off,
        "effective_from": effective_from,
        "effective_until": effective_until,
    }
    defaults.update(overrides)
    return defaults


# ---- PriceMatchClaim ----
def create_price_match_claim_payload(order_id: str, order_line_id: str,
                                     competitor_price_cents: int, **overrides) -> dict:
    defaults = {
        "order_id": order_id,
        "order_line_id": order_line_id,
        "competitor_price_cents": competitor_price_cents,
    }
    defaults.update(overrides)
    return defaults


# ---- TeamOrder ----
def create_team_order_payload(customer_id: str, store_id: str,
                              team_name: str = None, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "store_id": store_id,
        "team_name": team_name if team_name is not None else DEFAULTS["TEAM_NAME"],
    }
    defaults.update(overrides)
    return defaults


def create_team_order_line_payload(sku_id: str, quantity: int = 1, **overrides) -> dict:
    defaults = {"sku_id": sku_id, "quantity": quantity}
    defaults.update(overrides)
    return defaults
