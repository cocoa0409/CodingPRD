"""Blueprint registry."""

from routes import (actions, cases, logbook, ops, people, plans, reports,
                   worksites)

BLUEPRINTS = (
    worksites.bp,
    plans.bp,
    people.bp,
    reports.bp,
    cases.bp,
    actions.bp,
    logbook.bp,
    ops.bp,
)
