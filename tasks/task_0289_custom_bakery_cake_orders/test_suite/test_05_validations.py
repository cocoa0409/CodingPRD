"""Business-rule validations: dietary safety, option allowance, lead time, cutoff,
credit sufficiency, the proof-approval gate, line immutability, and delivery input."""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    make_customer_headers,
    line_payload,
    balance_payment_payload,
    slot_payload,
)
import test_helpers.fixtures as fx


# ---------------------------------------------------------------------------
# Queue A: priority_pair_validation_conflict — dietary beats option-allowance
# ---------------------------------------------------------------------------
def test_dietary_conflict_beats_option_not_allowed(api):
    """PRD 2.10: "and then the business rules — allergen/dietary safety, option
    allowance, lead time, cutoff, route-window overlap, the proof-approval gate,
    production-day capacity, credit sufficiency, and payment-amount correctness —
    as detailed in Section 3."
    PRD 3.4: "If either part fails, the line operation is rejected with
    `ERR_DIETARY_CONFLICT`."

    A line selecting BUTTERCREAM (excludes VEGAN, and not in the product's allowed
    list) while requesting VEGAN reports the higher-priority ERR_DIETARY_CONFLICT,
    not ERR_OPTION_NOT_ALLOWED.

    Design: Difficulty/priority_pair_validation_conflict/dietary_safety_beats_option_constraint
    """
    order, customer, product, pday = fx.setup_draft_order(
        product_overrides={"name": "Limited Cake", "allowed_option_codes": ["SPRINKLES"]},
        options=[("SPRINKLES", 1500),
                 ("BUTTERCREAM", 2000, {"introduces_allergen_codes": ["DAIRY"],
                                        "dietary_exclusion_codes": ["VEGAN"]})],
    )
    headers = make_customer_headers(customer["id"])
    validate_error(
        api.add_line(order["id"],
                     line_payload(units=1, selected_option_codes=["BUTTERCREAM"],
                                  requested_dietary_codes=["VEGAN"]),
                     headers),
        ApiErrorId.ERR_DIETARY_CONFLICT)


def test_dietary_conflict_wins_when_allergen_also_forbidden(api):
    """PRD 2.10: "and then the business rules — allergen/dietary safety, option
    allowance, lead time, cutoff, route-window overlap, the proof-approval gate,
    production-day capacity, credit sufficiency, and payment-amount correctness —
    as detailed in Section 3."
    PRD 3.4: "the line's computed `effective_allergen_codes` must not contain an
    allergen that a requested dietary tag forbids; for example a `VEGAN`
    requirement forbids `DAIRY` and `EGG`, and a `GLUTEN_FREE` requirement forbids
    `GLUTEN`. If either part fails, the line operation is rejected with
    `ERR_DIETARY_CONFLICT`."

    A line that selects a NOT-allowed option whose introduced allergen (DAIRY)
    also violates the requested VEGAN tag still reports the higher-priority
    ERR_DIETARY_CONFLICT, not ERR_OPTION_NOT_ALLOWED.

    Design: Difficulty/priority_pair_validation_conflict/dietary_safety_beats_option_constraint
    """
    order, customer, product, pday = fx.setup_draft_order(
        product_overrides={"name": "Limited2", "allowed_option_codes": ["SPRINKLES"]},
        options=[("SPRINKLES", 1500),
                 ("CREAM", 2000, {"introduces_allergen_codes": ["DAIRY"],
                                  "dietary_exclusion_codes": ["VEGAN"]})],
    )
    headers = make_customer_headers(customer["id"])
    validate_error(
        api.add_line(order["id"],
                     line_payload(units=1, selected_option_codes=["CREAM"],
                                  requested_dietary_codes=["VEGAN"]),
                     headers),
        ApiErrorId.ERR_DIETARY_CONFLICT)


def test_option_not_allowed_alone_returns_option_error(api):
    """PRD 3.3: "every entry in `selected_option_codes` must appear in the
    product's `allowed_option_codes`; an option the product does not permit is
    rejected with `ERR_OPTION_NOT_ALLOWED`."

    A line selecting CHOCO_DRIP (a real option, not in the allowed list, with no
    dietary conflict) reports ERR_OPTION_NOT_ALLOWED.

    Design: Corner/validations/option_not_allowed_rejected
    """
    order, customer, product, pday = fx.setup_draft_order(
        product_overrides={"name": "Allowlist", "allowed_option_codes": ["SPRINKLES"]},
        options=[("SPRINKLES", 1500), ("CHOCO_DRIP", 1200)],
    )
    headers = make_customer_headers(customer["id"])
    validate_error(
        api.add_line(order["id"],
                     line_payload(units=1, selected_option_codes=["CHOCO_DRIP"]),
                     headers),
        ApiErrorId.ERR_OPTION_NOT_ALLOWED)


# ---------------------------------------------------------------------------
# Queue B: validations — temporal gates
# ---------------------------------------------------------------------------
def test_lead_time_not_met_blocks_quote(api):
    """PRD 3.6: "If the lead time is not satisfied and no manager override is
    supplied, the quote is rejected with `ERR_LEAD_TIME_NOT_MET`."

    Clock at 2026-06-18, base_lead_days=5, production_date 2026-06-20 (only 2 days
    out) -> ERR_LEAD_TIME_NOT_MET.

    Design: Corner/validations/lead_time_not_met_blocks_quote
    """
    fx.set_clock("2026-06-18T00:00:00Z")
    product = fx.create_product(name="Lead", base_lead_days=5)
    pday = fx.create_production_day(production_date="2026-06-20",
                                    order_cutoff_at="2026-06-30T00:00:00Z")
    customer = fx.create_customer()
    order = fx.create_order(customer, product, pday)
    headers = make_customer_headers(customer["id"])
    fx.add_line(order, customer, units=1)
    validate_error(api.quote_order(order["id"], {}, headers), ApiErrorId.ERR_LEAD_TIME_NOT_MET)


def test_past_cutoff_blocks_quote(api):
    """PRD 3.6: "if the cutoff has already passed and no manager override is
    supplied, the quote is rejected with `ERR_PAST_ORDER_CUTOFF`."

    Clock at 2026-06-16, order_cutoff_at 2026-06-15 (past) -> ERR_PAST_ORDER_CUTOFF.

    Design: Corner/validations/past_cutoff_blocks_quote_unless_override
    """
    fx.set_clock("2026-06-16T00:00:00Z")
    product = fx.create_product(name="Cutoff", base_lead_days=1)
    pday = fx.create_production_day(production_date="2026-06-30",
                                    order_cutoff_at="2026-06-15T00:00:00Z")
    customer = fx.create_customer()
    order = fx.create_order(customer, product, pday)
    headers = make_customer_headers(customer["id"])
    fx.add_line(order, customer, units=1)
    validate_error(api.quote_order(order["id"], {}, headers), ApiErrorId.ERR_PAST_ORDER_CUTOFF)


# ---------------------------------------------------------------------------
# Queue B: validations — credit and proof-gate
# ---------------------------------------------------------------------------
def test_insufficient_credit_rejected(api):
    """PRD 3.10: "Before applying, the system enforces that `applied_credit_cents`
    may not exceed either the customer's `store_credit_cents` or the gross balance;
    an excess election is rejected with `ERR_INSUFFICIENT_CREDIT`."

    A balance capture electing 9999 credit against only 1000 store credit ->
    ERR_INSUFFICIENT_CREDIT.

    Design: Corner/validations/insufficient_credit_rejected
    """
    order, customer, proof, product, pday = fx.setup_proof_approved_order(units=2)
    fx.grant_credit(customer["id"], 1000, "small")
    headers = make_customer_headers(customer["id"])
    fresh = validate_success(api.get_order(order["id"], headers), 200)
    validate_error(
        api.post_balance_payment(order["id"], balance_payment_payload(fresh["version"], 9999), headers),
        ApiErrorId.ERR_INSUFFICIENT_CREDIT)


def test_balance_before_proof_approved_rejected(api):
    """PRD 3.10: "attempting to settle the balance, or to start production, before
    a proof is `APPROVED` is rejected with `ERR_PROOF_NOT_APPROVED`".

    A balance capture while the order is only DEPOSIT_PAID and PROOF_PENDING ->
    ERR_PROOF_NOT_APPROVED.

    Design: Corner/validations/balance_before_proof_approved_rejected
    """
    order, customer, proof, product, pday = fx.setup_proof_pending_order(units=1, image_ref="p1")
    headers = make_customer_headers(customer["id"])
    fresh = validate_success(api.get_order(order["id"], headers), 200)
    validate_error(
        api.post_balance_payment(order["id"], balance_payment_payload(fresh["version"], 0), headers),
        ApiErrorId.ERR_PROOF_NOT_APPROVED)


def test_edit_line_after_approval_rejected_immutable(api):
    """PRD 3.3: "once the order has advanced past proof approval the lines are
    frozen, and any add, edit, or delete attempt is rejected with
    `ERR_LINE_IMMUTABLE`."

    A PATCH on a line of a PROOF_APPROVED order -> ERR_LINE_IMMUTABLE.

    Design: Corner/validations/edit_line_after_approval_rejected_immutable
    """
    order, customer, product, pday = fx.setup_draft_order(product_overrides={"name": "Lock"})
    headers = make_customer_headers(customer["id"])
    line = fx.add_line(order, customer, units=1)
    fx.quote(order, customer)
    fx.pay_deposit(order, customer)
    proof = fx.post_proof(order, "p1")
    fx.approve_proof(order, proof, customer)
    validate_error(api.edit_line(order["id"], line["id"], {"units": 3}, headers),
                   ApiErrorId.ERR_LINE_IMMUTABLE)


# ---------------------------------------------------------------------------
# Queue B: endpoints — delivery reservation input validation
# ---------------------------------------------------------------------------
def test_delivery_reservation_missing_window_invalid_request(api):
    """PRD 3.11: "A `DELIVERY` reservation binds a `DeliveryRoute`: it requires a
    `route_id` and a `window_start_min` expressed as minutes-from-midnight on the
    route's service date (valid only in the range 0 through 1439)."
    PRD 2.10: "Malformed bodies, missing required fields, bad enum values, and
    out-of-range numerics (such as a `window_start_min` outside the 0-to-1439 range
    or `units` below 1) are rejected with `ERR_INVALID_REQUEST`."

    A DELIVERY reservation omitting window_start_min -> ERR_INVALID_REQUEST.

    Design: Corner/endpoints/delivery_reservation_missing_window_invalid_request
    """
    order, customer, proof, product, pday = fx.setup_proof_approved_order(units=1)
    route = fx.create_route(route_name="R3", service_date="2026-06-20", stop_minutes=30)
    headers = make_customer_headers(customer["id"])
    validate_error(
        api.create_slot(order["id"], slot_payload("DELIVERY", route_id=route["id"]), headers),
        ApiErrorId.ERR_INVALID_REQUEST)
