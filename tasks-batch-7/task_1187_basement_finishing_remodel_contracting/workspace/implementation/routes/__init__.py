"""Route registration."""
from routes import (
    anchors, projects, assessments, designs, permits, money, phases, logs,
    inspections, warranty, clock,
)

BLUEPRINTS = [
    anchors.bp, projects.bp, assessments.bp, designs.bp, permits.bp,
    money.bp, phases.bp, logs.bp, inspections.bp, warranty.bp, clock.bp,
]


def register_routes(app):
    for bp in BLUEPRINTS:
        app.register_blueprint(bp)
