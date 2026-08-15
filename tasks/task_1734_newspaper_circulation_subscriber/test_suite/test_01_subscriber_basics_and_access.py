"""Subscriber/plan creation defaults, envelope rules, auth and RBAC."""
from test_helpers import (
    DIRECTOR,
    MGR,
    NO_AUTH_HEADERS,
    NON_EXISTENT_UUID,
    REP,
    ApiErrorId,
    assert_subscriber,
    create_plan,
    create_subscriber,
    create_subscriber_payload,
    create_subscription,
    create_subscription_plan_payload,
    make_subscriber_headers,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestSubscriberCreation:
    def test_subscriber_creation_defaults_applied(self, api):
        """PRD §3.1: "A new subscriber starts `ACTIVE` with a zero
        `balance_due_cents` and zero `unapplied_cash_cents`."
        PRD §2.4: "All entities in this system also carry an `updated_at`
        timestamp of the same format, refreshed on every mutation, and a
        `version` integer that starts at creation and increments by one on
        every modification — including system-driven mutations such as
        cascade side effects, status re-evaluations, and staged plan
        changes."

        Design: Corner/entities/subscriber_creation_defaults_applied
        """
        resp = api.create_subscriber(
            create_subscriber_payload(display_name="D", email="d@x.com"), REP
        )
        data = validate_success(resp, 201)
        assert_subscriber(data)
        assert data["status"] == "ACTIVE"
        assert data["balance_due_cents"] == 0
        assert data["unapplied_cash_cents"] == 0
        assert data.get("service_address") is None

        fetched = validate_success(api.get_subscriber(data["id"], REP))
        assert fetched["status"] == "ACTIVE"
        assert fetched["balance_due_cents"] == 0
        assert fetched["unapplied_cash_cents"] == 0
        assert fetched.get("service_address") is None

    def test_subscriber_creation_defaults_via_director(self, api):
        """PRD §3.1: "A new subscriber starts `ACTIVE` with a zero
        `balance_due_cents` and zero `unapplied_cash_cents`."

        Design: Corner/entities/subscriber_creation_defaults_applied
        """
        resp = api.create_subscriber(
            create_subscriber_payload(display_name="DD", email="dd@x.com"), DIRECTOR
        )
        data = validate_success(resp, 201)
        assert_subscriber(data)
        assert data["status"] == "ACTIVE"
        assert data["balance_due_cents"] == 0
        assert data["unapplied_cash_cents"] == 0


class TestPlanCreationValidation:
    def test_subscription_plan_missing_required_field_rejected(self, api):
        """PRD §3.1: "A `CirculationDirector` creates one with a display
        `name`, a `plan_type` of `PRINT`, `DIGITAL`, or `BUNDLE`, a count of
        `issues_per_week` (zero for `DIGITAL` plans, between one and seven
        otherwise), a `base_weekly_rate_cents` that must be positive, and a
        `min_weekly_rate_cents` floor used later by retention offers."
        PRD §2.10: "then request-body shape — required fields present, types
        valid, enum membership, positive amounts, date ordering,
        Monday-anchored week starts, returned-copies not exceeding
        delivered-copies — with violations rejected as `ERR_INVALID_REQUEST`."

        Design: Corner/entities/subscription_plan_missing_required_field_rejected
        """
        payload = {
            "name": "X",
            "plan_type": "PRINT",
            "issues_per_week": 7,
            "min_weekly_rate_cents": 0,
        }
        resp = api.create_subscription_plan(payload, DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)

    def test_subscription_plan_invalid_enum_rejected(self, api):
        """PRD §3.1: "a `plan_type` of `PRINT`, `DIGITAL`, or `BUNDLE`"
        PRD §2.10: "then request-body shape — required fields present, types
        valid, enum membership, positive amounts, date ordering,
        Monday-anchored week starts, returned-copies not exceeding
        delivered-copies — with violations rejected as `ERR_INVALID_REQUEST`."

        Design: Corner/entities/subscription_plan_invalid_enum_rejected
        """
        payload = create_subscription_plan_payload(
            name="X", plan_type="WEEKLY", issues_per_week=7,
            base_weekly_rate_cents=100, min_weekly_rate_cents=0,
        )
        resp = api.create_subscription_plan(payload, DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)


class TestNotFound:
    def test_get_subscriber_not_found_returns_404(self, api):
        """PRD §2.10: "Only then does the system look at the resource graph:
        path identifiers must exist, validated left-to-right so the first
        missing id yields `ERR_NOT_FOUND`; then request-body shape — required
        fields present, types valid, enum membership, positive amounts, date
        ordering, Monday-anchored week starts, returned-copies not exceeding
        delivered-copies — with violations rejected as `ERR_INVALID_REQUEST`."

        Design: Corner/entities/get_subscriber_not_found_returns_404
        """
        resp = api.get_subscriber(NON_EXISTENT_UUID, REP)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND, 404)


class TestSubscriberPagination:
    def test_subscriber_list_pagination_envelope(self, api):
        """PRD §2.3: "List endpoints accept `limit` and `offset` query
        parameters. `limit` defaults to 10, with a minimum of 1 and a maximum
        of 100. `offset` defaults to 0."
        PRD §2.3: "The `meta` object of every list response carries the four
        pagination fields `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/subscriber_list_pagination_envelope
        """
        for i in range(3):
            create_subscriber(display_name=f"P{i+1}", email=f"p{i+1}@x.com")

        page1, meta1 = validate_paginated(api.list_subscribers(REP, params={"limit": 2, "offset": 0}))
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        assert meta1["limit"] == 2
        assert meta1["offset"] == 0

        page2, meta2 = validate_paginated(api.list_subscribers(REP, params={"limit": 2, "offset": 2}))
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False

    def test_subscriber_list_pagination_second_page_items_distinct(self, api):
        """PRD §2.3: "Unless a list endpoint states otherwise, results are
        sorted by `created_at` in ascending order; the billing-charge list
        instead sorts by `period_start` ascending, then `created_at`
        ascending."

        Design: Corner/entities/subscriber_list_pagination_envelope
        """
        ids = []
        for i in range(3):
            sub = create_subscriber(display_name=f"Q{i+1}", email=f"q{i+1}@x.com")
            ids.append(sub["id"])

        page1, _ = validate_paginated(api.list_subscribers(REP, params={"limit": 2, "offset": 0}))
        page2, _ = validate_paginated(api.list_subscribers(REP, params={"limit": 2, "offset": 2}))
        paged_ids = [row["id"] for row in page1] + [row["id"] for row in page2]
        assert paged_ids == ids, "pages together must cover all subscribers in creation order"


class TestAuthContext:
    def test_missing_auth_header_rejected(self, api):
        """PRD §2.1: "A request missing either header, or presenting a role
        the system does not recognize, is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/validations/missing_auth_header_rejected
        """
        resp = api.create_subscriber(
            {"display_name": "NA", "email": "na@x.com"}, NO_AUTH_HEADERS
        )
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER, 400)


class TestOwnership:
    def test_not_own_resource_forbidden(self, api):
        """PRD §2.1: "A `Subscriber` caller touching any resource outside
        their own account chain is rejected with `ERR_NOT_OWN_RESOURCE`
        (HTTP 403)."

        Design: Corner/validations/not_own_resource_forbidden
        """
        set_clock("2026-08-03T00:00:00Z")
        plan = create_plan(
            name="OW", plan_type="DIGITAL", issues_per_week=0,
            base_weekly_rate_cents=400, proration_method="PER_DAY",
            min_weekly_rate_cents=0,
        )
        owner = create_subscriber(display_name="O1", email="o1@x.com")
        other = create_subscriber(display_name="O2", email="o2@x.com")
        subscription = create_subscription(owner["id"], plan["id"], start_date="2026-08-03")

        resp = api.get_subscription(subscription["id"], make_subscriber_headers(other["id"]))
        validate_error(resp, ApiErrorId.ERR_NOT_OWN_RESOURCE, 403)


class TestRbac:
    def test_subscriber_cannot_create_subscription_plan(self, api):
        """PRD §2.1: "A request whose role is recognized but not permitted
        for the target endpoint is rejected with `ERR_FORBIDDEN_FOR_ROLE`
        (HTTP 403)."
        PRD §4: "POST | `/api/subscription-plans` | Create a subscription plan
        | CirculationDirector".

        Design: Corner/rbac/subscriber_cannot_create_subscription_plan
        """
        caller = create_subscriber(display_name="RB1", email="rb1@x.com")
        payload = {
            "name": "NOPE", "plan_type": "PRINT", "issues_per_week": 7,
            "base_weekly_rate_cents": 100, "min_weekly_rate_cents": 0,
        }
        resp = api.create_subscription_plan(payload, make_subscriber_headers(caller["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE, 403)

    def test_service_rep_cannot_reverse_payment(self, api):
        """PRD §3.8: "Reversal is the deepest compensation in the system,
        reserved for `CirculationDirector`, and only available on a `CLEARED`
        payment (otherwise `ERR_PAYMENT_NOT_CLEARED`)."

        Design: Corner/rbac/service_rep_cannot_reverse_payment
        """
        subscriber = create_subscriber(display_name="RB2", email="rb2@x.com")
        payment = validate_success(
            api.create_payment(
                {"subscriber_id": subscriber["id"], "amount_cents": 500, "method": "CARD"},
                REP,
            ),
            201,
        )
        cleared = validate_success(api.mark_payment_cleared(payment["id"], REP))
        assert cleared["status"] == "CLEARED"

        resp = api.reverse_payment(payment["id"], REP)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE, 403)

        after = validate_success(api.get_payment(payment["id"], REP))
        assert after["status"] == "CLEARED", "denied reversal must not mutate the payment"

    def test_district_manager_cannot_issue_goodwill_credit(self, api):
        """PRD §2.1: "District managers own distribution: routes, carriers,
        route assignments, rack locations, rack sales reports, and the
        carrier settlement read."
        PRD §4: "POST | `/api/credit-memos` | Issue a manual GOODWILL credit
        | ServiceRep, CirculationDirector".

        Design: Corner/rbac/district_manager_cannot_issue_goodwill_credit
        """
        subscriber = create_subscriber(display_name="RB3", email="rb3@x.com")
        resp = api.create_credit_memo(
            {"subscriber_id": subscriber["id"], "amount_cents": 100, "reason": "dm attempt"},
            MGR,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE, 403)

    def test_director_override_hierarchical_ops(self, api):
        """PRD §2.1: "The circulation director is the hierarchical override
        role: every operation available to `ServiceRep` and `DistrictManager`
        is available to `CirculationDirector`, plus plan configuration, audit
        bureau reporting, payment reversal, charge write-off, credit-memo
        void, rack report reconciliation and dispute, the nightly batch
        cycle, and the test-driving clock."

        Design: Corner/rbac/director_override_hierarchical_ops
        """
        subscriber = validate_success(
            api.create_subscriber(
                {"display_name": "RB4", "email": "rb4@x.com"}, DIRECTOR
            ),
            201,
        )
        payment = validate_success(
            api.create_payment(
                {"subscriber_id": subscriber["id"], "amount_cents": 500, "method": "ACH"},
                DIRECTOR,
            ),
            201,
        )
        cleared = validate_success(api.mark_payment_cleared(payment["id"], DIRECTOR))
        assert cleared["status"] == "CLEARED"
