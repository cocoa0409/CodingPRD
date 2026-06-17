"""Payload factories — one per writable entity, input fields only.

Each factory provides PRD-valid defaults and accepts **overrides so a test can
control the field under assertion. Optional fields (rush, license_*, deed_*,
encumbrance_count, notes) are omitted from defaults unless a test supplies them.
"""
import itertools

_counter = itertools.count(1)


def _seq() -> int:
    return next(_counter)


# ─── CrewMember ───────────────────────────────────────
def create_crew_member_payload(role_type="COORDINATOR", **overrides) -> dict:
    payload = {
        "full_name": overrides.pop("full_name", f"Crew {role_type} {_seq()}"),
        "role_type": role_type,
    }
    payload.update(overrides)
    return payload


def create_pls_payload(**overrides) -> dict:
    """A PLS crew member with a non-expired license by default."""
    payload = {
        "full_name": overrides.pop("full_name", f"PLS {_seq()}"),
        "role_type": "PLS",
        "license_number": overrides.pop("license_number", f"L-{_seq()}"),
        "license_state": overrides.pop("license_state", "CA"),
        "license_expires_on": overrides.pop("license_expires_on", "2030-01-01T00:00:00.000Z"),
    }
    payload.update(overrides)
    return payload


# ─── Instrument ───────────────────────────────────────
def create_instrument_payload(**overrides) -> dict:
    payload = {
        "asset_tag": overrides.pop("asset_tag", f"TAG-{_seq()}"),
        "instrument_type": overrides.pop("instrument_type", "TOTAL_STATION"),
        "calibration_due_on": overrides.pop("calibration_due_on", "2027-01-01T00:00:00.000Z"),
    }
    payload.update(overrides)
    return payload


# ─── SurveyOrder ──────────────────────────────────────
def create_survey_order_payload(**overrides) -> dict:
    payload = {
        "client_name": overrides.pop("client_name", f"Client {_seq()}"),
        "survey_type": overrides.pop("survey_type", "BOUNDARY"),
        "parcel_apn": overrides.pop("parcel_apn", f"APN-{_seq()}"),
        "county_fips": overrides.pop("county_fips", "06037"),
        "acreage": overrides.pop("acreage", 3),
        "requested_due_date": overrides.pop("requested_due_date", "2026-08-01T00:00:00.000Z"),
    }
    payload.update(overrides)
    return payload


# ─── ResearchPacket ───────────────────────────────────
def create_research_packet_payload(order_id, assigned_researcher_id, **overrides) -> dict:
    payload = {
        "order_id": order_id,
        "assigned_researcher_id": assigned_researcher_id,
    }
    payload.update(overrides)
    return payload


# ─── FieldAssignment ──────────────────────────────────
def create_field_assignment_payload(order_id, crew_member_id, scheduled_start,
                                     scheduled_end, **overrides) -> dict:
    payload = {
        "order_id": order_id,
        "crew_member_id": crew_member_id,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
    }
    payload.update(overrides)
    return payload


# ─── InstrumentReservation ────────────────────────────
def create_instrument_reservation_payload(assignment_id, instrument_id, **overrides) -> dict:
    payload = {
        "assignment_id": assignment_id,
        "instrument_id": instrument_id,
    }
    payload.update(overrides)
    return payload


# ─── DataSet ──────────────────────────────────────────
def create_data_set_payload(order_id, assignment_id, recorded_by_id,
                            point_count=50, closure_error_ppm=20, **overrides) -> dict:
    payload = {
        "order_id": order_id,
        "assignment_id": assignment_id,
        "recorded_by_id": recorded_by_id,
        "point_count": point_count,
        "closure_error_ppm": closure_error_ppm,
    }
    payload.update(overrides)
    return payload


# ─── PlatDrawing ──────────────────────────────────────
def create_plat_drawing_payload(order_id, dataset_id, drafted_by_id, **overrides) -> dict:
    payload = {
        "order_id": order_id,
        "dataset_id": dataset_id,
        "drafted_by_id": drafted_by_id,
    }
    payload.update(overrides)
    return payload


def seal_payload(sealed_by_id, expected_order_version, **overrides) -> dict:
    payload = {
        "sealed_by_id": sealed_by_id,
        "expected_order_version": expected_order_version,
    }
    payload.update(overrides)
    return payload


# ─── RevisionRequest ──────────────────────────────────
def create_revision_request_payload(plat_id, reason="CLIENT_CHANGE", **overrides) -> dict:
    payload = {
        "plat_id": plat_id,
        "reason": reason,
    }
    payload.update(overrides)
    return payload


# ─── Deliverable ──────────────────────────────────────
def create_deliverable_payload(order_id, plat_id, format="PDF", **overrides) -> dict:
    payload = {
        "order_id": order_id,
        "plat_id": plat_id,
        "format": format,
    }
    payload.update(overrides)
    return payload


# ─── Invoice ──────────────────────────────────────────
def create_invoice_payload(order_id, issued_by_id, **overrides) -> dict:
    payload = {
        "order_id": order_id,
        "issued_by_id": issued_by_id,
    }
    payload.update(overrides)
    return payload


def issue_invoice_payload(expected_order_version, **overrides) -> dict:
    payload = {"expected_order_version": expected_order_version}
    payload.update(overrides)
    return payload


def payment_payload(amount_cents, **overrides) -> dict:
    payload = {"amount_cents": amount_cents}
    payload.update(overrides)
    return payload
