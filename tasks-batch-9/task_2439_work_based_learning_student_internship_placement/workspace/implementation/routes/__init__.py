"""Blueprint registry; every blueprint mounts under the /wbl prefix."""

from routes import (agreements, clock, cycles, incidents, outcomes, partners,
                    placements, plans, students, timesheets)

BLUEPRINTS = (
    clock.bp,
    partners.bp,
    agreements.bp,
    students.bp,
    placements.bp,
    plans.bp,
    timesheets.bp,
    cycles.bp,
    incidents.bp,
    outcomes.bp,
)
