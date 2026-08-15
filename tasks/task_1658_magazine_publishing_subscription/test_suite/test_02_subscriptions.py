"""Subscription creation guards, list filtering, and the cross-entity
activation dependency on Publication status."""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    TEST_USERS,
    assert_subscription,
    create_publication,
    create_issue,
    create_subscriber,
    create_subscription,
    create_active_subscription,
    activate_subscription,
    set_clock,
    PD,
    PM,
    CM,
)

PD_H = TEST_USERS["publishing_director_headers"]
CM_H = TEST_USERS["circulation_manager_headers"]


class TestSubscriptionCreation:
    def test_paid_subscription_with_zero_price_rejected(self, api):
        """A PAID subscription created with price_paid_cents of zero is
        rejected with ERR_PAID_REQUIRES_PAYMENT already at creation.

        PRD §3.2: "Tier-and-payment consistency is enforced already at creation — a `PAID` subscription created with a `price_paid_cents` of zero or a `payment_method` of `NONE` is rejected with `ERR_PAID_REQUIRES_PAYMENT`, and a `CONTROLLED` subscription created with a nonzero price is rejected with `ERR_CONTROLLED_MUST_BE_FREE` — and the same rules guard activation, as described below."

        Design: Corner/validations/paid_subscription_with_zero_price_rejected
        """
        set_clock()
        pub = create_publication()
        issue = create_issue(pub["id"])
        subscriber = create_subscriber()
        resp = api.create_subscription(
            pub["id"],
            subscriber["id"],
            {
                "start_issue_id": issue["id"],
                "term_issues": 12,
                "price_paid_cents": 0,
                "qualification_tier": "PAID",
                "payment_method": "CARD",
            },
            CM_H,
        )
        validate_error(resp, ApiErrorId.ERR_PAID_REQUIRES_PAYMENT, 422)

    def test_list_subscriptions_filtered_by_status(self, api):
        """The publication's subscription list honors the status filter.

        PRD §4: "List endpoints accept the pagination parameters `limit` and `offset`; individual lists additionally accept filter parameters drawn from `status`, `subscriber_id`, `publication_id`, `issue_id`, `qualification_tier`, `circulation_class`, `is_deliverable`, `response`, `access_level`, `is_controlled_copy`, `entry_type`, and `variant`, as narrated in §3."

        Design: Corner/endpoints/get_subscriptions_filtered_by_status
        """
        set_clock()
        pub = create_publication()
        issue = create_issue(pub["id"])
        subscriber_a = create_subscriber()
        subscriber_b = create_subscriber()
        active_sub = create_active_subscription(pub["id"], subscriber_a["id"], issue["id"])
        pending_sub = create_subscription(pub["id"], subscriber_b["id"], issue["id"])
        assert pending_sub["status"] == "PENDING_START"

        resp = api.list_subscriptions(pub["id"], CM_H, params={"status": "ACTIVE"})
        data, meta = validate_paginated(resp)
        assert len(data) == 1, f"expected exactly the ACTIVE subscription, got {len(data)} rows"
        assert data[0]["id"] == active_sub["id"]
        assert data[0]["status"] == "ACTIVE"


class TestActivationDependsOnPublicationActive:
    def test_activate_rejected_when_publication_suspended(self, api):
        """Activation requires the publication to be ACTIVE; a SUSPENDED
        publication blocks activation with ERR_PUBLICATION_NOT_ACTIVE.

        PRD §3.2: "A `CirculationManager` activates a `PENDING_START` subscription, moving it to `ACTIVE`, under four guards evaluated against the publication, the tier, and the address: the publication must be `ACTIVE`, else `ERR_PUBLICATION_NOT_ACTIVE`; a `PAID` tier requires a positive `price_paid_cents` and a `payment_method` other than `NONE`, else `ERR_PAID_REQUIRES_PAYMENT`; a `CONTROLLED` tier requires `price_paid_cents` of exactly zero, else `ERR_CONTROLLED_MUST_BE_FREE`; and the subscriber must be deliverable, else `ERR_UNDELIVERABLE_ADDRESS`."

        Design: Difficulty/cross_entity_state_dependency/subscription_activate_depends_on_publication_active
        """
        set_clock()
        pub = create_publication()
        issue = create_issue(pub["id"])
        subscriber = create_subscriber()
        sub = create_subscription(pub["id"], subscriber["id"], issue["id"])
        assert sub["status"] == "PENDING_START"

        # Publication has only a PLANNING issue, so suspension is permitted.
        validate_success(api.suspend_publication(pub["id"], PD_H))

        resp = api.activate_subscription(pub["id"], sub["id"], CM_H)
        validate_error(resp, ApiErrorId.ERR_PUBLICATION_NOT_ACTIVE, 409)

    def test_activate_succeeds_after_publication_resumed(self, api):
        """Resuming the publication lifts the activation block: the same
        subscription then activates and its first term is created.

        PRD §3.8: "Resuming returns the publication from `SUSPENDED` to `ACTIVE`, brings its suspended subscriptions back to `ACTIVE`, and recomputes each subscription's `issues_remaining` with no credit for the suspended period."
        PRD §3.2: "A `CirculationManager` activates a `PENDING_START` subscription, moving it to `ACTIVE`, under four guards evaluated against the publication, the tier, and the address: the publication must be `ACTIVE`, else `ERR_PUBLICATION_NOT_ACTIVE`; a `PAID` tier requires a positive `price_paid_cents` and a `payment_method` other than `NONE`, else `ERR_PAID_REQUIRES_PAYMENT`; a `CONTROLLED` tier requires `price_paid_cents` of exactly zero, else `ERR_CONTROLLED_MUST_BE_FREE`; and the subscriber must be deliverable, else `ERR_UNDELIVERABLE_ADDRESS`."

        Design: Difficulty/cross_entity_state_dependency/subscription_activate_depends_on_publication_active
        """
        set_clock()
        pub = create_publication()
        issue = create_issue(pub["id"])
        subscriber = create_subscriber()
        sub = create_subscription(pub["id"], subscriber["id"], issue["id"])

        validate_success(api.suspend_publication(pub["id"], PD_H))
        resumed = validate_success(api.resume_publication(pub["id"], PD_H))
        assert resumed["status"] == "ACTIVE"

        activated = validate_success(api.activate_subscription(pub["id"], sub["id"], CM_H))
        assert_subscription(activated)
        assert activated["status"] == "ACTIVE", (
            f"activation must succeed once the publication is ACTIVE again, got {activated['status']}"
        )
