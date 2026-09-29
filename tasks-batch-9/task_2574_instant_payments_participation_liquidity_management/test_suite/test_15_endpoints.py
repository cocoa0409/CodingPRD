"""Read, list and bulk surfaces that report figures nobody submitted.

A nested list has to combine a filter with a page window and still describe the
filtered set honestly; a single housekeeping call has to close two unrelated
backlogs and keep their counts apart; a fulfilling payment has to carry the link
back to the request that unlocked it so the list can find it again; a cycle read
has to expose a per-transfer fee sum and a settled count that were derived at
cutoff; and an action endpoint has to refuse a payment that was never parked even
though the payload names a valid rail and the caller holds a permitted role.
"""

from test_helpers import (
    accept_transfer,
    alpha_and_beta_scenario,
    alpha_scenario,
    assert_instant,
    assert_ledger_entry,
    assert_pagination_meta,
    assert_segment_policy_shape,
    assert_sweep_counts,
    assert_transfer_dimensions,
    cutoff_cycle,
    declare_outage,
    deliver_request_for_payment,
    diversion_payload,
    divert_transfer,
    ERR_INVALID_STATE_TRANSITION,
    LIQUIDITY_OFFICER,
    list_ledger_entries_with_meta,
    list_segment_policies_with_meta,
    list_transfers_with_meta,
    live_alpha,
    participant_version,
    PAYMENT_OPERATOR_ALPHA,
    PAYMENT_OPERATOR_BETA,
    publish_segment_policy,
    raise_request_for_payment,
    read_account,
    read_cycle,
    read_return_request,
    read_rfp,
    read_transfer,
    respond_to_request_for_payment,
    return_requested_scenario,
    run_sweep,
    send_from_alpha,
    set_clock,
    settle_transfer,
    validate_error,
)

FEE_ACCOUNT = {
    "opening_balance_cents": 1_200_000_000,
    "warning_threshold_cents": 1_000_000_000,
    "critical_threshold_cents": 900_000_000,
    "floor_cents": 200_000_000,
}


def test_the_policy_page_after_the_filter_still_describes_the_whole_filtered_set(api):
    """A skipped page reports total_count 3 and has_more false at the same time.

    PRD 2.3: "List responses populate `limit`, `offset`, `total_count` and `has_more` inside
    `meta`, where `total_count` counts every record matching the filters before pagination is
    applied and `has_more` indicates whether records remain beyond the current page."

    PRD 3.1: "Reading a participant returns its derived `operational_posture` alongside its
    stored enrolment fields, and four reverse-reachability lists hang off the participant
    record: its zero-or-one prefunded position accounts, its segment policies (returned newest
    `effective_from` first, optionally narrowed by `segment`), its customer accounts
    (optionally narrowed by `segment` and by `status`), and the outage events scoped to it
    (optionally narrowed by `status`)."

    PRD 3.2: "Every successful publication also increments the owning `Participant.version`,
    which is precisely why a second publication in the same session must re-read the
    participant to obtain a fresh `expected_participant_version`."

    Design: Corner/endpoints/segment_policy_listing_filters_and_paginates_with_envelope
    """
    set_clock(api, "2026-08-03T13:00:00Z")
    alpha = live_alpha(api)
    first_version = participant_version(api, alpha.id)

    consumer = publish_segment_policy(
        api,
        alpha.id,
        segment="CONSUMER",
        per_transaction_limit_cents=25_000_000,
        effective_from="2026-08-01T00:00:00Z",
    )
    second_version = participant_version(api, alpha.id)

    small_business = publish_segment_policy(
        api,
        alpha.id,
        segment="SMALL_BUSINESS",
        per_transaction_limit_cents=50_000_000,
        effective_from="2026-07-31T00:00:00Z",
    )
    third_version = participant_version(api, alpha.id)

    corporate = publish_segment_policy(
        api,
        alpha.id,
        segment="CORPORATE",
        effective_from="2026-07-30T00:00:00Z",
    )
    fourth_version = participant_version(api, alpha.id)

    assert first_version < second_version < third_version < fourth_version
    assert second_version == first_version + 1
    assert third_version == second_version + 1
    assert fourth_version == third_version + 1

    for policy in (consumer, small_business, corporate):
        assert_segment_policy_shape(policy)
        assert policy["participant_id"] == alpha.id
        assert policy["version"] == 1
        assert policy["effective_to"] is None
        assert policy["superseded_at"] is None

    last_page, last_meta = list_segment_policies_with_meta(
        api, alpha.id, {"limit": 2, "offset": 2}
    )
    assert [row["id"] for row in last_page] == [corporate["id"]]
    assert last_page[0]["segment"] == "CORPORATE"
    assert_pagination_meta(last_meta, total_count=3, has_more=False, limit=2, offset=2)

    filtered, filtered_meta = list_segment_policies_with_meta(
        api, alpha.id, {"segment": "SMALL_BUSINESS", "limit": 10, "offset": 0}
    )
    assert [row["id"] for row in filtered] == [small_business["id"]]
    assert filtered[0]["segment"] == "SMALL_BUSINESS"
    assert filtered[0]["per_transaction_limit_cents"] == 50_000_000
    assert_pagination_meta(filtered_meta, total_count=1, has_more=False, limit=10, offset=0)


def test_one_sweep_closes_two_backlogs_and_keeps_the_counts_apart(api):
    """The expired request touches nothing; the expired return marks its transfer.

    PRD 3.10: "Finally, the network housekeeping sweep is the one operation that advances
    time-driven state, and it does exactly four things at the current logical clock, reporting
    a count for each: it expires every request for payment in `CREATED`, `DELIVERED` or
    `AMENDMENT_REQUESTED` whose `expiry_at` the clock has reached, reported as
    `expired_rfp_count`; it expires every `REQUESTED` return request whose
    `response_deadline_at` the clock has reached, setting the underlying transfer's
    `exception_status` to `RETURN_EXPIRED`, reported as `expired_return_request_count`; it
    expires every `QUEUED_THROTTLED` transfer whose `queued_at` is at least 120 minutes old,
    releasing its reservation, reported as `expired_transfer_count`; and it escalates every
    `OPEN` liquidity alert at least 60 minutes old, stamping `escalated_at`, reported as
    `escalated_alert_count`."

    PRD 3.7: "From any of `CREATED`, `DELIVERED` or `AMENDMENT_REQUESTED`, a request whose
    `expiry_at` has been reached by the clock becomes `EXPIRED` during the housekeeping sweep,
    and no other record is touched by that hop."

    PRD 3.8: "A request nobody answers is expired by the housekeeping sweep once the clock
    reaches its `response_deadline_at`, which turns the request `EXPIRED` and the transfer's
    `exception_status` `RETURN_EXPIRED`, again with no ledger movement — so a declined or
    expired return leaves the customer's daily usage consumed, which is the whole reason the
    conserved counter is defined the way it is."

    Design: Corner/endpoints/network_sweep_expires_rfp_and_return_request_in_one_call
    """
    scenario, transfer, request = return_requested_scenario(
        api,
        amount_cents=50_000_000,
        reason_code="DUPLICATE_PAYMENT",
        settlement_clock="2026-08-03T13:00:00Z",
        lodgement_clock="2026-08-03T13:00:00Z",
    )
    assert request["status"] == "REQUESTED"
    assert_instant(request["response_deadline_at"], "2026-08-04T13:00:00Z", "response_deadline_at")
    assert_transfer_dimensions(transfer, "SETTLED", "RETURN_REQUESTED")

    assert scenario.beta is not None
    unanswered = raise_request_for_payment(
        api,
        scenario.beta.id,
        scenario.alpha.customer_account_id,
        3_000_000,
        "2026-08-03T13:20:00Z",
        operator=PAYMENT_OPERATOR_BETA,
        memo="Invoice INV-9100",
    )
    delivered = deliver_request_for_payment(api, unanswered["id"])
    assert delivered["status"] == "DELIVERED"
    assert_instant(delivered["delivered_at"], "2026-08-03T13:00:00Z", "delivered_at")
    assert_instant(delivered["response_deadline_at"], "2026-08-03T13:20:00Z", "response_deadline_at")

    funded = read_account(api, scenario.alpha.account_id)
    assert funded["current_balance_cents"] == 1_150_000_000
    assert funded["alert_tier"] == "GREEN"

    set_clock(api, "2026-08-04T13:05:00Z")
    report = run_sweep(api)
    assert_sweep_counts(report, 1, 1, 0, 0)

    swept_rfp = read_rfp(api, unanswered["id"])
    assert swept_rfp["status"] == "EXPIRED"
    assert swept_rfp["last_response"] is None
    assert swept_rfp["amendment_round"] == 0
    assert_instant(swept_rfp["delivered_at"], "2026-08-03T13:00:00Z", "delivered_at")
    assert swept_rfp["amount_cents"] == 3_000_000

    swept_request = read_return_request(api, request["id"])
    assert swept_request["status"] == "EXPIRED"
    assert swept_request["honored_transfer_id"] is None
    assert_transfer_dimensions(read_transfer(api, transfer["id"]), "SETTLED", "RETURN_EXPIRED")

    settled_position = read_account(api, scenario.alpha.account_id)
    assert settled_position["current_balance_cents"] == 1_150_000_000
    assert settled_position["reserved_cents"] == 0
    assert settled_position["available_cents"] == 1_150_000_000

    assert_sweep_counts(run_sweep(api), 0, 0, 0, 0)


def test_a_matching_fulfilment_links_the_payment_to_the_request_it_answers(api):
    """The admitted twin of the mismatch refusal, discoverable by the rfp_id filter.

    PRD 3.4: "When the send names an `rfp_id`, three coherence conditions apply together: the
    referenced request must be in `ACCEPTED` status, its `debtor_customer_account_id` must
    equal the transfer's `customer_account_id`, and the transfer's `amount_cents` must equal
    the request's `amount_cents` exactly — partial and over-payment of a request are both
    refused with `ERR_RFP_FULFILMENT_MISMATCH`."

    PRD 3.4: "A send that clears the whole ladder is persisted with `direction` `OUTBOUND`,
    `rail` `INSTANT`, `clearing_status` `INITIATED`, `exception_status` `NONE`,
    `segment_policy_id` pinned to the governing policy, `initiated_by_user_id` taken from the
    acting `X-User-ID`, and `rejection_reason_code` unset."

    PRD 3.4: "Transfers can be read individually, returning both dimensions along with the
    frozen `fraud_score` and `fraud_reason_codes`, and listed with filters on
    `originator_participant_id`, `customer_account_id`, `segment_policy_id`, `rfp_id`,
    `compensating_for_transfer_id`, `clearing_status`, `exception_status` and
    `settlement_business_date`."

    PRD 3.7: "An `ACCEPT` additionally requires the clock to be strictly before `expiry_at`
    and the debtor `CustomerAccount.status` to be `ACTIVE`, and moves the request `DELIVERED →
    ACCEPTED`; an accepted request is what unlocks a fulfilling origination that names it in
    `rfp_id`, and it becomes payable exactly once that way."

    Design: Corner/endpoints/accepted_rfp_fulfilled_by_matching_transfer_links_both_rows
    """
    scenario = alpha_and_beta_scenario(api)
    assert scenario.beta is not None

    requested = raise_request_for_payment(
        api,
        scenario.beta.id,
        scenario.alpha.customer_account_id,
        5_000_000,
        "2026-08-04T13:00:00Z",
        operator=PAYMENT_OPERATOR_BETA,
        memo="Invoice INV-9005",
    )
    deliver_request_for_payment(api, requested["id"])
    accepted = respond_to_request_for_payment(
        api, requested["id"], "ACCEPT", operator=PAYMENT_OPERATOR_ALPHA
    )
    assert accepted["status"] == "ACCEPTED"
    assert accepted["last_response"] == "ACCEPT"

    fulfilling = send_from_alpha(
        api,
        scenario,
        5_000_000,
        rfp_id=requested["id"],
        remittance_reference="INV-9005",
    )
    assert fulfilling["rfp_id"] == requested["id"]
    assert fulfilling["remittance_reference"] == "INV-9005"
    assert fulfilling["direction"] == "OUTBOUND"
    assert fulfilling["rail"] == "INSTANT"
    assert_transfer_dimensions(fulfilling, "INITIATED", "NONE")
    assert fulfilling["fraud_score"] == 57
    assert fulfilling["fraud_reason_codes"] == ["AMOUNT_BAND", "NEW_BENEFICIARY"]
    assert fulfilling["rejection_reason_code"] is None

    rows, meta = list_transfers_with_meta(
        api, {"rfp_id": requested["id"], "limit": 10, "offset": 0}
    )
    assert [row["id"] for row in rows] == [fulfilling["id"]]
    assert_pagination_meta(meta, total_count=1, has_more=False, limit=10, offset=0)

    unchanged = read_rfp(api, requested["id"])
    assert unchanged["status"] == "ACCEPTED"
    assert unchanged["amount_cents"] == 5_000_000
    assert unchanged["amendment_round"] == 0

    account = read_account(api, scenario.alpha.account_id)
    assert account["reserved_cents"] == 5_000_000
    assert account["available_cents"] == 1_195_000_000
    assert account["current_balance_cents"] == 1_200_000_000


def test_the_cycle_read_shows_a_fee_total_and_a_count_nobody_submitted(api):
    """Two 50,000,000-cent settlements produce 50,000 + 50,000 and no rebate.

    PRD 3.10: "Cutoff stamps `cutoff_at`, moves the cycle `OPEN → CUTOFF`, and assesses the
    **intraday liquidity access fee** for every participant whose `enrollment_status` is
    `LIVE`, processing participants in ascending `created_at` order."

    PRD 3.10: "Each such transfer contributes its own fee of ten basis points of its
    `amount_cents` — that is, the amount multiplied by 10 and divided by 10,000 — **rounded
    half up to whole cents for that transfer individually**, and the gross fee is the integer
    sum of those per-transfer figures taken in ascending `created_at` order."

    PRD 3.10: "A volume rebate then applies: when the participant settled at least 10
    transfers on that date, the rebate is one tenth of the gross fee with any fraction
    discarded, and otherwise the rebate is zero."

    PRD 3.6: "Alongside those hops, the debtor customer's `daily_sent_amount_cents` is
    recomputed and rises by the settled amount, and the cycle's `settled_transfer_count` is
    recomputed as the number of outbound transfers in `SETTLED` whose
    `settlement_business_date` equals its `business_date`."

    PRD 3.4: "The *new-beneficiary term* is 12 when the debtor customer account has no other
    outbound transfer in `SETTLED` clearing status to the same `receiver_routing_number`, and 0
    otherwise."

    PRD 3.3: "The account's ledger may be listed in ascending `sequence_no` order and narrowed
    by `entry_type`, by `business_date`, or by `related_transfer_id` to isolate the movements a
    single transfer produced."

    Design: Corner/endpoints/settlement_cycle_read_exposes_computed_fee_total_and_count
    """
    scenario = alpha_scenario(api, account=FEE_ACCOUNT)
    assert scenario.cycle is not None
    assert scenario.cycle["assessed_fee_total_cents"] == 0
    assert scenario.cycle["settled_transfer_count"] == 0

    first = send_from_alpha(api, scenario, 50_000_000)
    assert first["fraud_score"] == 57
    accept_transfer(api, first["id"])
    settle_transfer(api, first["id"])

    second = send_from_alpha(api, scenario, 50_000_000)
    assert second["fraud_score"] == 44
    assert second["fraud_reason_codes"] == ["AMOUNT_BAND"]
    accept_transfer(api, second["id"])
    settle_transfer(api, second["id"])

    for transfer in (first, second):
        settled = read_transfer(api, transfer["id"])
        assert settled["clearing_status"] == "SETTLED"
        assert settled["settlement_business_date"] == "2026-08-03"

    drained = read_account(api, scenario.alpha.account_id)
    assert drained["current_balance_cents"] == 1_100_000_000
    assert drained["alert_tier"] == "GREEN"

    cutoff_cycle(api, scenario.cycle_id)

    cycle = read_cycle(api, scenario.cycle_id, LIQUIDITY_OFFICER)
    assert cycle["status"] == "CUTOFF"
    assert_instant(cycle["cutoff_at"], "2026-08-03T13:00:00Z", "cutoff_at")
    assert cycle["settled_transfer_count"] == 2
    assert cycle["assessed_fee_total_cents"] == 100_000
    assert cycle["closed_at"] is None

    fees, fee_meta = list_ledger_entries_with_meta(
        api,
        scenario.alpha.account_id,
        {"entry_type": "FEE_DEBIT", "business_date": "2026-08-03", "limit": 10, "offset": 0},
        LIQUIDITY_OFFICER,
    )
    assert_pagination_meta(fee_meta, total_count=1, has_more=False, limit=10, offset=0)
    assert_ledger_entry(
        fees[0],
        entry_type="FEE_DEBIT",
        amount_cents=-100_000,
        balance_after_cents=1_099_900_000,
        sequence_no=3,
        business_date="2026-08-03",
    )
    assert fees[0]["related_transfer_id"] is None

    account = read_account(api, scenario.alpha.account_id)
    assert account["current_balance_cents"] == 1_099_900_000
    assert account["reserved_cents"] == 0
    assert account["available_cents"] == 1_099_900_000
    assert account["alert_tier"] == "GREEN"


def test_a_payment_that_was_never_parked_has_no_fallback_claim(api):
    """Diversion belongs to queued payments only; the reservation survives the refusal.

    PRD 3.6: "Attempting any of the three clearing hops from a state for which it is not
    declared — settling a transfer still in `INITIATED`, accepting one already `ACCEPTED`,
    diverting one that was never queued — is refused with `ERR_INVALID_STATE_TRANSITION`, and
    the four states `SETTLED`, `REJECTED`, `DIVERTED` and `EXPIRED` are terminal on the
    clearing dimension."

    PRD 3.9: "While a covering outage is open, a queued transfer may be moved to the alternate
    rail."

    PRD 3.9: "It requires the transfer to be in `QUEUED_THROTTLED`, requires its
    `irrevocable_at` to still be null — an accepted or settled payment can never be diverted,
    and the attempt against a settled one is refused with `ERR_TRANSFER_IRREVOCABLE` — requires
    a `DECLARED` outage event covering the originating participant, and requires the supplied
    rail to equal that event's own `fallback_rail` and not to be `NONE`."

    PRD 3.9: "`DIVERTED` is terminal and non-reserving: the amount stays outside
    `reserved_cents` and the transfer never returns to the instant rail."

    Design: Corner/endpoints/diversion_of_unparked_transfer_rejected
    """
    scenario = alpha_scenario(api)
    assert read_account(api, scenario.alpha.account_id)["alert_tier"] == "GREEN"
    transfer = send_from_alpha(api, scenario, 50_000_000)
    assert_transfer_dimensions(transfer, "INITIATED", "NONE")
    assert transfer["rail"] == "INSTANT"

    response = api.divert_credit_transfer(
        transfer["id"], diversion_payload("FALLBACK_ACH"), PAYMENT_OPERATOR_ALPHA
    )
    validate_error(response, ERR_INVALID_STATE_TRANSITION)

    untouched = read_transfer(api, transfer["id"])
    assert untouched["clearing_status"] == "INITIATED"
    assert untouched["rail"] == "INSTANT"
    assert untouched["queued_at"] is None
    assert read_account(api, scenario.alpha.account_id)["reserved_cents"] == 50_000_000

    set_clock(api, "2026-08-03T13:05:00Z")
    event = declare_outage(api, "2026-08-03T13:05:00Z", participant_id=scenario.alpha.id)
    assert event["status"] == "DECLARED"
    parked = read_transfer(api, transfer["id"])
    assert parked["clearing_status"] == "QUEUED_THROTTLED"
    assert_instant(parked["queued_at"], "2026-08-03T13:05:00Z", "queued_at")
    assert read_account(api, scenario.alpha.account_id)["reserved_cents"] == 0

    set_clock(api, "2026-08-03T13:06:00Z")
    diverted = divert_transfer(api, transfer["id"], "FALLBACK_ACH", PAYMENT_OPERATOR_ALPHA)
    assert diverted["clearing_status"] == "DIVERTED"
    assert diverted["rail"] == "FALLBACK_ACH"

    account = read_account(api, scenario.alpha.account_id)
    assert account["reserved_cents"] == 0
    assert account["current_balance_cents"] == 1_200_000_000
    assert account["available_cents"] == 1_200_000_000
