"""Billing: pro-rated first charge, late fees, payment waterfall, escalation, termination gate."""
from test_helpers import (
    ApiErrorId,
    api_client,
    assert_charge_ledger_identity,
    create_airport,
    get_lease,
    list_rent_charges,
    make_tenant_headers,
    set_clock,
    setup_lease,
    validate_error,
    validate_success,
)


def _pay(lease_id, amount_cents):
    return api_client.create_payment(lease_id, {"amount_cents": amount_cents},
                                     make_tenant_headers(lease_id))


def test_late_fee_floor_and_cap_on_small_charge(api, manager_headers):
    """PRD §3.5: "When the count is positive, the daily fee is the greater of 500 cents and half a percent (0.005) of the charge's `base_amount_cents` rounded half up to a whole cent. The accrued fee is the daily fee times the overdue-day count, and `late_fee_cents` becomes the lesser of that accrual and a cap of 25 percent (0.25) of the same charge's `base_amount_cents`, rounded half up — the cap is per charge, never against the lease-wide balance."
    PRD §3.5: "The first charge is created at lease activation for the partial period from `lease_start_date` to the first instant of the following calendar month; its `base_amount_cents` is the lease's `current_monthly_rate_cents` multiplied by the number of days remaining in the start month — counting the start day itself — divided by the number of days in that calendar month, with the result rounded down to a whole cent."

    Design: Difficulty/combinatorial_formula/late_fee_daily_floor_cap_threshold_mode_a
    """
    # Lease starts 2026-08-27: August has 31 days, 5 days remain, so the first
    # charge base is floor(62000*5/31) = 10000 — a small charge that exercises
    # the 500-cent daily floor and the 25% cap (2500).
    ctx = setup_lease(airport_overrides={"airport_code": "KLTE", "late_fee_grace_days": 5},
                      size_class="BOX", rate=62000, hangar_code="B-9",
                      start_clock="2026-08-27T00:00:00Z", applicant_name="Larry Late",
                      insurance_effective_from="2026-08-01T00:00:00Z")
    lease = ctx["lease"]

    # At 2026-09-12 the August charge (due 08-27, grace ends 09-01) is 11 days
    # overdue: 500*11 = 5500 accrual, capped at round(10000*0.25) = 2500.
    set_clock("2026-09-12T00:00:00Z")
    charges = list_rent_charges(lease["id"])
    assert len(charges) == 2, "sweep creates the September charge"
    first = charges[0]
    assert first["base_amount_cents"] == 10000
    assert first["late_fee_cents"] == 2500, (
        f"per-charge cap of 25% of base must bind at 2500, got {first['late_fee_cents']}"
    )
    assert_charge_ledger_identity(first)


def test_late_fee_daily_accrual_below_cap(api, manager_headers):
    """PRD §3.5: "A charge's overdue-day count is the number of whole days from the end of its grace window — `due_date` plus the airport's `late_fee_grace_days` — to the sweep instant, truncated, and never below zero; at exactly the end of the grace window the count is zero and no fee accrues, so the first fee day is the day after grace ends."
    PRD §3.5: "The sweep moves an `ACTIVE` lease to `DELINQUENT` when any charge's `balance_cents` is positive and the logical clock has passed that charge's `due_date` plus the grace days, recomputing `days_delinquent`; the hangar's posture stays `LEASED` throughout, since a delinquent tenant still occupies."

    Design: Difficulty/combinatorial_formula/late_fee_daily_floor_cap_threshold_mode_a
    """
    ctx = setup_lease(airport_overrides={"airport_code": "KLT2", "late_fee_grace_days": 5},
                      size_class="BOX", rate=62000, hangar_code="B-10",
                      start_clock="2026-08-27T00:00:00Z", applicant_name="Larry Late",
                      insurance_effective_from="2026-08-01T00:00:00Z")
    lease = ctx["lease"]

    set_clock("2026-09-12T00:00:00Z")
    charges = list_rent_charges(lease["id"])
    september = charges[1]
    # September charge: full month 62000, due 09-01, grace ends 09-06; at
    # 09-12 it is 6 days overdue: daily fee max(500, round(62000*0.005)=310)
    # = 500, accrual 3000, below the 15500 cap.
    assert september["base_amount_cents"] == 62000
    assert september["late_fee_cents"] == 3000, (
        f"expected 6 days at the 500-cent floor = 3000, got {september['late_fee_cents']}"
    )
    assert_charge_ledger_identity(september)
    assert get_lease(lease["id"])["status"] == "DELINQUENT"


def test_prorated_first_charge_floor_rounding(api, manager_headers):
    """PRD §3.5: "The first charge is created at lease activation for the partial period from `lease_start_date` to the first instant of the following calendar month; its `base_amount_cents` is the lease's `current_monthly_rate_cents` multiplied by the number of days remaining in the start month — counting the start day itself — divided by the number of days in that calendar month, with the result rounded down to a whole cent. Pro-rating happens first, with late fees added later as a separate component; amounts are never summed before rounding."

    Design: Difficulty/combinatorial_formula/payment_waterfall_rounding_order_mode_b
    """
    # Lease starts 2026-08-15: 17 days remain of 31, so the pro-rated base is
    # floor(100000*17/31) = 54838 — round-half-up would give 54839.
    ctx = setup_lease(airport_overrides={"airport_code": "KWFL", "late_fee_grace_days": 5},
                      size_class="EXECUTIVE", rate=100000, hangar_code="E-3",
                      start_clock="2026-08-15T00:00:00Z", applicant_name="Wanda Water",
                      insurance_effective_from="2026-08-01T00:00:00Z")
    lease = ctx["lease"]

    set_clock("2026-09-10T00:00:00Z")
    charges = list_rent_charges(lease["id"])
    first = charges[0]
    assert first["base_amount_cents"] == 54838, (
        f"pro-ration must round down at the daily level (54838), got {first['base_amount_cents']}"
    )
    # Due 08-15, grace ends 08-20; at 09-10 it is 21 days overdue:
    # 500*21 = 10500, below the cap round(54838*0.25) = 13710.
    assert first["late_fee_cents"] == 10500
    assert charges[1]["base_amount_cents"] == 100000
    assert charges[1]["late_fee_cents"] == 2000


def test_payment_waterfall_fees_before_principal(api, manager_headers):
    """PRD §3.5: "Payments arrive from the tenant as `amount_cents` and are allocated by waterfall: charges in chronological order by `period_start` ascending with `created_at` ascending as the tie-break, and within each charge the late fees are paid first, then the base amount — fees before principal, in integer cents with no fractional allocation. Partial application to the final charge is allowed and leaves it `PARTIALLY_PAID`; any remainder left after every charge is `PAID` is rejected with `ERR_OVERPAYMENT` (HTTP 402), because the system holds no credit balances."

    Design: Difficulty/combinatorial_formula/payment_waterfall_rounding_order_mode_b
    """
    ctx = setup_lease(airport_overrides={"airport_code": "KWF2", "late_fee_grace_days": 5},
                      size_class="EXECUTIVE", rate=100000, hangar_code="E-4",
                      start_clock="2026-08-15T00:00:00Z", applicant_name="Wanda Water",
                      insurance_effective_from="2026-08-01T00:00:00Z")
    lease = ctx["lease"]
    set_clock("2026-09-10T00:00:00Z")

    # 150000 pays charge 1 in full (late 10500 then base 54838 = 65338), then
    # charge 2's late fee 2000 and 82662 of its base — leaving 17338.
    validate_success(_pay(lease["id"], 150000))
    charges = list_rent_charges(lease["id"])
    assert charges[0]["status"] == "PAID"
    assert charges[1]["balance_cents"] == 17338, (
        f"fees-before-principal waterfall must leave 17338 on charge 2, got {charges[1]['balance_cents']}"
    )
    assert charges[1]["status"] == "PARTIALLY_PAID"
    assert get_lease(lease["id"])["status"] == "DELINQUENT"


def test_payment_conserves_charge_ledger_identity(api, manager_headers):
    """PRD §3.5: "A charge's `balance_cents` is always its `base_amount_cents` plus `late_fee_cents` minus `paid_cents`, recomputed on every payment or fee event, and the charge's status moves among `OPEN`, `PARTIALLY_PAID`, and `PAID`."

    Design: Difficulty/compensating_invariant/payment_waterfall_conserves_charge_total
    """
    ctx = setup_lease(airport_overrides={"airport_code": "KINV", "late_fee_grace_days": 5},
                      size_class="EXECUTIVE", rate=100000, hangar_code="E-60",
                      start_clock="2026-08-15T00:00:00Z", applicant_name="Ivy Invariant",
                      insurance_effective_from="2026-08-01T00:00:00Z")
    lease = ctx["lease"]
    set_clock("2026-09-10T00:00:00Z")

    # Exactly the first charge's total (54838 + 10500 = 65338).
    validate_success(_pay(lease["id"], 65338))
    charges = list_rent_charges(lease["id"])
    first, second = charges[0], charges[1]
    assert first["balance_cents"] == 0 and first["paid_cents"] == 65338
    assert_charge_ledger_identity(first)
    assert_charge_ledger_identity(second)
    assert first["balance_cents"] + first["paid_cents"] == 54838 + 10500
    assert second["balance_cents"] + second["paid_cents"] == 100000 + 2000


def test_outstanding_balance_tracks_open_charge_balances(api, manager_headers):
    """PRD §3.4: "The outstanding balance is the sum of `balance_cents` across the lease's `OPEN` and `PARTIALLY_PAID` charges, kept in step on every charge creation, late-fee accrual, and payment."

    Design: Difficulty/compensating_invariant/payment_waterfall_conserves_charge_total
    """
    ctx = setup_lease(airport_overrides={"airport_code": "KIN2", "late_fee_grace_days": 5},
                      size_class="EXECUTIVE", rate=100000, hangar_code="E-61",
                      start_clock="2026-08-15T00:00:00Z", applicant_name="Ivy Invariant",
                      insurance_effective_from="2026-08-01T00:00:00Z")
    lease = ctx["lease"]
    set_clock("2026-09-10T00:00:00Z")

    validate_success(_pay(lease["id"], 65338))  # zeroes charge 1
    # Only charge 2 remains open: 100000 base + 2000 late = 102000.
    assert get_lease(lease["id"])["outstanding_balance_cents"] == 102000


def test_overpayment_rejected_no_credit_balance(api, manager_headers):
    """PRD §3.5: "Partial application to the final charge is allowed and leaves it `PARTIALLY_PAID`; any remainder left after every charge is `PAID` is rejected with `ERR_OVERPAYMENT` (HTTP 402), because the system holds no credit balances."

    Design: Corner/calculations/overpayment_rejected_no_credit_balance
    """
    ctx = setup_lease(airport_overrides={"airport_code": "KOVP"}, size_class="T_HANGAR",
                      rate=100000, hangar_code="T-110", applicant_name="Ollie Pay")
    lease = ctx["lease"]

    # Single charge of 100000 outstanding; one cent above the total rejects.
    resp = _pay(lease["id"], 100001)
    validate_error(resp, ApiErrorId.ERR_OVERPAYMENT)
    assert get_lease(lease["id"])["outstanding_balance_cents"] == 100000


def test_lease_delinquent_to_active_on_full_payoff(api, manager_headers):
    """PRD §3.5: "Paying down from `DELINQUENT` flips the lease back to `ACTIVE` only when the waterfall zeroes `outstanding_balance_cents`, resetting `days_delinquent` to zero. A payment that reduces but does not zero the balance is still applied to charges yet leaves the lease `DELINQUENT` — the no-flip behavior documented in the catalogue as `ERR_PARTIAL_CURE_NOT_ALLOWED` (HTTP 402)."

    Design: Corner/state_machines/lease_delinquent_to_active_on_full_payoff
    """
    ctx = setup_lease(airport_overrides={"airport_code": "KDLQ", "late_fee_grace_days": 5},
                      size_class="T_HANGAR", rate=100000, hangar_code="T-90",
                      applicant_name="Del Quent")
    lease = ctx["lease"]
    # At 2026-08-10 the August charge (due 08-01, grace ends 08-06) is 4 days
    # overdue: late fee 2000, outstanding 102000, lease DELINQUENT.
    set_clock("2026-08-10T00:00:00Z")

    validate_success(_pay(lease["id"], 50000))
    mid = get_lease(lease["id"])
    assert mid["status"] == "DELINQUENT", "partial payment must not flip status"
    assert mid["outstanding_balance_cents"] == 52000

    validate_success(_pay(lease["id"], 52000))
    final = get_lease(lease["id"])
    assert final["status"] == "ACTIVE", "full payoff must flip the lease back to ACTIVE"
    assert final["outstanding_balance_cents"] == 0
    assert final["days_delinquent"] == 0
    charges = list_rent_charges(lease["id"])
    assert charges[0]["status"] == "PAID"


def test_terminate_with_one_cent_balance_rejected(api, manager_headers):
    """PRD §3.8: "A tenant terminates voluntarily from `ACTIVE` or `DELINQUENT` — `ERR_LEASE_NOT_ACTIVE` (HTTP 409) guards the state requirement — with `outstanding_balance_cents` at zero (`ERR_OUTSTANDING_BALANCE`, HTTP 402), and the hangar's posture returns to `AVAILABLE`."

    Design: Difficulty/boundary_precision_check/zero_balance_termination_gate_boundary
    """
    ctx = setup_lease(airport_overrides={"airport_code": "KZB"}, size_class="T_HANGAR",
                      rate=100000, hangar_code="T-20", applicant_name="Zed Zero")
    lease = ctx["lease"]
    validate_success(_pay(lease["id"], 99999))  # leaves exactly 1 cent

    resp = api_client.terminate_lease(lease["id"], {}, make_tenant_headers(lease["id"]))
    validate_error(resp, ApiErrorId.ERR_OUTSTANDING_BALANCE)
    assert get_lease(lease["id"])["status"] == "ACTIVE"


def test_terminate_with_zero_balance_succeeds(api, manager_headers):
    """PRD §3.8: "A tenant terminates voluntarily from `ACTIVE` or `DELINQUENT` — `ERR_LEASE_NOT_ACTIVE` (HTTP 409) guards the state requirement — with `outstanding_balance_cents` at zero (`ERR_OUTSTANDING_BALANCE`, HTTP 402), and the hangar's posture returns to `AVAILABLE`."

    Design: Difficulty/boundary_precision_check/zero_balance_termination_gate_boundary
    """
    ctx = setup_lease(airport_overrides={"airport_code": "KZB2"}, size_class="T_HANGAR",
                      rate=100000, hangar_code="T-21", applicant_name="Zed Zero")
    lease = ctx["lease"]
    validate_success(_pay(lease["id"], 99999))
    validate_success(_pay(lease["id"], 1))

    assert get_lease(lease["id"])["outstanding_balance_cents"] == 0
    resp = api_client.terminate_lease(lease["id"], {}, make_tenant_headers(lease["id"]))
    terminated = validate_success(resp)
    assert terminated["status"] == "TERMINATED"


def test_escalation_compound_two_anniversaries(api, manager_headers):
    """PRD §3.5: "Each anniversary not yet applied per `last_escalation_anniversary` is then applied in ascending order, rounding half up to a whole cent once per step: under `ANNIVERSARY_COMPOUND`, the running `current_monthly_rate_cents` is multiplied by one plus the airport's `escalation_pct`, so growth compounds on the already-escalated rate; under `ANNIVERSARY_SIMPLE`, the original `base_monthly_rate_cents` is multiplied by one plus `escalation_pct` times the index of the anniversary being applied, so growth is linear in the number of anniversaries. The two policies agree through the first anniversary and diverge from the second onward."

    Design: Difficulty/dual_variant_calc/annual_escalation_compound_vs_simple_on_lease
    """
    ctx = setup_lease(
        airport_overrides={"airport_code": "KCPA", "escalation_pct": 0.04,
                           "escalation_policy": "ANNIVERSARY_COMPOUND"},
        size_class="T_HANGAR", rate=100000, hangar_code="T-1",
        applicant_name="Amy Compound",
    )
    lease = ctx["lease"]

    # Past the second anniversary (2027-08-01 and 2028-08-01):
    # 100000 -> 104000 -> 108160 compounding at 4%.
    set_clock("2028-08-02T00:00:00Z")
    after = get_lease(lease["id"])
    assert after["current_monthly_rate_cents"] == 108160, (
        f"compound escalation must reach 108160 after two anniversaries, got {after['current_monthly_rate_cents']}"
    )
    assert after["last_escalation_anniversary"] == 2


def test_escalation_simple_two_anniversaries_diverges(api, manager_headers):
    """PRD §3.5: "Each anniversary not yet applied per `last_escalation_anniversary` is then applied in ascending order, rounding half up to a whole cent once per step: under `ANNIVERSARY_COMPOUND`, the running `current_monthly_rate_cents` is multiplied by one plus the airport's `escalation_pct`, so growth compounds on the already-escalated rate; under `ANNIVERSARY_SIMPLE`, the original `base_monthly_rate_cents` is multiplied by one plus `escalation_pct` times the index of the anniversary being applied, so growth is linear in the number of anniversaries. The two policies agree through the first anniversary and diverge from the second onward."

    Design: Difficulty/dual_variant_calc/annual_escalation_compound_vs_simple_on_lease
    """
    ctx_simple = setup_lease(
        airport_overrides={"airport_code": "KSIM", "escalation_pct": 0.04,
                           "escalation_policy": "ANNIVERSARY_SIMPLE"},
        size_class="T_HANGAR", rate=100000, hangar_code="T-1",
        applicant_name="Sam Simple",
    )
    ctx_compound = setup_lease(
        airport_overrides={"airport_code": "KCP2", "escalation_pct": 0.04,
                           "escalation_policy": "ANNIVERSARY_COMPOUND"},
        size_class="T_HANGAR", rate=100000, hangar_code="T-1",
        applicant_name="Amy Compound",
    )

    set_clock("2028-08-02T00:00:00Z")
    simple = get_lease(ctx_simple["lease"]["id"])
    compound = get_lease(ctx_compound["lease"]["id"])
    # SIMPLE: 100000 * (1 + 0.04*2) = 108000; COMPOUND: 108160 — divergent.
    assert simple["current_monthly_rate_cents"] == 108000
    assert simple["last_escalation_anniversary"] == 2
    assert simple["current_monthly_rate_cents"] != compound["current_monthly_rate_cents"]


def test_escalation_anniversary_boundary_inclusive(api, manager_headers):
    """PRD §3.5: "The sweep counts elapsed anniversaries, one per 365 days after `lease_start_date`, where an anniversary landing exactly on the sweep instant counts as elapsed while an instant one millisecond before it does not."

    Design: Corner/calculations/escalation_single_anniversary_boundary_at_exact_day
    """
    # Two independent leases (one per airport) observe both sides of the
    # boundary against a single forward-moving logical clock.
    ctx_before = setup_lease(
        airport_overrides={"airport_code": "KAN1", "escalation_pct": 0.04,
                           "escalation_policy": "ANNIVERSARY_COMPOUND"},
        size_class="T_HANGAR", rate=100000, hangar_code="T-1", applicant_name="Ann One",
    )
    ctx_exact = setup_lease(
        airport_overrides={"airport_code": "KAN2", "escalation_pct": 0.04,
                           "escalation_policy": "ANNIVERSARY_COMPOUND"},
        size_class="T_HANGAR", rate=100000, hangar_code="T-1", applicant_name="Ann Two",
    )

    # One millisecond before the first anniversary: nothing applied yet.
    set_clock("2027-07-31T23:59:59.999Z")
    before = get_lease(ctx_before["lease"]["id"])
    assert before["current_monthly_rate_cents"] == 100000
    assert before["last_escalation_anniversary"] == 0

    # Exactly on the anniversary (lease_start 2026-08-01 + 365 days): it counts.
    set_clock("2027-08-01T00:00:00Z")
    exact = get_lease(ctx_exact["lease"]["id"])
    assert exact["current_monthly_rate_cents"] == 104000
    assert exact["last_escalation_anniversary"] == 1
