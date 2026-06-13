"""Payload factories — one per entity, input fields only (PRD §3 + §4).

Only fields the client supplies appear here; all computed/system fields
(quoted_amount_cents, charged_amount_cents, status, version, ...) are minted
by the server and never sent.
"""


def create_pricing_plan_payload(**overrides) -> dict:
    """A full DRAFT pricing plan. Required: label, wash_base_cents,
    dry_base_cents_per_block, wdf_rate_cents_per_lb. Everything else has a
    PRD-stated default but is supplied here for deterministic pricing."""
    defaults = {
        "label": "P1",
        "wash_base_cents": 300,
        "dry_base_cents_per_block": 75,
        "dry_block_minutes": 8,
        "surge_multiplier_bps": 10000,
        "surge_start_hour_utc": 16,
        "surge_end_hour_utc": 20,
        "wdf_rate_cents_per_lb": 180,
        "wdf_minimum_cents": 1500,
        "reload_bonus_tier1_min_cents": 2000,
        "reload_bonus_tier1_bps": 500,
        "reload_bonus_tier2_min_cents": 5000,
        "reload_bonus_tier2_bps": 1000,
        "loyalty_cents_per_point": 100,
        "loyalty_redeem_threshold_points": 50,
    }
    defaults.update(overrides)
    return defaults


def create_machine_payload(**overrides) -> dict:
    """Register a machine. Required: label, machine_type, capacity_lb.
    cycle_minutes optional (washer default 30)."""
    defaults = {
        "label": "W1",
        "machine_type": "WASHER",
        "capacity_lb": 25,
    }
    defaults.update(overrides)
    return defaults


def create_member_payload(**overrides) -> dict:
    """Register a member. Required: full_name, phone, card_token."""
    defaults = {
        "full_name": "M One",
        "phone": "555-0001",
        "card_token": "tok-m1",
    }
    defaults.update(overrides)
    return defaults


def create_vend_payload(expected_machine_version, **overrides) -> dict:
    """Capture a vend. Required: payment_method, expected_machine_version.
    Optional: member_id, dry_blocks, used_free_credit, card_token."""
    defaults = {
        "payment_method": "COIN",
        "expected_machine_version": expected_machine_version,
    }
    defaults.update(overrides)
    return defaults


def create_reload_payload(**overrides) -> dict:
    """Reload a wallet. Required: tender, principal_cents."""
    defaults = {
        "tender": "APP",
        "principal_cents": 5000,
    }
    defaults.update(overrides)
    return defaults


def create_shift_payload(attendant_id, **overrides) -> dict:
    """Open a shift. Required: attendant_id, opening_float_cents."""
    defaults = {
        "attendant_id": attendant_id,
        "opening_float_cents": 5000,
    }
    defaults.update(overrides)
    return defaults


def close_shift_payload(counted_drawer_cents, **overrides) -> dict:
    """Close a shift. Required: counted_drawer_cents."""
    defaults = {"counted_drawer_cents": counted_drawer_cents}
    defaults.update(overrides)
    return defaults


def create_wdf_order_payload(intake_attendant_id, weight_lb, **overrides) -> dict:
    """Intake a WDF order. Required: intake_attendant_id, weight_lb.
    Optional: member_id, rush."""
    defaults = {
        "intake_attendant_id": intake_attendant_id,
        "weight_lb": weight_lb,
    }
    defaults.update(overrides)
    return defaults


def pay_wdf_order_payload(pay_method, **overrides) -> dict:
    """Pay a WDF order. Required: pay_method."""
    defaults = {"pay_method": pay_method}
    defaults.update(overrides)
    return defaults


def create_refund_claim_payload(vend_id, reported_by_id, **overrides) -> dict:
    """File a refund claim. Required: vend_id, reported_by_id, reason.
    Optional: refund_destination (defaults to WALLET)."""
    defaults = {
        "vend_id": vend_id,
        "reported_by_id": reported_by_id,
        "reason": "MACHINE_FAULT",
    }
    defaults.update(overrides)
    return defaults


def approve_refund_claim_payload(expected_claim_version, **overrides) -> dict:
    """Approve a refund claim. Required: expected_claim_version."""
    defaults = {"expected_claim_version": expected_claim_version}
    defaults.update(overrides)
    return defaults


def create_lost_found_payload(logged_by_id, description, **overrides) -> dict:
    """Log a found item. Required: logged_by_id, description. Optional: machine_id."""
    defaults = {
        "logged_by_id": logged_by_id,
        "description": description,
    }
    defaults.update(overrides)
    return defaults


def claim_lost_found_payload(claimed_by_id, **overrides) -> dict:
    """Claim a found item. Required: claimed_by_id."""
    defaults = {"claimed_by_id": claimed_by_id}
    defaults.update(overrides)
    return defaults
