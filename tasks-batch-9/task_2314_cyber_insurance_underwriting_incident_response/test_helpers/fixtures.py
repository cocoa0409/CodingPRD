"""Composite state builders.

Every builder drives the public API only — no direct database access — and
returns the created rows so a test can assert against them. The builders are
plain functions so that a test can vary any step; `conftest.py` wraps the most
common chains as pytest fixtures.
"""
from . import constants as C
from . import factories as F
from .assertions import data_of, get_rows
from .test_users import (
    ADJUSTER_2_HEADERS,
    ADJUSTER_HEADERS,
    PANEL_ADMIN_HEADERS,
    UNDERWRITER_2_HEADERS,
    UNDERWRITER_HEADERS,
)


# ==========================================================================
# Clock
# ==========================================================================
def set_clock(client, instant, headers=None):
    return data_of(client.set_clock(instant, headers or UNDERWRITER_HEADERS))


# ==========================================================================
# Catalog
# ==========================================================================
def seed_catalog(client, rows=None, headers=None):
    """Create the control catalog and return {control_key: row}."""
    headers = headers or UNDERWRITER_HEADERS
    rows = rows if rows is not None else C.STANDARD_CATALOG
    created = {}
    for spec in rows:
        row = data_of(client.create_control_requirement(dict(spec), headers), 201)
        created[row["control_key"]] = row
    return created


# ==========================================================================
# Accounts and applications
# ==========================================================================
def create_account(client, spec=None, headers=None, **overrides):
    headers = headers or UNDERWRITER_HEADERS
    payload = dict(spec if spec is not None else C.ACCOUNT_AURORA)
    payload.update(overrides)
    return data_of(client.create_insured_account(payload, headers), 201)


def create_application(
    client,
    account_id,
    requested_aggregate_limit_usd=5000000,
    requested_retention_usd=250000,
    dependent_bi_definition="NAMED_PLUS_SUPPLY_CHAIN",
    headers=None,
    **overrides,
):
    headers = headers or UNDERWRITER_HEADERS
    payload = F.application_payload(
        account_id,
        requested_aggregate_limit_usd=requested_aggregate_limit_usd,
        requested_retention_usd=requested_retention_usd,
        dependent_bi_definition=dependent_bi_definition,
        **overrides,
    )
    return data_of(client.create_application(payload, headers), 201)


def attest_controls(client, application_id, levels, headers=None):
    """Attest each control_key -> attested_level pair, in catalog order."""
    headers = headers or UNDERWRITER_HEADERS
    created = {}
    for control_key in C.ALL_CONTROL_KEYS:
        if control_key not in levels:
            continue
        row = data_of(
            client.create_control_attestation(
                application_id,
                F.control_attestation_payload(control_key, levels[control_key]),
                headers,
            ),
            201,
        )
        created[control_key] = row
    return created


def submit_application(client, application_id, headers=None):
    return data_of(client.submit_application(application_id, headers or UNDERWRITER_HEADERS))


def order_scan(client, application_id, scan_score=68, vendor_name="Perimeter Signal", headers=None):
    return data_of(
        client.create_external_scan(
            application_id, F.external_scan_payload(vendor_name, scan_score), headers or UNDERWRITER_HEADERS
        ),
        201,
    )


def complete_scan(client, scan_id, findings=None, outcome="COMPLETED", headers=None):
    return data_of(
        client.complete_external_scan(
            scan_id, F.scan_complete_payload(outcome, findings), headers or UNDERWRITER_HEADERS
        )
    )


def read_application(client, application_id, headers=None):
    return data_of(client.get_application(application_id, headers or UNDERWRITER_HEADERS))


def quote_application(client, application_id, headers=None):
    """Read the current version, then issue the quote against it."""
    headers = headers or UNDERWRITER_HEADERS
    current = read_application(client, application_id, headers)
    return data_of(
        client.quote_application(
            application_id, F.quote_payload(current["version"]), headers
        )
    )


def bind_application(
    client,
    application_id,
    coverage_sections=None,
    period_start="2026-08-01T00:00:00Z",
    period_end="2027-08-01T00:00:00Z",
    bi_baseline_method="TRAILING_12M",
    headers=None,
    **overrides,
):
    """Bind as a different underwriter than the one that quoted (PRD §2.11)."""
    headers = headers or UNDERWRITER_2_HEADERS
    current = read_application(client, application_id, UNDERWRITER_HEADERS)
    payload = F.bind_payload(
        current["version"],
        period_start=period_start,
        period_end=period_end,
        bi_baseline_method=bi_baseline_method,
        coverage_sections=coverage_sections,
        **overrides,
    )
    return data_of(client.bind_application(application_id, payload, headers), 201)


# ==========================================================================
# Whole-chain builders
# ==========================================================================
def quoted_application(
    client,
    account_spec=None,
    attestations=None,
    requested_aggregate_limit_usd=5000000,
    requested_retention_usd=250000,
    dependent_bi_definition="NAMED_PLUS_SUPPLY_CHAIN",
    scan_score=68,
    findings=None,
    seed=True,
    catalog_rows=None,
):
    """Catalog -> account -> application -> attest -> submit -> scan -> quote."""
    catalog = seed_catalog(client, catalog_rows) if seed else None
    account = create_account(client, account_spec)
    application = create_application(
        client,
        account["id"],
        requested_aggregate_limit_usd=requested_aggregate_limit_usd,
        requested_retention_usd=requested_retention_usd,
        dependent_bi_definition=dependent_bi_definition,
    )
    attested = attest_controls(
        client, application["id"], attestations if attestations is not None else C.ATTEST_95
    )
    submit_application(client, application["id"])
    scan = order_scan(client, application["id"], scan_score)
    complete_scan(client, scan["id"], findings)
    quoted = quote_application(client, application["id"])
    return {
        "catalog": catalog,
        "account": account,
        "application": quoted,
        "attestations": attested,
        "scan": scan,
    }


def bound_policy(
    client,
    account_spec=None,
    attestations=None,
    requested_aggregate_limit_usd=5000000,
    requested_retention_usd=250000,
    dependent_bi_definition="NAMED_PLUS_SUPPLY_CHAIN",
    coverage_sections=None,
    period_start="2026-08-01T00:00:00Z",
    period_end="2027-08-01T00:00:00Z",
    bi_baseline_method="TRAILING_12M",
    scan_score=68,
    findings=None,
    seed=True,
    catalog_rows=None,
):
    """The quoted-application chain plus the bind, returning the tower too."""
    chain = quoted_application(
        client,
        account_spec=account_spec,
        attestations=attestations,
        requested_aggregate_limit_usd=requested_aggregate_limit_usd,
        requested_retention_usd=requested_retention_usd,
        dependent_bi_definition=dependent_bi_definition,
        scan_score=scan_score,
        findings=findings,
        seed=seed,
        catalog_rows=catalog_rows,
    )
    policy = bind_application(
        client,
        chain["application"]["id"],
        coverage_sections=coverage_sections,
        period_start=period_start,
        period_end=period_end,
        bi_baseline_method=bi_baseline_method,
    )
    sections = get_rows(
        client.list_policy_coverage_sections(policy["id"], UNDERWRITER_HEADERS)
    )
    chain["policy"] = policy
    chain["sections"] = {row["section_key"]: row for row in sections}
    return chain


# ==========================================================================
# Panel vendors
# ==========================================================================
def create_vendor(client, spec=None, headers=None, **overrides):
    headers = headers or PANEL_ADMIN_HEADERS
    payload = dict(spec if spec is not None else C.VENDOR_POSTMARK_NOTIFY)
    payload.update(overrides)
    return data_of(client.create_panel_vendor(payload, headers), 201)


# ==========================================================================
# Claims
# ==========================================================================
def notify_claim(
    client,
    policy_id,
    incident_type="RANSOMWARE",
    incident_discovered_at="2026-09-01T00:00:00Z",
    headers=None,
    **overrides,
):
    headers = headers or ADJUSTER_HEADERS
    payload = F.incident_claim_payload(
        policy_id,
        incident_type=incident_type,
        incident_discovered_at=incident_discovered_at,
        **overrides,
    )
    return data_of(client.create_incident_claim(payload, headers), 201)


def triage_claim(client, claim_id, headers=None):
    return data_of(client.triage_incident_claim(claim_id, headers or ADJUSTER_HEADERS))


def confirm_coverage(
    client,
    claim_id,
    covered_section_keys=None,
    initial_reserve_usd=250000,
    headers=None,
    **overrides,
):
    headers = headers or ADJUSTER_HEADERS
    payload = F.confirm_coverage_payload(
        covered_section_keys=covered_section_keys,
        initial_reserve_usd=initial_reserve_usd,
        **overrides,
    )
    return data_of(client.confirm_coverage(claim_id, payload, headers))


def confirmed_claim(
    client,
    policy_id,
    incident_type="RANSOMWARE",
    incident_discovered_at="2026-09-01T00:00:00Z",
    outage_start_at=None,
    outage_end_at=None,
    covered_section_keys=None,
    initial_reserve_usd=250000,
    **overrides,
):
    """Notify -> triage -> confirm-coverage, returning the confirmed claim."""
    extras = dict(overrides)
    if outage_start_at is not None:
        extras["outage_start_at"] = outage_start_at
    if outage_end_at is not None:
        extras["outage_end_at"] = outage_end_at
    claim = notify_claim(
        client,
        policy_id,
        incident_type=incident_type,
        incident_discovered_at=incident_discovered_at,
        **extras,
    )
    triage_claim(client, claim["id"])
    return confirm_coverage(
        client,
        claim["id"],
        covered_section_keys=covered_section_keys,
        initial_reserve_usd=initial_reserve_usd,
    )


def read_claim(client, claim_id, headers=None):
    return data_of(client.get_incident_claim(claim_id, headers or ADJUSTER_HEADERS))


# ==========================================================================
# Vendor engagements
# ==========================================================================
def authorize_engagement(
    client,
    claim_id,
    vendor_type="NOTIFICATION",
    deployment_start_at="2026-09-10T00:00:00Z",
    deployment_end_at="2026-09-20T00:00:00Z",
    authorized_hours_cap=40,
    panel_vendor_id=None,
    headers=None,
    **overrides,
):
    headers = headers or ADJUSTER_HEADERS
    payload = F.vendor_engagement_payload(
        vendor_type=vendor_type,
        deployment_start_at=deployment_start_at,
        deployment_end_at=deployment_end_at,
        authorized_hours_cap=authorized_hours_cap,
        **overrides,
    )
    if panel_vendor_id is not None:
        payload["panel_vendor_id"] = panel_vendor_id
    return data_of(client.create_vendor_engagement(claim_id, payload, headers), 201)


def log_hours(client, engagement_id, hours=1, records_notified=None, headers=None):
    return data_of(
        client.log_engagement_hours(
            engagement_id,
            F.log_hours_payload(hours=hours, records_notified=records_notified),
            headers or ADJUSTER_HEADERS,
        )
    )


def complete_engagement(client, engagement_id, headers=None):
    return data_of(
        client.complete_vendor_engagement(engagement_id, headers or ADJUSTER_HEADERS)
    )


# ==========================================================================
# Proofs of loss and payments
# ==========================================================================
def file_proof(client, claim_id, headers=None, **overrides):
    """Read the claim's current version, then file the proof against it."""
    headers = headers or ADJUSTER_HEADERS
    claim = read_claim(client, claim_id, headers)
    payload = F.proof_of_loss_payload(claim["version"], **overrides)
    return data_of(client.create_proof_of_loss(claim_id, payload, headers), 201)


def request_info(client, proof_id, note="Please supply the ledger extract.", headers=None):
    return data_of(
        client.request_proof_info(
            proof_id, F.request_info_payload(note), headers or ADJUSTER_HEADERS
        )
    )


def accept_proof(client, proof_id, headers=None):
    """Accept as a second adjuster so segregation of duties is satisfied."""
    return data_of(client.accept_proof_of_loss(proof_id, headers or ADJUSTER_2_HEADERS))


def list_payments_for_claim(client, claim_id, headers=None):
    return get_rows(
        client.list_claim_payments(
            headers or ADJUSTER_HEADERS, params={"incident_claim_id": claim_id}
        )
    )


# ==========================================================================
# Renewal assessments
# ==========================================================================
def open_renewal_assessment(client, policy_id, required_control_keys=None, headers=None, **overrides):
    headers = headers or UNDERWRITER_HEADERS
    payload = F.renewal_assessment_payload(
        required_control_keys=required_control_keys, **overrides
    )
    return data_of(client.create_renewal_assessment(policy_id, payload, headers), 201)


def submit_remediation(client, assessment_id, submitted_control_keys=None, headers=None):
    return data_of(
        client.submit_remediation(
            assessment_id,
            F.submit_remediation_payload(submitted_control_keys),
            headers or UNDERWRITER_HEADERS,
        )
    )


def verify_remediation(client, assessment_id, verified_control_keys=None, headers=None):
    return data_of(
        client.verify_remediation(
            assessment_id,
            F.verify_remediation_payload(verified_control_keys),
            headers or UNDERWRITER_HEADERS,
        )
    )


def read_policy(client, policy_id, headers=None):
    return data_of(client.get_policy(policy_id, headers or UNDERWRITER_HEADERS))


def issue_renewal_quote(client, assessment_id, policy_id, headers=None):
    from .test_users import ACTUARY_HEADERS

    policy = read_policy(client, policy_id)
    return data_of(
        client.issue_renewal_quote(
            assessment_id,
            F.issue_renewal_quote_payload(policy["version"]),
            headers or ACTUARY_HEADERS,
        )
    )


# ==========================================================================
# Systemic scenarios
# ==========================================================================
def draft_scenario(client, headers=None, **overrides):
    from .test_users import ACTUARY_HEADERS

    payload = F.systemic_scenario_payload(**overrides)
    return data_of(
        client.create_systemic_scenario(payload, headers or ACTUARY_HEADERS), 201
    )


def run_model(client, scenario_id, headers=None):
    from .test_users import ACTUARY_HEADERS

    return data_of(
        client.model_systemic_scenario(scenario_id, headers or ACTUARY_HEADERS)
    )
