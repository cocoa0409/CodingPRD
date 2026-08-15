"""Pre-built role headers for every role in the PRD (section 2.1).

All five roles are opaque: X-User-ID is an operator identifier that the server
records for audit but never compares to any entity id. Shared constants are
therefore the canonical form. A second RightOfWayAgent identity is provided so
that offer tender/counter flows never involve the offer's creator, keeping
those flows independent of the segregation-of-duties rule in PRD section 3.5.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    "row_agent_headers": build_user_headers("row-agent-1", "RightOfWayAgent"),
    "row_agent_creator_headers": build_user_headers("row-agent-creator-1", "RightOfWayAgent"),
    "title_examiner_headers": build_user_headers("examiner-1", "TitleExaminer"),
    "vegetation_inspector_headers": build_user_headers("inspector-1", "VegetationInspector"),
    "litigation_counsel_headers": build_user_headers("counsel-1", "LitigationCounsel"),
    "department_director_headers": build_user_headers("director-1", "DepartmentDirector"),
}

# Convenience aliases.
ROW_AGENT = TEST_USERS["row_agent_headers"]
ROW_AGENT_CREATOR = TEST_USERS["row_agent_creator_headers"]
TITLE_EXAMINER = TEST_USERS["title_examiner_headers"]
VEGETATION_INSPECTOR = TEST_USERS["vegetation_inspector_headers"]
LITIGATION_COUNSEL = TEST_USERS["litigation_counsel_headers"]
DEPARTMENT_DIRECTOR = TEST_USERS["department_director_headers"]


def make_row_agent_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "RightOfWayAgent")


def make_title_examiner_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "TitleExaminer")


def make_vegetation_inspector_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "VegetationInspector")


def make_litigation_counsel_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "LitigationCounsel")


def make_department_director_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "DepartmentDirector")
