"""Stale views refused on two parents, and a write-off tier that never stacks."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import assertions, factories as f, fixtures
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import OPTICIAN_A_HEADERS, TECHNICIAN_A_HEADERS

RETRACE = {"a_mm": 50.0, "b_mm": 28.0, "ed_mm": 54.0, "dbl_mm": 17.0}
FREE_WINDOW = ("2026-08-01T13:00:00Z", "2026-08-01T14:00:00Z")
REPLACEMENT_WINDOW = ("2026-08-01T10:00:00Z", "2026-08-01T11:00:00Z")
STOCK_GROSS = 26985
FIRST_TIER_WRITEOFF = 6746
FIRST_TIER_PORTION = 20239
SECOND_TIER_WRITEOFF = 16191
SECOND_TIER_PORTION = 10794
STACKED_WRITEOFF = 18889


def _order_traced_once(api):
    """A DRAFT order at version 1 traced once, leaving it at version 2."""
    scenario = fixtures.stock_layout_ready_order(api)
    assert scenario["layout"]["required_blank_diameter_mm"] == 58.0
    assert scenario["order_version"] == 2
    return scenario


def _job_with_one_booking(api):
    """A QUEUED job at version 1 with one 08:00-09:00 window, leaving it at 2."""
    scenario = fixtures.stock_queued_job(api)
    assert scenario["job"]["version"] == 1
    operation = fixtures.book_edging(api, scenario)
    scenario["first_operation_id"] = operation["id"]
    assert scenario["job_version"] == 2
    return scenario


def _first_warranty_remake(api):
    """One warranty case against the EDGED stock job, which scraps that job."""
    scenario = fixtures.stock_edged_job(api)
    assert scenario["order"]["gross_charge_cents"] == STOCK_GROSS
    assert scenario["order"]["patient_portion_cents"] == STOCK_GROSS
    assert fixtures.read_job(api, scenario["job_id"])["released_at"] is None
    case = validate_success(
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
    assert case["warranty_covered"] is True
    scenario["first_case"] = case
    scenario["first_job_id"] = scenario["job_id"]
    return scenario


def _second_warranty_remake(api):
    """A replacement job driven back to EDGED, then a second warranty case."""
    scenario = _first_warranty_remake(api)
    scenario = fixtures.stock_replacement_job(api, scenario)
    scenario = fixtures.stock_edged_job(
        api, scenario, REPLACEMENT_WINDOW[0], REPLACEMENT_WINDOW[1]
    )
    case = validate_success(
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
    assert case["warranty_covered"] is True
    scenario["second_case"] = case
    scenario["second_job_id"] = scenario["job_id"]
    return scenario


def test_a_retrace_replaying_the_pre_trace_version_is_refused(api):
    """The state machine welcomes a second layout; only the version check objects.

    PRD 2.5: "`POST /frame-layouts` requires `expected_rx_order_version` as a
    non-optional input field, carrying the `version` of the target order as the client
    last observed it. If that value does not match the order's current `version`, the
    request is rejected with `ERR_STALE_RX_ORDER_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/a_retrace_against_a_stale_order_version_is_rejected_then_accepted
    """
    scenario = _order_traced_once(api)

    validate_error(
        api.create_frame_layout(
            f.create_frame_layout_payload(scenario["order_id"], 1, **RETRACE),
            OPTICIAN_A_HEADERS,
        ),
        ApiErrorId.STALE_RX_ORDER_VERSION.value,
        412,
    )

    rows, meta = validate_paginated(
        api.list_order_frame_layouts(scenario["order_id"], OPTICIAN_A_HEADERS)
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == scenario["layout_id"]
    assert fixtures.read_layout(api, scenario["layout_id"])["layout_status"] == "COMPUTED"
    assert fixtures.read_order(api, scenario["order_id"])["version"] == 2


def test_the_same_retrace_body_supersedes_once_it_carries_version_two(api):
    """Identical geometry, one different integer, and the layout of record moves.

    PRD 3.4: "Every earlier layout of that order has its `layout_status` set to
    `SUPERSEDED`, so exactly one layout is ever the layout of record."

    Design: Corner/cross_cutting_complexity_layers/a_retrace_against_a_stale_order_version_is_rejected_then_accepted
    """
    scenario = _order_traced_once(api)
    validate_error(
        api.create_frame_layout(
            f.create_frame_layout_payload(scenario["order_id"], 1, **RETRACE),
            OPTICIAN_A_HEADERS,
        ),
        ApiErrorId.STALE_RX_ORDER_VERSION.value,
        412,
    )

    second = validate_success(
        api.create_frame_layout(
            f.create_frame_layout_payload(scenario["order_id"], 2, **RETRACE),
            OPTICIAN_A_HEADERS,
        ),
        expected_status=201,
    )

    # ed 54.0 plus twice the 2.0 horizontal decentration plus the 2.0 chuck allowance.
    assert second["required_blank_diameter_mm"] == 60.0
    assert second["layout_status"] == "COMPUTED"
    assert fixtures.read_layout(api, scenario["layout_id"])["layout_status"] == "SUPERSEDED"

    order = fixtures.read_order(api, scenario["order_id"])
    assert order["version"] == 3
    assert order["fulfillment_status"] == "LAYOUT_READY"


def test_a_second_booking_replaying_the_job_version_at_creation_is_refused(api):
    """Booking the first window bumped the job, so version 1 is stale by one.

    PRD 2.5: "`POST /lab-operations` requires `expected_lab_job_version` as a
    non-optional input field, carrying the `version` of the target lab job as the client
    last observed it. If that value does not match the job's current `version`, the
    request is rejected with `ERR_STALE_LAB_JOB_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/a_second_operation_booked_on_a_stale_job_version_is_rejected_then_accepted
    """
    scenario = _job_with_one_booking(api)

    validate_error(
        api.create_lab_operation(
            f.create_edging_operation_payload(
                scenario["job_id"],
                1,
                scenario["bay_id"],
                FREE_WINDOW[0],
                FREE_WINDOW[1],
            ),
            TECHNICIAN_A_HEADERS,
        ),
        ApiErrorId.STALE_LAB_JOB_VERSION.value,
        412,
    )

    rows, meta = validate_paginated(
        api.list_lab_operations(
            TECHNICIAN_A_HEADERS, {"lab_job_id": scenario["job_id"]}
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == scenario["first_operation_id"]
    assert fixtures.read_job(api, scenario["job_id"])["version"] == 2


def test_the_same_booking_is_accepted_once_it_carries_the_bumped_job_version(api):
    """The window was always feasible; the guard was the only obstacle.

    PRD 2.5: "Multiple operations per job are correct by design — surfacing then edging,
    and another pair after every rework loop — so a second create is never forbidden by
    state; the version check is what stops an occupation from being booked against a job
    whose route, blank allocation or rework cycle has already moved on."

    Design: Corner/cross_cutting_complexity_layers/a_second_operation_booked_on_a_stale_job_version_is_rejected_then_accepted
    """
    scenario = _job_with_one_booking(api)
    validate_error(
        api.create_lab_operation(
            f.create_edging_operation_payload(
                scenario["job_id"], 1, scenario["bay_id"], *FREE_WINDOW
            ),
            TECHNICIAN_A_HEADERS,
        ),
        ApiErrorId.STALE_LAB_JOB_VERSION.value,
        412,
    )

    second = validate_success(
        api.create_lab_operation(
            f.create_edging_operation_payload(
                scenario["job_id"], 2, scenario["bay_id"], *FREE_WINDOW
            ),
            TECHNICIAN_A_HEADERS,
        ),
        expected_status=201,
    )

    assert second["status"] == "SCHEDULED"
    assert fixtures.read_job(api, scenario["job_id"])["version"] == 3


def test_the_first_warranty_remake_writes_off_a_quarter_of_the_portion(api):
    """26985 at 25 percent is 6746.25, and half up lands on 6746.

    PRD 3.8: "take the writeoff-free base, which is the current `patient_portion_cents`
    plus the current `lab_writeoff_cents`; read the cumulative write-off percentage for
    the new `remake_count`, which is 25 percent after the first remake and 60 percent
    after the second; set `lab_writeoff_cents` to that base multiplied by the cumulative
    percentage, rounded half up to whole cents; and set `patient_portion_cents` to the
    base less the new `lab_writeoff_cents`, with `patient_balance_due_cents` following as
    `patient_portion_cents` less `patient_paid_cents`."

    Design: Corner/cross_cutting_complexity_layers/two_warranty_remakes_land_on_the_cumulative_sixty_percent_tier
    """
    scenario = _first_warranty_remake(api)

    order = fixtures.read_order(api, scenario["order_id"])

    assert order["remake_count"] == 1
    assert order["lab_writeoff_cents"] == FIRST_TIER_WRITEOFF
    assert order["patient_portion_cents"] == FIRST_TIER_PORTION
    assert order["patient_balance_due_cents"] == FIRST_TIER_PORTION
    assert order["gross_charge_cents"] == STOCK_GROSS
    assertions.assert_money_identity(order)


def test_the_second_warranty_remake_recomputes_from_the_writeoff_free_base(api):
    """The 60 percent tier is taken on 26985 again, not on the 20239 remainder.

    PRD 3.8: "Because the percentage is cumulative and is always recomputed from the
    writeoff-free base, two successive remakes produce exactly the second-tier write-off
    and never the first tier plus the second; the money identity of §2.8 survives every
    remake untouched."

    Design: Corner/cross_cutting_complexity_layers/two_warranty_remakes_land_on_the_cumulative_sixty_percent_tier
    """
    scenario = _second_warranty_remake(api)

    order = fixtures.read_order(api, scenario["order_id"])

    assert order["remake_count"] == 2
    assert order["lab_writeoff_cents"] == SECOND_TIER_WRITEOFF
    assert order["lab_writeoff_cents"] != STACKED_WRITEOFF
    assert order["patient_portion_cents"] == SECOND_TIER_PORTION
    assert order["patient_balance_due_cents"] == SECOND_TIER_PORTION
    assert order["gross_charge_cents"] == STOCK_GROSS
    assert order["insurance_benefit_cents"] == 0
    assertions.assert_money_identity(order)


def test_both_remakes_scrap_their_job_and_append_one_movement_each(api):
    """Two append-only movements of 6746 and 9445 add up to the write-off on record.

    PRD 3.8: "The first hop creates the case with `status` `SUBMITTED`, `responsibility`
    `UNASSIGNED`, a null `adjudication_method`, a null `lab_share_pct` and
    `lab_chargeback_cents` of 0, and simultaneously scraps the linked job with
    `scrap_reason` `REMAKE_REQUESTED`"

    PRD 3.9: "The sign convention is fixed: `ORDER_CHARGE` and `BENEFIT_REVERSAL` are
    positive because they increase what the patient owes, while `INSURANCE_BENEFIT`,
    `LAB_WRITEOFF` and `PATIENT_PAYMENT` are negative because they decrease it."

    Design: Corner/cross_cutting_complexity_layers/two_warranty_remakes_land_on_the_cumulative_sixty_percent_tier
    """
    scenario = _second_warranty_remake(api)

    first_job = fixtures.read_job(api, scenario["first_job_id"])
    second_job = fixtures.read_job(api, scenario["second_job_id"])
    assert first_job["status"] == "SCRAPPED"
    assert first_job["scrap_reason"] == "REMAKE_REQUESTED"
    assert second_job["status"] == "SCRAPPED"
    assert second_job["scrap_reason"] == "REMAKE_REQUESTED"

    entries, meta = validate_paginated(
        api.list_order_settlement_entries(scenario["order_id"], OPTICIAN_A_HEADERS)
    )

    assert meta["total_count"] == 2
    assertions.assert_ledger_types_in_order(entries, ["LAB_WRITEOFF", "LAB_WRITEOFF"])
    assert entries[0]["amount_cents"] == -FIRST_TIER_WRITEOFF
    assert entries[1]["amount_cents"] == -(SECOND_TIER_WRITEOFF - FIRST_TIER_WRITEOFF)
    assert sum(entry["amount_cents"] for entry in entries) == -SECOND_TIER_WRITEOFF
