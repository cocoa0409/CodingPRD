"""Support cases: the cyclic review machine, specialist selection,
determinations, checklist gating, and the verification cascade
(PRD §3.2, §3.4, §3.9)."""
from test_helpers import (
    ADMIN,
    IMPORTER,
    NON_EXISTENT_UUID,
    ApiErrorId,
    accept_case,
    add_senior,
    coord,
    create_matched_senior,
    create_specialist,
    create_status_event_payload,
    create_support_case,
    fresh_senior,
    get_checklist_for_senior,
    get_checklist_items,
    get_staff,
    grant_consent,
    make_specialist_headers,
    setup_campaign_with_school,
    setup_case_scenario,
    setup_verification_case,
    spec_headers,
    validate_error,
    validate_paginated,
    validate_success,
    verify_all_items,
)


class TestCaseReviewLoop:
    def test_review_loop_cycles_between_review_and_awaiting_family(self, api):
        """PRD §3.9: "requesting documents moves `IN_REVIEW` to
        `AWAITING_FAMILY`; documents arriving move `AWAITING_FAMILY` back to
        `IN_REVIEW`; escalation lifts either `IN_REVIEW` or `AWAITING_FAMILY`
        to `ESCALATED`."

        Design: Difficulty/non_linear_state_machine/support_case_review_loop_cycles
        """
        ctx = setup_case_scenario()
        case = create_support_case(
            ctx["school"],
            ctx["senior"]["id"],
            "SPECIAL_CIRCUMSTANCE",
            notes="possible homelessness liaison referral",
        )
        assert case["status"] == "OPEN"
        assert case["assigned_specialist_id"] == ctx["specialist"]["id"], (
            "the selector must assign the only ACTIVE CASE_SPECIALIST"
        )
        spec = spec_headers(ctx["specialist"])

        resp = api.accept_support_case(case["id"], spec)
        assert validate_success(resp, 200)["status"] == "IN_REVIEW"
        resp = api.request_documents(case["id"], spec)
        assert validate_success(resp, 200)["status"] == "AWAITING_FAMILY"
        resp = api.documents_received(case["id"], spec)
        assert validate_success(resp, 200)["status"] == "IN_REVIEW", (
            "the loop returns to IN_REVIEW — the machine is cyclic, not linear"
        )
        resp = api.escalate_support_case(case["id"], spec)
        assert validate_success(resp, 200)["status"] == "ESCALATED"

    def test_resolve_from_escalated_with_not_qualified_reverts_dependency(self, api):
        """PRD §3.9: "Resolution is possible from `IN_REVIEW` or `ESCALATED`"
        and "`NOT_QUALIFIED` instead returns a `PENDING_REVIEW` senior to
        `DEPENDENT`, leaving the checklist alone."
        PRD §3.9: "opening a `SPECIAL_CIRCUMSTANCE` referral moves the senior's
        `dependency_status` to `PENDING_REVIEW`" and "Resolving decrements the
        specialist's `active_case_count` with overload recovery re-evaluated."

        Design: Difficulty/non_linear_state_machine/support_case_review_loop_cycles
        """
        ctx = setup_case_scenario()
        case = create_support_case(
            ctx["school"], ctx["senior"]["id"], "SPECIAL_CIRCUMSTANCE"
        )
        assert fresh_senior(ctx["senior"]["id"])["dependency_status"] == (
            "PENDING_REVIEW"
        )
        spec = spec_headers(ctx["specialist"])
        api.accept_support_case(case["id"], spec)
        api.request_documents(case["id"], spec)
        api.documents_received(case["id"], spec)
        api.escalate_support_case(case["id"], spec)

        resp = api.resolve_support_case(case["id"], spec, "NOT_QUALIFIED")
        resolved = validate_success(resp, 200)
        assert resolved["status"] == "RESOLVED"
        assert resolved["resolution_outcome"] == "NOT_QUALIFIED"

        senior = fresh_senior(ctx["senior"]["id"])
        assert senior["dependency_status"] == "DEPENDENT", (
            "a NOT_QUALIFIED determination returns the senior to DEPENDENT"
        )
        staff = get_staff(ctx["specialist"]["id"])
        assert staff["active_case_count"] == 0, (
            f"resolve must decrement the caseload, got {staff['active_case_count']}"
        )


class TestCaseDeterminationRules:
    def test_determination_required_and_terminal_lockdown(self, api):
        """PRD §3.9: "a `SPECIAL_CIRCUMSTANCE` case requires the caller to
        supply a `resolution_outcome` of `INDEPENDENT_CONFIRMED` or
        `NOT_QUALIFIED` (`ERR_DETERMINATION_REQUIRED` when absent or invalid)."
        PRD §3.9: "Every case action requires the case to be in the state the
        action expects — acting on a `PAUSED`, terminal, or otherwise
        wrong-state case draws `ERR_CASE_NOT_ACTIONABLE`."

        Design: Corner/state_machines/special_case_determination_and_terminal_lockdown
        """
        ctx = setup_case_scenario()
        case = create_support_case(
            ctx["school"], ctx["senior"]["id"], "SPECIAL_CIRCUMSTANCE"
        )
        spec = spec_headers(ctx["specialist"])
        api.accept_support_case(case["id"], spec)

        # Resolve without the determination payload.
        resp = api.resolve_support_case(case["id"], spec)
        validate_error(resp, ApiErrorId.ERR_DETERMINATION_REQUIRED)
        resp = api.get_support_case(case["id"], coord(ctx["school"]))
        assert validate_success(resp, 200)["status"] == "IN_REVIEW"

        resp = api.resolve_support_case(case["id"], spec, "NOT_QUALIFIED")
        assert validate_success(resp, 200)["status"] == "RESOLVED"

        # RESOLVED is terminal: any further action is rejected.
        resp = api.escalate_support_case(case["id"], spec)
        validate_error(resp, ApiErrorId.ERR_CASE_NOT_ACTIONABLE)

    def test_independent_confirmed_regenerates_checklist(self, api):
        """PRD §3.9: "`INDEPENDENT_CONFIRMED` moves `dependency_status` from
        `DEPENDENT` or `PENDING_REVIEW` to `INDEPENDENT` and regenerates the
        checklist to the `INDEPENDENT_STANDARD` template: items whose
        `doc_type` has no place in the new template and that still sit in
        `PENDING` or `REJECTED` are auto-waived, items already `RECEIVED` or
        `VERIFIED` are kept, any new-template items not yet present are
        appended in `PENDING`, and the checklist status is re-evaluated — a
        `COMPLETE` checklist can legitimately fall back to `IN_PROGRESS`."

        Design: Corner/state_machines/special_circumstance_determination_regenerates_checklist
        """
        campaign, school = setup_campaign_with_school()
        specialist = create_specialist(campaign)
        senior, _aid, link, consent = create_matched_senior(
            campaign,
            school,
            student_ref="S1",
            full_name="Ana Lee",
            dob="2009-03-04",
            aid_status="SUBMITTED",
            consent_scopes=["STATUS_DETAIL"],
            consent_before_link=True,
        )
        assert link["status"] == "AUTO_CONFIRMED"
        checklist = get_checklist_for_senior(senior["id"])
        verify_all_items(school, checklist["id"])
        resp = api.get_document_checklist(checklist["id"], ADMIN)
        assert validate_success(resp, 200)["status"] == "COMPLETE"

        case = create_support_case(
            school, senior["id"], "SPECIAL_CIRCUMSTANCE",
            notes="foster youth liaison referral",
        )
        spec = spec_headers(specialist)
        api.accept_support_case(case["id"], spec)
        resp = api.resolve_support_case(case["id"], spec, "INDEPENDENT_CONFIRMED")
        resolved = validate_success(resp, 200)
        assert resolved["status"] == "RESOLVED"
        assert resolved["resolution_outcome"] == "INDEPENDENT_CONFIRMED"

        senior = fresh_senior(senior["id"])
        assert senior["dependency_status"] == "INDEPENDENT"

        resp = api.get_document_checklist(checklist["id"], ADMIN)
        checklist = validate_success(resp, 200)
        assert checklist["template_key"] == "INDEPENDENT_STANDARD"
        assert checklist["status"] == "IN_PROGRESS", (
            "the appended PENDING item must pull the COMPLETE checklist back "
            "to IN_PROGRESS"
        )

        by_doc_type = {
            item["doc_type"]: item["status"]
            for item in get_checklist_items(checklist["id"])
        }
        assert len(by_doc_type) == 5
        for kept in (
            "STUDENT_ID",
            "STUDENT_TAX_RETURN",
            "PARENT_TAX_RETURN",
            "BANK_STATEMENT",
        ):
            assert by_doc_type[kept] == "VERIFIED", (
                f"{kept} was VERIFIED and must be kept, got {by_doc_type[kept]}"
            )
        assert by_doc_type["DEPENDENCY_OVERRIDE_FORM"] == "PENDING", (
            "the new-template item must be appended in PENDING"
        )


class TestSpecialistSelection:
    def test_selector_ranks_language_then_caseload_then_created_at(self, api):
        """PRD §3.9: "creation runs the specialist selector: the candidate pool
        is the campaign's staff profiles holding the `CASE_SPECIALIST`
        capability and currently `ACTIVE`; ranking prefers a language match on
        the senior's `home_language`, then the lower `active_case_count`, then
        the earlier `created_at` as the final tie-break — never any
        identifier."

        Design: Corner/calculations/specialist_selector_ranking_language_caseload_created_at
        """
        campaign, school = setup_campaign_with_school()
        sp1 = create_specialist(campaign, languages=["es"], name="Spec Uno")
        sp2 = create_specialist(campaign, languages=["en"], name="Spec Dos")

        senior_ids = []
        for i, (ref, lang) in enumerate(
            [("K1", "es"), ("K2", "es"), ("K3", "fr"), ("K4", "fr"), ("K5", "fr")]
        ):
            senior = add_senior(
                school,
                student_ref=ref,
                full_name=f"K {['One', 'Two', 'Three', 'Four', 'Five'][i]}",
                dob=f"2009-01-0{i + 1}",
                home_language=lang,
            )
            grant_consent(school, senior["id"], ["STATUS_DETAIL"])
            senior_ids.append(senior["id"])

        assigned = []
        for senior_id in senior_ids:
            case = create_support_case(
                school, senior_id, "SPECIAL_CIRCUMSTANCE"
            )
            assigned.append(case["assigned_specialist_id"])

        # es seniors: language match outranks caseload growth on sp1.
        assert assigned[0] == sp1["id"]
        assert assigned[1] == sp1["id"], (
            "language match must outrank sp1's higher caseload (1 vs 0)"
        )
        # fr seniors: language tie 0=0 falls to the lower caseload.
        assert assigned[2] == sp2["id"], "caseload 0 < 2 must win the tie"
        assert assigned[3] == sp2["id"], "caseload 1 < 2 must win"
        # Full tie (2 = 2): the earlier-created specialist wins.
        assert assigned[4] == sp1["id"], (
            "a full tie must resolve to the earlier created_at, never an id"
        )

    def test_empty_pool_leaves_case_unassigned_until_manual_assign(self, api):
        """PRD §3.9: "An empty pool leaves `assigned_specialist_id` as `null`
        and the case in `OPEN` until a `CampaignAdmin` assigns a
        `specialist_id` manually".
        PRD §3.9: "Accepting moves `OPEN` to `IN_REVIEW` and requires a
        non-null assignee (`ERR_CASE_UNASSIGNED`)".

        Design: Corner/calculations/specialist_selector_empty_pool_then_manual_assign
        """
        campaign, school = setup_campaign_with_school()
        senior = add_senior(school)
        grant_consent(school, senior["id"], ["STATUS_DETAIL"])

        case = create_support_case(school, senior["id"], "SPECIAL_CIRCUMSTANCE")
        assert case["status"] == "OPEN"
        assert case["assigned_specialist_id"] is None, (
            "with an empty selector pool the case is created unassigned"
        )

        # Accept on an unassigned case is rejected.
        resp = api.accept_support_case(
            case["id"], make_specialist_headers(NON_EXISTENT_UUID)
        )
        validate_error(resp, ApiErrorId.ERR_CASE_UNASSIGNED)

        specialist = create_specialist(campaign)
        resp = api.assign_support_case(case["id"], specialist["id"], ADMIN)
        case = validate_success(resp, 200)
        assert case["assigned_specialist_id"] == specialist["id"]

        resp = api.accept_support_case(case["id"], spec_headers(specialist))
        assert validate_success(resp, 200)["status"] == "IN_REVIEW"


class TestVerificationCaseGating:
    def test_verification_resolve_requires_complete_checklist(self, api):
        """PRD §3.9: "a `VERIFICATION_FOLLOWUP` case resolves only when the
        senior's checklist stands `COMPLETE` (`ERR_CHECKLIST_NOT_COMPLETE`),
        and its `resolution_outcome` is forced to `VERIFICATION_COMPLETED`".

        Design: Difficulty/cross_entity_state_dependency/verification_resolve_requires_checklist_complete
        """
        ctx = setup_verification_case()
        case = accept_case(ctx["case"], ctx["specialist"])
        assert case["status"] == "IN_REVIEW"

        resp = api.resolve_support_case(case["id"], spec_headers(ctx["specialist"]))
        validate_error(resp, ApiErrorId.ERR_CHECKLIST_NOT_COMPLETE)
        resp = api.get_support_case(case["id"], coord(ctx["school"]))
        assert validate_success(resp, 200)["status"] == "IN_REVIEW", (
            "the rejected resolve must leave the case in IN_REVIEW"
        )

    def test_verification_resolve_succeeds_once_checklist_complete(self, api):
        """PRD §3.9: "a `VERIFICATION_FOLLOWUP` case resolves only when the
        senior's checklist stands `COMPLETE` (`ERR_CHECKLIST_NOT_COMPLETE`),
        and its `resolution_outcome` is forced to `VERIFICATION_COMPLETED`".
        PRD §3.9: "reaches `COMPLETE` when every item stands in `VERIFIED` or
        `WAIVED`".

        Design: Difficulty/cross_entity_state_dependency/verification_resolve_requires_checklist_complete
        """
        ctx = setup_verification_case()
        case = accept_case(ctx["case"], ctx["specialist"])
        checklist = get_checklist_for_senior(ctx["senior"]["id"])
        verify_all_items(ctx["school"], checklist["id"])
        resp = api.get_document_checklist(checklist["id"], ADMIN)
        assert validate_success(resp, 200)["status"] == "COMPLETE"

        resp = api.resolve_support_case(case["id"], spec_headers(ctx["specialist"]))
        resolved = validate_success(resp, 200)
        assert resolved["status"] == "RESOLVED"
        assert resolved["resolution_outcome"] == "VERIFICATION_COMPLETED", (
            "the verification outcome is forced, not caller-supplied"
        )


class TestVerificationCascade:
    def _setup_two_seniors(self, api):
        """max_caseload=1; two seniors each matched (score 1.00) to a
        SUBMITTED aid record, STATUS_DETAIL consented, one specialist."""
        campaign, school = setup_campaign_with_school(
            campaign_overrides={"max_caseload": 1}
        )
        specialist = create_specialist(campaign)
        senior_a, aid_a, link_a, _c1 = create_matched_senior(
            campaign, school, student_ref="SA", full_name="Amy A",
            dob="2009-01-01", aid_status="SUBMITTED",
            aid_effective_date="2027-01-10", consent_scopes=["STATUS_DETAIL"],
        )
        senior_b, aid_b, link_b, _c2 = create_matched_senior(
            campaign, school, student_ref="SB", full_name="Ben B",
            dob="2009-02-02", aid_status="SUBMITTED",
            aid_effective_date="2027-01-11", consent_scopes=["STATUS_DETAIL"],
            external_ref="EXB",
        )
        assert link_a["status"] == "AUTO_CONFIRMED"
        assert link_b["status"] == "AUTO_CONFIRMED"
        return campaign, school, specialist, (senior_a, aid_a), (senior_b, aid_b)

    def _cases_for(self, api, senior_id):
        resp = api.list_support_cases(ADMIN, params={"senior_record_id": senior_id})
        cases, meta = validate_paginated(resp)
        return cases, meta["total_count"]

    def test_import_event_flips_senior_and_auto_creates_case(self, api):
        """PRD §3.4: "Whenever a senior's status becomes
        `VERIFICATION_SELECTED` — whether arriving from `NO_RECORD`, `STARTED`,
        or `SUBMITTED` — the verification cascade fires: unless that senior
        already has a non-terminal verification case, the system opens a
        support case of type `VERIFICATION_FOLLOWUP` and runs the specialist
        selector (§3.8)".

        Design: Difficulty/transitive_cascade/verification_snapshot_cascade_depth3
        """
        _campaign, _school, specialist, (senior_a, aid_a), _b = (
            self._setup_two_seniors(api)
        )
        api.append_status_event(
            aid_a["id"],
            create_status_event_payload(
                fafsa_status="VERIFICATION_SELECTED", effective_date="2027-02-01"
            ),
            IMPORTER,
        )

        senior_a = fresh_senior(senior_a["id"])
        assert senior_a["fafsa_status"] == "VERIFICATION_SELECTED"

        cases, total = self._cases_for(api, senior_a["id"])
        assert total == 1
        assert cases[0]["case_type"] == "VERIFICATION_FOLLOWUP"
        assert cases[0]["status"] == "OPEN", (
            "consent is in place, so the case is born actionable, not PAUSED"
        )
        assert cases[0]["assigned_specialist_id"] == specialist["id"]

        staff = get_staff(specialist["id"])
        assert staff["active_case_count"] == 1
        assert staff["status"] == "ACTIVE", (
            "1 is not strictly above max_caseload 1 — no overload flip yet"
        )

    def test_second_case_pushes_specialist_overloaded(self, api):
        """PRD §3.2: "When a case assignment pushes `active_case_count`
        strictly above the campaign's `max_caseload`, the profile flips from
        `ACTIVE` to `OVERLOADED` and is excluded from the specialist selector
        pool while overloaded".

        Design: Difficulty/transitive_cascade/verification_snapshot_cascade_depth3
        """
        _campaign, _school, specialist, (senior_a, aid_a), (senior_b, aid_b) = (
            self._setup_two_seniors(api)
        )
        api.append_status_event(
            aid_a["id"],
            create_status_event_payload(
                fafsa_status="VERIFICATION_SELECTED", effective_date="2027-02-01"
            ),
            IMPORTER,
        )
        api.append_status_event(
            aid_b["id"],
            create_status_event_payload(
                fafsa_status="VERIFICATION_SELECTED", effective_date="2027-02-02"
            ),
            IMPORTER,
        )

        _cases_b, total_b = self._cases_for(api, senior_b["id"])
        assert total_b == 1
        staff = get_staff(specialist["id"])
        assert staff["active_case_count"] == 2
        assert staff["status"] == "OVERLOADED", (
            f"2 > max_caseload 1 must flip the specialist to OVERLOADED, got "
            f"{staff['status']}"
        )
