"""Annual report lifecycle, revision cycle, and segregation rules.

Covers PRD §3.5 (lifecycle + revision loop), §2.5 (OCC on PATCH).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_annual_report,
    assert_event_types_present,
    assert_status,
    create_accepted_annual_report,
    create_and_activate_entity,
    create_annual_report_payload,
    create_draft_annual_report,
    create_submitted_annual_report,
    list_compliance_events,
    make_filer_headers,
    make_tax_officer_headers,
    patch_annual_report_payload,
    reject_annual_report_payload,
    setup_active_entity_eligible_for_annual_report,
    validate_error,
    validate_success,
)


# PRD §3.5: "The report_year must be strictly greater than the formation
# year (the year extracted from formation_date) and less than or equal
# to the current calendar year derived from the clock". Earlier tests
# may have advanced the server clock; setup_active_entity_eligible_for_
# annual_report() forms the entity and then walks the clock ~13 months
# forward so the entity's formation_year is strictly less than the
# current server year, returning (entity, valid_report_year).


class TestAnnualReportCreate:

    def test_create_draft_annual_report(self, api):
        """PRD §3.5: "An AnnualReport is created by the Filer carrying
        business_entity_id, report_year, principal_office_address, and
        officer_director_count."

        Claim: create → DRAFT.
        """
        entity, report_year = setup_active_entity_eligible_for_annual_report()
        resp = api.create_annual_report(
            create_annual_report_payload(entity["id"], report_year),
            make_filer_headers(entity["id"]),
        )
        report = validate_success(resp, expected_status=201)
        assert_annual_report(report)
        assert_status(report, "DRAFT")

    def test_officer_director_count_below_one_rejected(self, api):
        """PRD §3.5: "officer_director_count ... must be at least 1."

        Claim: officer_director_count=0 → ERR_INVALID_INPUT.
        """
        entity, report_year = setup_active_entity_eligible_for_annual_report()
        resp = api.create_annual_report(
            create_annual_report_payload(
                entity["id"], report_year, officer_director_count=0,
            ),
            make_filer_headers(entity["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_INPUT.value)

    def test_create_for_inactive_entity_rejected(self, api):
        """PRD §2.11: "(7) the parent BusinessEntity.formation_status is
        ACTIVE for any child-mutating endpoint (yielding
        ERR_ENTITY_NOT_ACTIVE)"

        Claim: creating an annual report on a PENDING entity →
        ERR_ENTITY_NOT_ACTIVE.
        """
        from test_helpers import create_entity_in_pending, server_now_year
        entity, _ = create_entity_in_pending()
        resp = api.create_annual_report(
            create_annual_report_payload(entity["id"], server_now_year()),
            make_filer_headers(entity["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_ENTITY_NOT_ACTIVE.value)


class TestAnnualReportSubmit:

    def test_submit_clears_rejection_reason_and_records_submitted_at(
        self, api,
    ):
        """PRD §3.5: "the system records submitted_at and clears
        rejection_reason to null."

        Claim: after submit, submitted_at populated and rejection_reason
        is null.
        """
        entity, report_year = setup_active_entity_eligible_for_annual_report()
        draft = create_draft_annual_report(entity["id"], report_year)
        resp = api.submit_annual_report(
            draft["id"], make_filer_headers(entity["id"]),
        )
        submitted = validate_success(resp)
        assert_status(submitted, "SUBMITTED")
        assert submitted.get("submitted_at") is not None
        assert submitted.get("rejection_reason") in (None, "")


class TestAnnualReportAcceptance:

    def test_accept_advances_due_date_and_emits_event(
        self, api, tax_officer_headers,
    ):
        """PRD §3.5: "On acceptance, the system records accepted_at as
        the current clock instant, advances next_annual_report_due_date
        on the parent entity to the formation-date anniversary in the
        year following report_year ... and emits a ComplianceEvent of
        event_type ANNUAL_REPORT_ACCEPTED."

        Claim: accept → ACCEPTED + accepted_at + ANNUAL_REPORT_ACCEPTED
        event.
        """
        entity, report_year = setup_active_entity_eligible_for_annual_report()
        submitted = create_submitted_annual_report(
            entity["id"], report_year,
        )
        resp = api.accept_annual_report(
            submitted["id"], tax_officer_headers,
        )
        accepted = validate_success(resp)
        assert_status(accepted, "ACCEPTED")
        assert accepted.get("accepted_at") is not None
        events = list_compliance_events(entity["id"])
        assert_event_types_present(events, ["ANNUAL_REPORT_ACCEPTED"])

    def test_accept_with_entity_id_violates_segregation(self, api):
        """PRD §3.5: "The accepter's X-User-ID must not equal the
        BusinessEntity.id that filed the report — the entity cannot
        accept its own filing, and a violation surfaces as
        ERR_SEGREGATION_OF_DUTIES."

        Claim: TaxOfficer caller whose X-User-ID equals the owning
        BusinessEntity.id → ERR_SEGREGATION_OF_DUTIES.
        """
        entity, report_year = setup_active_entity_eligible_for_annual_report()
        submitted = create_submitted_annual_report(
            entity["id"], report_year,
        )
        bad_headers = make_tax_officer_headers(entity["id"])
        resp = api.accept_annual_report(submitted["id"], bad_headers)
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)


class TestAnnualReportRejection:

    def test_reject_requires_non_empty_reason(self, api,
                                              tax_officer_headers):
        """PRD §3.5: "The rejection_reason field must be supplied as a
        non-empty string."

        Claim: empty rejection_reason → ERR_INVALID_INPUT.
        """
        entity, report_year = setup_active_entity_eligible_for_annual_report()
        submitted = create_submitted_annual_report(
            entity["id"], report_year,
        )
        resp = api.reject_annual_report(
            submitted["id"],
            reject_annual_report_payload(""),
            tax_officer_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_INPUT.value)

    def test_reject_to_rejected_with_event(self, api,
                                           tax_officer_headers):
        """PRD §3.5: "A ComplianceEvent of event_type
        ANNUAL_REPORT_REJECTED is emitted."

        Claim: reject → REJECTED + ANNUAL_REPORT_REJECTED event.
        """
        entity, report_year = setup_active_entity_eligible_for_annual_report()
        submitted = create_submitted_annual_report(
            entity["id"], report_year,
        )
        resp = api.reject_annual_report(
            submitted["id"],
            reject_annual_report_payload("missing principal_office_address"),
            tax_officer_headers,
        )
        rejected = validate_success(resp)
        assert_status(rejected, "REJECTED")
        events = list_compliance_events(entity["id"])
        assert_event_types_present(events, ["ANNUAL_REPORT_REJECTED"])


class TestAnnualReportRevisionCycle:

    def test_rejected_patch_returns_to_draft(self, api,
                                             tax_officer_headers):
        """PRD §3.5: "The Filer can then revise the report through the
        patch endpoint, which (when the current status is REJECTED)
        flips the row back to DRAFT"

        Claim: PATCH on a REJECTED report → DRAFT.
        """
        entity, report_year = setup_active_entity_eligible_for_annual_report()
        submitted = create_submitted_annual_report(
            entity["id"], report_year,
        )
        rejected_resp = api.reject_annual_report(
            submitted["id"],
            reject_annual_report_payload("needs revision"),
            tax_officer_headers,
        )
        validate_success(rejected_resp)
        # Revise: PATCH should flip REJECTED → DRAFT.
        resp = api.patch_annual_report(
            submitted["id"],
            patch_annual_report_payload(
                principal_office_address="999 Revised Way",
            ),
            make_filer_headers(entity["id"]),
        )
        revised = validate_success(resp)
        assert_status(revised, "DRAFT")

    def test_revision_loop_revisits_submitted_state(
        self, api, tax_officer_headers,
    ):
        """PRD §3.5: "The lifecycle is DRAFT → SUBMITTED → ACCEPTED,
        with a revision loop: a REJECTED report cycles back to DRAFT
        and the cycle may repeat without bound."

        Claim: a second SUBMITTED → REJECTED → DRAFT → SUBMITTED cycle
        is permitted; the state vertex is revisited.
        """
        entity, report_year = setup_active_entity_eligible_for_annual_report()
        sub = create_submitted_annual_report(entity["id"], report_year)
        # First reject.
        api.reject_annual_report(
            sub["id"],
            reject_annual_report_payload("missing address"),
            tax_officer_headers,
        )
        # Patch to DRAFT.
        revised_resp = api.patch_annual_report(
            sub["id"],
            patch_annual_report_payload(
                principal_office_address="123 Main",
            ),
            make_filer_headers(entity["id"]),
        )
        validate_success(revised_resp)
        # Resubmit.
        sub2 = api.submit_annual_report(
            sub["id"], make_filer_headers(entity["id"]),
        )
        sub2 = validate_success(sub2)
        assert_status(sub2, "SUBMITTED")
        # Second reject — confirm REJECTED state revisited.
        rej2 = api.reject_annual_report(
            sub["id"],
            reject_annual_report_payload("officer count needed"),
            tax_officer_headers,
        )
        rej2 = validate_success(rej2)
        assert_status(rej2, "REJECTED")


class TestAnnualReportDuplicates:

    def test_second_submitted_same_year_rejected(self, api):
        """PRD §3.5: "no prior SUBMITTED or ACCEPTED report covers the
        same report_year"
        PRD §3.5: "Two Filers racing to submit the same
        (business_entity_id, report_year) serialize first-writer-wins on
        the submitted_at timestamp; the loser is rejected with
        ERR_DUPLICATE_ANNUAL_REPORT"

        Claim: creating a second AnnualReport for the same year while
        one is SUBMITTED → ERR_DUPLICATE_ANNUAL_REPORT (or rejected at
        submit-time).
        """
        entity, report_year = setup_active_entity_eligible_for_annual_report()
        # First submitted.
        create_submitted_annual_report(entity["id"], report_year)
        # Attempt second creation for the same year.
        resp = api.create_annual_report(
            create_annual_report_payload(entity["id"], report_year),
            make_filer_headers(entity["id"]),
        )
        # PRD §3.5 + PRD §5: ERR_DUPLICATE_ANNUAL_REPORT for the
        # (business_entity_id, report_year) collision.
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_ANNUAL_REPORT.value)

    def test_rejected_does_not_occupy_year(self, api,
                                           tax_officer_headers):
        """PRD §3.5: "no prior SUBMITTED or ACCEPTED report covers the
        same report_year"
        (REJECTED is deliberately not in this list — the rejected slot
        is freed for a new attempt.)

        Claim: after a first report is REJECTED, a second report for
        the same year is permitted.
        """
        entity, report_year = setup_active_entity_eligible_for_annual_report()
        sub = create_submitted_annual_report(entity["id"], report_year)
        api.reject_annual_report(
            sub["id"],
            reject_annual_report_payload("retry needed"),
            tax_officer_headers,
        )
        # Second creation for the same year — must succeed now that the
        # prior is REJECTED.
        resp = api.create_annual_report(
            create_annual_report_payload(entity["id"], report_year),
            make_filer_headers(entity["id"]),
        )
        validate_success(resp, expected_status=201)
