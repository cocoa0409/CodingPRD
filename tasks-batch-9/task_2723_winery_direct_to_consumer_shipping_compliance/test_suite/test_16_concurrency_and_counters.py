"""Optimistic concurrency on the two guarded writes and the missed-run threshold.

The two stale-read guards of PRD §2.6 sit on `POST /dtc/orders` and
`POST /dtc/carrier-enrollments`, and each guards a parent whose `version` moves for
reasons the client never initiated.  The third test follows the club scheduler's
missed-run counter across the suspension threshold and back again.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers.assertions import (
    assert_ledger_entry,
    assert_order_dimensions,
    assert_rejection,
)
from test_helpers.fixtures import (
    create_active_permit,
    create_carrier_program,
    create_prohibited_zip,
    create_state_rule,
    create_verified_consumer,
    create_winery,
    set_clock,
    winery_version,
)
from test_helpers.test_users import (
    ADMIN,
    CARRIER,
    CARRIER_USER_ID,
    OFFICER_A,
    make_winery_operator_headers,
)


def _single_bottle_order_payload(landscape, expected_consumer_version):
    """One 750 ml bottle at 4200 cents — 0.750 L, far inside the TX limit."""
    return f.order_payload(
        landscape.winery_id,
        landscape.consumer_id,
        expected_consumer_version,
        lines=f.canonical_lines(bottles=1),
    )


def test_order_create_rejects_a_stale_consumer_version_and_accepts_the_refreshed_one(
    api, landscape
):
    """The same captured version goes stale twice, for two unrelated reasons.

    "Creating an order requires the request to carry `expected_consumer_version`, a
    non-optional field holding the `version` of the target `Consumer` as the client
    last observed it." "If that value does not equal the consumer's current `version`,
    the create is rejected with `ERR_STALE_VERSION` and HTTP 412." "Under the product's
    own semantics that second order may be perfectly lawful — which is exactly why it
    is the stale-version check, and not any state precondition, that must reject it."
    (PRD 2.6) "Creation also increments `Consumer.version` by 1." (PRD 3.5) "Because
    that entry now exists, the consumer's `rolling_liters_by_state`,
    `rolling_liters_settled_by_state`, `risk_score_screening`, `risk_score_audit` and
    `screening_tier` are all recomputed and `Consumer.version` increments by 1."
    (PRD 3.6)

    Design: Corner/complexity_layers/order_create_rejects_a_stale_consumer_version_and_accepts_the_refreshed_one
    """
    observed = landscape.consumer_version()

    order_a = validate_success(
        api.create_order(
            _single_bottle_order_payload(landscape, observed), landscape.operator
        ),
        201,
    )
    assert_order_dimensions(order_a, "DRAFT", "UNFULFILLED")
    after_create_a = landscape.consumer_version()
    assert after_create_a == observed + 1

    validate_error(
        api.create_order(
            _single_bottle_order_payload(landscape, observed), landscape.operator
        ),
        "ERR_STALE_VERSION",
        412,
    )
    refused_orders, refused_meta = validate_paginated(
        api.list_orders(OFFICER_A, {"consumer_id": landscape.consumer_id})
    )
    assert refused_meta["total_count"] == 1
    assert refused_orders[0]["id"] == order_a["id"]
    assert landscape.consumer_version() == after_create_a

    order_b = validate_success(
        api.create_order(
            _single_bottle_order_payload(landscape, after_create_a), landscape.operator
        ),
        201,
    )
    after_create_b = landscape.consumer_version()
    assert after_create_b == after_create_a + 1

    screened = landscape.screen(order_a["id"])
    assert_order_dimensions(screened, "CLEARED", "UNFULFILLED")
    after_clearance = landscape.consumer_version()
    assert after_clearance == after_create_b + 1

    validate_error(
        api.create_order(
            _single_bottle_order_payload(landscape, after_create_a), landscape.operator
        ),
        "ERR_STALE_VERSION",
        412,
    )

    order_c = validate_success(
        api.create_order(
            _single_bottle_order_payload(landscape, after_clearance),
            landscape.operator,
        ),
        201,
    )
    assert landscape.consumer_version() == after_clearance + 1

    orders, meta = validate_paginated(
        api.list_orders(OFFICER_A, {"consumer_id": landscape.consumer_id})
    )
    assert meta["total_count"] == 3
    assert sorted(row["id"] for row in orders) == sorted(
        [order_a["id"], order_b["id"], order_c["id"]]
    )

    ledger_rows, ledger_meta = validate_paginated(
        api.list_volume_ledger_entries(
            OFFICER_A, {"consumer_id": landscape.consumer_id}
        )
    )
    assert ledger_meta["total_count"] == 1
    assert_ledger_entry(
        ledger_rows[0],
        event_type="SHIPMENT_ACCEPTED",
        liters=0.750,
        state_code="TX",
        order_id=order_a["id"],
    )


def _enrollment_payload(winery_id, program_id, expected_winery_version, account_number):
    return f.carrier_enrollment_payload(
        winery_id,
        program_id,
        expected_winery_version,
        account_number=account_number,
    )


def test_enrollment_create_rejects_a_stale_winery_version_before_it_supersedes(api):
    """A stale winery version is refused before it can demote an unseen enrollment.

    "Creating a carrier enrollment requires the request to carry
    `expected_winery_version`, a non-optional field holding the `version` of the target
    `Winery` as the client last observed it." "If that value does not equal the
    winery's current `version`, the create is rejected with `ERR_STALE_VERSION` and
    HTTP 412." "Here the hazard is supersession: creating an enrollment demotes any
    enrollment the winery already holds on the same carrier program, so a create issued
    from a stale read of the winery would silently supersede an enrollment the client
    never saw." (PRD 2.6) "Enrollment creation carries a supersession side effect that
    is easy to overlook: at most one enrollment per winery-and-program pair may be live
    at a time, so any enrollment the winery already holds for the same
    `carrier_program_id` in `PENDING` or `APPROVED` is moved by the system to
    `SUSPENDED` as part of the same call, and `Winery.version` increments by 1."
    (PRD 3.3)

    Design: Corner/complexity_layers/enrollment_create_rejects_a_stale_winery_version_before_it_can_supersede_an_unseen_row
    """
    set_clock(api)
    winery = create_winery(api)
    create_state_rule(api)
    create_active_permit(api, winery["id"])
    program = create_carrier_program(api)
    create_verified_consumer(api)
    operator = make_winery_operator_headers(winery["id"])

    first = validate_success(
        api.create_carrier_enrollment(
            _enrollment_payload(
                winery["id"], program["id"], winery_version(api, winery["id"]), "ACCT-1"
            ),
            operator,
        ),
        201,
    )
    assert first["status"] == "PENDING"
    assert first["approved_at"] is None
    assert first["decided_by_user_id"] is None
    after_first = winery_version(api, winery["id"])

    approved = validate_success(
        api.decide_carrier_enrollment(
            first["id"], f.enrollment_decision_payload("APPROVED"), CARRIER
        ),
        200,
    )
    assert approved["status"] == "APPROVED"
    assert approved["decided_by_user_id"] == CARRIER_USER_ID
    assert approved["approved_at"] is not None
    assert winery_version(api, winery["id"]) == after_first

    second = validate_success(
        api.create_carrier_enrollment(
            _enrollment_payload(winery["id"], program["id"], after_first, "ACCT-2"),
            operator,
        ),
        201,
    )
    assert second["status"] == "PENDING"
    assert second["account_number"] == "ACCT-2"
    superseded = validate_success(api.get_carrier_enrollment(first["id"], ADMIN), 200)
    assert superseded["status"] == "SUSPENDED"
    after_second = winery_version(api, winery["id"])
    assert after_second == after_first + 1

    for account_number in ("ACCT-2B", "ACCT-2C"):
        validate_error(
            api.create_carrier_enrollment(
                _enrollment_payload(
                    winery["id"], program["id"], after_first, account_number
                ),
                operator,
            ),
            "ERR_STALE_VERSION",
            412,
        )
    still_live = validate_success(api.get_carrier_enrollment(second["id"], ADMIN), 200)
    assert still_live["status"] == "PENDING"
    assert winery_version(api, winery["id"]) == after_second

    third = validate_success(
        api.create_carrier_enrollment(
            _enrollment_payload(winery["id"], program["id"], after_second, "ACCT-3"),
            operator,
        ),
        201,
    )
    assert third["status"] == "PENDING"
    demoted = validate_success(api.get_carrier_enrollment(second["id"], ADMIN), 200)
    assert demoted["status"] == "SUSPENDED"
    assert winery_version(api, winery["id"]) == after_second + 1

    rows, meta = validate_paginated(
        api.list_carrier_enrollments(ADMIN, {"winery_id": winery["id"]})
    )
    assert meta["total_count"] == 3
    assert sorted(row["id"] for row in rows) == sorted(
        [first["id"], second["id"], third["id"]]
    )


def test_missed_run_count_suspends_at_the_second_miss_and_a_reset_restarts_it(
    api, landscape
):
    """Two misses suspend, one does not, and a reinstatement restarts the count at 0.

    "If the generated order landed in `REJECTED`, the subscription's
    `missed_run_count` grows by 1 and its `next_run_date` is left **unchanged**, so the
    same member is retried on the next run; and if that increment brings
    `missed_run_count` to 2 or more, the subscription is moved `ACTIVE` →
    `SUSPENDED_COMPLIANCE` with its `next_run_date` set to null, the winery's
    `suspended_subscription_count` is recomputed and `Winery.version` increments by 1."
    "A subscription in `SUSPENDED_COMPLIANCE` is never a candidate, since its
    `next_run_date` is null by construction." "An empty candidate set is not an error:
    the run answers HTTP 200 with `generated_count` 0 and an empty
    `generated_order_ids` array." "A reinstatement puts `missed_run_count` back to 0,
    sets `next_run_date` to the logical clock date so the subscription rejoins the
    schedule immediately, recomputes the winery's `suspended_subscription_count`, and
    increments `Winery.version` by 1." (PRD 3.8) "A matching row records
    `ERR_PROHIBITED_DESTINATION`." (PRD 3.6)

    Design: Corner/complexity_layers/missed_run_count_suspends_at_the_second_miss_and_a_reset_restarts_the_count_from_zero
    """
    create_prohibited_zip(api, landscape.state_rule_id)
    subscription = landscape.create_subscription(
        next_run_date="2026-08-01",
        annual_allotment=6,
        bottles_per_shipment=2,
    )
    opened = landscape.read_subscription(subscription["id"])
    assert opened["status"] == "ACTIVE"
    assert opened["missed_run_count"] == 0
    assert opened["consumed_shipments"] == 0

    generated_order_ids = []

    def missed_run():
        run = landscape.club_run("2026-08-01")
        assert run["generated_count"] == 1
        assert run["skipped_count"] == 0
        order = landscape.read_order(run["generated_order_ids"][0])
        assert_order_dimensions(order, "REJECTED", "UNFULFILLED")
        assert_rejection(order, "ERR_PROHIBITED_DESTINATION")
        generated_order_ids.append(order["id"])
        return landscape.read_subscription(subscription["id"])

    first_miss = missed_run()
    assert first_miss["missed_run_count"] == 1
    assert first_miss["status"] == "ACTIVE"
    assert first_miss["next_run_date"] == "2026-08-01"

    winery_version_before_suspension = landscape.winery_version()
    second_miss = missed_run()
    assert second_miss["missed_run_count"] == 2
    assert second_miss["status"] == "SUSPENDED_COMPLIANCE"
    assert second_miss["next_run_date"] is None

    suspended_winery = landscape.read_winery()
    assert suspended_winery["suspended_subscription_count"] == 1
    assert suspended_winery["version"] == winery_version_before_suspension + 1

    empty_run = landscape.club_run("2026-08-01")
    assert empty_run["generated_count"] == 0
    assert empty_run["skipped_count"] == 0
    assert empty_run["generated_order_ids"] == []
    assert empty_run["skipped_subscription_ids"] == []

    reinstated = validate_success(
        api.release_hold(subscription["id"], f.release_hold_payload(True), OFFICER_A),
        200,
    )
    assert reinstated["status"] == "ACTIVE"
    assert reinstated["missed_run_count"] == 0
    assert reinstated["next_run_date"] == "2026-08-01"
    assert landscape.read_winery()["suspended_subscription_count"] == 0

    third_miss = missed_run()
    assert third_miss["missed_run_count"] == 1
    assert third_miss["status"] == "ACTIVE"
    assert third_miss["next_run_date"] == "2026-08-01"

    fourth_miss = missed_run()
    assert fourth_miss["missed_run_count"] == 2
    assert fourth_miss["status"] == "SUSPENDED_COMPLIANCE"
    assert fourth_miss["next_run_date"] is None
    assert landscape.read_winery()["suspended_subscription_count"] == 1

    assert fourth_miss["consumed_shipments"] == 0
    assert fourth_miss["remaining_allotment"] == 6

    orders, meta = validate_paginated(
        api.list_orders(OFFICER_A, {"club_subscription_id": subscription["id"]})
    )
    assert meta["total_count"] == 4
    assert sorted(row["id"] for row in orders) == sorted(generated_order_ids)
    for row in orders:
        assert_order_dimensions(row, "REJECTED", "UNFULFILLED")

    _, ledger_meta = validate_paginated(
        api.list_volume_ledger_entries(
            OFFICER_A, {"consumer_id": landscape.consumer_id}
        )
    )
    assert ledger_meta["total_count"] == 0
