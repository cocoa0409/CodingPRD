"""Pre-built role headers for every role in the PRD (§2.1).

Staff roles (BandDirector, AssistantDirector, BoosterTreasurer, EquipmentManager)
carry an opaque user id never compared to any entity id, so shared constants are
canonical. Reads marked `Any` in PRD §4 are served by READER_HEADERS (a director
credential, which §2.1 grants every read endpoint).

Student and SectionLeader are entity-backed roles: X-User-ID must be the acting
Student record's id. Their shared constants are fallbacks for non-ownership
contexts only; ownership-gated calls MUST use the per-instance builders.
"""
from prd_bench_local_runner.testing import build_user_headers

DIRECTOR_HEADERS = build_user_headers("dir-1", "BandDirector")
DIRECTOR_2_HEADERS = build_user_headers("dir-2", "BandDirector")
ASSISTANT_HEADERS = build_user_headers("asst-1", "AssistantDirector")
TREASURER_HEADERS = build_user_headers("treas-1", "BoosterTreasurer")
EQUIPMENT_HEADERS = build_user_headers("equip-1", "EquipmentManager")
# Reads marked "Any" in PRD §4: every declared role may read, so a director
# credential is a valid canonical reader.
READER_HEADERS = build_user_headers("reader-1", "BandDirector")

TEST_USERS = {
    "director_headers": DIRECTOR_HEADERS,
    "director_2_headers": DIRECTOR_2_HEADERS,
    "assistant_headers": ASSISTANT_HEADERS,
    "treasurer_headers": TREASURER_HEADERS,
    "equipment_headers": EQUIPMENT_HEADERS,
    "reader_headers": READER_HEADERS,
    # entity_backed roles — fallback constants for non-ownership tests only.
    "student_headers": build_user_headers("test-student-1", "Student"),
    "section_leader_headers": build_user_headers("test-leader-1", "SectionLeader"),
}


def make_student_headers(user_id: str) -> dict:
    """Student is entity_backed: pass the acting Student record's id as user_id
    whenever the call is ownership-gated (self-enrollment, self-excuse)."""
    return build_user_headers(user_id, "Student")


def make_section_leader_headers(user_id: str) -> dict:
    """SectionLeader is entity_backed: pass the acting Student record's id as
    user_id whenever the call gates on section leadership (chair challenge)."""
    return build_user_headers(user_id, "SectionLeader")


def make_director_headers(user_id: str) -> dict:
    """BandDirector with a caller-chosen opaque id (segregation-of-duties tests
    need distinct director identities)."""
    return build_user_headers(user_id, "BandDirector")


def make_assistant_headers(user_id: str) -> dict:
    """AssistantDirector with a caller-chosen opaque id."""
    return build_user_headers(user_id, "AssistantDirector")
