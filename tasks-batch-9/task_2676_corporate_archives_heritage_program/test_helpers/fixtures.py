"""Composite state builders.

Every test starts against an empty database, so any state a test needs must be
built through the public API. The builders here compose the declared endpoints
into the recurring shapes the suite needs — a processed holding, a request
sitting under screening, an activated plan carrying an approved job, a dually
cleared proposal — and they always read the affected rows back so the caller
receives freshly reconciled server state rather than stale create responses.

Builders use the lenient ``setup`` validator: a failure inside a builder is a
broken precondition, not the assertion the test is making.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from . import factories as f
from .api_client import ApiClient
from .assertions import setup
from .test_users import (
    ARCHIVIST_A,
    COUNSEL_A,
    DIRECTOR_A,
    OFFICER_A,
    OFFICER_B,
    OPERATOR,
    PRESERV_A,
    PRESERV_B,
    make_requester_headers,
)

Row = Dict[str, Any]


# ═══ Logical clock ════════════════════════════════════════════════════════

def set_clock(client: ApiClient, current_utc: str) -> Row:
    """Move the server's logical UTC clock."""
    return setup(client.set_clock(current_utc, OPERATOR))


# ═══ Tier 1: single rows ══════════════════════════════════════════════════

def make_schedule(client: ApiClient, **overrides) -> Row:
    return setup(
        client.create_retention_schedule(
            f.retention_schedule_payload(**overrides), DIRECTOR_A
        )
    )


def make_series(
    client: ApiClient, schedule_id: Optional[str] = None, *, schedule_overrides=None,
    **overrides,
) -> Row:
    if schedule_id is None:
        schedule_id = make_schedule(client, **(schedule_overrides or {}))["id"]
    return setup(
        client.create_record_series(
            f.record_series_payload(schedule_id, **overrides), ARCHIVIST_A
        )
    )


def make_zone(client: ApiClient, **overrides) -> Row:
    return setup(client.create_storage_zone(f.storage_zone_payload(**overrides), PRESERV_A))


def make_accession(client: ApiClient, series_id: str, **overrides) -> Row:
    return setup(
        client.create_accession(f.accession_payload(series_id, **overrides), ARCHIVIST_A)
    )


def make_item(client: ApiClient, accession_id: str, zone_id: str, **overrides) -> Row:
    return setup(
        client.create_archival_item(
            f.archival_item_payload(accession_id, zone_id, **overrides), ARCHIVIST_A
        )
    )


def make_requester(client: ApiClient, **overrides) -> Row:
    return setup(client.create_requester(f.requester_payload(**overrides), OFFICER_A))


def read_series(client: ApiClient, series_id: str) -> Row:
    return setup(client.get_record_series(series_id, ARCHIVIST_A))


def read_accession(client: ApiClient, accession_id: str) -> Row:
    return setup(client.get_accession(accession_id, ARCHIVIST_A))


def read_item(client: ApiClient, item_id: str) -> Row:
    return setup(client.get_archival_item(item_id, ARCHIVIST_A))


def read_zone(client: ApiClient, zone_id: str) -> Row:
    return setup(client.get_storage_zone(zone_id, PRESERV_A))


def read_plan(client: ApiClient, plan_id: str) -> Row:
    return setup(client.get_preservation_plan(plan_id, PRESERV_A))


def read_job(client: ApiClient, job_id: str) -> Row:
    return setup(client.get_migration_job(job_id, PRESERV_A))


def read_request(client: ApiClient, request_id: str) -> Row:
    return setup(client.get_access_request(request_id, OFFICER_A))


def read_screening(client: ApiClient, screening_id: str) -> Row:
    return setup(client.get_screening(screening_id, OFFICER_A))


def read_finding_aid(client: ApiClient, aid_id: str) -> Row:
    return setup(client.get_finding_aid(aid_id, ARCHIVIST_A))


def read_loan(client: ApiClient, loan_id: str) -> Row:
    return setup(client.get_exhibit_loan(loan_id, ARCHIVIST_A))


def read_proposal(client: ApiClient, proposal_id: str) -> Row:
    return setup(client.get_deaccession_proposal(proposal_id, ARCHIVIST_A))


def read_appraisal(client: ApiClient, appraisal_id: str) -> Row:
    return setup(client.get_appraisal(appraisal_id, ARCHIVIST_A))


def read_hold(client: ApiClient, hold_id: str) -> Row:
    return setup(client.get_legal_hold(hold_id, COUNSEL_A))


def read_package(client: ApiClient, package_id: str) -> Row:
    return setup(client.get_evidence_package(package_id, COUNSEL_A))


def read_interview(client: ApiClient, interview_id: str) -> Row:
    return setup(client.get_interview(interview_id, ARCHIVIST_A))


def read_requester(client: ApiClient, requester_id: str) -> Row:
    return setup(client.get_requester(requester_id, OFFICER_A))


# ═══ Tier 2: a shelved holding ════════════════════════════════════════════

@dataclass
class Holding:
    """A schedule, its series, a zone, one accession and its items."""

    schedule: Row
    series: Row
    zone: Row
    accession: Row
    items: List[Row] = field(default_factory=list)

    @property
    def schedule_id(self) -> str:
        return self.schedule["id"]

    @property
    def series_id(self) -> str:
        return self.series["id"]

    @property
    def zone_id(self) -> str:
        return self.zone["id"]

    @property
    def accession_id(self) -> str:
        return self.accession["id"]

    @property
    def item(self) -> Row:
        return self.items[0]

    @property
    def item_id(self) -> str:
        return self.items[0]["id"]

    @property
    def item_ids(self) -> List[str]:
        return [row["id"] for row in self.items]


def make_holding(
    client: ApiClient,
    *,
    item_specs: Optional[List[Dict[str, Any]]] = None,
    schedule_overrides: Optional[Dict[str, Any]] = None,
    series_overrides: Optional[Dict[str, Any]] = None,
    zone_overrides: Optional[Dict[str, Any]] = None,
    accession_overrides: Optional[Dict[str, Any]] = None,
    declared_unit_count: Optional[int] = None,
    schedule: Optional[Row] = None,
    series: Optional[Row] = None,
    zone: Optional[Row] = None,
    stage: str = "PROCESSED",
) -> Holding:
    """Build a holding and drive its accession to ``stage``.

    ``stage`` is one of ``RECEIVED``, ``PROVENANCE_VERIFIED`` or ``PROCESSED``.
    ``item_specs`` is a list of ``archival_item_payload`` keyword dicts, one per
    container; the accession's declared unit count defaults to the sum of the
    containers' unit counts so that processing reconciles.
    """
    if item_specs is None:
        item_specs = [{"unit_count": 2}]
    if schedule is None:
        schedule = make_schedule(client, **(schedule_overrides or {}))
    if series is None:
        series = make_series(
            client, schedule["id"], **(series_overrides or {})
        )
    if zone is None:
        zone = make_zone(client, **(zone_overrides or {}))

    declared = declared_unit_count
    if declared is None:
        declared = sum(int(spec.get("unit_count", 2)) for spec in item_specs)
    accession = make_accession(
        client,
        series["id"],
        declared_unit_count=declared,
        **(accession_overrides or {}),
    )

    items = [
        make_item(client, accession["id"], zone["id"], **spec) for spec in item_specs
    ]

    if stage in ("PROVENANCE_VERIFIED", "PROCESSED"):
        setup(
            client.verify_accession_provenance(
                accession["id"], f.verify_provenance_payload(), ARCHIVIST_A
            )
        )
    if stage == "PROCESSED":
        setup(client.process_accession(accession["id"], ARCHIVIST_A))

    return Holding(
        schedule=schedule,
        series=read_series(client, series["id"]),
        zone=read_zone(client, zone["id"]),
        accession=read_accession(client, accession["id"]),
        items=[read_item(client, row["id"]) for row in items],
    )


def add_item(client: ApiClient, holding: Holding, **overrides) -> Row:
    """Register one more container under an existing holding's accession."""
    row = make_item(client, holding.accession_id, holding.zone_id, **overrides)
    holding.items.append(row)
    holding.accession = read_accession(client, holding.accession_id)
    return row


# ═══ Appraisal ════════════════════════════════════════════════════════════

def make_appraisal(
    client: ApiClient, series: Row, *, expected_series_version: Optional[int] = None,
    **overrides,
) -> Row:
    version = (
        expected_series_version
        if expected_series_version is not None
        else series["version"]
    )
    return setup(
        client.create_appraisal(
            f.appraisal_payload(series["id"], version, **overrides), ARCHIVIST_A
        )
    )


def screened_appraisal(client: ApiClient, series: Row, **overrides) -> Row:
    row = make_appraisal(client, series, **overrides)
    return setup(client.screen_appraisal(row["id"], ARCHIVIST_A))


def finalized_appraisal(client: ApiClient, series: Row, **overrides) -> Row:
    row = screened_appraisal(client, series, **overrides)
    return setup(client.finalize_appraisal(row["id"], DIRECTOR_A))


# ═══ Legal holds ══════════════════════════════════════════════════════════

def make_hold(client: ApiClient, series_id: str, **overrides) -> Row:
    return setup(
        client.create_legal_hold(f.legal_hold_payload(series_id, **overrides), COUNSEL_A)
    )


def active_hold(client: ApiClient, series_id: str, **overrides) -> Row:
    """Draft and activate a hold, driving the three-hop suspension cascade."""
    row = make_hold(client, series_id, **overrides)
    return setup(client.activate_legal_hold(row["id"], COUNSEL_A))


def release_hold(client: ApiClient, hold_id: str, **overrides) -> Row:
    return setup(client.release_legal_hold(hold_id, f.release_payload(**overrides), COUNSEL_A))


# ═══ Finding aids ═════════════════════════════════════════════════════════

def make_finding_aid(client: ApiClient, accession_id: str, **overrides) -> Row:
    return setup(
        client.create_finding_aid(f.finding_aid_payload(accession_id, **overrides), ARCHIVIST_A)
    )


def reviewed_finding_aid(client: ApiClient, accession_id: str, **overrides) -> Row:
    row = make_finding_aid(client, accession_id, **overrides)
    return setup(client.submit_finding_aid_review(row["id"], ARCHIVIST_A))


def published_finding_aid(client: ApiClient, accession_id: str, **overrides) -> Row:
    """Draft, review and publish an aid over a processed accession."""
    row = reviewed_finding_aid(client, accession_id, **overrides)
    return setup(client.publish_finding_aid(row["id"], DIRECTOR_A))


# ═══ Preservation plans and migration jobs ════════════════════════════════

def make_plan(
    client: ApiClient, zone_id: str, *, activate: bool = True, **overrides
) -> Row:
    row = setup(
        client.create_preservation_plan(
            f.preservation_plan_payload(zone_id, **overrides), PRESERV_A
        )
    )
    if activate:
        row = setup(client.activate_preservation_plan(row["id"], PRESERV_A))
    return row


def make_job(
    client: ApiClient,
    plan_id: str,
    item_id: str,
    *,
    stage: str = "PENDING_APPROVAL",
    approver=PRESERV_B,
    **overrides,
) -> Row:
    """Create a job and drive it to ``stage``.

    ``stage`` is one of ``PENDING_APPROVAL``, ``APPROVED``, ``IN_PROGRESS`` or
    ``COMPLETED``. Approval is presented by a second officer so that the
    segregation-of-duties comparison against the requesting officer passes.
    """
    row = setup(
        client.create_migration_job(
            f.migration_job_payload(plan_id, item_id, **overrides), PRESERV_A
        )
    )
    if stage in ("APPROVED", "IN_PROGRESS", "COMPLETED"):
        row = setup(client.approve_migration_job(row["id"], approver))
    if stage in ("IN_PROGRESS", "COMPLETED"):
        row = setup(client.start_migration_job(row["id"], PRESERV_A))
    if stage == "COMPLETED":
        row = setup(client.complete_migration_job(row["id"], PRESERV_A))
    return row


# ═══ Requesters, access requests and screenings ═══════════════════════════

@dataclass
class AccessCase:
    """A requester plus the request filed on its behalf, and any screening."""

    requester: Row
    request: Row
    screening: Optional[Row] = None

    @property
    def requester_id(self) -> str:
        return self.requester["id"]

    @property
    def request_id(self) -> str:
        return self.request["id"]

    @property
    def screening_id(self) -> str:
        return self.screening["id"]

    @property
    def requester_headers(self) -> Dict[str, str]:
        return make_requester_headers(self.requester["id"])


def make_access_request(
    client: ApiClient,
    holding: Holding,
    *,
    requester: Optional[Row] = None,
    requester_overrides: Optional[Dict[str, Any]] = None,
    item_ids: Optional[List[str]] = None,
    finding_aid_id: Optional[str] = None,
    headers=OFFICER_A,
    **overrides,
) -> AccessCase:
    if requester is None:
        requester = make_requester(client, **(requester_overrides or {}))
    if item_ids is None:
        item_ids = holding.item_ids
    request = setup(
        client.create_access_request(
            f.access_request_payload(
                requester["id"],
                holding.series_id,
                item_ids,
                finding_aid_id=finding_aid_id,
                **overrides,
            ),
            headers,
        )
    )
    return AccessCase(requester=requester, request=request)


def drive_to_screening(client: ApiClient, case: AccessCase) -> AccessCase:
    case.request = setup(client.begin_screening(case.request_id, OFFICER_A))
    return case


def open_screening(
    client: ApiClient, case: AccessCase, *, headers=OFFICER_A,
    expected_access_request_version: Optional[int] = None,
) -> AccessCase:
    version = (
        expected_access_request_version
        if expected_access_request_version is not None
        else case.request["version"]
    )
    case.screening = setup(
        client.create_screening(
            f.screening_payload(case.request_id, version), headers
        )
    )
    case.request = read_request(client, case.request_id)
    return case


def complete_screening(
    client: ApiClient, case: AccessCase, *, decision: str = "GRANT_FULL",
    redaction_required: Optional[bool] = None, headers=OFFICER_A, **overrides,
) -> AccessCase:
    case.screening = setup(
        client.complete_screening(
            case.screening_id,
            f.complete_screening_payload(
                decision=decision, redaction_required=redaction_required, **overrides
            ),
            headers,
        )
    )
    case.request = read_request(client, case.request_id)
    return case


def screened_case(
    client: ApiClient,
    holding: Holding,
    *,
    decision: str = "GRANT_FULL",
    redaction_required: Optional[bool] = None,
    screener=OFFICER_A,
    **kwargs,
) -> AccessCase:
    """A request driven into screening with one completed screening on it."""
    case = make_access_request(client, holding, **kwargs)
    drive_to_screening(client, case)
    open_screening(client, case, headers=screener)
    complete_screening(
        client, case, decision=decision, redaction_required=redaction_required,
        headers=screener,
    )
    return case


def approved_case(
    client: ApiClient, holding: Holding, *, approver=OFFICER_B, scope: str = "FULL",
    **kwargs,
) -> AccessCase:
    """A request carried all the way to an approval decision."""
    case = screened_case(client, holding, **kwargs)
    case.request = setup(
        client.approve_access_request(
            case.request_id, f.approve_request_payload(scope), approver
        )
    )
    return case


# ═══ Oral history interviews ══════════════════════════════════════════════

def make_interview(client: ApiClient, accession_id: str, **overrides) -> Row:
    return setup(
        client.create_interview(f.interview_payload(accession_id, **overrides), ARCHIVIST_A)
    )


def consent(client: ApiClient, interview_id: str, action: str) -> Row:
    return setup(
        client.interview_consent(interview_id, f.consent_payload(action), ARCHIVIST_A)
    )


def transcription(client: ApiClient, interview_id: str, action: str) -> Row:
    return setup(
        client.interview_transcription(
            interview_id, f.transcription_payload(action), ARCHIVIST_A
        )
    )


def interview_at(
    client: ApiClient,
    accession_id: str,
    *,
    consent_actions: Optional[List[str]] = None,
    transcription_actions: Optional[List[str]] = None,
    **overrides,
) -> Row:
    """Drive both interview axes independently through the listed actions."""
    row = make_interview(client, accession_id, **overrides)
    for action in consent_actions or []:
        row = consent(client, row["id"], action)
    for action in transcription_actions or []:
        row = transcription(client, row["id"], action)
    return row


# ═══ Trademark evidence packages ══════════════════════════════════════════

def make_package(
    client: ApiClient, series_id: str, claimed_first_use_year: int,
    evidence_item_ids: List[str], **overrides,
) -> Row:
    return setup(
        client.create_evidence_package(
            f.evidence_package_payload(
                series_id, claimed_first_use_year, evidence_item_ids, **overrides
            ),
            ARCHIVIST_A,
        )
    )


def certified_package(
    client: ApiClient, series_id: str, claimed_first_use_year: int,
    evidence_item_ids: List[str], **overrides,
) -> Row:
    """A package whose coverage arithmetic clears both certification gates."""
    row = make_package(
        client, series_id, claimed_first_use_year, evidence_item_ids, **overrides
    )
    return setup(client.certify_evidence_package(row["id"], COUNSEL_A))


# ═══ Exhibit loans ════════════════════════════════════════════════════════

def make_loan(
    client: ApiClient,
    item_id: str,
    window_start: str,
    window_end: str,
    *,
    stage: str = "REQUESTED",
    units: int = 2,
    **overrides,
) -> Row:
    """Create a loan and drive it to ``stage``.

    ``stage`` is one of ``REQUESTED``, ``CONFIRMED`` or ``OUT``. Reaching ``OUT``
    requires the logical clock to already stand at or after ``window_start``.
    """
    row = setup(
        client.create_exhibit_loan(
            f.exhibit_loan_payload(
                item_id, window_start, window_end, units=units, **overrides
            ),
            ARCHIVIST_A,
        )
    )
    if stage in ("CONFIRMED", "OUT"):
        row = setup(client.confirm_exhibit_loan(row["id"], PRESERV_A))
    if stage == "OUT":
        row = setup(client.check_out_exhibit_loan(row["id"], ARCHIVIST_A))
    return row


# ═══ Deaccession proposals ════════════════════════════════════════════════

def make_proposal(
    client: ApiClient,
    item_id: str,
    *,
    stage: str = "SUBMITTED",
    units: int = 2,
    route: str = "DESTRUCTION",
    recipient_repository: Optional[str] = None,
    legal_clearer=COUNSEL_A,
    heritage_clearer=DIRECTOR_A,
    approver=DIRECTOR_A,
    **overrides,
) -> Row:
    """Create a proposal and drive it along the fork-join to ``stage``.

    ``stage`` is one of ``SUBMITTED``, ``LEGAL_CLEARED``, ``HERITAGE_CLEARED``,
    ``DUALLY_CLEARED``, ``APPROVED`` or ``EXECUTED``. Approval is presented by a
    director distinct from the legal clearer, which the clearer defaults already
    satisfy because the two clearances are granted by different roles.
    """
    row = setup(
        client.create_deaccession_proposal(
            f.deaccession_proposal_payload(
                item_id, units=units, route=route,
                recipient_repository=recipient_repository, **overrides,
            ),
            ARCHIVIST_A,
        )
    )
    if stage in ("LEGAL_CLEARED", "DUALLY_CLEARED", "APPROVED", "EXECUTED"):
        row = setup(client.legal_clearance(row["id"], legal_clearer))
    if stage in ("HERITAGE_CLEARED", "DUALLY_CLEARED", "APPROVED", "EXECUTED"):
        row = setup(client.heritage_clearance(row["id"], heritage_clearer))
    if stage in ("APPROVED", "EXECUTED"):
        row = setup(client.approve_deaccession_proposal(row["id"], approver))
    if stage == "EXECUTED":
        row = setup(
            client.execute_deaccession_proposal(
                row["id"], f.execute_payload("TR-0001"), ARCHIVIST_A
            )
        )
    return row


# ═══ Tier 3: whole-pipeline states ════════════════════════════════════════

def suspended_holding(client: ApiClient, holding: Holding, **overrides) -> Row:
    """Freeze a holding's series behind an active hold; returns the hold."""
    hold = active_hold(client, holding.series_id, **overrides)
    holding.series = read_series(client, holding.series_id)
    return hold


def eligible_series_holding(
    client: ApiClient,
    *,
    latest_record_year: int = 2015,
    retention_years: int = 5,
    clock: str = "2026-08-01T00:00:00Z",
    disposition_action: str = "DESTROY",
    min_appraisal_score_for_permanent: float = 95.00,
    item_specs: Optional[List[Dict[str, Any]]] = None,
) -> Holding:
    """A holding whose series has been appraised into ELIGIBLE_FOR_DISPOSITION.

    The schedule's permanence threshold is set out of reach so the finalised
    appraisal recommends the schedule's disposition action, and the clock is
    moved to an instant at or after the derived retention expiry so the series
    leaves ACTIVE.
    """
    holding = make_holding(
        client,
        item_specs=item_specs,
        schedule_overrides={
            "retention_years": retention_years,
            "disposition_action": disposition_action,
            "min_appraisal_score_for_permanent": min_appraisal_score_for_permanent,
        },
        series_overrides={
            "earliest_record_year": 2000,
            "latest_record_year": latest_record_year,
        },
    )
    set_clock(client, clock)
    finalized_appraisal(client, holding.series)
    holding.series = read_series(client, holding.series_id)
    return holding


def plan_with_approved_job(
    client: ApiClient,
    holding: Holding,
    *,
    budget_cents: int = 1000000,
    units: int = 10,
    window_start: str = "2026-09-01T00:00:00Z",
    window_end: str = "2026-09-30T00:00:00Z",
    item_id: Optional[str] = None,
) -> Dict[str, Row]:
    """An activated plan over the holding's zone carrying one APPROVED job."""
    plan = make_plan(client, holding.zone_id, budget_cents=budget_cents)
    job = make_job(
        client,
        plan["id"],
        item_id or holding.item_id,
        stage="APPROVED",
        units=units,
        window_start=window_start,
        window_end=window_end,
    )
    return {"plan": read_plan(client, plan["id"]), "job": job}


def request_awaiting_decision(
    client: ApiClient,
    holding: Holding,
    *,
    decision: str = "GRANT_FULL",
    redaction_required: Optional[bool] = None,
    finding_aid_id: Optional[str] = None,
    requester_overrides: Optional[Dict[str, Any]] = None,
    item_ids: Optional[List[str]] = None,
    screener=OFFICER_A,
) -> AccessCase:
    """A request in SCREENING whose current screening is COMPLETED."""
    return screened_case(
        client,
        holding,
        decision=decision,
        redaction_required=redaction_required,
        finding_aid_id=finding_aid_id,
        requester_overrides=requester_overrides,
        item_ids=item_ids,
        screener=screener,
    )


def revalidation_required_case(
    client: ApiClient, holding: Holding, **kwargs
) -> Dict[str, Any]:
    """An approved request pushed into REVALIDATION_REQUIRED by a deaccession.

    The request cites a published finding aid over the holding's accession; the
    deaccession approval cascade then marks the aid stale and drives the already
    approved request back for re-screening.
    """
    aid = published_finding_aid(client, holding.accession_id)
    case = approved_case(client, holding, finding_aid_id=aid["id"], **kwargs)
    proposal = make_proposal(client, holding.item_id, stage="APPROVED")
    case.request = read_request(client, case.request_id)
    return {
        "case": case,
        "finding_aid": read_finding_aid(client, aid["id"]),
        "proposal": proposal,
    }
