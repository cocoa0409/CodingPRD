"""Pre-built role headers for every role in the PRD (§2.1).

`ProgramManager`, `Inspector`, `QAReviewer`, and `AttacherRep` are opaque roles:
their `X-User-ID` is an operator identifier never compared to an entity id, so
the shared constants are canonical. `Contractor` is entity-backed: its
`X-User-ID` IS the acting `ContractorCrew.id`, so any ownership-gated call
(applying a treatment order) MUST use `make_contractor_headers(crew_id)` with
the real crew id — never the shared fallback constant.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    "program_manager_headers": build_user_headers("pm-1", "ProgramManager"),
    "inspector_headers": build_user_headers("insp-1", "Inspector"),
    "qa_reviewer_headers": build_user_headers("qa-1", "QAReviewer"),
    # Fallback for non-ownership calls only (e.g. 404/role-denial probes).
    "contractor_headers": build_user_headers("contractor-unowned", "Contractor"),
    "attacher_rep_headers": build_user_headers("att-9", "AttacherRep"),
}


def make_program_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ProgramManager")


def make_inspector_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Inspector")


def make_qa_reviewer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "QAReviewer")


def make_contractor_headers(user_id: str) -> dict:
    """For Contractor (entity-backed: ContractorCrew). Pass the actual
    ContractorCrew.id as user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Contractor")


def make_attacher_rep_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "AttacherRep")
