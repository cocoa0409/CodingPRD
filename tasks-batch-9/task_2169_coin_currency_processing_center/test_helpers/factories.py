"""Payload factories — one per resource, input fields only."""

import itertools

_SEQ = itertools.count(1)


def unique_suffix() -> str:
    """Monotonic suffix so several rows created inside one test never collide
    on a unique business identifier."""
    return f"{next(_SEQ):04d}"


# ─── Vault ────────────────────────────────────────────────────────────────

def create_vault_payload(**overrides) -> dict:
    suffix = unique_suffix()
    payload = {
        "vault_code": f"CV-{suffix}",
        "name": f"Cash Vault {suffix}",
    }
    payload.update(overrides)
    return payload


def vault_posture_payload(posture: str) -> dict:
    return {"posture": posture}


def inventory_adjustment_payload(denomination: str, delta_boxes: int) -> dict:
    return {"denomination": denomination, "delta_boxes": delta_boxes}


# ─── CustomerAccount ──────────────────────────────────────────────────────

def create_customer_account_payload(**overrides) -> dict:
    suffix = unique_suffix()
    payload = {
        "account_number": f"ACC-{suffix}",
        "customer_name": f"Depositor {suffix}",
        "tier": "STANDARD",
        "status": "ACTIVE",
    }
    payload.update(overrides)
    return payload


# ─── DepositTicket ────────────────────────────────────────────────────────

def create_deposit_ticket_payload(customer_account_id: str, vault_id: str, **overrides) -> dict:
    suffix = unique_suffix()
    payload = {
        "customer_account_id": customer_account_id,
        "vault_id": vault_id,
        "courier_manifest_number": f"MAN-{suffix}",
        "declared_bag_count": 1,
    }
    payload.update(overrides)
    return payload


def hold_payload(hold_reason: str = "Manifest and seal log disagree; awaiting carrier statement.") -> dict:
    return {"hold_reason": hold_reason}


def reverse_provisional_credit_payload(
    reason: str = "Manifest mismatch found before counting; credit withdrawn.",
) -> dict:
    return {"reason": reason}


# ─── SealedBag / CustodyEvent ─────────────────────────────────────────────

def create_sealed_bag_payload(deposit_ticket_id: str, **overrides) -> dict:
    suffix = unique_suffix()
    payload = {
        "deposit_ticket_id": deposit_ticket_id,
        "seal_number": f"S-{suffix}",
        "bag_type": "CURRENCY",
        "declared_amount_cents": 100_000,
        "declared_note_count": 100,
        "declared_coin_weight_grams": 0,
    }
    payload.update(overrides)
    return payload


def custody_event_payload(event_type: str, observed_seal_number: str, location_code: str = "SITE-CUST") -> dict:
    return {
        "event_type": event_type,
        "location_code": location_code,
        "observed_seal_number": observed_seal_number,
    }


# ─── CountingMachine ──────────────────────────────────────────────────────

def create_counting_machine_payload(vault_id: str, **overrides) -> dict:
    suffix = unique_suffix()
    payload = {
        "vault_id": vault_id,
        "machine_code": f"SORT-{suffix}",
        "machine_type": "CURRENCY_SORTER",
        "status": "AVAILABLE",
    }
    payload.update(overrides)
    return payload


# ─── CountSession ─────────────────────────────────────────────────────────

def create_count_session_payload(
    sealed_bag_id: str,
    counting_machine_id: str,
    expected_sealed_bag_version: int,
    window_start: str = "2026-08-03T09:00:00Z",
    window_end: str = "2026-08-03T10:00:00Z",
    **overrides,
) -> dict:
    payload = {
        "sealed_bag_id": sealed_bag_id,
        "counting_machine_id": counting_machine_id,
        "window_start": window_start,
        "window_end": window_end,
        "expected_sealed_bag_version": expected_sealed_bag_version,
    }
    payload.update(overrides)
    return payload


def lot_entry(category: str, denomination_cents: int, note_count: int) -> dict:
    return {
        "category": category,
        "denomination_cents": denomination_cents,
        "note_count": note_count,
    }


def complete_count_session_payload(
    counted_amount_cents: int,
    counted_note_count: int,
    lots: list,
    counted_coin_weight_grams: int = 0,
) -> dict:
    return {
        "counted_amount_cents": counted_amount_cents,
        "counted_note_count": counted_note_count,
        "counted_coin_weight_grams": counted_coin_weight_grams,
        "lots": lots,
    }


# ─── CounterfeitReport ────────────────────────────────────────────────────

def create_counterfeit_report_payload(
    fitness_lot_id: str, denomination_cents: int, note_count: int, **overrides
) -> dict:
    payload = {
        "fitness_lot_id": fitness_lot_id,
        "serial_number": f"FB{unique_suffix()}0000A",
        "denomination_cents": denomination_cents,
        "note_count": note_count,
    }
    payload.update(overrides)
    return payload


def correction_note_payload(
    correction_note: str = "Serial number transposed; refile with the corrected serial.",
) -> dict:
    return {"correction_note": correction_note}


def case_number_payload(case_number: str = "SS-2026-000123") -> dict:
    return {"case_number": case_number}


# ─── DiscrepancyClaim ─────────────────────────────────────────────────────

def create_discrepancy_claim_payload(
    sealed_bag_id: str, claimed_amount_cents: int, claim_type: str = "COUNT_VARIANCE"
) -> dict:
    return {
        "sealed_bag_id": sealed_bag_id,
        "claim_type": claim_type,
        "claimed_amount_cents": claimed_amount_cents,
    }


def request_info_payload(info_request_note: str = "Send the customer-side tape for this round.") -> dict:
    return {"info_request_note": info_request_note}


def resubmit_claim_payload(claimed_amount_cents: int) -> dict:
    return {"claimed_amount_cents": claimed_amount_cents}


def approve_claim_payload(resolution_amount_cents: int) -> dict:
    return {"resolution_amount_cents": resolution_amount_cents}


def deny_claim_payload(
    denial_reason: str = "Machine tape and customer tape agree; no shortage found.",
) -> dict:
    return {"denial_reason": denial_reason}


# ─── FedDeposit ───────────────────────────────────────────────────────────

def create_fed_deposit_payload(vault_id: str, fitness_lot_ids: list, **overrides) -> dict:
    payload = {
        "vault_id": vault_id,
        "cash_letter_number": f"CL-{unique_suffix()}",
        "deposit_date": "2026-08-04",
        "fitness_lot_ids": fitness_lot_ids,
    }
    payload.update(overrides)
    return payload


def confirm_fed_deposit_payload(credited_total_cents: int) -> dict:
    return {"credited_total_cents": credited_total_cents}


# ─── CoinOrder ────────────────────────────────────────────────────────────

def coin_order_line(denomination: str, boxes_requested: int) -> dict:
    return {"denomination": denomination, "boxes_requested": boxes_requested}


def create_coin_order_payload(
    customer_account_id: str,
    vault_id: str,
    lines: list,
    pickup_window_start: str = "2026-08-05T10:00:00Z",
    pickup_window_end: str = "2026-08-05T12:00:00Z",
) -> dict:
    return {
        "customer_account_id": customer_account_id,
        "vault_id": vault_id,
        "pickup_window_start": pickup_window_start,
        "pickup_window_end": pickup_window_end,
        "lines": lines,
    }


def approve_coin_order_payload(allow_partial: bool) -> dict:
    return {"allow_partial": allow_partial}


def release_coin_order_payload(expected_vault_version: int) -> dict:
    return {"expected_vault_version": expected_vault_version}


def return_coin_order_payload(
    return_reason: str = "Customer pickup cancelled; boxes returned unopened.",
) -> dict:
    return {"return_reason": return_reason}


# ─── Logical clock ────────────────────────────────────────────────────────

def set_clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}


__all__ = [
    "unique_suffix",
    "create_vault_payload",
    "vault_posture_payload",
    "inventory_adjustment_payload",
    "create_customer_account_payload",
    "create_deposit_ticket_payload",
    "hold_payload",
    "reverse_provisional_credit_payload",
    "create_sealed_bag_payload",
    "custody_event_payload",
    "create_counting_machine_payload",
    "create_count_session_payload",
    "lot_entry",
    "complete_count_session_payload",
    "create_counterfeit_report_payload",
    "correction_note_payload",
    "case_number_payload",
    "create_discrepancy_claim_payload",
    "request_info_payload",
    "resubmit_claim_payload",
    "approve_claim_payload",
    "deny_claim_payload",
    "create_fed_deposit_payload",
    "confirm_fed_deposit_payload",
    "coin_order_line",
    "create_coin_order_payload",
    "approve_coin_order_payload",
    "release_coin_order_payload",
    "return_coin_order_payload",
    "set_clock_payload",
]
