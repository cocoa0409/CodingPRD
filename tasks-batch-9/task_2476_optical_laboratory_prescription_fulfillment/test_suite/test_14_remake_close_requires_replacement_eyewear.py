"""An adjudicated case that cannot close until the patient has glasses again."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import assertions, factories as f, fixtures
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import (
    MANAGER_A_HEADERS,
    OPTICIAN_A_HEADERS,
    TECHNICIAN_A_HEADERS,
)

REPLACEMENT_SURFACING = ("2026-08-01T13:00:00Z", "2026-08-01T14:00:00Z")
REPLACEMENT_EDGING = ("2026-08-01T15:00:00Z", "2026-08-01T16:00:00Z")


def _adjudicated_case_on_a_remake_pending_order(api):
    """A store-attributable case, adjudicated, with the order in REMAKE_PENDING."""
    scenario = fixtures.surfaced_edged_job(api)
    scenario["first_job_id"] = scenario["job_id"]

    case = validate_success(
        api.create_remake_case(
            f.create_remake_case_payload(
                scenario["job_id"], defect_codes=["WRONG_FRAME"], warranty_claim=False
            ),
            OPTICIAN_A_HEADERS,
        ),
        expected_status=201,
    )
    adjudicated = validate_success(
        api.adjudicate_remake_case(
            case["id"],
            f.create_adjudication_payload("PROCESS_AUDIT"),
            MANAGER_A_HEADERS,
        )
    )
    assert adjudicated["status"] == "ADJUDICATED"
    assert adjudicated["lab_share_pct"] == 0
    assert adjudicated["responsibility"] == "STORE"

    scenario["case_id"] = case["id"]
    assert fixtures.read_order(api, scenario["order_id"])["fulfillment_status"] == (
        "REMAKE_PENDING"
    )
    return scenario


def _release_the_replacement(api, scenario):
    scenario = fixtures.surfaced_queued_job(api, scenario)
    scenario = fixtures.surfaced_surfaced_job(api, scenario, *REPLACEMENT_SURFACING)
    scenario = fixtures.surfaced_edged_job(api, scenario, *REPLACEMENT_EDGING)
    scenario = fixtures.surfaced_passed_job(api, scenario)
    job = validate_success(
        api.release_lab_job(scenario["job_id"], TECHNICIAN_A_HEADERS)
    )
    assert job["status"] == "RELEASED"
    return scenario


def test_closing_is_refused_while_the_order_sits_in_remake_pending(api):
    """The case itself is ready; the replacement eyewear does not exist yet.

    PRD 3.8: "A `LabManager` closes an adjudicated case, and two gates apply: the
    case's `status` must be `ADJUDICATED`, and anything else yields
    `ERR_REMAKE_STATE_INVALID`; and the replacement eyewear must actually exist,
    meaning the order behind the case must be in `fulfillment_status` `LAB_COMPLETE`
    or `DISPENSED`, with anything else yielding `ERR_REMAKE_NOT_DELIVERABLE`."

    Design: Difficulty/cross_entity_state_dependency/remake_case_close_blocked_until_the_replacement_order_reaches_lab_complete
    """
    scenario = _adjudicated_case_on_a_remake_pending_order(api)

    validate_error(
        api.close_remake_case(scenario["case_id"], MANAGER_A_HEADERS),
        ApiErrorId.REMAKE_NOT_DELIVERABLE.value,
        409,
    )

    assert fixtures.read_case(api, scenario["case_id"])["status"] == "ADJUDICATED"


def test_the_identical_close_succeeds_once_the_replacement_is_released(api):
    """Driving a second job to release returns the order to LAB_COMPLETE.

    PRD 3.8: "Closing moves the case `ADJUDICATED → CLOSED`, after which no further
    adjudication is accepted and the case is immutable."

    Design: Difficulty/cross_entity_state_dependency/remake_case_close_blocked_until_the_replacement_order_reaches_lab_complete
    """
    scenario = _adjudicated_case_on_a_remake_pending_order(api)
    validate_error(
        api.close_remake_case(scenario["case_id"], MANAGER_A_HEADERS),
        ApiErrorId.REMAKE_NOT_DELIVERABLE.value,
        409,
    )

    scenario = _release_the_replacement(api, scenario)
    assert fixtures.read_order(api, scenario["order_id"])["fulfillment_status"] == (
        "LAB_COMPLETE"
    )

    case = validate_success(
        api.close_remake_case(scenario["case_id"], MANAGER_A_HEADERS)
    )
    assert case["status"] == "CLOSED"


def test_a_non_warranty_remake_moves_no_money_and_conserves_the_lot(api):
    """One blank came back to the shelf and the second was consumed outright.

    PRD 3.8: "When `warranty_covered` is false, nothing in the money block changes at
    all."

    Design: Difficulty/cross_entity_state_dependency/remake_case_close_blocked_until_the_replacement_order_reaches_lab_complete
    """
    scenario = _adjudicated_case_on_a_remake_pending_order(api)
    validate_error(
        api.close_remake_case(scenario["case_id"], MANAGER_A_HEADERS),
        ApiErrorId.REMAKE_NOT_DELIVERABLE.value,
        409,
    )
    scenario = _release_the_replacement(api, scenario)
    validate_success(api.close_remake_case(scenario["case_id"], MANAGER_A_HEADERS))

    order = fixtures.read_order(api, scenario["order_id"])
    assert order["remake_count"] == 1
    assert order["lab_writeoff_cents"] == 0

    lot = fixtures.read_lot(api, scenario["lot_id"])
    assertions.assert_lot_quantities(
        lot, on_hand=1, allocated=0, consumed=1, scrapped=0
    )
    assertions.assert_blank_ledger_conserved(lot)
