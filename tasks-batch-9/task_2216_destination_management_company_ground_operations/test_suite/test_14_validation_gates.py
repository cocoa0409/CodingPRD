"""Aggregate ceilings, clock-relative lead time, insurance cover and a clean create."""

from test_helpers import (
    CONTRACT_SENDER_USER_ID,
    CONTRACT_SIGNER_USER_ID,
    TEST_USERS,
    ApiErrorId,
    add_element,
    confirm_assignment,
    create_permit,
    create_program,
    create_program_element_payload,
    create_staff_member,
    create_supplier,
    create_venue,
    draft_contract,
    lock_design,
    make_supplier_manager_headers,
    propose_assignment,
    read_program,
    set_clock,
    validate_error,
    validate_success,
)

PD = TEST_USERS["program_director_headers"]
PO = TEST_USERS["permit_officer_headers"]
SM = TEST_USERS["supplier_manager_headers"]

SENDER = make_supplier_manager_headers(CONTRACT_SENDER_USER_ID)
SIGNER = make_supplier_manager_headers(CONTRACT_SIGNER_USER_ID)


class TestStaffDailyCeilingIsAggregate:
    MORNING_ELEMENT = {
        "element_type": "ACTIVITY",
        "title": "Cap E1",
        "starts_at": "2026-09-11T08:00:00Z",
        "ends_at": "2026-09-11T12:00:00Z",
        "planned_headcount": 20,
        "guaranteed_headcount": 20,
        "per_person_cost_cents": 4_000,
    }
    AFTERNOON_ELEMENT = {
        "element_type": "ACTIVITY",
        "title": "Cap E2",
        # One minute after the morning element ends: no overlap, and no rest gap to clear.
        "starts_at": "2026-09-11T12:01:00Z",
        "ends_at": "2026-09-11T17:00:00Z",
        "planned_headcount": 20,
        "guaranteed_headcount": 20,
        "per_person_cost_cents": 4_000,
    }
    PRIYA = {
        "full_name": "Priya Raman",
        "role_type": "COORDINATOR",
        "pay_rate_cents_per_hour": 3_600,
        "min_rest_minutes": 0,
        "max_daily_minutes": 480,
    }

    def _two_shifts_of_240_and_299_minutes(self):
        """Each shift fits under the 480-minute ceiling; together they reach 539."""
        venue_a = create_venue(
            name="Cap Venue A", capacity_seated=100, capacity_reception=200
        )
        venue_b = create_venue(
            name="Cap Venue B", capacity_seated=100, capacity_reception=200
        )
        supplier = create_supplier(legal_name="Cap Supplier")
        program = create_program(
            client_name="Cap Client", group_name="Cap Group", guaranteed_count=20
        )
        morning = add_element(
            program["id"], supplier["id"], venue_id=venue_a["id"], **self.MORNING_ELEMENT
        )
        afternoon = add_element(
            program["id"], supplier["id"], venue_id=venue_b["id"], **self.AFTERNOON_ELEMENT
        )
        # Confirmation is only open once the element set is frozen.
        lock_design(program["id"])
        staff = create_staff_member(**self.PRIYA)
        first = propose_assignment(
            staff["id"],
            program["id"],
            element_id=morning["id"],
            starts_at="2026-09-11T08:00:00Z",
            ends_at="2026-09-11T12:00:00Z",
        )
        confirm_assignment(first["id"])
        second = propose_assignment(
            staff["id"],
            program["id"],
            element_id=afternoon["id"],
            starts_at="2026-09-11T12:01:00Z",
            ends_at="2026-09-11T17:00:00Z",
        )
        return {
            "program": program,
            "staff": staff,
            "first": first,
            "second": second,
        }

    def test_two_individually_legal_shifts_breach_the_ceiling_together(self, api):
        """PRD §3.6: "Add up the scheduled minutes of the member's assignments in
        `CONFIRMED`, `CHECKED_IN` or `COMPLETED` whose `starts_at` falls on the same UTC
        calendar day as the candidate's `starts_at`, add the candidate's own minutes, and
        require the result to be at most the member's `max_daily_minutes`."

        Design: Corner/validations/staff_daily_minute_cap_is_aggregate_not_per_shift
        """
        ctx = self._two_shifts_of_240_and_299_minutes()

        response = api.confirm_staff_assignment(ctx["second"]["id"], PD)

        validate_error(response, ApiErrorId.ERR_STAFF_DAILY_LIMIT_EXCEEDED.value, 422)
        failed_with = response.json()["data"]["error_id"]
        # The shifts abut without touching, so neither scheduling neighbour rule fires.
        assert failed_with != ApiErrorId.ERR_STAFF_ASSIGNMENT_OVERLAP.value
        assert failed_with != ApiErrorId.ERR_STAFF_REST_GAP_VIOLATION.value

    def test_the_rejected_confirmation_leaves_the_accumulator_at_the_first_shift(self, api):
        """PRD §3.6: "A confirmation that clears all of that runs the **planned** variant of
        the labour-cost calculation, writes the result to `planned_labor_cost_cents`, adds the
        assignment's scheduled minutes to the member's `confirmed_minutes_total`, and
        increments the assignment's `version`."

        Design: Corner/validations/staff_daily_minute_cap_is_aggregate_not_per_shift
        """
        ctx = self._two_shifts_of_240_and_299_minutes()
        api.confirm_staff_assignment(ctx["second"]["id"], PD)

        staff = validate_success(api.get_staff_member(ctx["staff"]["id"], PD))

        assert staff["confirmed_minutes_total"] == 240
        assert (
            validate_success(api.get_staff_assignment(ctx["first"]["id"], PD))["status"]
            == "CONFIRMED"
        )
        assert (
            validate_success(api.get_staff_assignment(ctx["second"]["id"], PD))["status"]
            == "PROPOSED"
        )
        assert read_program(ctx["program"]["id"])["staffing_gap_count"] == 0


class TestPermitLeadTimeFollowsTheClock:
    GALA = {
        "element_type": "OFF_PREMISE_EVENT",
        "title": "Warehouse Gala",
        "starts_at": "2026-09-11T09:00:00Z",
        "ends_at": "2026-09-11T12:00:00Z",
        "planned_headcount": 60,
        "guaranteed_headcount": 60,
        "per_person_cost_cents": 4_000,
    }

    def _permit_demanding_forty_five_days(self):
        venue = create_venue(
            name="Lead Time Venue",
            capacity_seated=100,
            capacity_reception=300,
            requires_special_venue_permit=True,
        )
        supplier = create_supplier(legal_name="Lead Time Supplier")
        program = create_program(
            client_name="Lead Time Client",
            group_name="Lead Time Group",
            guaranteed_count=60,
        )
        element = add_element(
            program["id"], supplier["id"], venue_id=venue["id"], **self.GALA
        )
        return create_permit(
            element["id"],
            permit_type="SPECIAL_VENUE",
            authority_name="City Licensing Board",
            lead_time_days_required=45,
        )

    def test_the_same_permit_is_refused_and_then_accepted_as_the_clock_moves(self, api):
        """PRD §3.4: "The lead-time test is the substantive one: take the interval from the
        logical clock's current instant to the element's `starts_at`, express it in whole
        24-hour days by discarding any fractional remainder, and require that the result be at
        least the permit's `lead_time_days_required`."

        Design: Corner/validations/permit_lead_time_depends_on_clock_position_not_on_the_permit
        """
        permit = self._permit_demanding_forty_five_days()

        # 41 whole days from 2026-08-01T00:00Z to the element's start.
        too_late = api.submit_permit(permit["id"], PO)

        validate_error(too_late, ApiErrorId.ERR_PERMIT_LEAD_TIME_INSUFFICIENT.value, 422)
        assert validate_success(api.get_permit(permit["id"], PO))["status"] == "DRAFT"

        # 53 whole days from 2026-07-20T00:00Z to the very same element start.
        set_clock("2026-07-20T00:00:00Z")
        in_time = api.submit_permit(permit["id"], PO)

        submitted = validate_success(in_time)
        assert submitted["status"] == "SUBMITTED"
        assert submitted["resubmission_count"] == 0
        assert submitted["submitted_at"].startswith("2026-07-20T00:00:00")


class TestCountersignNeedsSufficientCover:
    THIN_COVER_SUPPLIER = {
        "legal_name": "Thin Cover Transport",
        "supplier_type": "TRANSPORT",
        "insurance_liability_limit_cents": 50_000_000,
    }

    def _contract_demanding_more_cover_than_the_supplier_carries(self):
        supplier = create_supplier(**self.THIN_COVER_SUPPLIER)
        program = create_program(
            client_name="Insurance Client",
            group_name="Insurance Group",
            guaranteed_count=30,
        )
        contract = draft_contract(
            program["id"],
            supplier["id"],
            contract_value_cents=300_000,
            required_liability_limit_cents=100_000_000,
            deposit_pct=0.3,
        )
        return {"supplier": supplier, "contract": contract}

    def test_a_thin_certificate_blocks_the_send_and_the_contract_stays_in_draft(self, api):
        """PRD §3.3: "A send from `DRAFT` additionally requires that the supplier's `status`
        be `APPROVED` — otherwise `ERR_SUPPLIER_NOT_APPROVED` — and that the supplier's
        insurance actually satisfy this contract: `coi_verified` must be true,
        `insurance_expires_on` must be at or after the logical clock's current instant, and
        `insurance_liability_limit_cents` must be at least the contract's
        `required_liability_limit_cents`."

        Design: Corner/validations/countersign_blocked_while_supplier_liability_limit_is_below_the_contract_requirement
        """
        ctx = self._contract_demanding_more_cover_than_the_supplier_carries()

        response = api.send_supplier_contract(ctx["contract"]["id"], SENDER)

        validate_error(
            response, ApiErrorId.ERR_SUPPLIER_INSURANCE_INSUFFICIENT.value, 422
        )
        stored = validate_success(api.get_supplier_contract(ctx["contract"]["id"], SM))
        assert stored["status"] == "DRAFT"
        assert stored["deposit_due_cents"] == 0
        assert stored["round_count"] == 0

    def test_topping_the_cover_up_to_exactly_the_requirement_clears_the_gate(self, api):
        """PRD §3.3: "On success it stamps `countersigned_by_user_id` with the acting
        `X-User-ID`, computes `deposit_due_cents` as the contract value multiplied by
        `deposit_pct` and rounded half up to whole cents, sets `deposit_paid_cents` equal to
        `deposit_due_cents` — the deposit is treated as banked at signature — and increments
        the contract's `version`."

        Design: Corner/validations/countersign_blocked_while_supplier_liability_limit_is_below_the_contract_requirement
        """
        ctx = self._contract_demanding_more_cover_than_the_supplier_carries()
        api.send_supplier_contract(ctx["contract"]["id"], SENDER)

        patched = validate_success(
            api.patch_supplier(
                ctx["supplier"]["id"], {"insurance_liability_limit_cents": 100_000_000}, SM
            )
        )
        validate_success(api.send_supplier_contract(ctx["contract"]["id"], SENDER))
        countersigned = validate_success(
            api.countersign_supplier_contract(ctx["contract"]["id"], SIGNER)
        )

        assert patched["insurance_liability_limit_cents"] == 100_000_000
        assert patched["version"] == 2
        assert countersigned["status"] == "ACTIVE"
        assert countersigned["deposit_due_cents"] == 90_000
        assert countersigned["deposit_paid_cents"] == 90_000


class TestElementCreateHappyPath:
    INCUMBENT = {
        "element_type": "ACTIVITY",
        "title": "Incumbent",
        "starts_at": "2026-09-11T09:00:00Z",
        "ends_at": "2026-09-11T11:00:00Z",
        "planned_headcount": 40,
        "guaranteed_headcount": 40,
        "per_person_cost_cents": 4_000,
    }
    SEATED_DINNER = {
        "element_type": "DINE_AROUND",
        "title": "Seated Dinner",
        # 12:30Z is exactly the incumbent's 11:00Z end plus the 90-minute buffer.
        "starts_at": "2026-09-11T12:30:00Z",
        "ends_at": "2026-09-11T15:00:00Z",
        "planned_headcount": 65,
        "guaranteed_headcount": 65,
        "per_person_cost_cents": 6_000,
    }

    def test_a_candidate_satisfying_window_turnover_and_capacity_is_created(self, api):
        """PRD §3.2: "A new element lands in `PLANNED`, and the create recomputes the
        programme's `element_count` and `open_element_count` and increments the programme's
        `version`."

        Design: Corner/validations/element_create_succeeds_when_every_rule_is_satisfied
        """
        venue = create_venue(
            name="Happy Path Venue",
            capacity_seated=100,
            capacity_reception=200,
            turnover_buffer_minutes=90,
        )
        supplier = create_supplier(legal_name="Happy Path Supplier")
        program = create_program(
            client_name="Happy Path Client",
            group_name="Happy Path Group",
            guaranteed_count=65,
        )
        add_element(program["id"], supplier["id"], venue_id=venue["id"], **self.INCUMBENT)
        current = read_program(program["id"])

        response = api.create_program_element(
            create_program_element_payload(
                program["id"],
                supplier["id"],
                current["version"],
                venue_id=venue["id"],
                **self.SEATED_DINNER,
            ),
            PD,
        )

        element = validate_success(response, 201)
        assert response.json()["response_type"] == "object"
        assert element["status"] == "PLANNED"
        assert element["planned_headcount"] == 65
        program = read_program(program["id"])
        assert program["element_count"] == 2
        assert program["open_element_count"] == 2
