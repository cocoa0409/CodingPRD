"""Queue A — rule_id: resource_temporal_overlap.

Three different interval semantics over three different resources: a 12-hour
buffered pad on the adjuster, a flat room counter on the housing block (where
overlap is not the criterion at all), and inclusive containment inside a
deployment window.
"""
from test_helpers import validate_error, validate_success
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_money_equals
from test_helpers.test_users import (
    make_catastrophe_manager_headers,
    make_claims_examiner_headers,
    make_deployment_coordinator_headers,
)

CM = make_catastrophe_manager_headers("cm_1")
DC = make_deployment_coordinator_headers("dc_1")
CE = make_claims_examiner_headers("ce_1")


def _staff_adjuster(api, full_name, home_state, daily_rate=450, per_diem_rate=60,
                    desk_certified=False):
    return validate_success(
        api.create_adjuster(
            {
                "full_name": full_name,
                "employment_type": "STAFF",
                "home_state": home_state,
                "licensed_states": [home_state],
                "license_expiry_utc": "2027-08-31T00:00:00.000Z",
                "max_open_claims": 10,
                "daily_rate": daily_rate,
                "per_diem_rate": per_diem_rate,
                "desk_certified": desk_certified,
                "aerial_certified": False,
            },
            DC,
        ),
        201,
    )


# ---------------------------------------------------------------------------
# Instance 1 — adjuster_deployment_buffered_semantics_12h_gap_exact_boundary
# ---------------------------------------------------------------------------
def _demobilized_base_window_and_two_probes(api):
    """CAT-2026-801 DECLARED; one DESK deployment 2026-09-01 -> 2026-09-05 already
    DEMOBILIZED; two REQUESTED probes starting 11h59m59s and exactly 12h after that
    window's end. Clock left at 2026-08-03 so the adjuster is AVAILABLE again."""
    event = validate_success(
        api.create_event(
            {
                "cat_code": "CAT-2026-801",
                "peril_type": "HAIL",
                "jurisdiction_state": "TX",
                "event_start_utc": "2026-07-28T00:00:00.000Z",
                "exposure_count": 520,
                "avg_insured_value": 165000,
                "expected_severity_index": 0.0700,
            },
            CM,
        ),
        201,
    )
    validate_success(api.declare_event(event["id"], CM))
    adjuster = _staff_adjuster(
        api, "Buffer Probe", "TX", daily_rate=400, per_diem_rate=0, desk_certified=True
    )

    def _desk_deployment(window_start, window_end):
        return validate_success(
            api.create_deployment(
                {
                    "event_id": event["id"],
                    "role_type": "DESK",
                    "window_start_utc": window_start,
                    "window_end_utc": window_end,
                    "adjuster_id": adjuster["id"],
                },
                DC,
            ),
            201,
        )

    base = _desk_deployment("2026-09-01T00:00:00.000Z", "2026-09-05T00:00:00.000Z")
    validate_success(api.confirm_deployment(base["id"], DC))
    validate_success(api.set_clock("2026-08-02T00:00:00.000Z", DC))
    validate_success(api.demobilize_deployment(base["id"], DC))
    validate_success(api.set_clock("2026-08-03T00:00:00.000Z", DC))
    bad = _desk_deployment("2026-09-05T11:59:59.000Z", "2026-09-09T00:00:00.000Z")
    ok = _desk_deployment("2026-09-05T12:00:00.000Z", "2026-09-09T00:00:00.000Z")
    return event, adjuster, base, bad, ok


def test_a_gap_one_second_inside_the_twelve_hour_pad_is_rejected(api):
    """PRD §3.5: "The **rest-buffer rule** must hold: for the window being confirmed, no
    other deployment of the same adjuster in `CONFIRMED`, `ON_SITE` or `DEMOBILIZED` may
    sit closer than twelve hours on either side."
    PRD §3.5: "Concretely, a conflict exists when the new window's start is earlier than
    the other window's end extended forward by twelve hours *and* the other window's start
    is earlier than the new window's end extended forward by twelve hours."
    PRD §3.5: "Exact adjacency is therefore **rejected**: a full twelve-hour gap must
    separate the windows, and the rejection is `ERR_DEPLOYMENT_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/adjuster_deployment_buffered_semantics_12h_gap_exact_boundary
    """
    _, adjuster, base, bad, _ = _demobilized_base_window_and_two_probes(api)
    staged = validate_success(api.get_adjuster(adjuster["id"], DC))
    assert staged["deployment_status"] == "AVAILABLE"
    assert validate_success(api.get_deployment(base["id"], DC))["status"] == "DEMOBILIZED"

    validate_error(
        api.confirm_deployment(bad["id"], DC), ApiErrorId.ERR_DEPLOYMENT_WINDOW_CONFLICT, 409
    )

    assert validate_success(api.get_deployment(bad["id"], DC))["status"] == "REQUESTED"
    after = validate_success(api.get_adjuster(adjuster["id"], DC))
    assert after["deployment_status"] == "AVAILABLE", "the rejected confirm had no side effect"
    assert_money_equals(after["cumulative_deployed_hours"], 96.00, "cumulative_deployed_hours")


def test_a_gap_of_exactly_twelve_hours_clears_the_pad(api):
    """PRD §3.5: "Exact adjacency is therefore **rejected**: a full twelve-hour gap must
    separate the windows, and the rejection is `ERR_DEPLOYMENT_WINDOW_CONFLICT`."
    PRD §3.3: "On the deployment axis, confirmation of a deployment for an available
    adjuster moves them `AVAILABLE → DEPLOYED` and recomputes their score."
    PRD §3.5: "Deployment lists may be filtered by `event_id`, `adjuster_id`,
    `housing_block_id`, `status` and `role_type`."

    Design: Difficulty/resource_temporal_overlap/adjuster_deployment_buffered_semantics_12h_gap_exact_boundary
    """
    _, adjuster, _, bad, ok = _demobilized_base_window_and_two_probes(api)
    validate_error(
        api.confirm_deployment(bad["id"], DC), ApiErrorId.ERR_DEPLOYMENT_WINDOW_CONFLICT
    )

    confirmed = validate_success(api.confirm_deployment(ok["id"], DC))

    assert confirmed["status"] == "CONFIRMED"
    assert validate_success(api.get_adjuster(adjuster["id"], DC))["deployment_status"] == "DEPLOYED"
    rows = validate_success(api.list_deployments(DC, params={"adjuster_id": adjuster["id"]}))
    assert len(rows) == 3


# ---------------------------------------------------------------------------
# Instance 2 — housing_block_aggregate_nightly_capacity_not_overlap_per_se
# ---------------------------------------------------------------------------
def _three_overlapping_confirms_exhaust_a_three_room_block(api):
    """CAT-2026-802 DECLARED with one ACTIVE 3-room block; three mutually overlapping
    FIELD deployments confirmed against it, plus a fourth REQUESTED deployment whose
    nights are disjoint from all three."""
    event = validate_success(
        api.create_event(
            {
                "cat_code": "CAT-2026-802",
                "peril_type": "FLOOD",
                "jurisdiction_state": "LA",
                "event_start_utc": "2026-07-29T00:00:00.000Z",
                "exposure_count": 900,
                "avg_insured_value": 175000,
                "expected_severity_index": 0.1300,
            },
            CM,
        ),
        201,
    )
    validate_success(api.declare_event(event["id"], CM))
    block = validate_success(
        api.create_housing_block(
            {
                "event_id": event["id"],
                "hotel_name": "Bayou Three",
                "city": "Lafayette",
                "rooms_total": 3,
                "nightly_rate": 140,
                "block_start_date": "2026-09-01T00:00:00.000Z",
                "block_end_date": "2026-09-30T00:00:00.000Z",
            },
            DC,
        ),
        201,
    )
    validate_success(api.open_housing_block(block["id"], DC))

    def _field_deployment(full_name, window_start, window_end):
        adjuster = _staff_adjuster(api, full_name, "LA")
        deployment = validate_success(
            api.create_deployment(
                {
                    "event_id": event["id"],
                    "role_type": "FIELD",
                    "window_start_utc": window_start,
                    "window_end_utc": window_end,
                    "adjuster_id": adjuster["id"],
                    "housing_block_id": block["id"],
                    "rooms_reserved": 1,
                },
                DC,
            ),
            201,
        )
        return adjuster, deployment

    _, d_a = _field_deployment("Night A", "2026-09-10T00:00:00.000Z", "2026-09-13T00:00:00.000Z")
    validate_success(api.confirm_deployment(d_a["id"], DC))
    _, d_b = _field_deployment("Night B", "2026-09-11T00:00:00.000Z", "2026-09-15T00:00:00.000Z")
    validate_success(api.confirm_deployment(d_b["id"], DC))
    _, d_c = _field_deployment("Night C", "2026-09-12T00:00:00.000Z", "2026-09-14T00:00:00.000Z")
    validate_success(api.confirm_deployment(d_c["id"], DC))
    adj_d, d_d = _field_deployment(
        "Night D", "2026-09-20T00:00:00.000Z", "2026-09-23T00:00:00.000Z"
    )
    return event, block, (d_a, d_b, d_c), (adj_d, d_d)


def test_overlapping_windows_are_legal_until_the_room_counter_is_exhausted(api):
    """PRD §2.10: "For every housing block, `rooms_total` equals `rooms_available` plus
    `rooms_occupied`, and `rooms_occupied` equals the sum of `rooms_reserved` over the
    deployments drawing on that block whose status is `CONFIRMED` or `ON_SITE`."
    PRD §3.4: "When a deployment confirmation draws the last free room and
    `rooms_available` lands on exactly zero, the block moves `ACTIVE → EXHAUSTED`."
    PRD §3.4: "From that span the system computes `block_night_count`, the number of whole
    days from `block_start_date` up to but not including `block_end_date`."

    Design: Difficulty/resource_temporal_overlap/housing_block_aggregate_nightly_capacity_not_overlap_per_se
    """
    _, block, confirmed, _ = _three_overlapping_confirms_exhaust_a_three_room_block(api)

    for deployment in confirmed:
        assert validate_success(api.get_deployment(deployment["id"], DC))["status"] == "CONFIRMED"
    refreshed = validate_success(api.get_housing_block(block["id"], DC))
    assert refreshed["rooms_total"] == 3
    assert refreshed["rooms_occupied"] == 3
    assert refreshed["rooms_available"] == 0
    assert refreshed["status"] == "EXHAUSTED"
    assert refreshed["block_night_count"] == 29
    rows = validate_success(
        api.list_deployments(DC, params={"housing_block_id": block["id"], "status": "CONFIRMED"})
    )
    assert len(rows) == 3


def test_a_night_disjoint_deployment_is_still_refused_when_no_room_is_free(api):
    """PRD §3.5: "Finally, unless `role_type` is `DESK`, the deployment must name a
    housing block, that block must be `ACTIVE`, and its `rooms_available` must be at least
    the deployment's `rooms_reserved`, failing which the answer is
    `ERR_HOUSING_CAPACITY_EXCEEDED`."
    PRD §2.10: "Deployments in `REQUESTED`, `DEMOBILIZED` or `CANCELLED` hold zero rooms."
    PRD §2.10: "Room counts are integers and are never rounded."

    Design: Difficulty/resource_temporal_overlap/housing_block_aggregate_nightly_capacity_not_overlap_per_se
    """
    _, block, _, (adj_d, d_d) = _three_overlapping_confirms_exhaust_a_three_room_block(api)

    validate_error(
        api.confirm_deployment(d_d["id"], DC), ApiErrorId.ERR_HOUSING_CAPACITY_EXCEEDED, 409
    )

    assert validate_success(api.get_deployment(d_d["id"], DC))["status"] == "REQUESTED"
    assert validate_success(api.get_adjuster(adj_d["id"], DC))["deployment_status"] == "AVAILABLE"
    refreshed = validate_success(api.get_housing_block(block["id"], DC))
    assert refreshed["rooms_occupied"] == 3
    assert refreshed["rooms_available"] == 0


# ---------------------------------------------------------------------------
# Instance 3 — deployment_containment_semantics_inclusive_bounds_one_second_out
# ---------------------------------------------------------------------------
def _deployment_with_two_adjacent_assignments(api):
    """CAT-2026-803 DECLARED; one CONFIRMED DESK deployment 2026-09-04 -> 2026-09-10;
    three identical FAST_TRACK/DESK claims; two SCHEDULED assignments that are exactly
    adjacent to one another, the first flush against the deployment start."""
    event = validate_success(
        api.create_event(
            {
                "cat_code": "CAT-2026-803",
                "peril_type": "HURRICANE",
                "jurisdiction_state": "FL",
                "event_start_utc": "2026-07-31T00:00:00.000Z",
                "exposure_count": 1300,
                "avg_insured_value": 260000,
                "expected_severity_index": 0.1000,
            },
            CM,
        ),
        201,
    )
    validate_success(api.declare_event(event["id"], CM))
    adjuster = validate_success(
        api.create_adjuster(
            {
                "full_name": "Contain Probe",
                "employment_type": "STAFF",
                "home_state": "FL",
                "licensed_states": ["FL"],
                "license_expiry_utc": "2027-08-31T00:00:00.000Z",
                "max_open_claims": 5,
                "daily_rate": 520,
                "per_diem_rate": 0,
                "desk_certified": True,
                "aerial_certified": False,
            },
            DC,
        ),
        201,
    )
    deployment = validate_success(
        api.create_deployment(
            {
                "event_id": event["id"],
                "role_type": "DESK",
                "window_start_utc": "2026-09-04T00:00:00.000Z",
                "window_end_utc": "2026-09-10T00:00:00.000Z",
                "adjuster_id": adjuster["id"],
            },
            DC,
        ),
        201,
    )
    validate_success(api.confirm_deployment(deployment["id"], DC))

    def _claim(policy_number):
        row = validate_success(
            api.create_claim(
                {
                    "policy_number": policy_number,
                    "loss_state": "FL",
                    "loss_date_utc": "2026-07-31T00:00:00.000Z",
                    "reported_loss_amount": 8000,
                    "coverage_lines": [
                        {
                            "coverage_code": "DWELLING",
                            "limit_amount": 400000,
                            "deductible_amount": 1000,
                            "estimated_damage_amount": 9000,
                        }
                    ],
                    "event_id": event["id"],
                    "access_status": "ACCESSIBLE",
                },
                CE,
            ),
            201,
        )
        return validate_success(api.triage_claim(row["id"], CE))

    claim_p, claim_q, claim_r = (_claim("POL-8301"), _claim("POL-8302"), _claim("POL-8303"))

    def _assignment(claim, window_start, window_end):
        return validate_success(
            api.create_inspection_assignment(
                {
                    "claim_id": claim["id"],
                    "mode": "DESK",
                    "window_start_utc": window_start,
                    "window_end_utc": window_end,
                    "adjuster_id": adjuster["id"],
                    "deployment_id": deployment["id"],
                },
                DC,
            ),
            201,
        )

    a_p = _assignment(claim_p, "2026-09-04T00:00:00.000Z", "2026-09-06T00:00:00.000Z")
    a_q = _assignment(claim_q, "2026-09-06T00:00:00.000Z", "2026-09-08T00:00:00.000Z")
    return event, adjuster, deployment, (claim_p, claim_q, claim_r), (a_p, a_q)


def test_flush_lower_bound_and_exact_adjacency_are_both_accepted(api):
    """PRD §3.7: "When a funding deployment is named, the assignment window must be fully
    **contained** in it: the deployment's `window_start_utc` must be at or before the
    assignment's `window_start_utc`, and the assignment's `window_end_utc` must be at or
    before the deployment's `window_end_utc`, otherwise
    `ERR_ASSIGNMENT_OUTSIDE_DEPLOYMENT` (HTTP 422)."
    PRD §3.7: "Because the buffer is zero, exact adjacency is **accepted** — an assignment
    starting at the precise instant another ends is legal, in deliberate contrast to the
    twelve-hour rest buffer that governs deployments — and a genuine overlap is
    `ERR_ASSIGNMENT_WINDOW_CONFLICT`."
    PRD §3.7: "Creation also pulls the claim onto the inspection track: a claim in
    `TRIAGED` moves `TRIAGED → INSPECTION_PENDING`, and a claim in `REOPENED` moves
    `REOPENED → INSPECTION_PENDING`; both branches are driven by the same event — an
    assignment for the claim coming into existence in `SCHEDULED` — and both leave no
    further side effects of their own."

    Design: Difficulty/resource_temporal_overlap/deployment_containment_semantics_inclusive_bounds_one_second_out
    """
    event, adjuster, _, claims, (a_p, a_q) = _deployment_with_two_adjacent_assignments(api)
    claim_p, claim_q, _ = claims

    assert a_p["status"] == "SCHEDULED"
    assert a_q["status"] == "SCHEDULED"
    assert_money_equals(claim_p["severity_score"], 4.30, "severity_score")
    assert_money_equals(claim_p["case_reserve"], 2000.00, "case_reserve")
    assert validate_success(api.get_claim(claim_p["id"], CE))["handling_status"] == (
        "INSPECTION_PENDING"
    )
    assert validate_success(api.get_claim(claim_q["id"], CE))["handling_status"] == (
        "INSPECTION_PENDING"
    )
    assert validate_success(api.get_adjuster(adjuster["id"], DC))["open_assignment_count"] == 2
    assert_money_equals(
        validate_success(api.get_event(event["id"], CM))["case_reserve_total"],
        6000.00,
        "case_reserve_total",
    )


def test_one_second_past_the_deployment_end_breaks_containment(api):
    """PRD §3.7: "When a funding deployment is named, the assignment window must be fully
    **contained** in it: the deployment's `window_start_utc` must be at or before the
    assignment's `window_start_utc`, and the assignment's `window_end_utc` must be at or
    before the deployment's `window_end_utc`, otherwise
    `ERR_ASSIGNMENT_OUTSIDE_DEPLOYMENT` (HTTP 422)."
    PRD §3.7: "The adjuster's `open_assignment_count` must be strictly below their
    `max_open_claims`, evaluated before this new assignment is counted, otherwise
    `ERR_ADJUSTER_AT_CAPACITY` (HTTP 409)."
    PRD §3.7: "Assignment lists may be filtered by `claim_id`, `adjuster_id`,
    `deployment_id`, `status` and `mode`."

    Design: Difficulty/resource_temporal_overlap/deployment_containment_semantics_inclusive_bounds_one_second_out
    """
    _, _, deployment, claims, _ = _deployment_with_two_adjacent_assignments(api)
    _, _, claim_r = claims

    error = validate_error(
        api.create_inspection_assignment(
            {
                "claim_id": claim_r["id"],
                "mode": "DESK",
                "window_start_utc": "2026-09-09T00:00:00.000Z",
                "window_end_utc": "2026-09-10T00:00:01.000Z",
                "adjuster_id": deployment["adjuster_id"],
                "deployment_id": deployment["id"],
            },
            DC,
        ),
        ApiErrorId.ERR_ASSIGNMENT_OUTSIDE_DEPLOYMENT,
        422,
    )

    assert error["error_id"] != ApiErrorId.ERR_ASSIGNMENT_WINDOW_CONFLICT.value
    assert error["error_id"] != ApiErrorId.ERR_ADJUSTER_AT_CAPACITY.value
    assert validate_success(api.get_claim(claim_r["id"], CE))["handling_status"] == "TRIAGED"
    rows = validate_success(
        api.list_inspection_assignments(DC, params={"deployment_id": deployment["id"]})
    )
    assert len(rows) == 2
