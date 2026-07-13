"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient) internally so setup failures produce clear
"Setup step failed" errors rather than confusing assertion failures.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_property_payload,
    create_permit_application_payload,
    discipline_decision_payload,
    pay_fee_payload,
    create_permit_payload,
    create_certificate_payload,
    create_inspection_payload,
    record_result_payload,
    finding,
    abatement_order_payload,
    create_hydrant_payload,
    create_flow_test_payload,
)
from .test_users import TEST_USERS, make_applicant_headers

FIRE_MARSHAL = TEST_USERS["fire_marshal_headers"]
PLAN_REVIEWER = TEST_USERS["plan_reviewer_headers"]
INSPECTOR = TEST_USERS["inspector_headers"]

DISCIPLINES = ("SPRINKLER", "ALARM", "EGRESS")

# Canonical CONSTRUCTION valuation used across the fee scenarios.
# base 20000 + round(100080*0.005=500.4)=500 + round(100080*0.001=100.08)=100
#       + round(100080*0.0004=40.032)=40  => estimated (0 resubmits) = 20640.
CONSTRUCTION_VALUATION_CENTS = 100080
CONSTRUCTION_ESTIMATED_FEE_CENTS = 20640
CONSTRUCTION_FINAL_FEE_ONE_RESUBMIT_CENTS = 25640  # +5000 resubmit surcharge


# ─── Primitive builders ───────────────────────────────────────────────────
def create_property(occupancy_classification="BUSINESS", construction_type="TYPE_II",
                    total_floor_area_sqft=5000, stories=1, address="100 Test St",
                    owner_name="Owner of Record", headers=FIRE_MARSHAL):
    """Register a property; server derives its life-safety metrics."""
    res = api_client.create_property(
        create_property_payload(
            address=address, owner_name=owner_name,
            occupancy_classification=occupancy_classification,
            construction_type=construction_type,
            total_floor_area_sqft=total_floor_area_sqft, stories=stories),
        headers)
    return get_success_data(res)


def create_certificate(property_id, headers=FIRE_MARSHAL):
    res = api_client.create_certificate(create_certificate_payload(property_id), headers)
    return get_success_data(res)


def open_application(property_id, applicant_user_id="app-1", permit_type="CONSTRUCTION",
                    project_valuation_cents=CONSTRUCTION_VALUATION_CENTS,
                    scope_area_sqft=5000, flow_test_id=None):
    """Open a DRAFT permit application owned by applicant_user_id."""
    extra = {}
    if flow_test_id is not None:
        extra["flow_test_id"] = flow_test_id
    res = api_client.create_permit_application(
        create_permit_application_payload(
            property_id, applicant_user_id=applicant_user_id,
            permit_type=permit_type, project_valuation_cents=project_valuation_cents,
            scope_area_sqft=scope_area_sqft, **extra),
        make_applicant_headers(applicant_user_id))
    return get_success_data(res)


def submit_application(application_id, applicant_user_id):
    res = api_client.submit_permit_application(
        application_id, make_applicant_headers(applicant_user_id))
    return get_success_data(res)


def get_plan_review_for_application(application_id):
    res = api_client.list_plan_reviews(PLAN_REVIEWER, params={"application_id": application_id})
    data, _ = _paginated(res)
    assert data, f"Setup step failed: no PlanReview for application {application_id}"
    return data[0]


def decide_discipline(plan_review_id, discipline, decision):
    res = api_client.discipline_decision(
        plan_review_id, discipline_decision_payload(discipline, decision), PLAN_REVIEWER)
    return get_success_data(res)


def approve_all_disciplines(plan_review_id):
    """Drive all three axes to APPROVED. Returns the final PlanReview."""
    pr = None
    for discipline in DISCIPLINES:
        pr = decide_discipline(plan_review_id, discipline, "APPROVED")
    return pr


def pay_application_fee(application_id, applicant_user_id, amount_cents):
    res = api_client.pay_fee(
        application_id, pay_fee_payload(amount_cents), make_applicant_headers(applicant_user_id))
    return get_success_data(res)


def issue_permit(application_id):
    res = api_client.create_permit(create_permit_payload(application_id), FIRE_MARSHAL)
    return get_success_data(res)


def _paginated(res):
    body = res.json()
    return body.get("data", []), body.get("meta", {})


# ─── Composite application-lifecycle fixtures ─────────────────────────────
def create_submitted_application(applicant_user_id="app-1",
                                 occupancy_classification="BUSINESS",
                                 construction_type="TYPE_II",
                                 project_valuation_cents=CONSTRUCTION_VALUATION_CENTS,
                                 permit_type="CONSTRUCTION", address="100 Test St"):
    """property -> open application -> submit. Returns (property, application, plan_review)."""
    prop = create_property(occupancy_classification=occupancy_classification,
                           construction_type=construction_type, address=address)
    app = open_application(prop["id"], applicant_user_id=applicant_user_id,
                           permit_type=permit_type,
                           project_valuation_cents=project_valuation_cents)
    app = submit_application(app["id"], applicant_user_id)
    pr = get_plan_review_for_application(app["id"])
    return prop, app, pr


def create_approved_application(applicant_user_id="app-1",
                                project_valuation_cents=CONSTRUCTION_VALUATION_CENTS,
                                address="100 Test St"):
    """Submit + approve all three disciplines. Returns (property, application, plan_review)."""
    prop, app, pr = create_submitted_application(
        applicant_user_id=applicant_user_id,
        project_valuation_cents=project_valuation_cents, address=address)
    approve_all_disciplines(pr["id"])
    app = get_success_data(api_client.get_permit_application(app["id"], FIRE_MARSHAL))
    pr = get_plan_review_for_application(app["id"])
    return prop, app, pr


def create_paid_approved_application(applicant_user_id="app-1",
                                     amount_cents=CONSTRUCTION_ESTIMATED_FEE_CENTS,
                                     address="100 Test St"):
    """Approved application with `amount_cents` paid. Returns (property, application, plan_review)."""
    prop, app, pr = create_approved_application(
        applicant_user_id=applicant_user_id, address=address)
    pay_application_fee(app["id"], applicant_user_id, amount_cents)
    app = get_success_data(api_client.get_permit_application(app["id"], FIRE_MARSHAL))
    return prop, app, pr


def create_issued_permit_scenario(applicant_user_id="app-1",
                                  amount_cents=CONSTRUCTION_ESTIMATED_FEE_CENTS,
                                  address="100 Test St"):
    """Full path through permit issuance. Returns (property, application, permit)."""
    prop, app, _pr = create_paid_approved_application(
        applicant_user_id=applicant_user_id, amount_cents=amount_cents, address=address)
    permit = issue_permit(app["id"])
    app = get_success_data(api_client.get_permit_application(app["id"], FIRE_MARSHAL))
    return prop, app, permit


def create_corrections_cycle_application(applicant_user_id="app-1",
                                         address="100 Test St"):
    """Submit -> SPRINKLER CORRECTIONS_REQUIRED. Returns (property, application, plan_review)."""
    prop, app, pr = create_submitted_application(
        applicant_user_id=applicant_user_id, address=address)
    decide_discipline(pr["id"], "SPRINKLER", "CORRECTIONS_REQUIRED")
    app = get_success_data(api_client.get_permit_application(app["id"], FIRE_MARSHAL))
    pr = get_plan_review_for_application(app["id"])
    return prop, app, pr


# ─── Inspection / violation / abatement fixtures ──────────────────────────
def schedule_inspection(property_id, inspection_type="PERIODIC",
                        scheduled_date="2026-03-05T00:00:00Z", complaint_description=None):
    extra = {}
    if complaint_description is not None:
        extra["complaint_description"] = complaint_description
    res = api_client.create_inspection(
        create_inspection_payload(property_id, inspection_type=inspection_type,
                                  scheduled_date=scheduled_date, **extra),
        INSPECTOR)
    return get_success_data(res)


def record_inspection_result(inspection_id, result, findings=None):
    res = api_client.record_result(
        inspection_id, record_result_payload(result, findings=findings), INSPECTOR)
    return get_success_data(res)


def get_violations_for_inspection(inspection_id):
    res = api_client.list_violations(INSPECTOR, params={"inspection_id": inspection_id})
    data, _ = _paginated(res)
    return data


def create_failed_inspection_with_violations(property_id, findings,
                                             scheduled_date="2026-03-05T00:00:00Z",
                                             inspection_type="PERIODIC"):
    """Schedule an inspection and record it FAILED with `findings`.
    Returns (inspection, [violations])."""
    insp = schedule_inspection(property_id, inspection_type=inspection_type,
                               scheduled_date=scheduled_date)
    insp = record_inspection_result(insp["id"], "FAILED", findings=findings)
    violations = get_violations_for_inspection(insp["id"])
    return insp, violations


def issue_abatement_order(violation_id, expected_violation_version):
    res = api_client.create_abatement_order(
        violation_id, abatement_order_payload(expected_violation_version), INSPECTOR)
    return get_success_data(res)


def comply_abatement_order(abatement_order_id):
    res = api_client.comply_abatement_order(abatement_order_id, INSPECTOR)
    return get_success_data(res)


def setup_certificate_suspended_by_imminent(occupancy_classification="ASSEMBLY",
                                            construction_type="TYPE_V",
                                            address="200 Cascade St"):
    """Property + VALID/GREEN certificate, then a FAILED inspection producing an
    IMMINENT_HAZARD violation (cascade C1 suspends the certificate).
    Returns (property, certificate, inspection, violation)."""
    prop = create_property(occupancy_classification=occupancy_classification,
                           construction_type=construction_type, address=address)
    cert = create_certificate(prop["id"])
    insp, violations = create_failed_inspection_with_violations(
        prop["id"], [finding("IFC_5003", "IMMINENT_HAZARD")])
    return prop, cert, insp, violations[0]


def setup_major_violation_with_order(address="210 Overdue St", occupancy_classification="ASSEMBLY",
                                     construction_type="TYPE_III", with_certificate=True):
    """Property (+ optional certificate) + FAILED inspection producing a MAJOR
    violation + a manually issued abatement order.
    Returns (property, certificate|None, inspection, violation, abatement_order)."""
    prop = create_property(occupancy_classification=occupancy_classification,
                           construction_type=construction_type, address=address)
    cert = create_certificate(prop["id"]) if with_certificate else None
    insp, violations = create_failed_inspection_with_violations(
        prop["id"], [finding("IFC_9001", "MAJOR")])
    violation = violations[0]
    order = issue_abatement_order(violation["id"], violation["version"])
    return prop, cert, insp, violation, order


# ─── Hydrant / flow-test fixtures ─────────────────────────────────────────
def create_hydrant(property_id, location_desc="hydrant location", main_size_inches=8):
    res = api_client.create_hydrant(
        create_hydrant_payload(property_id, location_desc=location_desc,
                               main_size_inches=main_size_inches), INSPECTOR)
    return get_success_data(res)


def create_flow_test(hydrant_id, test_date="2026-03-01T00:00:00Z",
                     static_psi=70, residual_psi=50, measured_flow_gpm=1500):
    res = api_client.create_flow_test(
        create_flow_test_payload(hydrant_id, test_date=test_date, static_psi=static_psi,
                                 residual_psi=residual_psi, measured_flow_gpm=measured_flow_gpm),
        INSPECTOR)
    return get_success_data(res)


def setup_hydrant_with_flow_test(address="220 Hydrant St", test_date="2026-03-01T00:00:00Z",
                                 static_psi=70, residual_psi=50, measured_flow_gpm=1500):
    """Property + hydrant + one accepted flow test. Returns (property, hydrant, flow_test)."""
    prop = create_property(address=address)
    hydrant = create_hydrant(prop["id"])
    ft = create_flow_test(hydrant["id"], test_date=test_date, static_psi=static_psi,
                          residual_psi=residual_psi, measured_flow_gpm=measured_flow_gpm)
    return prop, hydrant, ft


# ─── Clock / ops ──────────────────────────────────────────────────────────
def set_clock(to_iso8601):
    return api_client.set_clock({"to_iso8601": to_iso8601}, FIRE_MARSHAL)


def process_overdue_orders():
    res = api_client.process_overdue_orders(FIRE_MARSHAL)
    return get_success_data(res)


# ─── Fetch helpers ────────────────────────────────────────────────────────
def get_property(property_id):
    return get_success_data(api_client.get_property(property_id, FIRE_MARSHAL))


def get_application(application_id):
    return get_success_data(api_client.get_permit_application(application_id, FIRE_MARSHAL))


def get_certificate(certificate_id):
    return get_success_data(api_client.get_certificate(certificate_id, FIRE_MARSHAL))


def get_violation(violation_id):
    return get_success_data(api_client.get_violation(violation_id, INSPECTOR))


def get_abatement_order(abatement_order_id):
    return get_success_data(api_client.get_abatement_order(abatement_order_id, INSPECTOR))
