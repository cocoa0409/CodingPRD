"""Pre-built role headers for every role in the PRD.

PRD §2.1 identity rules:

  All five roles (WarehouseAdmin, Receiver, QAOfficer, Picker,
  RecallOfficer) are OPAQUE. PRD §2.1: "For all five roles, X-User-ID
  is an opaque operator identifier — none of the roles is backed by a
  persisted user entity, and the server does not compare X-User-ID to
  any entity's id." Shared-constant headers are therefore canonical
  for ownership; tests do not need per-entity builders for role
  identity.

  However, PRD §2.1 ALSO requires that the server record actor_user_id
  for segregation-of-duties enforcement: the inspector of a receipt
  must not be the same X-User-ID that performs the corresponding
  acceptance; the QAOfficer that performed the quarantine transition
  must not be the X-User-ID that performs release-from-quarantine; the
  RecallOfficer that announces a recall must not be the X-User-ID of
  the QAOfficer that assessed the in-scope deviation. To exercise SOD
  pass paths (and SOD violation paths), tests need at least two
  distinct X-User-IDs PER role.

  We therefore expose, per role, a primary and an "_alt" shared
  constant. Builders `make_<role>_headers(actor_id)` mint headers for
  arbitrary opaque identifiers — useful for tests that need fine-
  grained control over which user_id is recorded as actor.
"""
from __future__ import annotations

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# ---------------------------------------------------------------------------
# Canonical opaque-actor identifiers — primary + alt per role for SOD.
# All five roles are opaque per PRD §2.1.
# ---------------------------------------------------------------------------
WAREHOUSE_ADMIN_ID = "wa-001"
WAREHOUSE_ADMIN_ID_ALT = "wa-002"

RECEIVER_ID = "receiver-001"
RECEIVER_ID_ALT = "receiver-002"

QA_OFFICER_ID = "qa-001"
QA_OFFICER_ID_ALT = "qa-002"
QA_OFFICER_ID_THIRD = "qa-003"

PICKER_ID = "picker-001"
PICKER_ID_ALT = "picker-002"

RECALL_OFFICER_ID = "recall-001"
RECALL_OFFICER_ID_ALT = "recall-002"


TEST_USERS: Dict[str, Dict[str, str]] = {
    # WarehouseAdmin
    "warehouse_admin_headers": build_user_headers(
        WAREHOUSE_ADMIN_ID, "WarehouseAdmin",
    ),
    "warehouse_admin_headers_alt": build_user_headers(
        WAREHOUSE_ADMIN_ID_ALT, "WarehouseAdmin",
    ),
    # Receiver
    "receiver_headers": build_user_headers(RECEIVER_ID, "Receiver"),
    "receiver_headers_alt": build_user_headers(
        RECEIVER_ID_ALT, "Receiver",
    ),
    # QAOfficer
    "qa_officer_headers": build_user_headers(QA_OFFICER_ID, "QAOfficer"),
    "qa_officer_headers_alt": build_user_headers(
        QA_OFFICER_ID_ALT, "QAOfficer",
    ),
    "qa_officer_headers_third": build_user_headers(
        QA_OFFICER_ID_THIRD, "QAOfficer",
    ),
    # Picker
    "picker_headers": build_user_headers(PICKER_ID, "Picker"),
    "picker_headers_alt": build_user_headers(PICKER_ID_ALT, "Picker"),
    # RecallOfficer
    "recall_officer_headers": build_user_headers(
        RECALL_OFFICER_ID, "RecallOfficer",
    ),
    "recall_officer_headers_alt": build_user_headers(
        RECALL_OFFICER_ID_ALT, "RecallOfficer",
    ),
}


# ---------------------------------------------------------------------------
# Per-instance builders — useful for tests that need fine control over
# which X-User-ID is recorded as actor_user_id (e.g. SOD chains where
# a different actor must perform each step).
# ---------------------------------------------------------------------------
def make_warehouse_admin_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, "WarehouseAdmin")


def make_receiver_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, "Receiver")


def make_qa_officer_headers(user_id: str) -> Dict[str, str]:
    """Used in segregation-of-duties chains: the QAOfficer that performs
    accept must differ from the X-User-ID that performed inspect, and
    the QAOfficer that releases-from-quarantine must differ from the
    QAOfficer that performed the quarantine transition.
    """
    return build_user_headers(user_id, "QAOfficer")


def make_picker_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, "Picker")


def make_recall_officer_headers(user_id: str) -> Dict[str, str]:
    """Used to enforce SOD on recall announce: the RecallOfficer's
    X-User-ID must differ from the QAOfficer X-User-ID that performed
    the most recent deviation assessment on any in-scope lot.
    """
    return build_user_headers(user_id, "RecallOfficer")


__all__ = [
    "WAREHOUSE_ADMIN_ID",
    "WAREHOUSE_ADMIN_ID_ALT",
    "RECEIVER_ID",
    "RECEIVER_ID_ALT",
    "QA_OFFICER_ID",
    "QA_OFFICER_ID_ALT",
    "QA_OFFICER_ID_THIRD",
    "PICKER_ID",
    "PICKER_ID_ALT",
    "RECALL_OFFICER_ID",
    "RECALL_OFFICER_ID_ALT",
    "TEST_USERS",
    "make_warehouse_admin_headers",
    "make_receiver_headers",
    "make_qa_officer_headers",
    "make_picker_headers",
    "make_recall_officer_headers",
]
