"""Trade-in valuation, the credit ledger and the refurbishment fork."""
from test_helpers import (
    assert_instant,
    NON_EXISTENT_UUID,
    apply_tradein_credit,
    apply_tradein_credit_payload,
    assert_version_incremented,
    complete_maintenance_visit,
    list_all,
    new_facility,
    new_maintenance_visit,
    read_facility,
    read_order,
    read_price_breakdown,
    read_serialized_asset,
    receive_parts,
    refurb_certify,
    refurb_certify_payload,
    refurb_intake,
    resell_payload,
    reverse_trade_in_payload,
    set_logical_clock,
    setup_active_pm_program,
    setup_installed_order,
    suspend_facility,
    sunset_revision,
    trade_in_asset,
    validate_error,
    validate_success,
)

GRADE_A_VALUATION = 263_973
GRADE_B_VALUATION = 224_377


def _installed_treadmills(quantity=1, actual_labor_hours=3.0,
                          account_name="Ashgrove Athletic Club"):
    """One order of in-service treadmills at a fresh facility, invoiced."""
    ctx = setup_installed_order(
        preset="T900", quantity=quantity, actual_labor_hours=actual_labor_hours,
        facility_overrides={"account_name": account_name, "freight_zone": "Z1"},
        partner_overrides={"name": "Meridian Service Co"},
    )
    ctx["assets"] = sorted(ctx["assets"], key=lambda asset: asset["sequence_no"])
    ctx["asset"] = ctx["assets"][0]
    return ctx


def test_a_trade_in_can_be_undone_while_its_credit_is_still_unspent(
    api, order_planner_headers
):
    """The back edge returns the unit to service and withdraws the whole grant.

    The PRD states that on a reversal "the valuation is subtracted from the
    facility's `tradein_credit_granted_cents` and the balance recomputed,
    `trade_in_valuation_cents` and `declared_condition_grade` are both cleared back to
    null".

    Design: Difficulty/non_linear_state_machine/asset_trade_in_reverse_back_edge_then_locked_after_refurb_intake
    """
    ctx = _installed_treadmills()
    asset_id = ctx["asset"]["id"]

    returned = trade_in_asset(asset_id, declared_condition_grade="A")

    assert returned["status"] == "TRADE_IN_RETURNED"
    assert returned["trade_in_valuation_cents"] == GRADE_A_VALUATION
    assert returned["declared_condition_grade"] == "A"
    granted = read_facility(ctx["facility"]["id"])
    assert granted["tradein_credit_granted_cents"] == GRADE_A_VALUATION
    assert granted["tradein_credit_balance_cents"] == GRADE_A_VALUATION

    reversed_asset = validate_success(
        api.reverse_asset_trade_in(
            asset_id,
            reverse_trade_in_payload(
                reverse_reason="customer withdrew the trade-in offer"),
            order_planner_headers,
        )
    )

    assert reversed_asset["status"] == "IN_SERVICE"
    assert reversed_asset["trade_in_valuation_cents"] is None
    assert reversed_asset["declared_condition_grade"] is None
    assert reversed_asset["service_history_count"] == 0
    facility = read_facility(ctx["facility"]["id"])
    assert facility["tradein_credit_granted_cents"] == 0
    assert facility["tradein_credit_applied_cents"] == 0
    assert facility["tradein_credit_balance_cents"] == 0


def test_no_reverse_edge_exists_once_the_unit_has_entered_refurbishment(
    api, order_planner_headers
):
    """After intake the same reversal call is an invalid transition.

    The PRD states that the back edge moves the asset "`TRADE_IN_RETURNED →
    IN_SERVICE`" and that refurbishment intake moves it "`TRADE_IN_RETURNED →
    REFURB_INTAKE` with no body and no precondition beyond the state itself."

    Design: Difficulty/non_linear_state_machine/asset_trade_in_reverse_back_edge_then_locked_after_refurb_intake
    """
    ctx = _installed_treadmills()
    asset_id = ctx["asset"]["id"]
    trade_in_asset(asset_id, declared_condition_grade="A")
    validate_success(
        api.reverse_asset_trade_in(
            asset_id,
            reverse_trade_in_payload(
                reverse_reason="customer withdrew the trade-in offer"),
            order_planner_headers,
        )
    )
    regraded = trade_in_asset(asset_id, declared_condition_grade="B")
    assert regraded["trade_in_valuation_cents"] == GRADE_B_VALUATION
    intake = refurb_intake(asset_id)
    assert intake["status"] == "REFURB_INTAKE"

    response = api.reverse_asset_trade_in(
        asset_id,
        reverse_trade_in_payload(reverse_reason="customer withdrew the trade-in offer"),
        order_planner_headers,
    )

    validate_error(response, "ERR_INVALID_STATE_TRANSITION", 409)
    asset = read_serialized_asset(asset_id)
    assert asset["status"] == "REFURB_INTAKE"
    assert asset["trade_in_valuation_cents"] == GRADE_B_VALUATION
    assert asset["declared_condition_grade"] == "B"
    assert_instant(asset["warranty_starts_at"], "2026-08-01T00:00:00Z", "warranty_starts_at")
    assert_instant(asset["warranty_expires_at"], "2029-07-31T00:00:00Z", "warranty_expires_at")
    facility = read_facility(ctx["facility"]["id"])
    assert facility["tradein_credit_granted_cents"] == GRADE_B_VALUATION
    assert facility["tradein_credit_applied_cents"] == 0
    assert facility["tradein_credit_balance_cents"] == GRADE_B_VALUATION


def _pair_with_one_traded_and_credit_applied():
    """A two-unit order with one unit traded in and 100000 cents already spent."""
    ctx = _installed_treadmills(quantity=2, actual_labor_hours=4.5,
                                account_name="Brookside Athletic Club")
    assert ctx["order"]["final_total_cents"] == 1_133_932
    traded = trade_in_asset(ctx["assets"][0]["id"], declared_condition_grade="A")
    assert traded["trade_in_valuation_cents"] == GRADE_A_VALUATION
    ctx["captured_version"] = read_facility(ctx["facility"]["id"])["version"]
    ctx["order"] = apply_tradein_credit(
        ctx["order"]["id"], 100_000,
        expected_facility_version=ctx["captured_version"],
    )
    return ctx


def test_a_reverse_is_refused_while_part_of_the_grant_is_already_spent(
    api, order_planner_headers
):
    """Spending 100000 cents leaves too little balance to unwind the grant.

    The PRD states that the single precondition of the reversal is "that the granted
    credit must still be unspent: the facility's `tradein_credit_balance_cents` must
    be greater than or equal to the asset's `trade_in_valuation_cents`, otherwise the
    reversal is refused with `ERR_TRADEIN_CREDIT_ALREADY_APPLIED`".

    Design: Difficulty/compensating_invariant/tradein_credit_ledger_conserved_under_blocked_and_allowed_reverse
    """
    ctx = _pair_with_one_traded_and_credit_applied()
    assert ctx["order"]["tradein_credit_applied_cents"] == 100_000
    assert ctx["order"]["amount_due_cents"] == 1_033_932
    spent = read_facility(ctx["facility"]["id"])
    assert spent["tradein_credit_granted_cents"] == GRADE_A_VALUATION
    assert spent["tradein_credit_applied_cents"] == 100_000
    assert spent["tradein_credit_balance_cents"] == 163_973
    assert_version_incremented(spent["version"], ctx["captured_version"])

    response = api.reverse_asset_trade_in(
        ctx["assets"][0]["id"],
        reverse_trade_in_payload(reverse_reason="customer withdrew the trade-in offer"),
        order_planner_headers,
    )

    validate_error(response, "ERR_TRADEIN_CREDIT_ALREADY_APPLIED", 409)
    asset = read_serialized_asset(ctx["assets"][0]["id"])
    assert asset["status"] == "TRADE_IN_RETURNED"
    assert asset["trade_in_valuation_cents"] == GRADE_A_VALUATION
    unchanged = read_facility(ctx["facility"]["id"])
    assert unchanged["tradein_credit_granted_cents"] == GRADE_A_VALUATION
    assert unchanged["tradein_credit_applied_cents"] == 100_000
    assert unchanged["tradein_credit_balance_cents"] == 163_973
    assert read_order(ctx["order"]["id"])["amount_due_cents"] == 1_033_932


def test_a_second_grant_lifts_the_balance_and_lets_the_reverse_through(
    api, order_planner_headers
):
    """Once the balance covers the grant again the ledger unwinds exactly.

    The PRD states that "After every mutation the balance must be greater than or
    equal to zero, and the granted total must equal the applied total plus the
    balance."

    Design: Difficulty/compensating_invariant/tradein_credit_ledger_conserved_under_blocked_and_allowed_reverse
    """
    ctx = _pair_with_one_traded_and_credit_applied()
    validate_error(
        api.reverse_asset_trade_in(
            ctx["assets"][0]["id"],
            reverse_trade_in_payload(
                reverse_reason="customer withdrew the trade-in offer"),
            order_planner_headers,
        ),
        "ERR_TRADEIN_CREDIT_ALREADY_APPLIED", 409,
    )
    second = trade_in_asset(ctx["assets"][1]["id"], declared_condition_grade="A")
    assert second["trade_in_valuation_cents"] == GRADE_A_VALUATION
    assert read_facility(ctx["facility"]["id"])[
        "tradein_credit_granted_cents"
    ] == 527_946

    reversed_asset = validate_success(
        api.reverse_asset_trade_in(
            ctx["assets"][0]["id"],
            reverse_trade_in_payload(
                reverse_reason="customer withdrew the trade-in offer"),
            order_planner_headers,
        )
    )

    assert reversed_asset["status"] == "IN_SERVICE"
    assert reversed_asset["trade_in_valuation_cents"] is None
    assert reversed_asset["declared_condition_grade"] is None
    facility = read_facility(ctx["facility"]["id"])
    assert facility["tradein_credit_granted_cents"] == GRADE_A_VALUATION
    assert facility["tradein_credit_applied_cents"] == 100_000
    assert facility["tradein_credit_balance_cents"] == 163_973
    assert facility["tradein_credit_granted_cents"] == (
        facility["tradein_credit_applied_cents"]
        + facility["tradein_credit_balance_cents"]
    )
    assert facility["tradein_credit_balance_cents"] >= 0
    order = read_order(ctx["order"]["id"])
    assert order["final_total_cents"] == 1_133_932
    assert order["amount_due_cents"] == 1_033_932, (
        "spent credit is never clawed back by the reversal"
    )
    held = read_serialized_asset(ctx["assets"][1]["id"])
    assert held["status"] == "TRADE_IN_RETURNED"
    assert held["trade_in_valuation_cents"] == GRADE_A_VALUATION


def test_the_residual_floor_is_applied_before_the_condition_multiplier(api):
    """An old, well-serviced unit and an older untouched one price differently.

    The PRD states that "the 0.10 floor is applied to the residual" before the
    condition and console multipliers, "so a floored asset can still be discounted
    further by a `C` grade or by an unsupported console, and the effective proportion
    of list price can legitimately land below 0.10."

    Design: Corner/calculations/trade_in_residual_floor_is_applied_before_the_grade_multiplier
    """
    ctx = _installed_treadmills(quantity=2, actual_labor_hours=4.5,
                                account_name="Ridgeline Fitness Group")
    partner_id = ctx["partner"]["id"]
    program = setup_active_pm_program(ctx["facility"]["id"], partner_id, tier="PRO",
                                      visit_interval_days=90)
    receive_parts(partner_id, 10)
    serviced, untouched = ctx["assets"][0], ctx["assets"][1]
    for scheduled_date, labor_hours in (("2026-09-20T09:00:00Z", 2.0),
                                        ("2026-10-18T09:00:00Z", 0.75)):
        visit = new_maintenance_visit(program["id"], serviced["id"], partner_id,
                                      scheduled_date=scheduled_date, reserved_units=3)
        complete_maintenance_visit(visit["id"], partner_id, labor_hours=labor_hours)
    history = read_serialized_asset(serviced["id"])
    assert history["service_history_count"] == 2
    assert history["accrued_service_labor_hours"] == 2.75

    set_logical_clock("2029-08-01T00:00:00Z")
    graded_c = trade_in_asset(serviced["id"], declared_condition_grade="C")

    assert graded_c["status"] == "TRADE_IN_RETURNED"
    assert graded_c["trade_in_valuation_cents"] == 87_351, (
        "three whole years and two visits leave a residual of 0.280"
    )
    after_first = read_facility(ctx["facility"]["id"])
    assert after_first["tradein_credit_granted_cents"] == 87_351
    assert after_first["tradein_credit_applied_cents"] == 0
    assert after_first["tradein_credit_balance_cents"] == 87_351

    set_logical_clock("2032-08-01T00:00:00Z")
    graded_a = trade_in_asset(untouched["id"], declared_condition_grade="A")

    assert graded_a["trade_in_valuation_cents"] == 47_995, (
        "a raw residual of 0.07 is raised to the 0.10 floor"
    )
    facility = read_facility(ctx["facility"]["id"])
    assert facility["tradein_credit_granted_cents"] == 135_346
    assert facility["tradein_credit_balance_cents"] == 135_346
    for asset_id in (serviced["id"], untouched["id"]):
        assert read_serialized_asset(asset_id)[
            "connectivity_support_status"
        ] == "NOT_APPLICABLE"


def test_a_console_past_its_support_horizon_cannot_be_certified_as_refurbished(
    api, service_ops_admin_headers
):
    """The shop refuses to certify a rower whose firmware commitment has run out.

    The PRD states that the precondition of certification "is that, if the model is
    connected, `firmware_support_expires_at` must be null or strictly after the
    current logical clock, otherwise `ERR_FIRMWARE_SUPPORT_EXPIRED` — the business
    will not certify a console it can no longer patch."

    Design: Corner/state_machines/refurb_certify_is_guarded_by_the_console_support_horizon
    """
    ctx = setup_installed_order(
        preset="C700", quantity=1,
        facility_overrides={"account_name": "Summit Athletic Club",
                            "freight_zone": "Z1"},
        partner_overrides={"name": "Meridian Service Co"},
    )
    revision = sunset_revision(ctx["revision"]["id"],
                               sunset_reason="platform refresh announced to the dealer network")
    assert_instant(revision["firmware_support_until"], "2031-07-31T00:00:00Z", "firmware_support_until")
    asset_id = ctx["asset"]["id"]
    set_logical_clock("2031-08-01T00:00:00Z")
    traded = trade_in_asset(asset_id, declared_condition_grade="B")
    assert traded["trade_in_valuation_cents"] == 53_677, (
        "five years of decay, grade B and the unsupported-console multiplier"
    )
    assert refurb_intake(asset_id)["status"] == "REFURB_INTAKE"

    response = api.refurb_certify_asset(asset_id, refurb_certify_payload("B"),
                                        service_ops_admin_headers)

    validate_error(response, "ERR_FIRMWARE_SUPPORT_EXPIRED", 409)
    asset = read_serialized_asset(asset_id)
    assert asset["status"] == "REFURB_INTAKE"
    assert asset["refurb_grade"] is None
    assert_instant(asset["firmware_support_expires_at"], "2031-07-31T00:00:00Z", "firmware_support_expires_at")
    assert_instant(asset["warranty_expires_at"], "2029-07-31T00:00:00Z", "warranty_expires_at")
    assert asset["connectivity_support_status"] == "SUNSET_TRACKED"
    assert asset["support_gap_days"] == 0
    facility = read_facility(ctx["facility"]["id"])
    assert facility["tradein_credit_granted_cents"] == 53_677
    assert facility["tradein_credit_balance_cents"] == 53_677


def test_a_refurbished_unit_is_resold_only_to_an_active_buyer_facility(
    api, order_planner_headers
):
    """An unknown buyer is a 404, a suspended buyer a 409, and the active one wins.

    The PRD states that on resale "the buyer facility's `status` must be `ACTIVE`
    (`ERR_FACILITY_SUSPENDED`)" and that resale "rewrites the asset's `facility_id` to
    the buyer facility and resets both `warranty_starts_at` and `warranty_expires_at`
    to null".

    Design: Corner/endpoints/resell_relinks_the_asset_to_an_active_buyer_facility_only
    """
    ctx = _installed_treadmills()
    asset_id = ctx["asset"]["id"]
    line_id = ctx["line"]["id"]
    trade_in_asset(asset_id, declared_condition_grade="B")
    refurb_intake(asset_id)
    certified = refurb_certify(asset_id, refurb_grade="B")
    assert certified["status"] == "REFURB_CERTIFIED"
    buyer = new_facility(account_name="Riverside Athletic Club", freight_zone="Z2")
    rejected_buyer = new_facility(account_name="Summit Wellness", freight_zone="Z3")
    suspend_facility(rejected_buyer["id"],
                     suspend_reason="account placed on credit hold")

    validate_error(
        api.resell_asset(asset_id, resell_payload(NON_EXISTENT_UUID),
                         order_planner_headers),
        "ERR_FACILITY_NOT_FOUND", 404,
    )
    validate_error(
        api.resell_asset(asset_id, resell_payload(rejected_buyer["id"]),
                         order_planner_headers),
        "ERR_FACILITY_SUSPENDED", 409,
    )
    still_held = read_serialized_asset(asset_id)
    assert still_held["status"] == "REFURB_CERTIFIED"
    assert still_held["facility_id"] == ctx["facility"]["id"]

    resold = validate_success(
        api.resell_asset(asset_id, resell_payload(buyer["id"]), order_planner_headers)
    )

    assert resold["status"] == "RESOLD"
    assert resold["facility_id"] == buyer["id"]
    assert resold["warranty_starts_at"] is None
    assert resold["warranty_expires_at"] is None
    assert resold["refurb_grade"] == "B"
    assert resold["order_line_id"] == line_id, "the build provenance survives"
    assert len(list_all(api.list_serialized_assets,
                        {"facility_id": buyer["id"]})) == 1
    assert list_all(api.list_serialized_assets,
                    {"facility_id": ctx["facility"]["id"]}) == []


def test_the_exact_credit_balance_can_be_applied_but_not_one_cent_more(
    api, order_planner_headers
):
    """Spending the balance to zero is allowed; the next cent is refused.

    The PRD states that the requested `amount_cents` "must be at least 1, must not
    exceed the facility's `tradein_credit_balance_cents`, and must not exceed the
    order's outstanding total" and that "A request outside those bounds is
    `ERR_INSUFFICIENT_TRADEIN_CREDIT`."

    Design: Corner/validations/applying_the_exact_credit_balance_succeeds_then_one_more_cent_is_refused
    """
    ctx = _installed_treadmills()
    assert ctx["order"]["final_total_cents"] == 573_622
    assert ctx["order"]["amount_due_cents"] == 573_622
    traded = trade_in_asset(ctx["asset"]["id"], declared_condition_grade="B")
    assert traded["trade_in_valuation_cents"] == GRADE_B_VALUATION

    order = apply_tradein_credit(ctx["order"]["id"], GRADE_B_VALUATION,
                                 facility_id=ctx["facility"]["id"])

    assert order["tradein_credit_applied_cents"] == GRADE_B_VALUATION
    assert order["final_total_cents"] == 573_622
    assert order["amount_due_cents"] == 349_245
    spent = read_facility(ctx["facility"]["id"])
    assert spent["tradein_credit_granted_cents"] == GRADE_B_VALUATION
    assert spent["tradein_credit_applied_cents"] == GRADE_B_VALUATION
    assert spent["tradein_credit_balance_cents"] == 0

    response = api.apply_tradein_credit(
        ctx["order"]["id"], apply_tradein_credit_payload(1, spent["version"]),
        order_planner_headers,
    )

    validate_error(response, "ERR_INSUFFICIENT_TRADEIN_CREDIT", 402)
    unchanged = read_facility(ctx["facility"]["id"])
    assert unchanged["tradein_credit_granted_cents"] == GRADE_B_VALUATION
    assert unchanged["tradein_credit_applied_cents"] == GRADE_B_VALUATION
    assert unchanged["tradein_credit_balance_cents"] == 0
    assert read_order(ctx["order"]["id"])["amount_due_cents"] == 349_245
    breakdown = read_price_breakdown(ctx["order"]["id"])
    assert breakdown["tradein_credit_applied_cents"] == GRADE_B_VALUATION
    assert breakdown["amount_due_cents"] == 349_245


def test_applying_credit_pins_the_facility_version_not_the_order_version(
    api, order_planner_headers
):
    """The second application must re-read the facility the first one bumped.

    The PRD states that applying credit carries "the `amount_cents` to apply and the
    `expected_facility_version` pinning the facility's credit-ledger snapshot" and
    that on success "the facility's `version` is incremented by one."

    Design: Corner/complexity_layers/trade_in_credit_application_rejects_a_stale_facility_version
    """
    ctx = _installed_treadmills(quantity=2, account_name="Lakeside Fitness Collective")
    assert ctx["order"]["final_total_cents"] == 1_120_619
    assert ctx["order"]["billing_status"] == "INVOICED"
    traded = trade_in_asset(ctx["assets"][0]["id"], declared_condition_grade="A")
    assert traded["trade_in_valuation_cents"] == GRADE_A_VALUATION
    captured_version = read_facility(ctx["facility"]["id"])["version"]

    first = validate_success(
        api.apply_tradein_credit(
            ctx["order"]["id"],
            apply_tradein_credit_payload(100_000, captured_version),
            order_planner_headers,
        )
    )

    assert first["tradein_credit_applied_cents"] == 100_000
    assert first["amount_due_cents"] == 1_020_619
    after_first = read_facility(ctx["facility"]["id"])
    assert after_first["tradein_credit_applied_cents"] == 100_000
    assert after_first["tradein_credit_balance_cents"] == 163_973
    assert_version_incremented(after_first["version"], captured_version)

    response = api.apply_tradein_credit(
        ctx["order"]["id"], apply_tradein_credit_payload(50_000, captured_version),
        order_planner_headers,
    )

    validate_error(response, "ERR_STALE_VERSION", 412)
    stale = read_facility(ctx["facility"]["id"])
    assert stale["tradein_credit_applied_cents"] == 100_000
    assert stale["tradein_credit_balance_cents"] == 163_973
    assert read_order(ctx["order"]["id"])["amount_due_cents"] == 1_020_619

    retried = validate_success(
        api.apply_tradein_credit(
            ctx["order"]["id"],
            apply_tradein_credit_payload(50_000, stale["version"]),
            order_planner_headers,
        )
    )

    assert retried["tradein_credit_applied_cents"] == 150_000
    assert retried["amount_due_cents"] == 970_619
    assert retried["final_total_cents"] == 1_120_619
    assert read_facility(ctx["facility"]["id"])[
        "tradein_credit_balance_cents"
    ] == 113_973
