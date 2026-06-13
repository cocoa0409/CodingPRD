"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for the opaque Publisher role, and for tests that do
# not exercise entity-backed ownership (401/404/422 paths).
TEST_USERS = {
    # Publisher identity is opaque — never tied to a persisted entity.
    "publisher_headers": build_user_headers("publisher-operator-1", "Publisher"),
    # entity_backed fallbacks — only valid for tests that do NOT exercise ownership.
    "author_headers": build_user_headers("test-author-1", "Author"),
    "agent_headers": build_user_headers("test-agent-1", "Agent"),
}


# Per-instance builders — required for every entity_backed role.
def make_author_headers(user_id: str) -> dict:
    """For Author (entity_backed:Author). Pass the actual Author.id as user_id
    whenever the call is ownership-gated (Author may read only contracts whose
    author_id == X-User-ID)."""
    return build_user_headers(user_id, "Author")


def make_agent_headers(user_id: str) -> dict:
    """For Agent (entity_backed:Agent). Pass the actual Agent.id as user_id
    whenever the call is ownership-gated (Agent may read only contracts whose
    agent_id == X-User-ID)."""
    return build_user_headers(user_id, "Agent")


def make_stranger_headers() -> dict:
    """A request whose X-User-Role is not one of Publisher/Author/Agent."""
    return build_user_headers("stranger-1", "Stranger")
