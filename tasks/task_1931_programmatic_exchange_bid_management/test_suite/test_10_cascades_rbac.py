"""Publisher suspension/resume cascades and role-based access control."""
from test_helpers import (
    ApiErrorId,
    approve_batch,
    create_batch,
    create_blocklist_entry_payload,
    create_package_for,
    create_publisher,
    fill_auction,
    get_deal,
    get_package,
    get_publisher,
    make_exchange_admin_headers,
    make_finance_officer_headers,
    make_publisher_manager_headers,
    setup_active_deal,
    submit_batch,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

ADMIN = TEST_USERS["exchange_admin_headers"]
DEMAND = TEST_USERS["demand_side_headers"]
FINANCE = TEST_USERS["finance_officer_headers"]


class TestPublisherSuspensionCascade:
    def test_suspend_pauses_packages_then_deals(self, api):
        """PRD §3.1: "When an `ExchangeAdmin` suspends an `ACTIVE` publisher, its
        `status` becomes `SUSPENDED` ... The suspension then cascades: every
        package of that publisher currently `ACTIVE` moves to `PAUSED` with its
        `version` incremented, and every deal on those packages currently
        `ACTIVE` moves to `PAUSED` with its own `version` incremented."

        Design: Difficulty/transitive_cascade/publisher_suspension_cascades_package_then_deal
        """
        sc = setup_active_deal()
        pkg_before = get_package(sc["pkg"]["id"])
        deal_before = get_deal(sc["deal"]["id"])

        suspended = validate_success(api.suspend_publisher(sc["pub"]["id"], ADMIN))
        assert suspended["status"] == "SUSPENDED", "Hop 1: the publisher itself"

        pkg_after = get_package(sc["pkg"]["id"])
        assert pkg_after["status"] == "PAUSED", "Hop 2: the package pauses"
        assert pkg_after["version"] == pkg_before["version"] + 1, (
            "The cascade increments the package version exactly once")

    def test_suspend_cascade_reaches_deal_with_single_version_bump(self, api):
        """PRD §2.10: "Suspending a publisher pauses its active packages and,
        one hop further, pauses every active deal on those packages; each
        cascaded mutation refreshes `updated_at` and increments the affected
        resource's `version`."

        Design: Difficulty/transitive_cascade/publisher_suspension_cascades_package_then_deal
        """
        sc = setup_active_deal()
        deal_before = get_deal(sc["deal"]["id"])
        validate_success(api.suspend_publisher(sc["pub"]["id"], ADMIN))

        deal_after = get_deal(sc["deal"]["id"])
        assert deal_after["status"] == "PAUSED", (
            "Hop 3: the deal pauses because its package paused")
        assert deal_after["version"] == deal_before["version"] + 1, (
            "The cascade increments the deal version exactly once")

    def test_publisher_resume_does_not_resume_deals(self, api):
        """PRD §3.1: "Resuming a `SUSPENDED` publisher returns it to `ACTIVE`
        and flips each of its `PAUSED` packages back to `ACTIVE`, recomputing
        their floors against the current date — but, deliberately, deals are not
        resumed by the cascade; each deal remains `PAUSED` until its owning
        manager resumes it individually."

        Design: Corner/state_machines/publisher_resume_does_not_resume_deals
        """
        sc = setup_active_deal()
        validate_success(api.suspend_publisher(sc["pub"]["id"], ADMIN))
        assert get_deal(sc["deal"]["id"])["status"] == "PAUSED"

        resumed = validate_success(api.resume_publisher(sc["pub"]["id"], ADMIN))
        assert resumed["status"] == "ACTIVE"
        assert get_package(sc["pkg"]["id"])["status"] == "ACTIVE", (
            "The resume cascade restores packages")
        assert get_deal(sc["deal"]["id"])["status"] == "PAUSED", (
            "The resume cascade deliberately stops at packages")


class TestRoleEnforcement:
    def test_publisher_manager_cannot_touch_other_publishers_package(self, api):
        """PRD §2.1: "a `PublisherManager` may only mutate resources whose
        owning publisher id equals their own."
        PRD §2.8: "Ownership for entity-backed roles is enforced at this same
        stage: a `PublisherManager` mutating a resource owned by a different
        publisher is rejected with `ERR_UNAUTHORIZED`."

        Design: Corner/rbac/publisher_manager_cannot_touch_other_publishers_package
        """
        pub_a = create_publisher("A", "a.com")
        pub_b = create_publisher("B", "b.com")
        pkg_a = create_package_for(pub_a["id"], name="PkgA")
        resp = api.pause_package(pkg_a["id"],
                                 make_publisher_manager_headers(pub_b["id"]))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
        assert get_package(pkg_a["id"])["status"] == "ACTIVE", (
            "The foreign manager's attempt changes nothing")

    def test_finance_officer_cannot_approve_batch_role_denied(self, api):
        """PRD §2.1: "A request whose role is not permitted for the target
        endpoint — or whose entity-backed ownership check fails — is rejected
        with `ERR_UNAUTHORIZED`."
        PRD §3.8: "An `ExchangeAdmin` approves a batch in `PENDING_APPROVAL` —
        any other state draws `ERR_BATCH_NOT_PENDING_APPROVAL`" (approval is an
        ExchangeAdmin operation; a FinanceOfficer caller is role-denied).

        Design: Corner/rbac/finance_officer_cannot_approve_batch_role_denied
        """
        batch = create_batch()
        submit_batch(batch["id"])
        resp = api.approve_payout_batch(
            batch["id"], make_finance_officer_headers("fin-9"))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
        after = validate_success(api.get_payout_batch(batch["id"], ADMIN))
        assert after["status"] == "PENDING_APPROVAL", (
            "Role denial fires before any state or segregation check")

    def test_demand_side_cannot_void_auction_record(self, api):
        """PRD §3.6: "Voiding is the fraud-correction path, reserved to
        `ExchangeAdmin`."
        PRD §2.1: "A request whose role is not permitted for the target endpoint
        ... is rejected with `ERR_UNAUTHORIZED`."

        Design: Corner/rbac/demand_side_cannot_void_auction_record
        """
        sc = setup_active_deal()
        record = fill_auction(sc["pub"]["id"])
        resp = api.void_auction_record(record["id"], DEMAND)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
        after = validate_success(api.get_auction_record(record["id"], ADMIN))
        assert after["voided"] is False

    def test_batch_creator_cannot_approve_own_batch(self, api):
        """PRD §3.8: "the approver's `X-User-ID` must differ from the batch's
        `created_by_user_id`; the person who built the batch may not approve it,
        and a violation is rejected with `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/rbac/batch_creator_cannot_approve_own_batch
        """
        batch = create_batch(creator="fin-1")
        submit_batch(batch["id"], creator="fin-1")

        resp = api.approve_payout_batch(
            batch["id"], make_exchange_admin_headers("fin-1"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        assert validate_success(
            api.get_payout_batch(batch["id"], ADMIN))["status"] == "PENDING_APPROVAL"

        approved = validate_success(api.approve_payout_batch(
            batch["id"], make_exchange_admin_headers("admin-2")))
        assert approved["status"] == "APPROVED", (
            "A different operator approves successfully")

    def test_publisher_manager_cannot_create_exchange_scope_blocklist(self, api):
        """PRD §3.4: "An `ExchangeAdmin` may create entries of any scope; a
        `PublisherManager` may create `PUBLISHER`-scoped entries only against
        their own publisher and `DEAL`-scoped entries only against their own
        deals."
        PRD §2.1: "A request whose role is not permitted for the target endpoint
        — or whose entity-backed ownership check fails — is rejected with
        `ERR_UNAUTHORIZED`."

        Design: Corner/rbac/publisher_manager_cannot_create_exchange_scope_blocklist
        """
        pub = create_publisher()
        resp = api.create_blocklist_entry(
            create_blocklist_entry_payload("EXCHANGE", "ADVERTISER_DOMAIN",
                                           "evil.com"),
            make_publisher_manager_headers(pub["id"]))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
