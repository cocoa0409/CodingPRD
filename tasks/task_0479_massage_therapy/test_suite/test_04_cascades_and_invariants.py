"""Cascading transitions (consent revoke, membership void) and conserved-quantity invariants.

Covers difficulty queue A instances on the consent-revoke depth-2 cascade, the void-PRICED
depth-3 credit-refund cascade, and the redeem/void package-credit conservation invariant.
"""
from test_helpers import (
    validate_success,
    bookable_scenario,
    book_appointment,
    drive_to_priced,
    set_clock,
    create_plan,
    create_package,
    make_client_headers,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]
FRONT = TEST_USERS["front_desk_headers"]


def test_consent_revoke_cascades_cancel_scheduled_appointment(api):
    """PRD §3.2: "Revoking consent that a live session still depends on cascades: every
    appointment referencing that consent whose scheduling_status is SCHEDULED or CHECKED_IN is
    cancelled with cancel_reason CONSENT_REVOKED, carries no fee, and — if a membership credit
    had been redeemed for it — has that credit refunded to the package, which in turn recomputes
    the package's credit balance."

    Revoking consent under a SCHEDULED membership appointment (never priced, so no credit
    redeemed) cancels it with cancel_reason CONSENT_REVOKED and leaves the package balance at
    the granted 1.

    Design: Difficulty/transitive_cascade/consent_revoke_cascade_depth2
    """
    set_clock("2026-03-02T08:00:00Z")
    scn = bookable_scenario()
    plan = create_plan(name="MemPlanRevoke", monthly_fee_cents=9000, included_sessions=1,
                       member_discount_pct=0.20, rollover_cap_sessions=1)
    pkg = create_package(scn["client"]["id"], plan["id"], cycle_anchor_day=1)
    appt = book_appointment(scn, package_id=pkg["id"],
                            start_at="2026-03-02T10:00:00Z", duration_minutes=60, payer="MEMBERSHIP")
    revoked = validate_success(api.revoke_consent(
        scn["consent"]["id"], make_client_headers(scn["client"]["id"])))
    assert revoked["consent_status"] == "REVOKED"
    fetched = validate_success(api.get_appointment(appt["id"], FRONT))
    assert fetched["scheduling_status"] == "CANCELLED"
    assert fetched["cancel_reason"] == "CONSENT_REVOKED"
    pkg_after = validate_success(api.get_package(pkg["id"], ADMIN))
    assert pkg_after["credit_balance_sessions"] == 1, \
        f"unredeemed credit stays at 1, got {pkg_after['credit_balance_sessions']}"


def test_consent_revoke_sets_consent_revoked(api):
    """PRD §3.2: "A client may revoke their own consent, moving it to REVOKED; revoking is
    allowed only from ACTIVE and only by the owning client."

    Design: Difficulty/transitive_cascade/consent_revoke_cascade_depth2
    """
    set_clock("2026-03-02T08:00:00Z")
    scn = bookable_scenario()
    book_appointment(scn, start_at="2026-03-02T10:00:00Z", duration_minutes=60, payer="CASH")
    revoked = validate_success(api.revoke_consent(
        scn["consent"]["id"], make_client_headers(scn["client"]["id"])))
    assert revoked["consent_status"] == "REVOKED"


def test_void_priced_membership_refunds_credit_cascade(api):
    """PRD §3.9: "If the session being voided had redeemed a membership credit at pricing, the
    void compensates by writing a REFUND ledger entry (delta plus one session) against the
    package and recomputing its credit_balance_sessions." PRD §3.10: "the latest entry's
    balance_after always equals the package's current balance."

    Voiding a PRICED membership appointment (credit redeemed, balance 0 of 1) writes a REFUND
    ledger entry and recomputes the balance back to 1.

    Design: Difficulty/transitive_cascade/void_priced_membership_cascade_depth3
    """
    set_clock("2026-03-02T08:00:00Z")
    scn = bookable_scenario()
    plan = create_plan(name="MemPlanVoid", monthly_fee_cents=9000, included_sessions=1,
                       member_discount_pct=0.20, rollover_cap_sessions=1)
    pkg = create_package(scn["client"]["id"], plan["id"], cycle_anchor_day=1)
    appt, _ = drive_to_priced(scn, package_id=pkg["id"],
                              start_at="2026-03-02T09:00:00Z", duration_minutes=60, payer="MEMBERSHIP")
    # After redemption the balance is 0.
    pkg_priced = validate_success(api.get_package(pkg["id"], ADMIN))
    assert pkg_priced["credit_balance_sessions"] == 0
    voided = validate_success(api.void_appointment(appt["id"], ADMIN))
    assert voided["settlement_status"] == "VOID"
    pkg_after = validate_success(api.get_package(pkg["id"], ADMIN))
    assert pkg_after["credit_balance_sessions"] == 1
    ledger = validate_success(api.get_package_ledger(pkg["id"], ADMIN))
    assert ledger[-1]["reason"] == "REFUND"
    assert ledger[-1]["balance_after"] == 1


def test_void_priced_membership_settlement_void(api):
    """PRD §3.9: "A PracticeAdmin may void a settlement that has not been paid. Voiding is
    allowed while settlement_status is UNSETTLED or PRICED and moves it to VOID."

    Design: Difficulty/transitive_cascade/void_priced_membership_cascade_depth3
    """
    set_clock("2026-03-02T08:00:00Z")
    scn = bookable_scenario()
    plan = create_plan(name="MemPlanVoid2", monthly_fee_cents=9000, included_sessions=1,
                       member_discount_pct=0.20, rollover_cap_sessions=1)
    pkg = create_package(scn["client"]["id"], plan["id"], cycle_anchor_day=1)
    appt, _ = drive_to_priced(scn, package_id=pkg["id"],
                              start_at="2026-03-02T09:00:00Z", duration_minutes=60, payer="MEMBERSHIP")
    voided = validate_success(api.void_appointment(appt["id"], ADMIN))
    assert voided["settlement_status"] == "VOID"


def test_redeem_then_void_conserves_package_credits(api):
    """PRD §3.8: "the redemption writes a CreditLedgerEntry with reason REDEEM and a delta of
    minus one session against the package and recomputes the package's credit_balance_sessions."
    PRD §3.9: "the void compensates by writing a REFUND ledger entry (delta plus one session)
    against the package and recomputing its credit_balance_sessions."

    Redeem (-1) at PRICE then void (+1) at PRICED conserves the package credit at its pre-redeem
    value of 1, with the ledger's latest balance_after matching.

    Design: Difficulty/compensating_invariant/redeem_then_void_conserves_package_credits
    """
    set_clock("2026-03-02T07:00:00Z")
    scn = bookable_scenario()
    plan = create_plan(name="ConsPlan", monthly_fee_cents=9000, included_sessions=1,
                       member_discount_pct=0.20, rollover_cap_sessions=1)
    pkg = create_package(scn["client"]["id"], plan["id"], cycle_anchor_day=1)
    appt, _ = drive_to_priced(scn, package_id=pkg["id"],
                              start_at="2026-03-02T09:00:00Z", duration_minutes=60, payer="MEMBERSHIP")
    validate_success(api.void_appointment(appt["id"], ADMIN))
    pkg_after = validate_success(api.get_package(pkg["id"], ADMIN))
    assert pkg_after["credit_balance_sessions"] == 1, \
        f"redeem+void must conserve credits at 1, got {pkg_after['credit_balance_sessions']}"
    ledger = validate_success(api.get_package_ledger(pkg["id"], ADMIN))
    assert ledger[-1]["balance_after"] == 1


def test_redeem_debits_credit_at_price(api):
    """PRD §3.8: "provided a credit has not already been debited for this appointment, it writes
    a CreditLedgerEntry with reason REDEEM and a delta of minus one session against the package
    and recomputes the package's credit_balance_sessions."

    Pricing a MEMBERSHIP appointment debits the single credit (balance 1 -> 0) before the
    compensating void restores it.

    Design: Difficulty/compensating_invariant/redeem_then_void_conserves_package_credits
    """
    set_clock("2026-03-02T07:00:00Z")
    scn = bookable_scenario()
    plan = create_plan(name="ConsPlan2", monthly_fee_cents=9000, included_sessions=1,
                       member_discount_pct=0.20, rollover_cap_sessions=1)
    pkg = create_package(scn["client"]["id"], plan["id"], cycle_anchor_day=1)
    drive_to_priced(scn, package_id=pkg["id"],
                    start_at="2026-03-02T09:00:00Z", duration_minutes=60, payer="MEMBERSHIP")
    pkg_priced = validate_success(api.get_package(pkg["id"], ADMIN))
    assert pkg_priced["credit_balance_sessions"] == 0, \
        f"redeem at price should debit to 0, got {pkg_priced['credit_balance_sessions']}"
