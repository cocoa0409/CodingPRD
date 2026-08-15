def register_routes(app):
    from routes import (
        catalog,
        clock_api,
        customers,
        exchange,
        invoices,
        lease,
        requisitions,
        test_cells,
        units,
        warranty,
        work_orders,
    )

    for module in (
        customers,
        catalog,
        units,
        work_orders,
        requisitions,
        test_cells,
        exchange,
        lease,
        warranty,
        invoices,
        clock_api,
    ):
        app.register_blueprint(module.bp)
