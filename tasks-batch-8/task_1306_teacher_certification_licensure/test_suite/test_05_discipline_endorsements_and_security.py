"""Endorsements, misconduct investigation, disciplinary cascades, and the
authentication/authorization boundary."""
from test_helpers import (
    EVALUATOR,
    INTAKE,
    INVESTIGATOR,
    LEGAL,
    NON_EXISTENT_UUID,
    ApiErrorId,
    add_transcript,
    advance_application,
    api_client,
    create_application,
    create_deficiency_plan,
    issue_action,
    issue_emergency_permit,
    make_applicant_headers,
    make_background_investigator_headers,
    make_legal_officer_headers,
    pay_application_fee,
    propose_action,
    register_applicant,
    request_endorsement,
    set_clock,
    setup_adjudicated_case,
    setup_licensed_applicant,
    transition_endorsement,
    transition_plan,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestEndorsementLifecycle:

    def test_endorsement_activate_twice_rejected(self):
        """PRD section 3.9: "A new endorsement starts in `PENDING_EVALUATION`.
        The evaluator activates it to `ACTIVE` — activation requires the
        license itself to be `ACTIVE` (else `ERR_INVALID_STATE`) — or denies
        it to `DENIED`."
        PRD section 2.5: "The target entity must be in a state from which the
        requested transition exists, and terminal states reject every
        transition, else `ERR_INVALID_STATE`."

        Design: Corner/state_machines/endorsement_activate_twice_rejected
        """
        ctx = setup_licensed_applicant(full_name="Zoe Zo", email="zoe@x.com")
        license_id = ctx["license"]["id"]
        endorsement = request_endorsement(license_id, ctx["applicant"]["id"])
        activated = transition_endorsement(endorsement["id"], "ACTIVE", EVALUATOR)
        assert activated["status"] == "ACTIVE"
        resp = api_client.transition_endorsement(
            endorsement["id"], {"to_status": "ACTIVE"}, EVALUATOR)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        fetched = validate_success(
            api_client.get_endorsement(endorsement["id"], EVALUATOR))
        assert fetched["status"] == "ACTIVE"

    def test_endorsement_duplicate_base_subject_rejected(self):
        """PRD section 3.9: "The owning `Applicant` requests an endorsement
        with the desired `subject_area` and `grade_band`; the request is
        rejected with `ERR_ENDORSEMENT_DUPLICATE` when the license already
        carries that `subject_area` as its base subject or as an endorsement
        in `PENDING_EVALUATION` or `ACTIVE`."

        Design: Corner/validations/endorsement_duplicate_base_subject_rejected
        """
        ctx = setup_licensed_applicant(full_name="Pia Pi", email="pia@x.com")
        resp = api_client.create_endorsement(
            ctx["license"]["id"],
            {"subject_area": "MATHEMATICS", "grade_band": "PK_6"},
            make_applicant_headers(ctx["applicant"]["id"]))
        validate_error(resp, ApiErrorId.ERR_ENDORSEMENT_DUPLICATE)

    def _active_endorsement_count(self, license_id):
        data, _ = validate_paginated(
            api_client.list_endorsements(license_id, EVALUATOR))
        return sum(1 for row in data if row["status"] == "ACTIVE")

    def test_endorsement_add_activate_remove_conserves_active_count(self):
        """PRD section 3.9: "A new endorsement starts in `PENDING_EVALUATION`.
        The evaluator activates it to `ACTIVE` — activation requires the
        license itself to be `ACTIVE` (else `ERR_INVALID_STATE`) — or denies
        it to `DENIED`. The licensee removes an `ACTIVE` endorsement to
        `REMOVED`."

        Design: Difficulty/compensating_invariant/endorsement_add_remove_conserves_active_count
        """
        ctx = setup_licensed_applicant(full_name="Sam Sa", email="sam@x.com")
        license_id = ctx["license"]["id"]
        applicant_id = ctx["applicant"]["id"]
        assert self._active_endorsement_count(license_id) == 0
        endorsement = request_endorsement(license_id, applicant_id)
        transition_endorsement(endorsement["id"], "ACTIVE", EVALUATOR)
        assert self._active_endorsement_count(license_id) == 1
        removed = transition_endorsement(
            endorsement["id"], "REMOVED", make_applicant_headers(applicant_id))
        assert removed["status"] == "REMOVED"
        assert self._active_endorsement_count(license_id) == 0

    def test_two_endorsements_remove_one_leaves_one(self):
        """PRD section 3.9: "A new endorsement starts in `PENDING_EVALUATION`.
        The evaluator activates it to `ACTIVE` — activation requires the
        license itself to be `ACTIVE` (else `ERR_INVALID_STATE`) — or denies
        it to `DENIED`. The licensee removes an `ACTIVE` endorsement to
        `REMOVED`."

        Design: Difficulty/compensating_invariant/endorsement_add_remove_conserves_active_count
        """
        ctx = setup_licensed_applicant(full_name="Sam Sb", email="samb@x.com")
        license_id = ctx["license"]["id"]
        applicant_id = ctx["applicant"]["id"]
        first = request_endorsement(license_id, applicant_id,
                                    subject_area="SPECIAL_EDUCATION",
                                    grade_band="PK_6")
        second = request_endorsement(license_id, applicant_id,
                                     subject_area="SCIENCE", grade_band="G5_8")
        transition_endorsement(first["id"], "ACTIVE", EVALUATOR)
        transition_endorsement(second["id"], "ACTIVE", EVALUATOR)
        assert self._active_endorsement_count(license_id) == 2
        transition_endorsement(first["id"], "REMOVED",
                               make_applicant_headers(applicant_id))
        assert self._active_endorsement_count(license_id) == 1
        fetched = validate_success(
            api_client.get_endorsement(second["id"], EVALUATOR))
        assert fetched["status"] == "ACTIVE"


class TestMisconductCaseGates:

    def test_adjudication_without_finding_rejected(self):
        """PRD section 3.9: "adjudication requires the request to carry the
        `finding`, either `SUBSTANTIATED` or `UNSUBSTANTIATED` (a missing
        finding is rejected with `ERR_CASE_FINDING_REQUIRED`)"

        Design: Corner/validations/adjudication_without_finding_rejected
        """
        ctx = setup_licensed_applicant(full_name="Bea Be", email="bea@x.com")
        resp = api_client.create_misconduct_case(
            ctx["license"]["id"],
            {"allegation_category": "FINANCIAL_MISCONDUCT"}, LEGAL)
        case = validate_success(resp, expected_status=201)
        resp = api_client.transition_misconduct_case(
            case["id"], {"to_status": "INVESTIGATING"},
            INVESTIGATOR)
        validate_success(resp)
        resp = api_client.transition_misconduct_case(
            case["id"], {"to_status": "HEARING"}, LEGAL)
        validate_success(resp)
        resp = api_client.transition_misconduct_case(
            case["id"], {"to_status": "ADJUDICATED"},
            make_legal_officer_headers("legal-5"))
        validate_error(resp, ApiErrorId.ERR_CASE_FINDING_REQUIRED)
        fetched = validate_success(
            api_client.get_misconduct_case(case["id"], EVALUATOR))
        assert fetched["status"] == "HEARING"

    def test_segregation_of_duties_on_adjudication_rejected(self):
        """PRD section 3.9: "segregation of duties forbids the adjudicating
        officer from being the recorded investigator: if the acting
        `X-User-ID` equals the case's `investigator_user_id`, the request is
        rejected with `ERR_SEGREGATION_OF_DUTIES`."
        PRD section 3.9: "A `BackgroundInvestigator` takes it to
        `INVESTIGATING`, and that move records the acting `X-User-ID` as the
        case's `investigator_user_id`."

        Design: Corner/rbac/segregation_of_duties_on_adjudication_rejected
        """
        ctx = setup_licensed_applicant(full_name="Jan Ja", email="jan@x.com")
        resp = api_client.create_misconduct_case(
            ctx["license"]["id"], {"allegation_category": "BOUNDARY_VIOLATION"},
            LEGAL)
        case = validate_success(resp, expected_status=201)
        resp = api_client.transition_misconduct_case(
            case["id"], {"to_status": "INVESTIGATING"},
            make_background_investigator_headers("inv-9"))
        case = validate_success(resp)
        assert case["investigator_user_id"] == "inv-9"
        resp = api_client.transition_misconduct_case(
            case["id"], {"to_status": "HEARING"},
            make_legal_officer_headers("legal-9"))
        validate_success(resp)
        resp = api_client.transition_misconduct_case(
            case["id"],
            {"to_status": "ADJUDICATED", "finding": "SUBSTANTIATED"},
            make_legal_officer_headers("inv-9"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        fetched = validate_success(
            api_client.get_misconduct_case(case["id"], EVALUATOR))
        assert fetched["status"] == "HEARING"
        assert fetched["investigator_user_id"] == "inv-9"


class TestSuspensionIntervalsAndSweeps:

    def _adjudicated_case_with_suspension(self, full_name, email):
        ctx = setup_licensed_applicant(full_name=full_name, email=email)
        case = setup_adjudicated_case(
            ctx["license"]["id"], allegation_category="INCOMPETENCE",
            investigator_id="inv-3", adjudicator_id="legal-3")
        action = propose_action(
            case["id"], sanction_type="SUSPENSION",
            suspension_start="2027-01-01T00:00:00Z",
            suspension_end="2027-06-30T00:00:00Z")
        return ctx, case, action

    def test_suspension_touching_endpoint_overlaps_closed_interval(self):
        """PRD section 3.9: "its closed interval — both endpoints included —
        must not overlap any `PROPOSED` or `ISSUED` suspension on the same
        license; under closed-interval semantics two suspensions that merely
        touch at an endpoint do overlap, and any such collision is rejected
        with `ERR_SUSPENSION_INTERVAL_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/suspension_closed_interval_touching_overlaps
        """
        _, case, action = self._adjudicated_case_with_suspension(
            "Qua Qu", "qua@x.com")
        resp = api_client.create_disciplinary_action(
            case["id"],
            {"sanction_type": "SUSPENSION",
             "suspension_start": "2027-06-30T00:00:00Z",
             "suspension_end": "2027-12-31T00:00:00Z"},
            LEGAL)
        validate_error(resp, ApiErrorId.ERR_SUSPENSION_INTERVAL_OVERLAP)
        fetched = validate_success(
            api_client.get_disciplinary_action(action["id"], EVALUATOR))
        assert fetched["status"] == "PROPOSED"

    def test_suspension_disjoint_interval_accepted(self):
        """PRD section 3.9: "its closed interval — both endpoints included —
        must not overlap any `PROPOSED` or `ISSUED` suspension on the same
        license"

        Design: Difficulty/resource_temporal_overlap/suspension_closed_interval_touching_overlaps
        """
        _, case, _ = self._adjudicated_case_with_suspension(
            "Qua Qb", "quab@x.com")
        resp = api_client.create_disciplinary_action(
            case["id"],
            {"sanction_type": "SUSPENSION",
             "suspension_start": "2027-07-01T00:00:00Z",
             "suspension_end": "2027-12-31T00:00:00Z"},
            LEGAL)
        second = validate_success(resp, expected_status=201)
        assert second["status"] == "PROPOSED"

    def test_suspension_issue_then_serve_restores_license(self):
        """PRD section 3.9: "Issuing a `SUSPENSION` moves an `ACTIVE` license
        to `SUSPENDED`, incrementing the license's `version`."
        PRD section 3.9: "a clock sweep moves an `ISSUED` action whose
        sanction is `SUSPENSION` to `SERVED` once the clock reaches
        `suspension_end`, and when no other `ISSUED` suspension remains on the
        license, the license returns from `SUSPENDED` to `ACTIVE` with its
        `version` incremented."
        PRD section 3.9: "In both cases the linked case moves from
        `ADJUDICATED` to `SANCTION_ISSUED`."

        Design: Corner/state_machines/suspension_issue_then_serve_restores_license
        """
        ctx, case, action = self._adjudicated_case_with_suspension(
            "Eve Ev", "eve@x.com")
        issue_action(action["id"])
        fetched_license = validate_success(
            api_client.get_license(ctx["license"]["id"], EVALUATOR))
        assert fetched_license["status"] == "SUSPENDED"
        fetched_case = validate_success(
            api_client.get_misconduct_case(case["id"], EVALUATOR))
        assert fetched_case["status"] == "SANCTION_ISSUED"
        set_clock("2027-07-01T00:00:00Z")
        fetched_action = validate_success(
            api_client.get_disciplinary_action(action["id"], EVALUATOR))
        assert fetched_action["status"] == "SERVED"
        fetched_license = validate_success(
            api_client.get_license(ctx["license"]["id"], EVALUATOR))
        assert fetched_license["status"] == "ACTIVE"


class TestRevocationCascade:

    def test_revocation_cascades_license_applicant_endorsement_permit(self):
        """PRD section 3.9: "Issuing a `REVOCATION` moves a license in
        `ACTIVE` or `SUSPENDED` to `REVOKED` and then cascades three links
        deep: the applicant becomes `BARRED`; every endorsement of the license
        in `PENDING_EVALUATION` or `ACTIVE` moves to `REVOKED`; and the
        applicant's new `BARRED` status revokes every emergency permit of that
        applicant in `ISSUED` or `ACTIVE`"
        PRD section 3.9: "In both cases the linked case moves from
        `ADJUDICATED` to `SANCTION_ISSUED`."

        Design: Difficulty/transitive_cascade/revocation_cascade_license_applicant_permit
        """
        ctx = setup_licensed_applicant(full_name="Hal Ha", email="hal@x.com")
        applicant_id = ctx["applicant"]["id"]
        license_id = ctx["license"]["id"]
        endorsement = request_endorsement(license_id, applicant_id,
                                          subject_area="SPECIAL_EDUCATION",
                                          grade_band="PK_6")
        transition_endorsement(endorsement["id"], "ACTIVE", EVALUATOR)
        # Second application of the same applicant, holding an ACTIVE permit.
        app2 = create_application(applicant_id, pathway="ALTERNATIVE",
                                  subject_area="SCIENCE", grade_band="G5_8")
        pay_application_fee(app2["id"], applicant_id)
        advance_application(app2["id"], "INTAKE_REVIEW", INTAKE)
        advance_application(app2["id"], "EVALUATION", INTAKE)
        app2 = advance_application(app2["id"], "DEFICIENCY_PENDING", EVALUATOR)
        plan2 = create_deficiency_plan(app2["id"], app2["version"])
        transition_plan(plan2["id"], "ACCEPTED")
        permit = issue_emergency_permit(
            app2["id"], district_code="D01",
            valid_from="2026-08-01T00:00:00Z",
            valid_until="2027-08-01T00:00:00Z")
        set_clock("2026-08-10T00:00:00Z")
        fetched_permit = validate_success(
            api_client.get_emergency_permit(permit["id"], EVALUATOR))
        assert fetched_permit["status"] == "ACTIVE"
        case = setup_adjudicated_case(
            license_id, allegation_category="CRIMINAL_CONDUCT",
            investigator_id="inv-1", adjudicator_id="legal-1")
        action = propose_action(case["id"], sanction_type="REVOCATION")
        issue_action(action["id"])
        fetched_license = validate_success(
            api_client.get_license(license_id, EVALUATOR))
        assert fetched_license["status"] == "REVOKED"
        fetched_applicant = validate_success(
            api_client.get_applicant(applicant_id, EVALUATOR))
        assert fetched_applicant["status"] == "BARRED"
        fetched_endorsement = validate_success(
            api_client.get_endorsement(endorsement["id"], EVALUATOR))
        assert fetched_endorsement["status"] == "REVOKED"
        fetched_permit = validate_success(
            api_client.get_emergency_permit(permit["id"], EVALUATOR))
        assert fetched_permit["status"] == "REVOKED"
        fetched_case = validate_success(
            api_client.get_misconduct_case(case["id"], EVALUATOR))
        assert fetched_case["status"] == "SANCTION_ISSUED"

    def test_revocation_while_suspended_still_cascades(self):
        """PRD section 3.9: "Issuing a `REVOCATION` moves a license in
        `ACTIVE` or `SUSPENDED` to `REVOKED` and then cascades three links
        deep: the applicant becomes `BARRED`; every endorsement of the license
        in `PENDING_EVALUATION` or `ACTIVE` moves to `REVOKED`; and the
        applicant's new `BARRED` status revokes every emergency permit of that
        applicant in `ISSUED` or `ACTIVE`"

        Design: Difficulty/transitive_cascade/revocation_cascade_license_applicant_permit
        """
        ctx = setup_licensed_applicant(full_name="Hal Hb", email="halb@x.com")
        license_id = ctx["license"]["id"]
        endorsement = request_endorsement(license_id, ctx["applicant"]["id"])
        transition_endorsement(endorsement["id"], "ACTIVE", EVALUATOR)
        case1 = setup_adjudicated_case(
            license_id, allegation_category="INCOMPETENCE",
            investigator_id="inv-6", adjudicator_id="legal-6")
        suspension = propose_action(
            case1["id"], sanction_type="SUSPENSION",
            suspension_start="2027-01-01T00:00:00Z",
            suspension_end="2027-06-30T00:00:00Z")
        issue_action(suspension["id"])
        fetched_license = validate_success(
            api_client.get_license(license_id, EVALUATOR))
        assert fetched_license["status"] == "SUSPENDED"
        case2 = setup_adjudicated_case(
            license_id, allegation_category="CRIMINAL_CONDUCT",
            investigator_id="inv-7", adjudicator_id="legal-7")
        revocation = propose_action(case2["id"], sanction_type="REVOCATION")
        issue_action(revocation["id"])
        fetched_license = validate_success(
            api_client.get_license(license_id, EVALUATOR))
        assert fetched_license["status"] == "REVOKED"
        fetched_applicant = validate_success(
            api_client.get_applicant(ctx["applicant"]["id"], EVALUATOR))
        assert fetched_applicant["status"] == "BARRED"
        fetched_endorsement = validate_success(
            api_client.get_endorsement(endorsement["id"], EVALUATOR))
        assert fetched_endorsement["status"] == "REVOKED"


class TestSecurityBoundary:

    def test_missing_auth_headers_returns_unauthenticated(self):
        """PRD section 2.1: "Every request must carry two HTTP headers:
        `X-User-ID`, identifying the acting individual, and `X-User-Role`,
        naming the role under which that individual acts. A request missing
        either header, or presenting a role string outside the declared set,
        is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
        """
        resp = api_client.get_application(NON_EXISTENT_UUID, headers={})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)
        assert resp.status_code == 401

    def test_applicant_cannot_verify_transcript(self):
        """PRD section 2.1: "A request whose role is not in the endpoint's
        authorized role list — or, for entity-backed roles, whose identity
        does not own the target resource — is rejected with `ERR_FORBIDDEN`
        (HTTP 403)."
        PRD section 3.3: "Verification belongs to the `CredentialEvaluator`,
        who submits a target `verification_status` and, when verifying, the
        attested `subject_relevant_hours`"

        Design: Corner/rbac/applicant_cannot_verify_transcript_forbidden
        """
        applicant = register_applicant(full_name="Gia Gi", email="gia@x.com")
        app = create_application(applicant["id"], pathway="RECIPROCITY",
                                 subject_area="MATHEMATICS", grade_band="G7_12")
        transcript = add_transcript(app["id"], applicant["id"],
                                    institution_name="TX State")
        resp = api_client.verify_transcript(
            transcript["id"],
            {"verification_status": "VERIFIED", "subject_relevant_hours": 18},
            make_applicant_headers(applicant["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        fetched = validate_success(
            api_client.get_transcript(transcript["id"], EVALUATOR))
        assert fetched["verification_status"] == "UNVERIFIED"

    def test_applicant_cannot_pay_others_fee(self):
        """PRD section 2.1: "ownership checks on any resource that chains back
        to an applicant — an application, its transcripts, test scores,
        background checks, reciprocity evaluations, deficiency plans,
        emergency permits, and any license, endorsement, or CE credit derived
        from that applicant — compare the resource's applicant foreign key to
        `X-User-ID`, and a mismatch yields `ERR_FORBIDDEN`."

        Design: Corner/rbac/applicant_cannot_pay_others_fee_forbidden
        """
        applicant_a = register_applicant(full_name="Hal Ha2", email="hal2@x.com")
        app_a = create_application(applicant_a["id"], pathway="ALTERNATIVE",
                                   subject_area="ELEMENTARY", grade_band="PK_6")
        applicant_b = register_applicant(full_name="Ire Ir", email="ire@x.com")
        resp = api_client.pay_application_fee(
            app_a["id"], {"payment_token": "tok_x"},
            make_applicant_headers(applicant_b["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        fetched = validate_success(
            api_client.get_application(app_a["id"], EVALUATOR))
        assert fetched["fee_status"] == "UNPAID"
