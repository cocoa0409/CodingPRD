"""Unwinds that must return a conserved quantity to a known figure.

Three quantities are put out of balance and then restored.  A placement's
ledger net is driven to 22275 by a conversion and must return to exactly 0 on
reversal.  An address's occupancy window is taken by a schedule and must be
released by the move's cancellation.  A move's open deposit liability is
raised to 18000 by a bureau answer and must return to 0 when the handoff is
voided by a provider failure.

Every one of those three figures is derived by summing or counting a listing,
never read from a field that merely claims to hold it.
"""

from typing import Any, Dict

from test_helpers import factories as f
from test_helpers import fixtures
from test_helpers.api_client import ApiClient
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_cents,
    assert_entry_types,
    assert_error,
    assert_immutable_resource,
    assert_ledger_net,
    assert_move_state,
    assert_ok,
    assert_order_dimensions,
    assert_page,
    assert_window_released,
    get_success_data,
    ledger_net,
)
from test_helpers.constants import CLOCK_STARTUP_DEFAULT
from test_helpers.test_users import make_provider_agent_headers
from test_helpers.types import (
    BlockedReason,
    ConsentScope,
    CreditResult,
    CreditStatus,
    HandoffStatus,
    LedgerEntryType,
    MoveLifecycleStatus,
    OrderCancellationReason,
    PlacementStatus,
    ProvisionStatus,
    UtilityType,
)


# ---------------------------------------------------------------------------
# Local derivations of the three conserved quantities
# ---------------------------------------------------------------------------
def occupied_window_count(
    api: ApiClient, service_address_id: str, utility_type: str, headers: Dict[str, str]
) -> int:
    """Count the orders holding a window on one address and utility pairing."""
    orders = get_success_data(
        api.list_utility_orders(
            headers,
            service_address_id=service_address_id,
            utility_type=utility_type,
            limit=100,
        )
    )
    holding = {ProvisionStatus.SCHEDULED.value, ProvisionStatus.ACTIVE_SERVICE.value}
    return sum(1 for order in orders if order["provision_status"] in holding)


def open_deposit_liability_cents(api: ApiClient, move_id: str, headers: Dict[str, str]) -> int:
    """Sum `deposit_amount_cents` over the move's orders still in DEPOSIT_DUE."""
    orders = get_success_data(api.list_utility_orders(headers, move_id=move_id, limit=100))
    return sum(
        order["deposit_amount_cents"]
        for order in orders
        if order["credit_status"] == CreditStatus.DEPOSIT_DUE.value
    )


# ---------------------------------------------------------------------------
# Reversal returns a placement's ledger net to zero
# ---------------------------------------------------------------------------
def test_01_reversal_returns_the_placement_ledger_net_to_zero(api, admin_headers):
    """A chargeback unwinds the accrual without erasing it.

    The conversion posts the waterfall the PRD works through: "a gross of
    100000 cents against a 0.3000 revenue share yields a provisional
    commission of 27000 cents; a feed source on a 0.1750 share takes 4725
    cents of it", and "Conversion posts an `ACCRUAL` entry whose
    `amount_cents` is the positive commission and a `FEED_SOURCE_SHARE` entry
    whose `amount_cents` is the negative of the feed source's cut."  The
    measured net is therefore 22275 before the unwind.  Then "Reversal posts a
    `REVERSAL` entry for the negative of the current `attributed_share_cents`
    and a `FEED_SOURCE_SHARE_REVERSAL` entry for the positive of the current
    `feed_source_share_cents`", and the invariant closes: "At all times it
    equals the placement's current `attributed_share_cents` minus its
    `feed_source_share_cents`, and once a placement has been reversed it
    equals exactly 0."  All four entries survive, and the feed source balance,
    being "the sum of the already-rounded per-placement
    `feed_source_share_cents` over that source's placements in `CONVERTED` or
    `SETTLED`", falls from 4725 back to 0.

    Design: Difficulty/compensating_invariant/placement_reversal_zeroes_ledger_net
    """
    bundle = fixtures.converted_referral(api, gross_revenue_cents=100000)
    placement = bundle["placement"]
    feed_source_id = bundle["feed_source"]["id"]

    assert placement["placement_status"] == PlacementStatus.CONVERTED.value, (
        f"expected the placement CONVERTED, got {placement['placement_status']}"
    )
    assert_cents(placement, "attributed_share_cents", 27000)
    assert_cents(placement, "feed_source_share_cents", 4725)

    before = fixtures.ledger_for_placement(api, placement["id"])
    assert_entry_types(
        before,
        [LedgerEntryType.ACCRUAL.value, LedgerEntryType.FEED_SOURCE_SHARE.value],
    )
    assert before[0]["amount_cents"] == 27000, (
        f"expected an ACCRUAL of 27000, got {before[0]['amount_cents']}"
    )
    assert before[1]["amount_cents"] == -4725, (
        f"expected a FEED_SOURCE_SHARE of -4725, got {before[1]['amount_cents']}"
    )
    assert ledger_net(before) == 22275, (
        f"expected a measured ledger net of 22275, got {ledger_net(before)}"
    )
    assert_ledger_net(before, placement)
    assert_cents(fixtures.read_feed_source(api, feed_source_id), "accrued_share_cents", 4725)

    unwound = assert_ok(
        api.reverse_placement(placement["id"], f.reversal_payload(), admin_headers)
    )
    assert unwound["placement_status"] == PlacementStatus.REVERSED.value, (
        f"expected the placement REVERSED, got {unwound['placement_status']}"
    )
    assert_cents(unwound, "attributed_share_cents", 0)
    assert_cents(unwound, "feed_source_share_cents", 0)
    assert unwound["reversal_reason"], "the reversal must record a non-empty reason"

    after = fixtures.ledger_for_placement(api, placement["id"])
    assert_entry_types(
        after,
        [
            LedgerEntryType.ACCRUAL.value,
            LedgerEntryType.FEED_SOURCE_SHARE.value,
            LedgerEntryType.REVERSAL.value,
            LedgerEntryType.FEED_SOURCE_SHARE_REVERSAL.value,
        ],
    )
    assert after[2]["amount_cents"] == -27000, (
        f"expected a REVERSAL of -27000, got {after[2]['amount_cents']}"
    )
    assert after[3]["amount_cents"] == 4725, (
        f"expected a FEED_SOURCE_SHARE_REVERSAL of 4725, got {after[3]['amount_cents']}"
    )
    assert ledger_net(after) == 0, (
        f"a reversed placement must measure a ledger net of exactly 0, got {ledger_net(after)}"
    )
    assert_ledger_net(after, unwound)
    for entry in after:
        assert_immutable_resource(entry)
    assert_cents(fixtures.read_feed_source(api, feed_source_id), "accrued_share_cents", 0)


def test_02_a_second_reversal_is_refused_and_posts_nothing_further(api, admin_headers):
    """The unwind runs once; the invariant is not re-entered.

    Reversal is reachable only from one state — "acceptance from `PLACED`,
    decline from `ACCEPTED`, conversion from `ACCEPTED`, settlement from
    `CONVERTED`, reversal from `CONVERTED`" — so a placement already
    `REVERSED` refuses the operation with `ERR_PLACEMENT_NOT_CONVERTIBLE` at
    409.  This is the negative case that protects the arithmetic: the ledger
    keeps exactly the four entries the single unwind posted, the measured net
    stays at exactly 0, and the feed source balance stays at 0.

    Design: Difficulty/compensating_invariant/placement_reversal_zeroes_ledger_net
    """
    bundle = fixtures.converted_referral(api, gross_revenue_cents=100000)
    placement = bundle["placement"]
    feed_source_id = bundle["feed_source"]["id"]

    assert_ok(api.reverse_placement(placement["id"], f.reversal_payload(), admin_headers))

    assert_error(
        api.reverse_placement(placement["id"], f.reversal_payload(), admin_headers),
        ApiErrorId.PLACEMENT_NOT_CONVERTIBLE,
        expected_status=409,
    )

    entries = assert_page(
        api.list_ledger_entries(admin_headers, placement_id=placement["id"], limit=100), 4
    )
    assert_entry_types(
        entries,
        [
            LedgerEntryType.ACCRUAL.value,
            LedgerEntryType.FEED_SOURCE_SHARE.value,
            LedgerEntryType.REVERSAL.value,
            LedgerEntryType.FEED_SOURCE_SHARE_REVERSAL.value,
        ],
    )
    assert ledger_net(entries) == 0, (
        f"a refused second reversal must leave the net at 0, got {ledger_net(entries)}"
    )

    still_reversed = get_success_data(api.get_placement(placement["id"], admin_headers))
    assert still_reversed["placement_status"] == PlacementStatus.REVERSED.value, (
        f"expected the placement to stay REVERSED, got {still_reversed['placement_status']}"
    )
    assert_cents(still_reversed, "attributed_share_cents", 0)
    assert_cents(still_reversed, "feed_source_share_cents", 0)
    assert_cents(fixtures.read_feed_source(api, feed_source_id), "accrued_share_cents", 0)


# ---------------------------------------------------------------------------
# Move cancellation releases the occupancy window it took
# ---------------------------------------------------------------------------
def test_03_cancelling_the_move_releases_the_address_occupancy_window(api, ops_headers):
    """The window a schedule took is handed back when the move is cancelled.

    The conserved quantity is defined as "the number of service orders holding
    a window on that pair.  Scheduling adds one; closure, provision failure,
    suspension and cancellation each release one."  Cancellation is the
    wholesale unwind: "Every service order in `DRAFT`, `SCHEDULED`,
    `ACTIVE_SERVICE` or `SUSPENDED` moves to `CANCELLED` with
    `cancellation_reason` `MOVE_CANCELLED` and both window fields cleared,
    which releases each occupied service window."  Measured on the pairing,
    occupancy goes from 1 to 0, and the move's readiness settles at 50 because
    a cancelled order leaves the utility ratio with nothing mapped: identity
    100 and consent 100 only.

    Design: Difficulty/compensating_invariant/order_cancellation_restores_address_window_occupancy
    """
    net = fixtures.build_network(api, clock=CLOCK_STARTUP_DEFAULT)
    bundle = fixtures.mapped_move(
        api, network=net, utility_types=[UtilityType.WATER.value]
    )
    move_id = bundle["move"]["id"]
    address_id = net["destination_address"]["id"]
    order = bundle["orders_by_type"][UtilityType.WATER.value]

    fixtures.schedule_order(
        api,
        order["id"],
        requested_service_date="2026-08-05",
        scheduled_window_start="2026-08-05T09:00:00Z",
        scheduled_window_end="2026-08-05T13:00:00Z",
    )
    assert occupied_window_count(
        api, address_id, UtilityType.WATER.value, ops_headers
    ) == 1, "the schedule must add exactly one occupied window"

    cancelled_move = assert_ok(
        api.cancel_move(move_id, f.cancellation_payload(), ops_headers)
    )
    assert_move_state(
        cancelled_move,
        lifecycle_status=MoveLifecycleStatus.CANCELLED.value,
        blocked_reason=BlockedReason.NONE.value,
        readiness_score=50,
    )

    released = fixtures.read_order(api, order["id"])
    assert released["provision_status"] == ProvisionStatus.CANCELLED.value, (
        f"expected the order CANCELLED, got {released['provision_status']}"
    )
    assert released["cancellation_reason"] == OrderCancellationReason.MOVE_CANCELLED.value, (
        f"expected cancellation_reason MOVE_CANCELLED, got {released['cancellation_reason']}"
    )
    assert_window_released(released)
    assert occupied_window_count(
        api, address_id, UtilityType.WATER.value, ops_headers
    ) == 0, "cancelling the move must return the pairing's occupancy to zero"


def test_04_the_released_window_becomes_bookable_by_another_household(api, ops_headers):
    """The release is real: the identical window is refused, then accepted.

    Before the unwind the second household's identical window intersects a
    live interval and "genuine overlap is refused with
    `ERR_SERVICE_WINDOW_CONFLICT`", with the measured occupancy conserved at 1.
    After the cancellation lands the order "with `cancellation_reason`
    `MOVE_CANCELLED` and both window fields cleared, which releases each
    occupied service window", the very same request succeeds and the pairing
    is back to an occupancy of 1 under a new holder.  This is the boundary
    that proves the unwind restored the resource rather than merely relabelling
    a row.

    Design: Difficulty/compensating_invariant/order_cancellation_restores_address_window_occupancy
    """
    net = fixtures.build_network(api, clock=CLOCK_STARTUP_DEFAULT)
    first = fixtures.mapped_move(api, network=net, utility_types=[UtilityType.WATER.value])
    second_resident = fixtures.create_second_resident(api)
    second = fixtures.mapped_move(
        api,
        network={**net, "resident": second_resident},
        utility_types=[UtilityType.WATER.value],
    )
    address_id = net["destination_address"]["id"]
    first_order = first["orders_by_type"][UtilityType.WATER.value]
    second_order = second["orders_by_type"][UtilityType.WATER.value]

    fixtures.schedule_order(
        api,
        first_order["id"],
        requested_service_date="2026-08-05",
        scheduled_window_start="2026-08-05T09:00:00Z",
        scheduled_window_end="2026-08-05T13:00:00Z",
    )

    contested = f.schedule_payload(
        requested_service_date="2026-08-05",
        scheduled_window_start="2026-08-05T09:00:00Z",
        scheduled_window_end="2026-08-05T13:00:00Z",
    )
    assert_error(
        api.schedule_order(second_order["id"], contested, ops_headers),
        ApiErrorId.SERVICE_WINDOW_CONFLICT,
        expected_status=409,
    )
    assert occupied_window_count(
        api, address_id, UtilityType.WATER.value, ops_headers
    ) == 1, "a refused schedule must not change the occupancy count"

    assert_ok(api.cancel_move(first["move"]["id"], f.cancellation_payload(), ops_headers))
    assert occupied_window_count(
        api, address_id, UtilityType.WATER.value, ops_headers
    ) == 0, "the cancellation must release the contested window"

    granted = assert_ok(api.schedule_order(second_order["id"], contested, ops_headers))
    assert granted["provision_status"] == ProvisionStatus.SCHEDULED.value, (
        f"expected the re-booked order SCHEDULED, got {granted['provision_status']}"
    )
    assert granted["scheduled_window_start"] == "2026-08-05T09:00:00Z", (
        "the second household must take the identical released window"
    )
    assert occupied_window_count(
        api, address_id, UtilityType.WATER.value, ops_headers
    ) == 1, "the released window is held once again, by the new holder"


# ---------------------------------------------------------------------------
# Voiding the handoff restores the move's open deposit liability to zero
# ---------------------------------------------------------------------------
def _electric_order_carrying_a_due_deposit(api) -> Dict[str, Any]:
    """A scheduled electric order whose bureau answer demanded 18000 cents.

    Dispatch happens from `DRAFT`, which freezes the snapshot at 40: identity
    100, utility 0, filing 0 and a consent component of 50 for a household
    covering exactly one of the two gate scopes.
    """
    net = fixtures.build_network(api, clock=CLOCK_STARTUP_DEFAULT)
    bundle = fixtures.verified_move(
        api, network=net, scopes=[ConsentScope.UTILITY_SETUP.value]
    )
    move_id = bundle["move"]["id"]
    fixtures.run_mapping(api, move_id, utility_types=[UtilityType.ELECTRIC.value])

    order = fixtures.order_of_type(api, move_id, UtilityType.ELECTRIC.value)
    assert_cents(order, "deposit_estimate_cents", 22500)

    handoff = fixtures.dispatch_credit_check(api, order["id"])
    frozen = fixtures.read_order(api, order["id"])
    assert frozen["readiness_snapshot"] == 40, (
        f"expected a frozen readiness_snapshot of 40, got {frozen['readiness_snapshot']}"
    )
    handoff = fixtures.answer_bureau(api, handoff["id"], 639)

    scheduled = fixtures.schedule_order(
        api, order["id"], requested_service_date="2026-08-05"
    )
    return {**bundle, "handoff": handoff, "order": scheduled}


def test_05_voiding_the_handoff_restores_the_open_deposit_liability_to_zero(
    api, ops_headers
):
    """A provider failure unwinds the credit exposure it never collected.

    "A `DEPOSIT_REQUIRED` result moves `credit_status` to `DEPOSIT_DUE`, writes
    the computed deposit into `deposit_amount_cents`, and raises the move's"
    open deposit liability by that amount, and the figure is the PRD's own
    worked example: "a `CREDIT_SCORE_BASED` provider with a bureau score of 639
    and a frozen snapshot of 40 yields 18000 cents against the 22500-cent
    estimate written at mapping".  The liability is the measured "sum of
    `deposit_amount_cents` across the move's orders whose `credit_status` is
    `DEPOSIT_DUE`", so it reads 18000.  The provider failure then "moves the
    order's `credit_status` from `PENDING_CHECK` or `DEPOSIT_DUE` to `VOIDED`
    and moves any credit-check handoff in `SUBMITTED` or `RESPONDED` to
    `VOIDED`, restoring the move's open deposit liability to its pre-handoff
    value", which is 0 — while "`deposit_amount_cents` survives a void so the
    historical exposure remains legible even though it no longer counts toward
    the move's liability".  The move parks at 40: identity 100, utility 0 with
    nothing done, filing 0, consent 50.

    Design: Difficulty/compensating_invariant/handoff_void_restores_zero_deposit_liability
    """
    setup = _electric_order_carrying_a_due_deposit(api)
    order = setup["order"]
    move_id = setup["move"]["id"]
    provider_id = setup["electric_provider"]["id"]

    assert_order_dimensions(
        order,
        provision_status=ProvisionStatus.SCHEDULED.value,
        credit_status=CreditStatus.DEPOSIT_DUE.value,
    )
    assert_cents(order, "deposit_amount_cents", 18000)
    assert_cents(order, "deposit_estimate_cents", 22500)
    assert_cents(order, "deposit_paid_cents", 0)
    assert open_deposit_liability_cents(api, move_id, ops_headers) == 18000, (
        "the bureau answer must raise the measured liability to 18000"
    )
    assert setup["handoff"]["handoff_status"] == HandoffStatus.RESPONDED.value, (
        f"expected the handoff RESPONDED, got {setup['handoff']['handoff_status']}"
    )
    assert setup["handoff"]["result"] == CreditResult.DEPOSIT_REQUIRED.value, (
        f"expected a DEPOSIT_REQUIRED result, got {setup['handoff']['result']}"
    )

    failed = assert_ok(
        api.report_provision_failure(
            order["id"],
            f.provision_failure_payload(),
            make_provider_agent_headers(provider_id),
        )
    )
    assert_order_dimensions(
        failed,
        provision_status=ProvisionStatus.PROVISION_FAILED.value,
        credit_status=CreditStatus.VOIDED.value,
    )
    assert failed["failure_reason"], "the failure must record a non-empty failure_reason"
    assert_window_released(failed)
    assert_cents(failed, "deposit_amount_cents", 18000)
    assert_cents(failed, "deposit_paid_cents", 0)

    voided_handoff = get_success_data(
        api.get_credit_check_handoff(setup["handoff"]["id"], ops_headers)
    )
    assert voided_handoff["handoff_status"] == HandoffStatus.VOIDED.value, (
        f"expected the handoff VOIDED, got {voided_handoff['handoff_status']}"
    )
    assert voided_handoff["score"] == 639, (
        f"the bureau score must survive the void, got {voided_handoff['score']}"
    )
    assert voided_handoff["result"] == CreditResult.DEPOSIT_REQUIRED.value, (
        f"the bureau result must survive the void, got {voided_handoff['result']}"
    )

    assert open_deposit_liability_cents(api, move_id, ops_headers) == 0, (
        "voiding the handoff must restore the measured liability to zero"
    )
    assert_move_state(
        fixtures.read_move(api, move_id),
        lifecycle_status=MoveLifecycleStatus.ATTENTION_REQUIRED.value,
        blocked_reason=BlockedReason.PROVISION_FAILED.value,
        readiness_score=40,
    )


def test_06_a_deposit_payment_after_the_void_is_refused(api, ops_headers):
    """The voided exposure cannot be re-collected by paying it late.

    Payment is gated on the provisioning dimension — "Payment additionally
    requires the order's `provision_status` to be `DRAFT` or `SCHEDULED`." —
    and the ladder additionally requires that "The addressed service order's
    `provision_status` permits the operation", refusing anything else with
    `ERR_ORDER_NOT_SCHEDULABLE` across "all seven order write operations: schedule,
    credit-checks, deposit-payments, activation, provision-failure, closure and
    waiver".  A payment of the retained 18000 against the failed order is
    therefore refused, `deposit_paid_cents` stays at 0, and the measured
    liability stays at 0 rather than swinging back.

    Design: Difficulty/compensating_invariant/handoff_void_restores_zero_deposit_liability
    """
    setup = _electric_order_carrying_a_due_deposit(api)
    order = setup["order"]
    move_id = setup["move"]["id"]
    provider_id = setup["electric_provider"]["id"]

    assert_ok(
        api.report_provision_failure(
            order["id"],
            f.provision_failure_payload(),
            make_provider_agent_headers(provider_id),
        )
    )
    assert open_deposit_liability_cents(api, move_id, ops_headers) == 0, (
        "the void must already have restored the liability to zero"
    )

    assert_error(
        api.pay_deposit(order["id"], f.deposit_payment_payload(18000), ops_headers),
        ApiErrorId.ORDER_NOT_SCHEDULABLE,
        expected_status=409,
    )

    after = fixtures.read_order(api, order["id"])
    assert_order_dimensions(
        after,
        provision_status=ProvisionStatus.PROVISION_FAILED.value,
        credit_status=CreditStatus.VOIDED.value,
    )
    assert_cents(after, "deposit_paid_cents", 0)
    assert_cents(after, "deposit_amount_cents", 18000)
    assert open_deposit_liability_cents(api, move_id, ops_headers) == 0, (
        "a refused late payment must not reopen the move's deposit liability"
    )
