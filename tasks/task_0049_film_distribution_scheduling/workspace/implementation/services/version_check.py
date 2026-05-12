"""Optimistic concurrency version check + idempotency helper."""

from errors import (
    ERR_VERSION_CONFLICT,
    ERR_DUPLICATE_OPERATION,
    raise_error,
)


def check_version(entity_version, requested_version):
    """If requested_version is provided and != current, raise ERR_VERSION_CONFLICT.
    Returns nothing.
    """
    if requested_version is None:
        return
    if not isinstance(requested_version, int) or isinstance(requested_version, bool):
        from errors import ERR_BAD_REQUEST
        raise_error(ERR_BAD_REQUEST, "version must be integer")
    if requested_version != entity_version:
        raise_error(ERR_VERSION_CONFLICT, "version conflict")


def check_idempotent_action(entity_version, requested_version, already_in_target_state):
    """If client passed an older version AND the entity has already advanced past that
    state (the action has already been applied), return ERR_DUPLICATE_OPERATION.

    Specifically: if requested_version < entity_version and already_in_target_state,
    raise ERR_DUPLICATE_OPERATION. If requested_version mismatches and not already
    in target state, raise ERR_VERSION_CONFLICT (handled by check_version).
    """
    if requested_version is None:
        return
    if not isinstance(requested_version, int) or isinstance(requested_version, bool):
        from errors import ERR_BAD_REQUEST
        raise_error(ERR_BAD_REQUEST, "version must be integer")
    if requested_version == entity_version:
        return  # all good
    if requested_version < entity_version and already_in_target_state:
        raise_error(ERR_DUPLICATE_OPERATION, "duplicate operation")
    raise_error(ERR_VERSION_CONFLICT, "version conflict")
