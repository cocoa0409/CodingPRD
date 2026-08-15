"""Quote lifecycle: version pinning, TTL expiry, fiscal gate, revision/cancel
cascades, and teardown seal-kit override revalidation (PRD §3.3-3.4)."""
from test_helpers import (
    ADMIN,
    ADVISOR,
    ApiErrorId,
    approve_quote,
    begin_teardown,
    create_customer,
    create_cylinder,
    create_inventory_item,
    create_seal_kit,
    create_shop,
    create_teardown_report_payload,
    draft_quote,
    file_findings,
    get_success_data,
    make_customer_headers,
    make_technician_headers,
    open_work_order,
    send_quote,
    setup_approved,
    setup_master_data,
    setup_quote_draft,
    setup_quote_sent,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestTeardownVersionPinning:
    def test_send_rejected_after_teardown_revision(self, api):
        """PRD §3.3: "The revision payload carries
        `expected_teardown_report_version` per §2.6 plus any subset of the
        findings fields to change, increments the report's `version` by one, and
        has a deliberate downstream effect: any `DRAFT` quote pinned to an older
        report version is now stale, and sending it will fail with
        `ERR_TEARDOWN_STALE`."

        Design: Difficulty/cross_entity_state_dependency/quote_send_requires_fresh_teardown_pin
        """
        sc = setup_quote_draft()
        quote = draft_quote(sc.work_order)
        assert quote["pinned_teardown_version"] == 1
        revised = get_success_data(
            api.patch_teardown_report(
                sc.report["id"],
                {"expected_teardown_report_version": sc.report["version"],
                 "estimated_labor_hours": 4.0},
                make_technician_headers(sc.tech["id"]),
            )
        )
        assert revised["version"] == 2
        resp = api.send_quote(quote["id"], ADVISOR)
        validate_error(resp, ApiErrorId.ERR_TEARDOWN_STALE)
        quote_after = get_success_data(api.get_quote(quote["id"], ADVISOR))
        assert quote_after["status"] == "DRAFT"
        assert quote_after["pinned_teardown_version"] == 1

    def test_quote_drafted_after_revision_pins_current_version(self, api):
        """PRD §3.4: "Sending requires the work order to be in `QUOTE_DRAFT` —
        otherwise `ERR_INVALID_STATE` — and requires the quote's
        `pinned_teardown_version` to equal the teardown report's current
        `version`; a quote pinned to a superseded revision of the findings is
        rejected with `ERR_TEARDOWN_STALE`."

        Design: Difficulty/cross_entity_state_dependency/quote_send_requires_fresh_teardown_pin
        """
        sc = setup_quote_draft()
        get_success_data(
            api.patch_teardown_report(
                sc.report["id"],
                {"expected_teardown_report_version": sc.report["version"],
                 "estimated_labor_hours": 4.0},
                make_technician_headers(sc.tech["id"]),
            )
        )
        quote = draft_quote(sc.work_order)
        assert quote["pinned_teardown_version"] == 2
        sent = validate_success(api.send_quote(quote["id"], ADVISOR))
        assert sent["status"] == "SENT"
        wo = get_success_data(api.get_work_order(sc.work_order["id"], ADVISOR))
        assert wo["status"] == "QUOTE_SENT"


class TestValidationPriorityOnApprove:
    def test_approving_approved_quote_reports_state_not_fiscal(self, api):
        """PRD §2.9: "Validations are applied to every request in a fixed
        priority order, and an earlier failure masks every later one — the
        client always sees the first failing check's error, never a later
        check's."
        PRD §2.9: "Because of this ordering, a credit-limit failure is reported
        only when every shape, identity, state, safety, temporal, structural,
        and pinning check has already passed, and a stale-teardown rejection is
        reported only after all state and structural checks have passed."
        PRD §3.4: "an approval aimed at a quote that is not `SENT` — already
        approved, revised, superseded, expired, or rejected — is rejected with
        `ERR_QUOTE_NOT_APPROVABLE`."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_quote_approve
        """
        # Approval fires the material cascade (PRD §3.4), which allocates stock
        # per §3.5 — rod inventory must exist or approval fails ERR_NO_STOCK_FITS.
        sc = setup_approved(customer_overrides={"credit_limit_cents": 150000})
        # 95896 <= 150000 passed on the first approve.
        # Second approve: state guard (not SENT) AND fiscal guard
        # (95896 open + 95896 > 150000) both fail; the earlier state guard wins.
        resp = api.approve_quote(sc.quote["id"], make_customer_headers(sc.customer["id"]))
        validate_error(resp, ApiErrorId.ERR_QUOTE_NOT_APPROVABLE)
        assert resp.status_code == 409

    def test_masked_rejection_leaves_quote_and_work_order_unchanged(self, api):
        """PRD §2.9: "Validations are applied to every request in a fixed
        priority order, and an earlier failure masks every later one — the
        client always sees the first failing check's error, never a later
        check's."
        PRD §3.4: "The quote moves from `SENT` to `APPROVED`, the work order
        moves from `QUOTE_SENT` to `APPROVED`, and the system automatically
        creates one `OPEN` stock reservation for the rod when the teardown's
        `rod_needed` is set"

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_quote_approve
        """
        # setup_approved stocks rod inventory so the approval cascade (PRD
        # §3.4/§3.5) can allocate; the first approve then succeeds.
        sc = setup_approved(customer_overrides={"credit_limit_cents": 150000})
        resp = api.approve_quote(sc.quote["id"], make_customer_headers(sc.customer["id"]))
        validate_error(resp, ApiErrorId.ERR_QUOTE_NOT_APPROVABLE)
        quote = get_success_data(api.get_quote(sc.quote["id"], ADVISOR))
        assert quote["status"] == "APPROVED"
        wo = get_success_data(api.get_work_order(sc.work_order["id"], ADVISOR))
        assert wo["status"] == "APPROVED"


class TestQuoteCollectionGuards:
    def test_second_quote_while_draft_exists_rejected(self, api):
        """PRD §3.3: "At most one quote per work order may be in `DRAFT` or
        `SENT`; drafting while another such quote exists is rejected with
        `ERR_ACTIVE_QUOTE_EXISTS`."

        Design: Corner/validations/second_quote_while_draft_exists_rejected
        """
        sc = setup_quote_draft()
        draft_quote(sc.work_order)
        resp = api.create_quote({"work_order_id": sc.work_order["id"]}, ADVISOR)
        validate_error(resp, ApiErrorId.ERR_ACTIVE_QUOTE_EXISTS)
        _data, meta = validate_paginated(
            api.list_quotes(ADVISOR, params={"work_order_id": sc.work_order["id"]})
        )
        assert meta["total_count"] == 1

    def test_teardown_seal_kit_override_revalidated(self, api):
        """PRD §3.3: "When an override kit is named, its compatibility with the
        cylinder is re-validated under the same rules as registration, with
        `ERR_SEAL_KIT_INCOMPATIBLE` on failure."

        Design: Corner/validations/teardown_seal_kit_override_revalidated
        """
        md = setup_master_data()
        wide_kit = create_seal_kit(
            kit_code="SK-120-PU", bore_min_mm=120, bore_max_mm=200,
            pressure_class_max="CLASS_5000",
            fluid_compat=["MINERAL_OIL", "PHOSPHATE_ESTER", "WATER_GLYCOL"],
            price_cents=32000, material="PU",
        )
        cylinder = create_cylinder(md.customer["id"], md.kit["id"], serial_number="CYL-V07")
        wo = open_work_order(cylinder["id"], tier="EXPEDITE", promised_hours=30)
        begin_teardown(wo, md.tech)
        payload = create_teardown_report_payload(
            wo["id"], rod_needed=False, tube_needed=False, honing_passes=0,
            estimated_labor_hours=1.0,
        )
        payload.pop("rod_cut_length_mm", None)
        payload["seal_kit_id"] = wide_kit["id"]  # override: bore range 120-200 vs bore 80
        resp = api.create_teardown_report(payload, make_technician_headers(md.tech["id"]))
        validate_error(resp, ApiErrorId.ERR_SEAL_KIT_INCOMPATIBLE)
        wo_after = get_success_data(api.get_work_order(wo["id"], ADVISOR))
        assert wo_after["status"] == "TEARDOWN"


class TestQuoteExpiry:
    def test_approve_quote_after_ttl_expires_it(self, api):
        """PRD §3.4: "Expiry is lazy: there is no background sweep, but an
        approval attempt arriving after `sent_at` plus the lifetime flips the
        quote to `EXPIRED` and the attempt fails with `ERR_QUOTE_EXPIRED`."
        PRD §2.10: "A sent quote lives for `quote_ttl_hours` (default 168 hours
        — one week)."

        Design: Corner/validations/approve_quote_after_ttl_expires_it
        """
        sc = setup_quote_sent(rod_needed=False, honing_passes=0, estimated_labor_hours=1.0)
        # sent_at = 2026-08-01T00:00:00Z (logical clock); advance 169h past TTL.
        get_success_data(api.set_clock({"to_iso8601": "2026-08-08T01:00:00Z"}, ADMIN))
        resp = api.approve_quote(sc.quote["id"], make_customer_headers(sc.customer["id"]))
        validate_error(resp, ApiErrorId.ERR_QUOTE_EXPIRED)
        quote = get_success_data(api.get_quote(sc.quote["id"], ADVISOR))
        assert quote["status"] == "EXPIRED"
        wo = get_success_data(api.get_work_order(sc.work_order["id"], ADVISOR))
        assert wo["status"] == "QUOTE_SENT"


class TestCreditExposure:
    def test_credit_limit_inclusive_boundary_passes(self, api):
        """PRD §3.4: "The boundary is inclusive — exposure exactly equal to the
        limit passes — and a breach is rejected with
        `ERR_CREDIT_LIMIT_EXCEEDED`."

        Design: Corner/calculations/credit_limit_inclusive_boundary_passes
        """
        sc = setup_quote_sent(customer_overrides={"credit_limit_cents": 95896})
        assert sc.quote["provisional_total_cents"] == 95896
        # Approval fires the material cascade (PRD §3.4), allocated per §3.5;
        # rod stock must exist or approval is rejected with ERR_NO_STOCK_FITS.
        create_inventory_item()
        approved = validate_success(
            api.approve_quote(sc.quote["id"], make_customer_headers(sc.customer["id"]))
        )
        assert approved["status"] == "APPROVED"

    def test_second_approval_over_credit_limit_rejected(self, api):
        """PRD §3.4: "Approval then runs the fiscal exposure check: the open
        exposure is the sum of `provisional_total_cents` over the customer's
        `APPROVED` quotes whose work orders are not `CLOSED`, `CANCELLED`, or
        `SCRAPPED`, and that open exposure plus the provisional total of the
        quote being approved must not exceed the customer's
        `credit_limit_cents`."

        Design: Corner/validations/second_approval_over_credit_limit_rejected
        """
        md = setup_master_data(customer_overrides={"credit_limit_cents": 150000})
        # Each approval cascade cuts 503mm of 45mm chrome rod (PRD §3.4/§3.5);
        # the first cut leaves 497mm, short of the second cut — two pieces.
        create_inventory_item()
        create_inventory_item()
        cyl1 = create_cylinder(md.customer["id"], md.kit["id"], serial_number="CYL-V11")
        cyl2 = create_cylinder(md.customer["id"], md.kit["id"], serial_number="CYL-V12")
        wo1 = open_work_order(cyl1["id"], tier="EXPEDITE", promised_hours=30)
        begin_teardown(wo1, md.tech)
        file_findings(wo1, md.tech)  # rod 500, honing 1, est 2.5 -> quote 95896
        q1 = send_quote(draft_quote(wo1))
        approve_quote(q1, md.customer)  # open exposure now 95896
        wo2 = open_work_order(cyl2["id"], tier="EXPEDITE", promised_hours=30)
        begin_teardown(wo2, md.tech)
        file_findings(wo2, md.tech)
        q2 = send_quote(draft_quote(wo2))
        assert q2["provisional_total_cents"] == 95896
        # 95896 open + 95896 new = 191792 > 150000.
        resp = api.approve_quote(q2["id"], make_customer_headers(md.customer["id"]))
        validate_error(resp, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED)
        assert resp.status_code == 402
        q2_after = get_success_data(api.get_quote(q2["id"], ADVISOR))
        assert q2_after["status"] == "SENT"
        wo2_after = get_success_data(api.get_work_order(wo2["id"], ADVISOR))
        assert wo2_after["status"] == "QUOTE_SENT"


class TestCancelCascade:
    def test_work_order_cancel_supersedes_sent_quote(self, api):
        """PRD §3.2: "Cancelling from `QUOTE_DRAFT` supersedes the work order's
        `DRAFT` quote, and cancelling from `QUOTE_SENT` supersedes its `SENT`
        quote; cancelling from `INTAKE`, `TEARDOWN`, or `REVISION_REQUESTED`
        touches no quote."
        PRD §3.4: "an approval aimed at a quote that is not `SENT` — already
        approved, revised, superseded, expired, or rejected — is rejected with
        `ERR_QUOTE_NOT_APPROVABLE`."

        Design: Corner/state_machines/work_order_cancel_supersedes_sent_quote
        """
        sc = setup_quote_sent(rod_needed=False, honing_passes=0, estimated_labor_hours=1.0)
        cancelled = validate_success(
            api.cancel_work_order(
                sc.work_order["id"],
                make_customer_headers(sc.customer["id"]),
                payload={"reason": "customer backed out"},
            )
        )
        assert cancelled["status"] == "CANCELLED"
        quote = get_success_data(api.get_quote(sc.quote["id"], ADVISOR))
        assert quote["status"] == "SUPERSEDED"
        resp = api.approve_quote(sc.quote["id"], make_customer_headers(sc.customer["id"]))
        validate_error(resp, ApiErrorId.ERR_QUOTE_NOT_APPROVABLE)
