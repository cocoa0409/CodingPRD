"""Route blueprints, one module per resource family."""

from routes import (adoptions, catalog, charges, clock, disclosure, enrollments,
                    opt_outs, reconciliation, sections, students, terms)

BLUEPRINTS = (
    clock.bp,
    terms.bp,
    students.bp,
    catalog.bp,
    sections.bp,
    adoptions.bp,
    enrollments.bp,
    charges.bp,
    opt_outs.bp,
    reconciliation.bp,
    disclosure.bp,
)
