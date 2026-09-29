"""The two version guards, the version counter, a line correction and an immediate cascade."""

from test_helpers import (
    CONTRACT_SENDER_USER_ID,
    CONTRACT_SIGNER_USER_ID,
    CONTROLLER_APPROVER_USER_ID,
    TEST_USERS,
    ApiErrorId,
    add_element,
    advance_to_in_execution,
    approve_line,
    create_program,
    create_program_element_payload,
    create_settlement_payment_payload,
    create_supplier,
    create_transport_segment,
    create_venue,
    deliver,
    draft_contract,
    issue_invoice,
    make_controller_headers,
    make_supplier_manager_headers,
    manifest_guest,
    mark_ready,
    open_reconciliation,
    patch_line,
    read_program,
    reset_clock,
    setup_delivered_single_element_program,
    validate_error,
    validate_paginated,
    validate_success,
)

PD = TEST_USERS["program_director_headers"]
OC = TEST_USERS["operations_coordinator_headers"]
SM = TEST_USERS["supplier_manager_headers"]
CTRL = make_controller_headers(CONTROLLER_APPROVER_USER_ID)

SENDER = make_supplier_manager_headers(CONTRACT_SENDER_USER_ID)
SIGNER = make_supplier_manager_headers(CONTRACT_SIGNER_USER_ID)


class TestElementCreateGuardsTheProgrammeVersion:
    FIRST = {
        "element_type": "ACTIVITY",
        "title": "OCC E1",
        "starts_at": "2026-09-11T09:00:00Z",
        "ends_at": "2026-09-11T11:00:00Z",
        "planned_headcount": 20,
        "guaranteed_headcount": 20,
        "per_person_cost_cents": 4_000,
    }
    SECOND = {
        "element_type": "ACTIVITY",
        "title": "OCC E2",
        # 12:30Z clears the incumbent's 11:00Z end plus the venue's 90-minute buffer.
        "starts_at": "2026-09-11T12:30:00Z",
        "ends_at": "2026-09-11T14:30:00Z",
        "planned_headcount": 20,
        "guaranteed_headcount": 20,
        "per_person_cost_cents": 4_000,
    }

    def test_the_version_captured_at_intake_goes_stale_with_the_first_element(self, api):
        """PRD §2.5: "Creating a program element requires a non-optional
        `expected_program_version` field carrying the client's last observed `version` of the
        parent programme named by `program_id`. If that value does not equal the programme's
        current `version`, the create is rejected with `ERR_STALE_PROGRAM_VERSION` (HTTP 412)."

        Design: Corner/complexity_layers/element_create_with_stale_program_version_returns_412
        """
        reset_clock()
        venue = create_venue(
            name="OCC Venue",
            capacity_seated=100,
            capacity_reception=200,
            turnover_buffer_minutes=90,
        )
        supplier = create_supplier(legal_name="OCC Supplier")
        program = create_program(
            client_name="OCC Client", group_name="OCC Group", guaranteed_count=40
        )
        version_at_intake = program["version"]
        validate_success(
            api.create_program_element(
                create_program_element_payload(
                    program["id"],
                    supplier["id"],
                    version_at_intake,
                    venue_id=venue["id"],
                    **self.FIRST,
                ),
                PD,
            ),
            201,
        )

        stale = api.create_program_element(
            create_program_element_payload(
                program["id"],
                supplier["id"],
                version_at_intake,
                venue_id=venue["id"],
                **self.SECOND,
            ),
            PD,
        )

        validate_error(stale, ApiErrorId.ERR_STALE_PROGRAM_VERSION.value, 412)
        after_refusal = read_program(program["id"])
        assert after_refusal["element_count"] == 1
        # The refused write left the counter exactly where the accepted one put it.
        assert after_refusal["version"] == version_at_intake + 1

        retried = api.create_program_element(
            create_program_element_payload(
                program["id"],
                supplier["id"],
                after_refusal["version"],
                venue_id=venue["id"],
                **self.SECOND,
            ),
            PD,
        )

        validate_success(retried, 201)
        final = read_program(program["id"])
        assert final["element_count"] == 2
        assert final["open_element_count"] == 2
        assert final["version"] == version_at_intake + 2


class TestSettlementCreateGuardsTheContractVersion:
    def _an_invoiced_programme_whose_contract_moved_after_the_send(self, api):
        """The version observed at send is one behind the countersigned contract."""
        reset_clock()
        venue = create_venue(
            name="Contract OCC Venue", capacity_seated=100, capacity_reception=200
        )
        supplier = create_supplier(legal_name="Contract OCC Supplier")
        program = create_program(
            client_name="Contract OCC Client",
            group_name="Contract OCC Group",
            guaranteed_count=40,
            markup_pct=0.20,
        )
        element = add_element(
            program["id"], supplier["id"], venue_id=venue["id"], title="Contract OCC Element"
        )
        contract = draft_contract(
            program["id"], supplier["id"], contract_value_cents=200_000, deposit_pct=0
        )
        sent = validate_success(api.send_supplier_contract(contract["id"], SENDER))
        validate_success(api.countersign_supplier_contract(contract["id"], SIGNER))
        advance_to_in_execution(program["id"])
        mark_ready(element["id"])
        deliver(element["id"], 40, clock="2026-09-11T13:30:00Z")
        line = open_reconciliation(program["id"])[0]
        approve_line(line["id"])
        issue_invoice(program["id"])
        return {
            "program": program,
            "supplier": supplier,
            "contract": contract,
            "version_at_send": sent["version"],
        }

    def test_the_version_observed_at_send_no_longer_opens_a_settlement(self, api):
        """PRD §2.5: "Creating a settlement payment requires a non-optional
        `expected_contract_version` field carrying the client's last observed `version` of the
        supplier contract named by `contract_id`. If that value does not equal the contract's
        current `version`, the create is rejected with `ERR_STALE_CONTRACT_VERSION` (HTTP 412)."

        Design: Corner/complexity_layers/settlement_create_with_stale_contract_version_returns_412
        """
        ctx = self._an_invoiced_programme_whose_contract_moved_after_the_send(api)

        stale = api.create_settlement_payment(
            create_settlement_payment_payload(
                ctx["program"]["id"],
                ctx["supplier"]["id"],
                ctx["contract"]["id"],
                ctx["version_at_send"],
            ),
            CTRL,
        )

        validate_error(stale, ApiErrorId.ERR_STALE_CONTRACT_VERSION.value, 412)
        current = validate_success(api.get_supplier_contract(ctx["contract"]["id"], SM))
        # The countersignature is the write that moved the contract on.
        assert current["version"] == ctx["version_at_send"] + 1

        retried = api.create_settlement_payment(
            create_settlement_payment_payload(
                ctx["program"]["id"],
                ctx["supplier"]["id"],
                ctx["contract"]["id"],
                current["version"],
            ),
            CTRL,
        )

        payment = validate_success(retried, 201)
        assert payment["gross_cents"] == 200_000
        assert payment["deposit_applied_cents"] == 0
        assert payment["net_payable_cents"] == 200_000
        _, meta = validate_paginated(
            api.list_settlement_payments(
                CTRL,
                params={"program_id": ctx["program"]["id"], "limit": 10, "offset": 0},
            )
        )
        assert meta["total_count"] == 1


class TestDerivedProgrammeMoneyIsRecomputedNotAccumulated:
    def _a_draft_line_billed_at_the_attrition_floor(self):
        """Thirty guests turned up against forty guaranteed, so 34 are billed."""
        ctx = setup_delivered_single_element_program(
            actual_headcount=30,
            program_overrides={
                "client_name": "Derived Client",
                "group_name": "Derived Group",
                "guaranteed_count": 40,
                "markup_pct": 0.20,
            },
            element_overrides={"title": "Derived Element"},
            venue_overrides={"name": "Derived Venue"},
            supplier_overrides={"legal_name": "Derived Supplier"},
            contract_overrides={"contract_value_cents": 200_000, "deposit_pct": 0},
        )
        ctx["line"] = open_reconciliation(ctx["program"]["id"])[0]
        return ctx

    def test_a_corrected_head_count_rewrites_every_figure_on_the_line(self, api):
        """PRD §3.8: "When `actual_headcount` is supplied, the final head-count rule and the
        line-amount rule are re-run from scratch, rewriting `billed_headcount`,
        `supplier_cost_cents`, `markup_cents`, `client_charge_cents` and `variance_pct`."

        Design: Corner/complexity_layers/derived_program_money_reconciles_after_a_line_correction
        """
        ctx = self._a_draft_line_billed_at_the_attrition_floor()

        before = validate_success(api.get_reconciliation_line(ctx["line"]["id"], PD))
        after = patch_line(ctx["line"]["id"], actual_headcount=42)

        assert before["billed_headcount"] == 34
        assert before["supplier_cost_cents"] == 170_000
        assert before["markup_cents"] == 34_000
        assert before["client_charge_cents"] == 204_000
        # The corrected turnout of 42 now outranks the floor of 34 on its own.
        assert after["billed_headcount"] == 42
        assert after["supplier_cost_cents"] == 210_000
        assert after["markup_cents"] == 42_000
        assert after["client_charge_cents"] == 252_000
        assert after["variance_pct"] == 0.05

    def test_approval_and_invoice_publish_the_corrected_totals(self, api):
        """PRD §3.8: "Approval recomputes four programme figures — `final_subtotal_cents` as
        the sum of `supplier_cost_cents` over the programme's `APPROVED` lines,
        `disclosed_markup_cents` as the sum of `markup_cents` over the same set,
        `supplier_gross_payable_cents` (which equals `final_subtotal_cents`, being the gross
        owed across all suppliers), and `supplier_open_payable_cents` as
        `supplier_gross_payable_cents` less `supplier_settled_cents` — and increments the line's
        `version`."

        Design: Corner/complexity_layers/derived_program_money_reconciles_after_a_line_correction
        """
        ctx = self._a_draft_line_billed_at_the_attrition_floor()
        patch_line(ctx["line"]["id"], actual_headcount=42)

        approved = approve_line(ctx["line"]["id"])
        after_approval = read_program(ctx["program"]["id"])
        invoiced = issue_invoice(ctx["program"]["id"])

        assert approved["status"] == "APPROVED"
        assert after_approval["final_subtotal_cents"] == 210_000
        assert after_approval["disclosed_markup_cents"] == 42_000
        assert after_approval["supplier_gross_payable_cents"] == 210_000
        assert after_approval["supplier_open_payable_cents"] == 210_000
        # A 252,000-cent base sits below the 500,000-cent ceiling, so the fee is 12 per cent.
        assert invoiced["management_fee_cents"] == 30_240
        assert invoiced["final_client_total_cents"] == 282_240


class TestProgrammeVersionAdvancesOncePerWrite:
    ELEMENT = {
        "element_type": "ACTIVITY",
        "title": "Version Element",
        "starts_at": "2026-09-11T09:00:00Z",
        "ends_at": "2026-09-11T11:00:00Z",
        "planned_headcount": 20,
        "guaranteed_headcount": 20,
        "per_person_cost_cents": 4_000,
    }

    def test_two_reads_leave_the_counter_alone_and_three_writes_advance_it(self, api):
        """PRD §3.1: "The lock recomputes `element_count` and `open_element_count` and
        increments the programme's `version`."

        Design: Corner/complexity_layers/program_version_increments_on_every_write
        """
        reset_clock()
        venue = create_venue(
            name="Version Venue", capacity_seated=100, capacity_reception=200
        )
        supplier = create_supplier(legal_name="Version Supplier")
        program = create_program(
            client_name="Version Client",
            group_name="Version Group",
            guaranteed_count=20,
        )

        assert program["version"] == 1
        assert read_program(program["id"])["version"] == 1

        validate_success(
            api.create_program_element(
                create_program_element_payload(
                    program["id"], supplier["id"], 1, venue_id=venue["id"], **self.ELEMENT
                ),
                PD,
            ),
            201,
        )
        assert read_program(program["id"])["version"] == 2

        locked = validate_success(api.lock_program_design(program["id"], PD))
        assert locked["version"] == 3
        assert locked["execution_status"] == "DESIGN_LOCKED"

        unlocked = validate_success(api.unlock_program_design(program["id"], PD))
        assert unlocked["version"] == 4
        assert unlocked["execution_status"] == "DRAFT"
        assert unlocked["element_count"] == 1


class TestSegmentCancellationIsVisibleInItsOwnResponse:
    SHUTTLE = {
        "segment_type": "DINE_AROUND_LEG",
        "vehicle_code": "IMM-01",
        "origin": "Host Hotel",
        "destination": "Old Town",
        "depart_at": "2026-09-11T18:00:00Z",
        "arrive_at": "2026-09-11T18:25:00Z",
        "seat_capacity": 12,
        "wheelchair_accessible": True,
    }

    def test_the_cancel_body_already_reports_the_released_seats(self, api):
        """PRD §3.5: "Every entry of the segment in `ASSIGNED` or `CHECKED_IN` moves to
        `RELEASED`; caused by each such release, the segment's `booked_seat_count` is
        decremented by that entry's `seat_count` and the programme's `unseated_guest_count` is
        incremented by one; and caused by that, the programme's `seated_guest_count` is
        recomputed as the sum of `booked_seat_count` across the programme's segments."

        Design: Corner/consistency_model/cascade_is_visible_in_the_triggering_response
        """
        reset_clock()
        program = create_program(
            client_name="Immediate Client",
            group_name="Immediate Group",
            guaranteed_count=20,
        )
        segment = create_transport_segment(program["id"], **self.SHUTTLE)
        first = manifest_guest(
            segment["id"], guest_ref="G-600", guest_name="Fen Adeyemi", seat_count=2
        )
        second = manifest_guest(
            segment["id"], guest_ref="G-700", guest_name="Gita Sharma", seat_count=2
        )
        assert (
            validate_success(api.get_transport_segment(segment["id"], OC))[
                "booked_seat_count"
            ]
            == 4
        )
        assert read_program(program["id"])["seated_guest_count"] == 4

        cancelled = validate_success(
            api.cancel_transport_segment(
                segment["id"], OC, {"cancel_reason": "Vehicle breakdown."}
            )
        )

        # No re-read: the triggering response already carries the cascaded occupancy.
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["booked_seat_count"] == 0
        entries, meta = validate_paginated(
            api.list_manifest_entries(
                OC, params={"segment_id": segment["id"], "limit": 10, "offset": 0}
            )
        )
        assert meta["total_count"] == 2
        assert {entry["id"]: entry["status"] for entry in entries} == {
            first["id"]: "RELEASED",
            second["id"]: "RELEASED",
        }
        program = read_program(program["id"])
        assert program["seated_guest_count"] == 0
        assert program["unseated_guest_count"] == 2
