"""Declared transitions: initial states, terminal lockdown, replays, side effects."""

from test_helpers import (
    entries_of_type,
    factories,
    fixtures,
    make_tire_technician_headers,
    validate_error,
    validate_success,
)


class TestCasingInitialState:
    def test_a_fresh_casing_opens_on_wheel_with_no_retreads_behind_it(self, api):
        """PRD §3.4: "A new casing starts `ON_WHEEL`, with `inspection_grade`,
        `inspected_by_user_id`, `collected_at_location_id`, `scrap_manifest_id` and
        `rejection_reason` all empty and `provisional_credit_cents` at 0."
        PRD §3.1: "New accounts start with `status` of `ACTIVE` and a
        `casing_credit_balance_cents` of 0."

        Design: Corner/state_machines/casing_initial_state_is_on_wheel
        """
        program = fixtures.setup_fleet_program()

        casing = validate_success(
            api.create_casing(
                factories.casing_payload(
                    program["fleet"]["id"], casing_serial="CS-4011"
                ),
                fixtures.ADMIN,
            ),
            expected_status=201,
        )

        assert casing["status"] == "ON_WHEEL"
        assert casing["retread_count"] == 0, (
            "the cycle returns to ON_WHEEL too, so the count is what tells them apart"
        )
        fleet = fixtures.read_fleet(program["fleet"]["id"])
        assert fleet["status"] == "ACTIVE"
        assert fleet["casing_credit_balance_cents"] == 0


class TestCollectIsDeclaredOnlyFromOnWheel:
    def test_a_second_collect_cannot_re_stamp_the_holding_location(self, api):
        """PRD §3.4: "A `TireTechnician` supplies `collected_at_location_id`, and the
        casing advances `ON_WHEEL → COLLECTED`; a casing in any other status is
        rejected with `ERR_CASING_INVALID_STATE`."
        PRD §2.10: "A service location's `casings_in_holding_count` is the number of
        casings whose `collected_at_location_id` is that location and whose `status` is
        one of `COLLECTED`, `INSPECTED`, `REJECTED`, `RETREAD_QUEUED` or `IN_RETREAD`."

        Design: Corner/state_machines/casing_collect_from_collected_returns_invalid_state
        """
        program = fixtures.setup_fleet_program()
        location_a = program["location"]
        location_b = fixtures.create_location(state_code="IN")
        casing = fixtures.create_collected_casing(
            program["fleet"]["id"], location_a["id"], casing_serial="CS-4012"
        )

        validate_error(
            api.collect_casing(
                casing["id"],
                factories.collect_casing_payload(location_b["id"]),
                fixtures.TECH,
            ),
            "ERR_CASING_INVALID_STATE",
            expected_status=409,
        )

        assert (
            fixtures.read_casing(casing["id"])["collected_at_location_id"]
            == location_a["id"]
        )
        assert fixtures.read_location(location_a["id"])["casings_in_holding_count"] == 1
        assert fixtures.read_location(location_b["id"])["casings_in_holding_count"] == 0


class TestPaidIsTerminal:
    def test_a_settled_invoice_can_no_longer_be_disputed(self, api):
        """PRD §3.8: "Both `PAID` and `DISPUTED` are terminal for an invoice;
        submitting an invoice that is not `OPEN`, or settling or disputing one that is
        not `SUBMITTED`, is rejected with `ERR_INVOICE_INVALID_STATE`."
        PRD §3.8: "The clerk supplies `paid_amount_cents`, which must equal the
        invoice's `total_cents` exactly; a partial or excess amount is rejected with
        `ERR_PAYMENT_AMOUNT_MISMATCH`."

        Design: Corner/state_machines/invoice_paid_is_terminal_and_rejects_dispute
        """
        program = fixtures.setup_submitted_invoice()
        invoice = program["invoice"]
        assert invoice["subtotal_cents"] == 12820
        assert invoice["discount_cents"] == 1603
        assert invoice["credit_applied_cents"] == 0, "nothing was ever accrued"
        assert invoice["total_cents"] == 11217

        paid = fixtures.settle_invoice(invoice["id"], 11217)
        assert paid["status"] == "PAID"

        validate_error(
            api.dispute_cross_location_invoice(
                invoice["id"],
                factories.dispute_invoice_payload("Late objection"),
                fixtures.CLERK,
            ),
            "ERR_INVOICE_INVALID_STATE",
            expected_status=409,
        )

        assert fixtures.read_invoice(invoice["id"])["status"] == "PAID"
        assert (
            fixtures.read_call(program["calls"][0]["id"])["billing_status"] == "SETTLED"
        )
        assert fixtures.list_ledger(program["fleet"]["id"]) == [], (
            "a zero credit posts nothing on submit and leaves nothing to reverse"
        )


class TestSubmitIsNotIdempotent:
    def test_replaying_a_submit_cannot_double_consume_the_credit(self, api):
        """PRD §3.8: "When `credit_applied_cents` is greater than 0, an `APPLICATION`
        ledger entry is posted whose `amount_cents` is the negation of
        `credit_applied_cents`, carrying a null `casing_id`, a `source_entity_type` of
        `CROSS_LOCATION_INVOICE` and this invoice's identifier as `source_entity_id`;
        when `credit_applied_cents` is 0, no entry is posted at all."
        PRD §2.8: "The fleet account's `casing_credit_balance_cents` is the sum of
        `amount_cents` over every entry carrying that fleet's `fleet_account_id`, with
        no filter on entry type, age or status."

        Design: Corner/state_machines/invoice_double_submit_is_not_idempotent
        """
        program = fixtures.setup_submitted_invoice(credit_grade="B")
        invoice = program["invoice"]
        assert invoice["net_before_credit_cents"] == 11217
        assert invoice["credit_applied_cents"] == 2804, (
            "25 percent of 11217 is 2804.25, truncated, and below the 10500 balance"
        )
        assert invoice["total_cents"] == 8413

        validate_error(
            api.submit_cross_location_invoice(invoice["id"], {}, fixtures.CLERK),
            "ERR_INVOICE_INVALID_STATE",
            expected_status=409,
        )

        entries = fixtures.list_ledger(program["fleet"]["id"])
        assert len(entries) == 2, "the replay posted nothing"
        assert [e["amount_cents"] for e in entries_of_type(entries, "ACCRUAL")] == [10500]
        assert [
            e["amount_cents"] for e in entries_of_type(entries, "APPLICATION")
        ] == [-2804]
        assert (
            fixtures.read_fleet(program["fleet"]["id"])["casing_credit_balance_cents"]
            == 7696
        ), "not 4892, which is what a second application would have left"


class TestArrivalIsScopedToTheAssignedTechnician:
    def test_only_the_dispatched_technician_may_record_arrival(self, api):
        """PRD §2.1: "When `X-User-Role` is `TireTechnician`, `X-User-ID` is the `id` of
        the acting `Technician`; a technician recording arrival or completion on a road
        service call must be the technician named in that call's `technician_id`, and
        any other technician is rejected with `ERR_TECHNICIAN_SCOPE_VIOLATION` (HTTP
        403)."
        PRD §3.6: "On a `NORMAL` call, the commitment is the location baseline plus a
        grace allowance of one hour, that is 60 minutes."

        Design: Corner/state_machines/arrive_by_unassigned_technician_returns_scope_violation
        """
        program = fixtures.setup_fleet_program()
        vehicle = fixtures.create_vehicle(program["fleet"]["id"])
        assigned = fixtures.create_technician(
            program["location"]["id"], certification_level="TIA_CERTIFIED"
        )
        bystander = fixtures.create_technician(
            program["location"]["id"], certification_level="TIA_CERTIFIED"
        )
        call = fixtures.open_call(
            program["fleet"]["id"],
            vehicle["id"],
            program["location"]["id"],
            "2026-08-12T12:00:00Z",
        )
        fixtures.dispatch_call(
            call["id"], "2026-08-12T12:05:00Z", 5, assigned["id"]
        )

        payload = factories.arrive_payload("2026-08-12T13:00:00Z")
        validate_error(
            api.arrive_road_service_call(
                call["id"], payload, make_tire_technician_headers(bystander["id"])
            ),
            "ERR_TECHNICIAN_SCOPE_VIOLATION",
            expected_status=403,
        )

        refused = fixtures.read_call(call["id"])
        assert refused["dispatch_status"] == "DISPATCHED"
        assert refused.get("arrived_at") is None
        assert fixtures.read_technician(bystander["id"])["status"] == "AVAILABLE", (
            "a refused arrival changes no technician state"
        )

        arrived = validate_success(
            api.arrive_road_service_call(
                call["id"], payload, make_tire_technician_headers(assigned["id"])
            )
        )
        assert arrived["dispatch_status"] == "ON_SITE"
        assert arrived["committed_response_minutes"] == 180
        assert arrived["actual_response_minutes"] == 60
        assert arrived["sla_met"] is True


class TestDispatchSideEffects:
    def test_one_dispatch_applies_every_declared_side_effect(self, api):
        """PRD §3.6: "On success the call records `technician_id`, `dispatched_at` and
        `dispatch_miles`, the assigned technician moves `AVAILABLE → ON_CALL`, and the
        unit's `status` becomes `OUT_OF_SERVICE` — a vehicle reads `OUT_OF_SERVICE` for
        exactly as long as some call for it has a `dispatch_status` of `OPEN`,
        `DISPATCHED` or `ON_SITE`. The `billing_status` is untouched by dispatch."
        PRD §3.6: "A new call starts with `dispatch_status` of `OPEN` and
        `billing_status` of `UNBILLED`."

        Design: Corner/state_machines/dispatch_side_effects_move_technician_and_vehicle
        """
        program = fixtures.setup_fleet_program()
        vehicle = fixtures.create_vehicle(
            program["fleet"]["id"], vehicle_type="TRAILER", current_odometer_miles=3000
        )
        technician = fixtures.create_technician(
            program["location"]["id"], certification_level="LEVEL_1"
        )
        call = fixtures.open_call(
            program["fleet"]["id"],
            vehicle["id"],
            program["location"]["id"],
            "2026-08-13T12:00:00Z",
        )
        assert call["dispatch_status"] == "OPEN"
        assert call["billing_status"] == "UNBILLED"

        dispatched = validate_success(
            api.dispatch_road_service_call(
                call["id"],
                factories.dispatch_payload(
                    "2026-08-13T12:20:00Z", 7, technician_id=technician["id"]
                ),
                fixtures.DISPATCHER,
            )
        )

        assert dispatched["dispatch_status"] == "DISPATCHED"
        assert dispatched["technician_id"] == technician["id"]
        assert dispatched["dispatched_at"] == "2026-08-13T12:20:00Z"
        assert dispatched["dispatch_miles"] == 7
        assert dispatched["billing_status"] == "UNBILLED", (
            "the billing dimension is untouched by dispatch"
        )
        assert dispatched.get("committed_response_minutes") is None
        assert dispatched.get("actual_response_minutes") is None
        assert dispatched.get("gross_cents") is None, (
            "pricing happens at arrival and completion, not at dispatch"
        )

        moved = fixtures.read_technician(technician["id"])
        assert moved["status"] == "ON_CALL"
        assert moved["completed_call_count"] == 0
        assert fixtures.read_vehicle(vehicle["id"])["status"] == "OUT_OF_SERVICE"
