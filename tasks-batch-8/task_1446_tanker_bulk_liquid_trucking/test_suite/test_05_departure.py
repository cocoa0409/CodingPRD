"""Departure gating claims: weights, placards, and the approved spill plan."""
import pytest

from test_helpers import (
    TEST_USERS,
    confirm_placards,
    create_approved_spill_plan,
    record_weights,
    setup_loaded_shipment,
    validate_error,
    validate_success,
)

DISP = TEST_USERS["dispatcher_headers"]


def test_depart_gates_layered(api):
    """PRD 3.4: "Three gates must all hold: weights verified (`weights_verified_at`
    set, else `ERR_WEIGHTS_NOT_VERIFIED`), placards confirmed (`placards_confirmed`
    true, else `ERR_PLACARDS_NOT_CONFIRMED`), and an APPROVED SpillResponsePlan
    existing for the shipment's (`customer_id`, `product_id`) pair whose `expires_at`
    is later than the logical clock — a missing, unapproved, suspended, or expired
    plan means `ERR_SPILL_PLAN_NOT_APPROVED`."

    Design: Corner/validations/depart_gates_layered
    """
    # LOADED via close-meter; no weights, no placards, no spill plan.
    scenario = setup_loaded_shipment(weigh=False, placard=False)

    res = api.depart_shipment(scenario["ship"]["id"], DISP)
    validate_error(res, "ERR_WEIGHTS_NOT_VERIFIED", expected_status=409)

    record_weights(scenario)
    res = api.depart_shipment(scenario["ship"]["id"], DISP)
    validate_error(res, "ERR_PLACARDS_NOT_CONFIRMED", expected_status=409)

    confirm_placards(scenario)
    res = api.depart_shipment(scenario["ship"]["id"], DISP)
    validate_error(res, "ERR_SPILL_PLAN_NOT_APPROVED", expected_status=422)


def test_depart_succeeds_when_all_gates_hold(api):
    """PRD 3.4: "Departure is the `Dispatcher`'s act and moves the shipment
    `LOADED → IN_TRANSIT`. Three gates must all hold: weights verified
    (`weights_verified_at` set, else `ERR_WEIGHTS_NOT_VERIFIED`), placards confirmed
    (`placards_confirmed` true, else `ERR_PLACARDS_NOT_CONFIRMED`), and an APPROVED
    SpillResponsePlan existing for the shipment's (`customer_id`, `product_id`) pair".

    Design: Corner/validations/depart_gates_layered
    """
    scenario = setup_loaded_shipment(weigh=True, placard=True)
    create_approved_spill_plan(scenario["cust"]["id"], scenario["prod"]["id"])
    departed = validate_success(api.depart_shipment(scenario["ship"]["id"], DISP), 200)
    assert departed["status"] == "IN_TRANSIT"
