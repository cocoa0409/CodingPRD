"""Role enforcement, segregation of duties, optimistic concurrency, and
validation-order tie-breaks (PRD §2.1, §2.8, §2.9, §2.10)."""
from test_helpers import (
    ApiErrorId,
    classify_event,
    create_audit_case,
    create_claim,
    create_event,
    create_rated_event,
    create_registrant,
    get_return_version,
    make_analyst_headers,
    make_reviewer_headers,
    new_admin_headers,
    new_analyst_headers,
    new_reviewer_headers,
    rate_event,
    setup_active_registration,
    setup_applied_export_claim,
    setup_filed_return,
    setup_return_with_rated_event,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestRoleEnforcement:
    def test_analyst_cannot_file_returns_forbidden(self, api):
        """PRD §3.6: "Filing is reserved to a `TaxReviewer` or
        `ComplianceAdmin`".
        PRD §2.1: "if the caller's role is declared but not listed among the
        endpoint's authorized roles, the request is rejected with
        `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."

        Design: Corner/rbac/analyst_cannot_file_returns_forbidden
        """
        _ctx, _ev, ret = setup_return_with_rated_event(quantity_units=100)
        validate_success(
            api.submit_return(ret["id"], make_analyst_headers("analyst-1")))
        version = get_return_version(ret["id"])
        resp = api.file_return(ret["id"], version,
                               make_analyst_headers("analyst-2"))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)

    def test_reviewer_cannot_classify_events_forbidden(self, api):
        """PRD §2.1: "A `TaxAnalyst` is the compliance preparer: it records
        taxable activity, classifies and rates events" and "if the caller's
        role is declared but not listed among the endpoint's authorized roles,
        the request is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."
        (§4: classify lists TaxAnalyst and ComplianceAdmin only.)

        Design: Corner/rbac/reviewer_cannot_classify_events_forbidden
        """
        ctx = setup_active_registration()
        ev = create_event(ctx["registration"], ctx["jurisdiction"],
                          ctx["product_class"], quantity_units=10)
        resp = api.classify_event(ev["id"], new_reviewer_headers())
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)

    def test_auditor_cannot_create_registrant_forbidden(self, api):
        """PRD §2.1: "A `JurisdictionAuditor` is an external jurisdiction
        auditor with read access to everything and write access to audit
        cases only" and "Role enforcement is uniform: if the caller's role is
        declared but not listed among the endpoint's authorized roles, the
        request is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403). All
        read endpoints are open to all four client-facing roles."

        Design: Corner/rbac/auditor_cannot_create_registrant_forbidden
        """
        rgt = create_registrant()
        auditor = {"X-User-ID": "auditor-1", "X-User-Role":
                   "JurisdictionAuditor", "Content-Type": "application/json"}
        resp = api.create_registrant(
            {"legal_name": "Evil", "fein": "99-9999999"}, auditor)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)

        got = validate_success(api.get_registrant(rgt["id"], auditor))
        assert got["id"] == rgt["id"], "shared read stays open to auditors"


class TestReturnSegregationOfDuties:
    def test_sod_return_self_file_forbidden(self, api):
        """PRD §2.9: "The operator who files a return must not be the
        operator recorded as that return's `prepared_by_user_id`; the operator
        who approves or denies a credit claim must not be the operator
        recorded as that claim's `submitted_by_user_id`. A violation is
        rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

        Design: Corner/rbac/sod_return_self_file_forbidden
        """
        _ctx, _ev, ret = setup_return_with_rated_event(quantity_units=100)
        validate_success(
            api.submit_return(ret["id"], make_analyst_headers("analyst-1")))
        version = get_return_version(ret["id"])
        # The filer role is permitted, but the X-User-ID equals the
        # preparer's: SoD violation.
        resp = api.file_return(ret["id"], version,
                               make_reviewer_headers("analyst-1"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)


class TestReturnFileOcc:
    def test_occ_return_file_stale_version_rejected(self, api):
        """PRD §2.8: "Filing a return requires the request body to carry
        `expected_return_version` equal to the return's current `version`. A
        return's version can legitimately advance between submission and
        filing — for instance when a late taxable event is rated into the
        return — so if the value presented does not match the current
        version, the filing is rejected with `ERR_STALE_VERSION` (HTTP 412),
        because the content the filer reviewed is stale."

        Design: Corner/cross_cutting_layers/occ_return_file_stale_version_rejected
        """
        ctx, _ev1, ret = setup_return_with_rated_event()
        ev2 = create_event(ctx["registration"], ctx["jurisdiction"],
                           ctx["product_class"],
                           event_date="2026-08-10T00:00:00Z",
                           quantity_units=100)
        classify_event(ev2["id"])
        validate_success(
            api.submit_return(ret["id"], make_analyst_headers("analyst-1")))
        v_seen = get_return_version(ret["id"])

        # A late event rated into the SUBMITTED return bumps its version.
        rate_event(ev2["id"])
        v_after = get_return_version(ret["id"])
        assert v_after > v_seen, "event inclusion must bump the return version"

        stale = api.file_return(ret["id"], v_seen,
                                make_reviewer_headers("reviewer-1"))
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)
        still = validate_success(api.get_return(ret["id"], new_reviewer_headers()))
        assert still["filing_status"] == "SUBMITTED"

        filed = api.file_return(ret["id"], get_return_version(ret["id"]),
                                make_reviewer_headers("reviewer-1"))
        assert validate_success(filed)["filing_status"] == "FILED"


class TestValidationOrderTieBreaks:
    def test_rate_draft_event_in_filed_period_yields_invalid_state(self, api):
        """PRD §2.10: "When a request would fail several checks, the server
        evaluates them in a fixed order and reports the earliest failure, so
        a caller always sees the same error for the same combination of
        defects." The order ranks "(5) state legality of the requested
        transition, including terminal-state lockdown, yielding
        `ERR_INVALID_STATE` (HTTP 409)" ahead of "(10) temporal rules in the
        order period lock, bad-debt earliest date, claim latest date, bond
        window elapsed, and records retention" — a DRAFT event rated in a
        FILED period fails the state check, not the period lock.

        Design: Difficulty/priority_pair_validation_conflict/state_beats_period_temporal_on_event_rate
        """
        ctx, _ev1, _filed = setup_filed_return()
        ev2 = create_event(ctx["registration"], ctx["jurisdiction"],
                           ctx["product_class"],
                           event_date="2026-08-10T00:00:00Z",
                           quantity_units=5)
        assert ev2["status"] == "DRAFT"
        resp = api.rate_event(ev2["id"], {}, new_analyst_headers())
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_rate_draft_event_rejection_leaves_state_untouched(self, api):
        """PRD §2.10: "the server evaluates them in a fixed order and reports
        the earliest failure, so a caller always sees the same error for the
        same combination of defects." The rejected rate attempt must not
        mutate the event or reopen the filed period.

        Design: Difficulty/priority_pair_validation_conflict/state_beats_period_temporal_on_event_rate
        """
        ctx, _ev1, filed = setup_filed_return()
        ev2 = create_event(ctx["registration"], ctx["jurisdiction"],
                           ctx["product_class"],
                           event_date="2026-08-10T00:00:00Z",
                           quantity_units=5)
        api.rate_event(ev2["id"], {}, new_analyst_headers())
        event = validate_success(
            api.get_taxable_event(ev2["id"], new_analyst_headers()))
        assert event["status"] == "DRAFT"
        ret = validate_success(api.get_return(filed["id"], new_analyst_headers()))
        assert ret["filing_status"] == "FILED"

    def test_amend_with_hold_and_foreign_event_yields_audit_hold(self, api):
        """PRD §2.10: "(8) the audit records hold; (9) registration-active
        requirements; (10) temporal rules in the order period lock, bad-debt
        earliest date, claim latest date, bond window elapsed, and records
        retention; (11) uniqueness constraints in the order registrant tax
        identifier, authority and product codes, registration, return, open
        amendment, rate window overlap, certificate window overlap, and audit
        range overlap; (12) movement receipt quantity bounds; (13)
        registrant-chain referential integrity" — the records hold (8)
        precedes the registrant-chain check (13), so an amend that violates
        both reports `ERR_AUDIT_RECORDS_HOLD`. PRD §3.9: "each rejected with
        `ERR_AUDIT_RECORDS_HOLD`: opening an amendment of a return of the
        period".

        Design: Difficulty/priority_pair_validation_conflict/audit_hold_beats_cross_registrant_on_amend
        """
        ctx1, _ev1, filed1 = setup_filed_return()
        ctx2 = setup_active_registration(
            jurisdiction_overrides={"code": "NV-TX", "name": "Nevada"})
        foreign = create_rated_event(
            ctx2["registration"], ctx2["jurisdiction"],
            ctx2["product_class"], event_date="2026-08-04T00:00:00Z",
            quantity_units=7)
        create_audit_case(ctx1["registration"], ctx1["jurisdiction"],
                          period_start="2026-08", period_end="2026-08")
        resp = api.amend_return(
            filed1["id"],
            {"expected_return_version": get_return_version(filed1["id"]),
             "add_event_ids": [foreign["id"]]},
            new_analyst_headers())
        validate_error(resp, ApiErrorId.ERR_AUDIT_RECORDS_HOLD)

    def test_amend_rejected_attempt_creates_no_amendment(self, api):
        """PRD §3.9: "while it covers a period it blocks five operations
        outright, each rejected with `ERR_AUDIT_RECORDS_HOLD`: opening an
        amendment of a return of the period" — a rejected attempt leaves the
        parent's amendment list empty.

        Design: Difficulty/priority_pair_validation_conflict/audit_hold_beats_cross_registrant_on_amend
        """
        ctx1, _ev1, filed1 = setup_filed_return()
        ctx2 = setup_active_registration(
            jurisdiction_overrides={"code": "NV-TX", "name": "Nevada"})
        foreign = create_rated_event(
            ctx2["registration"], ctx2["jurisdiction"],
            ctx2["product_class"], event_date="2026-08-04T00:00:00Z",
            quantity_units=7)
        create_audit_case(ctx1["registration"], ctx1["jurisdiction"],
                          period_start="2026-08", period_end="2026-08")
        api.amend_return(
            filed1["id"],
            {"expected_return_version": get_return_version(filed1["id"]),
             "add_event_ids": [foreign["id"]]},
            new_analyst_headers())
        rows, meta = validate_paginated(api.list_returns(
            new_analyst_headers(),
            params={"amendment_of_id": filed1["id"]}))
        assert meta["total_count"] == 0 and rows == []

    def test_bad_debt_too_early_preempts_already_claimed(self, api):
        """PRD §2.10: "(10) temporal rules in the order period lock, bad-debt
        earliest date, claim latest date, bond window elapsed, and records
        retention" ranks ahead of "(15) linkability of certificates,
        movements, claim events, export documentation, and rate resolution" —
        a BAD_DEBT claim inside the 183-day embargo whose event is also on a
        live claim reports `ERR_BAD_DEBT_TOO_EARLY`. PRD §3.8: "A `BAD_DEBT`
        claim may be submitted no earlier than one hundred eighty-three days
        after the return's `filed_at` — earlier attempts fail with
        `ERR_BAD_DEBT_TOO_EARLY`".

        Design: Difficulty/priority_pair_validation_conflict/bad_debt_timing_beats_already_claimed
        """
        ctx, ev, filed, _applied = setup_applied_export_claim()
        # Filed at the default clock 2026-08-01; 2026-11-09 is only 100 days
        # later — inside the 183-day embargo.
        validate_success(
            api.set_clock("2026-11-09T00:00:00Z", new_admin_headers()))
        clm2 = create_claim(ctx["registration"], filed, [ev["id"]],
                            claim_type="BAD_DEBT",
                            justification="customer insolvent")
        resp = api.submit_credit_claim(
            clm2["id"], make_analyst_headers("analyst-1"))
        validate_error(resp, ApiErrorId.ERR_BAD_DEBT_TOO_EARLY)

    def test_bad_debt_rejected_claim_stays_draft(self, api):
        """PRD §3.8: "A new claim starts in `DRAFT` with
        `submitted_by_user_id` and `reviewed_by_user_id` unset" and "The
        claim moves to `SUBMITTED`." only on a valid submission — a
        submission rejected for the bad-debt embargo leaves the claim in
        `DRAFT`.

        Design: Difficulty/priority_pair_validation_conflict/bad_debt_timing_beats_already_claimed
        """
        ctx, ev, filed, _applied = setup_applied_export_claim()
        validate_success(
            api.set_clock("2026-11-09T00:00:00Z", new_admin_headers()))
        clm2 = create_claim(ctx["registration"], filed, [ev["id"]],
                            claim_type="BAD_DEBT",
                            justification="customer insolvent")
        api.submit_credit_claim(clm2["id"], make_analyst_headers("analyst-1"))
        claim = validate_success(
            api.get_credit_claim(clm2["id"], new_analyst_headers()))
        assert claim["status"] == "DRAFT"
