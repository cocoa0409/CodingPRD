"""Lapse sweeps and their ledger consequences, holdover settlement identity,
and withdrawal neutrality."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_contact,
    assert_ledger_entry,
    create_amendment,
    create_lease_payload,
    create_notice_payload,
    create_option_payload,
    get_success_data,
    make_am_headers,
    make_lc_headers,
    propose_amendment,
    set_clock,
    setup_active_lease,
    setup_lease_in_holdover,
    setup_option_on_active_lease,
    setup_portfolio_with_contacts,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


class TestMissedOptionConsequence:
    def _setup_two_lapsing_options(self, api, name):
        """One TERMINATION option with positive penalty, one ROFR with zero.
        Both share the same window so they lapse on the same sweep."""
        ws = setup_active_lease(name=name, region="EAST",
                                rentable_square_feet=8000,
                                base_rent_cents_per_rsf_year=4200)
        opt_a = get_success_data(api.create_option(
            ws["pid"], ws["lid"],
            create_option_payload(
                option_type="TERMINATION",
                notice_window_open_date="2026-08-10T00:00:00Z",
                notice_window_close_date="2026-09-10T00:00:00Z",
                target_commencement_date="2027-03-31T00:00:00Z",
                rate_determination="FIXED",
                fixed_rent_cents_per_rsf_year=4200,
                exercise_fee_cents=0,
                missed_option_penalty_cents=250000),
            ws["am_headers"]))
        opt_b = get_success_data(api.create_option(
            ws["pid"], ws["lid"],
            create_option_payload(
                option_type="ROFR",
                notice_window_open_date="2026-08-10T00:00:00Z",
                notice_window_close_date="2026-09-10T00:00:00Z",
                target_commencement_date="2027-03-31T00:00:00Z",
                rate_determination="FIXED",
                fixed_rent_cents_per_rsf_year=4200,
                exercise_fee_cents=0,
                missed_option_penalty_cents=0),
            ws["am_headers"]))
        ws["oid_a"] = opt_a["id"]
        ws["oid_b"] = opt_b["id"]
        return ws

    def test_positive_penalty_lapse_posts_ledger_entry(self, api):
        """PRD §3.8: "When the option's `missed_option_penalty_cents` is
        positive, the lapse posts a `MISSED_OPTION_PENALTY` ledger entry for
        that amount with the clock date as its `effective_date` and the option
        as `source_option_id`"

        Design: Difficulty/dual_variant_calc/missed_option_penalty_vs_silent_lapse_diverge
        """
        ws = self._setup_two_lapsing_options(api, "P2")
        set_clock("2026-09-11T00:00:01Z")  # both options lapse on this sweep
        opt_a = validate_success(api.get_option(
            ws["pid"], ws["lid"], ws["oid_a"], ws["am_headers"]))
        assert opt_a["status"] == "LAPSED"
        data, _ = validate_paginated(api.list_ledger(ws["pid"], ws["lid"],
                                                     ws["am_headers"]))
        penalty_entries = [
            e for e in data
            if e["entry_kind"] == "MISSED_OPTION_PENALTY"
            and e.get("source_option_id") == ws["oid_a"]
        ]
        assert len(penalty_entries) == 1, "Positive-penalty lapse posts exactly one entry"
        entry = penalty_entries[0]
        assert_ledger_entry(entry)
        assert entry["amount_cents"] == 250000
        assert entry["effective_date"].startswith("2026-09-11"), (
            "The effective_date is the clock date of the lapse sweep"
        )

    def test_zero_penalty_lapse_posts_nothing(self, api):
        """PRD §3.8: "a zero-penalty lapse is silent, with only the status
        transition observable."

        Design: Difficulty/dual_variant_calc/missed_option_penalty_vs_silent_lapse_diverge
        """
        ws = self._setup_two_lapsing_options(api, "P2b")
        set_clock("2026-09-11T00:00:01Z")
        opt_b = validate_success(api.get_option(
            ws["pid"], ws["lid"], ws["oid_b"], ws["am_headers"]))
        assert opt_b["status"] == "LAPSED"
        data, _ = validate_paginated(api.list_ledger(ws["pid"], ws["lid"],
                                                     ws["am_headers"]))
        # Only the positive-penalty option posts; the zero-penalty lapse is silent.
        b_entries = [e for e in data if e.get("source_option_id") == ws["oid_b"]]
        assert b_entries == [], "Zero-penalty lapse must not post any ledger entry"


class TestZeroPenaltyLapseEmptyLedger:
    def test_zero_penalty_lapse_posts_empty_ledger(self, api):
        """PRD §3.8: "a zero-penalty lapse is silent, with only the status
        transition observable."

        Design: Difficulty/boundary_precision_check/zero_penalty_lapse_posts_empty_ledger
        """
        ws = setup_active_lease(name="P12", region="EAST",
                                rentable_square_feet=5000,
                                base_rent_cents_per_rsf_year=4000)
        # missed_option_penalty_cents omitted → defaults to 0.
        opt = get_success_data(api.create_option(
            ws["pid"], ws["lid"],
            create_option_payload(
                option_type="ROFR",
                notice_window_open_date="2026-08-10T00:00:00Z",
                notice_window_close_date="2026-09-10T00:00:00Z",
                target_commencement_date="2027-06-01T00:00:00Z",
                rate_determination="FIXED",
                fixed_rent_cents_per_rsf_year=4000),
            ws["am_headers"]))
        set_clock("2026-09-11T00:00:00Z")
        opt_now = validate_success(api.get_option(
            ws["pid"], ws["lid"], opt["id"], ws["am_headers"]))
        assert opt_now["status"] == "LAPSED"
        data, meta = validate_paginated(api.list_ledger(
            ws["pid"], ws["lid"], ws["am_headers"]))
        assert meta["total_count"] == 0 and data == [], (
            "Zero-penalty lapse: ledger remains empty, not an entry with amount 0"
        )

    def test_zero_penalty_lapse_still_cancels_pending_reminders(self, api):
        """PRD §3.8: "an option still in `AVAILABLE`, `WINDOW_OPEN`, or
        `NOTICE_SENT` — ... — moves to `LAPSED`, stamps `lapsed_at`, and
        cancels its `PENDING` reminders."
        PRD §3.8: "a zero-penalty lapse is silent, with only the status
        transition observable."
        PRD §3.4: "On each advance, every `PENDING` reminder whose
        `scheduled_for` is at or before the clock transitions to `SENT`" — a
        reminder already due fires rather than being canceled; the lapse only
        cancels the ones still PENDING.

        Design: Difficulty/boundary_precision_check/zero_penalty_lapse_posts_empty_ledger
        """
        ws = setup_active_lease(name="P12b", region="EAST",
                                rentable_square_feet=5000,
                                base_rent_cents_per_rsf_year=4000)
        opt = get_success_data(api.create_option(
            ws["pid"], ws["lid"],
            create_option_payload(
                option_type="ROFR",
                notice_window_open_date="2026-08-10T00:00:00Z",
                # Close on a Saturday so the T0 reminder rolls forward to the
                # following Monday 09:00 — past the lapse advance below, hence
                # still PENDING when the lapse lands.
                notice_window_close_date="2026-09-12T00:00:00Z",
                target_commencement_date="2027-06-01T00:00:00Z",
                rate_determination="FIXED",
                fixed_rent_cents_per_rsf_year=4000),
            ws["am_headers"]))
        # Move the clock into the window so the cascade spawns PENDING reminders.
        set_clock("2026-08-15T00:00:00Z")
        data_before, meta_before = validate_paginated(api.list_reminders(
            ws["pid"], ws["lid"], opt["id"], ADMIN))
        assert meta_before["total_count"] == 5
        # Advance past the close (Sat 2026-09-12) to lapse the option. By then
        # T90/T60/T30/T7 (scheduled 06-15, 07-14, 08-13, 09-07) are all due and
        # fire to SENT; T0 rolled to Mon 2026-09-14 09:00, is not yet due, and
        # is the PENDING reminder the lapse cancels.
        set_clock("2026-09-13T00:00:00Z")
        data_after, _ = validate_paginated(api.list_reminders(
            ws["pid"], ws["lid"], opt["id"], ADMIN))
        assert len(data_after) == 5
        expected_by_tier = {
            "T90": "SENT", "T60": "SENT", "T30": "SENT", "T7": "SENT",
            "T0": "CANCELED",
        }
        for r in data_after:
            assert r["status"] == expected_by_tier[r["tier"]], (
                f"tier {r['tier']}: due reminders fire (SENT); the lapse "
                "cancels only still-PENDING reminders"
            )
        opt_now = validate_success(api.get_option(
            ws["pid"], ws["lid"], opt["id"], ws["am_headers"]))
        assert opt_now["status"] == "LAPSED"
        # Zero-penalty lapse is silent: no ledger entry posts.
        _ledger, ledger_meta = validate_paginated(api.list_ledger(
            ws["pid"], ws["lid"], ADMIN))
        assert ledger_meta["total_count"] == 0, (
            "A zero-penalty lapse posts no MISSED_OPTION_PENALTY entry"
        )


class TestWithdrawConservation:
    def test_withdraw_on_zero_fee_zero_penalty_posts_no_ledger_entry(self, api):
        """PRD §3.8: "the option moves to `WITHDRAWN`, its `PENDING` reminders
        are `CANCELED`, any of its notices still in `SENT` or `DELIVERED` become
        `VOID`, and the lease's `version` increments."
        PRD §2.9: "Every financial consequence of the option lifecycle posts to
        the owning lease's ledger as a `LedgerEntry`" — withdraw is not a
        financial consequence.

        Design: Difficulty/compensating_invariant/withdraw_restores_lease_version_delta_symmetric
        """
        ws = setup_option_on_active_lease(
            name="P17", region="WEST",
            option_overrides={
                "option_type": "ROFR",
                "notice_window_open_date": "2026-08-01T00:00:00Z",
                "notice_window_close_date": "2026-12-31T00:00:00Z",
                "target_commencement_date": "2027-06-01T00:00:00Z",
                "rate_determination": "FIXED",
                "fixed_rent_cents_per_rsf_year": 4000,
                "exercise_fee_cents": 0,
                "missed_option_penalty_cents": 0,
            })
        set_clock("2026-09-01T00:00:00Z")
        lease = get_success_data(api.get_lease(ws["pid"], ws["lid"], ws["am_headers"]))
        get_success_data(api.withdraw_option(
            ws["pid"], ws["lid"], ws["oid"],
            {"expected_lease_version": lease["version"]}, ws["am_headers"]))
        opt = validate_success(api.get_option(ws["pid"], ws["lid"], ws["oid"],
                                              ws["am_headers"]))
        assert opt["status"] == "WITHDRAWN"
        data, meta = validate_paginated(api.list_ledger(
            ws["pid"], ws["lid"], ws["am_headers"]))
        assert meta["total_count"] == 0, (
            "create+withdraw with zero fee and zero penalty conserves an empty ledger"
        )

    def test_withdraw_cancels_pending_reminders(self, api):
        """PRD §3.8: "the option moves to `WITHDRAWN`, its `PENDING` reminders
        are `CANCELED`"

        Design: Difficulty/compensating_invariant/withdraw_restores_lease_version_delta_symmetric
        """
        ws = setup_option_on_active_lease(
            name="P17b", region="WEST",
            option_overrides={
                "option_type": "ROFR",
                "notice_window_open_date": "2026-08-01T00:00:00Z",
                "notice_window_close_date": "2026-12-31T00:00:00Z",
                "target_commencement_date": "2027-06-01T00:00:00Z",
                "rate_determination": "FIXED",
                "fixed_rent_cents_per_rsf_year": 4000,
                "exercise_fee_cents": 0,
                "missed_option_penalty_cents": 0,
            })
        set_clock("2026-08-15T00:00:00Z")  # cascade spawns 5 PENDING
        lease = get_success_data(api.get_lease(ws["pid"], ws["lid"], ws["am_headers"]))
        get_success_data(api.withdraw_option(
            ws["pid"], ws["lid"], ws["oid"],
            {"expected_lease_version": lease["version"]}, ws["am_headers"]))
        data, _ = validate_paginated(api.list_reminders(
            ws["pid"], ws["lid"], ws["oid"], ADMIN))
        pending = [r for r in data if r["status"] == "PENDING"]
        assert pending == [], "Withdraw must cancel every PENDING reminder"


class TestHoldoverSettlement:
    def _setup_settled_holdover(self, api, name):
        """Lease enters HOLDOVER, accrues 30 days, settles via HOLDOVER_SETTLEMENT."""
        ws = setup_lease_in_holdover(
            name=name, region="EAST",
            rentable_square_feet=10000,
            base_rent_cents_per_rsf_year=5000,
            holdover_tier1_pct=150, holdover_tier2_pct=200,
            expiration_date="2026-12-31T00:00:00Z",
            holdover_advance_to="2027-01-31T00:00:00Z",
        )
        # daily_base = floor(5000*10000/365) = 136986; tier1_daily = 205479.
        # 30 days held → 30 * 205479 = 6164370.
        amendment = create_amendment(ws, kind="HOLDOVER_SETTLEMENT",
                                     new_expiration_date="2028-12-31T00:00:00Z",
                                     new_base_rent_cents_per_rsf_year=5200)
        propose_amendment(ws, amendment["id"])
        get_success_data(api.agree_amendment(
            ws["pid"], ws["lid"], amendment["id"], ws["lc_headers"]))
        ws["amendment"] = amendment
        return ws

    def test_holdover_settlement_posts_amendment_settlement_entry(self, api):
        """PRD §3.7: "Executing a `HOLDOVER_SETTLEMENT` ... returns the lease
        `HOLDOVER` → `ACTIVE`, clears `holdover_entered_at` to null, posts an
        `AMENDMENT_SETTLEMENT` ledger entry for the final accrued holdover
        delta, and resets `accrued_holdover_rent_cents` to zero."

        Design: Difficulty/compensating_invariant/holdover_enter_and_settle_conserves_accrual_identity
        """
        ws = self._setup_settled_holdover(api, "P18")
        lease_now = get_success_data(api.get_lease(
            ws["pid"], ws["lid"], ws["am_headers"]))
        get_success_data(api.execute_amendment(
            ws["pid"], ws["lid"], ws["amendment"]["id"],
            {"expected_lease_version": lease_now["version"]}, ws["am_headers"]))
        data, _ = validate_paginated(api.list_ledger(
            ws["pid"], ws["lid"], ws["am_headers"]))
        settlement = [e for e in data if e["entry_kind"] == "AMENDMENT_SETTLEMENT"]
        assert len(settlement) == 1, "Exactly one AMENDMENT_SETTLEMENT posts at settlement"
        assert settlement[0]["amount_cents"] == 6164370, (
            "30 days × tier1_daily 205479 = 6164370"
        )

    def test_holdover_settlement_resets_accrual_and_applies_terms(self, api):
        """PRD §3.7: "resets `accrued_holdover_rent_cents` to zero" and
        "applies `new_expiration_date` and `new_base_rent_cents_per_rsf_year`
        to the lease"

        Design: Difficulty/compensating_invariant/holdover_enter_and_settle_conserves_accrual_identity
        """
        ws = self._setup_settled_holdover(api, "P18b")
        lease_now = get_success_data(api.get_lease(
            ws["pid"], ws["lid"], ws["am_headers"]))
        get_success_data(api.execute_amendment(
            ws["pid"], ws["lid"], ws["amendment"]["id"],
            {"expected_lease_version": lease_now["version"]}, ws["am_headers"]))
        lease = validate_success(api.get_lease(ws["pid"], ws["lid"], ws["am_headers"]))
        assert lease["status"] == "ACTIVE", "HOLDOVER → ACTIVE on settlement"
        assert lease["holdover_entered_at"] is None
        assert lease["accrued_holdover_rent_cents"] == 0, (
            "Accrual counter resets to exactly zero"
        )
        assert lease["expiration_date"] == "2028-12-31T00:00:00Z"
        assert lease["base_rent_cents_per_rsf_year"] == 5200
        assert lease["active_amendment_id"] == ws["amendment"]["id"]


class TestLedgerEntryImmutability:
    def test_ledger_entry_immutable_no_version_field(self, api):
        """PRD §2.5: "A `LedgerEntry` and a `ClockEvent` each expose `id` and
        `created_at` only; `updated_at` and `version` are absent from both,
        because neither is ever modified after creation."

        Design: Corner/entities/ledger_entry_immutable_no_version_field
        """
        # Drive an exercise that posts an OPTION_FEE entry.
        ws = setup_option_on_active_lease(
            name="P6", region="WEST", with_bk=True, with_lc=True,
            option_overrides={
                "option_type": "TERMINATION",
                "notice_window_open_date": "2026-08-01T00:00:00Z",
                "notice_window_close_date": "2026-12-31T00:00:00Z",
                "target_commencement_date": "2027-06-30T00:00:00Z",
                "rate_determination": "FIXED",
                "fixed_rent_cents_per_rsf_year": 4000,
                "exercise_fee_cents": 50000,
            },
            expiration_date="2028-12-31T00:00:00Z")
        set_clock("2026-09-01T00:00:00Z")
        lease = get_success_data(api.get_lease(ws["pid"], ws["lid"], ws["am_headers"]))
        notice = get_success_data(api.create_notice(
            ws["pid"], ws["lid"], ws["oid"],
            create_notice_payload(lease["version"], delivery_method="COURIER"),
            ws["am_headers"]))
        get_success_data(api.deliver_notice(
            ws["pid"], ws["lid"], ws["oid"], notice["id"], ws["bk_headers"]))
        get_success_data(api.acknowledge_notice(
            ws["pid"], ws["lid"], ws["oid"], notice["id"], ws["lc_headers"]))
        data, _ = validate_paginated(api.list_ledger(ws["pid"], ws["lid"], ADMIN))
        fees = [e for e in data if e["entry_kind"] == "OPTION_FEE"]
        assert len(fees) == 1
        assert fees[0]["amount_cents"] == 50000
        for entry in data:
            assert_ledger_entry(entry)  # asserts no updated_at and no version
