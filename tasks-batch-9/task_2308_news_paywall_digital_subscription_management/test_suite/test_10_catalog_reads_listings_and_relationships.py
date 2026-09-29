"""Reading rows back: single GETs, paged catalogues, joins and missing parents."""

from test_helpers import (
    NON_EXISTENT_UUID,
    OPS_AGENT_HEADERS,
    REVENUE_MANAGER_HEADERS,
    api_client,
    create_active_institutional_plan,
    create_registered_reader,
    fresh_group_version,
    fresh_plan_version,
    invoice_for_cycle,
    make_group_admin_headers,
    open_subscription,
    read_group,
    read_plan,
    set_clock_date,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import factories as f


def test_single_plan_get_echoes_the_stored_row_including_its_system_fields():
    """The read-back carries the server's own status and version, not a fresh object.

    PRD: "A newly authored plan is born in `status` `DRAFT`, with `active_subscription_count` at 0 and its `price_change_state` at `NONE`."
    PRD: "`version` (integer): an integer that starts at 1 and increments by one on every mutation of that resource, including mutations that only touch derived fields."

    Design: Corner/entities/offer_plan_retrieved_by_id_matches_stored_row
    """
    set_clock_date("2026-09-01")
    created = validate_success(
        api_client.create_offer_plan(
            f.create_offer_plan_payload(name="Digital Read"), REVENUE_MANAGER_HEADERS
        ),
        201,
    )

    plan = validate_success(
        api_client.get_offer_plan(created["id"], OPS_AGENT_HEADERS), 200
    )

    assert plan["id"] == created["id"]
    assert plan["status"] == "DRAFT"
    assert plan["intro_price_cents"] == 499
    assert plan["intro_cycles"] == 1
    assert plan["cycle_days"] == 30
    assert plan["version"] == 1


def test_plan_catalogue_pages_report_the_full_total_and_flip_has_more():
    """Two rows first, one row second, and the total stays three across both pages.

    PRD: "`limit` caps the number of items returned; when omitted it defaults to 10, its minimum accepted value is 1 and its maximum accepted value is 100. `offset` is the number of items to skip; when omitted it defaults to 0. Every list response carries `limit`, `offset`, `total_count` and `has_more` inside the `meta` object of the envelope."
    PRD: "Unless a specific listing states otherwise, list endpoints return their rows sorted by `created_at` ascending."

    Design: Corner/entities/offer_plan_list_paginates_with_total_count_and_has_more
    """
    set_clock_date("2026-09-01")
    ladder = [(499, 1499), (599, 1599), (699, 1699)]
    created = [
        validate_success(
            api_client.create_offer_plan(
                f.create_offer_plan_payload(
                    name=f"List Plan {index}",
                    intro_price_cents=intro,
                    standard_price_cents=standard,
                ),
                REVENUE_MANAGER_HEADERS,
            ),
            201,
        )
        for index, (intro, standard) in enumerate(ladder, start=1)
    ]

    first_rows, first_meta = validate_paginated(
        api_client.list_offer_plans(REVENUE_MANAGER_HEADERS, {"limit": 2, "offset": 0})
    )
    second_rows, second_meta = validate_paginated(
        api_client.list_offer_plans(REVENUE_MANAGER_HEADERS, {"limit": 2, "offset": 2})
    )

    assert len(first_rows) == 2
    assert first_meta["total_count"] == 3
    assert first_meta["has_more"] is True
    assert len(second_rows) == 1
    assert second_meta["total_count"] == 3
    assert second_meta["has_more"] is False
    assert second_rows[0]["id"] == created[2]["id"]
    assert second_rows[0]["name"] == "List Plan 3"


def test_subscription_lookup_on_an_unused_uuid_answers_the_subscription_not_found_code():
    """A well-formed identifier that names nothing is a 404, not an empty success.

    PRD: "**Path existence**, checked left to right (§2.9): the offer plan (`ERR_OFFER_PLAN_NOT_FOUND`), then the paywall rule (`ERR_PAYWALL_RULE_NOT_FOUND`), the article (`ERR_ARTICLE_NOT_FOUND`), the reader (`ERR_READER_NOT_FOUND`), the subscription (`ERR_SUBSCRIPTION_NOT_FOUND`), the invoice (`ERR_INVOICE_NOT_FOUND`), the cancellation request (`ERR_CANCELLATION_REQUEST_NOT_FOUND`), the save offer (`ERR_SAVE_OFFER_NOT_FOUND`), the hold (`ERR_HOLD_NOT_FOUND`), the group account (`ERR_GROUP_ACCOUNT_NOT_FOUND`) and the seat (`ERR_SEAT_NOT_FOUND`), each in that relative order."

    Design: Corner/entities/unknown_subscription_id_returns_not_found
    """
    error = validate_error(
        api_client.get_subscription(NON_EXISTENT_UUID, OPS_AGENT_HEADERS),
        "ERR_SUBSCRIPTION_NOT_FOUND",
        404,
    )

    assert error["error_id"] == "ERR_SUBSCRIPTION_NOT_FOUND"
    assert isinstance(error.get("message"), str)
    assert error["message"] != ""


def test_payment_attempt_history_is_append_only_and_carries_no_version():
    """Two attempts stack up in order, each of them a bare record of a past event.

    PRD: "Two resources are append-only records of something that already happened and therefore carry **only** `id` and `created_at` — both `updated_at` and `version` are absent from a `PaymentAttempt` and from a `ReaderEvent`."
    PRD: "`attempt_no` is the one-based ordinal of this attempt on the invoice: the count of existing attempts on that invoice, counted chronologically by `created_at` ascending, plus one."
    PRD: "`is_final` is true when the `outcome` is `HARD_DECLINE`, and also when the `outcome` is `SOFT_DECLINE` and `attempt_no` is greater than or equal to `max_payment_attempts`."

    Design: Corner/entities/payment_attempt_rows_are_immutable_and_versionless
    """
    set_clock_date("2026-09-01")
    plan = validate_success(
        api_client.create_offer_plan(
            f.create_offer_plan_payload(name="Digital Immutable"),
            REVENUE_MANAGER_HEADERS,
        ),
        201,
    )
    validate_success(
        api_client.activate_offer_plan(plan["id"], REVENUE_MANAGER_HEADERS), 200
    )
    reader = create_registered_reader("immutable@mail.test")
    subscription = open_subscription(reader["id"], plan["id"])
    invoice = invoice_for_cycle(subscription["id"], 1)

    validate_success(
        api_client.create_payment_attempt(
            invoice["id"],
            f.create_payment_attempt_payload("SOFT_DECLINE", 499, "do_not_honor"),
            OPS_AGENT_HEADERS,
        ),
        201,
    )
    set_clock_date("2026-09-04")
    validate_success(
        api_client.create_payment_attempt(
            invoice["id"],
            f.create_payment_attempt_payload("SUCCEEDED", 499),
            OPS_AGENT_HEADERS,
        ),
        201,
    )

    attempts, meta = validate_paginated(
        api_client.list_payment_attempts(invoice["id"], OPS_AGENT_HEADERS)
    )
    assert meta["total_count"] == 2
    assert [row["attempt_no"] for row in attempts] == [1, 2]
    for row in attempts:
        assert "id" in row
        assert "created_at" in row
        assert "version" not in row
        assert "updated_at" not in row
    assert attempts[0]["outcome"] == "SOFT_DECLINE"
    assert attempts[0]["is_final"] is False
    assert attempts[0]["decline_code"] == "do_not_honor"
    assert attempts[1]["outcome"] == "SUCCEEDED"
    assert attempts[1]["is_final"] is False


def test_seat_create_under_a_group_that_does_not_exist_fails_on_the_missing_parent():
    """The path is resolved before the version guard and before capacity accounting.

    PRD: "When a request path names more than one resource identifier, identifiers are resolved strictly left to right and the request fails on the **first** one that matches nothing, with that resource's own 404 code."
    PRD: "**Stale-view guards** (§2.7): first `ERR_STALE_OFFER_PLAN_VERSION`, then `ERR_STALE_GROUP_ACCOUNT_VERSION`."

    Design: Corner/entities/seat_create_under_unknown_group_account_not_found
    """
    set_clock_date("2026-09-01")
    reader = create_registered_reader("orphan@univ.edu")
    plan = create_active_institutional_plan(
        name="Seats Orphan",
        intro_price_cents=5000,
        intro_cycles=1,
        standard_price_cents=5000,
        standard_from_cycle=2,
        cycle_days=30,
        per_seat_price_cents=400,
    )
    real_group = validate_success(
        api_client.create_group_account(
            f.create_group_account_payload(
                plan["id"],
                seat_capacity=2,
                name="Univ Orphan Group",
                admin_email="bursar@univ.edu",
                allowed_email_domain="univ.edu",
            ),
            OPS_AGENT_HEADERS,
        ),
        201,
    )

    response = api_client.create_seat(
        NON_EXISTENT_UUID,
        f.create_seat_payload(
            reader["id"],
            "2026-09-05",
            fresh_group_version(
                real_group["id"], make_group_admin_headers(real_group["id"])
            ),
        ),
        make_group_admin_headers(NON_EXISTENT_UUID),
    )

    error = validate_error(response, "ERR_GROUP_ACCOUNT_NOT_FOUND", 404)
    assert error["error_id"] != "ERR_STALE_GROUP_ACCOUNT_VERSION"
    assert error["error_id"] != "ERR_UNAUTHORIZED"
    rows, meta = validate_paginated(api_client.list_seats(OPS_AGENT_HEADERS))
    assert meta["total_count"] == 0
    assert rows == []
    assert read_group(real_group["id"])["seats_assigned_count"] == 0


def test_one_funding_subscription_is_reachable_from_reader_plan_and_group_alike():
    """The same row answers all three filters because it references all three parents.

    PRD: "Subscription listings accept `reader_id`, `offer_plan_id`, `group_account_id`, `lifecycle_status` and `dunning_status`."
    PRD: "The same request generates the cycle-1 invoice, computes `next_cycle_price_cents` through the forward-looking price variant, recomputes the plan's `active_subscription_count` — the count of subscriptions on that plan whose `lifecycle_status` is `PENDING_ACTIVATION`, `ACTIVE`, `PAUSED` or `CANCEL_SCHEDULED` — and increments the plan's `version`."

    Design: Corner/entities/institutional_subscription_joins_reader_plan_and_group
    """
    set_clock_date("2026-09-01")
    plan = create_active_institutional_plan(
        name="Institution Graph",
        intro_price_cents=5000,
        intro_cycles=0,
        standard_price_cents=5000,
        standard_from_cycle=1,
        cycle_days=30,
        per_seat_price_cents=400,
    )
    admin_reader = create_registered_reader("libadming@univ.edu")
    group = validate_success(
        api_client.create_group_account(
            f.create_group_account_payload(
                plan["id"],
                seat_capacity=2,
                name="Univ Library G",
                admin_email="libadming@univ.edu",
                allowed_email_domain="univ.edu",
            ),
            OPS_AGENT_HEADERS,
        ),
        201,
    )
    subscription = open_subscription(
        admin_reader["id"],
        plan["id"],
        group["id"],
        expected_offer_plan_version=fresh_plan_version(plan["id"]),
    )

    for query in (
        {"group_account_id": group["id"]},
        {"reader_id": admin_reader["id"]},
        {"offer_plan_id": plan["id"]},
    ):
        rows, meta = validate_paginated(
            api_client.list_subscriptions(OPS_AGENT_HEADERS, query)
        )
        assert meta["total_count"] == 1
        assert len(rows) == 1
        assert rows[0]["id"] == subscription["id"]
        assert rows[0]["reader_id"] == admin_reader["id"]
        assert rows[0]["offer_plan_id"] == plan["id"]
        assert rows[0]["group_account_id"] == group["id"]

    assert read_plan(plan["id"])["active_subscription_count"] == 1
