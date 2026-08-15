"""File lifecycle: activation side effects, compliance audit, close/archive, and
the termination cascade."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    api_client, ApiErrorId, TEST_USERS,
    assert_invoice_invariants,
    create_coordinator_payload, create_template_payload,
    create_subscription_payload, create_file_payload, create_purchase_file_payload,
    make_coordinator, make_agent, make_coordinator_with_seller,
    make_coordinator_with_buyer_seller, make_template, make_subscription,
    make_file, activate_file, make_active_listing_file, make_active_purchase_file,
    make_closed_listing_file, get_milestone_by_name, get_deadline_by_kind,
    list_milestones_for_file, list_reminders_for_deadline, get_file_invoice,
    get_file_version, make_routed_amendment, make_fully_signed_amendment,
    get_file_closing_verification, clear_to_close, request_close, run_audit,
)


class TestActivationSideEffects:
    def test_immediate_visibility_of_activation_side_effects(self):
        """PRD §3.4: "On success, activation pins `template_id` and the template's
        current `template_version` onto the file, then instantiates the working set.
        One `Milestone` is created per entry in the template's `milestone_defs`,
        copying `name`, `offset_days`, and `mandatory` verbatim and computing
        `due_date` as the file's `effective_date` plus `offset_days` calendar days.
        Three deadlines are considered: an `INSPECTION` deadline from
        `inspection_offset_days`, an `APPRAISAL` deadline from `appraisal_offset_days`,
        and a `FINANCING` deadline only when `financing_offset_days` was provided."
        PRD §3.4: "Finally, activation computes `fee_estimate_cents` and creates the
        file's one-and-only `Invoice` in `DRAFT` with the estimate's line items."

        Design: Corner/consistency_model/immediate_visibility_of_activation_side_effects
        """
        coord, coord_h, seller, _seller_h = make_coordinator_with_seller()
        tmpl = make_template(
            state_code="TX", contract_type="LISTING_ONLY",
            milestone_defs=[
                {"name": "Earnest Money", "offset_days": 3, "mandatory": True},
                {"name": "Listing Paperwork", "offset_days": 5, "mandatory": False},
            ],
            required_doc_types=[],
        )
        f = make_file(coord_h, seller["id"], closing_date="2026-08-31")
        activated = validate_success(api_client.activate_file(f["id"], coord_h))
        assert activated["status"] == "ACTIVE"
        # The instant activate returns, follow-up reads must show the instantiated set.
        milestones = list_milestones_for_file(coord_h, f["id"])
        assert len(milestones) == 2, f"expected 2 milestones, got {len(milestones)}"
        by_name = {m["name"]: m for m in milestones}
        assert by_name["Earnest Money"]["due_date"] == "2026-08-06"
        assert by_name["Listing Paperwork"]["due_date"] == "2026-08-08"
        assert by_name["Earnest Money"]["mandatory"] is True
        deadlines = get_success_data(api_client.list_deadlines(coord_h, params={"limit": 100}))
        assert len(deadlines) == 2, (
            f"cash file must have exactly INSPECTION and APPRAISAL deadlines "
            f"(no FINANCING); got {len(deadlines)}"
        )
        by_kind = {d["kind"]: d for d in deadlines}
        assert by_kind["INSPECTION"]["due_date"] == "2026-08-10"
        assert by_kind["APPRAISAL"]["due_date"] == "2026-08-17"
        assert "FINANCING" not in by_kind
        invoices = get_success_data(api_client.list_invoices(coord_h, params={"limit": 10}))
        assert len(invoices) == 1, "activation must create exactly one invoice"
        assert invoices[0]["status"] == "DRAFT"
        assert invoices[0]["total_cents"] == 29500

    def test_activate_without_published_template_not_found(self):
        """PRD §3.4: "Five preconditions hold: an `ACTIVE` checklist template must
        exist for the file's pair of `state_code` and `contract_type`
        (`ERR_TEMPLATE_NOT_FOUND`); when the billing model is `SUBSCRIPTION`, the
        referenced subscription must exist, be `ACTIVE`, and belong to the acting
        coordinator (`ERR_SUBSCRIPTION_INACTIVE`); `closing_date` must not be before
        the current clock date (`ERR_CLOSING_DATE_IN_PAST`); and the closing calendar
        must have room — no other file of the same coordinator in `ACTIVE` or
        `PENDING_CLOSE` may have a `closing_date` within one day of this file's,
        meaning a difference of 0 or 1 day in either direction conflicts with
        `ERR_CLOSING_DATE_CONFLICT` while 2 or more days is allowed."

        Design: Corner/validations/activate_without_published_template_not_found
        """
        coord, coord_h, seller, _seller_h = make_coordinator_with_seller()
        f = make_file(coord_h, seller["id"], state_code="WA")
        resp = api_client.activate_file(f["id"], coord_h)
        validate_error(resp, ApiErrorId.ERR_TEMPLATE_NOT_FOUND)
        fetched = validate_success(api_client.get_file(f["id"], coord_h))
        assert fetched["status"] == "DRAFT", "failed activation must leave the file DRAFT"
        milestones = list_milestones_for_file(coord_h, f["id"])
        assert milestones == [], "failed activation must not instantiate milestones"
        invoices = get_success_data(api_client.list_invoices(coord_h, params={"limit": 10}))
        assert invoices == [], "failed activation must not create an invoice"


class TestTerminationCascade:
    def test_terminated_file_lockdown_rejected(self):
        """PRD §3.9: "Terminating a file in `ACTIVE` or `PENDING_CLOSE` moves it to
        `TERMINATED`; targeting a file already in a terminal state is
        `ERR_FILE_ALREADY_TERMINAL`."
        PRD §3.3: "A new file is created in `DRAFT`. Its full lifecycle is
        `DRAFT → ACTIVE → PENDING_CLOSE → CLOSED → ARCHIVED`, with termination
        possible from `ACTIVE` or `PENDING_CLOSE` into `TERMINATED`. `ARCHIVED` and
        `TERMINATED` are terminal."

        Design: Corner/state_machines/terminated_file_lockdown_rejected
        """
        scen = make_active_listing_file()
        coord_h, file_id = scen["coord_h"], scen["file"]["id"]
        first = validate_success(
            api_client.terminate_file(file_id, coord_h, payload={"reason": "seller withdrew"})
        )
        assert first["status"] == "TERMINATED"
        resp = api_client.terminate_file(file_id, coord_h, payload={"reason": "second attempt"})
        validate_error(resp, ApiErrorId.ERR_FILE_ALREADY_TERMINAL)
        fetched = validate_success(api_client.get_file(file_id, coord_h))
        assert fetched["status"] == "TERMINATED"

    def test_file_termination_deadline_reminder_cascade(self):
        """PRD §3.9: "Cascade one: every milestone in `PENDING`, `IN_PROGRESS`, or
        `OVERDUE` moves to `CANCELLED`. Cascade two: every deadline in `PENDING` moves
        to `CANCELLED`, and that cancellation itself cancels all of the deadline's
        `QUEUED` reminders. Cascade three: every amendment in `DRAFT`, `ROUTED`,
        `PARTIALLY_SIGNED`, or `FULLY_SIGNED` moves to `VOIDED`, and that voiding
        itself voids all of the amendment's `PENDING` signature requests. Cascade
        four: every communication entry in `OPEN` or `ESCALATED` moves to `RESOLVED`,
        and the file's `open_escalation_count` is reset to 0. Cascade five: an invoice
        still in `DRAFT` moves to `VOIDED` with `TERMINATION_CREDIT` lines appended —
        one per existing charge line, each with an amount equal to the negated charge
        amount — so the net line sum is 0 and both `subtotal_cents` and `total_cents`
        become 0."
        PRD §3.9: "One conditional release follows: when the file's billing model is
        `SUBSCRIPTION` and no document on the file ever reached `ACCEPTED`, the
        subscription's `included_files_used` is decremented by 1 and the
        subscription's `version` is bumped by 1 — the slot is handed back."

        Design: Difficulty/transitive_cascade/file_termination_deadline_reminder_cascade
        """
        coord, coord_h, buyer, buyer_h, seller, seller_h = make_coordinator_with_buyer_seller()
        make_template(
            state_code="TX", contract_type="PURCHASE_SALE",
            milestone_defs=[
                {"name": "Earnest Money", "offset_days": 3, "mandatory": True},
                {"name": "Inspection Period", "offset_days": 7, "mandatory": True},
            ],
            required_doc_types=["EXECUTED_CONTRACT"],
        )
        sub = make_subscription(coord_h, included_files_quota=2)
        f = make_file(
            coord_h, seller["id"], buyer_agent_id=buyer["id"],
            billing_model="SUBSCRIPTION", contract_type="PURCHASE_SALE",
            financing_offset_days=21, subscription=sub,
        )
        activate_file(coord_h, f["id"])
        am = make_routed_amendment(coord_h, f["id"], "2026-08-10", "2026-08-15")

        resp = api_client.terminate_file(f["id"], coord_h, payload={"reason": "buyer walked"})
        terminated = validate_success(resp)
        assert terminated["status"] == "TERMINATED"

        milestones = list_milestones_for_file(coord_h, f["id"])
        assert len(milestones) == 2
        assert all(m["status"] == "CANCELLED" for m in milestones), \
            "termination must cancel every PENDING/IN_PROGRESS/OVERDUE milestone"

        deadlines = get_success_data(api_client.list_deadlines(coord_h, params={"limit": 100}))
        assert len(deadlines) == 3
        cancelled_reminders = 0
        for dl in deadlines:
            assert dl["status"] == "CANCELLED", f"deadline {dl['kind']} must be CANCELLED"
            cancelled_reminders += len(list_reminders_for_deadline(coord_h, dl["id"], status="CANCELLED"))
        assert cancelled_reminders == 9, (
            f"3 deadlines x 3 reminders must all be CANCELLED; got {cancelled_reminders}"
        )

        am_after = validate_success(api_client.get_amendment(am["id"], coord_h))
        assert am_after["status"] == "VOIDED"
        sigs = get_success_data(
            api_client.list_signature_requests(coord_h, params={"amendment_id": am["id"], "limit": 100})
        )
        assert len(sigs) == 2
        assert all(s["status"] == "VOIDED" for s in sigs), \
            "termination must void the routed amendment's PENDING signature requests"

        invoice = get_file_invoice(coord_h, f["id"])
        assert invoice["status"] == "VOIDED"
        assert invoice["total_cents"] == 0

        sub_after = validate_success(api_client.get_subscription(sub["id"], coord_h))
        assert sub_after["included_files_used"] == 0, (
            f"eligible slot release must decrement included_files_used to 0; "
            f"got {sub_after['included_files_used']}"
        )

class TestSubscriptionConservation:
    def test_subscription_slot_conserved_across_activate_terminate(self):
        """PRD §3.2: "The `included_files_used` counter is the subscription's
        committed-slot ledger: it increases by 1 the moment a file is created under
        the subscription and decreases by 1 only on an eligible termination release
        described in §3.6."
        PRD §3.9: "One conditional release follows: when the file's billing model is
        `SUBSCRIPTION` and no document on the file ever reached `ACCEPTED`, the
        subscription's `included_files_used` is decremented by 1 and the
        subscription's `version` is bumped by 1 — the slot is handed back."

        Design: Difficulty/compensating_invariant/subscription_slot_conserved_across_activate_terminate
        """
        coord, coord_h, buyer, buyer_h, seller, seller_h = make_coordinator_with_buyer_seller()
        make_template(
            state_code="TX", contract_type="PURCHASE_SALE",
            milestone_defs=[{"name": "Earnest Money", "offset_days": 3, "mandatory": True}],
            required_doc_types=["EXECUTED_CONTRACT"],
        )
        sub = make_subscription(coord_h, included_files_quota=2)
        assert sub["included_files_used"] == 0
        f = make_file(
            coord_h, seller["id"], buyer_agent_id=buyer["id"],
            billing_model="SUBSCRIPTION", contract_type="PURCHASE_SALE",
            financing_offset_days=21, subscription=sub,
        )
        activate_file(coord_h, f["id"])
        mid = validate_success(api_client.get_subscription(sub["id"], coord_h))
        assert mid["included_files_used"] == 1, \
            "file creation under the subscription must commit one slot"
        validate_success(api_client.terminate_file(f["id"], coord_h,
                                                   payload={"reason": "mutual release"}))
        end = validate_success(api_client.get_subscription(sub["id"], coord_h))
        assert end["included_files_used"] == 0, (
            f"forward(+1) + compensating(-1) must restore the pre-cycle value 0; "
            f"got {end['included_files_used']}"
        )

    def test_invoice_net_receivable_conserved_across_activate_terminate(self):
        """PRD §3.9: "Cascade five: an invoice still in `DRAFT` moves to `VOIDED`
        with `TERMINATION_CREDIT` lines appended — one per existing charge line, each
        with an amount equal to the negated charge amount — so the net line sum is 0
        and both `subtotal_cents` and `total_cents` become 0."
        PRD §2.7: "All money amounts are integer cents; no fractional cents ever
        appear."

        Design: Difficulty/compensating_invariant/invoice_net_receivable_conserved_across_activate_terminate
        """
        scen = make_active_purchase_file(closing_date="2026-08-31",
                                         required_doc_types=["EXECUTED_CONTRACT"])
        coord_h, file_id = scen["coord_h"], scen["file"]["id"]
        invoice = get_file_invoice(coord_h, file_id)
        assert invoice["status"] == "DRAFT"
        assert invoice["subtotal_cents"] == 39500
        assert invoice["total_cents"] == 39500
        validate_success(api_client.terminate_file(file_id, coord_h,
                                                   payload={"reason": "inspection failed"}))
        after = validate_success(api_client.get_invoice(invoice["id"], coord_h))
        assert after["status"] == "VOIDED"
        assert_invoice_invariants(after)
        amounts = {line["label"]: line["amount_cents"] for line in after["line_items"]}
        assert amounts.get("BASE_FEE") == 39500
        assert amounts.get("TERMINATION_CREDIT") == -39500
        assert sum(line["amount_cents"] for line in after["line_items"]) == 0
        assert after["total_cents"] == 0


class TestFullLifecycle:
    def test_invoice_issue_pay_then_archive_happy_path(self):
        """PRD §3.8: "The close also rebuilds the file's invoice to its final line
        set."
        PRD §3.8: "On close, the rebuilt invoice moves from `DRAFT` to `ISSUED` with
        `issued_at` stamped."
        PRD §3.8: "Archival is the last step, moving `CLOSED → ARCHIVED`. The file
        must be `CLOSED` (`ERR_FILE_NOT_CLOSED`) and its invoice must be `PAID`
        (`ERR_INVOICE_UNPAID`, HTTP 402). Archival stamps `archived_at` with the
        current clock time and renders the file read-only: the post-close archive is
        immutable from then on."

        Design: Corner/endpoints/invoice_issue_pay_then_archive_happy_path
        """
        scen = make_closed_listing_file()
        coord_h, file_id = scen["coord_h"], scen["file"]["id"]
        invoice = scen["invoice"]
        assert scen["file"]["status"] == "CLOSED"
        assert invoice["status"] == "ISSUED", "close must auto-issue the invoice"
        assert invoice["total_cents"] == 29500, "LISTING_ONLY base, no amendments"
        assert invoice["issued_at"] is not None
        paid = validate_success(api_client.mark_invoice_paid(invoice["id"], coord_h))
        assert paid["status"] == "PAID"
        archived = validate_success(api_client.archive_file(file_id, coord_h))
        assert archived["status"] == "ARCHIVED"
        assert archived["archived_at"] is not None, "archive must stamp archived_at"

    def test_archive_with_unpaid_invoice_returns_402(self):
        """PRD §3.8: "Archival is the last step, moving `CLOSED → ARCHIVED`. The file
        must be `CLOSED` (`ERR_FILE_NOT_CLOSED`) and its invoice must be `PAID`
        (`ERR_INVOICE_UNPAID`, HTTP 402). Archival stamps `archived_at` with the
        current clock time and renders the file read-only: the post-close archive is
        immutable from then on."

        Design: Corner/errors/archive_with_unpaid_invoice_returns_402
        """
        scen = make_closed_listing_file()
        coord_h, file_id = scen["coord_h"], scen["file"]["id"]
        assert scen["invoice"]["status"] == "ISSUED", "invoice is ISSUED but not PAID"
        resp = api_client.archive_file(file_id, coord_h)
        validate_error(resp, ApiErrorId.ERR_INVOICE_UNPAID)
        fetched = validate_success(api_client.get_file(file_id, coord_h))
        assert fetched["status"] == "CLOSED", "a failed archive must leave the file CLOSED"


class TestValidationPriorityPairs:
    def test_archive_state_error_beats_fiscal_error(self):
        """PRD §2.5: "When several checks could reject the same request, the service
        evaluates them in a fixed order so the returned error is deterministic."
        PRD §2.5: "Sixth, state-machine legality (`ERR_FILE_NOT_DRAFT`,
        `ERR_FILE_NOT_ACTIVE`, `ERR_FILE_NOT_PENDING_CLOSE`, `ERR_FILE_NOT_CLOSED`,
        `ERR_FILE_ALREADY_TERMINAL`, `ERR_MILESTONE_INVALID_STATE`,
        `ERR_DEADLINE_INVALID_STATE`, `ERR_DOCUMENT_INVALID_STATE`,
        `ERR_AMENDMENT_INVALID_STATE`, `ERR_SIGNATURE_INVALID_STATE`,
        `ERR_COMMUNICATION_INVALID_STATE`, `ERR_TEMPLATE_INVALID_STATE`,
        `ERR_SUBSCRIPTION_INVALID_STATE`, `ERR_INVOICE_INVALID_STATE`)."
        PRD §2.5: "Eleventh, fiscal gates (`ERR_INVOICE_UNPAID`)."

        Design: Difficulty/priority_pair_validation_conflict/archive_state_error_beats_fiscal_error
        """
        scen = make_active_purchase_file(required_doc_types=["EXECUTED_CONTRACT"])
        coord_h, file_id = scen["coord_h"], scen["file"]["id"]
        invoice = get_file_invoice(coord_h, file_id)
        assert invoice["status"] == "DRAFT", "the invoice is also unpaid"
        resp = api_client.archive_file(file_id, coord_h)
        data = validate_error(resp, ApiErrorId.ERR_FILE_NOT_CLOSED)
        assert data["error_id"] == "ERR_FILE_NOT_CLOSED"
        assert data["error_id"] != "ERR_INVOICE_UNPAID", \
            "the state error (sixth) must win over the fiscal error (eleventh)"
        fetched = validate_success(api_client.get_file(file_id, coord_h))
        assert fetched["status"] == "ACTIVE"
        invoice_after = validate_success(api_client.get_invoice(invoice["id"], coord_h))
        assert invoice_after["status"] == "DRAFT"

    def test_amendment_temporal_error_beats_constraint_error(self):
        """PRD §2.5: "Eighth, temporal sanity (`ERR_CLOSING_DATE_IN_PAST`,
        `ERR_AMENDMENT_DATE_IN_PAST`, `ERR_INVALID_AMENDMENT_WINDOW`,
        `ERR_RESPONSE_DUE_IN_PAST`). Ninth, business constraints
        (`ERR_TEMPLATE_ALREADY_ACTIVE`, `ERR_SUBSCRIPTION_ALREADY_ACTIVE`,
        `ERR_AMENDMENT_IN_FLIGHT`, `ERR_AMENDMENT_WINDOW_OVERLAP`,
        `ERR_CLOSING_DATE_CONFLICT`, `ERR_MILESTONE_MANDATORY`)."
        PRD §3.6: "A `new_closing_date` in the past at creation is
        `ERR_AMENDMENT_DATE_IN_PAST`."

        Design: Difficulty/priority_pair_validation_conflict/amendment_temporal_error_beats_constraint_error
        """
        scen = make_active_purchase_file(required_doc_types=["EXECUTED_CONTRACT"])
        coord_h, file_id = scen["coord_h"], scen["file"]["id"]
        am_a = make_routed_amendment(coord_h, file_id, "2026-08-10", "2026-08-15")
        file_v2 = get_file_version(coord_h, file_id)
        resp = api_client.create_amendment(
            {
                "file_id": file_id,
                "expected_file_version": file_v2,
                "effective_from": "2026-08-12",
                "effective_to": "2026-08-18",
                "new_closing_date": "2026-07-20",
            },
            coord_h,
        )
        data = validate_error(resp, ApiErrorId.ERR_AMENDMENT_DATE_IN_PAST)
        assert data["error_id"] == "ERR_AMENDMENT_DATE_IN_PAST"
        assert data["error_id"] != "ERR_AMENDMENT_WINDOW_OVERLAP", \
            "the temporal error (eighth) must beat the constraint error (ninth)"
        amendments = get_success_data(api_client.list_amendments(coord_h, params={"limit": 100}))
        assert len(amendments) == 1, "the rejected amendment must not be persisted"
        assert amendments[0]["id"] == am_a["id"]


class TestClosingCalendarGap:
    def test_closing_calendar_min_gap_conflict(self):
        """PRD §3.4: "Five preconditions hold: an `ACTIVE` checklist template must
        exist for the file's pair of `state_code` and `contract_type`
        (`ERR_TEMPLATE_NOT_FOUND`); when the billing model is `SUBSCRIPTION`, the
        referenced subscription must exist, be `ACTIVE`, and belong to the acting
        coordinator (`ERR_SUBSCRIPTION_INACTIVE`); `closing_date` must not be before
        the current clock date (`ERR_CLOSING_DATE_IN_PAST`); and the closing calendar
        must have room — no other file of the same coordinator in `ACTIVE` or
        `PENDING_CLOSE` may have a `closing_date` within one day of this file's,
        meaning a difference of 0 or 1 day in either direction conflicts with
        `ERR_CLOSING_DATE_CONFLICT` while 2 or more days is allowed."

        Design: Difficulty/resource_temporal_overlap/closing_calendar_min_gap_conflict
        """
        coord, coord_h, seller, _seller_h = make_coordinator_with_seller()
        make_template(state_code="TX", contract_type="LISTING_ONLY")
        file_a = make_file(coord_h, seller["id"], closing_date="2026-08-20")
        activate_file(coord_h, file_a["id"])
        file_b = make_file(coord_h, seller["id"], closing_date="2026-08-21",
                           property_address="2 Oak Ave")
        file_c = make_file(coord_h, seller["id"], closing_date="2026-08-22",
                           property_address="3 Elm Dr")
        # 1 day away from the ACTIVE file's closing: conflicts.
        resp_b = api_client.activate_file(file_b["id"], coord_h)
        validate_error(resp_b, ApiErrorId.ERR_CLOSING_DATE_CONFLICT)
        b_after = validate_success(api_client.get_file(file_b["id"], coord_h))
        assert b_after["status"] == "DRAFT", "a conflicting activation must leave the file DRAFT"
        # Exactly 2 days away: allowed (the boundary is inclusive at 2).
        c_active = validate_success(api_client.activate_file(file_c["id"], coord_h))
        assert c_active["status"] == "ACTIVE"

    def test_closing_calendar_same_day_conflicts(self):
        """PRD §3.4: "Five preconditions hold: an `ACTIVE` checklist template must
        exist for the file's pair of `state_code` and `contract_type`
        (`ERR_TEMPLATE_NOT_FOUND`); when the billing model is `SUBSCRIPTION`, the
        referenced subscription must exist, be `ACTIVE`, and belong to the acting
        coordinator (`ERR_SUBSCRIPTION_INACTIVE`); `closing_date` must not be before
        the current clock date (`ERR_CLOSING_DATE_IN_PAST`); and the closing calendar
        must have room — no other file of the same coordinator in `ACTIVE` or
        `PENDING_CLOSE` may have a `closing_date` within one day of this file's,
        meaning a difference of 0 or 1 day in either direction conflicts with
        `ERR_CLOSING_DATE_CONFLICT` while 2 or more days is allowed."

        Design: Difficulty/resource_temporal_overlap/closing_calendar_min_gap_conflict
        """
        coord, coord_h, seller, _seller_h = make_coordinator_with_seller()
        make_template(state_code="TX", contract_type="LISTING_ONLY")
        file_a = make_file(coord_h, seller["id"], closing_date="2026-08-20")
        activate_file(coord_h, file_a["id"])
        # Difference 0: same closing day as the ACTIVE file.
        file_b = make_file(coord_h, seller["id"], closing_date="2026-08-20",
                           property_address="2 Oak Ave")
        resp = api_client.activate_file(file_b["id"], coord_h)
        validate_error(resp, ApiErrorId.ERR_CLOSING_DATE_CONFLICT)
        b_after = validate_success(api_client.get_file(file_b["id"], coord_h))
        assert b_after["status"] == "DRAFT"


class TestTerminationFromPendingClose:
    def test_termination_from_pending_close_cascades(self):
        """PRD §3.9: "Terminating a file in `ACTIVE` or `PENDING_CLOSE` moves it to
        `TERMINATED`; targeting a file already in a terminal state is
        `ERR_FILE_ALREADY_TERMINAL`."
        PRD §3.9: "Cascade five: an invoice still in `DRAFT` moves to `VOIDED` with
        `TERMINATION_CREDIT` lines appended — one per existing charge line, each with
        an amount equal to the negated charge amount — so the net line sum is 0 and
        both `subtotal_cents` and `total_cents` become 0."
        PRD §3.9: "One conditional release follows: when the file's billing model is
        `SUBSCRIPTION` and no document on the file ever reached `ACCEPTED`, the
        subscription's `included_files_used` is decremented by 1 and the
        subscription's `version` is bumped by 1 — the slot is handed back. If any
        document was accepted, the slot is forfeit. A `ClosingVerification` that
        already exists is left with its `overall_status` unchanged; the file is simply
        terminal."

        Design: Difficulty/transitive_cascade/file_termination_deadline_reminder_cascade
        """
        scen = make_active_listing_file(state_code="CO")
        coord_h, file_id = scen["coord_h"], scen["file"]["id"]
        run_audit(coord_h, file_id)
        ms = get_milestone_by_name(coord_h, file_id, "Listing Paperwork")
        api_client.waive_milestone(ms["id"], coord_h)
        request_close(coord_h, file_id)
        cv = get_file_closing_verification(coord_h, file_id)
        assert cv["overall_status"] == "PENDING"

        terminated = validate_success(
            api_client.terminate_file(file_id, coord_h, payload={"reason": "seller withdrew"})
        )
        assert terminated["status"] == "TERMINATED"
        invoice = get_file_invoice(coord_h, file_id)
        assert invoice["status"] == "VOIDED"
        assert invoice["subtotal_cents"] == 0
        assert invoice["total_cents"] == 0
        cv_after = validate_success(api_client.get_closing_verification(cv["id"], coord_h))
        assert cv_after["overall_status"] == "PENDING", \
            "the existing verification keeps its overall_status; the file is simply terminal"
        deadlines = get_success_data(api_client.list_deadlines(coord_h, params={"limit": 100}))
        assert all(d["status"] == "CANCELLED" for d in deadlines)


class TestArchivePrioritySecondForm:
    def test_archive_pending_close_unpaid_invoice_state_error_wins(self):
        """PRD §2.5: "When several checks could reject the same request, the service
        evaluates them in a fixed order so the returned error is deterministic."
        PRD §2.5: "Sixth, state-machine legality (`ERR_FILE_NOT_DRAFT`,
        `ERR_FILE_NOT_ACTIVE`, `ERR_FILE_NOT_PENDING_CLOSE`, `ERR_FILE_NOT_CLOSED`,
        `ERR_FILE_ALREADY_TERMINAL`, `ERR_MILESTONE_INVALID_STATE`,
        `ERR_DEADLINE_INVALID_STATE`, `ERR_DOCUMENT_INVALID_STATE`,
        `ERR_AMENDMENT_INVALID_STATE`, `ERR_SIGNATURE_INVALID_STATE`,
        `ERR_COMMUNICATION_INVALID_STATE`, `ERR_TEMPLATE_INVALID_STATE`,
        `ERR_SUBSCRIPTION_INVALID_STATE`, `ERR_INVOICE_INVALID_STATE`)."
        PRD §2.5: "Eleventh, fiscal gates (`ERR_INVOICE_UNPAID`)."
        PRD §3.8: "A coordinator may also issue a `DRAFT` invoice manually while the
        owning file is `ACTIVE` or `CLOSED` (otherwise `ERR_INVOICE_INVALID_STATE` or
        `ERR_FILE_NOT_ACTIVE`), and may mark an `ISSUED` invoice `PAID` (any other
        starting state: `ERR_INVOICE_INVALID_STATE`)."

        Design: Difficulty/priority_pair_validation_conflict/archive_state_error_beats_fiscal_error
        """
        scen = make_active_listing_file(state_code="CO")
        coord_h, file_id = scen["coord_h"], scen["file"]["id"]
        invoice = get_file_invoice(coord_h, file_id)
        # Manually issue while ACTIVE, then advance to PENDING_CLOSE: the invoice is
        # ISSUED but unpaid and the file is not CLOSED — both gates are violated.
        issued = validate_success(api_client.issue_invoice(invoice["id"], coord_h))
        assert issued["status"] == "ISSUED"
        run_audit(coord_h, file_id)
        ms = get_milestone_by_name(coord_h, file_id, "Listing Paperwork")
        api_client.waive_milestone(ms["id"], coord_h)
        request_close(coord_h, file_id)
        resp = api_client.archive_file(file_id, coord_h)
        data = validate_error(resp, ApiErrorId.ERR_FILE_NOT_CLOSED)
        assert data["error_id"] == "ERR_FILE_NOT_CLOSED"
        assert data["error_id"] != "ERR_INVOICE_UNPAID"
        fetched = validate_success(api_client.get_file(file_id, coord_h))
        assert fetched["status"] == "PENDING_CLOSE"


class TestTemporalBeatsConstraintSecondForm:
    def test_amendment_temporal_error_beats_overlap_with_effective_window(self):
        """PRD §2.5: "Eighth, temporal sanity (`ERR_CLOSING_DATE_IN_PAST`,
        `ERR_AMENDMENT_DATE_IN_PAST`, `ERR_INVALID_AMENDMENT_WINDOW`,
        `ERR_RESPONSE_DUE_IN_PAST`). Ninth, business constraints
        (`ERR_TEMPLATE_ALREADY_ACTIVE`, `ERR_SUBSCRIPTION_ALREADY_ACTIVE`,
        `ERR_AMENDMENT_IN_FLIGHT`, `ERR_AMENDMENT_WINDOW_OVERLAP`,
        `ERR_CLOSING_DATE_CONFLICT`, `ERR_MILESTONE_MANDATORY`)."
        PRD §3.6: "A `new_closing_date` in the past at creation is
        `ERR_AMENDMENT_DATE_IN_PAST`."

        Design: Difficulty/priority_pair_validation_conflict/amendment_temporal_error_beats_constraint_error
        """
        scen = make_active_purchase_file(required_doc_types=["EXECUTED_CONTRACT"])
        coord_h, file_id = scen["coord_h"], scen["file"]["id"]
        # Amendment A reaches EFFECTIVE with window [2026-08-10, 2026-08-15).
        am = make_fully_signed_amendment(
            coord_h, file_id,
            buyer_h=scen["buyer_h"], seller_h=scen["seller_h"],
            buyer_id=scen["buyer"]["id"], seller_id=scen["seller"]["id"],
            effective_from="2026-08-10", effective_to="2026-08-15",
            new_list_price_cents=44500000,
        )
        applied = validate_success(api_client.apply_amendment(am["id"], coord_h))
        assert applied["status"] == "EFFECTIVE"
        # B's window overlaps A's EFFECTIVE window AND its new_closing_date is in the
        # past; the temporal error (eighth) must beat the overlap error (ninth).
        resp = api_client.create_amendment(
            {
                "file_id": file_id,
                "expected_file_version": get_file_version(coord_h, file_id),
                "effective_from": "2026-08-12",
                "effective_to": "2026-08-18",
                "new_closing_date": "2026-07-20",
            },
            coord_h,
        )
        data = validate_error(resp, ApiErrorId.ERR_AMENDMENT_DATE_IN_PAST)
        assert data["error_id"] == "ERR_AMENDMENT_DATE_IN_PAST"
        assert data["error_id"] != "ERR_AMENDMENT_WINDOW_OVERLAP"
        amendments = get_success_data(api_client.list_amendments(coord_h, params={"limit": 100}))
        assert len(amendments) == 1, "the rejected amendment must not be persisted"


class TestCompensatingInvariantSecondForms:
    def test_slot_forfeit_when_document_was_accepted(self):
        """PRD §3.9: "One conditional release follows: when the file's billing model
        is `SUBSCRIPTION` and no document on the file ever reached `ACCEPTED`, the
        subscription's `included_files_used` is decremented by 1 and the
        subscription's `version` is bumped by 1 — the slot is handed back. If any
        document was accepted, the slot is forfeit."
        PRD §3.2: "The `included_files_used` counter is the subscription's
        committed-slot ledger: it increases by 1 the moment a file is created under
        the subscription and decreases by 1 only on an eligible termination release
        described in §3.6."

        Design: Difficulty/compensating_invariant/subscription_slot_conserved_across_activate_terminate
        """
        coord, coord_h, buyer, buyer_h, seller, seller_h = make_coordinator_with_buyer_seller()
        make_template(
            state_code="TX", contract_type="PURCHASE_SALE",
            milestone_defs=[{"name": "Earnest Money", "offset_days": 3, "mandatory": True}],
            required_doc_types=["EXECUTED_CONTRACT"],
        )
        sub = make_subscription(coord_h, included_files_quota=2)
        f = make_file(
            coord_h, seller["id"], buyer_agent_id=buyer["id"],
            billing_model="SUBSCRIPTION", contract_type="PURCHASE_SALE",
            financing_offset_days=21, subscription=sub,
        )
        activate_file(coord_h, f["id"])
        mid = validate_success(api_client.get_subscription(sub["id"], coord_h))
        assert mid["included_files_used"] == 1
        # A document reaches ACCEPTED before termination: the slot is forfeit.
        doc = get_success_data(api_client.create_document(
            {"file_id": f["id"], "doc_type": "EXECUTED_CONTRACT"}, coord_h
        ))
        api_client.submit_document(doc["id"], buyer_h)
        accepted = validate_success(api_client.accept_document(doc["id"], coord_h))
        assert accepted["status"] == "ACCEPTED"
        validate_success(api_client.terminate_file(f["id"], coord_h,
                                                   payload={"reason": "mutual release"}))
        end = validate_success(api_client.get_subscription(sub["id"], coord_h))
        assert end["included_files_used"] == 1, \
            "no release: a document reached ACCEPTED, so the slot is forfeit"

    def test_subscription_overage_invoice_voided_to_zero(self):
        """PRD §3.9: "Cascade five: an invoice still in `DRAFT` moves to `VOIDED`
        with `TERMINATION_CREDIT` lines appended — one per existing charge line, each
        with an amount equal to the negated charge amount — so the net line sum is 0
        and both `subtotal_cents` and `total_cents` become 0."
        PRD §3.8: "The `total_cents` is the subtotal minus the discount."

        Design: Difficulty/compensating_invariant/invoice_net_receivable_conserved_across_activate_terminate
        """
        coord, coord_h, buyer, buyer_h, seller, seller_h = make_coordinator_with_buyer_seller()
        make_template(
            state_code="TX", contract_type="PURCHASE_SALE",
            milestone_defs=[{"name": "Earnest Money", "offset_days": 3, "mandatory": True}],
            required_doc_types=["EXECUTED_CONTRACT"],
        )
        sub = make_subscription(coord_h, included_files_quota=0, overage_fee_cents=34900)
        f = make_file(
            coord_h, seller["id"], buyer_agent_id=buyer["id"],
            billing_model="SUBSCRIPTION", contract_type="PURCHASE_SALE",
            closing_date="2026-08-31", financing_offset_days=21, subscription=sub,
        )
        activate_file(coord_h, f["id"])
        invoice = get_file_invoice(coord_h, f["id"])
        assert invoice["subtotal_cents"] == 34900
        assert invoice["discount_cents"] == 1745
        assert invoice["total_cents"] == 33155
        validate_success(api_client.terminate_file(f["id"], coord_h,
                                                   payload={"reason": "inspection failed"}))
        after = validate_success(api_client.get_invoice(invoice["id"], coord_h))
        assert after["status"] == "VOIDED"
        assert_invoice_invariants(after)
        amounts = {line["label"]: line["amount_cents"] for line in after["line_items"]}
        assert amounts.get("SUBSCRIPTION_OVERAGE") == 34900
        assert amounts.get("TERMINATION_CREDIT") == -34900
        assert after["subtotal_cents"] == 0
        assert after["discount_cents"] == 0
        assert after["total_cents"] == 0
