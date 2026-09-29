"""Which resource is blamed first: headers, path ids, body ids, then flow state."""

from test_helpers import (
    OPS_AGENT_HEADERS,
    api_client,
    create_active_plan,
    create_article,
    create_hold,
    create_registered_reader,
    invite_seat,
    invoice_for_cycle,
    make_reader_headers,
    open_subscription,
    read_hold,
    read_reader,
    read_seat,
    read_subscription,
    record_payment,
    run_billing,
    set_clock_date,
    setup_institutional_group,
    validate_error,
    validate_paginated,
)
from test_helpers import factories as f

UNKNOWN_PLAN = "11111111-1111-4111-8111-111111111111"
UNKNOWN_RULE = "22222222-2222-4222-8222-222222222222"
UNKNOWN_ARTICLE = "33333333-3333-4333-8333-333333333333"
UNKNOWN_READER = "44444444-4444-4444-8444-444444444444"
UNKNOWN_INVOICE = "55555555-5555-4555-8555-555555555555"
UNKNOWN_REQUEST = "66666666-6666-4666-8666-666666666666"
UNKNOWN_SAVE_OFFER = "77777777-7777-4777-8777-777777777777"
UNKNOWN_HOLD = "88888888-8888-4888-8888-888888888888"
UNKNOWN_SEAT = "99999999-9999-4999-8999-999999999999"


def test_nine_unknown_path_ids_answer_with_nine_distinct_not_found_codes():
    """Each resource owns its own 404 code; none of them shares a generic one.

    PRD: "**Path existence**, checked left to right (§2.9): the offer plan (`ERR_OFFER_PLAN_NOT_FOUND`), then the paywall rule (`ERR_PAYWALL_RULE_NOT_FOUND`), the article (`ERR_ARTICLE_NOT_FOUND`), the reader (`ERR_READER_NOT_FOUND`), the subscription (`ERR_SUBSCRIPTION_NOT_FOUND`), the invoice (`ERR_INVOICE_NOT_FOUND`), the cancellation request (`ERR_CANCELLATION_REQUEST_NOT_FOUND`), the save offer (`ERR_SAVE_OFFER_NOT_FOUND`), the hold (`ERR_HOLD_NOT_FOUND`), the group account (`ERR_GROUP_ACCOUNT_NOT_FOUND`) and the seat (`ERR_SEAT_NOT_FOUND`), each in that relative order."
    PRD: "When a request path names more than one resource identifier, identifiers are resolved strictly left to right and the request fails on the **first** one that matches nothing, with that resource's own 404 code."

    Design: Corner/errors/unknown_path_ids_return_not_found
    """
    reads = [
        (api_client.get_offer_plan(UNKNOWN_PLAN, OPS_AGENT_HEADERS), "ERR_OFFER_PLAN_NOT_FOUND"),
        (api_client.get_paywall_rule(UNKNOWN_RULE, OPS_AGENT_HEADERS), "ERR_PAYWALL_RULE_NOT_FOUND"),
        (api_client.get_article(UNKNOWN_ARTICLE, OPS_AGENT_HEADERS), "ERR_ARTICLE_NOT_FOUND"),
        (api_client.get_reader(UNKNOWN_READER, OPS_AGENT_HEADERS), "ERR_READER_NOT_FOUND"),
        (api_client.get_invoice(UNKNOWN_INVOICE, OPS_AGENT_HEADERS), "ERR_INVOICE_NOT_FOUND"),
        (
            api_client.get_cancellation_request(UNKNOWN_REQUEST, OPS_AGENT_HEADERS),
            "ERR_CANCELLATION_REQUEST_NOT_FOUND",
        ),
        (api_client.get_save_offer(UNKNOWN_SAVE_OFFER, OPS_AGENT_HEADERS), "ERR_SAVE_OFFER_NOT_FOUND"),
        (api_client.get_hold(UNKNOWN_HOLD, OPS_AGENT_HEADERS), "ERR_HOLD_NOT_FOUND"),
        (api_client.get_seat(UNKNOWN_SEAT, OPS_AGENT_HEADERS), "ERR_SEAT_NOT_FOUND"),
    ]

    seen = []
    for response, expected_error_id in reads:
        error = validate_error(response, expected_error_id, 404)
        seen.append(error["error_id"])
    assert len(set(seen)) == 9


def test_an_unknown_reader_in_the_body_is_blamed_before_an_unknown_article():
    """Body references resolve in the declared order, and both outrank the stale guard.

    PRD: "**Body referential integrity**: a `reader_id` in the body must reference an existing reader (`ERR_READER_NOT_FOUND`); an `offer_plan_id` in the body must reference an existing plan (`ERR_OFFER_PLAN_NOT_FOUND`); an `article_id` must reference an existing article and a supplied `group_account_id` must reference an existing group account (`ERR_ARTICLE_NOT_FOUND`)."
    PRD: "The same left-to-right discipline governs body references: a path identifier is always resolved before a body identifier, and within the body, references are resolved in the order given in §2.8 step 6."

    Design: Corner/errors/unknown_body_foreign_keys_return_not_found
    """
    set_clock_date("2026-09-01")
    plan = create_active_plan(name="Digital FK")
    reader = create_registered_reader("fk@mail.test")
    create_article(
        headline="FK Article",
        section="politics",
        content_type="NEWS",
        access_class="METERED",
    )

    both_unknown = api_client.create_access_decision(
        f.access_decision_payload(UNKNOWN_READER, UNKNOWN_ARTICLE), OPS_AGENT_HEADERS
    )
    article_unknown = api_client.create_access_decision(
        f.access_decision_payload(reader["id"], UNKNOWN_ARTICLE), OPS_AGENT_HEADERS
    )
    plan_unknown = api_client.create_subscription(
        f.create_subscription_payload(reader["id"], UNKNOWN_PLAN, plan["version"]),
        OPS_AGENT_HEADERS,
    )

    validate_error(both_unknown, "ERR_READER_NOT_FOUND", 404)
    validate_error(article_unknown, "ERR_ARTICLE_NOT_FOUND", 404)
    stale_free = validate_error(plan_unknown, "ERR_OFFER_PLAN_NOT_FOUND", 404)
    assert stale_free["error_id"] != "ERR_STALE_OFFER_PLAN_VERSION"
    _, subscription_meta = validate_paginated(
        api_client.list_subscriptions(OPS_AGENT_HEADERS)
    )
    assert subscription_meta["total_count"] == 0
    _, event_meta = validate_paginated(api_client.list_reader_events(OPS_AGENT_HEADERS))
    assert event_meta["total_count"] == 0


def test_a_headerless_request_is_refused_before_the_unknown_id_is_ever_looked_up():
    """Rule one of the ladder answers 401, so the 404 that would follow never happens.

    PRD: "If either header is absent, or if `X-User-Role` carries any string that is not one of those five, the request is refused with `ERR_MISSING_AUTH_HEADERS` (HTTP 401)."
    PRD: "When more than one rule could reject a request, the rejection reported is always the one from the earliest rule in the following ladder."

    Design: Corner/errors/request_without_auth_headers_returns_401
    """
    response = api_client.get_offer_plan(
        "dddddddd-dddd-4ddd-8ddd-dddddddddddd", {}
    )

    error = validate_error(response, "ERR_MISSING_AUTH_HEADERS", 401)
    assert error["error_id"] != "ERR_OFFER_PLAN_NOT_FOUND"
    assert error["error_id"] != "ERR_UNAUTHORIZED"


def test_a_paused_subscription_is_not_terminal_but_still_cannot_be_cancelled():
    """The pause pass left it PAUSED, which is neither ACTIVE nor an ending.

    PRD: "The subscription must be `ACTIVE`: a terminal one answers `ERR_SUBSCRIPTION_TERMINAL` and a merely non-active one answers `ERR_SUBSCRIPTION_NOT_ACTIVE`."
    PRD: "A `PAUSE_BILLING` hold reaching its start date moves the hold to `ACTIVE` and drives the lifecycle dimension `ACTIVE → PAUSED`, then recomputes the reader's `entitlement_source` — and because `PAUSED` is not an entitling status, a reader with no seat drops to `NONE` and is metered again."

    Design: Corner/errors/cancellation_request_on_paused_subscription_rejected
    """
    set_clock_date("2026-09-01")
    plan = create_active_plan(name="Digital Paused")
    reader = create_registered_reader("paused@mail.test")
    reader_headers = make_reader_headers(reader["id"])
    subscription = open_subscription(reader["id"], plan["id"])
    record_payment(invoice_for_cycle(subscription["id"], 1), "SUCCEEDED", 499)
    hold = create_hold(
        subscription["id"], "PAUSE_BILLING", "2026-09-06", "2026-09-12", reader_headers
    )
    set_clock_date("2026-09-06")
    run_billing("HOLDS_ONLY")
    assert read_subscription(subscription["id"])["lifecycle_status"] == "PAUSED"

    response = api_client.create_cancellation_request(
        subscription["id"], {"reason_code": "OTHER"}, reader_headers
    )

    error = validate_error(response, "ERR_SUBSCRIPTION_NOT_ACTIVE", 409)
    assert error["error_id"] != "ERR_SUBSCRIPTION_TERMINAL"
    assert read_subscription(subscription["id"])["lifecycle_status"] == "PAUSED"
    assert read_hold(hold["id"])["status"] == "ACTIVE"
    assert read_reader(reader["id"])["entitlement_source"] == "NONE"
    _, meta = validate_paginated(
        api_client.list_cancellation_requests(subscription["id"], OPS_AGENT_HEADERS)
    )
    assert meta["total_count"] == 0


def test_a_fortnight_old_invitation_can_no_longer_be_claimed_even_though_it_is_invited():
    """No EXPIRY pass has run, so the row is still INVITED and the date rule must bite.

    PRD: "**Claiming a seat** is the `Reader`'s exclusive act and is where institutional authentication happens. The seat must still be `INVITED`, otherwise `ERR_SEAT_NOT_INVITED`; the clock date must be on or before `invite_expires_on`, otherwise `ERR_SEAT_INVITE_EXPIRED`; the reader's `email` must end with an at-sign followed by the group's `allowed_email_domain`, otherwise `ERR_SEAT_DOMAIN_MISMATCH` (HTTP 422); and the group's funding subscription must still be `ACTIVE` with a `dunning_status` other than `FAILED_FINAL`, otherwise `ERR_GROUP_SUBSCRIPTION_NOT_ACTIVE`."
    PRD: "Invitations nobody claims lapse on their own: the EXPIRY pass of a run moves a seat whose `status` is `INVITED` and whose `invite_expires_on` is strictly behind the clock date to `EXPIRED`, recomputes the group's two counters, and reports the seat in `seats_expired`."

    Design: Corner/errors/expired_seat_invite_claim_rejected
    """
    scenario = setup_institutional_group(
        seat_capacity=2,
        group_name="Campus Expiry Group",
        allowed_email_domain="campus.test",
        funding_reader_email="bursar5@campus.test",
        clock_date="2026-09-01",
        name="Campus Expiry",
        per_seat_price_cents=400,
    )
    student = create_registered_reader("student5@campus.test")
    seat = invite_seat(
        scenario["group"]["id"],
        student["id"],
        "2026-09-02",
        admin_headers=scenario["group_headers"],
    )
    assert seat["status"] == "INVITED"
    assert seat["invite_expires_on"] == "2026-09-15"
    set_clock_date("2026-09-16")

    response = api_client.activate_seat(seat["id"], make_reader_headers(student["id"]))

    error = validate_error(response, "ERR_SEAT_INVITE_EXPIRED", 409)
    assert error["error_id"] != "ERR_SEAT_NOT_INVITED"
    assert error["error_id"] != "ERR_SEAT_DOMAIN_MISMATCH"
    unclaimed = read_seat(seat["id"])
    assert unclaimed["status"] == "INVITED"
    assert unclaimed["claimed_on"] is None
    assert read_reader(student["id"])["entitlement_source"] == "NONE"
