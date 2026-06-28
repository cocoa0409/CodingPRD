"""Membership credits, the empty-balance redemption block, rollover, and HSA payment.

Covers the difficulty queue A boundary instance on zero-credit redemption, plus corner queue B
calculation/error claims for rollover, renewal timing, and HSA insufficiency.
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    bookable_scenario,
    drive_to_priced,
    drive_to_completed,
    set_clock,
    create_plan,
    create_package,
    create_table,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]
FRONT = TEST_USERS["front_desk_headers"]


def test_empty_credit_balance_blocks_membership_redeem(api):
    """PRD §3.10: "at price time the payer must be MEMBERSHIP, a package_id must be supplied,
    the package must be ACTIVE, it must belong to the appointment's client, and its
    credit_balance_sessions must be at least 1. If any of those fail, pricing is rejected with
    ERR_NO_CREDITS."

    A second MEMBERSHIP appointment priced after the single included credit was already spent
    (balance 0) is rejected with ERR_NO_CREDITS.

    Design: Difficulty/boundary_precision_check/empty_credit_balance_blocks_membership_redeem
    """
    set_clock("2026-03-02T08:00:00Z")
    scn = bookable_scenario()
    plan = create_plan(name="OneCreditPlan", monthly_fee_cents=9000, included_sessions=1,
                       member_discount_pct=0.20, rollover_cap_sessions=1)
    pkg = create_package(scn["client"]["id"], plan["id"], cycle_anchor_day=1)
    # First membership appointment spends the single credit (balance 1 -> 0).
    drive_to_priced(scn, package_id=pkg["id"],
                    start_at="2026-03-02T09:00:00Z", duration_minutes=60, payer="MEMBERSHIP")
    pkg_after = validate_success(api.get_package(pkg["id"], ADMIN))
    assert pkg_after["credit_balance_sessions"] == 0
    # Second membership appointment, completed; pricing finds balance 0.
    tbl2 = create_table()
    appt2, _ = drive_to_completed(scn, table=tbl2, package_id=pkg["id"],
                                  start_at="2026-03-02T11:00:00Z", duration_minutes=60, payer="MEMBERSHIP")
    validate_error(api.price_appointment(appt2["id"], FRONT), ApiErrorId.ERR_NO_CREDITS.value)
    pkg_final = validate_success(api.get_package(pkg["id"], ADMIN))
    assert pkg_final["credit_balance_sessions"] == 0


def test_membership_redeem_succeeds_with_one_credit(api):
    """PRD §3.10: "its credit_balance_sessions must be at least 1. If any of those fail, pricing
    is rejected with ERR_NO_CREDITS; otherwise the redemption writes the REDEEM ledger entry
    described in §3.8."

    With balance 1 (>= 1), pricing a MEMBERSHIP appointment succeeds and debits to 0.

    Design: Difficulty/boundary_precision_check/empty_credit_balance_blocks_membership_redeem
    """
    set_clock("2026-03-02T08:00:00Z")
    scn = bookable_scenario()
    plan = create_plan(name="OneCreditPlanOK", monthly_fee_cents=9000, included_sessions=1,
                       member_discount_pct=0.20, rollover_cap_sessions=1)
    pkg = create_package(scn["client"]["id"], plan["id"], cycle_anchor_day=1)
    appt, _ = drive_to_completed(scn, package_id=pkg["id"],
                                 start_at="2026-03-02T09:00:00Z", duration_minutes=60, payer="MEMBERSHIP")
    priced = validate_success(api.price_appointment(appt["id"], FRONT))
    assert priced["settlement_status"] == "PRICED"
    assert priced["service_charge_cents"] == 0
    pkg_after = validate_success(api.get_package(pkg["id"], ADMIN))
    assert pkg_after["credit_balance_sessions"] == 0


# ---------------------------------------------------------------------------
# Corner queue B — calculations / errors
# ---------------------------------------------------------------------------
def test_rollover_under_cap_no_forfeit(api):
    """PRD §3.10: "When the balance is at or under the cap, nothing is forfeited and all unused
    credits roll forward before the grant." PRD §3.10: "the new credit_balance_sessions equals
    the kept amount plus included_sessions."

    Plan included 2 / cap 1; spend one credit (balance 2 -> 1); renewal keeps min(1,1)=1 +
    granted 2 -> 3, with no ROLLOVER_FORFEIT entry (latest entry is GRANT).

    Design: Corner/calculations/rollover_under_cap_no_forfeit
    """
    set_clock("2026-01-01T00:00:00Z")
    scn = bookable_scenario()
    plan = create_plan(name="UnderCapPlanB", monthly_fee_cents=9000, included_sessions=2,
                       member_discount_pct=0.20, rollover_cap_sessions=1)
    pkg = create_package(scn["client"]["id"], plan["id"])
    drive_to_priced(scn, package_id=pkg["id"],
                    start_at="2026-01-05T09:00:00Z", duration_minutes=60, payer="MEMBERSHIP")
    pkg_spent = validate_success(api.get_package(pkg["id"], ADMIN))
    assert pkg_spent["credit_balance_sessions"] == 1
    set_clock("2026-02-02T00:00:00Z")
    renewed = validate_success(api.renew_package(pkg["id"], ADMIN))
    assert renewed["credit_balance_sessions"] == 3, \
        f"kept 1 + granted 2 should be 3, got {renewed['credit_balance_sessions']}"
    ledger = validate_success(api.get_package_ledger(pkg["id"], ADMIN))
    assert ledger[-1]["reason"] == "GRANT"
    assert ledger[-1]["balance_after"] == 3


def test_renew_too_early_rejected(api):
    """PRD §3.10: "renewal is permitted only while package_status is ACTIVE and only when the
    clock has reached or passed current_cycle_end; an early attempt is rejected with
    ERR_RENEWAL_TOO_EARLY."

    Design: Corner/calculations/renew_too_early_rejected
    """
    set_clock("2026-01-01T00:00:00Z")
    plan = create_plan(name="EarlyPlanB", monthly_fee_cents=9000, included_sessions=1)
    client = validate_success(api.create_client(
        {"full_name": "Early Cli", "email": "earlycli@example.com"}, FRONT), expected_status=201)
    pkg = create_package(client["id"], plan["id"])
    validate_error(api.renew_package(pkg["id"], ADMIN), ApiErrorId.ERR_RENEWAL_TOO_EARLY.value)


def test_insufficient_hsa_at_pay(api):
    """PRD §3.9: "If the payer is HSA, the client's hsa_balance_cents must be at least the
    client_owed_cents — otherwise payment is rejected with ERR_INSUFFICIENT_HSA — and on success
    that balance is decremented by client_owed_cents."

    An HSA Swedish-60 (charge 12000) with hsa_balance 5000 is rejected at pay; balance unchanged.

    Design: Corner/errors/insufficient_hsa_at_pay_stub
    """
    set_clock("2026-01-05T07:00:00Z")
    scn = bookable_scenario(client_overrides={"hsa_balance_cents": 5000})
    appt, _ = drive_to_priced(scn, start_at="2026-01-05T09:00:00Z", duration_minutes=60, payer="HSA")
    validate_error(api.pay_appointment(appt["id"], {"gratuity_cents": 0}, FRONT),
                   ApiErrorId.ERR_INSUFFICIENT_HSA.value)
    client = validate_success(api.get_client(scn["client"]["id"], ADMIN))
    assert client["hsa_balance_cents"] == 5000, "HSA balance must be untouched on rejected pay"
