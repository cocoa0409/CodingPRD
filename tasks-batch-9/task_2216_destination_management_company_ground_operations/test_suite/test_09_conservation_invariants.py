"""Round trips that must leave the ledgers exactly where they started."""

from test_helpers import (
    TEST_USERS,
    assert_supplier_payable_conserved,
    create_transport_segment,
    manifest_guest,
    setup_pending_settlement,
    setup_program_with_segment,
    validate_success,
)

PD = TEST_USERS["program_director_headers"]
OC = TEST_USERS["operations_coordinator_headers"]
CTRL = TEST_USERS["controller_headers"]

VOID_REASON = "Supplier reissued the invoice with corrected banking details."


class TestManifestMoveConservesSeats:
    HALCYON = {
        "client_name": "Halcyon Foundation",
        "group_name": "Donor Dinner Series",
        "guaranteed_count": 30,
    }
    OSTERIA_LEG = {
        "segment_type": "DINE_AROUND_LEG",
        "vehicle_code": "VAN-21",
        "origin": "Host Hotel",
        "destination": "Osteria Blu",
        "depart_at": "2026-09-12T18:00:00Z",
        "arrive_at": "2026-09-12T18:40:00Z",
        "seat_capacity": 20,
        "wheelchair_accessible": True,
    }
    CASA_VERDE_LEG = {
        "segment_type": "DINE_AROUND_LEG",
        "vehicle_code": "VAN-22",
        "origin": "Host Hotel",
        "destination": "Casa Verde",
        "depart_at": "2026-09-12T18:15:00Z",
        "arrive_at": "2026-09-12T18:55:00Z",
        "seat_capacity": 20,
        "wheelchair_accessible": True,
    }

    def _party_of_three_on_the_first_leg(self):
        ctx = setup_program_with_segment(
            program_overrides=self.HALCYON, segment_overrides=self.OSTERIA_LEG
        )
        ctx["first_leg"] = ctx["segment"]
        ctx["second_leg"] = create_transport_segment(
            ctx["program"]["id"], **self.CASA_VERDE_LEG
        )
        ctx["entry"] = manifest_guest(
            ctx["first_leg"]["id"],
            guest_ref="G-501",
            guest_name="Party Aoyama",
            seat_count=3,
        )
        return ctx

    def _seat_counts(self, api, ctx):
        first = validate_success(api.get_transport_segment(ctx["first_leg"]["id"], OC))
        second = validate_success(api.get_transport_segment(ctx["second_leg"]["id"], OC))
        program = validate_success(api.get_program(ctx["program"]["id"], PD))
        return (
            first["booked_seat_count"],
            second["booked_seat_count"],
            program["seated_guest_count"],
        )

    def test_a_move_relocates_seats_without_creating_or_destroying_any(self, api):
        """PRD §3.5: "Crucially, the programme's `seated_guest_count` is recomputed and
        comes out **unchanged** — seats are conserved by a move, never created or destroyed."

        Design: Difficulty/compensating_invariant/manifest_move_and_move_back_conserves_program_seat_count
        """
        ctx = self._party_of_three_on_the_first_leg()
        assert self._seat_counts(api, ctx) == (3, 0, 3)

        validate_success(
            api.move_manifest_entry(
                ctx["entry"]["id"], {"target_segment_id": ctx["second_leg"]["id"]}, OC
            )
        )

        assert self._seat_counts(api, ctx) == (0, 3, 3)

    def test_moving_back_restores_both_vehicles_and_counts_the_trip(self, api):
        """PRD §3.5: "A successful move adds one to `move_count`, subtracts the entry's
        `seat_count` from the source segment's `booked_seat_count` and adds it to the
        target's, and increments the entry's `version`."

        Design: Difficulty/compensating_invariant/manifest_move_and_move_back_conserves_program_seat_count
        """
        ctx = self._party_of_three_on_the_first_leg()
        validate_success(
            api.move_manifest_entry(
                ctx["entry"]["id"], {"target_segment_id": ctx["second_leg"]["id"]}, OC
            )
        )

        entry = validate_success(
            api.move_manifest_entry(
                ctx["entry"]["id"], {"target_segment_id": ctx["first_leg"]["id"]}, OC
            )
        )

        assert self._seat_counts(api, ctx) == (3, 0, 3)
        assert entry["segment_id"] == ctx["first_leg"]["id"]
        assert entry["move_count"] == 2
        assert entry["status"] == "ASSIGNED"
        program = validate_success(api.get_program(ctx["program"]["id"], PD))
        assert program["unseated_guest_count"] == 0


class TestSettlementVoidRestoresThePayableSplit:
    SOLSTICE = {
        "client_name": "Solstice Retail",
        "group_name": "Store Manager Summit",
        "guaranteed_count": 50,
        "markup_pct": 0.20,
    }
    CHALLENGE = {
        "element_type": "ACTIVITY",
        "title": "Cliffside Team Challenge",
        "starts_at": "2026-09-13T10:00:00Z",
        "ends_at": "2026-09-13T14:00:00Z",
        "planned_headcount": 50,
        "guaranteed_headcount": 50,
        "per_person_cost_cents": 8_000,
    }

    def _pending_payment(self):
        return setup_pending_settlement(
            actual_headcount=50,
            deliver_clock="2026-09-13T14:30:00Z",
            program_overrides=self.SOLSTICE,
            element_overrides=self.CHALLENGE,
            venue_overrides={"name": "Cliffside Pavilion"},
            supplier_overrides={"legal_name": "Cliffside Experiences SA"},
            contract_overrides={"contract_value_cents": 400_000},
        )

    def test_the_pending_payment_nets_the_banked_deposit_off_the_gross(self, api):
        """PRD §3.9: "`deposit_applied_cents` is the contract's `deposit_paid_cents` less
        whatever deposit remains at the end of the walk; `net_payable_cents` is `gross_cents`
        less `deposit_applied_cents`, floored at zero so it is never negative; and
        `overpayment_credit_cents` is the deposit still stranded after the walk — the money
        the DMC advanced that this supplier's work never earned."

        Design: Difficulty/compensating_invariant/settlement_approve_then_void_restores_supplier_payable_split
        """
        ctx = self._pending_payment()
        payment = ctx["payment"]

        assert payment["status"] == "PENDING"
        assert payment["gross_cents"] == 400_000
        assert payment["deposit_applied_cents"] == 120_000
        assert payment["net_payable_cents"] == 280_000
        assert payment["overpayment_credit_cents"] == 0
        program = validate_success(api.get_program(ctx["program"]["id"], PD))
        assert program["supplier_gross_payable_cents"] == 400_000
        assert program["supplier_settled_cents"] == 0
        assert program["supplier_open_payable_cents"] == 400_000
        assert_supplier_payable_conserved(program)

    def test_approval_moves_the_net_between_the_two_buckets(self, api):
        """PRD §3.9: "On success `approved_by_user_id` is stamped with the acting
        `X-User-ID`, `supplier_settled_cents` rises by `net_payable_cents`,
        `supplier_open_payable_cents` falls by the same amount — the two always sum to
        `supplier_gross_payable_cents` — and the payment's `version` increments."

        Design: Difficulty/compensating_invariant/settlement_approve_then_void_restores_supplier_payable_split
        """
        ctx = self._pending_payment()

        approved = validate_success(
            api.approve_settlement_payment(ctx["payment"]["id"], CTRL)
        )

        assert approved["status"] == "APPROVED"
        program = validate_success(api.get_program(ctx["program"]["id"], PD))
        assert program["supplier_gross_payable_cents"] == 400_000
        assert program["supplier_settled_cents"] == 280_000
        assert program["supplier_open_payable_cents"] == 120_000
        assert_supplier_payable_conserved(program)

    def test_voiding_an_approved_payment_returns_the_buckets_to_where_they_were(self, api):
        """PRD §3.9: "When the prior status was `APPROVED`, the void subtracts
        `net_payable_cents` from the programme's `supplier_settled_cents` and adds it back to
        `supplier_open_payable_cents`, returning the two buckets to the sum they had before
        approval."

        Design: Difficulty/compensating_invariant/settlement_approve_then_void_restores_supplier_payable_split
        """
        ctx = self._pending_payment()
        validate_success(api.approve_settlement_payment(ctx["payment"]["id"], CTRL))

        voided = validate_success(
            api.void_settlement_payment(
                ctx["payment"]["id"], CTRL, {"void_reason": VOID_REASON}
            )
        )

        assert voided["status"] == "VOID"
        program = validate_success(api.get_program(ctx["program"]["id"], PD))
        assert program["supplier_gross_payable_cents"] == 400_000
        assert program["supplier_settled_cents"] == 0
        assert program["supplier_open_payable_cents"] == 400_000
        assert_supplier_payable_conserved(program)
        # Nothing was released, so the settlement dimension never bubbles up to SETTLED.
        assert program["settlement_status"] == "CLIENT_INVOICED"
        assert program["final_client_total_cents"] == 537_600
