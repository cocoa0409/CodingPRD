"""Validation outcomes, validation-order precedence, OCC stale-version, and
resource-overlap conflicts. Covers difficulty rules priority_pair_validation_conflict
and resource_temporal_overlap, plus the validations / errors corner instances.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    TEST_USERS, make_account_holder_headers, NON_EXISTENT_UUID,
    ApiErrorId,
    create_active_account, create_plan, create_zone, set_clock,
    create_account, add_standard_carts, account_version,
    basic_plan_payload,
    setup_account_with_open_invoice, setup_account_with_scheduled_extra_pickup,
    generate_invoice_payload,
)

DISP = TEST_USERS["dispatcher_headers"]
CREW = TEST_USERS["crew_lead_headers"]

NONEXISTENT = "00000000-0000-4000-8000-000000000000"


class TestValidationPrecedence:
    def test_pay_void_invoice_wrong_amount_is_invalid_state_not_mismatch(self, api):
        """PRD §2.6: "then the state-transition legality check that the target resource is
        in a state from which the requested transition is defined (ERR_INVALID_STATE); and
        only after all of those, the endpoint's specific business rules."
        PRD §3.12: "Settlement is exact-only: the payment's amount_cents must equal the
        invoice's amount_due_cents, and any other amount — too little or too much — is
        rejected with ERR_PAYMENT_AMOUNT_MISMATCH (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_pay_on_void_invoice
        """
        s = setup_account_with_open_invoice(address="26 Oak St")
        acct, inv = s["account"], s["invoice"]
        validate_success(api.void_invoice(inv["id"], DISP), 200)
        holder = make_account_holder_headers(acct["id"])
        # wrong amount AND voided state -> state check (priority 7) precedes fiscal (15)
        validate_error(api.pay_invoice(inv["id"], {"amount_cents": 999, "method": "MANUAL"}, holder),
                       ApiErrorId.ERR_INVALID_STATE.value)

    def test_activate_nonexistent_account_is_not_found_not_carts_incomplete(self, api):
        """PRD §2.6: "then existence of every path-referenced resource, left to right
        (ERR_NOT_FOUND); ... and only after all of those, the endpoint's specific business
        rules."
        PRD §2.5: "The server validates every path identifier left to right and rejects
        the request with ERR_NOT_FOUND (HTTP 404) at the first identifier in the path that
        names no existing resource."

        Design: Difficulty/priority_pair_validation_conflict/existence_beats_carts_incomplete_on_activate
        """
        validate_error(api.activate_start(NONEXISTENT, DISP), ApiErrorId.ERR_NOT_FOUND.value)

    def test_activate_missing_cart_existing_account_is_carts_incomplete(self, api):
        """PRD §2.5: "The server validates every path identifier left to right and rejects
        the request with ERR_NOT_FOUND (HTTP 404) at the first identifier in the path that
        names no existing resource."
        PRD §3.3: "If either required cart is missing the activation is rejected with
        ERR_CARTS_INCOMPLETE (HTTP 409)."

        When the path id DOES exist, the existence check passes and the cart-completeness
        business check fires instead — the complement that confirms the precedence ordering.

        Design: Difficulty/priority_pair_validation_conflict/existence_beats_carts_incomplete_on_activate
        """
        plan = create_plan()
        zone = create_zone()
        acct = create_account(plan["id"], zone["id"], address="27 Oak St")
        get_success_data(api.create_cart(acct["id"], {"cart_type": "TRASH", "size_gallons": 65}, DISP))
        validate_error(api.activate_start(acct["id"], DISP), ApiErrorId.ERR_CARTS_INCOMPLETE.value)

    def test_pay_open_invoice_wrong_amount_is_fiscal_mismatch(self, api):
        """PRD §3.12: "Settlement is exact-only: the payment's amount_cents must equal the
        invoice's amount_due_cents, and any other amount — too little or too much — is
        rejected with ERR_PAYMENT_AMOUNT_MISMATCH (HTTP 422)."

        With the invoice still OPEN, the state check passes and the fiscal check fires —
        the complement that confirms ERR_INVALID_STATE only pre-empts when the state is bad.

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_pay_on_void_invoice
        """
        s = setup_account_with_open_invoice(address="33 Oak St")
        acct, inv = s["account"], s["invoice"]
        holder = make_account_holder_headers(acct["id"])
        validate_error(api.pay_invoice(inv["id"], {"amount_cents": 999, "method": "MANUAL"}, holder),
                       ApiErrorId.ERR_PAYMENT_AMOUNT_MISMATCH.value)


class TestResourceOverlap:
    def test_same_day_double_booking_rejected(self, api):
        """PRD §3.10: "but only when the parent account is ACTIVE and no other SCHEDULED
        extra-pickup request on the same account already holds the same requested_date; a
        same-day collision is rejected with ERR_DATE_DOUBLE_BOOKED (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/extra_pickup_same_day_double_booking_rejected
        """
        s = setup_account_with_scheduled_extra_pickup(
            "2026-03-27T00:00:00Z", 1, address="36 Oak St")
        acct = s["account"]
        holder = make_account_holder_headers(acct["id"])
        req2 = get_success_data(api.create_extra_pickup(
            acct["id"], {"requested_date": "2026-03-27T00:00:00Z", "bulk_item_count": 2}, holder))
        validate_error(api.schedule_extra_pickup(req2["id"], DISP),
                       ApiErrorId.ERR_DATE_DOUBLE_BOOKED.value)

    def test_different_day_extra_pickup_schedules_cleanly(self, api):
        """PRD §3.10: "but only when the parent account is ACTIVE and no other SCHEDULED
        extra-pickup request on the same account already holds the same requested_date; a
        same-day collision is rejected with ERR_DATE_DOUBLE_BOOKED (HTTP 409)."

        A request on a DIFFERENT calendar day does not collide — exact-day equality
        semantics, so a neighbouring date schedules cleanly.

        Design: Difficulty/resource_temporal_overlap/extra_pickup_same_day_double_booking_rejected
        """
        s = setup_account_with_scheduled_extra_pickup(
            "2026-03-27T00:00:00Z", 1, address="37 Oak St")
        acct = s["account"]
        holder = make_account_holder_headers(acct["id"])
        req2 = get_success_data(api.create_extra_pickup(
            acct["id"], {"requested_date": "2026-03-28T00:00:00Z", "bulk_item_count": 1}, holder))
        scheduled = validate_success(api.schedule_extra_pickup(req2["id"], DISP), 200)
        assert scheduled["status"] == "SCHEDULED"

    def test_duplicate_active_address_rejected(self, api):
        """PRD §3.2: "The address must be non-empty and must be unique among accounts whose
        status is PENDING_START, ACTIVE, or SUSPENDED; a collision against any such account
        is rejected with ERR_ADDRESS_IN_USE (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/address_uniqueness_overlap_across_active_accounts
        """
        plan = create_plan()
        zone = create_zone()
        get_success_data(api.create_account(
            {"plan_id": plan["id"], "zone_id": zone["id"],
             "service_address": "40 Oak St", "holder_name": "Di G"}, DISP))
        validate_error(api.create_account(
            {"plan_id": plan["id"], "zone_id": zone["id"],
             "service_address": "40 Oak St", "holder_name": "Eh H"}, DISP),
            ApiErrorId.ERR_ADDRESS_IN_USE.value)

    def test_address_reusable_after_first_account_stopped(self, api):
        """PRD §3.2: "The address must be non-empty and must be unique among accounts whose
        status is PENDING_START, ACTIVE, or SUSPENDED; a collision against any such account
        is rejected with ERR_ADDRESS_IN_USE (HTTP 409)."

        A STOPPED account is outside the occupancy window {PENDING_START, ACTIVE,
        SUSPENDED}, so its address is free for a new account — the complement that fixes
        the boundary of the open-ended status-window semantics.

        Design: Difficulty/resource_temporal_overlap/address_uniqueness_overlap_across_active_accounts
        """
        plan = create_plan()
        zone = create_zone()
        first = create_account(plan["id"], zone["id"], address="41 Oak St")
        add_standard_carts(first["id"])
        get_success_data(api.activate_start(first["id"], DISP))
        get_success_data(api.stop_account(first["id"], DISP))
        # address now free: a new account at the same address succeeds
        reused = validate_success(api.create_account(
            {"plan_id": plan["id"], "zone_id": zone["id"],
             "service_address": "41 Oak St", "holder_name": "Re U"}, DISP), 201)
        assert reused["service_address"] == "41 Oak St"


class TestBusinessValidations:
    def test_activate_without_recycling_cart_rejected(self, api):
        """PRD §3.3: "the account is equipped with at least one ACTIVE cart of cart_type
        TRASH and at least one ACTIVE cart of cart_type RECYCLING. If either required cart
        is missing the activation is rejected with ERR_CARTS_INCOMPLETE (HTTP 409)."

        Design: Corner/validations/activate_without_recycling_cart_returns_carts_incomplete
        """
        plan = create_plan()
        zone = create_zone()
        acct = create_account(plan["id"], zone["id"], address="72 Oak St")
        get_success_data(api.create_cart(acct["id"], {"cart_type": "TRASH", "size_gallons": 65}, DISP))
        validate_error(api.activate_start(acct["id"], DISP), ApiErrorId.ERR_CARTS_INCOMPLETE.value)

    def test_create_account_on_archived_plan_rejected(self, api):
        """PRD §3.2: "If the referenced plan is archived, the account cannot be created and
        the request is rejected with ERR_PLAN_ARCHIVED (HTTP 409)."

        Design: Corner/validations/create_account_on_archived_plan_returns_plan_archived
        """
        plan = get_success_data(api.create_service_plan(basic_plan_payload(), DISP))
        get_success_data(api.archive_service_plan(plan["id"], DISP))
        zone = create_zone()
        validate_error(api.create_account(
            {"plan_id": plan["id"], "zone_id": zone["id"],
             "service_address": "74 Oak St", "holder_name": "Hh C"}, DISP),
            ApiErrorId.ERR_PLAN_ARCHIVED.value)

    def test_report_event_before_effective_date_rejected(self, api):
        """PRD §3.7: "The reported_at instant must be at or after the schedule row's
        effective_pickup_date — a pickup cannot be reported before it was due — and an
        earlier timestamp is rejected with ERR_REPORT_TOO_EARLY (HTTP 409)."

        Design: Corner/validations/report_event_before_effective_date_returns_too_early
        """
        _, _, acct = create_active_account(clock="2026-03-02T00:00:00Z", address="76 Oak St")
        rows = get_success_data(api.list_pickup_schedules(acct["id"], DISP, {"stream": "TRASH"}))
        s0 = rows[0]
        validate_error(api.report_event(
            s0["id"], {"outcome": "COLLECTED", "reported_at": "2026-01-01T00:00:00Z"}, CREW),
            ApiErrorId.ERR_REPORT_TOO_EARLY.value)

    def test_contaminated_on_trash_schedule_rejected(self, api):
        """PRD §3.7: "A CONTAMINATED outcome may only be reported against a row whose
        stream is RECYCLING; reporting contamination on a trash row is rejected with
        ERR_CONTAMINATION_NOT_RECYCLING (HTTP 409)."

        Design: Corner/validations/contaminated_on_trash_schedule_returns_not_recycling
        """
        _, _, acct = create_active_account(clock="2026-03-02T00:00:00Z", address="78 Oak St")
        rows = get_success_data(api.list_pickup_schedules(acct["id"], DISP, {"stream": "TRASH"}))
        s0 = rows[0]
        # A CONTAMINATED report carries severity (PRD §3.9 "The crew reports the
        # severity as MINOR or MAJOR"); supplying it makes the body well-formed so
        # the stream-mismatch business rule (priority 13) fires rather than the
        # well-formedness check (priority 5) per the §2.6 validation order.
        validate_error(api.report_event(
            s0["id"], {"outcome": "CONTAMINATED", "reported_at": s0["effective_pickup_date"],
                       "severity": "MINOR"}, CREW),
            ApiErrorId.ERR_CONTAMINATION_NOT_RECYCLING.value)

    def test_enable_autopay_without_payment_method_rejected(self, api):
        """PRD §3.5: "Autopay cannot be enabled while the account has a null
        stored_payment_token — an attempt to do so is rejected with ERR_NO_PAYMENT_METHOD
        (HTTP 409)."

        Design: Corner/validations/enable_autopay_without_payment_method_returns_no_payment_method
        """
        plan = create_plan()
        zone = create_zone()
        acct = create_account(plan["id"], zone["id"], address="80 Oak St")
        holder = make_account_holder_headers(acct["id"])
        validate_error(api.set_autopay(acct["id"], {"autopay_enabled": True}, holder),
                       ApiErrorId.ERR_NO_PAYMENT_METHOD.value)

    def test_pay_invoice_wrong_amount_rejected(self, api):
        """PRD §3.12: "Settlement is exact-only: the payment's amount_cents must equal the
        invoice's amount_due_cents, and any other amount — too little or too much — is
        rejected with ERR_PAYMENT_AMOUNT_MISMATCH (HTTP 422)."

        Design: Corner/validations/pay_invoice_wrong_amount_returns_amount_mismatch
        """
        s = setup_account_with_open_invoice(address="82 Oak St")
        acct, inv = s["account"], s["invoice"]
        holder = make_account_holder_headers(acct["id"])
        validate_error(api.pay_invoice(inv["id"], {"amount_cents": 3999, "method": "MANUAL"}, holder),
                       ApiErrorId.ERR_PAYMENT_AMOUNT_MISMATCH.value)

    def test_create_account_unknown_plan_reference_not_found(self, api):
        """PRD §2.5: "when a write carries a foreign key in its body — a plan_id, a
        zone_id, an invoice_id, or any other reference to another resource — and that key
        names a resource that does not exist, the request is rejected with
        ERR_REFERENCE_NOT_FOUND (HTTP 404)."

        Design: Corner/validations/create_account_unknown_plan_returns_reference_not_found
        """
        zone = create_zone()
        validate_error(api.create_account(
            {"plan_id": "00000000-0000-4000-8000-000000000001", "zone_id": zone["id"],
             "service_address": "84 Oak St", "holder_name": "Mm H"}, DISP),
            ApiErrorId.ERR_REFERENCE_NOT_FOUND.value)


class TestErrorsAndOCC:
    def test_pagination_limit_above_max_rejected(self, api):
        """PRD §2.3: "A limit outside the inclusive range of 1 to 100, or a negative
        offset, is a malformed request rejected with ERR_INVALID_REQUEST (HTTP 422)."

        Design: Corner/errors/invalid_pagination_limit_returns_invalid_request
        """
        validate_error(api.list_service_plans(DISP, {"limit": 1000}),
                       ApiErrorId.ERR_INVALID_REQUEST.value)

    def test_stale_version_on_invoice_generate_rejected(self, api):
        """PRD §2.8: "Before the operation proceeds, the server compares that value to the
        account's current version; if they differ, the write is rejected with
        ERR_STALE_VERSION (HTTP 412) and nothing is mutated."
        PRD §2.8: "an invoice request carrying an expected_account_version that no longer
        matches the account's current version is refused with ERR_STALE_VERSION rather than
        billing an outdated amount."

        Design: Corner/errors/stale_version_on_invoice_generate_returns_412
        """
        _, _, acct = create_active_account(address="92 Oak St")
        v_stale = account_version(acct["id"])
        # first generation bumps the account version
        get_success_data(api.generate_invoice(acct["id"], generate_invoice_payload(
            v_stale, "2026-03-01T00:00:00Z", "2026-04-01T00:00:00Z", "2026-04-15T00:00:00Z"), DISP))
        # second generation reuses the now-stale version
        validate_error(api.generate_invoice(acct["id"], generate_invoice_payload(
            v_stale, "2026-04-01T00:00:00Z", "2026-05-01T00:00:00Z", "2026-05-15T00:00:00Z"), DISP),
            ApiErrorId.ERR_STALE_VERSION.value)
