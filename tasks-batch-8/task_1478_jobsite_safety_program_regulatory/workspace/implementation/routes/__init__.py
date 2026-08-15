from flask import Blueprint


def register_routes(app):
    from . import (
        clock,
        projects,
        plans,
        workers,
        certificates,
        subcontractors,
        huddles,
        jhas,
        inspections,
        deficiencies,
        incidents,
        permits,
        drugtests,
    )

    for mod in (
        clock,
        projects,
        plans,
        workers,
        certificates,
        subcontractors,
        huddles,
        jhas,
        inspections,
        deficiencies,
        incidents,
        permits,
        drugtests,
    ):
        app.register_blueprint(mod.bp)
