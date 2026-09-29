"""Reads, filters, the bulk sweep and the conditional close.

The filter parameters are named after the attribute they filter on, and they
compose with one another and with paging. The sweep skips rather than fails on
notices that are ineligible, and close is refused until the money is settled.
"""

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_rate_program,
    factories,
    make_dispute_reviewer_headers,
    make_pricing_analyst_headers,
    make_terminal_operator_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import fixtures as fx

ANALYST = make_pricing_analyst_headers()

CLOCK = "2026-01-10T08:00:00Z"

DENSE_LINE = {
    # 4 x (48.0 x 40.0 x 48.0) is 213.33 cubic feet, so 400 pounds is 1.88 pcf,
    # which the standard bracket table rates at class 300.  Declaring that same
    # class is what makes the capture below merely confirming.
    "line_no": 1,
    "declared_class_code": 300,
    "declared_weight_lb": 400,
    "pieces": 4,
    "declared_length_in": 48.0,
    "declared_width_in": 40.0,
    "declared_height_in": 48.0,
}


def _list_programs(**params):
    params.setdefault("limit", 100)
    return validate_paginated(api_client.list_rate_programs(ANALYST, params=params))


def _list_capture_events(headers=None, **params):
    return validate_paginated(
        api_client.list_capture_events(headers or ANALYST, params=params)
    )


def _list_notices(**params):
    return validate_paginated(
        api_client.list_correction_notices(ANALYST, params=params)
    )


# ==========================================================================
# Collection reads
# ==========================================================================


def test_pricing_programs_are_readable_by_id_and_filterable_by_attribute():
    """Three programs for one shipper page two at a time and filter independently.

    PRD: "Pricing programs may be filtered by `customer_id`, `status`,
    `program_type` and `pinned_tariff_version_id`."

    Design: Corner/endpoints/rate_program_crud_round_trip_with_filters_and_paging
    """
    fx.set_clock(CLOCK)
    standard = fx.create_published_standard()
    acme = fx.create_customer(account_code="ACME", name="Acme Mfg")
    beta = fx.create_customer(account_code="BETA", name="Beta Foods")
    fx.create_approved_rate_program(
        acme["id"],
        program_type="DENSITY_BASED",
        base_rate_per_cwt_cents=3900,
        discount_pct=0.3,
        min_charge_cents=11000,
    )
    modeling = fx.create_rate_program(
        acme["id"],
        program_type="FAK",
        base_rate_per_cwt_cents=4000,
        discount_pct=0.4,
        min_charge_cents=12000,
        fak_class_code=92.5,
    )
    other = fx.create_rate_program(
        beta["id"],
        program_type="CLASS_BASED",
        base_rate_per_cwt_cents=4100,
        discount_pct=0.2,
        min_charge_cents=9000,
    )

    drafted = validate_success(
        api_client.create_rate_program(
            factories.create_rate_program_payload(acme["id"]), ANALYST
        ),
        expected_status=201,
    )
    assert drafted["status"] == "MODELING"
    assert drafted["base_rate_per_cwt_cents"] == 4200
    assert drafted["discount_pct"] == 0.35
    assert drafted["min_charge_cents"] == 12500
    assert drafted["fak_class_code"] is None
    fx.approve_rate_program(drafted["id"])
    fx.activate_rate_program(drafted["id"], acme["id"])

    read_back = fx.get_rate_program(drafted["id"])
    assert_rate_program(read_back)
    assert read_back["status"] == "ACTIVE"
    assert read_back["pinned_tariff_version_id"] == standard["tariff_version_id"]
    assert read_back["effective_from"].startswith("2026-01-10T08:00:00")

    page, meta = _list_programs(customer_id=acme["id"], limit=2, offset=0)
    assert len(page) == 2
    assert meta["total_count"] == 3
    assert meta["limit"] == 2
    assert meta["offset"] == 0
    assert meta["has_more"] is True

    active_rows, _active_meta = _list_programs(customer_id=acme["id"], status="ACTIVE")
    assert [row["id"] for row in active_rows] == [drafted["id"]]

    fak_rows, _fak_meta = _list_programs(
        customer_id=acme["id"], program_type="FAK", status="MODELING"
    )
    assert [row["id"] for row in fak_rows] == [modeling["id"]]

    all_acme, _all_meta = _list_programs(customer_id=acme["id"])
    assert other["id"] not in [row["id"] for row in all_acme], (
        "the other shipper's program never appears under this customer_id filter"
    )


def test_a_capture_and_the_notice_it_produced_resolve_from_either_side():
    """The link is navigable both ways, and the confirming capture links to nothing.

    PRD: "Capture events may be filtered by `shipment_id` and `terminal_id`."

    Design: Corner/endpoints/notice_and_capture_cross_reference_filters_resolve_both_sides
    """
    env = fx.setup_pricing_environment(clock=CLOCK)
    second_terminal = fx.create_terminal(code="TRM2", name="Dallas Dock")
    reclassed = fx.setup_billed_shipment(env=env, pro_number="PROE030")
    # A dock capture is only permitted when the addressed shipment's
    # `origin_terminal_id` equals the operator's own `X-User-ID`, so the shipment
    # captured at the second terminal must be tendered against that terminal.
    second_env = dict(env)
    second_env["terminal_id"] = second_terminal["id"]
    second_env["operator_headers"] = make_terminal_operator_headers(second_terminal["id"])
    confirming = fx.setup_billed_shipment(
        env=second_env, pro_number="PROE031", line_specs=[DENSE_LINE]
    )

    first_capture = fx.record_capture(
        reclassed["shipment_id"], env["terminal_id"], 520, fx.single_line_measurement(520)
    )
    second_capture = fx.record_capture(
        confirming["shipment_id"],
        second_terminal["id"],
        400,
        fx.single_line_measurement(400),
        device_type="SCALE",
    )

    by_terminal, _meta = _list_capture_events(terminal_id=env["terminal_id"])
    assert [row["id"] for row in by_terminal] == [first_capture["id"]]
    assert by_terminal[0]["capture_sequence"] == 1

    by_basis, _basis_meta = _list_notices(basis_capture_event_id=first_capture["id"])
    assert len(by_basis) == 1
    assert by_basis[0]["shipment_id"] == reclassed["shipment_id"]
    assert by_basis[0]["origin"] == "AUTOMATED_CAPTURE"
    assert by_basis[0]["notice_type"] == "BOTH"

    unrelated, unrelated_meta = _list_notices(
        basis_capture_event_id=second_capture["id"]
    )
    assert unrelated == []
    assert unrelated_meta["total_count"] == 0

    as_reviewer, _reviewer_meta = _list_capture_events(
        make_dispute_reviewer_headers("rev-1"), shipment_id=confirming["shipment_id"]
    )
    assert [row["id"] for row in as_reviewer] == [second_capture["id"]]
    assert as_reviewer[0]["captured_by_user_id"] == second_terminal["id"]
    assert as_reviewer[0]["triggered_reclass"] is False
    assert as_reviewer[0]["variance_pct"] == 0.00
    assert as_reviewer[0]["triggered_reweigh"] is False

    confirming_shipment = fx.get_shipment(confirming["shipment_id"])
    reclassed_shipment = fx.get_shipment(reclassed["shipment_id"])
    assert confirming_shipment["class_status"] == "CAPTURED"
    assert confirming_shipment["open_notice_count"] == 0
    assert reclassed_shipment["class_status"] == "RECLASS_PENDING"
    assert reclassed_shipment["open_notice_count"] == 1


def test_a_shipper_read_shows_a_strike_that_no_index_has_absorbed_yet():
    """An issued notice is a strike but is not yet a contributing notice.

    PRD: "A notice contributes to either index only when it has been resolved —
    meaning its `resolved_at` is stamped and its `status` is `UPHELD` or
    `PARTIALLY_OVERTURNED`."

    Design: Corner/endpoints/customer_read_exposes_strikes_without_index_contribution
    """
    scenario = fx.setup_issued_notice_scenario(pro_number="PROE010")

    customer = fx.get_customer(scenario["customer_id"])
    notice = fx.get_notice(scenario["notice_id"])

    assert customer["offender_strike_count"] == 1
    assert customer["liability_index_rolling"] == 0.00
    assert customer["liability_index_lifetime"] == 0.00
    assert customer["offender_tier"] == "TIER_0"
    assert customer["dispute_window_days"] == 30
    assert customer["education_status"] == "NONE", (
        "one strike is short of the default threshold of three"
    )
    assert customer["education_threshold_strikes"] == 3
    assert customer["active_program_type"] == "CLASS_BASED"
    assert notice["dispute_deadline_at"].startswith("2026-02-09T08:00:00")


# ==========================================================================
# The bulk sweep and the conditional close
# ==========================================================================


def test_the_sweep_upholds_only_the_expired_undisputed_notice():
    """Three issued notices, one eligible; the other two are skipped, not failed.

    PRD: "An operations sweep, restricted to a `PricingAnalyst`, walks every notice
    in `status` `ISSUED` whose `dispute_deadline_at` is strictly in the past
    relative to the current logical instant and against which no dispute exists at
    all, and moves each one `ISSUED → UPHELD` with `resolved_at` stamped at the
    sweep instant."

    Design: Corner/endpoints/notice_sweep_upholds_only_expired_undisputed_notices
    """
    fx.set_clock(CLOCK)
    standard = fx.create_published_standard()
    terminal = fx.create_terminal()
    scenarios = []
    for index, account_code in enumerate(["ACME1", "ACME2", "ACME3"], start=1):
        customer = fx.create_customer(account_code=account_code, name=f"Acme {index}")
        fx.create_active_rate_program(customer["id"])
        env = {
            "customer_id": customer["id"],
            "terminal_id": terminal["id"],
            "commodity_profile_id": standard["commodity_profile_id"],
        }
        scenarios.append(
            fx.setup_captured_shipment_with_draft_notice(
                env=env, pro_number=f"PROS00{index}"
            )
        )

    expired = scenarios[0]
    disputed = scenarios[1]
    still_open = scenarios[2]
    fx.issue_notice(expired["notice_id"])
    fx.issue_notice(disputed["notice_id"])
    fx.file_dispute(disputed["notice_id"], disputed["customer_id"])
    fx.set_clock("2026-02-08T00:00:00Z")
    fx.issue_notice(still_open["notice_id"])
    fx.set_clock("2026-02-10T00:00:00Z")

    result = fx.sweep_notices()

    assert result["swept_count"] == 1, (
        f"only the expired undisputed notice is eligible, "
        f"got {result['swept_count']}"
    )
    assert result["upheld_notice_ids"] == [expired["notice_id"]]
    upheld = fx.get_notice(expired["notice_id"])
    assert upheld["status"] == "UPHELD"
    assert upheld["resolved_at"].startswith("2026-02-10T00:00:00")
    assert upheld["applied_delta_cents"] == 28314, (
        "the sweep moves no money"
    )
    assert fx.get_notice(disputed["notice_id"])["status"] == "DISPUTED"
    assert fx.get_notice(disputed["notice_id"])["resolved_at"] is None
    third = fx.get_notice(still_open["notice_id"])
    assert third["status"] == "ISSUED"
    assert third["dispute_deadline_at"].startswith("2026-03-10T00:00:00")
    for scenario in scenarios:
        shipment = fx.get_shipment(scenario["shipment_id"])
        assert shipment["assessed_total_cents"] == 45314
        assert shipment["billing_status"] == "REBILLED"
    assert fx.sweep_notices()["swept_count"] == 0, (
        "a second sweep at the same instant finds nothing left to close"
    )


def test_closing_requires_billing_first_and_then_locks_out_the_dock():
    """Close is refused while UNBILLED and freezes the shipment once it succeeds.

    PRD: "It requires that the shipment's `open_notice_count` is 0 and that its
    `billing_status` is `BILLED`, `REBILLED` or `CREDITED`; closing a shipment that
    is still `UNBILLED` is rejected with `ERR_SHIPMENT_NOT_BILLED`."

    Design: Corner/endpoints/close_is_conditional_on_billing_and_locks_out_later_capture
    """
    env = fx.setup_pricing_environment(clock=CLOCK)
    tendered = fx.setup_shipment_with_lines(env, "PROE020")

    too_early = api_client.close_shipment(tendered["shipment_id"], {}, ANALYST)
    validate_error(
        too_early, ApiErrorId.ERR_SHIPMENT_NOT_BILLED.value, expected_status=409
    )
    assert fx.get_shipment(tendered["shipment_id"])["billing_status"] == "UNBILLED"

    billed = fx.bill_shipment(tendered["shipment_id"])
    assert billed["original_charge_cents"] == 12500
    assert billed["billing_status"] == "BILLED"

    closed = fx.close_shipment(tendered["shipment_id"])
    assert closed["billing_status"] == "CLOSED"
    assert closed["class_status"] == "CLASS_CONFIRMED", (
        "freight that was never measured confirms straight from DECLARED"
    )

    late_capture = api_client.create_capture_event(
        factories.create_capture_event_payload(
            tendered["shipment_id"], 520, fx.single_line_measurement(520)
        ),
        make_terminal_operator_headers(env["terminal_id"]),
    )
    validate_error(
        late_capture, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value, expected_status=409
    )
    rows, meta = _list_capture_events(shipment_id=tendered["shipment_id"])
    assert rows == []
    assert meta["total_count"] == 0
    terminal = fx.get_terminal(env["terminal_id"])
    assert terminal["captures_since_calibration"] == 0
    line = fx.get_shipment_line(tendered["line_ids"][0])
    assert line["measured_weight_lb"] is None
    assert fx.get_shipment(tendered["shipment_id"])["assessed_total_cents"] == 12500
