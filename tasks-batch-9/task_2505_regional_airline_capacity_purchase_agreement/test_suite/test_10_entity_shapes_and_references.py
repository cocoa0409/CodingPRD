"""Resource shapes as created, as read back, as listed and as refused.

System-owned defaults, derived staffing figures on an empty base, a filtered and
paginated leg listing, and the four ways a reference or a field can be wrong.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_errors import (
    ERR_AIRCRAFT_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_REFERENCE_NOT_FOUND,
)
from test_helpers.assertions import (
    assert_block_hours,
    assert_common_fields,
    assert_departure_ledger_identity,
    assert_is_null,
    assert_money,
    assert_page_meta,
    assert_staffing_picture,
    assert_status,
    default_list_order,
    ids_of,
)
from test_helpers.factories import (
    make_agreement_payload,
    make_aircraft_payload,
    make_brand_audit_payload,
    make_completion_payload,
    make_crew_base_payload,
    make_flight_leg_payload,
    make_pilot_payload,
    make_schedule_cycle_payload,
)
from test_helpers.fixtures import (
    add_leg,
    build_active_agreement,
    build_open_cycle,
    create_agreement,
    read_crew_base,
    read_cycle,
)
from test_helpers.test_users import (
    ADMIN_HEADERS,
    AUDITOR_HEADERS,
    OPS_HEADERS,
    SCHEDULER_HEADERS,
)

UNKNOWN_ID = "00000000-0000-0000-0000-000000000000"


class TestAgreementCreation:
    """The contract is born in draft with every derived money field at zero."""

    def test_a_new_agreement_is_draft_with_system_defaults(self, api):
        """The five money terms are echoed and nothing derived is accepted.

        PRD 3.1: "A newly registered agreement lands in `DRAFT` with
        `extension_round_count` at 0, `settled_to_date_usd` at 0.00,
        `open_invoice_count` at 0, and `activated_at` null."

        Design: Corner/entities/create_agreement_returns_201_with_system_defaults
        """
        payload = make_agreement_payload()

        agreement = validate_success(api.create_agreement(payload, headers=ADMIN_HEADERS), 201)

        assert_status(agreement, "DRAFT")
        assert agreement["extension_round_count"] == 0
        assert_money(agreement["settled_to_date_usd"], 0.00, "settled to date")
        assert agreement["open_invoice_count"] == 0
        assert_is_null(agreement, "activated_at")

        assert_money(agreement["block_hour_rate_usd"], 1450.75, "block hour rate")
        assert agreement["term_end_date"] == "2029-12-31"
        assert_common_fields(agreement, expected_version=1)


class TestCrewBaseRetrieval:
    """An empty base reads back staffed, because it holds no aeroplanes to crew."""

    def test_a_fresh_base_reads_back_with_every_derivation_at_zero(self, api):
        """The two supplied capacities survive and the six derived figures are empty.

        PRD 3.2: "A fresh base opens with `lifecycle_status` `ACTIVE` and every derived
        figure at zero: `line_qualified_pilot_count`, `in_training_pilot_count`,
        `assigned_aircraft_count`, `required_pilot_count`, `headcount_shortfall`,
        `pipeline_shortfall`, and `allocatable_aircraft_count` are all 0, and
        `staffing_posture` reads `STAFFED`."

        Design: Corner/entities/get_crew_base_returns_stored_and_derived_fields
        """
        agreement = create_agreement(api, make_agreement_payload())
        created = validate_success(
            api.create_crew_base(
                make_crew_base_payload(
                    agreement["id"],
                    station_code="MKE",
                    pilots_required_per_aircraft=2,
                    aircraft_allocation_cap=3,
                ),
                headers=OPS_HEADERS,
            ),
            201,
        )

        base = validate_success(api.get_crew_base(created["id"], headers=OPS_HEADERS))

        assert base["id"] == created["id"]
        assert base["agreement_id"] == agreement["id"]
        assert base["station_code"] == "MKE"
        assert base["pilots_required_per_aircraft"] == 2
        assert base["aircraft_allocation_cap"] == 3
        assert_status(base, "ACTIVE", field="lifecycle_status")
        assert_staffing_picture(
            base,
            line_qualified=0,
            in_training=0,
            assigned_aircraft=0,
            required_pilots=0,
            headcount_shortfall=0,
            pipeline_shortfall=0,
            posture="STAFFED",
            allocatable_aircraft=0,
        )


class TestFlightLegListing:
    """The cycle filter and the offset window compose over three published legs."""

    def test_three_legs_of_one_month_paginate_two_then_one(self, api):
        """The window moves while the filtered size stays fixed at three.

        PRD 2.3: "List responses carry `limit`, `offset`, `total_count`, and `has_more`
        inside the `meta` object of the envelope, where `total_count` is the size of the
        filtered set before pagination is applied and `has_more` states whether records
        remain beyond the returned window."

        PRD 2.3: "Unless a specific endpoint says otherwise, every list is ordered by
        `created_at` ascending, with the record `id` ascending as the tie-break when two
        records share a creation timestamp."

        Design: Corner/entities/list_flight_legs_filtered_by_cycle_with_pagination
        """
        scenario = build_open_cycle(
            api,
            agreement_payload=make_agreement_payload(),
            station_code="MKE",
            pilots_required_per_aircraft=1,
            aircraft_allocation_cap=1,
            line_qualified_pilots=1,
            tail_numbers=["N2001RG"],
            cycle_month="2026-09",
            published_departures=10,
        )
        first = add_leg(
            api,
            scenario,
            flight_number="SM6001",
            origin="MKE",
            destination="ORD",
            scheduled_departure_utc="2026-09-02T08:00:00Z",
            scheduled_arrival_utc="2026-09-02T09:00:00Z",
            planned_block_hours=1.000,
        )
        second = add_leg(
            api,
            scenario,
            flight_number="SM6002",
            origin="MKE",
            destination="DTW",
            scheduled_departure_utc="2026-09-04T08:00:00Z",
            scheduled_arrival_utc="2026-09-04T09:00:00Z",
            planned_block_hours=1.000,
        )
        third = add_leg(
            api,
            scenario,
            flight_number="SM6003",
            origin="MKE",
            destination="MSP",
            scheduled_departure_utc="2026-09-06T08:00:00Z",
            scheduled_arrival_utc="2026-09-06T09:00:00Z",
            planned_block_hours=1.000,
        )

        page_one, meta_one = validate_paginated(
            api.list_flight_legs(
                headers=SCHEDULER_HEADERS,
                params={"cycle_id": scenario.cycle_id, "limit": 2, "offset": 0},
            )
        )
        page_two, meta_two = validate_paginated(
            api.list_flight_legs(
                headers=SCHEDULER_HEADERS,
                params={"cycle_id": scenario.cycle_id, "limit": 2, "offset": 2},
            )
        )

        expected = ids_of(default_list_order([first, second, third]))
        assert ids_of(page_one) == expected[:2]
        assert_page_meta(meta_one, limit=2, offset=0, total_count=3, has_more=True)
        assert ids_of(page_two) == expected[2:]
        assert_page_meta(meta_two, limit=2, offset=2, total_count=3, has_more=False)

        for leg in page_one + page_two:
            assert leg["cycle_id"] == scenario.cycle_id
            assert_status(leg, "SCHEDULED")


class TestUnknownPathIdentifier:
    """A path identifier that resolves to nothing yields that entity's own 404."""

    def test_reading_an_unknown_tail_returns_the_aircraft_not_found_code(self, api):
        """The code is entity-specific rather than a generic reference failure.

        PRD 2.10: "Path identifiers are resolved left to right, and the first identifier
        that does not resolve produces its own 404: `ERR_AGREEMENT_NOT_FOUND`,
        `ERR_CREW_BASE_NOT_FOUND`, `ERR_AIRCRAFT_NOT_FOUND`, `ERR_PILOT_NOT_FOUND`,
        `ERR_SCHEDULE_CYCLE_NOT_FOUND`, `ERR_FLIGHT_LEG_NOT_FOUND`,
        `ERR_CANCELLATION_CLAIM_NOT_FOUND`, `ERR_PASSTHROUGH_CLAIM_NOT_FOUND`,
        `ERR_SCORECARD_NOT_FOUND`, `ERR_INVOICE_NOT_FOUND`, `ERR_BRAND_AUDIT_NOT_FOUND`,
        or `ERR_NEGOTIATION_NOT_FOUND` respectively."

        Design: Corner/entities/get_aircraft_unknown_id_returns_not_found
        """
        response = api.get_aircraft(UNKNOWN_ID, headers=OPS_HEADERS)

        validate_error(response, ERR_AIRCRAFT_NOT_FOUND, 404)


class TestPilotRequiredFields:
    """A missing required enum is caught before any base reasoning happens."""

    def test_hiring_a_pilot_without_a_seat_is_rejected_and_creates_nothing(self, api):
        """The seat is required, so the request never reaches the base's counters.

        PRD 2.12: "Structural validity of the body and query: required fields present,
        enum members recognised, monetary amounts strictly positive with at most two
        decimals, block hours strictly positive with at most three decimals,
        `published_departures` at least 0, `findings_count` at least 1,
        `pilots_required_per_aircraft` at least 1, `aircraft_allocation_cap` at least 1,
        and pagination `limit` between 1 and 100 inclusive — `ERR_INVALID_REQUEST`."

        Design: Corner/entities/create_pilot_missing_seat_rejected
        """
        scenario = build_active_agreement(
            api,
            agreement_payload=make_agreement_payload(),
            station_code="MKE",
            pilots_required_per_aircraft=1,
            aircraft_allocation_cap=1,
        )
        payload = make_pilot_payload(
            scenario.crew_base_id, employee_ref="EMP-2101", hire_class_date="2026-06-01"
        )
        payload.pop("seat")

        validate_error(api.create_pilot(payload, headers=OPS_HEADERS), ERR_INVALID_REQUEST, 400)

        pilots, meta = validate_paginated(
            api.list_pilots(headers=OPS_HEADERS, params={"base_id": scenario.crew_base_id})
        )
        assert pilots == []
        assert meta["total_count"] == 0
        assert_staffing_picture(
            read_crew_base(api, scenario.crew_base_id), line_qualified=0, in_training=0
        )


class TestScheduleCycleDefaults:
    """A month opens with empty counters and a ledger that already balances."""

    def test_a_new_month_applies_its_declared_defaults(self, api):
        """Only the bought departure count is supplied; everything else is declared.

        PRD 3.4: "At creation the month's operational counters are all empty —
        `recorded_completed_legs`, `open_leg_count`, `cancelled_controllable_count`,
        `cancelled_uncontrollable_count`, `enplaned_bags_total`, `mishandled_bags_total`
        and `on_time_leg_count` are 0, `credited_block_hours` is 0.000,
        `estimated_passthrough_total_usd` and `passthrough_settlement_usd` are 0.00, and
        `closed_at` is null."

        Design: Corner/entities/new_schedule_cycle_applies_declared_defaults
        """
        scenario = build_active_agreement(
            api,
            agreement_payload=make_agreement_payload(),
            station_code="MKE",
            pilots_required_per_aircraft=1,
            aircraft_allocation_cap=1,
        )

        cycle = validate_success(
            api.create_schedule_cycle(
                make_schedule_cycle_payload(
                    scenario.agreement_id, cycle_month="2026-11", published_departures=40
                ),
                headers=SCHEDULER_HEADERS,
            ),
            201,
        )

        assert_status(cycle, "PLANNED")
        assert cycle["published_departures"] == 40
        assert cycle["recorded_completed_legs"] == 0
        assert cycle["open_leg_count"] == 0
        assert cycle["cancelled_controllable_count"] == 0
        assert cycle["cancelled_uncontrollable_count"] == 0
        assert cycle["enplaned_bags_total"] == 0
        assert cycle["mishandled_bags_total"] == 0
        assert cycle["on_time_leg_count"] == 0
        assert_block_hours(cycle["credited_block_hours"], 0.000, "credited block hours")
        assert_money(cycle["estimated_passthrough_total_usd"], 0.00, "estimated pass-throughs")
        assert_money(cycle["passthrough_settlement_usd"], 0.00, "pass-through settlement")
        assert_is_null(cycle, "closed_at")

        assert cycle["metric_completed_departures"] == 40
        assert cycle["departure_ledger_total"] == 40
        assert_departure_ledger_identity(cycle)


class TestLegCompletionComputedFields:
    """The two derived leg fields come from the report, not from the request."""

    def test_completing_a_leg_computes_its_payment_and_punctuality(self, api):
        """Block hours at the contract rate plus the departure rate, rounded at the leg.

        PRD 3.4: "`leg_variable_payment_usd` is the leg's own variable earnings: the
        product of `actual_block_hours` and the agreement's `block_hour_rate_usd`, rounded
        half-up to two decimal places, plus the agreement's `departure_rate_usd`, which is
        already carried at two decimals."

        Design: Corner/entities/leg_completion_computes_variable_payment_and_on_time_flag
        """
        scenario = build_open_cycle(
            api,
            agreement_payload=make_agreement_payload(),
            station_code="MKE",
            pilots_required_per_aircraft=1,
            aircraft_allocation_cap=1,
            line_qualified_pilots=1,
            tail_numbers=["N2101RG"],
            cycle_month="2026-09",
            published_departures=10,
        )
        leg = add_leg(
            api,
            scenario,
            flight_number="SM6101",
            origin="MKE",
            destination="ORD",
            scheduled_departure_utc="2026-09-02T08:00:00Z",
            scheduled_arrival_utc="2026-09-02T09:30:00Z",
            planned_block_hours=1.500,
        )

        flown = validate_success(
            api.complete_flight_leg(
                leg["id"],
                make_completion_payload(
                    actual_block_hours=1.500,
                    actual_arrival_utc="2026-09-02T09:20:00Z",
                    enplaned_bags=90,
                    mishandled_bags=1,
                ),
                headers=OPS_HEADERS,
            )
        )

        assert_status(flown, "COMPLETED")
        assert flown["on_time"] is True, "ten minutes early is inside the grace allowance"
        assert_money(flown["leg_variable_payment_usd"], 2496.13, "leg variable payment")

        month = read_cycle(api, scenario.cycle_id)
        assert_block_hours(month["credited_block_hours"], 1.500, "credited block hours")
        assert month["recorded_completed_legs"] == 1
        assert month["on_time_leg_count"] == 1
        assert month["enplaned_bags_total"] == 90
        assert month["mishandled_bags_total"] == 1
        assert month["open_leg_count"] == 0
        assert month["departure_ledger_total"] == 10


class TestBrandAuditSystemFields:
    """Both status dimensions and the evidence reference are server-owned."""

    def test_a_new_audit_generates_its_two_statuses_and_leaves_evidence_null(self, api):
        """The caller names only the scope, the count and the severity.

        PRD 3.7: "A new audit opens with `finding_status` `OPEN`, `remediation_status`
        `NOT_STARTED` and `evidence_ref` null."

        Design: Corner/entities/brand_audit_system_fields_generated_not_accepted
        """
        scenario = build_active_agreement(
            api,
            agreement_payload=make_agreement_payload(),
            station_code="MKE",
            pilots_required_per_aircraft=1,
            aircraft_allocation_cap=1,
        )
        payload = make_brand_audit_payload(
            scenario.crew_base_id, audit_scope="CABIN_PRODUCT", findings_count=1, severity="MINOR"
        )

        audit = validate_success(api.create_brand_audit(payload, headers=AUDITOR_HEADERS), 201)

        assert_status(audit, "OPEN", field="finding_status")
        assert_status(audit, "NOT_STARTED", field="remediation_status")
        assert_is_null(audit, "evidence_ref")
        assert_common_fields(audit, expected_version=1)

        assert audit["base_id"] == scenario.crew_base_id
        assert audit["audit_scope"] == "CABIN_PRODUCT"
        assert audit["findings_count"] == 1
        assert audit["severity"] == "MINOR"


class TestAircraftEnumConstraint:
    """The ownership form accepts only its three declared members."""

    def test_a_plausible_but_undeclared_ownership_form_is_rejected(self, api):
        """No tail is registered and the fleet listing stays empty.

        PRD 3.3: "`ownership` is one of `REGIONAL_OWNED`, `MAINLINE_OWNED`, or `LEASED`,
        and only a `REGIONAL_OWNED` tail ever earns the agreement's
        `aircraft_ownership_fee_usd`."

        Design: Corner/entities/create_aircraft_invalid_ownership_enum_rejected
        """
        scenario = build_active_agreement(
            api,
            agreement_payload=make_agreement_payload(),
            station_code="MKE",
            pilots_required_per_aircraft=1,
            aircraft_allocation_cap=1,
        )

        response = api.create_aircraft(
            make_aircraft_payload(
                scenario.agreement_id,
                scenario.crew_base_id,
                tail_number="N2201RG",
                ownership="LEASED_FROM_MAINLINE",
            ),
            headers=OPS_HEADERS,
        )
        validate_error(response, ERR_INVALID_REQUEST, 400)

        fleet, meta = validate_paginated(
            api.list_aircraft(headers=OPS_HEADERS, params={"agreement_id": scenario.agreement_id})
        )
        assert fleet == []
        assert meta["total_count"] == 0


class TestBodyReferenceResolution:
    """Every relationship travels in the body, so every one of them is a body 404."""

    def test_a_leg_naming_an_unknown_captain_is_refused_before_any_business_rule(self, api):
        """The unresolvable captain is caught ahead of qualification and availability.

        PRD 2.10: "When a creation request names a related record — `agreement_id`,
        `assigned_base_id`, `base_id`, `cycle_id`, `aircraft_id`, or `captain_pilot_id` —
        that reference is resolved before any business rule is evaluated, and a reference
        that does not resolve yields `ERR_REFERENCE_NOT_FOUND` (HTTP 404)."

        Design: Corner/entities/create_flight_leg_with_unknown_pilot_reference_rejected
        """
        scenario = build_open_cycle(
            api,
            agreement_payload=make_agreement_payload(),
            station_code="MKE",
            pilots_required_per_aircraft=1,
            aircraft_allocation_cap=1,
            line_qualified_pilots=1,
            tail_numbers=["N2301RG"],
            cycle_month="2026-09",
            published_departures=10,
        )

        response = api.create_flight_leg(
            make_flight_leg_payload(
                scenario.cycle_id,
                scenario.aircraft_id,
                UNKNOWN_ID,
                flight_number="SM6201",
                origin="MKE",
                destination="ORD",
                scheduled_departure_utc="2026-09-02T08:00:00Z",
                scheduled_arrival_utc="2026-09-02T09:00:00Z",
                planned_block_hours=1.000,
            ),
            headers=SCHEDULER_HEADERS,
        )
        validate_error(response, ERR_REFERENCE_NOT_FOUND, 404)

        assert read_cycle(api, scenario.cycle_id)["open_leg_count"] == 0

    def test_a_pilot_hired_under_an_unknown_base_is_refused(self, api):
        """A pilot's parent is a base named in the body, so the failure is a body 404.

        PRD 2.10: "This body-reference resolution applies to the creation of crew bases,
        aircraft, pilots, schedule cycles, flight legs, pass-through claims, and brand
        audits."

        Design: Corner/entities/create_pilot_under_unknown_base_rejected
        """
        response = api.create_pilot(
            make_pilot_payload(
                UNKNOWN_ID,
                employee_ref="EMP-2401",
                seat="FIRST_OFFICER",
                hire_class_date="2026-06-01",
            ),
            headers=OPS_HEADERS,
        )
        error_id = validate_error(response, ERR_REFERENCE_NOT_FOUND, 404)["error_id"]
        assert error_id != "ERR_CREW_BASE_NOT_FOUND", (
            "the entity-specific code is reserved for identifiers that arrive in the path"
        )

        pilots, meta = validate_paginated(api.list_pilots(headers=OPS_HEADERS))
        assert pilots == []
        assert meta["total_count"] == 0
