"""Actions refused because a neighbouring entity is in the wrong state, then replayed."""

from test_helpers import (
    COUNSELOR,
    ApiErrorId,
    api_client,
    authorize_entitlement,
    award_shipment,
    create_capacity_block,
    create_claim_payload,
    create_shipment_payload,
    create_tsp,
    deliver_shipment,
    entitlement_version,
    get_success_data,
    list_notifications,
    pack_payload,
    read_capacity_block,
    read_entitlement,
    read_shipment,
    set_clock,
    setup_authorized_entitlement,
    setup_picked_up_shipment,
    setup_surveyed_shipment,
    validate_error,
    validate_success,
)

CLAIM_NOTICE_DATE = "2026-08-21T00:00:00Z"
PACK_DATE = "2026-08-15T00:00:00Z"


def _draft_entitlement_with_a_provider():
    """Counseling done, so the entitlement exists, but nobody has authorized it."""
    scenario = setup_authorized_entitlement(authorize=False)
    scenario["tsp"] = create_tsp()
    return scenario


def _booking_attempt(scenario):
    """Try to book the canonical household-goods shipment on the scenario's entitlement."""
    payload = create_shipment_payload(
        scenario["order"]["id"],
        scenario["entitlement"]["id"],
        scenario["tsp"]["id"],
        entitlement_version(scenario["entitlement"]["id"]),
    )
    return api_client.create_shipment(payload, COUNSELOR)


def _surveyed_shipment_and_an_unawarded_block():
    """A surveyed 5,286 pound shipment beside a published block it has not been awarded."""
    scenario = setup_surveyed_shipment()
    scenario["block"] = create_capacity_block(scenario["tsp"]["id"])
    return scenario


def _pack_attempt(scenario):
    return api_client.pack_shipment(
        scenario["shipment"]["id"], pack_payload(PACK_DATE), scenario["tsp_headers"]
    )


def _picked_up_shipment_at_notice_time():
    """A shipment weighed and picked up on 17 August, with the clock moved to 21 August."""
    scenario = setup_picked_up_shipment(
        weigh_date="2026-08-17T00:00:00Z",
        actual_pickup_date="2026-08-17T00:00:00Z",
    )
    set_clock(CLAIM_NOTICE_DATE)
    return scenario


def _claim_attempt(scenario):
    return api_client.create_claim(
        scenario["shipment"]["id"],
        create_claim_payload(CLAIM_NOTICE_DATE),
        scenario["member_headers"],
    )


class TestBookingNeedsAnAuthorizedEntitlement:
    """A ledger that was never authorized takes no shipment work at all."""

    def test_a_draft_entitlement_refuses_the_booking(self):
        """The counselor's booking is turned away while the entitlement sits in DRAFT.

        "The entitlement must be neither `DRAFT` nor `CLOSED` — a ledger never authorized,
        or already closed, takes no shipment work, and the attempt draws
        `ERR_ENTITLEMENT_NOT_AUTHORIZED`"

        Design: Difficulty/cross_entity_state_dependency/shipment_booking_requires_authorized_entitlement
        """
        scenario = _draft_entitlement_with_a_provider()

        validate_error(
            _booking_attempt(scenario),
            ApiErrorId.ERR_ENTITLEMENT_NOT_AUTHORIZED.value,
            409,
        )
        assert read_entitlement(scenario["entitlement"]["id"])["status"] == "DRAFT"

    def test_the_refusal_leaves_the_ledger_empty(self):
        """No pounds are charged and the entitlement owns no shipments.

        "When the inclusion set is empty, `charged_billable_weight_lbs` is 0,
        `excess_weight_lbs` is 0 and `gross_excess_cost_usd` is 0.00."

        Design: Difficulty/cross_entity_state_dependency/shipment_booking_requires_authorized_entitlement
        """
        scenario = _draft_entitlement_with_a_provider()
        _booking_attempt(scenario)

        entitlement = read_entitlement(scenario["entitlement"]["id"])
        assert entitlement["charged_billable_weight_lbs"] == 0
        assert entitlement["excess_weight_lbs"] == 0

        shipments = get_success_data(
            api_client.list_entitlement_shipments(
                scenario["entitlement"]["id"], COUNSELOR
            )
        )
        assert shipments == []

    def test_authorizing_the_entitlement_lets_the_same_body_through(self):
        """Once the E6 ledger is authorized at 11,000 pounds the booking is created.

        "Authorizing the entitlement moves it `DRAFT → AUTHORIZED` and is available to a
        counselor or administrator"

        Design: Difficulty/cross_entity_state_dependency/shipment_booking_requires_authorized_entitlement
        """
        scenario = _draft_entitlement_with_a_provider()
        _booking_attempt(scenario)

        authorized = authorize_entitlement(scenario["entitlement"]["id"])
        assert authorized["status"] == "AUTHORIZED"
        assert authorized["total_billable_cap_lbs"] == 11000

        shipment = validate_success(_booking_attempt(scenario), 201)
        assert shipment["movement_status"] == "AWARDED"
        assert shipment["weight_recon_status"] == "PENDING"


class TestPackingNeedsAnAwardedCapacityBlock:
    """A surveyed shipment with no weekly slot cannot be packed."""

    def test_packing_without_a_slot_is_refused(self):
        """A published block nearby is no help until the shipment is awarded into it.

        "the shipment must already hold a weekly capacity slot — a null
        `capacity_block_id` is refused with `ERR_CAPACITY_BLOCK_NOT_ASSIGNED`"

        Design: Difficulty/cross_entity_state_dependency/packing_requires_an_awarded_capacity_block
        """
        scenario = _surveyed_shipment_and_an_unawarded_block()

        validate_error(
            _pack_attempt(scenario),
            ApiErrorId.ERR_CAPACITY_BLOCK_NOT_ASSIGNED.value,
            409,
        )

    def test_the_refusal_stores_no_pack_date_and_raises_no_obligation(self):
        """The shipment stays surveyed, slotless and free of any notice obligation.

        "On acceptance `pack_date` is stored and one notification obligation of type
        `PACK_DATE_CONFIRMED` is created for the shipment in `status` `PENDING`, with
        `trigger_event_at` taken from the logical clock."

        Design: Difficulty/cross_entity_state_dependency/packing_requires_an_awarded_capacity_block
        """
        scenario = _surveyed_shipment_and_an_unawarded_block()
        _pack_attempt(scenario)

        shipment = read_shipment(scenario["shipment"]["id"])
        assert shipment["movement_status"] == "SURVEYED"
        assert shipment["capacity_block_id"] is None
        assert shipment["pack_date"] is None
        assert list_notifications(scenario["shipment"]["id"]) == []

    def test_the_award_commits_the_pounds_and_unblocks_the_pack(self):
        """5,286 surveyed pounds enter the general pool and the replayed pack succeeds.

        "On acceptance the pounds are added to `committed_general_lbs`."

        Design: Difficulty/cross_entity_state_dependency/packing_requires_an_awarded_capacity_block
        """
        scenario = _surveyed_shipment_and_an_unawarded_block()
        _pack_attempt(scenario)

        award_shipment(scenario["block"]["id"], scenario["shipment"]["id"])
        assert (
            read_shipment(scenario["shipment"]["id"])["capacity_block_id"]
            == scenario["block"]["id"]
        )
        assert read_capacity_block(scenario["block"]["id"])["committed_general_lbs"] == 5286

        packed = validate_success(_pack_attempt(scenario), 200)
        assert packed["movement_status"] == "PACKED"
        assert packed["pack_date"] == PACK_DATE


class TestClaimFilingNeedsADeliveredShipment:
    """Damage is discovered at destination, so nothing can be claimed before delivery."""

    def test_a_claim_against_a_shipment_in_transit_is_refused(self):
        """The goods are still on the road, so the notice has nowhere to land.

        "a claim can only be opened against a shipment whose `movement_status` is
        `DELIVERED`; anything earlier is refused with `ERR_SHIPMENT_NOT_DELIVERED`"

        Design: Difficulty/cross_entity_state_dependency/claim_filing_requires_delivered_shipment
        """
        scenario = _picked_up_shipment_at_notice_time()

        validate_error(
            _claim_attempt(scenario), ApiErrorId.ERR_SHIPMENT_NOT_DELIVERED.value, 409
        )

        shipment = read_shipment(scenario["shipment"]["id"])
        assert shipment["movement_status"] == "PICKED_UP"
        assert shipment["delivery_date"] is None

    def test_the_refusal_records_no_claim_on_the_shipment(self):
        """The shipment's claim list is still empty after the attempt.

        "A new claim is `DRAFT`, with `settlement_basis` `UNDETERMINED`, `filed_date` and
        `filing_window_days` null, `claimed_total_usd` 0.00, `settlement_total_usd` 0.00,
        `item_count` 0, `info_request_count` 0"

        Design: Difficulty/cross_entity_state_dependency/claim_filing_requires_delivered_shipment
        """
        scenario = _picked_up_shipment_at_notice_time()
        _claim_attempt(scenario)

        claims = get_success_data(
            api_client.list_shipment_claims(scenario["shipment"]["id"], COUNSELOR)
        )
        assert claims == []

    def test_delivery_opens_the_claim_and_fixes_the_transit_deadline(self):
        """Delivered inside its six transit days, the shipment now accepts the notice.

        "`required_delivery_by` remains null until pickup, at which point it becomes the
        `actual_pickup_date` advanced by `transit_days_allowed` days."

        Design: Difficulty/cross_entity_state_dependency/claim_filing_requires_delivered_shipment
        """
        scenario = _picked_up_shipment_at_notice_time()
        _claim_attempt(scenario)

        delivered = deliver_shipment(scenario, delivery_date="2026-08-20T00:00:00Z")
        assert delivered["movement_status"] == "DELIVERED"
        assert delivered["required_delivery_by"] == "2026-08-23T00:00:00Z"

        claim = validate_success(_claim_attempt(scenario), 201)
        assert claim["status"] == "DRAFT"
        assert claim["settlement_basis"] == "UNDETERMINED"
