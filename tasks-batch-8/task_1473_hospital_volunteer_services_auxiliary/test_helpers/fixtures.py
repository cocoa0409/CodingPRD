"""Composite setup helpers.

Every fixture builds its preconditions from scratch against a fresh server using only
PRD-declared endpoints. Setup calls use get_success_data() so failures surface as
clear "Setup failed" errors. Identity threading: any call ownership-gated on the
Volunteer role uses make_volunteer_headers(volunteer_id).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_application_payload, create_department_payload, create_role_payload,
    create_request_payload, create_placement_payload, create_shift_payload,
    create_assignment_payload, create_hour_entry_payload, create_campaign_payload,
    create_item_payload, create_sale_payload, create_training_record_payload,
    create_clearance_payload,
)
from .test_users import (
    TEST_USERS, make_volunteer_headers, make_screener_headers,
    make_department_head_headers, make_treasurer_headers,
)

DIRECTOR = TEST_USERS["director_headers"]
COORDINATOR = TEST_USERS["coordinator_headers"]
SCREENER_1 = TEST_USERS["screener_headers"]
SCREENER_2 = TEST_USERS["screener2_headers"]
TREASURER = TEST_USERS["treasurer_headers"]

ALL_CLEARANCE_TYPES = ["BACKGROUND", "HEALTH_TB", "HEALTH_FLU"]


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str = "2026-08-01T00:00:00Z"):
    resp = api_client.set_clock(to_iso8601, DIRECTOR)
    get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 1/2: applications, volunteers, clearances
# ---------------------------------------------------------------------------

def create_application(full_name="Test Applicant", date_of_birth="1990-01-01",
                       email="applicant@x.org", phone="555-0001", **extra):
    payload = create_application_payload(
        full_name=full_name, date_of_birth=date_of_birth, email=email,
        phone=phone, **extra)
    resp = api_client.create_application(payload, COORDINATOR)
    return get_success_data(resp)


def approve_application(full_name="Test Applicant", date_of_birth="1990-01-01",
                        email="applicant@x.org", phone="555-0001"):
    """Intake -> start-review -> APPROVE. Returns (application, volunteer_id)."""
    app = create_application(full_name, date_of_birth, email, phone)
    get_success_data(api_client.start_review(app["id"], COORDINATOR))
    decided = get_success_data(api_client.decide_application(
        app["id"], {"decision": "APPROVE"}, DIRECTOR))
    return decided, decided["volunteer_id"]


def submit_clearance(volunteer_id, clearance_type, document_ref="doc-1",
                     submitter_headers=None):
    hdrs = submitter_headers or SCREENER_1
    resp = api_client.create_clearance(
        create_clearance_payload(volunteer_id=volunteer_id,
                                 clearance_type=clearance_type,
                                 document_ref=document_ref), hdrs)
    return get_success_data(resp)


def adjudicate_clearance(clearance_id, decision="CLEARED", adjudicator_headers=None):
    hdrs = adjudicator_headers or SCREENER_2
    resp = api_client.adjudicate_clearance(clearance_id, {"decision": decision}, hdrs)
    return get_success_data(resp)


def clear_all_clearances(volunteer_id):
    """Submit + adjudicate all three required clearance types (posture becomes CLEAR).
    Returns dict mapping clearance_type -> clearance row."""
    out = {}
    for ctype in ALL_CLEARANCE_TYPES:
        row = submit_clearance(volunteer_id, ctype, document_ref=f"{ctype.lower()}-1")
        out[ctype] = adjudicate_clearance(row["id"], "CLEARED")
    return out


def complete_orientation(volunteer_id):
    """The approval cascade creates the ORIENTATION record; find and complete it."""
    resp = api_client.list_training_records(
        COORDINATOR, params={"volunteer_id": volunteer_id})
    records = get_success_data(resp)
    orientation = next(r for r in records if r["training_code"] == "ORIENTATION")
    return get_success_data(api_client.complete_training_record(orientation["id"], COORDINATOR))


# ---------------------------------------------------------------------------
# Tier 2: org structure (department / role / request)
# ---------------------------------------------------------------------------

def create_department(name="Emergency", head_user_id="dh-1", **extra):
    resp = api_client.create_department(
        create_department_payload(name=name, head_user_id=head_user_id, **extra),
        DIRECTOR)
    return get_success_data(resp)


def create_role(name="ED Greeter", category="PATIENT_FACING", minimum_age=18, **extra):
    resp = api_client.create_role(
        create_role_payload(name=name, category=category, minimum_age=minimum_age,
                            **extra), DIRECTOR)
    return get_success_data(resp)


def create_open_request(department_id, role_id, slots_needed=1, head_user_id="dh-1",
                        **extra):
    """Create request (DRAFT) as the department's head and open it. Returns request."""
    head = make_department_head_headers(head_user_id)
    req = get_success_data(api_client.create_department_request(
        create_request_payload(department_id=department_id, role_id=role_id,
                               slots_needed=slots_needed, **extra), head))
    return get_success_data(api_client.open_request(req["id"], head))


def create_offer(request_id, volunteer_id, **extra):
    resp = api_client.create_placement(
        create_placement_payload(request_id=request_id, volunteer_id=volunteer_id,
                                 **extra), COORDINATOR)
    return get_success_data(resp)


def accept_placement(placement_id, volunteer_id):
    """Accept as the placement's own volunteer (ownership-gated)."""
    resp = api_client.accept_placement(placement_id, make_volunteer_headers(volunteer_id))
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 3: full volunteer pipelines
# ---------------------------------------------------------------------------

def create_cleared_volunteer(full_name="V One", date_of_birth="1990-01-01",
                             email="v@x.org", phone="555-1001"):
    """Approved application + all three clearances CLEARED. Volunteer is ONBOARDING,
    posture CLEAR. Returns dict(application, volunteer_id, clearances)."""
    app, vol_id = approve_application(full_name, date_of_birth, email, phone)
    clearances = clear_all_clearances(vol_id)
    return {"application": app, "volunteer_id": vol_id, "clearances": clearances}


def create_active_volunteer(dept, role, request, full_name="V Active",
                            date_of_birth="1990-01-01", email="va@x.org",
                            phone="555-1002"):
    """Full onboarding pipeline to ACTIVE with badge ISSUED and one ACCEPTED
    placement on `request`. Returns dict with volunteer_id, placement, badge."""
    ctx = create_cleared_volunteer(full_name, date_of_birth, email, phone)
    vol_id = ctx["volunteer_id"]
    complete_orientation(vol_id)
    placement = create_offer(request["id"], vol_id)
    placement = accept_placement(placement["id"], vol_id)
    volunteer = get_success_data(api_client.activate_volunteer(vol_id, COORDINATOR))
    badge = get_volunteer_badge(vol_id)
    return {
        "volunteer_id": vol_id,
        "volunteer": volunteer,
        "placement": placement,
        "badge": badge,
        "clearances": ctx["clearances"],
        "application": ctx["application"],
        "department": dept,
        "role": role,
        "request": request,
    }


def get_volunteer_badge(volunteer_id):
    resp = api_client.list_badges(COORDINATOR, params={"volunteer_id": volunteer_id})
    badges = get_success_data(resp)
    assert len(badges) >= 1, "Setup failed: expected a badge for the volunteer"
    return badges[0]


def get_summary(volunteer_id):
    return get_success_data(api_client.get_volunteer_summary(volunteer_id, COORDINATOR))


def get_volunteer(volunteer_id):
    return get_success_data(api_client.get_volunteer(volunteer_id, COORDINATOR))


def get_current_version(volunteer_id) -> int:
    return get_volunteer(volunteer_id)["version"]


# ---------------------------------------------------------------------------
# Tier 3: shifts and assignments
# ---------------------------------------------------------------------------

def create_published_shift(dept_id, role_id, start_at="2026-08-10T08:00:00Z",
                           end_at="2026-08-10T12:00:00Z", capacity=5, **extra):
    shift = get_success_data(api_client.create_shift(
        create_shift_payload(department_id=dept_id, role_id=role_id,
                             start_at=start_at, end_at=end_at, capacity=capacity,
                             **extra), COORDINATOR))
    return get_success_data(api_client.publish_shift(shift["id"], COORDINATOR))


def signup(shift_id, volunteer_id, as_staff=False):
    """Sign up; default is the volunteer themself (ownership-gated)."""
    hdrs = COORDINATOR if as_staff else make_volunteer_headers(volunteer_id)
    resp = api_client.create_shift_assignment(
        create_assignment_payload(shift_id=shift_id, volunteer_id=volunteer_id), hdrs)
    return get_success_data(resp)


def confirm_assignment(assignment_id, payload=None):
    resp = api_client.confirm_assignment(assignment_id, payload or {}, COORDINATOR)
    return get_success_data(resp)


def signup_and_confirm(shift_id, volunteer_id, payload=None):
    asg = signup(shift_id, volunteer_id)
    confirm_assignment(asg["id"], payload)
    return get_success_data(api_client.get_shift_assignment(asg["id"], COORDINATOR))


# ---------------------------------------------------------------------------
# Tier 4: hour entries and recognition accumulation
# ---------------------------------------------------------------------------

def log_hour_entry(volunteer_id, service_date, minutes, service_category, **extra):
    resp = api_client.create_hour_entry(
        create_hour_entry_payload(volunteer_id=volunteer_id, service_date=service_date,
                                  minutes=minutes, service_category=service_category,
                                  **extra),
        make_volunteer_headers(volunteer_id))
    return get_success_data(resp)


def approve_entry(entry_id):
    """OCC-safe approve: re-read the volunteer's current version first."""
    entry = get_success_data(api_client.get_hour_entry(entry_id, COORDINATOR))
    version = get_current_version(entry["volunteer_id"])
    return get_success_data(api_client.approve_hour_entry(
        entry_id, {"expected_volunteer_version": version}, COORDINATOR))


def log_and_approve_entries(volunteer_id, entries):
    """entries: list of (service_date, minutes, service_category). Creates and
    approves each in order (OCC version re-read between approvals)."""
    for service_date, minutes, category in entries:
        entry = log_hour_entry(volunteer_id, service_date, minutes, category)
        approve_entry(entry["id"])


# ---------------------------------------------------------------------------
# Tier 5: gift shop / campaigns
# ---------------------------------------------------------------------------

def create_gift_shop_cashier(full_name="Carol Cashier", date_of_birth="1988-03-20",
                             email="cashier@x.org", phone="555-0201"):
    """ACTIVE volunteer whose ACCEPTED placement's role category is GIFT_SHOP.
    Returns the full pipeline dict (department/role/request included)."""
    dept = create_department(name="Gift Shop", head_user_id="dh-2")
    role = create_role(name="Gift Shop Clerk", category="GIFT_SHOP", minimum_age=16)
    request = create_open_request(dept["id"], role["id"], slots_needed=1,
                                  head_user_id="dh-2")
    return create_active_volunteer(dept, role, request, full_name, date_of_birth,
                                   email, phone)


def create_item(sku="SKU-1", name="Plush Bear", unit_price_cents=1000,
                unit_cost_cents=300, stock_on_hand=10, **extra):
    resp = api_client.create_item(
        create_item_payload(sku=sku, name=name, unit_price_cents=unit_price_cents,
                            unit_cost_cents=unit_cost_cents,
                            stock_on_hand=stock_on_hand, **extra), TREASURER)
    return get_success_data(resp)


def create_campaign(name="Scanner Fund", goal_cents=50000,
                    start_at="2026-08-01T00:00:00Z", end_at="2026-08-05T00:00:00Z",
                    promo_discount_pct=0, creator_headers=None, activate=False):
    hdrs = creator_headers or TREASURER
    campaign = get_success_data(api_client.create_campaign(
        create_campaign_payload(name=name, goal_cents=goal_cents, start_at=start_at,
                                end_at=end_at, promo_discount_pct=promo_discount_pct),
        hdrs))
    if activate:
        campaign = get_success_data(api_client.activate_campaign(campaign["id"], hdrs))
    return campaign


def ring_sale(cashier_volunteer_id, lines, tendered_cents, buyer_volunteer_id=None,
              campaign_id=None, headers=None):
    payload = create_sale_payload(cashier_volunteer_id=cashier_volunteer_id,
                                  lines=lines, tendered_cents=tendered_cents)
    if buyer_volunteer_id is not None:
        payload["buyer_volunteer_id"] = buyer_volunteer_id
    if campaign_id is not None:
        payload["campaign_id"] = campaign_id
    resp = api_client.create_sale(payload, headers or TREASURER)
    return get_success_data(resp)


def enroll_and_complete_training(volunteer_id, training_code, recurrence="ANNUAL"):
    record = get_success_data(api_client.create_training_record(
        create_training_record_payload(volunteer_id=volunteer_id,
                                       training_code=training_code,
                                       recurrence=recurrence), COORDINATOR))
    return get_success_data(api_client.complete_training_record(record["id"], COORDINATOR))
