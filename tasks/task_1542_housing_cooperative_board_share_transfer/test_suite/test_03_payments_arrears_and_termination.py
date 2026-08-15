"""Payments, arrears, and termination of the proprietary lease: payment caps,
void compensation, derived arrears reconciliation, the termination-notice
threshold boundary, ledger conservation, and the termination cascade."""
from test_helpers import (
    AGENT,
    OFFICER,
    ApiErrorId,
    assert_charge_money_conservation,
    assert_payment,
    charge_for_month,
    force_charge_issuance,
    get_charge,
    get_shareholder,
    issue_arrears_action,
    open_resolution,
    pass_resolution,
    post_payment,
    setup_approved_schedule,
    setup_delinquent_shareholder,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestPaymentConstraints:
    def test_payment_exceeds_outstanding_rejected(self, api):
        """PRD §3.4: "The amount must be positive — a zero or negative
        amount is rejected with `ERR_INVALID_REQUEST` — and may not exceed the
        charge's `outstanding_cents`, on pain of `ERR_PAYMENT_EXCEEDS_OUTSTANDING`
        (HTTP 422)."

        Design: Corner/validations/payment_exceeds_outstanding_rejected
        """
        env = setup_approved_schedule(
            coop_overrides={"arrears_late_fee_flat_cents": 0,
                            "arrears_interest_rate_bps": 0},
            annual_budget_cents=1200000)
        coop_id = env["coop"]["id"]
        force_charge_issuance(coop_id)
        charge = charge_for_month(coop_id, "2026-08", env["unit"]["id"])
        assert charge["outstanding_cents"] == 100000
        resp = api.post_payment(coop_id, charge["id"],
                                {"shareholder_id": env["owner"]["id"],
                                 "amount_cents": 99999999},
                                AGENT)
        validate_error(resp, ApiErrorId.ERR_PAYMENT_EXCEEDS_OUTSTANDING,
                       expected_status=422)


class TestVoidCompensation:
    def test_payment_void_restores_charge_amounts(self, api):
        """PRD §3.4: "Voiding flips the payment to `VOIDED`, subtracts
        its amount from the charge's `paid_cents`, recomputes `outstanding_cents`
        and the shareholder's arrears balance, and if a formerly `PAID` charge
        reopens a positive balance the charge falls back to `PARTIALLY_PAID` —
        or to `PAST_DUE` when the grace window has already elapsed."

        Design: Corner/state_machines/payment_void_compensation_flow
        """
        env = setup_delinquent_shareholder(
            coop_overrides={"arrears_late_fee_flat_cents": 5000})
        coop_id = env["coop"]["id"]
        charge = env["charge"]
        assert charge["outstanding_cents"] == 105000  # base 100000 + late 5000

        payment = post_payment(coop_id, charge["id"], env["owner"]["id"], 30000)
        assert_payment(payment)
        resp = api.void_payment(coop_id, payment["id"], AGENT)
        voided = validate_success(resp, 200)
        assert voided["payment_status"] == "VOIDED"

        restored = get_charge(coop_id, charge["id"])
        assert restored["paid_cents"] == 0
        assert restored["outstanding_cents"] == 105000, (
            "void must restore outstanding to base + late fee "
            f"(105000), got {restored['outstanding_cents']}")
        assert_charge_money_conservation(restored)


class TestDerivedArrearsReconciliation:
    def test_arrears_balance_tracks_charges_and_payments(self, api):
        """PRD §3.1: "`arrears_balance_cents` is itself a derived figure
        — the sum of `outstanding_cents` across every maintenance charge
        attached to units the shareholder owns, recomputed on every charge or
        payment write."
        PRD §3.4: "When the balance returns to zero — and no termination
        notice is outstanding — `standing` returns from `DELINQUENT` to
        `GOOD_STANDING`."

        Design: Corner/complexity_layers/derived_field_reconciliation_arrears_balance
        """
        env = setup_delinquent_shareholder(
            coop_overrides={"arrears_late_fee_flat_cents": 5000})
        coop_id = env["coop"]["id"]
        owner_id = env["owner"]["id"]

        before = get_shareholder(coop_id, owner_id)
        assert before["arrears_balance_cents"] == 105000
        assert before["standing"] == "DELINQUENT"

        charge = get_charge(coop_id, env["charge"]["id"])
        payment = post_payment(coop_id, charge["id"], owner_id,
                               charge["outstanding_cents"])
        assert_payment(payment)
        paid_charge = get_charge(coop_id, charge["id"])
        assert paid_charge["charge_status"] == "PAID"
        assert paid_charge["outstanding_cents"] == 0

        after = get_shareholder(coop_id, owner_id)
        assert after["arrears_balance_cents"] == 0, \
            "derived balance recomputed on payment write"
        assert after["standing"] == "GOOD_STANDING"


class TestTerminationThresholdBoundary:
    def test_termination_notice_allowed_at_exact_threshold(self, api):
        """PRD §3.4: "Issuing a `TERMINATION_NOTICE` has a fiscal gate:
        the shareholder's `arrears_balance_cents` must be at least the
        cooperative's `arrears_termination_threshold_cents`, otherwise the
        issuance is rejected with `ERR_FISCAL_THRESHOLD_VIOLATION` (HTTP 422)."
        PRD §3.4: "the action starts `ISSUED`, stamped with `issued_at`,
        carrying a `cure_amount_cents` snapshot of the shareholder's arrears
        balance at issuance".

        Design: Difficulty/boundary_precision_check/arrears_termination_threshold_boundary
        """
        env = setup_delinquent_shareholder(
            coop_overrides={"arrears_termination_threshold_cents": 100000})
        coop_id = env["coop"]["id"]
        # budget 1200000 -> monthly base 100000; no late fee, no interest.
        assert env["charge"]["outstanding_cents"] == 100000
        owner = get_shareholder(coop_id, env["owner"]["id"])
        assert owner["arrears_balance_cents"] == 100000, "arrears exactly at threshold"

        action = validate_success(api.create_arrears_action(
            coop_id, {"shareholder_id": env["owner"]["id"],
                      "action_type": "TERMINATION_NOTICE"}, OFFICER), 201)
        assert action["action_type"] == "TERMINATION_NOTICE"
        assert action["action_status"] == "ISSUED"
        assert action["cure_amount_cents"] == 100000

    def test_termination_notice_rejected_one_cent_below_threshold(self, api):
        """PRD §3.4: "Issuing a `TERMINATION_NOTICE` has a fiscal gate:
        the shareholder's `arrears_balance_cents` must be at least the
        cooperative's `arrears_termination_threshold_cents`, otherwise the
        issuance is rejected with `ERR_FISCAL_THRESHOLD_VIOLATION` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/arrears_termination_threshold_boundary
        """
        # budget 1199988 -> round_half_up(1199988 / 12) = 99999 monthly base,
        # i.e. arrears exactly one cent below the 100000 threshold.
        env = setup_delinquent_shareholder(
            coop_overrides={"arrears_termination_threshold_cents": 100000},
            annual_budget_cents=1199988)
        coop_id = env["coop"]["id"]
        assert env["charge"]["outstanding_cents"] == 99999
        owner = get_shareholder(coop_id, env["owner"]["id"])
        assert owner["arrears_balance_cents"] == 99999

        resp = api.create_arrears_action(
            coop_id, {"shareholder_id": env["owner"]["id"],
                      "action_type": "TERMINATION_NOTICE"}, OFFICER)
        validate_error(resp, ApiErrorId.ERR_FISCAL_THRESHOLD_VIOLATION,
                       expected_status=422)


class TestChargeLedgerConservation:
    def test_payment_moves_money_within_conservation_law(self, api):
        """PRD §3.3: "its `outstanding_cents` is always the base plus
        late fee plus interest minus payments, never less than zero."
        PRD §3.4: "A payment smaller than the outstanding balance moves
        an `ISSUED` charge to `PARTIALLY_PAID`, adding the amount into
        `paid_cents` and recomputing `outstanding_cents` and the shareholder's
        `arrears_balance_cents`."

        Design: Difficulty/compensating_invariant/charge_ledger_conservation_through_payment_and_void
        """
        env = setup_delinquent_shareholder(
            coop_overrides={"arrears_late_fee_flat_cents": 5000})
        coop_id = env["coop"]["id"]
        charge = get_charge(coop_id, env["charge"]["id"])
        assert charge["base_amount_cents"] == 100000
        assert charge["late_fee_cents"] == 5000
        assert charge["outstanding_cents"] == 105000

        post_payment(coop_id, charge["id"], env["owner"]["id"], 50000)
        mid = get_charge(coop_id, charge["id"])
        assert mid["paid_cents"] == 50000
        assert mid["outstanding_cents"] == 55000
        assert_charge_money_conservation(mid)
        owner = get_shareholder(coop_id, env["owner"]["id"])
        assert owner["arrears_balance_cents"] == 55000, \
            "shareholder balance moves with the charge"

    def test_payment_then_void_exactly_restores_ledger(self, api):
        """PRD §3.3: "its `outstanding_cents` is always the base plus
        late fee plus interest minus payments, never less than zero."
        PRD §3.4: "Voiding flips the payment to `VOIDED`, subtracts its
        amount from the charge's `paid_cents`, recomputes `outstanding_cents`
        and the shareholder's arrears balance".

        Design: Difficulty/compensating_invariant/charge_ledger_conservation_through_payment_and_void
        """
        env = setup_delinquent_shareholder(
            coop_overrides={"arrears_late_fee_flat_cents": 5000})
        coop_id = env["coop"]["id"]
        charge_id = env["charge"]["id"]

        payment = post_payment(coop_id, charge_id, env["owner"]["id"], 50000)
        mid = get_charge(coop_id, charge_id)
        assert (mid["paid_cents"], mid["outstanding_cents"]) == (50000, 55000)

        voided = validate_success(api.void_payment(coop_id, payment["id"], AGENT), 200)
        assert voided["payment_status"] == "VOIDED"

        restored = get_charge(coop_id, charge_id)
        assert restored["paid_cents"] == 0
        assert restored["outstanding_cents"] == 105000, \
            "forward payment + compensating void leave the ledger unchanged"
        assert_charge_money_conservation(restored)
        owner = get_shareholder(coop_id, env["owner"]["id"])
        assert owner["arrears_balance_cents"] == 105000


class TestTerminationCascade:
    def test_termination_supersedes_share_ledger_entries(self, api):
        """PRD §3.4: "Escalating a `TERMINATION_NOTICE` is the gravest
        step and carries an extra precondition — a `PASSED` resolution of kind
        `ISSUE_ARREARS_ACTION` naming the shareholder must exist — and its
        effect is to move the shareholder's `standing` to `TERMINATED`, the
        terminal state of the standing machine."
        PRD §3.4: "Termination of the proprietary lease cascades widely:
        every `ShareLedgerEntry` the shareholder holds becomes `SUPERSEDED`".

        Design: Corner/complexity_layers/cascading_side_effect_termination_cascade
        """
        env = setup_delinquent_shareholder(
            coop_overrides={"arrears_termination_threshold_cents": 50000})
        coop_id = env["coop"]["id"]
        owner_id = env["owner"]["id"]
        assert get_shareholder(coop_id, owner_id)["arrears_balance_cents"] == 100000

        action = issue_arrears_action(coop_id, owner_id, "TERMINATION_NOTICE")
        resolution = open_resolution(
            coop_id, "ISSUE_ARREARS_ACTION", "Shareholder", owner_id,
            payload_json={"arrears_action_id": action["id"]})
        resolution = pass_resolution(coop_id, resolution["id"])
        assert resolution["resolution_status"] == "PASSED"
        # Manual escalation performs the transition once the prerequisite
        # resolution exists; tolerate the escalate call either way, then assert
        # the terminal outcome the PRD pins.
        api.escalate_arrears_action(coop_id, action["id"], OFFICER)

        owner = get_shareholder(coop_id, owner_id)
        assert owner["standing"] == "TERMINATED"
        data, _meta = validate_paginated(api.list_share_ledger_entries(
            coop_id, OFFICER, params={"shareholder_id": owner_id}))
        assert len(data) >= 1
        for entry in data:
            assert entry["entry_status"] == "SUPERSEDED", (
                "every ShareLedgerEntry the shareholder holds becomes SUPERSEDED")
