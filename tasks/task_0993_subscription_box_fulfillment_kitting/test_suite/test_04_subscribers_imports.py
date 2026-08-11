"""Subscriber imports, pause/resume/churn lifecycle, batch listing, and
immediate read-after-write visibility.

Covers PRD §2.3 (pagination), §3.3 (imports and subscriber lifecycle).
"""
from test_helpers import (
    ApiErrorId,
    api_client,
    assert_subscriber,
    churn_payload,
    create_client,
    create_plan,
    import_batch_payload,
    import_named_subscribers,
    import_subscribers,
    make_client_ops_headers,
    set_clock,
    subscriber_row,
    validate_error,
    validate_paginated,
    validate_success,
    TEST_USERS,
)

WAREHOUSE = TEST_USERS["warehouse_ops_headers"]
SUPPORT = TEST_USERS["customer_service_headers"]


class TestSubscriberLifecycle:
    def test_subscriber_pause_resume_cycle_restores_active(self):
        """PRD §3.3: "Within a plan, a subscriber moves `ACTIVE → PAUSED` on
        pause and `PAUSED → ACTIVE` on resume; each transition increments the
        subscriber's `version` by one."

        Design: Corner/state_machines/subscriber_pause_resume_cycle_restores_active
        """
        set_clock()
        client = create_client(name="SM1 Client", billing_email="sm1@acme.test")
        headers = make_client_ops_headers(client["id"])
        plan = create_plan(client["id"], "PL-SM1", name="SM1 Box",
                           shipping_weight_grams=500)
        subscribers = import_named_subscribers(plan["id"], client["id"],
                                               [("sm1@x.test", 4)])
        subscriber = subscribers[0]
        assert subscriber["status"] == "ACTIVE"
        v0 = subscriber["version"]

        paused = validate_success(api_client.pause_subscriber(subscriber["id"], headers))
        assert_subscriber(paused)
        assert paused["status"] == "PAUSED"
        assert paused["version"] == v0 + 1, \
            f"pause must bump version by one: {v0} -> {paused['version']}"

        resumed = validate_success(api_client.resume_subscriber(subscriber["id"], headers))
        assert resumed["status"] == "ACTIVE"
        assert resumed["version"] == v0 + 2, \
            f"resume must bump version by one again: {v0} -> {resumed['version']}"

    def test_churned_subscriber_cannot_pause_returns_invalid_state(self):
        """PRD §3.3: "Churn — `ACTIVE → CHURNED` or `PAUSED → CHURNED` — is
        terminal: the operator must supply a `reason`, recorded into
        `churn_reason` as one of `PRICE`, `PRODUCT`, `MOVED`, or `OTHER`".
        PRD §2.9: "The generic wrong-state rejection is `ERR_INVALID_STATE`
        (HTTP 409)".

        Design: Corner/state_machines/churned_subscriber_cannot_pause_returns_invalid_state
        """
        set_clock()
        client = create_client(name="SM2 Client", billing_email="sm2@acme.test")
        headers = make_client_ops_headers(client["id"])
        plan = create_plan(client["id"], "PL-SM2", name="SM2 Box",
                           shipping_weight_grams=500)
        subscriber = import_named_subscribers(plan["id"], client["id"],
                                              [("sm2@x.test", 4)])[0]
        churned = validate_success(
            api_client.churn_subscriber(subscriber["id"], churn_payload("PRICE"),
                                        headers))
        assert churned["status"] == "CHURNED"

        resp = api_client.pause_subscriber(subscriber["id"], headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        after = validate_success(api_client.get_subscriber(subscriber["id"], headers))
        assert after["status"] == "CHURNED", "terminal CHURNED must not mutate"
        assert after["churn_reason"] == "PRICE"
        assert after["version"] == churned["version"], \
            "a rejected transition must not bump the subscriber version"


class TestImportBatches:
    def test_import_batch_double_commit_rejected(self):
        """PRD §3.3: "Committing an already-committed batch is rejected with
        `ERR_IMPORT_ALREADY_COMMITTED`; reading a batch back shows the frozen
        counts." PRD §3.3: "Four kinds of rows are skipped instead: a malformed
        email, a zone outside the 1-to-8 range, a duplicate email within the
        same file, or an email that is already `CHURNED` on this plan."

        Design: Corner/state_machines/import_batch_double_commit_rejected
        """
        set_clock()
        client = create_client(name="SM5 Client", billing_email="sm5@acme.test")
        headers = make_client_ops_headers(client["id"])
        plan = create_plan(client["id"], "PL-SM5", name="SM5 Box",
                           shipping_weight_grams=500)
        batch = validate_success(
            api_client.create_import_batch(
                plan["id"],
                import_batch_payload([
                    subscriber_row("sm5a@x.test", 2),
                    subscriber_row("sm5b@x.test", 2),
                    subscriber_row("sm5bad@x.test", 9),
                ]),
                headers),
            expected_status=201)
        committed = validate_success(api_client.commit_import_batch(batch["id"], headers))
        assert committed["status"] == "COMMITTED"
        assert committed["accepted_count"] == 2, \
            f"two valid rows must be accepted, got {committed['accepted_count']}"
        assert committed["rejected_count"] == 1, \
            f"the zone-9 row must be skipped, got {committed['rejected_count']}"

        resp = api_client.commit_import_batch(batch["id"], headers)
        validate_error(resp, ApiErrorId.ERR_IMPORT_ALREADY_COMMITTED)

        reread = validate_success(api_client.get_import_batch(batch["id"], headers))
        assert reread["accepted_count"] == 2 and reread["rejected_count"] == 1, \
            "counts stay frozen at their first-commit values"
        sub_resp = api_client.list_subscribers(headers,
                                               params={"plan_id": plan["id"]})
        subscribers, meta = validate_paginated(sub_resp)
        assert meta["total_count"] == 2, \
            f"no duplicate subscribers may be created, got {meta['total_count']}"

    def test_import_batch_list_pagination_envelope(self):
        """PRD §2.3: "The `limit` parameter caps how many items one page
        returns; it defaults to 10, with a minimum of 1 and a maximum of 100.
        The `offset` parameter says how many items to skip before the page
        begins and defaults to 0." PRD §2.3: "Paginated list responses carry
        `limit`, `offset`, `total_count`, and `has_more` in the envelope's
        `meta` object." PRD §3.3: "The batch is born `UPLOADED`, bound to the
        plan from the path as its `plan_id`, with its `total_rows` fixed at
        upload time as the number of rows submitted".

        Design: Corner/entities/import_batch_list_pagination_envelope
        """
        set_clock()
        client = create_client(name="PG Client", billing_email="pg@acme.test")
        headers = make_client_ops_headers(client["id"])
        plan = create_plan(client["id"], "PL-PG", name="PG Box",
                           shipping_weight_grams=500)
        for email in ("pg1@x.test", "pg2@x.test"):
            validate_success(
                api_client.create_import_batch(
                    plan["id"], import_batch_payload([subscriber_row(email, 1)]),
                    headers),
                expected_status=201)

        resp = api_client.list_import_batches(plan["id"], headers)
        batches, meta = validate_paginated(resp)
        assert meta["limit"] == 10, f"default limit must be 10, got {meta['limit']}"
        assert meta["offset"] == 0, f"default offset must be 0, got {meta['offset']}"
        assert meta["total_count"] == 2
        assert meta["has_more"] is False
        assert len(batches) == 2
        for batch in batches:
            assert batch["status"] == "UPLOADED"
            assert batch["total_rows"] == 1


class TestImmediateConsistency:
    def test_immediate_visibility_after_pause(self):
        """PRD §2.2: "Unless otherwise noted, operations that create or modify
        a resource will return the created or updated resource object in the
        data field." PRD §3.3: "Within a plan, a subscriber moves
        `ACTIVE → PAUSED` on pause and `PAUSED → ACTIVE` on resume; each
        transition increments the subscriber's `version` by one."

        Design: Corner/consistency_model/immediate_visibility_after_pause
        """
        set_clock()
        client = create_client(name="Y1 Client", billing_email="y1@acme.test")
        headers = make_client_ops_headers(client["id"])
        plan = create_plan(client["id"], "PL-Y1", name="Y1 Box",
                           shipping_weight_grams=500)
        subscriber = import_named_subscribers(plan["id"], client["id"],
                                              [("y1@x.test", 2)])[0]

        paused = validate_success(api_client.pause_subscriber(subscriber["id"], headers))
        assert paused["status"] == "PAUSED"

        fetched = validate_success(api_client.get_subscriber(subscriber["id"], WAREHOUSE))
        assert fetched["status"] == "PAUSED", \
            "a follow-up read by another role must see the pause immediately"
        assert fetched["version"] == paused["version"], \
            "the follow-up read must show the bumped version"


class TestImportRbac:
    def test_customer_service_cannot_commit_import(self):
        """PRD §4: POST /import-batches/{id}/commit is authorized for
        "ClientOps" only. PRD §2.1: "an authenticated caller whose role is not
        admitted, or who violates the ownership rule below, is rejected with
        `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/customer_service_cannot_commit_import
        """
        set_clock()
        client = create_client(name="RB4 Client", billing_email="rb4@acme.test")
        headers = make_client_ops_headers(client["id"])
        plan = create_plan(client["id"], "PL-RB4", name="RB4 Box",
                           shipping_weight_grams=500)
        batch = validate_success(
            api_client.create_import_batch(
                plan["id"], import_batch_payload([subscriber_row("rb4@x.test", 2)]),
                headers),
            expected_status=201)

        resp = api_client.commit_import_batch(batch["id"], SUPPORT)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

        after = validate_success(api_client.get_import_batch(batch["id"], headers))
        assert after["status"] == "UPLOADED", \
            "a forbidden commit must leave the batch UPLOADED"
