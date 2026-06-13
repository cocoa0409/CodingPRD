"""GRH reimbursement arithmetic, subsidy reconciliation, and the periodic batch
(PRD §3.9, §3.10, §2.10, §3.4).
"""
from test_helpers import (
    validate_success, get_success_data,
    make_rider_headers, make_program_admin_headers, make_platform_ops_headers,
    create_grh_claim,
)

PA = make_program_admin_headers()
OPS = make_platform_ops_headers()


def test_grh_reimbursement_binds_to_per_event_cap(api):
    """PRD §3.9: "The `reimbursed_cents` is computed as the smallest of the
    `claimed_fare_cents`, the program's `grh_per_event_cap_cents`, and the member's
    remaining annual allowance ... The member's `wallet_balance_cents` is credited by
    `reimbursed_cents`".

    claimed 8000 vs per_event_cap 6000 vs annual_remaining 20000 -> 6000; the
    per-event cap binds and the wallet is credited 6000 (1000 -> 7000).

    Design: Corner/calculations/grh_reimbursement_per_event_cap_binds
    """
    program = get_success_data(api.create_employer_program(
        {"employer_name": "Acme", "hov_discount_pct": 0.50, "employer_match_pct": 0.30,
         "monthly_benefit_cap_cents": 31500, "grh_annual_cap_cents": 20000,
         "grh_per_event_cap_cents": 6000, "subsidy_budget_cents": 1000000}, PA))
    rider = get_success_data(api.create_member(
        {"employer_program_id": program["id"], "full_name": "Rae", "home_zone": "Z-N",
         "work_zone": "Z-DT", "wallet_balance_cents": 1000}, PA))
    grh = create_grh_claim(rider["id"], program["id"], api=api, claimed_fare_cents=8000,
                           reason_code="EMERGENCY")
    get_success_data(api.approve_grh_claim(grh["id"], PA))
    reimbursed = validate_success(api.reimburse_grh_claim(grh["id"], PA))
    assert reimbursed["reimbursed_cents"] == 6000
    assert reimbursed["status"] == "REIMBURSED"
    assert get_success_data(api.get_member(rider["id"], PA))["wallet_balance_cents"] == 7000
    assert get_success_data(api.get_employer_program(program["id"], PA))["subsidy_consumed_cents"] == 6000


def test_subsidy_consumed_reconciles_after_grh_reimburse(api):
    """PRD §3.10: "a debit at finalization or GRH reimbursement raises it and a
    credit at cancellation lowers it."
    PRD §3.9: "a `SubsidyLedgerEntry` debit of `reimbursed_cents` with reason
    `GRH_REIMBURSED` is appended, the program's `subsidy_consumed_cents` is
    recomputed".

    A single 4000-cent reimbursement (under both caps) leaves subsidy_consumed_cents
    at 4000 and credits the wallet 4000.

    Design: Corner/cross_cutting_complexity_layers/derived_subsidy_consumed_reconciles_after_reimburse
    """
    program = get_success_data(api.create_employer_program(
        {"employer_name": "Acme", "hov_discount_pct": 0.50, "employer_match_pct": 0.30,
         "monthly_benefit_cap_cents": 31500, "grh_annual_cap_cents": 20000,
         "grh_per_event_cap_cents": 6000, "subsidy_budget_cents": 1000000}, PA))
    rider = get_success_data(api.create_member(
        {"employer_program_id": program["id"], "full_name": "Rae", "home_zone": "Z-N",
         "work_zone": "Z-DT", "wallet_balance_cents": 0}, PA))
    grh = create_grh_claim(rider["id"], program["id"], api=api, claimed_fare_cents=4000,
                           reason_code="ILLNESS")
    get_success_data(api.approve_grh_claim(grh["id"], PA))
    reimbursed = validate_success(api.reimburse_grh_claim(grh["id"], PA))
    assert reimbursed["reimbursed_cents"] == 4000
    assert get_success_data(api.get_employer_program(program["id"], PA))["subsidy_consumed_cents"] == 4000
    assert get_success_data(api.get_member(rider["id"], PA))["wallet_balance_cents"] == 4000


def test_batch_run_expires_stale_open_match_request(api):
    """PRD §3.4: "the periodic batch run by `PlatformOps` sweeps every still-`OPEN`
    request whose `created_at` is more than fourteen days before the current clock
    and moves it to the terminal `EXPIRED` state."

    Design: Corner/endpoints/batch_run_expires_stale_open_match_request
    """
    get_success_data(api.set_clock({"now_iso8601": "2026-06-01T00:00:00Z"}, OPS))
    program = get_success_data(api.create_employer_program(
        {"employer_name": "Acme", "hov_discount_pct": 0.50, "employer_match_pct": 0.30,
         "monthly_benefit_cap_cents": 31500, "grh_annual_cap_cents": 20000,
         "grh_per_event_cap_cents": 6000, "subsidy_budget_cents": 1000000}, PA))
    rider = get_success_data(api.create_member(
        {"employer_program_id": program["id"], "full_name": "Rae", "home_zone": "Z-N",
         "work_zone": "Z-DT"}, PA))
    mr = get_success_data(api.create_match_request(
        {"rider_member_id": rider["id"], "origin_zone": "Z-N", "dest_zone": "Z-DT",
         "needed_days": ["MON"], "earliest_departure_min": 480, "latest_departure_min": 600},
        make_rider_headers(rider["id"])))
    get_success_data(api.set_clock({"now_iso8601": "2026-06-16T00:00:00Z"}, OPS))
    get_success_data(api.run_batch(OPS))
    after = get_success_data(api.get_match_request(mr["id"], make_rider_headers(rider["id"])))
    assert after["status"] == "EXPIRED"
