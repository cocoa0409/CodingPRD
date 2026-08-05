"""Ordering functional panels: wash-out adjudication, collection and funding."""

from test_helpers import (
    ApiErrorId,
    assert_calendar_date,
    assert_lab_order,
    assert_membership_lab_credit_conservation,
    make_nd_headers,
    open_membership,
    order_panel,
    read_membership,
    read_patient,
    register_nd,
    register_patient,
    setup_active_protocol,
    setup_collected_panel,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_washout_bound_is_closed_at_the_computed_clearance_date(api):
    """PRD §3.4: "That bound is closed at the bottom. A
    `requested_collection_date` equal to `washout_clearance_date` satisfies the
    wash-out and the order is created `ORDERED`; only a strictly earlier
    requested date sends the order to `WASHOUT_HOLD` instead, with the computed
    clearance date recorded on it."
    PRD §3.4: "A release attempted while neither condition holds is refused with
    `ERR_WASHOUT_NOT_ELAPSED`, and a successful release increments the order's
    `version` by 1."
    PRD §3.4: "`DUTCH_HORMONE` collects a `DRIED_URINE` specimen, does not
    require fasting, must be collected between cycle day 19 and cycle day 22
    inclusive, is interfered with by the `HORMONE_SUPPORT` supplement class with
    a 14-day wash-out, and costs 39000 cents in cash or 2 laboratory credits."

    Design: Corner/calculations/washout_adjudication_is_closed_at_the_clearance_date
    """
    ctx = setup_active_protocol(
        api,
        with_tech=False,
        with_lot=False,
        product_overrides={
            "sku": "DIM-200",
            "name": "DIM complex",
            "supplement_class": "HORMONE_SUPPORT",
            "retail_price_cents": 5200,
            "practitioner_cost_cents": 3100,
        },
        item_overrides={"dose_amount_mg": 200, "titration_interval_days": 21},
        protocol_overrides={"title": "Hormone balance", "symptom_score_baseline": 24},
    )
    nd, patient = ctx["nd"], ctx["patient"]

    held = validate_success(
        api.create_lab_order(
            {
                "patient_id": patient["id"],
                "panel_code": "DUTCH_HORMONE",
                "funding_source": "CASH",
                "requested_collection_date": "2026-05-14",
                "cycle_day": 20,
            },
            make_nd_headers(nd["id"]),
        ),
        201,
    )
    assert_lab_order(held)
    assert held["status"] == "WASHOUT_HOLD"
    assert held["washout_class"] == "HORMONE_SUPPORT"
    assert_calendar_date(
        held["washout_clearance_date"], "2026-05-15", "washout_clearance_date"
    )

    release = api.release_washout_hold(held["id"], make_nd_headers(nd["id"]))
    validate_error(release, ApiErrorId.ERR_WASHOUT_NOT_ELAPSED.value, 409)

    cancelled = validate_success(
        api.cancel_lab_order(
            held["id"], {"reason": "re-dating the draw"}, make_nd_headers(nd["id"])
        )
    )
    assert cancelled["status"] == "CANCELLED"

    on_time = validate_success(
        api.create_lab_order(
            {
                "patient_id": patient["id"],
                "panel_code": "DUTCH_HORMONE",
                "funding_source": "CASH",
                "requested_collection_date": "2026-05-15",
                "cycle_day": 20,
            },
            make_nd_headers(nd["id"]),
        ),
        201,
    )
    assert on_time["status"] == "ORDERED"
    assert on_time["specimen_type"] == "DRIED_URINE"
    assert on_time["price_cents"] == 39000


def test_collection_enforces_fasting_and_the_closed_cycle_day_window(api):
    """PRD §3.4: "It is a gated family, and it enforces the panel's biological
    window: when the catalogue block requires fasting, the order's
    `fasting_attested` must be true, and when the catalogue block declares a
    cycle-day window, the order's `cycle_day` must be present and inside that
    **closed** window — for the hormone panel, cycle days 19 and 22 both qualify
    while 18 and 23 do not. Either failure is refused with
    `ERR_COLLECTION_WINDOW_INVALID`."

    Design: Corner/endpoints/collection_enforces_fasting_and_the_closed_cycle_day_window
    """
    nd = register_nd(api)
    patient = register_patient(api, nd["id"])

    unfasted = order_panel(
        api,
        nd["id"],
        patient["id"],
        panel_code="SERUM_METABOLIC",
        requested_collection_date="2026-05-04",
        fasting_attested=False,
    )
    out_of_window = order_panel(
        api,
        nd["id"],
        patient["id"],
        panel_code="DUTCH_HORMONE",
        requested_collection_date="2026-05-20",
        cycle_day=23,
        fasting_attested=False,
    )

    for order in (unfasted, out_of_window):
        response = api.collect_lab_order(order["id"], make_nd_headers(nd["id"]))
        validate_error(response, ApiErrorId.ERR_COLLECTION_WINDOW_INVALID.value, 422)

        unchanged = validate_success(
            api.get_lab_order(order["id"], make_nd_headers(nd["id"]))
        )
        assert unchanged["status"] == "ORDERED"
        assert unchanged["collected_at"] is None

    assert out_of_window["specimen_type"] == "DRIED_URINE"


def test_a_second_open_order_for_the_same_panel_is_refused(api):
    """PRD §3.4: "A patient may not hold two open orders for the same panel: if
    an order for that same `panel_code` already exists for that patient in
    status `ORDERED`, `WASHOUT_HOLD` or `COLLECTED`, the request is refused with
    `ERR_DUPLICATE_PANEL_ORDER`."

    Design: Corner/errors/second_open_order_for_the_same_panel_returns_duplicate_panel_order
    """
    nd = register_nd(api)
    patient = register_patient(api, nd["id"])
    order_panel(api, nd["id"], patient["id"], panel_code="SERUM_METABOLIC")

    duplicate = api.create_lab_order(
        {
            "patient_id": patient["id"],
            "panel_code": "SERUM_METABOLIC",
            "funding_source": "CASH",
            "requested_collection_date": "2026-05-06",
            "fasting_attested": True,
        },
        make_nd_headers(nd["id"]),
    )
    validate_error(duplicate, ApiErrorId.ERR_DUPLICATE_PANEL_ORDER.value, 409)

    other_panel = validate_success(
        api.create_lab_order(
            {
                "patient_id": patient["id"],
                "panel_code": "STOOL_GI_MAP",
                "funding_source": "CASH",
                "requested_collection_date": "2026-05-06",
            },
            make_nd_headers(nd["id"]),
        ),
        201,
    )
    assert other_panel["status"] == "ORDERED"

    rows, meta = validate_paginated(
        api.list_lab_orders(make_nd_headers(nd["id"]), params={"patient_id": patient["id"]})
    )
    assert meta["total_count"] == 2 and len(rows) == 2


def test_credit_funded_order_without_a_membership_is_refused_at_the_fiscal_rung(api):
    """PRD §3.4: "And a `MEMBERSHIP_CREDIT` order requires a membership in status
    `ACTIVE` whose `lab_credits_remaining` is at least the panel's credit cost;
    a patient with no active membership, or one whose credits are short, is
    refused with `ERR_ENTITLEMENT_EXHAUSTED` and HTTP 402."

    Design: Corner/errors/membership_funded_order_without_a_membership_returns_entitlement_exhausted
    """
    nd = register_nd(api)
    patient = register_patient(api, nd["id"])

    response = api.create_lab_order(
        {
            "patient_id": patient["id"],
            "panel_code": "SERUM_METABOLIC",
            "funding_source": "MEMBERSHIP_CREDIT",
            "requested_collection_date": "2026-05-04",
            "fasting_attested": True,
        },
        make_nd_headers(nd["id"]),
    )
    validate_error(response, ApiErrorId.ERR_ENTITLEMENT_EXHAUSTED.value, 402)

    rows, meta = validate_paginated(
        api.list_lab_orders(make_nd_headers(nd["id"]), params={"patient_id": patient["id"]})
    )
    assert meta["total_count"] == 0 and rows == []


def test_an_interpreted_order_is_terminal_and_cannot_be_cancelled(api):
    """PRD §3.5: "Interpretation closes the order. A `NaturopathicDoctor` records
    the `interpretation_summary`, moving the order `RESULTED → INTERPRETED` or
    `CRITICAL_ESCALATED → INTERPRETED`, and the order's `version` increments by
    1."
    PRD §3.5: "`INTERPRETED` is terminal."
    PRD §2.6: "The addressed resource is in a state from which the requested
    transition is declared, on the relevant axis, on every state-transition
    endpoint — otherwise `ERR_INVALID_STATE` (409)."

    Design: Corner/state_machines/cancelling_an_interpreted_lab_order_is_refused_by_terminal_lockdown
    """
    ctx = setup_collected_panel(api)
    nd, patient, order = ctx["nd"], ctx["patient"], ctx["order"]

    validate_success(
        api.create_lab_result(
            order["id"],
            {
                "analyte_code": "TSH",
                "value": 2.0,
                "unit": "uIU/mL",
                "standard_low": 0.45,
                "standard_high": 4.50,
                "optimal_low": 1.00,
                "optimal_high": 2.50,
                "critical_low": 0.10,
                "critical_high": 10.00,
            },
            make_nd_headers(nd["id"]),
        ),
        201,
    )
    interpreted = validate_success(
        api.interpret_lab_order(
            order["id"],
            {"interpretation_summary": "euthyroid, optimal"},
            make_nd_headers(nd["id"]),
        )
    )
    assert interpreted["status"] == "INTERPRETED"

    response = api.cancel_lab_order(
        order["id"], {"reason": "billing error"}, make_nd_headers(nd["id"])
    )
    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value, 409)

    still = validate_success(api.get_lab_order(order["id"], make_nd_headers(nd["id"])))
    assert still["status"] == "INTERPRETED"

    refreshed = read_patient(api, patient["id"])
    assert refreshed["cash_charged_total_cents"] == 24000
    assert refreshed["cash_refunded_total_cents"] == 0


def test_credit_funded_panel_debits_exactly_the_panels_credit_cost(api):
    """PRD §3.4: "On success the membership's `lab_credits_consumed` grows by the
    panel's credit cost and `lab_credits_remaining` shrinks by the same amount,
    with `lab_credits_granted` untouched."
    PRD §3.4: "a cash order carries the catalogue price in `price_cents` with
    `lab_credit_cost` at 0, and a credit-funded order carries the catalogue
    credit cost in `lab_credit_cost` with `price_cents` at 0."

    Design: Difficulty/compensating_invariant/lab_credit_returned_exactly_on_lab_order_cancellation
    """
    nd = register_nd(api)
    patient = register_patient(api, nd["id"])
    open_membership(api, patient["id"], tier="CORE", cycle_start_date="2026-05-01")

    order = validate_success(
        api.create_lab_order(
            {
                "patient_id": patient["id"],
                "panel_code": "DUTCH_HORMONE",
                "funding_source": "MEMBERSHIP_CREDIT",
                "requested_collection_date": "2026-05-20",
                "cycle_day": 20,
            },
            make_nd_headers(nd["id"]),
        ),
        201,
    )

    assert order["lab_credit_cost"] == 2
    assert order["price_cents"] == 0
    assert order["status"] == "ORDERED"

    membership = read_membership(api, patient["id"])
    assert membership["lab_credits_granted"] == 2
    assert membership["lab_credits_consumed"] == 2
    assert membership["lab_credits_remaining"] == 0
    assert membership["lab_credits_forfeited"] == 0
    assert_membership_lab_credit_conservation(membership)
    assert read_patient(api, patient["id"])["cash_charged_total_cents"] == 0


def test_cancelling_a_credit_funded_panel_returns_exactly_what_it_consumed(api):
    """PRD §3.4: "A credit-funded order gives back precisely its
    `lab_credit_cost`: `lab_credits_consumed` decreases by that amount and
    `lab_credits_remaining` increases by the same amount, with
    `lab_credits_granted` deliberately untouched so the conservation identity
    survives."
    PRD §2.9: "For any membership, `lab_credits_granted` always equals
    `lab_credits_consumed` plus `lab_credits_remaining` plus
    `lab_credits_forfeited`."

    Design: Difficulty/compensating_invariant/lab_credit_returned_exactly_on_lab_order_cancellation
    """
    nd = register_nd(api)
    patient = register_patient(api, nd["id"])
    open_membership(api, patient["id"], tier="CORE", cycle_start_date="2026-05-01")
    order = validate_success(
        api.create_lab_order(
            {
                "patient_id": patient["id"],
                "panel_code": "DUTCH_HORMONE",
                "funding_source": "MEMBERSHIP_CREDIT",
                "requested_collection_date": "2026-05-20",
                "cycle_day": 20,
            },
            make_nd_headers(nd["id"]),
        ),
        201,
    )

    cancelled = validate_success(
        api.cancel_lab_order(
            order["id"], {"reason": "patient deferred"}, make_nd_headers(nd["id"])
        )
    )
    assert cancelled["status"] == "CANCELLED"

    membership = read_membership(api, patient["id"])
    assert membership["lab_credits_granted"] == 2
    assert membership["lab_credits_consumed"] == 0
    assert membership["lab_credits_remaining"] == 2
    assert membership["lab_credits_forfeited"] == 0
    assert_membership_lab_credit_conservation(membership)

    refreshed = read_patient(api, patient["id"])
    assert refreshed["cash_charged_total_cents"] == 0
    assert refreshed["cash_refunded_total_cents"] == 0
