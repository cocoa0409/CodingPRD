"""Intake and scheduling validation rules at their exact acceptance boundaries.

Every rule here is exercised from both sides: the request that trips it and the
neighbouring request that satisfies it.  A rejected call is always followed by a
re-read proving the addressed row kept its status, its null fields and its
version, so nothing in the store moved on a refusal.
"""

from test_helpers import factories as fac
from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_created,
    assert_duplicate_score,
    assert_error,
    assert_move_state,
    assert_ok,
    assert_order_dimensions,
    assert_page,
    assert_unchanged,
    assert_version_bumped,
    assert_window_retained,
)
from test_helpers.test_users import make_provider_agent_headers
from test_helpers.types import (
    BlockedReason,
    BureauName,
    ConsentScope,
    CreditStatus,
    DuplicateFlag,
    FeedStatus,
    HandoffStatus,
    MoveLifecycleStatus,
    ProviderStatus,
    ProvisionStatus,
    SourceType,
    UtilityType,
)


def _electric_order_ready_to_schedule(api):
    """A SCHEDULING move whose DRAFT electric order awaits a service window."""
    bundle = fx.mapped_move(
        api,
        utility_types=[UtilityType.ELECTRIC.value],
        scopes=[ConsentScope.UTILITY_SETUP.value],
    )
    return bundle, bundle["orders_by_type"][UtilityType.ELECTRIC.value]


def test_01_a_service_date_one_day_inside_the_lead_time_floor_is_refused(
    api, ops_headers
):
    """A three-day carrier cannot be booked for the second day after the clock.

    PRD: "for an order whose `order_kind` is `START`, `requested_service_date`
    must be at or after the logical clock's date plus the provider's
    `scheduling_lead_days`".

    Design: Corner/validations/satisfaction_to_pass_schedule_at_the_exact_lead_time_floor
    """
    bundle, order = _electric_order_ready_to_schedule(api)
    assert bundle["electric_provider"]["scheduling_lead_days"] == 3, (
        "the carrier under test must demand three days of lead time"
    )

    response = api.schedule_order(
        order["id"], fac.schedule_payload(requested_service_date="2026-08-03"), ops_headers
    )
    assert_error(response, ApiErrorId.LEAD_TIME_VIOLATION)

    after = fx.read_order(api, order["id"])
    assert_order_dimensions(after, provision_status=ProvisionStatus.DRAFT.value)
    assert after["scheduled_window_start"] is None, (
        "a refused schedule must leave scheduled_window_start null"
    )
    assert after["scheduled_window_end"] is None, (
        "a refused schedule must leave scheduled_window_end null"
    )
    assert_unchanged(order, after)


def test_02_a_service_date_exactly_at_the_lead_time_floor_is_scheduled(
    api, ops_headers
):
    """The third day after the clock is the first bookable date and it is accepted.

    PRD: The lead-time floor asks that `requested_service_date` be "at or after
    the logical clock's date plus the provider's `scheduling_lead_days`".

    Design: Corner/validations/satisfaction_to_pass_schedule_at_the_exact_lead_time_floor
    """
    _bundle, order = _electric_order_ready_to_schedule(api)

    scheduled = assert_ok(
        api.schedule_order(
            order["id"],
            fac.schedule_payload(requested_service_date="2026-08-04"),
            ops_headers,
        )
    )

    assert_order_dimensions(
        scheduled,
        provision_status=ProvisionStatus.SCHEDULED.value,
        credit_status=CreditStatus.PENDING_CHECK.value,
    )
    assert scheduled["scheduled_window_start"] == "2026-08-04T09:00:00Z", (
        f"expected the committed window to open at 09:00, got {scheduled['scheduled_window_start']}"
    )
    assert scheduled["scheduled_window_end"] == "2026-08-04T13:00:00Z", (
        f"expected the committed window to close at 13:00, got {scheduled['scheduled_window_end']}"
    )


WATER_ACCOUNT_DATA = {"account_holder_name": "Dana Ruiz"}


def _water_order_ready_to_schedule(api):
    """A SCHEDULING move whose DRAFT water order has no lead time to respect."""
    bundle = fx.mapped_move(
        api,
        utility_types=[UtilityType.WATER.value],
        scopes=[ConsentScope.UTILITY_SETUP.value],
    )
    return bundle, bundle["orders_by_type"][UtilityType.WATER.value]


def test_03_an_overlong_a_reversed_and_a_straddling_window_are_each_refused(
    api, ops_headers
):
    """Each of the three window-shape clauses rejects on its own.

    PRD: "`scheduled_window_start` must be strictly earlier than
    `scheduled_window_end`, both must fall on the calendar date named by
    `requested_service_date`, and the span between them must be at most 8
    hours; a violation is `ERR_INVALID_SERVICE_WINDOW`."

    Design: Corner/validations/violation_to_error_service_window_shape_rules_each_rejected
    """
    _bundle, order = _water_order_ready_to_schedule(api)
    malformed = [
        ("a nine-hour span", "2026-08-05T09:00:00Z", "2026-08-05T18:00:00Z"),
        ("an end before its start", "2026-08-05T13:00:00Z", "2026-08-05T09:00:00Z"),
        ("an end on the following date", "2026-08-05T20:00:00Z", "2026-08-06T02:00:00Z"),
    ]

    for label, start, end in malformed:
        response = api.schedule_order(
            order["id"],
            fac.schedule_payload(
                requested_service_date="2026-08-05",
                scheduled_window_start=start,
                scheduled_window_end=end,
                account_data=WATER_ACCOUNT_DATA,
            ),
            ops_headers,
        )
        assert_error(response, ApiErrorId.INVALID_SERVICE_WINDOW)

        after = fx.read_order(api, order["id"])
        assert_order_dimensions(after, provision_status=ProvisionStatus.DRAFT.value)
        assert after["scheduled_window_start"] is None, (
            f"{label} must leave scheduled_window_start null"
        )
        assert after["scheduled_window_end"] is None, (
            f"{label} must leave scheduled_window_end null"
        )
        assert_unchanged(order, after)


def test_04_a_span_of_exactly_eight_hours_is_a_legal_service_window(api, ops_headers):
    """Eight hours is the inclusive ceiling on the technician window, so it passes.

    PRD: The window shape requires "the span between them must be at most 8
    hours".

    Design: Corner/validations/violation_to_error_service_window_shape_rules_each_rejected
    """
    _bundle, order = _water_order_ready_to_schedule(api)

    scheduled = assert_ok(
        api.schedule_order(
            order["id"],
            fac.schedule_payload(
                requested_service_date="2026-08-05",
                scheduled_window_start="2026-08-05T09:00:00Z",
                scheduled_window_end="2026-08-05T17:00:00Z",
                account_data=WATER_ACCOUNT_DATA,
            ),
            ops_headers,
        )
    )

    assert_order_dimensions(
        scheduled,
        provision_status=ProvisionStatus.SCHEDULED.value,
        credit_status=CreditStatus.NOT_REQUIRED.value,
    )
    assert scheduled["scheduled_window_end"] == "2026-08-05T17:00:00Z", (
        f"expected an eight-hour window closing at 17:00, got {scheduled['scheduled_window_end']}"
    )
    assert_window_retained(scheduled)


def _intake_reference_data(api):
    """The feed, household and two addresses a move record points at."""
    fx.set_clock(api, "2026-08-01T00:00:00Z")
    return {
        "feed_source": fx.create_feed_source(api),
        "resident": fx.create_resident(api),
        "origin_address": fx.create_origin_address(api),
        "destination_address": fx.create_destination_address(api),
    }


def _ingest_on(api, reference, move_date, headers):
    """Attempt one move ingestion on a chosen move_date and return the response."""
    return api.create_move(
        fac.move_payload(
            reference["resident"]["id"],
            reference["feed_source"]["id"],
            reference["origin_address"]["id"],
            reference["destination_address"]["id"],
            move_date=move_date,
        ),
        headers,
    )


def test_05_a_move_date_one_day_past_the_forward_horizon_is_refused(api, ops_headers):
    """The 180th day ahead is ingestible; the 181st is out of range.

    PRD: "`move_date` falls inside the inclusive window running from 30 days
    before the logical clock's date through 180 days after it".

    Design: Corner/validations/temporal_validation_move_date_horizon_and_past_grace_boundaries
    """
    reference = _intake_reference_data(api)

    at_horizon = assert_created(_ingest_on(api, reference, "2027-01-28", ops_headers))
    assert at_horizon["move_date"] == "2027-01-28", (
        f"expected the horizon date to be stored, got {at_horizon['move_date']}"
    )
    assert_move_state(at_horizon, lifecycle_status=MoveLifecycleStatus.INTAKE.value)

    assert_error(
        _ingest_on(api, reference, "2027-01-29", ops_headers),
        ApiErrorId.MOVE_DATE_OUT_OF_RANGE,
    )

    assert_page(
        api.list_moves(ops_headers, resident_id=reference["resident"]["id"]),
        total_count=1,
    )


def test_06_a_move_date_one_day_past_the_grace_period_is_refused(api, ops_headers):
    """The 30th day behind the clock is ingestible; the 31st is out of range.

    PRD: The inclusive window runs "from 30 days before the logical clock's date
    through 180 days after it".

    Design: Corner/validations/temporal_validation_move_date_horizon_and_past_grace_boundaries
    """
    reference = _intake_reference_data(api)

    at_grace = assert_created(_ingest_on(api, reference, "2026-07-02", ops_headers))
    assert at_grace["move_date"] == "2026-07-02", (
        f"expected the grace date to be stored, got {at_grace['move_date']}"
    )
    assert_duplicate_score(at_grace, 0.00)

    assert_error(
        _ingest_on(api, reference, "2026-07-01", ops_headers),
        ApiErrorId.MOVE_DATE_OUT_OF_RANGE,
    )

    assert_page(
        api.list_moves(ops_headers, resident_id=reference["resident"]["id"]),
        total_count=1,
    )


def _mover_feed_reference_data(api):
    """Intake reference data whose lead arrives from a moving company's feed."""
    reference = _intake_reference_data(api)
    reference["feed_source"] = fx.create_feed_source(
        api,
        name="Coastal Mover Feed",
        source_type=SourceType.MOVER.value,
        referral_revenue_share_pct=0.1000,
    )
    return reference


def test_07_a_suspended_feed_cannot_hand_the_platform_a_new_move(
    api, admin_headers, ops_headers
):
    """Suspending the feed closes intake for every lead it would supply.

    PRD: "a suspended feed is refused at move intake with `ERR_FEED_SUSPENDED`".

    Design: Corner/validations/cross_entity_validation_suspended_feed_blocks_move_creation
    """
    reference = _mover_feed_reference_data(api)
    feed_source_id = reference["feed_source"]["id"]

    suspended = assert_ok(
        api.patch_feed_source_status(
            feed_source_id,
            fac.status_payload("feed_status", FeedStatus.SUSPENDED.value),
            admin_headers,
        )
    )
    assert suspended["feed_status"] == FeedStatus.SUSPENDED.value, (
        f"expected the feed to be SUSPENDED, got {suspended['feed_status']}"
    )

    assert_error(
        _ingest_on(api, reference, "2026-08-20", ops_headers),
        ApiErrorId.FEED_SUSPENDED,
    )

    assert_page(api.list_moves(ops_headers, feed_source_id=feed_source_id), total_count=0)
    still_suspended = fx.read_feed_source(api, feed_source_id)
    assert still_suspended["feed_status"] == FeedStatus.SUSPENDED.value, (
        "a refused ingestion must not disturb the feed's own status"
    )


def test_08_reactivating_the_feed_reopens_intake_for_the_same_request(
    api, admin_headers, ops_headers
):
    """The identical body that was refused succeeds once the feed is ACTIVE again.

    PRD: The feed check asks that "The `FeedSource` named by `feed_source_id` has
    `feed_status` `ACTIVE`".

    Design: Corner/validations/cross_entity_validation_suspended_feed_blocks_move_creation
    """
    reference = _mover_feed_reference_data(api)
    feed_source_id = reference["feed_source"]["id"]
    assert_ok(
        api.patch_feed_source_status(
            feed_source_id,
            fac.status_payload("feed_status", FeedStatus.SUSPENDED.value),
            admin_headers,
        )
    )
    assert_error(
        _ingest_on(api, reference, "2026-08-20", ops_headers),
        ApiErrorId.FEED_SUSPENDED,
    )

    assert_ok(
        api.patch_feed_source_status(
            feed_source_id,
            fac.status_payload("feed_status", FeedStatus.ACTIVE.value),
            admin_headers,
        )
    )
    ingested = assert_created(_ingest_on(api, reference, "2026-08-20", ops_headers))

    assert_move_state(ingested, lifecycle_status=MoveLifecycleStatus.INTAKE.value)
    assert ingested["feed_source_id"] == feed_source_id, (
        "the accepted move must carry the very feed that had been suspended"
    )
    assert_page(api.list_moves(ops_headers, feed_source_id=feed_source_id), total_count=1)


def _set_provider_status(api, provider_id, status, admin_headers):
    """Flip a carrier's `provider_status` and confirm the patch landed."""
    patched = assert_ok(
        api.patch_provider_status(
            provider_id, fac.status_payload("provider_status", status), admin_headers
        )
    )
    assert patched["provider_status"] == status, (
        f"expected provider_status {status}, got {patched['provider_status']}"
    )
    return patched


def _schedule_the_water_order(api, order_id, ops_headers):
    """Book the water order's window on 2026-08-05 from 09:00 to 13:00."""
    return api.schedule_order(
        order_id,
        fac.schedule_payload(
            requested_service_date="2026-08-05", account_data=WATER_ACCOUNT_DATA
        ),
        ops_headers,
    )


def test_09_a_deactivated_carrier_cannot_be_booked_and_then_can_be_again(
    api, admin_headers, ops_headers
):
    """Scheduling is refused while the carrier is INACTIVE and accepted once ACTIVE.

    PRD: "an `INACTIVE` provider is ineligible as a mapping candidate and is
    refused at scheduling and activation with `ERR_PROVIDER_INACTIVE`".

    Design: Corner/validations/cross_entity_validation_inactive_provider_blocks_schedule_and_activation
    """
    bundle, order = _water_order_ready_to_schedule(api)
    provider_id = bundle["water_provider"]["id"]

    _set_provider_status(api, provider_id, ProviderStatus.INACTIVE.value, admin_headers)
    assert_error(
        _schedule_the_water_order(api, order["id"], ops_headers),
        ApiErrorId.PROVIDER_INACTIVE,
    )

    held = fx.read_order(api, order["id"])
    assert_order_dimensions(held, provision_status=ProvisionStatus.DRAFT.value)
    assert held["scheduled_window_start"] is None, (
        "a refused schedule must leave the window unbooked"
    )
    assert_unchanged(order, held)

    _set_provider_status(api, provider_id, ProviderStatus.ACTIVE.value, admin_headers)
    scheduled = assert_ok(_schedule_the_water_order(api, order["id"], ops_headers))
    assert_order_dimensions(scheduled, provision_status=ProvisionStatus.SCHEDULED.value)


def test_10_a_deactivated_carrier_cannot_switch_the_service_on_either(
    api, admin_headers, ops_headers
):
    """Activation is the second operation the carrier's status gates.

    PRD: The carrier check "Applies to two operations: order scheduling and
    order activation."

    Design: Corner/validations/cross_entity_validation_inactive_provider_blocks_schedule_and_activation
    """
    bundle, order = _water_order_ready_to_schedule(api)
    provider_id = bundle["water_provider"]["id"]
    assert_ok(_schedule_the_water_order(api, order["id"], ops_headers))

    _set_provider_status(api, provider_id, ProviderStatus.INACTIVE.value, admin_headers)
    fx.set_clock(api, "2026-08-05T09:00:00Z")
    provider_agent = make_provider_agent_headers(provider_id)
    before = fx.read_order(api, order["id"])

    assert_error(
        api.activate_order(
            order["id"],
            fac.activation_payload(confirmation_code="AWB-77120"),
            provider_agent,
        ),
        ApiErrorId.PROVIDER_INACTIVE,
    )

    held = fx.read_order(api, order["id"])
    assert_order_dimensions(held, provision_status=ProvisionStatus.SCHEDULED.value)
    assert_window_retained(held)
    assert held["confirmation_code"] is None, (
        "a refused activation must not record a confirmation code"
    )
    assert_unchanged(before, held)

    _set_provider_status(api, provider_id, ProviderStatus.ACTIVE.value, admin_headers)
    activated = assert_ok(
        api.activate_order(
            order["id"],
            fac.activation_payload(confirmation_code="AWB-77120"),
            provider_agent,
        )
    )
    assert_order_dimensions(activated, provision_status=ProvisionStatus.ACTIVE_SERVICE.value)
    assert activated["confirmation_code"] == "AWB-77120", (
        f"expected the supplied confirmation code, got {activated['confirmation_code']!r}"
    )
    assert_move_state(
        fx.read_move(api, bundle["move"]["id"]),
        lifecycle_status=MoveLifecycleStatus.SCHEDULING.value,
    )


def _held_twin_move(api):
    """A second identical intake for the same household, held as a suspected duplicate."""
    bundle = fx.full_consent_move(api, scopes=[ConsentScope.UTILITY_SETUP.value])
    twin = fx.ingest_move(api, bundle, move_date="2026-08-20")

    assert_duplicate_score(twin, 1.00)
    assert_move_state(
        twin,
        lifecycle_status=MoveLifecycleStatus.INTAKE.value,
        duplicate_flag=DuplicateFlag.SUSPECTED.value,
        blocked_reason=BlockedReason.DUPLICATE_SUSPECTED.value,
    )
    assert twin["duplicate_candidate_move_id"] == bundle["move"]["id"], (
        "the held twin must name the earlier move as its candidate"
    )
    return bundle, twin


def test_11_a_suspected_duplicate_cannot_even_open_an_identity_check(api, ops_headers):
    """The hold refuses the very first step of the identity flow.

    PRD: "while `duplicate_flag` is `SUSPECTED`, opening an identity
    verification, running provider mapping, drafting a postal filing and
    creating a referral placement are all refused with
    `ERR_DUPLICATE_MOVE_UNRESOLVED`".

    Design: Corner/validations/cascading_validation_duplicate_dismissal_unblocks_the_held_move
    """
    _bundle, twin = _held_twin_move(api)

    assert_error(
        api.create_identity_verification(
            twin["id"], fac.kba_attempt_payload(), ops_headers
        ),
        ApiErrorId.DUPLICATE_MOVE_UNRESOLVED,
    )

    assert_page(api.list_identity_verifications(ops_headers, move_id=twin["id"]), total_count=0)
    after = fx.read_move(api, twin["id"])
    assert_move_state(
        after,
        lifecycle_status=MoveLifecycleStatus.INTAKE.value,
        duplicate_flag=DuplicateFlag.SUSPECTED.value,
        blocked_reason=BlockedReason.DUPLICATE_SUSPECTED.value,
    )
    assert after["identity_attempt_count"] == 0, (
        f"a refused attempt must not be counted, got {after['identity_attempt_count']}"
    )
    assert_unchanged(twin, after)


def test_12_dismissing_the_suspicion_lets_the_held_move_run_its_whole_flow(
    api, ops_headers, gateway_headers
):
    """A DISMISS clears the hold without moving the move out of INTAKE.

    PRD: "When the score sits below 0.80, the feed's `trust_tier` decides the
    outcome" — above it the move "is held in `INTAKE` until a duplicate
    resolution decides its fate".

    Design: Corner/validations/cascading_validation_duplicate_dismissal_unblocks_the_held_move
    """
    bundle, twin = _held_twin_move(api)

    dismissed = assert_ok(
        api.resolve_duplicate(
            twin["id"], fac.dismiss_payload(twin["version"]), ops_headers
        )
    )
    assert_move_state(
        dismissed,
        lifecycle_status=MoveLifecycleStatus.INTAKE.value,
        duplicate_flag=DuplicateFlag.DISMISSED.value,
        blocked_reason=BlockedReason.NONE.value,
    )
    assert dismissed["duplicate_candidate_move_id"] == bundle["move"]["id"], (
        "the near-miss stays visible after a dismissal"
    )
    assert_version_bumped(twin, dismissed)

    verification = assert_created(
        api.create_identity_verification(twin["id"], fac.kba_attempt_payload(), ops_headers)
    )
    assert_ok(
        api.post_kba_result(
            verification["id"], fac.kba_result_payload(score=720), gateway_headers
        )
    )
    mapped = fx.run_mapping(api, twin["id"], utility_types=[UtilityType.WATER.value])
    assert_move_state(mapped, lifecycle_status=MoveLifecycleStatus.SCHEDULING.value)
    assert mapped["mapped_order_count"] == 1, (
        f"expected one mapped order, got {mapped['mapped_order_count']}"
    )

    survivor = fx.read_move(api, bundle["move"]["id"])
    assert_move_state(
        survivor,
        lifecycle_status=MoveLifecycleStatus.INTAKE.value,
        duplicate_flag=DuplicateFlag.NONE.value,
    )


def test_13_re_running_mapping_for_a_type_that_already_has_a_draft_order_is_refused(
    api, ops_headers
):
    """A DRAFT order already counts as live, so the type cannot be mapped twice.

    PRD: "When every requested pairing of `utility_type` and `order_kind`
    already has an order in `DRAFT`, `SCHEDULED`, `ACTIVE_SERVICE` or
    `SUSPENDED`, the re-run has nothing to do and is refused with
    `ERR_TYPE_ALREADY_MAPPED`."

    Design: Corner/validations/violation_to_error_second_mapping_of_a_live_utility_type_rejected
    """
    bundle, order = _electric_order_ready_to_schedule(api)
    assert_order_dimensions(order, provision_status=ProvisionStatus.DRAFT.value)
    before = fx.read_move(api, bundle["move"]["id"])

    assert_error(
        api.run_provider_mapping(
            bundle["move"]["id"],
            fac.mapping_payload([UtilityType.ELECTRIC.value]),
            ops_headers,
        ),
        ApiErrorId.TYPE_ALREADY_MAPPED,
    )

    assert_page(
        api.list_utility_orders(ops_headers, move_id=bundle["move"]["id"]), total_count=1
    )
    after = fx.read_move(api, bundle["move"]["id"])
    assert after["mapped_order_count"] == 1, (
        f"a refused re-run must not raise mapped_order_count, got {after['mapped_order_count']}"
    )
    assert_unchanged(before, after)


def test_14_mapping_the_remaining_utility_type_self_loops_the_scheduling_move(
    api, ops_headers
):
    """The type that has no order yet still maps, leaving the move in SCHEDULING.

    PRD: The refusal only bites when "every requested pairing of `utility_type`
    and `order_kind` already has an order in `DRAFT`, `SCHEDULED`,
    `ACTIVE_SERVICE` or `SUSPENDED`".

    Design: Corner/validations/violation_to_error_second_mapping_of_a_live_utility_type_rejected
    """
    bundle, _order = _electric_order_ready_to_schedule(api)

    mapped = assert_ok(
        api.run_provider_mapping(
            bundle["move"]["id"],
            fac.mapping_payload([UtilityType.WATER.value]),
            ops_headers,
        )
    )

    assert_move_state(mapped, lifecycle_status=MoveLifecycleStatus.SCHEDULING.value)
    assert mapped["mapped_order_count"] == 2, (
        f"expected two mapped orders, got {mapped['mapped_order_count']}"
    )
    assert mapped["unmapped_utility_types"] == [], (
        f"expected nothing left unmapped, got {mapped['unmapped_utility_types']}"
    )
    assert_page(
        api.list_utility_orders(ops_headers, move_id=bundle["move"]["id"]), total_count=2
    )


def _electric_order_with_an_open_handoff(api):
    """An electric order whose credit-check handoff is still awaiting the bureau."""
    bundle = fx.mapped_move(api, scopes=[ConsentScope.UTILITY_SETUP.value])
    order = bundle["orders_by_type"][UtilityType.ELECTRIC.value]
    handoff = fx.dispatch_credit_check(api, order["id"], bureau=BureauName.EXPERIAN.value)
    return bundle, order, handoff


def test_15_a_second_credit_check_while_one_is_still_open_is_refused(api, ops_headers):
    """Only one handoff may sit in SUBMITTED against an order at a time.

    PRD: "a second concurrent handoff is refused with
    `ERR_HANDOFF_ALREADY_OPEN`".

    Design: Corner/validations/violation_to_error_second_credit_check_while_one_is_open_rejected
    """
    _bundle, order, handoff = _electric_order_with_an_open_handoff(api)
    assert handoff["handoff_status"] == HandoffStatus.SUBMITTED.value, (
        f"the first handoff must be open, got {handoff['handoff_status']}"
    )

    assert_error(
        api.create_credit_check(
            order["id"],
            fac.credit_check_payload(bureau=BureauName.EQUIFAX.value),
            ops_headers,
        ),
        ApiErrorId.HANDOFF_ALREADY_OPEN,
    )

    assert_page(
        api.list_credit_check_handoffs(ops_headers, order_id=order["id"]), total_count=1
    )


def test_16_the_refused_dispatch_leaves_the_open_handoff_and_its_snapshot_alone(
    api, ops_headers
):
    """The surviving handoff keeps its bureau, its null score and its frozen readiness.

    PRD: The dispatch "writes `readiness_snapshot` on the order, freezing the
    parent move's `readiness_score` **as of that instant**".

    Design: Corner/validations/violation_to_error_second_credit_check_while_one_is_open_rejected
    """
    _bundle, order, handoff = _electric_order_with_an_open_handoff(api)

    assert_error(
        api.create_credit_check(
            order["id"],
            fac.credit_check_payload(bureau=BureauName.EQUIFAX.value),
            ops_headers,
        ),
        ApiErrorId.HANDOFF_ALREADY_OPEN,
    )

    survivor = assert_ok(api.get_credit_check_handoff(handoff["id"], ops_headers))
    assert survivor["bureau"] == BureauName.EXPERIAN.value, (
        f"the open handoff must keep its original bureau, got {survivor['bureau']}"
    )
    assert survivor["handoff_status"] == HandoffStatus.SUBMITTED.value, (
        f"expected the handoff to stay SUBMITTED, got {survivor['handoff_status']}"
    )
    assert survivor["score"] is None, "no bureau has answered, so score must stay null"

    after = fx.read_order(api, order["id"])
    assert_order_dimensions(after, credit_status=CreditStatus.PENDING_CHECK.value)
    assert after["readiness_snapshot"] == 40, (
        f"the snapshot was frozen once at 40, got {after['readiness_snapshot']}"
    )
