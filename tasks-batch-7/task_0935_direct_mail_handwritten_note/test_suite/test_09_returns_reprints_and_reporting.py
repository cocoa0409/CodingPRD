"""Return-to-sender settlement, reprint allowances and the two campaign reports."""

from test_helpers import (
    ApiErrorId,
    CAMPAIGN_MANAGER,
    EIGHT_RECORD_ROSTER,
    LIST_OPERATOR,
    PRODUCTION_OPERATOR,
    assert_return_event,
    build_addressed_scenario,
    build_returned_record_scenario,
    ledger_rows,
    list_record_version,
    read_account,
    read_campaign,
    read_list_record,
    read_mail_job,
    read_reprint_request,
    request_reprint,
    request_reprint_ok,
    validate_error,
    validate_success,
)


def test_recording_a_return_moves_only_the_mail_status_axis(api):
    """PRD §3.9: "1. **Hop 1** — the recipient record moves `MAILED → RETURNED`,
    and its `version` increments by one."
    PRD §3.3: "A forwarding address moves `move_status` `NONE → MOVE_APPLIED` (or
    `MOVE_NO_FORWARD → MOVE_APPLIED`, if an earlier update had found no forwarding
    address), rewrites `address_line1`, `city`, `state_code`, `zip5` and
    `dpv_confirmation_code` from the supplied values, and then re-derives
    `cass_status` and `deliverability_tier` through the same mapping
    standardization uses."
    PRD §3.3: "Under `EXACT`, records group on `exact_key`. The survivor's
    `dedupe_status` moves `UNSCREENED → UNIQUE` and later members move
    `UNSCREENED → DUP_EXACT`."

    Design: Difficulty/non_linear_state_machine/list_record_four_parallel_axes_evolve_independently
    """
    world = build_returned_record_scenario(
        permit_number="PMT-112", move_applied=True, return_reason="VACANT"
    )

    record = read_list_record(world["record"]["id"])
    assert record["mail_status"] == "RETURNED"
    assert record["cass_status"] == "STANDARDIZED"
    assert record["dedupe_status"] == "UNIQUE"
    assert record["move_status"] == "MOVE_APPLIED"
    assert record["deliverability_tier"] == "AUTOMATION"


def test_a_record_with_an_applied_move_earns_the_reprint_entitlement(api):
    """PRD §3.9: "Entitlement is decided by one fact and one fact only: the
    record's `move_status` at the moment the return is recorded. A record whose
    `move_status` is `MOVE_APPLIED` — someone found a forwarding address for them —
    takes the `REPRINT` entitlement. A record at `NONE` or `MOVE_NO_FORWARD` takes
    the `REFUND` entitlement."
    PRD §3.9: "Under a `REPRINT` entitlement, no ledger row is written at all and
    the account balance is untouched; what the mailer receives instead is the right
    to write and send the piece again, once, as described below."

    Design: Difficulty/non_linear_state_machine/list_record_four_parallel_axes_evolve_independently
    """
    world = build_returned_record_scenario(
        permit_number="PMT-112", move_applied=True, return_reason="VACANT"
    )

    event = world["return_event"]
    assert_return_event(event)
    assert event["entitlement"] == "REPRINT"
    assert event["return_reason"] == "VACANT"
    assert event["mail_job_id"] == world["job"]["id"]

    account = read_account(world["account"]["id"])
    # 500000 seeded less the single 306-cent commit draw; the reprint branch
    # writes no ledger row at all.
    assert account["permit_balance_cents"] == 499_694
    assert account["lifetime_forfeit_cents"] == 0
    assert ledger_rows(account_id=account["id"], entry_type="FORFEIT") == []


def test_a_refund_entitled_marketing_return_forfeits_the_class_fee(api):
    """PRD §3.9: "Under a `REFUND` entitlement, the fee is read from the mailing
    job's class: a `FIRST_CLASS` return costs nothing, because the postal service
    returns first-class mail free, while a `MARKETING_MAIL` return costs 89 cents
    per piece."
    PRD §3.9: "3. **Hop 3** — when the entitlement is a refund settlement and the
    class fee is non-zero, a `FORFEIT` ledger entry for `return_fee_cents` is
    appended and the account's `permit_balance_cents` falls by that amount."

    Design: Difficulty/transitive_cascade/return_event_cascade_forfeit_to_campaign_counters
    """
    world = build_returned_record_scenario(
        permit_number="PMT-121", move_applied=False, return_reason="REFUSED"
    )

    event = world["return_event"]
    assert event["entitlement"] == "REFUND"
    assert event["return_fee_cents"] == 89

    account = read_account(world["account"]["id"])
    # 500000 seeded, less the 306-cent commit draw, less the 89-cent forfeit.
    assert account["permit_balance_cents"] == 499_605
    assert account["lifetime_forfeit_cents"] == 89

    forfeits = ledger_rows(account_id=account["id"], entry_type="FORFEIT")
    assert len(forfeits) == 1
    assert forfeits[0]["amount_cents"] == 89
    assert forfeits[0]["signed_amount_cents"] == -89


def test_the_forfeit_flows_through_to_the_job_and_campaign_counters(api):
    """PRD §3.9: "4. **Hop 4** — the job's `returned_piece_count` rises, which in
    turn refreshes the campaign's `returned_piece_count` and
    `forfeited_postage_cents`."
    PRD §3.9: "`net_postage_cents` is the draws less the refunds plus the forfeits
    — money the campaign genuinely consumed."

    Design: Difficulty/transitive_cascade/return_event_cascade_forfeit_to_campaign_counters
    """
    world = build_returned_record_scenario(
        permit_number="PMT-121", move_applied=False, return_reason="REFUSED"
    )

    assert read_mail_job(world["job"]["id"])["returned_piece_count"] == 1

    campaign = read_campaign(world["campaign"]["id"])
    assert campaign["returned_piece_count"] == 1
    assert campaign["forfeited_postage_cents"] == 89

    report = validate_success(
        api.get_postage_reconciliation(world["campaign"]["id"], CAMPAIGN_MANAGER)
    )
    assert report["draw_cents"] == 306
    assert report["refund_cents"] == 0
    assert report["forfeit_cents"] == 89
    # 306 drawn, nothing refunded, 89 forfeited: 306 - 0 + 89 = 395.
    assert report["net_postage_cents"] == 395


def test_a_refund_entitled_return_cannot_back_a_reprint_request(api):
    """PRD §3.9: "The cited return event must carry the `REPRINT` entitlement;
    citing a refund-entitled return is `ERR_REPRINT_NOT_ENTITLED` (HTTP 409) at
    rung 37."

    Design: Difficulty/cross_entity_state_dependency/reprint_requires_reprint_entitled_return_event
    """
    world = build_returned_record_scenario(
        permit_number="PMT-152", move_applied=False, return_reason="VACANT"
    )
    assert world["return_event"]["entitlement"] == "REFUND"

    response = request_reprint(
        world["record"]["id"], world["return_event"]["id"], world["campaign"]["id"]
    )
    validate_error(response, ApiErrorId.ERR_REPRINT_NOT_ENTITLED.value)


def test_the_refused_reprint_leaves_the_record_returned_and_its_allowance_intact(api):
    """PRD §3.9: "An accepted request is created at `status` `REQUESTED` with
    `deny_reason` null, and the recipient record's `version` increments by one."
    PRD §3.9: "1. **Hop 1** — the recipient record moves `MAILED → RETURNED`, and
    its `version` increments by one."

    Design: Difficulty/cross_entity_state_dependency/reprint_requires_reprint_entitled_return_event
    """
    world = build_returned_record_scenario(
        permit_number="PMT-152", move_applied=False, return_reason="VACANT"
    )

    request_reprint(
        world["record"]["id"], world["return_event"]["id"], world["campaign"]["id"]
    )

    record = read_list_record(world["record"]["id"])
    assert record["mail_status"] == "RETURNED"
    assert record["reprint_count"] == 0

    listed = api.list_reprint_requests(
        LIST_OPERATOR, params={"list_record_id": world["record"]["id"]}
    )
    assert listed.json()["data"] == [], "no reprint request was created"


def test_a_record_may_be_reprinted_once_and_no_more_within_one_campaign(api):
    """PRD §3.9: "Fulfilment requires an open write gate, a request in `REQUESTED`
    at rung 20, a return event still carrying the `REPRINT` entitlement at rung 37,
    and an unused allowance at rung 38: the record's `reprint_count` must be
    strictly below the cap of one reprint per record per campaign, so a record that
    has already been reprinted once is refused with `ERR_REPRINT_CAP_EXCEEDED`
    (HTTP 409)."
    PRD §3.9: "Fulfilment moves the request `REQUESTED → FULFILLED`, moves the
    recipient record `RETURNED → QUEUED` so it will be written and mailed again
    with the job, raises the record's `reprint_count` by one, and increments both
    the record's and the request's `version`."

    Design: Corner/validations/second_reprint_fulfilment_returns_cap_exceeded
    """
    world = build_returned_record_scenario(
        permit_number="PMT-247", move_applied=True, return_reason="MOVED_NO_FORWARD"
    )
    assert world["return_event"]["entitlement"] == "REPRINT"

    first = request_reprint_ok(
        world["record"]["id"], world["return_event"]["id"], world["campaign"]["id"]
    )
    second = request_reprint_ok(
        world["record"]["id"], world["return_event"]["id"], world["campaign"]["id"]
    )

    fulfilled = validate_success(
        api.fulfill_reprint_request(first["id"], PRODUCTION_OPERATOR)
    )
    assert fulfilled["status"] == "FULFILLED"

    record = read_list_record(world["record"]["id"])
    assert record["reprint_count"] == 1
    assert record["mail_status"] == "QUEUED"

    response = api.fulfill_reprint_request(second["id"], PRODUCTION_OPERATOR)
    validate_error(response, ApiErrorId.ERR_REPRINT_CAP_EXCEEDED.value)
    assert read_reprint_request(second["id"])["status"] == "REQUESTED"


def test_a_reprint_request_carrying_a_stale_record_version_is_rejected(api):
    """PRD §2.7: "**Requesting a reprint.** `POST /mail/reprint-requests` requires
    `expected_list_record_version` matching the cited `ListRecord`'s current
    `version`."
    PRD §2.7: "A record can legitimately accumulate further return events and move
    updates that change its entitlement, so the create is not blocked by state
    alone. A mismatch is `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_list_record_version_rejects_reprint_creation
    """
    world = build_returned_record_scenario(
        permit_number="PMT-261", move_applied=True, return_reason="MOVED_NO_FORWARD"
    )
    stale = list_record_version(world["record"]["id"]) - 1

    response = request_reprint(
        world["record"]["id"], world["return_event"]["id"], world["campaign"]["id"], stale
    )
    validate_error(response, ApiErrorId.ERR_STALE_VERSION.value)

    record = read_list_record(world["record"]["id"])
    assert record["reprint_count"] == 0
    assert record["mail_status"] == "RETURNED"
    assert world["return_event"]["entitlement"] == "REPRINT"

    listed = api.list_reprint_requests(
        LIST_OPERATOR, params={"list_record_id": world["record"]["id"]}
    )
    assert listed.json()["data"] == [], "no ReprintRequest row was created"


def test_the_deliverability_report_partitions_the_campaigns_recipients(api):
    """PRD §3.9: "For each `ADDRESSED` job on the campaign, over the records of
    that job's mailing list, it counts `automation_pieces` as records whose tier is
    `AUTOMATION` and whose `dedupe_status` is `UNSCREENED`, `UNIQUE` or
    `HOUSEHOLD_HEAD`; `retail_pieces` as the same count for `RETAIL` tier;
    `unmailable_pieces` as records whose tier is `UNMAILABLE`; and
    `duplicate_pieces` as records whose `dedupe_status` is `DUP_EXACT` or
    `DUP_HOUSEHOLD`."
    PRD §3.9: "Alongside the recipient buckets, `eddm_pieces` is the sum of
    `eddm_piece_count` over the campaign's EDDM jobs — saturation mail contributes
    pieces but no recipient-level detail — and `returned_pieces` is the count of
    return events across all of the campaign's jobs."

    Design: Corner/endpoints/deliverability_report_partitions_campaign_pieces
    """
    world = build_addressed_scenario(
        permit_number="PMT-250", roster=EIGHT_RECORD_ROSTER, list_name="Partition List",
        dedupe_mode="HOUSEHOLD", lock=False, stage="draft",
        target_in_home_date=None, topup_cents=None,
    )

    report = validate_success(
        api.get_deliverability_report(world["campaign"]["id"], CAMPAIGN_MANAGER)
    )

    assert report["automation_pieces"] == 5
    assert report["retail_pieces"] == 1
    assert report["unmailable_pieces"] == 1
    assert report["duplicate_pieces"] == 1
    assert report["record_total"] == 8
    assert report["eddm_pieces"] == 0
    assert report["returned_pieces"] == 0
    assert (
        report["automation_pieces"] + report["retail_pieces"]
        + report["unmailable_pieces"] + report["duplicate_pieces"]
    ) == report["record_total"]
