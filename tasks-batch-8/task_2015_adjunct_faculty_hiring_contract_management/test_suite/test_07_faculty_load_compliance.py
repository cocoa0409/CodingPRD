"""Faculty record: load variants, benefits boundary, compliance-gated activation,
parallel status dimensions, rollover lapse, completion conservation
(PRD Sections 2.4, 3.4, 3.5, 3.6, 3.7)."""
from test_helpers import (
    ApiErrorId,
    activate_fall_term,
    add_credential,
    assert_load_read,
    create_department,
    create_fall_term,
    create_section,
    get_faculty,
    get_success_data,
    hire_faculty,
    issue_contract,
    issue_contract_in,
    set_clock,
    setup_active_contract_scenario,
    standard_fall_scenario,
    validate_error,
    validate_success,
    verify_credential,
)
from test_helpers import TEST_USERS

ADMIN = TEST_USERS["hr_admin_headers"]
CHAIR = TEST_USERS["chair_headers"]
DEAN = TEST_USERS["dean_headers"]


class TestLoadVariants:
    def _issued_contract_scenario(self, dept_code):
        """One ISSUED contract (load 3.00), zero ACTIVE; clock parked pre-term."""
        scn = standard_fall_scenario(
            dept_code=dept_code, load_cap_units=4.50,
            rate_basis="PER_CONTACT_HOUR", base_rate_cents=200000,
            longevity_step_cents=5000, longevity_step_cap=5,
            weekly_contact_hours=3.0,
        )
        scn["contract"] = issue_contract_in(scn)
        return scn

    def test_faculty_load_scheduled_variant_counts_issued(self, api, hr_admin_headers):
        """PRD Section 3.4: "The scheduled variant sums `load_units` over contracts
        in either `ISSUED` or `ACTIVE` status, making it a pre-term planning
        preview"
        PRD Section 3.4: "A computed read of load returns the actual variant by
        default and the scheduled variant when the caller passes the `variant`
        query parameter as `scheduled`; the response carries `load_units`, the
        echoed `variant`, the resolved `term_code`, the term's `load_cap_units`,
        and the resulting `benefits_eligible`."

        Design: Difficulty/dual_variant_calc/faculty_load_scheduled_vs_actual_variant_divergence
        """
        scn = self._issued_contract_scenario("ENGL")
        data = validate_success(api.get_faculty_load(
            scn["faculty"]["id"], hr_admin_headers, params={"variant": "scheduled"}), 200)
        assert_load_read(data)
        assert data["variant"] == "scheduled"
        assert data["load_units"] == 3.00, "the ISSUED contract counts in the preview"
        assert data["term_code"] == "2026FA"
        assert data["load_cap_units"] == 4.50

    def test_faculty_load_actual_variant_gates_benefits(self, api, hr_admin_headers):
        """PRD Section 3.4: "The authoritative actual variant sums `load_units`
        over contracts in `ACTIVE` status only; `current_term_load_units` always
        stores this variant, and it is what `benefits_eligible` reads."
        PRD Section 3.4: "A computed read of load returns the actual variant by
        default"

        Same stored data as the scheduled read: the ISSUED contract contributes
        zero to the actual variant.

        Design: Difficulty/dual_variant_calc/faculty_load_scheduled_vs_actual_variant_divergence
        """
        scn = self._issued_contract_scenario("ENG2")
        data = validate_success(
            api.get_faculty_load(scn["faculty"]["id"], hr_admin_headers), 200)
        assert_load_read(data)
        assert data["load_units"] == 0.00, "only ACTIVE contracts count"
        assert data["benefits_eligible"] is False, "0.00 < 4.50"
        contract = get_success_data(api.get_contract(scn["contract"]["id"], hr_admin_headers))
        assert contract["contract_status"] == "ISSUED", "section still SCHEDULED pre-term"


class TestActivationGuard:
    def _onboarding_contract_scenario(self, dept_code):
        scn = standard_fall_scenario(
            dept_code=dept_code, load_cap_units=4.50, tier="DOCTORATE",
            compliance="ONBOARDING_NO_COMPLIANCE_CREDS",
            rate_basis="PER_COURSE", base_rate_cents=480000,
        )
        scn["contract"] = issue_contract_in(scn)
        return scn

    def test_contract_activation_guarded_by_faculty_compliance(self, api, hr_admin_headers):
        """PRD Section 3.5: "Activation is guarded: the contract moves from `ISSUED`
        to `ACTIVE` only when its faculty's `compliance_status` is `COMPLIANT`. A
        contract whose faculty is still in onboarding or has lapsed remains
        `ISSUED` while the section runs without it — the section flip is not
        blocked."

        Design: Difficulty/cross_entity_state_dependency/contract_activation_guarded_by_faculty_compliance
        """
        scn = self._onboarding_contract_scenario("PHIL")
        activate_fall_term()
        section = get_success_data(api.get_section(scn["section"]["id"], hr_admin_headers))
        contract = get_success_data(api.get_contract(scn["contract"]["id"], hr_admin_headers))
        assert section["section_status"] == "RUNNING", "term start fired the section flip"
        assert contract["contract_status"] == "ISSUED", (
            "activation guard blocked: faculty compliance_status is ONBOARDING"
        )

    def test_guarded_contract_contributes_zero_actual_load(self, api, hr_admin_headers):
        """PRD Section 3.4: "The authoritative actual variant sums `load_units`
        over contracts in `ACTIVE` status only"

        Design: Difficulty/cross_entity_state_dependency/contract_activation_guarded_by_faculty_compliance
        """
        scn = self._onboarding_contract_scenario("PHI2")
        activate_fall_term()
        faculty = get_faculty(scn["faculty"]["id"])
        assert faculty["compliance_status"] == "ONBOARDING"
        assert faculty["current_term_load_units"] == 0.00, (
            "the still-ISSUED contract contributes nothing to the actual load"
        )
        assert faculty["benefits_eligible"] is False


class TestBenefitsBoundary:
    def _at_cap_scenario(self, dept_code):
        """Two ACTIVE contracts of 3.00 + 1.50 load: exactly the 4.50 cap."""
        scn = standard_fall_scenario(
            dept_code=dept_code, load_cap_units=4.50,
            weekly_contact_hours=3.0, course_code="NUR-101",
        )
        sec_b = create_section(scn["dept"]["id"], term_code="2026FA",
                               course_code="NUR-102", weekly_contact_hours=1.5,
                               credit_hours=1)
        issue_contract_in(scn)
        issue_contract(scn["faculty"]["id"], sec_b["id"], scn["schedule"]["id"])
        activate_fall_term()
        return scn

    def test_benefits_cap_exact_equality_is_eligible(self, api, hr_admin_headers):
        """PRD Section 3.4: "The system maintains `current_term_load_units`, the sum
        of `load_units` over the faculty's contracts in the current term, and
        `benefits_eligible`, a boolean that is true exactly when that sum reaches or
        exceeds the current term's `load_cap_units` — the comparison is inclusive,
        so a load exactly equal to the cap qualifies."

        3.00 + 1.50 == 4.50 == load_cap_units -> eligible.

        Design: Difficulty/boundary_precision_check/benefits_cap_exact_equality_is_eligible
        """
        scn = self._at_cap_scenario("NURS")
        data = validate_success(
            api.get_faculty_load(scn["faculty"]["id"], hr_admin_headers), 200)
        assert_load_read(data)
        assert data["load_units"] == 4.50
        assert data["load_cap_units"] == 4.50
        assert data["benefits_eligible"] is True, "boundary is inclusive (>=)"

    def test_benefits_flag_on_faculty_record_agrees(self, api):
        """PRD Section 3.4: "`current_term_load_units` always stores this variant,
        and it is what `benefits_eligible` reads."

        Design: Difficulty/boundary_precision_check/benefits_cap_exact_equality_is_eligible
        """
        scn = self._at_cap_scenario("NUR2")
        faculty = get_faculty(scn["faculty"]["id"])
        assert faculty["current_term_load_units"] == 4.50
        assert faculty["benefits_eligible"] is True


class TestParallelDimensions:
    def _onboarding_retention_listed_faculty(self, api, dept_code):
        """Faculty approved with a verified DEGREE but REJECTED background/training
        (compliance stays ONBOARDING), then placed on the 2027SP retention list."""
        set_clock("2026-06-01T00:00:00Z")
        dept = create_department(code=dept_code, contact_hour_value=1.00)
        create_fall_term()
        hired = hire_faculty(
            dept["id"], tier="MASTERS", min_education_tier="BACHELORS",
            tier_credential_kind="DEGREE", compliance="ONBOARDING_REJECTED_COMPLIANCE",
        )
        faculty = hired["faculty"]
        entry = get_success_data(api.create_retention_entry(
            {"faculty_id": faculty["id"], "department_id": dept["id"],
             "list_term_code": "2027SP"}, DEAN))
        return dept, hired, entry

    def test_retention_listing_moves_only_the_retention_dimension(self, api, hr_admin_headers):
        """PRD Section 3.4: "The retention dimension — `retention_status` — moves
        among `PROVISIONAL`, `RETENTION_LISTED`, and `NON_REAPPOINTED`, and gates
        whether new contracts may be issued at all. Neither dimension implies
        anything about the other."
        PRD Section 3.8: "Creation also flips the faculty's `retention_status` from
        `PROVISIONAL` to `RETENTION_LISTED`, bumping the faculty `version`"

        Design: Difficulty/non_linear_state_machine/faculty_parallel_dimensions_independent_evolution
        """
        _, hired, entry = self._onboarding_retention_listed_faculty(api, "CHEM")
        faculty = get_faculty(hired["faculty"]["id"])
        assert faculty["compliance_status"] == "ONBOARDING", (
            "no VERIFIED BACKGROUND_CHECK + TRAINING pair exists"
        )
        assert faculty["retention_status"] == "RETENTION_LISTED", (
            "the retention dimension moved independently"
        )
        assert entry["rank_position"] == 1, "sole entry in scope ranks first"

    def test_compliance_completion_moves_only_the_compliance_dimension(self, api, hr_admin_headers):
        """PRD Section 3.3: "When the application is already `APPROVED` and a verify
        decision completes the pair of verified `BACKGROUND_CHECK` and `TRAINING`
        credentials, the hired faculty member's compliance status flips
        automatically"
        PRD Section 3.3: "Registration is accepted while the application is
        `SUBMITTED`, `UNDER_REVIEW`, `RETURNED_FOR_REVISION`, or `APPROVED`"

        Design: Difficulty/non_linear_state_machine/faculty_parallel_dimensions_independent_evolution
        """
        _, hired, entry = self._onboarding_retention_listed_faculty(api, "CHE2")
        app_id = hired["application"]["id"]
        bg = add_credential(app_id, "BACKGROUND_CHECK")
        tr = add_credential(app_id, "TRAINING")
        verify_credential(bg["id"])
        verify_credential(tr["id"])

        faculty = get_faculty(hired["faculty"]["id"])
        assert faculty["compliance_status"] == "COMPLIANT", (
            "post-approval completion of the pair flips compliance"
        )
        assert faculty["retention_status"] == "RETENTION_LISTED", (
            "the retention dimension is untouched by the compliance flip"
        )


class TestCompletionConservation:
    def test_completion_moves_contract_and_increments_completed_terms(self, api, hr_admin_headers):
        """PRD Section 3.6: "Completion moves every attached `ACTIVE` contract to
        `COMPLETED`, sets each such contract's `payable_cents` equal to its
        `gross_pay_cents` — the final variant of the pay calculation — increments
        the faculty's `completed_terms` by one per completed contract, and
        recomputes load aggregates."

        Design: Difficulty/compensating_invariant/faculty_load_conserved_across_activation_and_completion
        """
        scn = setup_active_contract_scenario(dept_code="MUSC")
        before = get_faculty(scn["faculty"]["id"])
        assert before["completed_terms"] == 0
        assert before["current_term_load_units"] == 3.00

        set_clock("2026-12-12T00:00:00Z")
        get_success_data(api.complete_section(scn["section"]["id"], CHAIR))

        contract = get_success_data(api.get_contract(scn["contract"]["id"], hr_admin_headers))
        assert contract["contract_status"] == "COMPLETED"
        assert contract["payable_cents"] == 450000, "completion pays the full gross"
        after = get_faculty(scn["faculty"]["id"])
        assert after["completed_terms"] == 1, (
            "completed_terms increments by one per completed contract"
        )

    def test_completion_releases_actual_load(self, api):
        """PRD Section 3.4: "The authoritative actual variant sums `load_units`
        over contracts in `ACTIVE` status only"
        PRD Section 3.6: "Completion ... recomputes load aggregates."

        One contract of load 3.00: load goes 3.00 -> 0.00 as the contract leaves
        ACTIVE.

        Design: Difficulty/compensating_invariant/faculty_load_conserved_across_activation_and_completion
        """
        scn = setup_active_contract_scenario(dept_code="MUS2")
        assert get_faculty(scn["faculty"]["id"])["current_term_load_units"] == 3.00
        set_clock("2026-12-12T00:00:00Z")
        get_success_data(api.complete_section(scn["section"]["id"], CHAIR))
        after = get_faculty(scn["faculty"]["id"])
        assert after["current_term_load_units"] == 0.00, (
            "load delta -3.00 == -(load_units of the completed contract)"
        )


class TestTermRollover:
    def test_term_rollover_lapses_idle_faculty_and_blocks_new_contracts(self, api, hr_admin_headers):
        """PRD Section 3.7: "The run completes every `RUNNING` section of that term
        whose `end_date` falls strictly before the current logical date, with the
        full contract-completion cascade of Section 3.6; it lapses every
        `COMPLIANT` faculty member who holds no `ACTIVE` and no `COMPLETED`
        contract in the term being closed; it recomputes faculty load aggregates;
        and it advances the term's `rollover_status` to `ROLLED_OVER`"
        PRD Section 3.1: "from that moment, publishing a posting that names the
        term is refused with `ERR_INVALID_STATE`, and issuing a contract into the
        term is refused with `ERR_CONTRACT_REFERENCE_INVALID`."

        Design: Corner/endpoints/term_rollover_lapses_idle_faculty_and_blocks_new_contracts
        """
        scn = standard_fall_scenario(
            dept_code="ROLL", load_cap_units=9.00,
            schedule_window=("2026-08-01", "2027-06-30"),
            weekly_contact_hours=3.0, course_code="ROL-101",
        )
        busy = scn["faculty"]
        idle = hire_faculty(scn["dept"]["id"], applicant_name="Idle One",
                            applicant_email="idle@x.edu")["faculty"]
        contract = issue_contract_in(scn)
        activate_fall_term()
        set_clock("2026-12-12T00:00:00Z")

        rolled = validate_success(api.rollover_term(scn["term"]["id"], hr_admin_headers), 200)
        assert rolled["rollover_status"] == "ROLLED_OVER"

        idle_after = get_faculty(idle["id"])
        assert idle_after["compliance_status"] == "LAPSED", (
            "no ACTIVE/COMPLETED contract in the closed term"
        )
        busy_after = get_faculty(busy["id"])
        assert busy_after["compliance_status"] == "COMPLIANT"
        assert busy_after["completed_terms"] == 1, "rollover completed the section"

        contract_after = get_success_data(api.get_contract(contract["id"], hr_admin_headers))
        assert contract_after["contract_status"] == "COMPLETED"

        late_section = create_section(scn["dept"]["id"], term_code="2026FA",
                                      course_code="ROL-102", weekly_contact_hours=3.0)
        refused = api.create_contract(
            {
                "faculty_id": busy["id"],
                "section_id": late_section["id"],
                "rate_schedule_id": scn["schedule"]["id"],
                "expected_faculty_version": busy_after["version"],
            },
            CHAIR,
        )
        validate_error(refused, ApiErrorId.ERR_CONTRACT_REFERENCE_INVALID)
