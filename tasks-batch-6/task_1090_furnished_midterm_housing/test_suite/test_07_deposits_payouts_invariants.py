"""Conservation invariants: the deposit three-bucket partition and the host
ledger through a pay-then-reverse compensating cycle.

Queue A (Difficulty): compensating_invariant.
"""
from test_helpers import (
    get_success_data,
    setup_completed_booking, get_deposit_for_booking, get_payout_for_booking,
    assert_deposit_conserved,
    make_host_headers, make_admin_headers, TEST_USERS,
)

REVIEWER = TEST_USERS["compliance_reviewer_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]


# --------------------------------------------------------------------------
# compensating_invariant / deposit_partition_conserved
# --------------------------------------------------------------------------

def _forfeit_and_settle_scenario(api):
    ctx = setup_completed_booking(api, unit_overrides={"deposit_cents": 150000},
                                  start_date="2026-06-01", end_date="2026-07-01",
                                  activate_clock="2026-06-15", complete_clock="2026-07-01")
    host, booking = ctx["host"], ctx["booking"]
    deposit = get_deposit_for_booking(api, booking["id"])
    claim = get_success_data(api.create_damage_claim(
        {"deposit_id": deposit["id"], "expected_deposit_version": deposit["version"],
         "claimed_cents": 40000, "description": "stain"},
        make_host_headers(host["id"])))
    get_success_data(api.transition_damage_claim(
        claim["id"], {"to_status": "APPROVED", "approved_cents": 40000}, REVIEWER))
    get_success_data(api.settle_deposit(deposit["id"], REVIEWER))
    return get_deposit_for_booking(api, booking["id"])


def test_deposit_settle_partially_refunded_buckets(api):
    """PRD §3.8: "If a partial amount was forfeited (`forfeited_cents` is greater
    than zero but less than `amount_cents`), the remaining held amount moves to
    `refunded_cents`, `held_cents` becomes zero, and the `status` becomes
    `PARTIALLY_REFUNDED`."

    Design: Difficulty/compensating_invariant/deposit_partition_conserved
    """
    deposit = _forfeit_and_settle_scenario(api)
    assert deposit["amount_cents"] == 150000
    assert deposit["held_cents"] == 0, f"held must be 0, got {deposit['held_cents']}"
    assert deposit["refunded_cents"] == 110000, f"refunded must be 110000, got {deposit['refunded_cents']}"
    assert deposit["forfeited_cents"] == 40000, f"forfeited must be 40000, got {deposit['forfeited_cents']}"
    assert deposit["status"] == "PARTIALLY_REFUNDED", f"status must be PARTIALLY_REFUNDED, got {deposit['status']}"


def test_deposit_partition_conserved_across_forfeit_and_refund(api):
    """PRD §2.10: "A deposit's `amount_cents` is partitioned at all times into
    three buckets — `held_cents`, `refunded_cents`, and `forfeited_cents` — whose
    sum always equals `amount_cents`."

    Design: Difficulty/compensating_invariant/deposit_partition_conserved
    """
    deposit = _forfeit_and_settle_scenario(api)
    assert_deposit_conserved(deposit)
    assert (deposit["held_cents"] + deposit["refunded_cents"] + deposit["forfeited_cents"]) == 150000


# --------------------------------------------------------------------------
# compensating_invariant / host_ledger_pay_reverse_conserved
# --------------------------------------------------------------------------

def _scheduled_payout_scenario(api):
    ctx = setup_completed_booking(api, unit_overrides={"deposit_cents": 0},
                                  start_date="2026-06-01", end_date="2026-07-01",
                                  activate_clock="2026-06-15", complete_clock="2026-07-01")
    host, booking = ctx["host"], ctx["booking"]
    payout = get_payout_for_booking(api, booking["id"])
    get_success_data(api.transition_payout(payout["id"], {"to_status": "SCHEDULED"}, make_admin_headers("admin-1")))
    return host, payout


def test_host_balance_credited_on_pay(api):
    """PRD §3.9: "Paying adds the payout's `net_cents` to the host's
    `payout_balance_cents` and subtracts the same net from
    `projected_payout_cents`."

    Design: Difficulty/compensating_invariant/host_ledger_pay_reverse_conserved
    """
    host, payout = _scheduled_payout_scenario(api)
    get_success_data(api.transition_payout(payout["id"], {"to_status": "PAID"}, make_admin_headers("admin-2")))
    host_data = get_success_data(api.get_host(host["id"], ADMIN))
    assert host_data["payout_balance_cents"] == 264000, \
        f"balance must be 264000 (sum of PAID net), got {host_data['payout_balance_cents']}"


def test_host_balance_restored_after_reverse(api):
    """PRD §2.10: "paying a payout adds its net to the balance, and reversing that
    same payout subtracts the identical net, so the invariant that the balance
    equals the sum of paid nets is preserved through a pay-then-reverse cycle."

    Design: Difficulty/compensating_invariant/host_ledger_pay_reverse_conserved
    """
    host, payout = _scheduled_payout_scenario(api)
    get_success_data(api.transition_payout(payout["id"], {"to_status": "PAID"}, make_admin_headers("admin-2")))
    get_success_data(api.transition_payout(payout["id"], {"to_status": "REVERSED"}, make_admin_headers("admin-2")))
    host_data = get_success_data(api.get_host(host["id"], ADMIN))
    assert host_data["payout_balance_cents"] == 0, \
        f"balance must return to 0 after pay-then-reverse, got {host_data['payout_balance_cents']}"
