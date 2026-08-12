"""Route blueprints."""
from routes import (
    cases, assessments, quotes, funding, jobs, rentals, inventory,
    inspections, invoices, claims, ot, schedules, clock,
)

ALL_BLUEPRINTS = [
    cases.bp,
    assessments.bp,
    quotes.bp,
    funding.bp,
    jobs.bp,
    rentals.bp,
    inventory.bp,
    inspections.bp,
    invoices.bp,
    claims.bp,
    ot.bp,
    schedules.bp,
    clock.bp,
]
