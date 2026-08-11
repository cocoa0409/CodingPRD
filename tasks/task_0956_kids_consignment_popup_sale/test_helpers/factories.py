"""Payload factories — one per entity, input fields only (PRD §3, §4)."""

# Standard one-week event skeleton used across tests (PRD §3.1).
STANDARD_EVENT_WINDOWS = {
    "intake_start": "2026-06-01T09:00:00Z",
    "intake_end": "2026-06-03T18:00:00Z",
    "presale_start": "2026-06-04T17:00:00Z",
    "presale_end": "2026-06-04T20:00:00Z",
    "sale_start": "2026-06-05T09:00:00Z",
    "sale_end": "2026-06-07T15:00:00Z",
    "pickup_deadline": "2026-06-07T18:00:00Z",
}

# Clock instants that satisfy each phase-advance gate of the standard skeleton.
CLOCK_INTAKE_OPEN = "2026-06-01T10:00:00Z"   # >= intake_start
CLOCK_INTAKE_END = "2026-06-03T18:00:00Z"    # >= intake_end
CLOCK_PRESALE_START = "2026-06-04T17:00:00Z"  # >= presale_start
CLOCK_SALE_START = "2026-06-05T09:00:00Z"    # >= sale_start
CLOCK_SALE_END = "2026-06-07T15:00:00Z"      # >= sale_end

DEFAULTS = {
    "EVENT_NAME": "Fall Sale",
    "SLOT_START": "2026-06-02T10:00:00Z",
    "SLOT_END": "2026-06-02T12:00:00Z",
    "SLOT_CAPACITY": 2,
    "ITEM_TITLE": "Blocks",
    "ITEM_CATEGORY": "TOYS",
    "ITEM_PRICE_CENTS": 1000,
    "SHIFT_ROLE": "Setup",
    "SHIFT_CAPACITY": 5,
}


def create_sale_event_payload(**overrides) -> dict:
    defaults = {"name": DEFAULTS["EVENT_NAME"], **STANDARD_EVENT_WINDOWS}
    defaults.update(overrides)
    return defaults


def create_markdown_rule_payload(sale_event_id, effective_from, effective_to,
                                 discount_pct, **overrides) -> dict:
    defaults = {
        "sale_event_id": sale_event_id,
        "effective_from": effective_from,
        "effective_to": effective_to,
        "discount_pct": discount_pct,
    }
    defaults.update(overrides)
    return defaults


def create_consignor_payload(sale_event_id, full_name="Ann", email=None, **overrides) -> dict:
    defaults = {
        "sale_event_id": sale_event_id,
        "full_name": full_name,
        "email": email or f"{full_name.lower().replace(' ', '.')}@x.com",
    }
    defaults.update(overrides)
    return defaults


def create_volunteer_payload(sale_event_id, full_name="Vic", email=None,
                             linked_consignor_id=None, **overrides) -> dict:
    defaults = {
        "sale_event_id": sale_event_id,
        "full_name": full_name,
        "email": email or f"{full_name.lower().replace(' ', '.')}@x.com",
    }
    if linked_consignor_id is not None:
        defaults["linked_consignor_id"] = linked_consignor_id
    defaults.update(overrides)
    return defaults


def create_drop_off_slot_payload(sale_event_id, start_time=None, end_time=None,
                                 capacity=None, **overrides) -> dict:
    defaults = {
        "sale_event_id": sale_event_id,
        "start_time": start_time or DEFAULTS["SLOT_START"],
        "end_time": end_time or DEFAULTS["SLOT_END"],
        "capacity": capacity if capacity is not None else DEFAULTS["SLOT_CAPACITY"],
    }
    defaults.update(overrides)
    return defaults


def create_drop_off_booking_payload(slot_id, consignor_id, **overrides) -> dict:
    defaults = {"slot_id": slot_id, "consignor_id": consignor_id}
    defaults.update(overrides)
    return defaults


def create_item_payload(consignor_id, title=None, category=None, price_cents=None,
                        **overrides) -> dict:
    defaults = {
        "consignor_id": consignor_id,
        "title": title or DEFAULTS["ITEM_TITLE"],
        "category": category or DEFAULTS["ITEM_CATEGORY"],
        "price_cents": price_cents if price_cents is not None else DEFAULTS["ITEM_PRICE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def inspect_item_payload(outcome="PASS", reasons=None, **overrides) -> dict:
    defaults = {"outcome": outcome}
    if reasons is not None:
        defaults["reasons"] = reasons
    defaults.update(overrides)
    return defaults


def create_volunteer_shift_payload(sale_event_id, role_name=None, start_time=None,
                                   end_time=None, capacity=None, **overrides) -> dict:
    defaults = {
        "sale_event_id": sale_event_id,
        "role_name": role_name or DEFAULTS["SHIFT_ROLE"],
        "start_time": start_time or "2026-05-28T09:00:00Z",
        "end_time": end_time or "2026-05-28T13:00:00Z",
        "capacity": capacity if capacity is not None else DEFAULTS["SHIFT_CAPACITY"],
    }
    defaults.update(overrides)
    return defaults


def create_shift_signup_payload(shift_id, volunteer_id, **overrides) -> dict:
    defaults = {"shift_id": shift_id, "volunteer_id": volunteer_id}
    defaults.update(overrides)
    return defaults


def create_pos_transaction_payload(sale_event_id, presale_pass_id=None, **overrides) -> dict:
    defaults = {"sale_event_id": sale_event_id}
    if presale_pass_id is not None:
        defaults["presale_pass_id"] = presale_pass_id
    defaults.update(overrides)
    return defaults


def scan_line_payload(barcode, **overrides) -> dict:
    defaults = {"barcode": barcode}
    defaults.update(overrides)
    return defaults


def checkout_payload(tendered_cents, **overrides) -> dict:
    defaults = {"tendered_cents": tendered_cents}
    defaults.update(overrides)
    return defaults


def advance_phase_payload(to_phase, **overrides) -> dict:
    defaults = {"to_phase": to_phase}
    defaults.update(overrides)
    return defaults


def generate_settlements_payload(expected_sale_event_version, **overrides) -> dict:
    defaults = {"expected_sale_event_version": expected_sale_event_version}
    defaults.update(overrides)
    return defaults


def dispute_payload(reason, **overrides) -> dict:
    defaults = {"reason": reason}
    defaults.update(overrides)
    return defaults


def resolve_payload(adjustment_cents, **overrides) -> dict:
    defaults = {"adjustment_cents": adjustment_cents}
    defaults.update(overrides)
    return defaults


def set_clock_payload(to_iso8601, **overrides) -> dict:
    defaults = {"to_iso8601": to_iso8601}
    defaults.update(overrides)
    return defaults
