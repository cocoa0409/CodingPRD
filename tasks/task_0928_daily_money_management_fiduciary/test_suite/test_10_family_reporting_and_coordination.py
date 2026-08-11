"""Family reporting behind the disclosure wall, and care-team coordination."""

from test_helpers import (
    ApiErrorId,
    CARE_1_USER_ID,
    CARE_2_USER_ID,
    CARE_3_USER_ID,
    CARE_4_USER_ID,
    api_client,
    assert_family_report,
    assert_same_instant,
    consent_payload,
    coordination_disposition_payload,
    create_active_authorization,
    create_active_client,
    create_family_report_payload,
    dispose_coordination_request,
    enrol_family_recipient,
    generate_family_report,
    make_care_coordinator_headers,
    make_client_headers,
    make_family_recipient_headers,
    open_and_close_period,
    open_coordination_request,
    read_coordination_request,
    read_family_recipient,
    read_family_report,
    record_consent,
    recipient_version,
    set_clock,
    setup_consented_recipient,
    TEST_USERS,
    validate_error,
    validate_success,
)

MANAGER = TEST_USERS["fiduciary_manager_headers"]


def test_the_provisional_flag_falls_once_the_account_month_is_closed():
    """PRD §3.9: "`is_provisional` tells the family how much to trust the
    figures. It reads false only when the client has at least one account
    **and** every one of those accounts has a reconciliation period for
    `report_month` whose `status` is `CLOSED` or `LOCKED`. In every other case
    — a client with no accounts at all, or any account whose month is still
    open, in review or reopened — it reads true."
    PRD §3.9: "Generating the report raises the recipient's `report_count` by
    one."

    Design: Difficulty/cross_entity_state_dependency/family_report_provisional_flag_tracks_period_status
    """
    world = setup_consented_recipient(permitted_categories=["BILL_PAY", "BALANCES"])
    recipient_id = world["recipient"]["id"]

    first = generate_family_report(recipient_id, "2026-06")
    assert first["is_provisional"] is True

    open_and_close_period(world["account"]["id"], "2026-06")

    second = generate_family_report(recipient_id, "2026-06")

    assert second["is_provisional"] is False
    assert read_family_recipient(recipient_id)["report_count"] == 2


def test_the_report_partitions_the_requested_categories_through_the_disclosure_wall():
    """PRD §3.9: "`included_categories` holds those categories, in that fixed
    order, that appear in the requested set **and** in the recipient's
    `permitted_categories`. `withheld_categories` holds those categories, in
    the same fixed order, that appear in the requested set but not in the
    included set."
    PRD §3.9: "`total_disbursed_cents` is the sum of `amount_cents` over the
    client's payments across all of that client's accounts whose
    `settlement_status` is `SETTLED` and whose `settled_on` falls inside
    `report_month` — but only when `BILL_PAY` made it into
    `included_categories`; otherwise it reads 0."
    PRD §3.9: "`closing_available_balance_cents` is the sum of
    `available_balance_cents` across all of that client's accounts as they
    stand at generation time — but only when `BALANCES` made it into
    `included_categories`; otherwise it reads 0."

    Design: Difficulty/cross_entity_state_dependency/family_report_provisional_flag_tracks_period_status
    """
    world = setup_consented_recipient(permitted_categories=["BILL_PAY", "BALANCES"])
    recipient_id = world["recipient"]["id"]
    generate_family_report(recipient_id, "2026-06")
    open_and_close_period(world["account"]["id"], "2026-06")

    report = generate_family_report(recipient_id, "2026-06")

    assert_family_report(report)
    assert report["included_categories"] == ["BILL_PAY", "BALANCES"]
    assert report["withheld_categories"] == ["BUDGET", "BENEFITS", "FRAUD", "CARE_TEAM"]
    assert report["total_disbursed_cents"] == 0
    assert report["closing_available_balance_cents"] == 5000000


def test_a_client_without_decisional_capacity_cannot_record_consent():
    """PRD §3.9: "when the caller's role is `Client`, that client's
    `capacity_determination` must read `RETAINS_CAPACITY` or the request is
    refused with `ERR_CAPACITY_REQUIRED` at rung 31 — a client with
    `DIMINISHED_CAPACITY`, `LACKS_CAPACITY` or `NOT_DETERMINED` cannot set
    their own disclosure rules, though their fiduciary manager can"
    PRD §3.9: "The role that recorded it is written to
    `consent_recorded_by_role` as either `Client` or `FiduciaryManager`, and
    the current logical instant to `consent_recorded_at`."

    Design: Corner/validations/corner_client_without_decisional_capacity_cannot_record_consent
    """
    set_clock("2026-06-01T09:00:00Z")
    client = create_active_client(
        determination="DIMINISHED_CAPACITY", intake_reference="INT-C053"
    )
    authorization = create_active_authorization(client["id"], scope_tier="FULL_AGENCY")
    recipient = enrol_family_recipient(client["id"], authorization["id"])

    refused = api_client.record_consent(
        recipient["id"], consent_payload(["BILL_PAY"]), make_client_headers(client["id"])
    )
    validate_error(refused, ApiErrorId.ERR_CAPACITY_REQUIRED.value, 403)

    allowed = api_client.record_consent(
        recipient["id"], consent_payload(["BILL_PAY"]), MANAGER
    )
    consented = validate_success(allowed, 200)

    assert consented["subscription_status"] == "ACTIVE"
    assert consented["permitted_categories"] == ["BILL_PAY"]
    assert consented["consent_recorded_by_role"] == "FiduciaryManager"


def test_a_family_recipient_cannot_generate_another_recipients_report():
    """PRD §3.9: "When the caller's role is `FamilyRecipient`, `X-User-ID` must
    equal the `recipient_id` named, or the request is refused with
    `ERR_DISCLOSURE_DENIED`."

    Design: Corner/validations/corner_family_recipient_cannot_generate_another_recipients_report
    """
    set_clock("2026-06-01T09:00:00Z")
    client = create_active_client(intake_reference="INT-C054")
    authorization = create_active_authorization(client["id"], scope_tier="FULL_AGENCY")
    recipient_a = enrol_family_recipient(
        client["id"],
        authorization["id"],
        full_name="Dana Mendel",
        contact_email="dana@example.org",
        relationship="CHILD",
    )
    recipient_b = enrol_family_recipient(
        client["id"],
        authorization["id"],
        full_name="Marek Mendel",
        contact_email="marek@example.org",
        relationship="SIBLING",
    )
    client_headers = make_client_headers(client["id"])
    record_consent(recipient_a["id"], ["BILL_PAY", "BALANCES"], headers=client_headers)
    record_consent(recipient_b["id"], ["BUDGET"], headers=client_headers)

    response = api_client.create_family_report(
        create_family_report_payload(
            recipient_b["id"], "2026-06", recipient_version(recipient_b["id"])
        ),
        make_family_recipient_headers(recipient_a["id"]),
    )

    validate_error(response, ApiErrorId.ERR_DISCLOSURE_DENIED.value, 403)
    assert read_family_recipient(recipient_b["id"])["report_count"] == 0


def test_a_stale_recipient_version_refuses_the_second_report():
    """PRD §2.10: "Generating a family report requires
    `expected_recipient_version`, carrying the client's last observed `version`
    of the `FamilyRecipient` named by `recipient_id`. Generating a second
    report is legitimate — but `permitted_categories` is replaced wholesale by
    every consent call, so a report projected from a stale category set would
    disclose a category the client has just withdrawn. A mismatch is refused
    with `ERR_STALE_VERSION` (412)."

    Design: Corner/cross_cutting_complexity_layers/corner_occ_stale_recipient_version_rejected_on_report_generation
    """
    world = setup_consented_recipient(permitted_categories=["BILL_PAY", "BALANCES"])
    recipient_id = world["recipient"]["id"]
    observed = recipient_version(recipient_id)
    first = generate_family_report(recipient_id, "2026-06", expected_recipient_version=observed)

    response = api_client.create_family_report(
        create_family_report_payload(recipient_id, "2026-06", observed),
        make_family_recipient_headers(recipient_id),
    )

    validate_error(response, ApiErrorId.ERR_STALE_VERSION.value, 412)
    assert read_family_recipient(recipient_id)["report_count"] == 1
    assert read_family_report(first["id"])["is_provisional"] is True


def test_two_declines_reroute_the_request_and_recompute_the_deadline():
    """PRD §3.9: "**`DECLINE`** keeps the request `OPEN` but hands it to
    somebody else. It requires `reassign_to_user_id` to be present and to
    differ from the current `assigned_member_user_id`; a missing or identical
    value is refused with `ERR_VALIDATION`. On success
    `assigned_member_user_id` becomes `reassign_to_user_id`, `reroute_count`
    rises by one, and `ack_due_at` is recomputed from scratch as the current
    logical instant plus the tier's own SLA hours."
    PRD §3.9: "The tier sets the acknowledgement clock: `ack_due_at` is the
    current logical instant plus 2 hours for `URGENT`, plus 48 hours for
    `ROUTINE`, and plus 120 hours for `INFORMATIONAL`."

    Design: Difficulty/non_linear_state_machine/coordination_request_reroute_self_loop_stops_at_cap
    """
    set_clock("2026-06-01T09:00:00Z")
    client = create_active_client(intake_reference="INT-9009")
    request = open_coordination_request(
        client["id"],
        CARE_1_USER_ID,
        tier="ROUTINE",
        headers=make_care_coordinator_headers(CARE_1_USER_ID),
    )

    dispose_coordination_request(
        request["id"],
        "DECLINE",
        headers=make_care_coordinator_headers(CARE_1_USER_ID),
        reassign_to_user_id=CARE_2_USER_ID,
        disposition_note="Out of my catchment area.",
    )
    second = dispose_coordination_request(
        request["id"],
        "DECLINE",
        headers=make_care_coordinator_headers(CARE_2_USER_ID),
        reassign_to_user_id=CARE_3_USER_ID,
        disposition_note="On leave this month.",
    )

    assert second["status"] == "OPEN"
    assert second["reroute_count"] == 2
    assert second["assigned_member_user_id"] == CARE_3_USER_ID
    assert_same_instant(
        second["ack_due_at"], "2026-06-03T09:00:00Z", "CoordinationRequest.ack_due_at"
    )


def test_the_third_decline_is_refused_and_the_request_stays_open():
    """PRD §3.9: "Rerouting is capped at 2: a decline arriving when
    `reroute_count` already reads 2 is refused with `ERR_REROUTE_LIMIT_REACHED`
    at rung 25, and the request must be escalated to case review instead."

    Design: Difficulty/non_linear_state_machine/coordination_request_reroute_self_loop_stops_at_cap
    """
    set_clock("2026-06-01T09:00:00Z")
    client = create_active_client(intake_reference="INT-9009")
    request = open_coordination_request(
        client["id"],
        CARE_1_USER_ID,
        tier="ROUTINE",
        headers=make_care_coordinator_headers(CARE_1_USER_ID),
    )
    dispose_coordination_request(
        request["id"],
        "DECLINE",
        headers=make_care_coordinator_headers(CARE_1_USER_ID),
        reassign_to_user_id=CARE_2_USER_ID,
        disposition_note="Out of my catchment area.",
    )
    dispose_coordination_request(
        request["id"],
        "DECLINE",
        headers=make_care_coordinator_headers(CARE_2_USER_ID),
        reassign_to_user_id=CARE_3_USER_ID,
        disposition_note="On leave this month.",
    )

    response = api_client.dispose_coordination_request(
        request["id"],
        coordination_disposition_payload(
            "DECLINE",
            reassign_to_user_id=CARE_4_USER_ID,
            disposition_note="Caseload full.",
        ),
        make_care_coordinator_headers(CARE_3_USER_ID),
    )

    validate_error(response, ApiErrorId.ERR_REROUTE_LIMIT_REACHED.value, 409)
    after = read_coordination_request(request["id"])
    assert after["status"] == "OPEN"
    assert after["reroute_count"] == 2
    assert after["assigned_member_user_id"] == CARE_3_USER_ID
    assert_same_instant(
        after["ack_due_at"], "2026-06-03T09:00:00Z", "CoordinationRequest.ack_due_at"
    )
