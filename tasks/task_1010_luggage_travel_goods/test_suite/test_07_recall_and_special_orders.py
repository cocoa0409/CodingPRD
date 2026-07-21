"""Recall cascades, product-recall safety precedence, product retirement, and special orders."""
import test_helpers as H


# ==========================================================================
# Queue A — transitive cascade: recall publish -> product -> registration -> claim
# ==========================================================================
def test_recall_publish_flags_product_and_registration(api, manager_headers):
    """PRD §3.8: "First, the owning product transitions `ACTIVE → RECALLED`."
    PRD §3.8: "Every warranty registration for that product that is currently `ACTIVE` is flagged,
    transitioning `ACTIVE → RECALL_FLAGGED`; and for each such newly flagged registration, every
    claim on it that sits in `SUBMITTED` or `UNDER_REVIEW` is moved to `NEEDS_INFO`."

    Design: Difficulty/transitive_cascade/recall_publish_cascade_product_registration_claim_depth3
    """
    product, _customer, reg, _claim = H.reviewed_claim(api, warranty_months=24,
                                                       purchase_date="2026-06-15T00:00:00Z")
    notice = H.new_recall_notice(product["id"], api, reason="hinge defect", remedy="REPAIR")
    H.get_success_data(api.publish_recall_notice(notice["id"], manager_headers))
    assert H.get_product(product["id"], api)["status"] == "RECALLED"
    assert H.get_registration(reg["id"], api)["status"] == "RECALL_FLAGGED"


def test_recall_publish_moves_open_claim_to_needs_info(api, manager_headers):
    """PRD §3.8: "Every warranty registration for that product that is currently `ACTIVE` is
    flagged, transitioning `ACTIVE → RECALL_FLAGGED`; and for each such newly flagged registration,
    every claim on it that sits in `SUBMITTED` or `UNDER_REVIEW` is moved to `NEEDS_INFO`."

    Design: Difficulty/transitive_cascade/recall_publish_cascade_product_registration_claim_depth3
    """
    product, _customer, _reg, claim = H.reviewed_claim(api, warranty_months=24,
                                                       purchase_date="2026-06-15T00:00:00Z")
    notice = H.new_recall_notice(product["id"], api, reason="hinge defect", remedy="REPAIR")
    H.get_success_data(api.publish_recall_notice(notice["id"], manager_headers))
    assert H.get_claim(claim["id"], api)["status"] == "NEEDS_INFO"


# ==========================================================================
# Queue A — validation precedence: state beats product-recall safety
# ==========================================================================
def test_approve_reports_invalid_state_before_recall_safety(api, manager_headers):
    """PRD §2.8: "4. **State validity** — the target resource is in a state from which the
    requested transition is defined, else `ERR_INVALID_STATE` (409)."
    PRD §2.8: "5. **Product-recall safety** — the referenced product is not `RECALLED` where that
    is forbidden, else `ERR_PRODUCT_RECALLED` (409)."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_safety_on_repair_approve
    """
    customer = H.new_customer(api)
    product = H.new_product(api)
    ro = H.new_repair_order(customer["id"], product["id"], api)  # left in INTAKE (never quoted)
    notice = H.new_recall_notice(product["id"], api, reason="wheel defect", remedy="REPAIR")
    H.get_success_data(api.publish_recall_notice(notice["id"], manager_headers))
    H.validate_error(api.approve_repair_order(ro["id"], manager_headers), H.ApiErrorId.ERR_INVALID_STATE)


def test_state_precedence_leaves_repair_order_in_intake(api, manager_headers):
    """PRD §2.8: "When more than one condition could reject a request, the system evaluates them in
    a fixed order and returns the first failure."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_safety_on_repair_approve
    """
    customer = H.new_customer(api)
    product = H.new_product(api)
    ro = H.new_repair_order(customer["id"], product["id"], api)
    notice = H.new_recall_notice(product["id"], api, reason="wheel defect", remedy="REPAIR")
    H.get_success_data(api.publish_recall_notice(notice["id"], manager_headers))
    H.validate_error(api.approve_repair_order(ro["id"], manager_headers), H.ApiErrorId.ERR_INVALID_STATE)
    assert H.get_repair_order(ro["id"], api)["status"] == "INTAKE"


# ==========================================================================
# Queue B — state machines: recall close compensation, special-order cascade
# ==========================================================================
def test_recall_close_reverts_product_and_registration(api, manager_headers):
    """PRD §3.8: "The owning product transitions `RECALLED → ACTIVE`, and every registration for
    that product still in `RECALL_FLAGGED` is reverted, transitioning `RECALL_FLAGGED → ACTIVE`."

    Design: Corner/state_machines/recall_close_reverts_product_and_registration
    """
    product = H.new_product(api)
    customer = H.new_customer(api)
    reg = H.new_registration(product["id"], customer["id"], api)
    notice = H.new_recall_notice(product["id"], api, remedy="REPLACE")
    H.get_success_data(api.publish_recall_notice(notice["id"], manager_headers))
    H.get_success_data(api.close_recall_notice(notice["id"], manager_headers))
    assert H.get_product(product["id"], api)["status"] == "ACTIVE"
    assert H.get_registration(reg["id"], api)["status"] == "ACTIVE"


def test_recall_publish_cancels_open_special_order(api, manager_headers):
    """PRD §3.8: "Separately, every special order for that product that is in `REQUESTED` or
    `SOURCED` is cancelled, moving to `CANCELLED`."

    Design: Corner/state_machines/recall_publish_cancels_open_special_order
    """
    product = H.new_product(api)
    customer = H.new_customer(api)
    spo = H.new_special_order(customer["id"], product["id"], api, quantity=2)
    notice = H.new_recall_notice(product["id"], api, reason="safety", remedy="REFUND")
    H.get_success_data(api.publish_recall_notice(notice["id"], manager_headers))
    assert H.get_success_data(api.get_special_order(spo["id"], manager_headers))["status"] == "CANCELLED"


def test_special_order_source_arrive_fulfill_happy_path(api, associate_headers):
    """PRD §3.7: "An `Associate` begins sourcing, moving `REQUESTED → SOURCED`, which requires the
    product not to be `RECALLED` (otherwise `ERR_PRODUCT_RECALLED`); marks stock arrived, moving
    `SOURCED → ARRIVED`; and hands the goods over, moving `ARRIVED → FULFILLED`."

    Design: Corner/state_machines/special_order_source_arrive_fulfill_happy_path
    """
    product = H.new_product(api)
    customer = H.new_customer(api)
    spo = H.new_special_order(customer["id"], product["id"], api, quantity=1, deposit_cents=2000)
    H.get_success_data(api.source_special_order(spo["id"], associate_headers))
    H.get_success_data(api.arrive_special_order(spo["id"], associate_headers))
    data = H.validate_success(api.fulfill_special_order(spo["id"], associate_headers))
    assert data["status"] == "FULFILLED"


def test_cancel_already_cancelled_special_order_returns_invalid_state(api, associate_headers):
    """PRD §2.8: "4. **State validity** — the target resource is in a state from which the
    requested transition is defined, else `ERR_INVALID_STATE` (409)."

    Design: Corner/state_machines/cancel_special_order_from_already_cancelled_returns_invalid_state
    """
    product = H.new_product(api)
    customer = H.new_customer(api)
    spo = H.new_special_order(customer["id"], product["id"], api, quantity=1)
    H.get_success_data(api.cancel_special_order(spo["id"], associate_headers))
    H.validate_error(api.cancel_special_order(spo["id"], associate_headers), H.ApiErrorId.ERR_INVALID_STATE)


# ==========================================================================
# Queue B — validations: recall safety on capture; discontinue guard
# ==========================================================================
def test_capture_order_with_recalled_product_rejected(api, associate_headers, manager_headers):
    """PRD §3.5: "Capture requires at least one line and requires that no line references a
    `RECALLED` product (otherwise `ERR_PRODUCT_RECALLED`)."

    Design: Corner/validations/capture_order_with_recalled_product_returns_product_recalled
    """
    customer = H.new_customer(api)
    product = H.new_product(api)
    order = H.new_sales_order(customer["id"], api)
    H.new_sales_order_line(order["id"], product["id"], api, unit_price_cents=20000, qty=1)
    notice = H.new_recall_notice(product["id"], api, reason="hazard", remedy="REFUND")
    H.get_success_data(api.publish_recall_notice(notice["id"], manager_headers))
    H.validate_error(api.capture_sales_order(order["id"], associate_headers), H.ApiErrorId.ERR_PRODUCT_RECALLED)


def test_discontinue_with_open_special_order_rejected(api, manager_headers):
    """PRD §3.1: "Retirement to `DISCONTINUED` is refused with `ERR_OPEN_SPECIAL_ORDER` while any
    special order in `REQUESTED`, `SOURCED`, or `ARRIVED` still references the product; once
    discontinued, the product is excluded from new sales-order lines and new registrations, and
    `DISCONTINUED` is terminal."

    Design: Corner/validations/discontinue_with_open_special_order_returns_open_special_order
    """
    product = H.new_product(api)
    customer = H.new_customer(api)
    H.new_special_order(customer["id"], product["id"], api, quantity=1)
    H.validate_error(api.discontinue_product(product["id"], manager_headers), H.ApiErrorId.ERR_OPEN_SPECIAL_ORDER)
