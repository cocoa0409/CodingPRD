"""Quote lifecycle: revision cycle, decline lockdown, lazy expiry, and
assessment shelf life."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    accept_quote,
    assert_quote,
    create_customer,
    create_material,
    create_property,
    create_submitted_assessment,
    find_work_order_for_quote,
    get_quote,
    make_customer_headers,
    send_quote,
    set_clock,
    setup_quote_scenario,
    setup_sent_quote,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["office_admin_headers"]
ESTIMATOR = TEST_USERS["estimator_headers"]


class TestQuoteRevisionCycle:
    def test_revision_cycle_resets_send_fields(self, api):
        """PRD §3.3: "A revision edit by an estimator is permitted while the
        quote is `DRAFT` or `REVISION_REQUESTED` (otherwise
        `ERR_QUOTE_NOT_EDITABLE`); it recomputes every pricing field from the
        revised inputs and clears `sent_at` and `expires_on` back to null,
        restarting the send cycle. A `REVISION_REQUESTED` quote edited this
        way returns to `DRAFT`."

        Design: Difficulty/non_linear_state_machine/quote_revision_cycle
        """
        ctx = setup_sent_quote()
        quote = ctx["quote"]
        assert quote["status"] == "SENT"
        assert quote["sent_at"] is not None

        revised = validate_success(
            api.request_quote_revision(
                quote["id"], make_customer_headers(ctx["customer"]["id"])
            )
        )
        assert revised["status"] == "REVISION_REQUESTED"

        patched = validate_success(
            api.patch_quote(quote["id"], {"coats": 2}, ESTIMATOR)
        )
        assert patched["status"] == "DRAFT", (
            f"PATCH on REVISION_REQUESTED returns the quote to DRAFT, got {patched['status']}"
        )
        assert patched["sent_at"] is None, "sent_at cleared for the restarted cycle"
        assert patched["expires_on"] is None, "expires_on cleared for the restarted cycle"

    def test_revision_reprices_and_completes_second_cycle(self, api):
        """PRD §3.3: "A successful send stamps `sent_at` and computes
        `expires_on` as the calendar date 14 days after the sent date." and
        "Acceptance moves the quote to `ACCEPTED` and is the consequential
        path: it creates the work order (§3.4)".

        Design: Difficulty/non_linear_state_machine/quote_revision_cycle
        """
        ctx = setup_sent_quote()
        quote_id = ctx["quote"]["id"]
        validate_success(
            api.request_quote_revision(
                quote_id, make_customer_headers(ctx["customer"]["id"])
            )
        )
        patched = validate_success(api.patch_quote(quote_id, {"coats": 2}, ESTIMATOR))
        # 2 coats: seal 1200*24*2 = 57600; crack 6000; patch 8000 -> 71600 + 7500
        assert patched["total_cents"] == 79100, (
            f"repriced 2-coat total must be 79100, got {patched['total_cents']}"
        )

        resent = validate_success(api.send_quote(quote_id, ESTIMATOR))
        assert resent["status"] == "SENT"
        assert resent["expires_on"] == "2026-08-15", (
            f"sent at 2026-08-01 + 14 days = 2026-08-15, got {resent['expires_on']}"
        )

        accepted = validate_success(
            api.accept_quote(quote_id, make_customer_headers(ctx["customer"]["id"]))
        )
        assert accepted["status"] == "ACCEPTED"
        work_order = find_work_order_for_quote(quote_id)
        assert work_order["execution_status"] == "PENDING"
        assert work_order["coats"] == 2, "work order snapshots the revised coat count"


class TestQuoteDeclineLockdown:
    def test_accept_after_decline_rejected(self, api):
        """PRD §3.3: "Acceptance, decline, and revision-request all require
        the quote to be `SENT` (else `ERR_QUOTE_NOT_ACCEPTABLE`)" and "Decline
        moves the quote to `DECLINED`, clears `open_quote_id`, and increments
        the property's `version`."

        Design: Corner/state_machines/quote_decline_terminal_lockdown
        """
        ctx = setup_sent_quote(lot_kind="RESIDENTIAL_DRIVEWAY", address="1 Elm St")
        quote_id = ctx["quote"]["id"]
        declined = validate_success(
            api.decline_quote(quote_id, make_customer_headers(ctx["customer"]["id"]))
        )
        assert declined["status"] == "DECLINED"

        resp = api.accept_quote(quote_id, make_customer_headers(ctx["customer"]["id"]))
        validate_error(resp, ApiErrorId.ERR_QUOTE_NOT_ACCEPTABLE, 409)

        after = get_quote(quote_id)
        assert after["status"] == "DECLINED"
        data, _meta = validate_paginated(
            api.list_work_orders(ESTIMATOR, params={"quote_id": quote_id})
        )
        assert data == [], "a declined quote must not have created a work order"


class TestQuoteLazyExpiry:
    def test_accept_after_expiry_flips_quote(self, api):
        """PRD §3.3: "If the current clock date has passed `expires_on`, the
        quote lazily flips to `EXPIRED`, `open_quote_id` is cleared if it
        pointed at this quote, and the attempted action fails with
        `ERR_QUOTE_EXPIRED`."

        Design: Corner/state_machines/quote_expiry_lazy_transition_on_accept
        """
        ctx = setup_sent_quote(lot_kind="RESIDENTIAL_DRIVEWAY", address="1 Elm St")
        quote = ctx["quote"]
        assert quote["expires_on"] == "2026-08-15", (
            f"sent 2026-08-01 + 14 days = 2026-08-15, got {quote['expires_on']}"
        )

        set_clock("2026-08-16T00:00:00Z")
        resp = api.accept_quote(
            quote["id"], make_customer_headers(ctx["customer"]["id"])
        )
        validate_error(resp, ApiErrorId.ERR_QUOTE_EXPIRED, 409)

        after = get_quote(quote["id"])
        assert after["status"] == "EXPIRED", "the lazy expiry flip is persisted"


class TestAssessmentShelfLife:
    def test_expired_assessment_rejected_at_quote_create(self, api):
        """PRD §3.2: "Separately, an assessment has a 30-day shelf life:
        whenever a quote creation or quote send loads an assessment whose
        submission date is more than 30 days in the past, the assessment
        lazily flips to `EXPIRED` and the referencing operation fails with
        `ERR_ASSESSMENT_EXPIRED`."

        Design: Corner/validations/assessment_expired_when_referenced_by_quote_create
        """
        set_clock("2026-08-01T00:00:00Z")
        customer = create_customer()
        prop = create_property(customer["id"])
        assessment = create_submitted_assessment(prop["id"])
        material = create_material()

        set_clock("2026-09-05T00:00:00Z")  # 35 days after submission
        prop_fresh = validate_success(api.get_property(prop["id"], ADMIN))
        resp = api.create_quote(
            {
                "property_id": prop["id"],
                "assessment_id": assessment["id"],
                "material_id": material["id"],
                "include_crack_fill": True,
                "include_patch": True,
                "include_seal": True,
                "include_striping": False,
                "coats": 1,
                "expected_property_version": prop_fresh["version"],
            },
            ESTIMATOR,
        )
        validate_error(resp, ApiErrorId.ERR_ASSESSMENT_EXPIRED, 422)

        after = validate_success(api.get_assessment(assessment["id"], ESTIMATOR))
        assert after["status"] == "EXPIRED", "the failed reference persists the EXPIRED flip"


class TestStripingCommercialOnly:
    def test_striping_scope_on_residential_quote_rejected(self, api):
        """PRD §3.3: "Striping is commercial-only: requesting
        `include_striping` on a residential driveway, or planning striping on
        one later, is rejected with `ERR_STRIPING_COMMERCIAL_ONLY`."

        Design: Corner/errors/striping_scope_on_residential_rejected
        """
        customer = create_customer()
        prop = create_property(customer["id"], lot_kind="RESIDENTIAL_DRIVEWAY")
        assessment = create_submitted_assessment(prop["id"])
        material = create_material()
        prop_fresh = validate_success(api.get_property(prop["id"], ADMIN))

        resp = api.create_quote(
            {
                "property_id": prop["id"],
                "assessment_id": assessment["id"],
                "material_id": material["id"],
                "include_crack_fill": True,
                "include_patch": False,
                "include_seal": True,
                "include_striping": True,
                "stripe_linear_ft": 100,
                "coats": 1,
                "expected_property_version": prop_fresh["version"],
            },
            ESTIMATOR,
        )
        validate_error(resp, ApiErrorId.ERR_STRIPING_COMMERCIAL_ONLY, 422)
        data, _meta = validate_paginated(api.list_quotes(ESTIMATOR))
        assert data == [], "no quote may be persisted when striping scope is unlawful"
