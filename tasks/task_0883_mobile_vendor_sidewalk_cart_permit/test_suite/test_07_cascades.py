"""Multi-hop suspension cascades from complaint substantiation and inspection
failure, plus the UNFOUNDED no-op branch (Difficulty: transitive_cascade;
Corner: cross_cutting)."""
from test_helpers import (
    validate_success, get_success_data, TEST_USERS,
    make_enforcement_headers, make_resident_headers,
    OFFICER_ISSUER_ID, OFFICER_ADJUDICATOR_ID,
    create_complaint_payload, resolve_complaint_payload, inspection_payload,
)
from test_helpers import fixtures as fx

PO = TEST_USERS["permit_officer_headers"]
HI = TEST_USERS["health_inspector_headers"]
EO2 = make_enforcement_headers(OFFICER_ADJUDICATOR_ID)
RES = make_resident_headers("res-1")


# --------------------------------------------------------------------------- #
# transitive_cascade / complaint_substantiation_depth4_cascade
# --------------------------------------------------------------------------- #
def _permit_ready_for_substantiation():
    """ISSUED permit with an ACTIVE assignment and a prior UPHELD MAJOR (6 pts)."""
    ctx = fx.setup_permit_with_active_assignment()
    # prior UPHELD MAJOR: 6 points, still below threshold.
    fx.issue_upheld_violation(ctx["permit"]["id"], violation_type="MAJOR")
    complaint = get_success_data(fx.api_client.create_complaint(
        ctx["permit"]["id"], create_complaint_payload("SANITATION", "unsanitary handling"), RES))
    ctx["complaint"] = complaint
    return ctx


def test_substantiation_pushes_points_to_threshold_and_suspends(api):
    """PRD §3.8: "auto-creates a violation of severity MAJOR on the complained-about
    permit; that violation is created ISSUED and immediately upheld by the resolving
    officer ... Because the generated violation is upheld, it recomputes the permit's
    violation_points, which may push the permit to or past the threshold and trigger
    the same ISSUED → SUSPENDED suspension and spot-release cascade"

    Design: Difficulty/transitive_cascade/complaint_substantiation_depth4_cascade
    """
    ctx = _permit_ready_for_substantiation()
    get_success_data(api.resolve_complaint(
        ctx["complaint"]["id"], resolve_complaint_payload("SUBSTANTIATED", "verified"), EO2))
    permit = validate_success(api.get_permit(ctx["permit"]["id"], PO), 200)
    assert permit["violation_points"] == 12  # 6 prior + 6 generated MAJOR
    assert permit["status"] == "SUSPENDED"


def test_substantiation_cascade_releases_assignment_and_frees_zone(api):
    """PRD §2.7: "When a permit leaves ISSUED for SUSPENDED, every SpotAssignment
    that belongs to that permit and is still ACTIVE transitions to RELEASED. Each
    such release sets the freed Spot back to AVAILABLE, decrements the owning zone's
    assigned_slots, recomputes that zone's available_slots, and increments the zone's
    version by 1."

    Design: Difficulty/transitive_cascade/complaint_substantiation_depth4_cascade
    """
    ctx = _permit_ready_for_substantiation()
    get_success_data(api.resolve_complaint(
        ctx["complaint"]["id"], resolve_complaint_payload("SUBSTANTIATED", "verified"), EO2))
    assignment = validate_success(api.get_spot_assignment(ctx["assignment"]["id"], PO), 200)
    assert assignment["status"] == "RELEASED"
    zone = validate_success(api.get_zone(ctx["zone"]["id"], PO), 200)
    assert zone["assigned_slots"] == 0


# --------------------------------------------------------------------------- #
# transitive_cascade / inspection_fail_depth2_cascade
# --------------------------------------------------------------------------- #
def test_inspection_fail_suspends_permit(api):
    """PRD §3.2: "When an inspection result is FAIL, every ISSUED permit that
    operates this cart is suspended (ISSUED → SUSPENDED), which in turn releases those
    permits' active spot assignments as described in Section 2.7."

    Design: Difficulty/transitive_cascade/inspection_fail_depth2_cascade
    """
    ctx = fx.setup_permit_with_active_assignment()
    failed = validate_success(api.inspect_cart(
        ctx["cart"]["id"], inspection_payload(result="FAIL", score=40), HI), 201)
    assert failed["inspection_status"] == "FAIL"
    permit = validate_success(api.get_permit(ctx["permit"]["id"], PO), 200)
    assert permit["status"] == "SUSPENDED"


def test_inspection_fail_releases_active_assignment(api):
    """PRD §3.2: "which in turn releases those permits' active spot assignments as
    described in Section 2.7."
    PRD §2.7: "every SpotAssignment that belongs to that permit and is still ACTIVE
    transitions to RELEASED."

    Design: Difficulty/transitive_cascade/inspection_fail_depth2_cascade
    """
    ctx = fx.setup_permit_with_active_assignment()
    get_success_data(api.inspect_cart(
        ctx["cart"]["id"], inspection_payload(result="FAIL", score=40), HI))
    assignment = validate_success(api.get_spot_assignment(ctx["assignment"]["id"], PO), 200)
    assert assignment["status"] == "RELEASED"


# --------------------------------------------------------------------------- #
# Corner cross_cutting: complaint_unfounded_no_side_effects
# --------------------------------------------------------------------------- #
def test_unfounded_complaint_has_no_side_effects(api):
    """PRD §3.8: "Resolving as UNFOUNDED moves the complaint to UNFOUNDED and produces
    no fiscal or permit-state effect."

    Design: Corner/cross_cutting/complaint_unfounded_no_side_effects
    """
    ctx = fx.setup_issued_permit()
    complaint = get_success_data(fx.api_client.create_complaint(
        ctx["permit"]["id"], create_complaint_payload("NOISE", "loud"), RES))
    resolved = validate_success(api.resolve_complaint(
        complaint["id"], resolve_complaint_payload("UNFOUNDED", "no basis"), EO2), 200)
    assert resolved["status"] == "UNFOUNDED"
    assert resolved["generated_violation_id"] is None
    permit = validate_success(api.get_permit(ctx["permit"]["id"], PO), 200)
    assert permit["violation_points"] == 0
    assert permit["status"] == "ISSUED"
