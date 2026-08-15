"""Disclosure-report generation, auditor acknowledgment, and certified-run gating."""
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
    create_disclosure_report,
    setup_certified_plan,
    api_client,
)

PLAN_ADMIN = TEST_USERS["plan_admin_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


def _computed_run_fixture(sponsor="Disc Co"):
    """Plan with a COMPUTED (not certified) run. Returns (plan, run, prep, rev)."""
    plan = create_plan(sponsor_name=sponsor, prior_aftap_pct=90.00)
    plan_id = plan["id"]
    prep, rev = register_prep_and_review_actuaries()
    batch = create_locked_census(plan_id, [
        {"external_ref": "R1", "date_of_birth": "1965-01-01", "status": "RETIREE",
         "current_annual_benefit": 1000},
    ])
    aset = create_locked_assumption_set(plan_id, prep["id"], rev["id"])
    create_asset_statement(plan_id)
    ava = create_asset_valuation(plan_id, prep["id"])
    run = create_valuation_run(plan_id, prep["id"], batch["id"], aset["id"], ava["id"])
    compute_run(run["id"], prep["id"])
    return plan, run, prep, rev


def _certified_single_retiree(sponsor="Ack Co"):
    return setup_certified_plan(
        sponsor_name=sponsor,
        participant_rows=[
            {"external_ref": "R1", "date_of_birth": "1965-01-01", "status": "RETIREE",
             "current_annual_benefit": 1000},
        ],
        market_value_begin=1000, benefits_paid=50, investment_return=50,
        prior_aftap_pct=90.00,
    )


class TestDisclosureGating:
    def test_disclosure_requires_certified_run(self, api):
        """PRD §3.9: "filing or disclosure work against an uncertified run is
        rejected with `ERR_VALUATION_RUN_NOT_CERTIFIED` (HTTP 422)."
        PRD §3.9: "A `PlanAdmin`, `Actuary`, or `SeniorActuary` generates one from
        a certified run belonging to the same plan — again
        `ERR_VALUATION_RUN_NOT_CERTIFIED` guards the reference."

        Design: Corner/validations/disclosure_requires_certified_run
        """
        plan, run, prep, rev = _computed_run_fixture()
        resp = api.create_disclosure_report(
            plan["id"], {"valuation_run_id": run["id"]}, PLAN_ADMIN
        )
        validate_error(resp, ApiErrorId.ERR_VALUATION_RUN_NOT_CERTIFIED, 422)


class TestAcknowledgeTerminal:
    def test_acknowledge_disclosure_twice_terminal_lockdown(self, api):
        """PRD §3.9: "The report begins `DRAFT` and reaches its terminal
        `ACKNOWLEDGED` state when an `Auditor` acknowledges it, stamping
        `acknowledged_by` with the auditor's `X-User-ID`."
        PRD §2.8: from-state violations reject as `ERR_INVALID_STATE` (HTTP 409).

        Design: Corner/state_machines/acknowledge_disclosure_twice_terminal_lockdown
        """
        fx = _certified_single_retiree()
        rep = create_disclosure_report(fx["plan"]["id"], fx["run"]["id"])
        assert rep["status"] == "DRAFT"

        acked = validate_success(api.acknowledge_disclosure_report(rep["id"], AUDITOR), 200)
        assert acked["status"] == "ACKNOWLEDGED"

        resp = api.acknowledge_disclosure_report(rep["id"], AUDITOR)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
