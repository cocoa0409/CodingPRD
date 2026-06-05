"""Pre-built role headers for every role in the Privacy DSAR PRD.

All five roles use an opaque X-User-ID that the server never compares to any
entity id. The one place identity matters is the segregation-of-duties rule:
the PrivacyOfficer who dispatches fulfillment must carry a different X-User-ID
than the IntakeAgent who verified identity. The per-actor builders below let
tests thread distinct operator ids when that distinction matters.
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for every test, since identity is opaque.
TEST_USERS = {
    "intake_agent_headers": build_user_headers("intake-default", "IntakeAgent"),
    "privacy_officer_headers": build_user_headers("officer-default", "PrivacyOfficer"),
    "fulfillment_worker_headers": build_user_headers("worker-default", "FulfillmentWorker"),
    "processor_agent_headers": build_user_headers("processor-default", "ProcessorAgent"),
    "data_subject_agent_headers": build_user_headers("subject-default", "DataSubjectAgent"),
}


def make_intake_agent_headers(user_id: str) -> dict:
    """IntakeAgent headers carrying a specific X-User-ID (the operator pinned
    into verified_by_user_id on verify-identity)."""
    return build_user_headers(user_id, "IntakeAgent")


def make_privacy_officer_headers(user_id: str) -> dict:
    """PrivacyOfficer headers carrying a specific X-User-ID. Use a different id
    than the verifying agent when dispatching fulfillment to satisfy the
    segregation-of-duties rule, or the SAME id to provoke
    ERR_SEGREGATION_OF_DUTIES."""
    return build_user_headers(user_id, "PrivacyOfficer")


def make_fulfillment_worker_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "FulfillmentWorker")


def make_processor_agent_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ProcessorAgent")


def make_data_subject_agent_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "DataSubjectAgent")
