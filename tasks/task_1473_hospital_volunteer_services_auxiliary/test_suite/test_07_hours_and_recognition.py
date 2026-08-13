"""Hour logging and recognition: entry state machine, weighted points vs raw hours,
pinned per-entry rounding, inclusive tier boundaries, approve/reverse compensation,
the recognition event log, and service-year no-show penalties."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data,
    api_client, ApiErrorId,
    set_clock, create_active_volunteer, create_department, create_role,
    create_open_request, create_published_shift, signup, signup_and_confirm,
    log_hour_entry, approve_entry, log_and_approve_entries, get_summary,
    get_current_version, assert_recognition_event,
    make_volunteer_headers,
)
from test_helpers import TEST_USERS

DIRECTOR = TEST_USERS["director_headers"]
COORDINATOR = TEST_USERS["coordinator_headers"]


def _active_volunteer(dept_name="Gift Shop", role_name="Gift Shop Clerk",
                      category="GIFT_SHOP", minimum_age=16, name="V Hours",
                      email="vh@x.org"):
    dept = create_department(name=dept_name, head_user_id="dh-2")
    role = create_role(name=role_name, category=category, minimum_age=minimum_age)
    request = create_open_request(dept["id"], role["id"], slots_needed=1,
                                  head_user_id="dh-2")
    return create_active_volunteer(dept, role, request, full_name=name, email=email)


class TestWeightedVsRawSameEntries:
    def _setup_two_entries(self):
        set_clock("2026-08-01T00:00:00Z")
        ctx = _active_volunteer(dept_name="Emergency", role_name="ED Greeter",
                                category="PATIENT_FACING", minimum_age=18,
                                name="Alice Adult", email="alice@x.org")
        vol_id = ctx["volunteer_id"]
        set_clock("2026-08-04T00:00:00Z")  # both service dates are no longer future
        e1 = log_hour_entry(vol_id, "2026-08-03", 120, "PATIENT_FACING")
        e2 = log_hour_entry(vol_id, "2026-08-04", 90, "CLERICAL")
        return vol_id, e1, e2

    def test_raw_hours_and_weighted_points_diverge(self, api):
        """PRD §3.6: "`total_service_hours` is the unweighted companion over the same
        input set — the sum of `minutes` over `APPROVED` entries, divided by 60, at
        two decimal places — and the two figures disagree whenever any entry carries
        a multiplier other than 1.0."
        PRD §3.6: "Each `APPROVED` entry contributes its hours — `minutes` over 60 —
        multiplied by the category multiplier: 1.5 for `PATIENT_FACING`, 1.2 for
        `FUNDRAISING`, 1.0 for `GIFT_SHOP`, 1.0 for `COMMUNITY`, and 0.8 for
        `CLERICAL`."

        Design: Difficulty/dual_variant_calc/recognition_weighted_vs_raw_same_entries
        """
        vol_id, e1, e2 = self._setup_two_entries()
        approve_entry(e1["id"])
        approve_entry(e2["id"])

        summary = get_summary(vol_id)
        assert summary["total_service_hours"] == pytest.approx(3.50, abs=0.001), (
            f"raw: (120+90)/60 = 3.50, got {summary['total_service_hours']}")
        assert summary["recognition_points"] == pytest.approx(4.20, abs=0.001), (
            f"weighted: round(2.0*1.5)=3.00 + round(1.5*0.8)=1.20, got "
            f"{summary['recognition_points']}")
        assert summary["total_service_hours"] != summary["recognition_points"]
        assert summary["recognition_tier"] == "NONE", "4.20 < 100.00"

    def test_single_weighted_entry_contribution(self, api):
        """PRD §3.6: "The per-entry product is rounded half-up to two decimal places
        **first**, and `recognition_points` is then the exact sum of those rounded
        per-entry values."

        Design: Difficulty/dual_variant_calc/recognition_weighted_vs_raw_same_entries
        """
        vol_id, e1, _ = self._setup_two_entries()
        approve_entry(e1["id"])
        summary = get_summary(vol_id)
        assert summary["total_service_hours"] == pytest.approx(2.00, abs=0.001)
        assert summary["recognition_points"] == pytest.approx(3.00, abs=0.001), (
            "120 min PATIENT_FACING -> 2.0h x 1.5 = 3.00 points")
        assert summary["recognition_tier"] == "NONE"


class TestPerEntryRoundingOrder:
    def _setup_active(self):
        set_clock("2026-08-01T00:00:00Z")
        return _active_volunteer(dept_name="Records", role_name="Filing Aide",
                                 category="CLERICAL", minimum_age=16,
                                 name="Alice Adult", email="alice@x.org")

    def test_three_25min_clerical_entries_give_099(self, api):
        """PRD §3.6: "The rounding order is pinned: per-entry first, then sum.
        Summing raw products and rounding once at the end is a different,
        non-conforming algorithm — three 25-minute `CLERICAL` entries contribute
        0.33 + 0.33 + 0.33 = 0.99 points under the pinned order, where sum-then-round
        would yield 1.00."

        Design: Difficulty/combinatorial_formula/recognition_per_entry_rounding_order
        """
        ctx = self._setup_active()
        vol_id = ctx["volunteer_id"]
        set_clock("2026-08-05T00:00:00Z")
        log_and_approve_entries(vol_id, [
            ("2026-08-03", 25, "CLERICAL"),
            ("2026-08-04", 25, "CLERICAL"),
            ("2026-08-05", 25, "CLERICAL"),
        ])
        summary = get_summary(vol_id)
        assert summary["recognition_points"] == pytest.approx(0.99, abs=0.0001), (
            f"per-entry rounding gives 0.99, not 1.00; got "
            f"{summary['recognition_points']}")
        assert summary["total_service_hours"] == pytest.approx(1.25, abs=0.001)

    def test_single_25min_clerical_entry_gives_033(self, api):
        """PRD §3.6: "three 25-minute `CLERICAL` entries contribute 0.33 + 0.33 +
        0.33 = 0.99 points under the pinned order" — each entry independently rounds
        25/60 x 0.8 = 0.3333... half-up to 0.33.

        Design: Difficulty/combinatorial_formula/recognition_per_entry_rounding_order
        """
        ctx = self._setup_active()
        vol_id = ctx["volunteer_id"]
        set_clock("2026-08-03T00:00:00Z")
        log_and_approve_entries(vol_id, [("2026-08-03", 25, "CLERICAL")])
        summary = get_summary(vol_id)
        assert summary["recognition_points"] == pytest.approx(0.33, abs=0.0001)
        assert summary["total_service_hours"] == pytest.approx(25 / 60, abs=0.01)


class TestTierBoundaries:
    def _setup_active(self):
        set_clock("2026-08-01T00:00:00Z")
        return _active_volunteer(name="Boundary Bob", email="bob@x.org")

    def test_bronze_at_exactly_100(self, api):
        """PRD §3.6: "The `recognition_tier` recomputes after every points change —
        approval, reversal, or the annual-review sweep — against inclusive
        thresholds: `PRESIDENT` at 1000.00 points or more, `GOLD` at 600.00 or more,
        `SILVER` at 300.00 or more, `BRONZE` at 100.00 or more (exactly 100.00 is
        `BRONZE`), and `NONE` below that."
        PRD §3.6: "A tier change appends a row to the recognition event log recording
        `volunteer_id`, an `event_type` of `TIER_INCREASED` or `TIER_DECREASED`, the
        `tier` moved into, and a `points_snapshot`".

        Design: Difficulty/boundary_precision_check/recognition_tier_bronze_at_exactly_100
        """
        ctx = self._setup_active()
        vol_id = ctx["volunteer_id"]
        set_clock("2026-08-09T00:00:00Z")
        entries = [(f"2026-08-{day:02d}", 960, "GIFT_SHOP") for day in range(3, 9)]
        log_and_approve_entries(vol_id, entries)  # 6 x 16.00 = 96.00
        mid = get_summary(vol_id)
        assert mid["recognition_points"] == pytest.approx(96.00, abs=0.001)
        assert mid["recognition_tier"] == "NONE", "96.00 is below the BRONZE threshold"

        log_and_approve_entries(vol_id, [("2026-08-09", 240, "GIFT_SHOP")])  # +4.00
        fin = get_summary(vol_id)
        assert fin["recognition_points"] == pytest.approx(100.00, abs=0.001)
        assert fin["recognition_tier"] == "BRONZE", "exactly 100.00 is BRONZE (inclusive)"

        events = get_success_data(api.list_recognition_events(
            COORDINATOR, params={"volunteer_id": vol_id}))
        assert len(events) == 1, f"exactly one tier crossing occurred, got {len(events)}"
        assert events[0]["event_type"] == "TIER_INCREASED"
        assert events[0]["tier"] == "BRONZE"
        assert events[0]["points_snapshot"] == pytest.approx(100.00, abs=0.001)

    def test_silver_at_exactly_300(self, api):
        """PRD §3.6: "The `recognition_tier` recomputes after every points change —
        approval, reversal, or the annual-review sweep — against inclusive
        thresholds" — the same rule at the next rung: `SILVER` at 300.00 or more
        (12 x 24.00 + 12.00 = 300.00 exactly).

        Design: Difficulty/boundary_precision_check/recognition_tier_bronze_at_exactly_100
        """
        ctx = self._setup_active()
        vol_id = ctx["volunteer_id"]
        set_clock("2026-08-15T00:00:00Z")
        entries = [(f"2026-08-{day:02d}", 960, "PATIENT_FACING")
                   for day in range(3, 15)]  # 12 x 24.00 = 288.00
        entries.append(("2026-08-15", 480, "PATIENT_FACING"))  # +12.00 -> 300.00
        log_and_approve_entries(vol_id, entries)
        fin = get_summary(vol_id)
        assert fin["recognition_points"] == pytest.approx(300.00, abs=0.001)
        assert fin["recognition_tier"] == "SILVER", "exactly 300.00 is SILVER (inclusive)"
        events = get_success_data(api.list_recognition_events(
            COORDINATOR, params={"volunteer_id": vol_id}))
        assert [(e["event_type"], e["tier"]) for e in events] == [
            ("TIER_INCREASED", "BRONZE"), ("TIER_INCREASED", "SILVER")]


class TestHourEntryStateMachine:
    def test_terminal_and_invalid_transitions(self, api):
        """PRD §3.6: "Only a `PENDING` entry is approvable
        (`ERR_HOUR_ENTRY_INVALID_STATE`)."
        PRD §3.6: "Reversal is the compensating path for an `APPROVED` entry — again
        `ERR_HOUR_ENTRY_INVALID_STATE` from any other state".

        Design: Corner/state_machines/hour_entry_terminal_and_invalid
        """
        set_clock("2026-08-01T00:00:00Z")
        ctx = _active_volunteer(dept_name="Records", role_name="Filing Aide",
                                category="CLERICAL", name="Hank Entry",
                                email="he@x.org")
        vol_id = ctx["volunteer_id"]
        set_clock("2026-08-04T00:00:00Z")
        e1 = log_hour_entry(vol_id, "2026-08-03", 60, "CLERICAL")
        e2 = log_hour_entry(vol_id, "2026-08-04", 60, "CLERICAL")
        validate_success(api.reject_hour_entry(
            e1["id"], {"decision_reason": "unverifiable"}, COORDINATOR))

        version = get_current_version(vol_id)
        resp = api.approve_hour_entry(
            e1["id"], {"expected_volunteer_version": version}, COORDINATOR)
        validate_error(resp, ApiErrorId.ERR_HOUR_ENTRY_INVALID_STATE)

        resp = api.reverse_hour_entry(
            e2["id"], {"decision_reason": "mistake"}, COORDINATOR)
        validate_error(resp, ApiErrorId.ERR_HOUR_ENTRY_INVALID_STATE)

        summary = get_summary(vol_id)
        assert summary["total_service_hours"] == pytest.approx(0.0, abs=0.001)
        assert summary["recognition_points"] == pytest.approx(0.0, abs=0.001)


class TestApproveReverseConservation:
    def _setup_active(self):
        set_clock("2026-08-01T00:00:00Z")
        return _active_volunteer(dept_name="Emergency", role_name="ED Greeter",
                                 category="PATIENT_FACING", minimum_age=18,
                                 name="V Hours", email="vh@x.org")

    def test_approve_then_reverse_returns_to_zero(self, api):
        """PRD §3.6: "Reversal subtracts from `total_service_hours` exactly the hours
        that approval added, subtracts from `recognition_points` exactly the same
        per-entry rounded points that approval added, and recomputes the tier,
        appending a `TIER_DECREASED` recognition event if it fell."

        Design: Difficulty/compensating_invariant/hour_approve_reverse_conserves_hours
        """
        ctx = self._setup_active()
        vol_id = ctx["volunteer_id"]
        set_clock("2026-08-03T00:00:00Z")
        entry = log_hour_entry(vol_id, "2026-08-03", 120, "PATIENT_FACING")
        approve_entry(entry["id"])

        mid = get_summary(vol_id)
        assert mid["total_service_hours"] == pytest.approx(2.00, abs=0.001)
        assert mid["recognition_points"] == pytest.approx(3.00, abs=0.001)
        assert mid["recognition_tier"] == "NONE"

        reversed_entry = validate_success(api.reverse_hour_entry(
            entry["id"], {"decision_reason": "logged against wrong day"}, COORDINATOR))
        assert reversed_entry["status"] == "REVERSED"

        fin = get_summary(vol_id)
        assert fin["total_service_hours"] == pytest.approx(0.00, abs=0.0001)
        assert fin["recognition_points"] == pytest.approx(0.00, abs=0.0001)
        assert fin["recognition_tier"] == "NONE"
        events = get_success_data(api.list_recognition_events(
            COORDINATOR, params={"volunteer_id": vol_id}))
        assert events == [], "NONE -> NONE -> NONE: no tier crossing, no event"

    def test_reverse_does_not_revert_completed_assignment(self, api):
        """PRD §3.6: "when the entry references a `CONFIRMED` assignment, flips that
        assignment to `COMPLETED`" (on approval).
        PRD §3.6: "One asymmetry is documented and deliberate: the linked assignment
        is **not** reverted out of `COMPLETED`."

        Design: Difficulty/compensating_invariant/hour_approve_reverse_conserves_hours
        """
        ctx = self._setup_active()
        vol_id = ctx["volunteer_id"]
        shift = create_published_shift(ctx["department"]["id"], ctx["role"]["id"],
                                       "2026-08-03T08:00:00Z", "2026-08-03T12:00:00Z",
                                       capacity=2)
        asg = signup_and_confirm(shift["id"], vol_id)

        set_clock("2026-08-04T00:00:00Z")
        entry = log_hour_entry(vol_id, "2026-08-03", 240, "CLERICAL",
                               shift_assignment_id=asg["id"])
        approve_entry(entry["id"])
        row = get_success_data(api.get_shift_assignment(asg["id"], COORDINATOR))
        assert row["status"] == "COMPLETED", "approving the linked entry completes it"

        validate_success(api.reverse_hour_entry(
            entry["id"], {"decision_reason": "wrong shift linked"}, COORDINATOR))
        row = get_success_data(api.get_shift_assignment(asg["id"], COORDINATOR))
        assert row["status"] == "COMPLETED", "the documented asymmetry: no revert"
        fin = get_summary(vol_id)
        assert fin["total_service_hours"] == pytest.approx(0.00, abs=0.0001)


class TestRecognitionEventImmutability:
    def test_event_rows_have_no_version_or_updated_at(self, api):
        """PRD §2.5: "Recognition event rows are append-only: they carry `id` and
        `created_at` only, with no `updated_at` and no `version`, and no endpoint
        ever modifies them."

        Design: Corner/entities/recognition_event_immutability
        """
        set_clock("2026-08-01T00:00:00Z")
        ctx = _active_volunteer(name="Event Eva", email="eva@x.org")
        vol_id = ctx["volunteer_id"]
        set_clock("2026-08-09T00:00:00Z")
        entries = [(f"2026-08-{day:02d}", 960, "GIFT_SHOP") for day in range(3, 9)]
        entries.append(("2026-08-09", 240, "GIFT_SHOP"))
        log_and_approve_entries(vol_id, entries)

        events = get_success_data(api.list_recognition_events(
            COORDINATOR, params={"volunteer_id": vol_id}))
        assert len(events) == 1
        event = get_success_data(api.get_recognition_event(events[0]["id"], COORDINATOR))
        assert_recognition_event(event)
        assert event["tier"] == "BRONZE"
        assert event["event_type"] == "TIER_INCREASED"
        assert event["points_snapshot"] == pytest.approx(100.00, abs=0.001)


class TestNoShowReconciliation:
    def _setup_two_volunteers_shift(self):
        set_clock("2026-08-01T00:00:00Z")
        dept = create_department(name="Emergency", head_user_id="dh-1")
        role = create_role(name="ED Greeter", category="PATIENT_FACING", minimum_age=18)
        request = create_open_request(dept["id"], role["id"], slots_needed=2)
        v1 = create_active_volunteer(dept, role, request, full_name="V One",
                                     email="v1@x.org")
        v2 = create_active_volunteer(dept, role, request, full_name="V Two",
                                     email="v2@x.org")
        shift = create_published_shift(dept["id"], role["id"], "2026-08-03T08:00:00Z",
                                       "2026-08-03T12:00:00Z", capacity=5)
        return dept, role, v1, v2, shift

    def test_shift_complete_no_show_reconciliation(self, api):
        """PRD §3.5: "On completion, each `CONFIRMED` assignment with no `APPROVED`
        hour entry referencing it flips to `NO_SHOW`, feeding the two-hour
        service-year penalty of §3.6, and each `SIGNED_UP` or `WAITLISTED` assignment
        is cancelled outright — again with no promotion, because the shift is over."
        PRD §3.6: "Third, the difference, floored at zero so the figure never goes
        negative."

        Design: Corner/state_machines/shift_complete_no_show_reconciliation
        """
        _, _, v1, v2, shift = self._setup_two_volunteers_shift()
        asg1 = signup_and_confirm(shift["id"], v1["volunteer_id"])
        asg2 = signup(shift["id"], v2["volunteer_id"])

        set_clock("2026-08-04T00:00:00Z")
        completed = validate_success(api.complete_shift(shift["id"], COORDINATOR))
        assert completed["status"] == "COMPLETED"

        row1 = get_success_data(api.get_shift_assignment(asg1["id"], COORDINATOR))
        assert row1["status"] == "NO_SHOW", "CONFIRMED without an approved entry"
        row2 = get_success_data(api.get_shift_assignment(asg2["id"], COORDINATOR))
        assert row2["status"] == "CANCELLED", "SIGNED_UP at completion is cancelled"

        summary = get_summary(v1["volunteer_id"])
        assert summary["service_year_hours"] == pytest.approx(0.0, abs=0.0001), (
            "0 approved - 2.0 no-show penalty, floored at zero")

    def test_no_show_penalty_math(self, api):
        """PRD §3.6: "The service-year hours figure is computed in a pinned order.
        First, approved hours: the sum of `minutes` over the volunteer's `APPROVED`
        entries whose `service_date` falls inside the window — start inclusive, end
        exclusive — divided by 60. Second, the penalty: 2.0 hours for each of the
        volunteer's `NO_SHOW` assignments whose shift's `end_at` falls inside the
        same window. Third, the difference, floored at zero so the figure never goes
        negative."

        Design: Corner/calculations/service_year_hours_no_show_penalty_math
        """
        set_clock("2026-08-01T00:00:00Z")
        dept = create_department(name="Gift Shop", head_user_id="dh-2")
        role = create_role(name="Gift Shop Clerk", category="GIFT_SHOP", minimum_age=16)
        request = create_open_request(dept["id"], role["id"], slots_needed=1,
                                      head_user_id="dh-2")
        ctx = create_active_volunteer(dept, role, request, full_name="Penalty Pam",
                                      email="pp2@x.org")
        vol_id = ctx["volunteer_id"]
        s1 = create_published_shift(dept["id"], role["id"], "2026-08-03T08:00:00Z",
                                    "2026-08-03T12:00:00Z", capacity=2)
        s2 = create_published_shift(dept["id"], role["id"], "2026-08-04T08:00:00Z",
                                    "2026-08-04T12:00:00Z", capacity=2)
        signup_and_confirm(s1["id"], vol_id)
        signup_and_confirm(s2["id"], vol_id)

        set_clock("2026-08-05T00:00:00Z")
        validate_success(api.complete_shift(s1["id"], COORDINATOR))
        validate_success(api.complete_shift(s2["id"], COORDINATOR))

        log_and_approve_entries(vol_id, [("2026-08-05", 300, "GIFT_SHOP")])
        summary = get_summary(vol_id)
        assert summary["service_year_hours"] == pytest.approx(1.00, abs=0.0001), (
            f"5.00 approved - 2 x 2.0 penalty = 1.00, got {summary['service_year_hours']}")
        assert summary["total_service_hours"] == pytest.approx(5.00, abs=0.001), (
            "penalties never touch the lifetime raw total")
