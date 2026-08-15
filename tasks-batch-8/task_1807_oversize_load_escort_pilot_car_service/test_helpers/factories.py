"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "CARRIER_NAME": "Test Carrier",
    "CREDIT_LIMIT_CENTS": 10_000_000,
    "OPERATOR_NAME": "Test Rider",
    "LOAD_DESCRIPTION": "Test load",
    "WIDTH_INCHES": 170,
    "HEIGHT_INCHES": 150,
    "LENGTH_INCHES": 600,
    "GROSS_WEIGHT_LBS": 150000,
    "DISTANCE_MILES": 120,
    "MAP_MIN_CLEARANCE_INCHES": 180,
}


def create_carrier_payload(**overrides) -> dict:
    defaults = {
        "carrier_name": DEFAULTS["CARRIER_NAME"],
        "credit_limit_cents": DEFAULTS["CREDIT_LIMIT_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_escort_payload(**overrides) -> dict:
    defaults = {
        "operator_name": DEFAULTS["OPERATOR_NAME"],
        "certified_state_codes": ["TX"],
    }
    defaults.update(overrides)
    return defaults


def leg_spec(
    state_code="TX",
    sequence_index=0,
    distance_miles=DEFAULTS["DISTANCE_MILES"],
    planned_entry_at="2026-08-10T09:00:00Z",
    planned_exit_at="2026-08-10T13:00:00Z",
    map_min_clearance_inches=DEFAULTS["MAP_MIN_CLEARANCE_INCHES"],
    **overrides,
) -> dict:
    spec = {
        "state_code": state_code,
        "sequence_index": sequence_index,
        "distance_miles": distance_miles,
        "planned_entry_at": planned_entry_at,
        "planned_exit_at": planned_exit_at,
        "map_min_clearance_inches": map_min_clearance_inches,
    }
    spec.update(overrides)
    return spec


def create_job_payload(carrier_id, legs=None, **overrides) -> dict:
    defaults = {
        "carrier_id": carrier_id,
        "load_description": DEFAULTS["LOAD_DESCRIPTION"],
        "width_inches": DEFAULTS["WIDTH_INCHES"],
        "height_inches": DEFAULTS["HEIGHT_INCHES"],
        "length_inches": DEFAULTS["LENGTH_INCHES"],
        "gross_weight_lbs": DEFAULTS["GROSS_WEIGHT_LBS"],
        "window_start_at": "2026-08-10T09:00:00Z",
        "window_end_at": "2026-08-10T13:00:00Z",
        "legs": legs if legs is not None else [leg_spec()],
    }
    defaults.update(overrides)
    return defaults


def create_permit_payload(
    permit_number="TX-P-1",
    valid_from="2026-08-09T00:00:00Z",
    valid_until="2026-08-12T00:00:00Z",
    **overrides,
) -> dict:
    payload = {
        "permit_number": permit_number,
        "valid_from": valid_from,
        "valid_until": valid_until,
    }
    payload.update(overrides)
    return payload


def submit_survey_payload(surveyed_min_clearance_inches, obstructions=None) -> dict:
    payload = {"surveyed_min_clearance_inches": surveyed_min_clearance_inches}
    if obstructions is not None:
        payload["obstructions"] = obstructions
    return payload


def obstruction_spec(
    milepost=12.5,
    obstruction_type="BRIDGE",
    measured_clearance_inches=175,
    disposition="REQUIRES_REROUTE",
    **overrides,
) -> dict:
    spec = {
        "milepost": milepost,
        "obstruction_type": obstruction_type,
        "measured_clearance_inches": measured_clearance_inches,
        "disposition": disposition,
    }
    spec.update(overrides)
    return spec


def decide_survey_payload(expected_leg_version, outcome="ACCEPTED", **overrides) -> dict:
    payload = {"expected_leg_version": expected_leg_version, "outcome": outcome}
    payload.update(overrides)
    return payload


def create_assignment_payload(position="REAR", escort_id=None) -> dict:
    payload = {"position": position}
    if escort_id is not None:
        payload["escort_id"] = escort_id
    return payload


def create_delay_event_payload(cause="CARRIER_DELAY", started_at="2026-08-10T10:00:00Z", **overrides) -> dict:
    payload = {"cause": cause, "started_at": started_at}
    payload.update(overrides)
    return payload


def create_incident_payload(
    incident_type="PROPERTY_DAMAGE",
    description="Incident under test",
    claimed_amount_cents=100000,
    assignment_id=None,
    **overrides,
) -> dict:
    payload = {
        "incident_type": incident_type,
        "description": description,
        "claimed_amount_cents": claimed_amount_cents,
    }
    if assignment_id is not None:
        payload["assignment_id"] = assignment_id
    payload.update(overrides)
    return payload


def assess_incident_payload(escort_fault_share_pct) -> dict:
    return {"escort_fault_share_pct": escort_fault_share_pct}


def dispute_invoice_payload(dispute_reason="Disputed amount") -> dict:
    return {"dispute_reason": dispute_reason}


def adjust_invoice_payload(adjustment_delta_cents, adjustment_note="Adjustment") -> dict:
    return {
        "adjustment_delta_cents": adjustment_delta_cents,
        "adjustment_note": adjustment_note,
    }


def record_payment_payload(amount_cents) -> dict:
    return {"amount_cents": amount_cents}


def amend_job_payload(expected_job_version, **field_overrides) -> dict:
    payload = {"expected_job_version": expected_job_version}
    payload.update(field_overrides)
    return payload


def clock_payload(to_iso8601) -> dict:
    return {"to_iso8601": to_iso8601}
