"""Validation priority conflicts (state vs segregation, state vs grace-timing) and
cross-entity state-dependency guards (GPS activate needs ACTIVE bond, record-fta
needs ACTIVE bond).
"""
from test_helpers import (
    validate_success, validate_error, get_success_data, api_client,
    setup_draft_surety_bond, setup_recovery_open_bond, setup_forfeited_bond,
    setup_active_bond_with_assigned_gps,
    pin_clock, bond_version,
    make_compliance_officer_headers,
    TEST_USERS,
)

OFFICER = TEST_USERS["compliance_officer_headers"]
COURT = TEST_USERS["court_headers"]
RECOVERY = TEST_USERS["recovery_agent_headers"]


# ---------------------------------------------------------------------------
# Difficulty/priority_pair_validation_conflict/state_beats_segregation_on_exonerate
# ---------------------------------------------------------------------------
def test_state_error_beats_segregation_on_draft_exonerate(api):
    """PRD 2.6: "then state-machine legality (`ERR_INVALID_STATE`, HTTP 409 — the
    target resource is not in a state from which the requested transition is
    defined), then optimistic-concurrency staleness, and finally the referential,
    temporal, and fiscal business rules described throughout Section 3."

    Exoneration is defined only from ACTIVE; exonerating a DRAFT bond surfaces
    ERR_INVALID_STATE before the segregation-of-duties (business_referential)
    check, even when the officer's X-User-ID equals the activating agent's.

    Design: Difficulty/priority_pair_validation_conflict/state_beats_segregation_on_exonerate
    """
    scen = setup_draft_surety_bond(bail_amount_cents=1_000_000, with_indemnity=False,
                                   with_collateral=False, agent_user_id="shared-user-1")
    # Same X-User-ID as the agent who created/would-activate the bond.
    same_user_officer = make_compliance_officer_headers("shared-user-1")
    resp = api.exonerate_bond(scen["def_id"], scen["bond_id"], same_user_officer)
    validate_error(resp, "ERR_INVALID_STATE")


def test_state_error_beats_segregation_on_revoked_bond_exonerate(api):
    """PRD 2.6: "then state-machine legality (`ERR_INVALID_STATE`, HTTP 409 — the
    target resource is not in a state from which the requested transition is
    defined), then optimistic-concurrency staleness, and finally the referential,
    temporal, and fiscal business rules described throughout Section 3."
    PRD 3.7: "Exoneration is defined only from `ACTIVE`."

    A REVOKED (terminal) bond likewise has no exonerate edge; a same-user officer
    self-approval surfaces ERR_INVALID_STATE before the segregation check.

    Design: Difficulty/priority_pair_validation_conflict/state_beats_segregation_on_exonerate
    """
    scen = setup_draft_surety_bond(bail_amount_cents=1_000_000, with_indemnity=False,
                                   with_collateral=False, agent_user_id="shared-user-2")
    get_success_data(api_client.revoke_bond(scen["def_id"], scen["bond_id"], scen["agent"]))
    same_user_officer = make_compliance_officer_headers("shared-user-2")
    resp = api.exonerate_bond(scen["def_id"], scen["bond_id"], same_user_officer)
    validate_error(resp, "ERR_INVALID_STATE")


# ---------------------------------------------------------------------------
# Difficulty/priority_pair_validation_conflict/state_beats_grace_not_expired_on_judgment
# ---------------------------------------------------------------------------
def test_state_error_beats_grace_not_expired_on_reinstated_proceeding(api):
    """PRD 2.6: "a forfeiture judgment attempted with a stale version against a
    proceeding in the wrong state surfaces the state error before the staleness
    check."
    PRD 3.6: "Judgment may be entered from either `FORFEITED` or `RECOVERY_OPEN`."

    A REINSTATED proceeding has no JUDGMENT edge; entering judgment within grace
    surfaces ERR_INVALID_STATE (priority 8) rather than ERR_GRACE_NOT_EXPIRED.

    Design: Difficulty/priority_pair_validation_conflict/state_beats_grace_not_expired_on_judgment
    """
    scen = setup_recovery_open_bond(bail_amount_cents=1_000_000, liability_share_cents=1_000_000)
    # Reinstate within grace -> proceeding terminal REINSTATED, clock still within grace.
    get_success_data(api_client.reinstate(scen["def_id"], scen["proc_id"], OFFICER))
    bv = bond_version(scen["bond_id"])
    resp = api.enter_judgment(scen["def_id"], scen["proc_id"], {"expected_bond_version": bv}, OFFICER)
    validate_error(resp, "ERR_INVALID_STATE")


def test_state_error_beats_grace_and_stale_version_on_reinstated_proceeding(api):
    """PRD 2.6: "a forfeiture judgment attempted with a stale version against a
    proceeding in the wrong state surfaces the state error before the staleness
    check."

    Same wrong-state REINSTATED proceeding within grace, but carrying a stale
    expected_bond_version: the state error (priority 8) still pre-empts both the
    staleness check (priority 9) and the grace-timing check (priority 16) ->
    ERR_INVALID_STATE.

    Design: Difficulty/priority_pair_validation_conflict/state_beats_grace_not_expired_on_judgment
    """
    scen = setup_recovery_open_bond(bail_amount_cents=1_000_000, liability_share_cents=1_000_000)
    get_success_data(api_client.reinstate(scen["def_id"], scen["proc_id"], OFFICER))
    stale = bond_version(scen["bond_id"]) - 1
    resp = api.enter_judgment(scen["def_id"], scen["proc_id"], {"expected_bond_version": stale}, OFFICER)
    validate_error(resp, "ERR_INVALID_STATE")


# ---------------------------------------------------------------------------
# Difficulty/cross_entity_state_dependency/gps_activate_requires_bond_active
# ---------------------------------------------------------------------------
def test_gps_activate_blocked_when_bond_draft(api):
    """PRD 3.8: "A `BondsAgent` then activates an assigned device, advancing it
    `ASSIGNED → ACTIVE`, which is permitted only when the device is `ASSIGNED` and
    the bond it monitors is in coverage status `ACTIVE`."

    A device assigned to a still-DRAFT bond cannot be activated -> ERR_INVALID_STATE.

    Design: Difficulty/cross_entity_state_dependency/gps_activate_requires_bond_active
    """
    # Build a DRAFT GPS-required bond, register + assign a device, but do NOT activate the bond.
    scen = setup_draft_surety_bond(bail_amount_cents=1_000_000, gps_required=True,
                                   with_indemnity=False, with_collateral=False)
    device = get_success_data(api_client.create_gps_device({"serial_number": "GPS-DRAFT-1"}, scen["agent"]))
    get_success_data(api_client.assign_gps(scen["def_id"], scen["bond_id"], {"device_id": device["id"]}, scen["agent"]))
    resp = api.activate_gps(scen["def_id"], device["id"], scen["agent"])
    validate_error(resp, "ERR_INVALID_STATE")


def test_gps_activate_succeeds_when_bond_active(api):
    """PRD 3.8: "A `BondsAgent` then activates an assigned device, advancing it
    `ASSIGNED → ACTIVE`, which is permitted only when the device is `ASSIGNED` and
    the bond it monitors is in coverage status `ACTIVE`; from activation onward the
    device counts violations."

    Positive complement on the same GpsDevice->Bond dependency: once the monitored
    bond is ACTIVE, activating the ASSIGNED device succeeds and the device reaches
    ACTIVE.

    Design: Difficulty/cross_entity_state_dependency/gps_activate_requires_bond_active
    """
    scen = setup_active_bond_with_assigned_gps(bail_amount_cents=1_000_000, liability_share_cents=1_000_000,
                                               serial_number="GPS-ACT-1")
    activated = validate_success(api.activate_gps(scen["def_id"], scen["device_id"], scen["agent"]))
    assert activated["status"] == "ACTIVE", activated["status"]


# ---------------------------------------------------------------------------
# Difficulty/cross_entity_state_dependency/record_fta_requires_bond_active
# ---------------------------------------------------------------------------
def test_record_fta_blocked_when_bond_not_active(api):
    """PRD 3.5: "Recording a failure to appear advances the date to
    `FAILED_TO_APPEAR`; this is allowed when the date is `SCHEDULED` or `NOTIFIED`,
    but only when the system clock is at or after the hearing's `scheduled_utc` (an
    earlier attempt is the same `ERR_TIMING_VIOLATION`), and only when the linked
    bond is currently in coverage status `ACTIVE`."

    A court date on a never-activated DRAFT bond cannot record FTA even after the
    scheduled instant -> ERR_INVALID_STATE.

    Design: Difficulty/cross_entity_state_dependency/record_fta_requires_bond_active
    """
    pin_clock("2026-07-01T00:00:00Z")
    scen = setup_draft_surety_bond(bail_amount_cents=1_000_000, with_indemnity=False,
                                   with_collateral=False)
    cd = get_success_data(api_client.create_court_date(
        scen["def_id"], scen["bond_id"], {"scheduled_utc": "2026-07-02T09:00:00Z", "duration_minutes": 60}, COURT))
    pin_clock("2026-07-02T10:00:00Z")
    resp = api.record_fta(scen["def_id"], cd["id"], COURT)
    validate_error(resp, "ERR_INVALID_STATE")


def test_record_fta_succeeds_when_bond_active(api):
    """PRD 3.5: "Recording a failure to appear advances the date to
    `FAILED_TO_APPEAR`; this is allowed when the date is `SCHEDULED` or `NOTIFIED`,
    but only when the system clock is at or after the hearing's `scheduled_utc` (an
    earlier attempt is the same `ERR_TIMING_VIOLATION`), and only when the linked
    bond is currently in coverage status `ACTIVE`."

    Positive complement on the same CourtDate->Bond dependency: with the linked bond
    ACTIVE and the clock at/after the scheduled instant, record-fta succeeds and the
    court date reaches FAILED_TO_APPEAR.

    Design: Difficulty/cross_entity_state_dependency/record_fta_requires_bond_active
    """
    scen = setup_forfeited_bond(bail_amount_cents=1_000_000, liability_share_cents=1_000_000)
    cd = validate_success(api.get_court_date(scen["court_date_id"], COURT))
    assert cd["status"] == "FAILED_TO_APPEAR", cd["status"]
