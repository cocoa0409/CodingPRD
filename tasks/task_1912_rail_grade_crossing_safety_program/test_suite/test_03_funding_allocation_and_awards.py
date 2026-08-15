"""Funding program allocation sweep, award rounding, pool invariant, and award OCC
(PRD §2.6, §3.4)."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_funding_program,
    assert_program_pool_invariant,
    assert_upgrade_project,
    create_crossing,
    create_crossing_payload,
    create_eligible_project,
    create_locality,
    create_program,
    get_success_data,
    setup_locality_and_crossing,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
OFFICER = TEST_USERS["officer_headers"]


def _alloc_crossing(locality_id, dot, bus_count):
    """Crossing with hazard driven by its bus term (exposure 5.00, MEDIUM band):
    bus 6 -> 8.50, bus 4 -> 7.50, bus 2 -> 6.50."""
    return create_crossing(
        locality_id,
        dot_crossing_number=dot,
        annual_train_count=365,
        train_speed_max_mph=25,
        aadt=5000,
        school_bus_count=bus_count,
        sight_distance_rating=3,
        warning_device_class="GATES",
    )


class TestAllocationDualVariant:
    def test_waterfall_funds_first_rank_and_stops(self, api, admin_headers):
        """PRD §3.4: "Under `WATERFALL_BY_RANK` the sweep walks the ranking with a
        running remainder initialized to `available_cents`: each project whose
        `estimated_cost_cents` fits within the remainder is moved to `SELECTED`
        with `tentative_award_cents` set to its full `estimated_cost_cents` and the
        remainder reduced accordingly — a project whose cost exactly equals the
        remainder is funded, leaving zero — and the first project that does not fit
        stops the sweep immediately, with no skipping ahead to smaller projects."

        Design: Difficulty/dual_variant_calc/funding_allocation_waterfall_vs_proportional
        """
        locality = create_locality(locality_name="Alloc Town")
        c1 = _alloc_crossing(locality["id"], "DOT-200001", 6)   # hazard 8.50
        c2 = _alloc_crossing(locality["id"], "DOT-200002", 4)   # hazard 7.50
        c3 = _alloc_crossing(locality["id"], "DOT-200003", 2)   # hazard 6.50
        prog = create_program(
            fiscal_year=2026,
            apportionment_cents=1_000_000,
            allocation_method="WATERFALL_BY_RANK",
        )
        p1 = create_eligible_project(c1["id"], prog["id"], estimated_cost_cents=600_000)
        p2 = create_eligible_project(c2["id"], prog["id"], estimated_cost_cents=500_000)
        p3 = create_eligible_project(c3["id"], prog["id"], estimated_cost_cents=100_000)

        get_success_data(
            api.transition_funding_program(
                prog["id"], {"to_status": "ALLOCATION_LOCKED"}, admin_headers
            )
        )

        p1_after = get_success_data(api.get_upgrade_project(p1["id"], admin_headers))
        p2_after = get_success_data(api.get_upgrade_project(p2["id"], admin_headers))
        p3_after = get_success_data(api.get_upgrade_project(p3["id"], admin_headers))
        assert p1_after["status"] == "SELECTED"
        assert p1_after["tentative_award_cents"] == 600_000
        # Sweep stopped: 500000 > 400000 remaining, no skipping to smaller projects.
        assert p2_after["status"] == "ELIGIBLE"
        assert p2_after["tentative_award_cents"] is None
        assert p3_after["status"] == "ELIGIBLE"
        assert p3_after["tentative_award_cents"] is None

    def test_proportional_share_funds_every_candidate_pro_rata(
        self, api, admin_headers
    ):
        """PRD §3.4: "Under `PROPORTIONAL_SHARE` every candidate becomes `SELECTED`:
        each project's `tentative_award_cents` is the smaller of its
        `estimated_cost_cents` and the floor of `available_cents` multiplied by its
        `estimated_cost_cents` and divided by the total requested across all
        candidates, and any unallocated remainder cents stay in `available_cents`."
        PRD §2.7: "Proportional funding shares are the one place a downward rounding
        is used: each pro-rata share is the floor of the exact quotient, never
        rounded up."

        Design: Difficulty/dual_variant_calc/funding_allocation_waterfall_vs_proportional
        """
        locality = create_locality(locality_name="Alloc Town")
        c1 = _alloc_crossing(locality["id"], "DOT-200004", 6)
        c2 = _alloc_crossing(locality["id"], "DOT-200005", 4)
        c3 = _alloc_crossing(locality["id"], "DOT-200006", 2)
        prog = create_program(
            fiscal_year=2027,
            apportionment_cents=1_000_000,
            allocation_method="PROPORTIONAL_SHARE",
        )
        p1 = create_eligible_project(c1["id"], prog["id"], estimated_cost_cents=600_000)
        p2 = create_eligible_project(c2["id"], prog["id"], estimated_cost_cents=500_000)
        p3 = create_eligible_project(c3["id"], prog["id"], estimated_cost_cents=100_000)

        get_success_data(
            api.transition_funding_program(
                prog["id"], {"to_status": "ALLOCATION_LOCKED"}, admin_headers
            )
        )

        p1_after = get_success_data(api.get_upgrade_project(p1["id"], admin_headers))
        p2_after = get_success_data(api.get_upgrade_project(p2["id"], admin_headers))
        p3_after = get_success_data(api.get_upgrade_project(p3["id"], admin_headers))
        # total_requested = 1200000; floor(1000000 * cost / 1200000)
        assert p1_after["status"] == "SELECTED"
        assert p1_after["tentative_award_cents"] == 500_000
        assert p2_after["status"] == "SELECTED"
        assert p2_after["tentative_award_cents"] == 416_666
        assert p3_after["status"] == "SELECTED"
        assert p3_after["tentative_award_cents"] == 83_333


class TestWaterfallExactPoolBoundary:
    def test_project_cost_equal_to_remaining_pool_is_funded(self, api, admin_headers):
        """PRD §3.4: "each project whose `estimated_cost_cents` fits within the
        remainder is moved to `SELECTED` with `tentative_award_cents` set to its
        full `estimated_cost_cents` and the remainder reduced accordingly — a
        project whose cost exactly equals the remainder is funded, leaving zero —
        and the first project that does not fit stops the sweep immediately, with
        no skipping ahead to smaller projects."

        Design: Difficulty/boundary_precision_check/waterfall_fit_at_exact_pool
        """
        locality = create_locality(locality_name="Exact Pool City")
        cx = _alloc_crossing(locality["id"], "DOT-600101", 6)   # rank 8.50
        cy = _alloc_crossing(locality["id"], "DOT-600102", 4)   # rank 7.50
        prog = create_program(
            fiscal_year=2032,
            apportionment_cents=600_000,
            allocation_method="WATERFALL_BY_RANK",
        )
        p1 = create_eligible_project(cx["id"], prog["id"], estimated_cost_cents=600_000)
        p2 = create_eligible_project(cy["id"], prog["id"], estimated_cost_cents=1)

        get_success_data(
            api.transition_funding_program(
                prog["id"], {"to_status": "ALLOCATION_LOCKED"}, admin_headers
            )
        )

        p1_after = get_success_data(api.get_upgrade_project(p1["id"], admin_headers))
        p2_after = get_success_data(api.get_upgrade_project(p2["id"], admin_headers))
        assert p1_after["status"] == "SELECTED"
        assert p1_after["tentative_award_cents"] == 600_000
        # Remaining 0 < 1 cent: the sweep stops, p2 stays ELIGIBLE.
        assert p2_after["status"] == "ELIGIBLE"
        assert p2_after["tentative_award_cents"] is None

    def test_zero_eligible_projects_lock_succeeds_with_no_selections(
        self, api, admin_headers
    ):
        """PRD §3.4: "Locking with zero `ELIGIBLE` projects is permitted and simply
        selects nothing; either way the lock increments the program's `version`."

        Design: Difficulty/boundary_precision_check/waterfall_fit_at_exact_pool
        """
        prog = create_program(
            fiscal_year=2037,
            apportionment_cents=600_000,
            allocation_method="WATERFALL_BY_RANK",
        )
        locked = get_success_data(
            api.transition_funding_program(
                prog["id"], {"to_status": "ALLOCATION_LOCKED"}, admin_headers
            )
        )
        assert locked["status"] == "ALLOCATION_LOCKED"
        assert locked["version"] == prog["version"] + 1
        assert locked["available_cents"] == 600_000
        assert locked["encumbered_cents"] == 0
        assert locked["eligible_demand_cents"] == 0


class TestMatchSplitPerAwardRounding:
    def test_federal_share_rounded_per_line_then_summed(self, api, admin_headers):
        """PRD §3.4: "`federal_share_cents` is the awarded amount multiplied by
        0.80 and rounded half-up to whole cents, computed per award line first, and
        `state_share_cents` is the awarded amount minus the federal share;
        program-level totals are always the sum of these per-line rounded values
        and are never re-rounded in aggregate."

        Design: Difficulty/combinatorial_formula/match_split_per_award_rounding
        """
        locality = create_locality(locality_name="Split City")
        ca = _alloc_crossing(locality["id"], "DOT-300101", 6)   # rank 8.50
        cb = _alloc_crossing(locality["id"], "DOT-300102", 4)   # rank 7.50
        prog = create_program(
            fiscal_year=2030,
            apportionment_cents=1_000_000,
            allocation_method="WATERFALL_BY_RANK",
        )
        pa = create_eligible_project(ca["id"], prog["id"], estimated_cost_cents=416_666)
        pb = create_eligible_project(cb["id"], prog["id"], estimated_cost_cents=83_333)
        locked = get_success_data(
            api.transition_funding_program(
                prog["id"], {"to_status": "ALLOCATION_LOCKED"}, admin_headers
            )
        )

        pa_after = get_success_data(
            api.award_upgrade_project(
                pa["id"],
                {"expected_funding_program_version": locked["version"]},
                admin_headers,
            )
        )
        assert pa_after["awarded_cents"] == 416_666
        # round_half_up(416666 * 0.80) = round_half_up(333332.8) = 333333
        assert pa_after["federal_share_cents"] == 333_333
        assert pa_after["state_share_cents"] == 83_333

        mid = get_success_data(api.get_funding_program(prog["id"], admin_headers))
        pb_after = get_success_data(
            api.award_upgrade_project(
                pb["id"],
                {"expected_funding_program_version": mid["version"]},
                admin_headers,
            )
        )
        # round_half_up(83333 * 0.80) = round_half_up(66666.4) = 66666
        assert pb_after["federal_share_cents"] == 66_666
        assert pb_after["state_share_cents"] == 16_667

        final = get_success_data(api.get_funding_program(prog["id"], admin_headers))
        assert final["encumbered_cents"] == 416_666 + 83_333 == 499_999
        assert final["available_cents"] == 500_001
        assert_program_pool_invariant(final)

    def test_share_fields_null_until_awarded(self, api, admin_headers):
        """PRD §3.4: "A successful award sets `awarded_cents` to the effective
        amount, splits it into the 80/20 federal/state match ..." and PRD §3.4:
        "the project's `awarded_cents`, `federal_share_cents`, and
        `state_share_cents` return to `null`" (on rescind — establishing these
        fields are null before award).

        Design: Difficulty/combinatorial_formula/match_split_per_award_rounding
        """
        locality = create_locality(locality_name="Split City")
        ca = _alloc_crossing(locality["id"], "DOT-300111", 6)
        prog = create_program(fiscal_year=2038, apportionment_cents=1_000_000)
        pa = create_eligible_project(ca["id"], prog["id"], estimated_cost_cents=416_666)
        assert pa["awarded_cents"] is None
        assert pa["federal_share_cents"] is None
        assert pa["state_share_cents"] is None

        awarded = get_success_data(
            api.award_upgrade_project(
                pa["id"],
                {"expected_funding_program_version": prog["version"]},
                admin_headers,
            )
        )
        assert awarded["awarded_cents"] == 416_666
        assert awarded["federal_share_cents"] == 333_333
        assert awarded["state_share_cents"] == 83_333
        assert (
            awarded["federal_share_cents"] + awarded["state_share_cents"]
            == awarded["awarded_cents"]
        )


class TestAwardRescindRestoresPool:
    def test_award_then_rescind_restores_pool_exactly(self, api, admin_headers):
        """PRD §3.4: "Thereafter the invariant `available_cents` plus
        `encumbered_cents` equals `apportionment_cents` holds at all times".
        PRD §3.4: "A `ProgramAdministrator` rescinding an `AWARDED` project ...
        moves it back `AWARDED` → `ELIGIBLE`: the program's `available_cents` is
        increased and its `encumbered_cents` decreased by exactly the rescinded
        `awarded_cents`, restoring the pool exactly; the project's `awarded_cents`,
        `federal_share_cents`, and `state_share_cents` return to `null`; and the
        program's `version` increments."

        Design: Difficulty/compensating_invariant/award_rescind_restores_pool
        """
        locality = create_locality(locality_name="Invariant City")
        cx = _alloc_crossing(locality["id"], "DOT-900001", 6)
        prog = create_program(
            fiscal_year=2034,
            apportionment_cents=1_000_000,
            allocation_method="WATERFALL_BY_RANK",
        )
        pj = create_eligible_project(cx["id"], prog["id"], estimated_cost_cents=300_000)

        awarded = get_success_data(
            api.award_upgrade_project(
                pj["id"],
                {"expected_funding_program_version": prog["version"]},
                admin_headers,
            )
        )
        assert awarded["status"] == "AWARDED"
        assert awarded["awarded_cents"] == 300_000
        assert awarded["federal_share_cents"] == 240_000
        assert awarded["state_share_cents"] == 60_000

        mid = get_success_data(api.get_funding_program(prog["id"], admin_headers))
        assert mid["available_cents"] == 700_000
        assert mid["encumbered_cents"] == 300_000
        assert_program_pool_invariant(mid)

        rescinded = get_success_data(api.rescind_award(pj["id"], admin_headers))
        assert rescinded["status"] == "ELIGIBLE"
        assert rescinded["awarded_cents"] is None
        assert rescinded["federal_share_cents"] is None
        assert rescinded["state_share_cents"] is None

        final = get_success_data(api.get_funding_program(prog["id"], admin_headers))
        assert final["available_cents"] == 1_000_000
        assert final["encumbered_cents"] == 0
        assert_program_pool_invariant(final)
        assert final["version"] == mid["version"] + 1

    def test_rolling_award_from_eligible_in_open_program(self, api, admin_headers):
        """PRD §3.4: "The project must be `ELIGIBLE` or `SELECTED` (else
        `ERR_PROJECT_NOT_SELECTED`) — a `SELECTED` project is awarded after a lock,
        while an `ELIGIBLE` project may receive a rolling award straight from an
        `OPEN` program". PRD §3.4: "The effective award is the request's optional
        `award_cents`, defaulting to the project's `tentative_award_cents` when
        `SELECTED` and to its `estimated_cost_cents` otherwise".

        Design: Difficulty/compensating_invariant/award_rescind_restores_pool
        """
        locality = create_locality(locality_name="Rolling City")
        cx = _alloc_crossing(locality["id"], "DOT-900011", 6)
        prog = create_program(
            fiscal_year=2039,
            apportionment_cents=1_000_000,
            allocation_method="WATERFALL_BY_RANK",
        )
        assert prog["status"] == "OPEN"
        pj = create_eligible_project(cx["id"], prog["id"], estimated_cost_cents=300_000)

        awarded = get_success_data(
            api.award_upgrade_project(
                pj["id"],
                {"expected_funding_program_version": prog["version"]},
                admin_headers,
            )
        )
        # Default effective award from ELIGIBLE is estimated_cost_cents.
        assert awarded["status"] == "AWARDED"
        assert awarded["awarded_cents"] == 300_000
        mid = get_success_data(api.get_funding_program(prog["id"], admin_headers))
        assert mid["available_cents"] == 700_000
        assert_program_pool_invariant(mid)


class TestAwardOcc:
    def test_second_award_with_stale_program_version_rejected(
        self, api, admin_headers
    ):
        """PRD §2.6: "Issuing an upgrade award requires the request to carry
        `expected_funding_program_version`, a non-optional field holding the
        `version` the client last observed on the funding program. Because a prior
        award or rescind legitimately changes the program's `available_cents`, a
        mismatch with the program's current `version` means the client's view of
        the pool is stale, and the award is rejected with `ERR_STALE_VERSION`
        (HTTP 412)."

        Design: Corner/complexity_layers/award_occ_stale_program_version
        """
        locality = create_locality(locality_name="OCC Award City")
        ca = _alloc_crossing(locality["id"], "DOT-070011", 6)
        cb = _alloc_crossing(locality["id"], "DOT-070012", 4)
        prog = create_program(
            fiscal_year=2051,
            apportionment_cents=1_000_000,
            allocation_method="WATERFALL_BY_RANK",
        )
        pa = create_eligible_project(ca["id"], prog["id"], estimated_cost_cents=300_000)
        pb = create_eligible_project(cb["id"], prog["id"], estimated_cost_cents=200_000)

        awarded = get_success_data(
            api.award_upgrade_project(
                pa["id"],
                {"expected_funding_program_version": prog["version"]},
                admin_headers,
            )
        )
        assert awarded["awarded_cents"] == 300_000

        # The first award advanced the program version; replaying the stale one fails.
        resp = api.award_upgrade_project(
            pb["id"],
            {"expected_funding_program_version": prog["version"]},
            admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

        pb_after = get_success_data(api.get_upgrade_project(pb["id"], admin_headers))
        assert pb_after["status"] == "ELIGIBLE"
        assert pb_after["awarded_cents"] is None

    def test_stale_version_reported_after_state_is_confirmed(
        self, api, admin_headers
    ):
        """PRD §2.9: "5. **Optimistic concurrency** — the `expected_*_version`
        fields of §2.6 are compared here, after state is confirmed; a mismatch
        yields `ERR_STALE_VERSION`."

        Design: Corner/complexity_layers/award_occ_stale_program_version
        """
        locality = create_locality(locality_name="OCC Order City")
        ca = _alloc_crossing(locality["id"], "DOT-070021", 6)
        prog = create_program(fiscal_year=2052, apportionment_cents=1_000_000)
        pa = create_eligible_project(ca["id"], prog["id"], estimated_cost_cents=300_000)

        # Advance the program version via a legitimate lock.
        locked = get_success_data(
            api.transition_funding_program(
                pa["program_id"], {"to_status": "ALLOCATION_LOCKED"}, admin_headers
            )
        )
        # The project was SELECTED by the sweep; awarding with the pre-lock
        # version is a pure OCC mismatch (state preconditions all pass).
        assert locked["version"] == prog["version"] + 1
        resp = api.award_upgrade_project(
            pa["id"],
            {"expected_funding_program_version": prog["version"]},
            admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, expected_status=412)
