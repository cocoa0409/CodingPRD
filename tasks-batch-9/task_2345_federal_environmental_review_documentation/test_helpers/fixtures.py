"""Composite setup helpers.

The harness restarts the API server before every individual test, so each test
begins against an empty database. Everything a test needs must therefore be
built from scratch through the declared endpoints; these helpers do that, from
single-step wrappers up to whole review chains carried to signature and remand.

All setup calls go through ``get_success_data`` so a broken precondition fails
loudly at the setup step rather than as a confusing assertion later.
"""
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import api_client
from .test_users import (
    DECIDING_OFFICIAL_USER_ID,
    NEPA_COORDINATOR_USER_ID,
    OBJECTION_REVIEWING_OFFICER_USER_ID,
    POLICY_ADMIN_HEADERS,
    NEPA_COORDINATOR_HEADERS,
    PUBLIC_COMMENTER_HEADERS,
    RESOURCE_SPECIALIST_HEADERS,
    REVIEWING_OFFICIAL_HEADERS,
    make_agency_liaison_headers,
    make_deciding_official_headers,
    make_nepa_coordinator_headers,
    make_objection_reviewing_officer_headers,
)

Ctx = Dict[str, Any]


# ==========================================================================
# Tier 1 — single-step wrappers
# ==========================================================================

def set_clock(current_utc: str) -> dict:
    """Move the server's logical clock (PRD 2.7)."""
    return get_success_data(api_client.set_clock(current_utc, POLICY_ADMIN_HEADERS))


def create_office(**overrides) -> dict:
    return get_success_data(
        api_client.create_review_office(f.review_office_payload(**overrides),
                                        POLICY_ADMIN_HEADERS)
    )


def create_agency(**overrides) -> dict:
    return get_success_data(
        api_client.create_agency(f.agency_payload(**overrides), POLICY_ADMIN_HEADERS)
    )


def create_action(office_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_proposed_action(
            f.proposed_action_payload(office_id, **overrides), NEPA_COORDINATOR_HEADERS
        )
    )


def read_action(action_id: str) -> dict:
    return get_success_data(
        api_client.get_proposed_action(action_id, NEPA_COORDINATOR_HEADERS)
    )


def read_office(office_id: str) -> dict:
    return get_success_data(api_client.get_review_office(office_id, POLICY_ADMIN_HEADERS))


def read_agency(agency_id: str) -> dict:
    return get_success_data(api_client.get_agency(agency_id, POLICY_ADMIN_HEADERS))


def read_document(document_id: str) -> dict:
    return get_success_data(api_client.get_document(document_id, NEPA_COORDINATOR_HEADERS))


def read_decision(decision_id: str) -> dict:
    return get_success_data(api_client.get_decision(decision_id, NEPA_COORDINATOR_HEADERS))


def read_analysis(analysis_id: str) -> dict:
    return get_success_data(
        api_client.get_resource_analysis(analysis_id, RESOURCE_SPECIALIST_HEADERS)
    )


def read_alternative(alternative_id: str) -> dict:
    return get_success_data(
        api_client.get_alternative(alternative_id, NEPA_COORDINATOR_HEADERS)
    )


def read_scoping_period(period_id: str) -> dict:
    return get_success_data(
        api_client.get_scoping_period(period_id, NEPA_COORDINATOR_HEADERS)
    )


def read_issue(issue_id: str) -> dict:
    return get_success_data(api_client.get_issue(issue_id, NEPA_COORDINATOR_HEADERS))


def read_consultation(consultation_id: str) -> dict:
    return get_success_data(
        api_client.get_consultation(consultation_id, NEPA_COORDINATOR_HEADERS)
    )


def read_mitigation(mitigation_id: str) -> dict:
    return get_success_data(
        api_client.get_mitigation(mitigation_id, NEPA_COORDINATOR_HEADERS)
    )


def read_objection(objection_id: str) -> dict:
    return get_success_data(
        api_client.get_objection(objection_id, NEPA_COORDINATOR_HEADERS)
    )


def read_statement(statement_id: str) -> dict:
    return get_success_data(
        api_client.get_purpose_need_statement(statement_id, NEPA_COORDINATOR_HEADERS)
    )


def read_record_entries(action_id: str, limit: int = 100) -> List[dict]:
    response = api_client.list_record_entries(
        action_id, NEPA_COORDINATOR_HEADERS, params={"limit": limit}
    )
    get_success_data(response)
    return response.json()["data"]


def submit_screen(action_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.submit_ec_screen(action_id, f.ec_screen_payload(**overrides),
                                    NEPA_COORDINATOR_HEADERS)
    )


def adjudicate_screen(screen_id: str, disposition: str, **overrides) -> dict:
    return get_success_data(
        api_client.adjudicate_ec_screen(
            screen_id, f.ec_adjudication_payload(disposition, **overrides),
            REVIEWING_OFFICIAL_HEADERS,
        )
    )


def resubmit_screen(screen_id: str, findings: List[dict]) -> dict:
    return get_success_data(
        api_client.resubmit_ec_screen(screen_id, {"findings": findings},
                                      NEPA_COORDINATOR_HEADERS)
    )


def classify(action_id: str) -> dict:
    return get_success_data(
        api_client.classify_proposed_action(action_id, NEPA_COORDINATOR_HEADERS)
    )


def draft_purpose_need(action_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_purpose_need_statement(
            action_id, f.purpose_need_payload(**overrides), NEPA_COORDINATOR_HEADERS
        )
    )


def adopt_purpose_need(statement_id: str, action_id: str,
                       expected_action_version: Optional[int] = None) -> dict:
    if expected_action_version is None:
        expected_action_version = read_action(action_id)["version"]
    return get_success_data(
        api_client.adopt_purpose_need_statement(
            statement_id, f.adopt_payload(expected_action_version),
            REVIEWING_OFFICIAL_HEADERS,
        )
    )


def open_scoping_period(action_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_scoping_period(
            action_id, f.scoping_period_payload(**overrides), NEPA_COORDINATOR_HEADERS
        )
    )


def close_scoping_period(period_id: str) -> dict:
    return get_success_data(
        api_client.close_scoping_period(period_id, NEPA_COORDINATOR_HEADERS)
    )


def record_issue(action_id: str, scoping_period_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_issue(
            action_id, f.issue_payload(scoping_period_id, **overrides),
            NEPA_COORDINATOR_HEADERS,
        )
    )


def create_alternative(action_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_alternative(
            f.alternative_payload(action_id, **overrides), NEPA_COORDINATOR_HEADERS
        )
    )


def screen_alternative(alternative_id: str, decision: str) -> dict:
    return get_success_data(
        api_client.screen_alternative(
            alternative_id, f.screen_alternative_payload(decision),
            REVIEWING_OFFICIAL_HEADERS,
        )
    )


def open_consultation(action_id: str, agency_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_consultation(
            f.consultation_payload(action_id, agency_id, **overrides),
            NEPA_COORDINATOR_HEADERS,
        )
    )


def respond_consultation(consultation_id: str, agency_id: str, outcome: str,
                         **overrides) -> dict:
    """Respond as the liaison of ``agency_id`` — the acting agency's own id is
    the caller's ``X-User-ID`` (PRD 2.1)."""
    return get_success_data(
        api_client.respond_to_consultation(
            consultation_id, f.consultation_response_payload(outcome, **overrides),
            make_agency_liaison_headers(agency_id),
        )
    )


def withdraw_consultation(consultation_id: str) -> dict:
    return get_success_data(
        api_client.respond_to_consultation(
            consultation_id, f.consultation_response_payload("WITHDRAWN"),
            NEPA_COORDINATOR_HEADERS,
        )
    )


def add_baseline_entry(action_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_cumulative_action(
            action_id, f.cumulative_action_payload(**overrides),
            RESOURCE_SPECIALIST_HEADERS,
        )
    )


def open_analysis(action_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_resource_analysis(
            action_id, f.resource_analysis_payload(**overrides),
            RESOURCE_SPECIALIST_HEADERS,
        )
    )


def finalize_analysis(analysis_id: str, basis: str = "UNMITIGATED") -> dict:
    return get_success_data(
        api_client.finalize_resource_analysis(
            analysis_id, f.finalize_analysis_payload(basis), RESOURCE_SPECIALIST_HEADERS
        )
    )


def reopen_analysis(analysis_id: str) -> dict:
    return get_success_data(
        api_client.reopen_resource_analysis(analysis_id, RESOURCE_SPECIALIST_HEADERS)
    )


def create_document(action_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_document(action_id, f.document_payload(**overrides),
                                   NEPA_COORDINATOR_HEADERS)
    )


def publish_document(document_id: str, comment_period_end_at: str) -> dict:
    return get_success_data(
        api_client.publish_document(
            document_id, f.publish_document_payload(comment_period_end_at),
            NEPA_COORDINATOR_HEADERS,
        )
    )


def submit_comment(document_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_comment(f.comment_payload(document_id, **overrides),
                                  PUBLIC_COMMENTER_HEADERS)
    )


def close_comment_period(document_id: str) -> dict:
    return get_success_data(
        api_client.close_comment_period(document_id, NEPA_COORDINATOR_HEADERS)
    )


def respond_comment(comment_id: str, response_category: str = "ANALYSIS_REVISED",
                    **overrides) -> dict:
    return get_success_data(
        api_client.respond_to_comment(
            comment_id, f.comment_response_payload(response_category, **overrides),
            NEPA_COORDINATOR_HEADERS,
        )
    )


def finalize_document(document_id: str) -> dict:
    return get_success_data(
        api_client.finalize_document(document_id, NEPA_COORDINATOR_HEADERS)
    )


def draft_decision(action_id: str, selected_alternative_id: str,
                   decision_type: str = "MITIGATED_FONSI",
                   prepared_by_user_id: str = NEPA_COORDINATOR_USER_ID,
                   **overrides) -> dict:
    return get_success_data(
        api_client.create_decision(
            f.decision_payload(action_id, selected_alternative_id, decision_type,
                               **overrides),
            make_nepa_coordinator_headers(prepared_by_user_id),
        )
    )


def attach_mitigation(decision_id: str, source_analysis_id: str,
                      expected_decision_version: Optional[int] = None,
                      **overrides) -> dict:
    if expected_decision_version is None:
        expected_decision_version = read_decision(decision_id)["version"]
    return get_success_data(
        api_client.add_mitigation(
            decision_id,
            f.mitigation_payload(source_analysis_id, expected_decision_version,
                                 **overrides),
            NEPA_COORDINATOR_HEADERS,
        )
    )


def sign_decision(decision_id: str,
                  signer_user_id: str = DECIDING_OFFICIAL_USER_ID) -> dict:
    return get_success_data(
        api_client.sign_decision(decision_id,
                                 make_deciding_official_headers(signer_user_id))
    )


def file_objection(decision_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.file_objection(decision_id, f.objection_payload(**overrides),
                                  PUBLIC_COMMENTER_HEADERS)
    )


def resolve_objection(objection_id: str, disposition: str,
                      resolver_user_id: str = OBJECTION_REVIEWING_OFFICER_USER_ID,
                      **overrides) -> dict:
    return get_success_data(
        api_client.resolve_objection(
            objection_id, f.resolve_objection_payload(disposition, **overrides),
            make_objection_reviewing_officer_headers(resolver_user_id),
        )
    )


def certify_record(decision_id: str) -> dict:
    return get_success_data(
        api_client.certify_record(decision_id, REVIEWING_OFFICIAL_HEADERS)
    )


# ==========================================================================
# Canonical fixture data
# ==========================================================================

#: The cleared screen used throughout: only the endangered-species circumstance
#: is present, and its severity of 2 sits below the office trigger threshold.
CLEARED_SCREEN_FINDINGS = [
    f.ec_finding("EC_HISTORIC", False, 0, "No historic properties in the action area"),
    f.ec_finding("EC_ENDANGERED_SPECIES", True, 2,
                 "Lynx transit habitat, discountable effects"),
    f.ec_finding("EC_WETLAND", False, 0, "No wetlands mapped"),
]

#: A screen on which no circumstance is present at all.
ALL_ABSENT_SCREEN_FINDINGS = [
    f.ec_finding("EC_HISTORIC", False, 0, "No historic properties in the action area"),
    f.ec_finding("EC_ENDANGERED_SPECIES", False, 0, "No listed species habitat"),
    f.ec_finding("EC_WETLAND", False, 0, "No wetlands mapped"),
]

#: A screen whose wetland finding is present at a severity at or above the
#: office trigger threshold.
WETLAND_TRIGGER_SCREEN_FINDINGS = [
    f.ec_finding("EC_HISTORIC", False, 0, "No historic properties in the action area"),
    f.ec_finding("EC_ENDANGERED_SPECIES", False, 0, "No listed species habitat"),
    f.ec_finding("EC_WETLAND", True, 4, "Delineated wetland inside the work area"),
]

#: The four included baseline entries plus one beyond the inclusion radius.
BIOLOGICAL_BASELINE_INCLUDED = [
    {"label": "Legacy grazing allotment", "intensity_contribution": 20.0,
     "footprint_hectares": 100.0, "distance_km": 10.0, "temporal_scope": "PAST"},
    {"label": "Adjacent solar array", "intensity_contribution": 12.0,
     "footprint_hectares": 40.0, "distance_km": 5.0, "temporal_scope": "PRESENT"},
    {"label": "Planned access road", "intensity_contribution": 10.0,
     "footprint_hectares": 300.0, "distance_km": 20.0,
     "temporal_scope": "REASONABLY_FORESEEABLE"},
    {"label": "Fire salvage harvest", "intensity_contribution": 7.0,
     "footprint_hectares": 15.0, "distance_km": 24.0, "temporal_scope": "PRESENT"},
]

BIOLOGICAL_BASELINE_EXCLUDED = {
    "label": "Distant hardrock mine", "intensity_contribution": 90.0,
    "footprint_hectares": 500.0, "distance_km": 60.0, "temporal_scope": "PAST",
}

#: Option bundle for the branch of the review chain that records no scoping
#: issue, no cumulative baseline and no resource analysis at all: the
#: publication gates are then satisfied by the alternatives range and the
#: concurred consultation alone.
NO_ISSUE_NO_BASELINE_NO_ANALYSIS = {
    "with_issue": False,
    "with_baseline": False,
    "with_analysis": False,
}

#: Same branch but carrying the biological analysis, which then aggregates over
#: an empty cumulative baseline.
NO_ISSUE_NO_BASELINE = {"with_issue": False, "with_baseline": False}

#: Instants the canonical chain pins the logical clock to.
PUBLICATION_INSTANT = "2026-09-05T00:00:00Z"
COMMENT_PERIOD_END = "2026-10-05T00:00:00Z"
SIGNATURE_INSTANT = "2026-11-01T12:00:00Z"
OBJECTION_WINDOW_CLOSE = "2026-12-16T12:00:00Z"


# ==========================================================================
# Tier 2 — office, agency and action hierarchy
# ==========================================================================

def setup_office_and_action(pin_clock: bool = True,
                            office_overrides: Optional[dict] = None,
                            action_overrides: Optional[dict] = None) -> Ctx:
    """An office on its declared defaults plus one proposed action at ``INTAKE``."""
    if pin_clock:
        set_clock("2026-08-01T00:00:00Z")
    office = create_office(**(office_overrides or {}))
    action = create_action(office["id"], **(action_overrides or {}))
    return {"office": office, "action": action}


def setup_agency(ctx: Ctx, key: str = "agency", **overrides) -> Ctx:
    ctx[key] = create_agency(**overrides)
    return ctx


# ==========================================================================
# Tier 3 — lifecycle shortcuts along the review chain
# ==========================================================================

def setup_screened_action(pin_clock: bool = True,
                          office_overrides: Optional[dict] = None,
                          action_overrides: Optional[dict] = None,
                          screen_findings: Optional[List[dict]] = None,
                          disposition: str = "CLEARED") -> Ctx:
    """Action carried to ``SCREENED`` through one submitted-and-adjudicated screen."""
    ctx = setup_office_and_action(pin_clock, office_overrides, action_overrides)
    ctx["screen"] = submit_screen(
        ctx["action"]["id"], findings=screen_findings or CLEARED_SCREEN_FINDINGS
    )
    ctx["screen"] = adjudicate_screen(ctx["screen"]["id"], disposition)
    ctx["action"] = read_action(ctx["action"]["id"])
    return ctx


def setup_classified_action(**opts) -> Ctx:
    """Action carried to ``CLASSIFIED``."""
    ctx = setup_screened_action(**opts)
    ctx["action"] = classify(ctx["action"]["id"])
    return ctx


def setup_scoping_action(scoping_overrides: Optional[dict] = None,
                         purpose_need_overrides: Optional[dict] = None,
                         **opts) -> Ctx:
    """Action at ``SCOPING`` with one open public period and an adopted statement."""
    ctx = setup_classified_action(**opts)
    action_id = ctx["action"]["id"]
    ctx["statement"] = draft_purpose_need(action_id, **(purpose_need_overrides or {}))
    ctx["scoping_period"] = open_scoping_period(action_id, **(scoping_overrides or {}))
    ctx["statement"] = adopt_purpose_need(ctx["statement"]["id"], action_id)
    ctx["action"] = read_action(action_id)
    return ctx


def setup_alternatives(ctx: Ctx, screen_in: bool = True,
                       include_third: bool = False) -> Ctx:
    """The canonical alternatives range: a no-action alternative and a proposed
    action, optionally a third high-cost alternative."""
    action_id = ctx["action"]["id"]
    ctx["alt_a"] = create_alternative(
        action_id, label="A - No Action", alternative_kind="NO_ACTION",
        goal_alignment_codes=[], estimated_cost_cents=0,
    )
    ctx["alt_b"] = create_alternative(action_id)
    if include_third:
        ctx["alt_c"] = create_alternative(
            action_id, label="C - Full Mechanical Removal",
            alternative_kind="REASONABLE_RANGE", goal_alignment_codes=["ACCESS"],
            estimated_cost_cents=30000000,
        )
    if screen_in:
        ctx["alt_a"] = screen_alternative(ctx["alt_a"]["id"], "SCREENED_IN")
        ctx["alt_b"] = screen_alternative(ctx["alt_b"]["id"], "SCREENED_IN")
    ctx["action"] = read_action(action_id)
    return ctx


def setup_required_consultation(ctx: Ctx, respond: bool = True,
                                outcome: str = "CONCURRED", **agency_overrides) -> Ctx:
    """A consulting agency plus the ESA consultation the action's critical-habitat
    flag makes mandatory."""
    ctx = setup_agency(ctx, agency_code="USFWS", name="US Fish and Wildlife Service",
                       agency_role="CONSULTING", max_concurrent_consultations=2,
                       handoff_buffer_days=3, statutory_response_days=135,
                       **agency_overrides)
    ctx["consultation"] = open_consultation(ctx["action"]["id"], ctx["agency"]["id"])
    if respond:
        ctx["consultation"] = respond_consultation(
            ctx["consultation"]["id"], ctx["agency"]["id"], outcome
        )
    return ctx


def setup_biological_baseline(ctx: Ctx, include_excluded: bool = True) -> Ctx:
    """The four included baseline entries that aggregate to the canonical
    cumulative effect score, plus one entry beyond the inclusion radius."""
    action_id = ctx["action"]["id"]
    ctx["baseline"] = [
        add_baseline_entry(action_id, resource_area="BIOLOGICAL", **entry)
        for entry in BIOLOGICAL_BASELINE_INCLUDED
    ]
    if include_excluded:
        ctx["baseline_excluded"] = add_baseline_entry(
            action_id, resource_area="BIOLOGICAL", **BIOLOGICAL_BASELINE_EXCLUDED
        )
    return ctx


def setup_analysis_stage_action(with_issue: bool = True,
                                with_alternatives: bool = True,
                                screen_alternatives: bool = True,
                                include_third_alternative: bool = False,
                                with_consultation: bool = True,
                                respond_consultation_flag: bool = True,
                                consultation_outcome: str = "CONCURRED",
                                with_baseline: bool = False,
                                with_analysis: bool = False,
                                finalize_analysis_flag: bool = True,
                                analysis_overrides: Optional[dict] = None,
                                **opts) -> Ctx:
    """Action carried to ``ANALYSIS`` by closing its only scoping period.

    Each precondition the publication gates read is switchable so a test can
    withhold exactly one of them.
    """
    ctx = setup_scoping_action(**opts)
    action_id = ctx["action"]["id"]
    if with_issue:
        ctx["issue"] = record_issue(action_id, ctx["scoping_period"]["id"])
    if with_alternatives:
        ctx = setup_alternatives(ctx, screen_in=screen_alternatives,
                                 include_third=include_third_alternative)
    if with_consultation:
        ctx = setup_required_consultation(ctx, respond=respond_consultation_flag,
                                          outcome=consultation_outcome)
    ctx["scoping_period"] = close_scoping_period(ctx["scoping_period"]["id"])
    if with_baseline:
        ctx = setup_biological_baseline(ctx)
    if with_analysis:
        ctx = setup_biological_analysis(ctx, finalize=finalize_analysis_flag,
                                       **(analysis_overrides or {}))
    ctx["action"] = read_action(action_id)
    return ctx


# ==========================================================================
# Tier 4 — analysis and accumulation targeting
# ==========================================================================

def setup_biological_analysis(ctx: Ctx, finalize: bool = True,
                              basis: str = "UNMITIGATED", **overrides) -> Ctx:
    """Open — and by default finalise — the canonical biological analysis."""
    ctx["analysis"] = open_analysis(ctx["action"]["id"], **overrides)
    if finalize:
        ctx["analysis"] = finalize_analysis(ctx["analysis"]["id"], basis)
    ctx["action"] = read_action(ctx["action"]["id"])
    return ctx


def setup_publish_ready_action(with_baseline: bool = True,
                              finalize_analysis_flag: bool = True,
                              with_analysis: bool = True,
                              analysis_overrides: Optional[dict] = None,
                              **opts) -> Ctx:
    """Action at ``ANALYSIS`` with every publication gate satisfied: no
    unaddressed significant issue, the required consultation concurred, two
    screened-in alternatives and a final biological analysis."""
    ctx = setup_analysis_stage_action(with_baseline=with_baseline, **opts)
    if with_analysis:
        ctx = setup_biological_analysis(ctx, finalize=finalize_analysis_flag,
                                        **(analysis_overrides or {}))
    return ctx


# ==========================================================================
# Tier 5 — publication, decision, signature and terminal states
# ==========================================================================

def setup_published_document(document_overrides: Optional[dict] = None,
                             publication_instant: str = PUBLICATION_INSTANT,
                             comment_period_end_at: str = COMMENT_PERIOD_END,
                             **opts) -> Ctx:
    """Action at ``DRAFT_PUBLISHED`` with a published environmental assessment
    whose comment period runs the office's full minimum length."""
    ctx = setup_publish_ready_action(**opts)
    ctx["document"] = create_document(ctx["action"]["id"], **(document_overrides or {}))
    set_clock(publication_instant)
    ctx["document"] = publish_document(ctx["document"]["id"], comment_period_end_at)
    ctx["action"] = read_action(ctx["action"]["id"])
    return ctx


def setup_comment_closed_document(comments: Optional[List[dict]] = None,
                                  close_instant: str = COMMENT_PERIOD_END,
                                  **opts) -> Ctx:
    """Action at ``COMMENT_CLOSED`` with the comment axis closed on its
    published document. ``comments`` is a list of comment overrides."""
    ctx = setup_published_document(**opts)
    ctx["comments"] = [
        submit_comment(ctx["document"]["id"], **overrides)
        for overrides in (comments if comments is not None else [{}])
    ]
    set_clock(close_instant)
    ctx["document"] = close_comment_period(ctx["document"]["id"])
    ctx["action"] = read_action(ctx["action"]["id"])
    return ctx


def setup_final_document(response_categories: Optional[List[str]] = None,
                         **opts) -> Ctx:
    """Action at ``COMMENT_CLOSED`` whose document has reached ``FINAL`` on the
    publication axis, every substantive comment answered."""
    ctx = setup_comment_closed_document(**opts)
    categories = response_categories or ["ANALYSIS_REVISED"] * len(ctx["comments"])
    for comment, category in zip(ctx["comments"], categories):
        respond_comment(comment["id"], category)
    ctx["document"] = finalize_document(ctx["document"]["id"])
    ctx["action"] = read_action(ctx["action"]["id"])
    return ctx


def setup_drafted_decision(decision_type: str = "MITIGATED_FONSI",
                           mitigations: Optional[List[dict]] = None,
                           **opts) -> Ctx:
    """Action at ``COMMENT_CLOSED`` with a final document and a drafted decision
    selecting the screened-in proposed action, plus any mitigation commitments."""
    ctx = setup_final_document(**opts)
    ctx["decision"] = draft_decision(ctx["action"]["id"], ctx["alt_b"]["id"],
                                     decision_type)
    ctx["mitigations"] = []
    for overrides in (mitigations or []):
        ctx["mitigations"].append(
            attach_mitigation(ctx["decision"]["id"], ctx["analysis"]["id"], **overrides)
        )
    ctx["decision"] = read_decision(ctx["decision"]["id"])
    return ctx


#: The canonical two-commitment mitigation package.
CANONICAL_MITIGATIONS = [
    {"cost_estimate_cents": 1200000, "monitoring_years": 3,
     "annual_monitoring_cost_cents": 4500, "reduction_points": 9.0,
     "measure_text": "Seasonal closure of the winter range unit"},
    {"cost_estimate_cents": 2100000, "monitoring_years": 3,
     "annual_monitoring_cost_cents": 2500, "reduction_points": 5.0,
     "measure_text": "Culvert retrofit with effectiveness monitoring"},
]


def setup_signed_decision(decision_type: str = "MITIGATED_FONSI",
                          mitigations: Optional[List[dict]] = None,
                          signature_instant: str = SIGNATURE_INSTANT,
                          signer_user_id: str = DECIDING_OFFICIAL_USER_ID,
                          **opts) -> Ctx:
    """Action at ``DECIDED`` with a signed decision and an open objection window."""
    ctx = setup_drafted_decision(decision_type=decision_type, mitigations=mitigations,
                                 **opts)
    set_clock(signature_instant)
    ctx["decision"] = sign_decision(ctx["decision"]["id"], signer_user_id)
    ctx["action"] = read_action(ctx["action"]["id"])
    ctx["office"] = read_office(ctx["office"]["id"])
    return ctx


def setup_signed_mitigated_fonsi(**opts) -> Ctx:
    """The canonical mitigated finding of no significant impact, signed."""
    return setup_signed_decision(decision_type="MITIGATED_FONSI",
                                 mitigations=CANONICAL_MITIGATIONS, **opts)


def setup_signed_fonsi(**opts) -> Ctx:
    """A plain finding of no significant impact, signed with no commitments."""
    return setup_signed_decision(decision_type="FONSI", mitigations=None, **opts)


def setup_filed_objection(objection_overrides: Optional[dict] = None,
                          **opts) -> Ctx:
    """A signed decision with one objection filed inside its objection window."""
    ctx = setup_signed_decision(**opts)
    ctx["objection"] = file_objection(ctx["decision"]["id"],
                                      **(objection_overrides or {}))
    ctx["decision"] = read_decision(ctx["decision"]["id"])
    return ctx


# ==========================================================================
# Branch-specific chains
# ==========================================================================

CE_ACTION_OVERRIDES = {
    "title": "Trailhead Vault Toilet Replacement",
    "disturbance_hectares": 2.0,
    "reference_cost_cents": 400000,
    "in_critical_habitat": False,
    "affects_historic_property": False,
    "tribal_interest": False,
    "floodplain_or_wetland": False,
}


def setup_categorical_exclusion_action(pin_clock: bool = True) -> Ctx:
    """A small action with no circumstance present, classified as a categorical
    exclusion."""
    return setup_classified_action(
        pin_clock=pin_clock,
        action_overrides=dict(CE_ACTION_OVERRIDES),
        screen_findings=ALL_ABSENT_SCREEN_FINDINGS,
    )


def setup_ce_memorandum_with_pending_trigger(pin_clock: bool = True) -> Ctx:
    """A categorical-exclusion action with a draft memorandum on file and a
    second screen submitted whose wetland finding triggers."""
    ctx = setup_categorical_exclusion_action(pin_clock=pin_clock)
    ctx["document"] = create_document(ctx["action"]["id"],
                                      document_type="CE_MEMORANDUM",
                                      title="Trailhead Vault Toilet CE Memorandum")
    ctx["second_screen"] = submit_screen(ctx["action"]["id"],
                                        findings=WETLAND_TRIGGER_SCREEN_FINDINGS)
    ctx["action"] = read_action(ctx["action"]["id"])
    return ctx


def setup_capacity_agencies(ctx: Ctx) -> Ctx:
    """Two agencies with contrasting scheduling parameters: one tolerating two
    overlapping pending consultations, one tolerating a single one."""
    ctx["noaa"] = create_agency(agency_code="NOAA", name="NOAA Fisheries",
                                agency_role="CONSULTING",
                                max_concurrent_consultations=2,
                                handoff_buffer_days=3, statutory_response_days=135)
    ctx["shpo"] = create_agency(agency_code="SHPO",
                                name="State Historic Preservation Office",
                                agency_role="CONSULTING",
                                max_concurrent_consultations=1,
                                handoff_buffer_days=3, statutory_response_days=30)
    return ctx
