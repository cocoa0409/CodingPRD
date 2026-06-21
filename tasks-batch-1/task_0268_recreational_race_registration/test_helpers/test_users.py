"""Pre-built role headers for every role in the PRD (§2.1).

Only `Participant` is entity-backed: its `X-User-ID` must equal the acting
Participant's `id`, so ownership-gated calls MUST use make_participant_headers()
with the real participant id. RaceDirector, PacketStaff, and TimingOfficial are
opaque operator identifiers never matched against a stored entity, so the shared
constants are the canonical form for them.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    # Entity-backed: shared constant is a fallback for non-ownership tests only
    # (e.g. 401/403/404 on bad payload). Ownership-gated calls use the builder.
    "participant_headers": build_user_headers("test-participant-1", "Participant"),
    # Opaque roles: shared constant is the canonical form.
    "race_director_headers": build_user_headers("test-director-1", "RaceDirector"),
    "packet_staff_headers": build_user_headers("test-packet-1", "PacketStaff"),
    "timing_official_headers": build_user_headers("test-timing-1", "TimingOfficial"),
}


def make_participant_headers(user_id: str) -> dict:
    """For the entity-backed Participant role. Pass the actual Participant.id as
    user_id whenever the call is ownership-gated (any participant-owned mutation)."""
    return build_user_headers(user_id, "Participant")


def make_race_director_headers(user_id: str = "test-director-1") -> dict:
    return build_user_headers(user_id, "RaceDirector")


def make_packet_staff_headers(user_id: str = "test-packet-1") -> dict:
    return build_user_headers(user_id, "PacketStaff")


def make_timing_official_headers(user_id: str = "test-timing-1") -> dict:
    return build_user_headers(user_id, "TimingOfficial")
