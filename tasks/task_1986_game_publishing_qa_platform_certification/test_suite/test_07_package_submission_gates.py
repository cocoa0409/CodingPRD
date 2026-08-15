"""The submission gate gauntlet (PRD §3.5): state, embargo, blackout,
checklist completeness, open blockers, age-rating grant, localization
readiness — plus the checklist edit freeze after submission."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    advance_title,
    assert_budget_invariant,
    close_bug_fully,
    create_age_rating_filing,
    create_blackout_window,
    create_bug,
    create_build,
    create_candidate_build,
    create_approved_plan,
    create_localization_pack,
    create_submission_package,
    create_title,
    create_vendor,
    get_checklist,
    get_checklist_id_for_package,
    get_package,
    get_title,
    set_clock,
    set_embargo,
    setup_submittable_package,
    sign_off_pack,
    submit_package,
    transition_build,
    transition_filing,
    transition_pack_translation,
    verify_checklist_pass_sequence,
    verify_item,
    validate_error,
    validate_success,
)

CL_HEADERS = TEST_USERS["certification_lead_headers"]
MONDAY = "2026-08-03T10:00:00Z"


class TestOpenBlockerGate:
    def _setup_one_open_blocker(self):
        """Submit-ready package plus one OPEN BLOCKER on a second,
        non-candidate build of the same title."""
        set_clock("2026-08-03T09:00:00Z")
        ctx = setup_submittable_package(title_code="BND-BLK",
                                        cert_budget_total_cents=1_000_000)
        other_build = create_build(ctx["title"]["id"], "PS5", "2.0.0")
        transition_build(other_build["id"], "IN_TEST")
        bug = create_bug(ctx["title"]["id"], other_build["id"],
                         severity="BLOCKER", category="NETWORK")
        set_clock(MONDAY)
        return ctx, bug

    def test_submit_with_one_open_blocker_rejected(self, api):
        """PRD §3.5: "The title's `open_blocker_count` must be zero
        (`ERR_OPEN_BLOCKERS_EXIST`)."

        Design: Difficulty/boundary_precision_check/open_blocker_count_zero_vs_one
        """
        ctx, _bug = self._setup_one_open_blocker()
        assert get_title(ctx["title"]["id"])["open_blocker_count"] == 1
        resp = api.transition_submission_package(
            ctx["package"]["id"], {"to_status": "SUBMITTED"}, CL_HEADERS
        )
        validate_error(resp, ApiErrorId.ERR_OPEN_BLOCKERS_EXIST)

    def test_submit_succeeds_at_zero_blockers(self, api):
        """PRD §3.5: "The title's `open_blocker_count` must be zero
        (`ERR_OPEN_BLOCKERS_EXIST`)."

        Design: Difficulty/boundary_precision_check/open_blocker_count_zero_vs_one
        """
        ctx, bug = self._setup_one_open_blocker()
        close_bug_fully(bug["id"], severity="BLOCKER")
        assert get_title(ctx["title"]["id"])["open_blocker_count"] == 0
        package = submit_package(ctx["package"]["id"])
        assert package["status"] == "SUBMITTED"
        # Round 1, weekday, not expedited: the PS5 base fee.
        assert package["fee_cents"] == 120000


class TestValidationPriority:
    def test_state_error_beats_fiscal_error(self, api):
        """PRD §3.5: "The package must be `ASSEMBLING` (submitting from
        anywhere else is `ERR_PACKAGE_NOT_ASSEMBLING`)."
        PRD §2.8: "5. **State legality.** The target entity is in a legal
        from-state for the requested transition — otherwise
        `ERR_INVALID_STATE` (or `ERR_PACKAGE_NOT_ASSEMBLING` for package
        submission)."
        PRD §2.8: "10. **Money and capacity, always last.** The certification
        budget covers the fee being charged — `ERR_CERT_BUDGET_EXCEEDED`
        (HTTP 402)"

        Design: Difficulty/priority_pair_validation_conflict/submit_state_beats_fiscal
        """
        title = create_title(title_code="PRIO-SF", cert_budget_total_cents=150000)
        advance_title(title["id"], "IN_DEVELOPMENT")
        vendor = create_vendor()
        plan = create_approved_plan(title["id"], vendor["id"], "PS5")
        build = create_candidate_build(title["id"], "PS5")
        for territory in ("ESRB", "PEGI", "CERO", "USK"):
            filing = create_age_rating_filing(title["id"], territory)
            transition_filing(filing["id"], "FILED")
        package = create_submission_package(
            title["id"], "PS5", build["id"], plan["id"]
        )
        # Abandon the assembly; no escrow was ever held.
        validate_success(
            api.transition_submission_package(
                package["id"], {"to_status": "WITHDRAWN"}, CL_HEADERS
            )
        )
        resp = api.transition_submission_package(
            package["id"], {"to_status": "SUBMITTED"}, CL_HEADERS
        )
        validate_error(resp, ApiErrorId.ERR_PACKAGE_NOT_ASSEMBLING)

    def test_fiscal_failure_is_armed_but_not_surfaced(self, api):
        """PRD §2.8: "10. **Money and capacity, always last.** The
        certification budget covers the fee being charged —
        `ERR_CERT_BUDGET_EXCEEDED` (HTTP 402) — and the vendor's weekly
        capacity covers a new reservation — `ERR_VENDOR_CAPACITY_EXCEEDED`
        (HTTP 409)."
        PRD §2.7: "The three partitions are defined so that available equals
        `cert_budget_total_cents` minus escrow minus spent, and the conserved
        invariant is that available, escrow, and spent always sum exactly to
        `cert_budget_total_cents`."

        Design: Difficulty/priority_pair_validation_conflict/submit_state_beats_fiscal
        """
        title = create_title(title_code="PRIO-SF", cert_budget_total_cents=150000)
        advance_title(title["id"], "IN_DEVELOPMENT")
        vendor = create_vendor()
        plan = create_approved_plan(title["id"], vendor["id"], "PS5")
        build = create_candidate_build(title["id"], "PS5")
        for territory in ("ESRB", "PEGI", "CERO", "USK"):
            filing = create_age_rating_filing(title["id"], territory)
            transition_filing(filing["id"], "FILED")
        view = get_title(title["id"])
        # 40000 + 25000 + round_half_up(18000 x 0.9) + round_half_up(15000 x 0.9)
        assert view["cert_budget_spent_cents"] == 94700
        assert view["cert_budget_available_cents"] == 55300
        assert_budget_invariant(view)
        package = create_submission_package(
            title["id"], "PS5", build["id"], plan["id"]
        )
        validate_success(
            api.transition_submission_package(
                package["id"], {"to_status": "WITHDRAWN"}, CL_HEADERS
            )
        )
        resp = api.transition_submission_package(
            package["id"], {"to_status": "SUBMITTED"}, CL_HEADERS
        )
        validate_error(resp, ApiErrorId.ERR_PACKAGE_NOT_ASSEMBLING)
        # The failed submit moved nothing.
        assert get_package(package["id"])["status"] == "WITHDRAWN"
        assert get_title(title["id"])["cert_budget_escrow_cents"] == 0


class TestBlackoutExclusion:
    def _setup_package_with_blackout(self):
        ctx = setup_submittable_package(title_code="OVL-BLK",
                                        cert_budget_total_cents=1_000_000)
        create_blackout_window(
            "PS5", start_utc="2026-08-10T00:00:00Z",
            end_utc="2026-08-12T00:00:00Z", buffer_hours=24,
            reason="platform cert freeze",
        )
        return ctx

    def test_submit_at_buffered_boundary_blocked(self, api):
        """PRD §2.9: "A package submission at logical time *t* is blocked
        whenever *t* is no earlier than the blackout's start minus its buffer
        and no later than its end plus its buffer; a submission exactly at the
        buffered boundary instant is still blocked, and only one second past
        it is allowed. A blocked submission is rejected with
        `ERR_SUBMISSION_BLACKOUT_ACTIVE`."

        Design: Difficulty/resource_temporal_overlap/blackout_closed_interval_with_buffer
        """
        ctx = self._setup_package_with_blackout()
        # Exactly end_utc + buffer: the closed bound is inclusive.
        set_clock("2026-08-13T00:00:00Z")
        resp = api.transition_submission_package(
            ctx["package"]["id"], {"to_status": "SUBMITTED"}, CL_HEADERS
        )
        validate_error(resp, ApiErrorId.ERR_SUBMISSION_BLACKOUT_ACTIVE)

    def test_submit_one_second_past_boundary_allowed(self, api):
        """PRD §2.9: "a submission exactly at the buffered boundary instant
        is still blocked, and only one second past it is allowed."

        Design: Difficulty/resource_temporal_overlap/blackout_closed_interval_with_buffer
        """
        ctx = self._setup_package_with_blackout()
        set_clock("2026-08-13T00:00:01Z")
        package = submit_package(ctx["package"]["id"])
        assert package["status"] == "SUBMITTED"
        # Round 1, Thursday, not expedited: the PS5 base fee.
        assert package["fee_cents"] == 120000


class TestStructuralSubmitGates:
    def test_unverified_recommended_item_blocks_submit(self, api):
        """PRD §3.5: "Every checklist item must be in `PASSED`, `WAIVED`, or
        `NA` (`ERR_CHECKLIST_INCOMPLETE`)."

        Design: Corner/validations/submit_with_unverified_checklist_item_rejected
        """
        set_clock(MONDAY)
        ctx = setup_submittable_package(title_code="VAL-CHK",
                                        cert_budget_total_cents=1_000_000,
                                        verify_checklist=False)
        # Verify the three REQUIRED items; leave RECOMMENDED TRC-PS-04 open.
        for code in ("TRC-PS-01", "TRC-PS-02", "TRC-PS-03"):
            verify_item(ctx["checklist_id"], code, "PASSED")
        resp = api.transition_submission_package(
            ctx["package"]["id"], {"to_status": "SUBMITTED"}, CL_HEADERS
        )
        validate_error(resp, ApiErrorId.ERR_CHECKLIST_INCOMPLETE)
        assert get_title(ctx["title"]["id"])["cert_budget_escrow_cents"] == 0

    def test_filed_but_ungranted_age_rating_blocks_submit(self, api):
        """PRD §3.5: "An age-rating filing for the territory mapped from the
        package's platform must be `GRANTED` (`ERR_AGE_RATING_NOT_GRANTED`)."
        PRD §3.8: "The submission gate maps each platform to its rating
        territory: `PS5` and `XSX` file under `ESRB`, `SWITCH2` under `CERO`,
        and `PC` under `USK`."

        Design: Corner/validations/submit_without_granted_age_rating_rejected
        """
        set_clock(MONDAY)
        ctx = setup_submittable_package(title_code="VAL-AGE",
                                        cert_budget_total_cents=1_000_000,
                                        age_rating="filed")
        resp = api.transition_submission_package(
            ctx["package"]["id"], {"to_status": "SUBMITTED"}, CL_HEADERS
        )
        validate_error(resp, ApiErrorId.ERR_AGE_RATING_NOT_GRANTED)
        transition_filing(ctx["filing"]["id"], "GRANTED",
                          headers=TEST_USERS["platform_reviewer_headers"])
        package = submit_package(ctx["package"]["id"])
        assert package["status"] == "SUBMITTED"

    def test_unlocked_required_locale_blocks_submit(self, api):
        """PRD §3.5: "Every localization pack of the title flagged
        `is_required` must be `LOCKED` on the translation axis and `SIGNED` on
        the signoff axis (`ERR_LOCALIZATION_NOT_LOCKED`)."

        Design: Corner/validations/submit_with_unlocked_required_locale_rejected
        """
        set_clock(MONDAY)
        ctx = setup_submittable_package(title_code="VAL-LOC",
                                        cert_budget_total_cents=1_000_000)
        required = create_localization_pack(
            ctx["title"]["id"], "fr-FR", is_required=True,
            text_asset_total=100, audio_asset_total=0,
        )
        # A non-required pack stays DRAFT throughout and never blocks.
        create_localization_pack(
            ctx["title"]["id"], "de-DE", is_required=False,
            text_asset_total=100, audio_asset_total=0,
        )
        resp = api.transition_submission_package(
            ctx["package"]["id"], {"to_status": "SUBMITTED"}, CL_HEADERS
        )
        validate_error(resp, ApiErrorId.ERR_LOCALIZATION_NOT_LOCKED)
        transition_pack_translation(required["id"], "TRANSLATING",
                                    translated_text_assets=100)
        transition_pack_translation(required["id"], "LQA")
        transition_pack_translation(required["id"], "LOCKED")
        sign_off_pack(required["id"])
        package = submit_package(ctx["package"]["id"])
        assert package["status"] == "SUBMITTED"

    def test_embargo_blocks_submit_until_lifted(self, api):
        """PRD §3.1: "While a title is embargoed, two operations are
        forbidden: submitting a submission package and declaring a hotfix —
        both are rejected with `ERR_TITLE_UNDER_EMBARGO` (HTTP 403)."

        Design: Corner/validations/embargo_blocks_package_submit_until_lifted
        """
        set_clock(MONDAY)
        ctx = setup_submittable_package(title_code="VAL-EMB",
                                        cert_budget_total_cents=1_000_000)
        set_embargo(ctx["title"]["id"], True, "legal hold")
        resp = api.transition_submission_package(
            ctx["package"]["id"], {"to_status": "SUBMITTED"}, CL_HEADERS
        )
        validate_error(resp, ApiErrorId.ERR_TITLE_UNDER_EMBARGO)
        set_embargo(ctx["title"]["id"], False, "hold cleared")
        package = submit_package(ctx["package"]["id"])
        assert package["status"] == "SUBMITTED"


class TestSubmittedPackageImmutability:
    def test_double_submit_rejected_and_escrow_not_doubled(self, api):
        """PRD §3.5: "The package must be `ASSEMBLING` (submitting from
        anywhere else is `ERR_PACKAGE_NOT_ASSEMBLING`)."
        PRD §2.7: "`cert_budget_escrow_cents` holds fees provisionally
        committed — the sum of `fee_cents` over the title's submission
        packages currently in `SUBMITTED` or `IN_REVIEW`"

        Design: Corner/state_machines/package_double_submit_rejected
        """
        set_clock(MONDAY)
        ctx = setup_submittable_package(title_code="SM-DBL",
                                        cert_budget_total_cents=1_000_000)
        submit_package(ctx["package"]["id"])
        resp = api.transition_submission_package(
            ctx["package"]["id"], {"to_status": "SUBMITTED"}, CL_HEADERS
        )
        validate_error(resp, ApiErrorId.ERR_PACKAGE_NOT_ASSEMBLING)
        assert get_title(ctx["title"]["id"])["cert_budget_escrow_cents"] == 120000

    def test_checklist_frozen_after_submit(self, api):
        """PRD §3.6: "Item edits are only possible while the owning package is
        `ASSEMBLING` — attempts after submission are rejected with
        `ERR_CHECKLIST_NOT_EDITABLE`."
        PRD §3.6: "The item must currently be `UNVERIFIED` or `FAILED`;
        anything else is `ERR_INVALID_STATE`."
        PRD §2.8: state legality (level 5) is evaluated before the structural
        business gates (level 9), so re-verifying an already-PASSED item on a
        submitted package surfaces `ERR_INVALID_STATE`, while the edit freeze
        surfaces only when the item's from-state is legal.

        Design: Corner/state_machines/checklist_not_editable_after_submit
        """
        set_clock(MONDAY)
        ctx = setup_submittable_package(title_code="SM2-CHK",
                                        cert_budget_total_cents=1_000_000)
        submit_package(ctx["package"]["id"])
        before = get_checklist(ctx["checklist_id"])
        # Post-submit every item is PASSED/WAIVED/NA, so the item from-state
        # check (§2.8 level 5) pre-empts the editability gate (level 9).
        resp = api.verify_checklist_item(
            ctx["checklist_id"],
            {"requirement_code": "TRC-PS-01", "result": "PASSED"},
            TEST_USERS["compliance_manager_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = get_checklist(ctx["checklist_id"])
        assert after["passed_count"] == before["passed_count"]
        assert after["na_count"] == before["na_count"]
        assert after["unverified_count"] == before["unverified_count"]

    def test_checklist_not_editable_once_package_leaves_assembling(self, api):
        """PRD §3.6: "Item edits are only possible while the owning package is
        `ASSEMBLING` — attempts after submission are rejected with
        `ERR_CHECKLIST_NOT_EDITABLE`."
        PRD §3.5: "A `CertificationLead` may withdraw manually from `SUBMITTED`
        or `IN_REVIEW` (any other state is `ERR_INVALID_STATE`), or abandon an
        `ASSEMBLING` package"

        Abandoning an ASSEMBLING package leaves its items UNVERIFIED, so the
        item from-state check passes and the edit freeze is the rejecting rule.

        Design: Corner/state_machines/checklist_not_editable_after_submit
        """
        set_clock(MONDAY)
        ctx = setup_submittable_package(title_code="SM2-CHF",
                                        cert_budget_total_cents=1_000_000,
                                        verify_checklist=False)
        abandoned = validate_success(
            api.transition_submission_package(
                ctx["package"]["id"], {"to_status": "WITHDRAWN"}, CL_HEADERS
            ),
            expected_status=200,
        )
        assert abandoned["status"] == "WITHDRAWN"
        assert abandoned["withdrawn_cause"] == "MANUAL"
        before = get_checklist(ctx["checklist_id"])
        assert before["unverified_count"] == before["total_items"]
        resp = api.verify_checklist_item(
            ctx["checklist_id"],
            {"requirement_code": "TRC-PS-01", "result": "PASSED"},
            TEST_USERS["compliance_manager_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_CHECKLIST_NOT_EDITABLE)
        after = get_checklist(ctx["checklist_id"])
        assert after["passed_count"] == before["passed_count"]
        assert after["na_count"] == before["na_count"]
        assert after["unverified_count"] == before["unverified_count"]
