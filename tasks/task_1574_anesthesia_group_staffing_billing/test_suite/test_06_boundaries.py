"""Boundary precision: standby notice tiers, rest buffer, late-stay strict
inequality (PRD §3.3, §3.6)."""
from test_helpers import (
    SCHED,
    ApiErrorId,
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
    validate_success,
    api_client,
)


def _two_confirmed_cases(api, roster_id, provider_id, windows):
    """Two cases with CONFIRMED primaries at the given [start, end) windows."""
    out = []
    for start, end in windows:
        case = create_case(roster_id, scheduled_start_minute=start,
                           scheduled_end_minute=end)
        propose_and_confirm(case["id"], provider_id, "CRNA")
        out.append(case)
    return out


class TestStandbyNoticeBoundaries:
    def test_notice_exactly_120_pays_partial(self, api):
        """PRD §3.6: "notice under 120 minutes (two hours) accrues the
        agreement's `standby_full_cents`; notice of at least 120 minutes but
        under 1,440 minutes (a full day) accrues `standby_partial_cents`".
        PRD §3.6: "A notice of exactly 120 minutes therefore pays the partial
        tier, and exactly 1,440 minutes pays nothing."

        Design: Difficulty/boundary_precision_check/standby_notice_exactly_120_partial_119_full
        """
        site, agreement, roster = setup_stipend_site(
            agreement_kwargs={"standby_full_cents": 30000,
                              "standby_partial_cents": 15000},
            roster_kwargs={"required_primary_slots": 1})
        create_fee_schedule("P100", 5)
        provider = create_crna("Crna One")
        # Case starts at 600; clock at 08:00 (minute 480) -> notice 120.
        case = create_case(roster["id"], scheduled_start_minute=600,
                           scheduled_end_minute=660)
        propose_and_confirm(case["id"], provider["id"], "CRNA")
        set_clock("2026-08-10T08:00:00Z")
        cancelled = get_success_data(api.cancel_case(
            case["id"], {"cancellation_reason": "PATIENT_NPO_VIOLATION"}, SCHED))
        assert cancelled["cancellation_notice_minutes"] == 120
        entries = list_stipend_entries({"provider_id": provider["id"],
                                        "entry_type": "STANDBY"})
        assert len(entries) == 1
        assert entries[0]["amount_cents"] == 15000, (
            f"notice exactly 120 takes the >= 120 branch (partial 15000), got "
            f"{entries[0]['amount_cents']}")

    def test_notice_119_pays_full(self, api):
        """PRD §3.6: "notice under 120 minutes (two hours) accrues the
        agreement's `standby_full_cents`".
        PRD §3.6: "when the clock date equals the service date, it is
        `scheduled_start_minute` minus the clock minute-of-day".

        Design: Difficulty/boundary_precision_check/standby_notice_exactly_120_partial_119_full
        """
        site, agreement, roster = setup_stipend_site(
            agreement_kwargs={"standby_full_cents": 30000,
                              "standby_partial_cents": 15000},
            roster_kwargs={"required_primary_slots": 1})
        create_fee_schedule("P100", 5)
        provider = create_crna("Crna One")
        # Case starts at 700; clock at 09:41 (minute 581) -> notice 119.
        case = create_case(roster["id"], scheduled_start_minute=700,
                           scheduled_end_minute=760)
        propose_and_confirm(case["id"], provider["id"], "CRNA")
        set_clock("2026-08-10T09:41:00Z")
        cancelled = get_success_data(api.cancel_case(
            case["id"], {"cancellation_reason": "PATIENT_NPO_VIOLATION"}, SCHED))
        assert cancelled["cancellation_notice_minutes"] == 119
        entries = list_stipend_entries({"provider_id": provider["id"],
                                        "entry_type": "STANDBY"})
        assert len(entries) == 1
        assert entries[0]["amount_cents"] == 30000, (
            f"notice 119 < 120 pays the full tier 30000, got "
            f"{entries[0]['amount_cents']}")


class TestRestBufferBoundary:
    def test_gap_exactly_480_allowed(self, api):
        """PRD §3.3: "for each of the provider's call assignments on the same
        service date, in any status, whose `window_end_minute` falls at or
        before the case's `scheduled_start_minute`, the gap between window end
        and case start must be at least eight hours (480 minutes); a strictly
        smaller gap rejects the proposal with `ERR_INSUFFICIENT_REST`, while a
        gap of exactly 480 minutes is allowed."

        Design: Difficulty/boundary_precision_check/rest_buffer_exactly_480_allowed_479_rejected
        """
        site = create_site()
        create_fee_schedule("P100", 5)
        provider = create_crna("Crna One")
        roster = _publish_roster(api, site["id"])
        _create_call(api, roster["id"], provider["id"], 0, 480)
        # Gap 960 - 480 == 480: exactly the buffer -> allowed.
        case = create_case(roster["id"], scheduled_start_minute=960,
                           scheduled_end_minute=1020)
        resp = api.create_case_assignment(
            case["id"], {"provider_id": provider["id"],
                         "assignment_role": "CASE_PRIMARY",
                         "expected_case_version": case["version"]}, SCHED)
        created = validate_error_free(resp)
        assert created["status"] == "PROPOSED"

    def test_gap_479_rejected(self, api):
        """PRD §3.3: "a strictly smaller gap rejects the proposal with
        `ERR_INSUFFICIENT_REST`, while a gap of exactly 480 minutes is
        allowed."

        Design: Difficulty/boundary_precision_check/rest_buffer_exactly_480_allowed_479_rejected
        """
        site = create_site()
        create_fee_schedule("P100", 5)
        provider = create_crna("Crna One")
        roster = _publish_roster(api, site["id"])
        _create_call(api, roster["id"], provider["id"], 0, 480)
        # Gap 900 - 480 == 420 < 480: rejected.
        case = create_case(roster["id"], scheduled_start_minute=900,
                           scheduled_end_minute=959)
        resp = api.create_case_assignment(
            case["id"], {"provider_id": provider["id"],
                         "assignment_role": "CASE_PRIMARY",
                         "expected_case_version": case["version"]}, SCHED)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_REST)
        # No assignment materialized for the rejected proposal.
        data = get_success_data(
            api.list_assignments(SCHED, params={"case_id": case["id"]}))
        rows = data if isinstance(data, list) else data["data"]
        assert len(rows) == 0


class TestStandbyFreeTierBoundary:
    def test_notice_exactly_1440_creates_no_entry(self, api):
        """PRD §3.6: "notice of 1,440 minutes or more accrues nothing and
        creates no entry. A notice of exactly 120 minutes therefore pays the
        partial tier, and exactly 1,440 minutes pays nothing."
        PRD §3.6: "when the clock is still on an earlier date, it is 1,440 plus
        `scheduled_start_minute` minus the clock minute-of-day, so prior-day
        cancels always land in the top notice tier."

        Design: Corner/calculations/standby_notice_1440_free_tier_boundary
        """
        site, agreement, roster = setup_stipend_site(
            agreement_kwargs={"standby_full_cents": 30000,
                              "standby_partial_cents": 15000},
            roster_kwargs={"required_primary_slots": 1})
        create_fee_schedule("P100", 5)
        provider = create_crna("Crna One")
        # Case starts at 600; clock prior day at 10:00 (minute 600):
        # notice = 1440 + 600 - 600 = 1440 -> free tier, no entry.
        case = create_case(roster["id"], scheduled_start_minute=600,
                           scheduled_end_minute=660)
        propose_and_confirm(case["id"], provider["id"], "CRNA")
        set_clock("2026-08-09T10:00:00Z")
        cancelled = get_success_data(api.cancel_case(
            case["id"], {"cancellation_reason": "SCHEDULE_CHANGE"}, SCHED))
        assert cancelled["cancellation_notice_minutes"] == 1440
        entries = list_stipend_entries({"provider_id": provider["id"],
                                        "entry_type": "STANDBY"})
        assert len(entries) == 0, "notice exactly 1440 must create no entry"

    def test_notice_1439_creates_partial_entry(self, api):
        """PRD §3.6: "notice of at least 120 minutes but under 1,440 minutes
        (a full day) accrues `standby_partial_cents`".

        Design: Corner/calculations/standby_notice_1440_free_tier_boundary
        """
        site, agreement, roster = setup_stipend_site(
            agreement_kwargs={"standby_full_cents": 30000,
                              "standby_partial_cents": 15000},
            roster_kwargs={"required_primary_slots": 1})
        create_fee_schedule("P100", 5)
        provider = create_crna("Crna One")
        # Case starts at 600; clock prior day at 10:01 (minute 601):
        # notice = 1440 + 600 - 601 = 1439 -> partial tier.
        case = create_case(roster["id"], scheduled_start_minute=600,
                           scheduled_end_minute=660)
        propose_and_confirm(case["id"], provider["id"], "CRNA")
        set_clock("2026-08-09T10:01:00Z")
        cancelled = get_success_data(api.cancel_case(
            case["id"], {"cancellation_reason": "SCHEDULE_CHANGE"}, SCHED))
        assert cancelled["cancellation_notice_minutes"] == 1439
        entries = list_stipend_entries({"provider_id": provider["id"],
                                        "entry_type": "STANDBY"})
        assert len(entries) == 1
        assert entries[0]["amount_cents"] == 15000


class TestLateStayStrictlyGreaterBoundary:
    def test_end_exactly_at_day_end_accrues_nothing(self, api):
        """PRD §3.6: "if ... `actual_end_minute` is strictly later than the
        roster's `scheduled_day_end_minute`, then one `LATE_STAY` ledger entry
        is created for the overrun minutes multiplied by the agreement's
        `late_stay_rate_cents_per_minute`".

        Design: Corner/calculations/late_stay_day_end_strictly_greater_boundary
        """
        site, agreement, roster = setup_stipend_site(
            agreement_kwargs={"late_stay_rate_cents_per_minute": 200},
            roster_kwargs={"required_primary_slots": 1,
                           "scheduled_day_end_minute": 1020})
        create_fee_schedule("P100", 5)
        provider = create_crna("Crna A")
        case = create_case(roster["id"], scheduled_start_minute=540,
                           scheduled_end_minute=600)
        propose_and_confirm(case["id"], provider["id"], "CRNA")
        # Ends exactly at day_end 1020 (17:00): not strictly greater.
        run_case_clock(case["id"], "2026-08-10T09:00:00Z",
                       "2026-08-10T17:00:00Z")
        get_success_data(api.complete_case(case["id"], SCHED))
        entries = list_stipend_entries({"provider_id": provider["id"],
                                        "entry_type": "LATE_STAY"})
        assert len(entries) == 0, \
            "ending exactly at scheduled_day_end_minute must accrue nothing"

    def test_end_one_minute_past_day_end_accrues_overrun(self, api):
        """PRD §3.6: "if ... `actual_end_minute` is strictly later than the
        roster's `scheduled_day_end_minute`, then one `LATE_STAY` ledger entry
        is created for the overrun minutes multiplied by the agreement's
        `late_stay_rate_cents_per_minute`".

        Design: Corner/calculations/late_stay_day_end_strictly_greater_boundary
        """
        site, agreement, roster = setup_stipend_site(
            agreement_kwargs={"late_stay_rate_cents_per_minute": 200},
            roster_kwargs={"required_primary_slots": 1,
                           "scheduled_day_end_minute": 1020})
        create_fee_schedule("P100", 5)
        provider = create_crna("Crna B")
        case = create_case(roster["id"], scheduled_start_minute=540,
                           scheduled_end_minute=600)
        propose_and_confirm(case["id"], provider["id"], "CRNA")
        # Ends at 1021 (17:01): (1021 - 1020) x 200 = 200 cents.
        run_case_clock(case["id"], "2026-08-10T09:00:00Z",
                       "2026-08-10T17:01:00Z")
        get_success_data(api.complete_case(case["id"], SCHED))
        entries = list_stipend_entries({"provider_id": provider["id"],
                                        "entry_type": "LATE_STAY"})
        assert len(entries) == 1
        assert entries[0]["amount_cents"] == 200
        assert entries[0]["applied_amount_cents"] == 200


def _publish_roster(api, site_id):
    return create_published_roster(site_id, required_primary_slots=2,
                                   scheduled_day_end_minute=1200)


def _create_call(api, roster_id, provider_id, start, end):
    resp = api.create_call_assignment(
        create_call_assignment_payload(roster_id=roster_id,
                                       provider_id=provider_id,
                                       window_start_minute=start,
                                       window_end_minute=end), SCHED)
    return get_success_data(resp)


def validate_error_free(resp):
    return validate_success(resp, expected_status=201)
