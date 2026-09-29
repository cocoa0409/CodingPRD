"""Composite setup helpers.

The harness restarts the API server before every individual test, so every
fixture below builds its preconditions from an empty database.  Nothing here
asserts business outcomes: each step uses get_success_data() so that a broken
setup fails loudly with the server's own error_id rather than silently
producing a misleading test result.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data, validate_paginated

from . import factories as f
from .api_client import RoiApiClient
from .constants import DEFAULT_CLOCK_UTC
from .test_users import (
    ANALYST_1,
    BILLING_1,
    INTAKE_1,
    PLATFORM_ADMIN,
    PRIVACY_1,
    REVIEWER_1,
    REVIEWER_2,
    make_facility_admin_headers,
    make_requester_headers,
)


# ---------------------------------------------------------------- clock
def set_clock(api: RoiApiClient, to_iso8601: str = DEFAULT_CLOCK_UTC) -> dict:
    return get_success_data(api.set_clock(to_iso8601, PLATFORM_ADMIN))


# ---------------------------------------------------------------- leaf entities
def make_fee_rule(api: RoiApiClient, **overrides: Any) -> dict:
    return get_success_data(api.create_state_fee_rule(f.state_fee_rule_payload(**overrides), PLATFORM_ADMIN))


def make_facility(api: RoiApiClient, fee_rule_id: str, **overrides: Any) -> dict:
    return get_success_data(api.create_facility(f.facility_payload(fee_rule_id, **overrides), PLATFORM_ADMIN))


def make_patient(api: RoiApiClient, facility_id: str, **overrides: Any) -> dict:
    headers = make_facility_admin_headers(facility_id)
    return get_success_data(api.create_patient(f.patient_payload(facility_id, **overrides), headers))


def make_attorney(api: RoiApiClient, **overrides: Any) -> dict:
    return get_success_data(api.create_requester(f.attorney_requester_payload(**overrides), INTAKE_1))


def make_insurer(api: RoiApiClient, **overrides: Any) -> dict:
    return get_success_data(api.create_requester(f.insurer_requester_payload(**overrides), INTAKE_1))


def make_patient_requester(api: RoiApiClient, patient_id: str, **overrides: Any) -> dict:
    return get_success_data(
        api.create_requester(f.patient_requester_payload(patient_id, **overrides), INTAKE_1)
    )


def patient_version(api: RoiApiClient, patient_id: str) -> int:
    return get_success_data(api.get_patient(patient_id, INTAKE_1))["version"]


def request_version(api: RoiApiClient, request_id: str) -> int:
    return get_success_data(api.get_request(request_id, BILLING_1))["version"]


def make_authorization(
    api: RoiApiClient,
    patient_id: str,
    requester_id: str,
    scope_categories: Optional[List[str]] = None,
    **overrides: Any,
) -> dict:
    payload = f.authorization_payload(
        patient_id,
        requester_id,
        patient_version(api, patient_id),
        scope_categories=scope_categories,
        **overrides,
    )
    return get_success_data(api.create_authorization(payload, INTAKE_1))


# ---------------------------------------------------------------- worlds
def base_world(api: RoiApiClient, clock: str = DEFAULT_CLOCK_UTC, **facility_overrides: Any) -> Dict[str, Any]:
    """Clock, CA fee rule, one facility, one patient."""
    set_clock(api, clock)
    fee_rule = make_fee_rule(api)
    facility = make_facility(api, fee_rule["id"], **facility_overrides)
    patient = make_patient(api, facility["id"])
    return {
        "fee_rule_id": fee_rule["id"],
        "facility_id": facility["id"],
        "patient_id": patient["id"],
        "facility_admin_headers": make_facility_admin_headers(facility["id"]),
    }


def third_party_world(
    api: RoiApiClient,
    clock: str = DEFAULT_CLOCK_UTC,
    scope_categories: Optional[List[str]] = None,
    facility_overrides: Optional[Dict[str, Any]] = None,
    **authorization_overrides: Any,
) -> Dict[str, Any]:
    """base_world plus an ATTORNEY requesting party holding one authorization."""
    world = base_world(api, clock, **(facility_overrides or {}))
    attorney = make_attorney(api)
    authorization = make_authorization(
        api,
        world["patient_id"],
        attorney["id"],
        scope_categories=scope_categories,
        **authorization_overrides,
    )
    world.update(
        {
            "requester_id": attorney["id"],
            "requester_headers": make_requester_headers(attorney["id"]),
            "authorization_id": authorization["id"],
            "authorization": authorization,
        }
    )
    return world


def patient_access_world(
    api: RoiApiClient, clock: str = DEFAULT_CLOCK_UTC, facility_overrides: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """base_world plus a PATIENT requesting party linked to that patient."""
    world = base_world(api, clock, **(facility_overrides or {}))
    requester = make_patient_requester(api, world["patient_id"])
    world.update(
        {
            "requester_id": requester["id"],
            "requester_headers": make_requester_headers(requester["id"]),
        }
    )
    return world


# ---------------------------------------------------------------- requests
def open_third_party_request(api: RoiApiClient, world: Dict[str, Any], **overrides: Any) -> dict:
    payload = f.third_party_request_payload(
        world["facility_id"],
        world["patient_id"],
        world["requester_id"],
        world["authorization_id"],
        **overrides,
    )
    return get_success_data(api.create_request(payload, INTAKE_1))


def open_patient_access_request(api: RoiApiClient, world: Dict[str, Any], **overrides: Any) -> dict:
    payload = f.patient_access_request_payload(
        world["facility_id"], world["patient_id"], world["requester_id"], **overrides
    )
    return get_success_data(api.create_request(payload, INTAKE_1))


def accept_request(api: RoiApiClient, request_id: str) -> dict:
    return get_success_data(api.intake_decision(request_id, f.intake_decision_payload("ACCEPT"), INTAKE_1))


# ---------------------------------------------------------------- segments
def open_segment(
    api: RoiApiClient,
    request_id: str,
    category: str = "GENERAL_MEDICAL",
    source_system: str = "EHR_CURRENT",
    **overrides: Any,
) -> dict:
    payload = f.record_segment_payload(request_id, category, source_system, **overrides)
    return get_success_data(api.create_record_segment(payload, ANALYST_1))


def retrieve_segment(api: RoiApiClient, segment_id: str, page_count: int, headers: dict = ANALYST_1) -> dict:
    return get_success_data(api.segment_disposition(segment_id, f.retrieved_payload(page_count), headers))


def add_retrieved_segment(
    api: RoiApiClient,
    request_id: str,
    page_count: int,
    category: str = "GENERAL_MEDICAL",
    source_system: str = "EHR_CURRENT",
    **overrides: Any,
) -> str:
    segment = open_segment(api, request_id, category, source_system, **overrides)
    retrieve_segment(api, segment["id"], page_count)
    return segment["id"]


def complete_compilation(api: RoiApiClient, request_id: str) -> dict:
    return get_success_data(api.complete_compilation(request_id, {}, ANALYST_1))


def run_sensitive_review(
    api: RoiApiClient,
    request_id: str,
    segment_decisions: Optional[List[Dict[str, Any]]] = None,
    headers: dict = REVIEWER_1,
) -> dict:
    payload = f.sensitive_review_payload(segment_decisions)
    return get_success_data(api.sensitive_review(request_id, payload, headers))


def apply_redaction(api: RoiApiClient, segment_id: str, pages: int, headers: dict = ANALYST_1) -> dict:
    return get_success_data(api.apply_redaction(segment_id, f.redaction_payload(pages), headers))


def approve_redaction(api: RoiApiClient, segment_id: str, headers: dict = REVIEWER_1) -> dict:
    return get_success_data(
        api.redaction_decision(segment_id, f.redaction_decision_payload("APPROVE"), headers)
    )


# ---------------------------------------------------------------- billing
def create_invoice(api: RoiApiClient, request_id: str) -> dict:
    payload = f.invoice_payload(request_id, request_version(api, request_id))
    return get_success_data(api.create_invoice(payload, BILLING_1))


def issue_invoice(api: RoiApiClient, invoice_id: str) -> dict:
    return get_success_data(api.issue_invoice(invoice_id, {}, BILLING_1))


def pay_invoice(api: RoiApiClient, invoice_id: str, amount_cents: int) -> dict:
    return get_success_data(api.settle_invoice(invoice_id, f.pay_payload(amount_cents), BILLING_1))


def waive_invoice(api: RoiApiClient, invoice_id: str) -> dict:
    return get_success_data(api.settle_invoice(invoice_id, f.waive_payload(), BILLING_1))


def void_invoice(api: RoiApiClient, invoice_id: str, reason: str = "BILLING_CLERK_VOID") -> dict:
    return get_success_data(api.settle_invoice(invoice_id, f.void_payload(reason), BILLING_1))


def invoice_and_pay(api: RoiApiClient, request_id: str) -> dict:
    """Price, issue and pay exactly amount_due_cents so the release gate opens."""
    invoice = create_invoice(api, request_id)
    issue_invoice(api, invoice["id"])
    pay_invoice(api, invoice["id"], invoice["amount_due_cents"])
    return invoice


def invoice_and_waive(api: RoiApiClient, request_id: str) -> dict:
    invoice = create_invoice(api, request_id)
    issue_invoice(api, invoice["id"])
    waive_invoice(api, invoice["id"])
    return invoice


# ---------------------------------------------------------------- release / delivery
def release_request(api: RoiApiClient, request_id: str, headers: dict = REVIEWER_2) -> dict:
    return get_success_data(api.release_request(request_id, f.release_payload(), headers))


def open_delivery(api: RoiApiClient, request_id: str, **overrides: Any) -> dict:
    return get_success_data(api.create_delivery(f.delivery_payload(request_id, **overrides), REVIEWER_2))


# ---------------------------------------------------------------- reads
def read_request(api: RoiApiClient, request_id: str, headers: dict = BILLING_1) -> dict:
    return get_success_data(api.get_request(request_id, headers))


def read_segment(api: RoiApiClient, segment_id: str, headers: dict = ANALYST_1) -> dict:
    return get_success_data(api.get_record_segment(segment_id, headers))


def read_invoice(api: RoiApiClient, invoice_id: str, headers: dict = BILLING_1) -> dict:
    return get_success_data(api.get_invoice(invoice_id, headers))


def read_facility(api: RoiApiClient, facility_id: str, headers: dict = PLATFORM_ADMIN) -> dict:
    return get_success_data(api.get_facility(facility_id, headers))


def read_lines(api: RoiApiClient, invoice_id: str, headers: dict = BILLING_1) -> List[dict]:
    body = api.list_invoice_lines(invoice_id, headers, {"limit": 100})
    return get_success_data(body)


def read_events(api: RoiApiClient, request_id: str, params: Optional[dict] = None) -> List[dict]:
    query = {"limit": 100}
    if params:
        query.update(params)
    return get_success_data(api.list_compliance_events(request_id, PRIVACY_1, query))


# ---------------------------------------------------------------- workflow walks
def build_segments(api: RoiApiClient, request_id: str, specs: List[Dict[str, Any]]) -> Dict[str, str]:
    """Open one segment per spec and dispose of it.

    Each spec carries a ``label`` used as the returned dictionary key, plus
    ``category``, ``page_count``, ``source_system`` and an optional
    ``disposition`` of RETRIEVED (the default), UNAVAILABLE or PENDING.
    """
    ids: Dict[str, str] = {}
    for spec in specs:
        extra = {}
        if spec.get("legacy_job_start_at"):
            extra["legacy_job_start_at"] = spec["legacy_job_start_at"]
        segment = open_segment(
            api,
            request_id,
            spec.get("category", "GENERAL_MEDICAL"),
            spec.get("source_system", "EHR_CURRENT"),
            **extra,
        )
        ids[spec["label"]] = segment["id"]
        disposition = spec.get("disposition", "RETRIEVED")
        if disposition == "RETRIEVED":
            retrieve_segment(api, segment["id"], spec["page_count"])
        elif disposition == "UNAVAILABLE":
            get_success_data(
                api.segment_disposition(
                    segment["id"],
                    f.unavailable_payload(spec.get("unavailable_reason", "chart destroyed")),
                    ANALYST_1,
                )
            )
    return ids


def walk_to_sensitive_review(
    api: RoiApiClient, request_id: str, segment_specs: List[Dict[str, Any]]
) -> Dict[str, str]:
    """Accept the request, compile the given segments and declare compilation finished."""
    accept_request(api, request_id)
    ids = build_segments(api, request_id, segment_specs)
    complete_compilation(api, request_id)
    return ids


def simple_third_party_request_at_release_ready(
    api: RoiApiClient, world: Dict[str, Any], page_count: int = 62, **request_overrides: Any
) -> Dict[str, Any]:
    """One general-medical segment, nothing segregated, straight to RELEASE_READY."""
    request = open_third_party_request(api, world, **request_overrides)
    ids = walk_to_sensitive_review(
        api, request["id"], [{"label": "gen", "category": "GENERAL_MEDICAL", "page_count": page_count}]
    )
    run_sensitive_review(api, request["id"], [])
    return {"request_id": request["id"], "segment_ids": ids}


def simple_patient_access_request_at_release_ready(
    api: RoiApiClient, world: Dict[str, Any], page_count: int = 62, **request_overrides: Any
) -> Dict[str, Any]:
    request = open_patient_access_request(api, world, **request_overrides)
    ids = walk_to_sensitive_review(
        api, request["id"], [{"label": "gen", "category": "GENERAL_MEDICAL", "page_count": page_count}]
    )
    run_sensitive_review(api, request["id"], [])
    return {"request_id": request["id"], "segment_ids": ids}


def released_third_party_request(
    api: RoiApiClient, world: Dict[str, Any], page_count: int = 62, **request_overrides: Any
) -> Dict[str, Any]:
    """RELEASE_READY, then invoiced, paid and released by u-review-2."""
    scenario = simple_third_party_request_at_release_ready(api, world, page_count, **request_overrides)
    invoice = invoice_and_pay(api, scenario["request_id"])
    release_request(api, scenario["request_id"])
    scenario["invoice_id"] = invoice["id"]
    scenario["invoice"] = invoice
    return scenario


# ---------------------------------------------------------------- paginated listings
def list_deliveries_for(api: RoiApiClient, request_id: str, headers: dict = REVIEWER_2, **params: Any):
    """(rows, meta) for the deliveries of one request."""
    query = {"request_id": request_id, "limit": 100}
    query.update(params)
    return validate_paginated(api.list_deliveries(headers, query))


def list_invoices_for(api: RoiApiClient, request_id: str, headers: dict = BILLING_1, **params: Any):
    query = {"request_id": request_id, "limit": 100}
    query.update(params)
    return validate_paginated(api.list_invoices(headers, query))


def list_segments_for(api: RoiApiClient, request_id: str, headers: dict = ANALYST_1, **params: Any):
    query = {"request_id": request_id, "limit": 100}
    query.update(params)
    return validate_paginated(api.list_record_segments(headers, query))


def list_authorizations_for(api: RoiApiClient, patient_id: str, headers: dict = INTAKE_1, **params: Any):
    query = {"patient_id": patient_id, "limit": 100}
    query.update(params)
    return validate_paginated(api.list_authorizations(headers, query))


def list_lines_of(api: RoiApiClient, invoice_id: str, headers: dict = BILLING_1, **params: Any):
    query = {"limit": 100}
    query.update(params)
    return validate_paginated(api.list_invoice_lines(invoice_id, headers, query))


def list_events_of(api: RoiApiClient, request_id: str, headers: dict = PRIVACY_1, **params: Any):
    query = {"limit": 100}
    query.update(params)
    return validate_paginated(api.list_compliance_events(request_id, headers, query))
