"""The IN_WORK / READY_FOR_DELIVERY / DELIVERED gates (PRD §3.5)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    advance_program,
    assert_calendar_day,
    create_and_certify_lot,
    create_invoice,
    get_program,
    issue_invoice,
    make_customer_rep_headers,
    pass_inspection,
    pass_standard_inspections,
    prepare_weight_record,
    record_burn_test_payload,
    set_logical_clock,
    setup_in_inspection_program,
    setup_ready_for_delivery,
    setup_surface_review_program,
    sign_off_weight_record,
    validate_error,
    validate_success,
)
from test_helpers.factories import create_soft_good_lot_payload, record_burn_test_payload as _bt_payload

_PM = TEST_USERS["program_manager_headers"]
_TECH = TEST_USERS["shop_technician_headers"]
_FIN = TEST_USERS["finance_clerk_headers"]


class TestInWorkSchemeGate:
    def test_in_work_blocked_until_scheme_approved(self, api, program_manager_headers):
        """PRD §3.5: "From `SURFACE_REVIEW` to `IN_WORK`: four gates. ... a
        paint scheme must be `APPROVED` (`ERR_SCHEME_NOT_APPROVED`)".

        Design: Difficulty/cross_entity_state_dependency/in_work_requires_approved_scheme
        """
        from test_helpers import (
            book_booth_window,
            create_booth,
            create_scheme,
            submit_scheme,
        )
        ctx = setup_surface_review_program(approve_scheme=False)
        scheme = create_scheme(ctx["program"]["id"])
        submit_scheme(scheme["id"])  # SUBMITTED only — not APPROVED
        ctx["booth"] = create_booth()
        book_booth_window(ctx["booth"]["id"], ctx["program"]["id"])

        resp = api.advance_program(
            ctx["program"]["id"], {"to_phase": "IN_WORK"}, program_manager_headers
        )
        validate_error(resp, ApiErrorId.ERR_SCHEME_NOT_APPROVED)

    def test_in_work_succeeds_after_scheme_approval(self, api, program_manager_headers):
        """PRD §3.5: "From `SURFACE_REVIEW` to `IN_WORK`: four gates. The
        current assessment must be `DECIDED` (`ERR_ASSESSMENT_REQUIRED`); the
        heavy-corrosion rule of §3.4 must be satisfied
        (`ERR_CORROSION_DISCOVERY_REQUIRED`); a paint scheme must be `APPROVED`
        (`ERR_SCHEME_NOT_APPROVED`); at least one booth booking must be
        `BOOKED` (`ERR_BOOTH_BOOKING_REQUIRED`)".

        Design: Difficulty/cross_entity_state_dependency/in_work_requires_approved_scheme
        """
        from test_helpers import (
            approve_scheme,
            book_booth_window,
            create_booth,
            create_scheme,
            submit_scheme,
        )
        ctx = setup_surface_review_program(approve_scheme=False)
        scheme = create_scheme(ctx["program"]["id"])
        submit_scheme(scheme["id"])
        ctx["booth"] = create_booth()
        book_booth_window(ctx["booth"]["id"], ctx["program"]["id"])

        blocked = api.advance_program(
            ctx["program"]["id"], {"to_phase": "IN_WORK"}, program_manager_headers
        )
        validate_error(blocked, ApiErrorId.ERR_SCHEME_NOT_APPROVED)

        approve_scheme(
            scheme["id"], ctx["customer"]["id"],
            get_program(ctx["program"]["id"])["version"],
        )
        ok = api.advance_program(
            ctx["program"]["id"], {"to_phase": "IN_WORK"}, program_manager_headers
        )
        assert validate_success(ok)["status"] == "IN_WORK"


class TestReadyCertGate:
    def test_ready_blocked_while_lot_not_certified(self, api, program_manager_headers):
        """PRD §3.5: "Step two: every soft-goods lot of the program must be
        `CERTIFIED` — a lot in any other state, including `CERT_QUARANTINED`,
        blocks the gate (`ERR_CERT_REQUIRED`)."

        Design: Difficulty/cross_entity_state_dependency/ready_requires_all_lots_certified
        """
        ctx = setup_in_inspection_program()
        pass_standard_inspections(ctx)
        # One FAIL -> CERT_FAILED lot; weight gate satisfied separately.
        lot = validate_success(
            api.create_soft_good_lot(
                create_soft_good_lot_payload(program_id=ctx["program"]["id"]), _TECH
            ),
            201,
        )
        validate_success(
            api.record_burn_test(
                lot["id"], _bt_payload(result="FAIL"), _TECH
            ),
            201,
        )
        ctx["wbr"] = prepare_weight_record(ctx["program"]["id"], ctx["scheme"]["id"])
        sign_off_weight_record(ctx["wbr"]["id"])

        resp = api.advance_program(
            ctx["program"]["id"], {"to_phase": "READY_FOR_DELIVERY"},
            program_manager_headers,
        )
        validate_error(resp, ApiErrorId.ERR_CERT_REQUIRED)

    def test_ready_succeeds_after_lot_certified(self, api, program_manager_headers):
        """PRD §3.5: "Step two: every soft-goods lot of the program must be
        `CERTIFIED`" and PRD §3.8: "a lot carrying two recorded failures that
        then passes becomes `CERTIFIED`" (a `PASS` moves the lot to
        `CERTIFIED`).

        Design: Difficulty/cross_entity_state_dependency/ready_requires_all_lots_certified
        """
        ctx = setup_in_inspection_program()
        pass_standard_inspections(ctx)
        lot = validate_success(
            api.create_soft_good_lot(
                create_soft_good_lot_payload(program_id=ctx["program"]["id"]), _TECH
            ),
            201,
        )
        validate_success(api.record_burn_test(lot["id"], _bt_payload(result="FAIL"), _TECH), 201)
        ctx["wbr"] = prepare_weight_record(ctx["program"]["id"], ctx["scheme"]["id"])
        sign_off_weight_record(ctx["wbr"]["id"])

        blocked = api.advance_program(
            ctx["program"]["id"], {"to_phase": "READY_FOR_DELIVERY"},
            program_manager_headers,
        )
        validate_error(blocked, ApiErrorId.ERR_CERT_REQUIRED)

        # Retest PASS certifies the lot; the gate now passes.
        validate_success(api.record_burn_test(lot["id"], _bt_payload(result="PASS"), _TECH), 201)
        lot_after = validate_success(api.get_soft_good_lot(lot["id"], _TECH))
        assert lot_after["status"] == "CERTIFIED"

        ok = api.advance_program(
            ctx["program"]["id"], {"to_phase": "READY_FOR_DELIVERY"},
            program_manager_headers,
        )
        assert validate_success(ok)["status"] == "READY_FOR_DELIVERY"


class TestReadyWeightGate:
    def test_ready_blocked_without_signed_weight_record(self, api, program_manager_headers):
        """PRD §3.5: "Step three: a weight-and-balance record with `variant` of
        `FINAL` and status `SIGNED_OFF` must exist whose absolute rounded
        `delta_lbs` is at most the aircraft's `max_delta_lbs`, or else an
        `APPROVED` change order of kind `WEIGHT_ACK` acknowledging that record
        must exist (`ERR_WEIGHT_NOT_SIGNED_OFF`)."

        Design: Corner/errors/ready_blocked_without_signed_weight_record
        """
        ctx = setup_in_inspection_program()
        pass_standard_inspections(ctx)
        create_and_certify_lot(ctx["program"]["id"])
        # FINAL record PREPARED but never signed off.
        prepare_weight_record(ctx["program"]["id"], ctx["scheme"]["id"])

        resp = api.advance_program(
            ctx["program"]["id"], {"to_phase": "READY_FOR_DELIVERY"},
            program_manager_headers,
        )
        validate_error(resp, ApiErrorId.ERR_WEIGHT_NOT_SIGNED_OFF)


class TestDeliveredGate:
    def test_delivered_blocked_until_final_invoice_paid(self, api, program_manager_headers):
        """PRD §3.5: "From `READY_FOR_DELIVERY` to `DELIVERED`: the fiscal
        gate — the program's `FINAL` invoice must exist in `PAID` status
        (`ERR_INVOICE_NOT_SETTLED`)."

        Design: Difficulty/cross_entity_state_dependency/delivered_requires_final_invoice_paid
        """
        ctx = setup_ready_for_delivery()
        invoice = create_invoice(ctx["program"]["id"], "FINAL")
        issue_invoice(invoice["id"])  # ISSUED — not PAID

        resp = api.advance_program(
            ctx["program"]["id"], {"to_phase": "DELIVERED"}, program_manager_headers
        )
        validate_error(resp, ApiErrorId.ERR_INVOICE_NOT_SETTLED)

    def test_delivery_cascades_aircraft_slots_and_stamps_date(self, api,
                                                              program_manager_headers):
        """PRD §3.5: "Delivery stamps `actual_delivery_date` from the logical
        clock, recomputes and persists `penalty_final_cents` via the settlement
        variant of the delivery penalty (§3.10), releases every `ACTIVE` hangar
        slot of the program, and returns the aircraft to `RETURNED`."

        Design: Difficulty/cross_entity_state_dependency/delivered_requires_final_invoice_paid
        """
        ctx = setup_ready_for_delivery()  # logical clock sits at 2026-08-01
        invoice = create_invoice(ctx["program"]["id"], "FINAL")
        issue_invoice(invoice["id"])
        validate_success(
            api.pay_invoice(
                invoice["id"], make_customer_rep_headers(ctx["customer"]["id"])
            )
        )

        delivered = validate_success(
            api.advance_program(
                ctx["program"]["id"], {"to_phase": "DELIVERED"}, program_manager_headers
            )
        )
        assert delivered["status"] == "DELIVERED"
        assert_calendar_day(
            delivered["actual_delivery_date"], "2026-08-01", "actual_delivery_date"
        )

        aircraft = validate_success(api.get_aircraft(ctx["aircraft"]["id"], _PM))
        assert aircraft["status"] == "RETURNED"
        slot = validate_success(api.get_hangar_slot(ctx["slot"]["id"], _PM))
        assert slot["status"] == "RELEASED"
