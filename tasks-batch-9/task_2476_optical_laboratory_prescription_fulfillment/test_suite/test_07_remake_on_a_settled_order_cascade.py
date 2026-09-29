"""A warranty remake opened against an order the patient has already paid for."""

from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers import assertions, factories as f, fixtures
from test_helpers.test_users import OPTICIAN_A_HEADERS


def _settled_surfaced_order(api):
    """A released, benefit-applied, fully paid progressive order."""
    scenario = fixtures.surfaced_settled_order(api)
    assert scenario["order"]["billing_status"] == "PATIENT_SETTLED"
    return scenario


def _open_warranty_case(api, scenario):
    return validate_success(
        api.create_remake_case(
            f.create_remake_case_payload(
                scenario["job_id"],
                defect_codes=["COSMETIC_DEFECT"],
                warranty_claim=True,
            ),
            OPTICIAN_A_HEADERS,
        ),
        expected_status=201,
    )


def test_opening_the_case_scraps_the_released_job_and_leaves_the_blank_consumed(api):
    """The blank was already consumed at release, so the scrap returns nothing.

    PRD 3.8: "The first hop creates the case with `status` `SUBMITTED`,
    `responsibility` `UNASSIGNED`, a null `adjudication_method`, a null
    `lab_share_pct` and `lab_chargeback_cents` of 0, and simultaneously scraps the
    linked job with `scrap_reason` `REMAKE_REQUESTED` — `RELEASED → SCRAPPED` for a
    job already handed to the store, and likewise `EDGED → SCRAPPED`, `PASSED →
    SCRAPPED` or `REWORK_QUEUED → SCRAPPED` for a job still inside the laboratory;
    if that job still holds a blank reservation, the reservation is returned to the
    shelf rather than destroyed — the lot's `allocated_qty` falls by 1 and its
    `on_hand_qty` rises by 1, and a lot that was `DEPLETED` flips back to
    `AVAILABLE` once its `on_hand_qty` becomes 1."

    Design: Difficulty/transitive_cascade/remake_on_a_settled_order_cascades_four_hops_into_refund_due
    """
    scenario = _settled_surfaced_order(api)

    case = _open_warranty_case(api, scenario)
    assert case["status"] == "SUBMITTED"
    assert case["warranty_covered"] is True

    job = fixtures.read_job(api, scenario["job_id"])
    assert job["status"] == "SCRAPPED"
    assert job["scrap_reason"] == "REMAKE_REQUESTED"

    lot = fixtures.read_lot(api, scenario["lot_id"])
    assertions.assert_lot_quantities(lot, on_hand=1, allocated=0, consumed=1, scrapped=0)


def test_the_scrap_moves_the_order_to_remake_pending_and_raises_the_count(api):
    """The order's second hop follows from the job scrap, not from the request.

    PRD 3.8: "The second hop follows from the job scrap: the order moves `IN_LAB →
    REMAKE_PENDING` or `LAB_COMPLETE → REMAKE_PENDING` and its `remake_count` rises
    by 1."

    Design: Difficulty/transitive_cascade/remake_on_a_settled_order_cascades_four_hops_into_refund_due
    """
    scenario = _settled_surfaced_order(api)

    _open_warranty_case(api, scenario)

    order = fixtures.read_order(api, scenario["order_id"])
    assert order["fulfillment_status"] == "REMAKE_PENDING"
    assert order["remake_count"] == 1


def test_the_count_change_writes_a_twenty_five_percent_warranty_writeoff(api):
    """25 percent of the 41977 writeoff-free base is 10494 after half-up rounding.

    PRD 3.8: "The third hop follows from that count change and only fires when
    `warranty_covered` is true: take the writeoff-free base, which is the current
    `patient_portion_cents` plus the current `lab_writeoff_cents`; read the
    cumulative write-off percentage for the new `remake_count`, which is 25 percent
    after the first remake and 60 percent after the second; set
    `lab_writeoff_cents` to that base multiplied by the cumulative percentage,
    rounded half up to whole cents; and set `patient_portion_cents` to the base
    less the new `lab_writeoff_cents`, with `patient_balance_due_cents` following
    as `patient_portion_cents` less `patient_paid_cents`."

    Design: Difficulty/transitive_cascade/remake_on_a_settled_order_cascades_four_hops_into_refund_due
    """
    scenario = _settled_surfaced_order(api)

    _open_warranty_case(api, scenario)

    order = fixtures.read_order(api, scenario["order_id"])
    assert order["lab_writeoff_cents"] == 10494
    assert order["patient_portion_cents"] == 31483
    assert order["gross_charge_cents"] == 81977
    assert order["insurance_benefit_cents"] == 40000
    assertions.assert_money_identity(order)

    entries, _ = validate_paginated(
        api.list_order_settlement_entries(scenario["order_id"], OPTICIAN_A_HEADERS)
    )
    writeoffs = [e for e in entries if e["entry_type"] == "LAB_WRITEOFF"]
    assert len(writeoffs) == 1
    assert writeoffs[0]["amount_cents"] == -10494


def test_the_dropped_portion_turns_the_settled_order_into_a_refund_obligation(api):
    """The patient has paid 41977 against a portion that is now only 31483.

    PRD 3.8: "The fourth hop follows from the patient portion having dropped: if
    `patient_paid_cents` now exceeds `patient_portion_cents`, the order moves
    `PATIENT_SETTLED → REFUND_DUE`, which is terminal on the billing dimension, and
    `patient_balance_due_cents` stays negative to record the amount owed back."

    Design: Difficulty/transitive_cascade/remake_on_a_settled_order_cascades_four_hops_into_refund_due
    """
    scenario = _settled_surfaced_order(api)

    _open_warranty_case(api, scenario)

    order = fixtures.read_order(api, scenario["order_id"])
    assert order["billing_status"] == "REFUND_DUE"
    assert order["patient_balance_due_cents"] == -10494
    assert order["patient_paid_cents"] == 41977
    assertions.assert_balance_definition(order)
