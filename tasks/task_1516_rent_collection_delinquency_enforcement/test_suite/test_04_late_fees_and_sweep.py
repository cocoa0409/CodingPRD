"""Late-fee assessment and the delinquency sweep: grace boundary, formula
branches and the statutory cap, sweep idempotency, and the provisional-vs-final
dual variant observed through the draft-notice demand."""
from test_helpers import (
    add_charge,
    create_notice,
    create_property_payload,
    create_lease_payload,
    create_tenant_payload,
    list_charges,
    run_sweep,
    set_clock,
    setup_property_tenant_lease,
    validate_success,
)
from test_helpers import TEST_USERS

PM = TEST_USERS["property_manager_headers"]
AGENT = TEST_USERS["leasing_agent_headers"]


def _late_fee_charges(lease_id):
    return list_charges(lease_id, params={"kind": "LATE_FEE"})


def test_grace_period_last_day_no_fee(api):
    """PRD 3.6: "For each candidate, the days late are the calendar days from the
    charge's `due_date` to the run date, reduced by the lease's `grace_period_days`,
    and never less than zero. No fee accrues until at least one full day of lateness
    remains after the grace period."

    Design: Difficulty/boundary_precision_check/grace_period_last_day_no_fee
    """
    ctx = setup_property_tenant_lease()
    lease_id = ctx["lease"]["id"]
    add_charge(lease_id, amount_cents=200000)
    set_clock("2026-08-06T00:00:00Z")

    report = run_sweep()
    assert report["late_fees_assessed_count"] == 0, (
        "Sweep on due_date + grace (2026-08-06) must leave days_late == 0 and assess nothing"
    )


def test_grace_period_first_late_day_assesses_fee(api):
    """PRD 3.6: "For each candidate, the days late are the calendar days from the
    charge's `due_date` to the run date, reduced by the lease's `grace_period_days`,
    and never less than zero. No fee accrues until at least one full day of lateness
    remains after the grace period. Under a `FLAT` late-fee type, the raw fee is simply
    the lease's `late_fee_flat_cents`."

    Design: Difficulty/boundary_precision_check/grace_period_last_day_no_fee
    """
    ctx = setup_property_tenant_lease()
    lease_id = ctx["lease"]["id"]
    add_charge(lease_id, amount_cents=200000)
    set_clock("2026-08-07T00:00:00Z")

    report = run_sweep()
    assert report["late_fees_assessed_count"] == 1, (
        "One day past the grace period (days_late == 1) must assess the flat 4000-cent fee"
    )
    fees = _late_fee_charges(lease_id)
    assert len(fees) == 1
    assert fees[0]["amount_cents"] == 4000


def test_late_fee_min_max_branch_formula(api):
    """PRD 3.6: "Under `PERCENT_PLUS_DAILY`, the raw fee is the charge's `amount_cents`
    multiplied by the lease's `late_fee_percent_bps` and divided by ten thousand,
    rounded half up to whole cents, plus the lease's `late_fee_daily_cents` for each
    day late. In both cases the assessed fee is the lesser of the raw fee and the
    property's `late_fee_cap_cents`, and a fee that lands exactly on the cap is
    permitted. When the assessed fee is greater than zero, the sweep persists a
    `LATE_FEE` charge on the lease: due on the run date, stamped with source `SWEEP`,
    and carrying the same coverage period as the rent charge that spawned it."

    Design: Difficulty/combinatorial_formula/late_fee_min_max_branch_formula
    """
    ctx = setup_property_tenant_lease(
        lease_overrides={
            "grace_period_days": 3,
            "late_fee_type": "PERCENT_PLUS_DAILY",
            "late_fee_percent_bps": 500,
            "late_fee_daily_cents": 100,
        }
    )
    lease_id = ctx["lease"]["id"]
    add_charge(lease_id, amount_cents=200000)
    set_clock("2026-08-10T00:00:00Z")

    report = run_sweep()
    assert report["late_fees_assessed_count"] == 1
    fees = _late_fee_charges(lease_id)
    assert len(fees) == 1
    fee = fees[0]
    # raw = round_half_up(200000 * 500 / 10000) + 100 * 6 = 10000 + 600 = 10600; min(10600, 5000) = 5000
    assert fee["amount_cents"] == 5000, (
        f"raw 10600 must clamp to the 5000 statutory cap, got {fee['amount_cents']}"
    )
    assert fee["due_date"] == "2026-08-10"
    assert fee["source"] == "SWEEP"
    assert fee["period_start_date"] == "2026-08-01"
    assert fee["period_end_date"] == "2026-08-31"


def test_late_fee_cap_equality_allowed(api):
    """PRD 3.6: "In both cases the assessed fee is the lesser of the raw fee and the
    property's `late_fee_cap_cents`, and a fee that lands exactly on the cap is
    permitted."
    PRD 3.7: "The provisional fee uses the late-fee formula of §3.6 but evaluates it
    as of the current date plus the property's `notice_cure_period_days` — it assumes
    the charge remains unpaid through the cure deadline — and it is never persisted as
    a charge."

    Design: Difficulty/boundary_precision_check/late_fee_cap_equality_and_clamp
    """
    prop = validate_success(api.create_property(create_property_payload(late_fee_cap_cents=5000), PM), 201)
    tenant = validate_success(api.create_tenant(create_tenant_payload(), AGENT), 201)
    lease = validate_success(
        api.create_lease(
            create_lease_payload(
                prop["id"], tenant["id"],
                grace_period_days=3,
                late_fee_type="PERCENT_PLUS_DAILY",
                late_fee_percent_bps=250,
                late_fee_daily_cents=0,
            ),
            PM,
        ),
        201,
    )
    charge = add_charge(lease["id"], amount_cents=200000)
    validate_success(api.transition_lease(lease["id"], {"action": "ACTIVATE"}, PM))
    set_clock("2026-08-05T00:00:00Z")

    notice = create_notice(lease["id"], [charge["id"]])
    # provisional as_of = 2026-08-15, days_late = 14 - 3 = 11; raw = 5000 == cap
    assert notice["amount_demanded_cents"] == 205000, (
        f"raw fee exactly equal to the cap must be allowed in full: expected 205000, got {notice['amount_demanded_cents']}"
    )


def test_late_fee_cap_clamp_one_bp_over(api):
    """PRD 3.6: "In both cases the assessed fee is the lesser of the raw fee and the
    property's `late_fee_cap_cents`, and a fee that lands exactly on the cap is
    permitted."

    Design: Difficulty/boundary_precision_check/late_fee_cap_equality_and_clamp
    """
    prop = validate_success(api.create_property(create_property_payload(late_fee_cap_cents=5000), PM), 201)
    tenant = validate_success(api.create_tenant(create_tenant_payload(), AGENT), 201)
    lease = validate_success(
        api.create_lease(
            create_lease_payload(
                prop["id"], tenant["id"],
                grace_period_days=3,
                late_fee_type="PERCENT_PLUS_DAILY",
                late_fee_percent_bps=251,
                late_fee_daily_cents=0,
            ),
            PM,
        ),
        201,
    )
    charge = add_charge(lease["id"], amount_cents=200000)
    validate_success(api.transition_lease(lease["id"], {"action": "ACTIVATE"}, PM))
    set_clock("2026-08-05T00:00:00Z")

    notice = create_notice(lease["id"], [charge["id"]])
    # raw = 5020 > cap 5000 -> clamped to 5000
    assert notice["amount_demanded_cents"] == 205000, (
        f"raw fee 5020 must be clamped to the cap: expected 205000, got {notice['amount_demanded_cents']}"
    )


def test_sweep_second_run_idempotent(api):
    """PRD 3.6: "The sweep is idempotent: a repeated run with an unchanged clock
    changes nothing."
    PRD 3.6: "The late-fee duty walks rent charges in `OPEN` or `PARTIALLY_PAID`
    status on `ACTIVE` leases whose lease-and-period pair does not already carry a
    non-`VOID` late-fee charge; at most one non-`VOID` `LATE_FEE` may exist per lease
    and period, which is what makes the sweep safe to repeat."

    Design: Corner/calculations/sweep_second_run_idempotent
    """
    ctx = setup_property_tenant_lease()
    lease_id = ctx["lease"]["id"]
    add_charge(lease_id, amount_cents=200000)
    set_clock("2026-08-07T00:00:00Z")

    first = run_sweep()
    second = run_sweep()
    assert first["late_fees_assessed_count"] == 1
    assert second["late_fees_assessed_count"] == 0, "A repeated run at an unchanged clock must change nothing"
    assert len(_late_fee_charges(lease_id)) == 1


def test_late_fee_provisional_vs_final_on_notice_draft(api):
    """PRD 3.7: "It is the sum of the covered charges' outstanding balances, plus, for
    each covered `RENT` charge that still has a positive outstanding balance and does
    not yet have a non-`VOID` late-fee charge for the same period, a provisional late
    fee. The provisional fee uses the late-fee formula of §3.6 but evaluates it as of
    the current date plus the property's `notice_cure_period_days` — it assumes the
    charge remains unpaid through the cure deadline — and it is never persisted as a
    charge."

    Design: Difficulty/dual_variant_calc/late_fee_provisional_vs_final_on_notice
    """
    ctx = setup_property_tenant_lease()
    lease_id = ctx["lease"]["id"]
    charge = add_charge(lease_id, amount_cents=200000)

    notice = create_notice(lease_id, [charge["id"]])
    # provisional as_of = 2026-08-01 + 10 days = 2026-08-11; days_late = 10 - 5 = 5 >= 1 -> FLAT 4000
    assert notice["amount_demanded_cents"] == 204000, (
        f"Draft demand must embed the 4000-cent provisional fee: expected 204000, got {notice['amount_demanded_cents']}"
    )


def test_late_fee_final_variant_assesses_nothing_before_grace(api):
    """PRD 3.6: "For each candidate, the days late are the calendar days from the
    charge's `due_date` to the run date, reduced by the lease's `grace_period_days`,
    and never less than zero. No fee accrues until at least one full day of lateness
    remains after the grace period."

    Design: Difficulty/dual_variant_calc/late_fee_provisional_vs_final_on_notice
    """
    ctx = setup_property_tenant_lease()
    lease_id = ctx["lease"]["id"]
    charge = add_charge(lease_id, amount_cents=200000)
    notice = create_notice(lease_id, [charge["id"]])
    assert notice["amount_demanded_cents"] == 204000

    set_clock("2026-08-02T00:00:00Z")
    report = run_sweep()
    assert report["late_fees_assessed_count"] == 0, (
        "Final variant at 2026-08-02: days_late = max(0, 1 - 5) = 0, so nothing is persisted"
    )
    assert len(list_charges(lease_id)) == 1, "No LATE_FEE row may exist after the sweep"


def test_late_fee_min_max_branch_formula_flat_branch_ignores_days_late(api):
    """PRD 3.6: "Under a `FLAT` late-fee type, the raw fee is simply the lease's
    `late_fee_flat_cents`. Under `PERCENT_PLUS_DAILY`, the raw fee is the charge's
    `amount_cents` multiplied by the lease's `late_fee_percent_bps` and divided by ten
    thousand, rounded half up to whole cents, plus the lease's `late_fee_daily_cents`
    for each day late."

    Design: Difficulty/combinatorial_formula/late_fee_min_max_branch_formula
    """
    # Same lease configuration as the min/max probe but FLAT: days_late does not
    # enter the FLAT branch, so sweeping one day later yields the identical fee.
    ctx = setup_property_tenant_lease(
        lease_overrides={
            "grace_period_days": 3,
            "late_fee_type": "FLAT",
            "late_fee_flat_cents": 4000,
        }
    )
    lease_id = ctx["lease"]["id"]
    add_charge(lease_id, amount_cents=200000)
    set_clock("2026-08-10T00:00:00Z")

    report = run_sweep()
    assert report["late_fees_assessed_count"] == 1
    fees = _late_fee_charges(lease_id)
    assert fees[0]["amount_cents"] == 4000, (
        "FLAT branch ignores days_late entirely: the raw fee is late_fee_flat_cents, capped at 5000"
    )
