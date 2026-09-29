"""Composite setup helpers.

The harness restarts the service before every test, so each test begins against
an empty store with the logical clock parked at ``CLOCK_EPOCH``. Everything a
test needs beyond its own trigger call is built here, in five tiers:

* tier 1 - single row creation (water system, line, evidence, crew, project, fund)
* tier 2 - statistical strata (open a batch, append samples, validate, reopen)
* tier 3 - the publication pipeline (advance, draft, certify, publish)
* tier 4 - notification walks (locate, deliver, acknowledge, return)
* tier 5 - replacement order pipelines and whole scenario builders

Every helper asserts its own success and returns parsed data, so a test body
never has to unwrap a setup response.
"""

from typing import Any, Dict, List, Optional, Sequence, Tuple

from prd_bench_local_runner.testing import get_success_data, validate_paginated

from . import factories
from .api_client import ApiClient
from .constants import CLOCK_EPOCH
from .test_users import (
    ADMIN_HEADERS,
    ANALYST_HEADERS,
    CONTRACTOR_HEADERS,
    CSR_HEADERS,
    OFFICER_HEADERS,
    make_field_technician_headers,
)
from .types import (
    ConsentOutcome,
    FundingMode,
    InventoryStatus,
    Material,
    PublicationBasis,
    SampleType,
    Side,
    SourceType,
    VerificationMethod,
)

#: The five sample readings used whenever a scenario only needs a stratum that
#: validates cleanly: sorted, the 90th percentile lands on 5.0 ppb, no reading
#: exceeds the action level, so confidence is 1.0000 and the batch validates.
CLEAN_SAMPLE_PPBS: Tuple[float, ...] = (1.0, 2.0, 3.0, 4.0, 5.0)

#: Collection instants paired with ``CLEAN_SAMPLE_PPBS``.
CLEAN_SAMPLE_INSTANTS: Tuple[str, ...] = (
    "2026-07-11T09:00:00Z",
    "2026-07-12T09:00:00Z",
    "2026-07-13T09:00:00Z",
    "2026-07-14T09:00:00Z",
    "2026-07-15T09:00:00Z",
)


# ===========================================================================
# tier 1 - single row creation
# ===========================================================================


def set_clock(client: ApiClient, to_iso8601: str) -> Dict[str, Any]:
    """Move the logical clock forward to ``to_iso8601``."""
    return get_success_data(client.set_clock(to_iso8601, ADMIN_HEADERS), 200)


def create_water_system(client: ApiClient, pwsid: str, **overrides: Any) -> Dict[str, Any]:
    """Create one water system and return it."""
    payload = factories.water_system_payload(pwsid, **overrides)
    return get_success_data(client.create_water_system(payload, ADMIN_HEADERS), 201)


def create_service_line(
    client: ApiClient, water_system_id: str, **overrides: Any
) -> Dict[str, Any]:
    """Create one service line under ``water_system_id`` and return it."""
    payload = factories.service_line_payload(water_system_id, **overrides)
    return get_success_data(client.create_service_line(payload, ANALYST_HEADERS), 201)


def add_evidence(
    client: ApiClient,
    service_line_id: str,
    source_type: str = SourceType.HISTORIC_RECORD,
    side: str = Side.UTILITY,
    observed_material: str = Material.LEAD,
    observed_at: str = "2026-06-01T00:00:00Z",
    notes: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Attach one manual evidence item to a line and return it."""
    payload = factories.evidence_item_payload(
        service_line_id,
        source_type=source_type,
        side=side,
        observed_material=observed_material,
        observed_at=observed_at,
        notes=notes,
    )
    return get_success_data(
        client.create_evidence_item(payload, headers or ANALYST_HEADERS), 201
    )


def retract_evidence(client: ApiClient, evidence_item_id: str, reason: str) -> Dict[str, Any]:
    """Retract one evidence item and return the updated row."""
    return get_success_data(
        client.retract_evidence_item(
            evidence_item_id, factories.retract_evidence_payload(reason), ANALYST_HEADERS
        ),
        200,
    )


def make_lead_line(client: ApiClient, water_system_id: str, **overrides: Any) -> Dict[str, Any]:
    """A line whose only record is a historic LEAD reading on the utility side."""
    line = create_service_line(client, water_system_id, **overrides)
    add_evidence(client, line["id"], observed_material=Material.LEAD)
    return line


def make_grr_line(client: ApiClient, water_system_id: str, **overrides: Any) -> Dict[str, Any]:
    """A line whose only record is a historic GRR reading on the utility side."""
    line = create_service_line(client, water_system_id, **overrides)
    add_evidence(client, line["id"], observed_material=Material.GRR)
    return line


def make_non_lead_line(client: ApiClient, water_system_id: str, **overrides: Any) -> Dict[str, Any]:
    """A line with copper on the utility side and plastic on the customer side."""
    line = create_service_line(client, water_system_id, **overrides)
    add_evidence(client, line["id"], side=Side.UTILITY, observed_material=Material.COPPER)
    add_evidence(client, line["id"], side=Side.CUSTOMER, observed_material=Material.PLASTIC)
    return line


def create_crew(client: ApiClient, water_system_id: str, **overrides: Any) -> Dict[str, Any]:
    """Create one verification crew and return it."""
    payload = factories.verification_crew_payload(water_system_id, **overrides)
    return get_success_data(client.create_verification_crew(payload, ADMIN_HEADERS), 201)


def set_crew_status(client: ApiClient, crew_id: str, status: str) -> Dict[str, Any]:
    """Flip a crew between ACTIVE and INACTIVE."""
    return get_success_data(
        client.set_crew_status(crew_id, factories.crew_status_payload(status), ADMIN_HEADERS),
        200,
    )


def create_street_project(
    client: ApiClient, water_system_id: str, **overrides: Any
) -> Dict[str, Any]:
    """Create one street project and return it."""
    payload = factories.street_project_payload(water_system_id, **overrides)
    return get_success_data(client.create_street_project(payload, ADMIN_HEADERS), 201)


def create_funding_source(
    client: ApiClient, water_system_id: str, **overrides: Any
) -> Dict[str, Any]:
    """Create one funding source and return it."""
    payload = factories.funding_source_payload(water_system_id, **overrides)
    return get_success_data(client.create_funding_source(payload, ADMIN_HEADERS), 201)


def read_water_system(client: ApiClient, water_system_id: str) -> Dict[str, Any]:
    """Re-read a water system with the officer identity."""
    return get_success_data(client.get_water_system(water_system_id, OFFICER_HEADERS), 200)


def read_service_line(client: ApiClient, service_line_id: str) -> Dict[str, Any]:
    """Re-read a service line with the analyst identity."""
    return get_success_data(client.get_service_line(service_line_id, ANALYST_HEADERS), 200)


def read_evidence_item(client: ApiClient, evidence_item_id: str) -> Dict[str, Any]:
    """Re-read an evidence item with the analyst identity."""
    return get_success_data(client.get_evidence_item(evidence_item_id, ANALYST_HEADERS), 200)


def read_crew(client: ApiClient, crew_id: str) -> Dict[str, Any]:
    """Re-read a verification crew with the administrator identity."""
    return get_success_data(client.get_verification_crew(crew_id, ADMIN_HEADERS), 200)


def read_appointment(client: ApiClient, appointment_id: str) -> Dict[str, Any]:
    """Re-read a verification appointment with the administrator identity."""
    return get_success_data(
        client.get_verification_appointment(appointment_id, ADMIN_HEADERS), 200
    )


def read_batch(client: ApiClient, batch_id: str) -> Dict[str, Any]:
    """Re-read a sampling batch with the officer identity."""
    return get_success_data(client.get_sampling_batch(batch_id, OFFICER_HEADERS), 200)


def read_publication(client: ApiClient, publication_id: str) -> Dict[str, Any]:
    """Re-read an inventory publication with the officer identity."""
    return get_success_data(
        client.get_inventory_publication(publication_id, OFFICER_HEADERS), 200
    )


def read_notification(client: ApiClient, notification_id: str) -> Dict[str, Any]:
    """Re-read a customer notification with the representative identity."""
    return get_success_data(client.get_customer_notification(notification_id, CSR_HEADERS), 200)


def read_order(client: ApiClient, order_id: str) -> Dict[str, Any]:
    """Re-read a replacement order with the administrator identity."""
    return get_success_data(client.get_replacement_order(order_id, ADMIN_HEADERS), 200)


def read_street_project(client: ApiClient, street_project_id: str) -> Dict[str, Any]:
    """Re-read a street project with the administrator identity."""
    return get_success_data(client.get_street_project(street_project_id, ADMIN_HEADERS), 200)


def read_funding_source(client: ApiClient, funding_source_id: str) -> Dict[str, Any]:
    """Re-read a funding source with the administrator identity."""
    return get_success_data(client.get_funding_source(funding_source_id, ADMIN_HEADERS), 200)


def read_progress_report(client: ApiClient, progress_report_id: str) -> Dict[str, Any]:
    """Re-read a progress report with the officer identity."""
    return get_success_data(client.get_progress_report(progress_report_id, OFFICER_HEADERS), 200)


# ===========================================================================
# tier 2 - statistical strata
# ===========================================================================


def open_batch(
    client: ApiClient,
    water_system_id: str,
    stratum_code: str = "STR-A",
    stratum_line_count: int = 20,
) -> Dict[str, Any]:
    """Open one sampling batch and return it."""
    payload = factories.sampling_batch_payload(
        water_system_id, stratum_code=stratum_code, stratum_line_count=stratum_line_count
    )
    return get_success_data(client.create_sampling_batch(payload, OFFICER_HEADERS), 201)


def append_sample(
    client: ApiClient,
    batch_id: str,
    service_line_id: str,
    lead_ppb: float,
    collected_at: str,
    sample_type: str = SampleType.FIRST_DRAW,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Append one reading to a batch and return the recomputed batch."""
    payload = factories.sample_payload(
        service_line_id, lead_ppb, collected_at, sample_type=sample_type
    )
    return get_success_data(
        client.append_sample(batch_id, payload, headers or OFFICER_HEADERS), 200
    )


def append_samples(
    client: ApiClient,
    batch_id: str,
    service_line_id: str,
    readings: Sequence[float] = CLEAN_SAMPLE_PPBS,
    instants: Optional[Sequence[str]] = None,
    sample_types: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    """Append several readings in order and return the batch after the last one."""
    stamps = list(instants) if instants is not None else [
        f"2026-07-{11 + index:02d}T09:00:00Z" for index in range(len(readings))
    ]
    kinds = list(sample_types) if sample_types is not None else [
        SampleType.FIRST_DRAW if index < 3 else SampleType.FIFTH_LITER
        for index in range(len(readings))
    ]
    batch: Dict[str, Any] = {}
    for reading, stamp, kind in zip(readings, stamps, kinds):
        batch = append_sample(
            client, batch_id, service_line_id, reading, stamp, sample_type=kind
        )
    return batch


def validate_batch(client: ApiClient, batch_id: str) -> Dict[str, Any]:
    """Run the statistical validation of a batch and return it."""
    return get_success_data(client.validate_sampling_batch(batch_id, OFFICER_HEADERS), 200)


def reopen_batch(client: ApiClient, batch_id: str, reason: str = "RESAMPLE_ROUND_2") -> Dict[str, Any]:
    """Reopen a rejected batch and return it."""
    return get_success_data(
        client.reopen_sampling_batch(
            batch_id, factories.reopen_batch_payload(reason), OFFICER_HEADERS
        ),
        200,
    )


def invalidate_sample(
    client: ApiClient, batch_id: str, sample_seq: int, reason: str
) -> Dict[str, Any]:
    """Strike one reading from the statistical population."""
    return get_success_data(
        client.invalidate_sample(
            batch_id, factories.invalidate_sample_payload(sample_seq, reason), OFFICER_HEADERS
        ),
        200,
    )


def open_and_validate_batch(
    client: ApiClient,
    water_system_id: str,
    service_line_id: str,
    stratum_code: str = "STR-A",
    stratum_line_count: int = 20,
    readings: Sequence[float] = CLEAN_SAMPLE_PPBS,
) -> Dict[str, Any]:
    """Open a stratum, fill it with clean readings and validate it."""
    batch = open_batch(
        client,
        water_system_id,
        stratum_code=stratum_code,
        stratum_line_count=stratum_line_count,
    )
    append_samples(
        client,
        batch["id"],
        service_line_id,
        readings=readings,
        instants=CLEAN_SAMPLE_INSTANTS[: len(readings)] if len(readings) <= 5 else None,
    )
    return validate_batch(client, batch["id"])


# ===========================================================================
# tier 3 - the publication pipeline
# ===========================================================================


def advance_inventory_status(
    client: ApiClient, water_system_id: str, target_status: str
) -> Dict[str, Any]:
    """Advance the inventory axis of a water system and return the system."""
    return get_success_data(
        client.advance_inventory_status(
            water_system_id,
            factories.advance_inventory_status_payload(target_status),
            OFFICER_HEADERS,
        ),
        200,
    )


def advance_to_validation_pending(client: ApiClient, water_system_id: str) -> Dict[str, Any]:
    """Move a water system from DRAFT to VALIDATION_PENDING."""
    return advance_inventory_status(
        client, water_system_id, InventoryStatus.VALIDATION_PENDING
    )


def draft_publication(
    client: ApiClient,
    water_system_id: str,
    expected_water_system_version: int,
    basis: str = PublicationBasis.RECORDS,
    reporting_period_label: str = "2026-H2",
) -> Dict[str, Any]:
    """Draft one inventory publication and return it."""
    payload = factories.inventory_publication_payload(
        water_system_id,
        expected_water_system_version,
        basis=basis,
        reporting_period_label=reporting_period_label,
    )
    return get_success_data(client.create_inventory_publication(payload, ANALYST_HEADERS), 201)


def certify_publication(client: ApiClient, publication_id: str) -> Dict[str, Any]:
    """Certify a drafted publication with the officer identity."""
    return get_success_data(client.certify_publication(publication_id, OFFICER_HEADERS), 200)


def publish_publication(client: ApiClient, publication_id: str) -> Dict[str, Any]:
    """Publish a certified publication with the officer identity."""
    return get_success_data(client.publish_publication(publication_id, OFFICER_HEADERS), 200)


def patch_corrosion_control(
    client: ApiClient, water_system_id: str, **overrides: Any
) -> Dict[str, Any]:
    """Update the corrosion control block of a water system."""
    payload = factories.corrosion_control_payload(**overrides)
    return get_success_data(
        client.patch_corrosion_control(water_system_id, payload, OFFICER_HEADERS), 200
    )


def patch_funding_policy(
    client: ApiClient, water_system_id: str, funding_mode: str
) -> Dict[str, Any]:
    """Switch the apportionment policy of a water system."""
    return get_success_data(
        client.patch_funding_policy(
            water_system_id, factories.funding_policy_payload(funding_mode), ADMIN_HEADERS
        ),
        200,
    )


def publish_inventory(
    client: ApiClient,
    water_system_id: str,
    service_line_id: str,
    basis: str = PublicationBasis.RECORDS,
    reporting_period_label: str = "2026-H2",
    stratum_code: str = "STR-A",
    stratum_line_count: int = 20,
    readings: Sequence[float] = CLEAN_SAMPLE_PPBS,
) -> Dict[str, Any]:
    """Take a water system all the way from DRAFT to PUBLISHED.

    Opens and validates one stratum, advances the inventory axis, drafts,
    certifies and publishes. Returns the published publication row.
    """
    open_and_validate_batch(
        client,
        water_system_id,
        service_line_id,
        stratum_code=stratum_code,
        stratum_line_count=stratum_line_count,
        readings=readings,
    )
    system = advance_to_validation_pending(client, water_system_id)
    publication = draft_publication(
        client,
        water_system_id,
        system["version"],
        basis=basis,
        reporting_period_label=reporting_period_label,
    )
    certify_publication(client, publication["id"])
    return publish_publication(client, publication["id"])


# ===========================================================================
# tier 4 - notification walks
# ===========================================================================


def list_notifications_for_line(client: ApiClient, service_line_id: str) -> List[Dict[str, Any]]:
    """Every notification raised against one line."""
    rows, _meta = validate_paginated(
        client.list_customer_notifications(CSR_HEADERS, service_line_id=service_line_id)
    )
    return rows


def notification_for_line(client: ApiClient, service_line_id: str) -> Dict[str, Any]:
    """The single notification raised against one line."""
    rows = list_notifications_for_line(client, service_line_id)
    assert rows, f"expected a notification for service line {service_line_id}"
    return rows[0]


def list_notifications_for_publication(
    client: ApiClient, inventory_publication_id: str
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Every notification a publication fanned out, with its pagination metadata."""
    return validate_paginated(
        client.list_customer_notifications(
            CSR_HEADERS, inventory_publication_id=inventory_publication_id
        )
    )


def deliver_notification(
    client: ApiClient, notification_id: str, delivered_at: str = "2026-08-01T09:00:00Z", **overrides: Any
) -> Dict[str, Any]:
    """Record a delivery attempt against a notification."""
    payload = factories.deliver_notification_payload(delivered_at, **overrides)
    return get_success_data(client.deliver_notification(notification_id, payload, CSR_HEADERS), 200)


def acknowledge_notification(
    client: ApiClient, notification_id: str, acknowledged_at: str
) -> Dict[str, Any]:
    """Record a customer acknowledgement."""
    payload = factories.acknowledge_notification_payload(acknowledged_at)
    return get_success_data(
        client.acknowledge_notification(notification_id, payload, CSR_HEADERS), 200
    )


def return_notification(client: ApiClient, notification_id: str, return_reason: str) -> Dict[str, Any]:
    """Record an undeliverable return."""
    payload = factories.return_notification_payload(return_reason)
    return get_success_data(client.return_notification(notification_id, payload, CSR_HEADERS), 200)


def deliver_notification_for_line(
    client: ApiClient, service_line_id: str, delivered_at: str = "2026-08-01T09:00:00Z"
) -> Dict[str, Any]:
    """Locate the notification of one line and deliver it."""
    notification = notification_for_line(client, service_line_id)
    return deliver_notification(client, notification["id"], delivered_at=delivered_at)


# ===========================================================================
# tier 5 - appointments and replacement orders
# ===========================================================================


def book_appointment(
    client: ApiClient,
    service_line_id: str,
    crew_id: str,
    method: str = VerificationMethod.POTHOLE,
    window_start_utc: str = "2026-08-05T09:00:00Z",
    window_end_utc: str = "2026-08-05T10:00:00Z",
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Book one verification appointment and return it."""
    payload = factories.verification_appointment_payload(
        service_line_id,
        crew_id,
        method=method,
        window_start_utc=window_start_utc,
        window_end_utc=window_end_utc,
    )
    return get_success_data(
        client.create_verification_appointment(payload, headers or ADMIN_HEADERS), 201
    )


def arrive(client: ApiClient, appointment_id: str, crew_id: str) -> Dict[str, Any]:
    """Mark a crew as on site."""
    return get_success_data(
        client.arrive_appointment(appointment_id, make_field_technician_headers(crew_id)), 200
    )


def complete_appointment(
    client: ApiClient,
    appointment_id: str,
    crew_id: str,
    observed_side: str = Side.UTILITY,
    observed_material: str = Material.COPPER,
) -> Dict[str, Any]:
    """Close out an on site appointment with an observation."""
    payload = factories.appointment_complete_payload(observed_side, observed_material)
    return get_success_data(
        client.complete_appointment(
            appointment_id, payload, make_field_technician_headers(crew_id)
        ),
        200,
    )


def report_no_access(
    client: ApiClient, appointment_id: str, crew_id: str, barrier_reason: str
) -> Dict[str, Any]:
    """Record a failed visit."""
    return get_success_data(
        client.no_access_appointment(
            appointment_id,
            factories.no_access_payload(barrier_reason),
            make_field_technician_headers(crew_id),
        ),
        200,
    )


def reschedule_appointment(
    client: ApiClient, appointment_id: str, window_start_utc: str, window_end_utc: str
) -> Dict[str, Any]:
    """Put a blocked appointment back on the calendar."""
    payload = factories.reschedule_payload(window_start_utc, window_end_utc)
    return get_success_data(
        client.reschedule_appointment(appointment_id, payload, ADMIN_HEADERS), 200
    )


def open_order(client: ApiClient, service_line_id: str, **overrides: Any) -> Dict[str, Any]:
    """Open one replacement order and return it."""
    payload = factories.replacement_order_payload(service_line_id, **overrides)
    return get_success_data(client.create_replacement_order(payload, ADMIN_HEADERS), 201)


def request_consent(client: ApiClient, order_id: str) -> Dict[str, Any]:
    """Send the consent canvass for an order."""
    return get_success_data(client.request_consent(order_id, CSR_HEADERS), 200)


def respond_consent(
    client: ApiClient,
    order_id: str,
    outcome: str = ConsentOutcome.GRANTED,
    barrier_reason: Optional[str] = None,
) -> Dict[str, Any]:
    """Record the consent outcome for an order."""
    payload = factories.consent_response_payload(outcome, barrier_reason)
    return get_success_data(client.respond_consent(order_id, payload, CSR_HEADERS), 200)


def resolve_consent(
    client: ApiClient,
    order_id: str,
    outcome: str = ConsentOutcome.GRANTED,
    barrier_reason: Optional[str] = None,
) -> Dict[str, Any]:
    """Canvass and answer in one step."""
    request_consent(client, order_id)
    return respond_consent(client, order_id, outcome=outcome, barrier_reason=barrier_reason)


def plan_funding(client: ApiClient, order_id: str) -> Dict[str, Any]:
    """Commit the apportionment for a scoped order."""
    return get_success_data(client.plan_funding(order_id, ADMIN_HEADERS), 200)


def schedule_order(
    client: ApiClient, order_id: str, excavation_start_date: str, excavation_end_date: str
) -> Dict[str, Any]:
    """Book the excavation window of a funded order."""
    payload = factories.schedule_order_payload(excavation_start_date, excavation_end_date)
    return get_success_data(client.schedule_order(order_id, payload, CONTRACTOR_HEADERS), 200)


def start_order(client: ApiClient, order_id: str) -> Dict[str, Any]:
    """Break ground on a scheduled order."""
    return get_success_data(client.start_order(order_id, CONTRACTOR_HEADERS), 200)


def complete_order(
    client: ApiClient, order_id: str, completed_at: str, replaced_sides: Sequence[str]
) -> Dict[str, Any]:
    """Close out an in progress order."""
    payload = factories.complete_order_payload(completed_at, list(replaced_sides))
    return get_success_data(client.complete_order(order_id, payload, CONTRACTOR_HEADERS), 200)


def cancel_order(client: ApiClient, order_id: str, reason: str) -> Dict[str, Any]:
    """Cancel an order and reverse its financial commitment."""
    return get_success_data(
        client.cancel_order(order_id, factories.cancel_order_payload(reason), ADMIN_HEADERS), 200
    )


def create_progress_report(
    client: ApiClient, water_system_id: str, period_start_date: str, period_end_date: str
) -> Dict[str, Any]:
    """Compute one credit period for a water system."""
    payload = factories.progress_report_payload(
        water_system_id, period_start_date, period_end_date
    )
    return get_success_data(client.create_progress_report(payload, OFFICER_HEADERS), 201)


# ===========================================================================
# tier 5b - whole scenario builders
# ===========================================================================


def published_system_with_lead_line(
    client: ApiClient,
    pwsid: str,
    system_name: str = "Test Water",
    address_label: str = "101 Elm St",
    census_tract_code: str = "17031-9900",
    disadvantaged_tract_codes: Optional[List[str]] = None,
    compliance_deadline_date: str = "2027-10-16",
    baseline_lead_and_grr_count: int = 100,
    funding_mode: str = FundingMode.WATERFALL,
    street_project_id: Optional[str] = None,
    serves_sensitive_population: Optional[bool] = None,
    basis: str = PublicationBasis.RECORDS,
    reporting_period_label: str = "2026-H2",
    deliver_notifications: bool = False,
) -> Dict[str, Any]:
    """One PUBLISHED water system holding one LEAD line.

    Returns a dictionary with the ``system``, ``line`` and ``publication`` rows
    as they stood immediately after publication, plus the water system version
    that was accepted by the publication draft.
    """
    system = create_water_system(
        client,
        pwsid,
        system_name=system_name,
        compliance_deadline_date=compliance_deadline_date,
        baseline_lead_and_grr_count=baseline_lead_and_grr_count,
        disadvantaged_tract_codes=disadvantaged_tract_codes
        if disadvantaged_tract_codes is not None
        else [],
        funding_mode=funding_mode,
    )
    line = create_service_line(
        client,
        system["id"],
        address_label=address_label,
        census_tract_code=census_tract_code,
        street_project_id=street_project_id,
        serves_sensitive_population=serves_sensitive_population,
    )
    add_evidence(client, line["id"], observed_material=Material.LEAD)
    publication = publish_inventory(
        client,
        system["id"],
        line["id"],
        basis=basis,
        reporting_period_label=reporting_period_label,
    )
    if deliver_notifications:
        deliver_notification_for_line(client, line["id"])
    return {
        "system": system,
        "line": line,
        "publication": publication,
        "water_system_id": system["id"],
        "service_line_id": line["id"],
        "publication_id": publication["id"],
    }


def open_posture_system_with_lead_line(
    client: ApiClient, pwsid: str, **overrides: Any
) -> Dict[str, Any]:
    """A published system whose only notification has been delivered.

    With the notification off the outstanding list, no funding shortfall and an
    unknown share of zero, the program posture settles on OPEN, which is what
    excavation scheduling requires.
    """
    overrides.setdefault("deliver_notifications", True)
    return published_system_with_lead_line(client, pwsid, **overrides)


def funded_order_on_published_system(
    client: ApiClient,
    pwsid: str,
    estimated_cost_cents: int = 100000,
    authorized_cents: int = 200000,
    max_share_pct: Optional[float] = 100.0,
    equity_required_pct: Optional[float] = 0.0,
    excavation_start_date: str = "2026-08-10",
    excavation_end_date: str = "2026-08-11",
    street_project_id: Optional[str] = None,
    consent_outcome: str = ConsentOutcome.GRANTED,
    barrier_reason: Optional[str] = None,
    **system_overrides: Any,
) -> Dict[str, Any]:
    """A published, OPEN system carrying one funded replacement order."""
    scenario = open_posture_system_with_lead_line(
        client, pwsid, street_project_id=street_project_id, **system_overrides
    )
    source = create_funding_source(
        client,
        scenario["water_system_id"],
        authorized_cents=authorized_cents,
        priority_rank=1,
        max_share_pct=max_share_pct,
        equity_required_pct=equity_required_pct,
    )
    order = open_order(
        client,
        scenario["service_line_id"],
        estimated_cost_cents=estimated_cost_cents,
        excavation_start_date=excavation_start_date,
        excavation_end_date=excavation_end_date,
        street_project_id=street_project_id,
    )
    resolve_consent(client, order["id"], outcome=consent_outcome, barrier_reason=barrier_reason)
    funded = plan_funding(client, order["id"])
    scenario.update(
        {
            "funding_source": source,
            "funding_source_id": source["id"],
            "order": funded,
            "order_id": order["id"],
        }
    )
    return scenario


def in_progress_order_on_published_system(
    client: ApiClient, pwsid: str, **overrides: Any
) -> Dict[str, Any]:
    """A funded order that has been scheduled and started."""
    start_date = overrides.get("excavation_start_date", "2026-08-10")
    end_date = overrides.get("excavation_end_date", "2026-08-11")
    scenario = funded_order_on_published_system(client, pwsid, **overrides)
    schedule_order(client, scenario["order_id"], start_date, end_date)
    scenario["order"] = start_order(client, scenario["order_id"])
    return scenario


def bare_system_with_crew(
    client: ApiClient,
    pwsid: str,
    crew_name: str = "Crew Alpha",
    certified_methods: Optional[List[str]] = None,
    daily_appointment_capacity: int = 5,
    shift_start_utc_time: str = "08:00",
    shift_end_utc_time: str = "18:00",
    address_label: str = "101 Elm St",
) -> Dict[str, Any]:
    """One unpublished system, one bare line and one active crew.

    Verification work needs no publication, so this is the cheapest setup for
    appointment scenarios.
    """
    system = create_water_system(client, pwsid, baseline_lead_and_grr_count=100)
    line = create_service_line(client, system["id"], address_label=address_label)
    crew = create_crew(
        client,
        system["id"],
        crew_name=crew_name,
        certified_methods=certified_methods,
        daily_appointment_capacity=daily_appointment_capacity,
        shift_start_utc_time=shift_start_utc_time,
        shift_end_utc_time=shift_end_utc_time,
    )
    return {
        "system": system,
        "line": line,
        "crew": crew,
        "water_system_id": system["id"],
        "service_line_id": line["id"],
        "crew_id": crew["id"],
    }


def reset_clock_baseline() -> str:
    """The instant the logical clock holds when a test starts."""
    return CLOCK_EPOCH
