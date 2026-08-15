"""Complaints, credit memos, caps, voids, and the complaint-credit cascade."""
from test_helpers import (
    DIRECTOR,
    REP,
    ApiErrorId,
    create_active_subscription,
    create_complaint,
    create_goodwill_memo,
    create_plan,
    create_subscriber,
    create_subscription,
    get_subscriber,
    get_subscription,
    list_charges_for_subscription,
    run_daily_cycle,
    set_clock,
    set_clock_and_cycle,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestComplaintFilingWindow:
    def test_complaint_window_closed_rejected(self, api):
        """PRD §3.4: "The filing window is tight: the service date must fall
        within today and the seven days prior — anything older is rejected
        with `ERR_COMPLAINT_WINDOW_CLOSED`."

        Design: Corner/validations/complaint_window_closed_rejected
        """
        ctx = create_active_subscription(
            start_date="2026-08-03", clock="2026-08-03T00:00:00Z"
        )
        set_clock("2026-08-11T00:00:00Z")

        stale = api.create_complaint(
            {
                "subscription_id": ctx["subscription"]["id"],
                "service_date": "2026-08-03",
                "complaint_type": "MISSED",
            },
            REP,
        )
        validate_error(stale, ApiErrorId.ERR_COMPLAINT_WINDOW_CLOSED, 409)

        boundary = api.create_complaint(
            {
                "subscription_id": ctx["subscription"]["id"],
                "service_date": "2026-08-04",
                "complaint_type": "MISSED",
            },
            REP,
        )
        data = validate_success(boundary, 201)
        assert data["status"] == "OPEN", (
            "service_date exactly seven days back is inside the inclusive window"
        )

    def test_complaint_for_today_accepted(self, api):
        """PRD §3.4: "The filing window is tight: the service date must fall
        within today and the seven days prior — anything older is rejected
        with `ERR_COMPLAINT_WINDOW_CLOSED`."

        Design: Corner/validations/complaint_window_closed_rejected
        """
        ctx = create_active_subscription(
            start_date="2026-08-03", clock="2026-08-03T00:00:00Z"
        )
        complaint = create_complaint(ctx["subscription"]["id"], "2026-08-03", "LATE")
        assert complaint["status"] == "OPEN"


class TestDuplicateComplaint:
    def test_duplicate_complaint_rejected(self, api):
        """PRD §3.4: "Only one non-`DENIED` complaint may exist per
        subscription per service date; a second filing collides with
        `ERR_DUPLICATE_COMPLAINT`."

        Design: Corner/validations/duplicate_complaint_rejected
        """
        ctx = create_active_subscription(
            start_date="2026-08-03", clock="2026-08-03T00:00:00Z"
        )
        create_complaint(ctx["subscription"]["id"], "2026-08-03", "MISSED")

        resp = api.create_complaint(
            {
                "subscription_id": ctx["subscription"]["id"],
                "service_date": "2026-08-03",
                "complaint_type": "LATE",
            },
            REP,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_COMPLAINT, 409)


class TestComplaintCredit:
    def test_complaint_credit_after_deny_rejected(self, api):
        """PRD §3.4: "Either resolution path requires the complaint to still
        be `OPEN` — acting on a resolved complaint surfaces
        `ERR_COMPLAINT_NOT_OPEN`."

        Design: Corner/state_machines/complaint_credit_after_deny_rejected
        """
        ctx = create_active_subscription(
            start_date="2026-08-03", clock="2026-08-03T00:00:00Z"
        )
        complaint = create_complaint(ctx["subscription"]["id"], "2026-08-03", "DAMAGED")
        denied = validate_success(
            api.deny_complaint(complaint["id"], {"reason": "photo shows delivery"}, REP)
        )
        assert denied["status"] == "DENIED"

        resp = api.credit_complaint(complaint["id"], {"amount_cents": 100}, REP)
        validate_error(resp, ApiErrorId.ERR_COMPLAINT_NOT_OPEN, 409)

        memos, _meta = validate_paginated(
            api.list_credit_memos(REP, params={"complaint_id": complaint["id"]})
        )
        assert memos == [], "denied complaint must not produce a credit memo"

    def test_complaint_credit_not_found_returns_404(self, api):
        """PRD §2.10: "Only then does the system look at the resource graph:
        path identifiers must exist, validated left-to-right so the first
        missing id yields `ERR_NOT_FOUND`; then request-body shape — required
        fields present, types valid, enum membership, positive amounts, date
        ordering, Monday-anchored week starts, returned-copies not exceeding
        delivered-copies — with violations rejected as `ERR_INVALID_REQUEST`.
        State preconditions come next (the specific state-axis errors such as
        `ERR_SUBSCRIPTION_NOT_ACTIVE`, `ERR_COMPLAINT_NOT_OPEN`,
        `ERR_OFFER_NOT_OPEN`, and their siblings), then the OCC stale-version
        check (`ERR_STALE_VERSION`)."

        Design: Corner/validations/complaint_credit_not_found_returns_404
        """
        resp = api.credit_complaint(
            "00000000-0000-4000-8000-000000000000", {"amount_cents": 100}, REP
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND, 404)

    def test_complaint_credit_cap_enforced(self, api):
        """PRD §3.4: "First, a per-complaint ceiling: the amount may not
        exceed 2000 cents, else `ERR_CREDIT_EXCEEDS_COMPLAINT_CAP`."

        Design: Corner/validations/complaint_credit_cap_enforced
        """
        ctx = create_active_subscription(
            start_date="2026-08-03", clock="2026-08-03T00:00:00Z"
        )
        complaint = create_complaint(ctx["subscription"]["id"], "2026-08-03", "LATE")

        resp = api.credit_complaint(complaint["id"], {"amount_cents": 2500}, REP)
        validate_error(resp, ApiErrorId.ERR_CREDIT_EXCEEDS_COMPLAINT_CAP, 409)

        after = validate_success(api.get_complaint(complaint["id"], REP))
        assert after["status"] == "OPEN", "rejected credit must not resolve the complaint"

    def test_complaint_credit_at_cap_accepted(self, api):
        """PRD §3.4: "First, a per-complaint ceiling: the amount may not
        exceed 2000 cents, else `ERR_CREDIT_EXCEEDS_COMPLAINT_CAP`."
        PRD §3.4: "**Crediting** flips the complaint to `CREDITED`, stamps
        its `credit_amount_cents`, and creates a credit memo with `source` of
        `COMPLAINT` and `complaint_id` set, which immediately auto-applies
        through the waterfall."

        Design: Corner/validations/complaint_credit_cap_enforced
        """
        ctx = create_active_subscription(
            start_date="2026-08-03", clock="2026-08-03T00:00:00Z"
        )
        complaint = create_complaint(ctx["subscription"]["id"], "2026-08-03", "LATE")

        memo = validate_success(
            api.credit_complaint(complaint["id"], {"amount_cents": 2000}, REP)
        )
        assert memo["source"] == "COMPLAINT"
        assert memo["complaint_id"] == complaint["id"]
        assert memo["amount_cents"] == 2000

        after = validate_success(api.get_complaint(complaint["id"], REP))
        assert after["status"] == "CREDITED"
        assert after["credit_amount_cents"] == 2000


class TestComplaintCreditCascade:
    def test_complaint_credit_depth3_cascade(self, api):
        """PRD §3.4: "The credit cascade is deliberately deep: the applied
        charge's `credit_applied_cents` rises (possibly flipping the charge
        to `PAID`), the subscriber's `balance_due_cents` is recomputed, and
        the subscription's billing axis is re-evaluated — a complaint credit
        can pull a subscription from `GRACE` back to `ACTIVE`."

        Design: Difficulty/transitive_cascade/complaint_credit_depth3_cascade
        """
        set_clock("2026-08-03T00:00:00Z")
        plan = create_plan(
            name="CC", plan_type="PRINT", issues_per_week=7,
            base_weekly_rate_cents=600, proration_method="PER_DAY",
            min_weekly_rate_cents=0,
        )
        subscriber = create_subscriber(
            display_name="C", email="c@x.com", service_address="8 Main St"
        )
        subscription = create_subscription(subscriber["id"], plan["id"], start_date="2026-08-03")
        run_daily_cycle()
        # Charges through 2026-08-24; oldest (due 2026-08-17) is 8 days past
        # due on 2026-08-25 -> GRACE.
        set_clock_and_cycle("2026-08-25T00:00:00Z")
        assert get_subscription(subscription["id"])["billing_status"] == "GRACE"

        complaint = create_complaint(subscription["id"], "2026-08-20", "MISSED")

        memo = validate_success(
            api.credit_complaint(complaint["id"], {"amount_cents": 600}, REP)
        )
        assert memo["source"] == "COMPLAINT"
        assert memo["amount_cents"] == 600
        assert memo["applied_cents"] == 600

        charges = list_charges_for_subscription(subscription["id"])
        oldest = charges[0]
        assert oldest["period_start"] == "2026-08-03"
        assert oldest["credit_applied_cents"] == 600
        assert oldest["status"] == "PAID"

        subscriber_after = get_subscriber(subscriber["id"])
        assert subscriber_after["balance_due_cents"] == 1800

        subscription_after = get_subscription(subscription["id"])
        assert subscription_after["billing_status"] == "ACTIVE", (
            "oldest remaining unpaid charge is only 1 day past due"
        )

    def test_complaint_credit_marks_complaint_credited(self, api):
        """PRD §3.4: "**Crediting** flips the complaint to `CREDITED`, stamps
        its `credit_amount_cents`, and creates a credit memo with `source` of
        `COMPLAINT` and `complaint_id` set, which immediately auto-applies
        through the waterfall."

        Design: Difficulty/transitive_cascade/complaint_credit_depth3_cascade
        """
        ctx = create_active_subscription(
            start_date="2026-08-03", clock="2026-08-03T00:00:00Z"
        )
        complaint = create_complaint(ctx["subscription"]["id"], "2026-08-03", "MISSED")

        memo = validate_success(
            api.credit_complaint(complaint["id"], {"amount_cents": 150}, REP)
        )
        assert memo["complaint_id"] == complaint["id"]
        assert memo["source"] == "COMPLAINT"

        complaint_after = validate_success(api.get_complaint(complaint["id"], REP))
        assert complaint_after["status"] == "CREDITED"
        assert complaint_after["credit_amount_cents"] == 150

        # The credit applied against the open charge through the waterfall.
        charges = list_charges_for_subscription(ctx["subscription"]["id"])
        assert charges[0]["credit_applied_cents"] == 150
        assert charges[0]["status"] == "PARTIALLY_PAID"


class TestGoodwillCap:
    def test_goodwill_monthly_cap_enforced(self, api):
        """PRD §3.4: "Both goodwill and complaint credits draw from the same
        monthly pool: the sum of `amount_cents` over the subscriber's credit
        memos with `source` of `GOODWILL` or `COMPLAINT`, excluding `VOIDED`
        memos, created within the current calendar month, plus the new
        amount, may not exceed 5000 cents — breach is rejected with
        `ERR_GOODWILL_CAP_EXCEEDED`."

        Design: Corner/validations/goodwill_monthly_cap_enforced
        """
        set_clock("2026-08-03T00:00:00Z")
        subscriber = create_subscriber(display_name="GC", email="gc@x.com")
        create_goodwill_memo(subscriber["id"], 2000, "g1")
        create_goodwill_memo(subscriber["id"], 2000, "g2")

        resp = api.create_credit_memo(
            {"subscriber_id": subscriber["id"], "amount_cents": 2000, "reason": "g3"}, REP
        )
        validate_error(resp, ApiErrorId.ERR_GOODWILL_CAP_EXCEEDED, 409)

    def test_goodwill_credit_at_exact_cap_accepted(self, api):
        """PRD §3.4: "Both goodwill and complaint credits draw from the same
        monthly pool: the sum of `amount_cents` over the subscriber's credit
        memos with `source` of `GOODWILL` or `COMPLAINT`, excluding `VOIDED`
        memos, created within the current calendar month, plus the new
        amount, may not exceed 5000 cents — breach is rejected with
        `ERR_GOODWILL_CAP_EXCEEDED`."

        Design: Corner/validations/goodwill_monthly_cap_enforced
        """
        set_clock("2026-08-03T00:00:00Z")
        subscriber = create_subscriber(display_name="GC2", email="gc2@x.com")
        create_goodwill_memo(subscriber["id"], 2000, "g1")
        create_goodwill_memo(subscriber["id"], 2000, "g2")

        memo = validate_success(
            api.create_credit_memo(
                {"subscriber_id": subscriber["id"], "amount_cents": 1000, "reason": "g3"}, REP
            ),
            201,
        )
        assert memo["amount_cents"] == 1000, "4000 + 1000 == 5000 is at the cap, not over"


class TestCreditMemoVoid:
    def test_void_applied_credit_memo_rejected(self, api):
        """PRD §3.4: "A `CirculationDirector` may void a memo, but only while
        nothing has been applied — voiding a memo with any `applied_cents`
        above zero is rejected with `ERR_CREDIT_MEMO_LOCKED`."

        Design: Corner/errors/void_applied_credit_memo_rejected
        """
        ctx = create_active_subscription(
            start_date="2026-08-03",
            clock="2026-08-03T00:00:00Z",
            plan_overrides={
                "name": "VM", "plan_type": "DIGITAL", "issues_per_week": 0,
                "base_weekly_rate_cents": 600,
            },
        )
        memo = create_goodwill_memo(ctx["subscriber"]["id"], 300, "goodwill")
        assert memo["applied_cents"] == 300, "memo auto-applies at issuance"

        resp = api.void_credit_memo(memo["id"], DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_CREDIT_MEMO_LOCKED, 409)

    def test_void_unapplied_credit_memo_succeeds(self, api):
        """PRD §3.4: "Every credit memo tracks `applied_cents`, the portion
        the waterfall consumed at issuance. A memo whose full amount applied
        flips from `ISSUED` to `APPLIED`; a memo with leftover funds stays
        `ISSUED`. A `CirculationDirector` may void a memo, but only while
        nothing has been applied — voiding a memo with any `applied_cents`
        above zero is rejected with `ERR_CREDIT_MEMO_LOCKED`."

        Design: Corner/errors/void_applied_credit_memo_rejected
        """
        subscriber = create_subscriber(display_name="VU", email="vu@x.com")
        memo = create_goodwill_memo(subscriber["id"], 300, "goodwill")
        assert memo["applied_cents"] == 0, "no open charges -> nothing applied"

        voided = validate_success(api.void_credit_memo(memo["id"], DIRECTOR))
        assert voided["status"] == "VOIDED"
