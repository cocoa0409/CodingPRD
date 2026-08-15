"""Annual inspection plans: prorated fees, posture derivation, lapse sweep,
and optimistic concurrency on the parent property."""
from test_helpers import (
    ApiErrorId,
    admin_headers,
    assert_plan,
    create_contractor,
    create_plan,
    create_property,
    get_success_data,
    set_clock,
    setup_completed_event,
    setup_inspection_site,
    setup_scheduled_event,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

MARSHAL = TEST_USERS["fire_marshal_headers"]


class TestPlanFeeProrationVariants:
    def _fee_scenario(self, api):
        """FIRE_ALARM system installed 2026-08-15; clock pinned at 2026-08-15."""
        set_clock("2026-08-15T00:00:00Z")
        ctx = setup_inspection_site(system_category="FIRE_ALARM",
                                    device_type="SMOKE_DETECTOR",
                                    install_date="2026-08-15",
                                    legal_name="Acme Fire Protection")
        prop = get_success_data(api.get_property(ctx["prop"]["id"], ctx["admin"]))
        ctx["prop"] = prop
        ctx["plan"] = create_plan(ctx["con"], prop, plan_year=2026)
        return ctx

    def test_provisional_fee_uses_calendar_day_proration(self, api):
        """PRD §3.3: "At creation, while the plan is `DRAFT`, the server computes
        `provisional_fee_cents` by calendar-day proration: for each covered
        system, the base annual fee is multiplied by the number of calendar days
        from the service start through December 31 inclusive and divided by 365,
        with the per-system line rounded half-up to whole cents, and the lines
        summed."
        PRD §3.3: "Fees are prorated from annual base rates by system category:
        120000 cents per year for `FIRE_ALARM`, 180000 for `SPRINKLER`, 9000 for
        `BACKFLOW`, and 240000 for `FIRE_PUMP`."
        PRD §3.3: "The service start is the later of the plan creation date and
        the latest `install_date` among covered systems; the certification year
        ends on December 31 of `plan_year`."

        Design: Difficulty/dual_variant_calc/plan_fee_provisional_vs_final_diverge
        """
        ctx = self._fee_scenario(api)
        plan = ctx["plan"]
        assert_plan(plan)
        # service_start = max(2026-08-15 creation, 2026-08-15 install) = 2026-08-15;
        # 139 calendar days through Dec 31 inclusive; 120000 * 139 / 365 = 45698.63 -> 45699.
        assert plan["provisional_fee_cents"] == 45699, (
            f"expected calendar-day proration 45699, got {plan['provisional_fee_cents']}")
        assert plan["plan_posture"] == "DRAFT"

    def test_publish_computes_final_fee_and_retains_provisional(self, api):
        """PRD §3.3: "the server computes `final_fee_cents` by remaining-full-month
        proration: the number of whole calendar months strictly after the service
        start's month through December of the plan year (when the service start
        falls within the plan year, that is the months following its month through
        month twelve; when the service start predates the plan year, all twelve
        months count), each covered system's fee being its annual base multiplied
        by that month count and divided by twelve, rounded half-up per system line
        and then summed. The provisional figure is retained for audit."
        PRD §3.3: "the plan becomes `SCHEDULED`"

        Design: Difficulty/dual_variant_calc/plan_fee_provisional_vs_final_diverge
        """
        ctx = self._fee_scenario(api)
        published = validate_success(api.publish_plan(ctx["plan"]["id"], ctx["admin"]))
        # Four whole months remain (Sep..Dec): 120000 * 4 / 12 = 40000.
        assert published["final_fee_cents"] == 40000, (
            f"expected remaining-full-month proration 40000, got {published['final_fee_cents']}")
        assert published["provisional_fee_cents"] == 45699, (
            "the provisional figure is retained for audit")
        assert published["plan_posture"] == "SCHEDULED"


class TestEmptyPlanBoundary:
    def _empty_plan(self, api):
        ctx = setup_inspection_site(device_count=0, legal_name="Empty Plan Co")
        prop = get_success_data(api.get_property(ctx["prop"]["id"], ctx["admin"]))
        ctx["prop"] = prop
        ctx["plan"] = create_plan(ctx["con"], prop, plan_year=2026)
        return ctx

    def test_zero_device_plan_has_zero_requirement_and_publish_rejected(self, api):
        """PRD §3.3: "Each `IN_SERVICE` device on an `IN_SERVICE` system
        contributes events per year according to its frequency: twelve for
        `MONTHLY`, four for `QUARTERLY`, one for `ANNUAL`. Devices no longer in
        service contribute zero. The sum is `total_events_required`"
        PRD §3.3: "a transition requiring the plan to be `DRAFT`,
        `total_events_required` greater than zero (else `ERR_EMPTY_PLAN`), and
        the contractor in `GOOD_STANDING` (else `ERR_CONTRACTOR_POSTURE_BLOCKED`)"

        Design: Difficulty/boundary_precision_check/empty_plan_publish_zero_events_rejected
        """
        ctx = self._empty_plan(api)
        assert ctx["plan"]["total_events_required"] == 0, (
            "a property whose system carries no devices requires zero events")
        resp = api.publish_plan(ctx["plan"]["id"], ctx["admin"])
        validate_error(resp, ApiErrorId.ERR_EMPTY_PLAN)

    def test_rejected_publish_leaves_plan_in_draft(self, api):
        """PRD §3.3: "a transition requiring the plan to be `DRAFT`,
        `total_events_required` greater than zero (else `ERR_EMPTY_PLAN`), and
        the contractor in `GOOD_STANDING` (else `ERR_CONTRACTOR_POSTURE_BLOCKED`)
        — the plan becomes `SCHEDULED`"

        Design: Difficulty/boundary_precision_check/empty_plan_publish_zero_events_rejected
        """
        ctx = self._empty_plan(api)
        validate_error(api.publish_plan(ctx["plan"]["id"], ctx["admin"]),
                       ApiErrorId.ERR_EMPTY_PLAN)
        after = validate_success(api.get_plan(ctx["plan"]["id"], ctx["admin"]))
        assert after["plan_posture"] == "DRAFT", (
            "the rejected publish leaves the plan posture unchanged")


class TestPlanPostureDerivation:
    def test_plan_fulfilled_when_all_events_complete(self, api):
        """PRD §3.3: "When `events_completed` reaches `total_events_required` and
        every child event is terminal with none in `NO_ACCESS`, the plan becomes
        `FULFILLED`, and the contractor's score is recomputed."
        PRD §3.3: "Each `IN_SERVICE` device on an `IN_SERVICE` system contributes
        events per year according to its frequency: twelve for `MONTHLY`, four
        for `QUARTERLY`, one for `ANNUAL`."

        Design: Corner/state_machines/compound_plan_posture_fulfilled_when_all_events_complete
        """
        ctx = setup_completed_event(
            scheduled_start="2026-08-02T09:00:00Z",
            scheduled_end="2026-08-02T10:00:00Z",
            complete_clock="2026-08-02T09:30:00Z",
            legal_name="Fulfill Co",
        )
        plan = validate_success(api.get_plan(ctx["plan"]["id"], ctx["admin"]))
        assert plan["events_completed"] == 1
        assert plan["total_events_required"] == 1, (
            "a single ANNUAL SMOKE_DETECTOR requires exactly one event per year")
        assert plan["plan_posture"] == "FULFILLED"

    def test_plan_lapses_and_cancels_events_after_year_end(self, api):
        """PRD §3.3: "When the logical date passes December 31 of the plan year
        without fulfillment, the plan becomes `LAPSED`: its still-`SCHEDULED`
        children are cancelled"
        PRD §2.9: "75 for each inspection plan in `LAPSED`"

        Design: Corner/state_machines/plan_lapse_cascade_on_year_end
        """
        ctx = setup_scheduled_event(device_type="GAUGE_VALVE",
                                    scheduled_start="2026-12-01T09:00:00Z",
                                    scheduled_end="2026-12-01T10:00:00Z",
                                    legal_name="Lapse Co")
        set_clock("2027-01-01T00:00:00Z")
        plan = validate_success(api.get_plan(ctx["plan"]["id"], ctx["admin"]))
        assert plan["plan_posture"] == "LAPSED"
        ev = validate_success(api.get_event(ctx["ev"]["id"], ctx["admin"]))
        assert ev["status"] == "CANCELLED", (
            "the lapse cascade cancels still-SCHEDULED children")
        con = validate_success(api.get_contractor(ctx["con"]["id"], MARSHAL))
        assert con["compliance_score"] == 925, (
            "1000 minus the 75-point lapsed-plan deduction")


class TestPlanOptimisticConcurrency:
    def test_stale_plan_create_rejected_then_fresh_retry_succeeds(self, api):
        """PRD §2.8: "If the property's current `version` differs — because
        another writer has mutated the property since the client last read it —
        the creation is rejected with `ERR_STALE_VERSION` (HTTP 412)"
        PRD §3.3: "Creation itself increments the parent property's `version` by
        one, which is precisely the mutation a concurrent planner's stale
        `expected_property_version` protects against."

        Design: Corner/cross_cutting_layers/occ_stale_plan_create_rejected
        """
        con = create_contractor(legal_name="Occ Co", state_license_no="C-99992")
        prop = create_property(con, address_line="1 Occ Ave")
        create_plan(con, prop, plan_year=2026)

        stale = api.create_plan(
            prop["id"],
            {"plan_year": 2027, "expected_property_version": prop["version"]},
            admin_headers(con))
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)

        fresh = validate_success(api.get_property(prop["id"], admin_headers(con)))
        retry = api.create_plan(
            prop["id"],
            {"plan_year": 2027, "expected_property_version": fresh["version"]},
            admin_headers(con))
        plan2 = validate_success(retry, 201)
        assert plan2["plan_year"] == 2027

    def test_property_version_increments_by_one_per_plan_create(self, api):
        """PRD §2.4: "`version` is an integer that starts on creation and
        increments by one on every mutation of that resource, including mutations
        driven by cascades or automatic system transitions."
        PRD §3.3: "Creation itself increments the parent property's `version` by
        one"

        Design: Corner/cross_cutting_layers/version_increments_on_every_mutation
        """
        con = create_contractor(legal_name="Version Co", state_license_no="C-99995")
        prop = create_property(con, address_line="1 Ver St")
        create_plan(con, prop, plan_year=2026)
        after = validate_success(api.get_property(prop["id"], admin_headers(con)))
        assert after["version"] == prop["version"] + 1, (
            f"one plan create increments the property version exactly once: "
            f"{prop['version']} -> {after['version']}")
