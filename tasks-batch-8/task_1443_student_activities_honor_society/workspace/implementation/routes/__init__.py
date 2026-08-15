"""Blueprint registration."""

from routes import (athletics, chapters, clock, cycles, dues_probation,
                    elections, entries, flat, funds, members, roles_minutes)

ALL_BLUEPRINTS = (
    clock.bp,
    chapters.bp,
    members.bp,
    cycles.bp,
    entries.bp,
    elections.bp,
    roles_minutes.bp,
    funds.bp,
    dues_probation.bp,
    athletics.bp,
    flat.bp,
)
