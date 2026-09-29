"""
Composite setup helpers.

Every helper builds state exclusively through the API's own endpoints, because
each test starts against an empty database. The helpers are layered:

* tier 1 - single-row creators (funding source, parcel, contractor, applicant)
* tier 2 - registry mutations (code violations, tax roll, owner of record,
  adjacency edges, reuse hearings)
* tier 3 - workflow steps (open / approve / close a packet, clear title, list a
  parcel, schedule / complete / cancel an order, plan / execute a run)
* tier 4 - disposition workflow (draft, submit, screen, recommend, decide,
  execute the agreement)
* tier 5 - whole-chain scenarios (an acquired parcel, a listed parcel, an
  awarded parcel, a parcel driven all the way to a reverter)

Two conventions matter throughout:

* the officer who initiates an acquisition packet may not close it, so
  ``close_packet`` acts as a second intake officer by default, and the officer
  who performed the governing screening may not recommend, so ``recommend``
  acts as a second disposition officer by default;
* scheduling a maintenance order and planning a demolition run both require the
  caller to state the version it read, so the helpers re-read that version
  immediately before the call.
"""

from itertools import count
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from . import factories
from .api_client import ApiClient
from .test_users import (
    CLERK_1,
    DISP_1,
    DISP_2,
    INTAKE_1,
    INTAKE_2,
    INV_1,
    TREAS_1,
    make_applicant_headers,
)

_resolution_seq = count(1)
_deed_seq = count(1)


def next_resolution_no() -> str:
    """Mint a board resolution number."""
    return f"R-2026-{next(_resolution_seq):03d}"


def next_deed_reference() -> str:
    """Mint a recorder's deed reference."""
    return f"BK-4400-PG-{next(_deed_seq):02d}"


# ─── tier 0: clock and reads ─────────────────────────────────────────────────
def set_clock(api: ApiClient, to_iso8601: str, headers: Dict[str, str] = INV_1) -> str:
    """Move the server's logical UTC clock and return the new instant."""
    data = get_success_data(api.set_clock(to_iso8601, headers))
    return data["current_utc"]


def read_property(api: ApiClient, property_id: str, headers: Dict[str, str] = INV_1) -> Dict[str, Any]:
    """Read one parcel."""
    return get_success_data(api.get_property(property_id, headers))


def property_version(api: ApiClient, property_id: str) -> int:
    """Read the parcel's current version, for the concurrency-guarded write."""
    return read_property(api, property_id)["version"]


def read_funding_source(
    api: ApiClient, funding_source_id: str, headers: Dict[str, str] = TREAS_1
) -> Dict[str, Any]:
    """Read one funding source with its full ledger position."""
    return get_success_data(api.get_funding_source(funding_source_id, headers))


def funding_source_version(api: ApiClient, funding_source_id: str) -> int:
    """Read the funding source's current version, for run planning."""
    return read_funding_source(api, funding_source_id)["version"]


def read_application(
    api: ApiClient, application_id: str, headers: Dict[str, str] = DISP_1
) -> Dict[str, Any]:
    """Read one disposition application."""
    return get_success_data(api.get_disposition_application(application_id, headers))


def read_applicant(
    api: ApiClient, applicant_id: str, headers: Dict[str, str] = DISP_1
) -> Dict[str, Any]:
    """Read one applicant with the aggregates that drive screening."""
    return get_success_data(api.get_applicant(applicant_id, headers))


def read_agreement(
    api: ApiClient, agreement_id: str, headers: Dict[str, str] = CLERK_1
) -> Dict[str, Any]:
    """Read one development agreement."""
    return get_success_data(api.get_development_agreement(agreement_id, headers))


def read_order(
    api: ApiClient, order_id: str, headers: Dict[str, str] = INV_1
) -> Dict[str, Any]:
    """Read one maintenance order."""
    return get_success_data(api.get_maintenance_order(order_id, headers))


def read_packet(
    api: ApiClient, packet_id: str, headers: Dict[str, str] = INTAKE_1
) -> Dict[str, Any]:
    """Read one acquisition packet."""
    return get_success_data(api.get_acquisition_packet(packet_id, headers))


def inventory_summary(
    api: ApiClient, situs_ward: Optional[int] = None, headers: Dict[str, str] = INV_1
) -> Dict[str, Any]:
    """Read the authority-wide conserved positions."""
    params = {"situs_ward": situs_ward} if situs_ward is not None else None
    return get_success_data(api.get_inventory_summary(headers, params))


def price_quote(
    api: ApiClient, property_id: str, program: str, headers: Dict[str, str] = DISP_1
) -> Dict[str, Any]:
    """Read the computed disposition price quote for a parcel and program."""
    return get_success_data(api.get_price_quote(property_id, program, headers))


# ─── tier 1: single-row creators ─────────────────────────────────────────────
def create_funding_source(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """Authorize a funding source. Defaults to an unrestricted 1,000,000 cents."""
    payload = factories.funding_source_payload(**overrides)
    return get_success_data(api.create_funding_source(payload, CLERK_1))


def create_acquisition_funding_source(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """
    Authorize a source restricted to acquisitions, so that maintenance and
    demolition ledgers on other sources stay clean.
    """
    defaults: Dict[str, Any] = {
        "name": "Acquisition Revolving Line",
        "source_type": "GENERAL_FUND",
        "authorized_cents": 500000,
        "restriction": "ACQUISITION_ONLY",
        "expires_on": "2029-12-31T00:00:00Z",
    }
    defaults.update(overrides)
    return create_funding_source(api, **defaults)


def create_property(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """Register a parcel in the prospect registry."""
    payload = factories.property_payload(**overrides)
    return get_success_data(api.create_property(payload, INTAKE_1))


def create_contractor(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """Register a maintenance or demolition contractor."""
    payload = factories.contractor_payload(**overrides)
    return get_success_data(api.create_contractor(payload, INV_1))


def create_applicant(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """Register a prospective buyer."""
    payload = factories.applicant_payload(**overrides)
    return get_success_data(api.create_applicant(payload, DISP_1))


def create_developer_applicant(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """Register a DEVELOPER applicant, the type the RFP program requires."""
    defaults: Dict[str, Any] = {
        "legal_name": "Anvil Development Group",
        "applicant_type": "DEVELOPER",
        "contact_email": "a@anvil-dev.example",
    }
    defaults.update(overrides)
    return create_applicant(api, **defaults)


def create_nonprofit_applicant(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """Register a NONPROFIT applicant with a registration number on file."""
    defaults: Dict[str, Any] = {
        "legal_name": "Willow Ward Community Trust",
        "applicant_type": "NONPROFIT",
        "contact_email": "hello@willowward.example",
        "nonprofit_registration_no": "NP-2026-0091",
    }
    defaults.update(overrides)
    return create_applicant(api, **defaults)


# ─── tier 2: registry mutations ──────────────────────────────────────────────
def post_code_violations(
    api: ApiClient,
    property_id: str,
    *,
    open_code_violation_count: int = 0,
    nuisance_complaint_count: int = 0,
) -> Dict[str, Any]:
    """Post the code-enforcement snapshot for a parcel."""
    payload = factories.code_violation_report_payload(
        open_code_violation_count=open_code_violation_count,
        nuisance_complaint_count=nuisance_complaint_count,
    )
    return get_success_data(
        api.post_code_violation_report(property_id, payload, INTAKE_1)
    )


def post_tax_roll(
    api: ApiClient,
    property_id: str,
    *,
    delinquent_tax_balance_cents: int,
    tax_year: int = 2026,
) -> Dict[str, Any]:
    """Post the county tax roll delinquency balance for a parcel."""
    payload = factories.tax_roll_posting_payload(
        delinquent_tax_balance_cents=delinquent_tax_balance_cents, tax_year=tax_year
    )
    return get_success_data(api.post_tax_roll_posting(property_id, payload, TREAS_1))


def set_owner_of_record(
    api: ApiClient, property_id: str, applicant_id: str
) -> Dict[str, Any]:
    """Record the private owner of record for a PROSPECT registry parcel."""
    return get_success_data(
        api.set_owner_of_record(property_id, {"applicant_id": applicant_id}, INTAKE_1)
    )


def create_adjacency(
    api: ApiClient,
    property_id: str,
    adjacent_property_id: str,
    shared_boundary_feet: float = 40,
) -> Dict[str, Any]:
    """Record a shared-boundary edge between two parcels."""
    payload = factories.parcel_adjacency_payload(
        property_id, adjacent_property_id, shared_boundary_feet=shared_boundary_feet
    )
    return get_success_data(api.create_parcel_adjacency(payload, INTAKE_1))


def create_reuse_hearing(api: ApiClient, property_id: str, **overrides: Any) -> Dict[str, Any]:
    """Record a community reuse-planning hearing for a parcel."""
    payload = factories.reuse_hearing_payload(**overrides)
    return get_success_data(api.create_reuse_hearing(property_id, payload, DISP_1))


# ─── tier 3: acquisition, title and inventory workflow ───────────────────────
def open_packet(
    api: ApiClient, property_id: str, funding_source_id: str, **overrides: Any
) -> Dict[str, Any]:
    """Open an acquisition packet against a PROSPECT parcel."""
    payload = factories.acquisition_packet_payload(
        property_id, funding_source_id, **overrides
    )
    return get_success_data(api.create_acquisition_packet(payload, INTAKE_1))


def board_approve_packet(
    api: ApiClient, packet_id: str, resolution_no: Optional[str] = None
) -> Dict[str, Any]:
    """Board-approve a packet in due diligence."""
    payload = {"resolution_no": resolution_no or next_resolution_no()}
    return get_success_data(api.board_approve_packet(packet_id, payload, CLERK_1))


def close_packet(
    api: ApiClient,
    packet_id: str,
    deed_reference: Optional[str] = None,
    headers: Dict[str, str] = INTAKE_2,
) -> Dict[str, Any]:
    """
    Close a board-approved packet. A different intake officer than the one who
    initiated the packet must perform this step.
    """
    payload = {"deed_reference": deed_reference or next_deed_reference()}
    return get_success_data(api.close_packet(packet_id, payload, headers))


def decline_packet(
    api: ApiClient, packet_id: str, declined_reason: str = "Title risk too high"
) -> Dict[str, Any]:
    """Decline a packet and release any commitment."""
    return get_success_data(
        api.decline_packet(packet_id, {"declined_reason": declined_reason}, INTAKE_1)
    )


def acquire_property(
    api: ApiClient, property_id: str, funding_source_id: str, **packet_overrides: Any
) -> Dict[str, Any]:
    """
    Drive one parcel from PROSPECT to ACQUIRED: open a packet, board-approve it
    and close it under a second intake officer. Returns the CLOSED packet.
    """
    packet = open_packet(api, property_id, funding_source_id, **packet_overrides)
    board_approve_packet(api, packet["id"])
    return close_packet(api, packet["id"])


def open_title_action(
    api: ApiClient, property_id: str, action_type: str = "QUIET_TITLE_SUIT"
) -> Dict[str, Any]:
    """Open a title-clearing action on a parcel."""
    payload = factories.title_action_payload(action_type=action_type)
    return get_success_data(api.create_title_action(property_id, payload, INTAKE_1))


def adjudicate_title_action(
    api: ApiClient,
    title_action_id: str,
    outcome: str = "CLEARED",
    defect_count: Optional[int] = None,
) -> Dict[str, Any]:
    """Adjudicate an open title action."""
    payload: Dict[str, Any] = {"outcome": outcome}
    if defect_count is not None:
        payload["defect_count"] = defect_count
    return get_success_data(
        api.adjudicate_title_action(title_action_id, payload, INTAKE_1)
    )


def clear_title(api: ApiClient, property_id: str) -> Dict[str, Any]:
    """Open and clear a quiet-title action, leaving the parcel's title CLEAR."""
    action = open_title_action(api, property_id)
    return adjudicate_title_action(api, action["id"], "CLEARED")


def list_parcel(api: ApiClient, property_id: str) -> Dict[str, Any]:
    """List an inventory parcel for disposition."""
    return get_success_data(api.list_property_for_disposition(property_id, DISP_1))


def schedule_order(
    api: ApiClient,
    property_id: str,
    *,
    funding_source_id: str,
    contractor_id: Optional[str] = None,
    work_type: str = "MOW",
    window_start: str = "2026-09-01T00:00:00Z",
    window_end: str = "2026-09-03T00:00:00Z",
    openings_count: Optional[int] = None,
    expected_property_version: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Schedule a maintenance order, re-reading the parcel's version first unless
    the caller pins one deliberately.
    """
    version = (
        expected_property_version
        if expected_property_version is not None
        else property_version(api, property_id)
    )
    payload = factories.maintenance_order_payload(
        contractor_id,
        funding_source_id,
        version,
        work_type=work_type,
        window_start=window_start,
        window_end=window_end,
    )
    if openings_count is not None:
        payload["openings_count"] = openings_count
    return get_success_data(
        api.create_maintenance_order(property_id, payload, INV_1)
    )


def complete_order(api: ApiClient, order_id: str, actual_cost_cents: int) -> Dict[str, Any]:
    """Complete a scheduled order with its actual cost."""
    return get_success_data(
        api.complete_maintenance_order(
            order_id, {"actual_cost_cents": actual_cost_cents}, INV_1
        )
    )


def cancel_order(
    api: ApiClient, order_id: str, cancelled_reason: str = "Work no longer required"
) -> Dict[str, Any]:
    """Cancel a scheduled order, returning its estimate to the funding source."""
    return get_success_data(
        api.cancel_maintenance_order(
            order_id, {"cancelled_reason": cancelled_reason}, INV_1
        )
    )


def plan_demolition_run(
    api: ApiClient,
    funding_source_id: str,
    budget_cents: int,
    *,
    situs_ward_filter: Optional[int] = None,
    expected_funding_source_version: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Plan a demolition prioritization run, re-reading the funding source's
    version first unless the caller pins one deliberately.
    """
    version = (
        expected_funding_source_version
        if expected_funding_source_version is not None
        else funding_source_version(api, funding_source_id)
    )
    payload = factories.demolition_run_payload(funding_source_id, budget_cents, version)
    if situs_ward_filter is not None:
        payload["situs_ward_filter"] = situs_ward_filter
    return get_success_data(api.create_demolition_run(payload, INV_1))


def execute_demolition_run(api: ApiClient, run_id: str) -> Dict[str, Any]:
    """Execute a planned run."""
    return get_success_data(api.execute_demolition_run(run_id, INV_1))


def run_compliance_sweep(api: ApiClient) -> Dict[str, Any]:
    """Run the periodic compliance sweep at the current logical clock."""
    return get_success_data(api.run_compliance_sweep(INV_1))


def post_tif_recapture(
    api: ApiClient, funding_source_id: str, recapture_cents: int, tax_year: int = 2026
) -> Dict[str, Any]:
    """Book a tax-increment recapture receipt onto a funding source."""
    return get_success_data(
        api.post_tif_recapture(
            funding_source_id,
            {"recapture_cents": recapture_cents, "tax_year": tax_year},
            TREAS_1,
        )
    )


# ─── tier 4: disposition workflow ────────────────────────────────────────────
def draft_application(
    api: ApiClient, property_id: str, applicant_id: str, **overrides: Any
) -> Dict[str, Any]:
    """Draft a disposition application for a listed parcel."""
    payload = factories.disposition_application_payload(
        property_id, applicant_id, **overrides
    )
    return get_success_data(api.create_disposition_application(payload, DISP_1))


def submit_application(
    api: ApiClient, application_id: str, applicant_id: str
) -> Dict[str, Any]:
    """Submit a draft application as its own applicant."""
    return get_success_data(
        api.submit_application(application_id, make_applicant_headers(applicant_id))
    )


def screen_application(
    api: ApiClient, application_id: str, headers: Dict[str, str] = DISP_1
) -> Dict[str, Any]:
    """Run a buyer eligibility screening and return the screening record."""
    return get_success_data(api.screen_application(application_id, headers))


def request_info(
    api: ApiClient,
    application_id: str,
    information_requested: str = "Provide a proof-of-funds letter",
) -> Dict[str, Any]:
    """Return a screened application to the applicant for more information."""
    return get_success_data(
        api.request_info(
            application_id, {"information_requested": information_requested}, DISP_1
        )
    )


def resubmit_application(
    api: ApiClient, application_id: str, applicant_id: str, **overrides: Any
) -> Dict[str, Any]:
    """Resubmit an application with a revised offer or use."""
    return get_success_data(
        api.resubmit_application(
            application_id, dict(overrides), make_applicant_headers(applicant_id)
        )
    )


def recommend_application(
    api: ApiClient,
    application_id: str,
    recommendation_memo: str = "Sole responsive offer on the parcel.",
    headers: Dict[str, str] = DISP_2,
) -> Dict[str, Any]:
    """
    Recommend a screened application. A different disposition officer than the
    one who performed the governing screening must do this.
    """
    return get_success_data(
        api.recommend_application(
            application_id, {"recommendation_memo": recommendation_memo}, headers
        )
    )


def board_decide(
    api: ApiClient,
    application_id: str,
    decision: str = "APPROVE",
    resolution_no: Optional[str] = None,
    denial_reason: Optional[str] = None,
) -> Dict[str, Any]:
    """Record the board's decision on a recommended application."""
    payload: Dict[str, Any] = {
        "decision": decision,
        "resolution_no": resolution_no or next_resolution_no(),
    }
    if denial_reason is not None:
        payload["denial_reason"] = denial_reason
    return get_success_data(api.board_decision(application_id, payload, CLERK_1))


def execute_agreement(api: ApiClient, application_id: str, **overrides: Any) -> Dict[str, Any]:
    """Execute the development agreement for a board-approved application."""
    payload = factories.development_agreement_payload(application_id, **overrides)
    return get_success_data(api.create_development_agreement(payload, CLERK_1))


def report_milestones(
    api: ApiClient,
    agreement_id: str,
    applicant_id: str,
    completed_count: int,
    evidence_reference: str = "PERMIT-2026-0001",
) -> Dict[str, Any]:
    """Report completed development milestones as the agreement's applicant."""
    return get_success_data(
        api.report_milestone_completions(
            agreement_id,
            {
                "completed_count": completed_count,
                "evidence_reference": evidence_reference,
            },
            make_applicant_headers(applicant_id),
        )
    )


# ─── tier 5: whole-chain scenarios ───────────────────────────────────────────
def acquired_parcel(
    api: ApiClient,
    *,
    funding_source: Optional[Dict[str, Any]] = None,
    property_overrides: Optional[Dict[str, Any]] = None,
    packet_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    An ACQUIRED parcel in inventory, with the funding source that paid for it.

    Returns ``{"funding_source", "property", "packet"}`` where ``property`` is
    re-read after the close so its acquisition fields are populated.
    """
    fs = funding_source or create_funding_source(api)
    prop = create_property(api, **(property_overrides or {}))
    packet = acquire_property(
        api, prop["id"], fs["id"], **(packet_overrides or {})
    )
    return {
        "funding_source": read_funding_source(api, fs["id"]),
        "property": read_property(api, prop["id"]),
        "packet": packet,
    }


def listed_parcel(
    api: ApiClient,
    *,
    funding_source: Optional[Dict[str, Any]] = None,
    property_overrides: Optional[Dict[str, Any]] = None,
    packet_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    A parcel driven all the way to LISTED: acquired, quiet-titled CLEAR and
    listed for disposition.

    Returns ``{"funding_source", "property", "packet", "title_action"}``.
    """
    bundle = acquired_parcel(
        api,
        funding_source=funding_source,
        property_overrides=property_overrides,
        packet_overrides=packet_overrides,
    )
    action = open_title_action(api, bundle["property"]["id"])
    adjudicate_title_action(api, action["id"], "CLEARED")
    list_parcel(api, bundle["property"]["id"])
    bundle["title_action"] = action
    bundle["property"] = read_property(api, bundle["property"]["id"])
    bundle["funding_source"] = read_funding_source(
        api, bundle["funding_source"]["id"]
    )
    return bundle


def screened_application(
    api: ApiClient,
    *,
    funding_source: Optional[Dict[str, Any]] = None,
    property_overrides: Optional[Dict[str, Any]] = None,
    packet_overrides: Optional[Dict[str, Any]] = None,
    applicant: Optional[Dict[str, Any]] = None,
    application_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    A listed parcel with one application submitted and screened.

    Returns the ``listed_parcel`` bundle plus ``{"applicant", "application",
    "screening"}``. The application is re-read after screening.
    """
    bundle = listed_parcel(
        api,
        funding_source=funding_source,
        property_overrides=property_overrides,
        packet_overrides=packet_overrides,
    )
    buyer = applicant or create_developer_applicant(api)
    application = draft_application(
        api,
        bundle["property"]["id"],
        buyer["id"],
        **(application_overrides or {}),
    )
    submit_application(api, application["id"], buyer["id"])
    screening = screen_application(api, application["id"])
    bundle["applicant"] = buyer
    bundle["application"] = read_application(api, application["id"])
    bundle["screening"] = screening
    return bundle


def awarded_parcel(
    api: ApiClient,
    *,
    funding_source: Optional[Dict[str, Any]] = None,
    property_overrides: Optional[Dict[str, Any]] = None,
    packet_overrides: Optional[Dict[str, Any]] = None,
    applicant: Optional[Dict[str, Any]] = None,
    application_overrides: Optional[Dict[str, Any]] = None,
    agreement_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    A parcel conveyed under an executed development agreement: the full chain
    from acquisition through screening, recommendation, board approval and
    agreement execution.

    Returns the ``screened_application`` bundle plus ``{"agreement"}``, with the
    parcel and application re-read after conveyance.
    """
    bundle = screened_application(
        api,
        funding_source=funding_source,
        property_overrides=property_overrides,
        packet_overrides=packet_overrides,
        applicant=applicant,
        application_overrides=application_overrides,
    )
    application_id = bundle["application"]["id"]
    recommend_application(api, application_id)
    board_decide(api, application_id, "APPROVE")
    agreement = execute_agreement(
        api, application_id, **(agreement_overrides or {})
    )
    bundle["agreement"] = agreement
    bundle["application"] = read_application(api, application_id)
    bundle["property"] = read_property(api, bundle["property"]["id"])
    return bundle


def demolition_candidate(
    api: ApiClient,
    funding_source_id: str,
    *,
    parcel_id: Optional[str] = None,
    address: str = "1 Candidate Row",
    situs_ward: int = 3,
    lot_area_sqft: int = 8000,
    assessed_value_cents: int = 200000,
    structure_condition_grade: str = "F",
    vacancy_months: int = 24,
    nuisance_complaint_count: Optional[int] = None,
    open_code_violation_count: Optional[int] = None,
) -> Dict[str, Any]:
    """
    An ACQUIRED, quiet-titled parcel that still carries a structure - the shape
    a demolition prioritization run looks for. Code-enforcement counts are
    posted before acquisition so the parcel's blight score reflects them.

    Returns the parcel as re-read after title clearing.
    """
    overrides: Dict[str, Any] = {
        "address": address,
        "situs_ward": situs_ward,
        "lot_area_sqft": lot_area_sqft,
        "assessed_value_cents": assessed_value_cents,
        "structure_present": True,
        "structure_condition_grade": structure_condition_grade,
        "vacancy_months": vacancy_months,
    }
    if parcel_id is not None:
        overrides["parcel_id"] = parcel_id
    prop = create_property(api, **overrides)
    if nuisance_complaint_count is not None or open_code_violation_count is not None:
        post_code_violations(
            api,
            prop["id"],
            open_code_violation_count=open_code_violation_count or 0,
            nuisance_complaint_count=nuisance_complaint_count or 0,
        )
    acquire_property(api, prop["id"], funding_source_id)
    clear_title(api, prop["id"])
    return read_property(api, prop["id"])


def list_orders(
    api: ApiClient, **params: Any
) -> List[Dict[str, Any]]:
    """List maintenance orders under the given filters."""
    return get_success_data(api.list_maintenance_orders(INV_1, dict(params)))
