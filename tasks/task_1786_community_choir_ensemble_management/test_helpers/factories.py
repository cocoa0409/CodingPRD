"""Payload factories — one per entity, input fields only."""
from .constants import STANDARD_SEASON_PAYLOAD


def create_season_payload(**overrides) -> dict:
    defaults = dict(STANDARD_SEASON_PAYLOAD)
    defaults.update(overrides)
    return defaults


def create_section_payload(season_id, voice_part="SOPRANO", target_min=1,
                           target_max=2, **overrides) -> dict:
    defaults = {
        "season_id": season_id,
        "voice_part": voice_part,
        "target_min": target_min,
        "target_max": target_max,
    }
    defaults.update(overrides)
    return defaults


def create_member_payload(season_id, full_name="Ada Alto",
                          email="ada@x.org", **overrides) -> dict:
    defaults = {
        "season_id": season_id,
        "full_name": full_name,
        "email": email,
    }
    defaults.update(overrides)
    return defaults


def create_audition_payload(member_id, scheduled_at="2026-08-02T10:00:00Z",
                            **overrides) -> dict:
    defaults = {"member_id": member_id, "scheduled_at": scheduled_at}
    defaults.update(overrides)
    return defaults


def score_audition_payload(tone_score=8, pitch_score=7, sight_score=9,
                           **overrides) -> dict:
    defaults = {
        "tone_score": tone_score,
        "pitch_score": pitch_score,
        "sight_score": sight_score,
    }
    defaults.update(overrides)
    return defaults


def audition_decision_payload(decision, section_id=None, **overrides) -> dict:
    payload = {"decision": decision}
    if section_id is not None:
        payload["section_id"] = section_id
    payload.update(overrides)
    return payload


def create_invoice_payload(member_id, **overrides) -> dict:
    defaults = {"member_id": member_id}
    defaults.update(overrides)
    return defaults


def create_payment_payload(member_id, amount_cents=18000, method="CARD",
                           **overrides) -> dict:
    defaults = {
        "member_id": member_id,
        "amount_cents": amount_cents,
        "method": method,
    }
    defaults.update(overrides)
    return defaults


def create_grant_payload(member_id, requested_cents=5000, need_note=None,
                         **overrides) -> dict:
    payload = {"member_id": member_id, "requested_cents": requested_cents}
    if need_note is not None:
        payload["need_note"] = need_note
    payload.update(overrides)
    return payload


def grant_decision_payload(decision, approved_cents=None, **overrides) -> dict:
    payload = {"decision": decision}
    if approved_cents is not None:
        payload["approved_cents"] = approved_cents
    payload.update(overrides)
    return payload


def grant_apply_payload(invoice_id, amount_cents=None, **overrides) -> dict:
    payload = {"invoice_id": invoice_id}
    if amount_cents is not None:
        payload["amount_cents"] = amount_cents
    payload.update(overrides)
    return payload


def create_rehearsal_payload(season_id, scheduled_at, location=None,
                             **overrides) -> dict:
    payload = {"season_id": season_id, "scheduled_at": scheduled_at}
    if location is not None:
        payload["location"] = location
    payload.update(overrides)
    return payload


def attendance_record_entry(member_id, status) -> dict:
    return {"member_id": member_id, "status": status}


def create_score_payload(title="Mass in G", copy_count=2,
                         replacement_cost_cents=7000, composer=None,
                         **overrides) -> dict:
    payload = {
        "title": title,
        "copy_count": copy_count,
        "replacement_cost_cents": replacement_cost_cents,
    }
    if composer is not None:
        payload["composer"] = composer
    payload.update(overrides)
    return payload


def create_checkout_payload(score_id, member_id,
                            due_date="2026-08-10T00:00:00Z",
                            **overrides) -> dict:
    defaults = {
        "score_id": score_id,
        "member_id": member_id,
        "due_date": due_date,
    }
    defaults.update(overrides)
    return defaults


def create_venue_payload(name="Hall", capacity=100, **overrides) -> dict:
    defaults = {"name": name, "capacity": capacity}
    defaults.update(overrides)
    return defaults


def create_concert_payload(season_id, title="Gala", expected_attendance=80,
                           **overrides) -> dict:
    defaults = {
        "season_id": season_id,
        "title": title,
        "expected_attendance": expected_attendance,
    }
    defaults.update(overrides)
    return defaults


def create_booking_payload(concert_id, venue_id,
                           start_at="2026-09-10T18:00:00Z",
                           end_at="2026-09-10T21:00:00Z",
                           deposit_cents=1000, **overrides) -> dict:
    defaults = {
        "concert_id": concert_id,
        "venue_id": venue_id,
        "start_at": start_at,
        "end_at": end_at,
        "deposit_cents": deposit_cents,
    }
    defaults.update(overrides)
    return defaults


def create_piece_payload(concert_id, title="Suite", duration_seconds=3600,
                         sequence_no=1, featured_member_ids=None,
                         guest_contract_id=None, **overrides) -> dict:
    payload = {
        "concert_id": concert_id,
        "title": title,
        "duration_seconds": duration_seconds,
        "sequence_no": sequence_no,
    }
    if featured_member_ids is not None:
        payload["featured_member_ids"] = featured_member_ids
    if guest_contract_id is not None:
        payload["guest_contract_id"] = guest_contract_id
    payload.update(overrides)
    return payload


def concert_line(rate_cents, units=1) -> dict:
    return {"kind": "CONCERT", "units": units, "rate_cents": rate_cents}


def create_contract_payload(season_id, musician_name="Cellist",
                            service_lines=None, travel_stipend_cents=0,
                            concert_id=None, **overrides) -> dict:
    payload = {
        "season_id": season_id,
        "musician_name": musician_name,
        "service_lines": (
            service_lines if service_lines is not None
            else [concert_line(30000)]
        ),
        "travel_stipend_cents": travel_stipend_cents,
    }
    if concert_id is not None:
        payload["concert_id"] = concert_id
    payload.update(overrides)
    return payload


def counter_contract_payload(expected_guest_contract_version,
                             service_lines=None, travel_stipend_cents=None,
                             **overrides) -> dict:
    payload = {
        "expected_guest_contract_version": expected_guest_contract_version,
    }
    if service_lines is not None:
        payload["service_lines"] = service_lines
    if travel_stipend_cents is not None:
        payload["travel_stipend_cents"] = travel_stipend_cents
    payload.update(overrides)
    return payload


def create_tour_payload(season_id, name="Fest", destination="Reno",
                        departure_at="2026-12-01T00:00:00Z",
                        return_at="2026-12-05T00:00:00Z",
                        seat_count=2, min_seats=1,
                        transport_lodging_cost_cents=10000,
                        **overrides) -> dict:
    defaults = {
        "season_id": season_id,
        "name": name,
        "destination": destination,
        "departure_at": departure_at,
        "return_at": return_at,
        "seat_count": seat_count,
        "min_seats": min_seats,
        "transport_lodging_cost_cents": transport_lodging_cost_cents,
    }
    defaults.update(overrides)
    return defaults


def create_registration_payload(tour_id, **overrides) -> dict:
    defaults = {"tour_id": tour_id}
    defaults.update(overrides)
    return defaults


def create_committee_payload(season_id, chair_member_id, name="Gala",
                             fundraising_goal_cents=50000,
                             **overrides) -> dict:
    defaults = {
        "season_id": season_id,
        "name": name,
        "chair_member_id": chair_member_id,
        "fundraising_goal_cents": fundraising_goal_cents,
    }
    defaults.update(overrides)
    return defaults


def create_pledge_payload(committee_id, donor_name="Donor A",
                          amount_cents=5000, **overrides) -> dict:
    defaults = {
        "committee_id": committee_id,
        "donor_name": donor_name,
        "amount_cents": amount_cents,
    }
    defaults.update(overrides)
    return defaults
