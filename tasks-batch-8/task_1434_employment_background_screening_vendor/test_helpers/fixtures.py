"""Composite setup helpers.

Every helper builds its preconditions from scratch through the public API and
uses get_success_data() so setup failures surface as clear "Setup step failed"
errors. Entity-backed ownership calls always thread the real entity id through
make_candidate_headers / make_vendor_agent_headers.
"""
from typing import List

from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .constants import CLOCK_STARTUP_DEFAULT

from .api_client import api_client
from .factories import (
    ADVERSE_RULES,
    create_assessment_payload,
    create_audit_payload,
    create_candidate_payload,
    create_consent_payload,
    create_dispute_payload,
    create_finding_payload,
    create_jurisdiction_rule_payload,
    create_matrix_payload,
    create_order_payload,
    create_package_payload,
    create_position_payload,
    create_report_payload,
    create_vendor_payload,
)
from .test_users import (
    TEST_USERS,
    make_adjudicator_headers,
    make_candidate_headers,
    make_vendor_agent_headers,
)

HR = TEST_USERS["hr_admin_headers"]
HM = TEST_USERS["hiring_manager_headers"]
CO = TEST_USERS["compliance_officer_headers"]
AUD = TEST_USERS["auditor_headers"]


# ---------------------------------------------------------------------------
# Tier 0: single-entity creation helpers
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str, headers=None):
    """Advance the logical clock (HRAdmin by default)."""
    return get_success_data(api_client.set_clock(to_iso8601, headers or HR))


def create_vendor_record(name="Test Vendor", **overrides):
    return get_success_data(
        api_client.create_vendor(create_vendor_payload(name=name, **overrides), HR)
    )


def create_active_package(name="Test Package", **overrides):
    pkg = get_success_data(
        api_client.create_package(create_package_payload(name=name, **overrides), HR)
    )
    return get_success_data(api_client.activate_package(pkg["id"], HR))


def create_active_jurisdiction(code="US-CA", **overrides):
    rule = get_success_data(
        api_client.create_jurisdiction_rule(
            create_jurisdiction_rule_payload(jurisdiction_code=code, **overrides), CO
        )
    )
    return get_success_data(api_client.activate_jurisdiction_rule(rule["id"], CO))


def create_active_matrix(rules=None, risk_tier="TIER_1_STANDARD"):
    matrix = get_success_data(
        api_client.create_matrix(
            create_matrix_payload(risk_tier=risk_tier, rules=rules or ADVERSE_RULES), CO
        )
    )
    return get_success_data(api_client.activate_matrix(matrix["id"], CO))


def create_position_record(package_id, jurisdiction_code="US-CA", **overrides):
    return get_success_data(
        api_client.create_position(
            create_position_payload(
                package_id, jurisdiction_code=jurisdiction_code, **overrides
            ),
            HR,
        )
    )


def create_candidate_record(full_name="Test Candidate", email="candidate@example.com", **overrides):
    return get_success_data(
        api_client.create_candidate(
            create_candidate_payload(
                full_name=full_name, email=email, **overrides
            ),
            HR,
        )
    )


def create_order_record(candidate_id, position_id, **overrides):
    return get_success_data(
        api_client.create_order(
            create_order_payload(candidate_id, position_id, **overrides), HM
        )
    )


def capture_consent_record(order_id, candidate_id, **overrides):
    """Capture consent as the owning candidate (entity-backed identity)."""
    return get_success_data(
        api_client.capture_consent(
            order_id,
            create_consent_payload(**overrides),
            make_candidate_headers(candidate_id),
        )
    )


def dispatch_order_record(order_id, vendor_id):
    return get_success_data(api_client.dispatch_order(order_id, vendor_id, HM))


def deliver_report_record(order_id, vendor_id, findings=None):
    """Deliver a report as the owning vendor agent (entity-backed identity)."""
    return get_success_data(
        api_client.create_report(
            create_report_payload(order_id, findings=findings),
            make_vendor_agent_headers(vendor_id),
        )
    )


# ---------------------------------------------------------------------------
# Tier 1-2: screening configuration and order hierarchy
# ---------------------------------------------------------------------------

def setup_screening_config(
    tag="T",
    vendor_overrides=None,
    package_overrides=None,
    jurisdiction_overrides=None,
    jurisdiction_code="US-CA",
    matrix_rules=None,
    with_matrix=True,
    position_overrides=None,
):
    """Vendor + ACTIVE package + ACTIVE jurisdiction rule + (optional) ACTIVE
    matrix + position. Returns a dict of the created records."""
    vendor = create_vendor_record(
        name=f"V-{tag}", **(vendor_overrides or {})
    )
    package = create_active_package(name=f"P-{tag}", **(package_overrides or {}))
    rule = create_active_jurisdiction(
        code=jurisdiction_code, **(jurisdiction_overrides or {})
    )
    matrix = None
    if with_matrix:
        matrix = create_active_matrix(rules=matrix_rules)
    position = create_position_record(
        package["id"],
        jurisdiction_code=jurisdiction_code,
        **(position_overrides or {}),
    )
    return {
        "vendor": vendor,
        "package": package,
        "rule": rule,
        "matrix": matrix,
        "position": position,
    }


def setup_consented_order(
    tag="T",
    candidate_name="Test Candidate",
    candidate_email=None,
    consent_signed_at="2026-08-04T09:00:00Z",
    order_extra=None,
    dispatch_at=None,
    **config_kwargs,
):
    """setup_screening_config + candidate + DRAFT order + CAPTURED consent.
    The order is left in fulfillment CONSENT_CAPTURED.

    ``dispatch_at`` is accepted for call-site symmetry with
    setup_dispatched_order and ignored: this stage never dispatches.

    PRD "Consent Capture": ``authorization_signed_at`` must not lie in the
    future of the logical clock. Every test boots a fresh server whose clock
    sits at the startup default, so a signature instant past that default
    requires advancing the clock before capture; a signature at or before the
    default leaves the clock untouched (tests that rely on the startup
    default, e.g. the Saturday-dispatch anchor, depend on that)."""
    ctx = setup_screening_config(tag=tag, **config_kwargs)
    candidate = create_candidate_record(
        full_name=candidate_name,
        email=candidate_email or f"{tag.lower()}-c@example.com",
    )
    order = create_order_record(
        candidate["id"], ctx["position"]["id"], **(order_extra or {})
    )
    if consent_signed_at > CLOCK_STARTUP_DEFAULT:
        set_clock(consent_signed_at)
    consent = capture_consent_record(
        order["id"], candidate["id"], authorization_signed_at=consent_signed_at
    )
    ctx.update({"candidate": candidate, "order": order, "consent": consent})
    return ctx


# ---------------------------------------------------------------------------
# Tier 3: lifecycle shortcuts
# ---------------------------------------------------------------------------

def setup_dispatched_order(
    tag="T",
    dispatch_at="2026-08-05T10:00:00Z",
    **kwargs,
):
    """Consented order dispatched to the vendor at dispatch_at.
    Order is DISPATCHED; vendor.active_order_count == 1."""
    ctx = setup_consented_order(tag=tag, **kwargs)
    if dispatch_at is not None:
        set_clock(dispatch_at)
    ctx["order"] = dispatch_order_record(ctx["order"]["id"], ctx["vendor"]["id"])
    return ctx


def setup_report_received(
    tag="T",
    findings=None,
    deliver_at="2026-08-06T10:00:00Z",
    dispatch_at="2026-08-05T10:00:00Z",
    **kwargs,
):
    """Dispatched order + vendor report delivery. Order is REPORT_RECEIVED with
    adjudication PENDING_REVIEW."""
    ctx = setup_dispatched_order(tag=tag, dispatch_at=dispatch_at, **kwargs)
    if deliver_at is not None:
        set_clock(deliver_at)
    ctx["report"] = deliver_report_record(
        ctx["order"]["id"], ctx["vendor"]["id"], findings=findings
    )
    ctx["order"] = get_success_data(api_client.get_order(ctx["order"]["id"], HR))
    return ctx


def setup_pre_adverse_case(
    tag="T",
    adjudicator_id="adj-1",
    initiate_at="2026-08-05T10:00:00Z",
    ia_first=False,
    ia_overrides=None,
    **kwargs,
):
    """Report delivered + INITIATE_ADVERSE. Creates the 1:1 AdverseActionCase
    in WAITING_PERIOD. When ia_first is True, records a DECIDED PROCEED_ADVERSE
    individualized assessment before the adverse decision."""
    ctx = setup_report_received(tag=tag, **kwargs)
    if ia_first:
        ctx["assessment"] = get_success_data(
            api_client.create_assessment(
                ctx["order"]["id"],
                create_assessment_payload(**(ia_overrides or {})),
                make_adjudicator_headers(adjudicator_id),
            )
        )
    if initiate_at is not None:
        set_clock(initiate_at)
    ctx["order"] = get_success_data(
        api_client.adjudication_decision(
            ctx["order"]["id"], "INITIATE_ADVERSE",
            make_adjudicator_headers(adjudicator_id),
        )
    )
    cases, _meta = validate_paginated(
        api_client.list_cases(CO, params={"order_id": ctx["order"]["id"]})
    )
    assert len(cases) == 1, f"expected exactly one adverse case, got {len(cases)}"
    ctx["case"] = cases[0]
    return ctx


def setup_disputed_order(
    tag="T",
    dispute_reason="the reported record is inaccurate",
    dispute_at=None,
    **kwargs,
):
    """Report delivered + candidate dispute filed. Order adjudication is
    DISPUTE_HOLD; report is DISPUTED; dispute is UNDER_REINVESTIGATION."""
    ctx = setup_report_received(tag=tag, **kwargs)
    if dispute_at is not None:
        set_clock(dispute_at)
    ctx["dispute"] = get_success_data(
        api_client.create_dispute(
            create_dispute_payload(ctx["order"]["id"], reason=dispute_reason),
            make_candidate_headers(ctx["candidate"]["id"]),
        )
    )
    return ctx


def setup_disputed_pre_adverse(
    tag="T",
    dispute_at="2026-08-06T09:00:00Z",
    **kwargs,
):
    """PRE_ADVERSE_PENDING chain + dispute: case is DISPUTE_HOLD."""
    ctx = setup_pre_adverse_case(tag=tag, **kwargs)
    if dispute_at is not None:
        set_clock(dispute_at)
    ctx["dispute"] = get_success_data(
        api_client.create_dispute(
            create_dispute_payload(ctx["order"]["id"]),
            make_candidate_headers(ctx["candidate"]["id"]),
        )
    )
    return ctx


# ---------------------------------------------------------------------------
# Tier 4: audit helpers
# ---------------------------------------------------------------------------

def create_audit_record(vendor_id, **overrides):
    return get_success_data(
        api_client.create_audit(create_audit_payload(vendor_id, **overrides), AUD)
    )


def finalize_audit_record(audit_id):
    return get_success_data(api_client.finalize_audit(audit_id, AUD))


def get_order_record(order_id, headers=None):
    return get_success_data(api_client.get_order(order_id, headers or HR))


def get_vendor_record(vendor_id, headers=None):
    return get_success_data(api_client.get_vendor(vendor_id, headers or HR))


def get_case_record(case_id, headers=None):
    return get_success_data(api_client.get_case(case_id, headers or HR))


def get_report_record(report_id, headers=None):
    return get_success_data(api_client.get_report(report_id, headers or HR))


def get_dispute_record(dispute_id, headers=None):
    return get_success_data(api_client.get_dispute(dispute_id, headers or HR))


def list_order_consents(order_id, headers=None):
    data, meta = validate_paginated(
        api_client.list_consents(order_id, headers or HR)
    )
    return data


def list_order_assessments(order_id, headers=None):
    data, meta = validate_paginated(
        api_client.list_assessments(order_id, headers or HR)
    )
    return data


def list_report_findings(report_id, headers=None):
    data, meta = validate_paginated(
        api_client.list_findings(report_id, headers or HR)
    )
    return data


def list_orders_filtered(headers=None, **params):
    data, meta = validate_paginated(api_client.list_orders(headers or HR, params=params))
    return data, meta


def list_cases_filtered(headers=None, **params):
    data, meta = validate_paginated(api_client.list_cases(headers or HR, params=params))
    return data, meta


def finding(check_type="CRIMINAL_COUNTY", **overrides):
    return create_finding_payload(check_type=check_type, **overrides)


def findings_list(*finding_dicts) -> List[dict]:
    return list(finding_dicts)
