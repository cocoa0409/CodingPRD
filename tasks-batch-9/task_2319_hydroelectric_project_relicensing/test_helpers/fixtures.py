"""Composite setup helpers.

Every helper builds its preconditions from scratch through documented endpoints
only, because each test starts against an empty database. Setup calls use the
lenient `get_success_data` validator so a broken precondition surfaces as a
setup failure rather than as a confusing assertion failure inside a test.

Party-backed callers (`AgencyReviewer`, `Stakeholder`) are always addressed with
`make_agency_reviewer_headers(...)` / `make_stakeholder_headers(...)` carrying
the exact `contact_user_id` that was registered on the party, never with a
generic shared header.
"""
from typing import Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .constants import DEFAULT_CLOCK_UTC, STANDARD_WQC_CONDITION
from .factories import (
    annual_report_payload,
    application_payload,
    comment_payload,
    condition_payload,
    dam_payload,
    measure_payload,
    party_payload,
    project_payload,
    schedule_payload,
    settlement_payload,
    signature_payload,
    site_payload,
    study_payload,
    study_plan_payload,
    water_quality_certification_payload,
)
from .test_users import (
    TEST_USERS,
    U_AGENCY,
    U_LICENSEE_A,
    U_LICENSEE_B,
    U_LICENSEE_REPORT,
    U_STATE_CERTIFIER,
    make_agency_reviewer_headers,
    make_licensee_headers,
    make_stakeholder_headers,
    make_state_certifier_headers,
)

REGULATOR = TEST_USERS["regulator_headers"]
LICENSEE = TEST_USERS["licensee_headers"]
STATE_CERTIFIER = TEST_USERS["state_certifier_headers"]


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
def set_clock(to_iso8601: str = DEFAULT_CLOCK_UTC) -> dict:
    """Move the server logical clock. Returns the clock payload."""
    return get_success_data(api_client.set_clock(to_iso8601, REGULATOR))


def read_clock() -> dict:
    return get_success_data(api_client.get_clock(REGULATOR))


# ---------------------------------------------------------------------------
# Single-step primitives
# ---------------------------------------------------------------------------
def new_project(**overrides) -> dict:
    return get_success_data(api_client.create_project(project_payload(**overrides), REGULATOR))


def read_project(project_id: str, headers: dict = REGULATOR) -> dict:
    return get_success_data(api_client.get_project(project_id, headers))


def project_version(project_id: str) -> int:
    return read_project(project_id)["version"]


def patch_project(project_id: str, **payload) -> dict:
    return get_success_data(api_client.patch_project(project_id, payload, REGULATOR))


def file_pad(project_id: str, user_id: str = U_LICENSEE_A, filing_note: str = "PAD") -> dict:
    return get_success_data(
        api_client.file_pre_application_document(
            project_id, {"filing_note": filing_note}, make_licensee_headers(user_id)
        )
    )


def run_sweep(project_id: str) -> dict:
    return get_success_data(api_client.run_compliance_sweep(project_id, REGULATOR))


def new_dam(project_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_dam(dam_payload(project_id, **overrides), LICENSEE)
    )


def new_site(project_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_site(site_payload(project_id, **overrides), LICENSEE)
    )


def new_study_plan(project_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_study_plan(study_plan_payload(project_id, **overrides), LICENSEE)
    )


def read_study_plan(study_plan_id: str) -> dict:
    return get_success_data(api_client.get_study_plan(study_plan_id, REGULATOR))


def submit_plan(study_plan_id: str, submission_note: str = "plan for review") -> dict:
    return get_success_data(
        api_client.submit_study_plan(
            study_plan_id, {"submission_note": submission_note}, LICENSEE
        )
    )


def decide_plan(
    study_plan_id: str,
    determination: str,
    agency_user_id: str = U_AGENCY,
    **extra,
) -> dict:
    payload = {"determination": determination}
    payload.update(extra)
    return get_success_data(
        api_client.decide_study_plan(
            study_plan_id, payload, make_agency_reviewer_headers(agency_user_id)
        )
    )


def new_study(study_plan_id: str, site_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_study(study_payload(study_plan_id, site_id, **overrides), LICENSEE)
    )


def read_study(study_id: str) -> dict:
    return get_success_data(api_client.get_study(study_id, REGULATOR))


def move_fieldwork(study_id: str, action: str, user_id: str = U_LICENSEE_A) -> dict:
    return get_success_data(
        api_client.study_fieldwork(study_id, {"action": action}, make_licensee_headers(user_id))
    )


def report_study(study_id: str, user_id: str = U_LICENSEE_REPORT) -> dict:
    return get_success_data(
        api_client.submit_study_report(
            study_id, {"report_note": "final report"}, make_licensee_headers(user_id)
        )
    )


def decide_study_review(study_id: str, decision: str, agency_user_id: str = U_AGENCY) -> dict:
    return get_success_data(
        api_client.decide_study_review(
            study_id, {"decision": decision}, make_agency_reviewer_headers(agency_user_id)
        )
    )


def register_party(project_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_party(party_payload(project_id, **overrides), REGULATOR)
    )


def register_parties(project_id: str, specs: List[dict]) -> List[dict]:
    return [register_party(project_id, **spec) for spec in specs]


def leave_comment(
    study_plan_id: str,
    party: dict,
    role: str = "AgencyReviewer",
    **overrides,
) -> dict:
    """Post a consultation comment as the party's registered contact user."""
    user_id = party["contact_user_id"]
    headers = (
        make_agency_reviewer_headers(user_id)
        if role == "AgencyReviewer"
        else make_stakeholder_headers(user_id)
    )
    payload = comment_payload(study_plan_id, party["id"], **overrides)
    return get_success_data(api_client.create_comment(payload, headers))


def read_comment(comment_id: str) -> dict:
    return get_success_data(api_client.get_comment(comment_id, REGULATOR))


def resolve_comment(comment_id: str, disposition: str, **extra) -> dict:
    payload = {"disposition": disposition}
    payload.update(extra)
    return get_success_data(api_client.resolve_comment(comment_id, payload, LICENSEE))


def new_settlement(project_id: str, expected_project_version: Optional[int] = None, **overrides) -> dict:
    version = (
        expected_project_version
        if expected_project_version is not None
        else project_version(project_id)
    )
    return get_success_data(
        api_client.create_settlement(
            settlement_payload(project_id, version, **overrides), LICENSEE
        )
    )


def circulate_settlement(settlement_id: str) -> dict:
    return get_success_data(
        api_client.circulate_settlement(
            settlement_id, {"circulation_note": "circulated for signature"}, LICENSEE
        )
    )


def sign_settlement(settlement_id: str, party: dict, position: str = "SUPPORT") -> dict:
    """Sign as the party's registered contact user, with the party's own role."""
    user_id = party["contact_user_id"]
    headers = (
        make_agency_reviewer_headers(user_id)
        if party["party_type"] == "AGENCY"
        else make_stakeholder_headers(user_id)
    )
    return get_success_data(
        api_client.create_signature(
            signature_payload(settlement_id, party["id"], position=position), headers
        )
    )


def read_settlement(settlement_id: str) -> dict:
    return get_success_data(api_client.get_settlement(settlement_id, REGULATOR))


def read_signature(signature_id: str) -> dict:
    return get_success_data(api_client.get_signature(signature_id, REGULATOR))


def tally_settlement(settlement_id: str, intended_outcome: str) -> dict:
    return get_success_data(
        api_client.tally_settlement(
            settlement_id, {"intended_outcome": intended_outcome}, LICENSEE
        )
    )


def withdraw_settlement(settlement_id: str, withdrawal_reason: str = "parties re-opened talks") -> dict:
    return get_success_data(
        api_client.withdraw_settlement(
            settlement_id, {"withdrawal_reason": withdrawal_reason}, LICENSEE
        )
    )


def request_certification(project_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_water_quality_certification(
            water_quality_certification_payload(project_id, **overrides), LICENSEE
        )
    )


def certify_with_conditions(
    wqc_id: str,
    conditions: Optional[List[dict]] = None,
    user_id: str = U_STATE_CERTIFIER,
) -> dict:
    payload = {
        "decision": "ISSUE_WITH_CONDITIONS",
        "conditions": conditions if conditions is not None else [dict(STANDARD_WQC_CONDITION)],
    }
    return get_success_data(
        api_client.decide_water_quality_certification(
            wqc_id, payload, make_state_certifier_headers(user_id)
        )
    )


def deny_certification(wqc_id: str, denial_reason: str = "state standards not met") -> dict:
    return get_success_data(
        api_client.decide_water_quality_certification(
            wqc_id, {"decision": "DENY", "denial_reason": denial_reason}, STATE_CERTIFIER
        )
    )


def new_measure(project_id: str, user_id: str = U_LICENSEE_A, **overrides) -> dict:
    return get_success_data(
        api_client.create_measure(
            measure_payload(project_id, **overrides), make_licensee_headers(user_id)
        )
    )


def read_measure(measure_id: str) -> dict:
    return get_success_data(api_client.get_measure(measure_id, REGULATOR))


def record_definitive_estimate(measure_id: str, user_id: str = U_LICENSEE_B, **payload) -> dict:
    body = {"estimate_note": "definitive estimate"}
    body.update(payload)
    return get_success_data(
        api_client.record_definitive_estimate(measure_id, body, make_licensee_headers(user_id))
    )


def list_measures(project_id: str, **params) -> List[dict]:
    query = {"project_id": project_id}
    query.update(params)
    rows, _ = validate_paginated(api_client.list_measures(REGULATOR, params=query))
    return rows


def file_application(
    project_id: str,
    expected_project_version: Optional[int] = None,
    **overrides,
) -> dict:
    version = (
        expected_project_version
        if expected_project_version is not None
        else project_version(project_id)
    )
    return get_success_data(
        api_client.create_application(
            application_payload(project_id, version, **overrides), LICENSEE
        )
    )


def read_application(application_id: str) -> dict:
    return get_success_data(api_client.get_application(application_id, REGULATOR))


def advance_environmental_review(application_id: str, target_stage: str) -> dict:
    return get_success_data(
        api_client.advance_environmental_review(
            application_id, {"target_stage": target_stage}, REGULATOR
        )
    )


def raise_deficiency(application_id: str, deficiency_note: str = "update the cost exhibit") -> dict:
    return get_success_data(
        api_client.raise_deficiency(
            application_id, {"deficiency_note": deficiency_note}, REGULATOR
        )
    )


def cure_application(application_id: str, cure_note: str = "exhibit refiled") -> dict:
    return get_success_data(
        api_client.cure_application(application_id, {"cure_note": cure_note}, LICENSEE)
    )


def issue_order(application_id: str, order_number: str) -> dict:
    return get_success_data(
        api_client.issue_order(application_id, {"order_number": order_number}, REGULATOR)
    )


def read_order(order_id: str) -> dict:
    return get_success_data(api_client.get_order(order_id, REGULATOR))


def file_annual_report(order_id: str, report_basis: str, period_year: int) -> dict:
    return get_success_data(
        api_client.file_annual_report(
            order_id, annual_report_payload(report_basis, period_year), LICENSEE
        )
    )


def list_obligations(order_id: str, **params) -> List[dict]:
    query = {"order_id": order_id, "limit": 100}
    query.update(params)
    rows, _ = validate_paginated(api_client.list_obligations(REGULATOR, params=query))
    return rows


def read_obligation(obligation_id: str) -> dict:
    return get_success_data(api_client.get_obligation(obligation_id, REGULATOR))


def schedule_obligation(obligation_id: str, start: str, end: str) -> dict:
    return get_success_data(
        api_client.schedule_obligation(obligation_id, schedule_payload(start, end), LICENSEE)
    )


def certify_obligation(obligation_id: str, user_id: str = U_LICENSEE_A) -> dict:
    return get_success_data(
        api_client.certify_obligation(
            obligation_id, {"certification_note": "work complete"}, make_licensee_headers(user_id)
        )
    )


# ---------------------------------------------------------------------------
# Tier 1 / Tier 2: stage progression and hierarchy
# ---------------------------------------------------------------------------
def setup_pad_filed_project(clock: str = DEFAULT_CLOCK_UTC, **project_overrides) -> dict:
    """Register a project and file its pre-application document.

    Returns {"project": <project after PAD filing>}.
    """
    set_clock(clock)
    project = new_project(**project_overrides)
    project = file_pad(project["id"])
    return {"project": project}


def setup_study_phase_project(
    clock: str = DEFAULT_CLOCK_UTC,
    sites: Optional[List[dict]] = None,
    dams: Optional[List[dict]] = None,
    plan_title: str = "Study Plan 1",
    **project_overrides,
) -> dict:
    """Project past PAD filing with a DRAFT study plan, plus any sites and dams.

    Returns {"project", "plan", "sites" (list), "dams" (list)}.
    """
    set_clock(clock)
    project = new_project(**project_overrides)
    dam_rows = [new_dam(project["id"], **spec) for spec in (dams or [])]
    site_rows = [new_site(project["id"], **spec) for spec in (sites or [])]
    file_pad(project["id"])
    plan = new_study_plan(project["id"], plan_title=plan_title)
    return {
        "project": read_project(project["id"]),
        "plan": plan,
        "sites": site_rows,
        "dams": dam_rows,
    }


def setup_plan_under_agency_review(
    clock: str = DEFAULT_CLOCK_UTC,
    study_overrides: Optional[dict] = None,
    site_overrides: Optional[dict] = None,
    **project_overrides,
) -> dict:
    """Project with one site, one study and the plan submitted for agency review.

    Returns {"project", "plan", "site", "study"}.
    """
    ctx = setup_study_phase_project(
        clock=clock, sites=[site_overrides or {}], **project_overrides
    )
    site = ctx["sites"][0]
    study = new_study(ctx["plan"]["id"], site["id"], **(study_overrides or {}))
    plan = submit_plan(ctx["plan"]["id"])
    return {
        "project": read_project(ctx["project"]["id"]),
        "plan": plan,
        "site": site,
        "study": study,
    }


def setup_agency_party(project_id: str, **overrides) -> dict:
    """Register the conditioning AGENCY party whose contact user reviews studies."""
    spec = {
        "party_name": "State Fish Agency",
        "party_type": "AGENCY",
        "has_conditioning_authority": True,
        "vote_weight": 1,
        "contact_user_id": U_AGENCY,
    }
    spec.update(overrides)
    return register_party(project_id, **spec)


# ---------------------------------------------------------------------------
# Tier 3: full lifecycle shortcuts
# ---------------------------------------------------------------------------
def setup_approved_study_plan(
    clock: str = DEFAULT_CLOCK_UTC,
    study_overrides: Optional[dict] = None,
    site_overrides: Optional[dict] = None,
    dams: Optional[List[dict]] = None,
    reporter_user_id: str = U_LICENSEE_REPORT,
    **project_overrides,
) -> dict:
    """Walk a project to an APPROVED study plan with an ACCEPTED study.

    Chain: register project, sites and dams, file the pre-application document,
    open a study plan, attach one study, submit the plan, run the fieldwork to
    COMPLETED, file the study report, register the conditioning agency party,
    accept the study and approve the plan.

    Returns {"project", "plan", "site", "study", "agency_party", "dams"}.
    """
    ctx = setup_study_phase_project(
        clock=clock, sites=[site_overrides or {}], dams=dams, **project_overrides
    )
    project_id = ctx["project"]["id"]
    site = ctx["sites"][0]
    study = new_study(ctx["plan"]["id"], site["id"], **(study_overrides or {}))
    submit_plan(ctx["plan"]["id"])
    move_fieldwork(study["id"], "START")
    move_fieldwork(study["id"], "COMPLETE")
    report_study(study["id"], user_id=reporter_user_id)
    agency_party = setup_agency_party(project_id)
    study = decide_study_review(study["id"], "ACCEPT")
    plan = decide_plan(ctx["plan"]["id"], "APPROVE")
    return {
        "project": read_project(project_id),
        "plan": plan,
        "site": site,
        "study": study,
        "agency_party": agency_party,
        "dams": ctx["dams"],
    }


def setup_certification_conditioned_project(
    conditions: Optional[List[dict]] = None,
    definitive: bool = False,
    definitive_user_id: str = U_LICENSEE_B,
    **kwargs,
) -> dict:
    """An APPROVED-plan project whose certification has been issued with conditions.

    Each condition becomes an INCLUDED measure priced at a PRELIMINARY estimate;
    with `definitive=True` every condition measure is then re-priced by a second
    licensee user so the definitive estimate is on file.

    Returns the `setup_approved_study_plan` context plus {"wqc",
    "condition_measures"}.
    """
    ctx = setup_approved_study_plan(**kwargs)
    project_id = ctx["project"]["id"]
    wqc = request_certification(project_id)
    wqc = certify_with_conditions(wqc["id"], conditions=conditions)
    measures = list_measures(project_id, source="WQC_CONDITION")
    if definitive:
        measures = [
            record_definitive_estimate(measure["id"], user_id=definitive_user_id)
            for measure in measures
        ]
    ctx.update(
        {
            "project": read_project(project_id),
            "wqc": wqc,
            "condition_measures": measures,
        }
    )
    return ctx


def setup_application_under_review(
    ea_stage: str = "SCOPING",
    conditions: Optional[List[dict]] = None,
    definitive: bool = True,
    **kwargs,
) -> dict:
    """A filed ORIGINAL_RELICENSE application advanced to `ea_stage`.

    `ea_stage` may be NOT_STARTED, SCOPING, DRAFT_EA or FINAL_EA; the stages are
    walked one step at a time in that order.

    Returns the certification context plus {"application"}.
    """
    ctx = setup_certification_conditioned_project(
        conditions=conditions, definitive=definitive, **kwargs
    )
    project_id = ctx["project"]["id"]
    application = file_application(project_id)
    for stage in ("SCOPING", "DRAFT_EA", "FINAL_EA"):
        if ea_stage == "NOT_STARTED":
            break
        application = advance_environmental_review(application["id"], stage)
        if stage == ea_stage:
            break
    ctx.update({"project": read_project(project_id), "application": application})
    return ctx


def setup_licensed_project(
    order_number: str = "ORD-1",
    conditions: Optional[List[dict]] = None,
    **kwargs,
) -> dict:
    """Walk a project all the way to an EFFECTIVE license order.

    Continues `setup_application_under_review` at FINAL_EA by issuing the order,
    then returns its generated obligation set.

    Returns the application context plus {"order", "obligations"}.
    """
    ctx = setup_application_under_review(
        ea_stage="FINAL_EA", conditions=conditions, definitive=True, **kwargs
    )
    order = issue_order(ctx["application"]["id"], order_number)
    ctx.update(
        {
            "project": read_project(ctx["project"]["id"]),
            "application": read_application(ctx["application"]["id"]),
            "order": order,
            "obligations": list_obligations(order["id"]),
        }
    )
    return ctx


def obligation_of_type(obligations: List[dict], obligation_type: str) -> dict:
    """Pick the single obligation of a given type out of a generated article set."""
    matches = [o for o in obligations if o["obligation_type"] == obligation_type]
    assert len(matches) == 1, (
        f"expected exactly one {obligation_type} obligation, got {len(matches)}"
    )
    return matches[0]


# ---------------------------------------------------------------------------
# Tier 4: settlement / threshold targeting
# ---------------------------------------------------------------------------
def setup_circulated_settlement(
    party_specs: Optional[List[dict]] = None,
    settlement_measures: Optional[List[dict]] = None,
    approve_plan: bool = True,
    clock: str = DEFAULT_CLOCK_UTC,
    **kwargs,
) -> dict:
    """A CIRCULATED settlement with a registered party roster ready to sign.

    `party_specs` entries are `POST /relicensing/parties` bodies; the AGENCY
    party from `setup_approved_study_plan` is always present and is the first
    entry of the returned roster. `settlement_measures` entries are
    `POST /relicensing/pme-measures` bodies created against the settlement, so
    they start PROPOSED.

    Returns the plan context plus {"parties", "settlement", "measures"}.
    """
    if approve_plan:
        ctx = setup_approved_study_plan(clock=clock, **kwargs)
    else:
        ctx = setup_plan_under_agency_review(clock=clock, **kwargs)
        ctx["agency_party"] = setup_agency_party(ctx["project"]["id"])
    project_id = ctx["project"]["id"]
    parties = [ctx["agency_party"]] + register_parties(project_id, party_specs or [])
    settlement = new_settlement(project_id)
    measures = [
        new_measure(
            project_id,
            source="SETTLEMENT",
            settlement_id=settlement["id"],
            **spec,
        )
        for spec in (settlement_measures or [])
    ]
    settlement = circulate_settlement(settlement["id"])
    ctx.update(
        {
            "project": read_project(project_id),
            "parties": parties,
            "settlement": settlement,
            "measures": measures,
        }
    )
    return ctx


def sign_roster(settlement_id: str, positions: List[tuple]) -> List[dict]:
    """Sign a circulated settlement for each `(party, position)` pairing."""
    return [
        sign_settlement(settlement_id, party, position=position)
        for party, position in positions
    ]
