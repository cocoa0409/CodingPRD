"""Compensating invariants of the Winery DTC Shipping Compliance API.

Two multi-stage reversal paths are exercised here, and both are asserted the way
PRD.md states they must be recorded: as *new* signed rows and dedicated reversal
fields, never as an edit of history.

  1. A package comes back and is then re-shipped.  The volume ledger nets to
     0.000 after the return and back to +4.500 after the re-ship, because the
     ledger is append-only and the compensation is a mirror row rather than a
     deletion.  The audit counter behind the risk model is deliberately *not*
     compensated.
  2. A permit is revoked under a CLEARED order and the frozen order is finally
     re-screened into REJECTED.  Suspension compensates nothing at all; only the
     terminal rejection reverses the liters and the money, and the winery's gross
     accrual stays visible next to an equal reversal so that the net is zero.

Every expectation is quoted from PRD.md and every cent and litre below was
recomputed from the PRD §3.5 chain and the PRD §2.7 rounding discipline against
the canonical 4.500 L TX order (6 x 750 ml at 4200 cents):

    total_liters 4.500, subtotal 25200, shipping 2490, excise 211,
    sales tax 2284, handling fee 0 (pre-fee total 30185 >= 20000),
    total 30185.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories as f
from test_helpers.api_client import DtcApiClient  # noqa: F401  (client under test)
from test_helpers.assertions import (
    assert_cents,
    assert_charge_chain,
    assert_immutable_identity,
    assert_instant_equals,
    assert_ledger_entry,
    assert_ledger_sums_to,
    assert_liters,
    assert_order_dimensions,
    assert_rejection,
)
from test_helpers.constants import (
    CANONICAL_ORDER_EXCISE_CENTS,
    CANONICAL_ORDER_SALES_TAX_CENTS,
    CANONICAL_ORDER_TOTAL_CENTS,
    CANONICAL_ORDER_TOTAL_LITERS,
    CLOCK_DEFAULT_CANONICAL,
    STATE_RULE_TX,
)
from test_helpers.fixtures import build_in_transit_order, build_landscape
from test_helpers.test_users import OFFICER_A

TX_LIMIT_LITERS = STATE_RULE_TX["per_consumer_limit_liters"]
LITERS_TOLERANCE = 0.0005


# ---------------------------------------------------------------------------
# Local helpers
# ---------------------------------------------------------------------------
def _per_state_numbers(summary, state_code):
    """Every numeric figure the volume summary reports for one state.

    PRD §3.4 pins the content of the ``per_state`` map — accumulated rolling
    liters, the per-consumer limit and the headroom between them — without
    pinning the three key names, so the figures are matched by value.
    """
    entry = summary["per_state"][state_code]
    return [
        value
        for value in entry.values()
        if isinstance(value, (int, float)) and not isinstance(value, bool)
    ]


def _assert_summary_rolling(summary, state_code, rolling, limit=TX_LIMIT_LITERS):
    """The accumulated liters, the limit and the headroom the summary reports."""
    values = _per_state_numbers(summary, state_code)
    for expected in (rolling, limit, limit - rolling):
        assert any(abs(value - expected) <= LITERS_TOLERANCE for value in values), (
            f"per_state.{state_code} must report {expected:.3f}; got {values}"
        )


def _state_liters(mapping, state_code):
    """One state's figure out of a ``rolling_liters_*_by_state`` map."""
    assert isinstance(mapping, dict), f"Expected a per-state map, got {mapping!r}"
    assert state_code in mapping, (
        f"Expected state {state_code} to be present in {mapping!r}"
    )
    return mapping[state_code]


def _order_ledger(landscape, order_id):
    """Every ledger row of one order (PRD §3.4 ``order_id`` filter)."""
    return landscape.ledger_rows(order_id=order_id)


def _rows_of_type(rows, event_type):
    """The subset of ledger rows carrying one ``event_type`` (PRD §3.4)."""
    return [row for row in rows if row["event_type"] == event_type]


def _only_row_of_type(rows, event_type):
    """Exactly one ledger row of the given ``event_type`` must be present."""
    matching = _rows_of_type(rows, event_type)
    assert len(matching) == 1, (
        f"Expected exactly one {event_type} row, got {matching}"
    )
    return matching[0]


# ===========================================================================
# A return nets the liters ledger to zero and a re-ship re-debits it
# ===========================================================================
def test_return_appends_a_mirror_ledger_row_instead_of_editing_the_debit(api):
    """The RETURN_CREDIT row is appended beside the original debit, which is left alone.

    "Three resource kinds are deliberately immutable once written and therefore carry only `id` and `created_at` — for these, both `updated_at` and `version` are absent from the resource entirely: **`ProhibitedZip`** (a prohibited-ZIP declaration is appended, never edited or withdrawn), **`OrderLine`** (a line is frozen with its computed money the moment its order is created), and **`VolumeLedgerEntry`** (the ledger is append-only by design; a correction is a new signed entry, never an edit)." (PRD 2.5)

    "Reversals follow a **compensating-entry** discipline rather than a delete-and-rewrite discipline." (PRD 2.10)

    "When an outcome has to be undone — a package comes back, a cleared order is re-screened into rejection — the system does not erase the original ledger entry or zero the original money field." (PRD 2.10)

    "Because the order became `RETURNED`, a ledger entry with `event_type` `RETURN_CREDIT` is appended carrying `liters` equal to negative `total_liters`, `order_id` set, `shipment_id` set to this shipment, and `occurred_at` at the logical clock; the order's `excise_reversed_cents` is set to its `excise_tax_cents` and its `sales_tax_reversed_cents` to its `sales_tax_cents`; and the winery's `excise_reversed_cents` grows by the order's `excise_tax_cents`." (PRD 3.7)

    "Entries are immutable and unversioned, and they can be listed filtered by `consumer_id`, `winery_id`, `order_id`, `shipment_id`, `state_code` and `event_type` — that list is the audit trail behind every volume decision the system has ever made." (PRD 3.4)

    Design: Difficulty/compensating_invariant/liters_ledger_nets_to_zero_on_return_and_is_re_debited_on_reship
    """
    landscape, order, shipment = build_in_transit_order(
        api, lines=f.canonical_lines()
    )

    # The clearance debit, standing alone before the package comes back.
    before = _order_ledger(landscape, order["id"])
    assert len(before) == 1, f"Expected exactly one ledger row before the return, got {before}"
    debit_id = before[0]["id"]
    assert_ledger_entry(
        before[0],
        event_type="SHIPMENT_ACCEPTED",
        liters=CANONICAL_ORDER_TOTAL_LITERS,
        state_code="TX",
        order_id=order["id"],
    )

    landscape.return_to_sender(shipment["id"])

    rows = _order_ledger(landscape, order["id"])
    assert len(rows) == 2, (
        f"The return must append a second row rather than edit the first, got {rows}"
    )

    # The original debit is untouched: same row, same sign, same magnitude.
    debit = _only_row_of_type(rows, "SHIPMENT_ACCEPTED")
    assert debit["id"] == debit_id, "The original SHIPMENT_ACCEPTED row must survive"
    assert_ledger_entry(
        debit,
        event_type="SHIPMENT_ACCEPTED",
        liters=CANONICAL_ORDER_TOTAL_LITERS,
        state_code="TX",
        order_id=order["id"],
    )
    assert debit["shipment_id"] is None, (
        "A SHIPMENT_ACCEPTED entry carries a null shipment_id (PRD 3.4)"
    )

    # The compensation is a new, immutable, oppositely signed row.
    credit = _only_row_of_type(rows, "RETURN_CREDIT")
    assert_immutable_identity(credit)
    assert_ledger_entry(
        credit,
        event_type="RETURN_CREDIT",
        liters=-CANONICAL_ORDER_TOTAL_LITERS,
        state_code="TX",
        order_id=order["id"],
        shipment_id=shipment["id"],
    )
    assert credit["id"] != debit_id
    assert_instant_equals(credit["occurred_at"], CLOCK_DEFAULT_CANONICAL)

    # The two rows net to exactly zero.
    assert_ledger_sums_to(rows, 0.000)


def test_return_puts_the_consumer_rolling_volume_back_to_its_pre_order_value(api):
    """Rolling and settled liters both return to 0.000 once the mirror row exists.

    "`rolling_liters_by_state` then holds, for each state, the signed sum of that consumer's ledger entries for that state whose `occurred_at` falls in the window, rounded half up to three decimal places — every event type included, with `SHIPMENT_ACCEPTED` adding, `RETURN_CREDIT` subtracting, and `MANUAL_ADJUSTMENT` doing either according to its sign." (PRD 3.4)

    "`rolling_liters_settled_by_state` is the same sum over the same window, restricted to entries whose `order_id` is null or whose order's `fulfillment_status` is one of `IN_TRANSIT`, `DELIVERED` or `RETURNED`." (PRD 3.4)

    The return leaves the order at `RETURNED`, so both of this order's entries stay
    inside the settled scope and the settled figure nets to 0.000 as well.

    "Because a `RETURN_CREDIT` entry now exists, the consumer's `rolling_liters_by_state`, `rolling_liters_settled_by_state`, `return_credit_count`, `risk_score_screening` and `risk_score_audit` are all recomputed and `Consumer.version` increments by 1." (PRD 3.7)

    Design: Difficulty/compensating_invariant/liters_ledger_nets_to_zero_on_return_and_is_re_debited_on_reship
    """
    landscape, order, shipment = build_in_transit_order(
        api, lines=f.canonical_lines()
    )

    picked_up = landscape.read_consumer()
    assert_liters(
        _state_liters(picked_up["rolling_liters_by_state"], "TX"),
        CANONICAL_ORDER_TOTAL_LITERS,
        "rolling_liters_by_state.TX",
    )
    version_before = picked_up["version"]

    landscape.return_to_sender(shipment["id"])

    consumer = landscape.read_consumer()
    assert_liters(
        _state_liters(consumer["rolling_liters_by_state"], "TX"),
        0.000,
        "rolling_liters_by_state.TX",
    )
    assert_liters(
        _state_liters(consumer["rolling_liters_settled_by_state"], "TX"),
        0.000,
        "rolling_liters_settled_by_state.TX",
    )
    assert consumer["version"] == version_before + 1, (
        "Appending the RETURN_CREDIT entry increments Consumer.version by exactly 1"
    )

    # The computed read agrees, and the whole 27.000 L of TX headroom is free again.
    summary = landscape.volume_summary(state_code="TX")
    _assert_summary_rolling(summary, "TX", 0.000)


def test_return_records_the_reversal_in_the_dedicated_money_fields(api):
    """The return reverses excise and sales tax into reversal fields, gross figures intact.

    "It appends an offsetting ledger entry with the opposite sign, and it records the reversal in a dedicated field (`Order.excise_reversed_cents`, `Order.sales_tax_reversed_cents`, `Winery.excise_reversed_cents`) so that gross and net figures are both recoverable." (PRD 2.10)

    "Reversal fields on an order are all-or-nothing: each is either 0 or exactly equal to the corresponding gross figure, never a partial amount." (PRD 2.10)

    "The winery's `excise_accrued_cents` grows by the order's `excise_tax_cents` — that counter is the running sum of `excise_tax_cents` across every order of the winery that has reached `CLEARED` at least once — and `Winery.version` increments by 1." (PRD 3.6)

    Design: Difficulty/compensating_invariant/liters_ledger_nets_to_zero_on_return_and_is_re_debited_on_reship
    """
    landscape, order, shipment = build_in_transit_order(
        api, lines=f.canonical_lines()
    )

    winery_before = landscape.read_winery()
    assert_cents(
        winery_before["excise_accrued_cents"],
        CANONICAL_ORDER_EXCISE_CENTS,
        "excise_accrued_cents",
    )
    assert_cents(winery_before["excise_reversed_cents"], 0, "excise_reversed_cents")

    landscape.return_to_sender(shipment["id"])

    reversed_order = landscape.read_order(order["id"])
    assert_cents(
        reversed_order["excise_reversed_cents"],
        CANONICAL_ORDER_EXCISE_CENTS,
        "excise_reversed_cents",
    )
    assert_cents(
        reversed_order["sales_tax_reversed_cents"],
        CANONICAL_ORDER_SALES_TAX_CENTS,
        "sales_tax_reversed_cents",
    )

    # The gross charges are frozen: the reversal never rewrites them.
    assert_charge_chain(
        reversed_order,
        total_liters=CANONICAL_ORDER_TOTAL_LITERS,
        excise_tax_cents=CANONICAL_ORDER_EXCISE_CENTS,
        sales_tax_cents=CANONICAL_ORDER_SALES_TAX_CENTS,
        total_cents=CANONICAL_ORDER_TOTAL_CENTS,
    )

    winery = landscape.read_winery()
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


def test_return_leaves_a_permanent_trace_in_the_return_credit_counter(api):
    """The return credit is counted once and lifts the screening score to exactly 10.

    "`return_credit_count` is the number of that consumer's ledger entries with `event_type` `RETURN_CREDIT` falling inside the widest `per_consumer_period` window in play, and `denied_exception_count` is the number of compliance exceptions in status `DENIED` raised on that consumer's orders." (PRD 3.4)

    "The first factor is 10 points per in-scope return credit, capped at 40." (PRD 3.4)

    "The second factor is 15 points per in-scope denied exception, capped at 30." (PRD 3.4)

    "The third factor is a utilisation term: among the states present in the relevant liters map, the system selects the state with the greatest ratio of accumulated liters to that state's `per_consumer_limit_liters`, breaking a tie in favour of the alphabetically earlier `state_code`; the factor is then 30 multiplied by the selected state's liters divided by that state's per-consumer limit, truncated downward to a whole number, and capped at 30." (PRD 3.4)

    "The **screening** variant is written to `risk_score_screening` and is the only variant that gates anything: its scope is ledger entries inside the state's `per_consumer_period` window whose `order_id` is null or whose order's `fulfillment_status` is `IN_TRANSIT`, `DELIVERED` or `RETURNED`, its utilisation term reads `rolling_liters_settled_by_state`, and its denial count includes only exceptions decided inside that same window." (PRD 3.4)

    "From the screening score alone the system derives `screening_tier`, which is `STANDARD` while `risk_score_screening` is below 50 and becomes `ELEVATED` as soon as `risk_score_screening` reaches 50 or more." (PRD 3.4)

    In transit the settled figure is 4.500 L against the 27.000 L TX limit, so the
    score is 0 + 0 + trunc(30 x 4.500 / 27.000) = 5.  After the return the settled
    figure nets to 0.000 while the return credit is counted, so the score becomes
    10 + 0 + 0 = 10 on both variants.

    Design: Difficulty/compensating_invariant/liters_ledger_nets_to_zero_on_return_and_is_re_debited_on_reship
    """
    landscape, order, shipment = build_in_transit_order(
        api, lines=f.canonical_lines()
    )

    before = landscape.read_consumer()
    assert before["return_credit_count"] == 0
    assert before["risk_score_screening"] == 5, (
        "In transit the utilisation term alone scores trunc(30 x 4.500 / 27.000)"
    )

    landscape.return_to_sender(shipment["id"])

    consumer = landscape.read_consumer()
    assert consumer["return_credit_count"] == 1, (
        "Exactly one RETURN_CREDIT entry exists, so the counter reads 1"
    )
    assert consumer["denied_exception_count"] == 0
    assert consumer["risk_score_screening"] == 10, (
        "10 points for the single in-scope return credit and nothing else"
    )
    assert consumer["risk_score_audit"] == 10, (
        "The all-time variant sees the same single return credit and 0.000 liters"
    )
    assert consumer["screening_tier"] == "STANDARD"

    # The computed read reports the same counters side by side.
    summary = landscape.volume_summary(state_code="TX")
    assert summary["return_credit_count"] == 1
    assert summary["risk_score_screening"] == 10
    assert summary["screening_tier"] == "STANDARD"


def test_reship_re_debits_the_liters_with_a_third_row_rather_than_un_crediting(api):
    """The re-ship appends a second SHIPMENT_ACCEPTED row; nothing is deleted.

    "A **re-ship** — a label whose `replacement_of_shipment_id` names a shipment in `RETURNED` status belonging to the same order — is the loop that makes the fulfillment dimension cyclic, running `UNFULFILLED` → `LABELED` → `IN_TRANSIT` → `RETURNED` → `LABELED`." (PRD 3.7)

    "Because the return credited the consumer's liters back, the re-ship must re-debit them, and it must therefore satisfy the per-consumer and per-winery volume limits all over again — a re-ship into a state whose room has since been taken by another order is refused." (PRD 3.7)

    "On success a new shipment row is created in `LABEL_CREATED` with `replacement_of_shipment_id` set, a `SHIPMENT_ACCEPTED` ledger entry is appended with `liters` equal to positive `total_liters`, `order_id` set and `shipment_id` null; the order's `excise_reversed_cents` and `sales_tax_reversed_cents` are both put back to 0 and the winery's `excise_reversed_cents` is reduced by the order's `excise_tax_cents`, undoing the reversal the return had recorded; and because the re-debit entry now exists, the consumer's rolling and risk fields are recomputed with `Consumer.version` incrementing by 1." (PRD 3.7)

    Design: Difficulty/compensating_invariant/liters_ledger_nets_to_zero_on_return_and_is_re_debited_on_reship
    """
    landscape, order, shipment = build_in_transit_order(
        api, lines=f.canonical_lines()
    )
    landscape.return_to_sender(shipment["id"])

    after_return = _order_ledger(landscape, order["id"])
    original_ids = {row["id"] for row in after_return}
    version_before = landscape.read_consumer()["version"]

    landscape.label(order["id"], replacement_of_shipment_id=shipment["id"])

    rows = _order_ledger(landscape, order["id"])
    assert len(rows) == 3, (
        f"The re-ship must append a third row rather than remove the credit, got {rows}"
    )
    assert original_ids.issubset({row["id"] for row in rows}), (
        "Neither of the first two ledger rows may disappear on a re-ship"
    )

    # The credit is still on file with its original negative sign.
    credit = _only_row_of_type(rows, "RETURN_CREDIT")
    assert_liters(credit["liters"], -CANONICAL_ORDER_TOTAL_LITERS, "liters")

    debits = _rows_of_type(rows, "SHIPMENT_ACCEPTED")
    assert len(debits) == 2, f"Expected two SHIPMENT_ACCEPTED rows, got {debits}"
    redebit = [row for row in debits if row["id"] not in original_ids]
    assert len(redebit) == 1, "Exactly one of the two debits is newly appended"
    assert_immutable_identity(redebit[0])
    assert_ledger_entry(
        redebit[0],
        event_type="SHIPMENT_ACCEPTED",
        liters=CANONICAL_ORDER_TOTAL_LITERS,
        state_code="TX",
        order_id=order["id"],
    )
    assert redebit[0]["shipment_id"] is None, (
        "The re-debit entry carries a null shipment_id"
    )
    assert_instant_equals(redebit[0]["occurred_at"], CLOCK_DEFAULT_CANONICAL)

    # Three rows, one of them negative, summing back to the order's own volume.
    assert_ledger_sums_to(rows, CANONICAL_ORDER_TOTAL_LITERS)

    consumer = landscape.read_consumer()
    assert_liters(
        _state_liters(consumer["rolling_liters_by_state"], "TX"),
        CANONICAL_ORDER_TOTAL_LITERS,
        "rolling_liters_by_state.TX",
    )
    assert consumer["version"] == version_before + 1, (
        "The re-debit entry increments Consumer.version by exactly 1"
    )

    summary = landscape.volume_summary(state_code="TX")
    _assert_summary_rolling(summary, "TX", CANONICAL_ORDER_TOTAL_LITERS)


def test_reship_undoes_the_money_reversal_without_touching_the_frozen_charges(api):
    """The re-ship puts both reversal fields back to 0 and leaves the gross charges alone.

    "On success a new shipment row is created in `LABEL_CREATED` with `replacement_of_shipment_id` set, a `SHIPMENT_ACCEPTED` ledger entry is appended with `liters` equal to positive `total_liters`, `order_id` set and `shipment_id` null; the order's `excise_reversed_cents` and `sales_tax_reversed_cents` are both put back to 0 and the winery's `excise_reversed_cents` is reduced by the order's `excise_tax_cents`, undoing the reversal the return had recorded; and because the re-debit entry now exists, the consumer's rolling and risk fields are recomputed with `Consumer.version` incrementing by 1." (PRD 3.7)

    "Every monetary and volumetric field on the order and on each of its lines is computed exactly once, at creation, from the governing state rule and the winery, and then **frozen**." (PRD 3.5)

    "Nothing later in the order's life recomputes them — not screening, not an override, not a return." (PRD 3.5)

    "Reversal fields on an order are all-or-nothing: each is either 0 or exactly equal to the corresponding gross figure, never a partial amount." (PRD 2.10)

    Design: Difficulty/compensating_invariant/liters_ledger_nets_to_zero_on_return_and_is_re_debited_on_reship
    """
    landscape, order, shipment = build_in_transit_order(
        api, lines=f.canonical_lines()
    )
    landscape.return_to_sender(shipment["id"])

    # The return has recorded a full reversal on both tiers.
    returned = landscape.read_order(order["id"])
    assert_cents(
        returned["excise_reversed_cents"],
        CANONICAL_ORDER_EXCISE_CENTS,
        "excise_reversed_cents",
    )
    assert_cents(
        returned["sales_tax_reversed_cents"],
        CANONICAL_ORDER_SALES_TAX_CENTS,
        "sales_tax_reversed_cents",
    )
    assert_cents(
        landscape.read_winery()["excise_reversed_cents"],
        CANONICAL_ORDER_EXCISE_CENTS,
        "excise_reversed_cents",
    )

    landscape.label(order["id"], replacement_of_shipment_id=shipment["id"])

    reshipped = landscape.read_order(order["id"])
    assert_cents(reshipped["excise_reversed_cents"], 0, "excise_reversed_cents")
    assert_cents(reshipped["sales_tax_reversed_cents"], 0, "sales_tax_reversed_cents")

    # None of the frozen charge-chain figures moved through the round trip.
    assert_charge_chain(
        reshipped,
        total_liters=CANONICAL_ORDER_TOTAL_LITERS,
        excise_tax_cents=CANONICAL_ORDER_EXCISE_CENTS,
        sales_tax_cents=CANONICAL_ORDER_SALES_TAX_CENTS,
        total_cents=CANONICAL_ORDER_TOTAL_CENTS,
    )

    winery = landscape.read_winery()
    assert_cents(winery["excise_reversed_cents"], 0, "excise_reversed_cents")
    assert_cents(
        winery["excise_accrued_cents"],
        CANONICAL_ORDER_EXCISE_CENTS,
        "excise_accrued_cents",
    )


def test_reship_leaves_the_returned_shipment_and_the_return_counter_standing(api):
    """A new LABEL_CREATED row points back at the RETURNED one, which keeps its status.

    "A **re-ship** — a label whose `replacement_of_shipment_id` names a shipment in `RETURNED` status belonging to the same order — is the loop that makes the fulfillment dimension cyclic, running `UNFULFILLED` → `LABELED` → `IN_TRANSIT` → `RETURNED` → `LABELED`." (PRD 3.7)

    "The shipment's `status` becomes `RETURNED` and its `returned_at` is stamped from the logical clock." (PRD 3.7)

    "Note what a return does **not** do: it leaves the order's `compliance_status` at `CLEARED`." (PRD 3.7)

    "`return_credit_count` is the number of that consumer's ledger entries with `event_type` `RETURN_CREDIT` falling inside the widest `per_consumer_period` window in play, and `denied_exception_count` is the number of compliance exceptions in status `DENIED` raised on that consumer's orders." (PRD 3.4)

    The re-ship appends a debit rather than removing the credit, so the counter
    that the credit produced still reads 1 once the round trip is complete.

    Design: Difficulty/compensating_invariant/liters_ledger_nets_to_zero_on_return_and_is_re_debited_on_reship
    """
    landscape, order, shipment = build_in_transit_order(
        api, lines=f.canonical_lines()
    )
    landscape.return_to_sender(shipment["id"])

    first = landscape.read_shipment(shipment["id"])
    assert first["status"] == "RETURNED"
    assert_instant_equals(first["returned_at"], CLOCK_DEFAULT_CANONICAL)
    returned_order = landscape.read_order(order["id"])
    assert_order_dimensions(
        returned_order, compliance_status="CLEARED", fulfillment_status="RETURNED"
    )
    assert_instant_equals(returned_order["returned_at"], CLOCK_DEFAULT_CANONICAL)

    replacement = landscape.label(
        order["id"], replacement_of_shipment_id=shipment["id"]
    )

    assert replacement["replacement_of_shipment_id"] == shipment["id"]
    assert replacement["status"] == "LABEL_CREATED"
    assert replacement["id"] != shipment["id"]

    # The returned package is not rewritten into the replacement.
    assert landscape.read_shipment(shipment["id"])["status"] == "RETURNED", (
        "The returned shipment keeps its terminal RETURNED status"
    )

    reshipped = landscape.read_order(order["id"])
    assert_order_dimensions(
        reshipped, compliance_status="CLEARED", fulfillment_status="LABELED"
    )

    # The audit trace of the round trip is deliberately not compensated.
    assert landscape.read_consumer()["return_credit_count"] == 1, (
        "The RETURN_CREDIT row still exists, so the counter still reads 1"
    )


# ===========================================================================
# The winery excise accrual nets to zero when a suspended order is rejected
# ===========================================================================
def _cleared_unfulfilled_order(api):
    """A CLEARED, still UNFULFILLED canonical order and its landscape."""
    landscape = build_landscape(api)
    order = landscape.create_order(lines=f.canonical_lines())
    cleared = landscape.screen(order["id"])
    assert_order_dimensions(
        cleared, compliance_status="CLEARED", fulfillment_status="UNFULFILLED"
    )
    return landscape, cleared


def test_permit_revocation_suspends_the_order_and_compensates_nothing(api):
    """Stage one deliberately reverses neither the liters nor the money.

    "**First**, every order of that winery bound for that state whose `compliance_status` is `CLEARED` and whose `fulfillment_status` is still `UNFULFILLED` is moved `CLEARED` → `SUSPENDED_PERMIT`, with `ERR_PERMIT_NOT_ACTIVE` written into its `rejection_error_id`." (PRD 3.2)

    "Critically, the volume the suspended order consumed is **not** given back: the ledger entry that debited it stays exactly where it is, because suspension is not a terminal outcome and the liters remain reserved for an order that may yet be re-screened and cleared." (PRD 3.2)

    "The winery's `excise_accrued_cents` grows by the order's `excise_tax_cents` — that counter is the running sum of `excise_tax_cents` across every order of the winery that has reached `CLEARED` at least once — and `Winery.version` increments by 1." (PRD 3.6)

    Design: Difficulty/compensating_invariant/winery_excise_accrual_nets_to_zero_when_a_suspended_order_is_finally_rejected
    """
    landscape, order = _cleared_unfulfilled_order(api)

    accrued = landscape.read_winery()
    assert_cents(
        accrued["excise_accrued_cents"],
        CANONICAL_ORDER_EXCISE_CENTS,
        "excise_accrued_cents",
    )
    assert_cents(accrued["excise_reversed_cents"], 0, "excise_reversed_cents")

    landscape.revoke_permit()

    suspended = landscape.read_order(order["id"])
    assert_order_dimensions(
        suspended,
        compliance_status="SUSPENDED_PERMIT",
        fulfillment_status="UNFULFILLED",
    )
    assert_rejection(suspended, "ERR_PERMIT_NOT_ACTIVE")

    # No compensation of any kind: the reversal fields stay at zero.
    assert_cents(suspended["excise_reversed_cents"], 0, "excise_reversed_cents")
    assert_cents(suspended["sales_tax_reversed_cents"], 0, "sales_tax_reversed_cents")

    # The debit stays exactly where it is — one row, still positive.
    rows = _order_ledger(landscape, order["id"])
    assert len(rows) == 1, (
        f"Suspension must not append or remove any ledger row, got {rows}"
    )
    assert_ledger_entry(
        rows[0],
        event_type="SHIPMENT_ACCEPTED",
        liters=CANONICAL_ORDER_TOTAL_LITERS,
        state_code="TX",
        order_id=order["id"],
    )
    assert_ledger_sums_to(rows, CANONICAL_ORDER_TOTAL_LITERS)

    # The liters stay reserved against the consumer's headroom.
    consumer = landscape.read_consumer()
    assert_liters(
        _state_liters(consumer["rolling_liters_by_state"], "TX"),
        CANONICAL_ORDER_TOTAL_LITERS,
        "rolling_liters_by_state.TX",
    )
    assert consumer["return_credit_count"] == 0, (
        "Suspension appends no RETURN_CREDIT row"
    )

    # The money stays accrued while the order might still be rescued.
    winery = landscape.read_winery()
    assert_cents(
        winery["excise_accrued_cents"],
        CANONICAL_ORDER_EXCISE_CENTS,
        "excise_accrued_cents",
    )
    assert_cents(winery["excise_reversed_cents"], 0, "excise_reversed_cents")


def test_re_screening_the_suspended_order_records_the_missing_permit_at_http_200(api):
    """The re-screen answers 200 and records ERR_PERMIT_MISSING_FOR_STATE, not an error.

    "**Screening never returns an error envelope.**" (PRD 2.9)

    "It always answers HTTP 200 with the order body, and the outcome is expressed by moving the order's compliance dimension and writing the identifier of the *first* — that is, the highest-ranked — failing ladder rule into the order's `rejection_error_id`." (PRD 2.9)

    "Only two starting states admit a screen: `DRAFT`, the ordinary case, and `SUSPENDED_PERMIT`, the re-screen of an order that a revocation had frozen." (PRD 3.6)

    "- **A licence must exist for the destination state.** The winery must hold a state permit for the order's `ship_to_state_code` in any status other than `REVOKED`; if it holds none, `ERR_PERMIT_MISSING_FOR_STATE`." (PRD 3.6)

    The only TX permit is now `REVOKED`, so the winery holds none that counts and
    the ladder fails one rung above the in-force test.

    Design: Difficulty/compensating_invariant/winery_excise_accrual_nets_to_zero_when_a_suspended_order_is_finally_rejected
    """
    landscape, order = _cleared_unfulfilled_order(api)
    landscape.revoke_permit()

    response = api.screen_order(order["id"], {}, OFFICER_A)
    screened = validate_success(response, expected_status=200)

    assert_order_dimensions(
        screened, compliance_status="REJECTED", fulfillment_status="UNFULFILLED"
    )
    assert_rejection(screened, "ERR_PERMIT_MISSING_FOR_STATE")

    # The same two facts are readable back off the order.
    stored = landscape.read_order(order["id"])
    assert_order_dimensions(stored, compliance_status="REJECTED")
    assert_rejection(stored, "ERR_PERMIT_MISSING_FOR_STATE")


def test_terminal_rejection_nets_the_winery_excise_accrual_to_zero(api):
    """Stage two reverses the money without decrementing the gross accrual.

    "A **`SUSPENDED_PERMIT` → `REJECTED`** outcome is where the reversal finally happens: the failing identifier is written to `rejection_error_id`, a `RETURN_CREDIT` ledger entry is appended with `liters` equal to negative `total_liters`, `order_id` set and `shipment_id` null, reversing the original debit; the order's `excise_reversed_cents` is set to its `excise_tax_cents` and its `sales_tax_reversed_cents` to its `sales_tax_cents`; the winery's `excise_reversed_cents` grows by the order's `excise_tax_cents`; and because a reversing entry now exists, the consumer's rolling and risk fields are recomputed with `Consumer.version` incrementing by 1." (PRD 3.6)

    "It appends an offsetting ledger entry with the opposite sign, and it records the reversal in a dedicated field (`Order.excise_reversed_cents`, `Order.sales_tax_reversed_cents`, `Winery.excise_reversed_cents`) so that gross and net figures are both recoverable." (PRD 2.10)

    "Reversal fields on an order are all-or-nothing: each is either 0 or exactly equal to the corresponding gross figure, never a partial amount." (PRD 2.10)

    The order's frozen excise is 211 cents and its frozen sales tax is 2284 cents,
    so the winery ends at 211 accrued against 211 reversed — a net of exactly 0
    with the gross accrual still on display.

    Design: Difficulty/compensating_invariant/winery_excise_accrual_nets_to_zero_when_a_suspended_order_is_finally_rejected
    """
    landscape, order = _cleared_unfulfilled_order(api)
    landscape.revoke_permit()
    landscape.screen(order["id"])

    rejected = landscape.read_order(order["id"])
    assert_order_dimensions(rejected, compliance_status="REJECTED")
    assert_cents(
        rejected["excise_reversed_cents"],
        CANONICAL_ORDER_EXCISE_CENTS,
        "excise_reversed_cents",
    )
    assert_cents(
        rejected["sales_tax_reversed_cents"],
        CANONICAL_ORDER_SALES_TAX_CENTS,
        "sales_tax_reversed_cents",
    )

    # The charge itself is never edited: only the reversal fields moved.
    assert_charge_chain(
        rejected,
        total_liters=CANONICAL_ORDER_TOTAL_LITERS,
        excise_tax_cents=CANONICAL_ORDER_EXCISE_CENTS,
        sales_tax_cents=CANONICAL_ORDER_SALES_TAX_CENTS,
        total_cents=CANONICAL_ORDER_TOTAL_CENTS,
    )

    winery = landscape.read_winery()
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
    assert (
        winery["excise_accrued_cents"] - winery["excise_reversed_cents"] == 0
    ), (
        "The winery's net excise must be exactly zero once the order is rejected, "
        "with the gross accrual left visible for audit"
    )


def test_terminal_rejection_appends_a_return_credit_that_nets_the_liters_to_zero(api):
    """Stage two releases the reserved liters with a mirror row, not a deletion.

    "A **`SUSPENDED_PERMIT` → `REJECTED`** outcome is where the reversal finally happens: the failing identifier is written to `rejection_error_id`, a `RETURN_CREDIT` ledger entry is appended with `liters` equal to negative `total_liters`, `order_id` set and `shipment_id` null, reversing the original debit; the order's `excise_reversed_cents` is set to its `excise_tax_cents` and its `sales_tax_reversed_cents` to its `sales_tax_cents`; the winery's `excise_reversed_cents` grows by the order's `excise_tax_cents`; and because a reversing entry now exists, the consumer's rolling and risk fields are recomputed with `Consumer.version` incrementing by 1." (PRD 3.6)

    "`rolling_liters_by_state` then holds, for each state, the signed sum of that consumer's ledger entries for that state whose `occurred_at` falls in the window, rounded half up to three decimal places — every event type included, with `SHIPMENT_ACCEPTED` adding, `RETURN_CREDIT` subtracting, and `MANUAL_ADJUSTMENT` doing either according to its sign." (PRD 3.4)

    "Three resource kinds are deliberately immutable once written and therefore carry only `id` and `created_at` — for these, both `updated_at` and `version` are absent from the resource entirely: **`ProhibitedZip`** (a prohibited-ZIP declaration is appended, never edited or withdrawn), **`OrderLine`** (a line is frozen with its computed money the moment its order is created), and **`VolumeLedgerEntry`** (the ledger is append-only by design; a correction is a new signed entry, never an edit)." (PRD 2.5)

    Design: Difficulty/compensating_invariant/winery_excise_accrual_nets_to_zero_when_a_suspended_order_is_finally_rejected
    """
    landscape, order = _cleared_unfulfilled_order(api)
    landscape.revoke_permit()

    debit_id = _order_ledger(landscape, order["id"])[0]["id"]
    version_before = landscape.read_consumer()["version"]

    landscape.screen(order["id"])

    rows = _order_ledger(landscape, order["id"])
    assert len(rows) == 2, (
        f"The rejection must append the reversing row, not edit the debit, got {rows}"
    )

    debit = _only_row_of_type(rows, "SHIPMENT_ACCEPTED")
    assert debit["id"] == debit_id, "The original debit row must survive the rejection"
    assert_liters(debit["liters"], CANONICAL_ORDER_TOTAL_LITERS, "liters")

    credit = _only_row_of_type(rows, "RETURN_CREDIT")
    assert_immutable_identity(credit)
    assert_ledger_entry(
        credit,
        event_type="RETURN_CREDIT",
        liters=-CANONICAL_ORDER_TOTAL_LITERS,
        state_code="TX",
        order_id=order["id"],
    )
    assert credit["shipment_id"] is None, (
        "No shipment was ever drawn, so the reversing row carries a null shipment_id"
    )

    assert_ledger_sums_to(rows, 0.000)

    consumer = landscape.read_consumer()
    assert_liters(
        _state_liters(consumer["rolling_liters_by_state"], "TX"),
        0.000,
        "rolling_liters_by_state.TX",
    )
    assert consumer["version"] == version_before + 1, (
        "Appending the reversing entry increments Consumer.version by exactly 1"
    )

    # The whole 27.000 L of TX headroom is free again.
    summary = landscape.volume_summary(state_code="TX")
    _assert_summary_rolling(summary, "TX", 0.000)
