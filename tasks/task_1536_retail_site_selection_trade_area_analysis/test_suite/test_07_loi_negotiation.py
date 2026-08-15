"""LOI negotiation (PRD §3.7): pinned effective-rent sequence, the
SENT->COUNTERED->SENT cycle, half-open exclusivity windows, clock gates, and
terminal lockdown."""
from test_helpers import (
    ApiErrorId,
    accept_loi,
    assert_loi,
    create_accepted_loi,
    create_approved_site,
    create_draft_loi,
    create_in_committee_site,
    create_loi_active_site,
    create_loi_payload,
    create_sent_loi,
    get_success_data,
    send_loi,
    validate_error,
    validate_paginated,
    validate_success,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]
MANAGER = TEST_USERS["manager_headers"]
CONSTRUCTION = TEST_USERS["construction_headers"]


class TestEffectiveRentPinnedRounding:
    """Nested rounding order: per-year psf rounded to whole cents before
    multiplying by sqft; year-1 monthly rounded before free-rent value."""

    def test_effective_rent_at_send_uses_pinned_sequence(self, api):
        """PRD §3.7: "Year one's per-square-foot rate is the given
        `rent_psf_cents`; each subsequent year's rate is the prior year's rate
        increased by the escalation fraction (`escalation_pct_bp`
        ten-thousandths), rounded half-up to whole cents before the next year
        is derived."
        PRD §3.7: "Year one's monthly rent is year one's rent divided by
        twelve, rounded half-up to whole cents, and the free-rent value is that
        monthly figure multiplied by `free_rent_months`. The total contract
        rent is the sum of all years' rents minus the `ti_allowance_cents`
        minus the free-rent value, and the effective annual rent is that total
        divided by `term_years`, rounded half-up to whole cents."

        Design: Difficulty/combinatorial_formula/loi_effective_rent_pinned_rounding
        """
        ctx = create_approved_site()
        loi = create_draft_loi(ctx["site"]["id"])
        loi = send_loi(loi["id"])
        assert_loi(loi)
        # psf 2000/2040/2081 -> rents 20000000/20400000/20810000; monthly
        # year-1 rounds to 1666667; free value 3333334; total 57376666; /3.
        assert loi["effective_annual_rent_cents"] == 19125555
        assert loi["loi_status"] == "SENT"

    def test_first_send_bubbles_site_to_loi_active(self, api):
        """PRD §3.7: "Sending a `DRAFT` LOI re-checks the exclusivity overlap
        and the end-date clock gate, computes the `effective_annual_rent_cents`
        (below), and moves the LOI to `SENT`; the first LOI of a site to reach
        `SENT` bubbles the site from `APPROVED` to `LOI_ACTIVE`."

        Design: Difficulty/combinatorial_formula/loi_effective_rent_pinned_rounding
        """
        ctx = create_approved_site()
        assert ctx["site"]["site_status"] == "APPROVED"
        loi = create_sent_loi(ctx["site"]["id"])
        assert loi["loi_status"] == "SENT"
        site = validate_success(api.get_site(ctx["site"]["id"], MANAGER))
        assert site["site_status"] == "LOI_ACTIVE"


class TestLoiCounterResendCycle:
    def test_send_then_counter_records_landlord_terms(self, api):
        """PRD §3.7: "A landlord's reply is recorded as a counter: the LOI
        moves from `SENT` to `COUNTERED` and stores the landlord's year-one
        figure in `countered_rent_psf_cents`."

        Design: Difficulty/non_linear_state_machine/loi_counter_resend_cycle
        """
        ctx = create_approved_site()
        loi = create_sent_loi(ctx["site"]["id"])
        countered = validate_success(
            api.counter_loi(loi["id"], {"countered_rent_psf_cents": 2200},
                            MANAGER)
        )
        assert countered["loi_status"] == "COUNTERED"
        assert countered["countered_rent_psf_cents"] == 2200

    def test_resend_increments_round_and_accept_pins_resend_rent(self, api):
        """PRD §3.7: "The broker may then re-send with revised terms, moving
        the LOI from `COUNTERED` back to `SENT`: `round_number` increments by
        one, `rent_psf_cents` is replaced by the resend input,
        `countered_rent_psf_cents` is cleared back to unset, and the effective
        rent is recomputed."
        PRD §3.7: "accepting from `SENT` pins the broker's own
        `rent_psf_cents`, while accepting from `COUNTERED` pins the landlord's
        `countered_rent_psf_cents` — the counter is what is being accepted."

        Design: Difficulty/non_linear_state_machine/loi_counter_resend_cycle
        """
        ctx = create_approved_site()
        loi = create_sent_loi(ctx["site"]["id"])
        validate_success(
            api.counter_loi(loi["id"], {"countered_rent_psf_cents": 2200},
                            MANAGER)
        )
        resent = validate_success(
            api.resend_loi(loi["id"], {"rent_psf_cents": 2100}, MANAGER)
        )
        assert resent["loi_status"] == "SENT"
        assert resent["round_number"] == 2
        assert resent.get("countered_rent_psf_cents") is None
        # psf 2100/2142/2185 -> rents 21000000/21420000/21850000; monthly
        # 1750000; free 3500000; total 60270000; /3.
        assert resent["effective_annual_rent_cents"] == 20090000
        accepted = accept_loi(loi["id"])
        assert accepted["loi_status"] == "ACCEPTED"
        assert accepted["agreed_rent_psf_cents"] == 2100, (
            "accept from the second SENT pins the resend rent, not the "
            "first-send rent"
        )


class TestLoiExclusivityHalfOpen:
    def _site_with_sent_loi(self, api):
        ctx = create_approved_site()
        loi_a = create_sent_loi(ctx["site"]["id"])
        return ctx, loi_a

    def test_adjacent_window_allowed(self, api):
        """PRD §3.7: "The window is half-open: it includes the start date and
        excludes the end date, so two windows that merely touch — one beginning
        exactly where another ends — do not overlap."

        Design: Difficulty/resource_temporal_overlap/loi_exclusivity_half_open_adjacency
        """
        ctx, loi_a = self._site_with_sent_loi(api)
        resp = api.create_loi(
            create_loi_payload(site_id=ctx["site"]["id"], rent_psf_cents=1950,
                               exclusivity_start_date="2026-10-01",
                               exclusivity_end_date="2026-11-01"),
            MANAGER,
        )
        loi_b = validate_success(resp, expected_status=201)
        assert loi_b["loi_status"] == "DRAFT"
        reloaded_a = validate_success(api.get_loi(loi_a["id"], MANAGER))
        assert reloaded_a["loi_status"] == "SENT"

    def test_overlapping_window_rejected(self, api):
        """PRD §3.7: "No other LOI of the same site in `SENT`, `COUNTERED`, or
        `ACCEPTED` may have a window intersecting the new one, and this overlap
        check runs both at creation and again at send time; a violation is
        rejected with `ERR_LOI_EXCLUSIVITY_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/loi_exclusivity_half_open_adjacency
        """
        ctx, _loi_a = self._site_with_sent_loi(api)
        resp = api.create_loi(
            create_loi_payload(site_id=ctx["site"]["id"], rent_psf_cents=1975,
                               exclusivity_start_date="2026-09-30",
                               exclusivity_end_date="2026-10-30"),
            MANAGER,
        )
        validate_error(resp, ApiErrorId.ERR_LOI_EXCLUSIVITY_OVERLAP)


class TestConstraintBeatsTemporalOnLoiCreate:
    """New LOI window both overlaps an active LOI and ends before the logical
    clock; the uniqueness/constraint layer outranks the temporal layer."""

    def _setup(self, api):
        ctx = create_loi_active_site()
        get_success_data(api.set_current_utc("2026-09-20T00:00:00Z", ADMIN))
        return ctx

    def test_overlap_error_wins_over_window_in_past(self, api):
        """PRD §2.7: "Every request is validated against the following layers
        in the order listed; a failure at an earlier layer is reported and
        masks any failure a later layer would have produced."
        PRD §3.7: "No other LOI of the same site in `SENT`, `COUNTERED`, or
        `ACCEPTED` may have a window intersecting the new one, and this overlap
        check runs both at creation and again at send time; a violation is
        rejected with `ERR_LOI_EXCLUSIVITY_OVERLAP`."

        Design: Difficulty/priority_pair_validation_conflict/constraint_beats_temporal_on_loi_create
        """
        ctx = self._setup(api)
        # Window [2026-08-15, 2026-09-15) intersects LOI A's [2026-09-01,
        # 2026-10-01) AND ends before the 2026-09-20 logical clock.
        resp = api.create_loi(
            create_loi_payload(site_id=ctx["site"]["id"], rent_psf_cents=1900,
                               exclusivity_start_date="2026-08-15",
                               exclusivity_end_date="2026-09-15"),
            MANAGER,
        )
        validate_error(resp, ApiErrorId.ERR_LOI_EXCLUSIVITY_OVERLAP)

    def test_active_loi_not_swept_before_its_end(self, api):
        """PRD §2.8: "Applying a new time fires every time-based transition
        whose deadline is strictly before the new time. Every LOI in `SENT` or
        `COUNTERED` whose exclusivity end date has been passed moves to
        `EXPIRED`."

        Design: Difficulty/priority_pair_validation_conflict/constraint_beats_temporal_on_loi_create
        """
        ctx = self._setup(api)
        # Clock 2026-09-20 has not passed LOI A's 2026-10-01 end: no sweep.
        reloaded = validate_success(api.get_loi(ctx["loi"]["id"], MANAGER))
        assert reloaded["loi_status"] == "SENT"


class TestLoiCreateGateAndShape:
    def test_loi_create_requires_site_approved_state(self, api):
        """PRD §3.7: "An LOI may be created for a site in `APPROVED` or
        `LOI_ACTIVE` (else `ERR_INVALID_STATE`)"

        Design: Difficulty/cross_entity_state_dependency/loi_create_requires_site_approved
        """
        ctx = create_in_committee_site()
        assert ctx["site"]["site_status"] == "IN_COMMITTEE"
        resp = api.create_loi(create_loi_payload(site_id=ctx["site"]["id"]),
                              MANAGER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_rejected_loi_create_leaves_review_open(self, api):
        """PRD §3.7: "An LOI may be created for a site in `APPROVED` or
        `LOI_ACTIVE` (else `ERR_INVALID_STATE`)"
        PRD §2.3: "LOIs by `site_id` and `loi_status`"

        Design: Difficulty/cross_entity_state_dependency/loi_create_requires_site_approved
        """
        ctx = create_in_committee_site()
        resp = api.create_loi(create_loi_payload(site_id=ctx["site"]["id"]),
                              MANAGER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        review = validate_success(
            api.get_committee_review(ctx["review"]["id"], MANAGER)
        )
        assert review["review_status"] == "OPEN"
        _lois, meta = validate_paginated(
            api.list_lois(MANAGER, params={"site_id": ctx["site"]["id"]})
        )
        assert meta["total_count"] == 0

    def test_loi_create_rejects_inverted_window(self, api):
        """PRD §2.7: "Then the request body itself is checked — required fields
        present, types correct, enum membership, date ordering (an exclusivity
        end date must be strictly after its start date; a build end date
        strictly after its start date), and numeric ranges per the entity
        constraints of §3; violations yield `ERR_INVALID_REQUEST` (400)."

        Design: Corner/validations/loi_create_rejects_inverted_window
        """
        ctx = create_approved_site()
        resp = api.create_loi(
            create_loi_payload(site_id=ctx["site"]["id"],
                               exclusivity_start_date="2026-10-01",
                               exclusivity_end_date="2026-10-01"),
            MANAGER,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestLoiClockGatesAndTerminal:
    def test_error_window_in_past_default_clock(self, api):
        """PRD §3.7: "Creation also requires the end date to be strictly after
        the logical clock's current date, else `ERR_WINDOW_IN_PAST`."
        PRD §2.8: "At server startup, before any clock operation, the logical
        clock reads exactly 2026-08-01T00:00:00Z, and it must not fall back to
        wall-clock time under any circumstance."

        Design: Corner/errors/error_window_in_past_default_clock
        """
        ctx = create_approved_site()
        resp = api.create_loi(
            create_loi_payload(site_id=ctx["site"]["id"],
                               exclusivity_start_date="2026-06-01",
                               exclusivity_end_date="2026-07-01"),
            MANAGER,
        )
        validate_error(resp, ApiErrorId.ERR_WINDOW_IN_PAST)

    def test_accept_terminal_loi_returns_already_terminal(self, api):
        """PRD §2.10: "No mutation endpoint accepts a resource that has reached
        a terminal state; the attempt is rejected with `ERR_ALREADY_TERMINAL`
        (HTTP 409)."
        PRD §3.7: "accepting from `SENT` pins the broker's own
        `rent_psf_cents`, while accepting from `COUNTERED` pins the landlord's
        `countered_rent_psf_cents` — the counter is what is being accepted."

        Design: Corner/state_machines/accept_terminal_loi_returns_already_terminal
        """
        ctx = create_approved_site()
        loi = create_accepted_loi(ctx["site"]["id"])
        assert loi["agreed_rent_psf_cents"] == 2000
        resp = api.accept_loi(loi["id"], MANAGER)
        validate_error(resp, ApiErrorId.ERR_ALREADY_TERMINAL)
        reloaded = validate_success(api.get_loi(loi["id"], MANAGER))
        assert reloaded["loi_status"] == "ACCEPTED"
        assert reloaded["agreed_rent_psf_cents"] == 2000

    def test_loi_expiry_clock_sweep(self, api):
        """PRD §2.8: "Applying a new time fires every time-based transition
        whose deadline is strictly before the new time. Every LOI in `SENT` or
        `COUNTERED` whose exclusivity end date has been passed moves to
        `EXPIRED`."
        PRD §2.10: "No mutation endpoint accepts a resource that has reached a
        terminal state; the attempt is rejected with `ERR_ALREADY_TERMINAL`
        (HTTP 409)."

        Design: Corner/state_machines/loi_expiry_clock_sweep
        """
        ctx = create_approved_site()
        loi = create_sent_loi(ctx["site"]["id"])
        get_success_data(api.set_current_utc("2026-10-02T00:00:00Z", ADMIN))
        reloaded = validate_success(api.get_loi(loi["id"], MANAGER))
        assert reloaded["loi_status"] == "EXPIRED"
        resp = api.accept_loi(loi["id"], MANAGER)
        validate_error(resp, ApiErrorId.ERR_ALREADY_TERMINAL)


class TestLoiRbac:
    def test_construction_manager_cannot_send_loi(self, api):
        """PRD §4: the `POST /api/lois/{id}/send` row authorizes only
        "RealEstateManager".
        PRD §2.1: "If the role is declared but not listed among the roles
        authorized for the endpoint, the request is rejected with
        `ERR_FORBIDDEN_ROLE` (HTTP 403)."

        Design: Corner/rbac/construction_manager_cannot_send_loi
        """
        ctx = create_approved_site()
        loi = create_draft_loi(ctx["site"]["id"])
        resp = api.send_loi(loi["id"], CONSTRUCTION)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
        reloaded = validate_success(api.get_loi(loi["id"], MANAGER))
        assert reloaded["loi_status"] == "DRAFT"
