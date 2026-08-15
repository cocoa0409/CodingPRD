"""Personal property holds/disposal and municipal registration / violation cure."""
from test_helpers import ApiErrorId, validate_error, validate_success
from test_helpers.factories import create_registration_payload
from test_helpers.fixtures import (
    assign_work_order,
    complete_work_order,
    create_code_violation,
    create_disposition,
    create_registration,
    create_work_order,
    run_daily_sweep,
    set_clock,
    setup_active_registration,
    setup_portfolio,
    start_work_order,
    submit_work_order,
    upload_minimum_photos,
)
from test_helpers.test_users import TEST_USERS, make_field_crew_headers, make_servicer_headers

ADMIN = TEST_USERS["vendor_admin_headers"]
QA = TEST_USERS["quality_reviewer_headers"]


class TestPersonalPropertyHold:
    def test_personal_property_initial_state_in_hold(self, api):
        """PRD: "Creation stamps `documented_date` from the logical clock's date and
        computes `hold_until_date` by adding the statutory hold to that date: 30
        days when the property's `state_code` is OH, 28 days for MI, and 30 days for
        every other state. The record starts `IN_HOLD`."

        Design: Corner/state_machines/personal_property_initial_state_in_hold
        """
        ctx = setup_portfolio(with_allowable=False)
        resp = api.create_disposition(
            {"property_id": ctx["property_id"], "description": "sofa and boxes",
             "valuation_cents": 12000},
            make_field_crew_headers(ctx["crew_id"]))
        disp = validate_success(resp, expected_status=201)
        assert disp["status"] == "IN_HOLD"
        assert disp["documented_date"] == "2026-08-01"
        assert disp["hold_until_date"] == "2026-08-31", (
            f"OH 30-day hold from 2026-08-01 lands 2026-08-31, got {disp['hold_until_date']}")

    def test_hold_release_eligible_boundary(self, api):
        """PRD: "a disposition in `IN_HOLD` whose `hold_until_date` is on or before
        the clock date moves to `RELEASE_ELIGIBLE` — the boundary is inclusive, so
        the hold day itself releases."

        Design: Corner/calculations/hold_release_eligible_boundary
        """
        ctx = setup_portfolio(with_allowable=False)
        disp = create_disposition(ctx["property_id"], crew_id=ctx["crew_id"],
                                  description="tools", valuation_cents=8000)
        set_clock("2026-08-30T00:00:00Z")
        run_daily_sweep()
        early = validate_success(api.get_disposition(disp["id"], ADMIN))
        assert early["status"] == "IN_HOLD", f"one day before hold_until keeps IN_HOLD, got {early['status']}"
        set_clock("2026-08-31T00:00:00Z")
        sweep = run_daily_sweep()
        on_day = validate_success(api.get_disposition(disp["id"], ADMIN))
        assert on_day["status"] == "RELEASE_ELIGIBLE", (
            f"the hold day itself releases, got {on_day['status']}")
        assert disp["id"] in sweep["released_disposition_ids"], "sweep enumerates the release"

    def test_authorize_during_hold_rejected(self, api):
        """PRD: "An attempt while the record is still `IN_HOLD` is rejected with
        `ERR_HOLD_PERIOD_ACTIVE`".

        Design: Corner/errors/authorize_during_hold_rejected
        """
        ctx = setup_portfolio(with_allowable=False)
        disp = create_disposition(ctx["property_id"], crew_id=ctx["crew_id"],
                                  description="boxes of clothes", valuation_cents=5000)
        set_clock("2026-08-20T00:00:00Z")
        resp = api.authorize_disposal(disp["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_HOLD_PERIOD_ACTIVE)

    def test_high_value_disposal_authority_boundary(self, api):
        """PRD: "when `valuation_cents` is at least 50,000 cents, the authorizer
        must be a `Servicer` — a `VendorAdmin` attempt is rejected with
        `ERR_DISPOSAL_AUTHORITY_LIMIT`. Authorization records the acting identity in
        `authorized_by_user_id`."

        Design: Corner/errors/high_value_disposal_authority_boundary
        """
        ctx = setup_portfolio(with_allowable=False)
        disp = create_disposition(ctx["property_id"], crew_id=ctx["crew_id"],
                                  description="riding mower", valuation_cents=60000)
        set_clock("2026-08-31T00:00:00Z")
        run_daily_sweep()
        blocked = api.authorize_disposal(disp["id"], ADMIN)
        validate_error(blocked, ApiErrorId.ERR_DISPOSAL_AUTHORITY_LIMIT)
        authorized = validate_success(api.authorize_disposal(
            disp["id"], make_servicer_headers(ctx["servicer_id"])))
        assert authorized["status"] == "DISPOSAL_AUTHORIZED"
        assert authorized["authorized_by_user_id"] == ctx["servicer_id"], (
            "the acting servicer identity is recorded")


class TestRegistrationOverlap:
    def _setup_registrations(self, api):
        ctx = setup_portfolio(with_allowable=False, with_crew=False,
                              clock="2026-03-01T00:00:00Z",
                              property_overrides={"heating_system": "NONE", "fixture_count": 4})
        r1 = create_registration(ctx["property_id"], registration_number="REG-1",
                                 valid_from="2026-01-01", valid_to="2026-07-01")
        validate_success(api.activate_registration(r1["id"], ADMIN))
        r2 = create_registration(ctx["property_id"], registration_number="REG-2",
                                 valid_from="2026-07-01", valid_to="2027-01-01")
        r3 = create_registration(ctx["property_id"], registration_number="REG-3",
                                 valid_from="2026-06-30", valid_to="2026-12-01")
        return ctx, r1, r2, r3

    def test_registration_adjacent_window_activates(self, api):
        """PRD: "Pure adjacency — one window's start equalling the other's end — is
        not an overlap and activates cleanly."

        Design: Difficulty/resource_temporal_overlap/registration_half_open_adjacency
        """
        _ctx, _r1, r2, _r3 = self._setup_registrations(api)
        activated = validate_success(api.activate_registration(r2["id"], ADMIN))
        assert activated["status"] == "ACTIVE", "adjacency at 2026-07-01 is not an overlap"

    def test_registration_one_day_overlap_rejected(self, api):
        """PRD: "the windows overlap when this registration's `valid_from` falls
        before the other's `valid_to` while this registration's `valid_to` falls
        after the other's `valid_from`, and an overlap is rejected with
        `ERR_REGISTRATION_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/registration_half_open_adjacency
        """
        _ctx, _r1, _r2, r3 = self._setup_registrations(api)
        resp = api.activate_registration(r3["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_REGISTRATION_OVERLAP)

    def test_registration_activate_twice_returns_invalid_state(self, api):
        """PRD: "Activation — `PENDING → ACTIVE`, by a `VendorAdmin`" — an already
        ACTIVE registration is out of the from-state, so "failures surface as
        `ERR_INVALID_STATE`".

        Design: Corner/state_machines/registration_activate_twice_returns_invalid_state
        """
        ctx = setup_portfolio(with_allowable=False, with_crew=False,
                              property_overrides={"heating_system": "NONE", "fixture_count": 4})
        reg = create_registration(ctx["property_id"], registration_number="REG-Z1")
        validate_success(api.activate_registration(reg["id"], ADMIN))
        resp = api.activate_registration(reg["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestCureStartGatePriority:
    def _setup_cure_without_registration(self, api):
        ctx = setup_portfolio(item_code="CODE_CURE",
                              allowable_overrides={
                                  "max_per_occurrence_cents": 50000,
                                  "max_occurrences_per_calendar_year": 10,
                                  "aggregate_cap_cents_per_property_year": 400000,
                                  "requires_bid_over_cents": 99999999},
                              property_overrides={"heating_system": "NONE", "fixture_count": 4},
                              clock="2026-08-05T00:00:00Z")
        cv = create_code_violation(ctx["property_id"], citation_number="CV-200",
                                   violation_class="MAJOR", daily_fine_cents=1000,
                                   fine_cap_cents=100000, cure_deadline="2026-08-10")
        wo = create_work_order(ctx["property_id"], ctx["servicer_id"],
                               order_type="CODE_CURE", due_date="2026-08-09",
                               code_violation_id=cv["id"])
        set_clock("2026-08-14T00:00:00Z")
        return ctx, cv, wo

    def test_start_cure_missing_registration_beats_deadline(self, api):
        """PRD: "Because referential checks rank above temporal ones, a cure start
        against a property with no active municipal registration is rejected with
        `ERR_REGISTRATION_REQUIRED` even when the cure deadline has also passed —
        the deadline failure never masks the missing registration."

        Design: Difficulty/priority_pair_validation_conflict/cure_referential_beats_temporal
        """
        _ctx, cv, wo = self._setup_cure_without_registration(api)
        resp = api.start_cure(cv["id"], {"work_order_id": wo["id"]}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_REGISTRATION_REQUIRED)

    def test_start_cure_missing_registration_leaves_violation_open(self, api):
        """PRD: "the violation moves `OPEN → CURE_IN_PROGRESS` and records the link
        in `cure_work_order_id`" only on a successful start; the rejected attempt
        leaves the violation `OPEN`.

        Design: Difficulty/priority_pair_validation_conflict/cure_referential_beats_temporal
        """
        _ctx, cv, wo = self._setup_cure_without_registration(api)
        api.start_cure(cv["id"], {"work_order_id": wo["id"]}, ADMIN)
        after = validate_success(api.get_code_violation(cv["id"], ADMIN))
        assert after["status"] == "OPEN", f"rejected start-cure leaves the violation OPEN, got {after['status']}"


class TestCureLifecycle:
    def test_violation_cure_happy_path(self, api):
        """PRD: "the violation moves `OPEN → CURE_IN_PROGRESS`" then "`CURE_IN_PROGRESS
        → CURE_SUBMITTED`"; "A rejected cure — `CURE_SUBMITTED → CURE_IN_PROGRESS`,
        by a `VendorAdmin` with a mandatory `reason` — forms a cyclic rework loop
        with no limit"; "Municipal verification, performed by a `VendorAdmin`,
        closes the violation — `CURE_SUBMITTED → VERIFIED_CLOSED`, with
        `VERIFIED_CLOSED` as the violation's only terminal state — freezing
        `accrued_fine_cents` at its current value and recomputing the property's
        condition score and posture."

        Design: Corner/state_machines/violation_cure_happy_path
        """
        ctx = setup_portfolio(item_code="CODE_CURE",
                              allowable_overrides={
                                  "max_per_occurrence_cents": 50000,
                                  "max_occurrences_per_calendar_year": 10,
                                  "aggregate_cap_cents_per_property_year": 400000,
                                  "requires_bid_over_cents": 99999999},
                              property_overrides={"heating_system": "NONE", "fixture_count": 4},
                              clock="2026-08-05T00:00:00Z")
        setup_active_registration(ctx["property_id"], registration_number="REG-AD1")
        cv = create_code_violation(ctx["property_id"], citation_number="CV-300",
                                   violation_class="MAJOR", daily_fine_cents=1000,
                                   fine_cap_cents=50000, cure_deadline="2026-08-20")
        wo = create_work_order(ctx["property_id"], ctx["servicer_id"],
                               order_type="CODE_CURE", due_date="2026-08-15",
                               code_violation_id=cv["id"])
        started = validate_success(api.start_cure(cv["id"], {"work_order_id": wo["id"]}, ADMIN))
        assert started["status"] == "CURE_IN_PROGRESS"
        assign_work_order(wo["id"], ctx["crew_id"], scheduled_date="2026-08-06")
        start_work_order(wo["id"], ctx["crew_id"])
        upload_minimum_photos(wo["id"], "CODE_CURE", ctx["crew_id"], date="2026-08-06",
                              hash_prefix="cure")
        submit_work_order(wo["id"], ctx["crew_id"], 8000)
        validate_success(api.approve_work_order(wo["id"], QA))
        complete_work_order(wo["id"])
        crew_headers = make_field_crew_headers(ctx["crew_id"])
        st2 = validate_success(api.submit_cure(cv["id"], crew_headers))
        assert st2["status"] == "CURE_SUBMITTED"
        st3 = validate_success(api.reject_cure(
            cv["id"], {"reason": "photos insufficient for municipal file"}, ADMIN))
        assert st3["status"] == "CURE_IN_PROGRESS", "municipal rejection loops back"
        st4 = validate_success(api.submit_cure(cv["id"], crew_headers))
        assert st4["status"] == "CURE_SUBMITTED"
        closed = validate_success(api.verify_code_violation(cv["id"], ADMIN))
        assert closed["status"] == "VERIFIED_CLOSED"
        assert closed["accrued_fine_cents"] == 0, (
            f"verified before the 2026-08-20 deadline, no accrual, got {closed['accrued_fine_cents']}")

    def test_submit_cure_before_work_completed_rejected(self, api):
        """PRD: "Once the linked order stands `COMPLETED`, a `FieldCrew` member
        submits the cure to the municipality — `CURE_IN_PROGRESS → CURE_SUBMITTED` —
        with `ERR_CURE_WORK_INCOMPLETE` while the order is anything short of
        `COMPLETED`."

        Design: Corner/errors/submit_cure_before_work_completed_rejected
        """
        ctx = setup_portfolio(item_code="CODE_CURE",
                              allowable_overrides={
                                  "max_per_occurrence_cents": 50000,
                                  "max_occurrences_per_calendar_year": 10,
                                  "aggregate_cap_cents_per_property_year": 400000,
                                  "requires_bid_over_cents": 99999999},
                              property_overrides={"heating_system": "NONE", "fixture_count": 4},
                              clock="2026-08-05T00:00:00Z")
        setup_active_registration(ctx["property_id"], registration_number="REG-BB1")
        cv = create_code_violation(ctx["property_id"], citation_number="CV-700",
                                   violation_class="MINOR", daily_fine_cents=500,
                                   fine_cap_cents=20000, cure_deadline="2026-08-20")
        wo = create_work_order(ctx["property_id"], ctx["servicer_id"],
                               order_type="CODE_CURE", due_date="2026-08-15",
                               code_violation_id=cv["id"])
        validate_success(api.start_cure(cv["id"], {"work_order_id": wo["id"]}, ADMIN))
        resp = api.submit_cure(cv["id"], make_field_crew_headers(ctx["crew_id"]))
        validate_error(resp, ApiErrorId.ERR_CURE_WORK_INCOMPLETE)

    def test_start_cure_after_deadline_rejected(self, api):
        """PRD: "the temporal gate requires the clock date to be on or before
        `cure_deadline` (`ERR_CURE_DEADLINE_PASSED`)".

        Design: Corner/errors/start_cure_after_deadline_rejected
        """
        ctx = setup_portfolio(item_code="CODE_CURE",
                              allowable_overrides={
                                  "max_per_occurrence_cents": 50000,
                                  "max_occurrences_per_calendar_year": 10,
                                  "aggregate_cap_cents_per_property_year": 400000,
                                  "requires_bid_over_cents": 99999999},
                              property_overrides={"heating_system": "NONE", "fixture_count": 4},
                              clock="2026-08-05T00:00:00Z")
        setup_active_registration(ctx["property_id"], registration_number="REG-BC1")
        cv = create_code_violation(ctx["property_id"], citation_number="CV-800",
                                   violation_class="MAJOR", daily_fine_cents=1000,
                                   fine_cap_cents=50000, cure_deadline="2026-08-10")
        wo = create_work_order(ctx["property_id"], ctx["servicer_id"],
                               order_type="CODE_CURE", due_date="2026-08-09",
                               code_violation_id=cv["id"])
        set_clock("2026-08-11T00:00:00Z")
        resp = api.start_cure(cv["id"], {"work_order_id": wo["id"]}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_CURE_DEADLINE_PASSED)
        after = validate_success(api.get_code_violation(cv["id"], ADMIN))
        assert after["status"] == "OPEN"


class TestFineAccrual:
    def test_fine_accrual_deadline_boundary(self, api):
        """PRD: "The number of overdue days is the count of days from `cure_deadline`
        to the clock date, floored at zero — the deadline date itself accrues
        nothing, and the first day after it accrues exactly one day's
        `daily_fine_cents`. The accrued figure, exposed as `accrued_fine_cents`, is
        the overdue days times the daily fine, capped at `fine_cap_cents`; it is
        recomputed by the daily sweep and whenever the violation is read".

        Design: Corner/calculations/fine_accrual_deadline_boundary
        """
        ctx = setup_portfolio(with_allowable=False, with_crew=False,
                              property_overrides={"heating_system": "NONE", "fixture_count": 4})
        cv = create_code_violation(ctx["property_id"], citation_number="CV-400",
                                   violation_class="MINOR", daily_fine_cents=1000,
                                   fine_cap_cents=5000, cure_deadline="2026-08-10")
        set_clock("2026-08-10T00:00:00Z")
        d0 = validate_success(api.get_code_violation(cv["id"], ADMIN))
        assert d0["accrued_fine_cents"] == 0, "the deadline date itself accrues nothing"
        set_clock("2026-08-11T00:00:00Z")
        d1 = validate_success(api.get_code_violation(cv["id"], ADMIN))
        assert d1["accrued_fine_cents"] == 1000, "the first day after accrues one daily fine"
        set_clock("2026-08-16T00:00:00Z")
        d6 = validate_success(api.get_code_violation(cv["id"], ADMIN))
        assert d6["accrued_fine_cents"] == 5000, (
            f"six days would be 6000 but the 5000 cap binds, got {d6['accrued_fine_cents']}")
