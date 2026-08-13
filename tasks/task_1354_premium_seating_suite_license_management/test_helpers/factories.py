"""Payload factories — one per entity, input fields only (PRD §3)."""
import itertools

from .constants import SEASON1

_n = itertools.count(1)


def _uniq(prefix):
    return f"{prefix}-{next(_n)}"


def create_venue_payload(**overrides) -> dict:
    defaults = {
        "name": "Metro Stadium",
        "address": "1 Arena Way",
        "default_catering_cutoff_hours": 72,
    }
    defaults.update(overrides)
    return defaults


def create_suite_payload(venue_id, **overrides) -> dict:
    defaults = {
        "venue_id": venue_id,
        "suite_code": _uniq("G"),
        "tier": "GOLD",
        "capacity_seats": 20,
        "base_annual_fee_cents": 12000000,
        "f_b_minimum_cents": 4000000,
    }
    defaults.update(overrides)
    return defaults


def create_season_payload(venue_id, **overrides) -> dict:
    defaults = {"venue_id": venue_id, **SEASON1}
    defaults.update(overrides)
    return defaults


def create_event_payload(season_id, **overrides) -> dict:
    defaults = {
        "season_id": season_id,
        "name": _uniq("Game"),
        "event_type": "REGULAR",
        "starts_at": "2026-09-10T17:00:00Z",
        "duration_hours": 4,
        "rental_base_price_cents": 500000,
    }
    defaults.update(overrides)
    return defaults


def create_account_payload(**overrides) -> dict:
    n = next(_n)
    defaults = {
        "legal_name": f"Acme Corp {n}",
        "account_type": "CORPORATE",
        "tax_id": f"T-{n}",
        "billing_email": f"ap-{n}@acme.example",
    }
    defaults.update(overrides)
    return defaults


def create_agreement_payload(suite_id, account_id, start_season_id, **overrides) -> dict:
    defaults = {
        "suite_id": suite_id,
        "account_id": account_id,
        "start_season_id": start_season_id,
        "term_seasons": 1,
        "base_annual_fee_cents": 12000000,
        "escalator_bp": 300,
        "f_b_minimum_cents": 4000000,
    }
    defaults.update(overrides)
    return defaults


def create_invoice_payload(account_id, **overrides) -> dict:
    defaults = {
        "account_id": account_id,
        "lines": [{"description": "Misc", "quantity": 1, "unit_price_cents": 5000}],
        "due_on": "2026-09-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_payment_payload(account_id, amount_cents, invoice_id, **overrides) -> dict:
    defaults = {
        "account_id": account_id,
        "amount_cents": amount_cents,
        "method": "ACH",
        "allocations": [{"invoice_id": invoice_id, "amount_cents": amount_cents}],
    }
    defaults.update(overrides)
    return defaults


def create_catering_order_payload(event_id, suite_id, **overrides) -> dict:
    defaults = {
        "event_id": event_id,
        "suite_id": suite_id,
        "package_tier": "STANDARD",
        "guest_count": 8,
        "lines": [{"item_code": "APP", "description": "Sliders",
                   "quantity": 1, "unit_price_cents": 1000}],
    }
    defaults.update(overrides)
    return defaults


def create_credential_payload(event_id, suite_id, **overrides) -> dict:
    n = next(_n)
    defaults = {
        "event_id": event_id,
        "suite_id": suite_id,
        "guest_name": f"Guest {n}",
        "guest_email": f"g{n}@x.example",
        "credential_type": "GUEST",
    }
    defaults.update(overrides)
    return defaults


def create_rental_payload(event_id, suite_id, account_id, **overrides) -> dict:
    defaults = {
        "event_id": event_id,
        "suite_id": suite_id,
        "account_id": account_id,
        "guest_count": 10,
    }
    defaults.update(overrides)
    return defaults


def create_transfer_request_payload(agreement_id, from_account_id, to_account_id,
                                    **overrides) -> dict:
    defaults = {
        "agreement_id": agreement_id,
        "from_account_id": from_account_id,
        "to_account_id": to_account_id,
        "transfer_type": "SALE_TRANSFER",
        "asking_price_cents": 9000000,
    }
    defaults.update(overrides)
    return defaults


def create_renewal_offer_payload(agreement_id, season_id, expected_agreement_version,
                                 **overrides) -> dict:
    defaults = {
        "agreement_id": agreement_id,
        "season_id": season_id,
        "proposed_fee_cents": 12400000,
        "proposed_escalator_bp": 300,
        "proposed_term_seasons": 1,
        "response_due_on": "2027-01-10T00:00:00Z",
        "expected_agreement_version": expected_agreement_version,
    }
    defaults.update(overrides)
    return defaults


def create_waitlist_entry_payload(account_id, **overrides) -> dict:
    defaults = {
        "account_id": account_id,
        "desired_tier": "GOLD",
    }
    defaults.update(overrides)
    return defaults


def create_assessment_payload(venue_id, **overrides) -> dict:
    defaults = {
        "venue_id": venue_id,
        "name": _uniq("Renovation"),
        "total_cost_cents": 1000000,
        "allocation_method": "PER_SUITE_EQUAL",
    }
    defaults.update(overrides)
    return defaults
