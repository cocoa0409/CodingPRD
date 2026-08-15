from routes import (
    departments,
    fiscal_periods,
    taxonomy,
    firms,
    counsel,
    matters,
    assignments,
    budgets,
    accruals,
    invoices,
    spend_lines,
    dashboards,
    reports,
    clock_routes,
)


def register_blueprints(app):
    for mod in (
        departments,
        fiscal_periods,
        taxonomy,
        firms,
        counsel,
        matters,
        assignments,
        budgets,
        accruals,
        invoices,
        spend_lines,
        dashboards,
        reports,
        clock_routes,
    ):
        app.register_blueprint(mod.bp)
