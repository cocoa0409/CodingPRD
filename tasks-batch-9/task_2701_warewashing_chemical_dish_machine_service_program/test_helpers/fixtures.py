"""
Composite state builders for the Warewashing API.

Every builder drives the API through PRD-declared endpoints only — there is no
back door into the store. Builders use `get_success_data()` so that a broken
setup step fails loudly with the server's own error identifier instead of a
downstream KeyError.

The harness restarts the server before every individual test, so each builder
starts from an empty database and each returns a plain dict of the identifiers
and version tokens the test needs.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from . import factories as F
from .test_users import (
    ACCOUNT_MANAGER_HEADERS,
    AUDITOR_1_HEADERS,
    AUDITOR_2_HEADERS,
    AUDITOR_3_HEADERS,
    PLATFORM_ADMIN_HEADERS,
    make_customer_contact_headers,
    make_technician_headers,
)
from .types import (
    BASIS_NAMEPLATE,
    DECISION_VERIFIED,
    SYMPTOM_RACK_QUALITY,
)

# ─── Tier 0: primitives ────────────────────────────────────────────────


def set_clock(api, current_utc: str) -> Dict[str, Any]:
    """Advance the logical clock (§2.4). Returns the sweep report."""
    return get_success_data(
        api.set_clock(F.clock_payload(current_utc), PLATFORM_ADMIN_HEADERS)
    )


def create_customer(api, **overrides) -> Dict[str, Any]:
    """Register a foodservice account (§3.1)."""
    return get_success_data(
        api.create_customer(F.customer_payload(**overrides), ACCOUNT_MANAGER_HEADERS)
    )


def create_site(api, customer_id: str, **overrides) -> Dict[str, Any]:
    """Register a kitchen under an account (§3.1)."""
    return get_success_data(
        api.create_site(
            F.site_payload(customer_id, **overrides), ACCOUNT_MANAGER_HEADERS
        )
    )


def create_detergent(api, **overrides) -> Dict[str, Any]:
    """Define DET-100 in the chemical catalog (§3.1)."""
    return get_success_data(
        api.create_chemical_product(
            F.detergent_payload(**overrides), PLATFORM_ADMIN_HEADERS
        )
    )


def create_sanitizer(api, **overrides) -> Dict[str, Any]:
    """Define SAN-200 in the chemical catalog (§3.1)."""
    return get_success_data(
        api.create_chemical_product(
            F.sanitizer_payload(**overrides), PLATFORM_ADMIN_HEADERS
        )
    )


def create_rinse_aid(api, **overrides) -> Dict[str, Any]:
    """Define RIN-050 in the chemical catalog (§3.1)."""
    return get_success_data(
        api.create_chemical_product(
            F.rinse_aid_payload(**overrides), PLATFORM_ADMIN_HEADERS
        )
    )


def create_machine_model(api, **overrides) -> Dict[str, Any]:
    """Define DT-88 in the machine catalog (§3.1)."""
    return get_success_data(
        api.create_machine_model(
            F.machine_model_payload(**overrides), PLATFORM_ADMIN_HEADERS
        )
    )


def create_technician(api, **overrides) -> Dict[str, Any]:
    """Add a technician to the dispatch roster (§3.1)."""
    return get_success_data(
        api.create_technician(F.technician_payload(**overrides), PLATFORM_ADMIN_HEADERS)
    )


# ─── Tier 1: agreements ────────────────────────────────────────────────


def create_draft_agreement(
    api, customer_id: str, covered_product_ids: List[str], **overrides
) -> Dict[str, Any]:
    """Draft an agreement (§3.2). The request never carries term_end_date."""
    return get_success_data(
        api.create_service_agreement(
            F.service_agreement_payload(customer_id, covered_product_ids, **overrides),
            ACCOUNT_MANAGER_HEADERS,
        )
    )


def activate_agreement(api, agreement_id: str) -> Dict[str, Any]:
    """Move a DRAFT agreement to ACTIVE, computing term_end_date (§3.2)."""
    return get_success_data(
        api.activate_service_agreement(agreement_id, ACCOUNT_MANAGER_HEADERS)
    )


def create_active_agreement(
    api, customer_id: str, covered_product_ids: List[str], **overrides
) -> Dict[str, Any]:
    """Draft and activate an agreement, returning the ACTIVE row."""
    draft = create_draft_agreement(api, customer_id, covered_product_ids, **overrides)
    return activate_agreement(api, draft["id"])


def agreement_version(api, agreement_id: str) -> int:
    """
    Re-read the agreement's current `version`. §2.7 requires the client to hand
    back the version it last observed, and §3.3 notes that each placement
    create increments it — so a caller placing two machines must re-read
    between them.
    """
    data = get_success_data(
        api.get_service_agreement(agreement_id, ACCOUNT_MANAGER_HEADERS)
    )
    return data["version"]


def site_version(api, site_id: str) -> int:
    """Re-read the site's current `version` for the delivery token of §2.7."""
    data = get_success_data(api.get_site(site_id, ACCOUNT_MANAGER_HEADERS))
    return data["version"]


def dispenser_version(api, dispenser_id: str, technician_id: str) -> int:
    """Re-read the dispenser's current `version` for the token of §2.7."""
    data = get_success_data(
        api.get_dispenser(dispenser_id, make_technician_headers(technician_id))
    )
    return data["version"]


# ─── Tier 2: the canonical program base ────────────────────────────────


def program_base(
    api,
    *,
    with_sanitizer: bool = False,
    customer_overrides: Optional[Dict[str, Any]] = None,
    site_overrides: Optional[Dict[str, Any]] = None,
    model_overrides: Optional[Dict[str, Any]] = None,
    agreement_overrides: Optional[Dict[str, Any]] = None,
    technician_overrides: Optional[Dict[str, Any]] = None,
    activate: bool = True,
) -> Dict[str, Any]:
    """
    The recurring preamble of nearly every scenario: one account, one kitchen,
    the DET-100 detergent (optionally also SAN-200), the DT-88 machine model, an
    agreement covering those products, and one AVAILABLE NW L2 technician.

    Returns a dict of identifiers plus `agreement_version`, the token a
    placement create must carry per §2.7.
    """
    customer = create_customer(api, **(customer_overrides or {}))
    detergent = create_detergent(api)
    sanitizer = create_sanitizer(api) if with_sanitizer else None
    model = create_machine_model(api, **(model_overrides or {}))
    site = create_site(api, customer["id"], **(site_overrides or {}))

    covered = [detergent["id"]]
    if sanitizer is not None:
        covered.append(sanitizer["id"])

    agreement_kwargs = dict(agreement_overrides or {})
    covered_override = agreement_kwargs.pop("covered_product_ids", None)
    if covered_override is not None:
        covered = covered_override

    if activate:
        agreement = create_active_agreement(
            api, customer["id"], covered, **agreement_kwargs
        )
    else:
        agreement = create_draft_agreement(
            api, customer["id"], covered, **agreement_kwargs
        )

    technician = create_technician(api, **(technician_overrides or {}))

    return {
        "customer": customer,
        "customer_id": customer["id"],
        "detergent": detergent,
        "detergent_id": detergent["id"],
        "sanitizer": sanitizer,
        "sanitizer_id": sanitizer["id"] if sanitizer else None,
        "model": model,
        "model_id": model["id"],
        "site": site,
        "site_id": site["id"],
        "agreement": agreement,
        "agreement_id": agreement["id"],
        "agreement_version": agreement["version"],
        "technician": technician,
        "technician_id": technician["id"],
        "technician_headers": make_technician_headers(technician["id"]),
        "customer_headers": make_customer_contact_headers(customer["id"]),
    }


# ─── Tier 3: placements ────────────────────────────────────────────────


def create_placement(
    api,
    base: Dict[str, Any],
    *,
    asset_tag: Optional[str] = None,
    site_id: Optional[str] = None,
    agreement_id: Optional[str] = None,
    model_id: Optional[str] = None,
    expected_agreement_version: Optional[int] = None,
    **overrides,
) -> Dict[str, Any]:
    """
    Place a machine (§3.3), re-reading the agreement version first unless the
    caller pins one deliberately.
    """
    agr_id = agreement_id or base["agreement_id"]
    version = (
        expected_agreement_version
        if expected_agreement_version is not None
        else agreement_version(api, agr_id)
    )
    payload = F.machine_placement_payload(
        site_id or base["site_id"],
        agr_id,
        model_id or base["model_id"],
        version,
        asset_tag=asset_tag,
        **overrides,
    )
    return get_success_data(
        api.create_machine_placement(payload, ACCOUNT_MANAGER_HEADERS)
    )


def install_placement(api, base: Dict[str, Any], placement_id: str) -> Dict[str, Any]:
    """Record physical installation (§3.3)."""
    return get_success_data(
        api.install_machine_placement(placement_id, base["technician_headers"])
    )


def installed_placement(
    api, base: Dict[str, Any], *, asset_tag: Optional[str] = None, **overrides
) -> Dict[str, Any]:
    """Place and install one machine, returning the INSTALLED placement row."""
    placement = create_placement(api, base, asset_tag=asset_tag, **overrides)
    return install_placement(api, base, placement["id"])


def fit_dispenser(
    api,
    base: Dict[str, Any],
    placement_id: str,
    product_id: Optional[str] = None,
    dose: float = 8.00,
) -> Dict[str, Any]:
    """Fit a dispenser to an INSTALLED placement (§3.4)."""
    return get_success_data(
        api.create_dispenser(
            F.dispenser_payload(
                placement_id, product_id or base["detergent_id"], dose
            ),
            base["technician_headers"],
        )
    )


def placement_with_dispenser(
    api,
    base: Dict[str, Any],
    *,
    asset_tag: Optional[str] = None,
    dose: float = 8.00,
    product_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    One INSTALLED placement carrying one dispenser. Returns
    `{"placement": ..., "dispenser": ...}`.
    """
    placement = installed_placement(api, base, asset_tag=asset_tag)
    dispenser = fit_dispenser(
        api, base, placement["id"], product_id=product_id, dose=dose
    )
    return {
        "placement": placement,
        "placement_id": placement["id"],
        "dispenser": dispenser,
        "dispenser_id": dispenser["id"],
        "dispenser_version": dispenser["version"],
    }


# ─── Tier 4: telemetry ─────────────────────────────────────────────────


def ingest_reading(
    api,
    placement_id: str,
    reading_at: str,
    cycle_count_total: int,
    **overrides,
) -> Dict[str, Any]:
    """Ingest one telemetry sample (§3.4). The clock must already be at or past
    `reading_at`, because a future-dated sample is refused."""
    return get_success_data(
        api.create_telemetry_reading(
            placement_id,
            F.telemetry_reading_payload(reading_at, cycle_count_total, **overrides),
            PLATFORM_ADMIN_HEADERS,
        )
    )


def ingest_reading_at_clock(
    api, placement_id: str, instant: str, cycle_count_total: int, **overrides
) -> Dict[str, Any]:
    """Move the clock to `instant` and ingest a sample stamped at that instant."""
    set_clock(api, instant)
    return ingest_reading(api, placement_id, instant, cycle_count_total, **overrides)


def list_alerts_for_placement(api, placement_id: str) -> List[Dict[str, Any]]:
    """Read a placement's alerts through the flat list endpoint (§2.9)."""
    return get_success_data(
        api.list_telemetry_alerts(
            AUDITOR_1_HEADERS, {"placement_id": placement_id, "limit": 100}
        )
    )


def list_readings_for_placement(api, placement_id: str) -> List[Dict[str, Any]]:
    """Read a placement's telemetry stream through the flat list endpoint (§2.9)."""
    return get_success_data(
        api.list_telemetry_readings(
            PLATFORM_ADMIN_HEADERS, {"placement_id": placement_id, "limit": 100}
        )
    )


# ─── Tier 5: tickets, visits and adjudication ──────────────────────────


def file_ticket(
    api,
    base: Dict[str, Any],
    placement_id: str,
    reported_symptom: str = SYMPTOM_RACK_QUALITY,
) -> Dict[str, Any]:
    """File a CUSTOMER_REPORT ticket as the account's own contact (§3.5)."""
    return get_success_data(
        api.create_service_ticket(
            F.service_ticket_payload(placement_id, reported_symptom),
            base["customer_headers"],
        )
    )


def dispatch_ticket(
    api, ticket_id: str, override_technician_id: Optional[str] = None
) -> Dict[str, Any]:
    """Run the dispatch selector on a QUEUED ticket (§3.5)."""
    return get_success_data(
        api.dispatch_service_ticket(
            ticket_id,
            PLATFORM_ADMIN_HEADERS,
            F.dispatch_payload(override_technician_id),
        )
    )


def dispatched_ticket(
    api,
    base: Dict[str, Any],
    placement_id: str,
    reported_symptom: str = SYMPTOM_RACK_QUALITY,
) -> Dict[str, Any]:
    """File then dispatch a ticket, returning the DISPATCHED row."""
    ticket = file_ticket(api, base, placement_id, reported_symptom)
    return dispatch_ticket(api, ticket["id"])


def book_visit(
    api,
    base: Dict[str, Any],
    ticket_id: str,
    scheduled_start_at: str = "2026-08-01T10:00:00Z",
    scheduled_end_at: str = "2026-08-01T11:00:00Z",
    **overrides,
) -> Dict[str, Any]:
    """Book a visit window against a DISPATCHED ticket (§3.6)."""
    return get_success_data(
        api.create_service_visit(
            F.service_visit_payload(
                ticket_id,
                base["technician_id"],
                scheduled_start_at,
                scheduled_end_at,
                **overrides,
            ),
            base["technician_headers"],
        )
    )


def arrive_visit(api, base: Dict[str, Any], visit_id: str) -> Dict[str, Any]:
    """Record arrival on site, moving the visit IN_PROGRESS (§3.6)."""
    return get_success_data(
        api.arrive_service_visit(visit_id, base["technician_headers"])
    )


def visit_in_progress(
    api,
    base: Dict[str, Any],
    placement_id: str,
    *,
    arrival_instant: str = "2026-08-01T10:00:00Z",
    scheduled_start_at: str = "2026-08-01T10:00:00Z",
    scheduled_end_at: str = "2026-08-01T11:00:00Z",
    reported_symptom: str = SYMPTOM_RACK_QUALITY,
) -> Dict[str, Any]:
    """
    A ticket dispatched to the base technician, a visit booked over the window
    and the clock moved to `arrival_instant` so the visit can arrive.
    """
    ticket = dispatched_ticket(api, base, placement_id, reported_symptom)
    visit = book_visit(
        api, base, ticket["id"], scheduled_start_at, scheduled_end_at
    )
    set_clock(api, arrival_instant)
    visit = arrive_visit(api, base, visit["id"])
    return {
        "ticket": ticket,
        "ticket_id": ticket["id"],
        "visit": visit,
        "visit_id": visit["id"],
    }


def record_calibration(
    api,
    base: Dict[str, Any],
    visit_id: str,
    dispenser_id: str,
    measured_ppm: int,
    measured_dose_ml_per_rack: float = 8.00,
    *,
    expected_dispenser_version: Optional[int] = None,
    adjusted_dose_ml_per_rack: Optional[float] = None,
    contact_seconds: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Record one calibration on one dispenser during an IN_PROGRESS visit (§3.6),
    re-reading the dispenser version unless the caller pins one — each record
    increments that version.
    """
    version = (
        expected_dispenser_version
        if expected_dispenser_version is not None
        else dispenser_version(api, dispenser_id, base["technician_id"])
    )
    payload = F.calibration_record_payload(
        dispenser_id,
        measured_ppm,
        measured_dose_ml_per_rack,
        version,
        adjusted_dose_ml_per_rack=adjusted_dose_ml_per_rack,
        contact_seconds=contact_seconds,
    )
    return get_success_data(
        api.create_calibration_record(visit_id, payload, base["technician_headers"])
    )


def submit_visit(
    api, base: Dict[str, Any], visit_id: str, repair_confirmed: Optional[bool] = None
) -> Dict[str, Any]:
    """Submit an IN_PROGRESS visit for audit (§3.6)."""
    return get_success_data(
        api.submit_service_visit(
            visit_id,
            base["technician_headers"],
            F.submit_visit_payload(repair_confirmed),
        )
    )


def verify_visit(
    api,
    visit_id: str,
    decision: str = DECISION_VERIFIED,
    rejection_reason: Optional[str] = None,
    auditor_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Adjudicate a SUBMITTED visit (§3.6). Never the engineer's own call."""
    return get_success_data(
        api.verify_service_visit(
            visit_id,
            F.verify_visit_payload(decision, rejection_reason),
            auditor_headers or AUDITOR_1_HEADERS,
        )
    )


def verified_visit_with_calibration(
    api,
    base: Dict[str, Any],
    placement_id: str,
    dispenser_id: str,
    measured_ppm: int,
    *,
    arrival_instant: str = "2026-08-01T10:00:00Z",
    verification_instant: Optional[str] = None,
    measured_dose_ml_per_rack: float = 8.00,
    adjusted_dose_ml_per_rack: Optional[float] = None,
    contact_seconds: Optional[int] = None,
    repair_confirmed: Optional[bool] = None,
) -> Dict[str, Any]:
    """
    The full field-evidence chain: dispatch, book, arrive, one calibration
    record, submit, and a QualityAuditor verification. The verification instant
    is stamped from the logical clock, so a caller may move the clock forward
    before adjudication.
    """
    stage = visit_in_progress(
        api, base, placement_id, arrival_instant=arrival_instant
    )
    record = record_calibration(
        api,
        base,
        stage["visit_id"],
        dispenser_id,
        measured_ppm,
        measured_dose_ml_per_rack,
        adjusted_dose_ml_per_rack=adjusted_dose_ml_per_rack,
        contact_seconds=contact_seconds,
    )
    submit_visit(api, base, stage["visit_id"], repair_confirmed)
    if verification_instant is not None:
        set_clock(api, verification_instant)
    visit = verify_visit(api, stage["visit_id"])
    return {
        "ticket_id": stage["ticket_id"],
        "visit_id": stage["visit_id"],
        "visit": visit,
        "record": record,
        "record_id": record["id"],
    }


# ─── Tier 6: deliveries, reviews and cases ─────────────────────────────


def record_delivery(
    api,
    base: Dict[str, Any],
    product_id: Optional[str] = None,
    unit_count: int = 1,
    delivered_at: str = "2026-08-05T12:00:00Z",
    *,
    site_id: Optional[str] = None,
    expected_site_version: Optional[int] = None,
) -> Dict[str, Any]:
    """Record a chemical delivery (§3.7), re-reading the site version token."""
    target_site = site_id or base["site_id"]
    version = (
        expected_site_version
        if expected_site_version is not None
        else site_version(api, target_site)
    )
    return get_success_data(
        api.create_chemical_delivery(
            F.chemical_delivery_payload(
                target_site,
                product_id or base["detergent_id"],
                version,
                unit_count,
                delivered_at,
            ),
            ACCOUNT_MANAGER_HEADERS,
        )
    )


def void_delivery(api, delivery_id: str) -> Dict[str, Any]:
    """Void a mis-keyed delivery (§3.7)."""
    return get_success_data(
        api.void_chemical_delivery(delivery_id, ACCOUNT_MANAGER_HEADERS)
    )


def draft_review(
    api,
    base: Dict[str, Any],
    *,
    product_id: Optional[str] = None,
    site_id: Optional[str] = None,
    period_start: str = "2026-08-01T00:00:00Z",
    period_end: str = "2026-09-01T00:00:00Z",
    basis: str = BASIS_NAMEPLATE,
    opening_inventory_ml: int = 5000,
    ending_inventory_ml: int = 5000,
    auditor_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Open a DRAFT variance review over a half-open window (§3.7)."""
    return get_success_data(
        api.create_usage_variance_review(
            F.usage_variance_review_payload(
                site_id or base["site_id"],
                product_id or base["detergent_id"],
                period_start,
                period_end,
                basis,
                opening_inventory_ml,
                ending_inventory_ml,
            ),
            auditor_headers or AUDITOR_1_HEADERS,
        )
    )


def publish_review(
    api, review_id: str, auditor_headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    """
    Publish a DRAFT review (§3.7). The publisher's X-User-ID must differ from
    `created_by_user_id`, so the default publisher is auditor-2.
    """
    return get_success_data(
        api.publish_usage_variance_review(
            review_id, auditor_headers or AUDITOR_2_HEADERS
        )
    )


def published_review(api, base: Dict[str, Any], **kwargs) -> Dict[str, Any]:
    """Draft with auditor-1 and publish with auditor-2, returning the PUBLISHED row."""
    draft = draft_review(api, base, **kwargs)
    return publish_review(api, draft["id"])


def open_case(
    api,
    review_id: str,
    opened_reason: str = "SUSPECTED_THEFT",
    auditor_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Open an investigation case, escalating the review in the same request (§3.8)."""
    return get_success_data(
        api.create_investigation_case(
            F.investigation_case_payload(review_id, opened_reason),
            auditor_headers or AUDITOR_1_HEADERS,
        )
    )


def submit_case(
    api,
    case_id: str,
    evidence_types: List[str],
    auditor_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Attach evidence and move the case to PENDING_REVIEW (§3.8)."""
    return get_success_data(
        api.submit_case_for_review(
            case_id,
            F.submit_for_review_payload(evidence_types),
            auditor_headers or AUDITOR_1_HEADERS,
        )
    )


def review_case(
    api,
    case_id: str,
    decision: str,
    remediation: Optional[str] = None,
    finding_note: Optional[str] = None,
    auditor_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """
    Adjudicate a PENDING_REVIEW case (§3.8). The adjudicating auditor may be
    neither the opener nor the review's publisher, so the default is auditor-3.
    """
    return get_success_data(
        api.review_investigation_case(
            case_id,
            F.case_review_payload(decision, remediation, finding_note),
            auditor_headers or AUDITOR_3_HEADERS,
        )
    )
