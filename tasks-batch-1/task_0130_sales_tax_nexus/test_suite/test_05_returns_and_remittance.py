"""Tax-return workflow: nexus-registration precondition, the filing lock on
swept transactions, the accept-time sweep cascade, amount matching, and the
OCC stale-version guard on remittance.

Queue A: cross_entity_state_dependency, transitive_cascade (accept path).
Queue B: validations (amount mismatch) + cross_cutting (OCC stale version).
"""
import pytest

from test_helpers import (
    make_seller_headers,
    validate_error,
    validate_success,
)
from test_helpers import fixtures as fx
from test_helpers.test_users import make_approver_headers


# ===========================================================================
# Queue A — cross_entity_state_dependency
# ===========================================================================

def test_return_accept_requires_nexus_profile_registered(api):
    """PRD §3.9: "Acceptance further requires that the seller's `NexusProfile` for this state be `REGISTERED`; if it is not, the attempt is rejected with `ERR_NEXUS_NOT_REGISTERED`."

    Design: Difficulty/cross_entity_state_dependency/return_accept_requires_nexusprofile_registered
    """
    fx.set_clock("2026-02-15T00:00:00Z")
    ca = fx.create_ca_jurisdiction()
    fx.create_category(ca["id"], "TANGIBLE", "FULL")
    seller = fx.create_seller(origin_state_code="CA")
    fx.create_nexus_profile(seller["id"], ca["id"])
    # Cross the threshold (THRESHOLD_MET) but DO NOT register.
    fx.settle_one_full_line(seller["id"], ca["id"], 100000.00, customer_ref="big")
    ret = fx.create_draft_return(seller["id"], ca["id"])
    res = api.accept_tax_return(ret["id"], make_approver_headers())
    validate_error(res, "ERR_NEXUS_NOT_REGISTERED", expected_status=409)


def test_return_accept_succeeds_when_nexus_profile_registered(api):
    """PRD §3.9: "When all preconditions hold, acceptance sweeps the period's activity, computes `tax_due`, records the approver in `approved_by`, advances `DRAFT → ACCEPTED`, appends an `AuditLogEntry` recording the acceptance, and increments the return's `version`."

    Design: Difficulty/cross_entity_state_dependency/return_accept_requires_nexusprofile_registered
    """
    fx.set_clock("2026-02-15T00:00:00Z")
    ca, seller, profile = fx.setup_registered_seller_ca()  # crosses threshold and registers
    assert profile["nexus_status"] == "REGISTERED", f"setup expected REGISTERED, got {profile['nexus_status']}"
    ret = fx.create_draft_return(seller["id"], ca["id"])
    accepted = validate_success(api.accept_tax_return(ret["id"], make_approver_headers()), 200)
    assert accepted["status"] == "ACCEPTED", \
        f"accept must succeed once the profile is REGISTERED, got {accepted['status']}"


def test_transaction_void_blocked_when_swept_into_return(api):
    """PRD §3.5: "voiding a transaction whose `tax_return_id` is already set (it has been swept into a return) is rejected with `ERR_TRANSACTION_LOCKED`."

    Design: Difficulty/cross_entity_state_dependency/transaction_void_blocked_when_swept_into_return
    """
    fx.set_clock("2026-02-15T00:00:00Z")
    ca, seller, profile = fx.setup_registered_seller_ca()  # already creates the TANGIBLE category
    small = fx.settle_one_full_line(seller["id"], ca["id"], 7.95, customer_ref="small")
    ret = fx.create_draft_return(seller["id"], ca["id"])
    fx.accept_return(ret["id"])  # sweep sets small.tax_return_id
    res = api.void_transaction(small["id"], make_seller_headers(seller["id"]))
    validate_error(res, "ERR_TRANSACTION_LOCKED", expected_status=409)


def test_unswept_settled_transaction_can_still_be_voided(api):
    """PRD §3.5: "A settled transaction may later be voided by the seller, but only while it is still `SETTLED` and has not been swept into a return."

    Design: Difficulty/cross_entity_state_dependency/transaction_void_blocked_when_swept_into_return
    """
    fx.set_clock("2026-02-15T00:00:00Z")
    ca, seller, profile = fx.setup_registered_seller_ca()  # already creates the TANGIBLE category
    # A SETTLED SELLER transaction that is never swept into any return.
    free = fx.settle_one_full_line(seller["id"], ca["id"], 7.95, customer_ref="free")
    assert free["tax_return_id"] is None, f"setup: must be unswept, got {free['tax_return_id']}"
    voided = validate_success(api.void_transaction(free["id"], make_seller_headers(seller["id"])), 200)
    assert voided["settlement_status"] == "VOIDED", \
        f"an unswept SETTLED transaction must be voidable, got {voided['settlement_status']}"


# ===========================================================================
# Queue A — transitive_cascade (accept sweeps transactions + use-tax)
# ===========================================================================

def test_accept_sweeps_transaction_and_usetax_into_tax_due(api):
    """PRD §3.9: "The return's `tax_due` is then the sum of every swept transaction's `tax_collected` plus the sum of every swept accrual's `accrued_use_tax`, rounded half-up to two decimal places."

    Design: Difficulty/transitive_cascade/accept_sweep_transactions_and_usetax_depth2
    """
    fx.set_clock("2026-02-15T00:00:00Z")
    ca, seller, profile = fx.setup_registered_seller_ca()
    # One small SELLER sale: two FULL lines 7.95 -> tax_collected 1.32.
    fx.create_and_settle_transaction(
        seller["id"], ca["id"],
        [{"category_code": "TANGIBLE", "quantity": 1, "unit_price": 7.95},
         {"category_code": "TANGIBLE", "quantity": 1, "unit_price": 7.95}],
        customer_ref="small", customer_exempt_requested=False)
    # One ACCRUED use-tax 1200.00 @ 0.0825 -> 99.00.
    fx.create_use_tax_accrual(seller["id"], ca["id"], purchase_amount=1200.00)
    ret = fx.create_draft_return(seller["id"], ca["id"])
    accepted = fx.accept_return(ret["id"])
    assert accepted["status"] == "ACCEPTED", f"got {accepted['status']}"
    # 1.32 sales + 99.00 use = 100.32.
    assert accepted["tax_due"] == 100.32, f"expected tax_due 100.32, got {accepted['tax_due']}"


def test_accept_marks_swept_usetax_included_in_return(api):
    """PRD §3.9: "each such accrual has its `tax_return_id` set and its `status` advanced to `INCLUDED_IN_RETURN`."

    Design: Difficulty/transitive_cascade/accept_sweep_transactions_and_usetax_depth2
    """
    fx.set_clock("2026-02-15T00:00:00Z")
    ca, seller, profile = fx.setup_registered_seller_ca()
    fx.create_and_settle_transaction(
        seller["id"], ca["id"],
        [{"category_code": "TANGIBLE", "quantity": 1, "unit_price": 7.95},
         {"category_code": "TANGIBLE", "quantity": 1, "unit_price": 7.95}],
        customer_ref="small", customer_exempt_requested=False)
    accrual = fx.create_use_tax_accrual(seller["id"], ca["id"], purchase_amount=1200.00)
    ret = fx.create_draft_return(seller["id"], ca["id"])
    accepted = fx.accept_return(ret["id"])
    refreshed = validate_success(
        api.get_use_tax_accrual(accrual["id"], make_seller_headers(seller["id"])), 200)
    assert refreshed["status"] == "INCLUDED_IN_RETURN", \
        f"swept accrual must become INCLUDED_IN_RETURN, got {refreshed['status']}"
    assert refreshed["tax_return_id"] == accepted["id"], \
        f"swept accrual's tax_return_id must be the return id, got {refreshed['tax_return_id']}"


# ===========================================================================
# Queue B — validations (amount mismatch)
# ===========================================================================

def test_remit_wrong_amount_returns_amount_mismatch(api):
    """PRD §3.10: "The `amount` must equal the return's `tax_due` exactly — a partial or excess payment is rejected with `ERR_AMOUNT_MISMATCH` — and the `amount` itself must be strictly greater than zero."

    Design: Corner/validations/remit_wrong_amount_returns_amount_mismatch
    """
    ctx = fx.setup_filed_return_ca(small_unit_price=10.00)  # tax_due 0.83
    ret = ctx["tax_return"]
    assert ret["tax_due"] == 0.83, f"setup sanity: expected 0.83, got {ret['tax_due']}"
    payload = {
        "tax_return_id": ret["id"],
        "amount": 1.00,  # != tax_due 0.83
        "expected_tax_return_version": ctx["filed_version"],
    }
    res = api.create_remittance_payment(payload, make_approver_headers())
    validate_error(res, "ERR_AMOUNT_MISMATCH", expected_status=422)


# ===========================================================================
# Queue B — cross_cutting (OCC stale version)
# ===========================================================================

def test_remit_stale_expected_version_returns_412(api):
    """PRD §2.8: "If `expected_tax_return_version` does not equal the return's current `version` — meaning another writer has advanced the return since the client read it — the request is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting/remit_stale_expected_version_returns_412
    """
    ctx = fx.setup_filed_return_ca(small_unit_price=10.00)
    ret = ctx["tax_return"]
    payload = {
        "tax_return_id": ret["id"],
        "amount": 0.83,
        "expected_tax_return_version": ctx["filed_version"] - 1,  # stale
    }
    res = api.create_remittance_payment(payload, make_approver_headers())
    validate_error(res, "ERR_STALE_VERSION", expected_status=412)
