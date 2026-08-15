"""Trade-in appraisals: provisional vs final credit, acceptance cascade, resale loop (PRD §3.3, §3.9)."""
from test_helpers import (
    TEST_USERS,
    accept_trade_in,
    assert_order_money_conservation,
    assert_trade_in_appraisal,
    canonical_community_scenario,
    confirm_order,
    create_application,
    create_customer,
    create_offered_trade_in,
    create_trade_in,
    get_success_data,
    inspect_trade_in,
    new_order_scenario,
    progress_to_site_approved,
    submit_application,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
CONSULTANT = TEST_USERS["consultant_headers"]
APPRAISER = TEST_USERS["appraiser_headers"]


# --- provisional vs final credit ------------------------------------------------

def test_provisional_credit_from_declared_year_and_condition(api):
    """PRD §3.9: "At creation the appraisal carries a `provisional_credit_cents`
    computed purely from the declarations and the logical clock. The depreciable
    age is the clock's current calendar year minus the declared model year minus
    a ten-year grace, floored at zero. The condition base is $18,000.00 for grade
    `A` (1,800,000 cents), $12,000.00 for `B` (1,200,000 cents), and $6,000.00
    for `C` (600,000 cents); that base is depreciated by three percent per year
    of depreciable age, rounded half-up to whole cents, and the provisional
    credit is the greater of that depreciated figure and a $2,000.00 floor
    (200,000 cents). The provisional figure takes no notice of any inspected
    value."

    Design: Difficulty/dual_variant_calc/provisional_vs_final_trade_in_credit
    """
    scn = new_order_scenario(placement_type="COMMUNITY_LOT", agreed_home_price_cents=9_200_000, double_wide=True)
    appraisal = create_trade_in(scn, declared_model_year=2012, declared_condition="B")
    assert_trade_in_appraisal(appraisal)
    # age = 2026 - 2012 - 10 = 4; 1,200,000 x (1 - 0.03 x 4) = 1,056,000.
    assert appraisal["provisional_credit_cents"] == 1_056_000, f"got {appraisal['provisional_credit_cents']}"


def test_final_credit_diverges_from_provisional(api):
    """PRD §3.9: "An `Appraiser` then inspects the trade-in, recording
    `appraised_value_cents`, the `reconditioning_cost_cents` needed to bring it
    to retail-ready, and the confirmed `condition_grade`; inspection moves the
    appraisal `DRAFT` → `INSPECTED` and fixes the `final_credit_cents` as the
    appraised value minus the reconditioning cost, floored at zero — a figure
    that generally diverges from the provisional credit."

    Design: Difficulty/dual_variant_calc/provisional_vs_final_trade_in_credit
    """
    scn = new_order_scenario(placement_type="COMMUNITY_LOT", agreed_home_price_cents=9_200_000, double_wide=True)
    appraisal = create_trade_in(scn, declared_model_year=2012, declared_condition="B")
    assert appraisal["provisional_credit_cents"] == 1_056_000

    inspected = inspect_trade_in(scn, appraisal, appraised_value_cents=1_500_000, reconditioning_cost_cents=400_000, condition_grade="B")
    assert inspected["status"] == "INSPECTED"
    # final = max(0, 1,500,000 - 400,000) = 1,100,000; provisional was 1,056,000.
    assert inspected["final_credit_cents"] == 1_100_000, f"got {inspected['final_credit_cents']}"
    assert inspected["final_credit_cents"] != inspected["provisional_credit_cents"]


def test_provisional_credit_floor_clamp(api):
    """PRD §3.9: "that base is depreciated by three percent per year of
    depreciable age, rounded half-up to whole cents, and the provisional credit
    is the greater of that depreciated figure and a $2,000.00 floor (200,000
    cents)."

    Design: Corner/calculations/trade_in_provisional_floor
    """
    scn = new_order_scenario(placement_type="PRIVATE_LAND", agreed_home_price_cents=4_200_000)
    appraisal = create_trade_in(scn, declared_model_year=1990, declared_condition="C")
    # age = 2026 - 1990 - 10 = 26; 600,000 x (1 - 0.03 x 26) = 132,000 < floor.
    assert appraisal["provisional_credit_cents"] == 200_000, (
        f"raw decayed value 132,000 must clamp up to the 200,000 floor, got {appraisal['provisional_credit_cents']}"
    )


# --- counter-offer loop ------------------------------------------------------------

def test_trade_in_counter_offer_supersedes(api, consultant_headers):
    """PRD §3.9: "A buyer trading in a used home gets a `TradeInAppraisal` opened
    by a `SalesConsultant` against the order receiving the credit, naming the
    `model_id` of the traded home, the customer-declared `declared_model_year`,
    the customer-declared `declared_condition` of `A`, `B`, or `C`, and
    optionally a `supersedes_appraisal_id` for the counter-offer loop — the
    referenced appraisal must belong to the same order and be `OFFERED`, and
    opening the counter-appraisal pushes it to `SUPERSEDED`."

    Design: Corner/state_machines/trade_in_counter_offer_supersedes
    """
    scn = new_order_scenario(placement_type="PRIVATE_LAND", agreed_home_price_cents=4_200_000)
    ta1 = create_offered_trade_in(scn)
    assert ta1["status"] == "OFFERED"

    ta2 = create_trade_in(scn, declared_model_year=2012, declared_condition="A", supersedes_appraisal_id=ta1["id"])
    assert ta2["status"] == "DRAFT", "the counter-offer opens a fresh DRAFT appraisal"

    ta1_view = get_success_data(api.get_trade_in_appraisal(ta1["id"], consultant_headers))
    assert ta1_view["status"] == "SUPERSEDED"

    rows, meta = validate_paginated(
        api.list_trade_in_appraisals(consultant_headers, params={"supersedes_appraisal_id": ta1["id"]})
    )
    assert meta["total_count"] == 1 and rows[0]["id"] == ta2["id"], "the filter resolves the counter-offer chain"


# --- resale loop ----------------------------------------------------------------------

def test_trade_in_retail_resale_loop(api, consultant_headers):
    """PRD §3.9: "The accepted trade-in then enters the used-inventory pipeline:
    the appraiser starts reconditioning, moving the appraisal `ACCEPTED` →
    `RECONDITIONING` and the unit `AT_DEALER` → `RECONDITIONING`; completing
    reconditioning moves the appraisal to its terminal `RETAIL_READY` and the
    unit `RECONDITIONING` → `RETAIL_READY`, from which it can be reserved and
    resold through a new sales order like any other unit."

    Design: Corner/state_machines/trade_in_retail_resale_loop
    """
    scn = new_order_scenario(placement_type="PRIVATE_LAND", agreed_home_price_cents=4_200_000)
    ta = create_offered_trade_in(scn)
    accepted = accept_trade_in(scn, ta)
    trade_unit_id = accepted["trade_in_unit_id"]
    assert trade_unit_id, "acceptance creates the trade-in unit"

    reconditioning = get_success_data(api.start_reconditioning(ta["id"], APPRAISER))
    assert reconditioning["status"] == "RECONDITIONING"
    unit_mid = get_success_data(api.get_home_unit(trade_unit_id, ADMIN))
    assert unit_mid["status"] == "RECONDITIONING"

    ready = get_success_data(api.complete_reconditioning(ta["id"], APPRAISER))
    assert ready["status"] == "RETAIL_READY"
    unit_ready = get_success_data(api.get_home_unit(trade_unit_id, ADMIN))
    assert unit_ready["status"] == "RETAIL_READY" and unit_ready["unit_kind"] == "TRADE_IN"

    resale_customer = create_customer()
    resale = validate_success(
        api.create_sales_order(
            {
                "customer_id": resale_customer["id"],
                "home_unit_id": trade_unit_id,
                "placement_type": "PRIVATE_LAND",
                "financing_type": "CHATTEL",
                "agreed_home_price_cents": 1_900_000,
            },
            consultant_headers,
        ),
        expected_status=201,
    )
    assert resale["home_unit_id"] == trade_unit_id
    unit_sold = get_success_data(api.get_home_unit(trade_unit_id, ADMIN))
    assert unit_sold["status"] == "RESERVED", "RETAIL_READY resumes the retail cycle"

    rows, meta = validate_paginated(api.list_unit_trade_in_appraisals(trade_unit_id, consultant_headers))
    assert meta["total_count"] == 1 and rows[0]["id"] == ta["id"], "the producing appraisal is reverse-reachable"


# --- acceptance cascade -----------------------------------------------------------------

def _order_with_submitted_app_and_offered_trade_in():
    scn = canonical_community_scenario()
    progress_to_site_approved(scn, deposit_cents=473_600)
    create_application(scn)
    submit_application(scn)
    create_offered_trade_in(scn)
    return scn


def test_trade_in_accept_creates_trade_in_unit(api):
    """PRD §3.9: "on acceptance a three-deep cascade fires in one request: first,
    a trade-in `HomeUnit` is created with `unit_kind` `TRADE_IN`, status
    `AT_DEALER`, its `model_id` and `condition_grade` taken from the appraisal
    and a system-minted `serial_number`, and the appraisal's `trade_in_unit_id`
    points at it".

    Design: Difficulty/transitive_cascade/trade_in_accept_depth3_cascade
    """
    scn = _order_with_submitted_app_and_offered_trade_in()
    accepted = accept_trade_in(scn)
    assert accepted["status"] == "ACCEPTED"
    trade_unit_id = accepted["trade_in_unit_id"]
    assert trade_unit_id, "trade_in_unit_id points at the created unit"

    unit = get_success_data(api.get_home_unit(trade_unit_id, ADMIN))
    assert unit["unit_kind"] == "TRADE_IN" and unit["status"] == "AT_DEALER"
    assert unit["model_id"] == scn["model"]["id"] and unit["condition_grade"] == "B"
    assert unit["serial_number"], "the serial number is system-minted"


def test_trade_in_accept_recomputes_order_and_application(api, consultant_headers):
    """PRD §3.9: "second, the order's `trade_in_credit_cents` is set to the
    `final_credit_cents`, its `amount_financed_cents` is recomputed, and its
    `version` is incremented; third, rippling from the order's recompute, the
    order's financing application — if still `DRAFT` or `SUBMITTED` — has its
    `requested_amount_cents` and `estimated_payment_cents` recomputed at the
    type's rate floor."

    Design: Difficulty/transitive_cascade/trade_in_accept_depth3_cascade
    """
    scn = _order_with_submitted_app_and_offered_trade_in()
    app_before = get_success_data(api.get_financing_application(scn["application"]["id"], consultant_headers))
    assert app_before["requested_amount_cents"] == 8_998_397
    assert app_before["estimated_payment_cents"] == 69_764

    accept_trade_in(scn)

    order = get_success_data(api.get_sales_order(scn["order"]["id"], consultant_headers))
    assert order["trade_in_credit_cents"] == 1_100_000
    assert order["amount_financed_cents"] == 7_898_397, "8,998,397 - 1,100,000"

    app_after = get_success_data(api.get_financing_application(scn["application"]["id"], consultant_headers))
    assert app_after["requested_amount_cents"] == 7_898_397, "hop 2: requested amount follows the order"
    assert app_after["estimated_payment_cents"] == 61_236, "estimate recomputed at the 700 bps floor"


# --- money conservation across the trade cycle -----------------------------------------

def test_money_conservation_after_option_void_and_confirm(api, consultant_headers):
    """PRD §3.3: "Finally, `amount_financed_cents` is the total minus
    `deposit_cents` minus `trade_in_credit_cents`, floored at zero, and is
    recomputed on every pricing or trade-in mutation."
    PRD §3.3: "A line is `ACTIVE` on creation and may be voided (`ACTIVE` →
    `VOIDED`) only while the owning order is still `DRAFT` — voiding against a
    confirmed order fails with `ERR_INVALID_STATE`. Every option add and every
    void recomputes the order's pricing fields and increments the order's
    `version`."

    Design: Difficulty/compensating_invariant/money_conservation_across_trade_cycle
    """
    scn = canonical_community_scenario()
    order_id = scn["order"]["id"]
    opt_c = get_success_data(
        api.add_order_option(
            order_id,
            {"option_code": "OPT-MISC", "description": "Misc credit line", "unit_price_cents": 10_050, "quantity": 1},
            consultant_headers,
        )
    )
    voided = get_success_data(api.void_order_option(opt_c["id"], consultant_headers))
    assert voided["status"] == "VOIDED"

    after_void = get_success_data(api.get_sales_order(order_id, consultant_headers))
    assert after_void["total_price_cents"] == 9_471_997, "option C is fully backed out by the void"
    assert after_void["deposit_cents"] == 0 and after_void["trade_in_credit_cents"] == 0
    assert after_void["amount_financed_cents"] == 9_471_997
    assert_order_money_conservation(after_void)

    after_confirm = confirm_order(scn, 473_600)
    assert after_confirm["total_price_cents"] == 9_471_997
    assert after_confirm["amount_financed_cents"] == 8_998_397, "9,471,997 - 473,600"
    assert_order_money_conservation(after_confirm)


def test_money_conservation_after_trade_in_accept(api, consultant_headers):
    """PRD §3.3: "Finally, `amount_financed_cents` is the total minus
    `deposit_cents` minus `trade_in_credit_cents`, floored at zero, and is
    recomputed on every pricing or trade-in mutation."
    PRD §3.9: "second, the order's `trade_in_credit_cents` is set to the
    `final_credit_cents`, its `amount_financed_cents` is recomputed, and its
    `version` is incremented".

    Design: Difficulty/compensating_invariant/money_conservation_across_trade_cycle
    """
    scn = _order_with_submitted_app_and_offered_trade_in()
    accept_trade_in(scn)

    order = get_success_data(api.get_sales_order(scn["order"]["id"], consultant_headers))
    assert order["total_price_cents"] == 9_471_997, "the trade-in cycle never touches the total"
    assert order["deposit_cents"] == 473_600
    assert order["trade_in_credit_cents"] == 1_100_000
    assert order["amount_financed_cents"] == 7_898_397
    assert_order_money_conservation(order)
