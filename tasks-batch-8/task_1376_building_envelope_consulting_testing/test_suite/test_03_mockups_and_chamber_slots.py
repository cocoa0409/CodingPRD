"""Mock-up testing fees, chamber-slot windows and overlap, retest cycle."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    create_active_engagement,
    create_assembly,
    create_chamber_slot,
    create_mock_up,
    drive_mock_up_to_ready,
    get_engagement,
    set_clock,
    setup_mock_up_testing,
    validate_error,
    validate_success,
)

P = TEST_USERS["principal_headers"]
C = TEST_USERS["consultant_headers"]


class TestMockUpFeeNestedRoundingOrder:

    def test_per_day_rounding_precedes_multiplication(self):
        """PRD §3.3: "The per-day charge is the slot's `daily_rate_cents`
        increased by a specimen surcharge of five percent for each specimen
        beyond the first; that per-day figure is rounded half-up to whole cents
        first, and only then multiplied by the day count and by the mock-up's
        `attempt_number`. Rounding once at the end instead is a different,
        explicitly rejected variant."
        PRD §3.3: "The slot length in days is the whole-day count of its
        half-open window — the number of days from `start_date` up to but not
        including `end_date`."

        Design: Difficulty/combinatorial_formula/mockup_fee_nested_rounding_order
        """
        eng, asm, slot, mu = setup_mock_up_testing(
            name="E4", tag="W4", chamber_code="CHAMBER-A",
            start_date="2026-09-01", end_date="2026-09-04",
            daily_rate_cents=123456, specimen_count=3,
            clock_iso="2026-09-02T09:00:00Z")
        resp = api_client.record_mock_up_result(
            eng["id"], mu["id"], {"measured_leakage_lps_m2": 1.0}, C)
        data = validate_success(resp, 200)
        # daily = round_half_up(123456 * 1.10) = 135802; fee = 135802*3*1.
        # The rejected sum-then-round order would yield 407405.
        assert data["testing_fee_cents"] == 407406
        assert data["testing_fee_cents"] != 407405
        assert data["status"] == "PASSED"

    def test_per_day_rounding_second_configuration(self):
        """PRD §3.3: "The per-day charge is the slot's `daily_rate_cents`
        increased by a specimen surcharge of five percent for each specimen
        beyond the first; that per-day figure is rounded half-up to whole cents
        first, and only then multiplied by the day count and by the mock-up's
        `attempt_number`."

        Design: Difficulty/combinatorial_formula/mockup_fee_nested_rounding_order
        """
        eng, asm, slot, mu = setup_mock_up_testing(
            name="E4B", tag="W4B", chamber_code="CHAMBER-A2",
            start_date="2026-09-01", end_date="2026-09-04",
            daily_rate_cents=100005, specimen_count=2,
            clock_iso="2026-09-02T09:00:00Z")
        resp = api_client.record_mock_up_result(
            eng["id"], mu["id"], {"measured_leakage_lps_m2": 1.0}, C)
        data = validate_success(resp, 200)
        # daily = round_half_up(100005 * 1.05) = round_half_up(105005.25)
        #       = 105005; fee = 105005 * 3 * 1 = 315015.
        # Sum-then-round would give round_half_up(315015.75) = 315016.
        assert data["testing_fee_cents"] == 315015
        assert get_engagement(eng["id"])["recognized_fees_cents"] == 315015


class TestChamberSlotAdjacencyBoundary:

    def test_adjacent_slot_sharing_boundary_day_allowed(self):
        """PRD §3.3: "A new reservation is rejected with `ERR_WINDOW_OVERLAP`
        (HTTP 409) when its half-open window would intersect the half-open
        window of any existing `RESERVED` or `CONSUMED` slot booked under the
        same `chamber_code` on the same engagement; two windows that merely
        touch at a boundary day — one ending on the day the other begins — do
        not conflict."

        Design: Difficulty/boundary_precision_check/chamber_slot_adjacent_window_allowed
        """
        eng = create_active_engagement(name="E12")
        create_chamber_slot(eng["id"], chamber_code="CHAMBER-B",
                            start_date="2026-09-01", end_date="2026-09-05",
                            daily_rate_cents=100000)
        resp = api_client.create_chamber_slot(
            eng["id"],
            {"chamber_code": "CHAMBER-B", "start_date": "2026-09-05",
             "end_date": "2026-09-08", "daily_rate_cents": 100000},
            C,
        )
        data = validate_success(resp, 201)
        assert data["status"] == "RESERVED"

    def test_slot_overlapping_by_one_day_rejected(self):
        """PRD §3.3: "A new reservation is rejected with `ERR_WINDOW_OVERLAP`
        (HTTP 409) when its half-open window would intersect the half-open
        window of any existing `RESERVED` or `CONSUMED` slot booked under the
        same `chamber_code` on the same engagement..."

        Design: Difficulty/boundary_precision_check/chamber_slot_adjacent_window_allowed
        """
        eng = create_active_engagement(name="E12B")
        create_chamber_slot(eng["id"], chamber_code="CHAMBER-B",
                            start_date="2026-09-01", end_date="2026-09-05",
                            daily_rate_cents=100000)
        resp = api_client.create_chamber_slot(
            eng["id"],
            {"chamber_code": "CHAMBER-B", "start_date": "2026-09-04",
             "end_date": "2026-09-06", "daily_rate_cents": 100000},
            C,
        )
        validate_error(resp, ApiErrorId.ERR_WINDOW_OVERLAP)


class TestChamberSlotHalfOpenOverlap:

    def test_contained_slot_conflicts_other_chamber_free(self):
        """PRD §3.3: "A new reservation is rejected with `ERR_WINDOW_OVERLAP`
        (HTTP 409) when its half-open window would intersect the half-open
        window of any existing `RESERVED` or `CONSUMED` slot booked under the
        same `chamber_code` on the same engagement..."

        Design: Difficulty/resource_temporal_overlap/chamber_slot_half_open_overlap
        """
        eng = create_active_engagement(name="E15")
        create_chamber_slot(eng["id"], chamber_code="CHAMBER-C",
                            start_date="2026-09-10", end_date="2026-09-20",
                            daily_rate_cents=90000)
        resp = api_client.create_chamber_slot(
            eng["id"],
            {"chamber_code": "CHAMBER-C", "start_date": "2026-09-12",
             "end_date": "2026-09-15", "daily_rate_cents": 90000},
            C,
        )
        validate_error(resp, ApiErrorId.ERR_WINDOW_OVERLAP)
        # Same dates under a different chamber_code are a different resource.
        resp = api_client.create_chamber_slot(
            eng["id"],
            {"chamber_code": "CHAMBER-D", "start_date": "2026-09-12",
             "end_date": "2026-09-15", "daily_rate_cents": 90000},
            C,
        )
        data = validate_success(resp, 201)
        assert data["status"] == "RESERVED"

    def test_released_slot_window_can_be_rebooked(self):
        """PRD §3.3: "A new reservation is rejected with `ERR_WINDOW_OVERLAP`
        (HTTP 409) when its half-open window would intersect the half-open
        window of any existing `RESERVED` or `CONSUMED` slot booked under the
        same `chamber_code` on the same engagement..."
        PRD §3.3: "Release is refused with `ERR_SLOT_NOT_RESERVED` when the
        slot is not currently `RESERVED`..."

        Design: Difficulty/resource_temporal_overlap/chamber_slot_half_open_overlap
        """
        eng = create_active_engagement(name="E15B")
        slot = create_chamber_slot(eng["id"], chamber_code="CHAMBER-C",
                                   start_date="2026-09-10",
                                   end_date="2026-09-20",
                                   daily_rate_cents=90000)
        resp = api_client.release_chamber_slot(eng["id"], slot["id"], C)
        data = validate_success(resp, 200)
        assert data["status"] == "RELEASED"
        resp = api_client.create_chamber_slot(
            eng["id"],
            {"chamber_code": "CHAMBER-C", "start_date": "2026-09-10",
             "end_date": "2026-09-20", "daily_rate_cents": 90000},
            C,
        )
        data = validate_success(resp, 201)
        assert data["status"] == "RESERVED"


class TestMockUpFailRetestCycle:

    def _setup_failed_mock_up(self):
        """Mock-up enters TESTING against slot S1 and FAILS; S2 RESERVED."""
        eng = create_active_engagement(name="E18")
        asm = create_assembly(eng["id"], tag="W18",
                              required_airtightness_lps_m2=1.5)
        s1 = create_chamber_slot(eng["id"], chamber_code="CHAMBER-E",
                                 start_date="2026-09-01", end_date="2026-09-03",
                                 daily_rate_cents=100000)
        s2 = create_chamber_slot(eng["id"], chamber_code="CHAMBER-E",
                                 start_date="2026-09-10", end_date="2026-09-12",
                                 daily_rate_cents=100000)
        mu = create_mock_up(eng["id"], asm["id"], s1["id"], specimen_count=1)
        drive_mock_up_to_ready(eng["id"], mu["id"])
        set_clock("2026-09-02T09:00:00Z")
        resp = api_client.begin_testing(eng["id"], mu["id"], {}, C)
        validate_success(resp, 200)
        resp = api_client.record_mock_up_result(
            eng["id"], mu["id"], {"measured_leakage_lps_m2": 2.0}, C)
        failed = validate_success(resp, 200)
        assert failed["status"] == "FAILED"
        assert failed["testing_fee_cents"] == 200000
        resp = api_client.mark_remediated(eng["id"], mu["id"], C)
        remediated = validate_success(resp, 200)
        assert remediated["status"] == "REMEDIATED"
        set_clock("2026-09-10T09:00:00Z")
        return eng, s1, s2, remediated

    def test_fail_retest_cycle_conserves_slot_occupancy(self):
        """PRD §3.3: "A remediated mock-up re-enters `TESTING` through the same
        begin-testing action, but from `REMEDIATED` the request must carry
        `new_chamber_slot_id`, referencing a chamber slot of the same
        engagement that is currently `RESERVED`... On re-entry the mock-up's
        `attempt_number` increments by 1, its `chamber_slot_id` is re-pointed
        to the new slot, and the new slot flips to `CONSUMED`; the previously
        consumed slot stays `CONSUMED`."
        PRD §3.3: "Because the fee formula multiplies by `attempt_number`, each
        retest bills proportionally more chamber time."
        PRD §2.6: "A mock-up test failure subtracts 25."

        Design: Difficulty/compensating_invariant/mockup_fail_retest_cycle_conserves_slot_occupancy
        """
        eng, s1, s2, mu = self._setup_failed_mock_up()
        resp = api_client.begin_testing(eng["id"], mu["id"],
                                        {"new_chamber_slot_id": s2["id"]}, C)
        data = validate_success(resp, 200)
        assert data["attempt_number"] == 2
        assert data["chamber_slot_id"] == s2["id"]
        assert data["status"] == "TESTING"

        resp = api_client.record_mock_up_result(
            eng["id"], mu["id"], {"measured_leakage_lps_m2": 1.0}, C)
        data = validate_success(resp, 200)
        # fee = 2 days * 100000 * attempt_number 2.
        assert data["testing_fee_cents"] == 400000
        assert data["status"] == "PASSED"

        s1_after = validate_success(
            api_client.get_chamber_slot(eng["id"], s1["id"], C), 200)
        s2_after = validate_success(
            api_client.get_chamber_slot(eng["id"], s2["id"], C), 200)
        assert s1_after["status"] == "CONSUMED"
        assert s2_after["status"] == "CONSUMED"

        eng_after = get_engagement(eng["id"])
        assert eng_after["recognized_fees_cents"] == 600000
        assert eng_after["risk_score"] == 75

    def test_retest_without_new_slot_rejected(self):
        """PRD §3.3: "from `REMEDIATED` the request must carry
        `new_chamber_slot_id`, referencing a chamber slot of the same
        engagement that is currently `RESERVED` — a missing or non-reserved
        reference is rejected with `ERR_SLOT_NOT_RESERVED`..."

        Design: Difficulty/compensating_invariant/mockup_fail_retest_cycle_conserves_slot_occupancy
        """
        eng, s1, s2, mu = self._setup_failed_mock_up()
        resp = api_client.begin_testing(eng["id"], mu["id"], {}, C)
        validate_error(resp, ApiErrorId.ERR_SLOT_NOT_RESERVED)
        # The already-consumed prior slot is likewise not RESERVED.
        resp = api_client.begin_testing(
            eng["id"], mu["id"], {"new_chamber_slot_id": s1["id"]}, C)
        validate_error(resp, ApiErrorId.ERR_SLOT_NOT_RESERVED)
        after = validate_success(api_client.get_mock_up(eng["id"], mu["id"], C),
                                 200)
        assert after["status"] == "REMEDIATED"
        assert after["attempt_number"] == 1


class TestMockUpAndSlotPreconditions:

    def test_mockup_begin_testing_outside_slot_window(self):
        """PRD §3.3: "the bound chamber slot must still be `RESERVED` —
        otherwise `ERR_SLOT_NOT_RESERVED` — and the logical clock's current
        date must fall inside that slot's half-open window, on `start_date` or
        any later day before `end_date`, otherwise `ERR_OUTSIDE_SLOT_WINDOW`
        (HTTP 409)."

        Design: Corner/state_machines/mockup_begin_testing_outside_slot_window
        """
        eng = create_active_engagement(name="EM")
        asm = create_assembly(eng["id"], tag="AM",
                              required_airtightness_lps_m2=1.5)
        slot = create_chamber_slot(eng["id"], chamber_code="CHAMBER-Z",
                                   start_date="2026-09-10",
                                   end_date="2026-09-12",
                                   daily_rate_cents=100000)
        mu = create_mock_up(eng["id"], asm["id"], slot["id"], specimen_count=1)
        drive_mock_up_to_ready(eng["id"], mu["id"])
        set_clock("2026-09-05T09:00:00Z")
        resp = api_client.begin_testing(eng["id"], mu["id"], {}, C)
        validate_error(resp, ApiErrorId.ERR_OUTSIDE_SLOT_WINDOW)
        mu_after = validate_success(api_client.get_mock_up(eng["id"], mu["id"], C),
                                    200)
        assert mu_after["status"] == "READY_FOR_TEST"
        slot_after = validate_success(
            api_client.get_chamber_slot(eng["id"], slot["id"], C), 200)
        assert slot_after["status"] == "RESERVED"

    def test_chamber_slot_release_blocked_while_mockup_live(self):
        """PRD §3.3: "Release is refused with `ERR_SLOT_NOT_RESERVED` when the
        slot is not currently `RESERVED`, and with `ERR_SLOT_IN_USE` (HTTP 409)
        when any mock-up in `PLANNED`, `CONSTRUCTING`, `READY_FOR_TEST`, or
        `REMEDIATED` still references it."

        Design: Corner/state_machines/chamber_slot_release_blocked_while_mockup_live
        """
        eng = create_active_engagement(name="EC")
        asm = create_assembly(eng["id"], tag="AC",
                              required_airtightness_lps_m2=1.5)
        slot = create_chamber_slot(eng["id"], chamber_code="CHAMBER-Y",
                                   start_date="2026-09-10",
                                   end_date="2026-09-12",
                                   daily_rate_cents=100000)
        create_mock_up(eng["id"], asm["id"], slot["id"], specimen_count=1)
        resp = api_client.release_chamber_slot(eng["id"], slot["id"], C)
        validate_error(resp, ApiErrorId.ERR_SLOT_IN_USE)
        slot_after = validate_success(
            api_client.get_chamber_slot(eng["id"], slot["id"], C), 200)
        assert slot_after["status"] == "RESERVED"
