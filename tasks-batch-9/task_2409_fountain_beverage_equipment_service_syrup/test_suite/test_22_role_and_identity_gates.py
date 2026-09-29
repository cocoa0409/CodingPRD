"""Role gates, outlet ownership, and the two identity separations.

One denial for each role's exclusive surface, the ownership rule in its refused and
its permitted form, both segregation-of-duties rules refused and then satisfied by a
second identity, and the dispatch-holder check on arrival and on resolution.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    activate_agreement,
    add_stop,
    ApiErrorId,
    arrive_call,
    create_agreement,
    create_call,
    create_outlet,
    create_position,
    create_route,
    create_route_payload,
    create_service_call_payload,
    create_supply_item,
    create_supply_item_payload,
    create_task,
    create_unit,
    create_van_stock,
    compliance_hold_payload,
    dispatch_call,
    dispatch_call_payload,
    evaluate_task,
    make_compliance_officer_headers,
    make_outlet_manager_headers,
    pin_clock,
    place_compliance_hold,
    read_agreement,
    read_call,
    read_outlet,
    read_position,
    read_stop,
    read_task,
    read_unit,
    read_van_stock,
    recall_decision_payload,
    resolve_call_payload,
    setup_shortfall_review,
    TEST_USERS,
    waive_task_payload,
)

ADMIN = TEST_USERS["admin_headers"]
PLANNER = TEST_USERS["planner_headers"]
DRIVER = TEST_USERS["driver_headers"]
TECH = TEST_USERS["technician_headers"]
TECH_ALT = TEST_USERS["technician_alt_headers"]
OFFICER = TEST_USERS["officer_headers"]
OFFICER_ALT = TEST_USERS["officer_alt_headers"]

CLOCK = "2026-08-01T00:00:00Z"


def _outlet(account_code="OUT-1001", name="Riverside Diner", region_code="R-WEST"):
    pin_clock(CLOCK)
    return create_outlet(name=name, account_code=account_code, region_code=region_code)


def _outlet_agreement_and_unit(activate=True):
    """Riverside Diner, an 8000-gallon agreement, and one IN_SERVICE machine."""
    outlet = _outlet()
    agreement = create_agreement(
        outlet["id"], annual_commitment_gallons=8000, equipment_value_cents=480000
    )
    unit = create_unit(
        outlet["id"], agreement["id"],
        serial_number="SN-9001", installed_at="2025-11-01T00:00:00Z",
    )
    if activate:
        activate_agreement(agreement["id"])
    return outlet, agreement, unit


def _cola_sku():
    return create_supply_item(
        sku_code="SKU-COLA", brand_name="Cola Classic", supply_form="BAG_IN_BOX",
        case_pack_units=4, ounces_per_unit=2000, national_allocation_units=100,
    )


def _outlet_with_a_position():
    outlet = _outlet()
    item = _cola_sku()
    return outlet, create_position(outlet["id"], item["id"], 2)


def _q3_assessment_by_the_admin():
    """An ACTIVE agreement assessed for Q3 by admin-001, leaving SHORTFALL_REVIEW."""
    return setup_shortfall_review(
        annual_commitment_gallons=8000,
        equipment_value_cents=480000,
        assess_clock=CLOCK,
        period_start_date="2026-07-01T00:00:00Z",
        period_end_date="2026-10-01T00:00:00Z",
        assessor_headers=ADMIN,
    )


def _overdue_sanitation_under_an_officers_hold():
    """A SANITATION task in OVERDUE at an outlet whose hold was placed by officer-001."""
    outlet, _agreement, unit = _outlet_agreement_and_unit()
    task = create_task(unit["id"], "SANITATION", "2026-07-01T00:00:00Z")
    evaluate_task(task["id"], OFFICER)
    place_compliance_hold(outlet["id"], OFFICER, hold_reason_code="SANITATION_LAPSE")
    return outlet, task


class TestExclusiveRoleSurfaces:
    def test_a_planner_may_not_register_a_consumable_sku(self, api):
        """PRD §2.1: "A `NetworkAdmin` is the bottler's operations administrator. It
        masters outlets, placement agreements, dispenser equipment, consumable SKUs and van
        loadouts, and it runs the volume-shortfall assessment." Per §2.6 rung 2: "The
        acting role appears in the target endpoint's role list, otherwise
        `ERR_UNAUTHORIZED` (403). Applies to every endpoint."

        Design: Corner/rbac/rbac_supply_planner_denied_registering_a_supply_item
        """
        pin_clock(CLOCK)

        validate_error(
            api.create_supply_item(
                create_supply_item_payload(
                    sku_code="SKU-COLA", brand_name="Cola Classic",
                    supply_form="BAG_IN_BOX", case_pack_units=4, ounces_per_unit=2000,
                    national_allocation_units=100,
                ),
                PLANNER,
            ),
            ApiErrorId.ERR_UNAUTHORIZED,
            403,
        )

    def test_a_driver_may_not_plan_the_route_it_would_drive(self, api):
        """PRD §2.1: "A `SupplyPlanner` is the demand planner. It opens stock positions,
        runs consumption forecasts, allocates the national pool and plans, dispatches,
        completes and cancels replenishment routes." The driver's own surface is narrower:
        "A `RouteDriver` executes a dispatched route stop by stop: arriving, serving and
        skipping."

        Design: Corner/rbac/rbac_route_driver_denied_planning_a_replenishment_route
        """
        pin_clock(CLOCK)

        validate_error(
            api.create_route(
                create_route_payload(
                    route_code="RT-01", depot_region_code="R-WEST",
                    service_date="2026-08-03T00:00:00Z", van_code="VAN-7",
                    capacity_units=60,
                ),
                DRIVER,
            ),
            ApiErrorId.ERR_UNAUTHORIZED,
            403,
        )

    def test_the_role_gate_answers_before_the_stop_state_is_examined(self, api):
        """PRD §2.1: "A `RouteDriver` executes a dispatched route stop by stop: arriving,
        serving and skipping." The ladder puts that check first, per §2.6: "Checks are
        evaluated in the following priority order, and the first failure terminates the
        request." Rung 2 is "**Authorization.** The acting role appears in the target
        endpoint's role list, otherwise `ERR_UNAUTHORIZED` (403). Applies to every
        endpoint."

        Design: Corner/rbac/rbac_network_admin_denied_arriving_at_a_route_stop
        """
        outlet = _outlet()
        route = create_route(
            route_code="RT-01", depot_region_code="R-WEST",
            service_date="2026-08-03T00:00:00Z", van_code="VAN-7", capacity_units=60,
        )
        stop = add_stop(
            route["id"], outlet["id"], 1,
            "2026-08-03T09:00:00Z", "2026-08-03T10:00:00Z",
        )

        validate_error(
            api.arrive_stop(stop["id"], ADMIN),
            ApiErrorId.ERR_UNAUTHORIZED,
            403,
        )

        pending = read_stop(stop["id"])
        assert pending["status"] == "PENDING"
        assert pending["version"] == 1

    def test_a_compliance_officer_may_not_dispatch_a_technician(self, api):
        """PRD §2.1: "A `ServiceTechnician` works service calls off a van and completes
        maintenance and calibration tasks; it also places and releases equipment service
        holds." The officer's own surface is elsewhere: "A `ComplianceOfficer` owns
        sanitation compliance holds, the preventive-maintenance schedule, due evaluation,
        waivers and the recall decision."

        Design: Corner/rbac/rbac_compliance_officer_denied_dispatching_a_service_call
        """
        _outlet, _agreement, unit = _outlet_agreement_and_unit()
        call = create_call(unit["id"], "LEAK", CLOCK)

        validate_error(
            api.dispatch_service_call(
                call["id"],
                dispatch_call_payload(
                    "VAN-7", "2026-08-02T09:00:00Z", "2026-08-02T11:00:00Z"
                ),
                OFFICER,
            ),
            ApiErrorId.ERR_UNAUTHORIZED,
            403,
        )

        undispatched = read_call(call["id"])
        assert undispatched["status"] == "OPEN"
        assert undispatched["van_code"] is None
        assert undispatched["version"] == 1

    def test_a_technician_may_not_put_a_whole_outlet_on_compliance_hold(self, api):
        """PRD §2.1: "A `ComplianceOfficer` owns sanitation compliance holds, the
        preventive-maintenance schedule, due evaluation, waivers and the recall decision."
        The outlet therefore keeps what §3.1 gave it: "A freshly registered outlet opens
        for business immediately: its `status` is `ACTIVE`, its derived `service_posture`
        is `OPEN`, both of its compliance counters — `open_compliance_hold_count` and
        `overdue_task_count` — stand at 0, its `last_hold_placed_by_user_id` is null, and
        its `version` is 1."

        Design: Corner/rbac/rbac_service_technician_denied_placing_a_compliance_hold
        """
        outlet = _outlet()

        validate_error(
            api.outlet_compliance_hold(
                outlet["id"],
                compliance_hold_payload("PLACE", hold_reason_code="SANITATION_LAPSE"),
                TECH,
            ),
            ApiErrorId.ERR_UNAUTHORIZED,
            403,
        )

        unheld = read_outlet(outlet["id"])
        assert unheld["open_compliance_hold_count"] == 0
        assert unheld["last_hold_placed_by_user_id"] is None
        assert unheld["service_posture"] == "OPEN"
        assert unheld["version"] == 1

    def test_the_planner_who_opened_the_position_may_not_acknowledge_its_alert(self, api):
        """PRD §3.6: "An `OutletManager` acknowledges the current low-supply alert on their
        own outlet's position, which records the acting `X-User-ID` in
        `alert_acknowledged_by_user_id` and increments the position's `version` by one."
        Per §2.6 rung 2: "The acting role appears in the target endpoint's role list,
        otherwise `ERR_UNAUTHORIZED` (403). Applies to every endpoint."

        Design: Corner/rbac/rbac_supply_planner_denied_acknowledging_a_position_alert
        """
        _outlet, position = _outlet_with_a_position()

        validate_error(
            api.acknowledge_alert(position["id"], PLANNER),
            ApiErrorId.ERR_UNAUTHORIZED,
            403,
        )

        unacknowledged = read_position(position["id"])
        assert unacknowledged["alert_acknowledged_by_user_id"] is None
        assert unacknowledged["version"] == 1


class TestOutletOwnership:
    def test_the_manager_of_the_outlet_may_acknowledge_its_own_alert(self, api):
        """PRD §2.1: "When `X-User-Role` is `OutletManager`, `X-User-ID` **is** the `id` of
        the acting `Outlet`." The acknowledgement is then recorded, per §3.6: "An
        `OutletManager` acknowledges the current low-supply alert on their own outlet's
        position, which records the acting `X-User-ID` in `alert_acknowledged_by_user_id`
        and increments the position's `version` by one."

        Design: Corner/rbac/rbac_outlet_manager_acknowledges_its_own_position_alert
        """
        outlet, position = _outlet_with_a_position()
        manager = make_outlet_manager_headers(outlet["id"])

        acknowledged = validate_success(api.acknowledge_alert(position["id"], manager))
        assert acknowledged["alert_acknowledged_by_user_id"] == outlet["id"]
        assert acknowledged["version"] == 2
        assert acknowledged["on_hand_units"] == 2

    def test_a_foreign_manager_may_not_acknowledge_this_outlets_alert(self, api):
        """PRD §2.1: "Ownership checks on any resource that references an outlet therefore
        compare that resource's outlet reference to `X-User-ID`: the outlet itself for the
        brand-mix report, the `outlet_id` of a stock position when acknowledging an alert,
        and the outlet of the service call's dispenser unit when opening or cancelling a
        service call. A mismatch is rejected with `ERR_OUTLET_OWNERSHIP_REQUIRED` and HTTP
        403."

        Design: Corner/rbac/rbac_outlet_manager_denied_acknowledging_another_outlets_position
        """
        _outlet, position = _outlet_with_a_position()
        neighbour = create_outlet(
            name="Eastside Grill", account_code="OUT-1002", region_code="R-EAST"
        )

        validate_error(
            api.acknowledge_alert(
                position["id"], make_outlet_manager_headers(neighbour["id"])
            ),
            ApiErrorId.ERR_OUTLET_OWNERSHIP_REQUIRED,
            403,
        )

        unacknowledged = read_position(position["id"])
        assert unacknowledged["alert_acknowledged_by_user_id"] is None
        assert unacknowledged["version"] == 1

    def test_a_foreign_manager_may_not_read_this_outlets_brand_mix_report(self, api):
        """PRD §2.6 rung 6: "When the acting role is `OutletManager`, `X-User-ID` must
        equal the `id` of the outlet the target resource resolves to, otherwise
        `ERR_OUTLET_OWNERSHIP_REQUIRED` (403). This rung guards exactly four operations:
        `GET /fountain-network/outlets/{id}/brand-mix-report`,
        `POST /fountain-network/supply-positions/{id}/acknowledge-alert`,
        `POST /fountain-network/service-calls` and
        `POST /fountain-network/service-calls/{id}/cancel`."

        Design: Corner/rbac/rbac_outlet_manager_denied_reading_another_outlets_brand_mix_report
        """
        outlet = _outlet()
        neighbour = create_outlet(
            name="Eastside Grill", account_code="OUT-1002", region_code="R-EAST"
        )

        validate_error(
            api.get_brand_mix_report(
                outlet["id"], make_outlet_manager_headers(neighbour["id"])
            ),
            ApiErrorId.ERR_OUTLET_OWNERSHIP_REQUIRED,
            403,
        )

    def test_a_foreign_manager_may_not_open_a_call_on_this_outlets_machine(self, api):
        """PRD §3.8: "An `OutletManager` may only open a call for a machine at their own
        outlet, per §2.1." That resolution runs through the unit, per §2.1: "Ownership
        checks on any resource that references an outlet therefore compare that resource's
        outlet reference to `X-User-ID`: the outlet itself for the brand-mix report, the
        `outlet_id` of a stock position when acknowledging an alert, and the outlet of the
        service call's dispenser unit when opening or cancelling a service call."

        Design: Corner/rbac/rbac_outlet_manager_denied_opening_a_call_for_another_outlets_unit
        """
        _outlet, _agreement, unit = _outlet_agreement_and_unit()
        neighbour = create_outlet(
            name="Eastside Grill", account_code="OUT-1002", region_code="R-EAST"
        )

        validate_error(
            api.create_service_call(
                create_service_call_payload(unit["id"], "NO_POUR", CLOCK),
                make_outlet_manager_headers(neighbour["id"]),
            ),
            ApiErrorId.ERR_OUTLET_OWNERSHIP_REQUIRED,
            403,
        )

        assert read_unit(unit["id"])["version"] == 1

    def test_a_foreign_manager_may_not_cancel_this_outlets_call(self, api):
        """PRD §3.8: "Cancellation is available to the `OutletManager` who owns the outlet
        or to a `NetworkAdmin`, from `OPEN` or from `DISPATCHED`, and drives the call to
        the terminal `CANCELLED`." A mismatch is refused, per §2.1: "A mismatch is rejected
        with `ERR_OUTLET_OWNERSHIP_REQUIRED` and HTTP 403."

        Design: Corner/rbac/rbac_outlet_manager_denied_cancelling_another_outlets_service_call
        """
        _outlet, _agreement, unit = _outlet_agreement_and_unit()
        neighbour = create_outlet(
            name="Eastside Grill", account_code="OUT-1002", region_code="R-EAST"
        )
        call = create_call(unit["id"], "ICE_FAULT", CLOCK)

        validate_error(
            api.cancel_service_call(
                call["id"], make_outlet_manager_headers(neighbour["id"])
            ),
            ApiErrorId.ERR_OUTLET_OWNERSHIP_REQUIRED,
            403,
        )

        standing = read_call(call["id"])
        assert standing["status"] == "OPEN"
        assert standing["version"] == 1


class TestAssessmentDecisionSeparation:
    def test_the_user_who_assessed_may_not_also_decide(self, api):
        """PRD §2.6 rung 16: "The officer recording the recall decision must not be the
        administrator who ran the assessment, that is `X-User-ID` must differ from
        `shortfall_assessed_by_user_id`; otherwise `ERR_SEGREGATION_OF_DUTIES` (409) on
        `POST /fountain-network/placement-agreements/{id}/recall-decision`."

        Design: Corner/rbac/rbac_segregation_blocks_the_assessor_from_deciding_the_recall
        """
        base, _item, assessed = _q3_assessment_by_the_admin()
        assert assessed["assessed_fee_cents"] == 100000

        validate_error(
            api.recall_decision(
                base.agreement_id,
                recall_decision_payload("FEE_ONLY"),
                make_compliance_officer_headers(ADMIN["X-User-ID"]),
            ),
            ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
            409,
        )

        undecided = read_agreement(base.agreement_id)
        assert undecided["status"] == "SHORTFALL_REVIEW"
        assert undecided["recall_decided_by_user_id"] is None
        assert undecided["assessed_fee_cents"] == 100000
        assert undecided["version"] == 3

    def test_a_second_identity_may_record_the_fee_only_outcome(self, api):
        """PRD §3.9: "`FEE_ONLY` returns the agreement `SHORTFALL_REVIEW → ACTIVE` and
        leaves `assessed_fee_cents` standing as the amount payable — the cycle
        `ACTIVE → SHORTFALL_REVIEW → ACTIVE` may therefore be travelled once per assessment
        period." The identities are recorded separately, per §2.1: "The server records it
        wherever an audit or segregation-of-duties rule requires a name — as
        `last_hold_placed_by_user_id` on an outlet, as `shortfall_assessed_by_user_id` and
        `recall_decided_by_user_id` on a placement agreement, as `completed_by_user_id` and
        `waived_by_user_id` on a maintenance task, and as `assigned_tech_user_id` on a
        service call — but it never compares it to any entity's `id`."

        Design: Corner/rbac/rbac_second_user_id_may_record_the_fee_only_decision
        """
        base, _item, _assessed = _q3_assessment_by_the_admin()

        decided = validate_success(
            api.recall_decision(
                base.agreement_id, recall_decision_payload("FEE_ONLY"), OFFICER
            )
        )
        assert decided["status"] == "ACTIVE"
        assert decided["recall_decided_by_user_id"] == OFFICER["X-User-ID"]
        assert decided["shortfall_assessed_by_user_id"] == ADMIN["X-User-ID"]
        assert decided["assessed_fee_cents"] == 100000
        assert decided["version"] == 4
        assert read_unit(base.unit_id)["status"] == "IN_SERVICE"


class TestHoldWaiverSeparation:
    def test_the_officer_who_placed_the_hold_may_not_waive_the_task(self, api):
        """PRD §2.6 rung 17: "The officer waiving a maintenance task must not be the
        officer recorded in the outlet's `last_hold_placed_by_user_id`; otherwise
        `ERR_WAIVER_SEGREGATION_VIOLATION` (409) on
        `POST /fountain-network/maintenance-tasks/{id}/waive`."

        Design: Corner/rbac/rbac_waiver_segregation_blocks_the_hold_placing_officer
        """
        outlet, task = _overdue_sanitation_under_an_officers_hold()

        validate_error(
            api.waive_task(
                task["id"],
                waive_task_payload("Outlet promised a deep clean next week"),
                OFFICER,
            ),
            ApiErrorId.ERR_WAIVER_SEGREGATION_VIOLATION,
            409,
        )

        unwaived = read_task(task["id"])
        assert unwaived["status"] == "OVERDUE"
        assert unwaived["waived_by_user_id"] is None
        held = read_outlet(outlet["id"])
        assert held["overdue_task_count"] == 1
        assert held["last_hold_placed_by_user_id"] == OFFICER["X-User-ID"]
        assert held["service_posture"] == "FROZEN"

    def test_a_second_officer_may_waive_without_thawing_the_outlet(self, api):
        """PRD §3.5: "The waiver records that reason and the acting `X-User-ID` in
        `waived_by_user_id`, moves the task to the terminal `WAIVED` state and increments
        its `version` by one; waiving a task that was `OVERDUE` also decrements the
        outlet's `overdue_task_count` and recomputes `service_posture`." The hold still
        rules that recomputation, per §2.10: "Because the frozen clause is tested first, an
        outlet under a compliance hold is `FROZEN` even when it has zero overdue tasks."

        Design: Corner/rbac/rbac_waiver_accepted_from_a_second_compliance_officer
        """
        outlet, task = _overdue_sanitation_under_an_officers_hold()

        waived = validate_success(
            api.waive_task(
                task["id"],
                waive_task_payload("Third-party sanitation certificate on file"),
                OFFICER_ALT,
            )
        )
        assert waived["status"] == "WAIVED"
        assert waived["waived_by_user_id"] == OFFICER_ALT["X-User-ID"]
        assert waived["waiver_reason"] == "Third-party sanitation certificate on file"

        thawing = read_outlet(outlet["id"])
        assert thawing["overdue_task_count"] == 0
        assert thawing["open_compliance_hold_count"] == 1
        assert thawing["service_posture"] == "FROZEN"


class TestDispatchHolder:
    def test_another_technician_may_not_arrive_on_someone_elses_dispatch(self, api):
        """PRD §2.6 rung 11: "Arriving on site, resolving and escalating must be performed
        by the technician holding the current dispatch, that is `X-User-ID` equal to
        `assigned_tech_user_id`; otherwise `ERR_TECHNICIAN_NOT_ASSIGNED` (403). Guards
        `POST /fountain-network/service-calls/{id}/arrive-on-site`,
        `POST /fountain-network/service-calls/{id}/resolve` and
        `POST /fountain-network/service-calls/{id}/escalate`."

        Design: Corner/rbac/rbac_unassigned_technician_denied_arriving_on_site
        """
        _outlet, _agreement, unit = _outlet_agreement_and_unit()
        call = create_call(unit["id"], "LEAK", CLOCK)
        dispatch_call(
            call["id"], "VAN-7", "2026-08-02T09:00:00Z", "2026-08-02T11:00:00Z", TECH
        )

        validate_error(
            api.arrive_on_site(call["id"], TECH_ALT),
            ApiErrorId.ERR_TECHNICIAN_NOT_ASSIGNED,
            403,
        )

        waiting = read_call(call["id"])
        assert waiting["status"] == "DISPATCHED"
        assert waiting["assigned_tech_user_id"] == TECH["X-User-ID"]
        assert waiting["version"] == 2

    def test_another_technician_may_not_resolve_a_call_after_the_arrival(self, api):
        """PRD §2.6 rung 11: "Arriving on site, resolving and escalating must be performed
        by the technician holding the current dispatch, that is `X-User-ID` equal to
        `assigned_tech_user_id`; otherwise `ERR_TECHNICIAN_NOT_ASSIGNED` (403)." Because
        the refusal lands before settlement, §3.8's ledger movement never runs: "Settlement
        of the van row then follows the ledger of §2.11 exactly: the whole held reservation
        leaves `reserved_units`, the fitted quantity is added to `consumed_units`, and the
        difference between what was held and what was fitted returns to `on_van_units`."

        Design: Corner/rbac/rbac_unassigned_technician_denied_resolving_the_call
        """
        _outlet, _agreement, unit = _outlet_agreement_and_unit()
        stock = create_van_stock("VAN-7", "PUMP_ASSY_12", 5)
        call = create_call(unit["id"], "NO_POUR", CLOCK)
        dispatch_call(
            call["id"], "VAN-7", "2026-08-02T09:00:00Z", "2026-08-02T11:00:00Z", TECH,
            part_sku="PUMP_ASSY_12", part_units=2,
        )
        arrive_call(call["id"], TECH)

        validate_error(
            api.resolve_service_call(
                call["id"],
                resolve_call_payload("PART_REPLACED", consumed_part_units=2),
                TECH_ALT,
            ),
            ApiErrorId.ERR_TECHNICIAN_NOT_ASSIGNED,
            403,
        )

        unresolved = read_call(call["id"])
        assert unresolved["status"] == "ON_SITE"
        assert unresolved["reserved_part_units"] == 2
        untouched = read_van_stock(stock["id"])
        assert untouched["on_van_units"] == 3
        assert untouched["reserved_units"] == 2
        assert untouched["consumed_units"] == 0
