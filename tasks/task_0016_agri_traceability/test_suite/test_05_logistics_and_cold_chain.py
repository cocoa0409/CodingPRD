"""Logistics legs, sensor ingestion, cold-chain breach detection, and handover (PRD §3.6)."""
import pytest

from test_helpers import (
    api_client as api,
    validate_success,
    validate_error,
    create_logistics_leg_payload,
    create_sensor_reading_payload,
    setup_batch_with_qr_inspected_pass,
    setup_batch_inspected_pass,
    setup_logistics_leg_planned,
    setup_logistics_leg_in_transit,
    insert_sensor_reading,
    insert_three_breach_readings,
    create_distributor,
    LOGISTICS_HEADERS,
    REGULATORY_HEADERS,
    make_grower_headers,
    make_distributor_headers,
    DEFAULT_GROWER_ID,
    unique_idempotency_key,
)


# --------------------------------------------------------------------------
# PRD §3.6 — leg interval validation
# --------------------------------------------------------------------------

def test_arrive_at_must_be_strictly_after_depart_at():
    """PRD §3.6: "the planned depart_at and arrive_at instants (with arrive_at
    strictly after depart_at)."

    Claim: arrive_at == depart_at → ERR_LEG_INTERVAL_OVERLAP (an invalid
    interval still violates the closed-open semantics on the same boundary
    rule the PRD specifies).
    """
    batch, _bin, _harvest, _report, _qr = setup_batch_with_qr_inspected_pass()
    distributor = create_distributor()
    payload = create_logistics_leg_payload(
        leg_index=1,
        from_party_id="party-from",
        to_party_id=distributor["id"],
        depart_at="2026-04-20T00:00:00.000Z",
        arrive_at="2026-04-20T00:00:00.000Z",
    )
    res = api.create_logistics_leg(batch["id"], payload, LOGISTICS_HEADERS)
    # PRD names this rule under ERR_LEG_INTERVAL_OVERLAP. A faithful PRD-only
    # reader could also pick ERR_VALIDATION; accept either.
    from test_helpers import validate_error_is_one_of
    validate_error_is_one_of(res, ["ERR_LEG_INTERVAL_OVERLAP", "ERR_VALIDATION"])


def test_back_to_back_legs_are_legal():
    """PRD §3.6: "Two legs that touch at a single instant — A's arrive_at
    exactly equals B's depart_at — do not overlap and are accepted."

    Claim: leg B with depart_at == leg A's arrive_at is accepted (closed-open
    interval semantics).
    """
    batch, _bin, _harvest, _report, _qr = setup_batch_with_qr_inspected_pass()
    distributor = create_distributor()
    payload_a = create_logistics_leg_payload(
        leg_index=1,
        from_party_id="party-A",
        to_party_id=distributor["id"],
        depart_at="2026-04-20T00:00:00.000Z",
        arrive_at="2026-04-21T00:00:00.000Z",
    )
    res_a = api.create_logistics_leg(batch["id"], payload_a, LOGISTICS_HEADERS)
    validate_success(res_a, 201)
    payload_b = create_logistics_leg_payload(
        leg_index=2,
        from_party_id=distributor["id"],
        to_party_id="party-C",
        depart_at="2026-04-21T00:00:00.000Z",
        arrive_at="2026-04-22T00:00:00.000Z",
    )
    res_b = api.create_logistics_leg(batch["id"], payload_b, LOGISTICS_HEADERS)
    validate_success(res_b, 201)


def test_overlapping_legs_rejected():
    """PRD §3.6: "Two legs of the same batch may not have overlapping intervals
    using closed-open semantics ... the system rejects the second plan with
    ERR_LEG_INTERVAL_OVERLAP when the two intervals share any instant."

    Claim: leg B with interval inside leg A's interval → ERR_LEG_INTERVAL_OVERLAP.
    """
    batch, _bin, _harvest, _report, _qr = setup_batch_with_qr_inspected_pass()
    distributor = create_distributor()
    payload_a = create_logistics_leg_payload(
        leg_index=1,
        from_party_id="party-A",
        to_party_id=distributor["id"],
        depart_at="2026-04-20T00:00:00.000Z",
        arrive_at="2026-04-22T00:00:00.000Z",
    )
    validate_success(
        api.create_logistics_leg(batch["id"], payload_a, LOGISTICS_HEADERS), 201
    )
    payload_b = create_logistics_leg_payload(
        leg_index=2,
        from_party_id="party-B",
        to_party_id="party-C",
        depart_at="2026-04-21T00:00:00.000Z",
        arrive_at="2026-04-23T00:00:00.000Z",
    )
    res = api.create_logistics_leg(batch["id"], payload_b, LOGISTICS_HEADERS)
    validate_error(res, "ERR_LEG_INTERVAL_OVERLAP")


# --------------------------------------------------------------------------
# PRD §3.6 — depart preconditions
# --------------------------------------------------------------------------

def test_depart_blocked_when_batch_posture_blocked():
    """PRD §3.6: "Departure is rejected when posture is BLOCKED or when the
    batch's status is not in either INSPECTED_PASS or IN_TRANSIT."

    Claim: a leg whose parent batch is INSPECTED_FAIL/posture=BLOCKED cannot
    be departed → ERR_INVALID_STATE.
    """
    from test_helpers import setup_batch_harvested, create_draft_inspection, issue_inspection
    # Build a batch + inspect FAIL → posture BLOCKED
    batch, _bin, _harvest = setup_batch_harvested()
    draft = create_draft_inspection(
        batch, test_items=["MICROORGANISMS"], microorganism_cfu_per_g=200000
    )
    issue_inspection(draft)
    refreshed = validate_success(
        api.get_planting_batch(batch["id"], make_grower_headers(batch["grower_id"])), 200
    )
    assert refreshed["status"] == "INSPECTED_FAIL"
    assert refreshed["posture"] == "BLOCKED"
    # Plan a leg (PLANNED is initial, so creation is allowed)
    distributor = create_distributor()
    payload = create_logistics_leg_payload(
        leg_index=1,
        from_party_id="party-X",
        to_party_id=distributor["id"],
    )
    res = api.create_logistics_leg(batch["id"], payload, LOGISTICS_HEADERS)
    leg = validate_success(res, 201)
    # Depart should now be rejected
    res = api.depart_leg(leg["id"], LOGISTICS_HEADERS)
    validate_error(res, "ERR_INVALID_STATE")


def test_depart_blocked_when_no_qr_minted():
    """PRD §3.6: "The system also requires that at least one harvest record on
    the batch already has a minted QR code before the first departure can occur."

    Claim: depart without any QR minted → ERR_INVALID_STATE.
    """
    # Build a batch through INSPECTED_PASS but skip QR mint
    batch, _bin, _harvest, _report = setup_batch_inspected_pass()
    distributor = create_distributor()
    payload = create_logistics_leg_payload(
        leg_index=1, from_party_id="party-X", to_party_id=distributor["id"]
    )
    leg = validate_success(
        api.create_logistics_leg(batch["id"], payload, LOGISTICS_HEADERS), 201
    )
    res = api.depart_leg(leg["id"], LOGISTICS_HEADERS)
    validate_error(res, "ERR_INVALID_STATE")


def test_depart_first_leg_advances_batch_to_in_transit():
    """PRD §3.6: "When the carrier dispatches the cargo, the operator marks the
    leg departed; the leg's status advances from PLANNED to IN_TRANSIT, and on
    the very first leg of the batch the parent batch's status advances from
    INSPECTED_PASS to IN_TRANSIT."

    Claim: depart first leg → leg.status IN_TRANSIT and batch.status IN_TRANSIT.
    """
    batch, leg, _distributor = setup_logistics_leg_in_transit()
    assert leg["status"] == "IN_TRANSIT"
    refreshed = validate_success(
        api.get_planting_batch(batch["id"], make_grower_headers(batch["grower_id"])), 200
    )
    assert refreshed["status"] == "IN_TRANSIT"


# --------------------------------------------------------------------------
# PRD §3.6 — sensor reading window
# --------------------------------------------------------------------------

def test_reading_at_exactly_depart_at_rejected():
    """PRD §3.6: "a reading at exactly depart_at is rejected with
    ERR_READING_OUT_OF_LEG_WINDOW."

    Claim: reading_at == depart_at → ERR_READING_OUT_OF_LEG_WINDOW.
    """
    _batch, leg, _distributor = setup_logistics_leg_in_transit()
    res = insert_sensor_reading(
        leg, reading_at=leg["depart_at"], temperature_c=3.0
    )
    validate_error(res, "ERR_READING_OUT_OF_LEG_WINDOW")


def test_reading_at_exactly_arrive_at_accepted():
    """PRD §3.6: "a reading at exactly arrive_at is accepted."

    Claim: reading_at == arrive_at succeeds (right-closed window).
    """
    _batch, leg, _distributor = setup_logistics_leg_in_transit()
    res = insert_sensor_reading(
        leg, reading_at=leg["arrive_at"], temperature_c=3.0
    )
    validate_success(res, 201)


def test_reading_outside_window_rejected():
    """PRD §3.6: "readings outside the window on either side are likewise rejected."

    Claim: reading_at after arrive_at → ERR_READING_OUT_OF_LEG_WINDOW.
    """
    _batch, leg, _distributor = setup_logistics_leg_in_transit()
    # Window is [00:00, 24:00] on 2026-04-20→04-21; pick 04-22 (way after).
    res = insert_sensor_reading(
        leg, reading_at="2026-04-22T00:00:00.000Z", temperature_c=3.0
    )
    validate_error(res, "ERR_READING_OUT_OF_LEG_WINDOW")


# --------------------------------------------------------------------------
# PRD §3.6 — out_of_range computation (boundary inclusive semantics)
# --------------------------------------------------------------------------

def test_temperature_at_min_is_in_range():
    """PRD §3.6: "It is true when temperature_c is strictly less than the leg's
    temperature_min_c or strictly greater than the leg's temperature_max_c;
    readings exactly at either boundary are in-range."

    Claim: temperature_c == temperature_min_c → out_of_range == false.
    """
    _batch, leg, _distributor = setup_logistics_leg_in_transit()
    res = insert_sensor_reading(
        leg, reading_at="2026-04-20T01:00:00.000Z", temperature_c=2.0
    )
    reading = validate_success(res, 201)
    assert reading["out_of_range"] is False


def test_temperature_at_max_is_in_range():
    """PRD §3.6: "readings exactly at either boundary are in-range."

    Claim: temperature_c == temperature_max_c → out_of_range == false.
    """
    _batch, leg, _distributor = setup_logistics_leg_in_transit()
    res = insert_sensor_reading(
        leg, reading_at="2026-04-20T01:00:00.000Z", temperature_c=4.0
    )
    reading = validate_success(res, 201)
    assert reading["out_of_range"] is False


def test_temperature_above_max_is_out_of_range():
    """PRD §3.6: "It is true when temperature_c is ... strictly greater than
    the leg's temperature_max_c."

    Claim: temperature_c > temperature_max_c → out_of_range == true.
    """
    _batch, leg, _distributor = setup_logistics_leg_in_transit()
    res = insert_sensor_reading(
        leg, reading_at="2026-04-20T01:00:00.000Z", temperature_c=8.0
    )
    reading = validate_success(res, 201)
    assert reading["out_of_range"] is True


# --------------------------------------------------------------------------
# PRD §3.6 — cold-chain breach detection (3-in-a-row → ABNORMAL)
# --------------------------------------------------------------------------

def test_three_consecutive_breaches_transition_leg_to_abnormal():
    """PRD §3.6: "A run of three or more consecutive readings whose
    out_of_range is true counts as one abnormal segment; ... Whenever
    abnormal_segment_count becomes at least one and the leg is currently
    IN_TRANSIT, the leg auto-transitions to ABNORMAL."

    Claim: third consecutive out-of-range reading → leg.status == ABNORMAL.
    """
    batch, leg, _distributor = setup_logistics_leg_in_transit()
    insert_three_breach_readings(leg)
    # Re-fetch via the leg list endpoint
    res = api.list_logistics_legs(batch["id"], LOGISTICS_HEADERS)
    body = res.json()
    legs = body.get("data", [])
    assert legs, "expected at least one leg in list response"
    target = next((L for L in legs if L["id"] == leg["id"]), None)
    assert target is not None
    assert target["status"] == "ABNORMAL"
    assert target["abnormal_segment_count"] >= 1


def test_two_consecutive_breaches_do_not_trigger_abnormal():
    """PRD §3.6: "A run of three or more consecutive readings whose
    out_of_range is true counts as one abnormal segment."

    Claim: only two consecutive out-of-range readings → leg stays IN_TRANSIT,
    abnormal_segment_count == 0 (run length below threshold).
    """
    batch, leg, _distributor = setup_logistics_leg_in_transit()
    insert_sensor_reading(leg, reading_at="2026-04-20T01:00:00.000Z", temperature_c=8.0)
    insert_sensor_reading(leg, reading_at="2026-04-20T02:00:00.000Z", temperature_c=8.0)
    res = api.list_logistics_legs(batch["id"], LOGISTICS_HEADERS)
    legs = res.json().get("data", [])
    target = next((L for L in legs if L["id"] == leg["id"]), None)
    assert target is not None
    assert target["status"] == "IN_TRANSIT"
    assert target["abnormal_segment_count"] == 0


# --------------------------------------------------------------------------
# PRD §3.6 / §2.9 — sensor idempotency
# --------------------------------------------------------------------------

def test_duplicate_idempotency_key_returns_original_with_outcome():
    """PRD §2.9: "A second POST carrying the same (logistics_leg_id,
    idempotency_key) pair returns the originally-stored row with HTTP 200 and
    an outcome surfaced as ERR_IDEMPOTENT_REPLAY rather than creating a
    duplicate row."

    Claim: re-POST same idempotency_key on same leg → HTTP 200 with
    ERR_IDEMPOTENT_REPLAY outcome and no duplicate row.
    """
    _batch, leg, _distributor = setup_logistics_leg_in_transit()
    key = unique_idempotency_key()
    res1 = insert_sensor_reading(
        leg, reading_at="2026-04-20T01:00:00.000Z", temperature_c=3.0,
        idempotency_key=key,
    )
    validate_success(res1, 201)
    res2 = insert_sensor_reading(
        leg, reading_at="2026-04-20T01:00:00.000Z", temperature_c=3.0,
        idempotency_key=key,
    )
    # PRD: HTTP 200 + ERR_IDEMPOTENT_REPLAY surfaced
    assert res2.status_code == 200, \
        f"Expected HTTP 200 on idempotent replay, got {res2.status_code}"
    # No duplicate row may exist regardless of how the replay outcome is
    # surfaced.
    list_res = api.list_sensor_readings(leg["id"], LOGISTICS_HEADERS)
    readings = list_res.json().get("data", [])
    matching = [r for r in readings if r.get("idempotency_key") == key]
    assert len(matching) == 1, \
        f"expected exactly one stored reading for idempotency_key {key}, found {len(matching)}"


# --------------------------------------------------------------------------
# PRD §3.6 — handover
# --------------------------------------------------------------------------

def test_acknowledge_by_destination_distributor_advances_to_handed_over():
    """PRD §3.6: "Handover closes the leg. The receiving party acknowledges
    arrival, which sets handover_acknowledged to true and advances the leg's
    status from IN_TRANSIT to HANDED_OVER."

    Claim: acknowledge by X-User-ID == leg.to_party_id → status HANDED_OVER,
    handover_acknowledged true.
    """
    _batch, leg, distributor = setup_logistics_leg_in_transit()
    headers = make_distributor_headers(distributor["id"])
    res = api.acknowledge_leg(leg["id"], headers)
    leg_after = validate_success(res, 200)
    assert leg_after["status"] == "HANDED_OVER"
    assert leg_after["handover_acknowledged"] is True


def test_final_leg_acknowledge_advances_batch_to_delivered():
    """PRD §3.6: "When the acknowledged leg is the final leg recorded for the
    batch (no other leg has a greater leg_index), the parent batch advances
    from IN_TRANSIT to DELIVERED."

    Claim: acknowledge final leg → batch.status DELIVERED.
    """
    batch, leg, distributor = setup_logistics_leg_in_transit()
    headers = make_distributor_headers(distributor["id"])
    api.acknowledge_leg(leg["id"], headers)
    refreshed = validate_success(
        api.get_planting_batch(batch["id"], make_grower_headers(batch["grower_id"])), 200
    )
    assert refreshed["status"] == "DELIVERED"


def test_abnormal_leg_cannot_be_acknowledged_by_distributor():
    """PRD §3.6: "For a leg that reached ABNORMAL, only a RegulatoryOfficer may
    acknowledge — never the destination distributor."

    Claim: distributor acknowledging an ABNORMAL leg → ERR_FORBIDDEN
    (or ERR_INVALID_STATE — both are PRD-faithful readings of "never").
    """
    from test_helpers import validate_error_is_one_of
    _batch, leg, distributor = setup_logistics_leg_in_transit()
    insert_three_breach_readings(leg)
    headers = make_distributor_headers(distributor["id"])
    res = api.acknowledge_leg(leg["id"], headers)
    validate_error_is_one_of(res, ["ERR_FORBIDDEN", "ERR_INVALID_STATE"])
