"""Reusable setup builders.

Every test starts against an empty data store, so all state is built here from
scratch through the API. Each builder returns the created resource objects so
the calling test can thread real ids into the headers of the entity-backed
roles: a coordinator's own id, an agency's own id, a panelist's own id.

The builders deliberately use `get_success_data`, which accepts any 2xx, so a
setup step never asserts a status the test itself is about to pin.
"""

from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from . import factories
from .api_client import api_client
from .test_users import (
    make_admin_headers,
    make_agency_rep_headers,
    make_allocations_director_headers,
    make_finance_reviewer_headers,
    make_panelist_headers,
)


def set_clock(to_iso8601: str) -> Dict[str, Any]:
    """Move the logical UTC clock (PRD 2.7)."""
    return get_success_data(
        api_client.set_logical_clock(
            factories.clock_payload(to_iso8601), make_admin_headers()
        )
    )


# ---------------------------------------------------------------------
# Employers, coordinators, campaigns
# ---------------------------------------------------------------------
def create_employer(**kwargs: Any) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_employer(factories.employer_payload(**kwargs), make_admin_headers())
    )


def create_active_employer(**kwargs: Any) -> Dict[str, Any]:
    """An employer registered with `partnership_signed` true is created directly
    in `ACTIVE` (PRD 3.1)."""
    kwargs.setdefault("partnership_signed", True)
    return create_employer(**kwargs)


def create_coordinator(employer_id: str, **kwargs: Any) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_coordinator(
            employer_id, factories.coordinator_payload(**kwargs), make_admin_headers()
        )
    )


def create_campaign(employer_id: str, **kwargs: Any) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_campaign(
            factories.campaign_payload(employer_id, **kwargs), make_admin_headers()
        )
    )


def create_open_campaign(
    employer_id: Optional[str] = None, **kwargs: Any
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Return `(employer, campaign)` with the campaign moved `PLANNED -> OPEN`."""
    employer = None
    if employer_id is None:
        employer = create_active_employer()
        employer_id = employer["id"]
    campaign = create_campaign(employer_id, **kwargs)
    campaign = get_success_data(api_client.open_campaign(campaign["id"], make_admin_headers()))
    if employer is None:
        employer = get_success_data(api_client.get_employer(employer_id, make_admin_headers()))
    return employer, campaign


def create_pledge(campaign_id: str, **kwargs: Any) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_pledge(
            campaign_id, factories.pledge_payload(**kwargs), make_admin_headers()
        )
    )


def create_confirmed_pledge(campaign_id: str, **kwargs: Any) -> Dict[str, Any]:
    pledge = create_pledge(campaign_id, **kwargs)
    return get_success_data(api_client.confirm_pledge(pledge["id"], make_admin_headers()))


def remit(pledge_id: str, amount: str, remitted_on: str = "2026-08-01") -> Dict[str, Any]:
    return get_success_data(
        api_client.create_collection(
            pledge_id,
            factories.collection_payload(amount, remitted_on),
            make_finance_reviewer_headers(),
        )
    )


# ---------------------------------------------------------------------
# Agencies and financial reviews
# ---------------------------------------------------------------------
def create_agency(**kwargs: Any) -> Dict[str, Any]:
    """An agency is admitted in `APPLICANT` membership status (PRD 3.6)."""
    return get_success_data(
        api_client.create_agency(factories.agency_payload(**kwargs), make_admin_headers())
    )


def file_review(agency_id: str, **kwargs: Any) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_agency_review(
            agency_id, factories.agency_review_payload(**kwargs), make_admin_headers()
        )
    )


def certify_review(agency_id: str, review_id: str, **kwargs: Any) -> Dict[str, Any]:
    return get_success_data(
        api_client.certify_agency_review(
            agency_id,
            review_id,
            factories.certify_payload(**kwargs),
            make_finance_reviewer_headers(),
        )
    )


def create_good_standing_agency(**kwargs: Any) -> Dict[str, Any]:
    """Admit an agency and certify a review whose certified score reaches the
    70.00 `GOOD_STANDING` band.

    Self-reported 0.7800 program, 0.1900 admin, 4.00 months reserve, 8
    governance items and an `UNQUALIFIED` opinion, audited unchanged, certify at
    40.00 + 20.00 + 20.00 + 10 = 90.00 with no penalties.
    """
    agency = create_agency(**kwargs)
    review = file_review(agency["id"])
    certify_review(agency["id"], review["id"])
    return get_success_data(api_client.get_agency(agency["id"], make_admin_headers()))


def create_probation_agency(**kwargs: Any) -> Dict[str, Any]:
    """Admit an agency and certify a review landing in the probation band.

    Self-reported 0.7800 / 0.1900 / 4.00 / 8 / `UNQUALIFIED` audited back as
    0.7400 / 0.2700 / 3.00 certifies at 69.50 (PRD 3.6 worked example).
    """
    agency = create_agency(**kwargs)
    review = file_review(agency["id"])
    certify_review(
        agency["id"],
        review["id"],
        audited_program_expense_ratio="0.7400",
        audited_admin_expense_ratio="0.2700",
        audited_months_operating_reserve="3.00",
    )
    return get_success_data(api_client.get_agency(agency["id"], make_admin_headers()))


def create_suspended_membership_agency(**kwargs: Any) -> Dict[str, Any]:
    """Admit an agency and certify a review scoring below the 55.00 band.

    A 0.6500 program ratio earns no program points, a 1.0000 admin ratio costs
    (1.0000 - 0.25) x 200 = 150.00, and the clamp floors the result at 0.00,
    which is below 55.00 and therefore terminal.
    """
    agency = create_agency(**kwargs)
    review = file_review(
        agency["id"],
        program_expense_ratio="0.6500",
        admin_expense_ratio="1.0000",
        months_operating_reserve="0.00",
        governance_checklist_passed_count=0,
        audit_opinion="NONE",
    )
    certify_review(
        agency["id"],
        review["id"],
        audited_program_expense_ratio="0.6500",
        audited_admin_expense_ratio="1.0000",
        audited_months_operating_reserve="0.00",
    )
    return get_success_data(api_client.get_agency(agency["id"], make_admin_headers()))


# ---------------------------------------------------------------------
# Panelists, cycles and panel seats
# ---------------------------------------------------------------------
def create_panelist(**kwargs: Any) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_panelist(factories.panelist_payload(**kwargs), make_admin_headers())
    )


def create_cycle(**kwargs: Any) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_allocation_cycle(
            factories.allocation_cycle_payload(**kwargs), make_allocations_director_headers()
        )
    )


def seat_panelist(cycle_id: str, panelist_id: str, **kwargs: Any) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_panel_assignment(
            cycle_id,
            factories.panel_assignment_payload(panelist_id, **kwargs),
            make_admin_headers(),
        )
    )


def create_open_cycle(
    panelist_count: int = 3, **kwargs: Any
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """Return `(cycle, panelists)` with the cycle moved `DRAFT -> OPEN`.

    Opening requires at least one seat whose `conflict_declared` is false, and
    three conflict-free scorers are seated by default so a request filed against
    the cycle can reach the panel quorum of three.
    """
    cycle = create_cycle(**kwargs)
    panelists = []
    for _ in range(panelist_count):
        panelist = create_panelist()
        seat_panelist(cycle["id"], panelist["id"])
        panelists.append(panelist)
    cycle = get_success_data(
        api_client.open_allocation_cycle(cycle["id"], make_allocations_director_headers())
    )
    return cycle, panelists


# ---------------------------------------------------------------------
# Allocation requests, scoring and awards
# ---------------------------------------------------------------------
def create_request(cycle_id: str, agency_id: str, **kwargs: Any) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_allocation_request(
            factories.allocation_request_payload(cycle_id, agency_id, **kwargs),
            make_agency_rep_headers(agency_id),
        )
    )


def create_submitted_request(cycle_id: str, agency_id: str, **kwargs: Any) -> Dict[str, Any]:
    request = create_request(cycle_id, agency_id, **kwargs)
    return get_success_data(
        api_client.submit_allocation_request(
            request["id"], make_agency_rep_headers(agency_id)
        )
    )


def file_score(request_id: str, panelist_id: str, **kwargs: Any) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_panel_score(
            request_id,
            factories.panel_score_payload(**kwargs),
            make_panelist_headers(panelist_id),
        )
    )


def finalize(request_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.finalize_review(request_id, make_allocations_director_headers())
    )


def create_panel_approved_request(
    cycle_id: str,
    agency_id: str,
    panelists: List[Dict[str, Any]],
    score_kwargs: Optional[Dict[str, Any]] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Submit a request, file one score per supplied panelist, and close review."""
    request = create_submitted_request(cycle_id, agency_id, **kwargs)
    for panelist in panelists:
        file_score(request["id"], panelist["id"], **(score_kwargs or {}))
    return finalize(request["id"])


def award(cycle_id: str, request_id: str, cycle_version: int) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_award(
            cycle_id,
            factories.award_payload(request_id, cycle_version),
            make_allocations_director_headers(),
        )
    )


def current_cycle_version(cycle_id: str) -> int:
    """Read the cycle's current `version` for the award's concurrency guard."""
    cycle = get_success_data(
        api_client.get_allocation_cycle(cycle_id, make_admin_headers())
    )
    return cycle["version"]


def create_awarded_request(
    cycle_id: str,
    agency_id: str,
    panelists: List[Dict[str, Any]],
    score_kwargs: Optional[Dict[str, Any]] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    request = create_panel_approved_request(
        cycle_id, agency_id, panelists, score_kwargs, **kwargs
    )
    award(cycle_id, request["id"], current_cycle_version(cycle_id))
    return get_success_data(
        api_client.get_allocation_request(request["id"], make_admin_headers())
    )


def create_outcome_report(request_id: str, agency_id: str, **kwargs: Any) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_outcome_report(
            request_id,
            factories.outcome_report_payload(**kwargs),
            make_agency_rep_headers(agency_id),
        )
    )
