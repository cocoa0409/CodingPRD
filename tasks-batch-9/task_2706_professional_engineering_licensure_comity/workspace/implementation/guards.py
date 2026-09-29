"""Ladder helpers shared by every route module."""
from errors import ApiError
from middleware import actor


def owned_by_caller(owner_id):
    if actor() != owner_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER",
                       "caller does not own the target resource")


def segregation(stamped_user_id):
    """Rung 7: the acting X-User-ID must differ from the stamped operator."""
    if stamped_user_id is not None and actor() == stamped_user_id:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "this operator may not take this action")


def state(condition, error_id, message):
    if not condition:
        raise ApiError(error_id, message)
