"""Election posture as the master gate (PRD 2.5)."""
from constants import POSTURES
from errors import ApiError


def require(election_rec, allowed):
    if election_rec is None:
        raise ApiError("ERR_ELECTION_POSTURE_FORBIDS")
    if election_rec["posture"] not in allowed:
        raise ApiError("ERR_ELECTION_POSTURE_FORBIDS")


def require_not_certified(election_rec):
    """Once CERTIFIED no mutating child operation of the election is permitted."""
    if election_rec is not None and election_rec["posture"] == "CERTIFIED":
        raise ApiError("ERR_ELECTION_POSTURE_FORBIDS")


def successor(posture):
    idx = POSTURES.index(posture)
    if idx + 1 >= len(POSTURES):
        return None
    return POSTURES[idx + 1]
