"""Lane assignments: half-open window overlap, commitment floor, state guards,
and the priority ordering between them."""
from test_helpers import (
    validate_success, validate_error, api_client,
    ApiErrorId, TEST_USERS, make_driver_headers,
    create_active_lease, offer_and_accept_lane, create_lane_payload,
)

ADMIN = TEST_USERS["lease_admin_headers"]


def _scenario_with_accepted_lane():
    """ACTIVE lease with lane L1 ACCEPTED over [2026-08-03, 2026-09-01)."""
    scenario = create_active_lease()
    lease_id = scenario["lease"]["id"]
    lane = offer_and_accept_lane(
        lease_id, scenario["operator"]["id"],
        start_date="2026-08-03", end_date="2026-09-01",
        weekly_commitment_cents=120000)
    scenario["lane"] = lane
    return scenario


def api_client_create_lane(scenario, **overrides):
    return api_client.create_lane_assignment(
        create_lane_payload(scenario["lease"]["id"], **overrides), ADMIN)


# ─── Queue A: difficulty/resource_temporal_overlap ───

def test_lane_adjacency_accepted_under_half_open_semantics(api):
    """PRD section 3.5: "the new window must not overlap any other `ACCEPTED`
    lane of the same lease — windows are half-open, so a new window whose
    `start_date` equals an existing window's `end_date` is adjacency and
    permitted, while any strict crossing rejects with `ERR_LANE_WINDOW_OVERLAP`".

    Design: Difficulty/resource_temporal_overlap/lane_half_open_adjacency_vs_overlap
    """
    scenario = _scenario_with_accepted_lane()
    driver = make_driver_headers(scenario["operator"]["id"])
    l2 = validate_success(api_client_create_lane(
        scenario, origin="DAL", destination="HOU", weekly_commitment_cents=110000,
        start_date="2026-09-01", end_date="2026-10-01"), 201)

    accepted = validate_success(api.accept_lane(l2["id"], driver), 200)
    assert accepted["status"] == "ACCEPTED", (
        "adjacency allowed: 2026-09-01 equals L1's end_date under half-open windows")


def test_lane_overlap_rejected_and_unchanged(api):
    """PRD section 3.5: "the new window must not overlap any other `ACCEPTED`
    lane of the same lease — windows are half-open, so a new window whose
    `start_date` equals an existing window's `end_date` is adjacency and
    permitted, while any strict crossing rejects with `ERR_LANE_WINDOW_OVERLAP`".

    Design: Difficulty/resource_temporal_overlap/lane_half_open_adjacency_vs_overlap
    """
    scenario = _scenario_with_accepted_lane()
    driver = make_driver_headers(scenario["operator"]["id"])
    l3 = validate_success(api_client_create_lane(
        scenario, origin="CHI", destination="MSP", weekly_commitment_cents=110000,
        start_date="2026-08-15", end_date="2026-09-10"), 201)

    res = api.accept_lane(l3["id"], driver)
    validate_error(res, ApiErrorId.ERR_LANE_WINDOW_OVERLAP.value)

    after = validate_success(api.get_lane_assignment(l3["id"], ADMIN), 200)
    assert after["status"] == "OFFERED", "rejected accept leaves the lane OFFERED"


# ─── Queue A: difficulty/priority_pair_validation_conflict ──

def test_lane_overlap_error_beats_commitment_floor(api):
    """PRD section 3.5: "Acceptance — `OFFERED` → `ACCEPTED` — is a `Driver`
    action gated by five checks, surfaced in priority order: the lane must be
    `OFFERED` (`ERR_LANE_NOT_OFFERED`), the acting driver must own the lease
    (`ERR_RESOURCE_NOT_OWNED`), the lease must be `ACTIVE` or `DEFAULTED`
    (`ERR_LEASE_NOT_ACTIVE`), the new window must not overlap any other
    `ACCEPTED` lane of the same lease — windows are half-open, so a new window
    whose `start_date` equals an existing window's `end_date` is adjacency and
    permitted, while any strict crossing rejects with `ERR_LANE_WINDOW_OVERLAP` —
    and the commitment must meet the floor: `weekly_commitment_cents` of at least
    50000 (five hundred dollars per week), failing with
    `ERR_LANE_COMMITMENT_BELOW_MIN`."

    Design: Difficulty/priority_pair_validation_conflict/lane_overlap_error_beats_commitment_floor
    """
    scenario = _scenario_with_accepted_lane()
    driver = make_driver_headers(scenario["operator"]["id"])
    # Overlaps L1 AND is below the 50000 commitment floor.
    l2 = validate_success(api_client_create_lane(
        scenario, origin="DAL", destination="HOU", weekly_commitment_cents=1000,
        start_date="2026-08-15", end_date="2026-09-10"), 201)

    res = api.accept_lane(l2["id"], driver)
    validate_error(res, ApiErrorId.ERR_LANE_WINDOW_OVERLAP.value)


def test_lane_overlap_priority_leaves_lane_offered(api):
    """PRD section 2.8: "When a request fails for more than one reason, the
    surfaced error follows a fixed priority order." and "Sixth, temporal rules
    (week-in-term, week-closed, lane-window validity, buyout timing, bay
    buffer)." and "Ninth, fiscal floors and caps."

    Design: Difficulty/priority_pair_validation_conflict/lane_overlap_error_beats_commitment_floor
    """
    scenario = _scenario_with_accepted_lane()
    driver = make_driver_headers(scenario["operator"]["id"])
    l2 = validate_success(api_client_create_lane(
        scenario, origin="DAL", destination="HOU", weekly_commitment_cents=1000,
        start_date="2026-08-15", end_date="2026-09-10"), 201)

    res = api.accept_lane(l2["id"], driver)
    body = res.json()
    assert body["data"]["error_id"] == ApiErrorId.ERR_LANE_WINDOW_OVERLAP.value, (
        f"temporal tier (sixth) must surface over fiscal tier (ninth), got "
        f"{body['data']['error_id']}")
    assert body["data"]["error_id"] != ApiErrorId.ERR_LANE_COMMITMENT_BELOW_MIN.value

    after = validate_success(api.get_lane_assignment(l2["id"], ADMIN), 200)
    assert after["status"] == "OFFERED", "rejected accept changes nothing"


# ─── Queue B: corner/state_machines + corner/validations ──

def test_lane_wrong_state_transitions_rejected(api):
    """PRD section 3.5: "Acceptance — `OFFERED` → `ACCEPTED` — is a `Driver`
    action gated by five checks, surfaced in priority order: the lane must be
    `OFFERED` (`ERR_LANE_NOT_OFFERED`)". PRD section 3.5: "A `LeaseAdmin` may
    revoke it (`ACCEPTED` → `REVOKED`; revoking a lane not `ACCEPTED` fails with
    `ERR_LANE_NOT_ACCEPTED`)."

    Design: Corner/state_machines/lane_wrong_state_transitions_rejected
    """
    scenario = _scenario_with_accepted_lane()
    driver = make_driver_headers(scenario["operator"]["id"])
    l1 = scenario["lane"]
    l2 = validate_success(api_client_create_lane(
        scenario, origin="DAL", destination="HOU", weekly_commitment_cents=110000,
        start_date="2026-09-01", end_date="2026-10-01"), 201)

    res1 = api.accept_lane(l1["id"], driver)
    validate_error(res1, ApiErrorId.ERR_LANE_NOT_OFFERED.value)

    res2 = api.revoke_lane(l2["id"], ADMIN)
    validate_error(res2, ApiErrorId.ERR_LANE_NOT_ACCEPTED.value)

    after1 = validate_success(api.get_lane_assignment(l1["id"], ADMIN), 200)
    after2 = validate_success(api.get_lane_assignment(l2["id"], ADMIN), 200)
    assert after1["status"] == "ACCEPTED"
    assert after2["status"] == "OFFERED"


def test_lane_create_and_accept_validation_guards(api):
    """PRD section 3.5: "The window must be nonempty — an `end_date` not strictly
    later than `start_date` is rejected with `ERR_INVALID_DATE_RANGE` (HTTP
    400)." PRD section 3.5: "the commitment must meet the floor:
    `weekly_commitment_cents` of at least 50000 (five hundred dollars per week),
    failing with `ERR_LANE_COMMITMENT_BELOW_MIN`."

    Design: Corner/validations/lane_create_and_accept_validation_guards
    """
    scenario = create_active_lease()
    driver = make_driver_headers(scenario["operator"]["id"])

    res1 = api_client_create_lane(
        scenario, origin="DAL", destination="HOU", weekly_commitment_cents=120000,
        start_date="2026-09-01", end_date="2026-09-01")
    validate_error(res1, ApiErrorId.ERR_INVALID_DATE_RANGE.value)

    lane = validate_success(api_client_create_lane(
        scenario, weekly_commitment_cents=1000,
        start_date="2026-08-03", end_date="2026-10-26"), 201)
    res2 = api.accept_lane(lane["id"], driver)
    validate_error(res2, ApiErrorId.ERR_LANE_COMMITMENT_BELOW_MIN.value)

    after = validate_success(api.get_lane_assignment(lane["id"], ADMIN), 200)
    assert after["status"] == "OFFERED", "rejected accept leaves the lane OFFERED"
