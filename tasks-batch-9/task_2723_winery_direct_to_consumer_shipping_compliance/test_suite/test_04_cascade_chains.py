"""Transitive cascades: one write that propagates across three or four tiers.

A ``RETURN_TO_SENDER`` scan travels shipment -> order -> ledger -> consumer risk
-> screening tier, and a permit revocation travels permit -> order ->
club subscription -> winery counter.  Each test observes one tier of the chain
that only moved because the previous tier did.
"""

from test_helpers import factories as f
from test_helpers.api_client import DtcApiClient  # noqa: F401  (client under test)
from test_helpers.assertions import (
    assert_cents,
    assert_charge_chain,
    assert_instant_equals,
    assert_ledger_entry,
    assert_ledger_sums_to,
    assert_liters,
    assert_order_dimensions,
)
from test_helpers.constants import (
    CANONICAL_ORDER_EXCISE_CENTS,
    CANONICAL_ORDER_SALES_TAX_CENTS,
    CANONICAL_ORDER_TOTAL_LITERS,
    CLOCK_STARTUP_DEFAULT,
)
from test_helpers.fixtures import append_manual_adjustment, build_landscape

# The seeded back-dated TX volume and the resulting utilisation term.
SEEDED_TX_LITERS = 22.500
SEEDED_TX_OCCURRED_AT = "2026-07-15T00:00:00Z"


# ---------------------------------------------------------------------------
# Local arrangement for the return-to-sender chain
# ---------------------------------------------------------------------------
def _returned_order_at_the_risk_threshold(api):
    """A picked-up order whose return will tip the consumer over 50 risk points.

    A 22.500 L manual adjustment dated inside the ROLLING_12_MONTHS window puts
    the utilisation term at ``floor(30 * 22.500 / 27.000)`` = 25.  Order A of
    9.000 L then breaches the 27.000 L consumer limit, goes ``OVERRIDE_PENDING``
    and has its exception ``DENIED``, adding 15 points.  Order B of 4.500 L lands
    exactly on the limit, clears, is labelled and picked up — so its liters settle
    and the utilisation term rises to 30, for ``risk_score_screening`` 45 and a
    still-``STANDARD`` tier.  Returning order B swaps 5 utilisation points for a
    10-point return credit, reaching exactly 50.
    """
    scape = build_landscape(api)
    append_manual_adjustment(
        api,
        scape.consumer_id,
        scape.winery_id,
        SEEDED_TX_LITERS,
        occurred_at=SEEDED_TX_OCCURRED_AT,
        reason="Pre-platform TX volume for this consumer",
    )

    order_a = scape.create_order(lines=[f.order_line(bottles=12)])
    screened_a = scape.screen(order_a["id"])
    assert_order_dimensions(screened_a, compliance_status="OVERRIDE_PENDING")
    exception = scape.raise_exception(
        order_a["id"], "ERR_CONSUMER_VOLUME_LIMIT_EXCEEDED"
    )
    scape.decide_exception(exception["id"], "DENIED")

    order_b = scape.create_order()
    cleared_b = scape.screen(order_b["id"])
    assert_order_dimensions(cleared_b, compliance_status="CLEARED")
    shipment = scape.label(order_b["id"])
    scape.pickup(shipment["id"])

    return scape, order_a, order_b, shipment


# ---------------------------------------------------------------------------
# Instance: return_to_sender_four_hop_cascade_to_screening_tier
# ---------------------------------------------------------------------------
def test_return_to_sender_moves_the_shipment_then_the_order(api):
    """Hops 0 and 1: the shipment returns, and the order follows it.

    PRD §3.7: "The shipment's `status` becomes `RETURNED` and its `returned_at` is
    stamped from the logical clock."
    PRD §3.7: "Because the shipment became `RETURNED`, the order's
    `fulfillment_status` becomes `RETURNED` and its `returned_at` is stamped from
    the logical clock too."
    PRD §3.7: "Note what a return does **not** do: it leaves the order's
    `compliance_status` at `CLEARED`."

    Design: Difficulty/transitive_cascade/return_to_sender_four_hop_cascade_to_screening_tier
    """
    scape, _, order_b, shipment = _returned_order_at_the_risk_threshold(api)

    returned = scape.return_to_sender(shipment["id"])

    assert returned["status"] == "RETURNED"
    assert_instant_equals(returned["returned_at"], CLOCK_STARTUP_DEFAULT)

    reread_order = scape.read_order(order_b["id"])
    assert_order_dimensions(
        reread_order, compliance_status="CLEARED", fulfillment_status="RETURNED"
    )
    assert_instant_equals(reread_order["returned_at"], CLOCK_STARTUP_DEFAULT)


def test_return_to_sender_reverses_both_tax_fields_on_the_order_and_the_winery(api):
    """Hop 2, the money half: reversal fields are all-or-nothing.

    PRD §3.7: "Because the order became `RETURNED`, a ledger entry with
    `event_type` `RETURN_CREDIT` is appended carrying `liters` equal to negative
    `total_liters`, `order_id` set, `shipment_id` set to this shipment, and
    `occurred_at` at the logical clock; the order's `excise_reversed_cents` is set
    to its `excise_tax_cents` and its `sales_tax_reversed_cents` to its
    `sales_tax_cents`; and the winery's `excise_reversed_cents` grows by the
    order's `excise_tax_cents`."
    PRD §2.10: "Reversal fields on an order are all-or-nothing: each is either 0
    or exactly equal to the corresponding gross figure, never a partial amount."

    Design: Difficulty/transitive_cascade/return_to_sender_four_hop_cascade_to_screening_tier
    """
    scape, _, order_b, shipment = _returned_order_at_the_risk_threshold(api)

    scape.return_to_sender(shipment["id"])

    reread_order = scape.read_order(order_b["id"])
    assert_charge_chain(
        reread_order,
        excise_tax_cents=CANONICAL_ORDER_EXCISE_CENTS,
        sales_tax_cents=CANONICAL_ORDER_SALES_TAX_CENTS,
    )
    assert_cents(
        reread_order["excise_reversed_cents"],
        CANONICAL_ORDER_EXCISE_CENTS,
        "excise_reversed_cents",
    )
    assert_cents(
        reread_order["sales_tax_reversed_cents"],
        CANONICAL_ORDER_SALES_TAX_CENTS,
        "sales_tax_reversed_cents",
    )

    # Only order B ever reached CLEARED, so the gross accrual is one order's
    # excise and the reversal cancels it exactly.
    winery = scape.read_winery()
    assert_cents(
        winery["excise_accrued_cents"],
        CANONICAL_ORDER_EXCISE_CENTS,
        "excise_accrued_cents",
    )
    assert_cents(
        winery["excise_reversed_cents"],
        CANONICAL_ORDER_EXCISE_CENTS,
        "excise_reversed_cents",
    )


def test_return_to_sender_appends_an_offsetting_ledger_entry(api):
    """Hop 2, the ledger half: a compensating entry, not an edit to history.

    PRD §2.10: "It appends an offsetting ledger entry with the opposite sign, and
    it records the reversal in a dedicated field (`Order.excise_reversed_cents`,
    `Order.sales_tax_reversed_cents`, `Winery.excise_reversed_cents`) so that
    gross and net figures are both recoverable."
    PRD §3.7: "Because the order became `RETURNED`, a ledger entry with
    `event_type` `RETURN_CREDIT` is appended carrying `liters` equal to negative
    `total_liters`, `order_id` set, `shipment_id` set to this shipment, and
    `occurred_at` at the logical clock"

    Design: Difficulty/transitive_cascade/return_to_sender_four_hop_cascade_to_screening_tier
    """
    scape, _, order_b, shipment = _returned_order_at_the_risk_threshold(api)

    scape.return_to_sender(shipment["id"])

    rows = scape.ledger_rows(order_id=order_b["id"])
    assert len(rows) == 2, (
        "the clearance debit and the return credit must both survive, got "
        f"{len(rows)} rows"
    )
    by_type = {row["event_type"]: row for row in rows}
    assert set(by_type) == {"SHIPMENT_ACCEPTED", "RETURN_CREDIT"}

    assert_ledger_entry(
        by_type["SHIPMENT_ACCEPTED"],
        event_type="SHIPMENT_ACCEPTED",
        liters=CANONICAL_ORDER_TOTAL_LITERS,
        state_code="TX",
        order_id=order_b["id"],
    )
    assert by_type["SHIPMENT_ACCEPTED"]["shipment_id"] is None

    assert_ledger_entry(
        by_type["RETURN_CREDIT"],
        event_type="RETURN_CREDIT",
        liters=-CANONICAL_ORDER_TOTAL_LITERS,
        state_code="TX",
        order_id=order_b["id"],
        shipment_id=shipment["id"],
    )
    assert_instant_equals(
        by_type["RETURN_CREDIT"]["occurred_at"], CLOCK_STARTUP_DEFAULT
    )

    assert_ledger_sums_to(rows, 0.000)


def test_return_to_sender_recomputes_the_consumer_volume_and_return_counter(api):
    """Hop 3: the credit exists, so the derived volume picture is rebuilt.

    PRD §3.7: "Because a `RETURN_CREDIT` entry now exists, the consumer's
    `rolling_liters_by_state`, `rolling_liters_settled_by_state`,
    `return_credit_count`, `risk_score_screening` and `risk_score_audit` are all
    recomputed and `Consumer.version` increments by 1."
    PRD §3.4: "`return_credit_count` is the number of that consumer's ledger
    entries with `event_type` `RETURN_CREDIT` falling inside the widest
    `per_consumer_period` window in play, and `denied_exception_count` is the
    number of compliance exceptions in status `DENIED` raised on that consumer's
    orders."

    Design: Difficulty/transitive_cascade/return_to_sender_four_hop_cascade_to_screening_tier
    """
    scape, _, _, shipment = _returned_order_at_the_risk_threshold(api)

    scape.return_to_sender(shipment["id"])

    consumer = scape.read_consumer()
    assert consumer["return_credit_count"] == 1, (
        "one RETURN_CREDIT entry sits inside the window, got "
        f"{consumer['return_credit_count']}"
    )
    # +22.500 seeded, +4.500 at clearance, -4.500 at the return.
    assert_liters(
        consumer["rolling_liters_by_state"]["TX"],
        SEEDED_TX_LITERS,
        "rolling_liters_by_state[TX]",
    )
    # The returned order is RETURNED, so both of its entries are settled and they
    # cancel, leaving only the order-less manual adjustment.
    assert_liters(
        consumer["rolling_liters_settled_by_state"]["TX"],
        SEEDED_TX_LITERS,
        "rolling_liters_settled_by_state[TX]",
    )


def test_return_to_sender_tips_the_screening_tier_to_elevated(api):
    """Hop 4: the score moved, so the derived tier flips at the threshold.

    PRD §3.7: "Because `risk_score_screening` moved, `screening_tier` is
    re-derived — becoming `ELEVATED` if the new screening score has reached 50 or
    more, which is how a series of returns eventually starts gating that
    consumer's future orders."
    PRD §3.4: "From the screening score alone the system derives `screening_tier`,
    which is `STANDARD` while `risk_score_screening` is below 50 and becomes
    `ELEVATED` as soon as `risk_score_screening` reaches 50 or more."

    Design: Difficulty/transitive_cascade/return_to_sender_four_hop_cascade_to_screening_tier
    """
    scape, _, _, shipment = _returned_order_at_the_risk_threshold(api)

    before = scape.read_consumer()
    assert before["risk_score_screening"] == 45, (
        "one denial (15) plus full utilisation (30) is 45 before the return, got "
        f"{before['risk_score_screening']}"
    )
    assert before["screening_tier"] == "STANDARD"

    scape.return_to_sender(shipment["id"])

    consumer = scape.read_consumer()
    # 10 for the return credit + 15 for the denial + floor(30 * 22.5 / 27) = 25.
    assert consumer["risk_score_screening"] == 50, (
        "expected 10 + 15 + 25 = 50 after the return, got "
        f"{consumer['risk_score_screening']}"
    )
    assert consumer["screening_tier"] == "ELEVATED"


def test_the_denied_exception_precondition_survives_the_return(api):
    """The denial that seeded 15 risk points is still on the record afterwards.

    PRD §3.6: "An **`OPEN` -> `DENIED`** decision moves the order
    `OVERRIDE_PENDING` -> `REJECTED` and leaves `rejection_error_id` holding the
    overridable identifier that caused the referral in the first place — the
    record of *why* the order died is preserved rather than cleared."
    PRD §3.6: "Instead the consumer's `denied_exception_count` grows by 1, and
    because that counter moved, `risk_score_screening`, `risk_score_audit` and
    `screening_tier` are recomputed and `Consumer.version` increments by 1"

    Design: Difficulty/transitive_cascade/return_to_sender_four_hop_cascade_to_screening_tier
    """
    scape, order_a, _, shipment = _returned_order_at_the_risk_threshold(api)

    scape.return_to_sender(shipment["id"])

    reread_a = scape.read_order(order_a["id"])
    assert_order_dimensions(reread_a, compliance_status="REJECTED")
    assert reread_a["rejection_error_id"] == "ERR_CONSUMER_VOLUME_LIMIT_EXCEEDED"

    consumer = scape.read_consumer()
    assert consumer["denied_exception_count"] == 1, (
        f"expected one DENIED exception, got {consumer['denied_exception_count']}"
    )

    winery = scape.read_winery()
    assert winery["open_exception_count"] == 0, (
        "the decided exception left the OPEN population, got "
        f"{winery['open_exception_count']}"
    )

    # The rejected order never cleared, so it never contributed to the accrual.
    rows = scape.ledger_rows(order_id=order_a["id"])
    assert rows == [], f"a rejected order appends no ledger entry, got {rows}"


# ---------------------------------------------------------------------------
# Local arrangement for the permit-revocation chain
# ---------------------------------------------------------------------------
# The club order: one line of 6 x 750 ml at 2600 cents with a club subscription
# named, so the twelve-step chain of PRD §3.5 runs with the club concession.
#   line_liters      6 * 750 / 1000                     = 4.500
#   subtotal         6 * 2600                           = 15600
#   shipping_gross   1500 + 220 * 4.500                 =  2490
#   tier             4.500 <= 9.000 so x1.00            =  2490
#   discount         2500 bps of 2490 -> 622.5 half up  =   623
#   shipping         2490 - 623                         =  1867
#   excise           round(4.500 * 55) = 248, credit
#                    1500 bps -> 37.2 half up 37        =   211
#   sales tax        (15600 + 1867) * 825 / 10000
#                    = 1441.0275 half up                =  1441
#   pre_fee_total    15600 + 1867 + 211 + 1441          = 19119
#   handling fee     19119 < 20000 so                   =   900
#   total            19119 + 900                        = 20019
CLUB_ORDER_LINE = {
    "sku": "CLUB-750",
    "bottle_ml": 750,
    "bottles": 6,
    "unit_price_cents": 2600,
}
CLUB_ORDER_SUBTOTAL_CENTS = 15600
CLUB_ORDER_SHIPPING_GROSS_CENTS = 2490
CLUB_ORDER_SHIPPING_TIERED_CENTS = 2490
CLUB_ORDER_SHIPPING_DISCOUNT_CENTS = 623
CLUB_ORDER_SHIPPING_CENTS = 1867
CLUB_ORDER_EXCISE_CENTS = 211
CLUB_ORDER_SALES_TAX_CENTS = 1441
CLUB_ORDER_PRE_FEE_TOTAL_CENTS = 19119
CLUB_ORDER_HANDLING_FEE_CENTS = 900
CLUB_ORDER_TOTAL_CENTS = 20019

REVOCATION_REASON = "Permit revoked for late excise filing"


def _cleared_club_order(api):
    """An ACTIVE MONTHLY subscription plus one CLEARED, still-UNFULFILLED order."""
    scape = build_landscape(api)
    subscription = scape.create_subscription(next_run_date="2026-08-15")
    order = scape.create_order(
        lines=[f.order_line(**CLUB_ORDER_LINE)],
        club_subscription_id=subscription["id"],
    )
    cleared = scape.screen(order["id"])
    assert_order_dimensions(
        cleared, compliance_status="CLEARED", fulfillment_status="UNFULFILLED"
    )
    return scape, subscription, cleared


# ---------------------------------------------------------------------------
# Instance: permit_revoke_three_hop_cascade_to_winery_counter
# ---------------------------------------------------------------------------
def test_club_order_charge_chain_is_frozen_before_the_revocation(api):
    """The club concession and the pre-fee waiver test pin this order at 20019.

    PRD §3.5: "`shipping_discount_cents` is the wine-club shipping concession: when
    `club_subscription_id` is not null it is 2,500 basis points — one quarter — of
    `shipping_tiered_cents`, rounded half up to whole cents; when
    `club_subscription_id` is null it is 0."
    PRD §3.5: "`compliance_handling_fee_cents` is 0 when `pre_fee_total_cents` is
    at least 20,000 cents — two hundred dollars — and otherwise 900 cents."

    Design: Difficulty/transitive_cascade/permit_revoke_three_hop_cascade_to_winery_counter
    """
    _, _, cleared = _cleared_club_order(api)

    assert_charge_chain(
        cleared,
        total_liters=CANONICAL_ORDER_TOTAL_LITERS,
        subtotal_cents=CLUB_ORDER_SUBTOTAL_CENTS,
        shipping_gross_cents=CLUB_ORDER_SHIPPING_GROSS_CENTS,
        shipping_tiered_cents=CLUB_ORDER_SHIPPING_TIERED_CENTS,
        shipping_discount_cents=CLUB_ORDER_SHIPPING_DISCOUNT_CENTS,
        shipping_cents=CLUB_ORDER_SHIPPING_CENTS,
        excise_tax_cents=CLUB_ORDER_EXCISE_CENTS,
        sales_tax_cents=CLUB_ORDER_SALES_TAX_CENTS,
        pre_fee_total_cents=CLUB_ORDER_PRE_FEE_TOTAL_CENTS,
        compliance_handling_fee_cents=CLUB_ORDER_HANDLING_FEE_CENTS,
        total_cents=CLUB_ORDER_TOTAL_CENTS,
    )


def test_revocation_records_the_reason_and_suspends_the_unfulfilled_order(api):
    """Hops 0 and 1: the permit dies and the cleared, unfulfilled order freezes.

    PRD §3.2: "The request supplies a `revocation_reason`, which is recorded on the
    row alongside the new `REVOKED` status."
    PRD §3.2: "**First**, every order of that winery bound for that state whose
    `compliance_status` is `CLEARED` and whose `fulfillment_status` is still
    `UNFULFILLED` is moved `CLEARED` -> `SUSPENDED_PERMIT`, with
    `ERR_PERMIT_NOT_ACTIVE` written into its `rejection_error_id`."

    Design: Difficulty/transitive_cascade/permit_revoke_three_hop_cascade_to_winery_counter
    """
    scape, _, cleared = _cleared_club_order(api)

    scape.revoke_permit(reason=REVOCATION_REASON)

    permit = scape.read_permit()
    assert permit["status"] == "REVOKED"
    assert permit["revocation_reason"] == REVOCATION_REASON

    reread_order = scape.read_order(cleared["id"])
    assert_order_dimensions(
        reread_order,
        compliance_status="SUSPENDED_PERMIT",
        fulfillment_status="UNFULFILLED",
    )
    assert reread_order["rejection_error_id"] == "ERR_PERMIT_NOT_ACTIVE"


def test_revocation_suspends_the_named_club_subscription_and_nulls_its_run_date(api):
    """Hop 2 fires only because the order left ``CLEARED``.

    PRD §3.2: "**Second**, because those orders left `CLEARED`, any club
    subscription named by a suspended order's `club_subscription_id` whose
    `status` is `ACTIVE` is moved `ACTIVE` -> `SUSPENDED_COMPLIANCE`, and its
    `next_run_date` is set to null so that it can never be picked up by a future
    run."

    Design: Difficulty/transitive_cascade/permit_revoke_three_hop_cascade_to_winery_counter
    """
    scape, subscription, _ = _cleared_club_order(api)
    assert subscription["status"] == "ACTIVE"
    assert subscription["next_run_date"] == "2026-08-15"

    scape.revoke_permit(reason=REVOCATION_REASON)

    reread = scape.read_subscription(subscription["id"])
    assert reread["status"] == "SUSPENDED_COMPLIANCE"
    assert reread["next_run_date"] is None, (
        f"next_run_date must be nulled, got {reread['next_run_date']!r}"
    )


def test_revocation_recomputes_the_winery_suspended_subscription_counter(api):
    """Hop 3 fires only because the subscription changed status.

    PRD §3.2: "**Third**, because those subscriptions changed status, the winery's
    `suspended_subscription_count` is recomputed as the number of that winery's
    subscriptions now sitting in `SUSPENDED_COMPLIANCE`, and `Winery.version`
    increments by 1."

    Design: Difficulty/transitive_cascade/permit_revoke_three_hop_cascade_to_winery_counter
    """
    scape, _, _ = _cleared_club_order(api)

    scape.revoke_permit(reason=REVOCATION_REASON)

    winery = scape.read_winery()
    assert winery["suspended_subscription_count"] == 1, (
        "exactly one subscription now sits in SUSPENDED_COMPLIANCE, got "
        f"{winery['suspended_subscription_count']}"
    )
    assert_cents(
        winery["excise_accrued_cents"],
        CLUB_ORDER_EXCISE_CENTS,
        "excise_accrued_cents",
    )


def test_suspension_is_not_a_return_so_nothing_is_reversed_or_released(api):
    """The cascade reverses no money and gives back no liters.

    PRD §3.2: "Critically, the volume the suspended order consumed is **not** given
    back: the ledger entry that debited it stays exactly where it is, because
    suspension is not a terminal outcome and the liters remain reserved for an
    order that may yet be re-screened and cleared."

    Design: Difficulty/transitive_cascade/permit_revoke_three_hop_cascade_to_winery_counter
    """
    scape, _, cleared = _cleared_club_order(api)

    scape.revoke_permit(reason=REVOCATION_REASON)

    winery = scape.read_winery()
    assert_cents(winery["excise_reversed_cents"], 0, "excise_reversed_cents")

    reread_order = scape.read_order(cleared["id"])
    assert_cents(reread_order["excise_reversed_cents"], 0, "excise_reversed_cents")
    assert_cents(
        reread_order["sales_tax_reversed_cents"], 0, "sales_tax_reversed_cents"
    )

    rows = scape.ledger_rows(order_id=cleared["id"])
    assert len(rows) == 1, (
        "the original clearance debit must be the only ledger row, got "
        f"{len(rows)} rows"
    )
    assert_ledger_entry(
        rows[0],
        event_type="SHIPMENT_ACCEPTED",
        liters=CANONICAL_ORDER_TOTAL_LITERS,
        state_code="TX",
        order_id=cleared["id"],
    )

    consumer = scape.read_consumer()
    assert_liters(
        consumer["rolling_liters_by_state"]["TX"],
        CANONICAL_ORDER_TOTAL_LITERS,
        "rolling_liters_by_state[TX]",
    )
