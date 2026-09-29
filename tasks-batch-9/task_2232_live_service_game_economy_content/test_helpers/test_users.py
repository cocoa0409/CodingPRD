"""Pre-built role headers plus per-instance builders for the player identity."""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .constants import OPERATOR_IDS

# Shared constants — the canonical form for the four operator roles, whose identity is
# not tied to any stored entity. The player entry is only safe for calls that do not
# depend on the caller owning the subject resource (missing-resource or bad-payload cases).
TEST_USERS: Dict[str, Dict[str, str]] = {
    "content_producer_headers": build_user_headers(OPERATOR_IDS["ContentProducer"], "ContentProducer"),
    "economy_designer_headers": build_user_headers(OPERATOR_IDS["EconomyDesigner"], "EconomyDesigner"),
    "economy_designer_alt_headers": build_user_headers(OPERATOR_IDS["EconomyDesignerAlt"], "EconomyDesigner"),
    "live_ops_commander_headers": build_user_headers(OPERATOR_IDS["LiveOpsCommander"], "LiveOpsCommander"),
    "compliance_officer_headers": build_user_headers(OPERATOR_IDS["ComplianceOfficer"], "ComplianceOfficer"),
    "compliance_officer_alt_headers": build_user_headers(OPERATOR_IDS["ComplianceOfficerAlt"], "ComplianceOfficer"),
    "player_headers": build_user_headers("u_player_placeholder", "Player"),
}


def make_player_headers(player_id: str) -> Dict[str, str]:
    """Headers for the Player role. The player's identity is the stored player record,
    so pass the actual player id whenever the call is ownership-gated."""
    return build_user_headers(player_id, "Player")


def make_content_producer_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, "ContentProducer")


def make_economy_designer_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, "EconomyDesigner")


def make_live_ops_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, "LiveOpsCommander")


def make_compliance_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, "ComplianceOfficer")


def make_headers(user_id: str, role: str) -> Dict[str, str]:
    """Arbitrary user id / role pair (used by unknown-role and cross-role checks)."""
    return build_user_headers(user_id, role)


# Convenience aliases for the four operator roles.
PRODUCER = TEST_USERS["content_producer_headers"]
DESIGNER = TEST_USERS["economy_designer_headers"]
DESIGNER_ALT = TEST_USERS["economy_designer_alt_headers"]
LIVEOPS = TEST_USERS["live_ops_commander_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]
COMPLIANCE_ALT = TEST_USERS["compliance_officer_alt_headers"]
