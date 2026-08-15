"""Interval algebras and capacity rules: closed-minute call windows,
aggregate-capacity supervision ratio, half-open double-booking (PRD §2.6,
§3.3, §3.4)."""
from test_helpers import (
    SCHED,
    ApiErrorId,
    create_call_assignment_payload,
    create_case,
    create_crna,
    create_fee_schedule,
    create_physician,
    create_published_roster,
    create_site,
    get_success_data,
    list_assignments,
    propose_assignment,
    validate_error,
    validate_success,
    api_client,
)


class TestCallWindowClosedInterval:
    def _setup_cross_roster_windows(self, api):
        """Two sites, two PUBLISHED rosters on the same date, one CRNA holding
        window [600,900] on roster 1."""
        s1 = create_site("General Hospital")
        s2 = create_site("Surgery Center")
        provider = create_crna("Crna One")
        r1 = create_published_roster(s1["id"], required_primary_slots=0,
                                     scheduled_day_end_minute=1200)
        r2 = create_published_roster(s2["id"], required_primary_slots=0,
                                     scheduled_day_end_minute=1200)
        get_success_data(api.create_call_assignment(
            create_call_assignment_payload(roster_id=r1["id"],
                                           provider_id=provider["id"],
                                           window_start_minute=600,
                                           window_end_minute=900), SCHED))
        return provider, r1, r2

    def test_shared_endpoint_minute_conflicts_across_rosters(self, api):
        """PRD §2.6: "Two windows for the same provider on the same service
        date conflict when they share any minute at all, including a single
        shared endpoint minute — a window ending at 600 and another beginning
        at 600 do conflict here, in deliberate contrast to case intervals."
        PRD §3.4: "any two windows for the same provider on the same
        `service_date` — across all rosters — that share even a single
        endpoint minute are rejected with `ERR_CALL_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/call_window_closed_interval_endpoint_minute_conflict
        """
        provider, r1, r2 = self._setup_cross_roster_windows(api)
        # [900,1200] on the OTHER roster shares endpoint minute 900.
        resp = api.create_call_assignment(
            create_call_assignment_payload(roster_id=r2["id"],
                                           provider_id=provider["id"],
                                           window_start_minute=900,
                                           window_end_minute=1200), SCHED)
        validate_error(resp, ApiErrorId.ERR_CALL_WINDOW_OVERLAP)

    def test_disjoint_window_on_other_roster_allowed(self, api):
        """PRD §2.6: "Two windows for the same provider on the same service
        date conflict when they share any minute at all, including a single
        shared endpoint minute".
        PRD §3.4: "New call assignments begin `SCHEDULED`, with
        `released_at_minute` null."

        Design: Difficulty/resource_temporal_overlap/call_window_closed_interval_endpoint_minute_conflict
        """
        provider, r1, r2 = self._setup_cross_roster_windows(api)
        # [901,1200] shares no minute with [600,900].
        resp = api.create_call_assignment(
            create_call_assignment_payload(roster_id=r2["id"],
                                           provider_id=provider["id"],
                                           window_start_minute=901,
                                           window_end_minute=1200), SCHED)
        created = validate_success(resp, expected_status=201)
        assert created["status"] == "SCHEDULED"
        assert created["released_at_minute"] is None


class TestSupervisionRatioCapacity:
    def _five_identical_cases(self, api):
        site = create_site()
        create_fee_schedule("P100", 5)
        physician = create_physician("Dr. Direct")
        roster = create_published_roster(site["id"], required_primary_slots=0,
                                         scheduled_day_end_minute=1200)
        cases = [create_case(roster["id"], scheduled_start_minute=540,
                             scheduled_end_minute=660) for _ in range(5)]
        return physician, cases

    def test_four_overlapping_directions_allowed_fifth_rejected(self, api):
        """PRD §3.3: "If adding the candidate would push the physician's peak
        directed concurrency above four rooms, the proposal is rejected with
        `ERR_SUPERVISION_RATIO_EXCEEDED`. This is an aggregate-capacity rule,
        not a pairwise rule: four pairwise-overlapping rooms are allowed, a
        fifth concurrent room is not."

        Design: Difficulty/resource_temporal_overlap/supervision_ratio_capacity_4_allowed_5th_rejected
        """
        physician, cases = self._five_identical_cases(api)
        for case in cases[:4]:
            resp = api.create_case_assignment(
                case["id"], {"provider_id": physician["id"],
                             "assignment_role": "CASE_DIRECTING",
                             "expected_case_version": case["version"]}, SCHED)
            created = validate_success(resp, expected_status=201)
            assert created["status"] == "PROPOSED"
        resp = api.create_case_assignment(
            cases[4]["id"], {"provider_id": physician["id"],
                             "assignment_role": "CASE_DIRECTING",
                             "expected_case_version": cases[4]["version"]},
            SCHED)
        validate_error(resp, ApiErrorId.ERR_SUPERVISION_RATIO_EXCEEDED)

    def test_exactly_four_directing_assignments_materialize(self, api):
        """PRD §3.3: "the system collects the physician's `PROPOSED` and
        `CONFIRMED` `CASE_DIRECTING` assignments on cases sharing the roster's
        `service_date`, adds the candidate case's scheduled interval, and
        computes the peak overlap across that set of half-open intervals
        (intervals touching at an endpoint do not overlap)."
        PRD §3.3: "Assignment lists may be filtered by `case_id`,
        `provider_id`, `roster_id`, `status`, or `assignment_role`."

        Design: Difficulty/resource_temporal_overlap/supervision_ratio_capacity_4_allowed_5th_rejected
        """
        physician, cases = self._five_identical_cases(api)
        for case in cases[:4]:
            get_success_data(api.create_case_assignment(
                case["id"], {"provider_id": physician["id"],
                             "assignment_role": "CASE_DIRECTING",
                             "expected_case_version": case["version"]}, SCHED))
        # Fifth rejected.
        api.create_case_assignment(
            cases[4]["id"], {"provider_id": physician["id"],
                             "assignment_role": "CASE_DIRECTING",
                             "expected_case_version": cases[4]["version"]}, SCHED)
        directing = list_assignments({"provider_id": physician["id"],
                                      "assignment_role": "CASE_DIRECTING"})
        assert len(directing) == 4, (
            f"exactly the four allowed directing assignments must exist, got "
            f"{len(directing)}")


class TestDoubleBookingHalfOpen:
    def _setup_provider_with_case_a(self, api):
        site = create_site()
        create_fee_schedule("P100", 5)
        provider = create_crna("Crna One")
        roster = create_published_roster(site["id"], required_primary_slots=3,
                                         scheduled_day_end_minute=1200)
        case_a = create_case(roster["id"], scheduled_start_minute=540,
                             scheduled_end_minute=660)
        propose_assignment(case_a["id"], provider["id"], "CASE_PRIMARY")
        case_b = create_case(roster["id"], scheduled_start_minute=660,
                             scheduled_end_minute=720)
        case_c = create_case(roster["id"], scheduled_start_minute=659,
                             scheduled_end_minute=720)
        return provider, case_b, case_c

    def test_adjacent_intervals_do_not_conflict(self, api):
        """PRD §2.6: "Two case intervals conflict only when each begins
        strictly before the other ends; two intervals that merely touch at an
        endpoint — one ending at minute 600, another beginning at minute 600 —
        do not conflict."

        Design: Corner/validations/double_booking_half_open_adjacency
        """
        provider, case_b, case_c = self._setup_provider_with_case_a(api)
        resp = api.create_case_assignment(
            case_b["id"], {"provider_id": provider["id"],
                           "assignment_role": "CASE_PRIMARY",
                           "expected_case_version": case_b["version"]}, SCHED)
        validate_success(resp, expected_status=201)

    def test_one_minute_overlap_conflicts(self, api):
        """PRD §3.3: "any pair where each interval begins before the other
        ends is a conflict rejected with `ERR_PROVIDER_DOUBLE_BOOKED`, while
        intervals that merely abut do not conflict."

        Design: Corner/validations/double_booking_half_open_adjacency
        """
        provider, case_b, case_c = self._setup_provider_with_case_a(api)
        # [659,720) vs existing [540,660): overlaps by one minute.
        resp = api.create_case_assignment(
            case_c["id"], {"provider_id": provider["id"],
                           "assignment_role": "CASE_PRIMARY",
                           "expected_case_version": case_c["version"]}, SCHED)
        validate_error(resp, ApiErrorId.ERR_PROVIDER_DOUBLE_BOOKED)
