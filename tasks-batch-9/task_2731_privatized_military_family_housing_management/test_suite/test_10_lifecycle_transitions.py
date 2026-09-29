"""Declared edges, birth states, terminal lockdown and replayed triggers."""

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
from test_helpers.test_users import TEST_USERS, make_service_member_headers

STARTUP_CLOCK = const.CLOCK_STARTUP_DEFAULT
ADMIN = TEST_USERS["platform_admin_headers"]
MANAGER = TEST_USERS["property_manager_headers"]
TECH = TEST_USERS["maintenance_tech_headers"]
HOUSING_OFFICE = TEST_USERS["installation_housing_office_headers"]

TWO_TOWNHOMES = (
    {"unit_code": "A-101"},
    {"unit_code": "A-102"},
)


def _two_available_units(api):
    """One installation, two identical AVAILABLE townhomes, nothing else."""
    return fx.setup_multi_unit_installation(api, TWO_TOWNHOMES, clock=STARTUP_CLOCK)


def _drive_status(api, unit_id, status, headers, **overrides):
    return validate_success(
        api.set_housing_unit_status(
            unit_id, f.housing_unit_status_payload(status, **overrides), headers
        )
    )


def test_the_offline_maintenance_round_trip_moves_only_two_counters(api):
    """Out of the pool and back again, one version bump and two counters a hop.

    PRD: "`AVAILABLE → OFFLINE_MAINTENANCE` takes a unit out of the offer pool for planned work, and `OFFLINE_MAINTENANCE → AVAILABLE` puts it back; each edge recomputes `available_unit_count` and `offline_unit_count` and raises the unit's `version` by 1."

    Design: Corner/state_machines/unit_offline_maintenance_round_trip_moves_only_two_counters
    """
    state = _two_available_units(api)
    first_unit, second_unit = state["units"]

    offline = _drive_status(api, first_unit["id"], "OFFLINE_MAINTENANCE", MANAGER)

    assert offline["status"] == "OFFLINE_MAINTENANCE"
    assert offline["version"] == 2
    mid = fx.read_installation(api, state["installation"]["id"])
    assert mid["available_unit_count"] == 1
    assert mid["offline_unit_count"] == 1
    assert mid["assigned_unit_count"] == 0
    assert mid["occupied_unit_count"] == 0
    assert mid["hazard_hold_unit_count"] == 0
    assert mid["total_unit_count"] == 2
    asserts.assert_installation_counter_conservation(mid)

    back = _drive_status(api, first_unit["id"], "AVAILABLE", ADMIN)

    assert back["status"] == "AVAILABLE"
    assert back["version"] == 3
    assert back["hazard_hold_reason"] is None
    after = fx.read_installation(api, state["installation"]["id"])
    assert after["available_unit_count"] == 2
    assert after["offline_unit_count"] == 0
    asserts.assert_installation_counter_conservation(after)
    untouched = fx.read_housing_unit(api, second_unit["id"])
    assert untouched["status"] == "AVAILABLE"
    assert untouched["version"] == 1


SECOND_UNIT_CODE = "A-102"
SECOND_SPONSOR = {
    "dodid": "1000000003",
    "last_name": "Vance",
    "first_name": "Iris",
    "pay_grade": "E5",
}
SECOND_APPLICATION = {
    "pcs_orders_date": "2026-08-20",
    "expected_arrival_date": "2026-10-01",
}
APPLIANCE_DESCRIPTION = "Dishwasher door latch will not catch"
MOLD_SYMPTOMS = "Musty smell in the hall bathroom"


def test_newly_created_rows_start_in_their_declared_initial_states(api):
    """Six machines observed at birth in one chain, none of them nudging another.

    PRD: "The inspection is created in `status` `SCHEDULED` with `deficiency_count` and `critical_open_count` both 0, an empty deficiency list, and `tenant_signature_name`, `tenant_signature_at` and `bill_of_rights_version_ack` all null."

    Design: Corner/state_machines/newly_created_rows_start_in_their_declared_initial_states
    """
    state = fx.setup_lease_pending_move_in(api)
    lease = fx.read_lease(api, state["lease"]["id"])
    assert lease["occupancy_status"] == "PENDING_MOVE_IN"
    assert lease["allotment_status"] == "NOT_STARTED"

    inspection = validate_success(
        api.create_move_in_inspection(
            f.create_move_in_inspection_payload(lease["id"]), MANAGER
        ),
        201,
    )
    assert inspection["status"] == "SCHEDULED"
    assert inspection["deficiency_count"] == 0
    assert inspection["critical_open_count"] == 0

    order = validate_success(
        api.create_work_order(
            f.create_work_order_payload(
                state["unit"]["id"],
                category="APPLIANCE",
                description=APPLIANCE_DESCRIPTION,
            ),
            MANAGER,
        ),
        201,
    )
    assert order["status"] == "SUBMITTED"
    assert order["escalation_level"] == 0
    assert order["reopen_count"] == 0

    hazard = validate_success(
        api.create_hazard_case(
            f.create_hazard_case_payload(
                state["unit"]["id"],
                hazard_type="MOLD",
                reported_symptoms=MOLD_SYMPTOMS,
            ),
            MANAGER,
        ),
        201,
    )
    assert hazard["status"] == "REPORTED"
    assert hazard["assessment_severity"] is None
    assert hazard["remediation_work_order_id"] is None

    fresh_unit = fx.create_housing_unit(
        api, state["installation"]["id"], unit_code=SECOND_UNIT_CODE
    )
    assert fx.read_housing_unit(api, fresh_unit["id"])["status"] == "AVAILABLE"

    other_sponsor, _ = fx.setup_sponsor_family(api, **SECOND_SPONSOR)
    second_application = fx.submit_application(
        api, state["installation"]["id"], other_sponsor, **SECOND_APPLICATION
    )
    assert second_application["status"] == "PENDING"
    assert second_application["decline_count"] == 0
    assert second_application["offer_count"] == 0

    # Reporting a hazard is not yet a finding: the leased unit never moved.
    assert fx.read_housing_unit(api, state["unit"]["id"])["status"] == "ASSIGNED"
    assert fx.read_lease(api, lease["id"])["allotment_status"] == "NOT_STARTED"


SINGLE_DECLINE_INSTALLATION = {"decline_limit": 1}
CONTROL_DATE = "2026-08-25"


def _application_expired_by_one_decline(api):
    """A decline budget of one, spent, so the application expires outright."""
    base = fx.setup_installation_with_unit(
        api, installation_overrides=SINGLE_DECLINE_INSTALLATION
    )
    sponsor, _ = fx.setup_sponsor_family(api)
    application = fx.submit_application(api, base["installation"]["id"], sponsor)
    fx.run_offer_run(api, base["installation"]["id"])
    base["sponsor"] = sponsor
    base["application"] = fx.decline_offer(api, application["id"], sponsor)
    return base


def test_the_expired_application_is_locked_and_refuses_every_offer_verb(api):
    """Terminal beats stale: even a correct version token cannot reopen it.

    PRD: "Rung 20 requires that the primary target not already be in a terminal state, failing with `ERR_TERMINAL_STATE_LOCKED` (409); the terminal states are `HOUSED` and `EXPIRED` for a waitlist application, `TERMINATED` for a lease's occupancy dimension and `CLOSED` for its allotment dimension, `COMPLETED` for a move-in inspection, `CLOSED` for a work order, `CLOSED` and `VOIDED` for a hazard case, `CLOSED` for a displacement lodging, and `CLOSED_RESOLVED` for a dispute case."

    Design: Corner/state_machines/expired_application_is_locked_and_refuses_every_offer_verb
    """
    state = _application_expired_by_one_decline(api)
    sponsor_headers = make_service_member_headers(state["sponsor"]["id"])
    expired = fx.read_application(api, state["application"]["id"])
    assert expired["status"] == "EXPIRED"
    assert expired["decline_count"] == 1
    # The penalty repositions a returning application; this one never returned.
    assert expired["effective_control_date"] == CONTROL_DATE
    # A decline clears both offer handles "in every case", expiry included.
    assert expired["offered_unit_id"] is None
    assert expired["offer_expires_at"] is None
    locked_version = expired["version"]

    validate_error(
        api.accept_offer(expired["id"], sponsor_headers),
        ApiErrorId.ERR_TERMINAL_STATE_LOCKED,
        409,
    )
    validate_error(
        api.decline_offer(expired["id"], sponsor_headers),
        ApiErrorId.ERR_TERMINAL_STATE_LOCKED,
        409,
    )
    validate_error(
        api.recertify_waitlist_application(
            expired["id"], f.recertify_payload(locked_version), HOUSING_OFFICE
        ),
        ApiErrorId.ERR_TERMINAL_STATE_LOCKED,
        409,
    )

    assert fx.read_housing_unit(api, state["unit"]["id"])["status"] == "AVAILABLE"
    assert fx.read_application(api, expired["id"])["version"] == locked_version


RANGE_HOOD_DESCRIPTION = "Range hood fan rattles"
EMPTY_COMPLETION_NOTE = {"completion_note": "Nothing done"}
STILL_RATTLING = "Still rattling"


def _submitted_work_order_on_a_vacant_unit(api):
    """One order sitting in SUBMITTED at version 1, never dispatched."""
    base = fx.setup_multi_unit_installation(
        api, ({"unit_code": "A-101"},), clock=STARTUP_CLOCK
    )
    unit = base["units"][0]
    order = fx.submit_work_order(
        api,
        unit["id"],
        category="APPLIANCE",
        description=RANGE_HOOD_DESCRIPTION,
    )
    assert order["status"] == "SUBMITTED"
    assert order["version"] == 1
    return order


def test_a_submitted_work_order_refuses_every_undeclared_trigger(api):
    """Start, complete and reopen are not edges out of SUBMITTED.

    PRD: "Rung 19 requires that the requested transition be declared in this document for the current state of the request's **primary** target resource, failing with `ERR_INVALID_STATE_TRANSITION` (409); it applies to every action endpoint that drives a state machine."

    Design: Corner/state_machines/submitted_work_order_refuses_every_undeclared_trigger
    """
    order = _submitted_work_order_on_a_vacant_unit(api)

    validate_error(
        api.start_work_order(order["id"], TECH),
        ApiErrorId.ERR_INVALID_STATE_TRANSITION,
        409,
    )
    validate_error(
        api.complete_work_order(order["id"], TECH, EMPTY_COMPLETION_NOTE),
        ApiErrorId.ERR_INVALID_STATE_TRANSITION,
        409,
    )
    # The state rung runs long before the reopen budget rung.
    validate_error(
        api.reopen_work_order(
            order["id"], f.reopen_work_order_payload(STILL_RATTLING), MANAGER
        ),
        ApiErrorId.ERR_INVALID_STATE_TRANSITION,
        409,
    )

    after = fx.read_work_order(api, order["id"])
    asserts.assert_work_order(after)
    assert after["status"] == "SUBMITTED"
    assert after["version"] == 1
    assert after["assigned_tech_user_id"] is None
    assert after["first_response_at"] is None
    assert after["completed_at"] is None
    assert after["reopen_count"] == 0
    assert after["escalation_level"] == 0


def test_replaying_a_consumed_trigger_repeats_none_of_its_side_effects(api):
    """A second move-in, acceptance and acknowledgment all bounce, changing nothing.

    PRD: "Rung 19 is evaluated **only** when the primary target's current state is not one of that entity's terminal states."

    Design: Corner/state_machines/replaying_a_consumed_trigger_is_refused_without_repeating_its_side_effects
    """
    state = fx.setup_occupied_lease(api)
    sponsor_headers = make_service_member_headers(state["sponsor"]["id"])
    lease_id = state["lease"]["id"]
    before = fx.read_lease(api, lease_id)
    assert before["occupancy_status"] == "OCCUPIED"
    assert before["allotment_status"] == "ACTIVE"

    # OCCUPIED is not terminal, so the replayed move-in is judged at rung 19.
    validate_error(
        api.move_in(lease_id, MANAGER),
        ApiErrorId.ERR_INVALID_STATE_TRANSITION,
        409,
    )
    # HOUSED and COMPLETED are terminal, so these two fall through to rung 20.
    validate_error(
        api.accept_offer(state["application"]["id"], sponsor_headers),
        ApiErrorId.ERR_TERMINAL_STATE_LOCKED,
        409,
    )
    validate_error(
        api.tenant_acknowledge(
            state["inspection"]["id"],
            f.tenant_acknowledge_payload(
                f"{state['sponsor']['first_name']} {state['sponsor']['last_name']}",
                state["installation"]["bill_of_rights_version"],
            ),
            sponsor_headers,
        ),
        ApiErrorId.ERR_TERMINAL_STATE_LOCKED,
        409,
    )

    after = fx.read_lease(api, lease_id)
    assert after["version"] == before["version"]
    assert after["gross_rent_cents"] == before["gross_rent_cents"]
    assert after["gross_rent_cents"] == const.BASE_GROSS_RENT_CENTS
    assert after["allotment_status"] == "ACTIVE"
    _, ledger_meta = validate_paginated(
        api.list_lease_allotment_transactions(lease_id, MANAGER)
    )
    assert ledger_meta["total_count"] == 0
    installation = fx.read_installation(api, state["installation"]["id"])
    assert installation["occupied_unit_count"] == 1
    asserts.assert_installation_counter_conservation(installation)
