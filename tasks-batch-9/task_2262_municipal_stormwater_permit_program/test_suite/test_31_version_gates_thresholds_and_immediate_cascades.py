"""Where a stale account version is refused, where two thresholds are read with
different strictness, and where a cascade is already complete in the response
body of the call that caused it."""

import pytest
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories, fixtures as fx
from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_fee_chain
from test_helpers.constants import INITIAL_CLOCK
from test_helpers.test_users import (
    CLERK_HEADERS,
    IDDE_HEADERS,
    IDDE_ONE,
    MANAGER_HEADERS,
    OPERATIONS_HEADERS,
    make_property_owner_headers,
)

SUSPECT_PANEL = {
    "indicator_bacteria_mpn": 5000.0,
    "indicator_surfactant_mg_per_l": 0.60,
}


class TestAStaleAccountVersionIsRefusedOnRemeasurement:
    """The refused update is the one that would have been correct a moment earlier."""

    @pytest.fixture
    def remeasured(self):
        """A RESIDENTIAL_SINGLE parcel taken from 3000 to 4500 square feet."""
        program = fx.setup_active_program(funding_target_cents=25000)
        account = fx.create_account(
            program["term_id"],
            parcel_id="P-1000",
            parcel_class="RESIDENTIAL_SINGLE",
            impervious_area_sqft=3000.0,
            owner_name="Ada Owner",
        )
        stale_version = account["version"]
        updated = fx.remeasure_account(account["id"], 4500.0, stale_version)
        return {
            "term_id": program["term_id"],
            "account_id": account["id"],
            "stale_version": stale_version,
            "current_version": updated["version"],
            "updated": updated,
        }

    def test_01_the_accepted_remeasurement_reruns_the_whole_fee_chain(self, remeasured):
        """1.50 units bill 9633 for the first and 4104 for the half above it.

        PRD: "A remeasurement of impervious area is recorded by the clerk under the version
        guard of §2.6, supplying the new `impervious_area_sqft` together with
        `expected_stormwater_account_version`. The update reruns the whole fee chain and
        `current_net_fee_cents`, increments the account's `version` by one, and recomputes
        the term's `projected_annual_revenue_cents` and `funding_adequacy_status`." And:
        "`eru_units` is `impervious_area_sqft` divided by the term's `eru_sqft`, rounded to
        2 decimal places. Those units are then split across three tiers: the first 1.00
        unit falls in the first tier, units above 1.00 and up to 4.00 fall in the second,
        and units above 4.00 fall in the third. The first tier bills 9633 cents per unit,
        the second 8207 cents per unit and the third 6541 cents per unit. Each tier's
        component is computed and **rounded to whole cents on its own**, and only then are
        the three components added together to give `gross_fee_cents`" And:
        "`gross_billable_cents` is `gross_fee_cents` plus `class_surcharge_cents`."

        Design: Corner/cross_cutting_complexity_layers/a_stale_account_version_is_refused_on_impervious_remeasurement
        """
        updated = remeasured["updated"]

        assert updated["impervious_area_sqft"] == pytest.approx(4500.0, abs=0.01), (
            f"the new measurement is stored, got {updated['impervious_area_sqft']}"
        )
        assert_fee_chain(
            updated,
            eru_units=1.50,
            gross_fee_cents=13737,
            class_surcharge_cents=0,
            gross_billable_cents=13737,
        )
        assert updated["version"] == remeasured["stale_version"] + 1, (
            "the accepted write moved the version by exactly one, got "
            f"{updated['version']}"
        )

    def test_02_replaying_the_superseded_version_is_refused(self, remeasured):
        """Version 1 was right until version 2 existed, and now it is not.

        PRD: "Recording a remeasured impervious area on a stormwater account requires
        `expected_stormwater_account_version` carrying the client's last observed `version`
        of that account. If the value does not equal the account's current `version`, the
        request is rejected with `ERR_ACCOUNT_VERSION_CONFLICT` (HTTP 412) and no field
        changes. The guard exists because a remeasurement rewrites `eru_units`, the whole
        fee chain and the account's net fee; an update computed against a superseded
        impervious area must not land."

        Design: Corner/cross_cutting_complexity_layers/a_stale_account_version_is_refused_on_impervious_remeasurement
        """
        response = api_client.create_impervious_update(
            remeasured["account_id"],
            factories.impervious_update_payload(9000.0, remeasured["stale_version"]),
            CLERK_HEADERS,
        )

        validate_error(response, ApiErrorId.ERR_ACCOUNT_VERSION_CONFLICT.value, 412)

        account = fx.read_account(remeasured["account_id"])
        assert account["impervious_area_sqft"] == pytest.approx(4500.0, abs=0.01), (
            "the refused 9000 never landed, got "
            f"{account['impervious_area_sqft']}"
        )
        assert account["gross_billable_cents"] == 13737, (
            "and the fee chain is still the version 2 figure, got "
            f"{account['gross_billable_cents']}"
        )
        assert account["version"] == remeasured["current_version"], (
            f"with no version bump, got {account['version']}"
        )

    def test_03_the_same_request_succeeds_once_the_version_is_refreshed(
        self, remeasured
    ):
        """9000 square feet is 3.00 units: 9633 plus two units at 8207.

        PRD: "If the value does not equal the account's current `version`, the request is
        rejected with `ERR_ACCOUNT_VERSION_CONFLICT` (HTTP 412) and no field changes." And:
        "The first tier bills 9633 cents per unit, the second 8207 cents per unit and the
        third 6541 cents per unit." And: "`class_surcharge_cents` is then the
        already-rounded `gross_fee_cents` multiplied by the surcharge rate of the parcel's
        `parcel_class` — 0.00 for `RESIDENTIAL_SINGLE`, 0.05 for `RESIDENTIAL_MULTI`, 0.12
        for `COMMERCIAL` and 0.08 for `INSTITUTIONAL` — rounded to whole cents."

        Design: Corner/cross_cutting_complexity_layers/a_stale_account_version_is_refused_on_impervious_remeasurement
        """
        validate_error(
            api_client.create_impervious_update(
                remeasured["account_id"],
                factories.impervious_update_payload(9000.0, remeasured["stale_version"]),
                CLERK_HEADERS,
            ),
            ApiErrorId.ERR_ACCOUNT_VERSION_CONFLICT.value,
            412,
        )

        accepted = fx.remeasure_account(
            remeasured["account_id"], 9000.0, remeasured["current_version"]
        )

        assert_fee_chain(
            accepted,
            eru_units=3.00,
            gross_fee_cents=26047,
            class_surcharge_cents=0,
            gross_billable_cents=26047,
            current_net_fee_cents=26047,
        )
        assert accepted["version"] == remeasured["current_version"] + 1, (
            f"the third version of the row, got {accepted['version']}"
        )

    def test_04_the_term_rollup_moves_once_per_accepted_write(self, remeasured):
        """One refusal and two acceptances leave the term at the last accepted fee.

        PRD: "The update reruns the whole fee chain and `current_net_fee_cents`, increments
        the account's `version` by one, and recomputes the term's
        `projected_annual_revenue_cents` and `funding_adequacy_status`." And: "which reads
        `ADEQUATE` when `projected_annual_revenue_cents` is greater than or equal to
        `funding_target_cents` and `UNDERFUNDED` otherwise."

        Design: Corner/cross_cutting_complexity_layers/a_stale_account_version_is_refused_on_impervious_remeasurement
        """
        validate_error(
            api_client.create_impervious_update(
                remeasured["account_id"],
                factories.impervious_update_payload(9000.0, remeasured["stale_version"]),
                CLERK_HEADERS,
            ),
            ApiErrorId.ERR_ACCOUNT_VERSION_CONFLICT.value,
            412,
        )
        fx.remeasure_account(
            remeasured["account_id"], 9000.0, remeasured["current_version"]
        )

        term = fx.read_term(remeasured["term_id"])
        assert term["projected_annual_revenue_cents"] == 26047, (
            "the term carries the one account's net fee, got "
            f"{term['projected_annual_revenue_cents']}"
        )
        assert term["funding_adequacy_status"] == "ADEQUATE", (
            "26047 clears a target of 25000, got "
            f"{term['funding_adequacy_status']}"
        )


class TestACreditApplicationAgainstASupersededSnapshotIsRefused:
    """The second version guard defends a child creation, so nothing is created."""

    @pytest.fixture
    def superseded(self, active_program):
        """A COMMERCIAL parcel remeasured to the very same 9020 square feet."""
        account = fx.create_account(
            active_program["term_id"],
            parcel_id="P-1000",
            parcel_class="COMMERCIAL",
            impervious_area_sqft=9020.0,
            owner_name="Ada Owner",
        )
        stale_version = account["version"]
        updated = fx.remeasure_account(account["id"], 9020.0, stale_version)
        return {
            "account_id": account["id"],
            "stale_version": stale_version,
            "current_version": updated["version"],
            "updated": updated,
            "owner": make_property_owner_headers(account["id"]),
        }

    def test_05_a_remeasurement_that_changes_no_value_still_moves_the_version(
        self, superseded
    ):
        """The guard keys on the version, not on whether a field moved.

        PRD: "The update reruns the whole fee chain and `current_net_fee_cents`, increments
        the account's `version` by one, and recomputes the term's
        `projected_annual_revenue_cents` and `funding_adequacy_status`." And: "each such
        recomputation is itself a mutation of the row that owns the field: `updated_at` is
        refreshed and `version` increments even when the only difference is a recomputed
        number."

        Design: Corner/cross_cutting_complexity_layers/a_credit_application_prepared_against_a_superseded_account_snapshot_is_refused
        """
        updated = superseded["updated"]

        assert updated["version"] == superseded["stale_version"] + 1, (
            f"the no-op remeasurement still bumped the version, got {updated['version']}"
        )
        assert_fee_chain(
            updated,
            eru_units=3.01,
            gross_fee_cents=26129,
            class_surcharge_cents=3135,
            gross_billable_cents=29264,
            total_credit_pct=0.0000,
            current_net_fee_cents=29264,
        )

    def test_06_filing_against_the_stale_snapshot_is_refused(self, superseded):
        """An application prepared against version 1 cannot be trusted.

        PRD: "Creating a fee credit application likewise requires
        `expected_stormwater_account_version` equal to the target account's current
        `version`, and a mismatch is rejected with `ERR_ACCOUNT_VERSION_CONFLICT` (HTTP
        412) with no application row created. The credit ceiling is evaluated against the
        account's current credit pool, so an application prepared against an outdated
        account snapshot must be refused."

        Design: Corner/cross_cutting_complexity_layers/a_credit_application_prepared_against_a_superseded_account_snapshot_is_refused
        """
        response = api_client.create_fee_credit_application(
            factories.credit_application_payload(
                superseded["account_id"], superseded["stale_version"], 0.2500
            ),
            superseded["owner"],
        )

        validate_error(response, ApiErrorId.ERR_ACCOUNT_VERSION_CONFLICT.value, 412)

        account = fx.read_account(superseded["account_id"])
        assert account["version"] == superseded["current_version"], (
            "the refused filing did not bump the account either, got "
            f"{account['version']}"
        )

    def test_07_the_refused_filing_leaves_no_application_row(self, superseded):
        """The account's own application collection is still empty afterwards.

        PRD: "a mismatch is rejected with `ERR_ACCOUNT_VERSION_CONFLICT` (HTTP 412) with no
        application row created." And: "Collections accept optional equality filters, and a
        filter that is omitted does not narrow the result." And: "Fee credit applications
        filter on `stormwater_account_id`, `post_construction_facility_id` and `status`."

        Design: Corner/cross_cutting_complexity_layers/a_credit_application_prepared_against_a_superseded_account_snapshot_is_refused
        """
        validate_error(
            api_client.create_fee_credit_application(
                factories.credit_application_payload(
                    superseded["account_id"], superseded["stale_version"], 0.2500
                ),
                superseded["owner"],
            ),
            ApiErrorId.ERR_ACCOUNT_VERSION_CONFLICT.value,
            412,
        )

        rows, meta = validate_paginated(
            api_client.list_fee_credit_applications(
                CLERK_HEADERS, {"stormwater_account_id": superseded["account_id"]}
            )
        )
        assert rows == [], f"no row was created, got {len(rows)}"
        assert meta["total_count"] == 0, (
            f"and the count agrees, got {meta['total_count']}"
        )

    def test_08_the_same_filing_succeeds_against_the_refreshed_version(
        self, superseded
    ):
        """Nothing about the request changes except the version it names.

        PRD: "A new application has `status` `SUBMITTED`, `submitted_at` stamped from the
        logical clock, `applicant_user_id` set to the submitting actor,
        `approved_credit_pct`, `reviewed_by_user_id`, `approved_at`, `return_reason`,
        `revoked_reason` and `revoked_at` null, and `resubmission_count` at 0. Filing
        increments the account's `version` by one, and the requested percentage enters the
        `INTERIM` forward-looking pool at once without changing `total_credit_pct`." And:
        "When `X-User-Role` is `PropertyOwner`, `X-User-ID` is the `id` of the acting
        `StormwaterAccount`; ownership checks on any resource that references a
        `StormwaterAccount` compare the resource's account foreign key to `X-User-ID`, and
        a fee credit application additionally records the submitting owner in
        `applicant_user_id` and compares it on resubmission."

        Design: Corner/cross_cutting_complexity_layers/a_credit_application_prepared_against_a_superseded_account_snapshot_is_refused
        """
        validate_error(
            api_client.create_fee_credit_application(
                factories.credit_application_payload(
                    superseded["account_id"], superseded["stale_version"], 0.2500
                ),
                superseded["owner"],
            ),
            ApiErrorId.ERR_ACCOUNT_VERSION_CONFLICT.value,
            412,
        )

        application = validate_success(
            api_client.create_fee_credit_application(
                factories.credit_application_payload(
                    superseded["account_id"], superseded["current_version"], 0.2500
                ),
                superseded["owner"],
            ),
            201,
        )

        assert application["status"] == "SUBMITTED", (
            f"the accepted filing is pending review, got {application['status']}"
        )
        assert application["applicant_user_id"] == superseded["account_id"], (
            "the owner acts as its own account, got "
            f"{application['applicant_user_id']}"
        )
        assert application["approved_credit_pct"] is None, "nothing is granted yet"
        assert application["reviewed_by_user_id"] is None, "and nobody has reviewed it"
        assert application["resubmission_count"] == 0, "it is the first attempt"
        assert application["submitted_at"] == INITIAL_CLOCK, (
            f"stamped from the logical clock, got {application['submitted_at']}"
        )

        account = fx.read_account(superseded["account_id"])
        assert account["total_credit_pct"] == pytest.approx(0.0000, abs=0.00005), (
            "a SUBMITTED row does not yet count, got "
            f"{account['total_credit_pct']}"
        )
        assert account["current_net_fee_cents"] == 29264, (
            f"so the net fee is still the gross, got {account['current_net_fee_cents']}"
        )


class TestTheOpenCaseGateIsStrictWhileTheEnforcementGateIsInclusive:
    """Three open cases are tolerated; the second enforcement action is not."""

    @pytest.fixture
    def program(self):
        """Four outfalls, one site, and two measures reported fully attained."""
        program = fx.setup_active_program(
            outfall_codes=("OF-01", "OF-02", "OF-03", "OF-04"),
            funding_target_cents=25000,
        )
        site = fx.create_site(
            program["term_id"],
            site_name="SITE-A",
            operator_name="Northgate Civil",
            disturbed_acres=1.50,
        )
        fx.report_progress(program["measures"]["ILLICIT_DISCHARGE"]["id"], 20.0)
        fx.report_progress(program["measures"]["CONSTRUCTION_RUNOFF"]["id"], 30.0)
        return {
            "term_id": program["term_id"],
            "outfalls": program["outfalls"],
            "measures": program["measures"],
            "site_id": site["id"],
        }

    def _screen(self, program, code, observed_at):
        return fx.record_screening(
            program["outfalls"][code]["id"], observed_at, suspect=True, **SUSPECT_PANEL
        )

    def _screen_three(self, program):
        self._screen(program, "OF-01", "2026-08-01T08:00:00Z")
        self._screen(program, "OF-02", "2026-08-01T09:00:00Z")
        self._screen(program, "OF-03", "2026-08-01T10:00:00Z")

    def _nov(self, program):
        return fx.issue_enforcement_action(
            "NOTICE_OF_VIOLATION",
            construction_site_id=program["site_id"],
            violation_days=0,
        )

    def test_09_three_open_cases_leave_a_fully_attained_measure_met(self, program):
        """The comparison is strictly greater than three, so three is not enough.

        PRD: "For the `ILLICIT_DISCHARGE` measure, if `open_case_count` is greater than
        three, the result is `BEHIND`." And: "`attainment_pct` is 0.00 when
        `measurable_goal_target` is 0; otherwise it is 100 multiplied by
        `measurable_goal_actual`, divided by `measurable_goal_target`, rounded to 2 decimal
        places." And: "If `attainment_pct` is at least 100.00, the result is `MET`."

        Design: Corner/cross_cutting_complexity_layers/the_open_case_gate_is_strict_while_the_enforcement_gate_is_inclusive
        """
        self._screen_three(program)

        measure = fx.read_measure(program["measures"]["ILLICIT_DISCHARGE"]["id"])
        assert measure["open_case_count"] == 3, (
            f"three screenings opened three cases, got {measure['open_case_count']}"
        )
        assert measure["attainment_pct"] == pytest.approx(100.00, abs=0.01), (
            f"20 of a target of 20, got {measure['attainment_pct']}"
        )
        assert measure["goal_status"] == "MET", (
            f"three is not above three, so no gate is tripped, got {measure['goal_status']}"
        )

    def test_10_the_fourth_open_case_overrides_a_hundred_percent_attainment(
        self, program
    ):
        """A gate wins outright once the count passes three.

        PRD: "For the `ILLICIT_DISCHARGE` measure, if `open_case_count` is greater than
        three, the result is `BEHIND`." And: "The first three tests are compliance **gates**,
        and a gate wins outright: a measure sitting at 125.00 percent attainment is still
        `BEHIND` while its gate is tripped." And: "Otherwise, if `behind_measure_count` is
        exactly one, or `exceeding_outfall_count` is at least one, it becomes `AT_RISK`."

        Design: Corner/cross_cutting_complexity_layers/the_open_case_gate_is_strict_while_the_enforcement_gate_is_inclusive
        """
        self._screen_three(program)
        self._screen(program, "OF-04", "2026-08-01T11:00:00Z")

        measure = fx.read_measure(program["measures"]["ILLICIT_DISCHARGE"]["id"])
        assert measure["open_case_count"] == 4, (
            f"a fourth case is open, got {measure['open_case_count']}"
        )
        assert measure["attainment_pct"] == pytest.approx(100.00, abs=0.01), (
            "nobody reported worse numbers, got "
            f"{measure['attainment_pct']}"
        )
        assert measure["goal_status"] == "BEHIND", (
            f"and the gate overrides the band, got {measure['goal_status']}"
        )

        term = fx.read_term(program["term_id"])
        assert term["behind_measure_count"] == 1, (
            f"one measure is behind, got {term['behind_measure_count']}"
        )
        assert term["compliance_posture"] == "AT_RISK", (
            f"exactly one behind measure is AT_RISK, got {term['compliance_posture']}"
        )

    def test_11_the_first_enforcement_action_leaves_construction_runoff_met(
        self, program
    ):
        """One action is below a threshold read as two or more.

        PRD: "For the `CONSTRUCTION_RUNOFF` measure, if `enforcement_count` is two or more,
        the result is `BEHIND`." And: "A site subject has its `open_enforcement_count` — the
        count of actions on the site whose `status` is `ISSUED` or `ESCALATED` — raised, and
        the `CONSTRUCTION_RUNOFF` control measure's `enforcement_count` raised with it,
        which is the counter that trips the construction-runoff gate at two." And: "Third,
        `escalation_multiplier` is read from that prior total: 1.00 when
        `prior_assessed_total_cents` is 0; 1.50 when it is greater than 0 but less than
        100000 cents; and 2.25 when it is 100000 cents or more." And: "`penalty_cents` is
        then the ladder base for the action's current `action_type` — 25000 cents for
        `NOTICE_OF_VIOLATION`, 50000 cents for `ADMINISTRATIVE_ORDER`, 100000 cents for
        `CIVIL_PENALTY` — plus 2000 cents for each of the `billable_violation_days`, with
        that sum multiplied by `escalation_multiplier` and the product rounded to whole
        cents."

        Design: Corner/cross_cutting_complexity_layers/the_open_case_gate_is_strict_while_the_enforcement_gate_is_inclusive
        """
        action = self._nov(program)

        assert action["prior_assessed_total_cents"] == 0, (
            f"it is the first action on the site, got {action['prior_assessed_total_cents']}"
        )
        assert action["escalation_multiplier"] == pytest.approx(1.00, abs=0.01), (
            f"a zero prior total multiplies by 1.00, got {action['escalation_multiplier']}"
        )
        assert action["billable_violation_days"] == 0, "no days were documented"
        assert action["penalty_cents"] == 25000, (
            f"the notice base alone, got {action['penalty_cents']}"
        )

        measure = fx.read_measure(program["measures"]["CONSTRUCTION_RUNOFF"]["id"])
        assert measure["enforcement_count"] == 1, (
            f"one action against the term's sites, got {measure['enforcement_count']}"
        )
        assert measure["goal_status"] == "MET", (
            f"one is below two, so the band stands, got {measure['goal_status']}"
        )

    def test_12_the_second_enforcement_action_trips_the_inclusive_gate(self, program):
        """Two or more is inclusive, so the second action alone flips the measure.

        PRD: "For the `CONSTRUCTION_RUNOFF` measure, if `enforcement_count` is two or more,
        the result is `BEHIND`." And: "Second, `prior_assessed_total_cents` is the sum of
        `penalty_cents` over the *other* enforcement actions on the same subject whose
        `status` is `ISSUED`, `ESCALATED` or `CLOSED`, excluding this action's own row and
        frozen before this row's own penalty is written." And: "1.50 when it is greater than
        0 but less than 100000 cents" And: "the construction-runoff gate flips it when a
        finalize cascade raises `enforcement_count` to two or more"

        Design: Corner/cross_cutting_complexity_layers/the_open_case_gate_is_strict_while_the_enforcement_gate_is_inclusive
        """
        self._nov(program)
        second = self._nov(program)

        assert second["prior_assessed_total_cents"] == 25000, (
            "the earlier notice is the prior total, got "
            f"{second['prior_assessed_total_cents']}"
        )
        assert second["escalation_multiplier"] == pytest.approx(1.50, abs=0.01), (
            f"a prior total under 100000 multiplies by 1.50, got "
            f"{second['escalation_multiplier']}"
        )
        assert second["penalty_cents"] == 37500, (
            f"25000 multiplied by 1.50, got {second['penalty_cents']}"
        )

        measure = fx.read_measure(program["measures"]["CONSTRUCTION_RUNOFF"]["id"])
        assert measure["enforcement_count"] == 2, (
            f"two actions now, got {measure['enforcement_count']}"
        )
        assert measure["goal_status"] == "BEHIND", (
            f"and the gate is inclusive at two, got {measure['goal_status']}"
        )
        assert measure["attainment_pct"] == pytest.approx(100.00, abs=0.01), (
            f"over an untouched attainment, got {measure['attainment_pct']}"
        )

    def test_13_both_gates_together_drive_the_term_non_compliant(self, program):
        """Four open cases and two notices leave two measures behind.

        PRD: "If `behind_measure_count` is two or more, or if `behind_measure_count` is at
        least one while `exceeding_outfall_count` is also at least one,
        `compliance_posture` becomes `NON_COMPLIANT`." And: "`behind_measure_count` is the
        number of control measures of the term whose `status` is `ACTIVE` and whose
        `goal_status` is `BEHIND`." And: "The new `penalty_cents` is added to the term's
        `total_assessed_penalty_cents`, which may push a `COMPILED` or `CERTIFIED` annual
        report back to `DRAFT`."

        Design: Corner/cross_cutting_complexity_layers/the_open_case_gate_is_strict_while_the_enforcement_gate_is_inclusive
        """
        self._screen_three(program)
        self._screen(program, "OF-04", "2026-08-01T11:00:00Z")
        self._nov(program)
        self._nov(program)

        term = fx.read_term(program["term_id"])
        assert term["behind_measure_count"] == 2, (
            f"both gated measures are behind, got {term['behind_measure_count']}"
        )
        assert term["exceeding_outfall_count"] == 0, (
            f"no outfall was ever assessed, got {term['exceeding_outfall_count']}"
        )
        assert term["compliance_posture"] == "NON_COMPLIANT", (
            f"two behind measures are NON_COMPLIANT, got {term['compliance_posture']}"
        )
        assert term["total_assessed_penalty_cents"] == 62500, (
            f"25000 plus 37500, got {term['total_assessed_penalty_cents']}"
        )


class TestRetirementWithdrawsLaneMilesFromTheMeasureOnly:
    """Two identically named fields with two different input sets."""

    @pytest.fixture
    def swept(self):
        """OF-01 swept for 12.00 lane miles and OF-02 for 8.00."""
        program = fx.setup_active_program(
            outfall_codes=("OF-01", "OF-02"), funding_target_cents=25000
        )
        fx.append_sweeping_run(
            program["outfalls"]["OF-01"]["id"], "2026-08-01", "2026-08-10", 12.00
        )
        fx.append_sweeping_run(
            program["outfalls"]["OF-02"]["id"], "2026-08-01", "2026-08-10", 8.00
        )
        return {
            "term_id": program["term_id"],
            "measure_id": program["measures"]["MUNICIPAL_OPERATIONS"]["id"],
            "of_01_id": program["outfalls"]["OF-01"]["id"],
            "of_02_id": program["outfalls"]["OF-02"]["id"],
        }

    def test_14_the_measure_sums_the_lane_miles_of_every_active_outfall(self, swept):
        """12.00 and 8.00 together attain a goal of 20.

        PRD: "Each accepted run mirrors the term-wide lane-mile total into the
        `MUNICIPAL_OPERATIONS` control measure's `swept_lane_miles_ytd` — the sum of
        `lane_miles_swept` across the `sweeping_runs` of every `ACTIVE` outfall in the term
        — and copies that same figure into that measure's `measurable_goal_actual`, then
        recomputes its `attainment_pct` and `goal_status` and the term's posture." And: "If
        `attainment_pct` is at least 100.00, the result is `MET`."

        Design: Corner/cross_cutting_complexity_layers/retiring_an_outfall_withdraws_its_lane_miles_from_the_measure_but_not_from_the_outfall
        """
        measure = fx.read_measure(swept["measure_id"])

        assert measure["swept_lane_miles_ytd"] == pytest.approx(20.00, abs=0.01), (
            f"the term-wide total, got {measure['swept_lane_miles_ytd']}"
        )
        assert measure["measurable_goal_actual"] == pytest.approx(20.0, abs=0.01), (
            f"copied into the actual, got {measure['measurable_goal_actual']}"
        )
        assert measure["attainment_pct"] == pytest.approx(100.00, abs=0.01), (
            f"20 of a target of 20, got {measure['attainment_pct']}"
        )
        assert measure["goal_status"] == "MET", (
            f"and the flags leave the gate open, got {measure['goal_status']}"
        )

    def test_15_retiring_an_outfall_recomputes_the_measure_from_the_live_set(
        self, swept
    ):
        """Withdrawing 8.00 lane miles leaves 12.00 against a goal of 20.

        PRD: "Retirement writes `RETIRED` into `status`, which removes the row from annual
        screening-coverage denominators and from the annual net load total, recomputes the
        term's `exceeding_outfall_count` and `compliance_posture`, and increments the
        outfall's `version` by one." And: "the sum of `lane_miles_swept` across the
        `sweeping_runs` of every `ACTIVE` outfall in the term" And: "Counters, percentages,
        postures, ledger totals and eligibility flags are recomputed by the server whenever
        any input to them changes" And: "If `attainment_pct` is at least 75.00, the result
        is `ON_TRACK`." And: "Otherwise the result is `BEHIND`."

        Design: Corner/cross_cutting_complexity_layers/retiring_an_outfall_withdraws_its_lane_miles_from_the_measure_but_not_from_the_outfall
        """
        validate_success(api_client.retire_outfall(swept["of_02_id"], MANAGER_HEADERS))

        measure = fx.read_measure(swept["measure_id"])
        assert measure["swept_lane_miles_ytd"] == pytest.approx(12.00, abs=0.01), (
            "only the surviving outfall's runs count, got "
            f"{measure['swept_lane_miles_ytd']}"
        )
        assert measure["measurable_goal_actual"] == pytest.approx(12.0, abs=0.01), (
            f"and the actual follows it down, got {measure['measurable_goal_actual']}"
        )
        assert measure["attainment_pct"] == pytest.approx(60.00, abs=0.01), (
            f"12 of a target of 20, got {measure['attainment_pct']}"
        )
        assert measure["goal_status"] == "BEHIND", (
            f"60.00 falls below the 75.00 band, got {measure['goal_status']}"
        )

    def test_16_the_retired_outfall_keeps_its_own_history(self, swept):
        """No sweeping run was written or deleted by the retirement.

        PRD: "Each accepted run is appended to the outfall's append-only `sweeping_runs`
        list as an entry holding `run_start_date`, `run_end_date` and `lane_miles_swept`,
        and raises the outfall's `swept_lane_miles_ytd`, which is the sum of
        `lane_miles_swept` over the whole list to 2 decimal places." And: "Retirement writes
        `RETIRED` into `status`, which removes the row from annual screening-coverage
        denominators and from the annual net load total, recomputes the term's
        `exceeding_outfall_count` and `compliance_posture`, and increments the outfall's
        `version` by one."

        Design: Corner/cross_cutting_complexity_layers/retiring_an_outfall_withdraws_its_lane_miles_from_the_measure_but_not_from_the_outfall
        """
        before = fx.read_outfall(swept["of_02_id"])
        validate_success(api_client.retire_outfall(swept["of_02_id"], MANAGER_HEADERS))

        retired = fx.read_outfall(swept["of_02_id"])
        assert retired["status"] == "RETIRED", (
            f"the row is retired, got {retired['status']}"
        )
        assert retired["swept_lane_miles_ytd"] == pytest.approx(8.00, abs=0.01), (
            "its own year-to-date total is untouched, got "
            f"{retired['swept_lane_miles_ytd']}"
        )
        assert len(retired["sweeping_runs"]) == 1, (
            f"and its one run is still logged, got {len(retired['sweeping_runs'])}"
        )
        entry = retired["sweeping_runs"][0]
        assert entry["run_start_date"] == "2026-08-01", "with its start date"
        assert entry["run_end_date"] == "2026-08-10", "its end date"
        assert entry["lane_miles_swept"] == pytest.approx(8.00, abs=0.01), (
            f"and its lane miles, got {entry['lane_miles_swept']}"
        )
        assert retired["version"] == before["version"] + 1, (
            f"retirement moved the version once, got {retired['version']}"
        )

        survivor = fx.read_outfall(swept["of_01_id"])
        assert survivor["swept_lane_miles_ytd"] == pytest.approx(12.00, abs=0.01), (
            f"the surviving outfall is untouched, got {survivor['swept_lane_miles_ytd']}"
        )

    def test_17_the_retirement_reaches_the_posture_through_the_measure(self, swept):
        """An outfall that was never assessed still moves the term's posture.

        PRD: "`behind_measure_count` is the number of control measures of the term whose
        `status` is `ACTIVE` and whose `goal_status` is `BEHIND`. `exceeding_outfall_count`
        is the number of outfalls of the term whose `status` is `ACTIVE` and whose
        `tmdl_status` is `EXCEEDING`." And: "Otherwise, if `behind_measure_count` is exactly
        one, or `exceeding_outfall_count` is at least one, it becomes `AT_RISK`."

        Design: Corner/cross_cutting_complexity_layers/retiring_an_outfall_withdraws_its_lane_miles_from_the_measure_but_not_from_the_outfall
        """
        before = fx.read_term(swept["term_id"])
        assert before["compliance_posture"] == "COMPLIANT", (
            f"nothing is behind before the retirement, got {before['compliance_posture']}"
        )

        validate_success(api_client.retire_outfall(swept["of_02_id"], MANAGER_HEADERS))

        term = fx.read_term(swept["term_id"])
        assert term["behind_measure_count"] == 1, (
            f"the operations measure fell behind, got {term['behind_measure_count']}"
        )
        assert term["exceeding_outfall_count"] == 0, (
            f"no outfall exceeds anything, got {term['exceeding_outfall_count']}"
        )
        assert term["compliance_posture"] == "AT_RISK", (
            f"one behind measure is AT_RISK, got {term['compliance_posture']}"
        )


class TestTheWritingCallsOwnResponseIsAlreadyConsistent:
    """One POST, and every aggregate it touched is correct on the first read."""

    @pytest.fixture
    def program(self, active_program):
        """OF-01 under a term whose illicit-discharge goal is fully attained."""
        fx.report_progress(active_program["measures"]["ILLICIT_DISCHARGE"]["id"], 20.0)
        return {
            "term_id": active_program["term_id"],
            "outfall_id": active_program["outfalls"]["OF-01"]["id"],
            "measure_id": active_program["measures"]["ILLICIT_DISCHARGE"]["id"],
        }

    def _screen(self, program):
        return fx.record_screening(
            program["outfall_id"], "2026-08-01T08:00:00Z", suspect=True, **SUSPECT_PANEL
        )

    def test_18_the_post_answers_with_the_computed_discriminator_already_set(
        self, program
    ):
        """The response body of the write already carries the derived result.

        PRD: "Unless otherwise noted, operations that create or modify a resource will
        return the created or updated resource object in the data field." And: "Otherwise
        the server counts how many of three indicator limits are exceeded, in each case by
        a strictly greater comparison, treating a null reading as not exceeding:
        `indicator_bacteria_mpn` above 1000 most probable number per 100 millilitres,
        `indicator_surfactant_mg_per_l` above 0.25 milligrams per litre, and
        `indicator_ammonia_mg_per_l` above 0.50 milligrams per litre. If two or more of
        those three are exceeded, the result is `SUSPECT`." And: "Screenings are stored with
        `validation_status` `NOT_APPLICABLE` and a null `sample_load_lb`; samples are stored
        with a null `screening_result`, as described in §3.7." And: "the acting operator is
        captured as `recorded_by_user_id`"

        Design: Corner/consistency_model/every_cascaded_field_is_already_correct_in_the_writing_calls_own_response
        """
        observation = self._screen(program)

        assert observation["screening_result"] == "SUSPECT", (
            "two exceeded limits are decided inside the write, got "
            f"{observation['screening_result']}"
        )
        assert observation["validation_status"] == "NOT_APPLICABLE", (
            f"a screening is never adjudicated, got {observation['validation_status']}"
        )
        assert observation["sample_load_lb"] is None, "and it carries no load"
        assert observation["recorded_by_user_id"] == IDDE_ONE, (
            f"the acting investigator is stamped, got {observation['recorded_by_user_id']}"
        )
        assert observation["observation_type"] == "DRY_WEATHER_SCREENING", (
            f"the kind is echoed, got {observation['observation_type']}"
        )
        assert observation["observed_at"] == "2026-08-01T08:00:00Z", (
            f"as is the field instant, got {observation['observed_at']}"
        )

    def test_19_the_first_read_of_the_outfall_already_agrees(self, program):
        """No second write and no settling period between the POST and the GET.

        PRD: "Every dry-weather screening stamps the outfall's `last_screened_at` with the
        observation's `observed_at` and increments `screening_count` by one." And: "A
        `SUSPECT` result moves `screening_status` from either `NOT_SCREENED` or `CLEAR` to
        `SUSPECT` and additionally opens a case: the server creates an **illicit discharge
        case** in `OPEN` whose `outfall_id` is this outfall and whose
        `origin_observation_id` is the new observation, stamps the case's `opened_at` from
        the logical clock, raises the outfall's `open_case_count` by one, then recomputes
        the `ILLICIT_DISCHARGE` control measure's `open_case_count` and `goal_status`, the
        term's posture, and — where the posture moved and the observation falls inside a
        closed reporting window — the annual report's return to `DRAFT`."

        Design: Corner/consistency_model/every_cascaded_field_is_already_correct_in_the_writing_calls_own_response
        """
        self._screen(program)

        outfall = fx.read_outfall(program["outfall_id"])
        assert outfall["screening_status"] == "SUSPECT", (
            f"the discriminator reached the parent, got {outfall['screening_status']}"
        )
        assert outfall["screening_count"] == 1, (
            f"one screening is counted, got {outfall['screening_count']}"
        )
        assert outfall["open_case_count"] == 1, (
            f"and one case is open against it, got {outfall['open_case_count']}"
        )
        assert outfall["last_screened_at"] == "2026-08-01T08:00:00Z", (
            "stamped from the observation rather than the clock, got "
            f"{outfall['last_screened_at']}"
        )

    def test_20_the_case_the_cascade_created_is_immediately_listable(self, program):
        """The case exists, in OPEN, pointing back at the observation that made it.

        PRD: "the server creates an **illicit discharge case** in `OPEN` whose `outfall_id`
        is this outfall and whose `origin_observation_id` is the new observation, stamps the
        case's `opened_at` from the logical clock" And: "No operator ever creates a case by
        hand; the screening cascade is its only origin." And: "Illicit discharge cases
        filter on `outfall_id`, `origin_observation_id` and `status`."

        Design: Corner/consistency_model/every_cascaded_field_is_already_correct_in_the_writing_calls_own_response
        """
        observation = self._screen(program)

        rows, meta = validate_paginated(
            api_client.list_illicit_discharge_cases(
                IDDE_HEADERS, {"outfall_id": program["outfall_id"], "status": "OPEN"}
            )
        )

        assert meta["total_count"] == 1, (
            f"exactly one case was opened, got {meta['total_count']}"
        )
        case = rows[0]
        assert case["status"] == "OPEN", f"it starts at OPEN, got {case['status']}"
        assert case["outfall_id"] == program["outfall_id"], "against this outfall"
        assert case["origin_observation_id"] == observation["id"], (
            "and it names its origin, got "
            f"{case['origin_observation_id']}"
        )
        assert case["opened_at"] == INITIAL_CLOCK, (
            f"opened from the logical clock, got {case['opened_at']}"
        )

    def test_21_the_measure_census_is_live_but_still_under_the_gate(self, program):
        """One open case is counted at once and does not trip a gate at three.

        PRD: "then recomputes the `ILLICIT_DISCHARGE` control measure's `open_case_count`
        and `goal_status`, the term's posture" And: "For the `ILLICIT_DISCHARGE` measure, if
        `open_case_count` is greater than three, the result is `BEHIND`." And: "If
        `attainment_pct` is at least 100.00, the result is `MET`."

        Design: Corner/consistency_model/every_cascaded_field_is_already_correct_in_the_writing_calls_own_response
        """
        self._screen(program)

        measure = fx.read_measure(program["measure_id"])
        assert measure["open_case_count"] == 1, (
            f"the census moved with the cascade, got {measure['open_case_count']}"
        )
        assert measure["attainment_pct"] == pytest.approx(100.00, abs=0.01), (
            f"20 of a target of 20, got {measure['attainment_pct']}"
        )
        assert measure["goal_status"] == "MET", (
            f"one is not above three, got {measure['goal_status']}"
        )

        term = fx.read_term(program["term_id"])
        assert term["behind_measure_count"] == 0, (
            f"nothing fell behind, got {term['behind_measure_count']}"
        )
        assert term["compliance_posture"] == "COMPLIANT", (
            f"so the posture held, got {term['compliance_posture']}"
        )

    def test_22_the_computed_result_is_filterable_in_the_same_breath(self, program):
        """A field the server derived is queryable, and re-reading changes nothing.

        PRD: "Observations at one outfall filter on `observation_type`,
        `validation_status` and `screening_result`." And: "Counters, percentages, postures,
        ledger totals and eligibility flags are recomputed by the server whenever any input
        to them changes" And: "A `SUSPECT` result moves `screening_status` from either
        `NOT_SCREENED` or `CLEAR` to `SUSPECT`"

        Design: Corner/consistency_model/every_cascaded_field_is_already_correct_in_the_writing_calls_own_response
        """
        observation = self._screen(program)

        rows, meta = validate_paginated(
            api_client.list_outfall_observations(
                program["outfall_id"], OPERATIONS_HEADERS, {"screening_result": "SUSPECT"}
            )
        )
        assert meta["total_count"] == 1, (
            f"the derived discriminator filters, got {meta['total_count']}"
        )
        assert rows[0]["id"] == observation["id"], "and it is the observation just written"

        first = fx.read_outfall(program["outfall_id"])
        second = fx.read_outfall(program["outfall_id"])
        assert first["screening_status"] == second["screening_status"] == "SUSPECT", (
            "a repeated read returns the same value"
        )
        assert first["open_case_count"] == second["open_case_count"] == 1, (
            "with no settling period anywhere in the cascade"
        )
        assert first["version"] == second["version"], (
            f"and no further write happened, got {first['version']} then {second['version']}"
        )
