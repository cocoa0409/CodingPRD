"""Pre-built role headers for every role in the PRD (§2.1).

ClientContact and Stenographer are entity-backed: their X-User-ID must equal the
acting entity's id, so per-instance builders are mandatory for ownership-gated
calls. The shared constants are only for flows where ownership is irrelevant
(bad-payload 400s, 404s, reads).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "client_contact_headers": build_user_headers("test-client-1", "ClientContact"),
    "intake_coordinator_headers": build_user_headers("intake-1", "IntakeCoordinator"),
    "caption_editor_headers": build_user_headers("editor-1", "CaptionEditor"),
    "ad_producer_headers": build_user_headers("ad-1", "ADProducer"),
    "qc_specialist_headers": build_user_headers("qc-1", "QCSpecialist"),
    "scheduler_headers": build_user_headers("sched-1", "Scheduler"),
    "stenographer_headers": build_user_headers("test-steno-1", "Stenographer"),
    "operations_manager_headers": build_user_headers("ops-1", "OperationsManager"),
}


def make_client_headers(client_id: str) -> dict:
    """ClientContact is entity-backed: pass the owning Client.id."""
    return build_user_headers(client_id, "ClientContact")


def make_stenographer_headers(stenographer_id: str) -> dict:
    """Stenographer is entity-backed: pass the acting Stenographer.id."""
    return build_user_headers(stenographer_id, "Stenographer")


def make_editor_headers(user_id: str = "editor-1") -> dict:
    return build_user_headers(user_id, "CaptionEditor")


def make_qc_headers(user_id: str = "qc-1") -> dict:
    return build_user_headers(user_id, "QCSpecialist")


def make_ad_producer_headers(user_id: str = "ad-1") -> dict:
    return build_user_headers(user_id, "ADProducer")


def make_ops_headers(user_id: str = "ops-1") -> dict:
    return build_user_headers(user_id, "OperationsManager")
