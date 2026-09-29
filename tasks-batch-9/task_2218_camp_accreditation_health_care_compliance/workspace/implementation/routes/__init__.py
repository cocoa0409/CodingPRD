"""Blueprint package: one module per aggregate."""

from routes import (
    assignments,
    camps,
    clock_control,
    cycles,
    deficiencies,
    evaluations,
    medications,
    plans,
    reports,
    standards,
    visitors,
    visits,
)

BLUEPRINTS = (
    camps.bp,
    standards.bp,
    cycles.bp,
    evaluations.bp,
    plans.bp,
    visitors.bp,
    visits.bp,
    assignments.bp,
    deficiencies.bp,
    medications.bp,
    reports.bp,
    clock_control.bp,
)
