"""Permit lifecycle: renewal self-loop, expiry, reinstatement, and OCC guards.

Covers difficulty queue A instances for the ACTIVE renew self-loop, plus corner
queue B instances for expiry, reinstatement, OCC conflicts, and issue side effects.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, PermitStatus,
    make_host_headers, TEST_USERS,
    setup_active_permit, setup_issued_permit, setup_suspended_permit,
    setup_active_permit_in_renewal_window,
    file_open_complaint,
)

REGISTRAR = TEST_USERS["registrar_headers"]


def test_renew_extends_expiry_by_365_from_anchor(api):
    """PRD §3.6: "A successful renewal extends expires_at by 365 days from the
    existing anchor - not from the current clock time - and increments the
    permit's version; it is a self-loop on the ACTIVE state and does not touch
    the zone's active permit count."

    Permit issued at 2026-05-01 expires 2027-05-01; renewing in-window extends
    the anchor by 365 days. 2027-05-01 + 365 days crosses leap-year Feb 2028
    (366-day span), landing on 2028-04-30, and status stays ACTIVE.

    Design: Difficulty/non_linear_state_machine/permit_cyclic_active_renew_self_loop
    """
    _, host, _, permit, ver = setup_active_permit_in_renewal_window("2027-04-15T00:00:00Z")
    data = validate_success(
        api.renew_permit(permit["id"], {"expected_permit_version": ver}, make_host_headers(host["id"]))
    )
    assert data["status"] == PermitStatus.ACTIVE.value
    assert data["expires_at"] == "2028-04-30T00:00:00.000Z", (
        f"expected 2028-04-30T00:00:00.000Z, got {data['expires_at']}"
    )


def test_renew_bumps_version_and_stays_active(api):
    """PRD §2.7: "A renewal request must carry expected_permit_version, which
    must equal the target permit's current version - the value the client last
    observed."
    PRD §2.4: "The version field is an integer that begins at its initial value
    on creation and increments by one on every successful mutation of the
    resource."

    Design: Difficulty/non_linear_state_machine/permit_cyclic_active_renew_self_loop
    """
    _, host, _, permit, ver = setup_active_permit_in_renewal_window("2027-04-15T00:00:00Z")
    data = validate_success(
        api.renew_permit(permit["id"], {"expected_permit_version": ver}, make_host_headers(host["id"]))
    )
    assert data["status"] == PermitStatus.ACTIVE.value
    assert data["version"] == ver + 1, f"expected version {ver + 1}, got {data['version']}"


def test_renew_correct_version_succeeds_and_bumps_version(api):
    """PRD §2.7: "A renewal request must carry expected_permit_version, which
    must equal the target permit's current version - the value the client last
    observed. Renewal legitimately re-anchors the permit's expiry and bumps its
    version."

    Design: Corner/cross_cutting_complexity_layers/renew_correct_version_succeeds_and_bumps_version
    """
    _, host, _, permit, ver = setup_active_permit_in_renewal_window("2027-04-15T00:00:00Z")
    data = validate_success(
        api.renew_permit(permit["id"], {"expected_permit_version": ver}, make_host_headers(host["id"]))
    )
    assert data["status"] == PermitStatus.ACTIVE.value
    assert data["version"] == ver + 1, f"expected version {ver + 1}, got {data['version']}"


def test_renew_stale_version_rejected(api):
    """PRD §2.7: "if the permit's version has advanced since the client last read
    it (for instance because an earlier renewal already ran), the
    expected_permit_version the client sends is stale, and the renewal is
    rejected with ERR_STALE_VERSION (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/renew_stale_permit_version_occ_conflict
    """
    # An in-window ACTIVE permit whose version is advanced by a suspend+reinstate
    # cycle (which leaves expires_at, and thus the renewal window, unchanged).
    # A renew carrying the pre-cascade version is therefore stale while the
    # permit remains ACTIVE and in-window, so the version guard (§2.7) fires.
    _, host, _, permit, ver = setup_active_permit_in_renewal_window("2027-04-15T00:00:00Z")
    hh = make_host_headers(host["id"])
    # One upheld OVER_OCCUPANCY (2 pts) suspends the ACTIVE permit (§3.6);
    # host strike_total stays at 2 (< 3) so standing remains GOOD (§3.7).
    c = file_open_complaint(permit["id"], "OVER_OCCUPANCY")
    validate_success(api.uphold_complaint(c["id"], REGISTRAR))
    # Registrar reinstates SUSPENDED -> ACTIVE, bumping the permit version again
    # without touching expires_at, so the clock is still inside the window.
    validate_success(api.reinstate_permit(permit["id"], REGISTRAR))
    # `ver` (read before the cascade) is now stale against the advanced version.
    validate_error(
        api.renew_permit(permit["id"], {"expected_permit_version": ver}, hh),
        ApiErrorId.ERR_STALE_VERSION,
    )


def test_renew_outside_window_rejected(api):
    """PRD §3.6: "Renewal is permitted only when the current clock time is at or
    after expires_at minus 30 days and strictly before expires_at; outside that
    window the renewal is rejected with ERR_RENEWAL_WINDOW_CLOSED (HTTP 422)."

    Clock at 2026-06-01 is well before the 2027-04-01 window open.

    Design: Corner/validations/renewal_outside_window_rejected
    """
    _, host, _, permit, ver = setup_active_permit_in_renewal_window("2026-06-01T00:00:00Z")
    validate_error(
        api.renew_permit(permit["id"], {"expected_permit_version": ver}, make_host_headers(host["id"])),
        ApiErrorId.ERR_RENEWAL_WINDOW_CLOSED,
    )


def test_permit_auto_expires_on_clock_advance(api):
    """PRD §2.5: "A permit in ISSUED or ACTIVE status whose expires_at is at or
    before the current clock time auto-transitions to EXPIRED on the next touch;
    because an expired permit no longer occupies a density seat, this also
    decrements its zone's active permit count."

    Design: Corner/state_machines/permit_auto_expires_on_clock_advance
    """
    zone, host, _, permit = setup_issued_permit()
    validate_success(api.set_clock("2027-05-01T00:00:00Z", REGISTRAR))
    data = validate_success(api.get_permit(permit["id"], REGISTRAR))
    assert data["status"] == PermitStatus.EXPIRED.value
    zone_after = validate_success(api.get_zone(zone["id"], REGISTRAR))
    assert zone_after["active_permit_count"] == 0, (
        f"expected active_permit_count 0 after expiry, got {zone_after['active_permit_count']}"
    )


def test_reinstate_suspended_permit_returns_active(api):
    """PRD §3.6: "A registrar may later reinstate a SUSPENDED permit - provided
    its cumulative upheld strike total is still below four - moving it from
    SUSPENDED back to ACTIVE and incrementing its version."

    Design: Corner/state_machines/reinstate_suspended_permit_returns_active
    """
    _, host, _, permit = setup_suspended_permit()
    assert permit["status"] == PermitStatus.SUSPENDED.value
    data = validate_success(api.reinstate_permit(permit["id"], REGISTRAR))
    assert data["status"] == PermitStatus.ACTIVE.value


def test_issue_side_effects_visible_same_response(api):
    """PRD §3.4: "it transitions from DRAFT to ISSUED, issued_at is set to the
    current clock time, expires_at is set to issued_at plus 365 days, the zone's
    active permit count is incremented by one ... and the permit's version is
    incremented."

    Issued at the default clock 2026-05-01 => expires_at 2027-05-01, visible in
    the same issue response.

    Design: Corner/consistency_model/issue_side_effects_visible_same_response
    """
    _, host, _, permit = setup_issued_permit()
    assert permit["status"] == PermitStatus.ISSUED.value
    assert permit["expires_at"] == "2027-05-01T00:00:00.000Z", (
        f"expected 2027-05-01T00:00:00.000Z, got {permit['expires_at']}"
    )
