"""Blueprint registry."""

from routes import (agreements, enforcement_actions, payments, pre_clearances,
                   programs, registry)

BLUEPRINTS = [
    programs.bp,
    registry.bp,
    pre_clearances.bp,
    agreements.bp,
    payments.bp,
    enforcement_actions.bp,
]
