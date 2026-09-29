"""Composite setup helpers.

The harness restarts the service before every individual test, so each test
begins against an empty store. Everything a test needs is therefore built here
from scratch, using only the endpoints the PRD declares, and every call is
checked leniently with `get_success_data` so a broken precondition surfaces as
a setup failure rather than as a confusing assertion later on.

The helpers are layered: atomic builders create one record each, and
`build_context` walks the whole intake-to-approval chain and stops at the
requested stage, returning a dict of every record it created.
"""

from typing import Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import DEFAULT_CLOCK_INSTANT
from .factories import (
    award_payload,
    board_approve_payload,
    clock_payload,
    create_agreement_payload,
    create_assessment_payload,
    create_developer_payload,
    create_disposition_request_payload,
    create_facility_replacement_payload,
    create_maintenance_charge_payload,
    create_negotiation_period_payload,
    create_proposal_payload,
    create_shared_facility_payload,
    create_site_payload,
    create_solicitation_payload,
    create_staging_window_payload,
    create_valuation_payload,
    maintenance_line_item,
    replacement_status_payload,
    staging_decision_payload,
)
from .test_users import (
    make_board_secretary_headers,
    make_developer_headers,
    make_grants_compliance_officer_headers,
    make_real_estate_officer_headers,
    make_system_admin_headers,
    make_transit_operations_manager_headers,
    make_valuation_officer_headers,
)

# Stage names understood by build_context, in the order the chain visits them.
CONTEXT_STAGES = [
    "SITE",
    "ASSESSED",
    "RELEASED",
    "SOLICITATION_ISSUED",
    "PROPOSAL",
    "NEGOTIATION",
    "VALUATION",
    "DRAFTING",
    "AGENCY_REVIEW",
    "BOARD_APPROVED",
]


# --------------------------------------------------------------------------
# Tier 1 — atomic builders
# --------------------------------------------------------------------------


def set_logical_clock(instant: str = DEFAULT_CLOCK_INSTANT) -> Dict:
    """Move the logical clock; returns the clock payload the service reports."""
    return get_success_data(
        api_client.set_clock(clock_payload(instant), make_system_admin_headers()))


def read_site(site_id: str) -> Dict:
    return get_success_data(
        api_client.get_site(site_id, make_real_estate_officer_headers()))


def read_agreement(agreement_id: str) -> Dict:
    return get_success_data(
        api_client.get_agreement(agreement_id, make_real_estate_officer_headers()))


def read_shared_facility(facility_id: str) -> Dict:
    return get_success_data(
        api_client.get_shared_facility(
            facility_id, make_transit_operations_manager_headers()))


def build_site(**overrides) -> Dict:
    return get_success_data(
        api_client.create_site(create_site_payload(**overrides),
                               make_real_estate_officer_headers()))


def build_assessment(site_id: str, **overrides) -> Dict:
    return get_success_data(
        api_client.create_assessment(site_id, create_assessment_payload(**overrides),
                                     make_real_estate_officer_headers()))


def certify_assessment(assessment_id: str) -> Dict:
    return get_success_data(
        api_client.certify_assessment(assessment_id,
                                      make_real_estate_officer_headers()))


def release_site(site_id: str) -> Dict:
    return get_success_data(
        api_client.release_site_for_solicitation(
            site_id, make_real_estate_officer_headers()))


def build_developer(**overrides) -> Dict:
    return get_success_data(
        api_client.create_developer(create_developer_payload(**overrides),
                                    make_real_estate_officer_headers()))


def build_solicitation(site_id: str, **overrides) -> Dict:
    return get_success_data(
        api_client.create_solicitation(site_id,
                                       create_solicitation_payload(**overrides),
                                       make_real_estate_officer_headers()))


def issue_solicitation(solicitation_id: str) -> Dict:
    return get_success_data(
        api_client.issue_solicitation(solicitation_id,
                                      make_real_estate_officer_headers()))


def build_proposal(solicitation_id: str, developer_id: str, **overrides) -> Dict:
    """Submitted by the developer itself, as ownership demands."""
    return get_success_data(
        api_client.create_proposal(solicitation_id,
                                   create_proposal_payload(developer_id, **overrides),
                                   make_developer_headers(developer_id)))


def shortlist_proposal(proposal_id: str) -> Dict:
    return get_success_data(
        api_client.shortlist_proposal(proposal_id,
                                      make_real_estate_officer_headers()))


def close_solicitation(solicitation_id: str) -> Dict:
    return get_success_data(
        api_client.close_solicitation(solicitation_id,
                                      make_real_estate_officer_headers()))


def award_solicitation(solicitation_id: str, proposal_id: str,
                       start_date: str = "2026-08-15",
                       end_date: str = "2027-01-15",
                       deviation_justification: Optional[str] = None) -> Dict:
    return get_success_data(
        api_client.award_solicitation(
            solicitation_id,
            award_payload(proposal_id, start_date, end_date,
                          deviation_justification),
            make_real_estate_officer_headers()))


def build_negotiation_period(site_id: str, proposal_id: str,
                             start_date: str = "2026-08-15",
                             end_date: str = "2027-01-15", **overrides) -> Dict:
    return get_success_data(
        api_client.create_negotiation_period(
            site_id,
            create_negotiation_period_payload(proposal_id, start_date, end_date,
                                              **overrides),
            make_real_estate_officer_headers()))


def build_valuation(site_id: str, expected_site_version: Optional[int] = None,
                    **overrides) -> Dict:
    """Reads the site first when no expected version is supplied, as §2.10 forces."""
    if expected_site_version is None:
        expected_site_version = read_site(site_id)["version"]
    return get_success_data(
        api_client.create_valuation(
            site_id, create_valuation_payload(expected_site_version, **overrides),
            make_valuation_officer_headers()))


def certify_valuation(valuation_id: str) -> Dict:
    return get_success_data(
        api_client.certify_valuation(valuation_id, make_valuation_officer_headers()))


def build_certified_valuation(site_id: str, **overrides) -> Dict:
    valuation = build_valuation(site_id, **overrides)
    return certify_valuation(valuation["id"])


def build_agreement(site_id: str, developer_id: str, proposal_id: str,
                    valuation_id: str, **overrides) -> Dict:
    return get_success_data(
        api_client.create_agreement(
            create_agreement_payload(site_id, developer_id, proposal_id,
                                     valuation_id, **overrides),
            make_real_estate_officer_headers()))


def submit_agreement(agreement_id: str, user_id: str = "reo-001") -> Dict:
    return get_success_data(
        api_client.submit_agreement_for_review(
            agreement_id, make_real_estate_officer_headers(user_id)))


def board_approve_agreement(agreement_id: str, resolution_number: str,
                            user_id: str = "bsec-001") -> Dict:
    return get_success_data(
        api_client.board_approve_agreement(
            agreement_id, board_approve_payload(resolution_number),
            make_board_secretary_headers(user_id)))


def build_shared_facility(site_id: str, **overrides) -> Dict:
    return get_success_data(
        api_client.create_shared_facility(
            site_id, create_shared_facility_payload(**overrides),
            make_transit_operations_manager_headers()))


def build_facility_replacement(agreement_id: str, **overrides) -> Dict:
    return get_success_data(
        api_client.create_facility_replacement(
            agreement_id, create_facility_replacement_payload(**overrides),
            make_transit_operations_manager_headers()))


def report_replacement_status(replacement_id: str, status: str, **overrides) -> Dict:
    return get_success_data(
        api_client.report_facility_replacement_status(
            replacement_id, replacement_status_payload(status, **overrides),
            make_transit_operations_manager_headers()))


def build_interim_facility_replacement(agreement_id: str, **overrides) -> Dict:
    """A replacement already reported as INTERIM_IN_PLACE, which unblocks
    staging approval and execution on a parcel carrying a transit facility."""
    replacement = build_facility_replacement(agreement_id, **overrides)
    return report_replacement_status(replacement["id"], "INTERIM_IN_PLACE")


def build_staging_window(agreement_id: str, facility_id: str, developer_id: str,
                         expected_facility_version: Optional[int] = None,
                         **overrides) -> Dict:
    """Reads the facility first when no expected version is supplied."""
    if expected_facility_version is None:
        expected_facility_version = read_shared_facility(facility_id)["version"]
    return get_success_data(
        api_client.create_staging_window(
            create_staging_window_payload(agreement_id, facility_id,
                                          expected_facility_version, **overrides),
            make_developer_headers(developer_id)))


def decide_staging_window(window_id: str, decision: str,
                          rejection_reason: Optional[str] = None) -> Dict:
    return get_success_data(
        api_client.decide_staging_window(
            window_id, staging_decision_payload(decision, rejection_reason),
            make_transit_operations_manager_headers()))


def build_approved_staging_window(agreement_id: str, facility_id: str,
                                  developer_id: str, **overrides) -> Dict:
    window = build_staging_window(agreement_id, facility_id, developer_id,
                                  **overrides)
    return decide_staging_window(window["id"], "APPROVE")


def close_staging_window(window_id: str) -> Dict:
    return get_success_data(
        api_client.close_staging_window(
            window_id, make_transit_operations_manager_headers()))


def build_disposition_request(agreement_id: str,
                              narrative: str = "Joint development disposition "
                                               "for the junction parcel") -> Dict:
    return get_success_data(
        api_client.create_disposition_request(
            agreement_id, create_disposition_request_payload(narrative),
            make_grants_compliance_officer_headers()))


def build_maintenance_charge(facility_id: str, agreement_id: str,
                             line_items: Optional[List[Dict]] = None,
                             **overrides) -> Dict:
    if line_items is None:
        line_items = [maintenance_line_item("Bay sweeping", 41250)]
    return get_success_data(
        api_client.create_maintenance_charge(
            facility_id,
            create_maintenance_charge_payload(agreement_id, line_items, **overrides),
            make_transit_operations_manager_headers()))


# --------------------------------------------------------------------------
# Tier 2 — the intake-to-approval chain, stopped at a chosen stage
# --------------------------------------------------------------------------


def build_context(
    stage: str = "RELEASED",
    site_overrides: Optional[Dict] = None,
    assessment_overrides: Optional[Dict] = None,
    developer_overrides: Optional[Dict] = None,
    solicitation_overrides: Optional[Dict] = None,
    proposal_overrides: Optional[Dict] = None,
    period_start_date: str = "2026-08-15",
    period_end_date: str = "2027-01-15",
    negotiation_via: str = "direct",
    valuation_overrides: Optional[Dict] = None,
    certify_valuation_record: bool = True,
    agreement_overrides: Optional[Dict] = None,
    submitter_user_id: str = "reo-001",
    approver_user_id: str = "bsec-001",
    resolution_number: str = "R-2026-100",
    pin_clock: bool = True,
) -> Dict:
    """Walk the chain a parcel travels and stop at `stage`.

    Returned keys accumulate as the chain advances: `site`, `assessment`,
    `developer`, `solicitation`, `proposal`, `period`, `valuation`,
    `agreement`. `site` always holds a freshly read copy, so its `version`
    and ledger fields are the ones a caller can quote back to the API.
    """
    assert stage in CONTEXT_STAGES, f"unknown stage {stage!r}"
    if pin_clock:
        set_logical_clock()

    ctx: Dict = {}
    site = build_site(**(site_overrides or {}))
    ctx["site"] = site
    if stage == "SITE":
        return ctx

    assessment = build_assessment(site["id"], **(assessment_overrides or {}))
    ctx["assessment"] = certify_assessment(assessment["id"])
    ctx["site"] = read_site(site["id"])
    if stage == "ASSESSED":
        return ctx

    release_site(site["id"])
    ctx["site"] = read_site(site["id"])
    if stage == "RELEASED":
        return ctx

    ctx["developer"] = build_developer(**(developer_overrides or {}))
    solicitation = build_solicitation(site["id"], **(solicitation_overrides or {}))
    ctx["solicitation"] = issue_solicitation(solicitation["id"])
    if stage == "SOLICITATION_ISSUED":
        return ctx

    ctx["proposal"] = build_proposal(ctx["solicitation"]["id"],
                                     ctx["developer"]["id"],
                                     **(proposal_overrides or {}))
    if stage == "PROPOSAL":
        return ctx

    if negotiation_via == "award":
        ctx["solicitation"] = close_solicitation(ctx["solicitation"]["id"])
        ctx["solicitation"] = award_solicitation(
            ctx["solicitation"]["id"], ctx["proposal"]["id"],
            period_start_date, period_end_date)
        periods, _ = _list_site_periods(site["id"])
        ctx["period"] = periods[0]
    else:
        ctx["period"] = build_negotiation_period(
            site["id"], ctx["proposal"]["id"], period_start_date, period_end_date)
    ctx["proposal"] = get_success_data(
        api_client.get_proposal(ctx["proposal"]["id"],
                                make_real_estate_officer_headers()))
    ctx["site"] = read_site(site["id"])
    if stage == "NEGOTIATION":
        return ctx

    valuation = build_valuation(site["id"], **(valuation_overrides or {}))
    ctx["valuation"] = (certify_valuation(valuation["id"])
                        if certify_valuation_record else valuation)
    ctx["site"] = read_site(site["id"])
    if stage == "VALUATION":
        return ctx

    ctx["agreement"] = build_agreement(site["id"], ctx["developer"]["id"],
                                       ctx["proposal"]["id"],
                                       ctx["valuation"]["id"],
                                       **(agreement_overrides or {}))
    if stage == "DRAFTING":
        return ctx

    ctx["agreement"] = submit_agreement(ctx["agreement"]["id"], submitter_user_id)
    if stage == "AGENCY_REVIEW":
        return ctx

    ctx["agreement"] = board_approve_agreement(ctx["agreement"]["id"],
                                               resolution_number, approver_user_id)
    return ctx


def _list_site_periods(site_id: str):
    response = api_client.list_negotiation_periods(
        make_real_estate_officer_headers(), params={"site_id": site_id})
    body = get_success_data(response)
    return body, response.json()["meta"]


# --------------------------------------------------------------------------
# Tier 3 — named shortcuts for the stages tests ask for most
# --------------------------------------------------------------------------


def build_released_site(**kwargs) -> Dict:
    """A site at SOLICITATION_READY with a certified READY assessment."""
    return build_context(stage="RELEASED", **kwargs)


def build_issued_solicitation_context(**kwargs) -> Dict:
    return build_context(stage="SOLICITATION_ISSUED", **kwargs)


def build_submitted_proposal_context(**kwargs) -> Dict:
    return build_context(stage="PROPOSAL", **kwargs)


def build_site_under_agreement(**kwargs) -> Dict:
    """A live exclusive negotiation period, so the site is UNDER_AGREEMENT."""
    return build_context(stage="NEGOTIATION", **kwargs)


def build_certified_valuation_context(**kwargs) -> Dict:
    return build_context(stage="VALUATION", **kwargs)


def build_drafting_agreement(**kwargs) -> Dict:
    return build_context(stage="DRAFTING", **kwargs)


def build_agency_review_agreement(**kwargs) -> Dict:
    return build_context(stage="AGENCY_REVIEW", **kwargs)


def build_board_approved_agreement(**kwargs) -> Dict:
    return build_context(stage="BOARD_APPROVED", **kwargs)


# --------------------------------------------------------------------------
# Tier 4 — accumulation and capacity targeting
# --------------------------------------------------------------------------


def build_board_approved_with_shared_facility(
        facility_overrides: Optional[Dict] = None, **kwargs) -> Dict:
    """A board-approved agreement plus a shared facility on the same parcel.

    When the parcel carries a transit facility, a replacement is also reported
    as INTERIM_IN_PLACE so staging approval and execution are not blocked.
    """
    ctx = build_board_approved_agreement(**kwargs)
    ctx["facility"] = build_shared_facility(ctx["site"]["id"],
                                            **(facility_overrides or {}))
    if ctx["site"]["transit_facility_present"]:
        ctx["replacement"] = build_interim_facility_replacement(
            ctx["agreement"]["id"])
    return ctx


def build_encumbered_site_context(
        narrative: str = "Joint development disposition for the junction parcel",
        **kwargs) -> Dict:
    """A board-approved agreement with one PENDING disposition request filed,
    so part of the site's federal interest is encumbered."""
    ctx = build_board_approved_agreement(**kwargs)
    ctx["disposition_request"] = build_disposition_request(
        ctx["agreement"]["id"], narrative)
    ctx["site"] = read_site(ctx["site"]["id"])
    return ctx


def build_occupied_facility_context(bays_occupied: int = 4,
                                    start_at: str = "2026-09-01T08:00:00Z",
                                    end_at: str = "2026-09-08T08:00:00Z",
                                    facility_overrides: Optional[Dict] = None,
                                    **kwargs) -> Dict:
    """A shared facility with one APPROVED window already holding bays."""
    ctx = build_board_approved_with_shared_facility(
        facility_overrides=facility_overrides, **kwargs)
    ctx["window"] = build_approved_staging_window(
        ctx["agreement"]["id"], ctx["facility"]["id"], ctx["developer"]["id"],
        start_at=start_at, end_at=end_at, bays_occupied=bays_occupied,
        purpose="Material laydown")
    ctx["facility"] = read_shared_facility(ctx["facility"]["id"])
    return ctx


# --------------------------------------------------------------------------
# Tier 5 — terminal states
# --------------------------------------------------------------------------


def build_executed_agreement(execution_date: str = "2026-08-25", **kwargs) -> Dict:
    """A fully executed agreement; for a fee disposition the site is CONVEYED."""
    from .factories import execute_agreement_payload
    ctx = build_board_approved_agreement(**kwargs)
    if ctx["site"]["transit_facility_present"]:
        ctx["replacement"] = build_interim_facility_replacement(
            ctx["agreement"]["id"])
    ctx["agreement"] = get_success_data(
        api_client.execute_agreement(ctx["agreement"]["id"],
                                     execute_agreement_payload(execution_date),
                                     make_real_estate_officer_headers()))
    ctx["site"] = read_site(ctx["site"]["id"])
    ctx["period"] = get_success_data(
        api_client.get_negotiation_period(ctx["period"]["id"],
                                          make_real_estate_officer_headers()))
    return ctx


def build_rejected_disposition_context(
        condition_notes: str = "Federal share not adequately protected",
        **kwargs) -> Dict:
    """A filed request the grantor rejected, driving the reversal cascade."""
    from .factories import determination_payload
    ctx = build_encumbered_site_context(**kwargs)
    ctx["disposition_request"] = get_success_data(
        api_client.record_disposition_determination(
            ctx["disposition_request"]["id"],
            determination_payload("REJECTED", condition_notes),
            make_grants_compliance_officer_headers()))
    ctx["site"] = read_site(ctx["site"]["id"])
    ctx["agreement"] = read_agreement(ctx["agreement"]["id"])
    return ctx
