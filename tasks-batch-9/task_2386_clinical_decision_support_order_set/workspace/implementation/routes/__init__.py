"""Blueprint registration for the whole governance surface."""
from routes import (adherence, alerts, annual_review, clinicians, content_requests,
                    downtime, ops, order_sets, review_assignments, vendor)

BLUEPRINTS = (
    clinicians.bp,
    content_requests.bp,
    order_sets.bp,
    review_assignments.bp,
    alerts.bp,
    vendor.bp,
    downtime.bp,
    adherence.bp,
    annual_review.bp,
    ops.bp,
)


def register_routes(app):
    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)
