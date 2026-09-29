"""Which rule speaks when a single request violates two of them at once."""

import pytest
from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
)

from test_helpers import factories, fixtures as fx
from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_cents
from test_helpers.test_users import (
    INSPECTOR_HEADERS,
    MANAGER_HEADERS,
    OFFICER_HEADERS,
    OPERATIONS_HEADERS,
)


class TestBodyForeignKeyOutranksSubjectCoherence:
    """A missing site is reported before the two-subject body is examined."""

    @pytest.fixture
    def site_with_facility(self):
        """SITE-D at ACTIVE_DISTURBANCE carrying one real permanent control."""
        program = fx.setup_active_program()
        site = fx.setup_site_with_approved_plan(
            program["term_id"],
            esc_plan_reference="ESC-D-1",
            site_name="SITE-D",
            operator_name="Dunmore Civil",
            disturbed_acres=2.00,
        )
        facility = fx.create_facility(
            site["id"],
            "PRIVATE",
            facility_type="BIORETENTION",
            design_capacity_cf=5200,
            service_area_acres=2.00,
        )
        return {"term_id": program["term_id"], "site": site, "facility": facility}

    def test_01_the_unresolvable_site_key_is_reported_not_the_double_subject(
        self, site_with_facility
    ):
        """Both rules are broken and only the referential one answers.

        PRD: "**Body referential integrity.** Every foreign key supplied in a
        request body must resolve, again yielding the entity's 404. This layer sits
        deliberately above every fiscal and safety rule: a credit application naming
        a facility that does not exist is `ERR_FACILITY_NOT_FOUND`, never a
        credit-ceiling failure."

        Design: Difficulty/priority_pair_validation_conflict/missing_site_fk_outranks_inspection_subject_mismatch
        """
        response = api_client.create_inspection(
            factories.esc_inspection_payload(
                NON_EXISTENT_UUID,
                "2026-07-01",
                "2026-07-15",
                post_construction_facility_id=site_with_facility["facility"]["id"],
                rainfall_trigger=False,
            ),
            INSPECTOR_HEADERS,
        )

        validate_error(response, ApiErrorId.ERR_CONSTRUCTION_SITE_NOT_FOUND.value, 404)

    def test_02_the_refused_request_writes_nothing_at_all(self, site_with_facility):
        """No inspection row appears and the site is left where it was.

        PRD: "Nothing is persisted when a request is rejected — no partial writes,
        no counter increments, no cascades."

        Design: Difficulty/priority_pair_validation_conflict/missing_site_fk_outranks_inspection_subject_mismatch
        """
        api_client.create_inspection(
            factories.esc_inspection_payload(
                NON_EXISTENT_UUID,
                "2026-07-01",
                "2026-07-15",
                post_construction_facility_id=site_with_facility["facility"]["id"],
                rainfall_trigger=False,
            ),
            INSPECTOR_HEADERS,
        )

        inspections, meta = validate_paginated(
            api_client.list_inspections(
                INSPECTOR_HEADERS,
                {"construction_site_id": site_with_facility["site"]["id"]},
            )
        )
        assert meta["total_count"] == 0, (
            f"a refused creation must store no inspection, got {meta['total_count']}"
        )
        assert inspections == [], "the refused creation must leave the page empty"

        site = fx.read_site(site_with_facility["site"]["id"])
        assert site["field_status"] == "ACTIVE_DISTURBANCE", "the site is untouched"
        assert site["open_deficiency_score"] == 0, "no score was written"

    def test_03_repairing_only_the_key_exposes_the_masked_subject_rule(
        self, site_with_facility
    ):
        """With a real site id the two-subject body finally answers.

        PRD: "**Subject and field-set coherence.** Polymorphic and type-conditional
        shape rules evaluate together at this level:
        `ERR_INSPECTION_SUBJECT_MISMATCH`, `ERR_ESC_PLAN_NOT_APPROVED` at inspection
        creation, `ERR_ENFORCEMENT_SUBJECT_INVALID`,
        `ERR_SOURCE_INSPECTION_NOT_FINALIZED` and
        `ERR_OBSERVATION_TYPE_FIELDS_INVALID` (all 422)."

        Design: Difficulty/priority_pair_validation_conflict/missing_site_fk_outranks_inspection_subject_mismatch
        """
        response = api_client.create_inspection(
            factories.esc_inspection_payload(
                site_with_facility["site"]["id"],
                "2026-07-01",
                "2026-07-15",
                post_construction_facility_id=site_with_facility["facility"]["id"],
                rainfall_trigger=False,
            ),
            INSPECTOR_HEADERS,
        )

        validate_error(response, ApiErrorId.ERR_INSPECTION_SUBJECT_MISMATCH.value, 422)


class TestCoolingOffOutranksTheNoDecreaseGuard:
    """An early escalation that also lowers the days reports the timing failure."""

    @pytest.fixture
    def early_notice(self):
        """A 20-day notice on a traced case, with the clock only four days on."""
        program = fx.setup_active_program()
        case = fx.setup_case_in_state(
            program["outfalls"]["OF-01"]["id"], "SOURCE_IDENTIFIED"
        )
        action = fx.issue_enforcement_action(
            "NOTICE_OF_VIOLATION", illicit_discharge_case_id=case["id"], violation_days=20
        )
        fx.set_clock("2026-08-05T00:00:00Z")
        return {"term_id": program["term_id"], "action": action}

    def test_04_the_timing_failure_masks_the_money_failure(self, early_notice):
        """Four days on and five days documented: the cooling-off rule answers.

        PRD: "Because the cooling-off rule outranks the fiscal one, an escalation
        attempted too early *and* with reduced days reports the cooling-off
        failure."

        Design: Difficulty/priority_pair_validation_conflict/escalation_cooling_off_outranks_penalty_decrease_guard
        """
        response = api_client.escalate_enforcement_action(
            early_notice["action"]["id"],
            factories.escalate_payload(violation_days=5),
            OFFICER_HEADERS,
        )

        validate_error(response, ApiErrorId.ERR_ESCALATION_COOLING_OFF.value, 409)

    def test_05_the_refused_escalation_moves_neither_the_row_nor_the_ledger(
        self, early_notice
    ):
        """The action stays ISSUED at 20 days and the term still reads 65000 cents.

        PRD: "A cooling-off period applies: the logical clock must be at least 14
        days after `last_escalated_at`, or at least 14 days after `issued_at` when
        the action has never been escalated, and an early attempt is refused with
        `ERR_ESCALATION_COOLING_OFF`."

        Design: Difficulty/priority_pair_validation_conflict/escalation_cooling_off_outranks_penalty_decrease_guard
        """
        api_client.escalate_enforcement_action(
            early_notice["action"]["id"],
            factories.escalate_payload(violation_days=5),
            OFFICER_HEADERS,
        )

        action = fx.read_action(early_notice["action"]["id"])
        assert action["status"] == "ISSUED", "the refused escalation left the status"
        assert action["action_type"] == "NOTICE_OF_VIOLATION", (
            "the ladder did not advance"
        )
        assert action["billable_violation_days"] == 20, (
            "the stored documented days are untouched"
        )
        assert action["escalation_count"] == 0, "no escalation was counted"
        assert_cents(action["penalty_cents"], 65000, "penalty_cents")

        term = fx.read_term(early_notice["term_id"])
        assert_cents(
            term["total_assessed_penalty_cents"], 65000, "total_assessed_penalty_cents"
        )

    def test_06_once_the_window_opens_the_money_rule_answers(self, early_notice):
        """At fourteen days the same payload is refused for lowering the days.

        PRD: "The officer may supply a revised `violation_days`, but escalation is
        monotonic in money: a supplied value below the stored `violation_days` is
        refused with `ERR_PENALTY_DECREASE_FORBIDDEN`."

        Design: Difficulty/priority_pair_validation_conflict/escalation_cooling_off_outranks_penalty_decrease_guard
        """
        fx.set_clock("2026-08-15T00:00:00Z")

        response = api_client.escalate_enforcement_action(
            early_notice["action"]["id"],
            factories.escalate_payload(violation_days=5),
            OFFICER_HEADERS,
        )

        validate_error(response, ApiErrorId.ERR_PENALTY_DECREASE_FORBIDDEN.value, 422)


class TestRoleCheckOutranksTheFieldStateCheck:
    """An unauthorised caller never learns what state the site is in."""

    @pytest.fixture
    def unreviewed_site(self):
        """SITE-E enrolled but never plan-approved, so still PRE_CONSTRUCTION."""
        program = fx.setup_active_program()
        site = fx.create_site(
            program["term_id"],
            site_name="SITE-E",
            operator_name="Eastgate Paving",
            disturbed_acres=1.80,
        )
        return {"term_id": program["term_id"], "site": site}

    def test_07_the_inspector_is_refused_on_role_not_on_field_state(
        self, unreviewed_site
    ):
        """Stop-work belongs to enforcement, and that is all the caller is told.

        PRD: "**Role authorisation.** A role not listed for the endpoint yields
        `ERR_UNAUTHORIZED` (403). Because this precedes every existence and state
        check, an unauthorised caller can never learn whether a resource exists or
        what state it is in."

        Design: Difficulty/priority_pair_validation_conflict/role_check_outranks_site_field_state_check_on_stop_work
        """
        assert unreviewed_site["site"]["field_status"] == "PRE_CONSTRUCTION", (
            "the site never reached ACTIVE_DISTURBANCE"
        )

        response = api_client.stop_work(
            unreviewed_site["site"]["id"],
            factories.stop_work_payload(
                reason="Inspector attempts an order reserved to enforcement"
            ),
            INSPECTOR_HEADERS,
        )

        validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value, 403)

        site = fx.read_site(unreviewed_site["site"]["id"])
        assert site["field_status"] == "PRE_CONSTRUCTION", "the site is untouched"
        assert site["stop_work_count"] == 0, "no order was counted"

    def test_08_the_authorised_caller_meets_the_masked_state_rule(self, unreviewed_site):
        """The officer's identical call reports the field-state failure.

        PRD: "Stop-work authority belongs to the `EnforcementOfficer`, who supplies
        a `reason` and drives `field_status` from `ACTIVE_DISTURBANCE` to
        `STOP_WORK` while the term is `ACTIVE`, recording that reason in
        `stop_work_reason`, incrementing `stop_work_count` by one, and leaving
        `plan_status` untouched."

        Design: Difficulty/priority_pair_validation_conflict/role_check_outranks_site_field_state_check_on_stop_work
        """
        response = api_client.stop_work(
            unreviewed_site["site"]["id"],
            factories.stop_work_payload(
                reason="Inspector attempts an order reserved to enforcement"
            ),
            OFFICER_HEADERS,
        )

        validate_error(response, ApiErrorId.ERR_SITE_NOT_ACTIVE_DISTURBANCE.value, 409)


class TestVersionGuardOutranksThePendingSampleBlock:
    """A stale compiler is told it is stale before it is told the window is unsettled."""

    @pytest.fixture
    def stale_compile_setup(self):
        """A pre-activation version, one PENDING sample in the window, a DRAFT report."""
        term = fx.create_permit_term()
        stale_version = term["version"]
        fx.register_standard_measure_set(term["id"])
        outfall = fx.create_outfall(
            term["id"],
            "OF-01",
            receiving_water="Mill Creek",
            drainage_area_acres=45.00,
            priority_tier="HIGH",
            baseline_concentration_mg_per_l=0.45,
            design_runoff_kl=20000,
            sweeping_capacity_lane_miles_per_month=40.00,
        )
        activated = fx.get_success_data(
            api_client.activate_permit_term(term["id"], MANAGER_HEADERS)
        )
        sample = fx.record_sample(outfall["id"], "2026-06-15T12:00:00Z", 0.45, 40000)
        report = fx.create_report(term["id"], "2026-01-01", "2026-12-31")
        return {
            "term_id": term["id"],
            "stale_version": stale_version,
            "current_version": activated["version"],
            "outfall_id": outfall["id"],
            "sample": sample,
            "report": report,
        }

    def test_09_the_stale_version_is_reported_before_the_unsettled_window(
        self, stale_compile_setup
    ):
        """The version captured before activation loses to the version guard.

        PRD: "**Optimistic concurrency.** The version guards of §2.6 fire here,
        before any state or business rule, so that a stale writer is told it is
        stale rather than told its business intent is wrong."

        Design: Difficulty/priority_pair_validation_conflict/stale_term_version_outranks_pending_sample_block_on_compile
        """
        assert (
            stale_compile_setup["stale_version"] < stale_compile_setup["current_version"]
        ), "activation must have advanced the term's version"
        assert stale_compile_setup["sample"]["validation_status"] == "PENDING", (
            "the sample in the window is unadjudicated"
        )

        response = api_client.compile_annual_report(
            stale_compile_setup["report"]["id"],
            factories.compile_report_payload(stale_compile_setup["stale_version"]),
            MANAGER_HEADERS,
        )

        validate_error(response, ApiErrorId.ERR_PERMIT_TERM_VERSION_CONFLICT.value, 412)

    def test_10_the_refused_compile_leaves_report_sample_and_term_alone(
        self, stale_compile_setup
    ):
        """Nothing is frozen, nothing is adjudicated, nothing is stamped.

        PRD: "A new report has `status` `DRAFT`, every statistic at its zero value,
        `invalidation_count` at 0, and `compiled_at`, `compiled_by_user_id`,
        `certified_at`, `certified_by_user_id`, `certification_statement`,
        `submitted_at` and `invalidated_reason` all null."

        Design: Difficulty/priority_pair_validation_conflict/stale_term_version_outranks_pending_sample_block_on_compile
        """
        api_client.compile_annual_report(
            stale_compile_setup["report"]["id"],
            factories.compile_report_payload(stale_compile_setup["stale_version"]),
            MANAGER_HEADERS,
        )

        report = fx.read_report(stale_compile_setup["report"]["id"])
        assert report["status"] == "DRAFT", "the refused compile left the report in DRAFT"
        assert report["compiled_at"] is None, "nothing was stamped"
        assert report["invalidation_count"] == 0, "no invalidation happened"

        observations, _ = validate_paginated(
            api_client.list_outfall_observations(
                stale_compile_setup["outfall_id"],
                OPERATIONS_HEADERS,
                {"observation_type": "WET_WEATHER_SAMPLE"},
            )
        )
        assert len(observations) == 1, "the one sample is still the only one"
        assert observations[0]["validation_status"] == "PENDING", (
            "the refused compile did not adjudicate the sample"
        )

        term = fx.read_term(stale_compile_setup["term_id"])
        assert term["last_compiled_at"] is None, (
            "a refused compile must not stamp the term"
        )

    def test_11_correcting_only_the_version_exposes_the_pending_sample_block(
        self, stale_compile_setup
    ):
        """Both blocks must be cleared, and in that order.

        PRD: "It is available only from `DRAFT`, otherwise `ERR_REPORT_NOT_DRAFT`;
        it requires the owning term to be `ACTIVE`; it requires
        `expected_permit_term_version` to match the term's current `version` as
        described in §2.6; and it requires that no wet-weather sample of the term
        whose `observed_at` falls inside the reporting window is still sitting at
        `validation_status` `PENDING`, refusing an unadjudicated window with
        `ERR_PENDING_SAMPLES_IN_WINDOW`."

        Design: Difficulty/priority_pair_validation_conflict/stale_term_version_outranks_pending_sample_block_on_compile
        """
        response = api_client.compile_annual_report(
            stale_compile_setup["report"]["id"],
            factories.compile_report_payload(fx.term_version(stale_compile_setup["term_id"])),
            MANAGER_HEADERS,
        )

        validate_error(response, ApiErrorId.ERR_PENDING_SAMPLES_IN_WINDOW.value, 422)
