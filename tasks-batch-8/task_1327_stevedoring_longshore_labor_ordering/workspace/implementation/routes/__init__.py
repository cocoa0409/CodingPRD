"""Route blueprint registry."""
from routes import (
    assignments, claims, equipment, gangs, invoices, moves, safety, shifts,
    timesheets, vessels, workers,
)

BLUEPRINTS = (
    vessels.bp,
    shifts.bp,
    gangs.bp,
    workers.bp,
    assignments.bp,
    equipment.bp,
    moves.bp,
    claims.bp,
    safety.bp,
    timesheets.bp,
    invoices.bp,
)


def register(app):
    for bp in BLUEPRINTS:
        app.register_blueprint(bp)
