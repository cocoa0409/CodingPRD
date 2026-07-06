"""Violation state-machine glue."""


def _noop():
    """Placeholder to keep circular-import discipline; state transitions are
    performed inline in the route handler with cascades running through
    services.homeowner.recompute_owner_and_property."""
    pass
