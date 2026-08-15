"""Pre-built role headers for every role in the PRD (§2.1).

All four roles are opaque operator identities: `X-User-ID` is never compared
against any resource id, so shared constants are the canonical form.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-platform-admin-1",
                                                 "PlatformAdmin"),
    "reserve_specialist_headers": build_user_headers("test-reserve-specialist-1",
                                                     "ReserveSpecialist"),
    "board_member_headers": build_user_headers("test-board-member-1",
                                               "BoardMember"),
    "association_manager_headers": build_user_headers("test-association-manager-1",
                                                      "AssociationManager"),
}
