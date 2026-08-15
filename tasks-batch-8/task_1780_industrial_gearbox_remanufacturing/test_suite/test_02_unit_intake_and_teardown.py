"""Order intake gates, teardown findings log, and unit lifecycle guards."""
from test_helpers import (
    ApiErrorId,
    assert_reman_order,
    assert_teardown_finding,
    create_decision_payload,
    create_finding_payload,
    create_order_payload,
    get_unit,
    make_customer,
    make_order,
    make_unit,
    setup_order_in_teardown,
    setup_unit_with_order,
    validate_error,
    validate_success,
)


class TestUnitAtShopGate:
    def test_order_creation_rejected_when_unit_not_at_shop(
            self, api, intake_coordinator_headers):
        """PRD §3.2: "Intake requires three things: the unit's
        `physical_status` must be `AT_SHOP` (`ERR_UNIT_NOT_AT_SHOP`)".

        Design: Difficulty/cross_entity_state_dependency/teardown_requires_unit_at_shop
        """
        customer = make_customer(legal_name="Gate Co")
        unit = make_unit(customer["id"], serial_number="GBX-G1",
                         check_in=False)
        assert unit["physical_status"] == "IN_SERVICE"

        resp = api.create_order(
            unit["id"],
            create_order_payload(intake_hours=0, quoted_estimate_cents=100_000,
                                 rush=False),
            intake_coordinator_headers)
        validate_error(resp, ApiErrorId.ERR_UNIT_NOT_AT_SHOP.value)
        assert get_unit(unit["id"])["physical_status"] == "IN_SERVICE"

    def test_order_creation_accepted_when_unit_at_shop(
            self, api, reman_engineer_headers):
        """PRD §3.1: "When a unit arrives at the shop, the coordinator checks
        it in, moving `physical_status` from `IN_SERVICE` to `AT_SHOP`".
        PRD §3.2: "The order is born in `INTAKE` with `approved_scope_cents`
        at 0 and both completion snapshots (`completed_at_hours`,
        `completed_at_utc`) unset".

        Design: Difficulty/cross_entity_state_dependency/teardown_requires_unit_at_shop
        """
        ctx = setup_unit_with_order(serial_number="GBX-G2",
                                    quoted_estimate_cents=100_000)
        order = ctx["order"]
        assert_reman_order(order)
        assert order["status"] == "INTAKE"
        assert order["approved_scope_cents"] == 0
        assert order.get("completed_at_hours") is None
        assert order.get("completed_at_utc") is None
        assert order["gear_unit_id"] == ctx["unit"]["id"]

        # The same AT_SHOP gate passes at teardown start.
        data = validate_success(
            api.start_teardown(order["id"], reman_engineer_headers))
        assert data["status"] == "TEARDOWN"


class TestOneOpenOrderPerUnit:
    def test_second_open_order_rejected(self, api, intake_coordinator_headers):
        """PRD §3.2: "the unit must have no other order in a non-terminal
        state — at most one open order per unit, enforced here and again at
        teardown start (`ERR_UNIT_BUSY`)".

        Design: Corner/state_machines/second_order_on_same_unit_rejected
        """
        customer = make_customer(legal_name="Busy Co")
        unit = make_unit(customer["id"], serial_number="GBX-BUSY")
        make_order(unit["id"], intake_hours=0, quoted_estimate_cents=100_000)

        resp = api.create_order(
            unit["id"],
            create_order_payload(intake_hours=0, quoted_estimate_cents=200_000),
            intake_coordinator_headers)
        validate_error(resp, ApiErrorId.ERR_UNIT_BUSY.value)

    def test_scrap_blocked_by_open_order(self, api, service_manager_headers):
        """PRD §3.1: "A `ServiceManager` may scrap a unit that is physically
        `AT_SHOP`, moving it to the terminal `SCRAPPED` state, but only while
        no order for that unit sits in a non-terminal state (`ERR_UNIT_BUSY`);
        scrapping also resets the unit's `commercial_status` to `STANDARD`."

        Design: Corner/state_machines/scrap_blocked_by_active_order
        """
        customer = make_customer(legal_name="Scrap Co")
        unit = make_unit(customer["id"], serial_number="GBX-SCR")
        make_order(unit["id"], intake_hours=0, quoted_estimate_cents=100_000)

        resp = api.scrap_unit(unit["id"], service_manager_headers)
        validate_error(resp, ApiErrorId.ERR_UNIT_BUSY.value)
        assert get_unit(unit["id"])["physical_status"] == "AT_SHOP"


class TestIntakeHours:
    def test_intake_hours_must_match_odometer(self, api, intake_coordinator_headers):
        """PRD §3.2: "the reported `intake_hours` must equal the unit's
        current `cumulative_service_hours` exactly, so the order's baseline
        odometer can never drift from the registry
        (`ERR_INTAKE_HOURS_MISMATCH`)".

        Design: Corner/state_machines/intake_hours_must_match_unit_odometer
        """
        customer = make_customer(legal_name="Mismatch Co")
        unit = make_unit(customer["id"], serial_number="GBX-MM", hours=700)

        resp = api.create_order(
            unit["id"],
            create_order_payload(intake_hours=650,
                                 quoted_estimate_cents=100_000),
            intake_coordinator_headers)
        validate_error(resp, ApiErrorId.ERR_INTAKE_HOURS_MISMATCH.value)


class TestFindingsLog:
    def test_finding_is_append_only_without_version(
            self, api, reman_engineer_headers):
        """PRD §2.4: "The `TeardownFinding` log is the deliberate exception:
        findings are append-only, so a finding carries only `id` and
        `created_at`; both `updated_at` and `version` are absent on it."
        PRD §3.2: "The log is append-only — findings are never edited or
        deleted, and per §2.4 they carry no `updated_at` or `version`."

        Design: Corner/entities/teardown_finding_immutable_append_only
        """
        ctx = setup_unit_with_order(serial_number="GBX-LOG")
        api.start_teardown(ctx["order"]["id"], reman_engineer_headers)

        resp = api.create_finding(
            ctx["order"]["id"],
            create_finding_payload(component_code="BRG_3", condition="REUSABLE",
                                   severity=1, notes="ok"),
            reman_engineer_headers)
        data = validate_success(resp, expected_status=201)
        assert_teardown_finding(data)

    def test_submit_scope_no_findings(self, api, reman_engineer_headers):
        """PRD §3.3: "at least one teardown finding must exist for the order
        (`ERR_NO_FINDINGS`)".

        Design: Corner/state_machines/submit_scope_without_findings_rejected
        """
        ctx = setup_order_in_teardown(serial_number="GBX-NF")
        resp = api.submit_scope(ctx["order"]["id"], reman_engineer_headers)
        validate_error(resp, ApiErrorId.ERR_NO_FINDINGS.value)

    def test_submit_scope_undecided_finding(self, api, reman_engineer_headers):
        """PRD §3.3: "every logged finding's `component_code` must be covered
        by a `PENDING` decision (`ERR_DECISIONS_INCOMPLETE`)".

        Design: Corner/state_machines/submit_scope_with_undecided_finding_rejected
        """
        ctx = setup_unit_with_order(serial_number="GBX-UD")
        api.start_teardown(ctx["order"]["id"], reman_engineer_headers)
        api.create_finding(
            ctx["order"]["id"],
            create_finding_payload(component_code="GEAR_9",
                                   condition="BEYOND_REPAIR", severity=5,
                                   notes="cracked"),
            reman_engineer_headers)

        resp = api.submit_scope(ctx["order"]["id"], reman_engineer_headers)
        validate_error(resp, ApiErrorId.ERR_DECISIONS_INCOMPLETE.value)

    def test_decision_invalid_action_rejected(self, api, reman_engineer_headers):
        """PRD §3.2: "an `action` of `REGRIND`, `CUT_NEW`, `REPLACE_OEM`, or
        `REUSE_AS_IS`".
        PRD §2.4: "Across all resources, a request body missing a required
        field or carrying a malformed value is rejected with
        `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/validations/invalid_enum_value_rejected
        """
        ctx = setup_order_in_teardown(serial_number="GBX-EN")
        resp = api.create_decision(
            ctx["order"]["id"],
            create_decision_payload(component_code="PINION_1",
                                    action="WELD_IT", labor_hours=1.0,
                                    material_cents=100),
            reman_engineer_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)
