"""Composite setup helpers and pytest fixtures.

The server is relaunched against an empty database before every test, so every
helper here builds its world from scratch through the public API. Helpers return
plain dictionaries of identifiers and headers so a test can keep threading the
real identities the API minted.
"""

from typing import Any, Dict, List, Optional

import pytest

from prd_bench_local_runner.testing import validate_success

from . import factories as f
from .api_client import ApiClient
from .api_errors import register_error_status_map
from .constants import (
    ACQUIRER_NAME,
    APPROVED_BUDGET,
    ASSESSMENT_YEAR,
    CLIENT_LEGAL_NAME,
    FACILITY_DC_EAST,
    FIELDWORK_END,
    FIELDWORK_START,
    LEAD_CERT_EXPIRES,
    LEAD_EMAIL,
    LEAD_NAME,
    QA_CERT_EXPIRES,
    QA_EMAIL,
    QA_NAME,
    VENDOR_APPROVAL_EXPIRES,
    VENDOR_NAME,
)
from .test_users import (
    admin_headers,
    client_rep_headers,
    make_assessor_headers,
    make_asv_vendor_headers,
    make_lead_headers,
    make_qa_reviewer_headers,
)


# ---------------------------------------------------------------------------
# Low-level creation helpers
# ---------------------------------------------------------------------------
def ok(response, expected_status: int = 200) -> Dict[str, Any]:
    """Unwrap a successful response, failing loudly with the body on error."""
    assert response.status_code == expected_status, (
        "setup call expected HTTP %d but got %d: %s"
        % (expected_status, response.status_code, response.text)
    )
    return validate_success(response, expected_status)


def created(response) -> Dict[str, Any]:
    return ok(response, 201)


def register_assessor(
    api: ApiClient,
    full_name: str,
    email: str,
    certification_expires_at: str = LEAD_CERT_EXPIRES,
    qa_qualified: bool = False,
    **extra: Any
) -> Dict[str, Any]:
    payload = f.assessor_payload(
        full_name=full_name,
        email=email,
        certification_expires_at=certification_expires_at,
        qa_qualified=qa_qualified,
        **extra
    )
    return created(api.create_assessor(payload, admin_headers()))


def register_vendor(
    api: ApiClient,
    name: str = VENDOR_NAME,
    approval_expires_at: str = VENDOR_APPROVAL_EXPIRES,
    **extra: Any
) -> Dict[str, Any]:
    payload = f.asv_vendor_payload(
        name=name, approval_expires_at=approval_expires_at, **extra
    )
    return created(api.create_asv_vendor(payload, admin_headers()))


def open_engagement(
    api: ApiClient,
    lead_id: str,
    qa_reviewer_id: Optional[str] = None,
    **overrides: Any
) -> Dict[str, Any]:
    payload = f.engagement_payload(
        lead_assessor_id=lead_id, qa_reviewer_id=qa_reviewer_id, **overrides
    )
    return created(api.create_engagement(payload, make_lead_headers(lead_id)))


def read_engagement(api: ApiClient, engagement_id: str, lead_id: str) -> Dict[str, Any]:
    return ok(api.get_engagement(engagement_id, make_lead_headers(lead_id)))


def engagement_version(api: ApiClient, engagement_id: str, lead_id: str) -> int:
    return read_engagement(api, engagement_id, lead_id)["version"]


def declare_segment(
    api: ApiClient,
    engagement_id: str,
    lead_id: str,
    name: str,
    segment_class: str = "CDE",
    parent_segment_id: Optional[str] = None,
) -> Dict[str, Any]:
    payload = f.network_segment_payload(
        name=name, segment_class=segment_class, parent_segment_id=parent_segment_id
    )
    return created(
        api.create_network_segment(engagement_id, payload, make_lead_headers(lead_id))
    )


def plan_segmentation(
    api: ApiClient,
    segment_id: str,
    lead_id: str,
    test_method: str = "PEN_TEST",
    planned_date: str = "2026-08-05",
) -> Dict[str, Any]:
    payload = f.segmentation_test_plan_payload(
        test_method=test_method, planned_date=planned_date
    )
    return ok(
        api.plan_segmentation_test(segment_id, payload, make_lead_headers(lead_id))
    )


def record_verdict(
    api: ApiClient, segment_id: str, lead_id: str, outcome: str = "PASS", **overrides: Any
) -> Dict[str, Any]:
    payload = f.validation_result_payload(outcome=outcome, **overrides)
    return ok(
        api.record_validation_result(segment_id, payload, make_lead_headers(lead_id))
    )


def validated_segment(
    api: ApiClient,
    engagement_id: str,
    lead_id: str,
    name: str = "CDE-CORE",
    segment_class: str = "CDE",
    test_method: str = "PEN_TEST",
    planned_date: str = "2026-08-05",
    parent_segment_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Declare a zone, plan its segmentation test and pass it."""
    segment = declare_segment(
        api,
        engagement_id,
        lead_id,
        name,
        segment_class=segment_class,
        parent_segment_id=parent_segment_id,
    )
    plan_segmentation(
        api, segment["id"], lead_id, test_method=test_method, planned_date=planned_date
    )
    return record_verdict(api, segment["id"], lead_id, outcome="PASS")


def add_component(
    api: ApiClient,
    engagement_id: str,
    lead_id: str,
    segment_id: str,
    hostname: str,
    component_type: str = "SERVER",
    function_class: str = "SECURITY_SERVICE",
    stores_chd: bool = False,
    facility_name: str = FACILITY_DC_EAST,
    facility_type: str = "DATA_CENTER",
) -> Dict[str, Any]:
    payload = f.system_component_payload(
        segment_id=segment_id,
        hostname=hostname,
        component_type=component_type,
        function_class=function_class,
        stores_chd=stores_chd,
        facility_name=facility_name,
        facility_type=facility_type,
    )
    return created(
        api.create_system_component(engagement_id, payload, make_lead_headers(lead_id))
    )


def draw_plan(
    api: ApiClient,
    engagement_id: str,
    lead_id: str,
    plan_variant: str = "FINAL",
    expected_engagement_version: Optional[int] = None,
    justification_text: str = "Full coverage of the in-scope inventory.",
) -> Dict[str, Any]:
    version = (
        expected_engagement_version
        if expected_engagement_version is not None
        else engagement_version(api, engagement_id, lead_id)
    )
    payload = f.sampling_plan_payload(
        expected_engagement_version=version,
        plan_variant=plan_variant,
        justification_text=justification_text,
    )
    return created(
        api.create_sampling_plan(engagement_id, payload, make_lead_headers(lead_id))
    )


def lock_scope(api: ApiClient, engagement_id: str, lead_id: str) -> Dict[str, Any]:
    return ok(api.lock_scope(engagement_id, make_lead_headers(lead_id)))


def open_requirement(
    api: ApiClient,
    engagement_id: str,
    lead_id: str,
    requirement_ref: str = "1.2.1",
    requirement_family: str = "R1",
    testing_procedure_count: int = 3,
    applicability: str = "APPLICABLE",
) -> Dict[str, Any]:
    payload = f.requirement_payload(
        requirement_ref=requirement_ref,
        requirement_family=requirement_family,
        testing_procedure_count=testing_procedure_count,
        applicability=applicability,
    )
    return created(
        api.create_requirement_assessment(
            engagement_id, payload, make_lead_headers(lead_id)
        )
    )


def start_testing(api: ApiClient, requirement_id: str, lead_id: str) -> Dict[str, Any]:
    return ok(api.start_testing(requirement_id, make_lead_headers(lead_id)))


def add_evidence(
    api: ApiClient, requirement_id: str, lead_id: str, payload: Dict[str, Any]
) -> Dict[str, Any]:
    return created(
        api.create_evidence_item(requirement_id, payload, make_lead_headers(lead_id))
    )


def add_complete_evidence(
    api: ApiClient,
    requirement_id: str,
    lead_id: str,
    requirement_ref: str,
    observed_component_id: str,
    interviewee_name: str = "Priya Raman",
    interviewee_title: str = "Network Engineering Manager",
) -> List[Dict[str, Any]]:
    """Append the three techniques evidence completeness insists on."""
    items = [
        add_evidence(
            api,
            requirement_id,
            lead_id,
            f.document_evidence("%s.a" % requirement_ref),
        ),
        add_evidence(
            api,
            requirement_id,
            lead_id,
            f.interview_evidence(
                "%s.b" % requirement_ref,
                interviewee_name=interviewee_name,
                interviewee_title=interviewee_title,
            ),
        ),
        add_evidence(
            api,
            requirement_id,
            lead_id,
            f.observation_evidence("%s.c" % requirement_ref, observed_component_id),
        ),
    ]
    return items


def conclude(
    api: ApiClient,
    requirement_id: str,
    lead_id: str,
    conclusion: str = "IN_PLACE",
    **overrides: Any
) -> Dict[str, Any]:
    payload = f.conclusion_payload(conclusion=conclusion, **overrides)
    return ok(
        api.conclude_requirement(requirement_id, payload, make_lead_headers(lead_id))
    )


def requirement_concluded(
    api: ApiClient,
    engagement_id: str,
    lead_id: str,
    requirement_ref: str,
    requirement_family: str,
    observed_component_id: str,
    conclusion: str = "IN_PLACE",
    testing_procedure_count: int = 3,
    interviewee_name: str = "Priya Raman",
    interviewee_title: str = "Network Engineering Manager",
    conclusion_rationale: str = "Ruleset restricts inbound traffic to documented services.",
) -> Dict[str, Any]:
    """Open a requirement, evidence it fully and record the given conclusion."""
    requirement = open_requirement(
        api,
        engagement_id,
        lead_id,
        requirement_ref=requirement_ref,
        requirement_family=requirement_family,
        testing_procedure_count=testing_procedure_count,
    )
    start_testing(api, requirement["id"], lead_id)
    add_complete_evidence(
        api,
        requirement["id"],
        lead_id,
        requirement_ref,
        observed_component_id,
        interviewee_name=interviewee_name,
        interviewee_title=interviewee_title,
    )
    return conclude(
        api,
        requirement["id"],
        lead_id,
        conclusion=conclusion,
        conclusion_rationale=conclusion_rationale,
    )


def draft_ccw(
    api: ApiClient,
    requirement_id: str,
    lead_id: str,
    expected_requirement_assessment_version: int,
    control_refs: Optional[List[str]] = None,
    monitoring_interval_days: int = 7,
) -> Dict[str, Any]:
    payload = f.ccw_payload(
        expected_requirement_assessment_version=expected_requirement_assessment_version,
        control_refs=control_refs,
        monitoring_interval_days=monitoring_interval_days,
    )
    return created(api.create_ccw(requirement_id, payload, make_lead_headers(lead_id)))


def submit_ccw(api: ApiClient, ccw_id: str, lead_id: str) -> Dict[str, Any]:
    return ok(api.submit_ccw(ccw_id, make_lead_headers(lead_id)))


def create_roc(
    api: ApiClient, engagement_id: str, lead_id: str, roc_version_label: str = "v1.0"
) -> Dict[str, Any]:
    return created(
        api.create_roc(
            engagement_id, f.roc_payload(roc_version_label), make_lead_headers(lead_id)
        )
    )


def qa_submit(api: ApiClient, roc_id: str, lead_id: str) -> Dict[str, Any]:
    return ok(api.qa_submit_roc(roc_id, make_lead_headers(lead_id)))


def schedule_scan_cycle(
    api: ApiClient,
    engagement_id: str,
    lead_id: str,
    vendor_id: str,
    quarter_label: str = "2026-Q3",
    window_start: str = "2026-07-01T00:00:00Z",
) -> Dict[str, Any]:
    payload = f.scan_cycle_payload(
        asv_vendor_id=vendor_id,
        quarter_label=quarter_label,
        window_start=window_start,
    )
    return created(
        api.create_scan_cycle(engagement_id, payload, make_lead_headers(lead_id))
    )


def publish_finding(
    api: ApiClient,
    cycle_id: str,
    vendor_id: str,
    component_id: str,
    plugin_reference: str = "PLG-40912",
    cvss_score: float = 7.5,
) -> Dict[str, Any]:
    payload = f.scan_finding_payload(
        component_id=component_id,
        plugin_reference=plugin_reference,
        cvss_score=cvss_score,
    )
    return created(
        api.create_scan_finding(cycle_id, payload, make_asv_vendor_headers(vendor_id))
    )


def complete_cycle(api: ApiClient, cycle_id: str, vendor_id: str) -> Dict[str, Any]:
    return ok(api.complete_scan_cycle(cycle_id, make_asv_vendor_headers(vendor_id)))


def set_clock(api: ApiClient, to_iso8601: str) -> Dict[str, Any]:
    return ok(api.set_clock(to_iso8601, admin_headers()))


def record_change(
    api: ApiClient,
    engagement_id: str,
    engagement_lead_id: str,
    change_type: str,
    description: str,
    affects_scope: bool,
    component_id: Optional[str] = None,
    as_client_rep: bool = True,
) -> Dict[str, Any]:
    payload = f.change_log_payload(
        change_type=change_type,
        description=description,
        affects_scope=affects_scope,
        component_id=component_id,
    )
    headers = (
        client_rep_headers() if as_client_rep else make_lead_headers(engagement_lead_id)
    )
    return created(api.create_change_log_entry(engagement_id, payload, headers))


# ---------------------------------------------------------------------------
# Composite scenarios
# ---------------------------------------------------------------------------
class Scenario(dict):
    """A dictionary of identifiers and headers with attribute access."""

    def __getattr__(self, item: str) -> Any:
        try:
            return self[item]
        except KeyError as exc:  # pragma: no cover - developer error surface
            raise AttributeError(item) from exc


def build_registry(api: ApiClient) -> Scenario:
    """Register the lead assessor and a qualified quality-assurance reviewer."""
    lead = register_assessor(
        api, LEAD_NAME, LEAD_EMAIL, LEAD_CERT_EXPIRES, qa_qualified=False
    )
    qa = register_assessor(
        api, QA_NAME, QA_EMAIL, QA_CERT_EXPIRES, qa_qualified=True
    )
    return Scenario(
        lead=lead,
        qa=qa,
        lead_id=lead["id"],
        qa_id=qa["id"],
        lead_headers=make_lead_headers(lead["id"]),
        staff_headers=make_assessor_headers(lead["id"]),
        qa_headers=make_qa_reviewer_headers(qa["id"]),
        admin_headers=admin_headers(),
        client_headers=client_rep_headers(),
    )


def build_scoping_engagement(api: ApiClient, **overrides: Any) -> Scenario:
    """A commissioned engagement sitting at SCOPING with posture OPEN."""
    scenario = build_registry(api)
    engagement = open_engagement(
        api, scenario["lead_id"], qa_reviewer_id=scenario["qa_id"], **overrides
    )
    scenario["engagement"] = engagement
    scenario["engagement_id"] = engagement["id"]
    return scenario


def build_validated_cde_engagement(api: ApiClient, **overrides: Any) -> Scenario:
    """A SCOPING engagement whose cardholder zone is VALIDATED with three hosts.

    The three hosts all sit in one data centre: app-01 as a SERVER and pay-01 and
    pay-02 as payment APPLICATIONs.
    """
    scenario = build_scoping_engagement(api, **overrides)
    lead_id = scenario["lead_id"]
    engagement_id = scenario["engagement_id"]
    segment = validated_segment(api, engagement_id, lead_id, name="CDE-CORE")
    scenario["segment"] = segment
    scenario["segment_id"] = segment["id"]
    components = {}
    components["app-01"] = add_component(
        api,
        engagement_id,
        lead_id,
        segment["id"],
        "app-01",
        component_type="SERVER",
        function_class="SECURITY_SERVICE",
        stores_chd=False,
    )
    components["pay-01"] = add_component(
        api,
        engagement_id,
        lead_id,
        segment["id"],
        "pay-01",
        component_type="APPLICATION",
        function_class="PAYMENT_APPLICATION",
        stores_chd=True,
    )
    components["pay-02"] = add_component(
        api,
        engagement_id,
        lead_id,
        segment["id"],
        "pay-02",
        component_type="APPLICATION",
        function_class="PAYMENT_APPLICATION",
        stores_chd=True,
    )
    scenario["components"] = components
    scenario["component_ids"] = {name: row["id"] for name, row in components.items()}
    return scenario


def build_sampled_engagement(api: ApiClient, **overrides: Any) -> Scenario:
    """The validated-zone engagement with a FINAL sampling plan drawn over it."""
    scenario = build_validated_cde_engagement(api, **overrides)
    plan = draw_plan(
        api, scenario["engagement_id"], scenario["lead_id"], plan_variant="FINAL"
    )
    scenario["plan"] = plan
    scenario["plan_id"] = plan["id"]
    return scenario


def build_fieldwork_engagement(api: ApiClient, **overrides: Any) -> Scenario:
    """The sampled engagement with scope locked, so it stands at FIELDWORK."""
    scenario = build_sampled_engagement(api, **overrides)
    scenario["engagement"] = lock_scope(
        api, scenario["engagement_id"], scenario["lead_id"]
    )
    return scenario


def build_engagement_with_in_place_requirement(
    api: ApiClient,
    requirement_ref: str = "1.2.1",
    requirement_family: str = "R1",
    **overrides: Any
) -> Scenario:
    """A FIELDWORK engagement with one fully evidenced IN_PLACE requirement."""
    scenario = build_fieldwork_engagement(api, **overrides)
    requirement = requirement_concluded(
        api,
        scenario["engagement_id"],
        scenario["lead_id"],
        requirement_ref,
        requirement_family,
        scenario["component_ids"]["pay-01"],
        conclusion="IN_PLACE",
    )
    scenario["requirement"] = requirement
    scenario["requirement_id"] = requirement["id"]
    return scenario


def build_engagement_with_gap(
    api: ApiClient,
    requirement_ref: str = "6.4.1",
    requirement_family: str = "R6",
    **overrides: Any
) -> Scenario:
    """A FIELDWORK engagement with one requirement concluded NOT_IN_PLACE."""
    scenario = build_fieldwork_engagement(api, **overrides)
    requirement = requirement_concluded(
        api,
        scenario["engagement_id"],
        scenario["lead_id"],
        requirement_ref,
        requirement_family,
        scenario["component_ids"]["pay-01"],
        conclusion="NOT_IN_PLACE",
        conclusion_rationale="The stated control is absent on the payment application.",
    )
    scenario["requirement"] = requirement
    scenario["requirement_id"] = requirement["id"]
    return scenario


def build_submitted_ccw(
    api: ApiClient,
    control_refs: Optional[List[str]] = None,
    monitoring_interval_days: int = 7,
    requirement_ref: str = "6.4.1",
    requirement_family: str = "R6",
    **overrides: Any
) -> Scenario:
    """A gapped engagement whose worksheet is drafted and submitted for review."""
    scenario = build_engagement_with_gap(
        api,
        requirement_ref=requirement_ref,
        requirement_family=requirement_family,
        **overrides
    )
    worksheet = draft_ccw(
        api,
        scenario["requirement_id"],
        scenario["lead_id"],
        scenario["requirement"]["version"],
        control_refs=control_refs,
        monitoring_interval_days=monitoring_interval_days,
    )
    scenario["ccw"] = submit_ccw(api, worksheet["id"], scenario["lead_id"])
    scenario["ccw_id"] = worksheet["id"]
    return scenario


def build_roc_in_drafting(api: ApiClient, **overrides: Any) -> Scenario:
    """An engagement whose report has just been created, so it is at DRAFTING."""
    scenario = build_engagement_with_in_place_requirement(api, **overrides)
    roc = create_roc(api, scenario["engagement_id"], scenario["lead_id"])
    scenario["roc"] = roc
    scenario["roc_id"] = roc["id"]
    return scenario


def build_roc_in_qa(api: ApiClient, **overrides: Any) -> Scenario:
    """An engagement whose report has been handed to quality assurance."""
    scenario = build_roc_in_drafting(api, **overrides)
    scenario["roc"] = qa_submit(api, scenario["roc_id"], scenario["lead_id"])
    return scenario


def build_approved_vendor_with_cycle(
    api: ApiClient,
    scenario: Scenario,
    quarter_label: str = "2026-Q3",
    window_start: str = "2026-07-01T00:00:00Z",
) -> Scenario:
    """Register the approved vendor and schedule one scan cycle on an engagement."""
    vendor = register_vendor(api)
    cycle = schedule_scan_cycle(
        api,
        scenario["engagement_id"],
        scenario["lead_id"],
        vendor["id"],
        quarter_label=quarter_label,
        window_start=window_start,
    )
    scenario["vendor"] = vendor
    scenario["vendor_id"] = vendor["id"]
    scenario["vendor_headers"] = make_asv_vendor_headers(vendor["id"])
    scenario["cycle"] = cycle
    scenario["cycle_id"] = cycle["id"]
    return scenario


# ---------------------------------------------------------------------------
# Pytest fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def api() -> ApiClient:
    """A client pointed at the service under test, with the error table loaded."""
    register_error_status_map()
    return ApiClient()


@pytest.fixture
def registry(api: ApiClient) -> Scenario:
    return build_registry(api)


@pytest.fixture
def scoping_engagement(api: ApiClient) -> Scenario:
    return build_scoping_engagement(api)


@pytest.fixture
def validated_cde_engagement(api: ApiClient) -> Scenario:
    return build_validated_cde_engagement(api)


@pytest.fixture
def sampled_engagement(api: ApiClient) -> Scenario:
    return build_sampled_engagement(api)


@pytest.fixture
def fieldwork_engagement(api: ApiClient) -> Scenario:
    return build_fieldwork_engagement(api)


@pytest.fixture
def engagement_with_in_place_requirement(api: ApiClient) -> Scenario:
    return build_engagement_with_in_place_requirement(api)


@pytest.fixture
def engagement_with_gap(api: ApiClient) -> Scenario:
    return build_engagement_with_gap(api)


@pytest.fixture
def roc_in_drafting(api: ApiClient) -> Scenario:
    return build_roc_in_drafting(api)


@pytest.fixture
def roc_in_qa(api: ApiClient) -> Scenario:
    return build_roc_in_qa(api)
