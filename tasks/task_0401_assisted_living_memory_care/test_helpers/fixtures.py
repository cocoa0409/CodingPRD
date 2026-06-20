"""Composite setup helpers for multi-step test prerequisites.

Each fixture builds its preconditions from scratch using only PRD-declared
endpoints, because the test harness restarts the server (empty DB) before every
individual test. Fixtures use get_success_data() (lenient) internally, so a setup
failure surfaces as a clear "Setup failed" error rather than a confusing assertion
failure later in the test.

Monotonic counters keep unique fields (Facility.license_number, Unit.unit_number)
from colliding across repeated fixture calls within a single test.
"""
import itertools
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import TEST_USERS
from . import factories as F

REGISTRAR = TEST_USERS["registrar_headers"]
CLINICAL = TEST_USERS["clinical_director_headers"]
NURSE = TEST_USERS["nurse_headers"]
BILLING = TEST_USERS["billing_clerk_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]
STAFF = TEST_USERS["staff_headers"]

_license_counter = itertools.count(1)
_unit_counter = itertools.count(1)


def _unique_license(prefix="LIC"):
    return f"{prefix}-{next(_license_counter):05d}"


def _unique_unit_number():
    return f"U{next(_unit_counter):04d}"


# ---------------------------------------------------------------------------
# Tier 1 — single-entity creation
# ---------------------------------------------------------------------------
def create_facility(care_point_rate_cents=2000, creator=REGISTRAR, **overrides):
    """Create a facility (ACTIVE, all metrics 0). Returns the facility dict."""
    payload = F.create_facility_payload(
        license_number=_unique_license(),
        care_point_rate_cents=care_point_rate_cents,
        **overrides,
    )
    return get_success_data(api_client.create_facility(payload, creator))


def create_unit(facility_id, wing="ASSISTED_LIVING", monthly_base_rent_cents=400000, unit_number=None):
    """Create an AVAILABLE unit in a facility. Returns the unit dict."""
    payload = F.create_unit_payload(
        unit_number=unit_number or _unique_unit_number(),
        wing=wing,
        monthly_base_rent_cents=monthly_base_rent_cents,
    )
    return get_success_data(api_client.create_unit(facility_id, payload, REGISTRAR))


def create_resident(facility_id, **overrides):
    """Register a PROSPECT resident. Returns the resident dict."""
    payload = F.create_resident_payload(facility_id, **overrides)
    return get_success_data(api_client.create_resident(payload, REGISTRAR))


# ---------------------------------------------------------------------------
# Tier 2 — assessment / finalize progression
# ---------------------------------------------------------------------------
def create_assessment(resident_id, **overrides):
    """Create a DRAFT assessment. Returns the assessment dict."""
    payload = F.create_assessment_payload(resident_id, **overrides)
    return get_success_data(api_client.create_assessment(payload, CLINICAL))


def finalize_assessment(assessment_id, expected_resident_version):
    """Finalize an assessment, supplying the OCC parent version. Returns the assessment dict."""
    return get_success_data(
        api_client.finalize_assessment(
            assessment_id, {"expected_resident_version": expected_resident_version}, CLINICAL,
        )
    )


def create_resident_with_finalized_assessment(facility_id=None, assessment_overrides=None,
                                              resident_overrides=None):
    """Facility + resident finalized to ASSESSED. Returns (facility, resident, assessment).

    Default assessment: all ADL 2 (sum 10), cognition 0, behavior 0 -> care_points 30,
    care_level LEVEL_2, so the resident sits at LEVEL_2 unless overridden.
    """
    fac = create_facility() if facility_id is None else {"id": facility_id}
    res = create_resident(fac["id"], **(resident_overrides or {}))
    a_over = {"adl_bathing": 2, "adl_dressing": 2, "adl_toileting": 2,
              "adl_transferring": 2, "adl_eating": 2, "cognition_score": 0, "behavior_flags": 0}
    a_over.update(assessment_overrides or {})
    asmt = create_assessment(res["id"], **a_over)
    asmt = finalize_assessment(asmt["id"], res["version"])
    res = get_success_data(api_client.get_resident(res["id"], STAFF))
    return fac, res, asmt


# ---------------------------------------------------------------------------
# Tier 3 — agreement / admission lifecycle
# ---------------------------------------------------------------------------
def create_agreement(resident_id, unit_id, move_in_date="2026-06-01", community_fee_cents=0):
    """Draft a move-in agreement. Returns the agreement dict."""
    payload = F.create_move_in_agreement_payload(
        resident_id, unit_id, move_in_date, community_fee_cents=community_fee_cents,
    )
    return get_success_data(api_client.create_move_in_agreement(payload, REGISTRAR))


def activate_agreement(agreement_id, expected_unit_version):
    """Activate an agreement (reserves the bed). Returns the agreement dict."""
    return get_success_data(
        api_client.activate_move_in_agreement(
            agreement_id, {"expected_unit_version": expected_unit_version}, REGISTRAR,
        )
    )


def setup_active_agreement(care_point_rate_cents=1500, base_rent_cents=400000,
                           wing="ASSISTED_LIVING", move_in_date="2026-06-01",
                           community_fee_cents=0, assessment_overrides=None):
    """Facility + AVAILABLE unit + ASSESSED resident + ACTIVE agreement (unit RESERVED).

    Returns dict with keys: facility, unit, resident, assessment, agreement.
    The resident is finalized to LEVEL_2 (cp 30) by default; the unit is reserved.
    """
    fac = create_facility(care_point_rate_cents=care_point_rate_cents)
    unit = create_unit(fac["id"], wing=wing, monthly_base_rent_cents=base_rent_cents)
    fac, res, asmt = create_resident_with_finalized_assessment(
        facility_id=fac["id"], assessment_overrides=assessment_overrides,
    )
    agr = create_agreement(res["id"], unit["id"], move_in_date=move_in_date,
                           community_fee_cents=community_fee_cents)
    agr = activate_agreement(agr["id"], unit["version"])
    unit = get_success_data(api_client.get_unit(unit["id"], STAFF))
    res = get_success_data(api_client.get_resident(res["id"], STAFF))
    return {"facility": fac, "unit": unit, "resident": res, "assessment": asmt, "agreement": agr}


def setup_admitted_resident(care_point_rate_cents=1500, base_rent_cents=400000,
                            wing="ASSISTED_LIVING", move_in_date="2026-06-01",
                            community_fee_cents=0, assessment_overrides=None):
    """Full chain to an ADMITTED resident in an OCCUPIED bed.

    Returns dict with keys: facility, unit, resident, assessment, agreement.
    """
    ctx = setup_active_agreement(
        care_point_rate_cents=care_point_rate_cents, base_rent_cents=base_rent_cents,
        wing=wing, move_in_date=move_in_date, community_fee_cents=community_fee_cents,
        assessment_overrides=assessment_overrides,
    )
    get_success_data(api_client.admit_resident(ctx["resident"]["id"], REGISTRAR))
    ctx["resident"] = get_success_data(api_client.get_resident(ctx["resident"]["id"], STAFF))
    ctx["unit"] = get_success_data(api_client.get_unit(ctx["unit"]["id"], STAFF))
    ctx["facility"] = get_success_data(api_client.get_facility(ctx["facility"]["id"], STAFF))
    return ctx


def setup_discharge_pending_resident(**kwargs):
    """ADMITTED resident moved to DISCHARGE_PENDING (zero balance). Returns the same ctx dict."""
    ctx = setup_admitted_resident(**kwargs)
    get_success_data(api_client.initiate_discharge(ctx["resident"]["id"], REGISTRAR))
    ctx["resident"] = get_success_data(api_client.get_resident(ctx["resident"]["id"], STAFF))
    return ctx


def setup_discharged_resident(disposition="OTHER", **kwargs):
    """Full lifecycle through DISCHARGED; unit ends CLEANING. Returns the ctx dict."""
    ctx = setup_discharge_pending_resident(**kwargs)
    get_success_data(
        api_client.finalize_discharge(ctx["resident"]["id"], {"disposition": disposition}, REGISTRAR)
    )
    ctx["resident"] = get_success_data(api_client.get_resident(ctx["resident"]["id"], STAFF))
    ctx["unit"] = get_success_data(api_client.get_unit(ctx["unit"]["id"], STAFF))
    ctx["facility"] = get_success_data(api_client.get_facility(ctx["facility"]["id"], STAFF))
    return ctx


# ---------------------------------------------------------------------------
# Tier 4 — billing setup
# ---------------------------------------------------------------------------
def create_statement(resident_id, period_year, period_month, is_first_statement=False):
    """Create a DRAFT billing statement. Returns the statement dict."""
    payload = F.create_billing_statement_payload(
        resident_id, period_year, period_month, is_first_statement=is_first_statement,
    )
    return get_success_data(api_client.create_billing_statement(payload, BILLING))


def setup_issued_full_month_statement(period_year=2026, period_month=10,
                                      care_point_rate_cents=1500, base_rent_cents=401500,
                                      move_in_date="2026-09-15"):
    """ADMITTED LEVEL_2 (cp 30) resident with one ISSUED full-month statement (total 446500).

    Returns dict with keys: facility, unit, resident, assessment, agreement, statement.
    """
    ctx = setup_admitted_resident(
        care_point_rate_cents=care_point_rate_cents, base_rent_cents=base_rent_cents,
        move_in_date=move_in_date,
        assessment_overrides={"adl_bathing": 2, "adl_dressing": 2, "adl_toileting": 2,
                              "adl_transferring": 2, "adl_eating": 2,
                              "cognition_score": 0, "behavior_flags": 0},
    )
    stmt = create_statement(ctx["resident"]["id"], period_year, period_month, is_first_statement=False)
    stmt = get_success_data(api_client.issue_billing_statement(stmt["id"], BILLING))
    ctx["statement"] = stmt
    ctx["resident"] = get_success_data(api_client.get_resident(ctx["resident"]["id"], STAFF))
    return ctx


# ---------------------------------------------------------------------------
# Tier 5 — medication orders + eMAR
# ---------------------------------------------------------------------------
def create_medication_order(resident_id, schedule_times=None, is_controlled=False, **overrides):
    """Create an ACTIVE medication order. Returns the order dict."""
    payload = F.create_medication_order_payload(
        resident_id, schedule_times=schedule_times or ["08:00"], is_controlled=is_controlled, **overrides,
    )
    return get_success_data(api_client.create_medication_order(payload, NURSE))


def setup_resident_with_med_order(schedule_times=None, is_controlled=False):
    """Facility + PROSPECT resident + one ACTIVE medication order.

    Returns dict with keys: facility, resident, order.
    """
    fac = create_facility()
    res = create_resident(fac["id"])
    order = create_medication_order(res["id"], schedule_times=schedule_times, is_controlled=is_controlled)
    return {"facility": fac, "resident": res, "order": order}


# ---------------------------------------------------------------------------
# Tier 6 — incidents + deficiencies
# ---------------------------------------------------------------------------
def create_incident(resident_id, incident_type="FALL", severity="MINOR",
                    occurred_at="2026-03-01T08:00:00Z"):
    """File a REPORTED incident. Returns the incident dict."""
    payload = F.create_incident_report_payload(
        resident_id, incident_type=incident_type, severity=severity, occurred_at=occurred_at,
    )
    return get_success_data(api_client.create_incident_report(payload, NURSE))


def setup_incident_under_investigation(severity="SEVERE", incident_type="FALL",
                                       occurred_at="2026-03-01T08:00:00Z"):
    """Facility + resident + one incident advanced to UNDER_INVESTIGATION.

    Returns dict with keys: facility, resident, incident.
    """
    fac = create_facility()
    res = create_resident(fac["id"])
    inc = create_incident(res["id"], incident_type=incident_type, severity=severity, occurred_at=occurred_at)
    get_success_data(api_client.investigate_incident(inc["id"], NURSE))
    inc = get_success_data(api_client.get_incident_report(inc["id"], STAFF))
    return {"facility": fac, "resident": res, "incident": inc}


def create_deficiency(facility_id, scope_severity="D_F_NO_HARM", tag_code="F-880",
                      cited_at="2026-03-05T10:00:00Z", creator=COMPLIANCE):
    """Cite a CITED survey deficiency. Returns the deficiency dict."""
    payload = F.create_deficiency_payload(
        scope_severity=scope_severity, tag_code=tag_code, cited_at=cited_at,
    )
    return get_success_data(api_client.create_deficiency(facility_id, payload, creator))


def setup_cited_deficiency(scope_severity="D_F_NO_HARM", cited_at="2026-03-05T10:00:00Z"):
    """Facility (created by ComplianceOfficer) + one CITED deficiency.

    Returns dict with keys: facility, deficiency.
    """
    fac = create_facility(creator=COMPLIANCE)
    deff = create_deficiency(fac["id"], scope_severity=scope_severity, cited_at=cited_at)
    return {"facility": fac, "deficiency": deff}


# ---------------------------------------------------------------------------
# Tier 7 — care plans
# ---------------------------------------------------------------------------
def create_care_plan(resident_id, source_assessment_id, supersedes_care_plan_id=None,
                     adl_support_items=None):
    """Create a DRAFT care plan. Returns the care plan dict."""
    over = {}
    if supersedes_care_plan_id is not None:
        over["supersedes_care_plan_id"] = supersedes_care_plan_id
    if adl_support_items is not None:
        over["adl_support_items"] = adl_support_items
    payload = F.create_care_plan_payload(resident_id, source_assessment_id, **over)
    return get_success_data(api_client.create_care_plan(payload, CLINICAL))


def setup_resident_with_active_care_plan():
    """ASSESSED resident with one ACTIVE care plan from a finalized assessment.

    Returns dict with keys: facility, resident, assessment, care_plan.
    """
    fac, res, asmt = create_resident_with_finalized_assessment()
    cp = create_care_plan(res["id"], asmt["id"])
    cp = get_success_data(api_client.activate_care_plan(cp["id"], CLINICAL))
    return {"facility": fac, "resident": res, "assessment": asmt, "care_plan": cp}
