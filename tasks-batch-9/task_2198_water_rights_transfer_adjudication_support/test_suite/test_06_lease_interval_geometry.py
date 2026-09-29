"""The two lease interval geometries and the headgate capacity aggregate.

PRD §3.9: "The two interval rules are deliberately not the same shape, and they
act on disjoint populations, so both geometries are independently reachable from
a single request."
"""
import pytest
from test_helpers import ApiErrorId, get_success_data, validate_error, validate_paginated
from test_helpers.fixtures import (
    ANALYST,
    api_client,
    read_account,
    reserve_lease,
    setup_authorized_headgate_account,
)

TWO_HEADGATES = [
    {
        "max_rate_cfs": 5.000,
        "legal_description": "NE1/4 SEC 12 T3N R4E upper headgate",
        "stream_reach_code": "SNK-14-A",
    },
    {
        "max_rate_cfs": 5.000,
        "legal_description": "SW1/4 SEC 18 T3N R4E lower headgate",
        "stream_reach_code": "SNK-14-B",
    },
]


class TestHeadgateCapacityAggregate:
    """PRD §3.9 — "the candidate's `diversion_rate_cfs` plus the
    `diversion_rate_cfs` of every overlapping lease, summed and rounded to 3
    decimal places, must be no greater than the headgate's `max_rate_cfs`, and
    equality is accepted."

    One headgate rated at exactly 3.000 CFS carries two fully overlapping leases
    of 1.250 and 1.750 CFS, which sum to the rating exactly.
    """

    WINDOW = ("2026-04-01T00:00:00Z", "2026-08-01T00:00:00Z")

    def _headgate_at_capacity(self):
        bundle = setup_authorized_headgate_account(
            deposit_af=100.00, max_rate_cfs=3.000
        )
        for rate in (1.250, 1.750):
            get_success_data(
                reserve_lease(
                    bundle["account"]["id"],
                    bundle["right"]["id"],
                    bundle["pod"]["id"],
                    self.WINDOW[0],
                    self.WINDOW[1],
                    10.00,
                    diversion_rate_cfs=rate,
                )
            )
        return bundle

    def test_aggregate_rate_exactly_at_capacity_is_accepted(self):
        """PRD §3.9: "The gate is a conservative aggregate rather than a
        per-instant maximum ... and equality is accepted."

        PRD §3.9: "two fully overlapping windows at one headgate pass whenever
        their aggregate rate fits". 1.250 + 1.750 is exactly 3.000, so both leases
        reserve and the account has 20.00 AF of credit committed against 80.00
        still available.

        Design: Difficulty/boundary_precision_check/pod_rate_equality_accepted_one_thousandth_rejected
        """
        bundle = self._headgate_at_capacity()

        listed, _meta = validate_paginated(
            api_client.list_lease_assignments(
                ANALYST, params={"point_of_diversion_id": bundle["pod"]["id"]}
            )
        )
        assert len(listed) == 2
        assert all(lease["status"] == "RESERVED" for lease in listed)
        account = read_account(bundle["account"]["id"])
        assert account["deposited_credit_af"] == pytest.approx(100.00, abs=0.01)
        assert account["committed_credit_af"] == pytest.approx(20.00, abs=0.01)
        assert account["leased_out_af"] == pytest.approx(0.00, abs=0.01)
        assert account["available_credit_af"] == pytest.approx(80.00, abs=0.01)
        assert account["posture"] == "OPEN"

    def test_one_thousandth_of_a_cfs_over_capacity_is_rejected(self):
        """PRD §3.9: "Exceeding it is `ERR_POD_CAPACITY_EXCEEDED` (409)."

        A third overlapping lease asking for only 0.001 CFS takes the aggregate to
        3.001 against a 3.000 rating, and the smallest representable excess is
        refused just as any larger one would be. No third row is created and the
        credit ledger does not move.

        Design: Difficulty/boundary_precision_check/pod_rate_equality_accepted_one_thousandth_rejected
        """
        bundle = self._headgate_at_capacity()

        response = reserve_lease(
            bundle["account"]["id"],
            bundle["right"]["id"],
            bundle["pod"]["id"],
            self.WINDOW[0],
            self.WINDOW[1],
            10.00,
            diversion_rate_cfs=0.001,
        )

        validate_error(
            response, ApiErrorId.ERR_POD_CAPACITY_EXCEEDED.value, expected_status=409
        )
        listed, _meta = validate_paginated(
            api_client.list_lease_assignments(
                ANALYST, params={"point_of_diversion_id": bundle["pod"]["id"]}
            )
        )
        assert len(listed) == 2
        account = read_account(bundle["account"]["id"])
        assert account["committed_credit_af"] == pytest.approx(20.00, abs=0.01)
        assert account["available_credit_af"] == pytest.approx(80.00, abs=0.01)


class TestSameHeadgateHalfOpenAdjacency:
    """PRD §3.9 — "The **same-headgate** rule enforces a physical capacity limit
    instead of an exclusivity rule, and it treats the window as half-open."

    One headgate rated at 3.000 CFS already carries a 2.000 CFS lease running
    `[2026-04-01, 2026-06-01)`; every candidate below asks for 10.00 AF.
    """

    def _headgate_with_first_lease(self):
        bundle = setup_authorized_headgate_account(
            deposit_af=100.00, max_rate_cfs=3.000
        )
        get_success_data(
            reserve_lease(
                bundle["account"]["id"],
                bundle["right"]["id"],
                bundle["pod"]["id"],
                "2026-04-01T00:00:00Z",
                "2026-06-01T00:00:00Z",
                10.00,
                diversion_rate_cfs=2.000,
            )
        )
        return bundle

    def _reserve(self, bundle, start, end, rate):
        return reserve_lease(
            bundle["account"]["id"],
            bundle["right"]["id"],
            bundle["pod"]["id"],
            start,
            end,
            10.00,
            diversion_rate_cfs=rate,
        )

    def test_back_to_back_windows_at_one_headgate_never_overlap(self):
        """PRD §3.9: "Touching endpoints do *not* overlap here, so back-to-back
        leases at one headgate are always permitted."

        A second 2.000 CFS lease beginning at the very instant the first ends is
        accepted even though 2.000 + 2.000 would breach the 3.000 rating, because
        the two windows share no positive-length intersection.

        Design: Difficulty/resource_temporal_overlap/pod_half_open_adjacency_and_aggregate
        """
        bundle = self._headgate_with_first_lease()

        response = self._reserve(
            bundle, "2026-06-01T00:00:00Z", "2026-08-01T00:00:00Z", 2.000
        )

        lease = get_success_data(response, expected_status=201)
        assert lease["status"] == "RESERVED"
        assert lease["diversion_rate_cfs"] == pytest.approx(2.000, abs=0.0005)
        account = read_account(bundle["account"]["id"])
        assert account["committed_credit_af"] == pytest.approx(20.00, abs=0.01)
        assert account["available_credit_af"] == pytest.approx(80.00, abs=0.01)

    def test_straddling_window_aggregates_both_neighbours_and_is_refused(self):
        """PRD §3.9: "the existing lease's `lease_start_date` is strictly before
        the candidate's `lease_end_date` and its `lease_end_date` is strictly after
        the candidate's `lease_start_date`."

        A window of `[2026-05-15, 2026-06-15)` genuinely intersects both existing
        leases, so the aggregate is 2.000 + 2.000 + 1.500 = 5.500 CFS against a
        3.000 rating and the reservation is refused.

        Design: Difficulty/resource_temporal_overlap/pod_half_open_adjacency_and_aggregate
        """
        bundle = self._headgate_with_first_lease()
        get_success_data(
            self._reserve(bundle, "2026-06-01T00:00:00Z", "2026-08-01T00:00:00Z", 2.000)
        )

        response = self._reserve(
            bundle, "2026-05-15T00:00:00Z", "2026-06-15T00:00:00Z", 1.500
        )

        validate_error(
            response, ApiErrorId.ERR_POD_CAPACITY_EXCEEDED.value, expected_status=409
        )
        listed, _meta = validate_paginated(
            api_client.list_lease_assignments(
                ANALYST, params={"point_of_diversion_id": bundle["pod"]["id"]}
            )
        )
        assert len(listed) == 2

    def test_window_touching_only_the_later_lease_fits_exactly(self):
        """PRD §3.9: "It examines every non-terminal lease at the same
        `point_of_diversion_id`, and considers a lease overlapping only when it
        shares a positive-length intersection with the candidate".

        `[2026-06-01, 2026-06-15)` touches the earlier lease's end instant and so
        excludes it from the aggregate, leaving 2.000 + 1.000 = 3.000 CFS exactly
        at the rating. Three leases end up committed against the account.

        Design: Difficulty/resource_temporal_overlap/pod_half_open_adjacency_and_aggregate
        """
        bundle = self._headgate_with_first_lease()
        get_success_data(
            self._reserve(bundle, "2026-06-01T00:00:00Z", "2026-08-01T00:00:00Z", 2.000)
        )

        response = self._reserve(
            bundle, "2026-06-01T00:00:00Z", "2026-06-15T00:00:00Z", 1.000
        )

        lease = get_success_data(response, expected_status=201)
        assert lease["status"] == "RESERVED"
        listed, _meta = validate_paginated(
            api_client.list_lease_assignments(
                ANALYST, params={"point_of_diversion_id": bundle["pod"]["id"]}
            )
        )
        assert len(listed) == 3
        account = read_account(bundle["account"]["id"])
        assert account["deposited_credit_af"] == pytest.approx(100.00, abs=0.01)
        assert account["committed_credit_af"] == pytest.approx(30.00, abs=0.01)
        assert account["leased_out_af"] == pytest.approx(0.00, abs=0.01)
        assert account["available_credit_af"] == pytest.approx(70.00, abs=0.01)
        assert account["posture"] == "OPEN"


class TestSameRightClosedFallowBuffer:
    """PRD §3.9 — "The **same-right, different-headgate** rule enforces that a
    right's water is delivered at only one headgate at a time."

    One right owns two authorized headgates. A 20.00 AF lease runs
    `[2026-04-01, 2026-06-30)` at the first, projecting a fallow exclusion window
    of `[2026-03-25, 2026-07-07]`. Every candidate below sits at the *second*
    headgate and asks for 10.00 AF at 1.000 CFS, so headgate capacity can never be
    the reason for a refusal.
    """

    def _right_with_two_headgates(self):
        bundle = setup_authorized_headgate_account(
            deposit_af=100.00, pod_specs=TWO_HEADGATES
        )
        get_success_data(
            reserve_lease(
                bundle["account"]["id"],
                bundle["right"]["id"],
                bundle["pods"][0]["id"],
                "2026-04-01T00:00:00Z",
                "2026-06-30T00:00:00Z",
                20.00,
                diversion_rate_cfs=1.000,
            )
        )
        return bundle

    def _candidate(self, bundle, start, end):
        return reserve_lease(
            bundle["account"]["id"],
            bundle["right"]["id"],
            bundle["pods"][1]["id"],
            start,
            end,
            10.00,
            diversion_rate_cfs=1.000,
        )

    @pytest.mark.parametrize(
        "start,end,edge",
        [
            (
                "2026-07-07T00:00:00Z",
                "2026-08-31T00:00:00Z",
                "starting exactly 7 days after the existing lease's end instant",
            ),
            (
                "2026-02-01T00:00:00Z",
                "2026-03-25T00:00:00Z",
                "ending exactly 7 days before the existing lease's start instant",
            ),
        ],
    )
    def test_candidate_touching_the_buffer_collides(self, start, end, edge):
        """PRD §3.9: "The collision test is closed on both ends: the candidate
        collides when its `lease_start_date` is at or before the exclusion window's
        end *and* its `lease_end_date` is at or after the exclusion window's
        start."

        PRD §3.9: "Touching endpoints therefore do collide — a candidate starting
        exactly 7 days after an existing lease's end instant still collides".
        Nothing is committed by the refusal.

        Design: Difficulty/resource_temporal_overlap/right_closed_buffer_across_headgates
        """
        bundle = self._right_with_two_headgates()

        response = self._candidate(bundle, start, end)

        validate_error(
            response, ApiErrorId.ERR_LEASE_WINDOW_CONFLICT.value, expected_status=409
        )
        account = read_account(bundle["account"]["id"])
        assert account["committed_credit_af"] == pytest.approx(20.00, abs=0.01)
        assert account["available_credit_af"] == pytest.approx(80.00, abs=0.01)

    @pytest.mark.parametrize(
        "start,end",
        [
            ("2026-07-08T00:00:00Z", "2026-09-01T00:00:00Z"),
            ("2026-02-01T00:00:00Z", "2026-03-24T00:00:00Z"),
        ],
    )
    def test_candidate_one_day_clear_of_the_buffer_is_accepted(self, start, end):
        """PRD §3.9: "a gap of 7 days and one second is the smallest separation
        that is accepted."

        Stepping either endpoint one day further out of the exclusion window turns
        the same refused request into an accepted reservation, which is what makes
        the buffer boundary observable rather than incidental.

        Design: Difficulty/resource_temporal_overlap/right_closed_buffer_across_headgates
        """
        bundle = self._right_with_two_headgates()

        response = self._candidate(bundle, start, end)

        lease = get_success_data(response, expected_status=201)
        assert lease["status"] == "RESERVED"
        assert lease["point_of_diversion_id"] == bundle["pods"][1]["id"]
        account = read_account(bundle["account"]["id"])
        assert account["committed_credit_af"] == pytest.approx(30.00, abs=0.01)
        assert account["available_credit_af"] == pytest.approx(70.00, abs=0.01)

    def test_both_clear_candidates_can_coexist_around_the_buffer(self):
        """PRD §3.9: "It examines every non-terminal lease — `RESERVED`, `ACTIVE`
        or `SUSPENDED`, never `COMPLETED` or `CANCELLED` — that sits on the same
        `water_right_id` but a *different* `point_of_diversion_id`."

        A lease wholly before the exclusion window and a lease wholly after it are
        each clear of the buffer *and* of one another, so the right ends up with
        three non-terminal leases and 40.00 AF of committed credit.

        Design: Difficulty/resource_temporal_overlap/right_closed_buffer_across_headgates
        """
        bundle = self._right_with_two_headgates()

        get_success_data(
            self._candidate(bundle, "2026-07-08T00:00:00Z", "2026-09-01T00:00:00Z")
        )
        get_success_data(
            self._candidate(bundle, "2026-02-01T00:00:00Z", "2026-03-24T00:00:00Z")
        )

        listed, _meta = validate_paginated(
            api_client.list_lease_assignments(
                ANALYST, params={"water_right_id": bundle["right"]["id"]}
            )
        )
        assert len(listed) == 3
        account = read_account(bundle["account"]["id"])
        assert account["deposited_credit_af"] == pytest.approx(100.00, abs=0.01)
        assert account["committed_credit_af"] == pytest.approx(40.00, abs=0.01)
        assert account["leased_out_af"] == pytest.approx(0.00, abs=0.01)
        assert account["available_credit_af"] == pytest.approx(60.00, abs=0.01)
        assert account["posture"] == "OPEN"


class TestWindowConflictOutranksCreditShortfall:
    """PRD §3.9 — "Reservation runs the longest gate ladder in the system, and its
    ordering is load-bearing."

    The account holds exactly 100.00 AF and has all of it committed to a lease
    running `[2026-04-01, 2026-06-30)` at the first headgate, so `available_credit_af`
    is 0.00 and every further reservation must fail the credit budget. Candidates
    at the second headgate therefore isolate the ordering question.
    """

    def _fully_committed(self):
        bundle = setup_authorized_headgate_account(
            deposit_af=100.00, pod_specs=TWO_HEADGATES
        )
        get_success_data(
            reserve_lease(
                bundle["account"]["id"],
                bundle["right"]["id"],
                bundle["pods"][0]["id"],
                "2026-04-01T00:00:00Z",
                "2026-06-30T00:00:00Z",
                100.00,
                diversion_rate_cfs=2.000,
            )
        )
        return bundle

    def _candidate(self, bundle, start, end):
        return reserve_lease(
            bundle["account"]["id"],
            bundle["right"]["id"],
            bundle["pods"][1]["id"],
            start,
            end,
            10.00,
            diversion_rate_cfs=2.000,
        )

    def _assert_ledger_untouched(self, bundle):
        account = read_account(bundle["account"]["id"])
        assert account["deposited_credit_af"] == pytest.approx(100.00, abs=0.01)
        assert account["committed_credit_af"] == pytest.approx(100.00, abs=0.01)
        assert account["leased_out_af"] == pytest.approx(0.00, abs=0.01)
        assert account["available_credit_af"] == pytest.approx(0.00, abs=0.01)
        assert account["posture"] == "RESTRICTED"
        listed, _meta = validate_paginated(
            api_client.list_lease_assignments(
                ANALYST, params={"water_right_id": bundle["right"]["id"]}
            )
        )
        assert len(listed) == 1

    def test_window_conflict_is_reported_ahead_of_insufficient_credit(self):
        """PRD §3.9: "Then come the two interval rules, then the
        headgate-authorization rule, and only last the credit-budget rule — so a
        window collision, priced at priority 41, is reported in preference to
        insufficient credit, priced at priority 46, even when both are true of the
        same request."

        A candidate starting 2026-07-01 sits inside the `[2026-03-25, 2026-07-07]`
        exclusion window and also asks for credit the account does not have; the
        window error is what comes back.

        Design: Difficulty/priority_pair_validation_conflict/lease_window_conflict_beats_insufficient_credit
        """
        bundle = self._fully_committed()

        response = self._candidate(
            bundle, "2026-07-01T00:00:00Z", "2026-08-31T00:00:00Z"
        )

        validate_error(
            response, ApiErrorId.ERR_LEASE_WINDOW_CONFLICT.value, expected_status=409
        )
        self._assert_ledger_untouched(bundle)

    def test_credit_shortfall_surfaces_once_the_window_is_clear(self):
        """PRD §3.9: "`requested_af` must be no greater than the account's
        `available_credit_af`, equality accepted, otherwise
        `ERR_INSUFFICIENT_BANK_CREDIT` (422)."

        Moving the candidate one day clear of the exclusion window, to a start of
        2026-07-08, removes the higher-priority defect and leaves only the credit
        shortfall, which is now the reported error. The account was `RESTRICTED`
        throughout because PRD §2.10 restricts an account whose available credit is
        strictly below 5.00 acre-feet.

        Design: Difficulty/priority_pair_validation_conflict/lease_window_conflict_beats_insufficient_credit
        """
        bundle = self._fully_committed()

        response = self._candidate(
            bundle, "2026-07-08T00:00:00Z", "2026-09-01T00:00:00Z"
        )

        validate_error(
            response, ApiErrorId.ERR_INSUFFICIENT_BANK_CREDIT.value, expected_status=422
        )
        self._assert_ledger_untouched(bundle)
