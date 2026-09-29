"""Blueprint registry."""

from routes import engagements, infra, labor, negotiations, riders, settlements, ticketing

BLUEPRINTS = (
    infra.bp,
    engagements.bp,
    negotiations.bp,
    riders.bp,
    labor.bp,
    ticketing.bp,
    settlements.bp,
)
