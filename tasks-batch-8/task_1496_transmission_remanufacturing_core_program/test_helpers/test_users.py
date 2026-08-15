"""Pre-built role headers for every role in the PRD (§2.1).

All roles are opaque: per PRD §2.1 the server never compares X-User-ID against
any entity's `id`. Two identifiers are nevertheless recorded for later
comparison — the calibration drafter (`cal_created_by_id`, §3.3) and the claim
filer (`installer_id`, §3.8) — so dedicated constants exist for the two
Calibrator identities and the Installer identity used by those flows.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    "program_admin_headers": build_user_headers("admin-1", "ProgramAdmin"),
    "inventory_planner_headers": build_user_headers("inv-1", "InventoryPlanner"),
    "reman_planner_headers": build_user_headers("plan-1", "RemanPlanner"),
    "reman_technician_headers": build_user_headers("tech-1", "RemanTechnician"),
    # Two distinct Calibrator identities so segregation-of-duties flows can
    # draft as one and verify as the other (PRD §3.3).
    "calibrator_a_headers": build_user_headers("cal-a", "Calibrator"),
    "calibrator_b_headers": build_user_headers("cal-b", "Calibrator"),
    "dyno_operator_headers": build_user_headers("dyno-1", "DynoOperator"),
    "core_intake_clerk_headers": build_user_headers("clerk-1", "CoreIntakeClerk"),
    "core_inspector_headers": build_user_headers("insp-1", "CoreInspector"),
    # The filing installer's identifier is stored as installer_id and
    # return-ship is accepted only from that same identifier (PRD §3.8).
    "installer_headers": build_user_headers("inst-1", "Installer"),
    "installer_other_headers": build_user_headers("inst-2", "Installer"),
    "warranty_adjuster_headers": build_user_headers("adj-1", "WarrantyAdjuster"),
    "any_headers": build_user_headers("reader-1", "Any"),
}


def make_program_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ProgramAdmin")


def make_inventory_planner_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "InventoryPlanner")


def make_reman_planner_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "RemanPlanner")


def make_reman_technician_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "RemanTechnician")


def make_calibrator_headers(user_id: str) -> dict:
    """For Calibrator calls where the specific X-User-ID matters (draft vs
    verify segregation of duties, PRD §3.3)."""
    return build_user_headers(user_id, "Calibrator")


def make_dyno_operator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "DynoOperator")


def make_core_intake_clerk_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "CoreIntakeClerk")


def make_core_inspector_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "CoreInspector")


def make_installer_headers(user_id: str) -> dict:
    """For Installer calls where X-User-ID is later matched against the
    claim's installer_id on return-ship (PRD §3.8)."""
    return build_user_headers(user_id, "Installer")


def make_warranty_adjuster_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "WarrantyAdjuster")
