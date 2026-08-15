"""Authentication, role authorization, ownership scoping, and segregation of
duties on covenant waivers."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    complete_inspection,
    create_borrower,
    create_inspector,
    create_loan,
    create_property,
    create_statement_payload,
    get_success_data,
    make_borrower_headers,
    make_inspector_headers,
    make_master_servicer_headers,
    make_special_servicer_headers,
    newest_assessment,
    schedule_inspection,
    setup_watchlist_via_dscr_breach,
    single_watchlist_entry,
    submit_statement,
    validate_error,
    validate_paginated,
    validate_success,
)

MS = TEST_USERS["master_servicer_headers"]
SS = TEST_USERS["special_servicer_headers"]


class TestAuthentication:
    def test_request_missing_auth_returns_unauthenticated(self, api):
        """PRD §2.1: "A request missing either header, naming an undeclared role,
        or — for the entity-backed roles below — presenting an `X-User-ID` that
        does not correspond to an existing entity of that kind is rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/request_missing_auth_returns_unauthenticated
        """
        resp = api.create_borrower(
            {"legal_name": "Anon", "tax_id": "TX-ANO", "contact_email": "anon@x.com"},
            {})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


class TestRoleAuthorization:
    def test_borrower_cannot_review_statement(self, api):
        """PRD §3.2: "Statements arrive in `SUBMITTED` status and are decided
        exclusively by a `MasterServicer` — a borrower attempting to review even
        its own statement draws `ERR_UNAUTHORIZED`."

        Design: Corner/validations/borrower_cannot_review_statement
        """
        borrower = create_borrower(legal_name="Role Co", tax_id="TX-ROL",
                                   contact_email="rol@x.com")
        loan = create_loan(borrower["id"], loan_number="LN-ROL",
                           dscr_basis="T3_ANNUALIZED")
        stmt = submit_statement(loan["id"], borrower["id"], "OPERATING_STATEMENT",
                                "2026-04-01T00:00:00Z", "2026-06-30T00:00:00Z",
                                net_operating_income_cents=20_000_000)
        resp = api.review_statement(stmt["id"], {"decision": "ACCEPT"},
                                    make_borrower_headers(borrower["id"]))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
        after = get_success_data(api.get_statement(stmt["id"], MS))
        assert after["status"] == "SUBMITTED", "the rejected review changes nothing"

    def test_rbac_exclusive_operation_denials(self, api):
        """PRD §2.1: "A request whose role does not appear on the target
        endpoint's authorized list is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD §4: `POST /borrowers` is authorized for MasterServicer;
        `POST /covenant-assessments/{id}/waive` for SpecialServicer;
        `POST /watchlist-entries/{id}/escalate` for MasterServicer;
        `POST /properties/{id}/inspections` for MasterServicer.

        Design: Corner/rbac/rbac_exclusive_operation_denials
        """
        ctx = setup_watchlist_via_dscr_breach(tax_id="TX-RBC")
        loan = ctx["loan"]
        borrower = ctx["borrower"]
        prop = create_property(loan["id"], address="1 Rbac St")
        inspector = create_inspector(full_name="Rbac Spect", license_no="LIC-RBC")
        insp = schedule_inspection(prop["id"], inspector["id"],
                                   scheduled_start="2026-08-01T09:00:00Z",
                                   scheduled_end="2026-08-01T10:00:00Z")

        # An OPEN assessment and an ACTIVE entry must exist as denial targets.
        assessment = ctx["assessment"]
        assert assessment["status"] == "OPEN"
        complete_inspection(insp["id"], inspector["id"], "POOR")
        entry = single_watchlist_entry(loan["id"], criterion="POOR_INSPECTION",
                                       status="ACTIVE")

        e1 = api.create_borrower(
            {"legal_name": "SS Onboard", "tax_id": "TX-SSO",
             "contact_email": "sso@x.com"}, SS)
        validate_error(e1, ApiErrorId.ERR_UNAUTHORIZED)

        e2 = api.waive_assessment(assessment["id"], {"waiver_reason": "ms attempt"},
                                  make_master_servicer_headers("ms_user_9"))
        validate_error(e2, ApiErrorId.ERR_UNAUTHORIZED)

        e3 = api.escalate_watchlist_entry(entry["id"],
                                          make_borrower_headers(borrower["id"]))
        validate_error(e3, ApiErrorId.ERR_UNAUTHORIZED)

        e4 = api.schedule_inspection(
            prop["id"],
            {"inspector_id": inspector["id"],
             "scheduled_start": "2026-08-02T09:00:00Z",
             "scheduled_end": "2026-08-02T10:00:00Z"},
            make_inspector_headers(inspector["id"]))
        validate_error(e4, ApiErrorId.ERR_UNAUTHORIZED)

        remaining = newest_assessment(loan["id"], params={"assessment_type": "DSCR"})
        assert remaining["status"] == "OPEN", "the denied waiver changes nothing"
        still_active = single_watchlist_entry(loan["id"], criterion="POOR_INSPECTION",
                                              status="ACTIVE")
        assert still_active["id"] == entry["id"], "the denied escalate changes nothing"

    def test_rbac_conditional_close_outcome_denials(self, api):
        """PRD §3.5: "The assigned inspector — and only that inspector, with the
        check comparing `X-User-ID` against the inspection's `inspector_id` and
        mismatches drawing `ERR_OWNERSHIP_MISMATCH` — closes with outcome
        `COMPLETED`, supplying a `condition_rating` of `GOOD`, `FAIR`, `POOR`, or
        `CRITICAL` and optional free-text `findings`; the completion stamps
        `completed_at`, which remains null until then. A `MasterServicer` instead
        closes with outcome `CANCELLED`."

        Design: Corner/rbac/rbac_conditional_close_outcome_denials
        """
        ctx_borrower = create_borrower(legal_name="Close Co", tax_id="TX-CLO",
                                       contact_email="clo@x.com")
        loan = create_loan(ctx_borrower["id"], loan_number="LN-CLO",
                           original_principal_cents=100_000_000, note_rate=0.05)
        prop = create_property(loan["id"], address="1 Clo St")
        inspector = create_inspector(full_name="Clo Spect", license_no="LIC-CLO")
        insp1 = schedule_inspection(prop["id"], inspector["id"],
                                    scheduled_start="2026-08-05T09:00:00Z",
                                    scheduled_end="2026-08-05T10:00:00Z")
        insp2 = schedule_inspection(prop["id"], inspector["id"],
                                    scheduled_start="2026-08-05T10:00:00Z",
                                    scheduled_end="2026-08-05T11:00:00Z")

        e1 = api.close_inspection(insp1["id"],
                                  {"outcome": "COMPLETED", "condition_rating": "GOOD"},
                                  MS)
        validate_error(e1, ApiErrorId.ERR_UNAUTHORIZED)

        e2 = api.close_inspection(insp2["id"], {"outcome": "CANCELLED"},
                                  make_inspector_headers(inspector["id"]))
        validate_error(e2, ApiErrorId.ERR_UNAUTHORIZED)

        rows, _meta = validate_paginated(api.list_inspections(prop["id"], MS))
        by_id = {r["id"]: r for r in rows}
        assert by_id[insp1["id"]]["status"] == "SCHEDULED"
        assert by_id[insp2["id"]]["status"] == "SCHEDULED"


class TestOwnershipScoping:
    def test_borrower_cannot_submit_statement_for_other_loan(self, api):
        """PRD §2.1: "A borrower writing into another borrower's chain is
        rejected with `ERR_OWNERSHIP_MISMATCH` (HTTP 403)."

        Design: Corner/validations/borrower_cannot_submit_statement_for_other_loan
        """
        owner_a = create_borrower(legal_name="Owner A", tax_id="TX-OWA",
                                  contact_email="a@x.com")
        owner_b = create_borrower(legal_name="Owner B", tax_id="TX-OWB",
                                  contact_email="b@x.com")
        loan_a = create_loan(owner_a["id"], loan_number="LN-OWA",
                             original_principal_cents=100_000_000, note_rate=0.05)
        resp = api.create_statement(
            loan_a["id"],
            create_statement_payload("RENT_ROLL", "2026-04-01T00:00:00Z",
                                     "2026-06-30T00:00:00Z", occupancy_pct=90),
            make_borrower_headers(owner_b["id"]))
        validate_error(resp, ApiErrorId.ERR_OWNERSHIP_MISMATCH)

    def test_borrower_read_other_loan_returns_not_found(self, api):
        """PRD §2.1: "Reads are scoped rather than forbidden: an entity-backed
        role reading a resource outside its own scope — a borrower reading another
        borrower's loan chain, an inspector reading another inspector's schedule —
        receives `ERR_NOT_FOUND` (HTTP 404), exactly as if the resource did not
        exist."

        Design: Corner/validations/borrower_read_other_loan_returns_not_found
        """
        owner_a = create_borrower(legal_name="Reader A", tax_id="TX-RDA",
                                  contact_email="ra@x.com")
        owner_b = create_borrower(legal_name="Reader B", tax_id="TX-RDB",
                                  contact_email="rb@x.com")
        loan_a = create_loan(owner_a["id"], loan_number="LN-RDA",
                             original_principal_cents=100_000_000, note_rate=0.05)
        resp = api.get_loan(loan_a["id"], make_borrower_headers(owner_b["id"]))
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_inspector_cannot_complete_others_inspection(self, api):
        """PRD §2.1: "Completing a property inspection compares the inspection's
        assigned `inspector_id` to `X-User-ID`, and a mismatch is rejected with
        `ERR_OWNERSHIP_MISMATCH` (HTTP 403)."

        Design: Corner/validations/inspector_cannot_complete_others_inspection
        """
        borrower = create_borrower(legal_name="Insp Co", tax_id="TX-INS",
                                   contact_email="ins@x.com")
        loan = create_loan(borrower["id"], loan_number="LN-INS",
                           original_principal_cents=100_000_000, note_rate=0.05)
        prop = create_property(loan["id"], address="1 Insp St")
        inspector1 = create_inspector(full_name="I One", license_no="LIC-I1")
        inspector2 = create_inspector(full_name="I Two", license_no="LIC-I2")
        insp = schedule_inspection(prop["id"], inspector1["id"],
                                   scheduled_start="2026-08-05T09:00:00Z",
                                   scheduled_end="2026-08-05T10:00:00Z")
        resp = api.close_inspection(
            insp["id"], {"outcome": "COMPLETED", "condition_rating": "GOOD"},
            make_inspector_headers(inspector2["id"]))
        validate_error(resp, ApiErrorId.ERR_OWNERSHIP_MISMATCH)

        rows, _meta = validate_paginated(api.list_inspections(prop["id"], MS))
        assert rows[0]["status"] == "SCHEDULED", "the mismatched completion changes nothing"


class TestSegregationOfDuties:
    def test_waive_by_reviewing_user_rejected_sod(self, api):
        """PRD §3.2: "Segregation of duties forbids the waiver from being the
        operator of record upstream: for a DSCR assessment the acting `X-User-ID`
        must differ from the source statement's `reviewed_by_user_id`, and for an
        LTV assessment it must differ from the property's `appraised_by_user_id`;
        a violation is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

        Design: Corner/validations/waive_by_reviewing_user_rejected_sod
        """
        ctx = setup_watchlist_via_dscr_breach(tax_id="TX-SOD",
                                              reviewer_id="ms_user_1")
        assessment = ctx["assessment"]
        assert assessment["status"] == "OPEN"
        # The waiving SpecialServicer presents the SAME operator id that the
        # accepting MasterServicer recorded as reviewed_by_user_id.
        resp = api.waive_assessment(
            assessment["id"], {"waiver_reason": "self-waiver attempt"},
            make_special_servicer_headers("ms_user_1"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        remaining = newest_assessment(ctx["loan"]["id"],
                                      params={"assessment_type": "DSCR"})
        assert remaining["status"] == "OPEN", "the SoD-blocked waiver changes nothing"
