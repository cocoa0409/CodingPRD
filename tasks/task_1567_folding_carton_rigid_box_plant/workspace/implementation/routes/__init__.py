"""Blueprint registry."""

from routes import (
    board_stocks,
    clock,
    color_standards,
    customers,
    design_revisions,
    finishing_bookings,
    finishing_lines,
    imposition_plans,
    invoices,
    jobs,
    kit_orders,
    press_approvals,
    press_bookings,
    presses,
    retail_audits,
)

ALL_BLUEPRINTS = (
    customers.bp,
    color_standards.bp,
    jobs.bp,
    design_revisions.bp,
    imposition_plans.bp,
    press_approvals.bp,
    presses.bp,
    press_bookings.bp,
    finishing_lines.bp,
    finishing_bookings.bp,
    board_stocks.bp,
    kit_orders.bp,
    retail_audits.bp,
    invoices.bp,
    clock.bp,
)
