"""Pre-built role headers for every role in the PRD (section 2.1).

DistributionAdmin, ChannelManager, and CreditOfficer carry an opaque
X-User-ID. InstallerRep is entity-backed: X-User-ID must equal the acting
Installer's id, so ownership-gated calls MUST use make_installer_rep_headers
with the real installer id.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles — shared constants are the canonical form.
    "admin_headers": build_user_headers("test-admin-1", "DistributionAdmin"),
    "manager_headers": build_user_headers("test-manager-1", "ChannelManager"),
    "officer_headers": build_user_headers("test-officer-1", "CreditOfficer"),
    # Entity-backed role — shared constant is a fallback for non-ownership
    # tests only (e.g., role-denial checks where the call is rejected before
    # any ownership comparison).
    "installer_rep_headers": build_user_headers("test-installer-rep-1", "InstallerRep"),
}


def make_installer_rep_headers(installer_id: str) -> dict:
    """Headers for an InstallerRep acting as the given Installer.

    Pass the actual Installer.id whenever the call is ownership-gated
    (project create/lock/cancel, allocation create/release, payments on own
    invoices, RMA create/submit, permit document/submit/reassemble/withdraw,
    project complete).
    """
    return build_user_headers(installer_id, "InstallerRep")
