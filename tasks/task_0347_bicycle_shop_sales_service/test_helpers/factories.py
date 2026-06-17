"""Payload factories — one per entity, input fields only (PRD §3).

Each factory provides PRD-valid defaults for the entity's input fields and
accepts **overrides so a test can pin the exact value it needs. Computed
fields (PRD §2.4) are never supplied — the server derives them.
"""
import itertools

_email_counter = itertools.count(1)


def unique_email(prefix: str = "user") -> str:
    """Generate a unique, '@'-containing email (PRD §3.1 uniqueness rule)."""
    return f"{prefix}-{next(_email_counter)}@example.com"


# ─── Customer (PRD §3.1) ────────────────────────────────────────────────────
def create_customer_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Customer",
        "email": unique_email("customer"),
    }
    defaults.update(overrides)
    return defaults


# ─── Sku (PRD §3.1) ─────────────────────────────────────────────────────────
def create_sku_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Sku",
        "category": "PART",
        "list_price_cents": 5000,
        "on_hand": 10,
    }
    defaults.update(overrides)
    return defaults


def restock_payload(units: int, **overrides) -> dict:
    defaults = {"units": units}
    defaults.update(overrides)
    return defaults


# ─── TuneUpTier (PRD §3.2) ──────────────────────────────────────────────────
def create_tune_up_tier_payload(**overrides) -> dict:
    defaults = {
        "code": "BASIC",
        "base_labor_cents": 8000,
        "turnaround_hours": 5,
    }
    defaults.update(overrides)
    return defaults


# ─── ServiceBay (PRD §3.4) ──────────────────────────────────────────────────
def create_service_bay_payload(**overrides) -> dict:
    defaults = {"name": "Bay 1"}
    defaults.update(overrides)
    return defaults


# ─── BayBooking (PRD §3.4) ──────────────────────────────────────────────────
def create_bay_booking_payload(bay_id: str, ticket_id: str, start_at: str,
                               end_at: str, **overrides) -> dict:
    defaults = {
        "bay_id": bay_id,
        "ticket_id": ticket_id,
        "start_at": start_at,
        "end_at": end_at,
    }
    defaults.update(overrides)
    return defaults


# ─── ServiceTicket (PRD §3.2) ───────────────────────────────────────────────
def create_service_ticket_payload(customer_id: str, tier_id: str, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "tier_id": tier_id,
    }
    defaults.update(overrides)
    return defaults


# ─── LaborLine (PRD §3.3) ───────────────────────────────────────────────────
def create_labor_line_payload(ticket_id: str, **overrides) -> dict:
    defaults = {
        "ticket_id": ticket_id,
        "menu_code": "BRAKE_BLEED",
        "labor_cents": 3000,
    }
    defaults.update(overrides)
    return defaults


# ─── SalesOrder (PRD §3.5) ──────────────────────────────────────────────────
def create_sales_order_payload(customer_id: str, **overrides) -> dict:
    defaults = {"customer_id": customer_id}
    defaults.update(overrides)
    return defaults


# ─── OrderLine (PRD §3.5) ───────────────────────────────────────────────────
def create_order_line_payload(order_id: str, sku_id: str, qty: int = 1, **overrides) -> dict:
    defaults = {
        "order_id": order_id,
        "sku_id": sku_id,
        "qty": qty,
    }
    defaults.update(overrides)
    return defaults


def reserve_payload(expected_sku_version: int, **overrides) -> dict:
    defaults = {"expected_sku_version": expected_sku_version}
    defaults.update(overrides)
    return defaults


# ─── LayawayPlan (PRD §3.7) ─────────────────────────────────────────────────
def create_layaway_plan_payload(customer_id: str, sku_id: str,
                                expected_sku_version: int, qty: int = 1, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "sku_id": sku_id,
        "qty": qty,
        "expected_sku_version": expected_sku_version,
    }
    defaults.update(overrides)
    return defaults


# ─── SpecialOrder (PRD §3.8) ────────────────────────────────────────────────
def create_special_order_payload(customer_id: str, sku_id: str, qty: int = 1, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "sku_id": sku_id,
        "qty": qty,
    }
    defaults.update(overrides)
    return defaults


# ─── BuildJob (PRD §3.9) ────────────────────────────────────────────────────
def create_build_job_payload(customer_id: str, frame_sku_id: str,
                             required_part_count: int = 1, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "frame_sku_id": frame_sku_id,
        "required_part_count": required_part_count,
    }
    defaults.update(overrides)
    return defaults


def reserve_part_payload(sku_id: str, qty: int = 1, **overrides) -> dict:
    defaults = {"sku_id": sku_id, "qty": qty}
    defaults.update(overrides)
    return defaults


# ─── WarrantyClaim (PRD §3.10) ──────────────────────────────────────────────
def create_warranty_claim_payload(customer_id: str, sku_id: str,
                                  source_order_line_id: str, defect_part: str,
                                  **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "sku_id": sku_id,
        "source_order_line_id": source_order_line_id,
        "defect_part": defect_part,
    }
    defaults.update(overrides)
    return defaults


def approve_warranty_payload(resolution: str, **overrides) -> dict:
    defaults = {"resolution": resolution}
    defaults.update(overrides)
    return defaults


# ─── TradeIn (PRD §3.11) ────────────────────────────────────────────────────
def create_trade_in_payload(customer_id: str, condition_grade: str,
                            appraised_value_cents: int, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "description": "Used bicycle",
        "condition_grade": condition_grade,
        "appraised_value_cents": appraised_value_cents,
    }
    defaults.update(overrides)
    return defaults


# ─── Payment (PRD §3.6) ─────────────────────────────────────────────────────
def create_payment_payload(target_type: str, target_id: str, amount_cents: int,
                           **overrides) -> dict:
    defaults = {
        "target_type": target_type,
        "target_id": target_id,
        "amount_cents": amount_cents,
    }
    defaults.update(overrides)
    return defaults


# ─── RecallNotice (PRD §3.11) ───────────────────────────────────────────────
def create_recall_notice_payload(sku_id: str, severity: str = "ADVISORY", **overrides) -> dict:
    defaults = {
        "sku_id": sku_id,
        "severity": severity,
        "remedy": "Inspect and repair as needed.",
    }
    defaults.update(overrides)
    return defaults


# ─── RecallAck (PRD §3.11) ──────────────────────────────────────────────────
def create_recall_ack_payload(recall_id: str, customer_id: str, **overrides) -> dict:
    defaults = {
        "recall_id": recall_id,
        "customer_id": customer_id,
    }
    defaults.update(overrides)
    return defaults


# ─── Clock (PRD §3.3) ───────────────────────────────────────────────────────
def set_clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}
