"""Pre-built role headers for every role in the PRD.

All nine roles use opaque operator identifiers: `X-User-ID` is never compared
against a resource's `id`. The identifier still matters where accountability is
recorded: make-step sign-offs append the signer to `step_signer_ids`, and
grading events store `grader_user_id`, so segregation-of-duties tests pick
deliberate user ids via `make_role_headers`.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for any test that does not exercise
# segregation-of-duties identity comparisons.
TEST_USERS = {
    "plant_admin_headers": build_user_headers("pa_default", "PlantAdmin"),
    "milk_receiver_headers": build_user_headers("mr_default", "MilkReceiver"),
    "make_planner_headers": build_user_headers("mp_default", "MakePlanner"),
    "cheesemaker_headers": build_user_headers("cm_alice", "Cheesemaker"),
    "qa_grader_headers": build_user_headers("qa_carol", "QAGrader"),
    "aging_room_operator_headers": build_user_headers("aro_default", "AgingRoomOperator"),
    "sales_planner_headers": build_user_headers("sp_default", "SalesPlanner"),
    "cut_wrap_operator_headers": build_user_headers("cwo_default", "CutWrapOperator"),
    "compliance_officer_headers": build_user_headers("co_default", "ComplianceOfficer"),
}

# Well-known named operator ids used by segregation-of-duties scenarios.
CM_ALICE = "cm_alice"
CM_BOB = "cm_bob"
QA_CAROL = "qa_carol"
QA_DAVE = "qa_dave"


def make_role_headers(user_id: str, role: str) -> dict:
    """Build headers for a specific operator id.

    Use this whenever the user id must be controlled — e.g. make-step
    sign-offs that must alternate between two cheesemakers, or a grader whose
    id must (or must not) appear in `step_signer_ids`.
    """
    return build_user_headers(user_id, role)


def make_cheesemaker_headers(user_id: str) -> dict:
    """Cheesemaker headers with a specific operator id (step sign-off identity)."""
    return build_user_headers(user_id, "Cheesemaker")


def make_qa_grader_headers(user_id: str) -> dict:
    """QAGrader headers with a specific operator id (grader identity)."""
    return build_user_headers(user_id, "QAGrader")
