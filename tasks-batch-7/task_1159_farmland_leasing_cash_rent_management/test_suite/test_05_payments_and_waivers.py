"""Cash collection: late fees, the fee-first waterfall, payment boundaries,
waivers, segregation-of-duties reversal, and the landlord-ledger invariant."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    assert_installment,
    assert_iso_instant_equal,
    assert_landlord_ledger,
    get_installment,
    get_landlord,
    list_lease_installments,
    setup_late_installment_scenario,
    setup_open_installment_scenario,
    setup_paid_installment_scenario,
    validate_error,
    validate_success,
)

MGR = TEST_USERS["farm_manager_headers"]
MGR_1 = TEST_USERS["mgr_1_headers"]
MGR_2 = TEST_USERS["mgr_2_headers"]


class TestLateFeeWaterfall:
    def test_late_fee_applied_once_and_waterfall_pays_fee_first(self, api):
        """PRD §3.5: "When the clock passes more than ten days beyond the `due_date` and the amount paid so far does not yet cover the scheduled amount plus the late fee, the sweep moves the installment from `OPEN` to `LATE`; that transition charges the late fee exactly once — five percent of the installment's `amount_cents`, rounded half up to whole cents"
        PRD §3.5: "Each payment is allocated as a waterfall: the late-fee portion is covered first, and only then does money flow to principal."
        PRD §3.5: "The installment reaches `PAID` exactly when its `paid_cents` covers the scheduled amount plus the late fee — equality pays in full"

        Design: Corner/state_machines/late_fee_applied_once_and_waterfall_pays_fee_first
        """
        ctx = setup_late_installment_scenario()  # clock 2027-03-12
        installment = ctx["installments"][0]
        assert installment["status"] == "LATE", "past due+10d grace with nothing paid"
        assert installment["late_fee_cents"] == 62500, (
            "one-time fee: round_half_up(1250000 * 0.05)"
        )

        fee_only = validate_success(
            api.record_payment(installment["id"], {"amount_cents": 62500}, MGR_1)
        )
        assert fee_only["status"] == "LATE", "fee covered but principal untouched"
        assert fee_only["paid_cents"] == 62500, "waterfall pays the late fee first"

        remainder = validate_success(
            api.record_payment(installment["id"], {"amount_cents": 1250000}, MGR_1)
        )
        assert remainder["status"] == "PAID"
        assert remainder["paid_cents"] == 1312500, "62500 fee + 1250000 principal"


class TestPaymentBoundaries:
    def test_payment_over_outstanding_rejected(self, api):
        """PRD §3.5: "The request carries an `amount_cents` that must be positive and no greater than the outstanding balance — the scheduled amount plus the late fee minus what has already been paid — or the recording is rejected with `ERR_PAYMENT_EXCEEDS_BALANCE`."

        Design: Corner/validations/payment_over_outstanding_rejected
        """
        ctx = setup_open_installment_scenario()
        installment = ctx["installments"][0]
        assert installment["status"] == "OPEN"
        resp = api.record_payment(installment["id"], {"amount_cents": 1250001}, MGR)
        validate_error(resp, ApiErrorId.ERR_PAYMENT_EXCEEDS_BALANCE)

    def test_exact_full_payment_marks_paid(self, api):
        """PRD §3.5: "The installment reaches `PAID` exactly when its `paid_cents` covers the scheduled amount plus the late fee — equality pays in full — and every recording recomputes the landlord's `total_received_cents` and `pending_receivable_cents`."
        PRD §2.10: "The `pending_receivable_cents` balance is the sum, over installments of that landlord's leases currently in `OPEN` or `LATE` status, of each installment's scheduled `amount_cents` plus its `late_fee_cents` minus its `paid_cents`."

        Design: Difficulty/boundary_precision_check/exact_full_payment_marks_paid
        """
        ctx = setup_open_installment_scenario()
        installment = ctx["installments"][0]
        paid = validate_success(
            api.record_payment(installment["id"], {"amount_cents": 1250000}, MGR_1)
        )
        assert paid["status"] == "PAID", "equality pays in full"
        assert paid["paid_cents"] == 1250000
        landlord = get_landlord(ctx["landlord"]["id"])
        # I1 PAID and I2 still SCHEDULED: neither contributes to the pending sum.
        assert_landlord_ledger(
            landlord, total_received_cents=1250000, pending_receivable_cents=0
        )

    def test_one_cent_short_leaves_installment_open(self, api):
        """PRD §3.5: "The installment reaches `PAID` exactly when its `paid_cents` covers the scheduled amount plus the late fee — equality pays in full"
        PRD §3.5: "Partial payments are ordinary; several recordings may precede full coverage."

        Design: Difficulty/boundary_precision_check/exact_full_payment_marks_paid
        """
        ctx = setup_open_installment_scenario()
        installment = ctx["installments"][0]
        partial = validate_success(
            api.record_payment(installment["id"], {"amount_cents": 1249999}, MGR_1)
        )
        assert partial["status"] == "OPEN", "one cent below full coverage stays OPEN"
        assert partial["paid_cents"] == 1249999
        landlord = get_landlord(ctx["landlord"]["id"])
        # outstanding on I1 = 1250000 - 1249999 = 1; I2 SCHEDULED is excluded.
        assert_landlord_ledger(
            landlord, total_received_cents=1249999, pending_receivable_cents=1
        )


class TestImmediateVisibility:
    def test_record_payment_response_reflects_immediate_mutation(self, api):
        """PRD §3.5: "The installment's `paid_cents` grows by the amount recorded, `last_payment_at` is stamped from the clock, and `paid_recorded_by` captures the recording manager's `X-User-ID`."
        PRD §2.2: "Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field."

        Design: Corner/consistency_model/record_payment_response_reflects_immediate_mutation
        """
        ctx = setup_open_installment_scenario()
        installment = ctx["installments"][0]
        resp = api.record_payment(installment["id"], {"amount_cents": 1250000}, MGR_1)
        data = validate_success(resp)  # the response body itself, no re-read
        assert_installment(data)
        assert data["status"] == "PAID"
        assert data["paid_cents"] == 1250000
        assert_iso_instant_equal(data["last_payment_at"], "2027-03-01T00:00:00Z")
        assert data["paid_recorded_by"] == "mgr-1"


class TestWaiverAuthority:
    def test_waiver_over_authority_cap_rejected_then_consent_passes(self, api):
        """PRD §3.5: "A manager's unilateral authority extends only to outstanding balances of one hundred thousand cents or less; waiving more than that requires the request to carry `landlord_consent` set to true, and without it the waiver is rejected with `ERR_WAIVER_EXCEEDS_AUTHORITY`."
        PRD §3.5: "Waiver writes off an outstanding balance, moving an `OPEN` or `LATE` installment to the terminal `WAIVED` state with a recorded `reason`."

        Design: Corner/validations/waiver_over_authority_cap_rejected_then_consent_passes
        """
        ctx = setup_open_installment_scenario(
            payment_pattern="FULL_MAR", cash_bid_cents=10000, min_bid_cents=5000
        )
        installment = ctx["installments"][0]
        assert installment["amount_cents"] == 1000000, "FULL_MAR: single annual bill"
        assert installment["status"] == "OPEN"

        denied = api.waive_installment(
            installment["id"], {"reason": "manager-only waiver attempt"}, MGR
        )
        validate_error(denied, ApiErrorId.ERR_WAIVER_EXCEEDS_AUTHORITY)
        assert get_installment(installment["id"])["status"] == "OPEN", (
            "failed waiver changes nothing"
        )

        waived = validate_success(
            api.waive_installment(
                installment["id"],
                {"reason": "owner-approved hardship waiver", "landlord_consent": True},
                MGR,
            )
        )
        assert waived["status"] == "WAIVED"


class TestPaymentOnWaivedInstallment:
    def _waived_installment(self, api):
        ctx = setup_open_installment_scenario()
        installment = ctx["installments"][0]
        waived = validate_success(
            api.waive_installment(
                installment["id"],
                {"reason": "goodwill after crop failure", "landlord_consent": True},
                MGR,
            )
        )
        assert waived["status"] == "WAIVED"
        return ctx, installment

    def test_payment_on_waived_installment_state_beats_fiscal(self, api):
        """PRD §2.8: "Incoming requests are validated against a fixed pipeline, and when several checks would fail, the earliest category's error is the one returned."
        PRD §2.8: "State preconditions — the target resource must be in a valid from-state for the requested transition (`ERR_INVALID_STATE`, HTTP 409)"
        PRD §3.5: "Payments are recorded by managers against `OPEN` or `LATE` installments."

        Design: Difficulty/priority_pair_validation_conflict/waived_installment_payment_state_beats_fiscal
        """
        _, installment = self._waived_installment(api)
        resp = api.record_payment(installment["id"], {"amount_cents": 1250000}, MGR)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_small_payment_on_waived_installment_state_beats_fiscal(self, api):
        """PRD §2.8: "Incoming requests are validated against a fixed pipeline, and when several checks would fail, the earliest category's error is the one returned."
        PRD §3.5: "Waiver writes off an outstanding balance, moving an `OPEN` or `LATE` installment to the terminal `WAIVED` state with a recorded `reason`."
        PRD §3.5: "Payments are recorded by managers against `OPEN` or `LATE` installments."

        Design: Difficulty/priority_pair_validation_conflict/waived_installment_payment_state_beats_fiscal
        """
        _, installment = self._waived_installment(api)
        resp = api.record_payment(installment["id"], {"amount_cents": 1}, MGR)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_installment(installment["id"])["status"] == "WAIVED"


class TestReversal:
    def test_reverse_by_recording_manager_forbidden(self, api):
        """PRD §2.11: "A payment recorded by one manager must be reversed by a different manager: the reversal request's `X-User-ID` must differ from the installment's `paid_recorded_by`, under the same error and status."

        Design: Corner/cross_cutting_layers/reverse_by_recording_manager_forbidden
        """
        ctx = setup_paid_installment_scenario(payer_headers=MGR_1)
        installment = ctx["paid_installment"]
        assert installment["status"] == "PAID"
        resp = api.reverse_payment(installment["id"], MGR_1)
        validate_error(resp, ApiErrorId.ERR_DUTY_SEGREGATION_VIOLATION)
        after = get_installment(installment["id"])
        assert after["status"] == "PAID" and after["paid_cents"] == 1250000

    def test_reversal_reopens_installment_and_zeroes_paid(self, api):
        """PRD §3.5: "Reversal undoes all payments on the installment in full: `paid_cents` resets to zero, `paid_recorded_by` is cleared, and the installment reopens to `OPEN` — unless the clock has already passed more than ten days beyond the `due_date`, in which case it lands in `LATE` instead, retaining the previously charged `late_fee_cents`."

        Design: Difficulty/transitive_cascade/payment_reversal_recomputes_landlord_ledger
        """
        ctx = setup_paid_installment_scenario(payer_headers=MGR_1)
        installment = ctx["paid_installment"]
        reversed_inst = validate_success(
            api.reverse_payment(installment["id"], MGR_2)
        )
        assert reversed_inst["status"] == "OPEN", (
            "clock 2027-03-01 is within the grace window, so the installment "
            "reopens to OPEN, not LATE"
        )
        assert reversed_inst["paid_cents"] == 0
        assert reversed_inst.get("paid_recorded_by") is None, (
            "paid_recorded_by is cleared on reversal"
        )

    def test_reversal_recomputes_landlord_ledger(self, api):
        """PRD §3.5: "Landlord balances are recomputed either way."
        PRD §2.10: "The `total_received_cents` balance is the sum of `paid_cents` over all installments of all leases belonging to that landlord, regardless of installment status. The `pending_receivable_cents` balance is the sum, over installments of that landlord's leases currently in `OPEN` or `LATE` status, of each installment's scheduled `amount_cents` plus its `late_fee_cents` minus its `paid_cents`."

        Design: Difficulty/transitive_cascade/payment_reversal_recomputes_landlord_ledger
        """
        ctx = setup_paid_installment_scenario(payer_headers=MGR_1)
        installment = ctx["paid_installment"]
        validate_success(api.reverse_payment(installment["id"], MGR_2))
        landlord = get_landlord(ctx["landlord"]["id"])
        # After reversal: I1 is OPEN again (outstanding 1250000), I2 SCHEDULED
        # is excluded from the pending sum; no payments remain anywhere.
        assert_landlord_ledger(
            landlord, total_received_cents=0, pending_receivable_cents=1250000
        )

    def test_payment_raises_total_received_from_baseline(self, api):
        """PRD §2.10: "The `total_received_cents` balance is the sum of `paid_cents` over all installments of all leases belonging to that landlord, regardless of installment status."
        PRD §3.5: "and every recording recomputes the landlord's `total_received_cents` and `pending_receivable_cents`"

        Design: Difficulty/compensating_invariant/payment_then_reversal_conserves_landlord_balance
        """
        ctx = setup_open_installment_scenario()
        baseline = get_landlord(ctx["landlord"]["id"])
        assert baseline["total_received_cents"] == 0, "nothing paid yet"

        installment = ctx["installments"][0]
        validate_success(
            api.record_payment(installment["id"], {"amount_cents": 1250000}, MGR_1)
        )
        after = get_landlord(ctx["landlord"]["id"])
        assert after["total_received_cents"] == 1250000, (
            "total_received_cents tracks SUM(paid_cents)"
        )

    def test_payment_then_reversal_conserves_landlord_balance(self, api):
        """PRD §2.10: "Each landlord carries two derived balances, recomputed immediately on every triggering mutation — installment creation, payment, reversal, waiver, the `SCHEDULED`-to-`OPEN` and `OPEN`-to-`LATE` transitions, lease termination, and settlement countersigning."
        PRD §3.5: "Reversal undoes all payments on the installment in full: `paid_cents` resets to zero, `paid_recorded_by` is cleared, and the installment reopens to `OPEN`"

        Design: Difficulty/compensating_invariant/payment_then_reversal_conserves_landlord_balance
        """
        ctx = setup_open_installment_scenario()
        assert get_landlord(ctx["landlord"]["id"])["total_received_cents"] == 0

        installment = ctx["installments"][0]
        validate_success(
            api.record_payment(installment["id"], {"amount_cents": 1250000}, MGR_1)
        )
        assert get_landlord(ctx["landlord"]["id"])["total_received_cents"] == 1250000

        reversed_inst = validate_success(
            api.reverse_payment(installment["id"], MGR_2)
        )
        assert reversed_inst["paid_cents"] == 0
        final = get_landlord(ctx["landlord"]["id"])
        assert final["total_received_cents"] == 0, (
            "the compensating reversal returns the ledger to baseline: money conserved"
        )
