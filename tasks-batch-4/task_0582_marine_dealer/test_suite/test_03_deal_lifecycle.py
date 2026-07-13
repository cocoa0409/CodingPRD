"""Sales-deal lifecycle: fund cascade, cancel compensation, sign guards, consignment payout."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    fixtures,
    create_deal_payload,
)

MANAGER = TEST_USERS["manager_headers"]
SALES = TEST_USERS["sales_rep_headers"]

FP_5M = {"principal_cents": 5000000, "apr_bps": 900, "advanced_at": "2026-04-01T00:00:00Z",
         "curtailment_pct_bps": 1000}
FP_8M = {"principal_cents": 8000000, "apr_bps": 950, "advanced_at": "2026-04-01T00:00:00Z",
         "curtailment_pct_bps": 1000}


# --- transitive_cascade: fund drives unit SOLD and floor plan PAID_OFF -----------
def test_fund_marks_deal_funded_and_unit_sold(api):
    """PRD §3.3: "Funding advances a `SIGNED` deal to `FUNDED` and is a `Manager`
    action." PRD §3.3: "Funding sets off the system's central cascade: the unit advances
    from `RESERVED` to `SOLD`".

    Design: Difficulty/transitive_cascade/fund_cascades_unit_sold_floorplan_paidoff
    """
    unit_id, _fp_id, deal_id = fixtures.create_funded_floor_planned_deal(
        fp_overrides=FP_8M,
        deal_overrides={"sale_price_cents": 6800000, "financing_type": "CASH",
                        "tax_rate_bps": 700, "down_payment_cents": 3000000},
    )
    deal = validate_success(api.get_deal(deal_id, MANAGER))
    assert deal["status"] == "FUNDED", f"Expected FUNDED, got {deal['status']}"
    unit = validate_success(api.get_unit(unit_id, MANAGER))
    assert unit["status"] == "SOLD", f"Expected SOLD, got {unit['status']}"


def test_fund_cascades_floor_plan_to_paid_off_with_zero_balance(api):
    """PRD §3.3: "that `SOLD` transition in turn drives the unit's `ACTIVE` or
    `CURTAILED` floor plan to `PAID_OFF`, snapshotting its `payoff_cents`, setting its
    `outstanding_principal_cents` to zero, and recomputing the unit's
    `floor_plan_balance_cents` to zero".

    Design: Difficulty/transitive_cascade/fund_cascades_unit_sold_floorplan_paidoff
    """
    unit_id, fp_id, _deal_id = fixtures.create_funded_floor_planned_deal(
        fp_overrides=FP_8M,
        deal_overrides={"sale_price_cents": 6800000, "financing_type": "CASH",
                        "tax_rate_bps": 700, "down_payment_cents": 3000000},
    )
    fp = validate_success(api.get_floor_plan(fp_id, MANAGER))
    assert fp["status"] == "PAID_OFF", f"Expected PAID_OFF, got {fp['status']}"
    assert fp["outstanding_principal_cents"] == 0
    unit = validate_success(api.get_unit(unit_id, MANAGER))
    assert unit["floor_plan_balance_cents"] == 0, \
        f"Expected balance 0, got {unit['floor_plan_balance_cents']}"


# --- non_linear_state_machine: FUNDED -> CANCELLED diverges from DRAFT branch -----
def test_cancel_funded_deal_reverts_deal_and_unit(api):
    """PRD §3.3: "Cancelling a `FUNDED` deal unwinds the entire funding cascade: the
    unit returns from `SOLD` to `AVAILABLE`". PRD §3.3: "`CANCELLED` is terminal."

    Design: Difficulty/non_linear_state_machine/deal_branch_funded_to_cancelled_diverges
    """
    unit_id, _fp_id, deal_id = fixtures.create_funded_floor_planned_deal(
        fp_overrides=FP_5M,
        deal_overrides={"sale_price_cents": 7000000, "financing_type": "CASH",
                        "tax_rate_bps": 700, "down_payment_cents": 3000000},
    )
    deal = validate_success(api.cancel_deal(deal_id, MANAGER))
    assert deal["status"] == "CANCELLED", f"Expected CANCELLED, got {deal['status']}"
    unit = validate_success(api.get_unit(unit_id, MANAGER))
    assert unit["status"] == "AVAILABLE", f"Expected AVAILABLE, got {unit['status']}"


def test_cancel_funded_deal_reactivates_floor_plan(api):
    """PRD §3.3: "which reactivates its floor plan from `PAID_OFF` back to `ACTIVE`
    with `outstanding_principal_cents` restored to its pre-payoff value and
    `floor_plan_balance_cents` recomputed".

    Design: Difficulty/non_linear_state_machine/deal_branch_funded_to_cancelled_diverges
    """
    _unit_id, fp_id, deal_id = fixtures.create_funded_floor_planned_deal(
        fp_overrides=FP_5M,
        deal_overrides={"sale_price_cents": 7000000, "financing_type": "CASH",
                        "tax_rate_bps": 700, "down_payment_cents": 3000000},
    )
    validate_success(api.cancel_deal(deal_id, MANAGER))
    fp = validate_success(api.get_floor_plan(fp_id, MANAGER))
    assert fp["status"] == "ACTIVE", f"Expected reactivated ACTIVE, got {fp['status']}"


# --- compensating_invariant: fund then cancel conserves floor-plan principal ------
def test_fund_then_cancel_restores_outstanding_principal(api):
    """PRD §3.3: "which reactivates its floor plan from `PAID_OFF` back to `ACTIVE`
    with `outstanding_principal_cents` restored to its pre-payoff value and
    `floor_plan_balance_cents` recomputed".

    Design: Difficulty/compensating_invariant/deal_fund_then_cancel_conserves_floorplan_principal
    """
    _unit_id, fp_id, deal_id = fixtures.create_funded_floor_planned_deal(
        fp_overrides={"principal_cents": 8000000, "apr_bps": 950,
                      "advanced_at": "2026-04-01T00:00:00Z", "curtailment_pct_bps": 1000},
        deal_overrides={"sale_price_cents": 9800000, "financing_type": "CASH",
                        "tax_rate_bps": 700, "down_payment_cents": 4000000},
    )
    validate_success(api.cancel_deal(deal_id, MANAGER))
    fp = validate_success(api.get_floor_plan(fp_id, MANAGER))
    assert fp["status"] == "ACTIVE"
    assert fp["outstanding_principal_cents"] == 8000000, \
        f"Expected restored 8000000, got {fp['outstanding_principal_cents']}"


def test_fund_then_cancel_preserves_immutable_principal(api):
    """PRD §3.2: "captures the original `principal_cents` (immutable once set)". PRD
    §3.3: "the unit returns from `SOLD` to `AVAILABLE`".

    Design: Difficulty/compensating_invariant/deal_fund_then_cancel_conserves_floorplan_principal
    """
    unit_id, fp_id, deal_id = fixtures.create_funded_floor_planned_deal(
        fp_overrides={"principal_cents": 8000000, "apr_bps": 950,
                      "advanced_at": "2026-04-01T00:00:00Z", "curtailment_pct_bps": 1000},
        deal_overrides={"sale_price_cents": 9800000, "financing_type": "CASH",
                        "tax_rate_bps": 700, "down_payment_cents": 4000000},
    )
    validate_success(api.cancel_deal(deal_id, MANAGER))
    fp = validate_success(api.get_floor_plan(fp_id, MANAGER))
    assert fp["principal_cents"] == 8000000, \
        f"principal_cents must be immutable, got {fp['principal_cents']}"
    unit = validate_success(api.get_unit(unit_id, MANAGER))
    assert unit["status"] == "AVAILABLE"


# --- cross_entity_state_dependency: sign requires unit AVAILABLE ------------------
def test_sign_deal_on_intake_unit_rejected(api):
    """PRD §3.3: "Signing requires that the referenced unit currently be `AVAILABLE`;
    if it is not, the sign is rejected with `ERR_UNIT_NOT_AVAILABLE` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/deal_sign_requires_unit_available
    """
    unit = fixtures.create_unit(acquisition_type="CASH")  # left in INTAKE, never listed
    deal = fixtures.create_draft_deal(unit["id"], sale_price_cents=4800000,
                                      down_payment_cents=2000000)
    validate_error(api.sign_deal(deal["id"], SALES),
                   ApiErrorId.ERR_UNIT_NOT_AVAILABLE.value)


def test_sign_deal_on_available_unit_reserves_unit(api):
    """PRD §3.3: "A successful sign cascades: the unit moves from `AVAILABLE` to
    `RESERVED`, held against this signing deal."

    Design: Difficulty/cross_entity_state_dependency/deal_sign_requires_unit_available
    """
    unit = fixtures.create_available_unit(acquisition_type="CASH")
    deal = fixtures.create_draft_deal(unit["id"], sale_price_cents=4800000,
                                      down_payment_cents=2000000)
    signed = validate_success(api.sign_deal(deal["id"], SALES))
    assert signed["status"] == "SIGNED"
    unit_after = validate_success(api.get_unit(unit["id"], MANAGER))
    assert unit_after["status"] == "RESERVED", \
        f"Expected RESERVED, got {unit_after['status']}"


# --- priority_pair_validation_conflict: state check pre-empts fiscal on fund -------
def test_fund_draft_deal_with_low_down_returns_invalid_state(api):
    """PRD §2.5: "Only after these four universal gates pass does the system evaluate
    the referential, concurrency, state, and business rules described in Section 3".
    PRD §3.3: "a request against a resource that is not in a legal state for the
    requested move is rejected with `ERR_INVALID_STATE` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/fund_state_beats_fiscal
    """
    unit = fixtures.create_available_unit(acquisition_type="CASH")
    deal = fixtures.create_draft_deal(unit["id"], sale_price_cents=5000000,
                                      financing_type="RETAIL_FINANCE",
                                      down_payment_cents=100000)  # never signed
    validate_error(api.fund_deal(deal["id"], MANAGER),
                   ApiErrorId.ERR_INVALID_STATE.value)


def test_fund_signed_deal_with_low_down_returns_down_payment_too_low(api):
    """PRD §3.3: "the `down_payment_cents` must be at least the ceiling of
    `sale_price_cents` times 1000 divided by 10000 — equivalently, at least ten percent
    of the sale price, rounded up to the next whole cent — otherwise the request is
    rejected with `ERR_DOWN_PAYMENT_TOO_LOW` (HTTP 402)."

    Design: Difficulty/priority_pair_validation_conflict/fund_state_beats_fiscal
    """
    _unit, deal = fixtures.create_signed_deal(
        unit_overrides={"acquisition_type": "CASH"},
        deal_overrides={"sale_price_cents": 5000000, "financing_type": "RETAIL_FINANCE",
                        "down_payment_cents": 100000},
    )
    validate_error(api.fund_deal(deal["id"], MANAGER),
                   ApiErrorId.ERR_DOWN_PAYMENT_TOO_LOW.value)


# --- Corner: invalid-state / idempotency / duplicate-deal / recall / payout --------
def test_sign_already_signed_deal_rejected(api):
    """PRD §3.3: "a request against a resource that is not in a legal state for the
    requested move is rejected with `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/deal_sign_from_signed_returns_invalid_state
    """
    _unit, deal = fixtures.create_signed_deal(
        unit_overrides={"acquisition_type": "CASH"},
        deal_overrides={"sale_price_cents": 5000000, "down_payment_cents": 2000000},
    )
    validate_error(api.sign_deal(deal["id"], SALES), ApiErrorId.ERR_INVALID_STATE.value)


def test_cancel_already_cancelled_deal_rejected(api):
    """PRD §3.3: "Cancelling a `DRAFT` deal has no side effects." PRD §3.3: "a request
    against a resource that is not in a legal state for the requested move is rejected
    with `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/deal_cancel_twice_idempotency_rejected
    """
    unit = fixtures.create_available_unit(acquisition_type="CASH")
    deal = fixtures.create_draft_deal(unit["id"], sale_price_cents=1900000,
                                      down_payment_cents=900000)
    validate_success(api.cancel_deal(deal["id"], MANAGER))
    validate_error(api.cancel_deal(deal["id"], MANAGER), ApiErrorId.ERR_INVALID_STATE.value)


def test_second_deal_on_unit_with_active_deal_rejected(api):
    """PRD §3.3: "A unit may carry only one live deal at a time: if the unit already
    has a deal in `DRAFT`, `SIGNED`, or `FUNDED`, the create is rejected with
    `ERR_UNIT_HAS_ACTIVE_DEAL` (HTTP 409), a check that follows existence and structural
    validation."

    Design: Corner/validations/second_deal_on_unit_with_active_deal_rejected
    """
    unit = fixtures.create_available_unit(acquisition_type="CASH")
    fixtures.create_draft_deal(unit["id"], sale_price_cents=6200000,
                               down_payment_cents=3000000)
    payload = create_deal_payload(unit["id"], sale_price_cents=6200000,
                                  down_payment_cents=3000000, customer_name="Cid")
    validate_error(api.create_deal(payload, SALES),
                   ApiErrorId.ERR_UNIT_HAS_ACTIVE_DEAL.value)


def test_deliver_funded_deal_with_open_recall_rejected(api):
    """PRD §3.3: "Delivery is blocked while the unit carries an unresolved recall: if
    the unit's `open_recall` is true, the request is rejected with
    `ERR_OPEN_RECALL_BLOCKS_DELIVERY` (HTTP 409)."

    Design: Corner/validations/deliver_with_open_recall_rejected
    """
    unit = fixtures.create_available_unit(acquisition_type="CASH", open_recall=True)
    deal = fixtures.create_draft_deal(unit["id"], sale_price_cents=7300000,
                                      down_payment_cents=3000000)
    validate_success(api.sign_deal(deal["id"], SALES))
    validate_success(api.fund_deal(deal["id"], MANAGER))
    validate_error(api.deliver_deal(deal["id"], SALES),
                   ApiErrorId.ERR_OPEN_RECALL_BLOCKS_DELIVERY.value)


def test_consignment_payout_settled_on_fund(api):
    """PRD §3.4: "When a consigned unit's deal is funded ... the consignment moves to
    `SOLD` and its `payout_cents` is settled. The dealer's commission is the funded
    deal's `sale_price_cents` multiplied by `commission_bps`, divided by 10000, rounded
    half up; the consignor's `payout_cents` is that same `sale_price_cents` minus the
    computed commission."

    Design: Corner/calculations/consignment_payout_computed_on_sale
    """
    unit = fixtures.create_unit(acquisition_type="CONSIGNMENT")
    consignment = fixtures.create_consignment(unit["id"], commission_bps=1200,
                                              agreed_floor_cents=5000000)
    validate_success(api.list_unit_for_sale(unit["id"], MANAGER))
    deal = fixtures.create_draft_deal(unit["id"], sale_price_cents=6000000,
                                      down_payment_cents=3000000)
    validate_success(api.sign_deal(deal["id"], SALES))
    validate_success(api.fund_deal(deal["id"], MANAGER))
    c = validate_success(api.get_consignment(consignment["id"], MANAGER))
    assert c["status"] == "SOLD", f"Expected SOLD, got {c['status']}"
    assert c["payout_cents"] == 5280000, f"Expected payout 5280000, got {c['payout_cents']}"
    u = validate_success(api.get_unit(unit["id"], MANAGER))
    assert u["status"] == "SOLD"
