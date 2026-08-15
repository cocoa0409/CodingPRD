"""Route blueprints."""
from . import (
    aliases,
    boilers,
    chemistry,
    dispatches,
    fuel,
    incidents,
    inspections,
    log_entries,
    operators,
    plants,
    steam_traps,
)

BLUEPRINTS = [
    plants.bp,
    boilers.bp,
    operators.bp,
    log_entries.bp,
    chemistry.bp,
    inspections.bp,
    steam_traps.bp,
    dispatches.bp,
    incidents.bp,
    fuel.bp,
    aliases.bp,
]
