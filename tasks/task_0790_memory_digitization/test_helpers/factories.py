"""Payload factories — one per entity, input fields only."""


def create_customer_payload(**overrides) -> dict:
    defaults = {"email": "cust@x.com", "full_name": "Test Customer", "state_code": "CA"}
    defaults.update(overrides)
    return defaults


def create_order_payload(customer_id, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "plan_tier": "STANDARD_KIT",
        "turnaround": "STANDARD",
        "output_option": "CLOUD",
    }
    defaults.update(overrides)
    return defaults


def create_machine_payload(**overrides) -> dict:
    defaults = {"name": "Station-1", "kind": "TAPE_DECK"}
    defaults.update(overrides)
    return defaults


def create_storage_bin_payload(**overrides) -> dict:
    defaults = {"label": "Bin-1", "capacity": 10}
    defaults.update(overrides)
    return defaults


def create_batch_payload(machine_id, **overrides) -> dict:
    defaults = {
        "machine_id": machine_id,
        "scheduled_start": "2026-03-01T09:00:00Z",
        "scheduled_end": "2026-03-01T10:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_media_item_payload(bin_id, **overrides) -> dict:
    defaults = {"media_type": "TAPE", "bin_id": bin_id}
    defaults.update(overrides)
    return defaults


def create_damage_claim_payload(order_id, media_item_id, **overrides) -> dict:
    defaults = {"order_id": order_id, "media_item_id": media_item_id, "claim_type": "LOST"}
    defaults.update(overrides)
    return defaults


def qc_review_payload(decision, **overrides) -> dict:
    defaults = {"decision": decision}
    defaults.update(overrides)
    return defaults
