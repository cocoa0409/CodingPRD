"""Shared state guards."""
from errors import ApiError


def ensure_not_stabilized(program):
    """PRD §3.9: from STABILIZED nothing further may be mutated."""
    if program["schedule_state"] == "STABILIZED":
        raise ApiError("ERR_INVALID_PROGRAM_STATE",
                       "The program is STABILIZED; no further mutation is permitted.")


def ensure_not_frozen(program):
    """PRD §2.6 / validation tier 9."""
    if program["readiness_posture"] == "FROZEN":
        raise ApiError("ERR_PROGRAM_FROZEN",
                       "The program's readiness posture is FROZEN.")
