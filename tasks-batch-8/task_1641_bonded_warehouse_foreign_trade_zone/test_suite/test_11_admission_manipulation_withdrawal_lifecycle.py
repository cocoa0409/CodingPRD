"""Corner coverage: admission initial/terminal states, manipulation reservation
release and output-lot valuation, withdrawal terminal lockdown, and entry
cycle/terminal states."""
from test_helpers import (
    ApiErrorId,
    api_client,
    approve_manipulation_order,
    complete_manipulation_order,
    create_admission,
    create_badge,
    create_filed_withdrawal,
    create_manipulation_order,
    create_zone,
    get_lot,
    get_success_data,
    make_customs_officer_headers,
    make_importer_headers,
    make_zone_operator_headers,
    setup_entry_with_filed_withdrawal,
    setup_zone_with_lot,
    submit_admission,
    admit_admission,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestAdmissionInitialAndTerminalStates:
    def test_admission_initial_state_draft(self):
        """PRD §3.2: "The importer creates it as a `DRAFT` by supplying the
        receiving `zone_id`, a merchandise `description`, the `hts_code` under
        which the goods are classified, the `quantity` of units (at least 1), the
        declared `unit_value_cents` per unit (at least 0), and the `zone_status`
        designation"
        PRD §3.2: "Admitting stamps `admission_date` from the logical clock (the
        field is null beforehand)"

        Design: Corner/state_machines/c_admission_initial_state_draft
        """
        zone = create_zone(bond_coverage_cents=10_000_000_000, name="Init Zone", zone_code="Z-INI")
        a = create_admission(zone["id"], importer_id="imp-1", description="Dairy",
                             hts_code="0401.10", quantity=5, unit_value_cents=1000,
                             zone_status="NON_PRIVILEGED_FOREIGN")
        assert a["status"] == "DRAFT", f"new admission must be DRAFT, got {a['status']}"
        assert a["version"] == 1
        assert a.get("admission_date") is None, "admission_date must be null before admission"

    def test_admit_after_cancel_returns_invalid_transition(self):
        """PRD §3.2: "An importer may also cancel an admission outright, from
        either `DRAFT` or `SUBMITTED`, moving it to the terminal `CANCELLED` state.
        ... acting from any other status yields `ERR_ADMISSION_INVALID_TRANSITION`."

        Design: Corner/state_machines/c_admit_after_cancel_returns_invalid_transition
        """
        zone = create_zone(bond_coverage_cents=10_000_000_000, name="Term Zone", zone_code="Z-TRM")
        imp = make_importer_headers("imp-1")
        a = create_admission(zone["id"], importer_id="imp-1", description="Dairy",
                             hts_code="0401.10", quantity=5, unit_value_cents=1000,
                             zone_status="NON_PRIVILEGED_FOREIGN")
        validate_success(api_client.cancel_admission(a["id"], imp))

        customs = make_customs_officer_headers()
        resp = api_client.admit_admission(a["id"], customs)
        validate_error(resp, ApiErrorId.ERR_ADMISSION_INVALID_TRANSITION, expected_status=409)

        op = make_zone_operator_headers()
        a_after = get_success_data(api_client.get_admission(a["id"], op))
        assert a_after["status"] == "CANCELLED"
        _lots, meta = validate_paginated(api_client.list_lots(op, params={"admission_id": a["id"]}))
        assert meta["total_count"] == 0, f"no lot may be created, got {meta['total_count']}"


class TestManipulationOrderLifecycle:
    def _setup_approved_order(self, input_quantity=40, lot_quantity=100):
        zone, _a, lot = setup_zone_with_lot(
            quantity=lot_quantity, unit_value_cents=10000, hts_code="8542.31",
            zone_status="NON_PRIVILEGED_FOREIGN", bond_coverage_cents=10_000_000_000,
            importer_id="imp-1", zone_name="Reserve Zone", zone_code="Z-RSV",
        )
        m = create_manipulation_order(
            zone["id"], lot["id"], input_quantity=input_quantity,
            output_hts_code="9503.00", output_quantity=20, value_added_cents=50000,
            output_description="Kitting", importer_id="imp-1",
        )
        approve_manipulation_order(m["id"])
        return zone, lot, m

    def test_approved_cancel_releases_reservation(self):
        """PRD §3.4: "cancelling an order that was `APPROVED` releases the
        reservation by decreasing the source lot's `reserved_quantity` by the
        `input_quantity`, leaving `quantity_on_hand` untouched."

        Design: Corner/state_machines/c_manipulation_cancel_releases_reservation
        """
        _zone, lot, m = self._setup_approved_order(input_quantity=40, lot_quantity=100)
        # Approval reserved 40 units.
        mid = get_lot(lot["id"])
        assert mid["reserved_quantity"] == 40
        assert mid["quantity_on_hand"] == 100

        imp = make_importer_headers("imp-1")
        cancelled = validate_success(api_client.cancel_manipulation_order(m["id"], imp))
        assert cancelled["status"] == "CANCELLED"

        end = get_lot(lot["id"])
        assert end["reserved_quantity"] == 0, (
            f"reservation released: expected 0, got {end['reserved_quantity']}"
        )
        assert end["quantity_on_hand"] == 100, (
            f"quantity_on_hand untouched: expected 100, got {end['quantity_on_hand']}"
        )
        assert end["status"] == "IN_ZONE"

    def test_complete_creates_output_lot_with_pinned_valuation(self):
        """PRD §3.4: "The input share is computed first: the order's
        `input_quantity` multiplied by the source lot's `unit_value_cents`, rounded
        half up to integer cents. The output basis is that rounded input share plus
        the order's `value_added_cents`. The output lot's `unit_value_cents` is the
        output basis divided by `output_quantity`, rounded half up to integer
        cents."
        PRD §3.4: "the output lot is created in `IN_ZONE` with `admitted_quantity`
        and `quantity_on_hand` both equal to the order's `output_quantity`, its
        `zone_status` inherited from the source lot, its `source_manipulation_id`
        set to this order, its `admission_id` null"

        Design: Corner/state_machines/c_manipulation_complete_creates_output_lot
        """
        zone, _a, lot = setup_zone_with_lot(
            quantity=100, unit_value_cents=10000, hts_code="8542.31",
            zone_status="NON_PRIVILEGED_FOREIGN", bond_coverage_cents=10_000_000_000,
            importer_id="imp-1", zone_name="Output Zone", zone_code="Z-OUT",
        )
        m = create_manipulation_order(
            zone["id"], lot["id"], input_quantity=100, output_hts_code="9503.00",
            output_quantity=50, value_added_cents=200000,
            output_description="Assembled toys", importer_id="imp-1",
        )
        approve_manipulation_order(m["id"])
        completed = complete_manipulation_order(m["id"], importer_id="imp-1")
        assert completed["status"] == "COMPLETED"

        op = make_zone_operator_headers()
        outs = get_success_data(
            api_client.list_lots(op, params={"source_manipulation_id": m["id"]}))
        assert len(outs) == 1
        ol = outs[0]
        # unit value: round((round(100 x 10000) + 200000) / 50) = 24000
        assert ol["unit_value_cents"] == 24000, (
            f"pinned valuation 24000, got {ol['unit_value_cents']}"
        )
        assert ol["hts_code"] == "9503.00"
        assert ol["zone_status"] == "NON_PRIVILEGED_FOREIGN"
        assert ol["admitted_quantity"] == 50
        assert ol.get("admission_id") is None
        assert completed["output_lot_id"] == ol["id"]

        src = get_lot(lot["id"])
        assert src["status"] == "DEPLETED", f"source fully consumed -> DEPLETED, got {src['status']}"
        assert src["cumulative_consumed"] == 100


class TestWithdrawalTerminalLockdown:
    def test_cancel_after_duty_paid_rejected(self):
        """PRD §3.5: "Once paid or exported, the withdrawal is terminal."
        PRD §3.5: "Any action on a withdrawal outside its valid states — including
        acting on a terminal withdrawal — yields
        `ERR_WITHDRAWAL_INVALID_TRANSITION`."

        Design: Corner/state_machines/c_withdrawal_terminal_lockdown
        """
        zone, _a, lot = setup_zone_with_lot(
            quantity=5, unit_value_cents=1000, hts_code="0401.10",
            zone_status="NON_PRIVILEGED_FOREIGN", bond_coverage_cents=10_000_000_000,
            importer_id="imp-1", zone_name="Lock Zone", zone_code="Z-LCK",
        )
        imp = make_importer_headers("imp-1")
        w = create_filed_withdrawal(zone["id"], lot["id"], quantity=2,
                                    withdrawal_type="CONSUMPTION", importer_id="imp-1")
        validate_success(api_client.pay_duty_withdrawal(w["id"], imp))

        resp = api_client.cancel_withdrawal(w["id"], imp)
        validate_error(resp, ApiErrorId.ERR_WITHDRAWAL_INVALID_TRANSITION, expected_status=409)

        w_after = get_success_data(api_client.get_withdrawal(w["id"], make_zone_operator_headers()))
        assert w_after["status"] == "DUTY_PAID"
        lot_after = get_lot(lot["id"])
        assert lot_after["quantity_on_hand"] == 3, (
            f"nothing restored after terminal lockdown: expected 3, got {lot_after['quantity_on_hand']}"
        )


class TestEntryCycleAndTerminalStates:
    def test_filed_entry_returned_to_open_then_accepted_terminal(self):
        """PRD §3.6: "Customs adjudicates a `FILED` entry through a transition
        action carrying `to_status`: `ACCEPTED` accepts the entry and is terminal,
        while `OPEN` returns it for correction, and the open–filed loop may repeat.
        Any other combination yields `ERR_ENTRY_INVALID_TRANSITION`."

        Design: Corner/state_machines/c_entry_filed_returned_to_open
        """
        zone, lot, entry, _w = setup_entry_with_filed_withdrawal(
            quantity=1, unit_value_cents=1221, hts_code="8708.29", lot_quantity=10,
            week_start_date="2026-07-27T00:00:00Z", importer_id="imp-1",
        )
        imp = make_importer_headers("imp-1")
        customs = make_customs_officer_headers()

        filed = validate_success(api_client.file_weekly_entry(entry["id"], imp))
        assert filed["status"] == "FILED"

        returned = validate_success(
            api_client.transition_weekly_entry(entry["id"], {"to_status": "OPEN"}, customs))
        assert returned["status"] == "OPEN", "FILED -> OPEN return must succeed"

        refiled = validate_success(api_client.file_weekly_entry(entry["id"], imp))
        assert refiled["status"] == "FILED", "re-file after return must succeed"

        accepted = validate_success(
            api_client.transition_weekly_entry(entry["id"], {"to_status": "ACCEPTED"}, customs))
        assert accepted["status"] == "ACCEPTED"

        resp = api_client.transition_weekly_entry(entry["id"], {"to_status": "OPEN"}, customs)
        validate_error(resp, ApiErrorId.ERR_ENTRY_INVALID_TRANSITION, expected_status=409)


class TestBadgeSuspendReinstateCycle:
    def test_cycle_then_revoked_terminal(self):
        """PRD §3.8: "An `ACTIVE` badge may be suspended to `SUSPENDED`, a
        `SUSPENDED` badge reinstated to `ACTIVE`, and a badge in either `ACTIVE` or
        `SUSPENDED` may be revoked to the terminal `REVOKED` state. ... a
        `to_status` unreachable from the badge's current status yields
        `ERR_BADGE_INVALID_TRANSITION`."

        Design: Corner/state_machines/c_badge_suspend_reinstate_cycle
        """
        zone = create_zone(bond_coverage_cents=10_000_000_000, name="Cycle Badge Zone",
                           zone_code="Z-CB")
        b = create_badge(zone["id"], holder_name="Grace Hopper",
                         valid_from="2026-08-01T00:00:00Z", valid_until="2026-12-31T00:00:00Z")
        op = make_zone_operator_headers()

        s1 = validate_success(api_client.transition_access_badge(b["id"], {"to_status": "SUSPENDED"}, op))
        assert s1["status"] == "SUSPENDED"
        s2 = validate_success(api_client.transition_access_badge(b["id"], {"to_status": "ACTIVE"}, op))
        assert s2["status"] == "ACTIVE", "suspend/reinstate loop is legal"
        s3 = validate_success(api_client.transition_access_badge(b["id"], {"to_status": "REVOKED"}, op))
        assert s3["status"] == "REVOKED"

        resp = api_client.transition_access_badge(b["id"], {"to_status": "ACTIVE"}, op)
        validate_error(resp, ApiErrorId.ERR_BADGE_INVALID_TRANSITION, expected_status=409)
