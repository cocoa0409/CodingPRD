"""PBGC premium computation, filing lifecycle, amend cycle, and cascade voiding."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    create_plan,
    register_prep_and_review_actuaries,
    create_locked_census,
    create_locked_assumption_set,
    create_asset_statement,
    create_asset_valuation,
    create_valuation_run,
    compute_run,
    certify_run,
    get_plan_version,
    get_run,
    create_pbgc_filing,
    get_pbgc_filing,
    set_clock,
    setup_certified_plan,
    api_client,
)

PLAN_ADMIN = TEST_USERS["plan_admin_headers"]

FAMILY_A_ROWS = [
    {"external_ref": "A1", "date_of_birth": "1966-03-10", "status": "ACTIVE",
     "years_of_service": 10, "annual_compensation": 100000},
    {"external_ref": "A2", "date_of_birth": "1968-11-20", "status": "ACTIVE",
     "years_of_service": 5, "annual_compensation": 60000},
    {"external_ref": "R1", "date_of_birth": "1965-01-30", "status": "RETIREE",
     "current_annual_benefit": 50000},
]

THREE_RETIREE_ROWS = [
    {"external_ref": "R1", "date_of_birth": "1965-01-30", "status": "RETIREE",
     "current_annual_benefit": 100000},
    {"external_ref": "R2", "date_of_birth": "1965-05-01", "status": "RETIREE",
     "current_annual_benefit": 0},
    {"external_ref": "R3", "date_of_birth": "1965-09-09", "status": "RETIREE",
     "current_annual_benefit": 0},
]


def _certified_plan(sponsor, rows, mvb, cr, bp, ir, **kwargs):
    return setup_certified_plan(
        sponsor_name=sponsor,
        participant_rows=rows,
        market_value_begin=mvb, contributions_received=cr,
        benefits_paid=bp, investment_return=ir,
        prior_aftap_pct=kwargs.get("prior_aftap_pct", 84.00),
    )


class TestPremiumMinCapBranches:
    def test_pbgc_premium_uncapped_branch(self, api):
        """PRD §3.9: "`flat_rate_premium` as one hundred dollars per participant;
        the uncapped variable premium as fifty dollars per thousand dollars of UVB,
        rounded half-up to cents; and `variable_rate_premium` as that uncapped
        value limited to a cap of six hundred dollars per participant."
        PRD §3.9: "`uvb`, the unfunded vested benefits, as the premium target minus
        market assets, floored at zero".

        Design: Difficulty/combinatorial_formula/pbgc_premium_min_cap_branch_switch
        """
        fx = _certified_plan("Uncapped Co", FAMILY_A_ROWS, 60000, 0, 2000, 3000)
        filing = create_pbgc_filing(fx["plan"]["id"], fx["run"]["id"], "STANDARD")
        # FT 67172.20; market 61000.00; UVB 6172.20; variable 308.61 < cap 1800
        assert filing["participant_count"] == 3
        assert filing["flat_rate_premium"] == 300.00
        assert filing["variable_rate_premium"] == 308.61
        assert filing["cap_applied"] is False
        assert filing["total_premium"] == 608.61

    def test_pbgc_premium_cap_bound_branch(self, api):
        """PRD §3.9: "`variable_rate_premium` as that uncapped value limited to a
        cap of six hundred dollars per participant. The `cap_applied` flag is true
        when the uncapped variable premium is greater than or equal to the cap —
        equality binds the cap."

        Design: Difficulty/combinatorial_formula/pbgc_premium_min_cap_branch_switch
        """
        fx = _certified_plan("Capped Co", THREE_RETIREE_ROWS, 64000, 0, 3200, 3200)
        filing = create_pbgc_filing(fx["plan"]["id"], fx["run"]["id"], "STANDARD")
        # FT 100000.00; market 64000.00; UVB 36000.00; uncapped 1800.00 == cap 1800
        assert filing["uvb"] == 36000.00
        assert filing["variable_rate_premium"] == 1800.00
        assert filing["cap_applied"] is True
        assert filing["total_premium"] == 2100.00

    def test_pbgc_cap_exact_equality_binds(self, api):
        """PRD §3.9: "The `cap_applied` flag is true when the uncapped variable
        premium is greater than or equal to the cap — equality binds the cap."

        Design: Difficulty/boundary_precision_check/pbgc_cap_exact_equality_binds
        """
        fx = _certified_plan("Cap Eq Co", THREE_RETIREE_ROWS, 64000, 0, 3200, 3200)
        filing = create_pbgc_filing(fx["plan"]["id"], fx["run"]["id"], "STANDARD")
        assert filing["uvb"] == 36000.00
        # uncapped variable = 36000 * 50/1000 = 1800.00; cap = 3 * 600 = 1800
        assert filing["variable_rate_premium"] == 1800.00
        assert filing["cap_applied"] is True
        assert filing["total_premium"] == 2100.00

    def test_pbgc_cap_just_below_equality_does_not_bind(self, api):
        """PRD §3.9: "The `cap_applied` flag is true when the uncapped variable
        premium is greater than or equal to the cap — equality binds the cap."
        Below the cap, the min() selects the uncapped value and the flag is false.

        Design: Difficulty/boundary_precision_check/pbgc_cap_exact_equality_binds
        """
        # Family A: UVB 6172.20 -> uncapped 308.61 < cap 1800 -> flag false
        fx = _certified_plan("Cap Below Co", FAMILY_A_ROWS, 60000, 0, 2000, 3000)
        filing = create_pbgc_filing(fx["plan"]["id"], fx["run"]["id"], "STANDARD")
        assert filing["variable_rate_premium"] == 308.61
        assert filing["cap_applied"] is False


class TestAlternativeMethod:
    def test_pbgc_alternative_method_variant_selection(self, api):
        """PRD §3.9: "`premium_target` equal to `funding_target` under the
        `STANDARD` method, or one hundred five percent of `funding_target` rounded
        half-up to cents under `ALTERNATIVE`".

        Design: Corner/calculations/pbgc_alternative_method_variant_selection
        """
        fx = _certified_plan("Alt Co", FAMILY_A_ROWS, 60000, 0, 2000, 3000)
        filing = create_pbgc_filing(fx["plan"]["id"], fx["run"]["id"], "ALTERNATIVE")
        # premium_target = 67172.20 * 1.05 = 70530.81; UVB = 9530.81
        assert filing["premium_target"] == 70530.81
        assert filing["uvb"] == 9530.81
        # variable = round_half_up(9530.81 * 50/1000, 2) = 476.54
        assert filing["variable_rate_premium"] == 476.54
        assert filing["total_premium"] == 776.54
        assert filing["cap_applied"] is False

    def test_pbgc_standard_method_default_when_omitted(self, api):
        """PRD §3.9: "an optional `premium_method` — `STANDARD` when omitted".
        PRD §3.9: "`premium_target` equal to `funding_target` under the `STANDARD`
        method".

        Design: Corner/calculations/pbgc_alternative_method_variant_selection
        """
        fx = _certified_plan("Alt 2 Co", FAMILY_A_ROWS, 60000, 0, 2000, 3000)
        resp = api.create_pbgc_filing(
            fx["plan"]["id"], {"valuation_run_id": fx["run"]["id"]}, PLAN_ADMIN
        )
        filing = validate_success(resp, 201)
        assert filing["premium_method"] == "STANDARD"
        assert filing["premium_target"] == 67172.20


class TestFilingGateAndDeadline:
    def test_pbgc_file_requires_certified_run(self, api):
        """PRD §3.9: "Filing moves a `DRAFT` filing to `FILED`, permitted only
        while the referenced run is `CERTIFIED`".
        PRD §3.9: "filing or disclosure work against an uncertified run is rejected
        with `ERR_VALUATION_RUN_NOT_CERTIFIED` (HTTP 422)".

        Design: Difficulty/cross_entity_state_dependency/pbgc_file_requires_certified_run
        """
        plan = create_plan(sponsor_name="File Gate Co", prior_aftap_pct=84.00)
        plan_id = plan["id"]
        prep, rev = register_prep_and_review_actuaries()
        batch = create_locked_census(plan_id, [
            {"external_ref": "R1", "date_of_birth": "1965-04-04", "status": "RETIREE",
             "current_annual_benefit": 1000},
        ])
        aset = create_locked_assumption_set(plan_id, prep["id"], rev["id"])
        create_asset_statement(plan_id)
        ava = create_asset_valuation(plan_id, prep["id"])
        run = create_valuation_run(plan_id, prep["id"], batch["id"], aset["id"], ava["id"])
        compute_run(run["id"], prep["id"])  # COMPUTED, not certified
        filing = create_pbgc_filing(plan_id, run["id"], "STANDARD")

        resp = api.file_pbgc_filing(filing["id"], PLAN_ADMIN)
        validate_error(resp, ApiErrorId.ERR_VALUATION_RUN_NOT_CERTIFIED, 422)
        f = get_pbgc_filing(filing["id"])
        assert f["status"] == "DRAFT"
        assert f["filed_at"] is None

    def test_pbgc_file_succeeds_once_run_certified(self, api):
        """PRD §3.9: "Filing moves a `DRAFT` filing to `FILED`, permitted only
        while the referenced run is `CERTIFIED` and the logical clock is on or
        before October 15 of the plan year ... a successful filing stamps
        `filed_at` from the logical clock."

        Design: Difficulty/cross_entity_state_dependency/pbgc_file_requires_certified_run
        """
        set_clock("2028-09-01T00:00:00Z")
        fx = _certified_plan("File Gate 4 Co", [
            {"external_ref": "R1", "date_of_birth": "1965-01-01", "status": "RETIREE",
             "current_annual_benefit": 1000},
        ], 1000, 0, 50, 50, prior_aftap_pct=90.00)
        # The run is CERTIFIED here, so the same filing that would be gated on a
        # COMPUTED run now files cleanly.
        filing = create_pbgc_filing(fx["plan"]["id"], fx["run"]["id"], "STANDARD")
        filed = validate_success(api.file_pbgc_filing(filing["id"], PLAN_ADMIN), 200)
        assert filed["status"] == "FILED"
        assert filed["filed_at"] is not None
        assert filed["filed_at"].startswith("2028-09-01")

    def test_filing_deadline_enforced(self, api):
        """PRD §3.9: "Filing moves a `DRAFT` filing to `FILED`, permitted only
        while the referenced run is `CERTIFIED` and the logical clock is on or
        before October 15 of the plan year; a filing attempted after that deadline
        is rejected with `ERR_FILING_DEADLINE_PASSED` (HTTP 422)".

        Design: Corner/validations/filing_deadline_enforced
        """
        fx = _certified_plan("Late File Co", [
            {"external_ref": "R1", "date_of_birth": "1965-01-01", "status": "RETIREE",
             "current_annual_benefit": 1000},
        ], 1000, 0, 50, 50, prior_aftap_pct=90.00)
        filing = create_pbgc_filing(fx["plan"]["id"], fx["run"]["id"], "STANDARD")
        set_clock("2028-10-16T00:00:00Z")
        resp = api.file_pbgc_filing(filing["id"], PLAN_ADMIN)
        validate_error(resp, ApiErrorId.ERR_FILING_DEADLINE_PASSED, 422)
        assert get_pbgc_filing(filing["id"])["status"] == "DRAFT"


class TestAmendCycle:
    def test_amend_without_supersession_rejected(self, api):
        """PRD §3.9: "Amending without such a delta — while the plan's currently
        certified run is the same run the filing already references — is rejected
        with `ERR_NO_AMENDMENT_DELTA` (HTTP 422)."

        Design: Corner/validations/amend_without_supersession_rejected
        """
        set_clock("2028-09-01T00:00:00Z")
        fx = _certified_plan("NoDelta Co", [
            {"external_ref": "R1", "date_of_birth": "1965-01-01", "status": "RETIREE",
             "current_annual_benefit": 1000},
        ], 1000, 0, 50, 50, prior_aftap_pct=90.00)
        filing = create_pbgc_filing(fx["plan"]["id"], fx["run"]["id"], "STANDARD")
        api.file_pbgc_filing(filing["id"], PLAN_ADMIN)

        resp = api.amend_pbgc_filing(filing["id"], PLAN_ADMIN)
        validate_error(resp, ApiErrorId.ERR_NO_AMENDMENT_DELTA, 422)
        assert get_pbgc_filing(filing["id"])["status"] == "FILED"

    def test_pbgc_filing_amend_cycle(self, api):
        """PRD §3.9: "When a newer certification has since superseded the run a
        `FILED` filing references ... the filing may be amended, moving `FILED` →
        `AMENDED`: `valuation_run_id` is re-pointed to the currently certified run,
        every premium field is recomputed from it, and `filed_at` is cleared to
        null. ... An `AMENDED` filing is filed again under the same certification
        and deadline preconditions, re-stamping `filed_at`."
        PRD §3.6: "Any previously `CERTIFIED` valuation run of the same plan
        transitions to `SUPERSEDED`."

        Design: Difficulty/non_linear_state_machine/pbgc_filing_amend_cycle
        """
        set_clock("2028-09-01T00:00:00Z")
        fx = _certified_plan("Amend Co", FAMILY_A_ROWS, 60000, 0, 2000, 3000)
        plan_id = fx["plan"]["id"]
        run1_id = fx["run"]["id"]
        filing = create_pbgc_filing(plan_id, run1_id, "STANDARD")
        api.file_pbgc_filing(filing["id"], PLAN_ADMIN)
        assert get_pbgc_filing(filing["id"])["status"] == "FILED"

        # Second run over same locked references -> certify supersedes run1
        prep, rev = fx["prep"], fx["rev"]
        run2 = create_valuation_run(
            plan_id, prep["id"], fx["batch"]["id"], fx["aset"]["id"], fx["ava"]["id"]
        )
        compute_run(run2["id"], prep["id"])
        plan_v2 = get_plan_version(plan_id)
        certify_run(run2["id"], rev["id"], plan_v2)

        assert get_run(run1_id)["status"] == "SUPERSEDED"
        assert get_run(run2["id"])["status"] == "CERTIFIED"
        # FILED filing survives the cascade (only DRAFT/AMENDED void)
        assert get_pbgc_filing(filing["id"])["status"] == "FILED"

        # amend: FILED -> AMENDED, filed_at cleared, re-pointed to run2
        amended = validate_success(api.amend_pbgc_filing(filing["id"], PLAN_ADMIN), 200)
        assert amended["status"] == "AMENDED"
        assert amended["filed_at"] is None
        assert amended["valuation_run_id"] == run2["id"]

        # re-file: AMENDED -> FILED
        refiled = validate_success(api.file_pbgc_filing(filing["id"], PLAN_ADMIN), 200)
        assert refiled["status"] == "FILED"
        assert refiled["filed_at"] is not None

    def test_pbgc_filing_amend_repoints_to_certified_run(self, api):
        """PRD §3.9: "the filing may be amended, moving `FILED` → `AMENDED`:
        `valuation_run_id` is re-pointed to the currently certified run, every
        premium field is recomputed from it, and `filed_at` is cleared to null."
        PRD §3.6: "Any previously `CERTIFIED` valuation run of the same plan
        transitions to `SUPERSEDED`."

        Design: Difficulty/non_linear_state_machine/pbgc_filing_amend_cycle
        """
        set_clock("2028-09-01T00:00:00Z")
        fx = _certified_plan("Amend 2 Co", FAMILY_A_ROWS, 60000, 0, 2000, 3000)
        plan_id = fx["plan"]["id"]
        run1_id = fx["run"]["id"]
        filing = create_pbgc_filing(plan_id, run1_id, "STANDARD")
        api.file_pbgc_filing(filing["id"], PLAN_ADMIN)
        filed = get_pbgc_filing(filing["id"])
        assert filed["filed_at"] is not None
        assert filed["valuation_run_id"] == run1_id

        prep, rev = fx["prep"], fx["rev"]
        run2 = create_valuation_run(
            plan_id, prep["id"], fx["batch"]["id"], fx["aset"]["id"], fx["ava"]["id"]
        )
        compute_run(run2["id"], prep["id"])
        plan_v2 = get_plan_version(plan_id)
        certify_run(run2["id"], rev["id"], plan_v2)

        amended = validate_success(api.amend_pbgc_filing(filing["id"], PLAN_ADMIN), 200)
        assert amended["valuation_run_id"] == run2["id"]
        assert amended["status"] == "AMENDED"
        assert amended["filed_at"] is None

    def test_cascade_voids_draft_filing_on_new_certification(self, api):
        """PRD §3.6: "Finally, every `DRAFT` or `AMENDED` PBGC filing of the plan
        transitions to `VOID`, because its premium basis is now stale."
        PRD §3.9: "a `FILED` filing is never cascade-voided and instead moves
        through the amend path."

        Design: Corner/cross_cutting_layers/cascade_voids_draft_filing_on_new_certification
        """
        fx = _certified_plan("VoidCasc Co", [
            {"external_ref": "R1", "date_of_birth": "1965-01-01", "status": "RETIREE",
             "current_annual_benefit": 1000},
        ], 1000, 0, 50, 50, prior_aftap_pct=90.00)
        plan_id = fx["plan"]["id"]
        run1_id = fx["run"]["id"]
        filing = create_pbgc_filing(plan_id, run1_id, "STANDARD")  # DRAFT

        prep, rev = fx["prep"], fx["rev"]
        run2 = create_valuation_run(
            plan_id, prep["id"], fx["batch"]["id"], fx["aset"]["id"], fx["ava"]["id"]
        )
        compute_run(run2["id"], prep["id"])
        plan_v2 = get_plan_version(plan_id)
        certify_run(run2["id"], rev["id"], plan_v2)

        assert get_pbgc_filing(filing["id"])["status"] == "VOID"
        assert get_run(run1_id)["status"] == "SUPERSEDED"
