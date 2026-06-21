"""Permit lifecycle: branching state machine, zone capacity (strict-less-than),
zone-type gating, expire-check, the OCC zone-version token, and the slot-conservation
invariant.

PRD §3.3 governs activation/rejection/revocation/expiry; §2.8 the OCC token.
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    setup_garage_with_zone,
    create_motorist,
    request_permit,
    activate_permit,
    get_zone,
    get_permit,
    set_clock,
)

ADMIN = TEST_USERS["facility_admin_headers"]


def test_new_permit_starts_in_requested(api):
    """PRD §3.3: "The new permit is created in `REQUESTED` status; its `status` is
    one of `REQUESTED`, `ACTIVE`, `REVOKED`, `EXPIRED`, or `REJECTED`."

    Design: Corner/state_machines/new_permit_starts_in_requested
    """
    facility = setup_garage_with_zone(zone_type="MIXED", permit_capacity=5)
    motorist = create_motorist("init@x.com", default_plate="INI111")
    permit = request_permit(facility["zone"]["id"], motorist["id"], "INI111")
    assert permit["status"] == "REQUESTED"


def test_permit_activate_in_permit_zone_succeeds(api):
    """PRD §3.3: "Second, the permit's zone must have a `zone_type` of either
    `PERMIT` or `MIXED`; a permit cannot be activated in a `TRANSIENT` zone, and an
    attempt is rejected with `ERR_ZONE_TYPE_FORBIDDEN`."
    PRD §3.3: "The zone's `permits_active_count` is incremented by one, and because
    that recomputation mutates the zone, the zone's `version` advances".

    Design: Difficulty/cross_entity_state_dependency/permit_activate_depends_on_zone_type_pair
    """
    facility = setup_garage_with_zone(zone_type="PERMIT", permit_capacity=5)
    zone = facility["zone"]
    motorist = create_motorist("ce1@x.com", default_plate="CEP111")
    permit = request_permit(zone["id"], motorist["id"], "CEP111")
    activated = activate_permit(permit["id"], zone["version"])
    assert activated["status"] == "ACTIVE"
    assert get_zone(zone["id"])["permits_active_count"] == 1


def test_activate_in_transient_zone_returns_zone_type_forbidden(api):
    """PRD §3.3: "a permit cannot be activated in a `TRANSIENT` zone, and an attempt
    is rejected with `ERR_ZONE_TYPE_FORBIDDEN`."

    Activating in a TRANSIENT zone (capacity 0) violates both zone-type and
    capacity; the zone-type business constraint is reported (priority 6 < 12).

    Design: Difficulty/priority_pair_validation_conflict/zone_type_beats_capacity_on_permit_activate
    """
    facility = setup_garage_with_zone(zone_type="TRANSIENT", permit_capacity=0)
    zone = facility["zone"]
    motorist = create_motorist("zt@x.com", default_plate="ZTP111")
    permit = request_permit(zone["id"], motorist["id"], "ZTP111")
    resp = api.activate_permit(permit["id"], {"expected_zone_version": zone["version"]}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_ZONE_TYPE_FORBIDDEN.value)


def test_activate_in_transient_zone_zone_type_pair(api):
    """PRD §3.3: "Second, the permit's zone must have a `zone_type` of either
    `PERMIT` or `MIXED`; a permit cannot be activated in a `TRANSIENT` zone, and an
    attempt is rejected with `ERR_ZONE_TYPE_FORBIDDEN`."

    Cross-entity gate on the Permit→Zone pair, asserted as the negative branch of
    the zone-type dependency.

    Design: Difficulty/cross_entity_state_dependency/permit_activate_depends_on_zone_type_pair
    """
    facility = setup_garage_with_zone(zone_type="TRANSIENT", permit_capacity=0)
    zone = facility["zone"]
    motorist = create_motorist("cet@x.com", default_plate="CET111")
    permit = request_permit(zone["id"], motorist["id"], "CET111")
    resp = api.activate_permit(permit["id"], {"expected_zone_version": zone["version"]}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_ZONE_TYPE_FORBIDDEN.value)


def test_zone_capacity_strict_less_than_blocks_second_activation(api):
    """PRD §3.3: "Third, the zone's `permits_active_count` must be strictly less
    than its `permit_capacity`; if the count has already reached or would reach the
    capacity, the activation is rejected with `ERR_ZONE_AT_CAPACITY`."

    capacity 1, count already 1 → 1 < 1 is false → second activation rejected.

    Design: Difficulty/boundary_precision_check/zone_capacity_strict_less_than_boundary_on_activate
    """
    facility = setup_garage_with_zone(zone_type="MIXED", permit_capacity=1)
    zone = facility["zone"]
    m1 = create_motorist("cap1@x.com", default_plate="CAP111")
    m2 = create_motorist("cap2@x.com", default_plate="CAP222")
    p1 = request_permit(zone["id"], m1["id"], "CAP111")
    activate_permit(p1["id"], zone["version"])
    p2 = request_permit(zone["id"], m2["id"], "CAP222")
    z_v1 = get_zone(zone["id"])["version"]
    resp = api.activate_permit(p2["id"], {"expected_zone_version": z_v1}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_ZONE_AT_CAPACITY.value)


def test_activate_already_active_permit_returns_invalid_state(api):
    """PRD §3.3: "First, the permit must currently be in `REQUESTED` status, or the
    request is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/activate_already_active_permit_returns_invalid_state
    """
    facility = setup_garage_with_zone(zone_type="MIXED", permit_capacity=5)
    zone = facility["zone"]
    motorist = create_motorist("aa@x.com", default_plate="AAP111")
    permit = request_permit(zone["id"], motorist["id"], "AAP111")
    activate_permit(permit["id"], zone["version"])
    z_v1 = get_zone(zone["id"])["version"]
    resp = api.activate_permit(permit["id"], {"expected_zone_version": z_v1}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    assert get_zone(zone["id"])["permits_active_count"] == 1


def test_permit_revert_loop_active_revoked_vs_requested_rejected(api):
    """PRD §3.3: "An administrator may revoke an `ACTIVE` permit, moving it from
    `ACTIVE` to `REVOKED`".
    PRD §3.3: "A `FacilityAdmin` may instead reject a still-`REQUESTED` permit,
    moving it from `REQUESTED` to `REJECTED`".

    One permit forks REQUESTED→ACTIVE→REVOKED; a second forks REQUESTED→REJECTED.

    Design: Difficulty/non_linear_state_machine/permit_revert_loop_requested_active_revoked
    """
    facility = setup_garage_with_zone(zone_type="MIXED", permit_capacity=1)
    zone = facility["zone"]
    motorist = create_motorist("rev@x.com", default_plate="PPP111")
    p = request_permit(zone["id"], motorist["id"], "PPP111")
    activate_permit(p["id"], zone["version"])
    q = request_permit(zone["id"], motorist["id"], "QQQ222")

    revoked = validate_success(api.revoke_permit(p["id"], ADMIN))
    rejected = validate_success(api.reject_permit(q["id"], ADMIN))
    assert revoked["status"] == "REVOKED"
    assert rejected["status"] == "REJECTED"
    assert get_zone(zone["id"])["permits_active_count"] == 0


def test_zone_capacity_conserved_under_revoke_without_promotion(api):
    """PRD §3.3: "Revocation lowers the zone's `permits_active_count` by one".
    PRD §3.3: "The `permit_capacity` is the maximum number of `ACTIVE` permits the
    zone may hold".

    Activate then revoke with no waitlist leaves permits_active_count back at 0 and
    capacity unchanged at 5 — no slot leak.

    Design: Difficulty/compensating_invariant/zone_capacity_conserved_under_revoke_without_promotion
    """
    facility = setup_garage_with_zone(zone_type="MIXED", permit_capacity=5)
    zone = facility["zone"]
    motorist = create_motorist("zc@x.com", default_plate="ZCP111")
    p = request_permit(zone["id"], motorist["id"], "ZCP111")
    activate_permit(p["id"], zone["version"])
    revoked = validate_success(api.revoke_permit(p["id"], ADMIN))
    assert revoked["status"] == "REVOKED"
    z = get_zone(zone["id"])
    assert z["permits_active_count"] == 0
    assert z["permit_capacity"] == 5


def test_expire_check_before_valid_until_is_no_op(api):
    """PRD §3.3: "The sweep expires an `ACTIVE` permit — moving it from `ACTIVE` to
    `EXPIRED` — only when the current clock instant is at or after the permit's
    `valid_until_utc`; a permit that has not yet reached its expiry instant is left
    untouched."

    Design: Corner/state_machines/expire_check_before_valid_until_no_op
    """
    set_clock("2026-06-01T00:00:00Z")
    facility = setup_garage_with_zone(zone_type="MIXED", permit_capacity=5)
    zone = facility["zone"]
    motorist = create_motorist("exp@x.com", default_plate="EXP111")
    p = request_permit(zone["id"], motorist["id"], "EXP111")
    activate_permit(p["id"], zone["version"])
    set_clock("2026-06-02T00:00:00Z")
    swept = validate_success(api.expire_check_permit(p["id"], ADMIN))
    assert swept["status"] == "ACTIVE"
    assert get_zone(zone["id"])["permits_active_count"] == 1


def test_expire_check_after_valid_until_expires_permit(api):
    """PRD §3.3: "Expiry, like revocation, lowers the zone's `permits_active_count`
    by one and triggers the same waitlist promotion cascade."
    PRD §3.3: "its `valid_until_utc` is set to thirty days after `valid_from_utc`".

    Activated 2026-06-01 (valid until 2026-07-01); clock at 2026-07-02 → EXPIRED.

    Design: Corner/state_machines/expire_check_after_valid_until_expires_permit
    """
    set_clock("2026-06-01T00:00:00Z")
    facility = setup_garage_with_zone(zone_type="MIXED", permit_capacity=5)
    zone = facility["zone"]
    motorist = create_motorist("exp2@x.com", default_plate="EXX111")
    p = request_permit(zone["id"], motorist["id"], "EXX111")
    activate_permit(p["id"], zone["version"])
    set_clock("2026-07-02T00:00:00Z")
    swept = validate_success(api.expire_check_permit(p["id"], ADMIN))
    assert swept["status"] == "EXPIRED"
    assert get_zone(zone["id"])["permits_active_count"] == 0


def test_activate_with_correct_zone_version_succeeds_and_bumps_version(api):
    """PRD §2.8: "The activation request must carry `expected_zone_version` holding
    the client's last observed `version` of the target permit's zone."
    PRD §3.3: "The zone's `permits_active_count` is incremented by one, and because
    that recomputation mutates the zone, the zone's `version` advances".

    Design: Corner/cross_cutting_complexity_layers/occ_correct_zone_version_activate_succeeds
    """
    facility = setup_garage_with_zone(zone_type="MIXED", permit_capacity=5)
    zone = facility["zone"]
    motorist = create_motorist("occ@x.com", default_plate="OCC111")
    p = request_permit(zone["id"], motorist["id"], "OCC111")
    activated = activate_permit(p["id"], zone["version"])
    assert activated["status"] == "ACTIVE"
    z = get_zone(zone["id"])
    assert z["version"] == zone["version"] + 1
    assert z["permits_active_count"] == 1


def test_activate_with_stale_zone_version_returns_412(api):
    """PRD §2.8: "If `expected_zone_version` does not equal the zone's current
    `version` — meaning another writer has changed the zone's capacity picture since
    the client last read it — the activation is rejected with
    `ERR_STALE_ZONE_VERSION` and an HTTP 412 status".

    P1 activates first (bumps zone version); P2 still carries the pre-activation
    version → 412.

    Design: Corner/cross_cutting_complexity_layers/occ_stale_zone_version_activate_returns_412
    """
    facility = setup_garage_with_zone(zone_type="MIXED", permit_capacity=5)
    zone = facility["zone"]
    stale_v = zone["version"]
    m1 = create_motorist("st1@x.com", default_plate="STA111")
    m2 = create_motorist("st2@x.com", default_plate="STA222")
    p1 = request_permit(zone["id"], m1["id"], "STA111")
    p2 = request_permit(zone["id"], m2["id"], "STA222")
    activate_permit(p1["id"], stale_v)
    resp = api.activate_permit(p2["id"], {"expected_zone_version": stale_v}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_STALE_ZONE_VERSION.value)
    assert get_permit(p2["id"])["status"] == "REQUESTED"
