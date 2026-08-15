from routes import (
    agreements,
    bookings,
    car_assignments,
    clock,
    crew_assignments,
    crew_members,
    excursions,
    manifests,
    rain_checks,
    rolling_stock,
    slots,
    work_orders,
)


def all_blueprints():
    return [
        clock.bp,
        agreements.bp,
        slots.bp,
        rolling_stock.bp,
        work_orders.bp,
        excursions.bp,
        car_assignments.bp,
        bookings.bp,
        crew_members.bp,
        crew_assignments.bp,
        manifests.bp,
        rain_checks.bp,
    ]
