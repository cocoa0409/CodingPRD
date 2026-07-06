"""Payload factories — one per creatable resource, input fields only (PRD §3)."""


def create_officer_payload(**overrides) -> dict:
    payload = {"badge_number": "B-100", "full_name": "Test Officer"}
    payload.update(overrides)
    return payload


def create_beat_payload(**overrides) -> dict:
    payload = {"beat_code": "BEAT1", "name": "Test Beat", "patrol_zone": "RESIDENTIAL"}
    payload.update(overrides)
    return payload


def create_violation_code_payload(**overrides) -> dict:
    payload = {
        "code": "EXP_METER",
        "description": "Expired meter",
        "base_fine_cents": 5000,
        "is_booting_eligible": True,
    }
    payload.update(overrides)
    return payload


def create_hearing_room_payload(**overrides) -> dict:
    payload = {"room_code": "HR1", "name": "Hearing Room 1"}
    payload.update(overrides)
    return payload


def create_shift_payload(officer_id, beat_id, **overrides) -> dict:
    payload = {
        "officer_id": officer_id,
        "beat_id": beat_id,
        "scheduled_start": "2026-03-02T08:00:00Z",
        "scheduled_end": "2026-03-02T16:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_vehicle_payload(**overrides) -> dict:
    payload = {"plate": "PLT100", "state": "CA"}
    payload.update(overrides)
    return payload


def create_citation_payload(vehicle_id, shift_id, violation_code_id, **overrides) -> dict:
    payload = {
        "vehicle_id": vehicle_id,
        "shift_id": shift_id,
        "violation_code_id": violation_code_id,
        "issued_via": "LPR",
        "evidence_photo_url": "https://evidence.example/photo.jpg",
    }
    payload.update(overrides)
    return payload


def create_payment_payload(citation_id, amount_cents, **overrides) -> dict:
    payload = {"citation_id": citation_id, "amount_cents": amount_cents, "method": "CARD"}
    payload.update(overrides)
    return payload


def create_contest_payload(citation_id, **overrides) -> dict:
    payload = {"citation_id": citation_id, "grounds": "Disputed citation"}
    payload.update(overrides)
    return payload


def create_hearing_payload(contest_id, room_id, **overrides) -> dict:
    payload = {
        "contest_id": contest_id,
        "room_id": room_id,
        "scheduled_start": "2026-03-05T09:00:00Z",
        "scheduled_end": "2026-03-05T10:00:00Z",
    }
    payload.update(overrides)
    return payload


def adjourn_hearing_payload(**overrides) -> dict:
    payload = {
        "scheduled_start": "2026-03-06T09:00:00Z",
        "scheduled_end": "2026-03-06T10:00:00Z",
    }
    payload.update(overrides)
    return payload


def decide_hearing_payload(decision, **overrides) -> dict:
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


def create_boot_tow_order_payload(vehicle_id, order_type="BOOT", **overrides) -> dict:
    payload = {"vehicle_id": vehicle_id, "order_type": order_type}
    payload.update(overrides)
    return payload


def reassess_citation_payload(new_fine_amount_cents, expected_citation_version, **overrides) -> dict:
    payload = {
        "new_fine_amount_cents": new_fine_amount_cents,
        "expected_citation_version": expected_citation_version,
    }
    payload.update(overrides)
    return payload


def adjustment_payload(citation_id, waive_amount_cents, expected_vehicle_version, **overrides) -> dict:
    payload = {
        "citation_id": citation_id,
        "waive_amount_cents": waive_amount_cents,
        "expected_vehicle_version": expected_vehicle_version,
    }
    payload.update(overrides)
    return payload


def set_clock_payload(to_iso8601, **overrides) -> dict:
    payload = {"to_iso8601": to_iso8601}
    payload.update(overrides)
    return payload
