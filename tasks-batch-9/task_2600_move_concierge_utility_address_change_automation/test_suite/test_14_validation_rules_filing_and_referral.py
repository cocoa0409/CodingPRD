"""Filing, provider-registration and referral validation rules at their edges.

The rules gathered here are the ones whose correctness depends on which of two
plausible errors surfaces, or on which side of an inclusive bound a figure
falls.  Every refusal is followed by a re-read showing the addressed row kept
its status, its null fields and its version.
"""

from test_helpers import factories as fac
from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_cents,
    assert_created,
    assert_entry_types,
    assert_error,
    assert_move_state,
    assert_ok,
    assert_order_dimensions,
    assert_page,
    assert_unchanged,
    assert_version_bumped,
    ledger_net,
)
from test_helpers.types import (
    ConsentScope,
    CreditStatus,
    DepositPolicy,
    DuplicateFlag,
    FilingStatus,
    KbaOutcome,
    LedgerEntryType,
    MoveLifecycleStatus,
    PartnerStatus,
    PartnerVertical,
    PlacementStatus,
    ProviderStatus,
    ProvisionStatus,
    UtilityType,
)

SERVICE_DATE = "2026-08-05"
NAME_ONLY = {"account_holder_name": "Dana Ruiz"}
NAME_AND_START = {"account_holder_name": "Dana Ruiz", "service_start_date": SERVICE_DATE}


def _two_orders_awaiting_account_data(api):
    """A SCHEDULING move with a DRAFT electric order and a DRAFT water order."""
    bundle = fx.mapped_move(api, scopes=[ConsentScope.UTILITY_SETUP.value])
    return (
        bundle,
        bundle["orders_by_type"][UtilityType.ELECTRIC.value],
        bundle["orders_by_type"][UtilityType.WATER.value],
    )


def test_01_the_electric_carrier_rejects_a_missing_and_an_empty_account_field(
    api, ops_headers
):
    """Its second required field must be present *and* carry a non-empty value.

    PRD: "The submitted `account_data` object supplies every key listed in the
    winning provider's `required_account_fields`, each with a non-empty value".

    Design: Corner/validations/conditional_validation_required_account_fields_are_per_provider
    """
    bundle, electric, _water = _two_orders_awaiting_account_data(api)
    assert bundle["electric_provider"]["required_account_fields"] == [
        "account_holder_name",
        "service_start_date",
    ], "the electric carrier under test must demand two account fields"

    for label, account_data in (
        ("an omitted field", NAME_ONLY),
        ("an empty field", {"account_holder_name": "Dana Ruiz", "service_start_date": ""}),
    ):
        assert_error(
            api.schedule_order(
                electric["id"],
                fac.schedule_payload(
                    requested_service_date=SERVICE_DATE, account_data=account_data
                ),
                ops_headers,
            ),
            ApiErrorId.MISSING_ACCOUNT_DATA,
        )
        after = fx.read_order(api, electric["id"])
        assert_order_dimensions(after, provision_status=ProvisionStatus.DRAFT.value)
        assert after["scheduled_window_start"] is None, (
            f"{label} must leave the window unbooked"
        )
        assert_unchanged(electric, after)


def test_02_each_carrier_is_judged_against_its_own_required_field_list(
    api, ops_headers
):
    """The water carrier accepts the very payload the electric carrier refused.

    PRD: The rule reads "every key listed in the winning provider's
    `required_account_fields`", and the water carrier lists only one.

    Design: Corner/validations/conditional_validation_required_account_fields_are_per_provider
    """
    bundle, electric, water = _two_orders_awaiting_account_data(api)
    assert bundle["water_provider"]["required_account_fields"] == [
        "account_holder_name"
    ], "the water carrier under test must demand a single account field"

    water_scheduled = assert_ok(
        api.schedule_order(
            water["id"],
            fac.schedule_payload(
                requested_service_date=SERVICE_DATE, account_data=NAME_ONLY
            ),
            ops_headers,
        )
    )
    assert_order_dimensions(
        water_scheduled, provision_status=ProvisionStatus.SCHEDULED.value
    )
    assert water_scheduled["account_data"] == NAME_ONLY, (
        f"expected the short account payload to be stored, got {water_scheduled['account_data']}"
    )

    electric_scheduled = assert_ok(
        api.schedule_order(
            electric["id"],
            fac.schedule_payload(
                requested_service_date=SERVICE_DATE, account_data=NAME_AND_START
            ),
            ops_headers,
        )
    )
    assert_order_dimensions(
        electric_scheduled, provision_status=ProvisionStatus.SCHEDULED.value
    )
    assert electric_scheduled["account_data"] == NAME_AND_START, (
        f"expected both account keys to be stored, got {electric_scheduled['account_data']}"
    )
    assert (
        electric_scheduled["scheduled_window_start"]
        == water_scheduled["scheduled_window_start"]
    ), "the two commodities may share one technician window at the same address"


def _draft_filing_starting_on_the_tenth(api):
    """A verified household whose DRAFT filing forwards mail from 2026-08-10."""
    bundle = fx.verified_move(api, scopes=[ConsentScope.USPS_FILING.value])
    filing = fx.draft_filing(api, bundle["move"]["id"], forward_start_date="2026-08-10")
    assert filing["status"] == FilingStatus.DRAFT.value, (
        f"expected a DRAFT filing, got {filing['status']}"
    )
    assert filing["forward_end_date"] == "2027-08-09", (
        f"expected a one-year forwarding term ending 2027-08-09, got {filing['forward_end_date']}"
    )
    assert filing["resubmit_count"] == 0, (
        f"a fresh filing has never been resubmitted, got {filing['resubmit_count']}"
    )
    return bundle, filing


def test_03_a_forward_start_date_the_clock_has_passed_cannot_be_submitted(
    api, ops_headers
):
    """Letting the start date slip behind the clock makes the filing unsubmittable.

    PRD: "`forward_start_date` must be at or after the logical clock's date, a
    backdated start being refused with `ERR_FORWARD_DATE_INVALID`".

    Design: Corner/validations/temporal_validation_forward_start_date_must_not_be_past_at_submission
    """
    _bundle, filing = _draft_filing_starting_on_the_tenth(api)
    fx.set_clock(api, "2026-08-11T00:00:00Z")

    assert_error(
        api.submit_filing(filing["id"], {}, ops_headers),
        ApiErrorId.FORWARD_DATE_INVALID,
    )

    after = assert_ok(api.get_filing(filing["id"], ops_headers))
    assert after["status"] == FilingStatus.DRAFT.value, (
        f"a refused submission must leave the filing in DRAFT, got {after['status']}"
    )
    assert after["submitted_by_user_id"] is None, (
        "a refused submission must not record a submitter"
    )
    assert after["resubmit_count"] == 0, (
        f"a refused submission must not count as a resubmit, got {after['resubmit_count']}"
    )
    assert_unchanged(filing, after)


def test_04_a_forward_start_date_equal_to_the_clock_date_still_submits(
    api, ops_headers
):
    """The start date may equal the clock's date, the boundary being inclusive.

    PRD: "`forward_start_date` is at or after the logical clock's date at
    submission time".

    Design: Corner/validations/temporal_validation_forward_start_date_must_not_be_past_at_submission
    """
    _bundle, filing = _draft_filing_starting_on_the_tenth(api)
    fx.set_clock(api, "2026-08-10T00:00:00Z")

    submitted = assert_ok(api.submit_filing(filing["id"], {}, ops_headers))

    assert submitted["status"] == FilingStatus.SUBMITTED.value, (
        f"expected SUBMITTED at the inclusive boundary, got {submitted['status']}"
    )
    assert submitted["submitted_by_user_id"] is not None, (
        "an accepted submission must record who sent it"
    )
    assert submitted["forward_start_date"] == "2026-08-10", (
        f"the forwarding start must survive submission, got {submitted['forward_start_date']}"
    )


def test_05_a_flat_carrier_may_sit_on_the_deposit_ceiling_but_not_above_it(
    api, admin_headers
):
    """50001 cents is refused at registration while 50000 registers cleanly.

    PRD: "registering a `FLAT` provider whose `flat_deposit_cents` exceeds the
    platform deposit ceiling of 50000 cents is refused with
    `ERR_DEPOSIT_CAP_EXCEEDED`".

    Design: Corner/validations/violation_to_error_flat_deposit_above_the_cap_rejected_at_provider_creation
    """
    assert_error(
        api.create_utility_provider(
            fac.gas_provider_payload(flat_deposit_cents=50001), admin_headers
        ),
        ApiErrorId.DEPOSIT_CAP_EXCEEDED,
    )

    at_the_ceiling = assert_created(
        api.create_utility_provider(
            fac.gas_provider_payload(flat_deposit_cents=50000), admin_headers
        )
    )
    assert_cents(at_the_ceiling, "flat_deposit_cents", 50000)
    assert at_the_ceiling["deposit_policy"] == DepositPolicy.FLAT.value, (
        f"expected a FLAT policy, got {at_the_ceiling['deposit_policy']}"
    )
    assert at_the_ceiling["provider_status"] == ProviderStatus.ACTIVE.value, (
        f"a newly registered carrier opens ACTIVE, got {at_the_ceiling['provider_status']}"
    )


def test_06_the_ceiling_does_not_apply_to_a_credit_scored_carrier(api, ops_headers):
    """The same 50001 registers under CREDIT_SCORE_BASED and changes no estimate.

    PRD: The ceiling bites only "When `deposit_policy` is `FLAT`,
    `flat_deposit_cents` does not exceed 50000", and a `CREDIT_SCORE_BASED`
    provider "therefore always estimates 22500 cents".

    Design: Corner/validations/violation_to_error_flat_deposit_above_the_cap_rejected_at_provider_creation
    """
    network = fx.build_network(api, electric_overrides={"flat_deposit_cents": 50001})
    carrier = network["electric_provider"]

    assert carrier["deposit_policy"] == DepositPolicy.CREDIT_SCORE_BASED.value, (
        f"expected a CREDIT_SCORE_BASED policy, got {carrier['deposit_policy']}"
    )
    assert_cents(carrier, "flat_deposit_cents", 50001)
    assert carrier["provider_status"] == ProviderStatus.ACTIVE.value, (
        f"the over-ceiling figure is irrelevant here, got {carrier['provider_status']}"
    )

    bundle = fx.mapped_move(
        api,
        network=network,
        utility_types=[UtilityType.ELECTRIC.value],
        scopes=[ConsentScope.UTILITY_SETUP.value],
    )
    order = bundle["orders_by_type"][UtilityType.ELECTRIC.value]
    assert_cents(order, "deposit_estimate_cents", 22500)
    assert_order_dimensions(order, credit_status=CreditStatus.PENDING_CHECK.value)


def _merge_candidates(api, ops_headers):
    """A held duplicate plus one valid survivor, one terminal twin and one stranger."""
    network = fx.build_network(api)
    survivor = fx.ingest_move(api, network, move_date="2026-08-20")

    terminal_twin = fx.ingest_move(api, network, move_date="2026-08-20")
    assert_ok(
        api.cancel_move(terminal_twin["id"], fac.cancellation_payload(), ops_headers)
    )

    held = fx.ingest_move(api, network, move_date="2026-08-20")
    assert_move_state(held, duplicate_flag=DuplicateFlag.SUSPECTED.value)

    stranger = assert_created(
        api.create_move(
            fac.move_payload(
                fx.create_second_resident(api)["id"],
                network["feed_source"]["id"],
                network["origin_address"]["id"],
                fx.create_address(api, fac.third_address_payload())["id"],
                move_date="2026-08-20",
            ),
            ops_headers,
        )
    )
    return {
        "survivor": survivor,
        "terminal_twin": terminal_twin,
        "held": held,
        "stranger": stranger,
    }


def test_07_naming_the_held_move_as_its_own_survivor_fails_the_earlier_rule(
    api, ops_headers
):
    """A self-merge surfaces the self-merge error, never the eligibility error.

    PRD: "A survivor that is terminal, or that shares neither signal, is refused
    with `ERR_SURVIVOR_MOVE_INVALID`; naming the move itself is refused earlier,
    with `ERR_SELF_MERGE_FORBIDDEN`."

    Design: Corner/validations/priority_ordering_self_merge_outranks_survivor_eligibility
    """
    cast = _merge_candidates(api, ops_headers)
    held = cast["held"]

    assert_error(
        api.resolve_duplicate(
            held["id"], fac.merge_payload(held["version"], held["id"]), ops_headers
        ),
        ApiErrorId.SELF_MERGE_FORBIDDEN,
    )

    after = fx.read_move(api, held["id"])
    assert_move_state(
        after,
        lifecycle_status=MoveLifecycleStatus.INTAKE.value,
        duplicate_flag=DuplicateFlag.SUSPECTED.value,
    )
    assert after["duplicate_of_move_id"] is None, (
        "a refused merge must not write duplicate_of_move_id"
    )
    assert_unchanged(held, after)


def test_08_a_terminal_or_unrelated_survivor_is_refused_and_a_sibling_is_accepted(
    api, ops_headers
):
    """Eligibility needs a non-terminal survivor sharing the household or address.

    PRD: "For a merge resolution the survivor move is non-terminal and shares
    either the `resident_id` or the destination `address_hash` of the move being
    merged".

    Design: Corner/validations/priority_ordering_self_merge_outranks_survivor_eligibility
    """
    cast = _merge_candidates(api, ops_headers)
    held = cast["held"]
    version = held["version"]

    for label, ineligible in (
        ("a household with no shared signal", cast["stranger"]),
        ("a twin already cancelled", cast["terminal_twin"]),
    ):
        assert_error(
            api.resolve_duplicate(
                held["id"],
                fac.merge_payload(version, ineligible["id"]),
                ops_headers,
            ),
            ApiErrorId.SURVIVOR_MOVE_INVALID,
        )
        assert fx.read_move(api, held["id"])["version"] == version, (
            f"{label} must leave the held move's version untouched"
        )

    merged = assert_ok(
        api.resolve_duplicate(
            held["id"],
            fac.merge_payload(version, cast["survivor"]["id"]),
            ops_headers,
        )
    )

    assert_move_state(
        merged,
        lifecycle_status=MoveLifecycleStatus.DUPLICATE_MERGED.value,
        duplicate_flag=DuplicateFlag.CONFIRMED_DUPLICATE.value,
    )
    assert merged["duplicate_of_move_id"] == cast["survivor"]["id"], (
        f"expected the survivor to be recorded, got {merged['duplicate_of_move_id']}"
    )
    assert_version_bumped(held, merged)


def _converted_revenue_share_referral(api):
    """An internet referral converted on a reported gross of 100000 cents."""
    bundle = fx.verified_move(api, scopes=[ConsentScope.PARTNER_MARKETING.value])
    partner = fx.add_internet_partner(api)
    converted = fx.converted_referral(
        api, gross_revenue_cents=100000, bundle=bundle, partner=partner
    )
    assert_cents(converted["placement"], "attributed_share_cents", 27000)
    assert_cents(converted["placement"], "feed_source_share_cents", 4725)
    return converted


def test_09_a_settled_gross_outside_the_band_of_one_to_twice_is_refused(
    api, admin_headers
):
    """Neither zero nor one cent above twice the reported gross may be settled.

    PRD: settlement "takes a `settled_gross_revenue_cents` that must be at least
    1 and must not exceed twice the recorded `gross_revenue_cents`, a figure
    outside that band being refused with `ERR_SETTLEMENT_AMOUNT_INVALID`".

    Design: Corner/validations/aggregate_validation_settlement_bounded_by_twice_the_reported_gross
    """
    converted = _converted_revenue_share_referral(api)
    placement = converted["placement"]

    for label, amount in (("one cent above the ceiling", 200001), ("nothing at all", 0)):
        assert_error(
            api.settle_placement(
                placement["id"], fac.settlement_payload(amount), admin_headers
            ),
            ApiErrorId.SETTLEMENT_AMOUNT_INVALID,
        )
        after = assert_ok(api.get_placement(placement["id"], admin_headers))
        assert after["placement_status"] == PlacementStatus.CONVERTED.value, (
            f"settling {label} must leave the placement CONVERTED, got {after['placement_status']}"
        )
        assert_cents(after, "attributed_share_cents", 27000)
        assert_cents(after, "feed_source_share_cents", 4725)
        assert_unchanged(placement, after)

    assert_page(
        api.list_ledger_entries(admin_headers, placement_id=placement["id"]),
        total_count=2,
    )


def test_10_a_settled_gross_at_exactly_twice_the_reported_gross_posts_the_deltas(
    api, admin_headers
):
    """Twice the gross is inside the band, and settlement journals only the deltas.

    PRD: Settlement "posts **only the deltas**: an `ADJUSTMENT` entry for the
    settled commission minus the provisional commission, and a
    `FEED_SOURCE_SHARE_ADJUSTMENT` entry for the negative of the settled feed
    share minus the provisional feed share".

    Design: Corner/validations/aggregate_validation_settlement_bounded_by_twice_the_reported_gross
    """
    converted = _converted_revenue_share_referral(api)
    placement = converted["placement"]

    settled = assert_ok(
        api.settle_placement(
            placement["id"], fac.settlement_payload(200000), admin_headers
        )
    )

    assert settled["placement_status"] == PlacementStatus.SETTLED.value, (
        f"expected SETTLED at the inclusive ceiling, got {settled['placement_status']}"
    )
    assert_cents(settled, "settled_gross_revenue_cents", 200000)
    assert_cents(settled, "attributed_share_cents", 60000)
    assert_cents(settled, "feed_source_share_cents", 10500)

    entries = fx.ledger_for_placement(api, placement["id"])
    assert_entry_types(
        entries,
        [
            LedgerEntryType.ACCRUAL.value,
            LedgerEntryType.FEED_SOURCE_SHARE.value,
            LedgerEntryType.ADJUSTMENT.value,
            LedgerEntryType.FEED_SOURCE_SHARE_ADJUSTMENT.value,
        ],
    )
    assert_cents(entries[2], "amount_cents", 33000)
    assert_cents(entries[3], "amount_cents", -5775)
    assert ledger_net(entries) == 49500, (
        f"the ledger must net to 60000 - 10500, got {ledger_net(entries)}"
    )

    feed = fx.read_feed_source(api, converted["feed_source"]["id"])
    assert_cents(feed, "accrued_share_cents", 10500)


def _two_verified_moves_and_two_internet_partners(api, ops_headers):
    """One household with two distinct verified moves, and two INTERNET partners."""
    network = fx.build_network(api)
    other_city = fx.create_address(api, fac.third_address_payload())
    fx.grant_consents(
        api, network["resident"]["id"], [ConsentScope.PARTNER_MARKETING.value]
    )

    first = fx.ingest_move(api, network, move_date="2026-08-20")
    fx.pass_identity_by_kba(api, first["id"])

    second = fx.ingest_move(
        api, {**network, "destination_address": other_city}, move_date="2026-08-04"
    )
    assert_move_state(second, duplicate_flag=DuplicateFlag.NONE.value)
    fx.pass_identity_by_kba(api, second["id"])

    return {
        "first_move": fx.read_move(api, first["id"]),
        "second_move": fx.read_move(api, second["id"]),
        "capped_partner": fx.add_internet_partner(api, monthly_placement_cap=1),
        "spare_partner": fx.create_partner(
            api, fac.alternate_internet_partner_payload()
        ),
    }


def _place(api, move_id, partner_id, ops_headers):
    """Place a referral using the move's current version for concurrency."""
    version = fx.read_move(api, move_id)["version"]
    return api.create_placement(
        move_id, fac.placement_payload(partner_id, version), ops_headers
    )


def test_11_a_second_live_placement_in_the_vertical_outranks_the_exhausted_quota(
    api, ops_headers
):
    """With both rules broken at once, the vertical clash is the error returned.

    PRD: "no other placement on this move may share the partner's `vertical`
    while sitting in `PLACED`, `ACCEPTED`, `CONVERTED` or `SETTLED`, a second
    live placement in the same vertical being refused with
    `ERR_DUPLICATE_VERTICAL_PLACEMENT`".

    Design: Corner/validations/aggregate_validation_partner_month_cap_ranks_below_the_paused_check
    """
    cast = _two_verified_moves_and_two_internet_partners(api, ops_headers)
    partner = cast["capped_partner"]
    move_id = cast["first_move"]["id"]
    assert partner["monthly_placement_cap"] == 1, (
        f"the capped partner must allow one placement a month, got {partner['monthly_placement_cap']}"
    )

    placed = assert_created(_place(api, move_id, partner["id"], ops_headers))
    assert placed["placement_status"] == PlacementStatus.PLACED.value, (
        f"expected PLACED, got {placed['placement_status']}"
    )
    assert placed["vertical"] == PartnerVertical.INTERNET.value, (
        f"the placement copies the partner's vertical, got {placed['vertical']}"
    )
    assert placed["placed_at"].startswith("2026-08-01"), (
        f"placed_at is taken from the logical clock, got {placed['placed_at']}"
    )
    assert_version_bumped(cast["first_move"], fx.read_move(api, move_id))

    assert_error(
        _place(api, move_id, partner["id"], ops_headers),
        ApiErrorId.DUPLICATE_VERTICAL_PLACEMENT,
    )
    assert_page(api.list_placements(ops_headers, move_id=move_id), total_count=1)


def test_12_pausing_the_partner_outranks_its_exhausted_monthly_quota(
    api, admin_headers, ops_headers
):
    """The same request answers with the cap while ACTIVE and with the pause once PAUSED.

    PRD: "the partner's `partner_status` must be `ACTIVE`, a paused partner being
    refused with `ERR_PARTNER_PAUSED`".

    Design: Corner/validations/aggregate_validation_partner_month_cap_ranks_below_the_paused_check
    """
    cast = _two_verified_moves_and_two_internet_partners(api, ops_headers)
    partner = cast["capped_partner"]
    second_move_id = cast["second_move"]["id"]
    assert_created(_place(api, cast["first_move"]["id"], partner["id"], ops_headers))

    assert_error(
        _place(api, second_move_id, partner["id"], ops_headers),
        ApiErrorId.PARTNER_CAP_REACHED,
    )

    paused = assert_ok(
        api.patch_partner_status(
            partner["id"],
            fac.status_payload("partner_status", PartnerStatus.PAUSED.value),
            admin_headers,
        )
    )
    assert paused["partner_status"] == PartnerStatus.PAUSED.value, (
        f"expected the partner to be PAUSED, got {paused['partner_status']}"
    )

    assert_error(
        _place(api, second_move_id, partner["id"], ops_headers),
        ApiErrorId.PARTNER_PAUSED,
    )

    spare = assert_created(
        _place(api, second_move_id, cast["spare_partner"]["id"], ops_headers)
    )
    assert spare["placement_status"] == PlacementStatus.PLACED.value, (
        f"the second partner is neither paused nor capped, got {spare['placement_status']}"
    )
    assert_page(api.list_placements(ops_headers, partner_id=partner["id"]), total_count=1)


def _verified_move_to_an_undeliverable_address(api):
    """A verified household forwarding mail to a destination the post cannot serve."""
    network = fx.build_network(api, resident_overrides={"full_name": "Ivan Cole"})
    undeliverable = fx.create_address(api, fac.undeliverable_address_payload())
    fx.grant_consents(
        api, network["resident"]["id"], [ConsentScope.USPS_FILING.value]
    )
    move = fx.ingest_move(
        api, {**network, "destination_address": undeliverable}, move_date="2026-08-20"
    )
    fx.pass_identity_by_kba(api, move["id"])
    return {**network, "undeliverable_address": undeliverable, "move": move}


def test_13_deliverability_is_derived_from_the_postal_code_alone(api, ops_headers):
    """A 000 prefix marks the address undeliverable while a real one stays deliverable.

    PRD: "`usps_deliverable` is derived as false when the `postal_code` begins
    with the non-deliverable prefix `000`".

    Design: Corner/validations/violation_to_error_undeliverable_destination_blocks_usps_submission
    """
    bundle = _verified_move_to_an_undeliverable_address(api)

    destination = assert_ok(
        api.get_service_address(bundle["undeliverable_address"]["id"], ops_headers)
    )
    assert destination["usps_deliverable"] is False, (
        f"a 000-prefixed postal code is undeliverable, got {destination['usps_deliverable']}"
    )

    origin = assert_ok(
        api.get_service_address(bundle["origin_address"]["id"], ops_headers)
    )
    assert origin["usps_deliverable"] is True, (
        f"an ordinary postal code is deliverable, got {origin['usps_deliverable']}"
    )


def test_14_an_undeliverable_destination_stops_the_filing_at_submission(
    api, ops_headers
):
    """Drafting is allowed, but the postal service is never reached.

    PRD: "the destination address must have `usps_deliverable` true, an
    undeliverable destination being refused with
    `ERR_ADDRESS_NOT_DELIVERABLE`".

    Design: Corner/validations/violation_to_error_undeliverable_destination_blocks_usps_submission
    """
    bundle = _verified_move_to_an_undeliverable_address(api)
    filing = fx.draft_filing(
        api, bundle["move"]["id"], forward_start_date="2026-08-20"
    )
    assert filing["status"] == FilingStatus.DRAFT.value, (
        f"drafting is not the step that checks deliverability, got {filing['status']}"
    )

    assert_error(
        api.submit_filing(filing["id"], {}, ops_headers),
        ApiErrorId.ADDRESS_NOT_DELIVERABLE,
    )

    after = assert_ok(api.get_filing(filing["id"], ops_headers))
    assert after["status"] == FilingStatus.DRAFT.value, (
        f"a refused submission must leave the filing in DRAFT, got {after['status']}"
    )
    assert after["submitted_by_user_id"] is None, (
        "a refused submission must not record a submitter"
    )
    assert after["resubmit_count"] == 0, (
        f"a refused submission must not count as a resubmit, got {after['resubmit_count']}"
    )
    assert_unchanged(filing, after)


def _move_with_one_open_identity_attempt(api, ops_headers):
    """A household consented to postal filing whose first KBA attempt is still open."""
    network = fx.build_network(api)
    fx.grant_consents(
        api, network["resident"]["id"], [ConsentScope.USPS_FILING.value]
    )
    move = fx.ingest_move(api, network, move_date="2026-08-20")
    attempt = assert_created(
        api.create_identity_verification(move["id"], fac.kba_attempt_payload(), ops_headers)
    )
    return {**network, "move": move, "attempt": attempt}


def test_15_a_filing_cannot_be_drafted_while_identity_is_pending_or_failed(
    api, ops_headers, gateway_headers
):
    """Both unverified postures give the identity error, not the lifecycle error.

    PRD: "drafting separately requires the move's `verified_at` to be non-null,
    so a filing prepared for a household that has not yet cleared identity is
    refused with `ERR_IDENTITY_NOT_VERIFIED` rather than with
    `ERR_MOVE_NOT_ACTIONABLE`".

    Design: Corner/validations/violation_to_error_filing_creation_before_identity_clears_rejected
    """
    bundle = _move_with_one_open_identity_attempt(api, ops_headers)
    move_id = bundle["move"]["id"]

    assert_move_state(
        fx.read_move(api, move_id),
        lifecycle_status=MoveLifecycleStatus.IDENTITY_PENDING.value,
    )
    assert_error(
        api.create_filing(move_id, fac.filing_payload(), ops_headers),
        ApiErrorId.IDENTITY_NOT_VERIFIED,
    )

    assert_ok(
        api.post_kba_result(
            bundle["attempt"]["id"],
            fac.kba_result_payload(outcome=KbaOutcome.FAILED.value, score=310),
            gateway_headers,
        )
    )
    assert_move_state(
        fx.read_move(api, move_id),
        lifecycle_status=MoveLifecycleStatus.IDENTITY_FAILED.value,
    )
    assert_error(
        api.create_filing(move_id, fac.filing_payload(), ops_headers),
        ApiErrorId.IDENTITY_NOT_VERIFIED,
    )

    assert_page(api.list_filings(ops_headers, move_id=move_id), total_count=0)


def test_16_the_same_draft_request_succeeds_once_identity_has_cleared(
    api, ops_headers, gateway_headers
):
    """A passing second attempt stamps verified_at and the filing drafts at once.

    PRD: "drafting separately requires the move's `verified_at` to be non-null,
    so a filing prepared for a household that has not yet cleared identity is
    refused with `ERR_IDENTITY_NOT_VERIFIED`".

    Design: Corner/validations/violation_to_error_filing_creation_before_identity_clears_rejected
    """
    bundle = _move_with_one_open_identity_attempt(api, ops_headers)
    move_id = bundle["move"]["id"]
    assert_ok(
        api.post_kba_result(
            bundle["attempt"]["id"],
            fac.kba_result_payload(outcome=KbaOutcome.FAILED.value, score=310),
            gateway_headers,
        )
    )

    retry = assert_created(
        api.create_identity_verification(move_id, fac.kba_attempt_payload(), ops_headers)
    )
    assert_ok(
        api.post_kba_result(
            retry["id"],
            fac.kba_result_payload(outcome=KbaOutcome.PASSED.value, score=700),
            gateway_headers,
        )
    )
    verified = fx.read_move(api, move_id)
    assert verified["verified_at"] is not None, "a passing attempt must stamp verified_at"

    filing = assert_created(
        api.create_filing(move_id, fac.filing_payload(), ops_headers)
    )
    assert filing["status"] == FilingStatus.DRAFT.value, (
        f"expected a DRAFT filing, got {filing['status']}"
    )
    assert filing["resident_id"] == bundle["resident"]["id"], (
        f"the filing must name the household, got {filing['resident_id']}"
    )
    assert filing["forward_end_date"] == "2027-08-19", (
        f"expected a one-year term ending 2027-08-19, got {filing['forward_end_date']}"
    )
    assert_page(api.list_filings(ops_headers, move_id=move_id), total_count=1)
