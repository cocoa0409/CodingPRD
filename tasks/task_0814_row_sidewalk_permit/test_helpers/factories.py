"""Payload factories — one per entity, input fields only."""


def create_applicant_payload(**overrides) -> dict:
    payload = {
        "company_name": "Acme",
        "license_number": "L1",
        "contact_email": "a@x.com",
    }
    payload.update(overrides)
    return payload


def create_street_segment_payload(**overrides) -> dict:
    payload = {
        "block_label": "Main 100",
        "zone_class": "COMMERCIAL",
        "last_repaved_date": "2020-01-01",
        "roadway_lane_count": 2,
    }
    payload.update(overrides)
    return payload


def create_sidewalk_span_payload(**overrides) -> dict:
    payload = {
        "block_label": "Main 100 N",
        "side": "NORTH",
        "width_ft": 12,
    }
    payload.update(overrides)
    return payload


def create_permit_payload(applicant_id, street_segment_id, **overrides) -> dict:
    payload = {
        "applicant_id": applicant_id,
        "street_segment_id": street_segment_id,
        "primary_obstruction_type": "LANE",
        "requested_start_date": "2026-04-01",
        "requested_end_date": "2026-04-11",
    }
    payload.update(overrides)
    return payload


def create_traffic_control_plan_payload(**overrides) -> dict:
    payload = {
        "device_list": ["CONES"],
        "requires_flaggers": False,
        "setback_ft": 5,
    }
    payload.update(overrides)
    return payload


def create_bond_payload(posted_cents, expected_permit_version, **overrides) -> dict:
    payload = {
        "posted_cents": posted_cents,
        "expected_permit_version": expected_permit_version,
    }
    payload.update(overrides)
    return payload


def create_lane_closure_payload(street_segment_id, **overrides) -> dict:
    payload = {
        "street_segment_id": street_segment_id,
        "obstruction_type": "LANE",
        "start_date": "2026-04-01",
        "end_date": "2026-04-11",
    }
    payload.update(overrides)
    return payload


def create_sidewalk_obstruction_payload(sidewalk_span_id, **overrides) -> dict:
    payload = {
        "sidewalk_span_id": sidewalk_span_id,
        "start_date": "2026-05-01",
        "end_date": "2026-05-10",
        "maintained_clearance_ft": 5.0,
    }
    payload.update(overrides)
    return payload


def create_encroachment_agreement_payload(**overrides) -> dict:
    payload = {
        "term_months": 24,
        "proposed_fee_cents": 120000,
    }
    payload.update(overrides)
    return payload


def create_violation_payload(**overrides) -> dict:
    payload = {
        "violation_type": "TCP_VIOLATION",
    }
    payload.update(overrides)
    return payload
