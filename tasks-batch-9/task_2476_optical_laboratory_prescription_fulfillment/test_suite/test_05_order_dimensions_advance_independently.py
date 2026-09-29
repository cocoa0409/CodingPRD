"""Production progress and money progress moving on one order row."""

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories as f
from test_helpers import fixtures
from test_helpers.test_users import (
    BENEFITS_A_HEADERS,
    OPTICIAN_A_HEADERS,
    TECHNICIAN_A_HEADERS,
)


def test_benefit_application_moves_the_billing_dimension_and_leaves_production(api):
    """The order is still IN_LAB after the money has been finalised.

    PRD 2.7: "Benefit application, benefit voiding and patient settlement may
    **never** change `fulfillment_status`."

    Design: Difficulty/non_linear_state_machine/rx_order_fulfillment_and_billing_dimensions_advance_independently
    """
    scenario = fixtures.surfaced_passed_job(api)

    before = fixtures.read_order(api, scenario["order_id"])
    assert before["fulfillment_status"] == "IN_LAB"
    assert before["billing_status"] == "PROVISIONAL_QUOTED"

    after = validate_success(api.apply_benefit(scenario["order_id"], BENEFITS_A_HEADERS))
    assert after["fulfillment_status"] == "IN_LAB"
    assert after["billing_status"] == "BENEFIT_APPLIED"


def test_release_moves_the_fulfillment_dimension_and_leaves_the_money(api):
    """Releasing the job advances production without touching billing.

    PRD 2.7: "Layout creation, job creation, occupation booking and execution,
    inspection recording, job release and dispensing may **never** change
    `billing_status`."

    Design: Difficulty/non_linear_state_machine/rx_order_fulfillment_and_billing_dimensions_advance_independently
    """
    scenario = fixtures.surfaced_passed_job(api)
    validate_success(api.apply_benefit(scenario["order_id"], BENEFITS_A_HEADERS))

    job = validate_success(
        api.release_lab_job(scenario["job_id"], TECHNICIAN_A_HEADERS)
    )
    assert job["status"] == "RELEASED"

    order = fixtures.read_order(api, scenario["order_id"])
    assert order["fulfillment_status"] == "LAB_COMPLETE"
    assert order["billing_status"] == "BENEFIT_APPLIED"


def test_settlement_clears_the_balance_without_moving_production_again(api):
    """Paying 41977 lands PATIENT_SETTLED while production stays LAB_COMPLETE.

    PRD 2.7: "An order tracks its production progress in `fulfillment_status` and
    its money progress in `billing_status`, and these two dimensions advance
    independently on the same row."

    Design: Difficulty/non_linear_state_machine/rx_order_fulfillment_and_billing_dimensions_advance_independently
    """
    scenario = fixtures.surfaced_passed_job(api)
    validate_success(api.apply_benefit(scenario["order_id"], BENEFITS_A_HEADERS))
    validate_success(api.release_lab_job(scenario["job_id"], TECHNICIAN_A_HEADERS))

    order = validate_success(
        api.settle_patient_portion(
            scenario["order_id"], f.create_settlement_payload(41977), OPTICIAN_A_HEADERS
        )
    )

    assert order["fulfillment_status"] == "LAB_COMPLETE"
    assert order["billing_status"] == "PATIENT_SETTLED"
    assert order["patient_balance_due_cents"] == 0
    assert order["tat_commitment_status"] == "ON_TRACK"
