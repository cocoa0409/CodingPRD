"""Endpoint-shape corners: reference-data round trips, empty-body actions, the
directed equivalence link, the auto-reorder bulk run and the reconciled ledger
read.
"""

from test_helpers import (
    ADMIN_HEADERS,
    CO_ALPHA,
    CO_ALPHA_HEADERS,
    DEFAULT_CLOCK_UTC,
    api_client,
    approve_return_request,
    assert_ledger_values,
    create_product_payload,
    deliver_order,
    generate_reimbursement_claim,
    get_success_data,
    make_compliance_headers,
    make_customer_headers,
    new_auto_reorder_schedule,
    new_customer,
    new_insurance_plan,
    new_order,
    new_prescription,
    new_product,
    new_reimbursement_claim,
    new_reorder_hold,
    set_clock,
    settle_return_request,
    ship_order,
    submit_prescription,
    validate_paginated,
    validate_success,
)

# ---------------------------------------------------------------------------
# Local setup helpers, composed from the shared primitives.
# ---------------------------------------------------------------------------

SKU_MONTHLY = {
    "brand": "MonthWear",
    "name": "Monthly 6",
    "wear_schedule": "MONTHLY",
    "lenses_per_box": 6,
    "unit_price_cents": 4800,
    "material_family": "hydrogel",
}


def _new_product_without_sphere_step(**overrides) -> dict:
    """Register a SKU while omitting `sphere_step`, so the declared default is
    the only thing that can populate it."""
    payload = create_product_payload(**overrides)
    payload.pop("sphere_step", None)
    return get_success_data(api_client.create_product(payload, ADMIN_HEADERS))


def _two_sku_catalog() -> dict:
    """A catalogue holding one daily-disposable SKU registered without an
    explicit `sphere_step`, plus one monthly SKU."""
    set_clock(DEFAULT_CLOCK_UTC)
    return {
        "daily": _new_product_without_sphere_step(),
        "monthly": new_product(**SKU_MONTHLY),
    }


def _prescription_events(prescription_id: str):
    """The whole compliance trail for one prescription, as (rows, meta)."""
    return validate_paginated(
        api_client.list_compliance_events_for_prescription(
            prescription_id, CO_ALPHA_HEADERS, params={"limit": 100}
        )
    )


def _count_events_of_type(prescription_id: str, event_type: str) -> int:
    rows, _meta = _prescription_events(prescription_id)
    return sum(1 for row in rows if row["event_type"] == event_type)


def _setup_two_due_schedules_one_held() -> dict:
    """Two patients, each owning one ACTIVE usage-adjusted schedule due at the
    same instant. The second patient also carries an OPEN manual hold, so the
    run has one shippable and one skippable schedule.
    """
    set_clock(DEFAULT_CLOCK_UTC)
    product = new_product()
    scenario = {"product": product, "customers": [], "prescriptions": [], "schedules": []}
    specs = [
        ("Ada Lin", "ada.lin@example.com", "scan-a", -2.25, -4.00),
        ("Ben Ortiz", "ben.ortiz@example.com", "scan-b", -1.00, -1.00),
    ]
    for full_name, email, document_reference, od_sphere, os_sphere in specs:
        customer = new_customer(full_name=full_name, email=email, state_code="UT")
        rx = new_prescription(
            customer["id"],
            product["id"],
            document_reference=document_reference,
            od_sphere=od_sphere,
            os_sphere=os_sphere,
        )
        prescription = submit_prescription(rx["id"], customer["id"])
        schedule = new_auto_reorder_schedule(
            customer["id"],
            prescription["id"],
            product["id"],
            boxes_per_run=1,
            anchor_date="2026-08-01",
            cadence_basis="USAGE_ADJUSTED",
            observed_days_per_box=16,
        )
        scenario["customers"].append(customer)
        scenario["prescriptions"].append(prescription)
        scenario["schedules"].append(schedule)
    scenario["hold"] = new_reorder_hold(
        scenario["customers"][1]["id"],
        scenario["prescriptions"][1]["id"],
        actor=CO_ALPHA,
        reason="MANUAL",
    )
    return scenario


def _setup_fully_loaded_ledger() -> dict:
    """A plan-covered patient carrying every aggregate the reconciled read spans:
    a delivered 6400-cent order, a SETTLED torn-lens return paid as store credit,
    a GENERATED claim, one ACTIVE schedule and one OPEN hold.
    """
    set_clock(DEFAULT_CLOCK_UTC)
    plan = new_insurance_plan()
    product = new_product()
    customer = new_customer(insurance_plan_id=plan["id"])
    rx = new_prescription(customer["id"], product["id"])
    prescription = submit_prescription(rx["id"], customer["id"])
    order = new_order(customer["id"], prescription["id"], product["id"], 1, 1)
    ship_order(order["id"])
    order = deliver_order(order["id"])

    return_request = get_success_data(
        api_client.create_return_request(
            {
                "order_id": order["id"],
                "customer_id": customer["id"],
                "reason": "TORN_LENS",
                "torn_lens_count": 30,
            },
            make_customer_headers(customer["id"]),
        )
    )
    approve_return_request(return_request["id"])
    return_request = settle_return_request(return_request["id"])

    claim = new_reimbursement_claim(order["id"], customer["id"], plan["id"])
    claim = generate_reimbursement_claim(claim["id"])

    schedule = new_auto_reorder_schedule(
        customer["id"],
        prescription["id"],
        product["id"],
        boxes_per_run=3,
        anchor_date="2026-09-08",
        cadence_basis="NOMINAL",
    )
    hold = new_reorder_hold(
        customer["id"], prescription["id"], actor=CO_ALPHA, reason="MANUAL"
    )
    return {
        "plan": plan,
        "product": product,
        "customer": customer,
        "prescription": prescription,
        "order": order,
        "return_request": return_request,
        "claim": claim,
        "schedule": schedule,
        "hold": hold,
    }


# ---------------------------------------------------------------------------
# Reference data: the lens SKU catalogue
# ---------------------------------------------------------------------------


class TestProductCatalogRoundTrip:
    def test_registered_sku_reads_back_with_declared_defaults(self, api, customer_headers):
        """PRD §3.1: "Its fitting envelope is described by `base_curve` and
        `diameter` in millimetres, by `sphere_min` and `sphere_max` bounding the
        stocked powers (where `sphere_max` must be at least `sphere_min`), and by
        `sphere_step`, the granularity of stocked powers, which defaults to
        0.25."

        PRD §3.1: "A product's `status` is `ACTIVE` or `INACTIVE` and defaults to
        `ACTIVE`; deactivating a product sets `INACTIVE`, and thereafter it may
        be neither ordered, nor scheduled, nor substituted into — such attempts
        are rejected with `ERR_PRODUCT_INACTIVE`."

        PRD §3.1: "It is registered with a `brand`, a `name`, a `wear_schedule`
        of `DAILY_DISPOSABLE`, `BIWEEKLY` or `MONTHLY`, a `lenses_per_box` count
        of at least 1, and a `unit_price_cents` price per box of at least 1."

        Design: Corner/endpoints/product_create_read_and_list_round_trip
        """
        catalog = _two_sku_catalog()
        daily = catalog["daily"]

        data = validate_success(api.get_product(daily["id"], customer_headers))

        assert data["id"] == daily["id"]
        assert data["brand"] == "AcuityFlex"
        assert data["lenses_per_box"] == 30
        assert data["unit_price_cents"] == 3200
        assert float(data["sphere_step"]) == 0.25
        assert data["status"] == "ACTIVE"

    def test_wear_schedule_filter_counts_only_the_matching_sku(self, api, admin_headers):
        """PRD §3.1: "Products may be browsed with filters on `wear_schedule`,
        `status` and `material_family`."

        PRD §2.3: "Every list response carries `limit`, `offset`, `total_count`
        and `has_more` inside the `meta` object, where `total_count` counts every
        row matching the filters before pagination is applied and `has_more` is
        true when rows remain beyond the returned page."

        Design: Corner/endpoints/product_create_read_and_list_round_trip
        """
        catalog = _two_sku_catalog()

        filtered, filtered_meta = validate_paginated(
            api.list_products(admin_headers, params={"wear_schedule": "DAILY_DISPOSABLE"})
        )
        assert filtered_meta["total_count"] == 1
        assert filtered[0]["id"] == catalog["daily"]["id"]

        _unfiltered, unfiltered_meta = validate_paginated(api.list_products(admin_headers))
        assert unfiltered_meta["total_count"] == 2


class TestProductDeactivation:
    def test_deactivate_takes_no_body_and_flips_the_status_filter(self, api, admin_headers):
        """PRD §3.1: "A product's `status` is `ACTIVE` or `INACTIVE` and defaults
        to `ACTIVE`; deactivating a product sets `INACTIVE`, and thereafter it may
        be neither ordered, nor scheduled, nor substituted into — such attempts
        are rejected with `ERR_PRODUCT_INACTIVE`."

        PRD §3.1: "Products may be browsed with filters on `wear_schedule`,
        `status` and `material_family`."

        PRD §4: "Every other operation — reads, state transitions, sweeps, and
        the logical-clock write — returns `200 OK`."

        Design: Corner/endpoints/deactivate_action_endpoint_takes_an_empty_body
        """
        set_clock(DEFAULT_CLOCK_UTC)
        product = new_product()

        data = validate_success(api.deactivate_product(product["id"], admin_headers))
        assert data["status"] == "INACTIVE"

        _active, active_meta = validate_paginated(
            api.list_products(admin_headers, params={"status": "ACTIVE"})
        )
        assert active_meta["total_count"] == 0

        inactive, inactive_meta = validate_paginated(
            api.list_products(admin_headers, params={"status": "INACTIVE"})
        )
        assert inactive_meta["total_count"] == 1
        assert inactive[0]["id"] == product["id"]


# ---------------------------------------------------------------------------
# Reference data: the directed equivalence edge
# ---------------------------------------------------------------------------


class TestLensEquivalenceLink:
    def test_link_takes_from_product_from_the_path_and_defaults_its_flags(
        self, api, admin_headers
    ):
        """PRD §3.1: "It is authored against a path product, which becomes the
        mapping's `from_product_id`, and names a `to_product_id` as the SKU that
        may be fulfilled instead."

        PRD §3.1: "Independently of the class, the flag
        `requires_patient_consent`, defaulting to false, forces consent when
        set."

        PRD §3.1: "A mapping's `status` is `ACTIVE` or `RETIRED`, defaulting to
        `ACTIVE`; a `RETIRED` mapping cannot be used for substitution."

        Design: Corner/endpoints/lens_equivalence_link_is_directed_and_listed_from_both_sides
        """
        set_clock(DEFAULT_CLOCK_UTC)
        origin = new_product()
        target = new_product(brand="OptiSoft", base_curve=8.70)

        data = validate_success(
            api.create_lens_equivalence(
                origin["id"],
                {"to_product_id": target["id"], "equivalence_class": "CLINICAL"},
                admin_headers,
            ),
            201,
        )

        assert data["from_product_id"] == origin["id"]
        assert data["to_product_id"] == target["id"]
        assert data["equivalence_class"] == "CLINICAL"
        assert data["requires_patient_consent"] is False
        assert data["status"] == "ACTIVE"

    def test_direction_filter_returns_the_edge_from_one_side_only(self, api, admin_headers):
        """PRD §3.1: "Mappings touching a product can be listed with an optional
        `direction` filter, where `FROM` returns the rows whose `from_product_id`
        is the path product, `TO` returns the rows whose `to_product_id` is the
        path product, and omitting the filter returns both, alongside the usual
        `status` filter."

        Design: Corner/endpoints/lens_equivalence_link_is_directed_and_listed_from_both_sides
        """
        set_clock(DEFAULT_CLOCK_UTC)
        origin = new_product()
        target = new_product(brand="OptiSoft", base_curve=8.70)
        equivalence = validate_success(
            api.create_lens_equivalence(
                origin["id"],
                {"to_product_id": target["id"], "equivalence_class": "CLINICAL"},
                admin_headers,
            ),
            201,
        )

        outbound, outbound_meta = validate_paginated(
            api.list_lens_equivalences_for_product(
                origin["id"], admin_headers, params={"direction": "FROM"}
            )
        )
        assert outbound_meta["total_count"] == 1
        assert outbound[0]["id"] == equivalence["id"]

        inbound, inbound_meta = validate_paginated(
            api.list_lens_equivalences_for_product(
                target["id"], admin_headers, params={"direction": "TO"}
            )
        )
        assert inbound_meta["total_count"] == 1
        assert inbound[0]["id"] == equivalence["id"]

        _reversed_rows, reversed_meta = validate_paginated(
            api.list_lens_equivalences_for_product(
                target["id"], admin_headers, params={"direction": "FROM"}
            )
        )
        assert reversed_meta["total_count"] == 0


# ---------------------------------------------------------------------------
# Hold escalation as the second exit from OPEN
# ---------------------------------------------------------------------------


class TestHoldEscalation:
    def test_escalation_records_the_reason_and_empties_the_open_hold_count(self, api):
        """PRD §3.7: "Alternatively a compliance officer may escalate the hold
        instead of releasing it, supplying an `escalated_reason` that is recorded
        on the row; escalation moves the hold to `ESCALATED`, appends a
        `HOLD_ESCALATED` compliance event, and — because `ESCALATED` is no longer
        `OPEN` — also decrements `open_hold_count` and recomputes
        `auto_reorder_enabled`, so escalation clears the fulfilment block just as
        release does."

        PRD §2.7: "`open_hold_count` is the number of that customer's reorder
        holds whose `status` is `OPEN`."

        Design: Corner/endpoints/escalate_action_endpoint_clears_the_fulfillment_block
        """
        set_clock(DEFAULT_CLOCK_UTC)
        product = new_product()
        customer = new_customer()
        rx = new_prescription(customer["id"], product["id"])
        prescription = submit_prescription(rx["id"], customer["id"])
        new_order(customer["id"], prescription["id"], product["id"], 1, 1)
        hold = new_reorder_hold(
            customer["id"], prescription["id"], actor=CO_ALPHA, reason="MANUAL"
        )

        data = validate_success(
            api.escalate_reorder_hold(
                hold["id"],
                {"escalated_reason": "state board referral"},
                make_compliance_headers(CO_ALPHA),
            )
        )
        assert data["status"] == "ESCALATED"
        assert data["escalated_reason"] == "state board referral"

        ledger = validate_success(
            api.get_customer_ledger(
                customer["id"], make_customer_headers(customer["id"])
            )
        )
        assert_ledger_values(ledger, open_hold_count=0)
        assert _count_events_of_type(prescription["id"], "HOLD_ESCALATED") == 1

    def test_escalated_hold_no_longer_blocks_shipping(self, api, fulfillment_headers):
        """PRD §3.7: "A warehouse operator may advance an order from `PENDING` to
        `SHIPPED` only when its `verification_state` is `RX_CLEARED` — an order
        still `RX_PENDING` or already `RX_BLOCKED` cannot ship, and the attempt is
        reported as an undeclared transition — and only when the order's customer
        has no reorder hold in `OPEN` status, which is reported specifically as
        `ERR_HOLD_OPEN_BLOCKS_ACTION`."

        PRD §3.7: "Alternatively a compliance officer may escalate the hold
        instead of releasing it, supplying an `escalated_reason` that is recorded
        on the row; escalation moves the hold to `ESCALATED`, appends a
        `HOLD_ESCALATED` compliance event, and — because `ESCALATED` is no longer
        `OPEN` — also decrements `open_hold_count` and recomputes
        `auto_reorder_enabled`, so escalation clears the fulfilment block just as
        release does."

        Design: Corner/endpoints/escalate_action_endpoint_clears_the_fulfillment_block
        """
        set_clock(DEFAULT_CLOCK_UTC)
        product = new_product()
        customer = new_customer()
        rx = new_prescription(customer["id"], product["id"])
        prescription = submit_prescription(rx["id"], customer["id"])
        order = new_order(customer["id"], prescription["id"], product["id"], 1, 1)
        hold = new_reorder_hold(
            customer["id"], prescription["id"], actor=CO_ALPHA, reason="MANUAL"
        )

        validate_success(
            api.escalate_reorder_hold(
                hold["id"],
                {"escalated_reason": "state board referral"},
                make_compliance_headers(CO_ALPHA),
            )
        )

        shipped = validate_success(api.ship_order(order["id"], fulfillment_headers))
        assert shipped["fulfillment_state"] == "SHIPPED"


# ---------------------------------------------------------------------------
# The auto-reorder run as a bulk action
# ---------------------------------------------------------------------------


class TestAutoReorderRunBulkAction:
    def test_usage_adjusted_cadence_lands_on_the_floor_and_sets_next_run_at(self, api):
        """PRD §3.7: "Under the `USAGE_ADJUSTED` variant, the supply is instead
        `boxes_per_run` multiplied by the reported `observed_days_per_box`,
        ignoring the wear schedule entirely."

        PRD §3.7: "`cadence_days` is then that supply figure reduced by a fixed
        reorder lead time of five days, but never allowed below a floor of
        fourteen days — so a schedule whose raw supply is sixteen days lands on
        the floor rather than on eleven."

        PRD §3.7: "`next_run_at` is the `anchor_date` advanced by `cadence_days`,
        at 08:00 UTC on that date."

        Design: Corner/endpoints/auto_reorder_run_is_a_bulk_action_that_ships_some_and_skips_others
        """
        scenario = _setup_two_due_schedules_one_held()

        for schedule in scenario["schedules"]:
            live = validate_success(
                api.get_auto_reorder_schedule(
                    schedule["id"],
                    make_customer_headers(schedule["customer_id"]),
                )
            )
            assert live["cadence_days"] == 14
            assert live["next_run_at"] == "2026-08-15T08:00:00.000Z"

    def test_run_ships_the_unblocked_schedule_and_skips_the_held_one(
        self, api, fulfillment_headers
    ):
        """PRD §3.7: "A warehouse operator triggers it, and it processes every
        `ACTIVE` schedule whose `next_run_at` has arrived relative to the logical
        clock, in ascending `next_run_at` order and, where two schedules are due
        at the same instant, in ascending `created_at` order."

        PRD §3.7: "For each due schedule, an order is created and shipped when
        three conditions hold: the prescription is `VERIFIED_ACTIVE` and
        unexpired, the customer has no hold in `OPEN` status, and the
        prescription's remaining box authorisation covers the schedule's
        `boxes_per_run`."

        PRD §3.7: "When any of those three fails, that schedule is **skipped
        rather than erroring** — the run still returns HTTP 200 — and its
        `consecutive_skip_count` is incremented; once that counter reaches the
        limit of two consecutive skips, the schedule moves from `ACTIVE` to
        `PAUSED` with `pause_reason` `SKIP_LIMIT` and a `SCHEDULE_PAUSED`
        compliance event is appended."

        PRD §3.7: "The run reports `run_at` as the logical instant it executed,
        plus `shipped_order_ids`, `skipped_schedule_ids` and
        `paused_schedule_ids`."

        Design: Corner/endpoints/auto_reorder_run_is_a_bulk_action_that_ships_some_and_skips_others
        """
        scenario = _setup_two_due_schedules_one_held()
        set_clock("2026-08-15T08:00:00Z")

        data = validate_success(api.run_auto_reorder(fulfillment_headers))

        assert data["run_at"] == "2026-08-15T08:00:00.000Z"
        assert len(data["shipped_order_ids"]) == 1
        assert data["skipped_schedule_ids"] == [scenario["schedules"][1]["id"]]
        assert data["paused_schedule_ids"] == []

        _held_orders, held_meta = validate_paginated(
            api.list_orders(
                fulfillment_headers,
                params={"customer_id": scenario["customers"][1]["id"]},
            )
        )
        assert held_meta["total_count"] == 0

    def test_both_schedules_advance_next_run_at_by_the_same_cadence(
        self, api, fulfillment_headers
    ):
        """PRD §3.7: "On both the shipping and the skipping path, `next_run_at` is
        advanced by `cadence_days` and the affected customer's ledgers are
        reconciled."

        PRD §3.7: "When any of those three fails, that schedule is **skipped
        rather than erroring** — the run still returns HTTP 200 — and its
        `consecutive_skip_count` is incremented; once that counter reaches the
        limit of two consecutive skips, the schedule moves from `ACTIVE` to
        `PAUSED` with `pause_reason` `SKIP_LIMIT` and a `SCHEDULE_PAUSED`
        compliance event is appended."

        Design: Corner/endpoints/auto_reorder_run_is_a_bulk_action_that_ships_some_and_skips_others
        """
        scenario = _setup_two_due_schedules_one_held()
        set_clock("2026-08-15T08:00:00Z")
        validate_success(api.run_auto_reorder(fulfillment_headers))

        shipped_schedule = validate_success(
            api.get_auto_reorder_schedule(
                scenario["schedules"][0]["id"],
                make_customer_headers(scenario["customers"][0]["id"]),
            )
        )
        assert shipped_schedule["consecutive_skip_count"] == 0
        assert shipped_schedule["next_run_at"] == "2026-08-29T08:00:00.000Z"

        skipped_schedule = validate_success(
            api.get_auto_reorder_schedule(
                scenario["schedules"][1]["id"],
                make_customer_headers(scenario["customers"][1]["id"]),
            )
        )
        assert skipped_schedule["consecutive_skip_count"] == 1
        assert skipped_schedule["status"] == "ACTIVE"
        assert skipped_schedule["next_run_at"] == "2026-08-29T08:00:00.000Z"

    def test_run_created_order_is_cleared_shipped_and_priced_from_the_snapshot(
        self, api, fulfillment_headers
    ):
        """PRD §3.7: "For each due schedule, an order is created and shipped when
        three conditions hold: the prescription is `VERIFIED_ACTIVE` and
        unexpired, the customer has no hold in `OPEN` status, and the
        prescription's remaining box authorisation covers the schedule's
        `boxes_per_run`."

        PRD §3.5: "Its `verification_state` is seeded from the prescription:
        `RX_CLEARED` when the prescription is already `VERIFIED_ACTIVE`, and
        `RX_PENDING` otherwise."

        PRD §3.5: "`subtotal_cents` is the snapshotted `unit_price_cents`
        multiplied by total boxes."

        PRD §3.5: "`shipping_cents` is zero when `subtotal_cents` has reached the
        free-shipping threshold of 5,000 cents — fifty dollars, and the
        comparison is inclusive, so a subtotal of exactly 5,000 cents ships free
        — and is otherwise the flat standard charge of 695 cents."

        PRD §3.5: "`total_cents` is `subtotal_cents` plus `shipping_cents`."

        Design: Corner/endpoints/auto_reorder_run_is_a_bulk_action_that_ships_some_and_skips_others
        """
        scenario = _setup_two_due_schedules_one_held()
        set_clock("2026-08-15T08:00:00Z")
        validate_success(api.run_auto_reorder(fulfillment_headers))

        orders, meta = validate_paginated(
            api.list_orders(
                fulfillment_headers,
                params={"customer_id": scenario["customers"][0]["id"]},
            )
        )
        assert meta["total_count"] == 1
        assert orders[0]["verification_state"] == "RX_CLEARED"
        assert orders[0]["fulfillment_state"] == "SHIPPED"
        assert orders[0]["total_cents"] == 3895


# ---------------------------------------------------------------------------
# The reconciled ledger read
# ---------------------------------------------------------------------------


class TestReconciledCustomerLedger:
    def test_ledger_reconciles_orders_returns_claims_holds_and_schedules(self, api):
        """PRD §2.7: "It returns `customer_id`, `lifetime_charged_cents`,
        `lifetime_refunded_cents`, `net_cash_position_cents`,
        `store_credit_cents`, `allowance_used_cents`,
        `allowance_remaining_cents`, `open_hold_count`, `active_schedule_count`
        and `auto_reorder_enabled`, each recomputed from live rows at read time so
        that any drift between the stored counters and reality is directly
        observable."

        PRD §2.7: "`lifetime_charged_cents` is the sum of `total_cents` over every
        order of that customer whose `fulfillment_state` is anything other than
        `CANCELLED`."

        PRD §2.7: "`lifetime_refunded_cents` is the sum of `settlement_cents` over
        that customer's return requests whose `status` is `SETTLED` and whose
        `settlement_channel` is `CASH_REFUND`."

        PRD §2.7: "`net_cash_position_cents` is `lifetime_charged_cents` less
        `lifetime_refunded_cents`."

        PRD §2.7: "`store_credit_cents` is the running store-credit balance,
        credited whenever a return settles through the `STORE_CREDIT` channel."

        PRD §3.8: "Under `NO_PRORATION`, no box residue is considered at all: the
        candidate figure is `torn_lens_count` multiplied by the per-box value,
        divided by the lenses per box and rounded half up to a whole cent, and
        `settlement_cents` is whichever is smaller — that candidate figure, or a
        cap equal to twenty percent of the order's `total_cents` with any fraction
        of a cent discarded downward."

        PRD §3.9: "`base_eligible_cents` is gross spend less
        `refund_offset_cents`, floored at zero."

        PRD §3.9: "`applied_allowance_cents` is whichever is smaller,
        `base_eligible_cents` or that remaining allowance."

        PRD §2.7: "`allowance_remaining_cents` is the plan's
        `annual_allowance_cents` less `allowance_used_cents`, floored at zero; for
        a self-pay customer who carries no `insurance_plan_id` it is zero."

        PRD §2.7: "`auto_reorder_enabled` is true exactly when
        `active_schedule_count` is greater than zero and `open_hold_count` is
        zero, and false in every other case."

        Design: Corner/endpoints/customer_ledger_is_a_computed_read_over_five_aggregates
        """
        scenario = _setup_fully_loaded_ledger()
        customer_id = scenario["customer"]["id"]

        data = validate_success(
            api.get_customer_ledger(customer_id, make_customer_headers(customer_id))
        )

        assert data["customer_id"] == customer_id
        assert_ledger_values(
            data,
            lifetime_charged_cents=6400,
            lifetime_refunded_cents=0,
            net_cash_position_cents=6400,
            store_credit_cents=1280,
            allowance_used_cents=5120,
            allowance_remaining_cents=9880,
            open_hold_count=1,
            active_schedule_count=1,
        )
        assert data["auto_reorder_enabled"] is False

    def test_ledger_read_is_side_effect_free(self, api):
        """PRD §2.7: "It returns `customer_id`, `lifetime_charged_cents`,
        `lifetime_refunded_cents`, `net_cash_position_cents`,
        `store_credit_cents`, `allowance_used_cents`,
        `allowance_remaining_cents`, `open_hold_count`, `active_schedule_count`
        and `auto_reorder_enabled`, each recomputed from live rows at read time so
        that any drift between the stored counters and reality is directly
        observable."

        PRD §2.11: "Third, every compliance-relevant transition against a
        prescription appends an append-only **compliance event**."

        Design: Corner/endpoints/customer_ledger_is_a_computed_read_over_five_aggregates
        """
        scenario = _setup_fully_loaded_ledger()
        customer_id = scenario["customer"]["id"]
        prescription_id = scenario["prescription"]["id"]
        _rows, before_meta = _prescription_events(prescription_id)

        first = validate_success(
            api.get_customer_ledger(customer_id, make_customer_headers(customer_id))
        )
        second = validate_success(
            api.get_customer_ledger(customer_id, make_customer_headers(customer_id))
        )

        assert first == second
        _rows_after, after_meta = _prescription_events(prescription_id)
        assert after_meta["total_count"] == before_meta["total_count"]
