"""Insider roster and the designation lifecycle (PRD §2.1, §3.2, §3.3)."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    get_success_data, ApiErrorId,
    make_compliance_officer_headers, make_equity_plan_admin_headers,
    create_issuer, create_reporting_person, create_active_person,
    person_action, get_person, get_transaction, find_filings, set_clock,
    ingest_transaction, confirm_transaction,
)


class TestPersonInitialState:
    def test_person_initial_state_proposed(self, api):
        """PRD §3.2: "A newly created insider sits in `PROPOSED` status — known
        to the system but not yet subject to Section 16."

        Design: Corner/state_machines/person_initial_state_proposed
        """
        issuer = create_issuer()
        resp = api.create_reporting_person(
            {"issuer_id": issuer["id"], "full_name": "Dana Officer",
             "person_cik": "0001000001"},
            make_compliance_officer_headers())
        data = validate_success(resp, 201)
        assert data["status"] == "PROPOSED", (
            f"Expected PROPOSED, got {data['status']}")


class TestDesignationLifecycle:
    def test_designate_active_person_returns_person_invalid_state(self, api):
        """PRD §3.2: "Any of these actions attempted from a state that does not
        allow it is rejected with `ERR_PERSON_INVALID_STATE`."

        Design: Corner/state_machines/designate_active_person_returns_person_invalid_state
        """
        issuer = create_issuer()
        person = create_reporting_person(issuer["id"])
        person_action(person["id"], "DESIGNATE")
        resp = api.person_transition(person["id"], {"action": "DESIGNATE"},
                                     make_compliance_officer_headers())
        validate_error(resp, ApiErrorId.ERR_PERSON_INVALID_STATE)
        # The rejected designation creates no duplicate Form 3 draft.
        form3s = find_filings(reporting_person_id=person["id"], form_type="FORM_3")
        assert len(form3s) == 1, (
            f"Expected exactly 1 FORM_3 after rejected DESIGNATE, got {len(form3s)}")

    def test_form3_draft_auto_created_on_designation(self, api):
        """PRD §3.2: "Designation moves a person from `PROPOSED` to `ACTIVE`,
        stamps `designation_date` with the logical clock date, and — because a
        new insider owes an initial statement — causes the system to create a
        `DRAFT` `FORM_3` filing with a null `prepared_by_user_id` whose
        `filing_deadline` falls ten calendar days after the designation date;
        the person's `open_obligation_count` rises by one for the new draft."

        Design: Corner/state_machines/form3_draft_auto_created_on_designation
        """
        issuer = create_issuer()
        person = create_reporting_person(issuer["id"])
        set_clock("2026-08-03T09:00:00Z")
        person_action(person["id"], "DESIGNATE")
        form3s = find_filings(reporting_person_id=person["id"],
                              form_type="FORM_3", status="DRAFT")
        assert len(form3s) == 1, (
            f"Expected exactly one DRAFT FORM_3, got {len(form3s)}")
        form3 = form3s[0]
        assert form3["filing_deadline"] == "2026-08-13", (
            f"Expected deadline 2026-08-13 (designation 2026-08-03 + 10 calendar "
            f"days), got {form3['filing_deadline']}")
        assert form3.get("prepared_by_user_id") is None, (
            f"System-generated Form 3 must carry null prepared_by_user_id, "
            f"got {form3.get('prepared_by_user_id')}")


class TestDesignationRbac:
    def test_equity_plan_admin_cannot_designate(self, api):
        """PRD §2.1: "`ComplianceOfficer` — the corporate secretary's Section 16
        compliance officer. This role owns issuer registration and
        configuration, blackout windows, insider designations and exits,
        transaction confirmation and voiding, 10b5-1 plan approvals and
        lifecycle actions, beneficial-owner monitoring and schedule recording,
        annual sweeps, filing-agent authorizations, and the logical clock."
        PRD §2.1: "Invoking an operation one's role does not permit is rejected
        with `ERR_FORBIDDEN_ROLE`."

        Design: Corner/rbac/equity_plan_admin_cannot_designate
        """
        issuer = create_issuer()
        person = create_reporting_person(issuer["id"])
        resp = api.person_transition(person["id"], {"action": "DESIGNATE"},
                                     make_equity_plan_admin_headers("epa_1"))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
        assert get_person(person["id"])["status"] == "PROPOSED", (
            "Person must remain PROPOSED after a forbidden DESIGNATE")


class TestConfirmRequiresActivePerson:
    def test_confirm_succeeds_while_active_fails_after_exit(self, api):
        """PRD §3.2: "Because both transaction confirmation and manual filing
        creation require an `ACTIVE` person, a `PROPOSED` or `EXITED` insider
        blocks those flows with `ERR_PERSON_NOT_ACTIVE`."
        PRD §3.3: "its reporting person must be `ACTIVE`
        (`ERR_PERSON_NOT_ACTIVE`)"

        Design: Difficulty/cross_entity_state_dependency/confirm_requires_active_reporting_person
        """
        issuer = create_issuer()
        person = create_active_person(issuer["id"])
        t1 = ingest_transaction(person["id"], transaction_date="2026-08-01",
                                shares=100, price_per_share=10.00)
        confirmed = confirm_transaction(t1["id"])
        assert confirmed["status"] == "CONFIRMED", (
            f"Confirm while ACTIVE must succeed, got {confirmed['status']}")
        person_action(person["id"], "EXIT")
        t2 = ingest_transaction(person["id"], transaction_date="2026-08-01",
                                shares=50, price_per_share=11.00)
        resp = api.confirm_transaction(t2["id"],
                                       make_compliance_officer_headers("co_1"))
        validate_error(resp, ApiErrorId.ERR_PERSON_NOT_ACTIVE)

    def test_confirm_blocked_for_proposed_person(self, api):
        """PRD §3.2: "Because both transaction confirmation and manual filing
        creation require an `ACTIVE` person, a `PROPOSED` or `EXITED` insider
        blocks those flows with `ERR_PERSON_NOT_ACTIVE`."

        Design: Difficulty/cross_entity_state_dependency/confirm_requires_active_reporting_person
        """
        issuer = create_issuer()
        person = create_reporting_person(issuer["id"])  # stays PROPOSED
        txn = ingest_transaction(person["id"], transaction_date="2026-08-01",
                                 shares=100, price_per_share=10.00)
        resp = api.confirm_transaction(txn["id"],
                                       make_compliance_officer_headers("co_1"))
        validate_error(resp, ApiErrorId.ERR_PERSON_NOT_ACTIVE)
        assert get_transaction(txn["id"])["status"] == "INGESTED", (
            "Rejected confirm must leave the transaction INGESTED")
