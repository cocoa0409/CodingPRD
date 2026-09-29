"""The resource surface: what a create persists, what a read returns, how the
collections page and filter, and which code an unresolvable reference reports.
"""

import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    PAYROLL_ANALYST,
    STAFFING_OFFICER,
    factories as f,
    fixtures as fx,
    is_iso8601_timestamp,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestStationRegistration:
    """What a station read reports the moment it is registered."""

    def test_creation_echoes_every_input_and_opens_both_money_counters_at_zero(
        self, api
    ):
        """A station is born with both counters at zero and a WITHIN posture.

        PRD 3.1: "The station comes into existence with both money counters at
        zero and a `budget_posture` of `WITHIN`."

        Design: Corner/entities/station_creation_returns_persisted_and_derived_budget_fields
        """
        created = validate_success(
            api.create_station(
                {
                    "name": "Station 60",
                    "battalion_code": "D1",
                    "minimum_staffing_floor": 3,
                    "fiscal_ot_budget_cents": 500000,
                    "fiscal_period_start_date": "2026-08-01",
                    "fiscal_period_end_date": "2026-09-30",
                },
                STAFFING_OFFICER,
            ),
            201,
        )

        assert created["name"] == "Station 60"
        assert created["battalion_code"] == "D1"
        assert created["minimum_staffing_floor"] == 3
        assert created["fiscal_ot_budget_cents"] == 500000
        assert created["fiscal_period_start_date"] == "2026-08-01"
        assert created["fiscal_period_end_date"] == "2026-09-30"
        assert created["ot_committed_cents"] == 0
        assert created["ot_actual_cents"] == 0
        assert created["budget_posture"] == "WITHIN"
        assert created["version"] == 1
        assert isinstance(created["id"], str) and created["id"]

    def test_system_fields_are_server_minted_and_client_values_are_ignored(self, api):
        """The four system-managed properties are never client-supplied.

        PRD 2.4: "**`version`** (integer): a monotone counter that increments by
        one on every mutation of the record."

        Design: Corner/entities/station_system_fields_generated_input_ignored
        """
        response = api.create_station(
            {
                "id": NON_EXISTENT_UUID,
                "name": "Station 67",
                "battalion_code": "D3",
                "minimum_staffing_floor": 1,
                "fiscal_ot_budget_cents": 500000,
                "fiscal_period_start_date": "2026-08-01",
                "fiscal_period_end_date": "2026-09-30",
                "ot_actual_cents": 777777,
            },
            STAFFING_OFFICER,
        )
        created = validate_success(response, 201)

        assert created["id"] != NON_EXISTENT_UUID
        assert created["version"] == 1
        assert is_iso8601_timestamp(created["created_at"])
        assert is_iso8601_timestamp(created["updated_at"])
        assert created["ot_actual_cents"] == 0
        assert created["ot_committed_cents"] == 0

        meta = response.json()["meta"]
        assert meta["api_request_id"].startswith("req_")
        assert meta["api_request_timestamp"]


class TestFirefighterRecord:
    """Enrolment persists the member exactly as supplied, counters at zero."""

    def test_reading_a_member_returns_the_enrolled_record_with_zeroed_counters(
        self, api
    ):
        """Five hiring-order counters exist on every member and all start at zero.

        PRD 3.1: "Five counters exist on every member purely so that the hiring
        order can rank on them, and all five start at zero:
        `voluntary_ot_hours_charged` (overtime hours charged against the voluntary
        hiring order), `mandatory_holdover_count` (times held over under the
        mandatory-holdover article), `callback_count` (times called back from off
        duty), `ot_pass_count` (consecutive declines or expiries on voluntary
        offers) and `pending_offer_count` (how many of the member's offers
        currently sit in `OFFERED`)."

        Design: Corner/entities/firefighter_retrieval_returns_stored_record
        """
        station = fx.create_station(api, name="Station 61", battalion_code="D1")
        member = fx.create_firefighter(
            api,
            station["id"],
            full_name="P Prior",
            rank="ENGINEER",
            platoon="C",
            seniority_rank=5,
            kelly_day_cycle_position=2,
            certifications=["PARAMEDIC"],
            hourly_rate_cents=4321,
        )

        read = validate_success(
            api.get_firefighter(
                member["id"], fx.make_company_officer_headers(member["id"])
            ),
            200,
        )

        assert read["id"] == member["id"]
        assert read["station_id"] == station["id"]
        assert read["full_name"] == "P Prior"
        assert read["rank"] == "ENGINEER"
        assert read["platoon"] == "C"
        assert read["seniority_rank"] == 5
        assert read["kelly_day_cycle_position"] == 2
        assert read["hourly_rate_cents"] == 4321
        assert read["certifications"] == ["PARAMEDIC"]
        assert read["employment_status"] == "ACTIVE"
        assert read["roster_standing"] == "AVAILABLE"
        assert read["voluntary_ot_hours_charged"] == 0
        assert read["mandatory_holdover_count"] == 0
        assert read["callback_count"] == 0
        assert read["ot_pass_count"] == 0
        assert read["pending_offer_count"] == 0

    def test_reading_an_unknown_member_reports_its_own_not_found_code(self, api):
        """An unresolvable member reference reports the member code, not a generic one.

        PRD 2.6: "The specific code identifies the reference class:
        `ERR_STATION_NOT_FOUND` for a station reference,
        `ERR_FIREFIGHTER_NOT_FOUND` for `firefighter_id`, `acting_supervisor_id`,
        `requesting_firefighter_id` or `counterparty_firefighter_id`,
        `ERR_DUTY_SHIFT_NOT_FOUND` for `duty_shift_id`" - a member reference
        therefore resolves to the member code rather than a generic one.

        Design: Corner/entities/get_firefighter_with_unknown_id_returns_not_found
        """
        fx.create_station(api, name="Station 63", battalion_code="D1")

        response = api.get_firefighter(NON_EXISTENT_UUID, STAFFING_OFFICER)

        error = validate_error(response, ApiErrorId.FIREFIGHTER_NOT_FOUND.value, 404)
        assert isinstance(error["message"], str) and error["message"]
        assert response.json()["response_type"] == "error"

    @pytest.mark.parametrize(
        "bad_field,bad_value",
        [("platoon", "E"), ("kelly_day_cycle_position", 9)],
    )
    def test_out_of_set_enrolment_values_are_rejected(self, api, bad_field, bad_value):
        """Platoon is A to D and the Kelly slot is 1 through 8.

        PRD 3.1: "Two ordering keys drive nearly every selection in the system:
        `seniority_rank`, an integer of at least 1 where 1 denotes the most senior
        member in the department and which is unique department-wide; and
        `kelly_day_cycle_position`, an integer from 1 through 8 naming which slot
        of the eight-position Kelly cycle the member takes off."

        Design: Corner/entities/firefighter_create_invalid_platoon_enum_rejected
        """
        station = fx.create_station(api, name="Station 68", battalion_code="D3")

        payload = f.firefighter_payload(
            station["id"], full_name="Q Quist", **{bad_field: bad_value}
        )
        validate_error(
            api.create_firefighter(payload, STAFFING_OFFICER),
            ApiErrorId.INVALID_REQUEST.value,
            400,
        )

        _, meta = validate_paginated(
            api.list_firefighters(STAFFING_OFFICER, station_id=station["id"])
        )
        assert meta["total_count"] == 0


class TestApparatusRegistration:
    """Company registration: required inputs, defaults and the parent reference."""

    def test_registering_a_company_without_a_crew_size_is_rejected(self, api):
        """Every required field must be present and non-null.

        PRD 2.6: "3. **Request shape** — `ERR_INVALID_REQUEST` (400), applied to
        every POST endpoint. The body must parse; every required field must be
        present and non-null; every field must carry its declared type; every
        enumerated field's value must be a member of its declared set; every
        integer must lie inside its declared bounds; dates must be ISO 8601
        calendar dates and datetimes must be ISO 8601 UTC instants."

        Design: Corner/entities/apparatus_create_missing_required_minimum_crew_size_rejected
        """
        station = fx.create_station(api, name="Station 64", battalion_code="D2")

        payload = f.apparatus_payload(station["id"], unit_designation="ENGINE-64")
        payload.pop("minimum_crew_size")

        validate_error(
            api.create_apparatus(payload, STAFFING_OFFICER),
            ApiErrorId.INVALID_REQUEST.value,
            400,
        )

        _, meta = validate_paginated(
            api.list_apparatus(STAFFING_OFFICER, station_id=station["id"])
        )
        assert meta["total_count"] == 0

    def test_omitted_optional_company_fields_take_their_declared_defaults(self, api):
        """Closure exemption defaults to false and a new unit is in service.

        PRD 3.1: "A unit may be marked `closure_exempt`, defaulting to false; a
        true value marks a first-due company that may never be taken out of
        service by a closure action. A unit's `status` is `IN_SERVICE` on
        registration and may otherwise read `OUT_OF_SERVICE`, in which case the
        unit stops contributing to the staffing requirement altogether."

        Design: Corner/entities/apparatus_create_applies_closure_exempt_and_status_defaults
        """
        station = fx.create_station(api, name="Station 65", battalion_code="D2")

        engine = validate_success(
            api.create_apparatus(
                {
                    "station_id": station["id"],
                    "unit_designation": "ENGINE-65",
                    "apparatus_type": "ENGINE",
                    "minimum_crew_size": 3,
                    "required_certifications": [],
                    "closure_priority": 10,
                },
                STAFFING_OFFICER,
            ),
            201,
        )
        assert engine["closure_exempt"] is False
        assert engine["status"] == "IN_SERVICE"

        medic = validate_success(
            api.create_apparatus(
                {
                    "station_id": station["id"],
                    "unit_designation": "MEDIC-65",
                    "apparatus_type": "MEDIC",
                    "minimum_crew_size": 2,
                    "required_certifications": ["PARAMEDIC"],
                    "closure_priority": 40,
                    "closure_exempt": True,
                    "status": "OUT_OF_SERVICE",
                },
                STAFFING_OFFICER,
            ),
            201,
        )
        assert medic["closure_exempt"] is True
        assert medic["status"] == "OUT_OF_SERVICE"
        assert medic["required_certifications"] == ["PARAMEDIC"]
        assert medic["closure_priority"] == 40

    def test_registering_a_company_under_an_unknown_station_reports_the_station_code(
        self, api
    ):
        """The body's foreign keys are resolved in the order the endpoint declares.

        PRD 2.6: "4. **Reference existence** — the 404 family. Path parameters are
        resolved first, strictly left to right; then the body's foreign keys are
        resolved in the order the endpoint declares them."

        Design: Corner/entities/apparatus_create_with_unknown_station_returns_station_not_found
        """
        station = fx.create_station(api, name="Station 69", battalion_code="D3")

        validate_error(
            api.create_apparatus(
                f.apparatus_payload(NON_EXISTENT_UUID, unit_designation="ENGINE-69"),
                STAFFING_OFFICER,
            ),
            ApiErrorId.STATION_NOT_FOUND.value,
            404,
        )

        _, meta = validate_paginated(
            api.list_apparatus(STAFFING_OFFICER, station_id=station["id"])
        )
        assert meta["total_count"] == 0


class TestDutyShiftDerivedOnOpen:
    """A brand-new shift already carries its derived staffing picture."""

    def test_the_staffing_requirement_counts_only_the_in_service_companies(self, api):
        """Out-of-service units contribute nothing to the requirement.

        PRD 2.11: "`required_staffing` is the sum of `minimum_crew_size` over the
        station's **open companies** for that shift — the apparatus whose
        `station_id` is the shift's station, whose `status` is `IN_SERVICE`, and
        whose `id` does not appear in the shift's `closed_apparatus_ids`."

        Design: Corner/entities/duty_shift_computed_staffing_fields_input_ignored
        """
        station = fx.create_station(
            api, name="Station 66", battalion_code="D2", minimum_staffing_floor=2
        )
        fx.create_apparatus(
            api,
            station["id"],
            unit_designation="ENGINE-66",
            minimum_crew_size=5,
            required_certifications=[],
            closure_priority=10,
        )
        fx.create_apparatus(
            api,
            station["id"],
            unit_designation="MEDIC-66",
            apparatus_type="MEDIC",
            minimum_crew_size=2,
            required_certifications=[],
            closure_priority=20,
        )
        fx.create_apparatus(
            api,
            station["id"],
            unit_designation="TRUCK-66",
            apparatus_type="LADDER",
            minimum_crew_size=4,
            required_certifications=[],
            closure_priority=30,
            status="OUT_OF_SERVICE",
        )

        shift = validate_success(
            api.create_duty_shift(
                {
                    "station_id": station["id"],
                    "shift_date": "2026-08-11",
                    "platoon": "C",
                    "required_staffing": 1,
                },
                STAFFING_OFFICER,
            ),
            201,
        )

        assert shift["required_staffing"] == 7
        assert shift["leave_floor_headcount"] == 5
        assert shift["assigned_headcount"] == 0
        assert shift["staffing_gap"] == 7
        assert shift["certification_gap_count"] == 0
        assert shift["staffing_posture"] == "CRITICAL"
        assert shift["status"] == "DRAFT"
        assert shift["ops_run_index"] == 0
        assert shift["closed_apparatus_ids"] == []
        assert shift["open_vacancy_count"] == 0

    def test_shift_listing_pages_in_date_order_and_reports_the_total(self, api):
        """Duty shifts are ordered by shift date, not by creation order.

        PRD 2.3: "Duty shifts are ordered by `shift_date` ascending, then
        `platoon` ascending, then `created_at` ascending."

        Design: Corner/entities/duty_shift_listing_paginates_and_reports_total_count
        """
        station = fx.create_station(api, name="Station 62", battalion_code="D1")
        last = fx.create_duty_shift(api, station["id"], "2026-08-12", "D")
        first = fx.create_duty_shift(api, station["id"], "2026-08-10", "B")
        middle = fx.create_duty_shift(api, station["id"], "2026-08-11", "C")

        page_one, meta_one = validate_paginated(
            api.list_duty_shifts(
                PAYROLL_ANALYST, station_id=station["id"], limit=2, offset=0
            )
        )
        assert len(page_one) == 2
        assert meta_one["total_count"] == 3
        assert meta_one["has_more"] is True
        assert meta_one["limit"] == 2
        assert meta_one["offset"] == 0
        assert [row["id"] for row in page_one] == [first["id"], middle["id"]]

        page_two, meta_two = validate_paginated(
            api.list_duty_shifts(
                PAYROLL_ANALYST, station_id=station["id"], limit=2, offset=2
            )
        )
        assert [row["id"] for row in page_two] == [last["id"]]
        assert meta_two["total_count"] == 3
        assert meta_two["has_more"] is False
        assert meta_two["offset"] == 2


class TestReferenceFilters:
    """The self-referential link and the polymorphic driver reference are queryable."""

    def test_supervisor_and_driver_source_filters_each_return_exactly_one_row(
        self, api
    ):
        """Both the supervisor link and the polymorphic driver reference filter.

        PRD 2.3: "Vacancies accept `duty_shift_id`, `apparatus_id`,
        `filled_by_assignment_id`, `driver`, the polymorphic `driver_source_id`,
        `required_certification` and `status`."

        Design: Corner/entities/self_referential_and_polymorphic_reference_filters_resolve
        """
        station = fx.create_station(
            api, name="Station 70", battalion_code="D4", fiscal_ot_budget_cents=900000
        )
        engine = fx.create_apparatus(
            api,
            station["id"],
            unit_designation="ENGINE-70",
            minimum_crew_size=2,
            required_certifications=[],
            closure_priority=10,
        )
        supervisor = fx.create_firefighter(
            api,
            station["id"],
            full_name="S Silva",
            rank="CAPTAIN",
            platoon="C",
            seniority_rank=9,
            kelly_day_cycle_position=3,
            certifications=[],
            hourly_rate_cents=5000,
        )
        subordinate = fx.create_firefighter(
            api,
            station["id"],
            full_name="T Tobin",
            platoon="C",
            seniority_rank=1,
            kelly_day_cycle_position=1,
            certifications=[],
            hourly_rate_cents=4000,
            acting_supervisor_id=supervisor["id"],
        )
        other = fx.create_firefighter(
            api,
            station["id"],
            full_name="U Uribe",
            platoon="C",
            seniority_rank=2,
            kelly_day_cycle_position=2,
            certifications=[],
            hourly_rate_cents=4000,
        )

        shift = fx.published_shift(api, station["id"], "2026-08-11", "C")
        fx.seat_member(
            api, shift["id"], subordinate["id"], engine["id"], supervisor["id"]
        )
        fx.seat_member(api, shift["id"], other["id"], engine["id"], supervisor["id"])
        backfilled = fx.approved_leave_with_backfill(
            api, shift["id"], subordinate["id"], supervisor["id"], "VACATION", 24
        )

        subordinates, sub_meta = validate_paginated(
            api.list_firefighters(
                STAFFING_OFFICER, acting_supervisor_id=supervisor["id"]
            )
        )
        assert sub_meta["total_count"] == 1
        assert [row["id"] for row in subordinates] == [subordinate["id"]]

        driven, driven_meta = validate_paginated(
            api.list_vacancies(
                STAFFING_OFFICER,
                driver="LEAVE",
                driver_source_id=backfilled["leave"]["id"],
            )
        )
        assert driven_meta["total_count"] == 1
        assert driven[0]["driver"] == "LEAVE"
        assert driven[0]["driver_source_id"] == backfilled["leave"]["id"]
        assert driven[0]["duty_shift_id"] == shift["id"]
        assert driven[0]["status"] == "OPEN"
        assert backfilled["leave"]["backfill_vacancy_id"] == driven[0]["id"]


class TestSupportingCollections:
    """Every supporting collection answers a filtered list; an empty one is not a 404."""

    def test_rosters_offers_leave_and_trades_all_list_and_the_vacancy_reads_by_id(
        self, api
    ):
        """An empty collection returns an empty array, and the vacancy detail reads.

        PRD 2.3: "Every list response carries `limit`, `offset`, `total_count` and
        `has_more` inside the `meta` object of the envelope."

        Design: Corner/entities/every_supporting_collection_is_listable_and_the_vacancy_is_readable_by_id
        """
        station = fx.create_station(
            api,
            name="Station 135",
            battalion_code="G6",
            fiscal_ot_budget_cents=900000,
            fiscal_period_end_date="2026-08-31",
        )
        engine = fx.create_apparatus(
            api,
            station["id"],
            unit_designation="ENGINE-135",
            minimum_crew_size=2,
            required_certifications=[],
            closure_priority=10,
        )
        seated = fx.create_firefighter(
            api,
            station["id"],
            full_name="A Alcott",
            platoon="C",
            seniority_rank=1,
            kelly_day_cycle_position=1,
            certifications=[],
            hourly_rate_cents=4000,
        )
        unseated = fx.create_firefighter(
            api,
            station["id"],
            full_name="B Brill",
            platoon="C",
            seniority_rank=2,
            kelly_day_cycle_position=2,
            certifications=[],
            hourly_rate_cents=4000,
        )
        officer = fx.create_firefighter(
            api,
            station["id"],
            full_name="C Calder",
            rank="CAPTAIN",
            platoon="C",
            seniority_rank=9,
            kelly_day_cycle_position=3,
            certifications=[],
            hourly_rate_cents=5000,
        )
        roster = fx.create_hiring_roster(api, station["id"], "VOLUNTARY_OT", "NONE")

        shift = fx.published_shift(api, station["id"], "2026-08-11", "C")
        seat = fx.seat_member(
            api, shift["id"], seated["id"], engine["id"], officer["id"]
        )
        vacancy = fx.first_vacancy(api, duty_shift_id=shift["id"], status="OPEN")
        offer = fx.dispatch_offer(api, vacancy["id"], "VOLUNTARY", 24)
        leave = fx.file_leave(api, seated["id"], shift["id"], "VACATION", 24)

        rosters, roster_meta = validate_paginated(
            api.list_hiring_rosters(
                PAYROLL_ANALYST, station_id=station["id"], roster_type="VOLUNTARY_OT"
            )
        )
        assert roster_meta["total_count"] == 1
        assert rosters[0]["id"] == roster["id"]

        offers, offer_meta = validate_paginated(
            api.list_overtime_offers(
                fx.make_company_officer_headers(officer["id"]),
                vacancy_id=vacancy["id"],
                status="OFFERED",
            )
        )
        assert offer_meta["total_count"] == 1
        assert offers[0]["id"] == offer["id"]
        assert offers[0]["firefighter_id"] == unseated["id"]

        leaves, leave_meta = validate_paginated(
            api.list_leave_requests(
                fx.make_firefighter_headers(seated["id"]),
                firefighter_id=seated["id"],
                status="QUEUED",
            )
        )
        assert leave_meta["total_count"] == 1
        assert leaves[0]["id"] == leave["id"]
        assert leaves[0]["decision_order_index"] is None

        trades_response = api.list_trade_requests(
            STAFFING_OFFICER, duty_shift_id=shift["id"]
        )
        trades, trade_meta = validate_paginated(trades_response)
        assert trades == []
        assert trade_meta["total_count"] == 0
        assert trades_response.json()["response_type"] == "array"

        detail = validate_success(
            api.get_vacancy(vacancy["id"], STAFFING_OFFICER), 200
        )
        assert detail["status"] == "OFFERING"
        assert detail["driver"] == "VACANT_POSITION"
        assert detail["required_certification"] == "NONE"
        assert detail["filled_by_assignment_id"] is None
        assert detail["duty_shift_id"] == shift["id"]

        filled, filled_meta = validate_paginated(
            api.list_vacancies(
                STAFFING_OFFICER, duty_shift_id=shift["id"], status="FILLED"
            )
        )
        assert filled_meta["total_count"] == 1
        assert filled[0]["filled_by_assignment_id"] == seat["id"]
