"""Pre-built role headers for every role in the PRD.

All three roles carry an opaque X-User-ID that the server never compares to any
entity id (PRD 2.1): "ownership and permission decisions are made purely on
X-User-Role and the operation being attempted." So the shared-constant form is
canonical for every role; no entity-backed per-instance builders are required.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "receiver_headers": build_user_headers("test-receiver-1", "Receiver"),
    "scheduler_headers": build_user_headers("test-scheduler-1", "Scheduler"),
    "qa_inspector_headers": build_user_headers("test-qa-1", "QAInspector"),
}

# Convenience header constants used directly by the test suite. Each is the
# canonical role-header dict for one of the PRD's three roles (PRD 2.1).
RECEIVER = TEST_USERS["receiver_headers"]
SCHEDULER = TEST_USERS["scheduler_headers"]
QA = TEST_USERS["qa_inspector_headers"]

# An unknown role for ERR_UNAUTHENTICATED tests.
UNKNOWN_ROLE_HEADERS = build_user_headers("test-ghost-1", "Ghost")
