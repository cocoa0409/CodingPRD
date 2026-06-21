"""Temporal-overlap geometry: HANGAR tow-buffer (closed) vs RAMP/TIE_DOWN half-open
adjacency, and the ramp-slot revoke/re-request cycle (PRD §3.4, §3.9).

Difficulty queue (A) instances:
  - resource_temporal_overlap / hangar_tow_buffer_blocks_adjacency
  - resource_temporal_overlap / ramp_slot_half_open_allows_adjacency
  - non_linear_state_machine / ramp_slot_revoke_re_request_cycle
"""
from test_helpers import (
    api_client as api,
    get_success_data,
    validate_error,
    validate_success,
    setup_operator_aircraft_contract,
    setup_on_ground_visit,
    setup_revoked_slot,
    create_parking_assignment_payload,
    create_ramp_slot_payload,
    occupy_payload,
    make_operator_headers,
    TEST_USERS,
)

OPS = TEST_USERS["ops_dispatcher_headers"]


def test_hangar_tow_buffer_blocks_adjacent_window():
    """PRD §3.4: "For a `HANGAR` spot, the assignment's interval is widened by a
    30-minute tow buffer at each side, and if that buffered window collides with any
    already-`OCCUPIED` assignment's window on the same spot (a closed, buffer-inclusive
    overlap), the request is rejected with `ERR_SPOT_TOW_BUFFER_CONFLICT` (HTTP 409)."

    On a HANGAR spot, [11:00,12:00) starting exactly when [10:00,11:00) ends is rejected
    because the 30-minute tow buffer is violated — adjacency is NOT allowed on hangars.

    Design: Difficulty/resource_temporal_overlap/hangar_tow_buffer_blocks_adjacency
    """
    operator, aircraft, _contract = setup_operator_aircraft_contract()
    spot = get_success_data(api.create_parking_spot(
        {"label": "H-1", "spot_type": "HANGAR", "max_weight_class": "HEAVY"}, OPS))

    v1 = setup_on_ground_visit(operator["id"], aircraft["id"])
    pa1 = get_success_data(api.create_parking_assignment(
        create_parking_assignment_payload(v1["id"], spot["id"],
                                          occupy_start_utc="2026-06-14T10:00:00.000Z",
                                          occupy_end_utc="2026-06-14T11:00:00.000Z"), OPS))
    get_success_data(api.occupy_parking_assignment(pa1["id"], occupy_payload(pa1["version"]), OPS))

    v2 = setup_on_ground_visit(operator["id"], aircraft["id"],
                               visit_overrides={"arrival_utc": "2026-06-14T09:00:00.000Z",
                                                "departure_utc": "2026-06-15T09:00:00.000Z"})
    pa2 = get_success_data(api.create_parking_assignment(
        create_parking_assignment_payload(v2["id"], spot["id"],
                                          occupy_start_utc="2026-06-14T11:00:00.000Z",
                                          occupy_end_utc="2026-06-14T12:00:00.000Z"), OPS))
    res = api.occupy_parking_assignment(pa2["id"], occupy_payload(pa2["version"]), OPS)
    validate_error(res, "ERR_SPOT_TOW_BUFFER_CONFLICT")
    pa2_after = get_success_data(api.get_parking_assignment(pa2["id"], OPS))
    assert pa2_after["status"] == "HELD", "rejected occupy must leave assignment HELD"


def test_ramp_slot_half_open_allows_adjacency_rejects_true_overlap():
    """PRD §3.9: "only when no other `APPROVED` slot on the same `pad_id`
    half-open-overlaps this window — adjacency, where one window ends exactly as another
    begins, is allowed, but a true overlap is rejected with `ERR_SLOT_OVERLAP`
    (HTTP 409)."

    On a RAMP pad with an APPROVED [10:00,11:00) slot: the adjacent [11:00,12:00) slot
    approves, while the overlapping [10:30,11:30) slot is rejected with ERR_SLOT_OVERLAP.

    Design: Difficulty/resource_temporal_overlap/ramp_slot_half_open_allows_adjacency
    """
    operator, aircraft, _contract = setup_operator_aircraft_contract()
    pad = get_success_data(api.create_parking_spot(
        {"label": "PAD-9", "spot_type": "RAMP", "max_weight_class": "HEAVY"}, OPS))
    visit = get_success_data(api.create_service_visit(
        {"operator_id": operator["id"], "aircraft_id": aircraft["id"],
         "arrival_utc": "2026-06-14T08:00:00.000Z", "departure_utc": "2026-06-15T08:00:00.000Z"}, OPS))

    s1 = get_success_data(api.create_ramp_slot(
        create_ramp_slot_payload(visit["id"], pad["id"],
                                 "2026-06-14T10:00:00.000Z", "2026-06-14T11:00:00.000Z"), OPS))
    get_success_data(api.approve_ramp_slot(s1["id"], OPS))

    s2 = get_success_data(api.create_ramp_slot(
        create_ramp_slot_payload(visit["id"], pad["id"],
                                 "2026-06-14T11:00:00.000Z", "2026-06-14T12:00:00.000Z"), OPS))
    s3 = get_success_data(api.create_ramp_slot(
        create_ramp_slot_payload(visit["id"], pad["id"],
                                 "2026-06-14T10:30:00.000Z", "2026-06-14T11:30:00.000Z"), OPS))

    approved2 = validate_success(api.approve_ramp_slot(s2["id"], OPS), 200)
    assert approved2["status"] == "APPROVED", "adjacent window must be approvable"

    res3 = api.approve_ramp_slot(s3["id"], OPS)
    validate_error(res3, "ERR_SLOT_OVERLAP")
    s3_after = get_success_data(api.get_ramp_slot(s3["id"], OPS))
    assert s3_after["status"] == "REQUESTED", "overlapping slot must stay REQUESTED"


def test_ramp_slot_revoke_then_re_request_cycle():
    """PRD §3.9: "**Revoking** an approved slot moves it `APPROVED → REVOKED` and frees
    the pad's approved window so it no longer blocks overlap checks. A revoked slot can be
    **re-requested** — moving it `REVOKED → REQUESTED` — by the `Operator` (or an
    `OpsDispatcher`), but only while the parent visit is not `DEPARTED` or `CANCELLED`"

    A slot traverses REQUESTED → APPROVED → REVOKED → REQUESTED, returning to a
    non-terminal state already visited (a true cyclic shape).

    Design: Difficulty/non_linear_state_machine/ramp_slot_revoke_re_request_cycle
    """
    operator, aircraft, _contract = setup_operator_aircraft_contract()
    visit, pad, slot = setup_revoked_slot(operator["id"], aircraft["id"])
    assert slot["status"] == "REVOKED"
    # Operator owns the visit; re-request is the ownership-gated Operator path.
    re_requested = validate_success(
        api.re_request_ramp_slot(slot["id"], make_operator_headers(operator["id"])), 200)
    assert re_requested["status"] == "REQUESTED", (
        "revoked slot should cycle back to REQUESTED on re-request"
    )
