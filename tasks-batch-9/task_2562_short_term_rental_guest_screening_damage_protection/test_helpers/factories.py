"""Payload builders for the rows the tests keep needing.

Every builder returns a plain dict of request fields, so a test may override any
one of them inline. Nothing here talks to the API; the fixtures do that.
"""


def jurisdiction_rule_payload(jurisdiction_code="US-CA-SFO", min_stay_nights=2,
                              max_occupancy_cap=8, events_prohibited=False,
                              registration_required=False, indoor_camera_allowed=True,
                              indoor_audio_allowed=False, sensor_notice_required=True,
                              noise_threshold_db=70, **overrides):
    """A permissive city rule set: two-night minimum, notice required, 70 dB."""
    payload = {
        "jurisdiction_code": jurisdiction_code,
        "min_stay_nights": min_stay_nights,
        "max_occupancy_cap": max_occupancy_cap,
        "events_prohibited": events_prohibited,
        "registration_required": registration_required,
        "indoor_camera_allowed": indoor_camera_allowed,
        "indoor_audio_allowed": indoor_audio_allowed,
        "sensor_notice_required": sensor_notice_required,
        "noise_threshold_db": noise_threshold_db,
    }
    payload.update(overrides)
    return payload


def host_payload(legal_name="Bayview Stays LLC", email="host1@stays.test", **overrides):
    payload = {"legal_name": legal_name, "email": email}
    payload.update(overrides)
    return payload


def guest_payload(full_name="Ada Fenwick", email="ada@guest.test", country_code="US",
                  **overrides):
    payload = {"full_name": full_name, "email": email, "country_code": country_code}
    payload.update(overrides)
    return payload


def waiver_property_payload(host_id, jurisdiction_rule_id, **overrides):
    """The canonical WAIVER listing: 30000 a night, 3000 nightly waiver fee."""
    payload = {
        "host_id": host_id,
        "jurisdiction_rule_id": jurisdiction_rule_id,
        "address_line": "14 Harbor Way",
        "city": "San Francisco",
        "max_occupancy": 6,
        "bedrooms": 3,
        "nightly_rate_cents": 30000,
        "protection_product": "WAIVER",
        "deposit_amount_cents": 0,
        "waiver_nightly_fee_cents": 3000,
        "claim_ceiling_cents": 500000,
        "event_policy": "EVENTS_ALLOWED",
        "turnover_buffer_nights": 0,
    }
    payload.update(overrides)
    return payload


def deposit_property_payload(host_id, jurisdiction_rule_id, **overrides):
    """The canonical DEPOSIT listing: 20000 a night, 50000 deposit, one buffer night."""
    payload = {
        "host_id": host_id,
        "jurisdiction_rule_id": jurisdiction_rule_id,
        "address_line": "8 Beach Street",
        "city": "San Francisco",
        "max_occupancy": 4,
        "bedrooms": 2,
        "nightly_rate_cents": 20000,
        "protection_product": "DEPOSIT",
        "deposit_amount_cents": 50000,
        "waiver_nightly_fee_cents": 0,
        "claim_ceiling_cents": 400000,
        "event_policy": "EVENTS_PROHIBITED",
        "turnover_buffer_nights": 1,
    }
    payload.update(overrides)
    return payload


def monitoring_device_payload(property_id, device_type="NOISE_DECIBEL",
                              placement_zone="EXTERIOR", records_audio=False,
                              guest_disclosure_text="A decibel meter monitors the "
                                                    "exterior deck and records no audio.",
                              **overrides):
    payload = {
        "property_id": property_id,
        "device_type": device_type,
        "placement_zone": placement_zone,
        "records_audio": records_audio,
        "guest_disclosure_text": guest_disclosure_text,
    }
    payload.update(overrides)
    return payload


def government_id_payload(guest_id, document_ref="gov-doc-1",
                          expires_on="2030-01-01T00:00:00Z", issuing_country="US",
                          **overrides):
    payload = {
        "guest_id": guest_id,
        "doc_type": "GOVERNMENT_ID",
        "issuing_country": issuing_country,
        "document_ref": document_ref,
        "expires_on": expires_on,
    }
    payload.update(overrides)
    return payload


def selfie_payload(guest_id, document_ref="selfie-doc-1",
                   expires_on="2030-01-01T00:00:00Z", issuing_country="US", **overrides):
    payload = {
        "guest_id": guest_id,
        "doc_type": "SELFIE",
        "issuing_country": issuing_country,
        "document_ref": document_ref,
        "expires_on": expires_on,
    }
    payload.update(overrides)
    return payload


def reservation_payload(guest_id, property_id, expected_property_version,
                        check_in="2026-08-10", check_out="2026-08-13", guest_count=2,
                        event_declared=False, **overrides):
    payload = {
        "guest_id": guest_id,
        "property_id": property_id,
        "check_in": check_in,
        "check_out": check_out,
        "guest_count": guest_count,
        "event_declared": event_declared,
        "expected_property_version": expected_property_version,
    }
    payload.update(overrides)
    return payload


def incident_payload(reservation_id, incident_type="PROPERTY_DAMAGE", severity="MEDIUM",
                     source="HOST_REPORT", detected_at="2026-08-11T01:00:00Z",
                     description="A guest broke the living-room window during the stay.",
                     **overrides):
    payload = {
        "reservation_id": reservation_id,
        "incident_type": incident_type,
        "severity": severity,
        "source": source,
        "detected_at": detected_at,
        "description": description,
    }
    payload.update(overrides)
    return payload


def noise_incident_payload(reservation_id, decibel_reading=82.0,
                           source="NEIGHBOR_COMPLAINT",
                           detected_at="2026-08-11T01:00:00Z", **overrides):
    payload = incident_payload(
        reservation_id,
        incident_type="NOISE_VIOLATION",
        severity="MEDIUM",
        source=source,
        detected_at=detected_at,
        description="Sustained noise from the listing well past midnight.",
        decibel_reading=decibel_reading,
    )
    payload.update(overrides)
    return payload


def damage_claim_payload(reservation_id, claimed_amount_cents,
                         expected_reservation_version,
                         description="Replacement of the broken living-room window.",
                         **overrides):
    payload = {
        "reservation_id": reservation_id,
        "claimed_amount_cents": claimed_amount_cents,
        "description": description,
        "expected_reservation_version": expected_reservation_version,
    }
    payload.update(overrides)
    return payload


def photo_evidence_payload(claim_id, file_ref, captured_at="2026-08-13T09:00:00Z",
                           **overrides):
    payload = {
        "claim_id": claim_id,
        "evidence_type": "PHOTO",
        "captured_at": captured_at,
        "file_ref": file_ref,
    }
    payload.update(overrides)
    return payload


def receipt_evidence_payload(claim_id, file_ref, amount_cents,
                             captured_at="2026-08-13T09:00:00Z", **overrides):
    payload = {
        "claim_id": claim_id,
        "evidence_type": "RECEIPT",
        "amount_cents": amount_cents,
        "captured_at": captured_at,
        "file_ref": file_ref,
    }
    payload.update(overrides)
    return payload


def police_report_evidence_payload(claim_id, file_ref,
                                   captured_at="2026-08-13T09:00:00Z", **overrides):
    payload = {
        "claim_id": claim_id,
        "evidence_type": "POLICE_REPORT",
        "captured_at": captured_at,
        "file_ref": file_ref,
    }
    payload.update(overrides)
    return payload


def coverage_layer_payload(source, layer_order, limit_cents, deductible_cents,
                           coverage_pct, scope, property_id=None, **overrides):
    payload = {
        "source": source,
        "layer_order": layer_order,
        "limit_cents": limit_cents,
        "deductible_cents": deductible_cents,
        "coverage_pct": coverage_pct,
        "scope": scope,
    }
    if property_id is not None:
        payload["property_id"] = property_id
    payload.update(overrides)
    return payload


def blocklist_entry_payload(guest_id, scope, reason_code, expected_guest_version,
                            property_id=None, host_id=None, supersedes_entry_id=None,
                            **overrides):
    payload = {
        "guest_id": guest_id,
        "scope": scope,
        "reason_code": reason_code,
        "expected_guest_version": expected_guest_version,
    }
    if property_id is not None:
        payload["property_id"] = property_id
    if host_id is not None:
        payload["host_id"] = host_id
    if supersedes_entry_id is not None:
        payload["supersedes_entry_id"] = supersedes_entry_id
    payload.update(overrides)
    return payload
