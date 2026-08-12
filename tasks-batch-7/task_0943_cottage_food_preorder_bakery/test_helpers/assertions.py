"""Entity assertions, semantic instant comparison and domain invariant checks."""
from datetime import datetime, timedelta, timezone

import pytest
from prd_bench_local_runner.testing import is_valid_uuid

from .constants import (
    BATCH_SLOT_UNITS,
    RATING_ROLLUP_MIN_REVIEWS,
    TAX_RATE_BPS,
)

# ─── Semantic instant handling ───────────────────────────────────────────────
#
# The PRD fixes the *instants* this system compares, not the byte-level
# rendering of a timestamp. Everything below therefore parses both sides and
# compares instants. Accepted shapes: trailing "Z", ".mmmZ", ".ffffffZ" and a
# "+HH:MM" / "-HH:MM" offset.


def parse_instant(value):
    """Parse an ISO 8601 instant into an aware UTC datetime."""
    assert isinstance(value, str) and value, f"expected an ISO 8601 string, got {value!r}"
    text = value.strip()
    if text.endswith(("z", "Z")):
        text = text[:-1] + "+00:00"
    # Trim sub-microsecond precision, which fromisoformat cannot take.
    if "." in text:
        head, _, tail = text.partition(".")
        digits = ""
        for ch in tail:
            if ch.isdigit():
                digits += ch
            else:
                break
        rest = tail[len(digits):]
        digits = (digits + "000000")[:6]
        text = f"{head}.{digits}{rest}"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def assert_same_instant(actual, expected, label="instant"):
    """Assert two ISO 8601 renderings denote the same instant.

    Rendering format is deliberately not asserted: only the instant is part of
    the contract. Comparison is at second granularity, as PRD §2.4 states.
    """
    got = parse_instant(actual).replace(microsecond=0)
    want = parse_instant(expected).replace(microsecond=0)
    assert got == want, f"{label}: expected instant {want.isoformat()}, got {got.isoformat()} (raw {actual!r})"


def instant_plus(base, *, minutes=0, hours=0, days=0):
    """Return the ISO rendering of `base` shifted by the given offset."""
    moment = parse_instant(base) + timedelta(minutes=minutes, hours=hours, days=days)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"


def assert_is_instant(value, label="timestamp"):
    parse_instant(value)


# ─── Entity assertions ───────────────────────────────────────────────────────

def _common(data, label):
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a bare UUID: {data.get('id')!r}"
    assert_is_instant(data.get("created_at"), f"{label}.created_at")


def _versioned(data, label):
    _common(data, label)
    assert_is_instant(data.get("updated_at"), f"{label}.updated_at")
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{label}.version must be an integer starting at 1, got {data.get('version')!r}"
    )


def assert_baker(data):
    _versioned(data, "Baker")
    assert data["permit_status"] in {"PENDING", "ACTIVE", "SUSPENDED", "CAP_REACHED"}
    assert isinstance(data["display_name"], str) and data["display_name"]
    assert isinstance(data["jurisdiction_code"], str) and data["jurisdiction_code"]
    assert isinstance(data["annual_cap_cents"], int)
    assert isinstance(data["cap_year"], int)
    assert isinstance(data["annual_gross_sales_cents"], int)
    assert isinstance(data["payout_net_cents"], int)


def assert_customer(data):
    _versioned(data, "Customer")
    assert isinstance(data["baker_id"], str)
    assert isinstance(data["email"], str) and data["email"]
    assert isinstance(data["allergen_avoidances"], list)
    assert isinstance(data["credit_balance_cents"], int)


def assert_recipe(data):
    _versioned(data, "Recipe")
    assert data["recipe_status"] in {"DRAFT", "PUBLISHED", "REVISING", "RETIRED"}
    assert isinstance(data["published_version"], int)
    assert isinstance(data["allergen_union"], list)
    assert isinstance(data["tree_depth"], int) and data["tree_depth"] >= 1


def assert_recipe_component(data):
    _versioned(data, "RecipeComponent")
    assert isinstance(data["component_name"], str) and data["component_name"]
    assert isinstance(data["declared_allergens"], list)
    assert isinstance(data["recalled_component"], bool)


def assert_ingredient_lot(data):
    _versioned(data, "IngredientLot")
    assert data["lot_status"] in {"RECEIVED", "RELEASED", "CONSUMED", "RECALLED", "EXPIRED"}
    assert isinstance(data["lot_code"], str) and data["lot_code"]
    assert isinstance(data["allergens"], list)
    assert isinstance(data["cross_contact_allergens"], list)


def assert_menu_item(data):
    _versioned(data, "MenuItem")
    assert data["listing_status"] in {"DRAFT", "LISTED", "PAUSED", "DELISTED"}
    assert data["product_class"] in {"SHELF_STABLE", "REFRIGERATION_REQUIRED"}
    assert data["pricing_basis"] in {"PER_UNIT", "PER_DOZEN_BAKERS"}
    assert isinstance(data["unit_price_cents"], int)
    assert isinstance(data["dozen_price_cents"], int)
    assert isinstance(data["rating_count"], int) and data["rating_count"] >= 0
    assert_rating_rollup_conservation(data)


def assert_offer_window(data):
    _versioned(data, "OfferWindow")
    assert data["window_status"] in {
        "DRAFT", "OPEN", "LOCKED", "IN_PRODUCTION", "HANDOFF_OPEN", "CLOSED", "CANCELLED",
    }
    assert data["plan_status"] in {"UNPLANNED", "PLANNED", "RECONCILED"}
    assert data["capacity_posture"] in {"OPEN_CAPACITY", "CONSTRAINED", "EXHAUSTED"}
    assert isinstance(data["capacity_units"], int)
    assert isinstance(data["capacity_batch_slots"], int)
    for field in ("opens_at", "order_cutoff_at", "production_date", "handoff_date",
                  "handoff_window_end_at"):
        assert_is_instant(data[field], f"OfferWindow.{field}")
    assert parse_instant(data["opens_at"]) < parse_instant(data["order_cutoff_at"])
    assert parse_instant(data["order_cutoff_at"]) <= parse_instant(data["production_date"])
    assert parse_instant(data["production_date"]) <= parse_instant(data["handoff_date"])
    assert parse_instant(data["handoff_date"]) < parse_instant(data["handoff_window_end_at"])


def assert_order(data):
    _versioned(data, "Order")
    assert data["order_status"] in {
        "DRAFT", "PENDING_HOLD", "EXPIRED_HOLD", "CONFIRMED", "IN_PRODUCTION",
        "READY", "FULFILLED", "FORFEITED", "CANCELLED", "VOIDED_RECALL",
    }
    assert data["payment_status"] in {
        "UNPAID", "AUTHORIZED", "CAPTURED", "PARTIALLY_REFUNDED", "REFUNDED", "VOIDED",
    }
    assert data["handoff_status"] in {
        "NOT_SCHEDULED", "SCHEDULED", "PICKUP_READY", "OUT_FOR_DELIVERY",
        "HANDED_OFF", "MISSED", "FORFEITED",
    }
    assert data["channel"] in {"DTC", "WHOLESALE"}
    assert data["handoff_mode"] in {"PICKUP_COUNTER", "PORCH_SELF_SERVE", "DELIVERY"}
    assert data["source"] in {"WALKUP", "SUBSCRIPTION_CLUB"}
    for field in ("subtotal_cents", "tax_total_cents", "delivery_fee_cents",
                  "tip_cents", "credit_applied_cents", "grand_total_cents"):
        assert isinstance(data[field], int), f"Order.{field} must be an integer number of cents"


def assert_order_line(data):
    _versioned(data, "OrderLine")
    assert data["line_status"] in {
        "PENDING", "RELEASED", "ALLOCATED", "FULFILLED", "SHORTED", "CREDITED",
        "RECALL_VOID",
    }
    assert data["disposition"] in {
        "WHOLE_UNHEATED", "WITH_UTENSILS", "BY_THE_SLICE", "HEATED",
    }
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert isinstance(data["line_total_cents"], int)
    assert isinstance(data["line_tax_cents"], int)
    assert isinstance(data["allocated_units"], int)
    assert isinstance(data["shorted_units"], int)


def assert_batch(data):
    _versioned(data, "Batch")
    assert data["batch_status"] in {
        "PLANNED", "MIXED", "BAKED", "YIELD_CONFIRMED", "UNDER_YIELD", "ALLOCATED",
        "CLOSED", "SCRAPPED_RECALL",
    }
    assert isinstance(data["slot_count"], int) and data["slot_count"] >= 1
    assert isinstance(data["planned_yield_units"], int)
    assert isinstance(data["surplus_units"], int)


def assert_label(data):
    _versioned(data, "Label")
    assert data["label_status"] in {"ISSUED", "SUPERSEDED", "VOID", "CONSUMED"}
    assert isinstance(data["allergen_union"], list)
    assert isinstance(data["recipe_version_pinned"], int)


def assert_subscription(data):
    _versioned(data, "Subscription")
    assert data["sub_status"] in {"PENDING", "ACTIVE", "PAUSED", "PAST_DUE", "CANCELLED"}
    assert data["billing_mode"] in {"PREPAID", "PAY_PER_CYCLE"}
    assert data["cadence"] in {"WEEKLY", "BIWEEKLY", "MONTHLY"}
    assert isinstance(data["pause_count"], int) and data["pause_count"] >= 0
    assert isinstance(data["prepaid_balance_cents"], int)


def assert_subscription_cycle(data):
    _versioned(data, "SubscriptionCycle")
    assert data["cycle_status"] in {
        "GENERATED", "RESERVED", "CONFIRMED", "SKIPPED", "RELEASED", "ORDER_PLACED",
    }
    assert isinstance(data["sequence_number"], int) and data["sequence_number"] >= 1
    assert isinstance(data["reserved_units"], int)
    assert isinstance(data["cycle_price_cents"], int)


def assert_payment(data):
    _versioned(data, "Payment")
    assert data["payment_state"] in {
        "INITIATED", "AUTHORIZED", "CAPTURED", "SETTLED", "DECLINED", "VOIDED",
    }
    assert data["tip_mode"] in {"PERCENT", "FIXED"}
    for field in ("tip_cents", "authorized_cents", "captured_cents", "refunded_cents"):
        assert isinstance(data[field], int)


def assert_money_movement(data):
    """A money movement is an immutable ledger entry: id and created_at only."""
    _common(data, "MoneyMovement")
    assert "updated_at" not in data, "MoneyMovement must not carry updated_at"
    assert "version" not in data, "MoneyMovement must not carry version"
    assert data["ledger_scope"] in {"CUSTOMER_CREDIT", "SUBSCRIPTION_PREPAID", "SETTLEMENT"}
    assert data["movement_kind"] in {
        "REFUND", "SHORTFALL_CREDIT", "PREPAY_DEPOSIT", "CREDIT_REDEEM",
    }
    # PRD §2.12 declares the closed value set for `MoneyMovement.reason`, and every
    # one of its five members is assigned by PRD prose to a *system-driven* pathway:
    # SHORTFALL to the shortfall cascade (§3.7), RECALL_VOID to recall hop 6 (§3.10),
    # CUSTOMER_CANCEL to the cancellation unwind (§3.5), the authorised-payment void
    # (§3.9) and the prepaid-membership cancel mirror (§3.6), SUBSCRIPTION_PREPAY to
    # club activation (§3.6), and ORDER_APPLY to credit redemption (§3.9, §3.6).  The
    # operator-initiated refund of §3.9 is assigned none of them: its request carries
    # a free-text `refund_reason` and no PRD sentence says which enum member — or that
    # any member — lands on the resulting movement.  So membership is asserted where a
    # reason is present (that half is verbatim in §2.12) but presence itself is not
    # demanded, which PRD nowhere states for this pathway.
    if data["reason"] is not None:
        assert data["reason"] in {
            "SHORTFALL", "RECALL_VOID", "CUSTOMER_CANCEL", "SUBSCRIPTION_PREPAY",
            "ORDER_APPLY",
        }
    assert isinstance(data["amount_cents"], int)


def assert_delivery_route(data):
    _versioned(data, "DeliveryRoute")
    assert data["route_status"] in {"DRAFT", "SEQUENCED", "DISPATCHED", "COMPLETED"}
    assert isinstance(data["stop_count"], int) and data["stop_count"] >= 0


def assert_review(data):
    _versioned(data, "Review")
    assert data["review_status"] in {"SUBMITTED", "RESPONDED", "HIDDEN"}
    assert isinstance(data["rating"], int) and 1 <= data["rating"] <= 5
    assert isinstance(data["counts_toward_rollup"], bool)


# ─── Domain invariants (PRD §2.10) ───────────────────────────────────────────

def assert_window_unit_conservation(capacity):
    """capacity_units equals units_remaining + confirmed + held + reserved."""
    total = (
        capacity["units_remaining"]
        + capacity["confirmed_units"]
        + capacity["held_units"]
        + capacity["reserved_units"]
    )
    assert "capacity_units" not in capacity or capacity["capacity_units"] == total
    return total


def assert_refund_legs_sum_to_amount(movement):
    """Every refund movement's four legs sum exactly to its amount_cents."""
    legs = (
        movement["leg_tip_cents"]
        + movement["leg_delivery_fee_cents"]
        + movement["leg_subtotal_cents"]
        + movement["leg_credit_cents"]
    )
    assert legs == movement["amount_cents"], (
        f"refund legs {legs} must sum to amount_cents {movement['amount_cents']}"
    )


def assert_yield_conservation(batch, lines):
    """Allocated units over ALLOCATED/SHORTED/CREDITED/FULFILLED lines plus
    surplus_units equals actual_yield_units."""
    counted = sum(
        line["allocated_units"]
        for line in lines
        if line["line_status"] in {"ALLOCATED", "SHORTED", "CREDITED", "FULFILLED"}
    )
    assert counted + batch["surplus_units"] == batch["actual_yield_units"], (
        f"yield conservation: allocated {counted} + surplus {batch['surplus_units']} "
        f"!= actual_yield_units {batch['actual_yield_units']}"
    )


def assert_rating_rollup_conservation(menu_item):
    """rating_avg is absent exactly when rating_count is below three."""
    if menu_item.get("rating_count", 0) < RATING_ROLLUP_MIN_REVIEWS:
        assert menu_item.get("rating_avg") is None, (
            "rating_avg must be absent while rating_count is below three, got "
            f"{menu_item.get('rating_avg')!r}"
        )
    else:
        assert menu_item.get("rating_avg") is not None


def assert_slot_count(units, yield_units_per_slot=None):
    """PRD §2.9: demand divided by the 24 units a slot holds, rounded up."""
    return -(-units // BATCH_SLOT_UNITS)


def assert_line_pricing(line, expected_total, expected_tax):
    assert line["line_total_cents"] == expected_total, (
        f"line_total_cents: expected {expected_total}, got {line['line_total_cents']}"
    )
    assert line["line_tax_cents"] == expected_tax, (
        f"line_tax_cents: expected {expected_tax}, got {line['line_tax_cents']}"
    )


def approx_hours(value):
    return pytest.approx(value, abs=0.005)


def approx_km(value):
    return pytest.approx(value, abs=0.005)


def assert_rejected(response, label="request"):
    """Assert a call was refused with a well-formed error envelope.

    Used where the specification states the precondition and states that a failing
    request is rejected with nothing mutated, but leaves the error identifier
    itself open. The rejection and the absence of side effects are asserted; the
    identifier is not pinned.
    """
    assert 400 <= response.status_code < 500, (
        f"{label}: expected a 4xx rejection, got {response.status_code}: {response.text}"
    )
    body = response.json()
    assert body.get("response_type") == "error", f"{label}: expected an error envelope"
    error = body.get("data") or {}
    assert isinstance(error.get("error_id"), str) and error["error_id"], (
        f"{label}: error envelope must carry a non-empty error_id"
    )
    assert isinstance(error.get("message"), str) and error["message"].strip(), (
        f"{label}: error envelope must carry a human-readable message"
    )
    return error["error_id"]
