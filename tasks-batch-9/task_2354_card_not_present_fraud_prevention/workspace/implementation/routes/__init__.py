"""Blueprint registry for the aegis-cnp-fraud API."""

from routes import assessments, clock, entities, policy, risk

BLUEPRINTS = (
    clock.bp,
    entities.bp,
    policy.bp,
    assessments.bp,
    risk.bp,
)
