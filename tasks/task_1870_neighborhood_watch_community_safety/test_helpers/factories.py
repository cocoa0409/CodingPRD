"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "GROUP_NAME": "Test Watch",
    "PRECINCT": "PCT1",
    "STREET": "100-199 Test St",
    "HOUSEHOLDS": 10,
    "MEMBER_NAME": "Test Member",
    "CHANNEL": "SMS",
    "BADGE": "B001",
    "OFFICER_NAME": "Officer Test",
    "OCCURRED_AT": "2026-07-15T10:00:00Z",
    "SEVERITY": 2,
    "CATEGORY": "SUSPICIOUS_ACTIVITY",
    "SCHEDULED_SEND": "2026-08-09T12:00:00Z",
    "EXPIRES_AT": "2027-01-01T00:00:00Z",
    "TRAINING_AT": "2026-08-02T10:00:00Z",
}


def set_clock_payload(to_iso8601):
    return {"to_iso8601": to_iso8601}


def create_watch_group_payload(name=DEFAULTS["GROUP_NAME"],
                               precinct_code=DEFAULTS["PRECINCT"], **overrides):
    payload = {"name": name, "precinct_code": precinct_code}
    payload.update(overrides)
    return payload


def create_block_payload(street_segment=DEFAULTS["STREET"],
                         household_count=DEFAULTS["HOUSEHOLDS"], **overrides):
    payload = {"street_segment": street_segment,
               "household_count": household_count}
    payload.update(overrides)
    return payload


def create_member_payload(watch_group_id, block_id,
                          full_name=DEFAULTS["MEMBER_NAME"],
                          contact_channel=DEFAULTS["CHANNEL"],
                          roster_visibility=None, **overrides):
    payload = {
        "watch_group_id": watch_group_id,
        "block_id": block_id,
        "full_name": full_name,
        "contact_channel": contact_channel,
    }
    if roster_visibility is not None:
        payload["roster_visibility"] = roster_visibility
    payload.update(overrides)
    return payload


def create_captain_assignment_payload(member_id, expected_block_version,
                                      **overrides):
    payload = {"member_id": member_id,
               "expected_block_version": expected_block_version}
    payload.update(overrides)
    return payload


def create_incident_report_payload(block_id, reporter_member_id,
                                   category=DEFAULTS["CATEGORY"],
                                   occurred_at=DEFAULTS["OCCURRED_AT"],
                                   severity=DEFAULTS["SEVERITY"], **overrides):
    payload = {
        "block_id": block_id,
        "reporter_member_id": reporter_member_id,
        "category": category,
        "occurred_at": occurred_at,
        "severity": severity,
    }
    payload.update(overrides)
    return payload


def create_alert_payload(watch_group_id, expected_watch_group_version,
                         alert_kind="SAFETY_TIP", audience_scope="GROUP",
                         scheduled_send_at=DEFAULTS["SCHEDULED_SEND"],
                         target_block_id=None, origin_incident_id=None,
                         **overrides):
    payload = {
        "watch_group_id": watch_group_id,
        "alert_kind": alert_kind,
        "audience_scope": audience_scope,
        "scheduled_send_at": scheduled_send_at,
        "expected_watch_group_version": expected_watch_group_version,
    }
    if target_block_id is not None:
        payload["target_block_id"] = target_block_id
    if origin_incident_id is not None:
        payload["origin_incident_id"] = origin_incident_id
    payload.update(overrides)
    return payload


def ack_alert_payload(member_id, **overrides):
    payload = {"member_id": member_id}
    payload.update(overrides)
    return payload


def create_liaison_officer_payload(badge_number=DEFAULTS["BADGE"],
                                   full_name=DEFAULTS["OFFICER_NAME"],
                                   precinct_code=DEFAULTS["PRECINCT"],
                                   **overrides):
    payload = {"badge_number": badge_number, "full_name": full_name,
               "precinct_code": precinct_code}
    payload.update(overrides)
    return payload


def create_liaison_meeting_payload(watch_group_id, liaison_officer_id,
                                   room_slot_start, room_slot_end, **overrides):
    payload = {
        "watch_group_id": watch_group_id,
        "liaison_officer_id": liaison_officer_id,
        "room_slot_start": room_slot_start,
        "room_slot_end": room_slot_end,
    }
    payload.update(overrides)
    return payload


def mark_held_payload(attendee_count, **overrides):
    payload = {"attendee_count": attendee_count}
    payload.update(overrides)
    return payload


def create_data_share_agreement_payload(watch_group_id, liaison_officer_id,
                                        scope="INCIDENT_SUMMARIES",
                                        expires_at=DEFAULTS["EXPIRES_AT"],
                                        **overrides):
    payload = {
        "watch_group_id": watch_group_id,
        "liaison_officer_id": liaison_officer_id,
        "scope": scope,
        "expires_at": expires_at,
    }
    payload.update(overrides)
    return payload


def create_training_session_payload(watch_group_id, trainer_officer_id,
                                    curriculum="BIAS_AVOIDANCE",
                                    scheduled_at=DEFAULTS["TRAINING_AT"],
                                    **overrides):
    payload = {
        "watch_group_id": watch_group_id,
        "trainer_officer_id": trainer_officer_id,
        "curriculum": curriculum,
        "scheduled_at": scheduled_at,
    }
    payload.update(overrides)
    return payload


def complete_training_payload(attending_member_ids, **overrides):
    payload = {"attending_member_ids": attending_member_ids}
    payload.update(overrides)
    return payload


def create_community_event_payload(watch_group_id, event_kind,
                                   street_closure_start, street_closure_end,
                                   estimated_attendance, **overrides):
    payload = {
        "watch_group_id": watch_group_id,
        "event_kind": event_kind,
        "street_closure_start": street_closure_start,
        "street_closure_end": street_closure_end,
        "estimated_attendance": estimated_attendance,
    }
    payload.update(overrides)
    return payload


def create_certification_review_payload(watch_group_id, reviewing_officer_id,
                                        **overrides):
    payload = {"watch_group_id": watch_group_id,
               "reviewing_officer_id": reviewing_officer_id}
    payload.update(overrides)
    return payload


def decide_review_payload(decision, **overrides):
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


def materials_payload(signs=0, materials=0, **overrides):
    payload = {"signs": signs, "materials": materials}
    payload.update(overrides)
    return payload
