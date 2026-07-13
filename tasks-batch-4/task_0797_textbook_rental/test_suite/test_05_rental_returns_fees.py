"""The rental loan cycle: extensions, returns, inspection fork, fee calculations,
the quoted-vs-final divergence, the loss cascade, and close-gating. Mixes difficulty
and corner instances."""
from test_helpers import (
    validate_success, validate_error,
    make_customer_headers,
    setup_paid_confirmed_rental, setup_return_opened, setup_inspected_rental,
    get_order, get_rental, get_inventory_unit, get_customer,
    inspect_return_payload,
    TEST_USERS,
)

WAREHOUSE = TEST_USERS["warehouse_headers"]


# ─── Dual-variant order_charge: quoted vs final divergence ────────────

def test_rent_quoted_vs_final_charge_divergence(api):
    """PRD 3.3: "For a `RENT` order the quote is the title's `rental_base_cents`
    multiplied by the term multiplier for the chosen term — 0.5 for a 30-day term, 0.75
    for 60 days, 1.0 for 90 days, and 1.25 for 120 days — multiplied by one minus the
    member discount, then rounded half up to whole cents."
    PRD 3.6: "then the pre-credit total, which is the order's `quoted_charge_cents` plus
    the rental's `late_fee_cents` plus its `damage_fee_cents`; then a loyalty credit of
    500 cents applies when that pre-credit total is at least 10000 cents and is zero
    otherwise; and finally the `final_charge_cents` is the pre-credit total minus the
    loyalty credit."

    Design: Difficulty/dual_variant_calc/rental_quoted_vs_final_charge_divergence
    """
    ctx = setup_inspected_rental(unit_condition="GOOD", reported_condition="ACCEPTABLE",
                                 highlight_pct_reported=0, inspect_clock="2026-06-03T00:00:00Z",
                                 email="qf@x.com")
    order = get_order(ctx["order"]["id"])
    assert order["quoted_charge_cents"] == 6000, order["quoted_charge_cents"]
    assert order["final_charge_cents"] == 7750, order["final_charge_cents"]


def test_rent_final_charge_fee_components(api):
    """PRD 3.6: "the chargeable `late_days` are the overdue days beyond a three-day
    grace, again floored at zero (so charging begins only once overdue days exceed
    three); and `late_fee_cents` is `late_days` multiplied by 250 cents per day, capped
    at the title's `replacement_fee_cents`."
    PRD 3.6: "the condition portion of the fee is that severity multiplied by 1500 cents
    per grade step."

    Design: Difficulty/dual_variant_calc/rental_quoted_vs_final_charge_divergence
    """
    ctx = setup_inspected_rental(unit_condition="GOOD", reported_condition="ACCEPTABLE",
                                 highlight_pct_reported=0, inspect_clock="2026-06-03T00:00:00Z",
                                 email="qf2@x.com")
    rental = get_rental(ctx["rental"]["id"])
    assert rental["late_fee_cents"] == 250, rental["late_fee_cents"]
    assert rental["damage_fee_cents"] == 1500, rental["damage_fee_cents"]


# ─── Loyalty credit keyed on the pre-credit total (circular) ──────────

def test_rent_final_loyalty_credit_applied(api):
    """PRD 3.6: "then a loyalty credit of 500 cents applies when that pre-credit total is
    at least 10000 cents and is zero otherwise; and finally the `final_charge_cents` is
    the pre-credit total minus the loyalty credit. The loyalty tier is keyed on the
    pre-credit total, not on the post-credit figure."

    Design: Difficulty/combinatorial_formula/rental_final_loyalty_circular_credit
    """
    # NEW unit, GOOD return with 15% highlight, 5 days late: T0 = 6000+500+4000 = 10500 -> credit 500.
    ctx = setup_inspected_rental(unit_condition="NEW", reported_condition="GOOD",
                                 highlight_pct_reported=15, inspect_clock="2026-06-04T00:00:00Z",
                                 email="ly@x.com")
    assert get_order(ctx["order"]["id"])["final_charge_cents"] == 10000


def test_rent_loyalty_fee_components(api):
    """PRD 3.6: "the overage is the `highlight_pct_reported` beyond the title's
    `max_highlight_pct` (charged only when the reported percentage strictly exceeds the
    maximum) and the highlight portion is that overage multiplied by 200 cents per
    percentage point, rounded half up".
    PRD 3.6: "the condition portion of the fee is that severity multiplied by 1500 cents
    per grade step."

    Design: Difficulty/combinatorial_formula/rental_final_loyalty_circular_credit
    """
    ctx = setup_inspected_rental(unit_condition="NEW", reported_condition="GOOD",
                                 highlight_pct_reported=15, inspect_clock="2026-06-04T00:00:00Z",
                                 email="ly2@x.com")
    rental = get_rental(ctx["rental"]["id"])
    assert rental["late_fee_cents"] == 500, rental["late_fee_cents"]
    assert rental["damage_fee_cents"] == 4000, rental["damage_fee_cents"]  # 3000 condition + 1000 highlight


# ─── Damage fee non-linear with min() cap at list_price ───────────────

def test_damage_fee_capped_at_list_price(api):
    """PRD 3.6: "The `damage_fee_cents` is the sum of the condition and highlight
    portions, capped at the title's `list_price_cents`."

    Design: Difficulty/combinatorial_formula/damage_fee_nonlinear_min_cap
    """
    # NEW->ACCEPTABLE severity 3 -> condition_fee 4500, but list_price 3500 caps it.
    ctx = setup_inspected_rental(catalog_overrides={"list_price_cents": 3500},
                                 unit_condition="NEW", reported_condition="ACCEPTABLE",
                                 highlight_pct_reported=0, email="dc@x.com")
    assert get_rental(ctx["rental"]["id"])["damage_fee_cents"] == 3500


def test_damage_fee_cap_lands_closed_damaged(api):
    """PRD 3.6: "When `is_lost` is false but either the damage fee is greater than zero
    or the late fee is greater than zero, the shipment closes as `CLOSED_DAMAGED` and its
    own `damage_fee_cents` is set to the computed damage fee."

    Design: Difficulty/combinatorial_formula/damage_fee_nonlinear_min_cap
    """
    ctx = setup_inspected_rental(catalog_overrides={"list_price_cents": 3500},
                                 unit_condition="NEW", reported_condition="ACCEPTABLE",
                                 highlight_pct_reported=0, email="dc2@x.com")
    assert ctx["inspect_result"]["status"] == "CLOSED_DAMAGED"


# ─── Late-fee grace boundary (exactly GRACE_DAYS overdue -> 0) ────────

def test_late_fee_zero_exactly_at_grace_boundary(api):
    """PRD 3.6: "the chargeable `late_days` are the overdue days beyond a three-day
    grace, again floored at zero (so charging begins only once overdue days exceed
    three)".

    Design: Difficulty/boundary_precision_check/late_fee_zero_exactly_at_grace_boundary
    """
    # Due 2026-05-30; inspect 2026-06-02 = exactly due+3 -> days_overdue 3, late_days 0.
    ctx = setup_inspected_rental(unit_condition="GOOD", reported_condition="GOOD",
                                 highlight_pct_reported=0, inspect_clock="2026-06-02T00:00:00Z",
                                 email="lg@x.com")
    rental = get_rental(ctx["rental"]["id"])
    assert rental["late_days"] == 0, rental["late_days"]
    assert rental["late_fee_cents"] == 0, rental["late_fee_cents"]


def test_grace_boundary_return_closes_good(api):
    """PRD 3.6: "When `is_lost` is false and both the computed damage fee and late fee
    are zero, the shipment closes as `CLOSED_GOOD`."

    Design: Difficulty/boundary_precision_check/late_fee_zero_exactly_at_grace_boundary
    """
    ctx = setup_inspected_rental(unit_condition="GOOD", reported_condition="GOOD",
                                 highlight_pct_reported=0, inspect_clock="2026-06-02T00:00:00Z",
                                 email="lg2@x.com")
    assert ctx["inspect_result"]["status"] == "CLOSED_GOOD"


# ─── ReturnShipment branching fork to CLOSED_DAMAGED ──────────────────

def test_return_fork_to_closed_damaged(api):
    """PRD 3.6: "When `is_lost` is false but either the damage fee is greater than zero
    or the late fee is greater than zero, the shipment closes as `CLOSED_DAMAGED` and its
    own `damage_fee_cents` is set to the computed damage fee."

    Design: Difficulty/non_linear_state_machine/return_shipment_branching_fork_to_damaged
    """
    # GOOD unit returned ACCEPTABLE on time: 1 grade step -> damage 1500 > 0 -> CLOSED_DAMAGED.
    ctx = setup_inspected_rental(unit_condition="GOOD", reported_condition="ACCEPTABLE",
                                 highlight_pct_reported=0, email="fd@x.com")
    assert ctx["inspect_result"]["status"] == "CLOSED_DAMAGED"


def test_return_fork_damaged_records_fee(api):
    """PRD 3.6: "the shipment closes as `CLOSED_DAMAGED` and its own `damage_fee_cents`
    is set to the computed damage fee."

    Design: Difficulty/non_linear_state_machine/return_shipment_branching_fork_to_damaged
    """
    ctx = setup_inspected_rental(unit_condition="GOOD", reported_condition="ACCEPTABLE",
                                 highlight_pct_reported=0, email="fd2@x.com")
    rs = ctx["inspect_result"]
    assert rs["damage_fee_cents"] == 1500, rs["damage_fee_cents"]


# ─── Depth-3 lost-return cascade ──────────────────────────────────────

def test_lost_return_cascade_states(api):
    """PRD 3.6: "When instead `is_lost` is true, ... the shipment closes as `CLOSED_LOST`
    and the linked rental is driven to `CLOSED_LOST`. In the loss outcome the rental's
    `late_fee_cents` and `damage_fee_cents` are both forced to zero, a `WalletTransaction`
    of `kind` `REPLACEMENT_CHARGE` is appended for the negative of the title's
    `replacement_fee_cents`, the copy's `status` moves from `IN_INSPECTION` to `RETIRED`,
    and the order bubbles up from `CONFIRMED` to `COMPLETED`."

    Design: Difficulty/transitive_cascade/lost_return_cascade_depth3
    """
    ctx = setup_inspected_rental(unit_condition="GOOD", reported_condition="GOOD",
                                 is_lost=True, email="lo@x.com")
    assert ctx["inspect_result"]["status"] == "CLOSED_LOST"
    assert get_rental(ctx["rental"]["id"])["status"] == "CLOSED_LOST"
    assert get_inventory_unit(ctx["unit"]["id"])["status"] == "RETIRED"


def test_lost_return_cascade_money(api):
    """PRD 3.6: "For a rental that closed as `CLOSED_LOST` the `final_charge_cents` is
    instead the order's `quoted_charge_cents` plus the title's `replacement_fee_cents`,
    and no loyalty credit is applied."
    PRD 3.6: "a `WalletTransaction` of `kind` `REPLACEMENT_CHARGE` is appended for the
    negative of the title's `replacement_fee_cents`".

    Design: Difficulty/transitive_cascade/lost_return_cascade_depth3
    """
    ctx = setup_inspected_rental(unit_condition="GOOD", reported_condition="GOOD",
                                 is_lost=True, topup=50000, email="lo2@x.com")
    assert get_order(ctx["order"]["id"])["final_charge_cents"] == 16000  # 6000 + 10000
    assert get_customer(ctx["customer"]["id"])["wallet_credit_cents"] == 34000  # 50000 - 6000 - 10000


# ─── Rental close gated by ReturnShipment inspection ──────────────────

def test_rental_holds_return_initiated_until_inspection(api):
    """PRD 3.5: "Starting a return mints a `ReturnShipment` in `LABEL_ISSUED` status
    linked by `rental_id` with a generated `carrier_label`, moves the rental's `status`
    from `ACTIVE` to `RETURN_INITIATED`, and moves the physical copy's `status` from
    `RENTED` to `IN_INSPECTION`."
    PRD 3.6: "In both of these no-loss outcomes the linked rental is driven from
    `RETURN_INITIATED` to `CLOSED_RETURNED`".

    Design: Difficulty/cross_entity_state_dependency/rental_close_gated_by_returnshipment_inspection
    """
    ctx = setup_return_opened(unit_condition="GOOD", email="rg@x.com")
    assert get_rental(ctx["rental"]["id"])["status"] == "RETURN_INITIATED"
    validate_success(api.inspect_return_shipment(
        ctx["return_shipment"]["id"], inspect_return_payload("GOOD"), WAREHOUSE), 200)
    assert get_rental(ctx["rental"]["id"])["status"] == "CLOSED_RETURNED"


def test_inspection_bubbles_order_to_completed(api):
    """PRD 3.6: "returns the copy's `status` from `IN_INSPECTION` to `AVAILABLE` and
    overwrites its `condition_grade` with the `reported_condition`; and bubbles the order
    up from `CONFIRMED` to `COMPLETED`."

    Design: Difficulty/cross_entity_state_dependency/rental_close_gated_by_returnshipment_inspection
    """
    ctx = setup_inspected_rental(unit_condition="GOOD", reported_condition="GOOD", email="rg2@x.com")
    assert ctx["inspect_result"]["status"] == "CLOSED_GOOD"
    assert get_order(ctx["order"]["id"])["fulfillment_status"] == "COMPLETED"


# ─── Priority: max-extensions (constraint) beats insufficient-credit ──

def test_extend_max_extensions_beats_insufficient_credit(api):
    """PRD 3.5: "the rental's `extension_count` must be below the ceiling of two
    extensions, and the new total term — the current `term_days` plus the thirty-day
    extension increment — must not exceed the maximum total term of 210 days. If either
    bound would be breached, the extension is refused with `ERR_MAX_EXTENSIONS_REACHED`."
    PRD 2.8: constraint business rules (priority 9) outrank fiscal credit sufficiency
    (priority 11): "9. **Constraint business rules** ... 11. **Fiscal credit
    sufficiency**".

    Design: Difficulty/priority_pair_validation_conflict/extend_max_extensions_beats_insufficient_credit
    """
    ctx = setup_paid_confirmed_rental(topup=9000, email="me@x.com")  # wallet 3000 after 6000 charge
    headers = ctx["headers"]
    validate_success(api.extend_rental(ctx["rental"]["id"], headers), 200)  # -1500 -> 1500
    validate_success(api.extend_rental(ctx["rental"]["id"], headers), 200)  # -1500 -> 0, count 2
    res = api.extend_rental(ctx["rental"]["id"], headers)  # count==MAX and wallet 0
    validate_error(res, "ERR_MAX_EXTENSIONS_REACHED", expected_status=422)


def test_rejected_third_extension_leaves_count_unchanged(api):
    """PRD 3.5: "If either bound would be breached, the extension is refused with
    `ERR_MAX_EXTENSIONS_REACHED`."

    Design: Difficulty/priority_pair_validation_conflict/extend_max_extensions_beats_insufficient_credit
    """
    ctx = setup_paid_confirmed_rental(topup=9000, email="me2@x.com")
    headers = ctx["headers"]
    validate_success(api.extend_rental(ctx["rental"]["id"], headers), 200)
    validate_success(api.extend_rental(ctx["rental"]["id"], headers), 200)
    api.extend_rental(ctx["rental"]["id"], headers)  # rejected
    assert get_rental(ctx["rental"]["id"])["extension_count"] == 2


# ─── Corner: rental / return lifecycle guards ─────────────────────────

def test_extend_closed_rental_returns_409(api):
    """PRD 3.5: "Extending applies only to an `ACTIVE` rental (else
    `ERR_RENTAL_NOT_ACTIVE`)".

    Design: Corner/state_machines/extend_closed_rental_returns_409
    """
    ctx = setup_inspected_rental(unit_condition="GOOD", reported_condition="GOOD", email="xc@x.com")
    res = api.extend_rental(ctx["rental"]["id"], ctx["headers"])
    validate_error(res, "ERR_RENTAL_NOT_ACTIVE", expected_status=409)


def test_return_twice_returns_409(api):
    """PRD 3.5: "Beginning a return also requires the rental to be `ACTIVE` (else
    `ERR_RENTAL_NOT_ACTIVE`) and requires that no return is already open for it — that
    is, no `ReturnShipment` for this rental is currently in `LABEL_ISSUED` status —
    otherwise the request is refused with `ERR_RETURN_ALREADY_OPEN`."

    Design: Corner/state_machines/return_twice_returns_409
    """
    ctx = setup_return_opened(unit_condition="GOOD", email="rt@x.com")
    res = api.return_rental(ctx["rental"]["id"], ctx["headers"])
    validate_error(res, "ERR_RETURN_ALREADY_OPEN", expected_status=409)


def test_inspect_return_not_open_returns_409(api):
    """PRD 3.6: "Inspection requires the shipment to be in `LABEL_ISSUED` status, else
    `ERR_RETURN_NOT_OPEN`."

    Design: Corner/state_machines/inspect_return_not_open_returns_409
    """
    ctx = setup_inspected_rental(unit_condition="GOOD", reported_condition="GOOD", email="ir@x.com")
    res = api.inspect_return_shipment(
        ctx["return_shipment"]["id"], inspect_return_payload("GOOD"), WAREHOUSE)
    validate_error(res, "ERR_RETURN_NOT_OPEN", expected_status=409)
