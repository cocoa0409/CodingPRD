"""Record shapes, defaults, derived fields and the not-found code of every collection.

Creation applies the declared defaults rather than the caller's optimism: the safest
participation model wins when the field is omitted, and the position account's derived trio
is computed from the opening deposit and an empty ledger even when the payload tries to
dictate it. The ledger entry is the one record with no version at all.

The rest of the file walks the addressable collections and pins each one's own 404 code,
including the ones reachable only through an action endpoint.
"""

from test_helpers import (
    CORE_BANKING_SYSTEM,
    ERR_CREDIT_TRANSFER_NOT_FOUND,
    ERR_CUSTOMER_ACCOUNT_NOT_FOUND,
    ERR_FRAUD_REVIEW_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_LIQUIDITY_ALERT_NOT_FOUND,
    ERR_OUTAGE_EVENT_NOT_FOUND,
    ERR_PARTICIPANT_NOT_FOUND,
    ERR_POSITION_ACCOUNT_NOT_FOUND,
    ERR_RECONCILIATION_RUN_NOT_FOUND,
    ERR_RETURN_REQUEST_NOT_FOUND,
    ERR_RFP_NOT_FOUND,
    ERR_SETTLEMENT_CYCLE_NOT_FOUND,
    FRAUD_REVIEWER,
    LIQUIDITY_OFFICER,
    NETWORK_OPERATOR,
    NON_EXISTENT_UUID,
    PAYMENT_OPERATOR_ALPHA,
    ROUTING_BETA,
    account_version,
    alert_acknowledgement_payload,
    assert_pagination_meta,
    assert_participant_shape,
    assert_position_account_shape,
    assert_system_fields,
    bring_participant_live,
    credit_transfer_payload,
    customer_account_payload,
    enroll_participant,
    is_valid_uuid,
    ledger_adjustment_payload,
    make_participant_admin_headers,
    open_position_account,
    open_settlement_cycle,
    outage_resolution_payload,
    participant_payload,
    position_account_payload,
    publish_segment_policy,
    read_account,
    read_participant,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)




def test_enrolment_applies_the_declared_defaults(api):
    """Only three inputs are needed, and every other field is defaulted by the rail.

    PRD 3.1: "The requested `participation_model` may be supplied at enrolment and, when
    omitted, defaults to `RECEIVE_ONLY`; the three tiers are `SEND_AND_RECEIVE`,
    `RECEIVE_ONLY` and `RECEIVE_AND_REQUEST_FOR_PAYMENT`."

    Design: Corner/entities/participant_create_applies_defaults_and_system_fields
    """
    set_clock(api, "2026-08-01T00:00:00Z")

    participant = validate_success(
        api.create_participant(participant_payload(), NETWORK_OPERATOR), 201
    )

    assert_participant_shape(participant)
    assert_system_fields(participant, "participant")
    assert is_valid_uuid(participant["id"])
    assert participant["participation_model"] == "RECEIVE_ONLY"
    assert participant["enrollment_status"] == "DRAFT"
    assert participant["operational_posture"] == "NORMAL"
    assert participant["version"] == 1
    assert participant["go_live_business_date"] is None
    assert participant["certification_round"] == 0
    assert participant["suspension_reason"] is None


def test_reading_a_participant_returns_the_supplied_model(api):
    """The read path returns what was stored rather than re-deriving the input fields.

    PRD 3.1: "A newly enrolled participant lands in `DRAFT` `enrollment_status` with
    `operational_posture` `NORMAL` and `certification_round` 0."

    Design: Corner/entities/participant_retrieval_returns_stored_row
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    created = enroll_participant(
        api,
        legal_name="Beta Trust Bank",
        routing_number=ROUTING_BETA,
        settlement_agent_reference="SA-BETA-01",
        participation_model="RECEIVE_AND_REQUEST_FOR_PAYMENT",
    )

    stored = validate_success(api.get_participant(created["id"], LIQUIDITY_OFFICER))

    assert stored["legal_name"] == "Beta Trust Bank"
    assert stored["routing_number"] == "021000089"
    assert stored["settlement_agent_reference"] == "SA-BETA-01"
    assert stored["participation_model"] == "RECEIVE_AND_REQUEST_FOR_PAYMENT"
    assert stored["enrollment_status"] == "DRAFT"
    assert stored["version"] == 1


def test_position_account_listing_is_scoped_to_its_parent_participant(api):
    """The sub-resource list carries the declared metadata and never leaks a sibling.

    PRD 2.3: "List responses populate `limit`, `offset`, `total_count` and `has_more`
    inside `meta`, where `total_count` counts every record matching the filters before
    pagination is applied and `has_more` indicates whether records remain beyond the current
    page."

    Design: Corner/entities/participant_position_accounts_listing_returns_envelope
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    alpha = enroll_participant(api, participation_model="SEND_AND_RECEIVE")
    alpha_account = open_position_account(api, alpha["id"])
    beta = enroll_participant(
        api,
        legal_name="Beta Trust Bank",
        routing_number=ROUTING_BETA,
        settlement_agent_reference="SA-BETA-01",
        participation_model="SEND_AND_RECEIVE",
    )
    open_position_account(
        api,
        beta["id"],
        opening_balance_cents=500_000_000,
        warning_threshold_cents=300_000_000,
        critical_threshold_cents=200_000_000,
        floor_cents=100_000_000,
    )

    accounts, meta = validate_paginated(
        api.list_participant_position_accounts(alpha["id"], LIQUIDITY_OFFICER)
    )

    assert_pagination_meta(meta, total_count=1, has_more=False)
    assert len(accounts) == 1
    listed = accounts[0]
    assert listed["id"] == alpha_account["id"]
    assert_position_account_shape(listed)
    assert listed["opening_balance_cents"] == 1_200_000_000
    assert listed["current_balance_cents"] == 1_200_000_000
    assert listed["reserved_cents"] == 0
    assert listed["available_cents"] == 1_200_000_000
    assert listed["alert_tier"] == "GREEN"


def test_opening_a_position_account_without_the_floor_is_refused(api):
    """A missing required input is a payload-shape refusal, not a silently zeroed floor.

    PRD 2.11: "**Payload shape.** Required inputs present, enum values inside their
    declared sets, JSON types correct, and every `*_cents` input that must be positive
    actually a positive integer — all of these yield `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/position_account_missing_required_floor_cents_rejected
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    participant = enroll_participant(api, participation_model="SEND_AND_RECEIVE")

    payload = position_account_payload(participant["id"])
    payload.pop("floor_cents")
    response = api.create_position_account(payload, LIQUIDITY_OFFICER)
    validate_error(response, ERR_INVALID_REQUEST)

    _accounts, meta = validate_paginated(
        api.list_participant_position_accounts(participant["id"], LIQUIDITY_OFFICER)
    )
    assert meta["total_count"] == 0


def test_customer_segment_outside_the_declared_four_is_refused(api):
    """An undeclared enum value is refused before any policy lookup could complain.

    PRD 3.2: "The administrator supplies the owning `participant_id`, the customer's
    `segment` (drawn from the same four values, since the segment both selects the governing
    policy and supplies the fraud multiplier), a bank-internal `account_reference` that must
    be unique within that participant, and a static `fraud_risk_baseline` between 0 and 100
    inclusive that feeds every fraud score computed for that customer."

    Design: Corner/entities/customer_account_invalid_enum_segment_rejected
    """
    set_clock(api, "2026-08-03T13:00:00Z")
    alpha = bring_participant_live(api)

    response = api.create_customer_account(
        customer_account_payload(alpha.id, "CUST-ALPHA-0009", "GOVERNMENT", 20),
        make_participant_admin_headers(alpha.id),
    )
    validate_error(response, ERR_INVALID_REQUEST)

    _customers, meta = validate_paginated(
        api.list_participant_customer_accounts(alpha.id, make_participant_admin_headers(alpha.id))
    )
    assert meta["total_count"] == 0


def test_supplied_values_for_the_derived_trio_are_ignored(api):
    """The balances come from the opening deposit and an empty ledger, not the payload.

    PRD 3.3: "Opening the account seeds the derived trio in a single pass:
    `current_balance_cents` starts equal to the opening balance because no entry has been
    posted yet, `reserved_cents` starts at 0 because nothing is in flight,
    `available_cents` follows from the two, and `last_ledger_sequence_no` starts at 0."

    Design: Corner/entities/position_account_computed_balances_input_ignored
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    participant = enroll_participant(api, participation_model="SEND_AND_RECEIVE")

    payload = position_account_payload(participant["id"])
    payload.update(
        {
            "current_balance_cents": 999,
            "reserved_cents": 777,
            "available_cents": 555,
            "alert_tier": "BREACH",
            "last_ledger_sequence_no": 42,
        }
    )
    account = validate_success(api.create_position_account(payload, LIQUIDITY_OFFICER), 201)

    assert account["current_balance_cents"] == 1_200_000_000
    assert account["reserved_cents"] == 0
    assert account["available_cents"] == 1_200_000_000
    assert account["alert_tier"] == "GREEN"
    assert account["last_ledger_sequence_no"] == 0
    assert read_participant(api, participant["id"])["operational_posture"] == "NORMAL"


def test_a_posted_ledger_entry_carries_no_version_and_no_updated_at(api):
    """The ledger row is an accounting fact, so it has nothing to update.

    PRD 2.4: "A `LiquidityLedgerEntry` is an append-only, immutable accounting fact: it
    carries only `id` and `created_at`."

    Design: Corner/entities/ledger_entry_immutable_carries_no_version
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    participant = enroll_participant(api, participation_model="SEND_AND_RECEIVE")
    account = open_position_account(api, participant["id"])

    entry = validate_success(
        api.post_ledger_adjustment(
            account["id"],
            ledger_adjustment_payload(
                "FUNDING_CREDIT", 100_000_000, "Morning prefunding top-up"
            ),
            LIQUIDITY_OFFICER,
        ),
        201,
    )

    assert is_valid_uuid(entry["id"])
    assert "created_at" in entry
    assert "version" not in entry
    assert "updated_at" not in entry
    assert entry["entry_type"] == "FUNDING_CREDIT"
    assert entry["amount_cents"] == 100_000_000
    assert entry["balance_after_cents"] == 1_300_000_000
    assert entry["sequence_no"] == 1
    assert entry["business_date"] == "2026-08-01"

    account_after = read_account(api, account["id"])
    assert account_after["current_balance_cents"] == 1_300_000_000
    assert account_after["alert_tier"] == "GREEN"
    assert account_after["last_ledger_sequence_no"] == 1


def test_origination_naming_an_unknown_customer_account_is_a_404(api):
    """Body references resolve before any business rule, and nothing is left behind.

    PRD 2.10: "A `customer_account_id` or `debtor_customer_account_id` must resolve to an
    existing customer account or the request fails with `ERR_CUSTOMER_ACCOUNT_NOT_FOUND`."

    Design: Corner/entities/credit_transfer_with_unknown_customer_account_id_not_found
    """
    set_clock(api, "2026-08-03T13:00:00Z")
    alpha = bring_participant_live(api)
    publish_segment_policy(api, alpha.id)
    open_settlement_cycle(api)
    version_before = account_version(api, alpha.account_id)

    response = api.create_credit_transfer(
        credit_transfer_payload(
            alpha.id,
            NON_EXISTENT_UUID,
            100_000_000,
            version_before,
            receiver_routing_number=ROUTING_BETA,
        ),
        PAYMENT_OPERATOR_ALPHA,
    )
    validate_error(response, ERR_CUSTOMER_ACCOUNT_NOT_FOUND)

    account = read_account(api, alpha.account_id)
    assert account["version"] == version_before
    assert account["reserved_cents"] == 0


def test_unknown_participant_read_is_a_participant_not_found(api):
    """Path resolution answers with the collection's own code, never a generic 400.

    PRD 2.10: "Path parameters are resolved strictly left to right, and each segment must
    resolve before the next is considered, so a request naming a participant that does not
    exist is answered `ERR_PARTICIPANT_NOT_FOUND` (HTTP 404) regardless of whether the
    sub-resource named further right would have existed."

    Design: Corner/entities/participant_unknown_id_not_found
    """
    set_clock(api, "2026-08-01T00:00:00Z")

    validate_error(api.get_participant(NON_EXISTENT_UUID, NETWORK_OPERATOR), ERR_PARTICIPANT_NOT_FOUND)


def test_unknown_position_account_returns_the_same_code_on_every_sub_path(api):
    """One resolution rule serves the account read and all three of its channels.

    PRD 2.10: "Each addressable collection has its own not-found code:
    `ERR_POSITION_ACCOUNT_NOT_FOUND`, `ERR_LIQUIDITY_ALERT_NOT_FOUND`,
    `ERR_CUSTOMER_ACCOUNT_NOT_FOUND`, `ERR_CREDIT_TRANSFER_NOT_FOUND`, `ERR_RFP_NOT_FOUND`,
    `ERR_FRAUD_REVIEW_NOT_FOUND`, `ERR_RETURN_REQUEST_NOT_FOUND`,
    `ERR_SETTLEMENT_CYCLE_NOT_FOUND`, `ERR_RECONCILIATION_RUN_NOT_FOUND` and
    `ERR_OUTAGE_EVENT_NOT_FOUND`, each answered with HTTP 404."

    Design: Corner/entities/position_account_unknown_id_not_found
    """
    set_clock(api, "2026-08-01T00:00:00Z")

    validate_error(
        api.get_position_account(NON_EXISTENT_UUID, LIQUIDITY_OFFICER),
        ERR_POSITION_ACCOUNT_NOT_FOUND,
    )
    validate_error(
        api.list_ledger_entries(NON_EXISTENT_UUID, LIQUIDITY_OFFICER),
        ERR_POSITION_ACCOUNT_NOT_FOUND,
    )
    validate_error(
        api.list_account_alerts(NON_EXISTENT_UUID, LIQUIDITY_OFFICER),
        ERR_POSITION_ACCOUNT_NOT_FOUND,
    )
    validate_error(
        api.get_liquidity_projection(NON_EXISTENT_UUID, LIQUIDITY_OFFICER),
        ERR_POSITION_ACCOUNT_NOT_FOUND,
    )


def test_acknowledging_an_unknown_alert_is_an_alert_not_found(api):
    """The alert's only action endpoint raises its 404 ahead of every state rule.

    PRD 2.10: "Sub-resource read paths are reverse-reachability channels only."

    Design: Corner/entities/liquidity_alert_unknown_id_not_found
    """
    set_clock(api, "2026-08-01T00:00:00Z")

    response = api.acknowledge_alert(
        NON_EXISTENT_UUID,
        alert_acknowledgement_payload("Funding request raised with treasury."),
        LIQUIDITY_OFFICER,
    )
    validate_error(response, ERR_LIQUIDITY_ALERT_NOT_FOUND)


def test_unknown_request_for_payment_is_a_404_on_read_and_on_delivery(api):
    """The request-for-payment code covers the read and its message actions alike.

    PRD 2.10: "An `rfp_id` is optional, but when it is supplied and non-null it must
    resolve to an existing request for payment or the request fails with
    `ERR_RFP_NOT_FOUND`."

    Design: Corner/entities/request_for_payment_unknown_id_not_found
    """
    set_clock(api, "2026-08-01T00:00:00Z")

    validate_error(api.get_request_for_payment(NON_EXISTENT_UUID, NETWORK_OPERATOR), ERR_RFP_NOT_FOUND)
    validate_error(
        api.deliver_request_for_payment(NON_EXISTENT_UUID, NETWORK_OPERATOR), ERR_RFP_NOT_FOUND
    )


def test_assigning_an_unknown_fraud_review_is_a_review_not_found(api):
    """Reviews are minted by the hold cascade, so their 404 surfaces on the actions.

    PRD 2.10: "Nothing is ever written through them, and they are the sole discovery route
    for records that other operations create as a side effect: the fraud review raised by an
    origination cascade, the ledger entries generated by a settlement or a honoured return,
    the alerts raised on an account, and the outage events scoped to a participant."

    Design: Corner/entities/fraud_review_unknown_id_not_found
    """
    set_clock(api, "2026-08-01T00:00:00Z")

    validate_error(
        api.assign_fraud_review(NON_EXISTENT_UUID, FRAUD_REVIEWER), ERR_FRAUD_REVIEW_NOT_FOUND
    )


def test_unknown_return_request_is_a_404_on_read_and_on_honour(api):
    """The lodged-request code guards the read and both adjudication actions.

    PRD 2.10: "References carried in a request body are checked after every path identifier
    has resolved, and they use the same codes as the paths they mirror."

    Design: Corner/entities/return_request_unknown_id_not_found
    """
    set_clock(api, "2026-08-01T00:00:00Z")

    validate_error(
        api.get_return_request(NON_EXISTENT_UUID, NETWORK_OPERATOR), ERR_RETURN_REQUEST_NOT_FOUND
    )
    validate_error(
        api.honor_return_request(NON_EXISTENT_UUID, NETWORK_OPERATOR), ERR_RETURN_REQUEST_NOT_FOUND
    )


def test_unknown_settlement_cycle_is_a_404_on_read_and_on_cutoff(api):
    """The cycle's own code answers the read and the day-end actions.

    PRD 2.10: "A `settlement_cycle_id` must resolve to an existing settlement cycle or the
    request fails with `ERR_SETTLEMENT_CYCLE_NOT_FOUND`."

    Design: Corner/entities/settlement_cycle_unknown_id_not_found
    """
    set_clock(api, "2026-08-01T00:00:00Z")

    validate_error(
        api.get_settlement_cycle(NON_EXISTENT_UUID, NETWORK_OPERATOR),
        ERR_SETTLEMENT_CYCLE_NOT_FOUND,
    )
    validate_error(
        api.cutoff_settlement_cycle(NON_EXISTENT_UUID, NETWORK_OPERATOR),
        ERR_SETTLEMENT_CYCLE_NOT_FOUND,
    )


def test_unknown_reconciliation_run_read_is_a_404_while_the_list_is_empty(api):
    """A missing single run is a 404; a matching-nothing list is an empty page.

    PRD 3.10: "Runs may be read individually and listed with filters on
    `settlement_cycle_id`, `participant_id`, `variant` and `outcome`, ascending by `revision`
    within a triple, exposing `rail_net_position_cents`, `variance_cents`, `outcome`,
    `included_transfer_count` and `fee_component_cents`."

    Design: Corner/entities/reconciliation_run_unknown_id_not_found
    """
    set_clock(api, "2026-08-01T00:00:00Z")

    validate_error(
        api.get_reconciliation_run(NON_EXISTENT_UUID, CORE_BANKING_SYSTEM),
        ERR_RECONCILIATION_RUN_NOT_FOUND,
    )

    runs, meta = validate_paginated(api.list_reconciliation_runs(CORE_BANKING_SYSTEM))
    assert runs == []
    assert_pagination_meta(meta, total_count=0, has_more=False)


def test_resolving_an_unknown_outage_event_is_an_event_not_found(api):
    """The event's 404 precedes both the interval rule and the declared-state rule.

    PRD 3.9: "Resolution is permitted only from `DECLARED` — `RESOLVED` is terminal — and
    it writes `ended_at`, moves the event `DECLARED → RESOLVED`, and then re-derives the
    posture of every participant the event covered."

    Design: Corner/entities/outage_event_unknown_id_not_found
    """
    set_clock(api, "2026-08-01T00:00:00Z")

    response = api.resolve_outage_event(
        NON_EXISTENT_UUID, outage_resolution_payload("2026-08-01T00:00:00Z"), NETWORK_OPERATOR
    )
    validate_error(response, ERR_OUTAGE_EVENT_NOT_FOUND)


def test_unknown_credit_transfer_read_is_a_transfer_not_found(api):
    """A well-formed but unknown identifier is the transfer collection's own 404.

    PRD 2.10: "A `credit_transfer_id` must resolve to an existing transfer or the request
    fails with `ERR_CREDIT_TRANSFER_NOT_FOUND`."

    Design: Corner/entities/credit_transfer_unknown_id_not_found
    """
    set_clock(api, "2026-08-01T00:00:00Z")

    validate_error(
        api.get_credit_transfer(NON_EXISTENT_UUID, NETWORK_OPERATOR), ERR_CREDIT_TRANSFER_NOT_FOUND
    )
