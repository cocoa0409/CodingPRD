from routes import (batches, clock, doors, legs, osd, pickup, reports,
                    scans_inspections, shipments, terminals, trailers)

all_blueprints = [
    clock.bp,
    terminals.bp,
    shipments.bp,
    pickup.bp,
    doors.bp,
    batches.bp,
    trailers.bp,
    legs.bp,
    scans_inspections.bp,
    osd.bp,
    reports.bp,
]
