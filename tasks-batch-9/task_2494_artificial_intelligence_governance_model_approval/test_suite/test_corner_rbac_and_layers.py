"""Role-based access control, the concurrency and pinning layers, and the
immediate-consistency guarantees of the write responses.

Every test builds its own world from scratch through the PRD's own endpoints: the
harness relaunches the API against an empty database before each test.
"""

from test_helpers import (
    BUSINESS_REVIEWER,
    BUSINESS_REVIEWER_AS_REQUESTER,
    DEFAULT_CLOCK,
    EVAL_THRESHOLDS,
    EVAL_WINDOWS,
    FIRST_PARTY_ASSET,
    MINIMAL_USE_CASE,
    OFFICER,
    OFFICER_AS_BUSINESS_REVIEWER,
    PRIVACY_REVIEWER,
    REASSESSMENT_INTERVAL_DAYS,
    REQUESTER,
    REQUIRED_METRIC_NAME,
    REQUIRED_SAMPLE_SIZE,
    SECURITY_REVIEWER,
    USER_BUSINESS_1,
    USER_OFFICER_1,
    USER_REQUESTER_1,
    ApiErrorId,
    Chain,
    ApiClient,
    approval_payload,
    approved_design,
    assert_debt_equals,
    assert_disclosure_notice,
    assert_iso_instant,
    assert_model_asset,
    assert_model_binding,
    assert_review_gate,
    assert_test_evaluation,
    assert_use_case,
    asset_revision_payload,
    classify,
    classify_payload,
    clear_all_gates,
    conditions,
    create_binding,
    current_version,
    disclosure_notice_payload,
    entry_types,
    expected_base_score,
    expected_control_credit,
    expected_final_score,
    expected_gate_debt,
    file_use_case,
    gates_by_type,
    issue_conditions_payload,
    limited_use_case_under_review,
    limited_use_case_with_binding,
    list_bindings,
    list_gates,
    list_ledger,
    list_notices,
    list_snapshots,
    minimal_use_case_under_review,
    model_binding_payload,
    oversight_design_payload,
    pin_clock,
    plus_days,
    read_asset,
    read_evaluation,
    read_summary,
    read_use_case,
    ready_asset,
    take_up_gate,
    # Aliased: a module-level name starting with "test_" would be collected as a test.
    test_evaluation_payload as evaluation_schedule_payload,
    use_case_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

# ─── Shared composite position ─────────────────────────────────────────────

# A MINIMAL-tier use case whose single BUSINESS gate is cleared by usr_biz_1, with
# a PINNED binding and an APPROVED oversight design already in place, so that
# every business rule downstream of the approval's role and identity checks is
# already satisfied. Composed from the primitives in the shared helpers.


def _minimal_ready_for_approval(api: ApiClient) -> Chain:
    chain = minimal_use_case_under_review(api)
    chain.binding = create_binding(api, chain.use_case_id, chain.asset_id)
    chain.design = approved_design(api, chain.use_case_id)
    chain.gates = clear_all_gates(api, chain.use_case_id)
    chain.use_case = read_use_case(api, chain.use_case_id)
    return chain


# An intake deployed in two jurisdictions, one high-scrutiny and one not, so the
# notice-window rule (keyed on notice_type plus jurisdiction) cannot interfere.
TWO_JURISDICTION_USE_CASE = use_case_payload(
    title="Applicant screening ranker",
    business_unit="HR",
    description="ranks external applicants for recruiter shortlisting",
    affects_individuals=True,
    decision_autonomy="HUMAN_IN_LOOP",
    data_sensitivity="CONFIDENTIAL",
    individual_impact="MATERIAL",
    jurisdictions=["EU", "US_CA"],
    deployed_headcount_reach=5000,
)


# ─── Role exclusivity and role sharing ─────────────────────────────────────


class TestRoleSurfaces:
    """Which role may call which endpoint, per PRD §2.1 and the §4 role lists."""

    def test_officer_drives_the_registry_classification_and_binding_block(
        self, api: ApiClient
    ) -> None:
        """PRD §2.1: "A `GovernanceOfficer` is the governance-office operator who
        runs classification, the model registry, vendor decisions, oversight
        decisions, model bindings, gate reopenings, approvals, revocations,
        reassessments, incident resolution, the shadow-deployment programme, the
        inventory reconciliation read and the periodic sweep."

        PRD §4: "Every endpoint that mints a new record responds with HTTP 201 on
        success; every other successful call — reads, revisions, state
        transitions, the reconciliation read, the clock setter and the sweep —
        responds with HTTP 200."

        PRD §3.1: "A freshly registered asset lands in status `REGISTERED` with
        `version` 1, `active_binding_count` 0, `enforced_shadow_count` 0 and
        `vendor_terms_grade` null."

        PRD §3.1: "Clearing an asset for use moves it from `REGISTERED` to
        `APPROVED_FOR_USE`, and this is the gate at which third-party supply is
        tested: if `is_third_party` is true, the asset must already carry a
        `VendorModelAssessment` with status `ACCEPTED` whose `terms_grade` is `A`,
        `B` or `C`, and without one the attempt is rejected with
        `ERR_VENDOR_ASSESSMENT_NOT_ACCEPTED`."

        PRD §3.2: "**On the ordinary branch**, where the prohibited combination
        does not hold, the use case moves `DRAFT → UNDER_REVIEW`."

        PRD §3.4: "The new binding lands in status `PINNED` with
        `pinned_model_version` set to the asset's `version` at that instant and
        `pinned_at` set to the current logical instant."

        Design: Corner/rbac/governance_officer_exclusive_registry_and_classification_operations
        """
        pin_clock(api)
        # Only a Requester may file an intake, so the officer needs one to classify.
        use_case = file_use_case(api, MINIMAL_USE_CASE, headers=REQUESTER)

        asset = validate_success(
            api.create_model_asset(FIRST_PARTY_ASSET, headers=OFFICER),
            expected_status=201,
        )
        assert_model_asset(asset, status="REGISTERED", version=1)

        cleared_asset = validate_success(
            api.approve_asset_for_use(asset["id"], headers=OFFICER),
            expected_status=200,
        )
        assert_model_asset(cleared_asset, status="APPROVED_FOR_USE")

        classified = validate_success(
            api.classify_use_case(
                use_case["id"],
                classify_payload(use_case["version"]),
                headers=OFFICER,
            ),
            expected_status=200,
        )
        assert_use_case(classified, status="UNDER_REVIEW")

        binding = validate_success(
            api.create_model_binding(
                use_case["id"],
                model_binding_payload(asset["id"], classified["version"]),
                headers=OFFICER,
            ),
            expected_status=201,
        )
        assert_model_binding(
            binding,
            status="PINNED",
            pinned_model_version=cleared_asset["version"],
        )

        entries, _ = validate_paginated(
            api.list_ledger_entries(use_case["id"], headers=OFFICER)
        )
        assert entries == [], "nothing ledgerable has happened yet"

        validate_success(
            api.get_inventory_summary(headers=OFFICER), expected_status=200
        )

    def test_business_reviewer_drives_its_own_gate_through_the_full_loop(
        self, api: ApiClient
    ) -> None:
        """PRD §2.1: "A `BusinessReviewer` owns the `BUSINESS` review gate — the
        only gate every non-prohibited risk tier demands."

        PRD §2.1: "**Gate ownership**: each gate type belongs to exactly one
        reviewer role — `LegalReviewer` owns `LEGAL`, `PrivacyReviewer` owns
        `PRIVACY`, `SecurityReviewer` owns `SECURITY`, `BusinessReviewer` owns
        `BUSINESS`."

        PRD §3.3: "Taking up a gate moves it `PENDING → IN_REVIEW` or
        `CONDITIONS_ISSUED → IN_REVIEW`, sets `assigned_reviewer_user_id` to the
        acting `X-User-ID`, and is permitted only while the parent use case is in
        `UNDER_REVIEW` or `CHANGES_REQUESTED`."

        PRD §3.3: "Issuing conditions moves a gate `IN_REVIEW →
        CONDITIONS_ISSUED`. The reviewer supplies a `conditions` array of between
        1 and 20 remediation strings, and optionally a `decision_note`.
        `open_condition_count` becomes the number of entries supplied,
        `control_debt_index` is recomputed for the gate, the use case's
        `open_conditions_count` is recomputed, and the use case bubbles
        `UNDER_REVIEW → CHANGES_REQUESTED` — any single gate issuing conditions
        pushes the whole intake back to its requester."

        PRD §3.3: "Coming out of `CONDITIONS_ISSUED` it additionally wipes the
        slate: `conditions` becomes empty, `open_condition_count` drops to 0 and
        `control_debt_index` drops to 0.00. The use case's `open_conditions_count`
        is then recomputed, and if it reaches 0 the use case bubbles
        `CHANGES_REQUESTED → UNDER_REVIEW`; while any other gate still holds open
        conditions the use case stays in `CHANGES_REQUESTED`."

        PRD §3.3: "A gate's `control_debt_index` is its gate-type weight,
        multiplied by its `open_condition_count` divided by 3, multiplied by the
        tier multiplier of its own `pinned_risk_tier`, with the product rounded
        half up to two decimal places. The gate-type weights are 1.35 for
        `LEGAL`, 1.25 for `PRIVACY`, 1.15 for `SECURITY` and 0.75 for `BUSINESS`.
        The tier multipliers are 0.5 for `MINIMAL`, 1.0 for `LIMITED`, 1.5 for
        `HIGH` and 2.0 for `PROHIBITED`."

        PRD §3.3: "Once those pass, the clearance captures `debt_before_clear`
        from the gate's current `control_debt_index` (this is what makes the
        compensating reopen exact), zeroes `control_debt_index` to 0.00 and
        `open_condition_count` to 0, records `cleared_by_user_id` and
        `cleared_at`, and appends a `GovernanceLedgerEntry` of type
        `GATE_CLEARED` with `reach_delta` 0 and a `debt_delta` of minus the
        captured `debt_before_clear`. The use case's `cleared_gate_count` is
        recomputed. When, after this clearance, every non-`VOIDED` gate on the use
        case is `CLEARED` and `cleared_gate_count` equals the number of entries in
        `required_gate_types`, the use case bubbles `UNDER_REVIEW →
        READY_FOR_APPROVAL`."

        PRD §2.4: "Most records additionally carry `updated_at`, refreshed to the
        logical clock's current reading on every mutation, and `version`, an
        integer that starts at 1 on creation and increments by exactly 1 on every
        mutation of that row — including mutations a cascade performs on the row
        rather than mutations a client requested directly."

        Design: Corner/rbac/business_reviewer_exclusive_business_gate_operations
        """
        chain = minimal_use_case_under_review(api)
        gate_id = chain.gate_id("BUSINESS")

        taken_up = validate_success(
            api.start_gate_review(gate_id, headers=BUSINESS_REVIEWER),
            expected_status=200,
        )
        assert_review_gate(
            taken_up,
            status="IN_REVIEW",
            version=2,
            assigned_reviewer_user_id=USER_BUSINESS_1,
        )

        conditioned = validate_success(
            api.issue_gate_conditions(
                gate_id,
                issue_conditions_payload(
                    conditions(2), decision_note="value case not yet evidenced"
                ),
                headers=BUSINESS_REVIEWER,
            ),
            expected_status=200,
        )
        assert_review_gate(
            conditioned, status="CONDITIONS_ISSUED", version=3, open_condition_count=2
        )
        assert_debt_equals(
            conditioned["control_debt_index"],
            expected_gate_debt("BUSINESS", 2, "MINIMAL"),
        )
        assert_use_case(
            read_use_case(api, chain.use_case_id),
            status="CHANGES_REQUESTED",
            open_conditions_count=2,
        )

        taken_up_again = validate_success(
            api.start_gate_review(gate_id, headers=BUSINESS_REVIEWER),
            expected_status=200,
        )
        assert_review_gate(
            taken_up_again, status="IN_REVIEW", version=4, open_condition_count=0
        )
        assert_debt_equals(taken_up_again["control_debt_index"], 0.00)
        assert_use_case(
            read_use_case(api, chain.use_case_id),
            status="UNDER_REVIEW",
            open_conditions_count=0,
        )

        cleared = validate_success(
            api.clear_gate(
                gate_id,
                {"decision_note": "conditions answered out of band"},
                headers=BUSINESS_REVIEWER,
            ),
            expected_status=200,
        )
        assert_review_gate(
            cleared,
            status="CLEARED",
            version=5,
            open_condition_count=0,
            cleared_by_user_id=USER_BUSINESS_1,
            assigned_reviewer_user_id=USER_BUSINESS_1,
        )
        assert_debt_equals(cleared["control_debt_index"], 0.00)
        assert_debt_equals(cleared["debt_before_clear"], 0.00)
        assert_use_case(
            read_use_case(api, chain.use_case_id),
            status="READY_FOR_APPROVAL",
            cleared_gate_count=1,
        )

    def test_requester_and_officer_are_interchangeable_on_notices(
        self, api: ApiClient
    ) -> None:
        """PRD §2.1: "A `Requester` is the business-unit owner who files an AI use
        case intake, keeps its intake data current, files the human-oversight
        design and publishes statutory notices."

        PRD §3.6: "Either the `Requester` or a `GovernanceOfficer` publishes one,
        declaring the `notice_type` it discharges — one of
        `USER_FACING_AI_DISCLOSURE`, `AUTOMATED_DECISION_NOTICE`,
        `TRAINING_DATA_NOTICE` or `EMPLOYMENT_SCREENING_NOTICE` — the
        `jurisdiction` whose law requires it, drawn from `EU`, `UK`, `US_CA`,
        `US_CO` and `US_FED`, the inclusive `effective_from` instant at which it
        comes into force, the inclusive `effective_to` instant at which it ceases
        (which must be strictly after `effective_from`), and the `locale_count`
        giving the number of locales it was published in, which must be at least
        1."

        PRD §3.6: "A published notice lands in status `PUBLISHED`; its only other
        status is the terminal `WITHDRAWN`."

        PRD §3.6: "Withdrawal moves a notice `PUBLISHED → WITHDRAWN` and stamps
        `withdrawn_at` with the current logical instant, releasing the
        jurisdiction slot for a fresh publication. Either a `GovernanceOfficer` or
        the use case's own `Requester` may withdraw a notice; when the actor is a
        `Requester`, their `X-User-ID` must match the use case's
        `requester_user_id`."

        Design: Corner/rbac/requester_and_officer_share_the_disclosure_notice_surface
        """
        pin_clock(api)
        use_case = file_use_case(api, TWO_JURISDICTION_USE_CASE, headers=REQUESTER)
        classify(api, use_case["id"])

        eu_notice = validate_success(
            api.create_disclosure_notice(
                use_case["id"],
                disclosure_notice_payload(
                    "EMPLOYMENT_SCREENING_NOTICE",
                    "EU",
                    "2026-07-01T00:00:00Z",
                    "2027-07-01T00:00:00Z",
                    locale_count=3,
                ),
                headers=REQUESTER,
            ),
            expected_status=201,
        )
        assert_disclosure_notice(
            eu_notice, status="PUBLISHED", version=1, jurisdiction="EU"
        )

        ca_notice = validate_success(
            api.create_disclosure_notice(
                use_case["id"],
                disclosure_notice_payload(
                    "EMPLOYMENT_SCREENING_NOTICE",
                    "US_CA",
                    "2026-07-01T00:00:00Z",
                    "2027-07-01T00:00:00Z",
                ),
                headers=OFFICER,
            ),
            expected_status=201,
        )
        assert_disclosure_notice(
            ca_notice, status="PUBLISHED", version=1, jurisdiction="US_CA"
        )

        # An officer may withdraw a notice the requester published.
        withdrawn = validate_success(
            api.withdraw_disclosure_notice(eu_notice["id"], headers=OFFICER),
            expected_status=200,
        )
        assert_disclosure_notice(withdrawn, status="WITHDRAWN", version=2)
        assert_iso_instant(withdrawn["withdrawn_at"], DEFAULT_CLOCK)

        published = list_notices(api, use_case["id"], status="PUBLISHED")
        assert [notice["id"] for notice in published] == [ca_notice["id"]]

    def test_security_reviewer_and_officer_write_the_same_evaluation_rows(
        self, api: ApiClient
    ) -> None:
        """PRD §2.1: "A `SecurityReviewer` owns the `SECURITY` review gate, runs
        the testing programme and reports unapproved deployments found in the
        estate."

        PRD §3.4: "A `SecurityReviewer` or a `GovernanceOfficer` schedules a
        **Test Evaluation** by naming the `use_case_id` whose tier fixes the
        thresholds, the `model_binding_id` under test, the `eval_type` — one of
        `BIAS`, `ROBUSTNESS`, `HALLUCINATION` or `SECURITY_REDTEAM` — and the pair
        `window_start_at` and `window_end_at` bounding the exclusive test window
        the run reserves on the bound asset."

        PRD §4: "| POST | `/test-evaluations/{id}/complete` | Record the run's
        results. The frozen threshold profile decides whether the evaluation lands
        in `PASSED` or `FAILED`. | `SecurityReviewer`, `GovernanceOfficer` |"

        PRD §3.4: "`required_metric_name` is the field the profile will score:
        `worst_group_parity_ratio` for a `BIAS` run, `adversarial_pass_rate` for a
        `ROBUSTNESS` run, `grounded_accuracy` for a `HALLUCINATION` run, and
        `adversarial_pass_rate` again for a `SECURITY_REDTEAM` run."

        PRD §3.4: "The body must contain whichever of the three
        `required_metric_name` designates; a body that omits it is malformed and
        is rejected with `ERR_INVALID_REQUEST`."

        PRD §3.4: "`required_metric_threshold` is drawn from the tier: at `HIGH`
        the thresholds are 0.80 for `BIAS`, 0.90 for `ROBUSTNESS`, 0.95 for
        `HALLUCINATION` and 0.95 for `SECURITY_REDTEAM`; at `LIMITED` they are
        0.70, 0.80, 0.85 and 0.85 respectively; at `MINIMAL` they are 0.60, 0.70,
        0.75 and 0.75; and at `PROHIBITED` every threshold is 1.00."

        PRD §3.4: "`required_sample_size` is likewise drawn from the tier: 100
        scored examples at `MINIMAL`, 300 at `LIMITED`, and 1000 at both `HIGH`
        and `PROHIBITED`."

        PRD §3.4: "The run lands in `PASSED` when `observed_metric_value` is at
        least `required_metric_threshold` **and** `sample_size` is at least
        `required_sample_size`; a value exactly equal to the threshold passes,
        because both comparisons are inclusive."

        PRD §3.4: "A `PASSED` run of any type sets `observed_metric_value` and
        `completed_at`, and if its `eval_type` is `BIAS` it additionally clears the
        use case's `safety_flag` to false."

        Design: Corner/rbac/security_reviewer_and_officer_share_the_evaluation_surface
        """
        chain = limited_use_case_with_binding(api)
        assert chain.use_case["risk_tier"] == "LIMITED"

        bias_start, bias_end = EVAL_WINDOWS["BIAS"]
        bias = validate_success(
            api.create_test_evaluation(
                evaluation_schedule_payload(
                    chain.binding_id,
                    "BIAS",
                    bias_start,
                    bias_end,
                    use_case_id=chain.use_case_id,
                ),
                headers=SECURITY_REVIEWER,
            ),
            expected_status=201,
        )
        assert_test_evaluation(bias, status="PLANNED", eval_type="BIAS")

        bias_done = validate_success(
            api.complete_test_evaluation(
                bias["id"],
                {
                    REQUIRED_METRIC_NAME["BIAS"]: EVAL_THRESHOLDS["LIMITED"]["BIAS"],
                    "sample_size": REQUIRED_SAMPLE_SIZE["LIMITED"],
                },
                headers=OFFICER,
            ),
            expected_status=200,
        )
        assert_test_evaluation(bias_done, status="PASSED")

        # The reverse pairing: the officer plans and the security reviewer completes.
        rob_start, rob_end = EVAL_WINDOWS["ROBUSTNESS"]
        robustness = validate_success(
            api.create_test_evaluation(
                evaluation_schedule_payload(
                    chain.binding_id,
                    "ROBUSTNESS",
                    rob_start,
                    rob_end,
                    use_case_id=chain.use_case_id,
                ),
                headers=OFFICER,
            ),
            expected_status=201,
        )
        assert_test_evaluation(robustness, status="PLANNED", eval_type="ROBUSTNESS")

        robustness_done = validate_success(
            api.complete_test_evaluation(
                robustness["id"],
                {
                    REQUIRED_METRIC_NAME["ROBUSTNESS"]: 0.8200,
                    "sample_size": REQUIRED_SAMPLE_SIZE["LIMITED"] + 100,
                },
                headers=SECURITY_REVIEWER,
            ),
            expected_status=200,
        )
        assert_test_evaluation(robustness_done, status="PASSED")

        assert_use_case(read_use_case(api, chain.use_case_id), safety_flag=False)


# ─── Role denials ──────────────────────────────────────────────────────────


class TestRoleDenials:
    """The three 403s of PRD §2.1, each on the operation the PRD assigns it."""

    def test_requester_cannot_run_classification(self, api: ApiClient) -> None:
        """PRD §2.1: "If the headers are well-formed but the named role does not
        appear in the authorized-role list of the endpoint being called (see the
        table in §4), the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

        PRD §4: "| POST | `/use-cases/{id}/classify` | Run risk classification,
        which forks: an ordinary intake moves to `UNDER_REVIEW` with freshly
        created gates, while a prohibited combination is rejected outright. |
        `GovernanceOfficer` |"

        Design: Corner/rbac/requester_cannot_classify_forbidden
        """
        pin_clock(api)
        use_case = file_use_case(api, MINIMAL_USE_CASE, headers=REQUESTER)

        # The version pinned here is the correct one, so only the role can be at fault.
        response = api.classify_use_case(
            use_case["id"],
            classify_payload(use_case["version"]),
            headers=REQUESTER,
        )
        validate_error(response, ApiErrorId.UNAUTHORIZED.value)

        assert_use_case(
            read_use_case(api, use_case["id"]),
            status="DRAFT",
            version=1,
            risk_score=None,
            risk_tier=None,
        )
        assert list_snapshots(api, use_case["id"]) == []
        assert list_gates(api, use_case["id"]) == []

    def test_business_reviewer_cannot_sign_the_approval(self, api: ApiClient) -> None:
        """PRD §2.1: "No `GovernanceOfficer` may clear a domain gate, and no
        reviewer role may sign an approval."

        PRD §2.1: "If the headers are well-formed but the named role does not
        appear in the authorized-role list of the endpoint being called (see the
        table in §4), the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

        PRD §2.9: "The order below is normative: checks are evaluated top to
        bottom and the **first** one that fails determines the response. A later
        check never masks an earlier one."

        PRD §4: "| POST | `/use-cases/{id}/approve` | Sign the deployment
        approval. Recomputes the risk tier from the evidence the provisional tier
        demanded, then schedules the first reassessment. | `GovernanceOfficer` |"

        Design: Corner/rbac/business_reviewer_cannot_approve_forbidden
        """
        chain = _minimal_ready_for_approval(api)
        assert_use_case(chain.use_case, status="READY_FOR_APPROVAL")

        response = api.approve_use_case(
            chain.use_case_id,
            approval_payload(current_version(api, chain.use_case_id)),
            headers=BUSINESS_REVIEWER,
        )
        # The role check resolves before the identity check can look at the
        # reviewer who cleared the gate.
        validate_error(response, ApiErrorId.UNAUTHORIZED.value)

        assert_use_case(
            read_use_case(api, chain.use_case_id),
            status="READY_FOR_APPROVAL",
            approved_at=None,
            approved_by_user_id=None,
        )
        summary = read_summary(api)
        assert summary["inventory_count"] == 0
        assert summary["ledger_reach_balance"] == 0

    def test_officer_cannot_clear_a_domain_gate(self, api: ApiClient) -> None:
        """PRD §2.1: "No `GovernanceOfficer` may clear a domain gate, and no
        reviewer role may sign an approval."

        PRD §2.1: "A reviewer acting on a gate whose `gate_type` belongs to a
        different role is rejected with `ERR_GATE_ROLE_MISMATCH` (HTTP 403); this
        applies when taking up a gate for review, when issuing conditions on it,
        and when clearing it."

        PRD §2.1: "If the headers are well-formed but the named role does not
        appear in the authorized-role list of the endpoint being called (see the
        table in §4), the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

        PRD §4: "| POST | `/review-gates/{id}/clear` | Clear a gate. The per-gate
        preconditions differ by gate type: `LEGAL` needs accepted vendor terms,
        `SECURITY` needs a passed red-team run, `PRIVACY` needs published notices.
        | `LegalReviewer`, `PrivacyReviewer`, `SecurityReviewer`,
        `BusinessReviewer` |"

        Design: Corner/rbac/governance_officer_cannot_clear_a_domain_gate_forbidden
        """
        chain = minimal_use_case_under_review(api)
        gate_id = chain.gate_id("BUSINESS")
        take_up_gate(api, gate_id, "BUSINESS")

        response = api.clear_gate(
            gate_id,
            {"decision_note": "officer trying to self-serve the clearance"},
            headers=OFFICER,
        )
        # The officer is not on this endpoint's role list at all, so the denial is
        # the role denial and not the gate-ownership one.
        validate_error(response, ApiErrorId.UNAUTHORIZED.value)

        assert_review_gate(
            gates_by_type(api, chain.use_case_id)["BUSINESS"],
            status="IN_REVIEW",
            version=2,
            cleared_by_user_id=None,
        )
        assert_use_case(
            read_use_case(api, chain.use_case_id),
            status="UNDER_REVIEW",
            cleared_gate_count=0,
        )

    def test_privacy_reviewer_cannot_take_up_the_business_gate(
        self, api: ApiClient
    ) -> None:
        """PRD §2.1: "**Gate ownership**: each gate type belongs to exactly one
        reviewer role — `LegalReviewer` owns `LEGAL`, `PrivacyReviewer` owns
        `PRIVACY`, `SecurityReviewer` owns `SECURITY`, `BusinessReviewer` owns
        `BUSINESS`. A reviewer acting on a gate whose `gate_type` belongs to a
        different role is rejected with `ERR_GATE_ROLE_MISMATCH` (HTTP 403); this
        applies when taking up a gate for review, when issuing conditions on it,
        and when clearing it."

        PRD §4: "| POST | `/review-gates/{id}/start-review` | Take up a gate for
        review, or return it to review after the requester answered conditions.
        Only the reviewer role that owns the gate type may call it. |
        `LegalReviewer`, `PrivacyReviewer`, `SecurityReviewer`, `BusinessReviewer`
        |"

        Design: Corner/rbac/privacy_reviewer_cannot_open_business_gate_mismatch
        """
        chain = limited_use_case_under_review(api)

        response = api.start_gate_review(
            chain.gate_id("BUSINESS"), headers=PRIVACY_REVIEWER
        )
        # PrivacyReviewer *is* a declared role on this endpoint, so the denial is
        # the gate-ownership one rather than the role one.
        validate_error(response, ApiErrorId.GATE_ROLE_MISMATCH.value)

        gates = gates_by_type(api, chain.use_case_id)
        assert_review_gate(
            gates["BUSINESS"],
            status="PENDING",
            version=1,
            assigned_reviewer_user_id=None,
        )
        assert_review_gate(
            gates["PRIVACY"],
            status="PENDING",
            version=1,
            assigned_reviewer_user_id=None,
        )


# ─── Segregation of duties ─────────────────────────────────────────────────


class TestSegregationOfDuties:
    """Identity, not role, decides these two — PRD §2.1 compares recorded
    operator strings against the acting `X-User-ID`."""

    def test_requester_wearing_the_reviewer_role_cannot_clear_its_own_gate(
        self, api: ApiClient
    ) -> None:
        """PRD §2.1: "**Segregation of duties**: the reviewer clearing a gate must
        not be the use case's requester; the officer signing an approval must be
        neither the requester nor any reviewer who cleared a gate on that use
        case; and the officer completing a periodic reassessment must not be the
        requester. Any of these violations is rejected with
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 403), which guards gate clearance,
        approval and reassessment completion."

        PRD §2.1: "When `X-User-Role` is `Requester`, `LegalReviewer`,
        `PrivacyReviewer`, `SecurityReviewer`, `BusinessReviewer` or
        `GovernanceOfficer`, `X-User-ID` is an opaque operator identifier that is
        not tied to any persisted entity and is never compared against any
        record's `id`."

        PRD §3.2: "A newly filed intake lands in status `DRAFT` with `version` 1
        and `requester_user_id` set to the filer's `X-User-ID`."

        PRD §3.3: "Taking up a gate moves it `PENDING → IN_REVIEW` or
        `CONDITIONS_ISSUED → IN_REVIEW`, sets `assigned_reviewer_user_id` to the
        acting `X-User-ID`, and is permitted only while the parent use case is in
        `UNDER_REVIEW` or `CHANGES_REQUESTED`."

        Design: Corner/rbac/requester_cannot_clear_own_gate_sod
        """
        chain = minimal_use_case_under_review(api)
        assert chain.use_case["requester_user_id"] == USER_REQUESTER_1
        gate_id = chain.gate_id("BUSINESS")

        # Taking up a gate is not guarded by segregation of duties.
        taken_up = validate_success(
            api.start_gate_review(gate_id, headers=BUSINESS_REVIEWER_AS_REQUESTER),
            expected_status=200,
        )
        assert_review_gate(
            taken_up,
            status="IN_REVIEW",
            version=2,
            assigned_reviewer_user_id=USER_REQUESTER_1,
        )

        response = api.clear_gate(
            gate_id,
            {"decision_note": "clearing my own intake"},
            headers=BUSINESS_REVIEWER_AS_REQUESTER,
        )
        validate_error(response, ApiErrorId.SEGREGATION_OF_DUTIES.value)

        assert_review_gate(
            gates_by_type(api, chain.use_case_id)["BUSINESS"],
            status="IN_REVIEW",
            version=2,
            cleared_by_user_id=None,
        )

        # The identical call under a different operator id succeeds, which is what
        # isolates the identity from the role.
        cleared = validate_success(
            api.clear_gate(
                gate_id,
                {"decision_note": "value case accepted"},
                headers=BUSINESS_REVIEWER,
            ),
            expected_status=200,
        )
        assert_review_gate(
            cleared, status="CLEARED", cleared_by_user_id=USER_BUSINESS_1
        )

    def test_officer_who_cleared_a_gate_cannot_sign_the_approval(
        self, api: ApiClient
    ) -> None:
        """PRD §2.1: "**Segregation of duties**: the reviewer clearing a gate must
        not be the use case's requester; the officer signing an approval must be
        neither the requester nor any reviewer who cleared a gate on that use
        case; and the officer completing a periodic reassessment must not be the
        requester. Any of these violations is rejected with
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 403), which guards gate clearance,
        approval and reassessment completion."

        PRD §3.7: "And segregation of duties must hold: the signing `X-User-ID`
        must differ from the use case's `requester_user_id` and must differ from
        the `cleared_by_user_id` of every gate on the use case whose status is
        `CLEARED`, or the attempt fails with `ERR_SEGREGATION_OF_DUTIES`."

        PRD §3.7: "On success the use case moves `READY_FOR_APPROVAL →
        APPROVED`."

        Design: Corner/rbac/clearing_reviewer_cannot_sign_the_approval_sod
        """
        chain = _minimal_ready_for_approval(api)
        assert_review_gate(
            chain.gates["BUSINESS"],
            status="CLEARED",
            cleared_by_user_id=USER_BUSINESS_1,
        )
        assert_use_case(chain.use_case, status="READY_FOR_APPROVAL")

        # The role on the header is GovernanceOfficer; only the operator id collides.
        response = api.approve_use_case(
            chain.use_case_id,
            approval_payload(current_version(api, chain.use_case_id)),
            headers=OFFICER_AS_BUSINESS_REVIEWER,
        )
        validate_error(response, ApiErrorId.SEGREGATION_OF_DUTIES.value)

        assert_use_case(
            read_use_case(api, chain.use_case_id),
            status="READY_FOR_APPROVAL",
            approved_by_user_id=None,
        )
        assert list_snapshots(api, chain.use_case_id, variant="DEPLOYMENT_FINAL") == []

        # The identical call by an officer who neither filed nor cleared succeeds.
        approved = validate_success(
            api.approve_use_case(
                chain.use_case_id,
                approval_payload(current_version(api, chain.use_case_id)),
                headers=OFFICER,
            ),
            expected_status=200,
        )
        assert_use_case(
            approved, status="APPROVED", approved_by_user_id=USER_OFFICER_1
        )


# ─── Optimistic concurrency and version pinning ────────────────────────────


class TestVersionPinningLayers:
    """The two independent pinning layers of PRD §2.6: the client-supplied
    `expected_use_case_version`, and the binding's `pinned_model_version`."""

    def test_stale_expected_version_rejects_binding_creation(
        self, api: ApiClient
    ) -> None:
        """PRD §2.6: "Four write operations require the client to prove that its
        picture of the parent `UseCase` is current, by supplying
        `expected_use_case_version` in the request body carrying the `version`
        value of that use case the client last observed. Those four are running
        classification, creating a model binding, filing an oversight design, and
        signing the approval. On any of them, if `expected_use_case_version` does
        not equal the use case's current `version`, the request is rejected with
        `ERR_STALE_USE_CASE_VERSION` (HTTP 412). The field is mandatory on all
        four — it is never optional and never defaulted."

        PRD §2.6: "Creating a `ModelBinding` on a use case supersedes whatever
        binding that use case previously held, retiring it. A client that read the
        use case, then had another writer advance the use case's `version` behind
        its back, would be superseding a binding it never saw. Supplying an
        `expected_use_case_version` that no longer matches the use case's current
        `version` is therefore rejected with `ERR_STALE_USE_CASE_VERSION` (HTTP
        412)."

        PRD §2.10: "`active_binding_count` on a `ModelAsset` is the number of
        bindings on that asset whose status is `PINNED` or `STALE`."

        PRD §2.4: "Most records additionally carry `updated_at`, refreshed to the
        logical clock's current reading on every mutation, and `version`, an
        integer that starts at 1 on creation and increments by exactly 1 on every
        mutation of that row — including mutations a cascade performs on the row
        rather than mutations a client requested directly."

        Design: Corner/cross_cutting_layers/occ_stale_expected_version_rejects_binding_creation
        """
        pin_clock(api)
        asset, _ = ready_asset(api, FIRST_PARTY_ASSET)
        use_case = file_use_case(api, MINIMAL_USE_CASE, headers=REQUESTER)
        classify(api, use_case["id"])

        observed_version = current_version(api, use_case["id"])
        response = api.create_model_binding(
            use_case["id"],
            model_binding_payload(asset["id"], observed_version - 1),
            headers=OFFICER,
        )
        validate_error(response, ApiErrorId.STALE_USE_CASE_VERSION.value)

        assert list_bindings(api, use_case["id"]) == []
        assert_model_asset(read_asset(api, asset["id"]), active_binding_count=0)
        # A rejected write mutates nothing, so the version has not moved.
        assert current_version(api, use_case["id"]) == observed_version

        accepted = validate_success(
            api.create_model_binding(
                use_case["id"],
                model_binding_payload(asset["id"], observed_version),
                headers=OFFICER,
            ),
            expected_status=201,
        )
        assert_model_binding(accepted, status="PINNED")

    def test_stale_expected_version_rejects_oversight_design_filing(
        self, api: ApiClient
    ) -> None:
        """PRD §2.6: "Four write operations require the client to prove that its
        picture of the parent `UseCase` is current, by supplying
        `expected_use_case_version` in the request body carrying the `version`
        value of that use case the client last observed. Those four are running
        classification, creating a model binding, filing an oversight design, and
        signing the approval. On any of them, if `expected_use_case_version` does
        not equal the use case's current `version`, the request is rejected with
        `ERR_STALE_USE_CASE_VERSION` (HTTP 412). The field is mandatory on all
        four — it is never optional and never defaulted."

        PRD §2.6: "Filing an `OversightDesign` on a use case supersedes any prior
        design on that use case still in `DRAFT`, moving the prior row to
        `REJECTED`. The risk tier the new design must clear may have changed since
        the filer last read the use case. Supplying an
        `expected_use_case_version` that no longer matches the use case's current
        `version` is therefore rejected with `ERR_STALE_USE_CASE_VERSION` (HTTP
        412)."

        Design: Corner/cross_cutting_layers/occ_stale_expected_version_rejects_oversight_design_filing
        """
        pin_clock(api)
        asset, _ = ready_asset(api, FIRST_PARTY_ASSET)
        use_case = file_use_case(api, MINIMAL_USE_CASE, headers=REQUESTER)
        classify(api, use_case["id"])
        # Binding creation advances the use case's version behind the requester.
        create_binding(api, use_case["id"], asset["id"])

        observed_version = current_version(api, use_case["id"])
        response = api.create_oversight_design(
            use_case["id"],
            oversight_design_payload(observed_version - 1),
            headers=REQUESTER,
        )
        validate_error(response, ApiErrorId.STALE_USE_CASE_VERSION.value)

        designs, _ = validate_paginated(
            api.list_oversight_designs(use_case["id"], headers=OFFICER)
        )
        assert designs == []
        assert current_version(api, use_case["id"]) == observed_version

        accepted = validate_success(
            api.create_oversight_design(
                use_case["id"],
                oversight_design_payload(observed_version),
                headers=REQUESTER,
            ),
            expected_status=201,
        )
        assert accepted["status"] == "DRAFT"

    def test_asset_revision_stales_the_binding_and_voids_its_evaluation(
        self, api: ApiClient
    ) -> None:
        """PRD §2.6: "A `ModelBinding` records `pinned_model_version`, the
        `ModelAsset.version` value that was current at the moment the binding was
        created."

        PRD §3.1: "An `APPROVED_FOR_USE` asset may also be revised in place. A
        `GovernanceOfficer` may overwrite any combination of `model_version`,
        `hosting` and `modality`, and at least one of those three must be
        supplied. This is the ordinary way a vendor shipping a new model version
        reaches the governance record, and it carries the same consequence: the
        asset's `version` increments, every `PINNED` binding pinned to an older
        asset version drops to `STALE` with `superseded_reason`
        `ASSET_REAPPROVED`, and every `TestEvaluation` still in `PLANNED` on a
        binding that just went stale is moved to `VOIDED`, freeing the test window
        it had reserved."

        PRD §2.10: "`active_binding_count` on a `ModelAsset` is the number of
        bindings on that asset whose status is `PINNED` or `STALE`."

        Design: Corner/cross_cutting_layers/version_pinning_stales_the_binding_and_voids_its_evaluation
        """
        pin_clock(api)
        asset, _ = ready_asset(api, FIRST_PARTY_ASSET)
        use_case = file_use_case(api, MINIMAL_USE_CASE, headers=REQUESTER)
        classify(api, use_case["id"])
        binding = create_binding(api, use_case["id"], asset["id"])
        assert_model_binding(
            binding, status="PINNED", pinned_model_version=asset["version"]
        )

        start, end = EVAL_WINDOWS["BIAS"]
        evaluation = validate_success(
            api.create_test_evaluation(
                evaluation_schedule_payload(
                    binding["id"],
                    "BIAS",
                    start,
                    end,
                    use_case_id=use_case["id"],
                ),
                headers=SECURITY_REVIEWER,
            ),
            expected_status=201,
        )
        assert_test_evaluation(evaluation, status="PLANNED")

        revised = validate_success(
            api.update_model_asset(
                asset["id"], asset_revision_payload(), headers=OFFICER
            ),
            expected_status=200,
        )
        assert_model_asset(
            revised,
            status="APPROVED_FOR_USE",
            version=asset["version"] + 1,
            model_version=asset_revision_payload()["model_version"],
            active_binding_count=1,
        )

        stale = list_bindings(api, use_case["id"])[0]
        assert_model_binding(
            stale,
            status="STALE",
            superseded_reason="ASSET_REAPPROVED",
            pinned_model_version=asset["version"],
        )
        assert_test_evaluation(read_evaluation(api, evaluation["id"]), status="VOIDED")
        assert_use_case(read_use_case(api, use_case["id"]), status="UNDER_REVIEW")


# ─── Immediate consistency of the write response ───────────────────────────


class TestWriteResponsesCarryDerivedValues:
    """PRD §2.10 forbids deferred settlement: the mutating response itself already
    carries every value the operation derived."""

    def test_approve_response_carries_the_final_tier_and_schedule(
        self, api: ApiClient
    ) -> None:
        """PRD §2.2: "Unless otherwise noted, operations that create or modify a
        resource will return the created or updated resource object in the data
        field."

        PRD §2.10: "There is no deferred or eventually-consistent settlement
        anywhere in this system — a read issued immediately after a write observes
        every consequence of that write."

        PRD §3.2: "Individual impact contributes nothing for `NONE`, 10 points for
        `LOW`, 25 points for `MATERIAL` and 40 points for `CONSEQUENTIAL`; these
        land on the snapshot as `impact_points`."

        PRD §3.2: "Decision autonomy contributes nothing for `ADVISORY`, 8 points
        for `HUMAN_IN_LOOP`, 18 points for `HUMAN_ON_LOOP` and 30 points for
        `FULLY_AUTOMATED`, recorded as `autonomy_points`."

        PRD §3.2: "Data sensitivity contributes nothing for `PUBLIC`, 6 points for
        `INTERNAL`, 14 points for `CONFIDENTIAL` and 24 points for
        `SPECIAL_CATEGORY`, recorded as `sensitivity_points`."

        PRD §3.2: "Reach contributes by band, taking the first band that matches
        `deployed_headcount_reach`: 6 points at one hundred thousand individuals a
        year or more, otherwise 4 points at ten thousand or more, otherwise 2
        points at one thousand or more, otherwise nothing; this is `reach_points`."

        PRD §3.2: "Finally, `jurisdiction_points` is 3 points for each declared
        jurisdiction that is one of the three high-scrutiny jurisdictions `EU`,
        `UK` and `US_CO` — a use case declaring all three of those plus `US_FED`
        therefore earns 9 points, not 12."

        PRD §3.7: "2. **Compute the control credit.** `control_credit` is 3 points
        for each cleared gate plus 2 points for each passed evaluation, capped at
        15 — so a `HIGH`-tier use case with all four gates cleared and three
        evaluations passed earns 12 plus 6, which the cap trims to 15."

        PRD §3.7: "**Compute the vendor penalty.** Take the use case's `PINNED`
        binding and the asset it names. If that asset's `is_third_party` is false,
        `vendor_penalty` is 0."

        PRD §3.7: "**Recompute the score under the deployment-final variant.** The
        five declared point contributions are computed exactly as they were at
        classification, summed into `base_score`, then the `vendor_penalty` from
        step 3 is added and the `control_credit` from step 2 is subtracted; the
        result is rounded half up to a whole number and clamped into 0 through 100
        to give `final_risk_score`. `final_risk_tier` is banded from that score by
        the same bands as before — 85 or more is `PROHIBITED`, 70 or more is
        `HIGH`, 35 or more is `LIMITED`, below 35 is `MINIMAL` — and the same
        prohibited-combination override still takes precedence over the bands."

        PRD §3.7: "**Select the reassessment interval.**
        `reassessment_interval_days` is 730 days (two years) for a `MINIMAL` final
        tier, 365 days (one year) for a `LIMITED` final tier, and 180 days (half a
        year) for a `HIGH` final tier."

        PRD §3.7: "**Stamp the approval clock.** `approved_at` is the current
        logical instant, `approval_expires_at` is that instant plus
        `reassessment_interval_days` days, `reassessment_due_at` is set to the very
        same instant as `approval_expires_at`, `reassessment_cycle_index` becomes 1
        and `reassessment_status` becomes `SCHEDULED`."

        Design: Corner/consistency_model/approve_response_already_carries_the_final_tier_and_schedule
        """
        chain = _minimal_ready_for_approval(api)

        base_score = expected_base_score(MINIMAL_USE_CASE)
        credit = expected_control_credit(1, 0)
        final_score = expected_final_score(base_score, 0, credit)
        interval = REASSESSMENT_INTERVAL_DAYS["MINIMAL"]
        expires_at = plus_days(DEFAULT_CLOCK, interval)

        approved = validate_success(
            api.approve_use_case(
                chain.use_case_id,
                approval_payload(current_version(api, chain.use_case_id)),
                headers=OFFICER,
            ),
            expected_status=200,
        )

        # The mutating response itself already carries the whole finalization.
        assert_use_case(
            approved,
            status="APPROVED",
            control_credit=credit,
            vendor_penalty=0,
            final_risk_score=final_score,
            final_risk_tier="MINIMAL",
            reassessment_interval_days=interval,
            approved_by_user_id=USER_OFFICER_1,
            reassessment_cycle_index=1,
            reassessment_status="SCHEDULED",
        )
        assert_iso_instant(approved["approved_at"], DEFAULT_CLOCK)
        assert_iso_instant(approved["approval_expires_at"], expires_at)
        assert_iso_instant(approved["reassessment_due_at"], expires_at)

        # Secondary check: the follow-up read agrees, with no second computation.
        reread = read_use_case(api, chain.use_case_id)
        for field in (
            "status",
            "version",
            "control_credit",
            "vendor_penalty",
            "final_risk_score",
            "final_risk_tier",
            "reassessment_interval_days",
            "approved_at",
            "approved_by_user_id",
            "approval_expires_at",
            "reassessment_due_at",
            "reassessment_cycle_index",
            "reassessment_status",
        ):
            assert reread[field] == approved[field], (
                f"{field} differs between the approve response and the re-read"
            )

    def test_gate_clear_response_carries_the_released_debt(
        self, api: ApiClient
    ) -> None:
        """PRD §2.10: "There is no deferred or eventually-consistent settlement
        anywhere in this system — a read issued immediately after a write observes
        every consequence of that write."

        PRD §3.3: "A gate's `control_debt_index` is its gate-type weight,
        multiplied by its `open_condition_count` divided by 3, multiplied by the
        tier multiplier of its own `pinned_risk_tier`, with the product rounded
        half up to two decimal places. The gate-type weights are 1.35 for
        `LEGAL`, 1.25 for `PRIVACY`, 1.15 for `SECURITY` and 0.75 for `BUSINESS`.
        The tier multipliers are 0.5 for `MINIMAL`, 1.0 for `LIMITED`, 1.5 for
        `HIGH` and 2.0 for `PROHIBITED`."

        PRD §3.3: "Once those pass, the clearance captures `debt_before_clear`
        from the gate's current `control_debt_index` (this is what makes the
        compensating reopen exact), zeroes `control_debt_index` to 0.00 and
        `open_condition_count` to 0, records `cleared_by_user_id` and
        `cleared_at`, and appends a `GovernanceLedgerEntry` of type
        `GATE_CLEARED` with `reach_delta` 0 and a `debt_delta` of minus the
        captured `debt_before_clear`. The use case's `cleared_gate_count` is
        recomputed."

        PRD §2.11: "`control_debt_index_total` is the sum of `control_debt_index`
        over every gate whose status is `PENDING`, `IN_REVIEW`,
        `CONDITIONS_ISSUED` or `CLEARED`; `VOIDED` gates are excluded entirely.
        The sum of `debt_delta` over all ledger entries is `ledger_debt_balance`."

        PRD §2.10: "`open_conditions_count` on a `UseCase` is the sum of
        `open_condition_count` over that use case's gates whose status is
        `CONDITIONS_ISSUED`."

        PRD §2.10: "`cleared_gate_count` on a `UseCase` is the number of that use
        case's gates whose status is `CLEARED`."

        Design: Corner/consistency_model/gate_clear_debt_release_is_visible_in_the_same_request
        """
        chain = minimal_use_case_under_review(api)
        gate_id = chain.gate_id("BUSINESS")
        booked_debt = expected_gate_debt("BUSINESS", 2, "MINIMAL")

        take_up_gate(api, gate_id, "BUSINESS")
        conditioned = validate_success(
            api.issue_gate_conditions(
                gate_id,
                issue_conditions_payload(
                    conditions(2), decision_note="value case not yet evidenced"
                ),
                headers=BUSINESS_REVIEWER,
            ),
            expected_status=200,
        )
        assert_debt_equals(conditioned["control_debt_index"], booked_debt)

        before = read_summary(api)
        assert_debt_equals(before["control_debt_index_total"], booked_debt)
        assert_debt_equals(before["ledger_debt_balance"], 0.00)
        assert_use_case(
            read_use_case(api, chain.use_case_id), open_conditions_count=2
        )

        cleared = validate_success(
            api.clear_gate(
                gate_id,
                {"decision_note": "conditions answered out of band"},
                headers=BUSINESS_REVIEWER,
            ),
            expected_status=200,
        )
        # The clear response itself already carries the released debt.
        assert_review_gate(cleared, status="CLEARED", open_condition_count=0)
        assert_debt_equals(cleared["control_debt_index"], 0.00)
        assert_debt_equals(cleared["debt_before_clear"], booked_debt)
        assert_iso_instant(cleared["cleared_at"], DEFAULT_CLOCK)

        # Secondary checks: the aggregates read straight afterwards already agree.
        assert_use_case(
            read_use_case(api, chain.use_case_id),
            cleared_gate_count=1,
            open_conditions_count=0,
        )
        after = read_summary(api)
        assert_debt_equals(after["control_debt_index_total"], 0.00)
        assert_debt_equals(after["ledger_debt_balance"], -booked_debt)

        entries = list_ledger(api, chain.use_case_id)
        assert entry_types(entries) == ["GATE_CLEARED"]
        assert entries[0]["reach_delta"] == 0
        assert_debt_equals(entries[0]["debt_delta"], -booked_debt)
