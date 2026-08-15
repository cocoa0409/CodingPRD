"""Shared state-transition guard (PRD §2.9 step 6).

A transition attempted on a resource already in a terminal state of its
lifecycle is reported as ERR_ALREADY_TERMINAL (HTTP 409); a transition from
a non-terminal but wrong from-state is ERR_INVALID_STATE (HTTP 409).
"""

from errors import ApiError, ERR_INVALID_STATE, ERR_ALREADY_TERMINAL


def guard_transition(entity, required_from, terminal_states, label="resource"):
    """Ensure entity.status is one of required_from.

    required_from may be a string or a collection of strings.
    """
    status = entity["status"]
    if isinstance(required_from, str):
        required = {required_from}
    else:
        required = set(required_from)
    if status in required:
        return
    if status in terminal_states:
        raise ApiError(
            ERR_ALREADY_TERMINAL,
            f"Attempted transition on a {label} already in terminal state {status}",
            409,
        )
    raise ApiError(
        ERR_INVALID_STATE,
        f"{label.capitalize()} is in state {status}, not in required state(s) "
        + ", ".join(sorted(required)),
        409,
    )
