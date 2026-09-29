"""Bulk writes, derived reads, forked actions and the addressed error codes."""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
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
    ENVIRONMENTAL_SPECIALIST_USER_ID,
    ENVIRONMENTAL_SPECIALIST_USER_ID_2,
    MAINTENANCE_TECH_USER_ID,
    TEST_USERS,
    make_service_member_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
MANAGER = TEST_USERS["property_manager_headers"]
TECH = TEST_USERS["maintenance_tech_headers"]
SPECIALIST = TEST_USERS["environmental_specialist_headers"]
SPECIALIST_2 = TEST_USERS["environmental_specialist_2_headers"]

INSPECTION_DATE = "2026-08-31"
WALKTHROUGH_CLOCK = "2026-08-31T10:00:00Z"
WALKTHROUGH_FINDINGS = (
    ("NO_HEAT", "LIVING_ROOM", "HABITABILITY_CRITICAL"),
    ("PLUMBING_LEAK", "KITCHEN", "HABITABILITY_CRITICAL"),
    ("COSMETIC", "BEDROOM_2", "COSMETIC"),
)


def test_one_deficiency_call_appends_the_whole_walkthrough_list(api):
    """Three entries in one body, two counts recomputed over them, no work order.

    PRD: "Logging recomputes `deficiency_count`, which is simply the length of the deficiency list, and `critical_open_count`, which is the number of entries whose `severity` is `HABITABILITY_CRITICAL` and whose entry status is anything other than `RESOLVED`."

    Design: Corner/endpoints/one_deficiency_call_appends_the_whole_walkthrough_list
    """
    state = fx.setup_lease_pending_move_in(api)
    inspection = fx.schedule_inspection(
        api, state["lease"]["id"], scheduled_date=INSPECTION_DATE
    )
    assert inspection["deficiency_count"] == 0
    assert inspection["critical_open_count"] == 0
    fx.set_clock(api, WALKTHROUGH_CLOCK)

    logged = validate_success(
        api.log_deficiencies(
            inspection["id"],
            f.log_deficiencies_payload(
                [f.deficiency_entry(*finding) for finding in WALKTHROUGH_FINDINGS]
            ),
            MANAGER,
        )
    )

    assert logged["status"] == "DEFICIENCIES_LOGGED"
    assert logged["deficiency_count"] == 3
    # Only the two HABITABILITY_CRITICAL entries count toward the move-in blocker.
    assert logged["critical_open_count"] == 2
    entries = logged["deficiencies"]
    assert entries[0]["status"] == "OPEN"
    assert entries[0]["work_order_id"] is None
    assert entries[2]["severity"] == "COSMETIC"

    _, order_meta = validate_paginated(
        api.list_work_orders(MANAGER, params={"housing_unit_id": state["unit"]["id"]})
    )
    assert order_meta["total_count"] == 0

    reread = validate_success(
        api.get_move_in_inspection(
            inspection["id"], make_service_member_headers(state["sponsor"]["id"])
        )
    )
    assert reread["deficiency_count"] == 3
    assert reread["critical_open_count"] == 2


MOVE_IN_CLOCK = fx.CLOCK_AT_MOVE_IN
NO_HEAT_DESCRIPTION = "Furnace will not ignite"
HVAC_DESCRIPTION = "Air handler is noisy"
COSMETIC_DESCRIPTION = "Scuffed hallway paint"
EMERGENCY_RESPONSE_DUE_AT = "2026-09-01T13:00:00Z"
EMERGENCY_COMPLETION_DUE_AT = "2026-09-02T09:00:00Z"
URGENT_RESPONSE_DUE_AT = "2026-09-02T09:00:00Z"
URGENT_COMPLETION_DUE_AT = "2026-09-04T09:00:00Z"
ROUTINE_RESPONSE_DUE_AT = "2026-09-06T09:00:00Z"
ROUTINE_COMPLETION_DUE_AT = "2026-10-01T09:00:00Z"


def test_the_work_order_read_returns_the_sla_clocks_the_write_derived(api):
    """One instant, one flag, three categories, three classes and six deadlines.

    PRD: "The stored `response_due_at` and `completion_due_at` are `reported_at` plus those hour counts."

    Design: Corner/endpoints/the_work_order_read_returns_the_sla_clocks_the_write_derived
    """
    state = fx.setup_occupied_lease(api)
    unit_id = state["unit"]["id"]
    lease_id = state["lease"]["id"]
    submissions = (
        ("NO_HEAT", NO_HEAT_DESCRIPTION),
        ("HVAC", HVAC_DESCRIPTION),
        ("COSMETIC", COSMETIC_DESCRIPTION),
    )
    emergency, urgent, routine = [
        fx.submit_work_order(
            api,
            unit_id,
            lease_id=lease_id,
            category=category,
            description=description,
            habitability_impact=False,
        )
        for category, description in submissions
    ]

    emergency_read = validate_success(api.get_work_order(emergency["id"], TECH))
    urgent_read = validate_success(api.get_work_order(urgent["id"], TECH))
    routine_read = validate_success(api.get_work_order(routine["id"], TECH))

    assert emergency_read["priority_class"] == "EMERGENCY"
    asserts.assert_instant_equals(
        emergency_read["response_due_at"], EMERGENCY_RESPONSE_DUE_AT
    )
    asserts.assert_instant_equals(
        emergency_read["completion_due_at"], EMERGENCY_COMPLETION_DUE_AT
    )
    asserts.assert_instant_equals(emergency_read["reported_at"], MOVE_IN_CLOCK)
    assert emergency_read["sla_breached"] is False
    assert emergency_read["escalation_level"] == 0
    assert emergency_read["status"] == "SUBMITTED"
    asserts.assert_work_order(emergency_read)

    assert urgent_read["priority_class"] == "URGENT"
    asserts.assert_instant_equals(
        urgent_read["response_due_at"], URGENT_RESPONSE_DUE_AT
    )
    asserts.assert_instant_equals(
        urgent_read["completion_due_at"], URGENT_COMPLETION_DUE_AT
    )
    # No assignment has stamped a first response.
    assert urgent_read["first_response_at"] is None

    assert routine_read["priority_class"] == "ROUTINE"
    asserts.assert_instant_equals(
        routine_read["response_due_at"], ROUTINE_RESPONSE_DUE_AT
    )
    asserts.assert_instant_equals(
        routine_read["completion_due_at"], ROUTINE_COMPLETION_DUE_AT
    )
    assert routine_read["reopen_count"] == 0

    filtered, filtered_meta = validate_paginated(
        api.list_work_orders(
            MANAGER, params={"housing_unit_id": unit_id, "priority_class": "URGENT"}
        )
    )
    # The filter reads the derived class, not the submitted category.
    assert filtered_meta["total_count"] == 1
    assert filtered[0]["id"] == urgent["id"]


CEILING_SYMPTOMS = "Spotting on the bathroom ceiling"
LOWEST_SEVERITY_AREA = {"affected_area_sqft": 10}
SECOND_REMEDIATION_NOTE = {"completion_note": "Cavity opened and remediated"}


def test_one_boolean_on_the_clearance_call_forks_the_case_two_ways(api):
    """A failed test mints a chained follow-on order; a passed one closes the case.

    PRD: "On a **fail**, `clearance_test_passed` is stamped false, `cleared_by_user_id` is cleared, the case cycles back `CLEARANCE_PENDING → REMEDIATION_IN_PROGRESS`, a follow-on work order is created with its `parent_work_order_id` pointing at the old remediation order and `remediation_work_order_id` repointed to the new one, the unit stays in `HAZARD_HOLD` when the case had displaced the household, and the case's `version` is incremented by 1."

    Design: Corner/endpoints/one_boolean_on_the_clearance_call_forks_the_case_two_ways
    """
    state = fx.setup_assessed_hazard(
        api,
        report_overrides={"reported_symptoms": CEILING_SYMPTOMS},
        assess_overrides=LOWEST_SEVERITY_AREA,
    )
    hazard = state["hazard_case"]
    assert hazard["assessment_severity"] == "SEVERITY_1"
    assert hazard["displacement_required"] is False
    assert hazard["assessed_by_user_id"] == ENVIRONMENTAL_SPECIALIST_USER_ID
    first_order_id = hazard["remediation_work_order_id"]
    fx.complete_remediation(api, hazard)
    assert fx.read_hazard_case(api, hazard["id"])["status"] == "CLEARANCE_PENDING"

    failed = validate_success(
        api.certify_clearance(hazard["id"], f.clearance_payload(False), SPECIALIST_2)
    )

    assert failed["status"] == "REMEDIATION_IN_PROGRESS"
    assert failed["clearance_test_passed"] is False
    assert failed["cleared_by_user_id"] is None
    second_order_id = failed["remediation_work_order_id"]
    assert second_order_id != first_order_id

    children, children_meta = validate_paginated(
        api.list_work_orders(MANAGER, params={"parent_work_order_id": first_order_id})
    )
    assert children_meta["total_count"] == 1
    assert children[0]["id"] == second_order_id
    assert children[0]["housing_unit_id"] == state["unit"]["id"]
    # This case never displaced the family, so the failed test moves no unit.
    assert fx.read_housing_unit(api, state["unit"]["id"])["status"] == "OCCUPIED"

    fx.assign_work_order(api, second_order_id, MAINTENANCE_TECH_USER_ID)
    fx.start_work_order(api, second_order_id)
    validate_success(
        api.complete_work_order(second_order_id, TECH, SECOND_REMEDIATION_NOTE)
    )
    assert fx.read_hazard_case(api, hazard["id"])["status"] == "CLEARANCE_PENDING"

    # Certifying is not the assessor's to do.
    validate_error(
        api.certify_clearance(hazard["id"], f.clearance_payload(True), SPECIALIST),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
        403,
    )

    passed = validate_success(
        api.certify_clearance(hazard["id"], f.clearance_payload(True), SPECIALIST_2)
    )

    assert passed["status"] == "CLOSED"
    assert passed["clearance_test_passed"] is True
    assert passed["cleared_by_user_id"] == ENVIRONMENTAL_SPECIALIST_USER_ID_2


ADDRESSED_ENTITY_READS = (
    ("get_installation", ApiErrorId.ERR_INSTALLATION_NOT_FOUND),
    ("get_housing_unit", ApiErrorId.ERR_HOUSING_UNIT_NOT_FOUND),
    ("get_service_member", ApiErrorId.ERR_SERVICE_MEMBER_NOT_FOUND),
    ("get_waitlist_application", ApiErrorId.ERR_APPLICATION_NOT_FOUND),
    ("get_lease", ApiErrorId.ERR_LEASE_NOT_FOUND),
    ("get_move_in_inspection", ApiErrorId.ERR_INSPECTION_NOT_FOUND),
    ("get_work_order", ApiErrorId.ERR_WORK_ORDER_NOT_FOUND),
    ("get_hazard_case", ApiErrorId.ERR_HAZARD_CASE_NOT_FOUND),
    ("get_displacement_lodging", ApiErrorId.ERR_LODGING_NOT_FOUND),
    ("get_dispute_case", ApiErrorId.ERR_DISPUTE_NOT_FOUND),
    ("get_reinvestment_account", ApiErrorId.ERR_ACCOUNT_NOT_FOUND),
)


def test_each_addressed_entity_has_its_own_not_found_code(api):
    """Eleven unknown ids, eleven different codes, all of them 404.

    PRD: "Rung 5 requires the addressed `Installation` to exist and covers installation reads, the installation's BAH rate listing, the waitlist offer run, the allotment run, and any request body carrying `installation_id`; failure is `ERR_INSTALLATION_NOT_FOUND` (404)."

    Design: Corner/errors/each_addressed_entity_has_its_own_not_found_code
    """
    fx.set_clock(api, const.CLOCK_STARTUP_DEFAULT)
    installation = fx.create_installation(api)
    unit = fx.create_housing_unit(api, installation["id"])

    for method_name, expected_error in ADDRESSED_ENTITY_READS:
        read = getattr(api, method_name)
        validate_error(read(NON_EXISTENT_UUID, ADMIN), expected_error, 404)

    # The two live rows in the same database prove the reads themselves work.
    assert validate_success(api.get_installation(installation["id"], ADMIN))["id"] == (
        installation["id"]
    )
    assert validate_success(api.get_housing_unit(unit["id"], ADMIN))["id"] == unit["id"]


OFFER_RUN_CLOCK = fx.CLOCK_BEFORE_ARRIVAL
OFFER_EXPIRES_AT = "2026-08-28T00:00:00Z"
ONE_SECOND_LATE_CLOCK = "2026-08-28T00:00:01Z"


def test_the_offer_window_closes_one_second_after_it_expires(api):
    """One second late is refused; standing exactly on the deadline is accepted.

    PRD: "Acceptance is permitted while the logical clock is at or before `offer_expires_at`; acceptance landing exactly on `offer_expires_at` is allowed, and one instant later it is refused with `ERR_OFFER_WINDOW_CLOSED`."

    Design: Corner/errors/the_offer_window_closes_one_second_after_it_expires
    """
    base = fx.setup_installation_with_unit(api, clock=OFFER_RUN_CLOCK)
    sponsor, _ = fx.setup_sponsor_family(api)
    application = fx.submit_application(api, base["installation"]["id"], sponsor)
    fx.run_offer_run(api, base["installation"]["id"])
    offered = fx.read_application(api, application["id"])
    sponsor_headers = make_service_member_headers(sponsor["id"])
    assert offered["status"] == "OFFERED"
    # Seventy-two hours after the run that made the offer.
    asserts.assert_instant_equals(offered["offer_expires_at"], OFFER_EXPIRES_AT)

    fx.set_clock(api, ONE_SECOND_LATE_CLOCK)
    validate_error(
        api.accept_offer(application["id"], sponsor_headers),
        ApiErrorId.ERR_OFFER_WINDOW_CLOSED,
        409,
    )

    fx.set_clock(api, OFFER_EXPIRES_AT)
    accepted = validate_success(api.accept_offer(application["id"], sponsor_headers))

    assert accepted["status"] == "ACCEPTED"
    assert accepted["offered_unit_id"] == base["unit"]["id"]
    # The unit stays reserved for this sponsor until the lease is written.
    assert fx.read_housing_unit(api, base["unit"]["id"])["status"] == "ASSIGNED"


MOLD_INVESTIGATION_HOLD = {"hazard_hold_reason": "MOLD_INVESTIGATION"}


def test_a_hazard_hold_blocks_the_move_in_after_the_inspection_gate_passes(api):
    """Signing the walkthrough clears rung 24 and exposes the habitability rung.

    PRD: "Rung 29 requires that the housing unit not be in `HAZARD_HOLD`, because a unit under an environmental hazard hold may neither be leased nor moved into; it guards exactly two operations, lease creation and move-in, failing with `ERR_HAZARD_HOLD_ACTIVE` (409)."

    Design: Corner/errors/a_hazard_hold_blocks_the_move_in_after_the_inspection_gate_passes
    """
    state = fx.setup_lease_pending_move_in(api)
    lease_id = state["lease"]["id"]
    sponsor = state["sponsor"]
    inspection = fx.schedule_inspection(api, lease_id, scheduled_date=INSPECTION_DATE)
    fx.set_clock(api, MOVE_IN_CLOCK)
    held = validate_success(
        api.set_housing_unit_status(
            state["unit"]["id"],
            f.housing_unit_status_payload("HAZARD_HOLD", **MOLD_INVESTIGATION_HOLD),
            MANAGER,
        )
    )
    assert held["status"] == "HAZARD_HOLD"

    # Rung 24 answers first, while the walkthrough is unsigned.
    validate_error(
        api.move_in(lease_id, MANAGER),
        ApiErrorId.ERR_INSPECTION_NOT_ACKNOWLEDGED,
        409,
    )

    fx.acknowledge_inspection(
        api,
        inspection["id"],
        sponsor,
        f"{sponsor['first_name']} {sponsor['last_name']}",
        state["installation"]["bill_of_rights_version"],
    )

    validate_error(
        api.move_in(lease_id, MANAGER),
        ApiErrorId.ERR_HAZARD_HOLD_ACTIVE,
        409,
    )

    lease = fx.read_lease(api, lease_id)
    assert lease["occupancy_status"] == "PENDING_MOVE_IN"
    assert lease["allotment_status"] == "NOT_STARTED"
    assert lease["rent_basis"] == "OFFER_PROVISIONAL"
    installation = fx.read_installation(api, state["installation"]["id"])
    assert installation["hazard_hold_unit_count"] == 1
    assert installation["occupied_unit_count"] == 0


SPARE_UNIT_CODE = "A-102"
BURNER_DESCRIPTION = "Range burner is dead"
MUSTY_SYMPTOMS = "Musty smell reported"


def test_a_lease_and_a_unit_that_are_not_the_same_tenancy_are_refused(api):
    """One mismatched pair refused on two creation endpoints, then both accepted.

    PRD: "Rung 32 requires a supplied `lease_id` and `housing_unit_id` to agree, meaning the lease must be that unit's current non-`TERMINATED` lease; it guards work-order submission, hazard-case reporting and lodging authorisation, failing with `ERR_LEASE_UNIT_MISMATCH` (422)."

    Design: Corner/errors/a_lease_and_a_unit_that_are_not_the_same_tenancy_are_refused
    """
    state = fx.setup_occupied_lease(api)
    lease_id = state["lease"]["id"]
    spare_unit = fx.create_housing_unit(
        api, state["installation"]["id"], unit_code=SPARE_UNIT_CODE
    )
    assert spare_unit["status"] == "AVAILABLE"

    validate_error(
        api.create_work_order(
            f.create_work_order_payload(
                spare_unit["id"],
                lease_id=lease_id,
                category="APPLIANCE",
                description=BURNER_DESCRIPTION,
            ),
            MANAGER,
        ),
        ApiErrorId.ERR_LEASE_UNIT_MISMATCH,
        422,
    )
    # The same rung guards both creation endpoints.
    validate_error(
        api.create_hazard_case(
            f.create_hazard_case_payload(
                spare_unit["id"], lease_id=lease_id, reported_symptoms=MUSTY_SYMPTOMS
            ),
            MANAGER,
        ),
        ApiErrorId.ERR_LEASE_UNIT_MISMATCH,
        422,
    )

    order = validate_success(
        api.create_work_order(
            f.create_work_order_payload(
                state["unit"]["id"],
                lease_id=lease_id,
                category="APPLIANCE",
                description=BURNER_DESCRIPTION,
            ),
            MANAGER,
        ),
        201,
    )
    hazard = validate_success(
        api.create_hazard_case(
            f.create_hazard_case_payload(
                state["unit"]["id"],
                lease_id=lease_id,
                reported_symptoms=MUSTY_SYMPTOMS,
            ),
            MANAGER,
        ),
        201,
    )

    assert order["housing_unit_id"] == state["unit"]["id"]
    assert hazard["status"] == "REPORTED"


PAINT_MISMATCH = "Paint does not match"
STILL_MISMATCHED = "Still does not match"
OFFICE_ESCALATION = "Resident escalated to the office"


def test_the_reopen_budget_is_scoped_to_the_acting_role(api):
    """The same order in the same state is out of budget for one actor and in for the other.

    PRD: "Rung 28 requires the work order's `reopen_count` to be below the reopen budget of the requesting actor — below 1 when the actor is a `ServiceMember`, below 2 when the actor is a `PropertyManager` — and guards work-order reopen, failing with `ERR_REOPEN_LIMIT_REACHED` (409)."

    Design: Corner/errors/the_reopen_budget_is_scoped_to_the_acting_role
    """
    state = fx.setup_occupied_lease(api)
    sponsor_headers = make_service_member_headers(state["sponsor"]["id"])
    order = fx.submit_work_order(
        api,
        state["unit"]["id"],
        headers=sponsor_headers,
        lease_id=state["lease"]["id"],
        category="COSMETIC",
        description=COSMETIC_DESCRIPTION,
    )
    fx.assign_work_order(api, order["id"], MAINTENANCE_TECH_USER_ID)
    fx.start_work_order(api, order["id"])
    fx.complete_work_order(api, order["id"])

    reopened_once = fx.reopen_work_order(
        api, order["id"], PAINT_MISMATCH, sponsor_headers
    )
    assert reopened_once["reopen_count"] == 1
    fx.assign_work_order(api, order["id"], MAINTENANCE_TECH_USER_ID)
    fx.start_work_order(api, order["id"])
    completed_again = fx.complete_work_order(api, order["id"])
    assert completed_again["status"] == "COMPLETED"

    # The resident budget of one is spent.
    validate_error(
        api.reopen_work_order(
            order["id"], f.reopen_work_order_payload(STILL_MISMATCHED), sponsor_headers
        ),
        ApiErrorId.ERR_REOPEN_LIMIT_REACHED,
        409,
    )

    reopened_twice = validate_success(
        api.reopen_work_order(
            order["id"], f.reopen_work_order_payload(OFFICE_ESCALATION), MANAGER
        )
    )

    assert reopened_twice["status"] == "REOPENED"
    assert reopened_twice["reopen_count"] == 2
    assert reopened_twice["completed_at"] is None
    assert reopened_twice["assigned_tech_user_id"] is None


RENT_COMPLAINT = "September rent looks too high"
STANDING_OFFER_CENTS = 25000
CREDIT_REMEDY = "One-time credit for the disputed month"
ZERO_CREDIT_REMEDY = "Written apology and no credit"
NOTICE_DATE = "2026-09-01"
EFFECTIVE_DATE = "2026-10-01"
TERMINATION_CLOCK = "2026-10-01T09:00:00Z"


def test_a_closed_ledger_refuses_a_positive_credit_but_takes_a_zero_one(api):
    """The rung is keyed on the award being positive, not on the case being finished.

    PRD: "Rung 27 requires that a dispute credit greater than zero be awarded only while the lease's `allotment_status` is `ACTIVE` or `SUSPENDED`, since a `CLOSED` ledger accepts no further credit; it guards a resident response with `accepted` true and `credit_offer_cents` greater than 0, and an installation decision with `credit_award_cents` greater than 0, failing with `ERR_ALLOTMENT_NOT_ACTIVE` (409)."

    Design: Corner/errors/a_closed_ledger_refuses_a_positive_credit_but_takes_a_zero_one
    """
    state = fx.setup_occupied_lease(api)
    lease_id = state["lease"]["id"]
    sponsor = state["sponsor"]
    dispute = fx.open_dispute(
        api, lease_id, sponsor, category="RENT_CHARGE", description=RENT_COMPLAINT
    )
    proposed = fx.propose_resolution(
        api, dispute["id"], CREDIT_REMEDY, STANDING_OFFER_CENTS
    )
    assert proposed["round_count"] == 1
    fx.give_termination_notice(api, lease_id, "CONVENIENCE", NOTICE_DATE, EFFECTIVE_DATE)
    # Termination waits for the clock to reach the effective date.
    fx.set_clock(api, TERMINATION_CLOCK)
    terminated = fx.terminate_lease(api, lease_id)
    assert terminated["occupancy_status"] == "TERMINATED"
    assert terminated["allotment_status"] == "CLOSED"
    settled_balance = terminated["allotment_balance_cents"]

    validate_error(
        api.respond_to_proposal(
            dispute["id"],
            f.respond_payload(True),
            make_service_member_headers(sponsor["id"]),
        ),
        ApiErrorId.ERR_ALLOTMENT_NOT_ACTIVE,
        409,
    )

    # round_count was 1, so the rejection returns the case for another round.
    rejected = fx.respond_to_proposal(api, dispute["id"], sponsor, False)
    assert rejected["status"] == "UNDER_REVIEW"
    reproposed = fx.propose_resolution(api, dispute["id"], ZERO_CREDIT_REMEDY, 0)
    assert reproposed["round_count"] == 2

    resolved = fx.respond_to_proposal(api, dispute["id"], sponsor, True)

    assert resolved["status"] == "CLOSED_RESOLVED"
    assert resolved["credit_award_cents"] == 0
    _, refund_meta = validate_paginated(
        api.list_lease_allotment_transactions(lease_id, MANAGER, params={"type": "REFUND"})
    )
    # The zero credit moved no money.
    assert refund_meta["total_count"] == 0
    assert fx.read_lease(api, lease_id)["allotment_balance_cents"] == settled_balance


HOUSING_OFFICE = TEST_USERS["installation_housing_office_headers"]
SETTLED_LEASE_FIELDS = (
    "occupancy_status",
    "allotment_status",
    "rent_basis",
    "gross_rent_cents",
    "net_rent_cents",
    "daily_rent_cents",
    "allotment_balance_cents",
    "version",
)


def test_every_cascade_is_final_in_the_response_that_caused_it(api):
    """Two writes, and after each one the next read is already settled.

    PRD: "When a single request touches several entities, every affected row is updated within that request before the response is emitted; there is no deferred or eventual reconciliation."

    Design: Corner/consistency_model/every_cascade_is_final_in_the_response_that_caused_it
    """
    state = fx.setup_accepted_application(api)
    sponsor = state["sponsor"]
    before = fx.read_installation(api, state["installation"]["id"])
    assert before["available_unit_count"] == 0
    assert before["assigned_unit_count"] == 1
    assert before["occupied_unit_count"] == 0
    assert before["pending_application_count"] == 0

    written = validate_success(
        api.create_lease(
            f.create_lease_payload(state["application"]["id"], state["unit"]["id"]),
            MANAGER,
        ),
        201,
    )

    # The write returns the post-cascade row, not a pre-cascade echo.
    assert written["occupancy_status"] == "PENDING_MOVE_IN"
    assert written["allotment_status"] == "NOT_STARTED"
    assert written["rent_basis"] == "OFFER_PROVISIONAL"
    assert written["gross_rent_cents"] == const.BASE_GROSS_RENT_CENTS
    assert fx.read_application(api, state["application"]["id"])["status"] == "HOUSED"
    # Immediate does not mean indiscriminate: the partial state is itself settled.
    assert fx.read_housing_unit(api, state["unit"]["id"])["status"] == "ASSIGNED"
    mid = fx.read_installation(api, state["installation"]["id"])
    assert mid["assigned_unit_count"] == 1
    assert mid["occupied_unit_count"] == 0
    assert mid["pending_application_count"] == 0

    inspection = fx.schedule_inspection(
        api, written["id"], scheduled_date=INSPECTION_DATE
    )
    fx.acknowledge_inspection(
        api,
        inspection["id"],
        sponsor,
        f"{sponsor['first_name']} {sponsor['last_name']}",
        state["installation"]["bill_of_rights_version"],
    )
    fx.set_clock(api, MOVE_IN_CLOCK)

    moved_in = validate_success(api.move_in(written["id"], MANAGER))

    assert moved_in["occupancy_status"] == "OCCUPIED"
    assert moved_in["allotment_status"] == "ACTIVE"
    assert moved_in["rent_basis"] == "MOVE_IN_FINAL"
    assert moved_in["gross_rent_cents"] == const.BASE_GROSS_RENT_CENTS
    assert moved_in["net_rent_cents"] == const.BASE_NET_RENT_CENTS
    assert moved_in["daily_rent_cents"] == const.BASE_DAILY_RENT_CENTS
    assert moved_in["allotment_balance_cents"] == 0

    reread = validate_success(
        api.get_lease(written["id"], make_service_member_headers(sponsor["id"]))
    )
    # Field for field with the write response: no read-your-writes lag.
    for field in SETTLED_LEASE_FIELDS:
        assert reread[field] == moved_in[field], field

    assert fx.read_housing_unit(api, state["unit"]["id"])["status"] == "OCCUPIED"
    after = fx.read_installation(api, state["installation"]["id"])
    assert after["available_unit_count"] == 0
    assert after["assigned_unit_count"] == 0
    assert after["occupied_unit_count"] == 1
    assert after["total_unit_count"] == 1
    asserts.assert_installation_counter_conservation(after)
    housed = validate_success(
        api.get_waitlist_application(state["application"]["id"], HOUSING_OFFICE)
    )
    # Nothing in the chain was compensated or re-applied later.
    assert housed["status"] == "HOUSED"
    assert fx.read_inspection(api, inspection["id"])["status"] == "COMPLETED"
