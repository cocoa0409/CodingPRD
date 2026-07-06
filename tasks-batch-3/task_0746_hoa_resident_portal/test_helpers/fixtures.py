"""Composite setup helpers for HOA Resident Portal tests.

Fixtures use get_success_data() (lenient validator) so setup failures produce
clear "Setup failed" messages, and ownership-gated calls thread the actual
Homeowner.id through make_homeowner_headers / make_board_member_headers.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import (
    TEST_USERS,
    make_homeowner_headers,
    make_board_member_headers,
)
from .factories import (
    create_homeowner_payload,
    create_property_payload,
    create_assessment_payload,
    create_payment_payload,
    create_amenity_payload,
    create_reservation_payload,
    create_arc_request_payload,
    create_arc_review_payload,
    create_violation_payload,
    create_motion_payload,
    create_work_order_payload,
    create_document_payload,
)

_MANAGER = TEST_USERS["hoa_manager_headers"]
_COMPLIANCE = TEST_USERS["compliance_headers"]


# ---------------------------------------------------------------------------
# Tier 0 — atomic single-call helpers
# ---------------------------------------------------------------------------
def create_homeowner(email, full_name, is_board_member=False):
    payload = create_homeowner_payload(
        email=email, full_name=full_name, is_board_member=is_board_member
    )
    resp = api_client.create_homeowner(payload, _MANAGER)
    return get_success_data(resp)


def create_property(homeowner_id, address, monthly_dues_cents=30000):
    payload = create_property_payload(
        homeowner_id, address=address, monthly_dues_cents=monthly_dues_cents
    )
    resp = api_client.create_property(payload, _MANAGER)
    return get_success_data(resp)


def create_assessment(property_id, **overrides):
    payload = create_assessment_payload(property_id, **overrides)
    resp = api_client.create_assessment(payload, _MANAGER)
    return get_success_data(resp)


def set_clock(iso_ts):
    resp = api_client.set_clock(iso_ts, _MANAGER)
    return get_success_data(resp)


def set_grace_policy(policy):
    resp = api_client.set_grace_policy(policy, _MANAGER)
    return get_success_data(resp)


def create_amenity(name, capacity=10, start_hour=6, end_hour=22, **overrides):
    payload = create_amenity_payload(
        name=name,
        capacity=capacity,
        reservation_window_start_hour=start_hour,
        reservation_window_end_hour=end_hour,
        **overrides,
    )
    resp = api_client.create_amenity(payload, _MANAGER)
    return get_success_data(resp)


def create_document(title, category="CCR", content_url="https://example.com/doc.pdf"):
    payload = create_document_payload(
        title=title, category=category, content_url=content_url
    )
    resp = api_client.create_document(payload, _MANAGER)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 1 — one homeowner + one property (the most common setup prefix)
# ---------------------------------------------------------------------------
def setup_homeowner_and_property(
    email="owner@example.com",
    full_name="Test Owner",
    address="1 Test Ln",
    monthly_dues_cents=30000,
    is_board_member=False,
):
    """Create one Homeowner + one Property. Returns (homeowner, property)."""
    homeowner = create_homeowner(email, full_name, is_board_member)
    prop = create_property(homeowner["id"], address, monthly_dues_cents)
    return homeowner, prop


def setup_homeowner_property_assessment(
    email="ha@example.com",
    address="1 HA Ln",
    monthly_dues_cents=30000,
    billing_period_start="2026-03-01T00:00:00Z",
    billing_period_end="2026-04-01T00:00:00Z",
    due_date="2026-04-15T00:00:00Z",
    prorate_from=None,
):
    """Create one Homeowner + Property + Assessment. Returns tuple."""
    homeowner, prop = setup_homeowner_and_property(
        email=email, address=address, monthly_dues_cents=monthly_dues_cents
    )
    kwargs = dict(
        billing_period_start=billing_period_start,
        billing_period_end=billing_period_end,
        due_date=due_date,
    )
    if prorate_from is not None:
        kwargs["prorate_from"] = prorate_from
    assessment = create_assessment(prop["id"], **kwargs)
    return homeowner, prop, assessment


# ---------------------------------------------------------------------------
# Tier 2 — board member + submitting homeowner + ARC request
# ---------------------------------------------------------------------------
def setup_board_member(email="bm@example.com", full_name="Board M"):
    return create_homeowner(email, full_name, is_board_member=True)


def setup_arc_request_submitted(
    homeowner_email="harc@example.com",
    board_email="bmarc@example.com",
    address="1 ARC Ln",
    arc_category="SIMPLE",
    description="Test modification",
):
    """Create board member + homeowner + property + submitted ARC request.

    Returns (board_member, homeowner, property, arc_request).
    """
    board_member = setup_board_member(board_email, "BM")
    homeowner, prop = setup_homeowner_and_property(
        email=homeowner_email, address=address
    )
    arc_payload = create_arc_request_payload(
        prop["id"], homeowner["id"],
        category=arc_category, description=description,
    )
    resp = api_client.create_arc_request(
        arc_payload, make_homeowner_headers(homeowner["id"])
    )
    arc = get_success_data(resp)
    resp = api_client.submit_arc_request(
        arc["id"], make_homeowner_headers(homeowner["id"])
    )
    arc = get_success_data(resp)
    return board_member, homeowner, prop, arc


def setup_arc_request_under_review(
    homeowner_email="hur@example.com",
    board_email="bmur@example.com",
    address="1 UR Ln",
    arc_category="SIMPLE",
    review_verdict="APPROVE",
    review_weight=1,
):
    """Create board + homeowner + property + ARC request that has received one
    review (thereby moved to UNDER_REVIEW).

    Returns (board_member, homeowner, property, arc_request).
    """
    board_member, homeowner, prop, arc = setup_arc_request_submitted(
        homeowner_email=homeowner_email,
        board_email=board_email,
        address=address,
        arc_category=arc_category,
    )
    resp = api_client.create_arc_review(
        arc["id"],
        create_arc_review_payload(
            board_member["id"], weight=review_weight, verdict=review_verdict
        ),
        make_board_member_headers(board_member["id"]),
    )
    get_success_data(resp)
    resp = api_client.get_arc_request(
        arc["id"], make_board_member_headers(board_member["id"])
    )
    arc = get_success_data(resp)
    return board_member, homeowner, prop, arc


# ---------------------------------------------------------------------------
# Tier 3 — Violation lifecycle helpers
# ---------------------------------------------------------------------------
def setup_fined_violation(
    homeowner_email="hv@example.com",
    address="1 V Ln",
    category="NUISANCE",
    fine_amount_cents=15000,
    fine_at_iso="2026-03-05T00:00:00Z",
):
    """Report + confirm + fine a violation.

    Advances clock to fine_at_iso before fining so fined_at is stamped at that
    instant. Returns (homeowner, property, violation).
    """
    homeowner, prop = setup_homeowner_and_property(
        email=homeowner_email, address=address
    )
    set_clock(fine_at_iso)
    resp = api_client.create_violation(
        create_violation_payload(prop["id"], category=category), _COMPLIANCE
    )
    violation = get_success_data(resp)
    resp = api_client.confirm_violation(violation["id"], _COMPLIANCE)
    get_success_data(resp)
    resp = api_client.fine_violation(
        violation["id"],
        {"fine_amount_cents": fine_amount_cents},
        _COMPLIANCE,
    )
    violation = get_success_data(resp)
    return homeowner, prop, violation


# ---------------------------------------------------------------------------
# Tier 4 — Autopay mandate helpers
# ---------------------------------------------------------------------------
def setup_homeowner_with_autopay(
    email="hap@example.com", full_name="H AP", max_charge_cents=50000
):
    """Create Homeowner (version=1) + one ACTIVE AutopayMandate.

    Returns (homeowner_after_first_mandate, first_mandate). The homeowner dict
    reflects the state after the mandate write (version=2).
    """
    homeowner = create_homeowner(email, full_name)
    resp = api_client.create_autopay_mandate(
        homeowner["id"],
        {"expected_homeowner_version": homeowner["version"],
         "max_charge_cents": max_charge_cents},
        make_homeowner_headers(homeowner["id"]),
    )
    mandate = get_success_data(resp)
    resp = api_client.get_homeowner(
        homeowner["id"], make_homeowner_headers(homeowner["id"])
    )
    homeowner = get_success_data(resp)
    return homeowner, mandate


# ---------------------------------------------------------------------------
# Tier 5 — Amenity + Reservation helpers
# ---------------------------------------------------------------------------
def setup_amenity_and_homeowner(
    amenity_name="Pool",
    capacity=10,
    email="hres@example.com",
    address="1 Res Ln",
):
    """Create Amenity + Homeowner (property NOT needed for reservations).

    Returns (amenity, homeowner).
    """
    homeowner = create_homeowner(email, "H Res")
    amenity = create_amenity(amenity_name, capacity=capacity)
    return amenity, homeowner


def create_reservation(amenity_id, homeowner_id, start_ts, end_ts, guest_count):
    resp = api_client.create_amenity_reservation(
        create_reservation_payload(
            amenity_id, homeowner_id,
            start_ts=start_ts, end_ts=end_ts, guest_count=guest_count,
        ),
        make_homeowner_headers(homeowner_id),
    )
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 6 — Motion helpers
# ---------------------------------------------------------------------------
def setup_open_motion(
    board_email="bmm@example.com",
    title="Motion",
    category="POLICY",
    voting_window_start="2026-04-01T00:00:00Z",
    voting_window_end="2026-04-05T00:00:00Z",
    eligible_voter_count=10,
    quorum_pct=50,
):
    """Create board member + one OPEN motion. Returns (board_member, motion)."""
    board_member = setup_board_member(board_email, "BM Motion")
    resp = api_client.create_motion(
        create_motion_payload(
            title=title, category=category,
            voting_window_start=voting_window_start,
            voting_window_end=voting_window_end,
            eligible_voter_count=eligible_voter_count,
            quorum_pct=quorum_pct,
        ),
        make_board_member_headers(board_member["id"]),
    )
    motion = get_success_data(resp)
    return board_member, motion


# ---------------------------------------------------------------------------
# Tier 7 — Work order lifecycle
# ---------------------------------------------------------------------------
def create_work_order(title="Fence repair", cost_estimate_cents=50000,
                     related_property_id=None):
    payload = create_work_order_payload(
        title=title, cost_estimate_cents=cost_estimate_cents,
    )
    if related_property_id is not None:
        payload["related_property_id"] = related_property_id
    resp = api_client.create_work_order(payload, _MANAGER)
    return get_success_data(resp)


def setup_work_order_completed(title="Fence repair", cost=50000):
    """Progress a work order NEW → ASSIGNED → IN_PROGRESS → COMPLETED."""
    wo = create_work_order(title, cost)
    get_success_data(
        api_client.assign_work_order(wo["id"], {"assigned_vendor_id": "v1"}, _MANAGER)
    )
    get_success_data(api_client.start_work_order(wo["id"], _MANAGER))
    resp = api_client.complete_work_order(wo["id"], _MANAGER)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 8 — Composite: paid-then-reversal cascade preparation
# ---------------------------------------------------------------------------
def setup_paid_assessment(
    email="hpaid@example.com",
    address="1 Paid Ln",
    monthly_dues_cents=200000,
    billing_period_start="2026-03-01T00:00:00Z",
    billing_period_end="2026-04-01T00:00:00Z",
    due_date="2026-04-15T00:00:00Z",
):
    """Create Homeowner + Property + Assessment + full-payment.

    Returns (homeowner, property, assessment, payment). The clock is not
    advanced here — callers move the clock as they need to.
    """
    homeowner, prop, assessment = setup_homeowner_property_assessment(
        email=email,
        address=address,
        monthly_dues_cents=monthly_dues_cents,
        billing_period_start=billing_period_start,
        billing_period_end=billing_period_end,
        due_date=due_date,
    )
    resp = api_client.pay_assessment(
        assessment["id"],
        create_payment_payload(
            amount_cents=assessment["amount_due_cents"], method="MANUAL"
        ),
        make_homeowner_headers(homeowner["id"]),
    )
    payment = get_success_data(resp)
    return homeowner, prop, assessment, payment


# ---------------------------------------------------------------------------
# Tier 9 — Push a homeowner into SUSPENDED property via long-standing FINED
# ---------------------------------------------------------------------------
def setup_property_suspended_via_fined_violation(
    email="hsus@example.com",
    address="1 Sus Ln",
    fine_amount_cents=50000,
    fine_at_iso="2026-03-05T00:00:00Z",
    advance_to_iso="2026-05-15T00:00:00Z",
):
    """Create Homeowner + Property + a STRUCTURAL Violation, fine it, and
    advance the clock past 60 days so the Property.compliance_flag reaches
    SUSPENDED. Returns (homeowner, property, violation)."""
    homeowner, prop, violation = setup_fined_violation(
        homeowner_email=email,
        address=address,
        category="STRUCTURAL",
        fine_amount_cents=fine_amount_cents,
        fine_at_iso=fine_at_iso,
    )
    set_clock(advance_to_iso)
    return homeowner, prop, violation
