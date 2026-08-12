"""Account applications, decision gates (certified institution, alt-ID,
barrier second-look, education), referral linkage, and barrier negotiation."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, TEST_USERS,
    make_institution_officer_headers, make_participant_headers,
    create_application_payload, decision_payload,
    setup_certified_institution, setup_documented_participant,
    setup_referral_docs_complete, setup_submitted_application,
    setup_declined_chex_case, create_event, book_referral, create_referral,
    create_participant, referral_docs_complete, create_application,
    decide_application, propose_case, counter_case, accept_case,
    create_pairing, complete_pairing, suspend_institution,
)

ADMIN = TEST_USERS["coalition_admin_headers"]
NAV = TEST_USERS["agency_navigator_headers"]


class TestDecisionInstitutionGate:
    def test_approve_after_suspend_rejected(self, api):
        """PRD §3.6: "Approval requires the institution to still be `CERTIFIED` (`ERR_INSTITUTION_NOT_CERTIFIED` otherwise)."
        PRD §3.2: "While an institution is `SUSPENDED` or `LAPSED`, creation of new account applications for it is blocked with `ERR_INSTITUTION_NOT_CERTIFIED`."

        Design: Difficulty/cross_entity_state_dependency/decision_requires_certified_institution
        """
        ctx = setup_submitted_application()  # application created while CERTIFIED
        suspend_institution(ctx["institution"]["id"])

        resp = api.decide_account_application(
            ctx["application"]["id"], decision_payload("APPROVE"),
            make_institution_officer_headers(ctx["institution"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INSTITUTION_NOT_CERTIFIED)

    def test_rejected_decision_leaves_application_untouched(self, api):
        """PRD §3.6: "Approval requires the institution to still be `CERTIFIED` (`ERR_INSTITUTION_NOT_CERTIFIED` otherwise)."
        PRD §3.6: "On approval the server mints the `account_number`, stamps `opened_at` with the current logical-clock reading, records the deciding officer's institution identity as `decided_by_user_id`, and creates two `RetentionCheckpoint` rows for the application"

        Design: Difficulty/cross_entity_state_dependency/decision_requires_certified_institution
        """
        ctx = setup_submitted_application()
        suspend_institution(ctx["institution"]["id"])
        api.decide_account_application(
            ctx["application"]["id"], decision_payload("APPROVE"),
            make_institution_officer_headers(ctx["institution"]["id"]),
        )

        app = get_success_data(api.get_account_application(ctx["application"]["id"], ADMIN))
        assert app["status"] == "SUBMITTED"
        assert app.get("account_number") is None, "no account_number minted"
        _, meta = validate_paginated(
            api.list_retention_checkpoints(
                ADMIN, params={"application_id": ctx["application"]["id"]}
            )
        )
        assert meta["total_count"] == 0, "no RetentionCheckpoints created"


class TestCreatePriorityPair:
    def test_docs_incomplete_beats_referral_mismatch(self, api):
        """PRD §2.10: "Compliance gates come seventh (segregation of duties, documentation completeness, alternative-ID admissibility, barrier-resolution, education-required, follow-up-due), temporal conflicts eighth (event window overlap, review-gap, campaign overlap), cross-entity state ninth (institution certified, standard effective, grant active, referral consistency, event bookable, campaign active), and capacity, quota, and fiscal limits tenth (event full, coach caseload, claim cap, grant funds, campaign budget, pending claims, negotiation rounds, certification lapsed)."
        PRD §3.6: "The participant's documentation must be complete — `ERR_DOCS_INCOMPLETE` when `docs_complete` is false."

        Design: Difficulty/priority_pair_validation_conflict/application_create_safety_vs_referential
        """
        ctx = setup_certified_institution()
        inst_id = ctx["institution"]["id"]
        # P1: VERIFIED identity doc but NO proof of address -> docs_complete false,
        # while the STATE_ID presented matches a VERIFIED doc (alt-ID leg passes).
        p1 = create_participant(id_documents=[
            {"doc_type": "STATE_ID", "status": "VERIFIED"},
        ])
        assert p1["docs_complete"] is False
        # P2 fully documented with a DOCS_COMPLETE referral R2.
        pr2 = setup_referral_docs_complete(full_name="Ben Okafor",
                                           date_of_birth="1985-11-02")

        resp = api.create_account_application(
            {
                "participant_id": p1["id"],
                "institution_id": inst_id,
                "id_type_presented": "STATE_ID",
                "referral_id": pr2["referral"]["id"],  # belongs to P2 -> mismatch
            },
            make_institution_officer_headers(inst_id),
        )
        validate_error(resp, ApiErrorId.ERR_DOCS_INCOMPLETE)

    def test_failed_create_leaves_no_application_row(self, api):
        """PRD §3.6: "The referral, when supplied, must belong to the named participant and must be in `DOCS_COMPLETE` or `BOOKED`; any violation of these linkage rules is rejected with `ERR_REFERRAL_MISMATCH`."
        PRD §3.6: "A created application lands in `SUBMITTED`."

        Design: Difficulty/priority_pair_validation_conflict/application_create_safety_vs_referential
        """
        ctx = setup_certified_institution()
        inst_id = ctx["institution"]["id"]
        p1 = create_participant(id_documents=[
            {"doc_type": "STATE_ID", "status": "VERIFIED"},
        ])
        pr2 = setup_referral_docs_complete(full_name="Ben Okafor",
                                           date_of_birth="1985-11-02")
        api.create_account_application(
            {
                "participant_id": p1["id"],
                "institution_id": inst_id,
                "id_type_presented": "STATE_ID",
                "referral_id": pr2["referral"]["id"],
            },
            make_institution_officer_headers(inst_id),
        )
        _, meta = validate_paginated(
            api.list_account_applications(ADMIN, params={"participant_id": p1["id"]})
        )
        assert meta["total_count"] == 0, "a rejected create persists no application"


class TestAltIdGate:
    def test_alt_id_not_in_standard_rejected(self, api):
        """PRD §3.6: "The `id_type_presented` is one of `STATE_ID`, `MATRICULA_CONSULAR`, `MUNICIPAL_ID`, or `FOREIGN_PASSPORT`; it must appear among the participant's `VERIFIED` documents, and when it is not `STATE_ID` it must additionally be permitted by the certified standard's `accepted_alt_id_types` — failures on either leg surface `ERR_ALT_ID_NOT_ACCEPTED`."

        Design: Corner/validations/alt_id_not_in_standard_rejected
        """
        # Certified standard accepts only MATRICULA_CONSULAR.
        ctx = setup_certified_institution(accepted_alt_id_types=("MATRICULA_CONSULAR",))
        inst_id = ctx["institution"]["id"]
        pr = setup_referral_docs_complete(id_doc_type="MUNICIPAL_ID")

        resp = api.create_account_application(
            {
                "participant_id": pr["participant"]["id"],
                "institution_id": inst_id,
                "id_type_presented": "MUNICIPAL_ID",
                "referral_id": pr["referral"]["id"],
            },
            make_institution_officer_headers(inst_id),
        )
        validate_error(resp, ApiErrorId.ERR_ALT_ID_NOT_ACCEPTED)
        _, meta = validate_paginated(
            api.list_account_applications(
                ADMIN, params={"participant_id": pr["participant"]["id"]}
            )
        )
        assert meta["total_count"] == 0


class TestBarrierSecondLookGate:
    def test_approve_flagged_without_resolved_case_rejected(self, api):
        """PRD §3.6: "When the participant's `prior_banking_record` is `FLAGGED`, or the decision payload's `chex_flagged` is true, approval additionally requires a `RESOLVED` barrier case to exist for this application — approving without one is rejected with `ERR_BARRIER_UNRESOLVED`."
        PRD §3.6: "A decline with `decline_reason` of `CHEX` moves the application to `DECLINED_CHEX` and creates a **BarrierCase** linked to the application — the ChexSystems second-look"

        Design: Corner/validations/approve_with_flagged_record_no_case_rejected
        """
        ctx = setup_submitted_application(prior_banking_record="FLAGGED")
        resp = api.decide_account_application(
            ctx["application"]["id"], decision_payload("APPROVE"),
            make_institution_officer_headers(ctx["institution"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_BARRIER_UNRESOLVED)

        app = get_success_data(api.get_account_application(ctx["application"]["id"], ADMIN))
        assert app["status"] == "SUBMITTED"
        _, meta = validate_paginated(
            api.list_barrier_cases(
                ADMIN, params={"application_id": ctx["application"]["id"]}
            )
        )
        assert meta["total_count"] == 0, "an APPROVE attempt spawns no case"


class TestEducationGate:
    def test_education_required_gate_on_approve(self, api):
        """PRD §3.6: "When the institution's certified standard declares `requires_financial_education`, approval requires the participant to hold an education pairing in `COMPLETED`, `FOLLOW_UP_DUE`, or `FOLLOW_UP_DONE` status, else `ERR_EDUCATION_REQUIRED`."

        Design: Corner/validations/education_required_gate_on_approve
        """
        ctx = setup_submitted_application(requires_financial_education=True)
        inst_id = ctx["institution"]["id"]
        officer = make_institution_officer_headers(inst_id)

        resp = api.decide_account_application(
            ctx["application"]["id"], decision_payload("APPROVE"), officer
        )
        validate_error(resp, ApiErrorId.ERR_EDUCATION_REQUIRED)
        app = get_success_data(api.get_account_application(ctx["application"]["id"], ADMIN))
        assert app["status"] == "SUBMITTED"

        pairing = create_pairing(ctx["participant"]["id"])
        complete_pairing(pairing["id"])
        data = validate_success(
            api.decide_account_application(
                ctx["application"]["id"], decision_payload("APPROVE"), officer
            ), 200
        )
        assert data["status"] == "OPENED", "gate is state-dependent, not sticky"


class TestReferralLinkage:
    def test_event_mismatch_with_booked_referral_rejected(self, api):
        """PRD §3.6: "Two optional linkages exist: a `referral_id` and an `event_id`. The `referral_id` is required when no `event_id` is present and optional for an event-day walk-in where `event_id` is present; when both are present, the `event_id` must equal the referral's `booked_event_id`. The referral, when supplied, must belong to the named participant and must be in `DOCS_COMPLETE` or `BOOKED`; any violation of these linkage rules is rejected with `ERR_REFERRAL_MISMATCH`."

        Design: Corner/validations/referral_event_mismatch_rejected
        """
        ctx = setup_certified_institution()
        inst_id = ctx["institution"]["id"]
        e1 = create_event(inst_id, venue_code="BR-1",
                          starts_at="2026-05-10T09:00:00Z", ends_at="2026-05-10T13:00:00Z")
        e2 = create_event(inst_id, venue_code="BR-2",
                          starts_at="2026-05-11T09:00:00Z", ends_at="2026-05-11T13:00:00Z")
        pr = setup_referral_docs_complete()
        book_referral(pr["referral"]["id"], e1["id"])

        resp = api.create_account_application(
            {
                "participant_id": pr["participant"]["id"],
                "institution_id": inst_id,
                "id_type_presented": "MATRICULA_CONSULAR",
                "referral_id": pr["referral"]["id"],
                "event_id": e2["id"],  # != referral.booked_event_id (E1)
            },
            make_institution_officer_headers(inst_id),
        )
        validate_error(resp, ApiErrorId.ERR_REFERRAL_MISMATCH)
        event1 = get_success_data(api.get_account_opening_event(e1["id"], ADMIN))
        assert event1["booked_count"] == 1, "no partial mutation"
        referral = get_success_data(api.get_referral(pr["referral"]["id"], NAV))
        assert referral["status"] == "BOOKED"


class TestDecisionConsistency:
    def test_decision_response_immediately_consistent(self, api):
        """PRD §3.6: "On approval the server mints the `account_number`, stamps `opened_at` with the current logical-clock reading, records the deciding officer's institution identity as `decided_by_user_id`, and creates two `RetentionCheckpoint` rows for the application, both `PENDING`"
        PRD §3.6: "The linked referral, if any, moves from `APPLIED` to `CLOSED_CONVERTED`; when that referral carries a `campaign_id`, the campaign's `spent_cents` increases by the campaign's `per_conversion_cents`. The participant's `pipeline_stage` is recomputed, and the institution's `accounts_opened_total` is incremented by one."
        PRD §2.5: "At startup the logical clock reads exactly `2026-05-01T00:00:00Z`; before any explicit set call it never falls back to wall-clock time."

        Design: Corner/consistency_model/decision_response_immediately_consistent
        """
        ctx = setup_submitted_application()
        data = validate_success(
            api.decide_account_application(
                ctx["application"]["id"], decision_payload("APPROVE"),
                make_institution_officer_headers(ctx["institution"]["id"]),
            ), 200
        )
        assert data["status"] == "OPENED"
        assert data.get("account_number"), "account_number minted on approval"
        assert str(data["opened_at"]).startswith("2026-05-01"), (
            "opened_at stamped from the logical clock at its startup default"
        )

        referral = get_success_data(api.get_referral(ctx["referral"]["id"], NAV))
        assert referral["status"] == "CLOSED_CONVERTED"
        inst = get_success_data(api.get_partner_institution(ctx["institution"]["id"], ADMIN))
        assert inst["accounts_opened_total"] == 1
        participant = get_success_data(api.get_participant(ctx["participant"]["id"], NAV))
        assert participant["pipeline_stage"] == "ACCOUNT_OPENED"


def _run_negotiation_cycle(api):
    """OPEN -> PLAN_PROPOSED -> COUNTERED -> PLAN_PROPOSED -> COUNTERED ->
    PLAN_PROPOSED -> RESOLVED; returns (context, case)."""
    ctx = setup_declined_chex_case()
    inst_id = ctx["institution"]["id"]
    case_id = ctx["case"]["id"]
    propose_case(case_id, inst_id, 20000)
    counter_case(case_id)
    propose_case(case_id, inst_id, 15000)
    counter_case(case_id)
    propose_case(case_id, inst_id, 12000)
    case = accept_case(case_id, ctx["participant"]["id"])
    return ctx, case


class TestBarrierNegotiationCycle:
    def test_cycle_pins_final_settlement_and_rounds(self, api):
        """PRD §3.6: "An `AgencyNavigator` counters a `PLAN_PROPOSED` case, optionally attaching a `resolution_note`; countering moves the case to `COUNTERED` and increments `negotiation_rounds` by one."
        PRD §3.6: "acceptance pins `final_settlement_cents` to the `proposed_settlement_cents` current at accept time, moves the case to `RESOLVED`, cascades the linked application from `DECLINED_CHEX` to `REINSTATED` (leaving its `decided_by_user_id` unchanged until the next decision), and recomputes the participant's pipeline stage."

        Design: Difficulty/non_linear_state_machine/barrier_case_negotiation_cycle
        """
        ctx, case = _run_negotiation_cycle(api)
        assert case["status"] == "RESOLVED"
        assert case["negotiation_rounds"] == 2, "one increment per counter, not per propose"
        assert case["final_settlement_cents"] == 12000, (
            "pinned to the accepted proposal, not the first"
        )

    def test_accept_cascades_application_to_reinstated(self, api):
        """PRD §3.6: "acceptance pins `final_settlement_cents` to the `proposed_settlement_cents` current at accept time, moves the case to `RESOLVED`, cascades the linked application from `DECLINED_CHEX` to `REINSTATED` (leaving its `decided_by_user_id` unchanged until the next decision), and recomputes the participant's pipeline stage."

        Design: Difficulty/non_linear_state_machine/barrier_case_negotiation_cycle
        """
        ctx, case = _run_negotiation_cycle(api)
        app = get_success_data(api.get_account_application(ctx["application"]["id"], ADMIN))
        assert app["status"] == "REINSTATED"


class TestBarrierEscalationGate:
    def test_escalate_before_three_rounds_rejected(self, api):
        """PRD §3.6: "Escalation is the officer's terminal denial: allowed only from `COUNTERED` (otherwise `ERR_INVALID_STATE`) and only once `negotiation_rounds` has reached at least 3 — escalating with rounds remaining is rejected with `ERR_NEGOTIATION_ROUNDS_REMAINING`."

        Design: Corner/validations/escalate_before_three_rounds_rejected
        """
        ctx = setup_declined_chex_case()
        inst_id = ctx["institution"]["id"]
        case_id = ctx["case"]["id"]
        propose_case(case_id, inst_id, 20000)
        counter_case(case_id)  # negotiation_rounds == 1

        resp = api.escalate_barrier_case(
            case_id, {}, make_institution_officer_headers(inst_id)
        )
        validate_error(resp, ApiErrorId.ERR_NEGOTIATION_ROUNDS_REMAINING)
        case = get_success_data(api.get_barrier_case(case_id, ADMIN))
        assert case["status"] == "COUNTERED"
        app = get_success_data(api.get_account_application(ctx["application"]["id"], ADMIN))
        assert app["status"] == "DECLINED_CHEX"


class TestBarrierAcceptRbac:
    def test_participant_cannot_accept_others_case(self, api):
        """PRD §3.6: "The participant — and only the participant whose `id` equals the case's `participant_id`, with anyone else rejected as `ERR_UNAUTHORIZED_ROLE` — accepts a `PLAN_PROPOSED` case, optionally attaching a `resolution_note`"

        Design: Corner/rbac/participant_cannot_accept_others_case
        """
        ctx = setup_declined_chex_case()
        inst_id = ctx["institution"]["id"]
        case_id = ctx["case"]["id"]
        propose_case(case_id, inst_id, 15000)
        other = create_participant(full_name="Ben Okafor", date_of_birth="1985-11-02")

        resp = api.accept_barrier_case(
            case_id, {}, make_participant_headers(other["id"])
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
        case = get_success_data(api.get_barrier_case(case_id, ADMIN))
        assert case["status"] == "PLAN_PROPOSED"
