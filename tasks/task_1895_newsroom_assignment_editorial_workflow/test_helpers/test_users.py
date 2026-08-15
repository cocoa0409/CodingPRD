"""Pre-built role headers for every role in the PRD.

NewsDirector is an opaque identity: X-User-ID is not tied to any persisted
entity, which is what allows the very first staff creation from an empty
database. Every other role is entity-backed by StaffMember: X-User-ID must be
the id of an existing staff member. Ownership-gated calls MUST use the
per-instance make_* builders with the real staff id.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for the opaque NewsDirector role, and for tests that
# do not exercise ownership (400-on-bad-payload or wrong-role checks).
TEST_USERS = {
    "news_director_headers": build_user_headers("test-news-director-1",
                                                "NewsDirector"),
    # entity_backed roles: shared constants are fallbacks for non-ownership
    # tests only — they never resolve to a real StaffMember, so any
    # ownership-gated or entity-resolved call must use the make_* builders.
    "reporter_headers": build_user_headers("test-reporter-1", "Reporter"),
    "photographer_headers": build_user_headers("test-photographer-1", "Photographer"),
    "copy_editor_headers": build_user_headers("test-copy-editor-1", "CopyEditor"),
    "fact_checker_headers": build_user_headers("test-fact-checker-1", "FactChecker"),
    "legal_reviewer_headers": build_user_headers("test-legal-reviewer-1",
                                                 "LegalReviewer"),
    "assignment_editor_headers": build_user_headers("test-assignment-editor-1",
                                                    "AssignmentEditor"),
    "managing_editor_headers": build_user_headers("test-managing-editor-1",
                                                  "ManagingEditor"),
    "analytics_producer_headers": build_user_headers("test-analytics-producer-1",
                                                     "AnalyticsProducer"),
}


def make_news_director_headers(user_id: str = "test-news-director-1") -> dict:
    """NewsDirector is opaque: any operator id authenticates."""
    return build_user_headers(user_id, "NewsDirector")


def make_reporter_headers(staff_id: str) -> dict:
    """Reporter is entity_backed:StaffMember — pass the acting StaffMember.id."""
    return build_user_headers(staff_id, "Reporter")


def make_photographer_headers(staff_id: str) -> dict:
    """Photographer is entity_backed:StaffMember — pass the StaffMember.id."""
    return build_user_headers(staff_id, "Photographer")


def make_copy_editor_headers(staff_id: str) -> dict:
    """CopyEditor is entity_backed:StaffMember — pass the StaffMember.id."""
    return build_user_headers(staff_id, "CopyEditor")


def make_fact_checker_headers(staff_id: str) -> dict:
    """FactChecker is entity_backed:StaffMember — pass the StaffMember.id."""
    return build_user_headers(staff_id, "FactChecker")


def make_legal_reviewer_headers(staff_id: str) -> dict:
    """LegalReviewer is entity_backed:StaffMember — pass the StaffMember.id."""
    return build_user_headers(staff_id, "LegalReviewer")


def make_assignment_editor_headers(staff_id: str) -> dict:
    """AssignmentEditor is entity_backed:StaffMember — pass the StaffMember.id."""
    return build_user_headers(staff_id, "AssignmentEditor")


def make_managing_editor_headers(staff_id: str) -> dict:
    """ManagingEditor is entity_backed:StaffMember — pass the StaffMember.id."""
    return build_user_headers(staff_id, "ManagingEditor")


def make_analytics_producer_headers(staff_id: str) -> dict:
    """AnalyticsProducer is entity_backed:StaffMember — pass the StaffMember.id."""
    return build_user_headers(staff_id, "AnalyticsProducer")
