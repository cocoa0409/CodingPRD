"""Composite setup helpers.

Every helper builds its preconditions from scratch (the server DB is empty before
each test) using only PRD-declared endpoints. Setup uses get_success_data() so
setup failures surface as clear "Setup failed" errors rather than assertion noise.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import (
    TEST_USERS,
    make_finance_approver_headers,
    make_cost_center_owner_headers,
    make_vendor_headers,
)
from . import factories as f

_SOURCING = TEST_USERS["sourcing_headers"]
_ANALYST = TEST_USERS["analyst_headers"]
_ADMIN = TEST_USERS["system_admin_headers"]

# Default financial scenario values shared across recipes.
DEFAULT_TERM_START = "2026-01-01T00:00:00Z"
DEFAULT_TERM_END = "2026-12-31T00:00:00Z"


# ---------------------------------------------------------------------------
# Building blocks
# ---------------------------------------------------------------------------

def set_clock(api, iso: str):
    """Set the server logical clock (SystemAdmin)."""
    return get_success_data(api.set_clock({"to_iso8601": iso}, _ADMIN))


def new_vendor(api, name="Acme SaaS", vendor_type="SAAS") -> dict:
    return get_success_data(api.create_vendor(f.create_vendor_payload(name=name, vendor_type=vendor_type), _SOURCING))


def new_contract(api, vendor_id, **overrides) -> dict:
    return get_success_data(api.create_contract(f.create_contract_payload(vendor_id, **overrides), _SOURCING))


def activate(api, contract_id) -> dict:
    return get_success_data(api.activate_contract(contract_id, _SOURCING))


def new_service(api, contract_id, **overrides) -> dict:
    return get_success_data(api.create_service(f.create_service_payload(contract_id, **overrides), _SOURCING))


def new_invoice(api, contract_id, **overrides) -> dict:
    return get_success_data(api.create_invoice(f.create_invoice_payload(contract_id, **overrides), _ANALYST))


def new_line_item(api, invoice_id, service_id, **overrides) -> dict:
    return get_success_data(
        api.create_line_item(invoice_id, f.create_line_item_payload(service_id, **overrides), _ANALYST))


def review(api, invoice_id) -> dict:
    return get_success_data(api.review_invoice(invoice_id, _ANALYST))


def new_cost_center(api, code, gl_account, owner_user_id) -> dict:
    return get_success_data(
        api.create_cost_center(f.create_cost_center_payload(code, gl_account, owner_user_id), _ADMIN))


def new_dispute(api, line_id, disputed_amount_cents, claimed_credit_cents, **overrides) -> dict:
    return get_success_data(api.create_dispute(
        line_id, f.create_dispute_payload(disputed_amount_cents, claimed_credit_cents, **overrides), _ANALYST))


def vendor_respond(api, dispute_id, vendor_id, response_type, offered_credit_cents) -> dict:
    return get_success_data(api.respond_dispute(
        dispute_id, f.respond_dispute_payload(response_type, offered_credit_cents), make_vendor_headers(vendor_id)))


def analyst_resubmit(api, dispute_id, claimed_credit_cents) -> dict:
    return get_success_data(api.resubmit_dispute(
        dispute_id, f.resubmit_dispute_payload(claimed_credit_cents), _ANALYST))


# ---------------------------------------------------------------------------
# Composite scenarios
# ---------------------------------------------------------------------------

def setup_active_contract(api, *, vendor_type="SAAS", contract_overrides=None) -> dict:
    """Vendor (ACTIVE) + contract activated to ACTIVE. Returns {vendor, contract}."""
    contract_overrides = contract_overrides or {}
    vendor = new_vendor(api, vendor_type=vendor_type)
    contract = new_contract(api, vendor["id"], **contract_overrides)
    contract = activate(api, contract["id"])
    return {"vendor": vendor, "contract": contract}


def setup_service(api, *, vendor_type="SAAS", contract_overrides=None, service_overrides=None) -> dict:
    """Active contract + one ACTIVE service. Returns {vendor, contract, service}."""
    service_overrides = service_overrides or {}
    base = setup_active_contract(api, vendor_type=vendor_type, contract_overrides=contract_overrides)
    service = new_service(api, base["contract"]["id"], **service_overrides)
    base["service"] = service
    # Creating a service refreshes the parent contract's monthly_committed_cost_cents
    # (PRD §3.2); re-fetch so base["contract"] reflects the recomputed figure rather
    # than the stale pre-service snapshot from setup_active_contract.
    base["contract"] = get_success_data(api.get_contract(base["contract"]["id"], _SOURCING))
    return base


def setup_invoice_with_line(api, *, vendor_type="SAAS", contract_overrides=None,
                            service_overrides=None, invoice_overrides=None,
                            line_overrides=None, do_review=False) -> dict:
    """Active contract + service + RECEIVED invoice + one line item.

    do_review=True moves the invoice to UNDER_REVIEW (recomputing final expected).
    Returns {vendor, contract, service, invoice, line}.
    """
    invoice_overrides = invoice_overrides or {}
    line_overrides = line_overrides or {}
    base = setup_service(api, vendor_type=vendor_type, contract_overrides=contract_overrides,
                         service_overrides=service_overrides)
    invoice = new_invoice(api, base["contract"]["id"], **invoice_overrides)
    line = new_line_item(api, invoice["id"], base["service"]["id"], **line_overrides)
    if do_review:
        invoice = review(api, invoice["id"])
    base["invoice"] = invoice
    base["line"] = line
    return base


def setup_submitted_dispute(api, *, line_billed_amount_cents=100000, disputed_amount_cents=9500,
                            claimed_credit_cents=9500) -> dict:
    """Reviewed invoice + a SUBMITTED dispute on the line (invoice now DISPUTED).
    Returns {vendor, contract, service, invoice, line, dispute}.
    """
    scen = setup_invoice_with_line(
        api,
        line_overrides={"billed_amount_cents": line_billed_amount_cents, "billed_quantity": 60},
        do_review=True,
    )
    dispute = new_dispute(api, scen["line"]["id"], disputed_amount_cents, claimed_credit_cents)
    scen["dispute"] = dispute
    return scen


def setup_vendor_responded_dispute(api, *, line_billed_amount_cents=100000, disputed_amount_cents=8000,
                                   claimed_credit_cents=8000, offered_credit_cents=8000,
                                   response_type="PARTIAL") -> dict:
    """SUBMITTED dispute advanced to VENDOR_RESPONDED. Returns full scenario + dispute."""
    scen = setup_submitted_dispute(
        api,
        line_billed_amount_cents=line_billed_amount_cents,
        disputed_amount_cents=disputed_amount_cents,
        claimed_credit_cents=claimed_credit_cents,
    )
    scen["dispute"] = vendor_respond(
        api, scen["dispute"]["id"], scen["vendor"]["id"], response_type, offered_credit_cents)
    return scen


def setup_posted_allocation(api, *, line_billed_amount_cents=100000, owner_user_id="own_ops") -> dict:
    """Reviewed invoice + one POSTED allocation (weight 100) on the line.
    Returns {vendor, contract, service, invoice, line, cost_center, allocation}.
    """
    scen = setup_invoice_with_line(
        api,
        line_overrides={"billed_amount_cents": line_billed_amount_cents, "billed_quantity": 60},
        do_review=True,
    )
    cc = new_cost_center(api, "OPS", "6000", owner_user_id)
    allocs = get_success_data(api.create_allocations(
        scen["line"]["id"], f.allocations_payload([{"cost_center_id": cc["id"], "weight_pct": 100.00}]), _ANALYST))
    alloc = allocs[0]
    posted = get_success_data(api.approve_allocation(alloc["id"], make_cost_center_owner_headers(owner_user_id)))
    scen["cost_center"] = cc
    scen["allocation"] = posted
    return scen


def setup_proposed_recommendation(api, *, rec_type="DOWNGRADE_SEATS", target_quantity=45,
                                  service_overrides=None, contract_overrides=None,
                                  clock_iso=None) -> dict:
    """Active contract + service + one PROPOSED recommendation.
    Returns {vendor, contract, service, service_version, recommendation}.
    """
    scen = setup_service(api, contract_overrides=contract_overrides, service_overrides=service_overrides)
    if clock_iso is not None:
        set_clock(api, clock_iso)
    ver = scen["service"]["version"]
    rec = get_success_data(api.create_recommendation(
        scen["service"]["id"],
        f.create_recommendation_payload(rec_type, target_quantity, ver),
        _ANALYST,
    ))
    scen["service_version"] = ver
    scen["recommendation"] = rec
    return scen


def setup_three_cost_centers(api) -> list:
    """Three ACTIVE cost centers A/B/C (owners own_a/own_b/own_c). Returns list of dicts."""
    return [
        new_cost_center(api, "CC-A", "6000", "own_a"),
        new_cost_center(api, "CC-B", "6001", "own_b"),
        new_cost_center(api, "CC-C", "6002", "own_c"),
    ]


def setup_approved_invoice(api, *, approver_user_id="fa_1") -> dict:
    """Active contract + RECEIVED invoice reviewed then APPROVED by approver_user_id.
    Returns {vendor, contract, invoice}.
    """
    base = setup_active_contract(api)
    invoice = new_invoice(api, base["contract"]["id"])
    review(api, invoice["id"])
    invoice = get_success_data(
        api.approve_invoice(invoice["id"], make_finance_approver_headers(approver_user_id)))
    base["invoice"] = invoice
    return base
