"""
Entity builders for the Ocean Cargo Insurance API.

Every builder drives the public API — nothing is inserted behind the API's
back — and returns the created row's `data` object. Each builder starts from a
canonical payload in `constants` and accepts keyword overrides, so a test that
cares about one field can name only that field.

The server is restarted with an empty database before every test, so builders
are always called from scratch inside the test that needs them.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from . import constants as C
from .api_client import ApiClient
from .test_users import (
    CLAIMS_ADJUSTER,
    COMPLIANCE_OFFICER,
    PLATFORM_ADMIN,
    PREMIUM_AUDITOR,
    UNDERWRITER,
    make_assured_headers,
    make_surveyor_headers,
)
from .types import Headers, JsonDict


def _merge(base: JsonDict, overrides: Dict[str, Any]) -> JsonDict:
    payload = dict(base)
    payload.update({k: v for k, v in overrides.items() if v is not None})
    return payload


# ---------------------------------------------------------------------------
# Reference data
# ---------------------------------------------------------------------------
def create_port(api: ApiClient, base: Optional[JsonDict] = None,
                headers: Headers = UNDERWRITER, **overrides: Any) -> JsonDict:
    """Create a port. Defaults to green-tier Singapore."""
    payload = _merge(base or C.PORT_SGSIN, overrides)
    return get_success_data(api.create_port(payload, headers))


def create_commodity_class(api: ApiClient, headers: Headers = UNDERWRITER,
                           **overrides: Any) -> JsonDict:
    """Create a commodity class. Defaults to S3 consumer electronics."""
    payload = _merge(C.COMMODITY_CLASS_ELECTRONICS, overrides)
    return get_success_data(api.create_commodity_class(payload, headers))


def create_vessel(api: ApiClient, base: Optional[JsonDict] = None,
                  review: bool = True, headers: Headers = UNDERWRITER,
                  **overrides: Any) -> JsonDict:
    """
    Create a hull and, unless `review=False`, run its classification review so
    the hull reaches its screened status.
    """
    payload = _merge(base or C.VESSEL_KITE, overrides)
    vessel = get_success_data(api.create_vessel(payload, headers))
    if review:
        vessel = get_success_data(
            api.review_vessel_classification(vessel["id"], headers))
    return vessel


def create_surveyor(api: ApiClient, base_port_id: str,
                    headers: Headers = COMPLIANCE_OFFICER,
                    **overrides: Any) -> JsonDict:
    """Appoint a panel surveyor based at `base_port_id`."""
    payload = _merge(C.SURVEYOR_ROTTERDAM, overrides)
    payload["base_port_id"] = base_port_id
    return get_success_data(api.create_surveyor(payload, headers))


# ---------------------------------------------------------------------------
# Open cover
# ---------------------------------------------------------------------------
def create_open_policy(api: ApiClient, activate: bool = True,
                       headers: Headers = UNDERWRITER,
                       **overrides: Any) -> JsonDict:
    """Write an open cover and, unless `activate=False`, activate it."""
    payload = _merge(C.OPEN_POLICY_CANONICAL, overrides)
    policy = get_success_data(api.create_open_policy(payload, headers))
    if activate:
        policy = get_success_data(api.activate_open_policy(policy["id"], headers))
    return policy


def policy_version(api: ApiClient, policy_id: str,
                   headers: Headers = UNDERWRITER) -> int:
    """Read the open cover's current version, for the issue precondition."""
    return get_success_data(api.get_open_policy(policy_id, headers))["version"]


def ga_event_version(api: ApiClient, ga_event_id: str,
                     headers: Headers = CLAIMS_ADJUSTER) -> int:
    """Read the general average event's current version, for the post precondition."""
    return get_success_data(api.get_ga_event(ga_event_id, headers))["version"]


# ---------------------------------------------------------------------------
# Certificates
# ---------------------------------------------------------------------------
def create_certificate(api: ApiClient, policy_id: str, commodity_class_id: str,
                       vessel_id: str, loading_port_id: str,
                       discharge_port_id: str,
                       base: Optional[JsonDict] = None,
                       headers: Optional[Headers] = None,
                       **overrides: Any) -> JsonDict:
    """
    Declare a shipment against an open cover. The assured acts with the open
    cover's own identifier unless the caller passes different headers.
    """
    payload = _merge(base or C.CERTIFICATE_CIF_SHIPMENT, overrides)
    payload.update({
        "open_policy_id": policy_id,
        "commodity_class_id": commodity_class_id,
        "vessel_id": vessel_id,
        "loading_port_id": loading_port_id,
        "discharge_port_id": discharge_port_id,
    })
    return get_success_data(
        api.create_certificate(payload, headers or make_assured_headers(policy_id)))


def issue_certificate(api: ApiClient, certificate_id: str, policy_id: str,
                      headers: Headers = UNDERWRITER,
                      expected_version: Optional[int] = None) -> JsonDict:
    """
    Issue a draft certificate, reading the open cover's current version first
    so the precondition matches.
    """
    version = (expected_version if expected_version is not None
               else policy_version(api, policy_id, headers))
    return get_success_data(api.issue_certificate(
        certificate_id, {"expected_open_policy_version": version}, headers))


def create_issued_certificate(api: ApiClient, env: JsonDict,
                              base: Optional[JsonDict] = None,
                              **overrides: Any) -> JsonDict:
    """
    Declare and immediately issue one shipment against the environment built by
    `fixtures.build_canonical_environment`. Returns the issued certificate.
    """
    certificate = create_certificate(
        api,
        env["policy_id"],
        env["commodity_class_id"],
        overrides.pop("vessel_id", env["vessel_id"]),
        overrides.pop("loading_port_id", env["loading_port_id"]),
        overrides.pop("discharge_port_id", env["discharge_port_id"]),
        base=base,
        **overrides,
    )
    return issue_certificate(api, certificate["id"], env["policy_id"])


# ---------------------------------------------------------------------------
# Premium declarations
# ---------------------------------------------------------------------------
def create_declaration(api: ApiClient, policy_id: str,
                       period_start: str = "2026-08-01T00:00:00Z",
                       period_end: str = "2026-09-01T00:00:00Z") -> JsonDict:
    """Open a premium declaration for a reporting period."""
    payload = {"open_policy_id": policy_id, "period_start": period_start,
               "period_end": period_end}
    return get_success_data(
        api.create_premium_declaration(payload, make_assured_headers(policy_id)))


def submit_declaration(api: ApiClient, declaration_id: str, policy_id: str,
                       declared_premium_total: float) -> JsonDict:
    """Report a premium total for an open declaration."""
    return get_success_data(api.submit_premium_declaration(
        declaration_id, {"declared_premium_total": declared_premium_total},
        make_assured_headers(policy_id)))


def audit_declaration(api: ApiClient, declaration_id: str,
                      audit_note: Optional[str] = None,
                      headers: Headers = PREMIUM_AUDITOR) -> JsonDict:
    """Take a submitted declaration through audit to its outcome."""
    get_success_data(api.start_declaration_audit(declaration_id, headers))
    payload = {"audit_note": audit_note} if audit_note is not None else {}
    return get_success_data(
        api.finish_declaration_audit(declaration_id, headers, payload))


# ---------------------------------------------------------------------------
# Claims, evidence and surveys
# ---------------------------------------------------------------------------
def open_claim_file(api: ApiClient, certificate_id: str,
                    loss_type: str = "PARTICULAR_AVERAGE",
                    peril: str = "WET_DAMAGE",
                    adjustment_basis: str = "DEPRECIATION_PCT",
                    claimed_amount: float = C.EXPECTED_CLAIM_GROSS,
                    loss_date: str = "2026-08-20T00:00:00Z",
                    headers: Headers = CLAIMS_ADJUSTER,
                    **overrides: Any) -> JsonDict:
    """Open a claim on an issued certificate."""
    payload = {
        "certificate_id": certificate_id,
        "loss_type": loss_type,
        "peril": peril,
        "adjustment_basis": adjustment_basis,
        "claimed_amount": claimed_amount,
        "loss_date": loss_date,
    }
    payload.update({k: v for k, v in overrides.items() if v is not None})
    return get_success_data(api.create_claim_file(payload, headers))


def add_claim_document(api: ApiClient, claim_id: str, doc_type: str,
                      reference: str, received_at: Optional[str] = None,
                      headers: Headers = CLAIMS_ADJUSTER) -> JsonDict:
    """Append one document to a claim's evidence log."""
    payload: JsonDict = {"doc_type": doc_type, "reference": reference}
    if received_at is not None:
        payload["received_at"] = received_at
    return get_success_data(api.add_claim_document(claim_id, payload, headers))


def complete_claim_documents(api: ApiClient, claim_id: str,
                             doc_types: Optional[List[str]] = None,
                             reference_prefix: str = "DOC",
                             received_at: str = "2026-08-22T00:00:00Z",
                             headers: Headers = CLAIMS_ADJUSTER) -> List[JsonDict]:
    """
    Append the documents a claim needs before it can be adjusted. Defaults to
    the survey report, the bill of lading and the carrier claim letter.
    """
    created = []
    for index, doc_type in enumerate(doc_types or C.REQUIRED_CLAIM_DOCUMENTS, start=1):
        created.append(add_claim_document(
            api, claim_id, doc_type, f"{reference_prefix}-{index}",
            received_at, headers))
    return created


def create_survey_order(api: ApiClient, claim_file_id: str, surveyor_id: str,
                        window_start_at: str = "2026-09-08T09:00:00Z",
                        window_end_at: str = "2026-09-08T11:00:00Z",
                        headers: Headers = CLAIMS_ADJUSTER) -> JsonDict:
    """Appoint a surveyor to attend a claim inside a window."""
    payload = {
        "claim_file_id": claim_file_id,
        "surveyor_id": surveyor_id,
        "window_start_at": window_start_at,
        "window_end_at": window_end_at,
    }
    return get_success_data(api.create_survey_order(payload, headers))


def file_survey_report(api: ApiClient, order_id: str, surveyor_id: str,
                       report_reference: str = "SR-1",
                       packaging_compliant: bool = True,
                       damage_percentage_found: Optional[float] = None) -> JsonDict:
    """File a survey report as the appointed surveyor."""
    payload: JsonDict = {
        "packaging_compliant": packaging_compliant,
        "report_reference": report_reference,
    }
    if damage_percentage_found is not None:
        payload["damage_percentage_found"] = damage_percentage_found
    return get_success_data(api.file_survey_report(
        order_id, payload, make_surveyor_headers(surveyor_id)))


def adjust_claim_file(api: ApiClient, claim_id: str,
                      headers: Headers = CLAIMS_ADJUSTER,
                      **payload: Any) -> JsonDict:
    """Adjust a claim whose evidence log is complete."""
    return get_success_data(api.adjust_claim_file(
        claim_id, headers, {k: v for k, v in payload.items() if v is not None}))


# ---------------------------------------------------------------------------
# General average
# ---------------------------------------------------------------------------
def declare_ga_event(api: ApiClient, vessel_id: str,
                     headers: Headers = CLAIMS_ADJUSTER,
                     **overrides: Any) -> JsonDict:
    """Declare a general average on a conveyance."""
    payload = _merge(C.GA_EVENT_CANONICAL, overrides)
    payload["vessel_id"] = vessel_id
    return get_success_data(api.create_ga_event(payload, headers))


def issue_ga_security_calls(api: ApiClient, ga_event_id: str,
                            headers: Headers = CLAIMS_ADJUSTER) -> JsonDict:
    """Issue the security calls for a declared general average."""
    return get_success_data(api.issue_ga_security_calls(ga_event_id, headers))


def ga_posting_for_certificate(api: ApiClient, ga_event_id: str,
                               certificate_id: str,
                               headers: Headers = CLAIMS_ADJUSTER) -> JsonDict:
    """Find the security posting raised against one certificate."""
    params = {"ga_event_id": ga_event_id, "certificate_id": certificate_id}
    rows = get_success_data(api.list_ga_security_postings(headers, params))
    assert rows, (
        f"No security posting found for certificate {certificate_id} "
        f"on event {ga_event_id}"
    )
    return rows[0]


def post_ga_security(api: ApiClient, posting_id: str, policy_id: str,
                     guarantee_amount: float, cash_deposit_amount: float,
                     expected_ga_event_version: Optional[int] = None,
                     ga_event_id: Optional[str] = None) -> JsonDict:
    """
    Lodge security against a posting, reading the event's current version first
    so the precondition matches.
    """
    version = expected_ga_event_version
    if version is None:
        assert ga_event_id, "ga_event_id is required to read the event version"
        version = ga_event_version(api, ga_event_id)
    payload = {
        "expected_ga_event_version": version,
        "guarantee_amount": guarantee_amount,
        "cash_deposit_amount": cash_deposit_amount,
    }
    return get_success_data(api.post_ga_security(
        posting_id, payload, make_assured_headers(policy_id)))


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
def set_clock(api: ApiClient, current_utc: str,
              headers: Headers = PLATFORM_ADMIN) -> JsonDict:
    """Move the logical clock to a fixed instant."""
    return get_success_data(
        api.set_current_utc({"current_utc": current_utc}, headers))
