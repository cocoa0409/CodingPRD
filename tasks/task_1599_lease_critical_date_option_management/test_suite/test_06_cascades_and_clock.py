"""Clock-advance cascades: lease EXPIRING chain, option WINDOW_OPEN chain,
reminder spawn, holdover entry, and contact-deactivation cascade."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_contact,
    assert_reminder,
    create_amendment,
    create_comparable_assessment_payload,
    create_lease,
    create_lease_payload,
    create_notice_payload,
    create_option,
    create_option_payload,
    get_success_data,
    make_am_headers,
    set_clock,
    setup_active_lease,
    setup_notice_delivered,
    setup_notice_sent,
    setup_option_on_active_lease,
    setup_portfolio_with_contacts,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


class TestClockAdvanceCascade:
    def test_lease_expiring_moves_options_window_open(self, api):
        """PRD §3.2: "When the logical clock reaches the day 180 days before a
        lease's `expiration_date` while remaining before that date, the lease
        moves `ACTIVE` → `EXPIRING` automatically, its `version` increments,
        and — as the first cascade hop — each of its options still `AVAILABLE`
        whose notice window contains the clock date opens to `WINDOW_OPEN`"

        Design: Difficulty/transitive_cascade/clock_advance_cascades_lease_to_option_to_reminder
        """
        # Lease expires 2027-01-31 → EXPIRING starts at 2027-01-31 - 180d = 2026-08-04.
        ws = setup_option_on_active_lease(
            name="P7", region="WEST",
            option_overrides={
                "option_type": "RENEWAL",
                "notice_window_open_date": "2026-08-10T00:00:00Z",
                "notice_window_close_date": "2026-11-30T00:00:00Z",
                "target_commencement_date": "2027-02-01T00:00:00Z",
                "extension_years": 3,
                "rate_determination": "FIXED",
                "fixed_rent_cents_per_rsf_year": 4300,
            },
            premises_label="ST-7",
            rentable_square_feet=6000,
            base_rent_cents_per_rsf_year=4000,
            commencement_date="2026-01-01T00:00:00Z",
            expiration_date="2027-01-31T00:00:00Z",
        )
        set_clock("2026-08-15T00:00:00Z")
        lease = validate_success(api.get_lease(ws["pid"], ws["lid"], ADMIN))
        assert lease["status"] == "EXPIRING", (
            "Clock advance at expiration-180d boundary moves lease ACTIVE → EXPIRING"
        )
        opt = validate_success(api.get_option(ws["pid"], ws["lid"], ws["oid"], ADMIN))
        assert opt["status"] == "WINDOW_OPEN", (
            "In-window AVAILABLE options follow the lease hop to WINDOW_OPEN"
        )

    def test_window_open_spawns_five_pending_reminders(self, api):
        """PRD §3.4: "The moment an option enters `WINDOW_OPEN`, the system
        builds its reminder cascade: for every contact of the portfolio whose
        `is_active` is true at that moment, five `PENDING` reminders are created
        — one per `tier`, named `T90`, `T60`, `T30`, `T7`, and `T0`"
        PRD §3.4: "Each reminder's `scheduled_for` begins as the close date
        minus its tier's offset in days, then rolls forward over weekends — a
        Saturday date shifts two days forward and a Sunday date one — and lands
        at 09:00:00 UTC."

        Design: Difficulty/transitive_cascade/clock_advance_cascades_lease_to_option_to_reminder
        """
        # close 2026-11-30 (Monday); T90 raw = 2026-11-30 - 90d = 2026-09-01 (Tuesday, no roll).
        ws = setup_option_on_active_lease(
            name="P7b", region="WEST",
            option_overrides={
                "option_type": "RENEWAL",
                "notice_window_open_date": "2026-08-10T00:00:00Z",
                "notice_window_close_date": "2026-11-30T00:00:00Z",
                "target_commencement_date": "2027-02-01T00:00:00Z",
                "extension_years": 3,
                "rate_determination": "FIXED",
                "fixed_rent_cents_per_rsf_year": 4300,
            },
            premises_label="ST-7",
            rentable_square_feet=6000,
            base_rent_cents_per_rsf_year=4000,
            commencement_date="2026-01-01T00:00:00Z",
            expiration_date="2027-01-31T00:00:00Z",
        )
        set_clock("2026-08-15T00:00:00Z")
        data, meta = validate_paginated(api.list_reminders(
            ws["pid"], ws["lid"], ws["oid"], ADMIN))
        assert meta["total_count"] == 5, (
            "One active contact on the portfolio → exactly five PENDING reminders"
        )
        tiers = {r["tier"] for r in data}
        assert tiers == {"T90", "T60", "T30", "T7", "T0"}
        for r in data:
            assert_reminder(r)
            assert r["status"] == "PENDING"
            assert r["contact_id"] == ws["am"]["id"]
        t90 = next(r for r in data if r["tier"] == "T90")
        # 2026-11-30 - 90 days = 2026-09-01 (a Tuesday, no weekend roll); 09:00:00Z.
        assert t90["scheduled_for"] == "2026-09-01T09:00:00Z"


class TestReminderSchedule:
    def test_reminder_fires_only_at_scheduled_time(self, api):
        """PRD §3.4: "On each advance, every `PENDING` reminder whose
        `scheduled_for` is at or before the clock transitions to `SENT` with
        `sent_at` stamped, provided its option is not `IN_ARBITRATION` and its
        recipient contact remains active."
        PRD §3.4: "rolls forward over weekends — a Saturday date shifts two days
        forward and a Sunday date one"

        Design: Corner/state_machines/reminder_fires_only_at_scheduled_time
        """
        # close 2027-06-30; T60 raw = 2027-05-01 (Saturday) → rolls to Monday 2027-05-03.
        ws = setup_option_on_active_lease(
            name="SM6", region="WEST",
            option_overrides={
                "option_type": "RENEWAL",
                "notice_window_open_date": "2026-08-01T00:00:00Z",
                "notice_window_close_date": "2027-06-30T00:00:00Z",
                "target_commencement_date": "2028-01-01T00:00:00Z",
                "extension_years": 5,
                "rate_determination": "FIXED",
                "fixed_rent_cents_per_rsf_year": 4200,
            },
            commencement_date="2026-01-01T00:00:00Z",
            expiration_date="2027-12-31T00:00:00Z",
        )
        set_clock("2026-08-15T00:00:00Z")  # option enters WINDOW_OPEN; reminders PENDING
        # Before T90 schedule (2027-04-01T09:00:00Z) no reminder has fired.
        set_clock("2027-03-31T00:00:00Z")
        data, _ = validate_paginated(api.list_reminders(
            ws["pid"], ws["lid"], ws["oid"], ADMIN))
        for r in data:
            assert r["status"] == "PENDING", (
                f"Before scheduled_for, tier {r['tier']} must remain PENDING"
            )
        # Advance past T90 (2027-04-01) and T60 (rolled to 2027-05-03).
        set_clock("2027-05-03T09:00:01Z")
        data, _ = validate_paginated(api.list_reminders(
            ws["pid"], ws["lid"], ws["oid"], ADMIN))
        by_tier = {r["tier"]: r for r in data}
        assert by_tier["T90"]["status"] == "SENT"
        assert by_tier["T90"]["scheduled_for"] == "2027-04-01T09:00:00Z"
        assert by_tier["T60"]["status"] == "SENT"
        # T60 raw = 2027-06-30 - 60d = 2027-05-01 (Saturday) → +2d → Monday 2027-05-03.
        assert by_tier["T60"]["scheduled_for"] == "2027-05-03T09:00:00Z", (
            "Saturday 2027-05-01 rolls forward two days to Monday 2027-05-03"
        )
        # T30 raw = 2027-05-31 (Monday, no roll); not yet reached.
        assert by_tier["T30"]["status"] == "PENDING"
        assert by_tier["T7"]["status"] == "PENDING"
        assert by_tier["T0"]["status"] == "PENDING"


class TestContactDeactivationCascade:
    def test_contact_deactivation_cancels_pending_reminders(self, api):
        """PRD §3.1: "flipping `is_active` from true to false cascades
        immediately, canceling every still-`PENDING` reminder addressed to that
        contact."

        Design: Corner/endpoints/contact_deactivation_cancels_pending_reminders
        """
        ws = setup_option_on_active_lease(
            name="E2", region="WEST", with_bk=True,
            option_overrides={
                "option_type": "RENEWAL",
                "notice_window_open_date": "2026-08-01T00:00:00Z",
                "notice_window_close_date": "2027-06-30T00:00:00Z",
                "target_commencement_date": "2028-01-01T00:00:00Z",
                "extension_years": 5,
                "rate_determination": "FIXED",
                "fixed_rent_cents_per_rsf_year": 4200,
            })
        set_clock("2026-08-15T00:00:00Z")  # spawns 5 PENDING for AM + 5 for BK
        # Deactivate the broker.
        get_success_data(api.patch_contact(
            ws["pid"], ws["bk"]["id"], {"is_active": False}, ws["am_headers"]))
        data, _ = validate_paginated(api.list_reminders(
            ws["pid"], ws["lid"], ws["oid"], ADMIN, params={"limit": 100}))
        bk_reminders = [r for r in data if r["contact_id"] == ws["bk"]["id"]]
        am_reminders = [r for r in data if r["contact_id"] == ws["am"]["id"]]
        assert len(bk_reminders) == 5
        for r in bk_reminders:
            assert r["status"] == "CANCELED", (
                "Deactivated contact's PENDING reminders flip to CANCELED"
            )
        assert len(am_reminders) == 5
        for r in am_reminders:
            assert r["status"] == "PENDING", (
                "Other contacts' reminders are unaffected"
            )

    def test_cascading_contact_deactivation_then_option_window_open(self, api):
        """PRD §3.4: "for every contact of the portfolio whose `is_active` is
        true at that moment, five `PENDING` reminders are created"

        Design: Corner/cross_cutting_complexity_layers/cascading_contact_deactivation_then_option_window_open
        """
        ws = setup_portfolio_with_contacts(name="CC2", region="EAST", with_bk=True)
        # Deactivate BK *before* the option's window opens.
        get_success_data(api.patch_contact(
            ws["pid"], ws["bk"]["id"], {"is_active": False}, ws["am_headers"]))
        lease = get_success_data(api.create_lease(
            ws["pid"],
            create_lease_payload(
                premises_label="CC2",
                rentable_square_feet=5000,
                base_rent_cents_per_rsf_year=4000,
                commencement_date="2026-01-01T00:00:00Z",
                expiration_date="2027-12-31T00:00:00Z",
                holdover_tier1_pct=150,
                holdover_tier2_pct=200,
            ),
            ws["am_headers"],
        ))
        lease = get_success_data(api.activate_lease(
            ws["pid"], lease["id"], {}, ws["am_headers"]))
        option = get_success_data(api.create_option(
            ws["pid"], lease["id"],
            create_option_payload(
                option_type="RENEWAL",
                notice_window_open_date="2026-08-10T00:00:00Z",
                notice_window_close_date="2026-12-31T00:00:00Z",
                target_commencement_date="2028-01-01T00:00:00Z",
                extension_years=5,
                rate_determination="FIXED",
                fixed_rent_cents_per_rsf_year=4200,
            ),
            ws["am_headers"],
        ))
        set_clock("2026-08-15T00:00:00Z")  # window opens
        data, meta = validate_paginated(api.list_reminders(
            ws["pid"], lease["id"], option["id"], ADMIN))
        assert meta["total_count"] == 5, (
            "Only the still-active contact spawns reminders at cascade time"
        )
        for r in data:
            assert r["contact_id"] == ws["am"]["id"], (
                "Deactivated-before-cascade contact receives no reminders"
            )


class TestHoldoverEntry:
    def test_lease_enters_holdover_after_expiration(self, api):
        """PRD §3.8: "When the clock passes a lease's `expiration_date` with no
        renewal in place — no executed `RENEWAL_TERM` or `EXPANSION_TERM`
        amendment and no exercised `RENEWAL` option — and no timely vacatur on
        record, the lease rolls from `ACTIVE` or `EXPIRING` into `HOLDOVER`.
        Entry is backdated: `holdover_entered_at` is set to the day after
        `expiration_date` at 00:00:00 UTC"

        Design: Difficulty/combinatorial_formula/holdover_accrual_nested_rounding_order
        """
        ws = setup_active_lease(
            name="P3", region="WEST",
            premises_label="WH-3",
            rentable_square_feet=10000,
            base_rent_cents_per_rsf_year=5000,
            commencement_date="2026-01-01T00:00:00Z",
            expiration_date="2026-12-31T00:00:00Z",
            holdover_tier1_pct=150,
            holdover_tier2_pct=200,
        )
        set_clock("2027-01-01T00:00:00Z")  # past expiration
        lease = validate_success(api.get_lease(ws["pid"], ws["lid"], ADMIN))
        assert lease["status"] == "HOLDOVER"
        assert lease["holdover_entered_at"] == "2027-01-01T00:00:00Z", (
            "Holdover entry is backdated to expiration_date + 1 day at 00:00:00Z"
        )

    def test_holdover_accrual_nested_rounding_order(self, api):
        """PRD §3.8: "The daily base is the lease's annual rent —
        `base_rent_cents_per_rsf_year` multiplied by `rentable_square_feet` —
        divided by 365 and rounded down to a whole cent. The first-tier daily
        charge is that daily base scaled by `holdover_tier1_pct` percent and
        rounded half up to a whole cent; the second-tier daily charge applies
        `holdover_tier2_pct` the same way. ... `accrued_holdover_rent_cents` is
        then the first-tier daily charge times the number of days held up to
        `holdover_tier1_days`, plus the second-tier daily charge times any days
        held beyond that count. The per-day tier amounts are rounded first,
        then multiplied by their day counts, then summed"

        Pinned numbers: RSF 10000, base 5000 → daily_base = floor(5000*10000/365)
        = 136986. tier1_daily = round_half_up(136986 * 150/100) = 205479.
        tier2_daily = round_half_up(136986 * 200/100) = 273972. 100 days held
        → 90*205479 + 10*273972 = 21232830.

        Design: Difficulty/combinatorial_formula/holdover_accrual_nested_rounding_order
        """
        ws = setup_active_lease(
            name="P3b", region="WEST",
            premises_label="WH-3",
            rentable_square_feet=10000,
            base_rent_cents_per_rsf_year=5000,
            commencement_date="2026-01-01T00:00:00Z",
            expiration_date="2026-12-31T00:00:00Z",
            holdover_tier1_pct=150,
            holdover_tier2_pct=200,
        )
        set_clock("2027-01-01T00:00:00Z")  # enters HOLDOVER at 2027-01-01
        set_clock("2027-04-11T00:00:00Z")  # 100 days held (2027-01-01 excl → 2027-04-11 incl)
        lease = validate_success(api.get_lease(ws["pid"], ws["lid"], ADMIN))
        assert lease["status"] == "HOLDOVER"
        assert lease["holdover_entered_at"] == "2027-01-01T00:00:00Z"
        assert lease["accrued_holdover_rent_cents"] == 21232830, (
            "per-day tier rounding, then multiply by days, then sum (pinned order)"
        )
