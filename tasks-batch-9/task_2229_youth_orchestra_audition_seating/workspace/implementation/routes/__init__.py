"""Blueprint registry."""

from routes import (auditions, clock, ensembles, events, members, placements,
                    seasons, tuition)

BLUEPRINTS = (
    clock.bp,
    seasons.bp,
    ensembles.bp,
    members.bp,
    auditions.bp,
    placements.bp,
    tuition.bp,
    events.bp,
)
