"""Composite setup helpers for the rep-agency commission domain.

Every helper builds its preconditions from scratch through the public API
(each test runs against a freshly restarted server). Lenient get_success_data
is used internally so setup failures surface as clear "Setup failed" errors.

Rep and PrincipalOps are entity-backed roles (PRD §2.1): every call that is
ownership-gated threads the acting entity's id through make_rep_headers /
make_principal_ops_headers — never the shared fallback constants.
"""
from datetime import datetime, timezone
from typing import List, Optional

from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .constants import (
    BASE_ATTAINMENT_TIERS,
    BASE_FAMILY_RATES,
    CLOCK_DEFAULT,
    TEST_DEFAULTS,
)
from .factories import (
    create_adjustment_payload,
    create_agreement_payload,
    create_customer_payload,
    create_order_payload,
    create_principal_payload,
    create_rate_schedule_payload,
    create_registration_payload,
    create_rep_payload,
    create_rma_payload,
    create_sample_checkout_payload,
    create_sample_unit_payload,
    create_statement_payload,
    make_order_line,
    make_statement_line,
    put_splits_payload,
)
from .test_users import (
    TEST_USERS,
    make_principal_ops_headers,
    make_rep_headers,
)

ADMIN = TEST_USERS["agency_admin_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp (with or without fractional digits)."""
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


# ---------------------------------------------------------------------------
# Master data
# ---------------------------------------------------------------------------

def create_principal(**overrides) -> dict:
    return get_success_data(api_client.create_principal(create_principal_payload(**overrides), ADMIN))


def create_agreement(principal_id: str, **overrides) -> dict:
    """Create a territory agreement (born DRAFT, PRD §3.1)."""
    return get_success_data(
        api_client.create_agreement(principal_id, create_agreement_payload(**overrides), ADMIN)
    )


def activate_agreement(agreement_id: str) -> dict:
    return get_success_data(api_client.activate_agreement(agreement_id, ADMIN))


def suspend_agreement(agreement_id: str) -> dict:
    return get_success_data(api_client.suspend_agreement(agreement_id, ADMIN))


def create_rate_schedule(principal_id: str, expected_principal_version: int,
                         family_rates: Optional[list] = None,
                         attainment_tiers: Optional[list] = None,
                         registration_bonus_bp: Optional[int] = None) -> dict:
    """Create a rate schedule (OCC-guarded on the principal version, PRD §2.8).

    registration_bonus_bp=None omits the field so the server default applies.
    """
    overrides = {}
    if family_rates is not None:
        overrides["family_rates"] = family_rates
    if attainment_tiers is not None:
        overrides["attainment_tiers"] = attainment_tiers
    if registration_bonus_bp is not None:
        overrides["registration_bonus_bp"] = registration_bonus_bp
    payload = create_rate_schedule_payload(expected_principal_version, **overrides)
    return get_success_data(api_client.create_rate_schedule(principal_id, payload, ADMIN))


def create_rep(display_name: str = "R1", territory_codes: Optional[List[str]] = None,
               **overrides) -> dict:
    payload = create_rep_payload(
        display_name=display_name,
        territory_codes=territory_codes if territory_codes is not None else ["CA", "OR"],
        **overrides,
    )
    return get_success_data(api_client.create_rep(payload, ADMIN))


def create_customer(**overrides) -> dict:
    return get_success_data(api_client.create_customer(create_customer_payload(**overrides), ADMIN))


def set_clock(to_iso8601: str) -> dict:
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


def get_principal(principal_id: str) -> dict:
    return get_success_data(api_client.get_principal(principal_id, ADMIN))


def get_rep(rep_id: str) -> dict:
    return get_success_data(api_client.get_rep(rep_id, ADMIN))


def get_agreement(agreement_id: str) -> dict:
    return get_success_data(api_client.get_agreement(agreement_id, ADMIN))


def get_order(order_id: str) -> dict:
    return get_success_data(api_client.get_order(order_id, ADMIN))


def get_registration(registration_id: str) -> dict:
    return get_success_data(api_client.get_registration(registration_id, ADMIN))


def get_rma(rma_id: str) -> dict:
    return get_success_data(api_client.get_rma(rma_id, ADMIN))


def get_statement(statement_id: str) -> dict:
    return get_success_data(api_client.get_statement(statement_id, ADMIN))


def get_sample_unit(sample_unit_id: str) -> dict:
    return get_success_data(api_client.get_sample_unit(sample_unit_id, ADMIN))


def get_checkout(checkout_id: str) -> dict:
    return get_success_data(api_client.get_sample_checkout(checkout_id, ADMIN))


# ---------------------------------------------------------------------------
# Canonical base scenario (shared multi-step preamble)
# ---------------------------------------------------------------------------

def setup_base_scenario(
    quota_cents: int = TEST_DEFAULTS["QUOTA_CENTS"],
    notice_period_days: int = TEST_DEFAULTS["NOTICE_PERIOD_DAYS"],
    agreement_territories: Optional[List[str]] = None,
    specify_share_bp: int = TEST_DEFAULTS["SPECIFY_SHARE_BP"],
    registered_protection_share_bp: int = TEST_DEFAULTS["REGISTERED_PROTECTION_SHARE_BP"],
    tail_period_days: int = TEST_DEFAULTS["TAIL_PERIOD_DAYS"],
    family_rates: Optional[list] = None,
    attainment_tiers: Optional[list] = None,
    registration_bonus_bp: Optional[int] = TEST_DEFAULTS["REGISTRATION_BONUS_BP"],
    reps: tuple = (("R1", ["CA", "OR"]), ("R2", ["WA"])),
    customer_spec: str = "CA",
    customer_ship: str = "WA",
) -> dict:
    """Principal + ACTIVE agreement + ACTIVE rate schedule + reps + customer.

    Mirrors the canonical preamble shared by most flows: principal P1
    (quota 10,000,000c), agreement over [CA,OR,WA,TX] (specify 6000bp,
    registered-protection 10000bp, tail 180d), schedule CONNECTORS 1000bp /
    CABLES 800bp with tiers 0/80/100%, rep R1 [CA,OR], rep R2 [WA],
    customer C1 (spec CA, ship WA).
    """
    principal = create_principal(
        annual_quota_cents=quota_cents, notice_period_days=notice_period_days,
    )
    agreement = create_agreement(
        principal["id"],
        territory_codes=(agreement_territories if agreement_territories is not None
                         else ["CA", "OR", "WA", "TX"]),
        specify_share_bp=specify_share_bp,
        registered_protection_share_bp=registered_protection_share_bp,
        tail_period_days=tail_period_days,
    )
    activate_agreement(agreement["id"])
    schedule = create_rate_schedule(
        principal["id"], principal["version"],
        family_rates=family_rates or BASE_FAMILY_RATES,
        attainment_tiers=attainment_tiers or BASE_ATTAINMENT_TIERS,
        registration_bonus_bp=registration_bonus_bp,
    )
    rep_list = [create_rep(name, list(codes)) for name, codes in reps]
    customer = create_customer(
        spec_territory_code=customer_spec, ship_to_territory_code=customer_ship,
    )
    return {
        "principal": principal,
        "agreement": agreement,
        "schedule": schedule,
        "reps": rep_list,
        "customer": customer,
    }


# ---------------------------------------------------------------------------
# Project registrations (Rep-submit, PrincipalOps-approve)
# ---------------------------------------------------------------------------

def submit_registration(principal_id: str, customer_id: str, rep_id: str,
                        family_code: str = "CONNECTORS",
                        project_name: str = "Project Falcon") -> dict:
    payload = create_registration_payload(
        principal_id=principal_id, customer_id=customer_id,
        family_code=family_code, project_name=project_name,
    )
    return get_success_data(api_client.create_registration(payload, make_rep_headers(rep_id)))


def approve_registration(registration_id: str, principal_id: str) -> dict:
    return get_success_data(
        api_client.approve_registration(
            registration_id, make_principal_ops_headers(principal_id),
        )
    )


def reject_registration(registration_id: str, principal_id: str) -> dict:
    return get_success_data(
        api_client.reject_registration(
            registration_id, make_principal_ops_headers(principal_id),
        )
    )


def resubmit_registration(registration_id: str, rep_id: str) -> dict:
    return get_success_data(
        api_client.resubmit_registration(registration_id, make_rep_headers(rep_id))
    )


def renew_registration(registration_id: str, rep_id: str) -> dict:
    return get_success_data(
        api_client.renew_registration(registration_id, make_rep_headers(rep_id))
    )


def withdraw_registration(registration_id: str, rep_id: str) -> dict:
    return get_success_data(
        api_client.withdraw_registration(registration_id, make_rep_headers(rep_id))
    )


# ---------------------------------------------------------------------------
# Orders and fulfillment
# ---------------------------------------------------------------------------

def create_order(customer_id: str, principal_id: str,
                 external_order_ref: str = "PO-1",
                 placed_at: str = CLOCK_DEFAULT,
                 lines: Optional[List[dict]] = None) -> dict:
    payload = create_order_payload(
        customer_id, principal_id, external_order_ref, placed_at, lines,
    )
    return get_success_data(api_client.create_order(payload, ADMIN))


def ship_order(order_id: str, principal_id: str) -> dict:
    return get_success_data(
        api_client.ship_order(order_id, make_principal_ops_headers(principal_id))
    )


def invoice_order(order_id: str, principal_id: str) -> dict:
    return get_success_data(
        api_client.invoice_order(order_id, make_principal_ops_headers(principal_id))
    )


def mark_order_paid(order_id: str, principal_id: str) -> dict:
    return get_success_data(
        api_client.mark_order_paid(order_id, make_principal_ops_headers(principal_id))
    )


def cancel_order(order_id: str) -> dict:
    return get_success_data(api_client.cancel_order(order_id, ADMIN))


def create_invoiced_order(customer_id: str, principal_id: str,
                          external_order_ref: str = "PO-1",
                          placed_at: str = CLOCK_DEFAULT,
                          lines: Optional[List[dict]] = None) -> dict:
    """Create -> ship -> invoice. Returns the invoiced order."""
    order = create_order(customer_id, principal_id, external_order_ref, placed_at, lines)
    ship_order(order["id"], principal_id)
    return invoice_order(order["id"], principal_id)


def list_splits(order_id: Optional[str] = None, rep_id: Optional[str] = None) -> list:
    params = {k: v for k, v in (("order_id", order_id), ("rep_id", rep_id)) if v}
    data, _meta = validate_paginated(api_client.list_order_splits(ADMIN, params=params or None))
    return data


def list_orders(**params) -> list:
    data, _meta = validate_paginated(api_client.list_orders(ADMIN, params=params or None))
    return data


# ---------------------------------------------------------------------------
# Returns (RMA)
# ---------------------------------------------------------------------------

def create_rma(order_id: str, lines: List[dict]) -> dict:
    return get_success_data(api_client.create_rma(create_rma_payload(order_id, lines), ADMIN))


def approve_rma(rma_id: str, principal_id: str) -> dict:
    return get_success_data(
        api_client.approve_rma(rma_id, make_principal_ops_headers(principal_id))
    )


def reject_rma(rma_id: str, principal_id: str) -> dict:
    return get_success_data(
        api_client.reject_rma(rma_id, make_principal_ops_headers(principal_id))
    )


def receive_rma(rma_id: str, principal_id: str) -> dict:
    return get_success_data(
        api_client.receive_rma(rma_id, make_principal_ops_headers(principal_id))
    )


# ---------------------------------------------------------------------------
# Commission ledger and statements
# ---------------------------------------------------------------------------

def post_adjustment(rep_id: str, amount_cents: int, note: str = "manual adjustment",
                    principal_id: Optional[str] = None) -> dict:
    return get_success_data(
        api_client.post_rep_adjustment(
            rep_id, create_adjustment_payload(amount_cents, note, principal_id), ADMIN,
        )
    )


def list_entries(rep_id: Optional[str] = None, principal_id: Optional[str] = None,
                 order_id: Optional[str] = None, statement_id: Optional[str] = None,
                 entry_type: Optional[str] = None) -> list:
    params = {}
    if rep_id:
        params["rep_id"] = rep_id
    if principal_id:
        params["principal_id"] = principal_id
    if order_id:
        params["order_id"] = order_id
    if statement_id:
        params["statement_id"] = statement_id
    if entry_type:
        params["type"] = entry_type
    data, _meta = validate_paginated(
        api_client.list_commission_entries(ADMIN, params=params or None)
    )
    return data


def create_statement(principal_id: str, period_label: str, lines: List[dict]) -> dict:
    payload = create_statement_payload(principal_id, period_label, lines)
    return get_success_data(
        api_client.create_statement(payload, make_principal_ops_headers(principal_id))
    )


def start_reconciliation(statement_id: str) -> dict:
    return get_success_data(api_client.start_reconciliation(statement_id, ADMIN))


def accept_variance(statement_id: str, line_id: str) -> dict:
    return get_success_data(api_client.accept_variance(statement_id, line_id, ADMIN))


def dispute_line(statement_id: str, line_id: str, reason: str = "disputed") -> dict:
    return get_success_data(
        api_client.dispute_statement_line(statement_id, line_id, {"reason": reason}, ADMIN)
    )


def respond_dispute(statement_id: str, principal_id: str, line_id: str, action: str,
                    adjustment_amount_cents: Optional[int] = None) -> dict:
    payload = {"line_id": line_id, "action": action}
    if adjustment_amount_cents is not None:
        payload["adjustment_amount_cents"] = adjustment_amount_cents
    return get_success_data(
        api_client.respond_dispute(
            statement_id, payload, make_principal_ops_headers(principal_id),
        )
    )


def settle_statement(statement_id: str) -> dict:
    return get_success_data(api_client.settle_statement(statement_id, ADMIN))


# ---------------------------------------------------------------------------
# Sample inventory
# ---------------------------------------------------------------------------

def create_sample_unit(principal_id: str, serial_number: str = "S-1",
                       family_code: str = "CONNECTORS", value_cents: int = 80_000) -> dict:
    payload = create_sample_unit_payload(
        principal_id, serial_number=serial_number,
        family_code=family_code, value_cents=value_cents,
    )
    return get_success_data(
        api_client.create_sample_unit(payload, make_principal_ops_headers(principal_id))
    )


def checkout_sample(sample_unit_id: str, rep_id: str) -> dict:
    return get_success_data(
        api_client.create_sample_checkout(
            create_sample_checkout_payload(sample_unit_id), make_rep_headers(rep_id),
        )
    )


def return_checkout(checkout_id: str, rep_id: str, condition: str = "SELLABLE") -> dict:
    return get_success_data(
        api_client.return_sample_checkout(
            checkout_id, {"condition_on_return": condition}, make_rep_headers(rep_id),
        )
    )


def convert_checkout(checkout_id: str, rep_id: str) -> dict:
    return get_success_data(
        api_client.convert_sample_checkout(checkout_id, make_rep_headers(rep_id))
    )


def list_units(principal_id: Optional[str] = None, status: Optional[str] = None) -> list:
    params = {}
    if principal_id:
        params["principal_id"] = principal_id
    if status:
        params["status"] = status
    data, _meta = validate_paginated(api_client.list_sample_units(ADMIN, params=params or None))
    return data


__all__ = [name for name in dir() if not name.startswith("_")]
