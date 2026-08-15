"""Composite setup helpers.

Every test starts against an empty database (the harness restarts the server
before each test), so these helpers build complete precondition chains out of
PRD-declared endpoints only. Setup calls use get_success_data() so failures
surface as clear "Setup step failed" errors.

Identity threading: LiaisonOfficer calls use headers built from the officer
entity's own id; Member/BlockCaptain calls use headers built from the acting
member's id. Ownership-gated calls never fall back to the shared constants.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    ack_alert_payload,
    complete_training_payload,
    create_alert_payload,
    create_block_payload,
    create_captain_assignment_payload,
    create_certification_review_payload,
    create_community_event_payload,
    create_data_share_agreement_payload,
    create_incident_report_payload,
    create_liaison_meeting_payload,
    create_liaison_officer_payload,
    create_member_payload,
    create_training_session_payload,
    create_watch_group_payload,
    decide_review_payload,
    mark_held_payload,
    materials_payload,
    set_clock_payload,
)
from .test_users import (
    TEST_USERS,
    make_captain_headers,
    make_member_headers,
    make_officer_headers,
)

COORD = TEST_USERS["coordinator_headers"]


# ---------------------------------------------------------------------------
# Primitive steps
# ---------------------------------------------------------------------------

def set_clock(to_iso8601):
    """Advance the program logical clock."""
    return get_success_data(api_client.set_clock(set_clock_payload(to_iso8601), COORD))


def create_watch_group(name="Test Watch", precinct_code="PCT1"):
    return get_success_data(
        api_client.create_watch_group(
            create_watch_group_payload(name, precinct_code), COORD,
        )
    )


def add_block(watch_group_id, street_segment="100-199 Test St", household_count=10):
    """Add a block (born PENDING)."""
    return get_success_data(
        api_client.create_block(
            watch_group_id,
            create_block_payload(street_segment, household_count),
            COORD,
        )
    )


def register_block(block_id):
    """Register a PENDING block; bubbles the group posture up to FORMATION."""
    return get_success_data(api_client.register_block(block_id, COORD))


def add_member(watch_group_id, block_id, full_name="Test Member",
               contact_channel="SMS", roster_visibility=None):
    return get_success_data(
        api_client.create_member(
            create_member_payload(
                watch_group_id, block_id, full_name=full_name,
                contact_channel=contact_channel,
                roster_visibility=roster_visibility,
            ),
            COORD,
        )
    )


def add_members(watch_group_id, block_id, count, name_prefix="M",
                channels=("SMS", "EMAIL")):
    """Enroll `count` members, cycling contact channels. Returns member list."""
    members = []
    for i in range(count):
        members.append(
            add_member(
                watch_group_id, block_id,
                full_name=f"{name_prefix}{i + 1:02d}",
                contact_channel=channels[i % len(channels)],
            )
        )
    return members


def create_officer(badge_number="B001", full_name="Officer Test",
                   precinct_code="PCT1"):
    return get_success_data(
        api_client.create_liaison_officer(
            create_liaison_officer_payload(badge_number, full_name, precinct_code),
            COORD,
        )
    )


def complete_bias_training(watch_group_id, officer, attending_member_ids,
                           scheduled_at="2026-08-02T10:00:00Z",
                           curriculum="BIAS_AVOIDANCE"):
    """Schedule + complete a training session as the trainer officer.
    Stamps bias_training_completed_at for BIAS_AVOIDANCE attendees and arms
    the group's 24h cooldown."""
    officer_headers = make_officer_headers(officer["id"])
    session = get_success_data(
        api_client.create_training_session(
            create_training_session_payload(
                watch_group_id, officer["id"],
                curriculum=curriculum, scheduled_at=scheduled_at,
            ),
            officer_headers,
        )
    )
    return get_success_data(
        api_client.complete_training_session(
            session["id"],
            complete_training_payload(attending_member_ids),
            officer_headers,
        )
    )


def assign_captain(block_id, member_id):
    """Appoint a captain, threading the block's current version (OCC)."""
    block = get_success_data(api_client.get_block(block_id, COORD))
    return get_success_data(
        api_client.create_captain_assignment(
            block_id,
            create_captain_assignment_payload(member_id, block["version"]),
            COORD,
        )
    )


def file_incident(block_id, reporter, category="SUSPICIOUS_ACTIVITY",
                  occurred_at="2026-07-15T10:00:00Z", severity=2):
    """File an incident report as the reporter (Member role, own id)."""
    return get_success_data(
        api_client.create_incident_report(
            create_incident_report_payload(
                block_id, reporter["id"],
                category=category, occurred_at=occurred_at, severity=severity,
            ),
            make_member_headers(reporter["id"]),
        )
    )


def move_report_to_under_review(report_id):
    return get_success_data(api_client.begin_review_incident(report_id, COORD))


def corroborate_report(report_id, officer):
    return get_success_data(
        api_client.corroborate_incident(report_id, make_officer_headers(officer["id"]))
    )


def create_active_agreement(watch_group_id, officer, scope="INCIDENT_SUMMARIES",
                            expires_at="2027-01-01T00:00:00Z"):
    """Draft + activate a data-sharing agreement (officer activates own)."""
    agreement = get_success_data(
        api_client.create_data_share_agreement(
            create_data_share_agreement_payload(
                watch_group_id, officer["id"], scope=scope, expires_at=expires_at,
            ),
            COORD,
        )
    )
    return get_success_data(
        api_client.activate_data_share_agreement(
            agreement["id"], make_officer_headers(officer["id"]),
        )
    )


def get_group_version(watch_group_id):
    """Freshly observed group version (for OCC-guarded alert creation)."""
    group = get_success_data(api_client.get_watch_group(watch_group_id, COORD))
    return group["version"]


def create_alert(watch_group_id, alert_kind="SAFETY_TIP", audience_scope="GROUP",
                 scheduled_send_at="2026-08-09T12:00:00Z", target_block_id=None,
                 origin_incident_id=None):
    """Draft an alert, threading the group's current version (OCC)."""
    version = get_group_version(watch_group_id)
    return get_success_data(
        api_client.create_alert(
            create_alert_payload(
                watch_group_id, version,
                alert_kind=alert_kind, audience_scope=audience_scope,
                scheduled_send_at=scheduled_send_at,
                target_block_id=target_block_id,
                origin_incident_id=origin_incident_id,
            ),
            COORD,
        )
    )


def queue_alert(alert_id):
    return get_success_data(api_client.queue_alert(alert_id, COORD))


def send_alert_at(alert_id, send_at):
    """Move the clock to the scheduled instant and send explicitly."""
    set_clock(send_at)
    return get_success_data(api_client.send_alert(alert_id, COORD))


def send_group_alert(watch_group_id, scheduled_send_at, alert_kind="SAFETY_TIP"):
    """Draft -> queue -> send a GROUP-scope alert at its scheduled instant."""
    alert = create_alert(
        watch_group_id, alert_kind=alert_kind,
        scheduled_send_at=scheduled_send_at,
    )
    queue_alert(alert["id"])
    return send_alert_at(alert["id"], scheduled_send_at)


# ---------------------------------------------------------------------------
# Tier 2/3: group workspaces
# ---------------------------------------------------------------------------

def setup_group_with_registered_block(name="Test Watch", precinct_code="PCT1",
                                      street_segment="100-199 Test St",
                                      household_count=10):
    """Group + one REGISTERED block (posture FORMATION). Returns (group, block)."""
    group = create_watch_group(name, precinct_code)
    block = add_block(group["id"], street_segment, household_count)
    block = register_block(block["id"])
    return group, block


def setup_group_with_member(name="Test Watch", precinct_code="PCT1",
                            contact_channel="SMS", roster_visibility=None):
    """Group + REGISTERED block + one ACTIVE member. Returns (group, block, member)."""
    group, block = setup_group_with_registered_block(name, precinct_code)
    member = add_member(group["id"], block["id"], full_name="Member One",
                        contact_channel=contact_channel,
                        roster_visibility=roster_visibility)
    return group, block, member


def setup_operational_group(name="Operational Watch", precinct_code="PCT1",
                            member_channels=("SMS", "SMS"),
                            train_member_indexes=(0,),
                            badge_number="B001",
                            street_segments=("100-199 Test St",)):
    """Group walked to OPERATIONAL: blocks REGISTERED, members enrolled,
    BIAS_AVOIDANCE training completed, every REGISTERED block captained.

    member_channels: one entry per member to create; members are spread across
    blocks round-robin. Returns a workspace dict.
    """
    group = create_watch_group(name, precinct_code)
    blocks = []
    for i, segment in enumerate(street_segments):
        block = add_block(group["id"], segment, 10)
        blocks.append(register_block(block["id"]))
    members = []
    for i, channel in enumerate(member_channels):
        block = blocks[i % len(blocks)]
        members.append(
            add_member(group["id"], block["id"],
                       full_name=f"OW{i + 1:02d}", contact_channel=channel)
        )
    officer = create_officer(badge_number, "Officer Ops", precinct_code)
    trainee_ids = [members[i]["id"] for i in train_member_indexes]
    complete_bias_training(group["id"], officer, trainee_ids)
    assignments = []
    for i, block in enumerate(blocks):
        # captain: first member living on that block
        captain = next(m for j, m in enumerate(members)
                       if j % len(blocks) == i)
        assignments.append(assign_captain(block["id"], captain["id"]))
    group = get_success_data(api_client.get_watch_group(group["id"], COORD))
    return {
        "group": group,
        "blocks": blocks,
        "members": members,
        "officer": officer,
        "assignments": assignments,
    }


def hold_quorum_meeting(watch_group_id, officer, room_slot_start, room_slot_end,
                        attendee_count):
    """Schedule a meeting as the officer, advance the clock into the slot,
    and mark it held with the supplied attendee_count."""
    officer_headers = make_officer_headers(officer["id"])
    meeting = get_success_data(
        api_client.create_liaison_meeting(
            create_liaison_meeting_payload(
                watch_group_id, officer["id"], room_slot_start, room_slot_end,
            ),
            officer_headers,
        )
    )
    # midpoint of the slot satisfies "clock must have reached room_slot_start"
    set_clock(room_slot_start[:11] + _mid_time(room_slot_start, room_slot_end))
    return get_success_data(
        api_client.mark_meeting_held(
            meeting["id"], mark_held_payload(attendee_count), officer_headers,
        )
    )


def _mid_time(start_iso, end_iso):
    """Return 'HH:MM:SSZ' halfway between two same-day ISO timestamps."""
    from datetime import datetime, timedelta

    fmt = "%Y-%m-%dT%H:%M:%SZ"
    start = datetime.strptime(start_iso, fmt)
    end = datetime.strptime(end_iso, fmt)
    mid = start + (end - start) / 2
    return mid.strftime("%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Tier 4: certification-points target fixtures
# ---------------------------------------------------------------------------

def setup_cert_scoring_group(name, precinct_code, member_count,
                             trained_count, quorum_meeting_count,
                             sent_alert_count, captained=True):
    """Build an OPERATIONAL group landing on a precise certification-points
    composite: min(25, trained_count) member points + min(25, 5*meetings)
    meeting points + 0 event points + (15 if captained else 0) captain points
    + (15 if alerts >= 3 else 5 if >= 1 else 0) alert points.

    Returns a workspace dict with two officers: `trainer` (delivered the bias
    session) and `reviewer` (eligible to certify per segregation of duties).
    """
    group = create_watch_group(name, precinct_code)
    block = add_block(group["id"], "1-1 Scoring Way", 40)
    block = register_block(block["id"])
    members = add_members(group["id"], block["id"], member_count,
                          name_prefix="SC")
    trainer = create_officer(f"{precinct_code}-T", "Officer Train", precinct_code)
    reviewer = create_officer(f"{precinct_code}-R", "Officer Review", precinct_code)
    complete_bias_training(
        group["id"], trainer,
        [m["id"] for m in members[:trained_count]],
    )
    if captained:
        assign_captain(block["id"], members[0]["id"])
    # quorum threshold at this membership size; attendee_count pinned to it
    import math
    threshold = max(2, math.ceil(member_count * 0.25))
    for i in range(quorum_meeting_count):
        day = 5 + i
        hold_quorum_meeting(
            group["id"], trainer,
            f"2026-08-{day:02d}T18:00:00Z", f"2026-08-{day:02d}T19:00:00Z",
            threshold,
        )
    for i in range(sent_alert_count):
        send_group_alert(group["id"], f"2026-08-11T{12 + i:02d}:00:00Z")
    group = get_success_data(api_client.get_watch_group(group["id"], COORD))
    return {
        "group": group,
        "block": block,
        "members": members,
        "trainer": trainer,
        "reviewer": reviewer,
    }


def open_certification_review(watch_group_id, reviewing_officer):
    """Open a review; certification_points is computed at creation."""
    return get_success_data(
        api_client.create_certification_review(
            create_certification_review_payload(
                watch_group_id, reviewing_officer["id"],
            ),
            COORD,
        )
    )


def decide_review(review_id, officer, decision):
    return get_success_data(
        api_client.decide_certification_review(
            review_id, decide_review_payload(decision),
            make_officer_headers(officer["id"]),
        )
    )


def propose_event(watch_group_id, event_kind, closure_start, closure_end,
                  estimated_attendance):
    return get_success_data(
        api_client.create_community_event(
            create_community_event_payload(
                watch_group_id, event_kind, closure_start, closure_end,
                estimated_attendance,
            ),
            COORD,
        )
    )


def issue_materials(watch_group_id, signs=0, materials=0):
    return get_success_data(
        api_client.issue_materials(
            watch_group_id, materials_payload(signs, materials), COORD,
        )
    )
