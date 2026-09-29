"""Composite setup builders for the Timberland Investment Management API.

Every test starts against an empty database, so all preconditions are built here
through the API itself. These helpers use `get_success_data`, which accepts any
2xx response, so that setup steps fail loudly with the server's own error
identifier rather than through an opaque KeyError.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from prd_bench_local_runner.testing import get_success_data

from .api_client import ApiClient
from .factories import (
    CANONICAL_CRUISE_PLOTS,
    CANONICAL_MEASURED_AT,
    audit_finding_payload,
    carbon_dedication_payload,
    carbon_project_payload,
    certification_audit_payload,
    cruise_plot_payload,
    fund_payload,
    harvest_block_payload,
    hazard_event_payload,
    hbu_parcel_payload,
    market_appraisal_submit_payload,
    property_payload,
    recreational_lease_payload,
    stand_payload,
    underwriting_case_payload,
)
from .test_users import (
    make_analyst_headers,
    make_appraiser_headers,
    make_auditor_headers,
    make_carbon_developer_headers,
    make_committee_headers,
    make_forest_manager_headers,
    make_fund_admin_headers,
    APPRAISER_1,
    APPRAISER_2,
)

# ---------------------------------------------------------------------------
# Small readers
# ---------------------------------------------------------------------------


def set_clock(client: ApiClient, current_utc: str) -> Dict[str, Any]:
    return get_success_data(client.set_clock(current_utc, make_fund_admin_headers()))


def read_fund(client: ApiClient, fund_id: str) -> Dict[str, Any]:
    return get_success_data(client.get_fund(fund_id, make_fund_admin_headers()))


def read_property(client: ApiClient, property_id: str) -> Dict[str, Any]:
    return get_success_data(client.get_property(property_id, make_fund_admin_headers()))


def read_case(client: ApiClient, case_id: str) -> Dict[str, Any]:
    return get_success_data(
        client.get_underwriting_case(case_id, make_fund_admin_headers())
    )


def read_stand(client: ApiClient, stand_id: str) -> Dict[str, Any]:
    return get_success_data(client.get_stand(stand_id, make_fund_admin_headers()))


def read_block(client: ApiClient, block_id: str) -> Dict[str, Any]:
    return get_success_data(client.get_harvest_block(block_id, make_fund_admin_headers()))


def read_carbon_project(client: ApiClient, project_id: str) -> Dict[str, Any]:
    return get_success_data(client.get_carbon_project(project_id, make_fund_admin_headers()))


def read_dedication(client: ApiClient, dedication_id: str) -> Dict[str, Any]:
    return get_success_data(
        client.get_carbon_dedication(dedication_id, make_fund_admin_headers())
    )


def read_parcel(client: ApiClient, parcel_id: str) -> Dict[str, Any]:
    return get_success_data(client.get_hbu_parcel(parcel_id, make_fund_admin_headers()))


def read_lease(client: ApiClient, lease_id: str) -> Dict[str, Any]:
    return get_success_data(
        client.get_recreational_lease(lease_id, make_fund_admin_headers())
    )


def read_audit(client: ApiClient, audit_id: str) -> Dict[str, Any]:
    return get_success_data(
        client.get_certification_audit(audit_id, make_fund_admin_headers())
    )


def read_finding(client: ApiClient, finding_id: str) -> Dict[str, Any]:
    return get_success_data(client.get_audit_finding(finding_id, make_fund_admin_headers()))


def read_hazard_event(client: ApiClient, event_id: str) -> Dict[str, Any]:
    return get_success_data(client.get_hazard_event(event_id, make_fund_admin_headers()))


def read_investor_report(client: ApiClient, fund_id: str) -> Dict[str, Any]:
    return get_success_data(client.get_investor_report(fund_id, make_fund_admin_headers()))


def stand_version(client: ApiClient, stand_id: str) -> int:
    return int(read_stand(client, stand_id)["version"])


def property_version(client: ApiClient, property_id: str) -> int:
    return int(read_property(client, property_id)["version"])


def fund_version(client: ApiClient, fund_id: str) -> int:
    return int(read_fund(client, fund_id)["version"])


# ---------------------------------------------------------------------------
# Tier 1 — single-entity creation
# ---------------------------------------------------------------------------


def create_fund(client: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        client.create_fund(fund_payload(**overrides), make_fund_admin_headers())
    )


def create_property(client: ApiClient, fund_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        client.create_property(
            property_payload(fund_id, **overrides), make_analyst_headers()
        )
    )


def create_stand(client: ApiClient, property_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        client.create_stand(
            stand_payload(property_id, **overrides), make_forest_manager_headers()
        )
    )


def record_cruise_plot(client: ApiClient, stand_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        client.create_cruise_plot(
            cruise_plot_payload(stand_id, **overrides), make_forest_manager_headers()
        )
    )


def close_cruise(client: ApiClient, stand_id: str) -> Dict[str, Any]:
    return get_success_data(client.close_cruise(stand_id, None, make_forest_manager_headers()))


# ---------------------------------------------------------------------------
# Tier 2 — the cruised tract
# ---------------------------------------------------------------------------


@dataclass
class TractContext:
    """A fund, a tract and one cruised stand on it."""

    fund: Dict[str, Any]
    tract: Dict[str, Any]
    stand: Dict[str, Any]
    plots: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def fund_id(self) -> str:
        return self.fund["id"]

    @property
    def property_id(self) -> str:
        return self.tract["id"]

    @property
    def stand_id(self) -> str:
        return self.stand["id"]


def cruised_stand(
    client: ApiClient,
    plots: Sequence[Dict[str, Any]] = CANONICAL_CRUISE_PLOTS,
    measured_at: str = CANONICAL_MEASURED_AT,
    fund_overrides: Optional[Dict[str, Any]] = None,
    property_overrides: Optional[Dict[str, Any]] = None,
    stand_overrides: Optional[Dict[str, Any]] = None,
) -> TractContext:
    """Fund, tract, stand, the supplied cruise plots, and a closed cruise.

    With the five canonical plots on 120.00 acres this lands the stand in
    `INVENTORIED` at `NORMAL` confidence with 4647.12 net merchantable tons.
    """
    fund = create_fund(client, **(fund_overrides or {}))
    tract = create_property(client, fund["id"], **(property_overrides or {}))
    stand = create_stand(client, tract["id"], **(stand_overrides or {}))
    recorded = [
        record_cruise_plot(client, stand["id"], measured_at=measured_at, **plot)
        for plot in plots
    ]
    stand = close_cruise(client, stand["id"])
    return TractContext(fund=fund, tract=tract, stand=stand, plots=recorded)


def open_cruise_stand(
    client: ApiClient,
    fund_overrides: Optional[Dict[str, Any]] = None,
    property_overrides: Optional[Dict[str, Any]] = None,
    stand_overrides: Optional[Dict[str, Any]] = None,
) -> TractContext:
    """Fund, tract and a freshly created stand whose cruise is still open."""
    fund = create_fund(client, **(fund_overrides or {}))
    tract = create_property(client, fund["id"], **(property_overrides or {}))
    stand = create_stand(client, tract["id"], **(stand_overrides or {}))
    return TractContext(fund=fund, tract=tract, stand=stand)


# ---------------------------------------------------------------------------
# Tier 3 — appraisal, underwriting and the acquisition closing
# ---------------------------------------------------------------------------


def submit_appraisal(
    client: ApiClient,
    property_id: str,
    payload: Optional[Dict[str, Any]] = None,
    submitter: str = APPRAISER_1,
) -> Dict[str, Any]:
    body = payload if payload is not None else market_appraisal_submit_payload()
    return get_success_data(
        client.appraisal_action(property_id, body, make_appraiser_headers(submitter))
    )


def sign_appraisal(
    client: ApiClient, property_id: str, signer: str = APPRAISER_2
) -> Dict[str, Any]:
    return get_success_data(
        client.appraisal_action(
            property_id, {"action": "SIGN"}, make_appraiser_headers(signer)
        )
    )


def invalidate_appraisal(
    client: ApiClient, property_id: str, actor: str = APPRAISER_1
) -> Dict[str, Any]:
    return get_success_data(
        client.appraisal_action(
            property_id, {"action": "INVALIDATE"}, make_appraiser_headers(actor)
        )
    )


def signed_appraisal(
    client: ApiClient,
    property_id: str,
    payload: Optional[Dict[str, Any]] = None,
    submitter: str = APPRAISER_1,
    signer: str = APPRAISER_2,
) -> Dict[str, Any]:
    """Submit an appraisal and countersign it with a different appraiser."""
    submit_appraisal(client, property_id, payload, submitter)
    return sign_appraisal(client, property_id, signer)


def create_case(
    client: ApiClient,
    property_id: str,
    author: str = "analyst-1",
    expected_property_version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    version = (
        expected_property_version
        if expected_property_version is not None
        else property_version(client, property_id)
    )
    return get_success_data(
        client.create_underwriting_case(
            underwriting_case_payload(property_id, version, **overrides),
            make_analyst_headers(author),
        )
    )


def submit_case(
    client: ApiClient, case_id: str, author: str = "analyst-1"
) -> Dict[str, Any]:
    return get_success_data(
        client.submit_underwriting_case(case_id, None, make_analyst_headers(author))
    )


def decide_case(
    client: ApiClient,
    case_id: str,
    decision: str = "APPROVE",
    decider: str = "ic-1",
    decision_note: Optional[str] = None,
) -> Dict[str, Any]:
    body: Dict[str, Any] = {"decision": decision}
    if decision_note is not None:
        body["decision_note"] = decision_note
    return get_success_data(
        client.decide_underwriting_case(case_id, body, make_committee_headers(decider))
    )


def approved_case(
    client: ApiClient,
    property_id: str,
    author: str = "analyst-1",
    decider: str = "ic-1",
    **overrides: Any,
) -> Dict[str, Any]:
    """Open a case, submit it, and have the committee approve it."""
    case = create_case(client, property_id, author=author, **overrides)
    submit_case(client, case["id"], author=author)
    return decide_case(client, case["id"], "APPROVE", decider)


def acquire(
    client: ApiClient,
    property_id: str,
    case_id: str,
    fund_id: str,
    expected_fund_version: Optional[int] = None,
) -> Dict[str, Any]:
    version = (
        expected_fund_version
        if expected_fund_version is not None
        else fund_version(client, fund_id)
    )
    return get_success_data(
        client.acquire_property(
            property_id,
            {"underwriting_case_id": case_id, "expected_fund_version": version},
            make_fund_admin_headers(),
        )
    )


@dataclass
class OwnedTractContext(TractContext):
    """A cruised tract taken all the way to `OWNED` with a signed appraisal."""

    case: Dict[str, Any] = field(default_factory=dict)

    @property
    def case_id(self) -> str:
        return self.case["id"]


def owned_tract(
    client: ApiClient,
    plots: Sequence[Dict[str, Any]] = CANONICAL_CRUISE_PLOTS,
    fund_overrides: Optional[Dict[str, Any]] = None,
    property_overrides: Optional[Dict[str, Any]] = None,
    stand_overrides: Optional[Dict[str, Any]] = None,
    appraisal_payload: Optional[Dict[str, Any]] = None,
    case_overrides: Optional[Dict[str, Any]] = None,
) -> OwnedTractContext:
    """The full acquisition chain: cruise, signed appraisal, approved case, closing.

    With the canonical figures the fund ends with 300000.00 of cash against a
    3900000.00 appraised value and a 4200000.00 net asset value.
    """
    ctx = cruised_stand(
        client,
        plots=plots,
        fund_overrides=fund_overrides,
        property_overrides=property_overrides,
        stand_overrides=stand_overrides,
    )
    signed_appraisal(client, ctx.property_id, appraisal_payload)
    case = approved_case(client, ctx.property_id, **(case_overrides or {}))
    tract = acquire(client, ctx.property_id, case["id"], ctx.fund_id)
    return OwnedTractContext(
        fund=read_fund(client, ctx.fund_id),
        tract=tract,
        stand=read_stand(client, ctx.stand_id),
        plots=ctx.plots,
        case=case,
    )


# ---------------------------------------------------------------------------
# Tier 4 — harvest blocks
# ---------------------------------------------------------------------------


def reserve_block(
    client: ApiClient,
    stand_id: str,
    expected_stand_version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    version = (
        expected_stand_version
        if expected_stand_version is not None
        else stand_version(client, stand_id)
    )
    return get_success_data(
        client.create_harvest_block(
            harvest_block_payload(stand_id, version, **overrides),
            make_forest_manager_headers(),
        )
    )


def commit_block(client: ApiClient, block_id: str) -> Dict[str, Any]:
    return get_success_data(
        client.commit_harvest_block(block_id, None, make_forest_manager_headers())
    )


def committed_block(client: ApiClient, stand_id: str, **overrides: Any) -> Dict[str, Any]:
    block = reserve_block(client, stand_id, **overrides)
    return commit_block(client, block["id"])


def complete_block(
    client: ApiClient,
    block_id: str,
    actual_tons: float,
    realized_price_index_factor: float,
) -> Dict[str, Any]:
    return get_success_data(
        client.close_harvest_block(
            block_id,
            {
                "action": "COMPLETE",
                "actual_tons": actual_tons,
                "realized_price_index_factor": realized_price_index_factor,
            },
            make_forest_manager_headers(),
        )
    )


def cancel_block(client: ApiClient, block_id: str) -> Dict[str, Any]:
    return get_success_data(
        client.close_harvest_block(
            block_id, {"action": "CANCEL"}, make_forest_manager_headers()
        )
    )


def completed_block(
    client: ApiClient,
    stand_id: str,
    actual_tons: float = 940.50,
    realized_price_index_factor: float = 0.92,
    **overrides: Any,
) -> Dict[str, Any]:
    """Reserve, commit and complete one block on the stand."""
    block = committed_block(client, stand_id, **overrides)
    return complete_block(client, block["id"], actual_tons, realized_price_index_factor)


# ---------------------------------------------------------------------------
# Tier 4 — carbon projects and dedications
# ---------------------------------------------------------------------------


def create_carbon_project(
    client: ApiClient, property_id: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        client.create_carbon_project(
            carbon_project_payload(property_id, **overrides),
            make_carbon_developer_headers(),
        )
    )


def dedicate(
    client: ApiClient,
    project_id: str,
    stand_id: str,
    expected_stand_version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    version = (
        expected_stand_version
        if expected_stand_version is not None
        else stand_version(client, stand_id)
    )
    return get_success_data(
        client.create_carbon_dedication(
            carbon_dedication_payload(project_id, stand_id, version, **overrides),
            make_carbon_developer_headers(),
        )
    )


def advance_carbon_project(
    client: ApiClient, project_id: str, action: str, **body: Any
) -> Dict[str, Any]:
    payload = {"action": action}
    payload.update(body)
    return get_success_data(
        client.advance_carbon_project(project_id, payload, make_carbon_developer_headers())
    )


def release_dedication(
    client: ApiClient, dedication_id: str, release_reason: Optional[str] = None
) -> Dict[str, Any]:
    payload = {} if release_reason is None else {"release_reason": release_reason}
    return get_success_data(
        client.release_carbon_dedication(
            dedication_id, payload, make_carbon_developer_headers()
        )
    )


@dataclass
class CarbonContext:
    project: Dict[str, Any]
    dedications: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def project_id(self) -> str:
        return self.project["id"]

    @property
    def dedication_id(self) -> str:
        return self.dedications[0]["id"]


def pending_carbon_project(
    client: ApiClient,
    property_id: str,
    stand_id: str,
    dedicated_tons: float = 500.00,
    project_overrides: Optional[Dict[str, Any]] = None,
) -> CarbonContext:
    """A DRAFT project with one PENDING dedication drawn against the stand."""
    project = create_carbon_project(client, property_id, **(project_overrides or {}))
    dedication = dedicate(client, project["id"], stand_id, dedicated_tons=dedicated_tons)
    return CarbonContext(project=read_carbon_project(client, project["id"]),
                         dedications=[dedication])


def registered_carbon_project(
    client: ApiClient,
    property_id: str,
    stand_id: str,
    dedicated_tons: float = 500.00,
    project_overrides: Optional[Dict[str, Any]] = None,
) -> CarbonContext:
    """A project pledged, submitted for validation and registered.

    Registration activates the pending dedication, stamps its
    `permanence_end_date` and fixes the eighteen percent buffer pool.
    """
    ctx = pending_carbon_project(
        client, property_id, stand_id, dedicated_tons, project_overrides
    )
    advance_carbon_project(client, ctx.project_id, "SUBMIT_VALIDATION")
    project = advance_carbon_project(client, ctx.project_id, "REGISTER")
    return CarbonContext(
        project=project,
        dedications=[read_dedication(client, d["id"]) for d in ctx.dedications],
    )


# ---------------------------------------------------------------------------
# Tier 4 — recreational leases
# ---------------------------------------------------------------------------


def create_lease(client: ApiClient, property_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        client.create_recreational_lease(
            recreational_lease_payload(property_id, **overrides), make_fund_admin_headers()
        )
    )


def activate_lease(client: ApiClient, lease_id: str) -> Dict[str, Any]:
    return get_success_data(
        client.activate_recreational_lease(lease_id, None, make_fund_admin_headers())
    )


def active_lease(client: ApiClient, property_id: str, **overrides: Any) -> Dict[str, Any]:
    lease = create_lease(client, property_id, **overrides)
    return activate_lease(client, lease["id"])


def terminate_lease(
    client: ApiClient, lease_id: str, termination_effective_date: str
) -> Dict[str, Any]:
    return get_success_data(
        client.terminate_recreational_lease(
            lease_id,
            {"termination_effective_date": termination_effective_date},
            make_fund_admin_headers(),
        )
    )


# ---------------------------------------------------------------------------
# Tier 4 — certification audits, findings and the corrective-action cycle
# ---------------------------------------------------------------------------


def schedule_audit(client: ApiClient, property_id: str, auditor: str = "ca-1", **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        client.create_certification_audit(
            certification_audit_payload(property_id, **overrides),
            make_auditor_headers(auditor),
        )
    )


def advance_audit(
    client: ApiClient, audit_id: str, action: str, auditor: str = "ca-1"
) -> Dict[str, Any]:
    return get_success_data(
        client.advance_certification_audit(
            audit_id, {"action": action}, make_auditor_headers(auditor)
        )
    )


def audit_in_findings_issued(
    client: ApiClient, property_id: str, auditor: str = "ca-1", **overrides: Any
) -> Dict[str, Any]:
    """Schedule an audit, start field work and issue findings."""
    audit = schedule_audit(client, property_id, auditor, **overrides)
    advance_audit(client, audit["id"], "START_FIELD_WORK", auditor)
    return advance_audit(client, audit["id"], "ISSUE_FINDINGS", auditor)


def raise_finding(
    client: ApiClient, audit_id: str, auditor: str = "ca-1", **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        client.create_audit_finding(
            audit_id, audit_finding_payload(**overrides), make_auditor_headers(auditor)
        )
    )


def transition_finding(
    client: ApiClient,
    finding_id: str,
    action: str,
    headers: Dict[str, str],
    **body: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"action": action}
    payload.update(body)
    return get_success_data(client.transition_audit_finding(finding_id, payload, headers))


def submit_car(
    client: ApiClient,
    finding_id: str,
    manager: str = "fm-1",
    car_text: str = "Buffer strip re-flagged and crew retrained.",
) -> Dict[str, Any]:
    return transition_finding(
        client,
        finding_id,
        "SUBMIT_CAR",
        make_forest_manager_headers(manager),
        car_text=car_text,
    )


def reject_car(client: ApiClient, finding_id: str, auditor: str = "ca-1") -> Dict[str, Any]:
    return transition_finding(
        client, finding_id, "REJECT_CAR", make_auditor_headers(auditor)
    )


def verify_close_car(
    client: ApiClient, finding_id: str, auditor: str = "ca-2"
) -> Dict[str, Any]:
    return transition_finding(
        client, finding_id, "VERIFY_CLOSE", make_auditor_headers(auditor)
    )


@dataclass
class AuditContext:
    audit: Dict[str, Any]
    findings: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def audit_id(self) -> str:
        return self.audit["id"]

    @property
    def finding_id(self) -> str:
        return self.findings[0]["id"]


def audit_with_open_findings(
    client: ApiClient,
    property_id: str,
    severities: Sequence[str] = ("MINOR",),
    auditor: str = "ca-1",
) -> AuditContext:
    """An audit in FINDINGS_ISSUED carrying one open finding per requested severity."""
    audit = audit_in_findings_issued(client, property_id, auditor)
    findings = [
        raise_finding(
            client,
            audit["id"],
            auditor,
            severity=severity,
            finding_code=f"SFI-{index + 1}.1",
            indicator_ref=f"{index + 1}.1.3",
        )
        for index, severity in enumerate(severities)
    ]
    return AuditContext(audit=read_audit(client, audit["id"]), findings=findings)


def suspended_tract(
    client: ApiClient, property_id: str, auditor: str = "ca-1"
) -> AuditContext:
    """Drive a tract's certification posture to SUSPENDED with two open majors."""
    return audit_with_open_findings(client, property_id, ("MAJOR", "MAJOR"), auditor)


# ---------------------------------------------------------------------------
# Tier 4 — HBU parcels
# ---------------------------------------------------------------------------


def identify_parcel(client: ApiClient, stand_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        client.create_hbu_parcel(
            hbu_parcel_payload(stand_id, **overrides), make_fund_admin_headers()
        )
    )


def advance_parcel(
    client: ApiClient, parcel_id: str, action: str, **body: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"action": action}
    payload.update(body)
    return get_success_data(
        client.advance_hbu_parcel(parcel_id, payload, make_fund_admin_headers())
    )


def listed_parcel(client: ApiClient, stand_id: str, **overrides: Any) -> Dict[str, Any]:
    parcel = identify_parcel(client, stand_id, **overrides)
    return advance_parcel(client, parcel["id"], "LIST")


def contracted_parcel(
    client: ApiClient,
    stand_id: str,
    contract_price_usd: float = 285000.00,
    **overrides: Any,
) -> Dict[str, Any]:
    parcel = listed_parcel(client, stand_id, **overrides)
    return advance_parcel(
        client, parcel["id"], "CONTRACT", contract_price_usd=contract_price_usd
    )


def close_parcel(
    client: ApiClient, parcel_id: str, closing_costs_usd: float = 4200.00
) -> Dict[str, Any]:
    return advance_parcel(
        client, parcel_id, "CLOSE", closing_costs_usd=closing_costs_usd
    )


# ---------------------------------------------------------------------------
# Tier 4 — hazard events and insurance
# ---------------------------------------------------------------------------


def report_hazard(client: ApiClient, stand_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        client.create_hazard_event(
            hazard_event_payload(stand_id, **overrides), make_forest_manager_headers()
        )
    )


def settle_hazard(
    client: ApiClient, event_id: str, settled_claim_usd: float, salvage_sold_tons: float
) -> Dict[str, Any]:
    return get_success_data(
        client.settle_hazard_event(
            event_id,
            {
                "settled_claim_usd": settled_claim_usd,
                "salvage_sold_tons": salvage_sold_tons,
            },
            make_fund_admin_headers(),
        )
    )


def record_risk_review(
    client: ApiClient, property_id: str, payload: Dict[str, Any]
) -> Dict[str, Any]:
    return get_success_data(
        client.risk_review(property_id, payload, make_fund_admin_headers())
    )
