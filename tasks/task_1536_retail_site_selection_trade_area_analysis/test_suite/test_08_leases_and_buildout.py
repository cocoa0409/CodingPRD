"""Lease execution, crew scheduling with the buffer rule, and the ordered
build-out milestones (PRD §3.8)."""
from test_helpers import (
    ApiErrorId,
    approve_and_ratify,
    assert_lease,
    complete_milestones_in_order,
    create_accepted_loi,
    create_accepted_loi_site,
    create_committee_roster,
    create_crew,
    create_draft_loi,
    create_in_committee_site,
    create_lease_executed_site,
    create_lease_payload,
    create_construction_crew_payload,
    create_loi_active_site,
    create_negotiating_lease,
    create_permit_milestone_payload,
    create_qualified_market,
    create_stores,
    plan_milestones,
    validate_error,
    validate_paginated,
    validate_success,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]
MANAGER = TEST_USERS["manager_headers"]
CONSTRUCTION = TEST_USERS["construction_headers"]


class TestCrewWindowClosedIntervalBuffer:
    """L1 occupies [2026-09-01, 2026-10-15] on the crew; conflict iff the new
    start falls on or before other_end + 6 days."""

    def _setup_three_sites(self, api):
        """Three APPROVED sites with ACCEPTED LOIs, one shared crew, and lease
        L1 already holding [2026-09-01, 2026-10-15]."""
        market = create_qualified_market(name="Metro CW")
        create_stores(market["id"])
        crew = create_crew("CREW-BUF")
        # One committee roster serves all three sites (the chair is a
        # chain-wide singleton).
        roster = create_committee_roster(num_voters=3)
        lois = []
        for i, window in enumerate((
            ("2026-09-01", "2026-10-01"),
            ("2026-09-15", "2026-12-15"),
            ("2026-10-01", "2027-01-01"),
        )):
            ctx = create_in_committee_site(
                market_id=market["id"], stores=None, roster=roster,
                site_overrides={"address": f"{i + 1} Ave"},
            )
            approve_and_ratify(
                ctx["review"]["id"], ctx["roster"]["chair"]["id"],
                [v["id"] for v in ctx["roster"]["voters"]],
            )
            lois.append(create_accepted_loi(
                ctx["site"]["id"], exclusivity_start_date=window[0],
                exclusivity_end_date=window[1],
            ))
        lease1 = create_negotiating_lease(lois[0]["id"], crew["id"])
        return market, crew, lois, lease1

    def test_gap_of_exactly_seven_days_allowed(self, api):
        """PRD §3.8: "Crew scheduling respects a buffer rule: the new window,
        treated as a closed interval, conflicts with any other lease in
        `NEGOTIATING` or `EXECUTED` on the same crew when the new window's
        start falls on or before six days after the other window's end —
        equivalently, consecutive windows on one crew must leave a gap of at
        least seven days, and a gap of exactly seven days is permitted."

        Design: Difficulty/resource_temporal_overlap/crew_window_closed_interval_buffer
        """
        _market, crew, lois, lease1 = self._setup_three_sites(api)
        assert lease1["lease_status"] == "NEGOTIATING"
        # 2026-10-22 is exactly 7 days after L1's 2026-10-15 end.
        lease2 = create_negotiating_lease(
            lois[1]["id"], crew["id"], build_start_date="2026-10-22",
            build_end_date="2026-11-30",
        )
        assert_lease(lease2)
        assert lease2["lease_status"] == "NEGOTIATING"

    def test_gap_of_six_days_conflicts(self, api):
        """PRD §3.8: "A conflict is rejected with `ERR_CREW_WINDOW_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/crew_window_closed_interval_buffer
        """
        _market, crew, lois, lease1 = self._setup_three_sites(api)
        lease2 = create_negotiating_lease(
            lois[1]["id"], crew["id"], build_start_date="2026-10-22",
            build_end_date="2026-11-30",
        )
        assert lease2["lease_status"] == "NEGOTIATING"
        # 2026-10-21 <= 2026-10-15 + 6 days -> conflict.
        resp = api.create_lease(
            create_lease_payload(loi_id=lois[2]["id"], crew_id=crew["id"],
                                 build_start_date="2026-10-21",
                                 build_end_date="2026-11-30"),
            MANAGER,
        )
        validate_error(resp, ApiErrorId.ERR_CREW_WINDOW_CONFLICT)


class TestTemporalBeatsReferentialOnLeaseCreate:
    """Lease create both conflicts with the crew's buffered window and
    references a DRAFT LOI; the temporal layer outranks the referential one."""

    def _setup(self, api):
        market = create_qualified_market(name="Metro TR")
        create_stores(market["id"])
        # One roster for both deals (the chair is a chain-wide singleton).
        roster = create_committee_roster(num_voters=3)
        roster_ctx = create_in_committee_site(
            market_id=market["id"], stores=None, roster=roster,
            site_overrides={"address": "1 First Ave"},
        )
        approve_and_ratify(
            roster_ctx["review"]["id"], roster_ctx["roster"]["chair"]["id"],
            [v["id"] for v in roster_ctx["roster"]["voters"]],
        )
        loi1 = create_accepted_loi(roster_ctx["site"]["id"])
        crew = create_crew("CREW-X")
        lease1 = create_negotiating_lease(loi1["id"], crew["id"])
        # Second site: fully approved, but its LOI stays DRAFT (never sent).
        ctx2 = create_in_committee_site(
            market_id=market["id"], stores=None, roster=roster,
            site_overrides={"address": "2 Second Ave"},
        )
        approve_and_ratify(
            ctx2["review"]["id"], ctx2["roster"]["chair"]["id"],
            [v["id"] for v in ctx2["roster"]["voters"]],
        )
        loi2 = create_draft_loi(
            ctx2["site"]["id"], exclusivity_start_date="2026-11-01",
            exclusivity_end_date="2026-12-01",
        )
        return crew, lease1, loi2

    def test_crew_conflict_error_wins_over_loi_not_accepted(self, api):
        """PRD §2.7: "Every request is validated against the following layers
        in the order listed; a failure at an earlier layer is reported and
        masks any failure a later layer would have produced."
        PRD §3.8: "Crew scheduling respects a buffer rule: the new window,
        treated as a closed interval, conflicts with any other lease in
        `NEGOTIATING` or `EXECUTED` on the same crew when the new window's
        start falls on or before six days after the other window's end"

        Design: Difficulty/priority_pair_validation_conflict/temporal_beats_referential_on_lease_create
        """
        crew, _lease1, loi2 = self._setup(api)
        # 2026-10-10 <= L1 end 2026-10-15 + 6 days (temporal) AND LOI2 is DRAFT
        # (referential); the temporal layer fires first.
        resp = api.create_lease(
            create_lease_payload(loi_id=loi2["id"], crew_id=crew["id"],
                                 final_rent_psf_cents=2000,
                                 build_start_date="2026-10-10",
                                 build_end_date="2026-11-10"),
            MANAGER,
        )
        validate_error(resp, ApiErrorId.ERR_CREW_WINDOW_CONFLICT)

    def test_rejected_create_leaves_no_lease(self, api):
        """PRD §3.8: "From an `ACCEPTED` LOI — anything else is rejected with
        `ERR_LOI_NOT_ACCEPTED` — the manager drafts a lease"
        PRD §2.3: "leases by `loi_id`, `crew_id`, and `lease_status`"

        Design: Difficulty/priority_pair_validation_conflict/temporal_beats_referential_on_lease_create
        """
        crew, _lease1, loi2 = self._setup(api)
        resp = api.create_lease(
            create_lease_payload(loi_id=loi2["id"], crew_id=crew["id"],
                                 final_rent_psf_cents=2000,
                                 build_start_date="2026-10-10",
                                 build_end_date="2026-11-10"),
            MANAGER,
        )
        validate_error(resp, ApiErrorId.ERR_CREW_WINDOW_CONFLICT)
        _leases, meta = validate_paginated(
            api.list_leases(MANAGER, params={"loi_id": loi2["id"]})
        )
        assert meta["total_count"] == 0
        reloaded = validate_success(api.get_loi(loi2["id"], MANAGER))
        assert reloaded["loi_status"] == "DRAFT"


class TestLeaseGates:
    def test_error_lease_terms_drift(self, api):
        """PRD §3.8: "Executing the lease performs the drift check: the
        `final_rent_psf_cents` may not exceed the source LOI's
        `agreed_rent_psf_cents` by more than five percent — the ceiling is the
        agreed rent multiplied by 10,500 and divided by 10,000, rounded half-up
        to whole cents, and the boundary is inclusive; drift beyond the ceiling
        is rejected with `ERR_LEASE_TERMS_DRIFT`."

        Design: Corner/errors/error_lease_terms_drift
        """
        ctx = create_accepted_loi_site()
        assert ctx["loi"]["agreed_rent_psf_cents"] == 2000
        crew = create_crew("CREW-LD")
        # Create succeeds (drift is checked at execute): 2101 > 2100 ceiling.
        lease = create_negotiating_lease(
            ctx["loi"]["id"], crew["id"], final_rent_psf_cents=2101,
        )
        resp = api.execute_lease(lease["id"], MANAGER)
        validate_error(resp, ApiErrorId.ERR_LEASE_TERMS_DRIFT)
        reloaded = validate_success(api.get_lease(lease["id"], MANAGER))
        assert reloaded["lease_status"] == "NEGOTIATING"
        site = validate_success(api.get_site(ctx["site"]["id"], MANAGER))
        assert site["site_status"] == "LOI_ACTIVE"

    def test_error_loi_not_accepted_on_lease_create(self, api):
        """PRD §3.8: "From an `ACCEPTED` LOI — anything else is rejected with
        `ERR_LOI_NOT_ACCEPTED` — the manager drafts a lease"

        Design: Corner/errors/error_loi_not_accepted_on_lease_create
        """
        ctx = create_loi_active_site()
        crew = create_crew("CREW-LA")
        resp = api.create_lease(
            create_lease_payload(loi_id=ctx["loi"]["id"], crew_id=crew["id"],
                                 final_rent_psf_cents=2000,
                                 build_start_date="2026-11-01",
                                 build_end_date="2026-12-01"),
            MANAGER,
        )
        validate_error(resp, ApiErrorId.ERR_LOI_NOT_ACCEPTED)

    def test_error_crew_not_available_after_retire(self, api):
        """PRD §3.8: "Retiring a crew moves it to `RETIRED`: leases already
        holding that crew's windows keep them, but any new lease naming a
        `RETIRED` crew is rejected with `ERR_CREW_NOT_AVAILABLE`."

        Design: Corner/errors/error_crew_not_available_after_retire
        """
        ctx = create_accepted_loi_site()
        crew = create_crew("CREW-RT")
        retired = validate_success(api.retire_construction_crew(crew["id"], ADMIN))
        assert retired["crew_status"] == "RETIRED"
        resp = api.create_lease(
            create_lease_payload(loi_id=ctx["loi"]["id"], crew_id=crew["id"],
                                 final_rent_psf_cents=2000,
                                 build_start_date="2026-11-01",
                                 build_end_date="2026-12-01"),
            MANAGER,
        )
        validate_error(resp, ApiErrorId.ERR_CREW_NOT_AVAILABLE)

    def test_error_crew_code_taken(self, api):
        """PRD §3.8: "A `PlatformAdmin` registers a crew with a chain-wide
        unique `crew_code` (case-sensitive; collisions are rejected with
        `ERR_CREW_CODE_TAKEN`); the crew begins with `crew_status` of
        `ACTIVE`."

        Design: Corner/errors/error_crew_code_taken
        """
        first = api.create_construction_crew(
            create_construction_crew_payload(crew_code="CREW-X"), ADMIN,
        )
        validate_success(first, expected_status=201)
        second = api.create_construction_crew(
            create_construction_crew_payload(crew_code="CREW-X"), ADMIN,
        )
        validate_error(second, ApiErrorId.ERR_CREW_CODE_TAKEN)


class TestMilestoneOrdering:
    def test_milestone_completion_order_enforced(self, api):
        """PRD §3.8: "Completing a milestone records its `actual_date` and
        moves it to `COMPLETED`, but only in type order: every lower-order
        milestone of the same site must already be `COMPLETED`, else
        `ERR_MILESTONE_OUT_OF_ORDER`."
        PRD §3.8: "Completing `BUILD_START` bubbles the site from
        `LEASE_EXECUTED` to `BUILD_OUT`."

        Design: Corner/state_machines/milestone_completion_order_enforced
        """
        ctx = create_lease_executed_site(crew_code="CREW-M1")
        milestones = plan_milestones(
            ctx["site"]["id"],
            types={"PERMIT_SUBMITTED", "PERMIT_APPROVED", "BUILD_START"},
        )
        # BUILD_START first: both lower-order milestones still PENDING.
        resp = api.complete_permit_milestone(
            milestones["BUILD_START"]["id"], {"actual_date": "2026-10-01"},
            CONSTRUCTION,
        )
        validate_error(resp, ApiErrorId.ERR_MILESTONE_OUT_OF_ORDER)
        complete_milestones_in_order(milestones, through="BUILD_START")
        done = validate_success(api.get_permit_milestone(
            milestones["BUILD_START"]["id"], CONSTRUCTION,
        ))
        assert done["milestone_status"] == "COMPLETED"
        assert done["actual_date"] == "2026-10-01"
        site = validate_success(api.get_site(ctx["site"]["id"], MANAGER))
        assert site["site_status"] == "BUILD_OUT"

    def test_duplicate_milestone_type_rejected(self, api):
        """PRD §3.8: "Each milestone carries the `site_id`, its
        `milestone_type`, and a `planned_date`, begins `PENDING` with its
        `actual_date` unset, and at most one milestone of each type may exist
        per site — a duplicate is rejected with `ERR_DUPLICATE_MILESTONE`."

        Design: Corner/state_machines/duplicate_milestone_type_rejected
        """
        ctx = create_lease_executed_site(crew_code="CREW-M2")
        first = api.create_permit_milestone(
            create_permit_milestone_payload(site_id=ctx["site"]["id"]),
            CONSTRUCTION,
        )
        validate_success(first, expected_status=201)
        second = api.create_permit_milestone(
            create_permit_milestone_payload(site_id=ctx["site"]["id"],
                                            planned_date="2026-09-06"),
            CONSTRUCTION,
        )
        validate_error(second, ApiErrorId.ERR_DUPLICATE_MILESTONE)

    def test_error_build_not_complete_on_open(self, api):
        """PRD §3.8: "Opening the store is the manager's final construction
        gate: the site's `BUILD_COMPLETE` milestone must be `COMPLETED`, else
        `ERR_BUILD_NOT_COMPLETE`."

        Design: Corner/errors/error_build_not_complete_on_open
        """
        ctx = create_lease_executed_site(crew_code="CREW-BC")
        milestones = plan_milestones(ctx["site"]["id"])
        # Complete the first three only; BUILD_COMPLETE stays PENDING.
        complete_milestones_in_order(milestones, through="BUILD_START")
        site = validate_success(api.get_site(ctx["site"]["id"], MANAGER))
        assert site["site_status"] == "BUILD_OUT"
        resp = api.open_site(ctx["site"]["id"], MANAGER)
        validate_error(resp, ApiErrorId.ERR_BUILD_NOT_COMPLETE)
        after = validate_success(api.get_site(ctx["site"]["id"], MANAGER))
        assert after["site_status"] == "BUILD_OUT"
