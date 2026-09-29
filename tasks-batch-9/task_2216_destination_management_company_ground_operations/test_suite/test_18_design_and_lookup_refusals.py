"""Per-entity not-found codes, the design lock, the markup band and the wiring rules."""

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    add_element,
    create_program,
    create_program_element_payload,
    create_program_payload,
    create_supplier,
    create_venue,
    lock_design,
    read_program,
    reset_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

PD = TEST_USERS["program_director_headers"]

WINDOW_ELEMENT = {
    "element_type": "ACTIVITY",
    "planned_headcount": 20,
    "guaranteed_headcount": 20,
    "per_person_cost_cents": 4_000,
}


class TestEveryLookupCarriesItsOwnNotFoundCode:
    def test_nine_single_resource_reads_answer_with_nine_distinct_codes(self, api):
        """PRD §2.8: "Each resource type has its own not-found code, all of them HTTP 404:
        `ERR_PROGRAM_NOT_FOUND`, `ERR_VENUE_NOT_FOUND`, `ERR_SUPPLIER_NOT_FOUND`,
        `ERR_CONTRACT_NOT_FOUND`, `ERR_ELEMENT_NOT_FOUND`, `ERR_PERMIT_NOT_FOUND`,
        `ERR_SEGMENT_NOT_FOUND`, `ERR_MANIFEST_ENTRY_NOT_FOUND`,
        `ERR_STAFF_MEMBER_NOT_FOUND`, `ERR_STAFF_ASSIGNMENT_NOT_FOUND`,
        `ERR_RECONCILIATION_LINE_NOT_FOUND` and `ERR_SETTLEMENT_PAYMENT_NOT_FOUND`."

        Design: Corner/errors/every_entity_lookup_with_an_unknown_id_returns_not_found
        """
        reset_clock()
        reads = (
            (api.get_venue, ApiErrorId.ERR_VENUE_NOT_FOUND),
            (api.get_supplier, ApiErrorId.ERR_SUPPLIER_NOT_FOUND),
            (api.get_supplier_contract, ApiErrorId.ERR_CONTRACT_NOT_FOUND),
            (api.get_program_element, ApiErrorId.ERR_ELEMENT_NOT_FOUND),
            (api.get_permit, ApiErrorId.ERR_PERMIT_NOT_FOUND),
            (api.get_staff_member, ApiErrorId.ERR_STAFF_MEMBER_NOT_FOUND),
            (api.get_staff_assignment, ApiErrorId.ERR_STAFF_ASSIGNMENT_NOT_FOUND),
            (api.get_reconciliation_line, ApiErrorId.ERR_RECONCILIATION_LINE_NOT_FOUND),
            (api.get_settlement_payment, ApiErrorId.ERR_SETTLEMENT_PAYMENT_NOT_FOUND),
        )

        observed = []
        for read, expected in reads:
            response = read(NON_EXISTENT_UUID, PD)
            validate_error(response, expected.value, 404)
            observed.append(response.json()["data"]["error_id"])

        # The same absent identifier, nine different answers: the code is per entity.
        assert len(set(observed)) == 9


class TestElementSetIsFrozenByTheDesignLock:
    ANCHOR = {
        "element_type": "ACTIVITY",
        "title": "Locked Design Anchor",
        "starts_at": "2026-09-11T09:00:00Z",
        "ends_at": "2026-09-11T13:00:00Z",
        "planned_headcount": 20,
        "guaranteed_headcount": 20,
        "per_person_cost_cents": 4_000,
    }
    LATE_ADDITION = {
        "element_type": "DINE_AROUND",
        "title": "Late Addition Dine-Around",
        "starts_at": "2026-09-12T19:00:00Z",
        "ends_at": "2026-09-12T22:00:00Z",
        "planned_headcount": 20,
        "guaranteed_headcount": 20,
        "per_person_cost_cents": 6_000,
    }

    def _locked_programme_with_one_element(self):
        venue = create_venue(
            name="Locked Design Ballroom", capacity_seated=100, capacity_reception=200
        )
        supplier = create_supplier(
            legal_name="Locked Design Caterer", supplier_type="VENUE_SERVICES"
        )
        program = create_program(
            client_name="Locked Design Client",
            group_name="Locked Design Group",
            guaranteed_count=20,
        )
        element = add_element(
            program["id"], supplier["id"], venue_id=venue["id"], **self.ANCHOR
        )
        return {
            "venue": venue,
            "supplier": supplier,
            "program": lock_design(program["id"]),
            "element": element,
        }

    def test_neither_a_new_element_nor_a_reshape_survives_the_lock(self, api):
        """PRD §3.1: "Because the design is frozen, adding an element to a programme whose
        `execution_status` is anything other than `DRAFT` is refused with
        `ERR_PROGRAM_DESIGN_LOCKED`, and so is reshaping an existing element."

        Design: Corner/errors/element_set_mutation_after_lock_design_rejected
        """
        ctx = self._locked_programme_with_one_element()
        locked_version = ctx["program"]["version"]

        creation = api.create_program_element(
            create_program_element_payload(
                ctx["program"]["id"],
                ctx["supplier"]["id"],
                locked_version,
                venue_id=ctx["venue"]["id"],
                **self.LATE_ADDITION,
            ),
            PD,
        )
        reshape = api.patch_program_element(
            ctx["element"]["id"], {"title": "Renamed While Locked"}, PD
        )

        validate_error(creation, ApiErrorId.ERR_PROGRAM_DESIGN_LOCKED.value, 409)
        validate_error(reshape, ApiErrorId.ERR_PROGRAM_DESIGN_LOCKED.value, 409)
        # The guard is the frozen design, not a concurrency miss: the version was current.
        assert (
            creation.json()["data"]["error_id"]
            != ApiErrorId.ERR_STALE_PROGRAM_VERSION.value
        )
        program = read_program(ctx["program"]["id"])
        assert program["execution_status"] == "DESIGN_LOCKED"
        assert program["element_count"] == 1
        assert program["version"] == locked_version == 3
        assert (
            validate_success(api.get_program_element(ctx["element"]["id"], PD))["title"]
            == "Locked Design Anchor"
        )


class TestDesignLockNeedsAtLeastOneElement:
    def test_an_element_free_programme_cannot_be_locked(self, api):
        """PRD §3.1: "Two things are checked at the lock: the programme must already have at
        least one element, or the request is refused with `ERR_PROGRAM_HAS_NO_ELEMENTS`, and
        `markup_pct` must still sit within the `0.05`-to-`0.35` band, or the request is refused
        with `ERR_MARKUP_PCT_OUT_OF_BAND`."

        Design: Corner/errors/lock_design_and_confirm_on_an_element_free_program_rejected
        """
        reset_clock()
        program = create_program(
            client_name="Elementless Client",
            group_name="Elementless Group",
            guaranteed_count=20,
        )

        response = api.lock_program_design(program["id"], PD)

        validate_error(response, ApiErrorId.ERR_PROGRAM_HAS_NO_ELEMENTS.value, 422)
        stored = read_program(program["id"])
        assert stored["execution_status"] == "DRAFT"
        assert stored["element_count"] == 0
        # A refused transition leaks no version bump and freezes no estimate.
        assert stored["version"] == 1
        assert stored["estimated_client_total_cents"] == 0


class TestMarkupBandIsInclusiveOnBothEnds:
    def test_a_third_above_and_a_twentieth_below_are_both_refused(self, api):
        """PRD §3.1: "An optional `markup_pct` sets the disclosed markup applied to supplier
        cost on every reconciliation line; when omitted it defaults to `0.18`, and whether
        supplied or defaulted it must be at least `0.05` and at most `0.35`, with anything
        outside that band refused as `ERR_MARKUP_PCT_OUT_OF_BAND`."

        Design: Corner/errors/program_create_with_markup_pct_outside_the_band_rejected
        """
        reset_clock()

        too_greedy = api.create_program(
            create_program_payload(
                client_name="Greedy Markup Client",
                group_name="Greedy Markup Group",
                guaranteed_count=20,
                markup_pct=0.36,
            ),
            PD,
        )
        too_thin = api.create_program(
            create_program_payload(
                client_name="Thin Markup Client",
                group_name="Thin Markup Group",
                guaranteed_count=20,
                markup_pct=0.04,
            ),
            PD,
        )
        on_the_bound = api.create_program(
            create_program_payload(
                client_name="Boundary Markup Client",
                group_name="Boundary Markup Group",
                guaranteed_count=20,
                markup_pct=0.05,
            ),
            PD,
        )

        validate_error(too_greedy, ApiErrorId.ERR_MARKUP_PCT_OUT_OF_BAND.value, 422)
        validate_error(too_thin, ApiErrorId.ERR_MARKUP_PCT_OUT_OF_BAND.value, 422)
        accepted = validate_success(on_the_bound, 201)
        assert accepted["markup_pct"] == 0.05
        _, meta = validate_paginated(
            api.list_programs(PD, params={"limit": 10, "offset": 0})
        )
        assert meta["total_count"] == 1


class TestElementsMustSitInsideTheProgrammeWindow:
    def _venue_supplier_and_five_day_programme(self):
        venue = create_venue(
            name="Window Test Pavilion", capacity_seated=100, capacity_reception=200
        )
        supplier = create_supplier(legal_name="Window Test Operator")
        program = create_program(
            client_name="Window Test Client",
            group_name="Window Test Group",
            guaranteed_count=20,
        )
        return venue, supplier, program

    def test_the_day_before_arrival_and_the_night_after_departure_are_both_out(self, api):
        """PRD §3.2: "An element whose `starts_at` falls before the programme's
        `arrival_date`, or whose `ends_at` falls after the programme's `departure_date`, is
        refused with `ERR_ELEMENT_OUTSIDE_PROGRAM_WINDOW`; the same containment rule applies to
        transport segments, whose `depart_at` must be at or after `arrival_date` and whose
        `arrive_at` must be at or before `departure_date`."

        Design: Corner/errors/element_create_outside_the_program_window_rejected
        """
        venue, supplier, program = self._venue_supplier_and_five_day_programme()

        def candidate(**overrides):
            return api.create_program_element(
                create_program_element_payload(
                    program["id"],
                    supplier["id"],
                    program["version"],
                    venue_id=venue["id"],
                    **WINDOW_ELEMENT,
                    **overrides,
                ),
                PD,
            )

        before_arrival = candidate(
            title="Pre-Arrival Recce",
            starts_at="2026-09-09T09:00:00Z",
            ends_at="2026-09-09T13:00:00Z",
        )
        after_departure = candidate(
            title="Post-Departure Extension",
            starts_at="2026-09-14T22:00:00Z",
            ends_at="2026-09-15T02:00:00Z",
        )
        on_the_departure_day = candidate(
            title="Departure Day Farewell Brunch",
            starts_at="2026-09-14T09:00:00Z",
            ends_at="2026-09-14T13:00:00Z",
        )

        validate_error(
            before_arrival, ApiErrorId.ERR_ELEMENT_OUTSIDE_PROGRAM_WINDOW.value, 422
        )
        validate_error(
            after_departure, ApiErrorId.ERR_ELEMENT_OUTSIDE_PROGRAM_WINDOW.value, 422
        )
        assert validate_success(on_the_departure_day, 201)["status"] == "PLANNED"
        stored = read_program(program["id"])
        assert stored["element_count"] == 1
        assert stored["version"] == 2


class TestRainPlanTargetMustBeWeatherDependent:
    INDOOR_GALA = {
        "element_type": "ACTIVITY",
        "title": "Indoor Gala Dinner",
        "starts_at": "2026-09-11T19:00:00Z",
        "ends_at": "2026-09-11T23:00:00Z",
        "planned_headcount": 20,
        "guaranteed_headcount": 20,
        "per_person_cost_cents": 5_000,
        "is_weather_dependent": False,
    }
    SPARE_SESSION = {
        "element_type": "ACTIVITY",
        "title": "Spare Loft Session",
        "starts_at": "2026-09-11T19:00:00Z",
        "ends_at": "2026-09-11T23:00:00Z",
        "planned_headcount": 20,
        "guaranteed_headcount": 20,
        "per_person_cost_cents": 5_000,
        "is_weather_dependent": False,
    }

    def _an_indoor_gala_and_an_unwired_spare(self):
        gala_hall = create_venue(
            name="Indoor Gala Hall", capacity_seated=100, capacity_reception=200
        )
        backup_loft = create_venue(
            name="Backup Loft", capacity_seated=100, capacity_reception=200
        )
        supplier = create_supplier(legal_name="Rain Plan Operator")
        program = create_program(
            client_name="Rain Plan Client",
            group_name="Rain Plan Group",
            guaranteed_count=20,
        )
        indoor = add_element(
            program["id"], supplier["id"], venue_id=gala_hall["id"], **self.INDOOR_GALA
        )
        spare = add_element(
            program["id"], supplier["id"], venue_id=backup_loft["id"], **self.SPARE_SESSION
        )
        return {
            "loft": backup_loft,
            "supplier": supplier,
            "program": program,
            "indoor": indoor,
            "spare": spare,
        }

    def test_a_fair_weather_target_is_refused_on_create_and_on_patch(self, api):
        """PRD §3.2: "The rain-plan graph formed by `alternative_for_element_id` has its own
        wiring rules: when supplied, it must reference an element of the same programme, that
        element must itself be flagged `is_weather_dependent`, it must not be the same element
        as the candidate's own `predecessor_element_id`, and the referenced element must not
        itself already carry a non-null `alternative_for_element_id` — a rain plan for a rain
        plan is not permitted."

        Design: Corner/errors/weather_alternative_pointing_at_a_fair_weather_element_rejected
        """
        ctx = self._an_indoor_gala_and_an_unwired_spare()

        creation = api.create_program_element(
            create_program_element_payload(
                ctx["program"]["id"],
                ctx["supplier"]["id"],
                read_program(ctx["program"]["id"])["version"],
                venue_id=ctx["loft"]["id"],
                element_type="ACTIVITY",
                title="Rain Plan For An Indoor Gala",
                starts_at="2026-09-12T19:00:00Z",
                ends_at="2026-09-12T23:00:00Z",
                planned_headcount=20,
                guaranteed_headcount=20,
                per_person_cost_cents=5_000,
                alternative_for_element_id=ctx["indoor"]["id"],
            ),
            PD,
        )
        rewire = api.patch_program_element(
            ctx["spare"]["id"], {"alternative_for_element_id": ctx["indoor"]["id"]}, PD
        )

        validate_error(creation, ApiErrorId.ERR_INVALID_WEATHER_ALTERNATIVE.value, 422)
        validate_error(rewire, ApiErrorId.ERR_INVALID_WEATHER_ALTERNATIVE.value, 422)
        assert read_program(ctx["program"]["id"])["element_count"] == 2

    def test_flipping_the_target_flag_makes_the_identical_rewire_legal(self, api):
        """PRD §3.2: "This is the only way an existing element's graph edges change, so it is
        where the acyclicity and rain-plan wiring checks bite a second time, and both
        `ERR_ELEMENT_DEPENDENCY_CYCLE` and `ERR_INVALID_WEATHER_ALTERNATIVE` apply here exactly
        as they do at creation."

        Design: Corner/errors/weather_alternative_pointing_at_a_fair_weather_element_rejected
        """
        ctx = self._an_indoor_gala_and_an_unwired_spare()
        api.patch_program_element(
            ctx["spare"]["id"], {"alternative_for_element_id": ctx["indoor"]["id"]}, PD
        )

        exposed = validate_success(
            api.patch_program_element(
                ctx["indoor"]["id"], {"is_weather_dependent": True}, PD
            )
        )
        rewired = validate_success(
            api.patch_program_element(
                ctx["spare"]["id"],
                {"alternative_for_element_id": ctx["indoor"]["id"]},
                PD,
            )
        )

        assert exposed["is_weather_dependent"] is True
        assert rewired["alternative_for_element_id"] == ctx["indoor"]["id"]
        _, meta = validate_paginated(
            api.list_program_elements(
                PD,
                params={
                    "alternative_for_element_id": ctx["indoor"]["id"],
                    "limit": 10,
                    "offset": 0,
                },
            )
        )
        assert meta["total_count"] == 1


class TestReconcileNeedsSomethingToReconcile:
    def test_a_cancelled_programme_with_no_elements_has_an_empty_line_set(self, api):
        """PRD §3.8: "Three conditions gate it: `settlement_status` must still be
        `NOT_STARTED`, or the request is refused with `ERR_PROGRAM_ALREADY_RECONCILING`; the
        execution dimension must have reached a final state, either `COMPLETED` or `CANCELLED`,
        or the request is refused with `ERR_PROGRAM_NOT_EXECUTION_FINAL`; and at least one
        element of the programme must be in `DELIVERED` or `CANCELLED`, since there is nothing
        to reconcile otherwise, with the empty case refused as
        `ERR_NO_RECONCILABLE_ELEMENTS`."

        Design: Corner/errors/reconcile_program_with_no_reconcilable_elements_rejected
        """
        reset_clock()
        program = create_program(
            client_name="Empty Reconcile Client",
            group_name="Empty Reconcile Group",
            guaranteed_count=20,
        )
        validate_success(
            api.cancel_program(program["id"], PD, {"cancel_reason": "Client never signed."})
        )

        response = api.reconcile_program(program["id"], PD)

        validate_error(response, ApiErrorId.ERR_NO_RECONCILABLE_ELEMENTS.value, 422)
        # CANCELLED is execution-final, so the preceding gate cannot be what fired.
        assert (
            response.json()["data"]["error_id"]
            != ApiErrorId.ERR_PROGRAM_NOT_EXECUTION_FINAL.value
        )
        stored = read_program(program["id"])
        assert stored["settlement_status"] == "NOT_STARTED"
        assert stored["element_count"] == 0
        _, meta = validate_paginated(
            api.list_reconciliation_lines(
                PD, params={"program_id": program["id"], "limit": 10, "offset": 0}
            )
        )
        assert meta["total_count"] == 0
