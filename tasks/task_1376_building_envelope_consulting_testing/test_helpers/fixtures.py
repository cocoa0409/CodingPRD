"""Composite setup helpers.

Every helper builds preconditions from scratch using only PRD-declared
endpoints (each test runs against a freshly restarted server with an empty
database). Setup calls use get_success_data so failures surface as clear
"Setup failed" errors. Actor-recording calls (review start/comments/approve,
field-test record/certify) take explicit user ids so segregation-of-duties
tests can control identities.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_anomaly_payload,
    create_assembly_payload,
    create_chamber_slot_payload,
    create_design_review_payload,
    create_engagement_payload,
    create_field_test_payload,
    create_invoice_payload,
    create_litigation_hold_payload,
    create_maintenance_visit_payload,
    create_mock_up_payload,
    create_remediation_plan_payload,
    create_survey_payload,
    create_warranty_claim_payload,
)
from .test_users import (
    TEST_USERS,
    make_field_technician_headers,
    make_manufacturer_rep_headers,
    make_principal_headers,
    make_reviewer_headers,
)

P = TEST_USERS["principal_headers"]
C = TEST_USERS["consultant_headers"]
R = TEST_USERS["reviewer_headers"]
FT = TEST_USERS["field_technician_headers"]
MR = TEST_USERS["manufacturer_rep_headers"]


def _fail(step, resp):
    raise AssertionError(
        f"Setup failed at {step}: HTTP {resp.status_code} {resp.text}"
    )


def _ok(step, resp, expected_status=None):
    if expected_status is not None and resp.status_code != expected_status:
        _fail(step, resp)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 1 — engagement stand-up
# ---------------------------------------------------------------------------

def create_engagement(name="E-1", fee_cap_cents=50_000_000,
                      labor_rate_cents_per_hour=15_000, **overrides):
    """Create an engagement (born SETUP, risk 100, posture OPEN, version 1)."""
    resp = api_client.create_engagement(
        create_engagement_payload(
            name=name, fee_cap_cents=fee_cap_cents,
            labor_rate_cents_per_hour=labor_rate_cents_per_hour, **overrides),
        P,
    )
    return _ok("create_engagement", resp, expected_status=201)


def activate_engagement(engagement_id):
    resp = api_client.activate_engagement(engagement_id, P)
    return _ok("activate_engagement", resp)


def create_active_engagement(name="E-1", fee_cap_cents=50_000_000,
                             labor_rate_cents_per_hour=15_000, **overrides):
    """Create + activate. Returns the IN_PROGRESS engagement dict."""
    eng = create_engagement(name, fee_cap_cents, labor_rate_cents_per_hour,
                            **overrides)
    return activate_engagement(eng["id"])


def get_engagement(engagement_id):
    resp = api_client.get_engagement(engagement_id, P)
    return _ok("get_engagement", resp)


def set_clock(to_iso8601):
    resp = api_client.set_clock({"to_iso8601": to_iso8601}, P)
    return _ok("set_clock", resp)


# ---------------------------------------------------------------------------
# Tier 2 — assemblies and design reviews
# ---------------------------------------------------------------------------

def create_assembly(engagement_id, tag="W1", assembly_type="CURTAIN_WALL",
                    design_u_factor=1.5, required_airtightness_lps_m2=1.5,
                    **overrides):
    resp = api_client.create_assembly(
        engagement_id,
        create_assembly_payload(
            tag=tag, assembly_type=assembly_type,
            design_u_factor=design_u_factor,
            required_airtightness_lps_m2=required_airtightness_lps_m2,
            **overrides),
        C,
    )
    return _ok("create_assembly", resp, expected_status=201)


def create_design_review(engagement_id, assembly_id, barrier_scope=None,
                         drawing_count=2, **overrides):
    """Submit a design review (born SUBMITTED, revision_round 0)."""
    resp = api_client.create_design_review(
        engagement_id,
        create_design_review_payload(assembly_id, barrier_scope,
                                     drawing_count, **overrides),
        C,
    )
    return _ok("create_design_review", resp, expected_status=201)


def start_review(engagement_id, review_id, reviewer_user="rev-user-1"):
    resp = api_client.start_review(engagement_id, review_id,
                                   make_reviewer_headers(reviewer_user))
    return _ok("start_review", resp)


def issue_comments(engagement_id, review_id, reviewer_user="rev-user-1"):
    resp = api_client.issue_comments(engagement_id, review_id,
                                     make_reviewer_headers(reviewer_user))
    return _ok("issue_comments", resp)


def submit_revision(engagement_id, review_id):
    resp = api_client.submit_revision(engagement_id, review_id, C)
    return _ok("submit_revision", resp)


def approve_review(engagement_id, review_id, reviewer_user="rev-user-1"):
    resp = api_client.approve_review(engagement_id, review_id,
                                     make_reviewer_headers(reviewer_user))
    return _ok("approve_review", resp)


def reject_review(engagement_id, review_id, reviewer_user="rev-user-1"):
    resp = api_client.reject_review(engagement_id, review_id,
                                    make_reviewer_headers(reviewer_user))
    return _ok("reject_review", resp)


def drive_review_through_cycle(engagement_id, review_id,
                               reviewer_user="rev-user-1"):
    """UNDER_REVIEW -> COMMENTS_ISSUED -> REVISED -> UNDER_REVIEW (one loop)."""
    issue_comments(engagement_id, review_id, reviewer_user)
    submit_revision(engagement_id, review_id)
    return start_review(engagement_id, review_id, reviewer_user)


def setup_approved_assembly(name="E-1", tag="W1", reviewer_user="rev-user-1",
                            required_airtightness_lps_m2=1.5,
                            fee_cap_cents=50_000_000,
                            labor_rate_cents_per_hour=15_000,
                            assembly_type="CURTAIN_WALL",
                            design_u_factor=1.5,
                            barrier_scope=None, drawing_count=2):
    """Active engagement + assembly whose design review is APPROVED.

    Approval happens at revision_round 0, so the segregation-of-duties rule
    (approver != round reviewer) is not engaged and a single reviewer user id
    suffices. Returns (engagement, assembly).
    """
    eng = create_active_engagement(name, fee_cap_cents,
                                   labor_rate_cents_per_hour)
    asm = create_assembly(eng["id"], tag=tag, assembly_type=assembly_type,
                          design_u_factor=design_u_factor,
                          required_airtightness_lps_m2=required_airtightness_lps_m2)
    rev = create_design_review(eng["id"], asm["id"], barrier_scope,
                               drawing_count)
    start_review(eng["id"], rev["id"], reviewer_user)
    approve_review(eng["id"], rev["id"], reviewer_user)
    return get_engagement(eng["id"]), asm


# ---------------------------------------------------------------------------
# Tier 2 — surveys and anomalies
# ---------------------------------------------------------------------------

def create_survey(engagement_id, assembly_id, survey_type="MOISTURE",
                  survey_date="2026-09-01", ambient_delta_t_c=1.0, **overrides):
    resp = api_client.create_survey(
        engagement_id,
        create_survey_payload(assembly_id, survey_type, survey_date,
                              ambient_delta_t_c, **overrides),
        C,
    )
    return _ok("create_survey", resp, expected_status=201)


def complete_survey(engagement_id, survey_id):
    resp = api_client.complete_survey(engagement_id, survey_id, FT)
    return _ok("complete_survey", resp)


def create_completed_survey(engagement_id, assembly_id, survey_type="MOISTURE",
                            **overrides):
    srv = create_survey(engagement_id, assembly_id, survey_type, **overrides)
    complete_survey(engagement_id, srv["id"])
    return srv


def create_anomaly(engagement_id, anomaly_type="MOISTURE_TRAP",
                   severity="MEDIUM", description="finding",
                   field_test_id=None, survey_id=None, **overrides):
    resp = api_client.create_anomaly(
        engagement_id,
        create_anomaly_payload(anomaly_type, severity, description,
                               field_test_id=field_test_id,
                               survey_id=survey_id, **overrides),
        C,
    )
    return _ok("create_anomaly", resp, expected_status=201)


def verify_anomaly(engagement_id, anomaly_id):
    resp = api_client.verify_anomaly(engagement_id, anomaly_id, C)
    return _ok("verify_anomaly", resp)


def setup_verified_anomaly(severity="MEDIUM", name="E-1",
                           fee_cap_cents=50_000_000,
                           anomaly_type="MOISTURE_TRAP"):
    """Active engagement + completed survey + one VERIFIED anomaly.

    Returns (engagement, assembly, survey, anomaly).
    """
    eng = create_active_engagement(name, fee_cap_cents)
    asm = create_assembly(eng["id"], tag="W1")
    srv = create_completed_survey(eng["id"], asm["id"])
    an = create_anomaly(eng["id"], anomaly_type=anomaly_type,
                        severity=severity, survey_id=srv["id"])
    an = verify_anomaly(eng["id"], an["id"])
    return get_engagement(eng["id"]), asm, srv, an


# ---------------------------------------------------------------------------
# Tier 2/3 — remediation plans (OCC-guarded create and issue)
# ---------------------------------------------------------------------------

def create_plan(engagement_id, anomaly_ids, spec_sections=("07 01 00",),
                supersedes_plan_id=None):
    """Create a DRAFT plan, reading the live engagement version for OCC."""
    eng = get_engagement(engagement_id)
    resp = api_client.create_remediation_plan(
        engagement_id,
        create_remediation_plan_payload(
            anomaly_ids, list(spec_sections), eng["version"],
            supersedes_plan_id=supersedes_plan_id),
        C,
    )
    return _ok("create_remediation_plan", resp, expected_status=201)


def issue_plan(engagement_id, plan_id):
    """Issue a DRAFT plan, reading the live engagement version for OCC."""
    eng = get_engagement(engagement_id)
    resp = api_client.issue_remediation_plan(
        engagement_id, plan_id,
        {"expected_engagement_version": eng["version"]}, C)
    return _ok("issue_remediation_plan", resp)


def setup_issued_plan(severity="MEDIUM", spec_sections=("07 01 00",),
                      name="E-1", fee_cap_cents=50_000_000,
                      anomaly_type="MOISTURE_TRAP"):
    """Active engagement + one VERIFIED anomaly + plan ISSUED against it.

    Returns (engagement, assembly, survey, anomaly, plan).
    """
    eng, asm, srv, an = setup_verified_anomaly(
        severity=severity, name=name, fee_cap_cents=fee_cap_cents,
        anomaly_type=anomaly_type)
    plan = create_plan(eng["id"], [an["id"]], spec_sections)
    plan = issue_plan(eng["id"], plan["id"])
    return get_engagement(eng["id"]), asm, srv, an, plan


# ---------------------------------------------------------------------------
# Tier 2/3 — chamber slots and mock-ups
# ---------------------------------------------------------------------------

def create_chamber_slot(engagement_id, chamber_code="CHAMBER-A",
                        start_date="2026-09-01", end_date="2026-09-04",
                        daily_rate_cents=100_000, **overrides):
    resp = api_client.create_chamber_slot(
        engagement_id,
        create_chamber_slot_payload(chamber_code, start_date, end_date,
                                    daily_rate_cents, **overrides),
        C,
    )
    return _ok("create_chamber_slot", resp, expected_status=201)


def create_mock_up(engagement_id, assembly_id, chamber_slot_id,
                   specimen_count=1, **overrides):
    resp = api_client.create_mock_up(
        engagement_id,
        create_mock_up_payload(assembly_id, chamber_slot_id, specimen_count,
                               **overrides),
        C,
    )
    return _ok("create_mock_up", resp, expected_status=201)


def drive_mock_up_to_ready(engagement_id, mock_up_id):
    """PLANNED -> CONSTRUCTING -> READY_FOR_TEST."""
    resp = api_client.begin_construction(engagement_id, mock_up_id, C)
    _ok("begin_construction", resp)
    resp = api_client.declare_ready(engagement_id, mock_up_id, C)
    return _ok("declare_ready", resp)


def setup_mock_up_testing(name="E-1", tag="W1", chamber_code="CHAMBER-A",
                          start_date="2026-09-01", end_date="2026-09-04",
                          daily_rate_cents=100_000, specimen_count=1,
                          clock_iso="2026-09-02T09:00:00Z",
                          required_airtightness_lps_m2=1.5,
                          fee_cap_cents=50_000_000):
    """Mock-up driven to TESTING with the logical clock inside the slot window.

    Returns (engagement, assembly, slot, mock_up).
    """
    eng = create_active_engagement(name, fee_cap_cents)
    asm = create_assembly(eng["id"], tag=tag,
                          required_airtightness_lps_m2=required_airtightness_lps_m2)
    slot = create_chamber_slot(eng["id"], chamber_code, start_date, end_date,
                               daily_rate_cents)
    mu = create_mock_up(eng["id"], asm["id"], slot["id"], specimen_count)
    drive_mock_up_to_ready(eng["id"], mu["id"])
    set_clock(clock_iso)
    resp = api_client.begin_testing(eng["id"], mu["id"], {}, C)
    mu = _ok("begin_testing", resp)
    return get_engagement(eng["id"]), asm, slot, mu


# ---------------------------------------------------------------------------
# Tier 2/3 — field tests
# ---------------------------------------------------------------------------

def create_field_test(engagement_id, assembly_id, test_method="ASTM_E783",
                      test_date="2026-09-10", test_pressure_pa=150,
                      **overrides):
    resp = api_client.create_field_test(
        engagement_id,
        create_field_test_payload(assembly_id, test_method, test_date,
                                  test_pressure_pa, **overrides),
        C,
    )
    return _ok("create_field_test", resp, expected_status=201)


def begin_field_test(engagement_id, field_test_id, tech_user="tech-user-1"):
    resp = api_client.begin_field_test(engagement_id, field_test_id,
                                       make_field_technician_headers(tech_user))
    return _ok("begin_field_test", resp)


def record_field_test_result(engagement_id, field_test_id, measured,
                             tech_user="tech-user-1"):
    resp = api_client.record_field_test_result(
        engagement_id, field_test_id, {"measured_leakage_lps_m2": measured},
        make_field_technician_headers(tech_user))
    return _ok("record_field_test_result", resp)


def setup_field_test_recorded(measured=3.5, name="E-1", tag="W1",
                              test_pressure_pa=150,
                              required_airtightness_lps_m2=1.5,
                              tech_user="tech-user-1",
                              fee_cap_cents=50_000_000):
    """Approved assembly + field test IN_PROGRESS, then result recorded.

    Returns (engagement, assembly, field_test).
    """
    eng, asm = setup_approved_assembly(
        name, tag, required_airtightness_lps_m2=required_airtightness_lps_m2,
        fee_cap_cents=fee_cap_cents)
    ft = create_field_test(eng["id"], asm["id"],
                           test_pressure_pa=test_pressure_pa)
    begin_field_test(eng["id"], ft["id"], tech_user)
    ft = record_field_test_result(eng["id"], ft["id"], measured, tech_user)
    return get_engagement(eng["id"]), asm, ft


def drive_diagnosis_complete(engagement_id, field_test_id):
    """UNDIAGNOSED -> DIAGNOSING -> DIAGNOSED."""
    resp = api_client.begin_diagnosis(engagement_id, field_test_id, C)
    _ok("begin_diagnosis", resp)
    resp = api_client.complete_diagnosis(engagement_id, field_test_id, C)
    return _ok("complete_diagnosis", resp)


# ---------------------------------------------------------------------------
# Tier 2/3 — warranty claims
# ---------------------------------------------------------------------------

def create_warranty_claim(engagement_id, anomaly_id,
                          manufacturer_name="ACME",
                          claimed_amount_cents=100_000, **overrides):
    resp = api_client.create_warranty_claim(
        engagement_id,
        create_warranty_claim_payload(anomaly_id, manufacturer_name,
                                      claimed_amount_cents, **overrides),
        C,
    )
    return _ok("create_warranty_claim", resp, expected_status=201)


def manufacturer_acknowledge(engagement_id, claim_id, mfr_user="mfr-user-1"):
    resp = api_client.manufacturer_acknowledge(
        engagement_id, claim_id, make_manufacturer_rep_headers(mfr_user))
    return _ok("manufacturer_acknowledge", resp)


def manufacturer_decide(engagement_id, claim_id, decision,
                        mfr_user="mfr-user-1"):
    resp = api_client.manufacturer_decide(engagement_id, claim_id,
                                          {"decision": decision},
                                          make_manufacturer_rep_headers(mfr_user))
    return _ok("manufacturer_decide", resp)


# ---------------------------------------------------------------------------
# Tier 2 — litigation holds, maintenance visits, invoices
# ---------------------------------------------------------------------------

def create_litigation_hold(engagement_id, matter_reference="CASE-2026-001"):
    resp = api_client.create_litigation_hold(
        engagement_id, create_litigation_hold_payload(matter_reference), P)
    return _ok("create_litigation_hold", resp, expected_status=201)


def create_maintenance_visit(engagement_id, visit_label="AUTUMN-2026",
                             window_start_date="2026-10-01",
                             window_end_date="2026-10-05", buffer_days=None):
    resp = api_client.create_maintenance_visit(
        engagement_id,
        create_maintenance_visit_payload(visit_label, window_start_date,
                                         window_end_date, buffer_days),
        C,
    )
    return _ok("create_maintenance_visit", resp, expected_status=201)


def create_invoice(engagement_id, labor_hours=1, expense_cents=0,
                   discount_pct=None):
    resp = api_client.create_invoice(
        engagement_id,
        create_invoice_payload(labor_hours, expense_cents, discount_pct),
        C,
    )
    return _ok("create_invoice", resp, expected_status=201)
