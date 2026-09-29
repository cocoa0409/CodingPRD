"""Negotiation loops, escalation ladders, hold releases and stamped-once fields."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import assertions as asserts
from test_helpers import constants as const
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import (
    MAINTENANCE_TECH_USER_ID,
    MAINTENANCE_TECH_USER_ID_2,
    PROPERTY_MANAGER_USER_ID,
    TEST_USERS,
    make_maintenance_tech_headers,
    make_service_member_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
MANAGER = TEST_USERS["property_manager_headers"]
HOUSING_OFFICE = TEST_USERS["installation_housing_office_headers"]
SPECIALIST = TEST_USERS["environmental_specialist_headers"]

MOVE_IN_CLOCK = fx.CLOCK_AT_MOVE_IN
RESOLUTION_DUE_AT = "2026-10-01T09:00:00Z"
HVAC_COMPLAINT = "The HVAC repair did not hold for a week"
ROUND_ONE_REMEDY = "Re-inspect the air handler"
ROUND_TWO_REMEDY = "Replace the blower motor"
ROUND_THREE_REMEDY = "Replace the condenser and credit one week of rent"
ROUND_FOUR_REMEDY = "One more try"
STANDING_OFFER_CENTS = 25000


def test_the_rejection_loop_runs_to_the_round_cap_then_escalates(api):
    """Two rejections cycle back; the third leaves the manager's authority.

    PRD: "When `round_count` has reached 3 the case instead goes `RESIDENT_REJECTED → ESCALATED_INSTALLATION` with `escalated_at` stamped from the logical clock; the case leaves the property manager's authority and no further landlord proposal is accepted."

    Design: Corner/state_machines/dispute_rejection_loops_to_the_round_cap_then_auto_escalates
    """
    state = fx.setup_occupied_lease(api)
    dispute = fx.open_dispute(
        api,
        state["lease"]["id"],
        state["sponsor"],
        category="MAINTENANCE_QUALITY",
        description=HVAC_COMPLAINT,
    )
    asserts.assert_instant_equals(dispute["resolution_due_at"], RESOLUTION_DUE_AT)

    first = fx.propose_resolution(api, dispute["id"], ROUND_ONE_REMEDY, 0)
    assert first["status"] == "PROPOSED_RESOLUTION"
    assert first["round_count"] == 1
    assert first["proposed_by_user_id"] == PROPERTY_MANAGER_USER_ID
    rejected_once = fx.respond_to_proposal(api, dispute["id"], state["sponsor"], False)
    assert rejected_once["status"] == "UNDER_REVIEW"

    second = fx.propose_resolution(api, dispute["id"], ROUND_TWO_REMEDY, 5000)
    assert second["round_count"] == 2
    rejected_twice = fx.respond_to_proposal(api, dispute["id"], state["sponsor"], False)
    assert rejected_twice["status"] == "UNDER_REVIEW"

    third = fx.propose_resolution(
        api, dispute["id"], ROUND_THREE_REMEDY, STANDING_OFFER_CENTS
    )
    assert third["round_count"] == const.DISPUTE_ROUND_CAP
    escalated = fx.respond_to_proposal(api, dispute["id"], state["sponsor"], False)

    assert escalated["status"] == "ESCALATED_INSTALLATION"
    asserts.assert_instant_equals(escalated["escalated_at"], MOVE_IN_CLOCK)
    # The standing offer survives on the record but nothing was awarded.
    assert escalated["credit_offer_cents"] == STANDING_OFFER_CENTS
    assert escalated["credit_award_cents"] == 0

    validate_error(
        api.propose_resolution(
            dispute["id"], f.propose_resolution_payload(ROUND_FOUR_REMEDY, 30000), MANAGER
        ),
        ApiErrorId.ERR_INVALID_STATE_TRANSITION,
        409,
    )
    _, ledger_meta = validate_paginated(
        api.list_lease_allotment_transactions(state["lease"]["id"], MANAGER)
    )
    assert ledger_meta["total_count"] == 0


SEPTEMBER = "2026-09"
CHARGE_SOURCE_REF = "ALLOTMENT_RUN:2026-09"
CREDIT_REMEDY = "One week of rent credited back"
BALANCE_AFTER_CREDIT_CENTS = 193150


def test_accepting_the_offer_posts_one_refund_row_and_reconciles_the_balance(api):
    """The credit is a negative row appended after the charge, not a rewrite.

    PRD: "When the awarded credit is greater than 0 a `REFUND` row is posted to the lease's ledger with `amount_cents` equal to the negated award and `source_ref` equal to `DISPUTE_AWARD:` followed by the dispute case's identifier, after which the lease's `allotment_balance_cents` is recomputed."

    Design: Corner/state_machines/accepted_dispute_credit_posts_one_refund_row_and_reconciles_the_balance
    """
    state = fx.setup_charged_lease(api, period_month=SEPTEMBER)
    dispute = fx.open_dispute(api, state["lease"]["id"], state["sponsor"])
    fx.propose_resolution(api, dispute["id"], CREDIT_REMEDY, STANDING_OFFER_CENTS)

    accepted = fx.respond_to_proposal(api, dispute["id"], state["sponsor"], True)

    assert accepted["status"] == "CLOSED_RESOLVED"
    assert accepted["credit_award_cents"] == STANDING_OFFER_CENTS
    assert accepted["credit_offer_cents"] == STANDING_OFFER_CENTS
    assert accepted["round_count"] == 1

    ledger, ledger_meta = validate_paginated(
        api.list_lease_allotment_transactions(
            state["lease"]["id"], MANAGER, params={"period_month": SEPTEMBER}
        )
    )
    assert ledger_meta["total_count"] == 2
    charge, refund = ledger
    assert charge["type"] == "CHARGE"
    assert charge["amount_cents"] == const.BASE_NET_RENT_CENTS
    assert charge["running_balance_cents"] == const.BASE_NET_RENT_CENTS
    assert charge["source_ref"] == CHARGE_SOURCE_REF
    assert refund["type"] == "REFUND"
    assert refund["amount_cents"] == -STANDING_OFFER_CENTS
    assert refund["running_balance_cents"] == BALANCE_AFTER_CREDIT_CENTS
    assert refund["source_ref"] == f"DISPUTE_AWARD:{dispute['id']}"
    assert refund["period_month"] == SEPTEMBER
    asserts.assert_instant_equals(refund["posted_at"], MOVE_IN_CLOCK)

    lease = fx.read_lease(api, state["lease"]["id"])
    assert lease["allotment_balance_cents"] == BALANCE_AFTER_CREDIT_CENTS
    # A dispute credit is not an abatement and does not suspend the allotment.
    assert lease["abatement_total_cents"] == 0
    assert lease["allotment_status"] == "ACTIVE"
    asserts.assert_ledger_conservation(ledger, lease)


NO_HEAT_CLOCK = "2026-09-05T00:00:00Z"
NO_HEAT_DESCRIPTION = "Furnace will not ignite, house at 12 degrees"
EMERGENCY_RESPONSE_DUE_AT = "2026-09-05T04:00:00Z"
EMERGENCY_COMPLETION_DUE_AT = "2026-09-06T00:00:00Z"
ONE_SECOND_SHORT_CLOCK = "2026-09-06T23:59:59Z"
LEVEL_TWO_CLOCK = "2026-09-07T00:00:00Z"


def test_the_escalation_self_loop_climbs_without_moving_the_work_status(api):
    """Level one at the deadline, level two only after twenty-four overdue hours.

    PRD: "Escalation is a self-loop: it is available from `SUBMITTED`, `ASSIGNED`, `IN_PROGRESS` and `REOPENED`, and it preserves the order's `status` while advancing the escalation ladder."

    Design: Corner/state_machines/escalation_self_loop_climbs_the_ladder_without_moving_the_work_status
    """
    state = fx.setup_occupied_lease(api)
    sponsor_headers = make_service_member_headers(state["sponsor"]["id"])
    fx.set_clock(api, NO_HEAT_CLOCK)
    order = fx.submit_work_order(
        api,
        state["unit"]["id"],
        headers=sponsor_headers,
        lease_id=state["lease"]["id"],
        category="NO_HEAT",
        description=NO_HEAT_DESCRIPTION,
    )
    assert order["priority_class"] == "EMERGENCY"
    asserts.assert_instant_equals(
        order["response_due_at"], EMERGENCY_RESPONSE_DUE_AT
    )
    asserts.assert_instant_equals(
        order["completion_due_at"], EMERGENCY_COMPLETION_DUE_AT
    )

    fx.set_clock(api, EMERGENCY_COMPLETION_DUE_AT)
    first = validate_success(api.escalate_work_order(order["id"], sponsor_headers))
    assert first["escalation_level"] == 1
    asserts.assert_instant_equals(first["escalated_at"], EMERGENCY_COMPLETION_DUE_AT)
    assert first["status"] == "SUBMITTED"
    # The breach comparison is strict and the order is not complete.
    assert first["sla_breached"] is False

    fx.set_clock(api, ONE_SECOND_SHORT_CLOCK)
    validate_error(
        api.escalate_work_order(order["id"], HOUSING_OFFICE),
        ApiErrorId.ERR_ESCALATION_NOT_DUE,
        409,
    )

    fx.set_clock(api, LEVEL_TWO_CLOCK)
    second = validate_success(api.escalate_work_order(order["id"], MANAGER))

    assert second["escalation_level"] == const.MAX_ESCALATION_LEVEL
    asserts.assert_instant_equals(second["escalated_at"], LEVEL_TWO_CLOCK)
    assert second["status"] == "SUBMITTED"
    assert second["priority_class"] == "EMERGENCY"
    assert second["assigned_tech_user_id"] is None
    # Escalation never rewrites the SLA clocks.
    asserts.assert_instant_equals(
        second["response_due_at"], EMERGENCY_RESPONSE_DUE_AT
    )
    asserts.assert_instant_equals(
        second["completion_due_at"], EMERGENCY_COMPLETION_DUE_AT
    )


TURN_HOLD_REASON = "MOLD suspected behind the tub surround during turn"
# The offer run stamps the logical clock plus the installation's default
# offer_response_hours of 72: 2026-08-25T00:00:00Z + 72h.
OFFER_EXPIRES_AT = "2026-08-28T00:00:00Z"


def _unit_reserved_by_an_open_offer(api):
    """One unit ASSIGNED by the offer run, its application still OFFERED."""
    base = fx.setup_installation_with_unit(api)
    sponsor, _ = fx.setup_sponsor_family(api)
    application = fx.submit_application(api, base["installation"]["id"], sponsor)
    fx.run_offer_run(api, base["installation"]["id"])
    base["sponsor"] = sponsor
    base["application"] = fx.read_application(api, application["id"])
    return base


def test_releasing_a_hold_returns_an_assigned_unit_to_available(api):
    """The unit comes back to the pool, not to the sponsor who was holding it.

    PRD: "One consequence deserves emphasis: a unit that was `ASSIGNED` before the hold returns to `AVAILABLE`, not to `ASSIGNED`."

    Design: Corner/state_machines/releasing_a_hazard_hold_returns_an_assigned_unit_to_available_not_assigned
    """
    state = _unit_reserved_by_an_open_offer(api)
    unit_id = state["unit"]["id"]
    assert state["application"]["status"] == "OFFERED"

    held = validate_success(
        api.set_housing_unit_status(
            unit_id,
            f.housing_unit_status_payload(
                "HAZARD_HOLD", hazard_hold_reason=TURN_HOLD_REASON
            ),
            MANAGER,
        )
    )

    assert held["status"] == "HAZARD_HOLD"
    assert held["hazard_hold_reason"] == TURN_HOLD_REASON
    assert held["version"] == 3
    during = fx.read_installation(api, state["installation"]["id"])
    assert during["assigned_unit_count"] == 0
    assert during["hazard_hold_unit_count"] == 1
    assert during["available_unit_count"] == 0
    assert during["total_unit_count"] == 1
    asserts.assert_installation_counter_conservation(during)
    # The unit machine moved without touching the application machine.
    offered = fx.read_application(api, state["application"]["id"])
    assert offered["status"] == "OFFERED"
    assert offered["offered_unit_id"] == unit_id
    asserts.assert_instant_equals(offered["offer_expires_at"], OFFER_EXPIRES_AT)

    released = validate_success(
        api.set_housing_unit_status(
            unit_id, f.housing_unit_status_payload("AVAILABLE"), MANAGER
        )
    )

    assert released["status"] == "AVAILABLE"
    assert released["hazard_hold_reason"] is None
    assert released["version"] == 4
    after = fx.read_installation(api, state["installation"]["id"])
    assert after["available_unit_count"] == 1
    assert after["hazard_hold_unit_count"] == 0
    assert after["assigned_unit_count"] == 0
    asserts.assert_installation_counter_conservation(after)


LEAK_REPORT_CLOCK = "2026-09-10T08:00:00Z"
LEAK_DESCRIPTION = "Slow drip under the kitchen sink"
URGENT_COMPLETION_DUE_AT = "2026-09-13T08:00:00Z"
WORK_START_CLOCK = "2026-09-10T12:00:00Z"
COMPLETION_CLOCK = "2026-09-11T09:00:00Z"
REOPEN_CLOCK = "2026-09-14T09:00:00Z"
REOPEN_REASON = "The drip came back overnight"
COMPLETION_NOTE = {"completion_note": "Tightened the P-trap"}


def test_first_response_at_is_stamped_once_and_survives_the_reopen_loop(api):
    """The reassignment after a reopen leaves the original first response alone.

    PRD: "Assignment stamps `first_response_at` from the logical clock **only when it is still null**, so the first assignment records the first response and a re-assignment after a reopen leaves the original first-response instant intact."

    Design: Corner/state_machines/first_response_at_is_stamped_once_and_survives_the_reopen_loop
    """
    state = fx.setup_occupied_lease(api)
    sponsor_headers = make_service_member_headers(state["sponsor"]["id"])
    fx.set_clock(api, LEAK_REPORT_CLOCK)
    order = fx.submit_work_order(
        api,
        state["unit"]["id"],
        headers=sponsor_headers,
        lease_id=state["lease"]["id"],
        category="PLUMBING_LEAK",
        description=LEAK_DESCRIPTION,
    )
    assert order["priority_class"] == "URGENT"
    asserts.assert_instant_equals(
        order["completion_due_at"], URGENT_COMPLETION_DUE_AT
    )

    assigned = fx.assign_work_order(api, order["id"], MAINTENANCE_TECH_USER_ID)
    assert assigned["status"] == "ASSIGNED"
    asserts.assert_instant_equals(assigned["first_response_at"], LEAK_REPORT_CLOCK)
    assert assigned["assigned_tech_user_id"] == MAINTENANCE_TECH_USER_ID

    fx.set_clock(api, WORK_START_CLOCK)
    started = fx.start_work_order(api, order["id"])
    assert started["status"] == "IN_PROGRESS"

    fx.set_clock(api, COMPLETION_CLOCK)
    completed = validate_success(
        api.complete_work_order(
            order["id"], make_maintenance_tech_headers(), COMPLETION_NOTE
        )
    )
    assert completed["status"] == "COMPLETED"
    asserts.assert_instant_equals(completed["completed_at"], COMPLETION_CLOCK)
    assert completed["sla_breached"] is False

    fx.set_clock(api, REOPEN_CLOCK)
    reopened = fx.reopen_work_order(
        api, order["id"], REOPEN_REASON, sponsor_headers
    )

    assert reopened["status"] == "REOPENED"
    assert reopened["reopen_count"] == 1
    assert reopened["completed_at"] is None
    assert reopened["assigned_tech_user_id"] is None
    asserts.assert_instant_equals(reopened["first_response_at"], LEAK_REPORT_CLOCK)
    asserts.assert_instant_equals(
        reopened["completion_due_at"], URGENT_COMPLETION_DUE_AT
    )

    reassigned = fx.assign_work_order(api, order["id"], MAINTENANCE_TECH_USER_ID_2)

    assert reassigned["status"] == "ASSIGNED"
    assert reassigned["assigned_tech_user_id"] == MAINTENANCE_TECH_USER_ID_2
    asserts.assert_instant_equals(reassigned["first_response_at"], LEAK_REPORT_CLOCK)
    asserts.assert_instant_equals(
        reassigned["completion_due_at"], URGENT_COMPLETION_DUE_AT
    )


CEILING_SYMPTOMS = "Black spotting on the master bedroom ceiling"
VOID_REASON = "Reported in error"
LODGING_WINDOW = {
    "start_date": "2026-09-02",
    "end_date": "2026-09-05",
    "nightly_rate_cents": 31000,
    "occupants_count": 5,
}


def test_a_reported_hazard_case_admits_neither_void_nor_lodging_nor_clearance(api):
    """Two of the three refusals are transition errors; the lodging is a gate.

    PRD: "It carries a `void_reason` and is available from `ASSESSED`, `REMEDIATION_IN_PROGRESS`, `DISPLACEMENT_ACTIVE` or `CLEARANCE_PENDING`, driving the case to `VOIDED`, which is terminal."

    Design: Corner/state_machines/a_reported_hazard_case_admits_neither_void_nor_lodging_nor_clearance
    """
    state = fx.setup_occupied_lease(api)
    sponsor_headers = make_service_member_headers(state["sponsor"]["id"])
    hazard = fx.report_hazard(
        api,
        state["unit"]["id"],
        headers=sponsor_headers,
        lease_id=state["lease"]["id"],
        hazard_type="MOLD",
        reported_symptoms=CEILING_SYMPTOMS,
    )
    assert hazard["status"] == "REPORTED"

    validate_error(
        api.void_hazard_case(
            hazard["id"], f.void_hazard_case_payload(VOID_REASON), ADMIN
        ),
        ApiErrorId.ERR_INVALID_STATE_TRANSITION,
        409,
    )
    validate_error(
        api.create_displacement_lodging(
            f.create_displacement_lodging_payload(
                hazard["id"], state["lease"]["id"], **LODGING_WINDOW
            ),
            MANAGER,
        ),
        ApiErrorId.ERR_HAZARD_NOT_ASSESSED,
        409,
    )
    # Clearance is a transition on the case, so rung 19 answers first.
    validate_error(
        api.certify_clearance(hazard["id"], f.clearance_payload(True), SPECIALIST),
        ApiErrorId.ERR_INVALID_STATE_TRANSITION,
        409,
    )

    after = fx.read_hazard_case(api, hazard["id"])
    asserts.assert_hazard_case(after)
    assert after["status"] == "REPORTED"
    assert after["version"] == 1
    assert after["assessment_severity"] is None
    assert after["remediation_work_order_id"] is None
    assert after["displacement_required"] is False
    _, lodging_meta = validate_paginated(
        api.list_displacement_lodgings(MANAGER, params={"hazard_case_id": hazard["id"]})
    )
    assert lodging_meta["total_count"] == 0
    assert fx.read_housing_unit(api, state["unit"]["id"])["status"] == "OCCUPIED"
    assert fx.read_lease(api, state["lease"]["id"])["allotment_status"] == "ACTIVE"
