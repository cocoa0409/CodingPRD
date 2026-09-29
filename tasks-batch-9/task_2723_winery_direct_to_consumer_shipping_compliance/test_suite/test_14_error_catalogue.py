"""Error outcomes of the Winery DTC Shipping Compliance API.

The harness restarts the server and empties the database before every test, so
each test drives the consumer, the carrier layer and the order into the state its
rule needs from nothing.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers import factories as f
from test_helpers.assertions import (
    assert_cents,
    assert_liters,
    assert_order_dimensions,
    assert_rejection,
)
from test_helpers.constants import (
    CARRIER_PROGRAM_GSO_TX,
    CARRIER_PROGRAM_NO_SIGNATURE,
)
from test_helpers.fixtures import (
    append_manual_adjustment,
    build_landscape,
    build_override_pending_order,
    create_approved_enrollment,
    create_carrier_program,
    decide_enrollment,
)
from test_helpers.test_users import OFFICER_A, OFFICER_A_USER_ID

# An AZ state rule whose per-consumer ceiling is exactly one canonical order, so
# the utilisation term of the risk score is easy to drive.
AZ_LIMIT_LITERS = 4.500
AZ_SHIP_TO = {"ship_to_state_code": "AZ", "ship_to_zip": "85001"}
LITERS_TOLERANCE = 0.0005


def _az_landscape(api):
    """A landscape whose destination state is AZ with a 4.500 L consumer ceiling."""
    return build_landscape(
        api,
        state_rule_overrides={
            "state_code": "AZ",
            "per_consumer_limit_liters": AZ_LIMIT_LITERS,
        },
        permit_overrides={"state_code": "AZ", "permit_number": "AZ-DTC-1"},
        program_overrides={"states_served": ["AZ"]},
        consumer_overrides={"state_code": "AZ", "city": "Phoenix", "zip_code": "85001"},
    )


def _assert_per_state(summary, state_code, rolling, limit):
    """The accumulated liters, the per-consumer limit and the headroom between."""
    entry = summary["per_state"][state_code]
    values = [
        value
        for value in entry.values()
        if isinstance(value, (int, float)) and not isinstance(value, bool)
    ]
    for expected in (rolling, limit, limit - rolling):
        assert any(abs(value - expected) <= LITERS_TOLERANCE for value in values), (
            f"per_state.{state_code} must report {expected:.3f}; got {values}"
        )


def test_elevated_screening_tier_parks_orders_and_bars_new_club_subscriptions(api):
    """The first factor is 10 points per in-scope return credit, capped at 40. The second factor is 15 points per in-scope denied exception, capped at 30. The third factor is a utilisation term: among the states present in the relevant liters map, the system selects the state with the greatest ratio of accumulated liters to that state's `per_consumer_limit_liters`, breaking a tie in favour of the alphabetically earlier `state_code`; the factor is then 30 multiplied by the selected state's liters divided by that state's per-consumer limit, truncated downward to a whole number, and capped at 30. An empty liters map yields a third factor of 0. The three factors are added and the sum is capped at 100.

    From the screening score alone the system derives `screening_tier`, which is `STANDARD` while `risk_score_screening` is below 50 and becomes `ELEVATED` as soon as `risk_score_screening` reaches 50 or more. (PRD 3.4)

    Two refusals guard the opening: a subscription may not be opened for a consumer whose `screening_tier` is `ELEVATED`, which is raised here as a real `ERR_ELEVATED_RISK_REVIEW_REQUIRED` error rather than recorded, and no subscription may be opened at all while the winery is `SUSPENDED`. (PRD 3.8)

    **The consumer must not be flagged for review.** `screening_tier` must be `STANDARD`; an `ELEVATED` consumer, meaning `risk_score_screening` of 50 or more, requires manual compliance review and records `ERR_ELEVATED_RISK_REVIEW_REQUIRED`. This failure is **overridable**. (PRD 3.6)

    Design: Corner/errors/elevated_screening_tier_parks_orders_and_bars_new_club_subscriptions
    """
    scape = _az_landscape(api)

    # One return credit: 10 points on the first factor.
    returned = scape.create_order(**AZ_SHIP_TO)
    scape.screen(returned["id"])
    shipment = scape.label(returned["id"])
    scape.pickup(shipment["id"])
    scape.return_to_sender(shipment["id"])

    # Two denied exceptions: the second factor saturates at 30 points.
    for _ in range(2):
        over_limit = scape.create_order(lines=f.canonical_lines(bottles=8), **AZ_SHIP_TO)
        parked = scape.screen(over_limit["id"])
        assert_order_dimensions(parked, "OVERRIDE_PENDING")
        assert_rejection(parked, "ERR_CONSUMER_VOLUME_LIMIT_EXCEEDED")
        exception = scape.raise_exception(
            parked["id"], "ERR_CONSUMER_VOLUME_LIMIT_EXCEEDED"
        )
        scape.decide_exception(exception["id"], "DENIED")

    # 1.500 settled liters against a 4.500 L ceiling: floor(30 * 1/3) = 10 points.
    append_manual_adjustment(
        api,
        scape.consumer_id,
        scape.winery_id,
        1.500,
        state_code="AZ",
        occurred_at="2026-07-20T00:00:00Z",
    )

    consumer = scape.read_consumer()
    assert consumer["return_credit_count"] == 1
    assert consumer["denied_exception_count"] == 2
    assert consumer["risk_score_screening"] == 50
    assert consumer["risk_score_audit"] == 50
    assert consumer["screening_tier"] == "ELEVATED"

    validate_error(
        api.create_club_subscription(
            f.club_subscription_payload(
                scape.consumer_id, scape.winery_id, next_run_date="2026-09-01"
            ),
            scape.operator,
        ),
        "ERR_ELEVATED_RISK_REVIEW_REQUIRED",
        422,
    )
    _, meta = validate_paginated(
        api.list_club_subscriptions(OFFICER_A, {"consumer_id": scape.consumer_id})
    )
    assert meta["total_count"] == 0

    # An order is still accepted; it is screening that parks it.
    accrued_before = scape.read_winery()["excise_accrued_cents"]
    small = scape.create_order(lines=f.canonical_lines(bottles=1), **AZ_SHIP_TO)
    assert_order_dimensions(small, "DRAFT", "UNFULFILLED")
    screened = scape.screen(small["id"])
    assert_order_dimensions(screened, "OVERRIDE_PENDING", "UNFULFILLED")
    assert_rejection(screened, "ERR_ELEVATED_RISK_REVIEW_REQUIRED")

    assert scape.ledger_rows(order_id=small["id"]) == []
    assert_cents(
        scape.read_winery()["excise_accrued_cents"],
        accrued_before,
        "excise_accrued_cents",
    )
    _assert_per_state(scape.volume_summary(state_code="AZ"), "AZ", 1.500, AZ_LIMIT_LITERS)


def test_a_carrier_program_without_a_signature_service_cannot_carry_the_order(api):
    """When the destination state rule's `requires_carrier_program` is true, the winery must hold an enrollment in `APPROVED` whose program's `states_served` array contains the order's `ship_to_state_code`; otherwise the outcome is `ERR_CARRIER_NOT_ENROLLED`. Then, when the order's own `adult_signature_required` is true, that same enrollment's program must have a non-null `adult_signature_service_code`; a program that cannot offer an age-verified signature service cannot lawfully carry a signature-required shipment, and the outcome is `ERR_ADULT_SIGNATURE_NOT_SUPPORTED`.

    While an enrollment sits in `SUSPENDED`, no new label may be drawn against it; the attempt is refused with `ERR_CARRIER_NOT_ENROLLED`. (PRD 3.3)

    The shipment's own `adult_signature_required` is copied from the order's `adult_signature_required`, and its `adult_signature_service_code` is copied from the enrolled program's `adult_signature_service_code` when a signature is required and is null when it is not. (PRD 3.7)

    Design: Corner/errors/a_carrier_program_without_a_signature_service_cannot_carry_a_signature_order
    """
    scape = build_landscape(api, program_overrides=CARRIER_PROGRAM_NO_SIGNATURE)

    blocked = scape.create_order()
    rejected = scape.screen(blocked["id"])
    assert_order_dimensions(rejected, "REJECTED", "UNFULFILLED")
    assert_rejection(rejected, "ERR_ADULT_SIGNATURE_NOT_SUPPORTED")
    assert rejected["adult_signature_required"] is True
    assert scape.ledger_rows(order_id=blocked["id"]) == []

    # Join a program that can offer the age-verified signature service.
    decide_enrollment(
        api, scape.enrollment_id, "SUSPENDED", note="No adult signature service"
    )
    signature_program = create_carrier_program(api, **CARRIER_PROGRAM_GSO_TX)
    signature_enrollment = create_approved_enrollment(
        api, scape.winery_id, signature_program["id"], account_number="ACCT-2"
    )

    shippable = scape.create_order()
    cleared = scape.screen(shippable["id"])
    assert_order_dimensions(cleared, "CLEARED", "UNFULFILLED")
    assert_rejection(cleared, None)

    validate_error(
        api.create_shipment(
            f.shipment_payload(shippable["id"], scape.enrollment_id), scape.operator
        ),
        "ERR_CARRIER_NOT_ENROLLED",
        422,
    )

    shipment = get_success_data(
        api.create_shipment(
            f.shipment_payload(shippable["id"], signature_enrollment["id"]),
            scape.operator,
        ),
        201,
    )
    assert shipment["status"] == "LABEL_CREATED"
    assert shipment["adult_signature_required"] is True
    assert shipment["adult_signature_service_code"] == "AS21"

    assert (
        get_success_data(api.get_carrier_enrollment(scape.enrollment_id, OFFICER_A))[
            "status"
        ]
        == "SUSPENDED"
    )
    assert (
        get_success_data(
            api.get_carrier_enrollment(signature_enrollment["id"], OFFICER_A)
        )["status"]
        == "APPROVED"
    )
    assert scape.read_order(blocked["id"])["compliance_status"] == "REJECTED"


def test_invalid_request_covers_empty_arrays_reversed_periods_and_mismatched_rules(api):
    """The concrete bounds enforced here are: a line's `bottles` is at least 1; a line's `bottle_ml` is one of 375, 500, 750, 1000, 1500 or 3000; a line's `unit_price_cents` is at least 1; the `lines` array holds at least 1 and at most 20 elements; `sales_tax_rate_bps` lies between 0 and 2000 inclusive; a remittance's `period_start` is strictly before its `period_end`; `horizon_days` lies between 1 and 365 inclusive; and `run_date` parses as a valid ISO 8601 date. Unknown fields in a request body are ignored rather than rejected. Any failure at this gate is `ERR_INVALID_REQUEST` (HTTP 400). (PRD 2.8)

    The supplied `raised_rule` must equal the order's currently recorded `rejection_error_id`; a mismatch is refused with `ERR_INVALID_REQUEST`, which prevents an officer from overriding a rule the order never actually failed. The exception opens in `status` `OPEN` with `requested_by_user_id` set from the raising officer's `X-User-ID`, with `decided_by_user_id`, `decision_note` and `decided_at` all null, and the winery's `open_exception_count` — the number of `OPEN` exceptions on that winery's orders — grows by 1. (PRD 3.6)

    Design: Corner/errors/invalid_request_covers_empty_arrays_reversed_periods_and_mismatched_rules
    """
    scape, parked = build_override_pending_order(
        api, seeded_liters=25.000, occurred_at="2026-07-01T00:00:00Z"
    )
    assert_order_dimensions(parked, "OVERRIDE_PENDING", "UNFULFILLED")
    assert_rejection(parked, "ERR_CONSUMER_VOLUME_LIMIT_EXCEEDED")
    assert scape.read_winery()["open_exception_count"] == 0

    validate_error(
        api.create_order(
            f.order_payload(
                scape.winery_id, scape.consumer_id, scape.consumer_version(), lines=[]
            ),
            scape.operator,
        ),
        "ERR_INVALID_REQUEST",
        400,
    )
    validate_error(
        api.create_remittance(
            f.remittance_payload(
                scape.winery_id, "TX", "2026-08-01T00:00:00Z", "2026-08-01T00:00:00Z"
            ),
            OFFICER_A,
        ),
        "ERR_INVALID_REQUEST",
        400,
    )
    validate_error(
        api.raise_compliance_exception(
            parked["id"],
            f.compliance_exception_payload(
                "ERR_PROHIBITED_DESTINATION", "Wrong rule named on purpose"
            ),
            OFFICER_A,
        ),
        "ERR_INVALID_REQUEST",
        400,
    )
    assert scape.read_winery()["open_exception_count"] == 0

    exception = scape.raise_exception(
        parked["id"], "ERR_CONSUMER_VOLUME_LIMIT_EXCEEDED"
    )
    assert exception["status"] == "OPEN"
    assert exception["raised_rule"] == "ERR_CONSUMER_VOLUME_LIMIT_EXCEEDED"
    assert exception["requested_by_user_id"] == OFFICER_A_USER_ID
    assert exception["order_id"] == parked["id"]
    assert exception["decided_by_user_id"] is None
    assert exception["decided_at"] is None
    assert scape.read_winery()["open_exception_count"] == 1

    rows, meta = validate_paginated(
        api.list_order_compliance_exceptions(parked["id"], OFFICER_A)
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [exception["id"]]

    unchanged = scape.read_order(parked["id"])
    assert_order_dimensions(unchanged, "OVERRIDE_PENDING", "UNFULFILLED")
    assert_rejection(unchanged, "ERR_CONSUMER_VOLUME_LIMIT_EXCEEDED")

    _, orders_meta = validate_paginated(
        api.list_orders(OFFICER_A, {"winery_id": scape.winery_id})
    )
    assert orders_meta["total_count"] == 1
    _, remittance_meta = validate_paginated(
        api.list_remittances(OFFICER_A, {"winery_id": scape.winery_id})
    )
    assert remittance_meta["total_count"] == 0
    assert_liters(
        scape.read_consumer()["rolling_liters_by_state"]["TX"], 25.000
    )
