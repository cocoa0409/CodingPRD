"""State paths that are neither single-file nor one-way.

A service order carries two state dimensions that advance independently and
touch only once, at activation.  A postal filing runs a rejection-and-retry
loop that returns to a state it has already occupied, bounded only by a
counter.  An accepted referral forks into two branches whose side effects are
opposites.  Each test below walks one of those shapes and pins every dimension,
counter and side effect it leaves behind.
"""

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_cents,
    assert_created,
    assert_entry_types,
    assert_error,
    assert_ledger_net,
    assert_move_state,
    assert_order_dimensions,
    assert_page,
    assert_readiness_breakdown,
    get_success_data,
)
from test_helpers.test_users import (
    make_partner_agent_headers,
    make_provider_agent_headers,
)
from test_helpers.types import (
    BlockedReason,
    ConsentScope,
    CreditStatus,
    FilingStatus,
    LedgerEntryType,
    MoveLifecycleStatus,
    PartnerVertical,
    PayoutModel,
    PlacementStatus,
    ProvisionStatus,
    ReadinessVariant,
    UtilityType,
)


def _order_owing_a_deposit_on_a_booked_window(api):
    """An order that owes 18000 cents and separately holds a committed window.

    The credit check is dispatched while the order is still a draft, the bureau
    answers with a score in the deposit band, and only then is the technician
    window committed — so the two dimensions have advanced one apiece.
    """
    bundle = fx.mapped_move(
        api,
        utility_types=[UtilityType.ELECTRIC.value],
        scopes=[ConsentScope.UTILITY_SETUP.value],
    )
    order = bundle["orders_by_type"][UtilityType.ELECTRIC.value]
    handoff = fx.dispatch_credit_check(api, order["id"])
    fx.answer_bureau(api, handoff["id"], 639)
    fx.schedule_order(api, order["id"], requested_service_date="2026-08-20")
    return bundle, fx.read_order(api, order["id"])


# ---------------------------------------------------------------------------
# One order row, two dimensions advancing side by side
# ---------------------------------------------------------------------------
def test_01_booking_a_window_leaves_the_outstanding_deposit_exactly_where_it_was(
    api, ops_headers
):
    """The provisioning dimension reaches SCHEDULED while the deposit stays due.

    PRD: "An order may be scheduled while its `credit_status` is
    `NOT_REQUIRED`, `PENDING_CHECK`, `CLEARED`, `DEPOSIT_DUE` or `DEPOSIT_PAID`"

    Design: Difficulty/non_linear_state_machine/utility_order_parallel_credit_and_provision_dimensions
    """
    bundle, order = _order_owing_a_deposit_on_a_booked_window(api)

    assert_order_dimensions(
        order,
        provision_status=ProvisionStatus.SCHEDULED.value,
        credit_status=CreditStatus.DEPOSIT_DUE.value,
    )
    assert_cents(order, "deposit_amount_cents", 18000)
    assert_cents(order, "deposit_paid_cents", 0)
    assert order["scheduled_window_start"] is not None, (
        "a scheduled order must carry the committed technician window"
    )
    assert order["scheduled_window_start"].startswith("2026-08-20T09:00:00"), (
        f"expected the committed window start, got {order['scheduled_window_start']}"
    )
    assert order["requested_service_date"] == "2026-08-20", (
        f"expected requested_service_date 2026-08-20, got {order['requested_service_date']}"
    )
    assert order["confirmation_code"] is None, (
        "the provisioning dimension has not yet reported the service live"
    )
    assert_move_state(
        fx.read_move(api, bundle["move"]["id"]),
        lifecycle_status=MoveLifecycleStatus.SCHEDULING.value,
        blocked_reason=BlockedReason.NONE.value,
        readiness_score=70,
    )


def test_02_activation_is_the_one_place_the_unpaid_deposit_blocks_provisioning(
    api, ops_headers
):
    """With the window reached but the deposit unpaid, activation is refused.

    PRD: "This is the single point in the entire system at which the credit
    dimension of a service order constrains its provisioning dimension."

    Design: Difficulty/non_linear_state_machine/utility_order_parallel_credit_and_provision_dimensions
    """
    bundle, order = _order_owing_a_deposit_on_a_booked_window(api)
    fx.set_clock(api, "2026-08-20T09:00:00Z")

    refused = api.activate_order(
        order["id"],
        f.activation_payload(),
        make_provider_agent_headers(order["provider_id"]),
    )
    assert_error(refused, ApiErrorId.CREDIT_NOT_CLEARED)

    after = fx.read_order(api, order["id"])
    assert_order_dimensions(
        after,
        provision_status=ProvisionStatus.SCHEDULED.value,
        credit_status=CreditStatus.DEPOSIT_DUE.value,
    )
    assert after["confirmation_code"] is None, (
        "a refused activation must not write a confirmation code"
    )
    assert_cents(after, "deposit_paid_cents", 0)
    assert_move_state(
        fx.read_move(api, bundle["move"]["id"]),
        lifecycle_status=MoveLifecycleStatus.SCHEDULING.value,
    )


def test_03_paying_then_activating_moves_one_dimension_each_and_nothing_else(
    api, ops_headers
):
    """Payment touches only credit; activation touches only provisioning.

    PRD: "the credit dimension gates activation and nothing else, which is
    exactly what makes the two dimensions on a single order row independent of
    one another"

    Design: Difficulty/non_linear_state_machine/utility_order_parallel_credit_and_provision_dimensions
    """
    bundle, order = _order_owing_a_deposit_on_a_booked_window(api)

    paid = get_success_data(
        api.pay_deposit(order["id"], f.deposit_payment_payload(18000), ops_headers)
    )
    assert_order_dimensions(
        paid,
        provision_status=ProvisionStatus.SCHEDULED.value,
        credit_status=CreditStatus.DEPOSIT_PAID.value,
    )
    assert_cents(paid, "deposit_paid_cents", 18000)
    assert_cents(paid, "deposit_amount_cents", 18000)

    fx.set_clock(api, "2026-08-20T09:00:00Z")
    activated = get_success_data(
        api.activate_order(
            order["id"],
            f.activation_payload(),
            make_provider_agent_headers(order["provider_id"]),
        )
    )
    assert_order_dimensions(
        activated,
        provision_status=ProvisionStatus.ACTIVE_SERVICE.value,
        credit_status=CreditStatus.DEPOSIT_PAID.value,
    )
    assert activated["confirmation_code"] == "CONF-88213", (
        f"expected the reported confirmation code, got {activated['confirmation_code']}"
    )
    assert_cents(activated, "deposit_paid_cents", 18000)

    move = fx.read_move(api, bundle["move"]["id"])
    assert_move_state(
        move,
        lifecycle_status=MoveLifecycleStatus.SCHEDULING.value,
        blocked_reason=BlockedReason.NONE.value,
        readiness_score=70,
    )
    assert_readiness_breakdown(
        fx.read_readiness(api, move["id"]),
        variant=ReadinessVariant.POST_VERIFICATION.value,
        identity_component=100,
        utility_component=100,
        filing_component=0,
        consent_component=50,
        readiness_score=70,
    )


# ---------------------------------------------------------------------------
# The postal filing loop: SUBMITTED, REJECTED, SUBMITTED again
# ---------------------------------------------------------------------------
def _submitted_filing_on_a_verified_move(api):
    """A verified household whose change-of-address filing has reached the post."""
    bundle = fx.verified_move(api)
    filing = fx.draft_filing(api, bundle["move"]["id"], forward_start_date="2026-08-20")
    filing = fx.submit_filing(api, filing["id"])
    return bundle, filing


def test_04_two_rejections_are_absorbed_and_the_retry_counter_climbs_to_two(
    api, ops_headers, gateway_headers
):
    """The filing re-enters SUBMITTED twice, each pass clearing the old reason.

    PRD: "A `REJECTED` filing may be resubmitted, which returns `status` to
    `SUBMITTED`, adds one to `resubmit_count`, clears `reject_reason`"

    Design: Difficulty/non_linear_state_machine/filing_rejected_resubmit_cycle_bounded_by_counter
    """
    bundle, filing = _submitted_filing_on_a_verified_move(api)
    filing_id = filing["id"]

    assert filing["status"] == FilingStatus.SUBMITTED.value, (
        f"expected the first submission to reach SUBMITTED, got {filing['status']}"
    )
    assert filing["resubmit_count"] == 0, (
        f"a first submission is not a retry, so resubmit_count is 0, got {filing['resubmit_count']}"
    )

    for expected_count, reason in ((1, "Name mismatch on record"), (2, "Unit number missing")):
        rejected = get_success_data(
            api.post_usps_response(
                filing_id, f.usps_rejection_payload(reject_reason=reason), gateway_headers
            )
        )
        assert rejected["status"] == FilingStatus.REJECTED.value, (
            f"expected the filing REJECTED, got {rejected['status']}"
        )
        assert rejected["reject_reason"] == reason, (
            f"expected reject_reason {reason!r}, got {rejected['reject_reason']!r}"
        )

        retried = get_success_data(api.submit_filing(filing_id, {}, ops_headers))
        assert retried["status"] == FilingStatus.SUBMITTED.value, (
            f"expected the retry to return the filing to SUBMITTED, got {retried['status']}"
        )
        assert retried["resubmit_count"] == expected_count, (
            f"expected resubmit_count {expected_count}, got {retried['resubmit_count']}"
        )
        assert retried["reject_reason"] is None, (
            "a retry must clear the reason the postal service gave last time"
        )

    assert_readiness_breakdown(
        fx.read_readiness(api, bundle["move"]["id"]),
        variant=ReadinessVariant.POST_VERIFICATION.value,
        identity_component=100,
        utility_component=0,
        filing_component=60,
        consent_component=100,
        readiness_score=62,
    )
    assert_move_state(
        fx.read_move(api, bundle["move"]["id"]),
        lifecycle_status=MoveLifecycleStatus.VERIFIED.value,
        blocked_reason=BlockedReason.NONE.value,
    )


def test_05_the_third_retry_is_refused_and_the_filing_stays_rejected(
    api, ops_headers, gateway_headers
):
    """The counter closes the loop: a filing gets one submission and two retries.

    PRD: "a filing may be submitted once and retried at most twice; the third
    retry is refused with `ERR_RESUBMIT_LIMIT_REACHED`"

    Design: Difficulty/non_linear_state_machine/filing_rejected_resubmit_cycle_bounded_by_counter
    """
    bundle, filing = _submitted_filing_on_a_verified_move(api)
    filing_id = filing["id"]

    for reason in ("Name mismatch on record", "Unit number missing"):
        get_success_data(
            api.post_usps_response(
                filing_id, f.usps_rejection_payload(reject_reason=reason), gateway_headers
            )
        )
        get_success_data(api.submit_filing(filing_id, {}, ops_headers))

    final_reason = "Unverifiable prior address"
    rejected = get_success_data(
        api.post_usps_response(
            filing_id, f.usps_rejection_payload(reject_reason=final_reason), gateway_headers
        )
    )
    assert rejected["resubmit_count"] == 2, (
        f"expected the counter at its limit of 2, got {rejected['resubmit_count']}"
    )

    refused = api.submit_filing(filing_id, {}, ops_headers)
    assert_error(refused, ApiErrorId.RESUBMIT_LIMIT_REACHED)

    after = get_success_data(api.get_filing(filing_id, ops_headers))
    assert after["status"] == FilingStatus.REJECTED.value, (
        f"a refused retry leaves the filing REJECTED, got {after['status']}"
    )
    assert after["resubmit_count"] == 2, (
        f"a refused retry must not move the counter, got {after['resubmit_count']}"
    )
    assert after["reject_reason"] == final_reason, (
        f"the last reason the postal service gave must survive, got {after['reject_reason']!r}"
    )

    assert_readiness_breakdown(
        fx.read_readiness(api, bundle["move"]["id"]),
        variant=ReadinessVariant.POST_VERIFICATION.value,
        identity_component=100,
        utility_component=0,
        filing_component=0,
        consent_component=100,
        readiness_score=50,
    )
    assert_move_state(
        fx.read_move(api, bundle["move"]["id"]),
        lifecycle_status=MoveLifecycleStatus.VERIFIED.value,
        blocked_reason=BlockedReason.NONE.value,
    )


# ---------------------------------------------------------------------------
# The referral fork: two branches out of one ACCEPTED row
# ---------------------------------------------------------------------------
def _two_accepted_referrals(api):
    """One move carrying an accepted internet referral and an accepted insurance one.

    Both partners pay a 0.3000 revenue share, so the branch each placement takes
    is the only thing that can make their side effects differ.
    """
    verified = fx.verified_move(api)
    internet = fx.add_internet_partner(api)
    insurance = fx.create_partner(
        api,
        f.insurance_partner_payload(
            payout_model=PayoutModel.REV_SHARE_PCT.value, rev_share_pct=0.3
        ),
    )
    first = fx.accepted_referral(api, bundle=verified, partner=internet)
    second = fx.accepted_referral(api, bundle=first, partner=insurance)
    return first, second


def test_06_the_decline_branch_journals_nothing_and_moves_no_money(api, admin_headers):
    """Declining an accepted referral leaves the ledger and the balance untouched.

    PRD: "the owning partner supplies a non-empty `decline_reason`,
    `placement_status` moves to `DECLINED`, and the placement posts no ledger
    entry at all"

    Design: Difficulty/non_linear_state_machine/placement_accept_branch_divergent_side_effects
    """
    _first, second = _two_accepted_referrals(api)
    insurance_placement = second["placement"]

    declined = get_success_data(
        api.decline_placement(
            insurance_placement["id"],
            f.decline_payload(),
            make_partner_agent_headers(second["partner"]["id"]),
        )
    )

    assert declined["placement_status"] == PlacementStatus.DECLINED.value, (
        f"expected placement_status DECLINED, got {declined['placement_status']}"
    )
    assert declined["decline_reason"] == "Household out of footprint", (
        f"expected the recorded decline reason, got {declined['decline_reason']!r}"
    )
    assert_cents(declined, "attributed_share_cents", 0)
    assert_cents(declined, "feed_source_share_cents", 0)
    assert declined["converted_at"] is None, "a declined referral never converted"

    assert_page(
        api.list_ledger_entries(admin_headers, placement_id=insurance_placement["id"]),
        total_count=0,
        has_more=False,
    )
    feed = fx.read_feed_source(api, second["feed_source"]["id"])
    assert_cents(feed, "accrued_share_cents", 0)


def test_07_the_conversion_branch_journals_two_entries_and_moves_the_balance(
    api, admin_headers
):
    """Only the converted branch produces ledger rows and a feed-source balance.

    PRD: "Conversion writes `gross_revenue_cents` and `converted_at`, moves
    `placement_status` to `CONVERTED`, computes both share figures, and posts two
    ledger entries."

    Design: Difficulty/non_linear_state_machine/placement_accept_branch_divergent_side_effects
    """
    first, second = _two_accepted_referrals(api)
    move_id = first["move"]["id"]

    get_success_data(
        api.decline_placement(
            second["placement"]["id"],
            f.decline_payload(),
            make_partner_agent_headers(second["partner"]["id"]),
        )
    )
    converted = get_success_data(
        api.convert_placement(
            first["placement"]["id"],
            f.conversion_payload(100000),
            make_partner_agent_headers(first["partner"]["id"]),
        )
    )

    assert converted["placement_status"] == PlacementStatus.CONVERTED.value, (
        f"expected placement_status CONVERTED, got {converted['placement_status']}"
    )
    assert converted["converted_at"] is not None, "conversion must stamp converted_at"
    assert_cents(converted, "gross_revenue_cents", 100000)
    assert_cents(converted, "attributed_share_cents", 27000)
    assert_cents(converted, "feed_source_share_cents", 4725)

    entries = assert_page(
        api.list_ledger_entries(admin_headers, move_id=move_id),
        total_count=2,
        has_more=False,
    )
    assert_entry_types(
        entries,
        [LedgerEntryType.ACCRUAL.value, LedgerEntryType.FEED_SOURCE_SHARE.value],
    )
    assert_cents(entries[0], "amount_cents", 27000)
    assert_cents(entries[1], "amount_cents", -4725)
    assert_ledger_net(entries, converted)
    assert all(entry["placement_id"] == converted["id"] for entry in entries), (
        "every journalled entry on this move must belong to the converted referral"
    )

    feed = fx.read_feed_source(api, first["feed_source"]["id"])
    assert_cents(feed, "accrued_share_cents", 4725)


def test_08_a_declined_vertical_reopens_while_an_accepted_one_stays_shut(
    api, ops_headers
):
    """The two branches diverge on occupancy as well as on money.

    PRD: "The move has no other placement in the partner's `vertical` whose
    `placement_status` is `PLACED`, `ACCEPTED`, `CONVERTED` or `SETTLED`"

    Design: Difficulty/non_linear_state_machine/placement_accept_branch_divergent_side_effects
    """
    first, second = _two_accepted_referrals(api)
    move_id = first["move"]["id"]

    get_success_data(
        api.decline_placement(
            second["placement"]["id"],
            f.decline_payload(),
            make_partner_agent_headers(second["partner"]["id"]),
        )
    )

    move = fx.read_move(api, move_id)
    replacement = assert_created(
        api.create_placement(
            move_id,
            f.placement_payload(second["partner"]["id"], move["version"]),
            ops_headers,
        )
    )
    assert replacement["placement_status"] == PlacementStatus.PLACED.value, (
        f"expected the replacement PLACED, got {replacement['placement_status']}"
    )
    assert replacement["vertical"] == PartnerVertical.INSURANCE.value, (
        f"expected the freed vertical INSURANCE, got {replacement['vertical']}"
    )
    assert replacement["id"] != second["placement"]["id"], (
        "the freed slot must be filled by a genuinely new placement"
    )

    rival = fx.create_partner(api, f.alternate_internet_partner_payload())
    move = fx.read_move(api, move_id)
    refused = api.create_placement(
        move_id, f.placement_payload(rival["id"], move["version"]), ops_headers
    )
    assert_error(refused, ApiErrorId.DUPLICATE_VERTICAL_PLACEMENT)

    placements = assert_page(
        api.list_placements(ops_headers, move_id=move_id),
        total_count=3,
        has_more=False,
    )
    statuses = sorted(row["placement_status"] for row in placements)
    assert statuses == [
        PlacementStatus.ACCEPTED.value,
        PlacementStatus.DECLINED.value,
        PlacementStatus.PLACED.value,
    ], f"expected one accepted, one declined and one placed referral, got {statuses}"
