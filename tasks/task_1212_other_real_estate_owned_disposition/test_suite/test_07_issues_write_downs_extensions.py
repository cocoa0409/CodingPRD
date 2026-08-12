"""Issue cases (open/remediation/resolved/waived), write-down lifecycle
(propose/approve/reject with segregation-of-duties), and holding-period
extension requests with the aggregate cap."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    validate_success,
    validate_error,
    create_property,
    create_issue_payload,
    create_write_down_payload,
    create_extension_request_payload,
    get_property,
    list_ledger_entries,
    set_clock,
    make_oreo_committee_headers,
    make_credit_officer_headers,
    make_property_manager_headers,
    make_compliance_officer_headers,
)

ADMIN = TEST_USERS["oreo_admin_headers"]
PM = TEST_USERS["property_manager_headers"]
COMMITTEE = TEST_USERS["oreo_committee_headers"]
CO = TEST_USERS["credit_officer_headers"]
COMP = TEST_USERS["compliance_officer_headers"]


class TestIssueLifecycle:
    def test_issue_lifecycle_open_remediation_resolved_updates_counts(self, api):
        """PRD §3.8: "an OPEN issue moves to IN_REMEDIATION via
        start-remediation — which changes no counts, since IN_REMEDIATION still
        counts as open — and an IN_REMEDIATION issue moves to RESOLVED via
        resolve, which records the supplied resolution_notes and recomputes the
        property's open-issue counts."
        Also: "open_title_issue_count counts title issues in the same two
        states."

        Design: Corner/state_machines/issue_lifecycle_open_remediation_resolved_updates_counts
        """
        prop = create_property()
        issue = validate_success(
            api.create_issue(
                create_issue_payload(
                    property_id=prop["id"],
                    issue_type="TITLE",
                    severity="MEDIUM",
                    description="Unreleased lien",
                ),
                PM,
            ),
            expected_status=201,
        )
        # open -> count 1
        assert get_property(prop["id"])["open_title_issue_count"] == 1
        # IN_REMEDIATION still counts as open
        api.start_remediation(issue["id"], PM)
        assert get_property(prop["id"])["open_title_issue_count"] == 1
        # resolve -> count 0
        api.resolve_issue(issue["id"], {"resolution_notes": "Lien release recorded"}, PM)
        after = get_property(prop["id"])
        assert after["open_title_issue_count"] == 0
        i_after = validate_success(api.get_issue(issue["id"], ADMIN))
        assert i_after["status"] == "RESOLVED"
        assert i_after["resolution_notes"] == "Lien release recorded"

    def test_resolve_open_issue_without_remediation_returns_invalid_state(self, api):
        """PRD §3.8: "waiving an issue that is already IN_REMEDIATION (or any
        transition attempted from an illegal from-state, such as resolving an
        OPEN issue) is rejected with ERR_ISSUE_INVALID_STATE (HTTP 409)."

        Design: Corner/state_machines/resolve_open_issue_without_remediation_returns_invalid_state
        """
        prop = create_property()
        issue = validate_success(
            api.create_issue(
                create_issue_payload(
                    property_id=prop["id"],
                    issue_type="TITLE",
                    severity="MEDIUM",
                    description="Unreleased lien",
                ),
                PM,
            ),
            expected_status=201,
        )
        resp = api.resolve_issue(issue["id"], {"resolution_notes": "skip"}, PM)
        validate_error(resp, ApiErrorId.ERR_ISSUE_INVALID_STATE)
        # unchanged
        i_after = validate_success(api.get_issue(issue["id"], ADMIN))
        assert i_after["status"] == "OPEN"

    def test_waive_environmental_issue_returns_422(self, api):
        """PRD §3.8: "The committee may instead waive an issue, but only a
        TITLE issue and only from OPEN: waiving an environmental issue is
        rejected with ERR_ENVIRONMENTAL_NOT_WAIVABLE (HTTP 422)".

        Design: Corner/validations/waive_environmental_issue_returns_422
        """
        prop = create_property()
        issue = validate_success(
            api.create_issue(
                create_issue_payload(
                    property_id=prop["id"],
                    issue_type="ENVIRONMENTAL",
                    severity="HIGH",
                    description="Asbestos",
                ),
                PM,
            ),
            expected_status=201,
        )
        resp = api.waive_issue(issue["id"], COMMITTEE)
        validate_error(resp, ApiErrorId.ERR_ENVIRONMENTAL_NOT_WAIVABLE)
        i_after = validate_success(api.get_issue(issue["id"], ADMIN))
        assert i_after["status"] == "OPEN"


class TestWriteDownLifecycle:
    def test_write_down_approval_posts_ledger_and_recomputes_carrying(self, api):
        """PRD §3.9: "Approving a PROPOSED write-down moves it to POSTED,
        records approved_by_user_id, appends a WRITE_DOWN ledger entry carrying
        the negative of the write-down's signed amount with write_down_id set,
        recomputes carrying_value as acquisition_basis plus
        capitalized_cost_total minus the sum of POSTED amounts, recomputes
        pending_write_down_count, and increments property.version."

        Design: Corner/state_machines/write_down_approval_posts_ledger_and_recomputes_carrying
        """
        prop = create_property()
        # manual proposal by co-1 (5000.00)
        wd = validate_success(
            api.create_write_down(
                create_write_down_payload(
                    property_id=prop["id"], amount=5000.00, reason="MARKET_DECLINE"
                ),
                make_credit_officer_headers("co-1"),
            ),
            expected_status=201,
        )
        # approve by a different committee member
        approve_resp = api.approve_write_down(
            wd["id"], make_oreo_committee_headers("committee-1")
        )
        approved = validate_success(approve_resp)
        assert approved["status"] == "POSTED"
        assert approved["approved_by_user_id"] == "committee-1"

        # carrying recomputed: 368000 - 5000 = 363000
        after = get_property(prop["id"])
        assert after["carrying_value"] == 363000.00
        assert after["pending_write_down_count"] == 0

        # ledger entry
        entries = list_ledger_entries(prop["id"], write_down_id=wd["id"])
        wd_entries = [e for e in entries if e["entry_type"] == "WRITE_DOWN"]
        assert len(wd_entries) == 1
        assert wd_entries[0]["amount"] == -5000.00
        assert wd_entries[0]["write_down_id"] == wd["id"]

    def test_approve_rejected_write_down_returns_invalid_state(self, api):
        """PRD §3.9: "Approve or reject attempted on a write-down not in
        PROPOSED fails with ERR_WRITE_DOWN_NOT_PROPOSED (HTTP 409)."

        Design: Corner/state_machines/approve_rejected_write_down_returns_invalid_state
        """
        prop = create_property()
        wd = validate_success(
            api.create_write_down(
                create_write_down_payload(
                    property_id=prop["id"], amount=5000.00, reason="MARKET_DECLINE"
                ),
                make_credit_officer_headers("co-1"),
            ),
            expected_status=201,
        )
        # reject first
        api.reject_write_down(wd["id"], COMMITTEE)
        # approve after reject must fail
        resp = api.approve_write_down(wd["id"], COMMITTEE)
        validate_error(resp, ApiErrorId.ERR_WRITE_DOWN_NOT_PROPOSED)
        # state remains REJECTED
        after = validate_success(api.get_write_down(wd["id"], ADMIN))
        assert after["status"] == "REJECTED"
        # no WRITE_DOWN ledger appended
        entries = list_ledger_entries(prop["id"], write_down_id=wd["id"])
        wd_entries = [e for e in entries if e["entry_type"] == "WRITE_DOWN"]
        assert len(wd_entries) == 0

    def test_write_down_approve_by_proposer_returns_segregation_error(self, api):
        """PRD §3.9: "Disposal of a proposal belongs to the OREOCommittee, with
        segregation of duties enforced at approve time: the approver's
        X-User-ID must differ from proposed_by_user_id, else
        ERR_SEGREGATION_OF_DUTIES (HTTP 403)."

        Design: Corner/validations/write_down_approve_by_proposer_returns_segregation_error
        """
        prop = create_property()
        wd = validate_success(
            api.create_write_down(
                create_write_down_payload(
                    property_id=prop["id"], amount=5000.00, reason="MARKET_DECLINE"
                ),
                make_credit_officer_headers("co-1"),
            ),
            expected_status=201,
        )
        # approver user id matches proposer
        resp = api.approve_write_down(wd["id"], make_oreo_committee_headers("co-1"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        # different committee user approves successfully
        ok = api.approve_write_down(wd["id"], make_oreo_committee_headers("committee-9"))
        approved = validate_success(ok)
        assert approved["status"] == "POSTED"

    def test_property_manager_cannot_approve_write_down_forbidden(self, api):
        """PRD §3.9: "Disposal of a proposal belongs to the OREOCommittee".
        PRD §2.1: "A request whose role is not on the endpoint's authorized
        list is rejected with ERR_FORBIDDEN (HTTP 403)." PropertyManager is
        not on the authorized list for write-down approval.

        Design: Corner/rbac/property_manager_cannot_approve_write_down_forbidden
        """
        prop = create_property()
        wd = validate_success(
            api.create_write_down(
                create_write_down_payload(
                    property_id=prop["id"], amount=5000.00, reason="MARKET_DECLINE"
                ),
                make_credit_officer_headers("co-1"),
            ),
            expected_status=201,
        )
        resp = api.approve_write_down(wd["id"], PM)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        after = validate_success(api.get_write_down(wd["id"], ADMIN))
        assert after["status"] == "PROPOSED"


class TestExtensionRequests:
    def test_extension_allowance_aggregate_capacity(self, api):
        """PRD §3.10: "Approval checks aggregate capacity:
        extension_days_approved plus the new requested_extension_days must not
        exceed the 1825-day total allowance, else ERR_EXTENSION_CAP_EXCEEDED
        (HTTP 422). On approval the request moves to APPROVED with
        decided_by_user_id recorded, extension_days_approved increases by the
        requested days, holding_deadline shifts out by the same number of
        days".

        Design: Difficulty/resource_temporal_overlap/extension_allowance_aggregate_capacity
        """
        prop = create_property(acquisition_date="2026-05-10")
        e1 = validate_success(
            api.create_extension_request(
                create_extension_request_payload(
                    property_id=prop["id"],
                    requested_extension_days=1000,
                    justification="Complex commercial parcel",
                ),
                COMP,
            ),
            expected_status=201,
        )
        api.submit_extension_request(e1["id"], COMP)
        approve1 = validate_success(
            api.approve_extension_request(e1["id"], COMMITTEE)
        )
        assert approve1["status"] == "APPROVED"
        # deadline shifts: 2031-05-09 + 1000 days = 2034-02-02
        after1 = get_property(prop["id"])
        assert after1["extension_days_approved"] == 1000
        assert after1["holding_deadline"].startswith("2034-02-02")

        # second request 900 -> 1000+900 = 1900 > 1825 -> cap error
        e2 = validate_success(
            api.create_extension_request(
                create_extension_request_payload(
                    property_id=prop["id"],
                    requested_extension_days=900,
                    justification="Further marketing time",
                ),
                COMP,
            ),
            expected_status=201,
        )
        api.submit_extension_request(e2["id"], COMP)
        resp = api.approve_extension_request(e2["id"], COMMITTEE)
        validate_error(resp, ApiErrorId.ERR_EXTENSION_CAP_EXCEEDED)

    def test_extension_deny_revise_resubmit_approves_within_cap(self, api):
        """PRD §3.10: "A denied request is not dead: the compliance officer
        may revise it back to DRAFT with a new requested_extension_days,
        opening a resubmission loop."

        Design: Difficulty/resource_temporal_overlap/extension_allowance_aggregate_capacity
        """
        prop = create_property(acquisition_date="2026-05-10")
        # approve 1000 first
        e1 = validate_success(
            api.create_extension_request(
                create_extension_request_payload(
                    property_id=prop["id"], requested_extension_days=1000
                ),
                COMP,
            ),
            expected_status=201,
        )
        api.submit_extension_request(e1["id"], COMP)
        api.approve_extension_request(e1["id"], COMMITTEE)

        # 900 -> cap error -> deny -> revise to 800 -> resubmit -> approve
        e2 = validate_success(
            api.create_extension_request(
                create_extension_request_payload(
                    property_id=prop["id"], requested_extension_days=900
                ),
                COMP,
            ),
            expected_status=201,
        )
        api.submit_extension_request(e2["id"], COMP)
        # cap error path already covered above; here we deny instead to enter the loop
        deny = validate_success(api.deny_extension_request(e2["id"], COMMITTEE))
        assert deny["status"] == "DENIED"
        # revise to 800 (1000+800 = 1800 <= 1825)
        revised = validate_success(
            api.revise_extension_request(e2["id"], {"requested_extension_days": 800}, COMP)
        )
        assert revised["status"] == "DRAFT"
        assert revised["requested_extension_days"] == 800
        # resubmit and approve
        api.submit_extension_request(e2["id"], COMP)
        ok = validate_success(api.approve_extension_request(e2["id"], COMMITTEE))
        assert ok["status"] == "APPROVED"
        final = get_property(prop["id"])
        assert final["extension_days_approved"] == 1800
        # 2031-05-09 + 1800 days = 2036-04-12
        assert final["holding_deadline"].startswith("2036-04-12")

    def test_extension_submit_blocked_on_terminal_property(self, api):
        """PRD §3.10: "The draft is then submitted; submission requires the
        property's lifecycle_status to be one of HELD, MARKETED, or
        UNDER_CONTRACT — the regulator will not consider a terminal property,
        and the attempt raises ERR_PROPERTY_ALREADY_TERMINAL".

        Design: Difficulty/cross_entity_state_dependency/extension_submit_blocked_on_terminal_property
        """
        prop = create_property(acquisition_date="2026-05-10")
        ext = validate_success(
            api.create_extension_request(
                create_extension_request_payload(
                    property_id=prop["id"], requested_extension_days=365
                ),
                COMP,
            ),
            expected_status=201,
        )
        # charge off via clock: deadline 2031-05-09 -> set clock past it
        set_clock("2031-05-10T00:00:00Z")
        # now property is CHARGED_OFF; submit must fail
        resp = api.submit_extension_request(ext["id"], COMP)
        validate_error(resp, ApiErrorId.ERR_PROPERTY_ALREADY_TERMINAL)
        # status remains DRAFT
        after = validate_success(api.get_extension_request(ext["id"], ADMIN))
        assert after["status"] == "DRAFT"

    def test_extension_submit_blocked_on_terminal_property_via_manual_chargeoff(self, api):
        """PRD §3.10: "a ComplianceOfficer executes a manual charge-off against
        a non-terminal property"; combined with the submit rule: "submission
        requires the property's lifecycle_status to be one of HELD, MARKETED,
        or UNDER_CONTRACT — the regulator will not consider a terminal
        property, and the attempt raises ERR_PROPERTY_ALREADY_TERMINAL".

        Design: Difficulty/cross_entity_state_dependency/extension_submit_blocked_on_terminal_property
        """
        prop = create_property()
        ext = validate_success(
            api.create_extension_request(
                create_extension_request_payload(
                    property_id=prop["id"], requested_extension_days=365
                ),
                COMP,
            ),
            expected_status=201,
        )
        # manual charge-off (does not depend on the clock)
        api.charge_off_property(prop["id"], COMP)
        resp = api.submit_extension_request(ext["id"], COMP)
        validate_error(resp, ApiErrorId.ERR_PROPERTY_ALREADY_TERMINAL)

    def test_deny_draft_extension_returns_invalid_state(self, api):
        """PRD §3.10: "Any submit, approve, deny, or revise attempted from an
        illegal from-state — denying a DRAFT, revising a SUBMITTED request —
        raises ERR_EXTENSION_INVALID_STATE (HTTP 409)."

        Design: Corner/state_machines/deny_draft_extension_returns_invalid_state
        """
        prop = create_property()
        ext = validate_success(
            api.create_extension_request(
                create_extension_request_payload(
                    property_id=prop["id"], requested_extension_days=365
                ),
                COMP,
            ),
            expected_status=201,
        )
        resp = api.deny_extension_request(ext["id"], COMMITTEE)
        validate_error(resp, ApiErrorId.ERR_EXTENSION_INVALID_STATE)
        after = validate_success(api.get_extension_request(ext["id"], ADMIN))
        assert after["status"] == "DRAFT"
