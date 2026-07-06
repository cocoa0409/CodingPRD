"""Complaint enforcement ladder, host standing, and density-seat conservation.

Covers difficulty queue A instances for the depth-3 uphold->revoke->bar cascade,
seat conservation invariant, and host strike scoring; plus corner queue B
instances for dismissal side effects and enforceability validation.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    PermitStatus, HostStanding, ComplaintStatus, TaxFilingStatus,
    make_host_headers, TEST_USERS,
    setup_active_permit, setup_issued_permit, setup_draft_permit,
    file_open_complaint,
)

REGISTRAR = TEST_USERS["registrar_headers"]


def test_uphold_single_noise_complaint_keeps_host_good(api):
    """PRD §3.7: "The host's strike_total is the sum of strike_points across
    every UPHELD complaint on every permit that host owns."
    PRD §3.7: "complaints in category NOISE or TRASH carry one point."
    PRD §3.7: "The host's standing is GOOD while that aggregate is strictly below
    three and becomes BARRED once it reaches three."

    One upheld NOISE complaint (1 pt) leaves strike_total=1 and standing GOOD.

    Design: Difficulty/dual_variant_calc/host_strike_standing_risk_scoring_on_host
    """
    _, host, _, permit = setup_issued_permit()
    complaint = file_open_complaint(permit["id"], "NOISE")
    validate_success(api.uphold_complaint(complaint["id"], REGISTRAR))
    host_data = validate_success(api.get_host(host["id"], REGISTRAR))
    assert host_data["strike_total"] == 1, f"expected strike_total 1, got {host_data['strike_total']}"
    assert host_data["standing"] == HostStanding.GOOD.value


def test_host_strike_total_aggregates_upheld_only(api):
    """PRD §3.7: "The host's strike_total is the sum of strike_points across
    every UPHELD complaint on every permit that host owns - open and dismissed
    complaints contribute nothing."

    Design: Difficulty/dual_variant_calc/host_strike_standing_risk_scoring_on_host
    """
    _, host, _, permit = setup_issued_permit()
    complaint = file_open_complaint(permit["id"], "NOISE")
    validate_success(api.uphold_complaint(complaint["id"], REGISTRAR))
    host_data = validate_success(api.get_host(host["id"], REGISTRAR))
    assert host_data["strike_total"] == 1
    assert host_data["standing"] == HostStanding.GOOD.value


def test_uphold_revoke_frees_seat_and_bars_host(api):
    """PRD §3.6: "When the cumulative upheld strike total reaches four, the
    permit is revoked: from ACTIVE (or from SUSPENDED) it moves to REVOKED, its
    zone's active permit count is decremented by one to free the density seat,
    and its version is incremented."
    PRD §3.7: "The host's standing is GOOD while that aggregate is strictly below
    three and becomes BARRED once it reaches three."

    Two upheld OVER_OCCUPANCY complaints (2 pts each) => cumulative 4 => REVOKED,
    zone seat freed (apc 0), host strike_total 4 => BARRED.

    Design: Difficulty/transitive_cascade/uphold_revoke_frees_seat_and_bars_host_depth3
    """
    zone, host, _, permit = setup_active_permit()
    c1 = file_open_complaint(permit["id"], "OVER_OCCUPANCY")
    validate_success(api.uphold_complaint(c1["id"], REGISTRAR))
    c2 = file_open_complaint(permit["id"], "OVER_OCCUPANCY")
    validate_success(api.uphold_complaint(c2["id"], REGISTRAR))

    permit_after = validate_success(api.get_permit(permit["id"], REGISTRAR))
    assert permit_after["status"] == PermitStatus.REVOKED.value
    zone_after = validate_success(api.get_zone(zone["id"], REGISTRAR))
    assert zone_after["active_permit_count"] == 0, (
        f"expected active_permit_count 0, got {zone_after['active_permit_count']}"
    )
    host_after = validate_success(api.get_host(host["id"], REGISTRAR))
    assert host_after["standing"] == HostStanding.BARRED.value


def test_zone_seat_conservation_issue_activate_then_revoke(api):
    """PRD §2.6: "Each zone tracks a computed active_permit_count, defined as the
    number of permits foreign-key-linked to that zone whose status is either
    ACTIVE or SUSPENDED; however, for the purpose of the density cap this count
    also includes ISSUED permits."
    PRD §3.6: "its zone's active permit count is decremented by one to free the
    density seat."

    Two upheld UNPERMITTED complaints (2 pts each) => cumulative 4 => REVOKED and
    the zone seat is released back to 0.

    Design: Difficulty/compensating_invariant/zone_seat_conservation_issue_then_revoke
    """
    zone, host, _, permit = setup_active_permit()
    c1 = file_open_complaint(permit["id"], "UNPERMITTED")
    validate_success(api.uphold_complaint(c1["id"], REGISTRAR))
    c2 = file_open_complaint(permit["id"], "UNPERMITTED")
    validate_success(api.uphold_complaint(c2["id"], REGISTRAR))

    permit_after = validate_success(api.get_permit(permit["id"], REGISTRAR))
    assert permit_after["status"] == PermitStatus.REVOKED.value
    zone_after = validate_success(api.get_zone(zone["id"], REGISTRAR))
    assert zone_after["active_permit_count"] == 0, (
        f"expected active_permit_count 0, got {zone_after['active_permit_count']}"
    )


def test_uphold_requires_permit_enforceable(api):
    """PRD §3.7: "Upholding is the consequential path and is available only when
    the target permit is currently enforceable - that is, in ISSUED, ACTIVE, or
    SUSPENDED status; upholding against a permit outside that set is rejected
    with ERR_PERMIT_NOT_ENFORCEABLE (HTTP 422)."

    A REJECTED permit is not enforceable.

    Design: Difficulty/cross_entity_state_dependency/complaint_uphold_requires_permit_enforceable
    """
    _, host, _, permit = setup_draft_permit(permit_overrides={"permit_type": "WHOLE_HOME"}, attest=False)
    validate_success(api.reject_permit(permit["id"], REGISTRAR))
    complaint = file_open_complaint(permit["id"], "NOISE")
    validate_error(
        api.uphold_complaint(complaint["id"], REGISTRAR),
        ApiErrorId.ERR_PERMIT_NOT_ENFORCEABLE,
    )


def test_dismiss_complaint_leaves_no_strike(api):
    """PRD §3.7: "A registrar dismisses an OPEN complaint, in which case its
    strike_points remains zero and its version increments."

    Design: Corner/state_machines/complaint_dismiss_no_strike_side_effect
    """
    _, host, _, permit = setup_issued_permit()
    complaint = file_open_complaint(permit["id"], "NOISE")
    data = validate_success(api.dismiss_complaint(complaint["id"], REGISTRAR))
    assert data["status"] == ComplaintStatus.DISMISSED.value
    assert data["strike_points"] == 0
    host_data = validate_success(api.get_host(host["id"], REGISTRAR))
    assert host_data["strike_total"] == 0
