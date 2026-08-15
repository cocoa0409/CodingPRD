"""Stipend ledger: daily cap waterfall order, void compensation, monthly
subsidy summary, call-stipend tiers, double-void lockdown (PRD §3.4, §3.6,
§3.8)."""
from test_helpers import (
    ADMIN,
    BILLING,
    SCHED,
    ApiErrorId,
    assert_stipend_summary,
    create_call_assignment_payload,
    create_case,
    create_crna,
    create_fee_schedule,
    create_published_roster,
    create_site,
    get_success_data,
    list_stipend_entries,
    propose_and_confirm,
    run_case_clock,
    set_clock,
    setup_stipend_site,
    validate_error,
    api_client,
)


def _standby_then_late_stay(api, standby_full, late_rate, day_end=1020):
    """Case X cancelled with notice 30 (STANDBY full tier, created first);
    case Y run to 20:00 (LATE_STAY (1200-day_end) x rate, created second).
    Returns (provider, roster, entries_by_type)."""
    site, agreement, roster = setup_stipend_site(
        agreement_kwargs={"standby_full_cents": standby_full,
                          "standby_partial_cents": 15000,
                          "late_stay_rate_cents_per_minute": late_rate,
                          "call_stipend_cents": 12000},
        roster_kwargs={"required_primary_slots": 2,
                       "scheduled_day_end_minute": day_end})
    create_fee_schedule("P100", 5)
    provider = create_crna("Crna One")
    case_x = create_case(roster["id"], scheduled_start_minute=600,
                         scheduled_end_minute=660)
    propose_and_confirm(case_x["id"], provider["id"], "CRNA")
    case_y = create_case(roster["id"], scheduled_start_minute=700,
                         scheduled_end_minute=800)
    propose_and_confirm(case_y["id"], provider["id"], "CRNA")
    # Cancel X at 09:30 (minute 570): notice 30 < 120 -> full standby tier.
    set_clock("2026-08-10T09:30:00Z")
    get_success_data(api.cancel_case(
        case_x["id"], {"cancellation_reason": "SURGEON_UNAVAILABLE"}, SCHED))
    # Run case Y: start 11:40, complete 20:00 (actual end 1200).
    run_case_clock(case_y["id"], "2026-08-10T11:40:00Z", "2026-08-10T20:00:00Z")
    get_success_data(api.complete_case(case_y["id"], SCHED))
    standby = list_stipend_entries({"provider_id": provider["id"],
                                    "entry_type": "STANDBY"})
    late = list_stipend_entries({"provider_id": provider["id"],
                                 "entry_type": "LATE_STAY"})
    assert len(standby) == 1 and len(late) == 1
    return provider, roster, standby[0], late[0]


class TestDailyCapWaterfallPinnedOrder:
    def test_earlier_created_standby_consumes_cap_first(self, api):
        """PRD §3.8: "The bucket is walked in `created_at` ascending order ...
        and each entry's `applied_amount_cents` is the smaller of its own
        `amount_cents` and the remaining capacity under a five-hundred-dollar
        (50,000-cent) daily ceiling after the entries before it."
        PRD §3.8: "a standby entry accrued at cancellation precedes a late-stay
        entry accrued at completion later that day."

        Design: Difficulty/combinatorial_formula/daily_cap_waterfall_circular_dependency_pinned_order
        """
        provider, roster, standby, late = _standby_then_late_stay(
            api, standby_full=40000, late_rate=200)
        assert standby["amount_cents"] == 40000
        assert standby["applied_amount_cents"] == 40000, \
            "standby created first takes min(40000, 50000 - 0)"
        assert late["amount_cents"] == 36000  # (1200 - 1020) x 200
        assert late["applied_amount_cents"] == 10000, (
            f"late-stay truncates to min(36000, 50000 - 40000) = 10000, got "
            f"{late['applied_amount_cents']}")
        assert standby["applied_amount_cents"] + late["applied_amount_cents"] == 50000

    def test_cap_binds_exactly_at_daily_ceiling(self, api):
        """PRD §3.8: "The bucket contains that provider's entries for the date
        that are not `VOIDED` and whose type is `STANDBY` or `LATE_STAY`;
        `CALL` entries are exempt and always apply in full".
        PRD §3.8: "the remaining capacity under a five-hundred-dollar
        (50,000-cent) daily ceiling".

        Design: Difficulty/combinatorial_formula/daily_cap_waterfall_circular_dependency_pinned_order
        """
        provider, roster, standby, late = _standby_then_late_stay(
            api, standby_full=40000, late_rate=200)
        total_applied = standby["applied_amount_cents"] + late["applied_amount_cents"]
        total_raw = standby["amount_cents"] + late["amount_cents"]
        assert total_applied == min(total_raw, 50000), (
            f"daily invariant min(sum, 50000) broken: applied {total_applied}, "
            f"raw {total_raw}")


class TestStipendAccrueVoidInvariant:
    def test_void_restores_remaining_entries_applied_amounts(self, api):
        """PRD §3.8: "A `GroupAdministrator` may void an `ACCRUED` entry
        (voiding anything else is `ERR_ENTRY_NOT_VOIDABLE`), moving it to
        `VOIDED`, bumping its `version`, and re-running the waterfall so the
        remaining entries re-apply in order."

        Design: Difficulty/compensating_invariant/stipend_accrue_void_conserves_daily_cap_budget
        """
        provider, roster, standby, late = _standby_then_late_stay(
            api, standby_full=45000, late_rate=300)
        # Saturated: 45000 / 5000.
        assert standby["applied_amount_cents"] == 45000
        assert late["amount_cents"] == 54000  # (1200 - 1020) x 300
        assert late["applied_amount_cents"] == 5000
        voided = get_success_data(api.void_stipend_entry(standby["id"], ADMIN))
        assert voided["status"] == "VOIDED"
        late_after = get_success_data(api.get_stipend_entry(late["id"], SCHED))
        assert late_after["applied_amount_cents"] == 50000, (
            f"after the void the waterfall re-runs: min(54000, 50000) = "
            f"50000, got {late_after['applied_amount_cents']}")

    def test_daily_cap_invariant_holds_before_and_after_void(self, api):
        """PRD §3.8: "each entry's `applied_amount_cents` is the smaller of
        its own `amount_cents` and the remaining capacity under a
        five-hundred-dollar (50,000-cent) daily ceiling after the entries
        before it. The walk always restarts from the beginning whenever any
        entry in the bucket is created or voided".

        Design: Difficulty/compensating_invariant/stipend_accrue_void_conserves_daily_cap_budget
        """
        provider, roster, standby, late = _standby_then_late_stay(
            api, standby_full=45000, late_rate=300)

        def bucket_applied_sum():
            entries = list_stipend_entries({"provider_id": provider["id"]})
            live = [e for e in entries
                    if e["status"] != "VOIDED"
                    and e["entry_type"] in ("STANDBY", "LATE_STAY")]
            raw = sum(e["amount_cents"] for e in live)
            applied = sum(e["applied_amount_cents"] for e in live)
            return raw, applied

        raw0, applied0 = bucket_applied_sum()
        assert applied0 == min(raw0, 50000)
        get_success_data(api.void_stipend_entry(standby["id"], ADMIN))
        raw1, applied1 = bucket_applied_sum()
        assert applied1 == min(raw1, 50000), \
            "the accrue->void round trip must not drift from the daily cap invariant"
        assert applied1 == 50000


class TestMonthlySubsidySummary:
    def test_daily_cap_bites_first_then_monthly(self, api):
        """PRD §3.8: "entries are walked in order of `occurred_date` ascending,
        then `created_at` ascending, and each entry contributes the smaller of
        its already-daily-capped `applied_amount_cents` and the remaining
        capacity under a four-thousand-dollar (400,000-cent) monthly ceiling."
        PRD §3.8: "The daily cap always bites first and the monthly cap second
        — the monthly walk consumes daily-capped applied amounts, never raw
        amounts."

        Design: Corner/calculations/monthly_subsidy_summary_applies_daily_then_monthly_caps
        """
        site = create_site()
        get_success_data(api.create_stipend_agreement(
            {"site_id": site["id"], "effective_from": "2026-08-10",
             "effective_to": "2026-08-14", "call_stipend_cents": 100000,
             "late_stay_rate_cents_per_minute": 10, "standby_full_cents": 5000,
             "standby_partial_cents": 2500}, ADMIN))
        provider = create_crna("Crna One")
        # Five call nights 08-10 .. 08-14, each swept to completion.
        for day in range(10, 15):
            date = f"2026-08-{day}"
            roster = create_published_roster(site["id"], service_date=date,
                                             required_primary_slots=0,
                                             scheduled_day_end_minute=1020)
            get_success_data(api.create_call_assignment(
                create_call_assignment_payload(roster_id=roster["id"],
                                               provider_id=provider["id"],
                                               window_start_minute=600,
                                               window_end_minute=1200), SCHED))
            set_clock(f"{date}T20:30:00Z")
        summary = get_success_data(api.get_stipend_summary(
            BILLING, params={"provider_id": provider["id"], "month": "2026-08"}))
        assert_stipend_summary(summary)
        assert summary["gross_cents"] == 500000
        assert summary["entry_count"] == 5
        # CALL entries are daily-cap-exempt (applied == amount each day); the
        # monthly walk caps the fifth night to 0.
        assert summary["applied_cents"] == 400000
        assert summary["capped_cents"] == 100000


class TestCallStipendSweepAndReleaseTiers:
    def _call_fixture(self, api, providers, window=(600, 1200),
                      roster_kwargs=None):
        site, agreement, roster = setup_stipend_site(
            agreement_kwargs={"call_stipend_cents": 12000},
            roster_kwargs=roster_kwargs or {"required_primary_slots": 0,
                                            "scheduled_day_end_minute": 1020})
        calls = {}
        for name, provider in providers.items():
            calls[name] = get_success_data(api.create_call_assignment(
                create_call_assignment_payload(roster_id=roster["id"],
                                               provider_id=provider["id"],
                                               window_start_minute=window[0],
                                               window_end_minute=window[1]), SCHED))
        return site, agreement, roster, calls

    def test_clock_sweep_auto_completes_with_full_stipend(self, api):
        """PRD §3.4: "when the logical clock is set strictly past a
        `SCHEDULED` window's end (past the service date's `window_end_minute`),
        the sweep transitions the assignment `SCHEDULED → COMPLETED`, bumps its
        `version`, and — when a stipend agreement covers the roster's site and
        service date — accrues a `CALL` ledger entry for the full
        `call_stipend_cents`, with the applied amount equal to the raw amount
        because call pay is exempt from the daily cap (§3.8)."

        Design: Corner/state_machines/call_assignment_auto_completes_on_clock_sweep_with_full_stipend
        """
        provider = create_crna("Crna One")
        site, agreement, roster, calls = self._call_fixture(
            api, {"p": provider}, window=(1020, 1200))
        call_id = calls["p"]["id"]
        set_clock("2026-08-10T20:30:00Z")
        swept = get_success_data(api.get_call_assignment(call_id, SCHED))
        assert swept["status"] == "COMPLETED"
        entries = list_stipend_entries({"provider_id": provider["id"],
                                        "entry_type": "CALL"})
        assert len(entries) == 1
        assert entries[0]["amount_cents"] == 12000
        assert entries[0]["applied_amount_cents"] == 12000, \
            "CALL entries are exempt from the daily cap: applied == amount"
        assert entries[0]["occurred_date"] == "2026-08-10"

    def test_release_tiers_full_half_none(self, api):
        """PRD §3.4: "Serving at least half the window earns the full
        `call_stipend_cents`; serving at least one quarter but less than half
        earns half the stipend, rounded half-up to whole cents; serving less
        than a quarter earns nothing and no ledger entry is created."

        Design: Corner/state_machines/call_release_tier_boundaries_half_and_quarter
        """
        p1, p2, p3 = (create_crna("Crna One"), create_crna("Crna Two"),
                      create_crna("Crna Three"))
        site, agreement, roster, calls = self._call_fixture(
            api, {"p1": p1, "p2": p2, "p3": p3}, window=(600, 1200))
        # Window length 600. Release p3 at 11:40 (700): served 100 (< quarter).
        set_clock("2026-08-10T11:40:00Z")
        r3 = get_success_data(api.release_call_assignment(calls["p3"]["id"], SCHED))
        # Release p2 at 12:30 (750): served 150, exactly quarter -> half.
        set_clock("2026-08-10T12:30:00Z")
        r2 = get_success_data(api.release_call_assignment(calls["p2"]["id"], SCHED))
        # Release p1 at 15:00 (900): served 300, exactly half -> full.
        set_clock("2026-08-10T15:00:00Z")
        r1 = get_success_data(api.release_call_assignment(calls["p1"]["id"], SCHED))
        assert (r1["released_at_minute"], r2["released_at_minute"],
                r3["released_at_minute"]) == (900, 750, 700)
        for r in (r1, r2, r3):
            assert r["status"] == "RELEASED"
        e1 = list_stipend_entries({"provider_id": p1["id"], "entry_type": "CALL"})
        e2 = list_stipend_entries({"provider_id": p2["id"], "entry_type": "CALL"})
        e3 = list_stipend_entries({"provider_id": p3["id"]})
        assert len(e1) == 1 and e1[0]["amount_cents"] == 12000
        assert len(e2) == 1 and e2[0]["amount_cents"] == 6000, \
            "half of 12000 rounded half-up is 6000"
        assert len(e3) == 0, "serving less than a quarter earns no entry"

    def test_release_at_window_start_rejected(self, api):
        """PRD §3.4: "the clock minute falling strictly inside the window — at
        or before the start, or at or after the end, the request is rejected
        with `ERR_CALL_NOT_RELEASABLE`, and natural completion must be left to
        the clock sweep."

        Design: Corner/state_machines/call_release_at_window_start_rejected
        """
        provider = create_crna("Crna One")
        site, agreement, roster, calls = self._call_fixture(
            api, {"p": provider}, window=(600, 1200))
        set_clock("2026-08-10T10:00:00Z")  # minute 600 == window_start
        resp = api.release_call_assignment(calls["p"]["id"], SCHED)
        validate_error(resp, ApiErrorId.ERR_CALL_NOT_RELEASABLE)
        after = get_success_data(api.get_call_assignment(calls["p"]["id"], SCHED))
        assert after["status"] == "SCHEDULED"


class TestStipendEntryVoidTwice:
    def test_second_void_rejected(self, api):
        """PRD §3.8: "A `GroupAdministrator` may void an `ACCRUED` entry
        (voiding anything else is `ERR_ENTRY_NOT_VOIDABLE`), moving it to
        `VOIDED`".

        Design: Corner/state_machines/stipend_entry_void_twice_rejected
        """
        site, agreement, roster = setup_stipend_site(
            agreement_kwargs={"standby_full_cents": 30000},
            roster_kwargs={"required_primary_slots": 1})
        create_fee_schedule("P100", 5)
        provider = create_crna("Crna One")
        case = create_case(roster["id"], scheduled_start_minute=600,
                           scheduled_end_minute=660)
        propose_and_confirm(case["id"], provider["id"], "CRNA")
        set_clock("2026-08-10T09:30:00Z")
        get_success_data(api.cancel_case(
            case["id"], {"cancellation_reason": "SURGEON_UNAVAILABLE"}, SCHED))
        entry = list_stipend_entries({"provider_id": provider["id"],
                                      "entry_type": "STANDBY"})[0]
        first = get_success_data(api.void_stipend_entry(entry["id"], ADMIN))
        assert first["status"] == "VOIDED"
        resp = api.void_stipend_entry(entry["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_ENTRY_NOT_VOIDABLE)
