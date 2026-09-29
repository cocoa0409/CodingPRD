"""Precondition builders.

Every test starts against an empty database, so each of these functions builds
the state it needs from scratch through the endpoints of PRD 4.  All of them use
the lenient success reader so that a broken precondition is reported as a setup
failure rather than as a false negative on the rule under test.

The identity-bearing roles of PRD 2.5 are threaded carefully: sponsor and
delegate headers are always built from the identifier of the jurisdiction that
owns the row being written.
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import api_client
from .test_users import (
    make_bca_reviewer_headers,
    make_equity_officer_headers,
    make_hazard_analyst_headers,
    make_jurisdiction_delegate_headers,
    make_project_sponsor_headers,
    make_regional_administrator_headers,
)

ADMIN = make_regional_administrator_headers
ANALYST = make_hazard_analyst_headers
REVIEWER = make_bca_reviewer_headers
EQUITY = make_equity_officer_headers


# --- Member governments (PRD 3.1) ------------------------------------------


def create_jurisdiction(**overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_jurisdiction(f.jurisdiction_payload(**overrides), ADMIN())
    )


def create_harbor(**overrides: Any) -> Dict[str, Any]:
    """The disadvantaged coastal member government (svi_score 0.62, weight 4)."""
    return get_success_data(api_client.create_jurisdiction(f.harbor_payload(**overrides), ADMIN()))


def create_ridge(**overrides: Any) -> Dict[str, Any]:
    """The low-vulnerability neighbouring member government (weight 3)."""
    return get_success_data(api_client.create_jurisdiction(f.ridge_payload(**overrides), ADMIN()))


def patch_jurisdiction(jurisdiction_id: str, **fields: Any) -> Dict[str, Any]:
    return get_success_data(
        api_client.patch_jurisdiction(jurisdiction_id, dict(fields), ADMIN())
    )


def read_jurisdiction(jurisdiction_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_jurisdiction(jurisdiction_id, ADMIN()))


# --- Hazard projections (PRD 3.2) ------------------------------------------


def create_hazard_profile(jurisdiction_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_hazard_profile(
            f.hazard_profile_payload(jurisdiction_id, **overrides), ANALYST()
        )
    )


def publish_hazard_profile(hazard_profile_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.publish_hazard_profile(hazard_profile_id, ANALYST()))


def revise_hazard_profile(hazard_profile_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api_client.revise_hazard_profile(
            hazard_profile_id, f.hazard_revision_payload(**overrides), ANALYST()
        )
    )


def create_published_profile(jurisdiction_id: str, **overrides: Any) -> Dict[str, Any]:
    """A projection recorded and then published, ready to be assessed against."""
    profile = create_hazard_profile(jurisdiction_id, **overrides)
    return publish_hazard_profile(profile["id"])


def read_hazard_profile(hazard_profile_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_hazard_profile(hazard_profile_id, ANALYST()))


# --- Lifeline assets (PRD 3.4) ---------------------------------------------


def create_asset(jurisdiction_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_asset(f.asset_payload(jurisdiction_id, **overrides), ADMIN())
    )


def patch_asset(asset_id: str, **fields: Any) -> Dict[str, Any]:
    return get_success_data(api_client.patch_asset(asset_id, dict(fields), ADMIN()))


def rank_asset(asset_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.rank_asset(asset_id, ANALYST()))


def read_asset(asset_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_asset(asset_id, ADMIN()))


# --- Vulnerability assessments (PRD 3.3) -----------------------------------


def create_assessment(hazard_profile_id: str, asset_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_assessment(
            f.assessment_payload(hazard_profile_id, asset_id, **overrides), ANALYST()
        )
    )


def assess(assessment_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.assess(assessment_id, ANALYST()))


def create_assessed_assessment(
    hazard_profile_id: str, asset_id: str, **overrides: Any
) -> Dict[str, Any]:
    row = create_assessment(hazard_profile_id, asset_id, **overrides)
    return assess(row["id"])


def read_assessment(assessment_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_assessment(assessment_id, ANALYST()))


# --- Plan update cycles (PRD 3.8) ------------------------------------------


def create_plan_cycle(**overrides: Any) -> Dict[str, Any]:
    return get_success_data(api_client.create_plan_cycle(f.plan_cycle_payload(**overrides), ADMIN()))


def open_engagement(plan_cycle_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.open_engagement(plan_cycle_id, ADMIN()))


def open_endorsement_round(plan_cycle_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.open_endorsement_round(plan_cycle_id, ADMIN()))


def close_endorsement_round(plan_cycle_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.close_endorsement_round(plan_cycle_id, ADMIN()))


def read_plan_cycle(plan_cycle_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_plan_cycle(plan_cycle_id, ADMIN()))


def read_tally(plan_cycle_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_endorsement_tally(plan_cycle_id, ADMIN()))


def create_session(plan_cycle_id: str, host_jurisdiction_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_engagement_session(
            plan_cycle_id,
            f.engagement_session_payload(host_jurisdiction_id, **overrides),
            make_jurisdiction_delegate_headers(host_jurisdiction_id),
        )
    )


def complete_session(session_id: str, host_jurisdiction_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api_client.complete_engagement_session(
            session_id,
            f.session_completion_payload(**overrides),
            make_jurisdiction_delegate_headers(host_jurisdiction_id),
        )
    )


def create_completed_session(
    plan_cycle_id: str, host_jurisdiction_id: str, completion: Optional[Dict[str, Any]] = None, **overrides: Any
) -> Dict[str, Any]:
    session = create_session(plan_cycle_id, host_jurisdiction_id, **overrides)
    return complete_session(session["id"], host_jurisdiction_id, **(completion or {}))


def read_session(session_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_engagement_session(session_id, ADMIN()))


def cast_endorsement(plan_cycle_id: str, jurisdiction_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api_client.cast_endorsement(
            plan_cycle_id,
            f.endorsement_payload(jurisdiction_id, **overrides),
            make_jurisdiction_delegate_headers(jurisdiction_id),
        )
    )


def read_endorsement(endorsement_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_endorsement(endorsement_id, ADMIN()))


# --- Adaptation projects (PRD 3.5) -----------------------------------------


def create_project(plan_cycle_id: str, jurisdiction_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_project(
            f.project_payload(plan_cycle_id, jurisdiction_id, **overrides),
            make_project_sponsor_headers(jurisdiction_id),
        )
    )


def create_retrofit_project(plan_cycle_id: str, jurisdiction_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_project(
            f.retrofit_project_payload(plan_cycle_id, jurisdiction_id, **overrides),
            make_project_sponsor_headers(jurisdiction_id),
        )
    )


def patch_project(project_id: str, jurisdiction_id: str, **fields: Any) -> Dict[str, Any]:
    return get_success_data(
        api_client.patch_project(
            project_id, dict(fields), make_project_sponsor_headers(jurisdiction_id)
        )
    )


def screen_project(project_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.screen_project(project_id, ADMIN()))


def read_project(project_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_project(project_id, ADMIN()))


def create_screened_project(plan_cycle_id: str, jurisdiction_id: str, **overrides: Any) -> Dict[str, Any]:
    project = create_project(plan_cycle_id, jurisdiction_id, **overrides)
    return screen_project(project["id"])


def create_screened_retrofit_project(
    plan_cycle_id: str, jurisdiction_id: str, **overrides: Any
) -> Dict[str, Any]:
    project = create_retrofit_project(plan_cycle_id, jurisdiction_id, **overrides)
    return screen_project(project["id"])


# --- Benefit attribution and benefit-cost cases (PRD 3.6) ------------------


def create_asset_link(
    project_id: str, jurisdiction_id: str, asset_id: str, avoided_loss_annual_cents: int, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_asset_link(
            project_id,
            f.asset_link_payload(asset_id, avoided_loss_annual_cents, **overrides),
            make_project_sponsor_headers(jurisdiction_id),
        )
    )


def read_asset_link(link_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_asset_link(link_id, ADMIN()))


def create_analysis(project_id: str, jurisdiction_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_analysis(
            project_id, f.analysis_payload(**overrides), make_project_sponsor_headers(jurisdiction_id)
        )
    )


def certify_analysis(analysis_id: str, reviewer_user_id: str = "reviewer-01") -> Dict[str, Any]:
    return get_success_data(
        api_client.certify_analysis(analysis_id, make_bca_reviewer_headers(reviewer_user_id))
    )


def reject_analysis(analysis_id: str, reviewer_user_id: str = "reviewer-01") -> Dict[str, Any]:
    return get_success_data(
        api_client.reject_analysis(analysis_id, make_bca_reviewer_headers(reviewer_user_id))
    )


def read_analysis(analysis_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_analysis(analysis_id, ADMIN()))


# --- Capital programming (PRD 3.7) -----------------------------------------


def create_capital_program(**overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_capital_program(f.capital_program_payload(**overrides), ADMIN())
    )


def read_capital_program(program_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_capital_program(program_id, ADMIN()))


def program_version(program_id: str) -> int:
    """Re-read the program purely to learn the version the next write must quote.

    PRD 2.7 makes `expected_capital_program_version` non-optional, and a cascade
    can move the version by more than one, so the value is always read rather
    than assumed.
    """
    return read_capital_program(program_id)["version"]


def allocate(program_id: str, project_id: str, allocated_cents: int, expected_version: Optional[int] = None) -> Dict[str, Any]:
    version = program_version(program_id) if expected_version is None else expected_version
    return get_success_data(
        api_client.allocate(
            program_id, f.allocation_payload(project_id, allocated_cents, version), ADMIN()
        )
    )


def grant_equity_waiver(project_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api_client.grant_equity_waiver(project_id, f.equity_waiver_payload(**overrides), EQUITY())
    )


def submit_grant(project_id: str, jurisdiction_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api_client.submit_grant(
            project_id,
            f.grant_submission_payload(**overrides),
            make_project_sponsor_headers(jurisdiction_id),
        )
    )


def award_grant(project_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.award_grant(project_id, ADMIN()))


def withdraw_project(project_id: str, jurisdiction_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.withdraw_project(project_id, make_project_sponsor_headers(jurisdiction_id))
    )


def report_indicator(project_id: str, jurisdiction_id: str, reported_value: float, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api_client.report_indicator(
            project_id,
            f.indicator_report_payload(reported_value, **overrides),
            make_project_sponsor_headers(jurisdiction_id),
        )
    )


# --- Mutual aid (PRD 3.9) --------------------------------------------------


def create_pact(host_jurisdiction_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_pact(
            f.pact_payload(host_jurisdiction_id, **overrides),
            make_jurisdiction_delegate_headers(host_jurisdiction_id),
        )
    )


def read_pact(pact_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_pact(pact_id, ADMIN()))


def pact_version(pact_id: str) -> int:
    """Re-read the pact for the version the next commitment must quote (PRD 2.7)."""
    return read_pact(pact_id)["version"]


def commit_aid(
    pact_id: str,
    requesting_jurisdiction_id: str,
    asset_id: str,
    committed_units: int,
    window_start: str,
    window_end: str,
    expected_version: Optional[int] = None,
) -> Dict[str, Any]:
    version = pact_version(pact_id) if expected_version is None else expected_version
    return get_success_data(
        api_client.create_commitment(
            pact_id,
            f.commitment_payload(
                requesting_jurisdiction_id,
                asset_id,
                committed_units,
                window_start,
                window_end,
                version,
            ),
            make_jurisdiction_delegate_headers(requesting_jurisdiction_id),
        )
    )


def release_commitment(commitment_id: str, jurisdiction_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.release_commitment(
            commitment_id, make_jurisdiction_delegate_headers(jurisdiction_id)
        )
    )


def fulfill_commitment(commitment_id: str, jurisdiction_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.fulfill_commitment(
            commitment_id, make_jurisdiction_delegate_headers(jurisdiction_id)
        )
    )


def read_commitment(commitment_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_commitment(commitment_id, ADMIN()))


# --- Logical clock (PRD 2.4) ----------------------------------------------


def set_clock(to_iso8601: str) -> Dict[str, Any]:
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN()))


# --- Composite preconditions ----------------------------------------------
#
# The workflows of PRD 3 are deeply chained: a benefit-cost case needs a screened
# project, which needs a plan cycle, and its assets need a ranked criticality,
# which needs an assessed vulnerability, which needs a published projection.  The
# builders below assemble those chains once so that each test only has to express
# the step its own rule is about.


def published_profile_context(**profile_overrides: Any) -> Dict[str, Any]:
    """Harbor plus a published downscaled projection for it."""
    harbor = create_harbor()
    profile = create_published_profile(harbor["id"], **profile_overrides)
    return {"harbor": harbor, "profile": profile}


def ranked_asset_context(
    asset_overrides: Optional[Dict[str, Any]] = None,
    assessment_overrides: Optional[Dict[str, Any]] = None,
    profile_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """A lifeline asset carried all the way to `RANKED` on a published projection."""
    context = published_profile_context(**(profile_overrides or {}))
    asset = create_asset(context["harbor"]["id"], **(asset_overrides or {}))
    assessment = create_assessed_assessment(
        context["profile"]["id"], asset["id"], **(assessment_overrides or {})
    )
    ranked = rank_asset(asset["id"])
    context.update({"asset": ranked, "assessment": assessment})
    return context


def add_ranked_asset(context: Dict[str, Any], **asset_overrides: Any) -> Dict[str, Any]:
    """Register one more asset in the same jurisdiction and rank it too."""
    asset = create_asset(context["harbor"]["id"], **asset_overrides)
    create_assessed_assessment(context["profile"]["id"], asset["id"])
    return rank_asset(asset["id"])


def screened_levee_context(
    cycle_overrides: Optional[Dict[str, Any]] = None,
    project_overrides: Optional[Dict[str, Any]] = None,
    asset_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """A ranked asset plus a plan cycle holding a `SCREENED_IN` PROTECT project."""
    context = ranked_asset_context(asset_overrides=asset_overrides)
    cycle = create_plan_cycle(**(cycle_overrides or {}))
    project = create_screened_project(
        cycle["id"], context["harbor"]["id"], **(project_overrides or {})
    )
    context.update({"cycle": cycle, "project": project})
    return context


def screened_retrofit_context(
    cycle_overrides: Optional[Dict[str, Any]] = None,
    project_overrides: Optional[Dict[str, Any]] = None,
    asset_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """The same chain for the accommodate-family retrofit project."""
    context = ranked_asset_context(asset_overrides=asset_overrides)
    cycle = create_plan_cycle(**(cycle_overrides or {}))
    project = create_screened_retrofit_project(
        cycle["id"], context["harbor"]["id"], **(project_overrides or {})
    )
    context.update({"cycle": cycle, "project": project})
    return context


def certified_levee_context(
    avoided_loss_annual_cents: int = 3333333,
    method: str = "ANNUALIZED_EQUIVALENT",
    cycle_overrides: Optional[Dict[str, Any]] = None,
    project_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """A PROTECT project with one attributed asset and a certified analysis."""
    context = screened_levee_context(
        cycle_overrides=cycle_overrides, project_overrides=project_overrides
    )
    harbor_id = context["harbor"]["id"]
    link = create_asset_link(
        context["project"]["id"],
        harbor_id,
        context["asset"]["id"],
        avoided_loss_annual_cents,
        benefit_reaches_disadvantaged=True,
    )
    analysis = create_analysis(context["project"]["id"], harbor_id, method=method)
    certified = certify_analysis(analysis["id"])
    context.update({"link": link, "analysis": certified})
    return context


def certified_retrofit_context(
    avoided_loss_annual_cents: int = 2118960,
    method: str = "ANNUALIZED_EQUIVALENT",
    cycle_overrides: Optional[Dict[str, Any]] = None,
    project_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """An ACCOMMODATE project with one attributed asset and a certified analysis."""
    context = screened_retrofit_context(
        cycle_overrides=cycle_overrides, project_overrides=project_overrides
    )
    harbor_id = context["harbor"]["id"]
    link = create_asset_link(
        context["project"]["id"],
        harbor_id,
        context["asset"]["id"],
        avoided_loss_annual_cents,
        benefit_reaches_disadvantaged=True,
    )
    analysis = create_analysis(context["project"]["id"], harbor_id, method=method)
    certified = certify_analysis(analysis["id"])
    context.update({"link": link, "analysis": certified})
    return context


def add_certified_retrofit_project(
    context: Dict[str, Any],
    name: str,
    avoided_loss_annual_cents: int = 2118960,
    method: str = "ANNUALIZED_EQUIVALENT",
    **project_overrides: Any,
) -> Dict[str, Any]:
    """A second certified project in the same cycle, linked to the same asset."""
    harbor_id = context["harbor"]["id"]
    project = create_screened_retrofit_project(
        context["cycle"]["id"], harbor_id, name=name, **project_overrides
    )
    create_asset_link(
        project["id"],
        harbor_id,
        context["asset"]["id"],
        avoided_loss_annual_cents,
        benefit_reaches_disadvantaged=True,
    )
    analysis = create_analysis(project["id"], harbor_id, method=method)
    certify_analysis(analysis["id"])
    return read_project(project["id"])


def two_certified_retrofit_projects(
    authorized_cents: int = 60000000,
    equity_target_bps: int = 4000,
    avoided_loss_annual_cents: int = 2118960,
) -> Dict[str, Any]:
    """Two fundable retrofit projects and an open capital program to fund them."""
    context = certified_retrofit_context(
        avoided_loss_annual_cents=avoided_loss_annual_cents,
        project_overrides={"name": "Harbor Pump Retrofit A"},
    )
    project_b = add_certified_retrofit_project(
        context,
        name="Harbor Pump Retrofit B",
        avoided_loss_annual_cents=avoided_loss_annual_cents,
    )
    program = create_capital_program(
        authorized_cents=authorized_cents, equity_target_bps=equity_target_bps
    )
    context["project_a"] = read_project(context["project"]["id"])
    context["project_b"] = project_b
    context["program"] = program
    return context


def aid_context(
    resource_class: str = "PUMPS",
    pledged_units: int = 10,
    max_concurrent_commitments: int = 3,
    asset_overrides: Optional[Dict[str, Any]] = None,
    **pact_overrides: Any,
) -> Dict[str, Any]:
    """Two member governments, a shared lifeline asset, and Ridge's open pledge.

    Ridge hosts the pledge and Harbor requests the aid, because PRD 3.9 forbids a
    member from drawing on its own pledge.
    """
    harbor = create_harbor()
    ridge = create_ridge()
    shared_asset = create_asset(harbor["id"], **(asset_overrides or {}))
    pact = create_pact(
        ridge["id"],
        resource_class=resource_class,
        pledged_units=pledged_units,
        max_concurrent_commitments=max_concurrent_commitments,
        **pact_overrides,
    )
    return {"harbor": harbor, "ridge": ridge, "asset": shared_asset, "pact": pact}
