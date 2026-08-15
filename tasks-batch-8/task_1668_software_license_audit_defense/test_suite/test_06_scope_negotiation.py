"""Scope negotiation: dispute/re-propose cycle, parent-state gates, duplicate
proposals, concurrent-audit occupation, and the response deadline (PRD §3.5)."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    advance_case,
    assert_scope_item,
    confirm_scope_item,
    create_audit_case,
    create_scope_item_payload,
    create_vendor_and_product,
    get_case,
    get_scope_item,
    propose_scope_item,
    set_clock,
    setup_case_in_scope_negotiation,
    setup_case_with_confirmed_item,
    validate_error,
    validate_success,
)


class TestDisputeReproposeCycle:
    def _setup_proposed_item(self):
        ctx = setup_case_in_scope_negotiation()
        item = propose_scope_item(ctx["case"]["id"], ctx["product"]["id"],
                                  rationale="believe deployed")
        return ctx, item

    def test_scope_item_dispute_then_repropose_returns_to_proposed(
            self, api, legal_counsel_headers, vendor_auditor_headers):
        """PRD §3.5: "Disputing a `PROPOSED` item records the supplied
        `dispute_rationale` on it and moves it to `DISPUTED`; either negotiating
        party may later re-propose a disputed item, which replaces its
        `inclusion_rationale` with the newly supplied value and returns it to
        `PROPOSED`."

        Design: Difficulty/non_linear_state_machine/scope_item_dispute_repropose_cycle
        """
        ctx, item = self._setup_proposed_item()
        assert item["scope_status"] == "PROPOSED"

        disputed = validate_success(
            api.dispute_scope_item(
                item["id"],
                {"dispute_rationale": "Retired product line, contract excludes it"},
                legal_counsel_headers), 200)
        assert_scope_item(disputed)
        assert disputed["id"] == item["id"], "the cycle runs on one row"
        assert disputed["scope_status"] == "DISPUTED"
        assert disputed["dispute_rationale"] == \
            "Retired product line, contract excludes it"
        assert disputed["version"] == item["version"] + 1

        reproposed = validate_success(
            api.repropose_scope_item(
                item["id"],
                {"inclusion_rationale": "Revised: contract amendment 4 brings it in scope"},
                vendor_auditor_headers), 200)
        assert reproposed["id"] == item["id"]
        assert reproposed["scope_status"] == "PROPOSED"
        assert reproposed["inclusion_rationale"] == \
            "Revised: contract amendment 4 brings it in scope"
        assert reproposed["version"] == disputed["version"] + 1

    def test_scope_item_cycle_reaches_confirmed_on_same_row(
            self, api, legal_counsel_headers, vendor_auditor_headers):
        """PRD §3.5: "Disputing a `PROPOSED` item records the supplied
        `dispute_rationale` on it and moves it to `DISPUTED`; either negotiating
        party may later re-propose a disputed item, which replaces its
        `inclusion_rationale` with the newly supplied value and returns it to
        `PROPOSED`."
        PRD §3.5: "Confirming a `PROPOSED` item moves it to `CONFIRMED` and is
        permitted only while the parent case is in `SCOPE_NEGOTIATION` and no later
        than the case's response deadline"
        PRD §2.5: "`version` (integer): a system-managed counter that increments
        with every modification of the resource, including server-initiated
        recomputation of derived fields; it underpins the optimistic concurrency
        rule of §2.9."

        Design: Difficulty/non_linear_state_machine/scope_item_dispute_repropose_cycle
        """
        ctx, item = self._setup_proposed_item()
        v0 = item["version"]

        disputed = validate_success(
            api.dispute_scope_item(item["id"], {"dispute_rationale": "out of scope"},
                                   legal_counsel_headers), 200)
        reproposed = validate_success(
            api.repropose_scope_item(item["id"], {"inclusion_rationale": "back in"},
                                     vendor_auditor_headers), 200)
        confirmed = validate_success(
            api.confirm_scope_item(item["id"], legal_counsel_headers), 200)

        assert confirmed["id"] == item["id"], \
            "no new entity is created per negotiation round"
        assert confirmed["scope_status"] == "CONFIRMED"
        assert disputed["version"] == v0 + 1
        assert reproposed["version"] == v0 + 2
        assert confirmed["version"] == v0 + 3, \
            "version increments once per modification across the whole loop"


class TestScopeConfirmParentGate:
    def test_scope_confirm_rejected_while_case_notice_received(
            self, api, legal_counsel_headers, vendor_auditor_headers):
        """PRD §3.5: "Confirming a `PROPOSED` item moves it to `CONFIRMED` and is
        permitted only while the parent case is in `SCOPE_NEGOTIATION` and no later
        than the case's response deadline"
        PRD §3.5: "Every one of these scope operations requires the item to be in
        the expected prior `scope_status`, failing with
        `ERR_SCOPE_ITEM_INVALID_STATE` otherwise, and requires the parent case state
        described above, failing with `ERR_AUDIT_CASE_INVALID_STATE` otherwise."

        Design: Difficulty/cross_entity_state_dependency/scope_confirm_requires_case_in_scope_negotiation
        """
        vendor, product = create_vendor_and_product()
        case = create_audit_case(vendor["id"])
        assert case["status"] == "NOTICE_RECEIVED"
        item = propose_scope_item(case["id"], product["id"],
                                  rationale="attached to the notice")

        resp = api.confirm_scope_item(item["id"], legal_counsel_headers)
        validate_error(resp, ApiErrorId.ERR_AUDIT_CASE_INVALID_STATE)

    def test_rejected_scope_confirm_leaves_item_proposed_then_succeeds(
            self, api, legal_counsel_headers):
        """PRD §3.5: "Confirming a `PROPOSED` item moves it to `CONFIRMED` and is
        permitted only while the parent case is in `SCOPE_NEGOTIATION` and no later
        than the case's response deadline"

        Design: Difficulty/cross_entity_state_dependency/scope_confirm_requires_case_in_scope_negotiation
        """
        vendor, product = create_vendor_and_product()
        case = create_audit_case(vendor["id"])
        item = propose_scope_item(case["id"], product["id"],
                                  rationale="attached to the notice")

        resp = api.confirm_scope_item(item["id"], legal_counsel_headers)
        validate_error(resp, ApiErrorId.ERR_AUDIT_CASE_INVALID_STATE)
        still = get_scope_item(case["id"], item["id"])
        assert still["scope_status"] == "PROPOSED", \
            "the rejected confirm leaves the item untouched"

        advance_case(case["id"], "SCOPE_NEGOTIATION")
        confirmed = validate_success(
            api.confirm_scope_item(item["id"], legal_counsel_headers), 200)
        assert confirmed["scope_status"] == "CONFIRMED"


class TestConcurrentAuditOccupation:
    def _setup_two_cases_same_product(self):
        """Case A with product CONFIRMED in scope; case B with the same product
        PROPOSED. Both cases sit in SCOPE_NEGOTIATION."""
        vendor, product = create_vendor_and_product()
        case_a = create_audit_case(vendor["id"])
        advance_case(case_a["id"], "SCOPE_NEGOTIATION")
        item_a = propose_scope_item(case_a["id"], product["id"],
                                    rationale="case A scope")
        confirm_scope_item(item_a["id"])

        case_b = create_audit_case(vendor["id"])
        case_b = advance_case(case_b["id"], "SCOPE_NEGOTIATION")
        item_b = propose_scope_item(case_b["id"], product["id"],
                                    rationale="case B scope")
        return vendor, product, case_a, case_b, item_a, item_b

    def test_concurrent_audit_confirm_rejected(self, api, legal_counsel_headers):
        """PRD §3.5: "Confirmation also enforces exclusive audit occupation: when
        any other audit case whose status is not `CLOSED_SETTLED`,
        `CLOSED_NO_ACTION`, or `WITHDRAWN` already holds a `CONFIRMED` scope item
        for the same product, confirmation is rejected with
        `ERR_PRODUCT_UNDER_CONCURRENT_AUDIT`."

        Design: Difficulty/resource_temporal_overlap/product_concurrent_audit_half_open_occupation
        """
        _v, _p, _case_a, _case_b, _item_a, item_b = \
            self._setup_two_cases_same_product()
        resp = api.confirm_scope_item(item_b["id"], legal_counsel_headers)
        validate_error(resp, ApiErrorId.ERR_PRODUCT_UNDER_CONCURRENT_AUDIT)

    def test_confirm_succeeds_after_occupying_case_withdrawn(
            self, api, legal_counsel_headers, vendor_auditor_headers):
        """PRD §3.5: "Occupation is measured as the half-open interval from the
        occupying case's `notice_received_on` up to but not including its closure,
        so a case that closed before the current case's notice was received does
        not block."
        PRD §3.7: "The vendor may abandon the audit entirely: a `VendorAuditor`
        withdrawal moves the case from any non-terminal state to `WITHDRAWN`"

        Design: Difficulty/resource_temporal_overlap/product_concurrent_audit_half_open_occupation
        """
        _v, _p, case_a, _case_b, _item_a, item_b = \
            self._setup_two_cases_same_product()

        blocked = api.confirm_scope_item(item_b["id"], legal_counsel_headers)
        validate_error(blocked, ApiErrorId.ERR_PRODUCT_UNDER_CONCURRENT_AUDIT)

        withdrawn = validate_success(
            api.withdraw_audit_case(case_a["id"], vendor_auditor_headers), 200)
        assert withdrawn["status"] == "WITHDRAWN"

        confirmed = validate_success(
            api.confirm_scope_item(item_b["id"], legal_counsel_headers), 200)
        assert confirmed["scope_status"] == "CONFIRMED", \
            "once the occupying case is WITHDRAWN the half-open occupation has ended"


class TestDeadlineVersusConstraintOrdering:
    def _setup_deadline_and_concurrent_conflict(self):
        """Case A holds product P CONFIRMED; case B proposes P; the clock is moved
        past both response deadlines so B's confirm violates the temporal rule
        (ERR_RESPONSE_DEADLINE_PASSED) and the occupation rule simultaneously."""
        vendor, product = create_vendor_and_product()
        case_a = create_audit_case(vendor["id"])
        advance_case(case_a["id"], "SCOPE_NEGOTIATION")
        item_a = propose_scope_item(case_a["id"], product["id"],
                                    rationale="case A scope")
        confirm_scope_item(item_a["id"])

        case_b = create_audit_case(vendor["id"])
        case_b = advance_case(case_b["id"], "SCOPE_NEGOTIATION")
        item_b = propose_scope_item(case_b["id"], product["id"],
                                    rationale="case B scope")
        set_clock("2026-09-15T00:00:00Z")
        return case_b, item_b

    def test_scope_confirm_past_deadline_reports_temporal_error(
            self, api, legal_counsel_headers):
        """PRD §2.10: "Every request is validated against a fixed, prioritized
        chain; the first failing check produces the error response and later checks
        are not evaluated."
        PRD §2.10: "7. Business-temporal rules — the response deadline on advancing
        to scope negotiation and on scope confirmation
        (`ERR_RESPONSE_DEADLINE_PASSED`), and the measurement-date rule on
        deployment confirmation (`ERR_MEASUREMENT_DATE_IN_FUTURE`).
        8. Business constraints — vendor code uniqueness
        (`ERR_DUPLICATE_VENDOR_CODE`), duplicate scope items
        (`ERR_DUPLICATE_SCOPE_ITEM`), concurrent audit occupation
        (`ERR_PRODUCT_UNDER_CONCURRENT_AUDIT`), and entitlement window overlap
        (`ERR_ENTITLEMENT_WINDOW_OVERLAP`)."

        Design: Difficulty/priority_pair_validation_conflict/scope_confirm_deadline_and_concurrent_audit_temporal_wins
        """
        case_b, item_b = self._setup_deadline_and_concurrent_conflict()
        resp = api.confirm_scope_item(item_b["id"], legal_counsel_headers)
        validate_error(resp, ApiErrorId.ERR_RESPONSE_DEADLINE_PASSED)

    def test_scope_confirm_past_deadline_leaves_item_unchanged(
            self, api, legal_counsel_headers):
        """PRD §3.5: "Confirming a `PROPOSED` item moves it to `CONFIRMED` and is
        permitted only while the parent case is in `SCOPE_NEGOTIATION` and no later
        than the case's response deadline — confirming past `response_deadline_on`
        fails with `ERR_RESPONSE_DEADLINE_PASSED`, with exactly-at-the-deadline
        still allowed."

        Design: Difficulty/priority_pair_validation_conflict/scope_confirm_deadline_and_concurrent_audit_temporal_wins
        """
        case_b, item_b = self._setup_deadline_and_concurrent_conflict()
        case_version_pre = get_case(case_b["id"])["version"]

        resp = api.confirm_scope_item(item_b["id"], legal_counsel_headers)
        validate_error(resp, ApiErrorId.ERR_RESPONSE_DEADLINE_PASSED)

        still = get_scope_item(case_b["id"], item_b["id"])
        assert still["scope_status"] == "PROPOSED", \
            "a rejected confirm does not move the item"
        assert get_case(case_b["id"])["version"] == case_version_pre, \
            "a rejected confirm does not touch the case"


class TestScopeItemCreateRules:
    def test_duplicate_scope_item_rejected(self, api, sam_manager_headers):
        """PRD §3.5: "Proposals are accepted only while the parent case is
        `NOTICE_RECEIVED` or `SCOPE_NEGOTIATION`, and a second item for the same
        case and product in `PROPOSED`, `CONFIRMED`, or `DISPUTED` status is
        rejected with `ERR_DUPLICATE_SCOPE_ITEM`; an `EXCLUDED` item does not block
        a fresh proposal."

        Design: Corner/validations/duplicate_scope_item_rejected
        """
        ctx = setup_case_in_scope_negotiation()
        first = propose_scope_item(ctx["case"]["id"], ctx["product"]["id"],
                                   rationale="first")
        assert first["scope_status"] == "PROPOSED"

        resp = api.create_scope_item(
            create_scope_item_payload(ctx["case"]["id"], ctx["product"]["id"],
                                      inclusion_rationale="duplicate"),
            sam_manager_headers)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_SCOPE_ITEM)

    def test_scope_item_not_found_on_confirm(self, api, legal_counsel_headers):
        """PRD §3.5: "Scope items can be listed per case with an optional
        `scope_status` filter, or per product across all cases; unknown item
        identifiers surface as `ERR_SCOPE_ITEM_NOT_FOUND`."

        Design: Corner/errors/scope_item_not_found_on_confirm
        """
        resp = api.confirm_scope_item(NON_EXISTENT_UUID, legal_counsel_headers)
        validate_error(resp, ApiErrorId.ERR_SCOPE_ITEM_NOT_FOUND)
