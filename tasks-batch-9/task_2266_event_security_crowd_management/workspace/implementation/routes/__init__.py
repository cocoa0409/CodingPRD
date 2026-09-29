"""Blueprint registry.

Everything except the clock control is mounted under the /event-security prefix.
"""

from routes import (
    assessments,
    assignments,
    clock,
    events,
    guards,
    incidents,
    lanes,
    plans,
    posts,
    readings,
    reviews,
    vendors,
    venues,
)

API_PREFIX = "/event-security"

PREFIXED_BLUEPRINTS = (
    venues.bp,
    events.bp,
    assessments.bp,
    plans.bp,
    posts.bp,
    vendors.bp,
    guards.bp,
    assignments.bp,
    lanes.bp,
    readings.bp,
    incidents.bp,
    reviews.bp,
)

ROOT_BLUEPRINTS = (clock.bp,)


def register(app):
    for blueprint in PREFIXED_BLUEPRINTS:
        app.register_blueprint(blueprint, url_prefix=API_PREFIX)
    for blueprint in ROOT_BLUEPRINTS:
        app.register_blueprint(blueprint)
