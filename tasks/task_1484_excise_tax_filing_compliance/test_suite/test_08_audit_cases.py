"""Audit cases and the records hold (PRD §3.9)."""
from test_helpers import (
    ApiErrorId,
    close_audit_case_no_change,
    create_audit_case,
    create_jurisdiction,
    create_pending_registration,
    create_registrant,
    get_return_version,
    new_analyst_headers,
    new_auditor_headers,
    open_amendment,
    setup_filed_return,
    validate_error,
    validate_success,
)


class TestAuditCaseLifecycle:
    def test_audit_case_full_happy_path_with_assessment(self, api):
        """PRD §3.9: "The auditor requests documents, moving the case from
        `OPENED` to `DOCUMENTS_REQUESTED`, and begins review, moving from
        `DOCUMENTS_REQUESTED` to `UNDER_REVIEW`" and "`ASSESSMENT` requires
        an `assessment_cents` of at least one cent (`ERR_INVALID_REQUEST`
        otherwise), records the assessment on the case, and ends it in
        `CLOSED_ASSESSMENT`. Either close releases the records hold."
        Also: "A new case starts in `OPENED` with `records_hold` true".

        Design: Corner/state_machines/audit_case_full_happy_path_with_assessment
        """
        jur = create_jurisdiction()
        rgt = create_registrant()
        rgn = create_pending_registration(rgt["id"], jur["id"])
        case = create_audit_case(rgn, jur, period_start="2026-06",
                                 period_end="2026-08")
        assert case["status"] == "OPENED"
        assert case["records_hold"] is True

        auditor = new_auditor_headers()
        s1 = validate_success(api.request_audit_documents(case["id"], auditor))
        assert s1["status"] == "DOCUMENTS_REQUESTED"
        s2 = validate_success(api.begin_audit_review(case["id"], auditor))
        assert s2["status"] == "UNDER_REVIEW"
        closed = validate_success(api.close_audit_case(
            case["id"], {"outcome": "ASSESSMENT", "assessment_cents": 50000},
            auditor))
        assert closed["status"] == "CLOSED_ASSESSMENT"
        assert closed["assessment_cents"] == 50000
        assert closed["records_hold"] is False


class TestAuditRangeOverlap:
    def test_audit_case_shared_bucket_rejected(self, api):
        """PRD §3.9: "Two cases for the same registration and jurisdiction
        may not share any month bucket while the existing case is
        non-terminal, failing with `ERR_AUDIT_RANGE_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/audit_case_month_bucket_overlap
        """
        jur = create_jurisdiction()
        rgt = create_registrant()
        rgn = create_pending_registration(rgt["id"], jur["id"])
        create_audit_case(rgn, jur, period_start="2026-06",
                          period_end="2026-08")
        resp = api.create_audit_case(
            {"registration_id": rgn["id"], "jurisdiction_id": jur["id"],
             "period_start": "2026-08", "period_end": "2026-10"},
            new_auditor_headers())
        validate_error(resp, ApiErrorId.ERR_AUDIT_RANGE_OVERLAP)

    def test_audit_case_adjacent_buckets_accepted(self, api):
        """PRD §3.9: "Audit cases cover inclusive ranges of month buckets"
        (§2.7) and "Two cases for the same registration and jurisdiction may
        not share any month bucket while the existing case is non-terminal" —
        adjacent-but-disjoint buckets ([.., 2026-08] then [2026-09, ..])
        share no bucket and are accepted.

        Design: Difficulty/resource_temporal_overlap/audit_case_month_bucket_overlap
        """
        jur = create_jurisdiction()
        rgt = create_registrant()
        rgn = create_pending_registration(rgt["id"], jur["id"])
        create_audit_case(rgn, jur, period_start="2026-06",
                          period_end="2026-08")
        created = validate_success(api.create_audit_case(
            {"registration_id": rgn["id"], "jurisdiction_id": jur["id"],
             "period_start": "2026-09", "period_end": "2026-10"},
            new_auditor_headers()), expected_status=201)
        assert created["status"] == "OPENED"


class TestRecordsHoldBlocksAmendment:
    def test_amend_blocked_while_records_hold(self, api):
        """PRD §3.9: "while it covers a period it blocks five operations
        outright, each rejected with `ERR_AUDIT_RECORDS_HOLD`: opening an
        amendment of a return of the period, reclassifying a `RETURNED` event
        inside an amendment of the period, applying an approved credit claim
        against a return of the period, purging the period's expired records,
        and revoking the registration."

        Design: Difficulty/cross_entity_state_dependency/amendment_gated_on_audit_records_hold
        """
        ctx, _ev, filed = setup_filed_return()
        create_audit_case(ctx["registration"], ctx["jurisdiction"],
                          period_start="2026-08", period_end="2026-08")
        resp = api.amend_return(
            filed["id"],
            {"expected_return_version": get_return_version(filed["id"])},
            new_analyst_headers())
        validate_error(resp, ApiErrorId.ERR_AUDIT_RECORDS_HOLD)

    def test_amend_allowed_after_audit_closes(self, api):
        """PRD §3.9: "Either close releases the records hold." — once the
        case closes, amendment proceeds per §3.6: "The amendment is created
        as a new return in `DRAFT` and `UNFILED`, its `amendment_of_id`
        naming the parent, its `amendment_sequence` one deeper than its
        parent's".

        Design: Difficulty/cross_entity_state_dependency/amendment_gated_on_audit_records_hold
        """
        ctx, _ev, filed = setup_filed_return()
        case = create_audit_case(ctx["registration"], ctx["jurisdiction"],
                                 period_start="2026-08", period_end="2026-08")
        close_audit_case_no_change(case["id"])
        amd = open_amendment(filed["id"])
        assert amd["filing_status"] == "DRAFT"
        assert amd["settlement_status"] == "UNFILED"
        assert amd["amendment_of_id"] == filed["id"]
        assert amd["amendment_sequence"] == 1


class TestAuditRoleEnforcement:
    def test_analyst_cannot_close_audit_forbidden(self, api):
        """PRD §2.1: "A `JurisdictionAuditor` is an external jurisdiction
        auditor with read access to everything and write access to audit
        cases only" — its converse binds the preparer roles: "if the caller's
        role is declared but not listed among the endpoint's authorized
        roles, the request is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP
        403)." (§4: audit-case lifecycle endpoints list JurisdictionAuditor
        only).

        Design: Corner/rbac/analyst_cannot_close_audit_forbidden
        """
        jur = create_jurisdiction()
        rgt = create_registrant()
        rgn = create_pending_registration(rgt["id"], jur["id"])
        case = create_audit_case(rgn, jur, period_start="2026-06",
                                 period_end="2026-08")
        validate_success(
            api.begin_audit_review(case["id"], new_auditor_headers()))
        resp = api.close_audit_case(
            case["id"], {"outcome": "NO_CHANGE"}, new_analyst_headers())
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)
