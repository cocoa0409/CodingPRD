"""Deferred payment agreements: tiered terms, forgiveness variants, ledger
conservation, capacity, default/cure cycle, and OCC."""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    get_success_data,
    ApiErrorId, NON_EXISTENT_UUID,
    assert_dpa, assert_dpa_ledger_invariants, assert_date_eq,
    create_account, charge_arrearage, setup_account_with_active_enrollment,
    create_dpa, attempt_create_dpa, pay, create_and_activate_dpa,
    fresh_account_version, set_clock, run_sweep, get_account,
    TEST_USERS,
    INCOME_TIER_2, INCOME_TIER_3,
)

CSR = TEST_USERS["csr_headers"]
ADMIN = TEST_USERS["admin_headers"]


class TestForgivenessProjectedVsPosted:
    def _active_tier2_dpa(self, api):
        """TIER_2 account with 120000 arrearage; DPA n=4 (down 6000, pool 40000,
        installment 18500) activated by its down payment at clock 2026-08-01."""
        account, _app, _enr = setup_account_with_active_enrollment(
            income=INCOME_TIER_2, arrearage_cents=120_000,
            service_address="200 Oak Ave")
        dpa = create_dpa(account["id"], installment_count=4)
        assert dpa["down_payment_required_cents"] == 6_000
        assert dpa["forgiveness_pool_cents"] == 40_000
        pay(account["id"], 6_000)
        return account, get_success_data(api_client.get_dpa(dpa["id"], CSR), 200)

    def test_projected_equals_pool_while_posted_starts_at_zero(self, api):
        """PRD §3.4: "`projected_forgiveness_cents` is the forward-looking variant:
        it always equals `forgiveness_pool_cents`, on the assumption that every
        remaining installment will settle on time."
        PRD §3.4: "`forgiven_posted_cents` is the actual ledger: the sum of
        ForgivenessCredit amounts with status `POSTED` on this DPA, starting at 0."

        Design: Difficulty/dual_variant_calc/forgiveness_projected_vs_posted
        """
        _account, dpa = self._active_tier2_dpa(api)
        assert dpa["status"] == "ACTIVE"
        assert dpa["projected_forgiveness_cents"] == 40_000
        assert dpa["forgiven_posted_cents"] == 0

    def test_posted_diverges_from_projected_after_on_time_installment(self, api):
        """PRD §3.5: "An on-time settlement immediately posts a ForgivenessCredit
        under the agreement, recording the 1-based `installment_number`, the
        credited `amount_cents`, status `POSTED`, and a `posted_at` clock timestamp."
        PRD §3.4: "The working balance `remaining_balance_cents` is
        `covered_arrearage_cents` minus `paid_to_arrearage_cents` minus
        `forgiven_posted_cents`".

        Design: Difficulty/dual_variant_calc/forgiveness_projected_vs_posted
        """
        account, dpa = self._active_tier2_dpa(api)
        set_clock("2026-08-05T00:00:00Z")
        payment = pay(account["id"], 18_500, tender_type="CARD")
        assert payment["installments_settled_count"] == 1
        assert payment["on_time"] is True
        assert payment["credit_accrued_cents"] == 10_000, (
            "round_half_up(40000/4) posts 10000 for the on-time installment")
        after = validate_success(api.get_dpa(dpa["id"], CSR), 200)
        assert after["forgiven_posted_cents"] == 10_000
        assert after["projected_forgiveness_cents"] == 40_000, (
            "the forward-looking variant does not move with payment history")
        assert after["remaining_balance_cents"] == 85_500  # 120000 - 24500 - 10000
        assert_dpa_ledger_invariants(after)


class TestDpaDownPaymentTieredTerms:
    def test_tier2_enrolled_account_terms(self, api):
        """PRD §3.4: "Third, the down payment: for `TIER_1` it is zero; for `TIER_2`
        it is the greater of five percent of the covered arrearage rounded half-up
        to cents and $25.00; for `TIER_3` or no active enrollment it is the greater
        of ten percent of the covered arrearage rounded half-up and $50.00."
        PRD §3.4: "`forgiveness_pool_cents` is the covered arrearage multiplied by
        the tier's forgiveness share — one half for `TIER_1`, one third for
        `TIER_2`, one quarter for `TIER_3`, zero when no enrollment is active —
        rounded half-up to cents."

        Design: Difficulty/combinatorial_formula/dpa_down_payment_tiered_terms
        """
        account, _app, _enr = setup_account_with_active_enrollment(
            income=INCOME_TIER_2, arrearage_cents=120_000,
            service_address="10 Tier Lane X")
        dpa = create_dpa(account["id"], installment_count=4)
        assert_dpa(dpa)
        assert dpa["covered_arrearage_cents"] == 120_000
        assert dpa["down_payment_required_cents"] == 6_000   # max(round(120000*.05), 2500)
        assert dpa["forgiveness_pool_cents"] == 40_000       # round(120000/3)
        assert dpa["installment_amount_cents"] == 18_500     # (120000-6000-40000)/4
        assert dpa["status"] == "DRAFT"

    def test_no_enrollment_account_terms(self, api):
        """PRD §3.4: "for `TIER_3` or no active enrollment it is the greater of ten
        percent of the covered arrearage rounded half-up and $50.00."
        PRD §3.4: "Fifth, the installment base is the covered arrearage minus the
        down payment minus the pool, and `installment_amount_cents` is that base
        divided by the installment count, rounded half-up; installments 1 through
        n-1 charge this equal amount."

        Design: Difficulty/combinatorial_formula/dpa_down_payment_tiered_terms
        """
        account = create_account(service_address="11 Tier Lane Y")
        charge_arrearage(account["id"], 120_000)
        dpa = create_dpa(account["id"], installment_count=4)
        assert_dpa(dpa)
        assert dpa["covered_arrearage_cents"] == 120_000
        assert dpa["down_payment_required_cents"] == 12_000  # max(round(120000*.10), 5000)
        assert dpa["forgiveness_pool_cents"] == 0            # zero when no enrollment
        assert dpa["installment_amount_cents"] == 27_000     # (120000-12000-0)/4
        assert dpa["status"] == "DRAFT"


class TestDpaDefaultReinstateCycle:
    def _defaulted_dpa(self, api):
        """Account 120000 (no enrollment); DPA n=4 activated via 12000 down at
        2026-08-01 (installment 27000, first due 2026-08-31); clock 2026-09-06,
        swept past due+grace."""
        account = create_account(service_address="8 Default Dr")
        charge_arrearage(account["id"], 120_000)
        dpa = create_dpa(account["id"], installment_count=4)
        pay(account["id"], 12_000)
        set_clock("2026-09-06T00:00:00Z")
        return account, dpa

    def test_sweep_defaults_dpa_past_due_plus_grace(self, api):
        """PRD §3.4: "Default is detected, not declared. The daily sweep moves an
        `ACTIVE` DPA to `DEFAULTED` when the earliest unsettled installment's due
        date plus five grace days has passed the clock date, stamping
        `defaulted_on` and adding 1 to `missed_payment_count`."

        Design: Difficulty/non_linear_state_machine/dpa_default_reinstate_cycle
        """
        account, dpa = self._defaulted_dpa(api)
        sweep = run_sweep()
        assert sweep["dpas_defaulted"] == 1
        mid = validate_success(api.get_dpa(dpa["id"], CSR), 200)
        assert mid["status"] == "DEFAULTED"
        assert mid["missed_payment_count"] == 1
        assert_date_eq(mid["defaulted_on"], "2026-09-06", "defaulted_on")

    def test_cure_payment_and_reinstate_closes_cycle(self, api):
        """PRD §3.4: "A default is curable within a fifteen-day window: a
        `CustomerServiceRep` reinstates the agreement when the clock date is on or
        before `defaulted_on` plus 15 days and every installment whose due date has
        been reached is fully settled. Reinstatement returns the DPA to `ACTIVE`
        and clears `defaulted_on` to null."
        PRD §3.5: "it is on time when the `paid_at` date falls on or before its due
        date plus five grace days."

        Design: Difficulty/non_linear_state_machine/dpa_default_reinstate_cycle
        """
        account, dpa = self._defaulted_dpa(api)
        run_sweep()
        payment = pay(account["id"], 27_000, tender_type="CHECK")
        assert payment["installments_settled_count"] == 1
        assert payment["on_time"] is False, (
            "paid 2026-09-06, past the 2026-08-31 due date plus five grace days")
        reinstated = validate_success(api.reinstate_dpa(dpa["id"], CSR), 200)
        assert reinstated["status"] == "ACTIVE"
        assert reinstated["defaulted_on"] is None


class TestDpaSingleActiveCapacity:
    def _account_with_two_dpas(self, api):
        """DPA-1 (DRAFT) superseded by DPA-2 (DRAFT); DPA-2 then activated."""
        account = create_account(service_address="62 Interval Ave")
        charge_arrearage(account["id"], 120_000)
        dpa1 = create_dpa(account["id"], installment_count=4)
        dpa2 = create_dpa(account["id"], installment_count=4)
        pay(account["id"], 12_000)
        dpa2 = get_success_data(api_client.get_dpa(dpa2["id"], CSR), 200)
        assert dpa2["status"] == "ACTIVE"
        return account, dpa1, dpa2

    def test_draft_superseded_and_active_blocks_successor(self, api):
        """PRD §3.4: "an account carrying an `ACTIVE` or `DEFAULTED` DPA is rejected
        with `ERR_OPEN_DPA_EXISTS` (HTTP 422), while a lingering `DRAFT` is quietly
        superseded into `CANCELLED` rather than treated as an error".

        Design: Difficulty/resource_temporal_overlap/dpa_single_active_capacity_per_account
        """
        account, dpa1, _dpa2 = self._account_with_two_dpas(api)
        old = validate_success(api.get_dpa(dpa1["id"], CSR), 200)
        assert old["status"] == "CANCELLED", "the superseded DRAFT is cancelled"
        resp = attempt_create_dpa(account["id"], installment_count=6)
        validate_error(resp, ApiErrorId.ERR_OPEN_DPA_EXISTS)

    def test_terminal_dpa_frees_capacity(self, api):
        """PRD §3.4: "Cancellation, by a `CustomerServiceRep` or `ProgramAdmin`, is
        available from `DRAFT`, `ACTIVE`, or `DEFAULTED`".
        PRD §3.4: "an account carrying an `ACTIVE` or `DEFAULTED` DPA is rejected
        with `ERR_OPEN_DPA_EXISTS` (HTTP 422), while a lingering `DRAFT` is quietly
        superseded into `CANCELLED` rather than treated as an error".

        Design: Difficulty/resource_temporal_overlap/dpa_single_active_capacity_per_account
        """
        account, _dpa1, dpa2 = self._account_with_two_dpas(api)
        cancelled = validate_success(api.cancel_dpa(dpa2["id"], CSR), 200)
        assert cancelled["status"] == "CANCELLED"
        successor = attempt_create_dpa(account["id"], installment_count=6)
        data = validate_success(successor, 201)
        assert data["status"] == "DRAFT"


class TestDpaLedgerConservationThroughBreak:
    def _defaulted_tier2_dpa(self, api):
        """TIER_2 account, 120000 arrearage; DPA n=4 (down 6000, pool 40000,
        installment 18500); down paid 2026-08-01; one on-time installment paid
        2026-08-05 (credit 10000); clock 2026-10-06 swept to DEFAULTED."""
        account, _app, _enr = setup_account_with_active_enrollment(
            income=INCOME_TIER_2, arrearage_cents=120_000,
            service_address="72 Ledger Ln")
        dpa = create_dpa(account["id"], installment_count=4)
        pay(account["id"], 6_000)
        set_clock("2026-08-05T00:00:00Z")
        pay(account["id"], 18_500, tender_type="CARD")
        set_clock("2026-10-06T00:00:00Z")
        run_sweep()
        return account, dpa

    def test_midflight_ledger_conserved_in_default(self, api):
        """PRD §3.4: "The working balance `remaining_balance_cents` is
        `covered_arrearage_cents` minus `paid_to_arrearage_cents` minus
        `forgiven_posted_cents`, where `paid_to_arrearage_cents` accumulates the
        down payment, whole installments, and any extra arrears payments routed
        through this DPA."

        Design: Difficulty/compensating_invariant/dpa_ledger_conservation_through_break
        """
        _account, dpa = self._defaulted_tier2_dpa(api)
        mid = validate_success(api.get_dpa(dpa["id"], CSR), 200)
        assert mid["status"] == "DEFAULTED"
        assert mid["paid_to_arrearage_cents"] == 24_500  # 6000 down + 18500 installment
        assert mid["forgiven_posted_cents"] == 10_000
        assert mid["remaining_balance_cents"] == 85_500
        assert_dpa_ledger_invariants(mid)

    def test_break_reverses_credits_with_zero_drift(self, api):
        """PRD §3.4: "Left uncured, the sweep breaks the agreement once the clock
        date passes `defaulted_on` plus 15 days: status becomes `BROKEN`, every
        `POSTED` ForgivenessCredit flips to `REVERSED`, the sum of the reversed
        amounts is added back onto the account's `arrearage_balance_cents`,
        `forgiven_posted_cents` is recomputed and drops to 0,
        `remaining_balance_cents` is recomputed".
        PRD §3.1: "`arrearage_balance_cents` is the past-due balance, mutated by
        charges, payments, forgiveness credits and their reversals, and assistance
        disbursements."

        Design: Difficulty/compensating_invariant/dpa_ledger_conservation_through_break
        """
        account, dpa = self._defaulted_tier2_dpa(api)
        set_clock("2026-10-22T00:00:00Z")  # past defaulted_on 2026-10-06 + 15 days
        sweep = run_sweep()
        assert sweep["dpas_broken"] == 1
        end = validate_success(api.get_dpa(dpa["id"], CSR), 200)
        assert end["status"] == "BROKEN"
        assert end["forgiven_posted_cents"] == 0
        assert end["paid_to_arrearage_cents"] == 24_500
        assert end["remaining_balance_cents"] == 95_500
        assert_dpa_ledger_invariants(end)
        credits, _meta = validate_paginated(
            api.list_forgiveness_credits(dpa["id"], CSR))
        assert len(credits) == 1
        assert credits[0]["status"] == "REVERSED"
        account = get_account(account["id"])
        assert account["arrearage_balance_cents"] == 95_500, (
            "85500 + the reversed 10000 lands back on arrearage with no drift")


def test_invalid_request_beats_not_found(api):
    """PRD §2.8: "Validation on every request proceeds through a fixed global
    pipeline; a failure at any stage surfaces that stage's error and masks nothing
    later."
    PRD §2.8: "4. **Request shape** — required fields are present, types match,
    enum members are valid, and integer ranges hold (`household_size` from 1 to 12
    inclusive, `installment_count` from 2 to 12 inclusive, a payment's
    `amount_cents` strictly positive), else `ERR_INVALID_REQUEST` (HTTP 400)."
    PRD §2.8: "5. **Existence** — every path identifier and every body-supplied
    foreign-key identifier must resolve to an existing resource, validated left to
    right; the first unresolvable identifier yields `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/validations/invalid_request_beats_not_found
    """
    resp = api_client.create_dpa({"account_id": NON_EXISTENT_UUID}, CSR)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_dpa_cancel_from_completed_rejected(api):
    """PRD §3.4: "Completion is the happy twin of default: when a payment posting
    leaves `remaining_balance_cents` at exactly zero, the DPA moves from `ACTIVE`
    to `COMPLETED` and its ledger closes — covered arrearage equals amounts paid
    plus amounts forgiven, with nothing left over."
    PRD §3.4: "Terminal states reject further transitions with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/dpa_cancel_from_completed_rejected
    """
    account = create_account(service_address="8 Complete Ct")
    charge_arrearage(account["id"], 120_000)
    dpa = create_dpa(account["id"], installment_count=4)  # down 12000, inst 27000
    pay(account["id"], 12_000)
    settle = pay(account["id"], 108_000, tender_type="CHECK")
    assert settle["installments_settled_count"] == 4
    before = validate_success(api.get_dpa(dpa["id"], CSR), 200)
    assert before["status"] == "COMPLETED"
    assert before["remaining_balance_cents"] == 0
    resp = api.cancel_dpa(dpa["id"], CSR)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    stayed = validate_success(api.get_dpa(dpa["id"], CSR), 200)
    assert stayed["status"] == "COMPLETED"


def test_dpa_schedule_remainder_and_final_credit(api):
    """PRD §3.4: "Sixth, `final_installment_amount_cents` — installment n — is the
    base minus (n-1) times the equal installment, absorbing the rounding remainder
    so the schedule sums exactly."
    PRD §3.5: "The credit amount for installment k of n is the forgiveness pool
    divided by n, rounded half-up, for every installment before the last; the final
    installment's credit is the pool minus the sum of the credits actually posted
    for installments 1 through n-1, so the final credit absorbs rounding."

    Design: Corner/calculations/dpa_schedule_remainder_and_final_credit
    """
    account, _app, _enr = setup_account_with_active_enrollment(
        income=INCOME_TIER_3, arrearage_cents=100_001,
        service_address="23 Remainder Rd")
    dpa = create_dpa(account["id"], installment_count=6)
    assert dpa["down_payment_required_cents"] == 10_000   # max(round(10000.1), 5000)
    assert dpa["forgiveness_pool_cents"] == 25_000        # round(100001*0.25)
    assert dpa["installment_amount_cents"] == 10_834      # round_half_up(65001/6)
    assert dpa["final_installment_amount_cents"] == 10_831  # 65001 - 5*10834
    pay(account["id"], 10_000)  # down payment activates at 2026-08-01
    set_clock("2026-08-05T00:00:00Z")
    payment = pay(account["id"], 65_001, tender_type="CHECK")
    assert payment["installments_settled_count"] == 6
    assert payment["on_time"] is True
    assert payment["credit_accrued_cents"] == 25_000
    credits, _meta = validate_paginated(api.list_forgiveness_credits(dpa["id"], CSR))
    by_installment = {c["installment_number"]: c["amount_cents"] for c in credits}
    assert len(by_installment) == 6
    for k in range(1, 6):
        assert by_installment[k] == 4_167, f"credit {k} should be round_half_up(25000/6)"
    assert by_installment[6] == 4_165, "final credit absorbs the rounding remainder"
    end = validate_success(api.get_dpa(dpa["id"], CSR), 200)
    assert end["forgiven_posted_cents"] == 25_000
    assert end["remaining_balance_cents"] == 0
    assert end["status"] == "COMPLETED"
    assert_dpa_ledger_invariants(end)


def test_arrearage_minimum_boundary_dpa_create(api):
    """PRD §3.4: "the fiscal floor, which refuses agreements over trivial debt: the
    account's `arrearage_balance_cents` must be at least 10000 cents ($100.00),
    else `ERR_ARREARAGE_BELOW_MINIMUM` (HTTP 422)."

    Design: Corner/validations/arrearage_minimum_boundary_dpa_create
    """
    a1 = create_account(service_address="34 Min Rd A1")
    charge_arrearage(a1["id"], 9_999)
    resp = attempt_create_dpa(a1["id"], installment_count=2)
    validate_error(resp, ApiErrorId.ERR_ARREARAGE_BELOW_MINIMUM)

    a2 = create_account(service_address="35 Min Rd A2")
    charge_arrearage(a2["id"], 10_000)
    created = attempt_create_dpa(a2["id"], installment_count=2)
    data = validate_success(created, 201)
    assert data["status"] == "DRAFT", "exactly 10000 meets the inclusive minimum"


def test_reinstate_cure_window_expired(api):
    """PRD §3.4: "Reinstate enforces its guards in order — a DPA that is not
    `DEFAULTED` fails with `ERR_DPA_NOT_REINSTATABLE` (HTTP 409), and a cure
    attempted after the window fails with `ERR_CURE_WINDOW_EXPIRED` (HTTP 422)."
    PRD §3.4: "A default is curable within a fifteen-day window: a
    `CustomerServiceRep` reinstates the agreement when the clock date is on or
    before `defaulted_on` plus 15 days".

    Design: Corner/validations/reinstate_cure_window_expired
    """
    account = create_account(service_address="32 Cure Ct")
    charge_arrearage(account["id"], 120_000)
    dpa = create_dpa(account["id"], installment_count=4)  # down 12000, inst 27000
    pay(account["id"], 12_000)
    set_clock("2026-09-06T00:00:00Z")
    run_sweep()  # installment 1 due 2026-08-31 + 5 grace days passed -> DEFAULTED
    pay(account["id"], 27_000)  # settle the missed installment inside the window
    set_clock("2026-09-22T00:00:00Z")  # defaulted_on 2026-09-06 + 15 = 2026-09-21
    resp = api.reinstate_dpa(dpa["id"], CSR)
    validate_error(resp, ApiErrorId.ERR_CURE_WINDOW_EXPIRED)
    stayed = validate_success(api.get_dpa(dpa["id"], CSR), 200)
    assert stayed["status"] == "DEFAULTED"


def test_dpa_reinstate_from_active_rejected(api):
    """PRD §3.4: "Reinstate enforces its guards in order — a DPA that is not
    `DEFAULTED` fails with `ERR_DPA_NOT_REINSTATABLE` (HTTP 409), and a cure
    attempted after the window fails with `ERR_CURE_WINDOW_EXPIRED` (HTTP 422)."

    Design: Corner/validations/dpa_reinstate_from_active_rejected
    """
    account = create_account(service_address="48 Reinstate Rd")
    charge_arrearage(account["id"], 120_000)
    dpa = create_and_activate_dpa(account["id"], installment_count=4)
    assert dpa["status"] == "ACTIVE"
    resp = api.reinstate_dpa(dpa["id"], CSR)
    validate_error(resp, ApiErrorId.ERR_DPA_NOT_REINSTATABLE)
    stayed = validate_success(api.get_dpa(dpa["id"], CSR), 200)
    assert stayed["status"] == "ACTIVE"


def test_occ_dpa_create_stale_version_rejected(api):
    """PRD §2.7: "If the account's current `version` has advanced beyond that
    observed value — because another writer posted a charge, filed a newer
    application, created a DPA, or otherwise mutated the account in the meantime —
    the create is rejected with `ERR_STALE_ACCOUNT_VERSION` (HTTP 412), so a client
    never silently supersedes work it never saw."

    Design: Corner/cross_cutting_layers/occ_dpa_create_stale_version_rejected
    """
    account = create_account(service_address="80 Occ Oaks")
    charge_arrearage(account["id"], 120_000)
    observed = fresh_account_version(account["id"])
    first = attempt_create_dpa(account["id"], installment_count=4, expected_version=observed)
    validate_success(first, 201)
    stale = attempt_create_dpa(account["id"], installment_count=6, expected_version=observed)
    validate_error(stale, ApiErrorId.ERR_STALE_ACCOUNT_VERSION)
    rows, meta = validate_paginated(api.list_dpas(ADMIN, params={"account_id": account["id"]}))
    assert meta["total_count"] == 1, "the rejected create must not supersede the first DRAFT"
    assert rows[0]["status"] == "DRAFT"
