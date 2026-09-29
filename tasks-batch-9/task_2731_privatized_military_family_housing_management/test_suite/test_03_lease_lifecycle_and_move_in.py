"""The tenancy's two state dimensions, the move-in gates, and the unit turn."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import assertions as asserts
from test_helpers import constants as const
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import TEST_USERS, make_service_member_headers

HAZARD_CLOCK = "2026-09-20T10:00:00Z"
REMEDIATION_CLOCK = "2026-09-25T09:00:00Z"
NOTICE_CLOCK = "2026-10-01T00:00:00Z"
TERMINATION_CLOCK = "2026-11-19T10:00:00Z"
NOTICE_DATE = "2026-10-01"
EFFECTIVE_DATE = "2026-11-19"

# September's rent charged, then eleven days of it credited back (2026-09-20
# through 2026-09-30 inclusive, at 7172 a day).
SEPTEMBER_ABATEMENT_CENTS = 78892
BALANCE_AFTER_ABATEMENT_CENTS = 139258
# Nineteen days of November at 7172, then eight percent of that base.
PRORATED_FINAL_MONTH_CENTS = 136268
CONVENIENCE_FEE_CENTS = 10901
SETTLEMENT_TOTAL_CENTS = 147169


def _suspended_by_a_hazard(api):
    """The canonical tenancy, charged for September and then displaced."""
    state = fx.setup_charged_lease(api)
    return fx.setup_displaced_household(
        api,
        occupied_state=state,
        hazard_clock=HAZARD_CLOCK,
        report_overrides={
            "lease_id": state["lease"]["id"],
            "reported_symptoms": "Black growth spreading across the master bedroom wall",
        },
        assess_overrides={"child_under_six_present": True},
    )


def test_move_in_advances_both_lease_dimensions_in_one_request(api):
    """Arrival starts the tenancy and the allotment together.

    PRD: "It advances the occupancy dimension `PENDING_MOVE_IN → OCCUPIED`."

    Design: Difficulty/non_linear_state_machine/lease_parallel_occupancy_and_allotment_dimensions
    """
    state = fx.setup_occupied_lease(api)
    lease = state["lease"]

    asserts.assert_lease(lease)
    assert lease["occupancy_status"] == "OCCUPIED"
    assert lease["allotment_status"] == "ACTIVE"
    assert lease["rent_basis"] == "MOVE_IN_FINAL"
    assert lease["net_rent_cents"] == const.BASE_NET_RENT_CENTS
    assert state["unit"]["status"] == "OCCUPIED"
    assert state["installation"]["occupied_unit_count"] == 1
    assert state["installation"]["assigned_unit_count"] == 0


def test_hazard_assessment_moves_only_the_allotment_dimension(api):
    """A displacement suspends the ledger and leaves the tenancy occupied.

    PRD: "As a third hop, because the unit entered `HAZARD_HOLD`, every lease on that unit whose `allotment_status` is `ACTIVE` advances `ACTIVE → SUSPENDED` with the lease's `version` incremented by 1."

    Design: Difficulty/non_linear_state_machine/lease_parallel_occupancy_and_allotment_dimensions
    """
    state = _suspended_by_a_hazard(api)
    lease = state["lease"]

    assert lease["occupancy_status"] == "OCCUPIED"
    assert lease["allotment_status"] == "SUSPENDED"
    assert state["unit"]["status"] == "HAZARD_HOLD"
    assert lease["abatement_total_cents"] == SEPTEMBER_ABATEMENT_CENTS
    assert lease["allotment_balance_cents"] == BALANCE_AFTER_ABATEMENT_CENTS
    asserts.assert_ledger_conservation(fx.read_ledger(api, lease["id"]), lease)


def test_clearance_returns_only_the_allotment_dimension(api):
    """A passed clearance restores collection without touching the ledger.

    PRD: "and the lease advances `SUSPENDED → ACTIVE` with **no reinstating ledger row**: the abatement was earned by a real habitability failure and stays on the ledger."

    Design: Difficulty/non_linear_state_machine/lease_parallel_occupancy_and_allotment_dimensions
    """
    state = _suspended_by_a_hazard(api)
    fx.set_clock(api, REMEDIATION_CLOCK)
    fx.complete_remediation(api, state["hazard_case"])
    fx.certify_clearance(api, state["hazard_case"]["id"], True)

    lease = fx.read_lease(api, state["lease"]["id"])
    assert lease["occupancy_status"] == "OCCUPIED"
    assert lease["allotment_status"] == "ACTIVE"
    assert lease["allotment_balance_cents"] == BALANCE_AFTER_ABATEMENT_CENTS
    assert lease["abatement_total_cents"] == SEPTEMBER_ABATEMENT_CENTS
    ledger = fx.read_ledger(api, lease["id"])
    assert [row["type"] for row in ledger] == ["CHARGE", "ABATEMENT"]
    assert fx.read_housing_unit(api, state["unit"]["id"])["status"] == "OCCUPIED"


def test_notice_moves_occupancy_alone_and_termination_closes_both(api):
    """Notice touches one dimension; only termination closes the ledger.

    PRD: "The notice deliberately leaves `allotment_status` untouched: rent keeps being collected right up to termination."

    Design: Difficulty/non_linear_state_machine/lease_parallel_occupancy_and_allotment_dimensions
    """
    state = _suspended_by_a_hazard(api)
    fx.set_clock(api, REMEDIATION_CLOCK)
    fx.complete_remediation(api, state["hazard_case"])
    fx.certify_clearance(api, state["hazard_case"]["id"], True)
    fx.set_clock(api, NOTICE_CLOCK)

    under_notice = fx.give_termination_notice(
        api,
        state["lease"]["id"],
        "CONVENIENCE",
        NOTICE_DATE,
        EFFECTIVE_DATE,
        headers=make_service_member_headers(state["sponsor"]["id"]),
    )
    assert under_notice["occupancy_status"] == "NOTICE_GIVEN"
    assert under_notice["allotment_status"] == "ACTIVE"

    fx.set_clock(api, TERMINATION_CLOCK)
    terminated = fx.terminate_lease(api, state["lease"]["id"])

    assert terminated["occupancy_status"] == "TERMINATED"
    assert terminated["allotment_status"] == "CLOSED"
    assert terminated["early_termination_fee_cents"] == CONVENIENCE_FEE_CENTS
    assert terminated["settlement_total_cents"] == SETTLEMENT_TOTAL_CENTS
    unit = fx.read_housing_unit(api, state["unit"]["id"])
    assert unit["status"] == "AVAILABLE"
    assert unit["last_lease_end_date"] == EFFECTIVE_DATE
    ledger = fx.read_ledger(api, state["lease"]["id"])
    asserts.assert_ledger_conservation(ledger, terminated)
    fee_rows = [r for r in ledger if r["type"] == "EARLY_TERMINATION_FEE"]
    assert len(fee_rows) == 1
    assert fee_rows[0]["amount_cents"] == CONVENIENCE_FEE_CENTS


DEFICIENCY_CLOCK = "2026-08-31T14:00:00Z"
CRITICAL_DUE_AT = "2026-09-01T14:00:00Z"
REPAIR_CLOCK = "2026-09-01T10:00:00Z"
ARRIVAL_CLOCK = "2026-09-01T11:00:00Z"


def _walkthrough_with_one_critical_finding(api):
    """A scheduled walkthrough that logged one critical and one cosmetic entry."""
    state = fx.setup_lease_pending_move_in(api)
    inspection = fx.schedule_inspection(api, state["lease"]["id"])
    fx.set_clock(api, DEFICIENCY_CLOCK)
    state["inspection"] = fx.log_deficiencies(
        api,
        inspection["id"],
        [
            f.deficiency_entry("NO_HEAT", "LIVING_ROOM", "HABITABILITY_CRITICAL"),
            f.deficiency_entry("COSMETIC", "HALLWAY", "COSMETIC"),
        ],
    )
    return state


def _acknowledge(api, state):
    sponsor = state["sponsor"]
    return fx.acknowledge_inspection(
        api,
        state["inspection"]["id"],
        sponsor,
        f"{sponsor['first_name']} {sponsor['last_name']}",
        state["installation"]["bill_of_rights_version"],
    )


def _spawned_work_orders(api, housing_unit_id):
    return validate_success(
        api.list_work_orders(
            TEST_USERS["property_manager_headers"],
            params={"housing_unit_id": housing_unit_id},
        )
    )


def test_logging_deficiencies_creates_no_work_order(api):
    """The walkthrough only records findings; nothing is dispatched yet.

    PRD: "Crucially, **no work order is created at logging time**; critical entries spawn their work orders later, at tenant acknowledgment."

    Design: Difficulty/cross_entity_state_dependency/move_in_gated_on_move_in_inspection_critical_deficiency_clearing
    """
    state = _walkthrough_with_one_critical_finding(api)
    inspection = state["inspection"]

    asserts.assert_move_in_inspection(inspection)
    assert inspection["status"] == "DEFICIENCIES_LOGGED"
    assert inspection["deficiency_count"] == 2
    assert inspection["critical_open_count"] == 1
    for entry in inspection["deficiencies"]:
        assert entry["status"] == "OPEN"
        assert entry["work_order_id"] is None
    assert _spawned_work_orders(api, state["unit"]["id"]) == []


def test_acknowledgment_spawns_the_critical_order_and_holds_the_count_up(api):
    """The signature dispatches the critical finding without clearing it.

    PRD: "As a third hop, `critical_open_count` is recomputed; because `WORK_ORDER_CREATED` is not `RESOLVED`, the count does not drop, so move-in stays blocked until every spawned order actually completes."

    Design: Difficulty/cross_entity_state_dependency/move_in_gated_on_move_in_inspection_critical_deficiency_clearing
    """
    state = _walkthrough_with_one_critical_finding(api)

    acknowledged = _acknowledge(api, state)

    assert acknowledged["status"] == "TENANT_ACKNOWLEDGED"
    assert acknowledged["critical_open_count"] == 1
    by_code = {e["deficiency_code"]: e for e in acknowledged["deficiencies"]}
    assert by_code["NO_HEAT"]["status"] == "WORK_ORDER_CREATED"
    assert by_code["NO_HEAT"]["work_order_id"] is not None
    assert by_code["COSMETIC"]["status"] == "OPEN"
    assert by_code["COSMETIC"]["work_order_id"] is None
    lease = fx.read_lease(api, state["lease"]["id"])
    assert lease["bill_of_rights_version_ack"] == const.TEST_DEFAULTS[
        "BILL_OF_RIGHTS_VERSION"
    ]
    assert lease["bill_of_rights_ack_at"] is not None
    orders = _spawned_work_orders(api, state["unit"]["id"])
    assert len(orders) == 1
    order = orders[0]
    assert order["category"] == "NO_HEAT"
    assert order["inspection_deficiency_code"] == "NO_HEAT"
    assert order["habitability_impact"] is True
    assert order["priority_class"] == "EMERGENCY"
    asserts.assert_instant_equals(order["completion_due_at"], CRITICAL_DUE_AT)


def test_move_in_waits_for_the_critical_order_to_complete(api):
    """The lease is ready in itself; the inspection's counter is what blocks it.

    PRD: "requires that inspection's `critical_open_count` to be 0 — otherwise `ERR_UNRESOLVED_CRITICAL_DEFICIENCY`"

    Design: Difficulty/cross_entity_state_dependency/move_in_gated_on_move_in_inspection_critical_deficiency_clearing
    """
    state = _walkthrough_with_one_critical_finding(api)
    acknowledged = _acknowledge(api, state)
    order_id = next(
        e["work_order_id"]
        for e in acknowledged["deficiencies"]
        if e["deficiency_code"] == "NO_HEAT"
    )

    blocked = api.move_in(state["lease"]["id"], TEST_USERS["property_manager_headers"])
    validate_error(blocked, ApiErrorId.ERR_UNRESOLVED_CRITICAL_DEFICIENCY, 409)
    lease = fx.read_lease(api, state["lease"]["id"])
    assert lease["occupancy_status"] == "PENDING_MOVE_IN"
    assert lease["allotment_status"] == "NOT_STARTED"
    assert fx.read_housing_unit(api, state["unit"]["id"])["status"] == "ASSIGNED"

    fx.set_clock(api, REPAIR_CLOCK)
    fx.assign_work_order(api, order_id)
    fx.start_work_order(api, order_id)
    completed = fx.complete_work_order(api, order_id)
    assert completed["status"] == "COMPLETED"
    assert completed["sla_breached"] is False

    inspection = fx.read_inspection(api, acknowledged["id"])
    by_code = {e["deficiency_code"]: e for e in inspection["deficiencies"]}
    assert by_code["NO_HEAT"]["status"] == "RESOLVED"
    assert by_code["COSMETIC"]["status"] == "OPEN"
    assert inspection["deficiency_count"] == 2
    assert inspection["critical_open_count"] == 0
    assert inspection["status"] == "COMPLETED"

    fx.set_clock(api, ARRIVAL_CLOCK)
    occupied = fx.move_in(api, state["lease"]["id"])
    assert occupied["occupancy_status"] == "OCCUPIED"
    assert occupied["allotment_status"] == "ACTIVE"
    assert occupied["rent_basis"] == "MOVE_IN_FINAL"
    assert occupied["net_rent_cents"] == const.BASE_NET_RENT_CENTS
    installation = fx.read_installation(api, state["installation"]["id"])
    assert installation["occupied_unit_count"] == 1
    assert installation["assigned_unit_count"] == 0


LEASE_START_CLOCK = "2026-09-01T09:00:00Z"
HOLD_REASON = "Lead paint survey pending on the stair rail"


def _pending_move_in_on_a_held_unit(api):
    """A lease whose inspection is unsigned and whose unit is also on hold."""
    state = fx.setup_lease_pending_move_in(api)
    state["inspection"] = fx.schedule_inspection(api, state["lease"]["id"])
    validate_success(
        api.set_housing_unit_status(
            state["unit"]["id"],
            f.housing_unit_status_payload(
                "HAZARD_HOLD", hazard_hold_reason=HOLD_REASON
            ),
            TEST_USERS["property_manager_headers"],
        )
    )
    fx.set_clock(api, LEASE_START_CLOCK)
    return state


def test_unsigned_inspection_is_reported_before_the_hazard_hold(api):
    """The state gate at rung 24 answers ahead of the safety gate at rung 29.

    PRD: "Rung 24 requires, on move-in, that the lease have a move-in inspection whose `status` is `TENANT_ACKNOWLEDGED` or `COMPLETED`, failing with `ERR_INSPECTION_NOT_ACKNOWLEDGED` (409)."

    Design: Difficulty/priority_pair_validation_conflict/move_in_inspection_gate_outranks_hazard_hold_gate
    """
    state = _pending_move_in_on_a_held_unit(api)

    response = api.move_in(
        state["lease"]["id"], TEST_USERS["property_manager_headers"]
    )

    validate_error(response, ApiErrorId.ERR_INSPECTION_NOT_ACKNOWLEDGED, 409)
    lease = fx.read_lease(api, state["lease"]["id"])
    assert lease["occupancy_status"] == "PENDING_MOVE_IN"
    assert lease["allotment_status"] == "NOT_STARTED"
    assert lease["rent_basis"] == "OFFER_PROVISIONAL"
    assert lease["gross_rent_cents"] == const.BASE_GROSS_RENT_CENTS
    assert lease["net_rent_cents"] == const.BASE_NET_RENT_CENTS
    assert lease["daily_rent_cents"] == const.BASE_DAILY_RENT_CENTS
    inspection = fx.read_inspection(api, state["inspection"]["id"])
    assert inspection["status"] == "SCHEDULED"
    assert inspection["tenant_signature_at"] is None
    unit = fx.read_housing_unit(api, state["unit"]["id"])
    assert unit["status"] == "HAZARD_HOLD"
    installation = fx.read_installation(api, state["installation"]["id"])
    assert installation["hazard_hold_unit_count"] == 1
    assert installation["assigned_unit_count"] == 0
    assert installation["occupied_unit_count"] == 0
    assert installation["total_unit_count"] == 1


def test_hazard_hold_surfaces_once_the_inspection_is_signed(api):
    """The lower-numbered gate was masking a live hold, not its absence.

    PRD: "Rung 29 requires that the housing unit not be in `HAZARD_HOLD`, because a unit under an environmental hazard hold may neither be leased nor moved into; it guards exactly two operations, lease creation and move-in, failing with `ERR_HAZARD_HOLD_ACTIVE` (409)."

    Design: Difficulty/priority_pair_validation_conflict/move_in_inspection_gate_outranks_hazard_hold_gate
    """
    state = _pending_move_in_on_a_held_unit(api)
    acknowledged = _acknowledge(api, state)
    assert acknowledged["status"] == "COMPLETED"
    assert acknowledged["critical_open_count"] == 0

    response = api.move_in(
        state["lease"]["id"], TEST_USERS["property_manager_headers"]
    )

    validate_error(response, ApiErrorId.ERR_HAZARD_HOLD_ACTIVE, 409)
    lease = fx.read_lease(api, state["lease"]["id"])
    assert lease["occupancy_status"] == "PENDING_MOVE_IN"
    assert lease["allotment_status"] == "NOT_STARTED"


TURN_NOTICE_DATE = "2026-10-15"
TURN_NOTICE_CLOCK = "2026-10-15T09:00:00Z"
LAST_LEASE_END_DATE = "2026-11-19"
RELET_CLOCK = "2026-11-20T00:00:00Z"
TOO_SOON_START = "2026-11-23"
EXACT_BUFFER_START = "2026-11-24"


def _released_unit_reoffered_to_a_second_family(api):
    """The unit freed on 2026-11-19 and already accepted by a second family."""
    state = fx.setup_released_unit(
        api,
        notice_date=TURN_NOTICE_DATE,
        effective_date=LAST_LEASE_END_DATE,
        notice_clock=TURN_NOTICE_CLOCK,
        terminate_clock=TERMINATION_CLOCK,
    )
    assert state["unit"]["status"] == "AVAILABLE"
    assert state["unit"]["last_lease_end_date"] == LAST_LEASE_END_DATE
    fx.set_clock(api, RELET_CLOCK)
    sponsor, dependents = fx.setup_sponsor_family(
        api, dodid="1000000002", last_name="Okafor", first_name="Dele"
    )
    application = fx.submit_application(
        api,
        state["installation"]["id"],
        sponsor,
        pcs_orders_date="2026-11-20",
        expected_arrival_date=EXACT_BUFFER_START,
    )
    fx.run_offer_run(api, state["installation"]["id"])
    state["sponsor_2"] = sponsor
    state["dependents_2"] = dependents
    state["application_2"] = fx.accept_offer(api, application["id"], sponsor)
    return state


def test_start_date_inside_the_turn_buffer_is_refused(api):
    """Four whole days after the last tenancy ended is not enough turn time.

    PRD: "Rung 41 requires the new lease's `start_date` to be at least the installation's `turn_buffer_days` whole days after the unit's `last_lease_end_date`; it guards lease creation, failing with `ERR_UNIT_TURN_BUFFER_VIOLATION` (409)."

    Design: Difficulty/resource_temporal_overlap/unit_turn_buffer_minimum_whole_day_gap_between_leases
    """
    state = _released_unit_reoffered_to_a_second_family(api)

    response = api.create_lease(
        f.create_lease_payload(
            state["application_2"]["id"],
            state["unit"]["id"],
            start_date=TOO_SOON_START,
        ),
        TEST_USERS["property_manager_headers"],
    )

    validate_error(response, ApiErrorId.ERR_UNIT_TURN_BUFFER_VIOLATION, 409)
    leases = validate_success(
        api.list_leases(
            TEST_USERS["property_manager_headers"],
            params={"housing_unit_id": state["unit"]["id"]},
        )
    )
    assert len(leases) == 1
    assert leases[0]["occupancy_status"] == "TERMINATED"
    assert fx.read_application(api, state["application_2"]["id"])["status"] == "ACCEPTED"
    assert fx.read_housing_unit(api, state["unit"]["id"])["status"] == "ASSIGNED"


def test_start_date_exactly_at_the_turn_buffer_is_accepted(api):
    """Exactly five whole days clears the gap, so the boundary is inclusive.

    PRD: "A unit that has never been leased carries a null `last_lease_end_date` and the turn-buffer rule does not constrain it."

    Design: Difficulty/resource_temporal_overlap/unit_turn_buffer_minimum_whole_day_gap_between_leases
    """
    state = _released_unit_reoffered_to_a_second_family(api)

    lease = fx.write_lease(
        api,
        state["application_2"]["id"],
        state["unit"]["id"],
        start_date=EXACT_BUFFER_START,
    )

    assert lease["occupancy_status"] == "PENDING_MOVE_IN"
    assert lease["allotment_status"] == "NOT_STARTED"
    assert lease["gross_rent_cents"] == const.BASE_GROSS_RENT_CENTS
    assert lease["net_rent_cents"] == const.BASE_NET_RENT_CENTS
    assert fx.read_application(api, state["application_2"]["id"])["status"] == "HOUSED"
    unit = fx.read_housing_unit(api, state["unit"]["id"])
    assert unit["last_lease_end_date"] == LAST_LEASE_END_DATE
