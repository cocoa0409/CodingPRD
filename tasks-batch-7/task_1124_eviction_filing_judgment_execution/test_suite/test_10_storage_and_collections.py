"""Storage charge variants and collection waterfall corners (PRD 3.7, 3.8)."""
from test_helpers import (
    ApiErrorId,
    CLERK_A,
    assert_instant_equal,
    create_collection_entry_payload,
    get_collection_entry,
    get_judgment,
    get_storage_record,
    make_deputy_headers,
    make_landlord_headers,
    run_ops,
    set_clock,
    setup_executed_with_storage,
    setup_judgment_entered,
    validate_error,
    validate_success,
)
from test_helpers import api_client


class TestStorageChargeCalendarVsElapsed24h:
    """Depth instance: identical instants, jurisdiction-selected variant
    diverges the accrued storage charge."""

    def _accrued_at(self, ctx, when, dep):
        set_clock(when)
        return get_storage_record(ctx["storage"]["id"])["accrued_charge_cents"]

    def test_calendar_inclusive_charges_two_days_where_elapsed_charges_one(self, api):
        """PRD 3.7: "under CALENDAR_INCLUSIVE the chargeable days are the
        calendar dates touched by the storage interval, counting both the
        stored date and the current date — a partial first day and a partial
        final day each count as a full day; under ELAPSED_24H the chargeable
        days are the elapsed 24-hour periods with any partial period rounded
        up, so a record twenty-three hours old charges one day where the
        inclusive-calendar mode would charge two."

        Design: Difficulty/dual_variant_calc/storage_charge_calendar_vs_elapsed_24h
        """
        ca = setup_executed_with_storage("CA")
        tx = setup_executed_with_storage("TX", deputy_id="dep-2")
        # Both stored at 2026-06-26T09:00:00Z; read at 2026-06-27T08:00:00Z
        # (23 elapsed hours).
        dep_ca = make_deputy_headers("dep-1")
        dep_tx = make_deputy_headers("dep-2")
        acc_ca = self._accrued_at(ca, "2026-06-27T08:00:00Z", dep_ca)
        acc_tx = self._accrued_at(tx, "2026-06-27T08:00:00Z", dep_tx)
        assert acc_ca == 3000, "CA CALENDAR_INCLUSIVE: 2 calendar days x 1500"
        assert acc_tx == 1000, "TX ELAPSED_24H: ceil(23h/24h) = 1 day x 1000"

        # Reclaim locks final_charge_cents to the accrued amount.
        rec_ca = validate_success(api.reclaim_storage_record(
            ca["storage"]["id"], {"charge_paid_cents": acc_ca}, dep_ca), 200)
        rec_tx = validate_success(api.reclaim_storage_record(
            tx["storage"]["id"], {"charge_paid_cents": acc_tx}, dep_tx), 200)
        assert rec_ca["final_charge_cents"] == 3000
        assert rec_tx["final_charge_cents"] == 1000
        assert rec_ca["status"] == "RECLAIMED"
        assert rec_tx["status"] == "RECLAIMED"

    def test_same_day_reclaim_single_day_charge(self, api):
        """PRD 3.7: "The charge is the chargeable days multiplied by the
        daily fee" and under CALENDAR_INCLUSIVE "counting both the stored
        date and the current date"; under ELAPSED_24H "any partial period
        rounded up".

        Design: Difficulty/dual_variant_calc/storage_charge_calendar_vs_elapsed_24h
        """
        ca = setup_executed_with_storage("CA")
        # Clock unchanged from the execution instant (2026-06-26T09:00:00Z):
        # stored date == current date -> one inclusive calendar day.
        record = get_storage_record(ca["storage"]["id"])
        assert record["accrued_charge_cents"] == 1500, (
            "CA: stored date counts as one full calendar day")
        assert record["daily_fee_cents"] == 1500

        tx = setup_executed_with_storage("TX", deputy_id="dep-2")
        # One hour after the execution instant: a partial 24-hour period has
        # elapsed, which rounds up to one day. (At exactly zero elapsed hours
        # the PRD's "elapsed 24-hour periods with any partial period rounded
        # up" does not say whether a period has begun, so that reading is not
        # asserted here.)
        set_clock("2026-06-26T10:00:00Z")
        record_tx = get_storage_record(tx["storage"]["id"])
        assert record_tx["accrued_charge_cents"] == 1000, (
            "TX: a partial 24h period rounds up to one day")
        assert record_tx["daily_fee_cents"] == 1000


class TestWaterfallPartialStraddleAllocation:
    """Corner instance: a payment straddles buckets in fixed priority order."""

    def test_straddle_fills_costs_then_late_fees(self, api):
        """PRD 3.8: "A PAYMENT allocates across five buckets in a fixed
        priority order — court costs first, then late fees, then damages,
        then interest, then rent ... The payment walks the buckets in order,
        applying to each bucket the lesser of its remainder and the amount
        still unallocated, until the payment is exhausted."

        Design: Corner/calculations/waterfall_partial_straddle_allocation
        """
        ctx = setup_judgment_entered(
            "CA", rent_awarded_cents=100000, damages_cents=5000,
            late_fee_cents=2000, court_costs_cents=1000,
            oldest_unpaid_due_date="2026-06-20",
        )
        ll = make_landlord_headers(ctx["landlord"]["id"])
        entry = validate_success(api.create_collection_entry(
            ctx["judgment"]["id"],
            create_collection_entry_payload("PAYMENT", 2500), ll), 201)
        assert entry["resulting_outstanding_cents"] == 105500
        assert entry["allocation"] == {
            "court_costs": 1000, "late_fees": 1500, "damages": 0,
            "interest": 0, "rent": 0,
        }


class TestCollectionEntryImmutableShape:
    """Corner instance: CollectionEntry carries only id + created_at among
    common fields; no updated_at, no version."""

    def test_entry_has_no_version_or_updated_at(self, api):
        """PRD 2.4: "Two resources are deliberately immutable ledger-style
        records and break this pattern: a **ServiceAttempt** and a
        **CollectionEntry** each carry only id and created_at. Both updated_at
        and version are absent from them, because neither resource is ever
        modified after creation."

        Design: Corner/entities/collection_entry_immutable_shape
        """
        ctx = setup_judgment_entered(
            "CA", rent_awarded_cents=100000, damages_cents=5000,
            late_fee_cents=2000, court_costs_cents=1000,
            oldest_unpaid_due_date="2026-06-20",
        )
        ll = make_landlord_headers(ctx["landlord"]["id"])
        entry = validate_success(api.create_collection_entry(
            ctx["judgment"]["id"],
            create_collection_entry_payload("PAYMENT", 1000), ll), 201)
        read = validate_success(api.get_collection_entry(entry["id"], CLERK_A), 200)
        assert "version" not in read, "CollectionEntry must not expose version"
        assert "updated_at" not in read, "CollectionEntry must not expose updated_at"
        assert "id" in read and "created_at" in read
        assert read["resulting_outstanding_cents"] == 107000


class TestOverpaymentRejectedExactPayoffSatisfies:
    """Corner instance: PAYMENT above outstanding fails; exact payoff flips
    the judgment to SATISFIED."""

    def test_overpayment_rejected_exact_payoff_satisfies(self, api):
        """PRD 3.8: "A payment larger than the judgment's current
        outstanding_balance_cents is rejected with
        ERR_PAYMENT_EXCEEDS_OUTSTANDING (HTTP 422), though an exact payoff is
        allowed" and "When a payment, reversal, or write-off drives that
        balance to zero, the judgment becomes SATISFIED and satisfied_at is
        stamped."

        Design: Corner/validations/overpayment_rejected_exact_payoff_satisfies
        """
        ctx = setup_judgment_entered(
            "CA", rent_awarded_cents=100000, damages_cents=5000,
            late_fee_cents=2000, court_costs_cents=1000,
            oldest_unpaid_due_date="2026-06-20",
        )
        ll = make_landlord_headers(ctx["landlord"]["id"])
        jid = ctx["judgment"]["id"]

        resp = api.create_collection_entry(
            jid, create_collection_entry_payload("PAYMENT", 108001), ll)
        validate_error(resp, ApiErrorId.ERR_PAYMENT_EXCEEDS_OUTSTANDING, 422)

        ok = validate_success(api.create_collection_entry(
            jid, create_collection_entry_payload("PAYMENT", 108000), ll), 201)
        assert ok["resulting_outstanding_cents"] == 0

        judgment = get_judgment(jid)
        assert judgment["status"] == "SATISFIED"
        assert_instant_equal(judgment["satisfied_at"], "2026-06-20T12:00:00Z")


class TestReversalTargetInvalid:
    """Corner instance: REVERSAL against a nonexistent entry id."""

    def test_reversal_of_nonexistent_entry_rejected(self, api):
        """PRD 3.8: "its reversal_of_id must reference a PAYMENT entry on the
        same judgment that has not already been reversed
        (ERR_REVERSAL_TARGET_INVALID, HTTP 422)."

        Design: Corner/validations/reversal_target_invalid
        """
        ctx = setup_judgment_entered(
            "CA", rent_awarded_cents=50000, oldest_unpaid_due_date="2026-06-20")
        ll = make_landlord_headers(ctx["landlord"]["id"])
        resp = api.create_collection_entry(
            ctx["judgment"]["id"],
            create_collection_entry_payload(
                "REVERSAL", 100,
                reversal_of_id="00000000-0000-0000-0000-000000000000"),
            ll,
        )
        validate_error(resp, ApiErrorId.ERR_REVERSAL_TARGET_INVALID, 422)


class TestReclaimWrongChargeRejected:
    """Corner instance: reclaim must pay exactly the accrued charge."""

    def test_wrong_charge_rejected_exact_reclaims(self, api):
        """PRD 3.7: "the deputy records the reclaim only when the payload's
        charge_paid_cents exactly equals the accrued_charge_cents at the
        current clock; any mismatch is rejected with
        ERR_STORAGE_CHARGE_MISMATCH (HTTP 422). A successful reclaim locks
        final_charge_cents to the accrued amount."

        Design: Corner/validations/reclaim_wrong_charge_rejected
        """
        ctx = setup_executed_with_storage("CA")
        dep = make_deputy_headers("dep-1")
        # Clock still at the execution instant: accrued = 1 day x 1500.
        resp = api.reclaim_storage_record(
            ctx["storage"]["id"], {"charge_paid_cents": 9999}, dep)
        validate_error(resp, ApiErrorId.ERR_STORAGE_CHARGE_MISMATCH, 422)

        ok = validate_success(api.reclaim_storage_record(
            ctx["storage"]["id"], {"charge_paid_cents": 1500}, dep), 200)
        assert ok["status"] == "RECLAIMED"
        assert ok["final_charge_cents"] == 1500


class TestDisposeWhileStoredRejected:
    """Corner instance: disposal requires the DISPOSABLE status."""

    def test_dispose_before_eligibility_rejected_then_allowed(self, api):
        """PRD 3.7: "Disposal of unclaimed property is permitted only from
        DISPOSABLE — disposing before the statutory period has elapsed is a
        compliance violation rejected with ERR_DISPOSAL_NOT_ELIGIBLE
        (HTTP 409) — and moves the record to DISPOSED."

        Design: Corner/validations/dispose_while_stored_rejected
        """
        ctx = setup_executed_with_storage("CA")
        dep = make_deputy_headers("dep-1")
        sr_id = ctx["storage"]["id"]
        # disposal_eligible_on is read from the record at runtime.
        eligible = ctx["storage"]["disposal_eligible_on"]

        resp = api.dispose_storage_record(sr_id, dep)
        validate_error(resp, ApiErrorId.ERR_DISPOSAL_NOT_ELIGIBLE, 409)

        # One second past eligibility; the sweep marks it DISPOSABLE.
        from datetime import datetime, timedelta

        dt = datetime.fromisoformat(eligible.replace("Z", "+00:00"))
        set_clock((dt + timedelta(seconds=1)).strftime("%Y-%m-%dT%H:%M:%SZ"))
        summary = run_ops()
        assert summary["storage_records_disposable"] == 1

        disposed = validate_success(api.dispose_storage_record(sr_id, dep), 200)
        assert disposed["status"] == "DISPOSED"
