"""Repair order lifecycle: initial state, teardown/inspection bubble-up,
start-repair gating, terminal lockdown, and report uniqueness."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_inspection_report,
    assert_repair_order,
    author_and_finalize_report,
    create_asset,
    create_customer,
    create_inspection_report_payload,
    create_quote_for_ro,
    create_repair_order,
    get_repair_order,
    get_success_data,
    issue_quote,
    issue_quote_for,
    make_customer_headers,
    make_technician_headers,
    setup_closed_shop,
    setup_quote_in_progress_shop,
    start_teardown,
    validate_error,
    validate_success,
    api_client,
)

SM = TEST_USERS["service_manager_headers"]
IC = TEST_USERS["intake_coordinator_headers"]
INSPECTOR = TEST_USERS["inspector_headers"]
TECH = TEST_USERS["technician_headers"]


class TestInitialState:
    def test_repair_order_initial_state(self, api):
        """PRD §3.3: "An order opens in `RECEIVED` with `repair_round` at zero and `repair_outcome` at `NONE`."

        Design: Corner/state_machines/repair_order_initial_state
        """
        customer = create_customer(name="Gila Bend", account_number="GB-160",
                                   credit_limit_cents=500000, warranty_terms_days=365)
        asset = create_asset(customer["id"], serial_number="V-1601")
        ro = get_success_data(api_client.create_repair_order(
            {"customer_id": customer["id"], "asset_id": asset["id"],
             "failure_mode": "SEAT_LEAKAGE", "failure_description": "x",
             "intake_priority": "STANDARD", "planned_start_date": "2026-08-10",
             "planned_end_date": "2026-08-20", "estimated_bay_hours": 5}, IC))
        assert_repair_order(ro)
        assert ro["status"] == "RECEIVED"
        assert ro["repair_outcome"] == "NONE"
        assert ro["repair_round"] == 0


class TestStartRepairGating:
    def test_start_repair_from_received_returns_invalid_state(self, api):
        """PRD §3.7: "With an approved quote behind it, a `Technician` starts repair, moving the order `AUTHORIZED` → `IN_REPAIR`; the precondition is that an `APPROVED` quote exists for the order, and without one the transition is rejected with `ERR_INVALID_STATE`."
        PRD §2.6: "5. **State validity** — the target entity must be in a valid from-state for the requested transition, terminal states are locked, and the quote-creation version check must match (`ERR_INVALID_STATE`, HTTP 409; the version mismatch carries `ERR_STALE_VERSION`, HTTP 412, on quote creation)."

        Design: Corner/state_machines/start_repair_from_received_returns_invalid_state
        """
        customer = create_customer(name="Hondo", account_number="HO-170",
                                   credit_limit_cents=500000, warranty_terms_days=365)
        asset = create_asset(customer["id"], serial_number="V-1701")
        ro = create_repair_order(customer["id"], asset["id"], estimated_bay_hours=5)

        resp = api.start_repair(ro["id"], TECH)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_repair_order(ro["id"])["status"] == "RECEIVED"

    def test_start_repair_blocked_while_quote_still_draft(self, api):
        """PRD §3.7: "With an approved quote behind it, a `Technician` starts repair, moving the order `AUTHORIZED` → `IN_REPAIR`; the precondition is that an `APPROVED` quote exists for the order, and without one the transition is rejected with `ERR_INVALID_STATE`."

        Design: Difficulty/cross_entity_state_dependency/start_repair_requires_approved_quote
        """
        shop = setup_quote_in_progress_shop()
        # A quote exists but is only DRAFT — never issued or approved.
        create_quote_for_ro(shop["ro"]["id"], shop["window"]["id"], labor_hours=2)

        resp = api.start_repair(shop["ro"]["id"], TECH)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_repair_order(shop["ro"]["id"])["status"] == "QUOTE_IN_PROGRESS"

    def test_start_repair_blocked_while_quote_issued_not_approved(self, api):
        """PRD §3.7: "With an approved quote behind it, a `Technician` starts repair, moving the order `AUTHORIZED` → `IN_REPAIR`; the precondition is that an `APPROVED` quote exists for the order, and without one the transition is rejected with `ERR_INVALID_STATE`."

        Design: Difficulty/cross_entity_state_dependency/start_repair_requires_approved_quote
        """
        shop = setup_quote_in_progress_shop()
        quote = create_quote_for_ro(shop["ro"]["id"], shop["window"]["id"], labor_hours=2)
        issue_quote(quote["id"])

        resp = api.start_repair(shop["ro"]["id"], TECH)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_repair_order(shop["ro"]["id"])["status"] == "QUOTE_IN_PROGRESS"


class TestInspectionReports:
    def test_finalize_bubbles_order_to_quote_in_progress(self, api):
        """PRD §3.4: "Finalization is permitted only while the order is still `IN_INSPECTION`, and it automatically drives the order `IN_INSPECTION` → `QUOTE_IN_PROGRESS`, incrementing the repair order's `version` by one."
        PRD §2.5: "Every repair order state transition — including the automatic transitions triggered by a finalized inspection report, an approved quote, a recorded test run, or an issued or voided certification — increments the repair order's `version` by one and refreshes its `updated_at`."

        Design: Corner/state_machines/inspection_finalize_bubbles_ro_to_quote_in_progress
        """
        customer = create_customer(name="Laredo Gas", account_number="LG-210",
                                   credit_limit_cents=99999999, warranty_terms_days=365)
        asset = create_asset(customer["id"], serial_number="V-2101")
        ro = create_repair_order(customer["id"], asset["id"], estimated_bay_hours=5)
        created_version = ro["version"]
        get_success_data(api_client.start_teardown(ro["id"], IC))
        report = get_success_data(api_client.create_inspection_report(
            ro["id"], create_inspection_report_payload(), INSPECTOR))

        finalized = get_success_data(api_client.finalize_inspection_report(report["id"], INSPECTOR))
        assert_inspection_report(finalized)
        assert finalized["report_status"] == "FINALIZED"

        after = get_repair_order(ro["id"])
        assert after["status"] == "QUOTE_IN_PROGRESS"
        assert after["version"] == created_version + 2, (
            "start-teardown and the finalize-driven transition each increment version"
        )

    def test_duplicate_inspection_report_rejected(self, api):
        """PRD §3.4: "One repair order carries at most one inspection report; a second authoring attempt against the same order is rejected with `ERR_REPORT_ALREADY_EXISTS`, so listing an order's reports returns zero or one element."

        Design: Corner/state_machines/duplicate_inspection_report_rejected
        """
        customer = create_customer(name="Mesilla", account_number="ME-220",
                                   credit_limit_cents=99999999, warranty_terms_days=365)
        asset = create_asset(customer["id"], serial_number="V-2201")
        ro = create_repair_order(customer["id"], asset["id"], estimated_bay_hours=5)
        start_teardown(ro["id"])
        first = get_success_data(api_client.create_inspection_report(
            ro["id"], create_inspection_report_payload(findings_summary="first"),
            INSPECTOR))

        dup = api_client.create_inspection_report(
            ro["id"], create_inspection_report_payload(findings_summary="second"),
            INSPECTOR)
        validate_error(dup, ApiErrorId.ERR_REPORT_ALREADY_EXISTS)

        listing = get_success_data(api_client.list_inspection_reports(ro["id"], SM))
        assert isinstance(listing, list) and len(listing) == 1
        assert listing[0]["id"] == first["id"]

    def test_finalize_finalized_report_returns_invalid_state(self, api):
        """PRD §3.4: "Finalizing the report moves it `DRAFT` → `FINALIZED`, from which it is immutable — no further writes are accepted."
        PRD §2.6: "5. **State validity** — the target entity must be in a valid from-state for the requested transition, terminal states are locked, and the quote-creation version check must match (`ERR_INVALID_STATE`, HTTP 409; the version mismatch carries `ERR_STALE_VERSION`, HTTP 412, on quote creation)."

        Design: Corner/state_machines/finalize_finalized_report_returns_invalid_state
        """
        customer = create_customer(name="Nogales", account_number="NO-230",
                                   credit_limit_cents=99999999, warranty_terms_days=365)
        asset = create_asset(customer["id"], serial_number="V-2301")
        ro = create_repair_order(customer["id"], asset["id"], estimated_bay_hours=5)
        start_teardown(ro["id"])
        report = author_and_finalize_report(ro["id"])

        again = api_client.finalize_inspection_report(report["id"], INSPECTOR)
        validate_error(again, ApiErrorId.ERR_INVALID_STATE)

        listing = get_success_data(api_client.list_inspection_reports(ro["id"], SM))
        assert listing[0]["report_status"] == "FINALIZED", "report remains FINALIZED"


class TestTerminalLockdown:
    def test_cancel_closed_repair_order_rejected(self, api):
        """PRD §3.9: "Terminal states lock: nothing leaves `CLOSED` or `CANCELLED`, and attempts to act on them are rejected with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/cancel_closed_repair_order_terminal_lockdown
        """
        shop = setup_closed_shop()
        assert shop["ro"]["status"] == "CLOSED"

        resp = api.cancel_repair_order(shop["ro"]["id"], IC)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_repair_order(shop["ro"]["id"])["status"] == "CLOSED"

    def test_approve_declined_quote_terminal_lockdown(self, api):
        """PRD §3.6: "Declining moves it `ISSUED` → `DECLINED` and cascades the repair order `QUOTE_IN_PROGRESS` → `CANCELLED`, carrying the cancellation's own side effects — notably the release of any pool reservation (§3.9)."
        PRD §3.5: "A quote's full status vocabulary is `DRAFT`, `ISSUED`, `REVISION_REQUESTED`, `APPROVED`, `DECLINED`, `EXPIRED`, `SUPERSEDED`, and `CANCELLED`, the last five terminal."
        PRD §2.6: "5. **State validity** — the target entity must be in a valid from-state for the requested transition, terminal states are locked, and the quote-creation version check must match (`ERR_INVALID_STATE`, HTTP 409; the version mismatch carries `ERR_STALE_VERSION`, HTTP 412, on quote creation)."

        Design: Corner/state_machines/approve_declined_quote_terminal_lockdown
        """
        shop = setup_quote_in_progress_shop()
        quote = issue_quote_for(shop)
        declined = get_success_data(api_client.decline_quote(
            quote["id"], make_customer_headers(shop["customer"]["id"])))
        assert declined["status"] == "DECLINED"
        assert get_repair_order(shop["ro"]["id"])["status"] == "CANCELLED"

        resp = api_client.approve_quote(
            quote["id"], make_customer_headers(shop["customer"]["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_success_data(api_client.get_quote(quote["id"], SM))["status"] == "DECLINED"
        assert get_repair_order(shop["ro"]["id"])["status"] == "CANCELLED"
