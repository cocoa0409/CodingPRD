"""Route registration."""


def register_routes(app):
    from routes.clock import bp as clock_bp
    from routes.rodeos import bp as rodeos_bp
    from routes.rodeo_events import bp as rodeo_events_bp
    from routes.performances import bp as performances_bp
    from routes.contestants import bp as contestants_bp
    from routes.stock import contracts_bp as contracts_bp, animals_bp as animals_bp
    from routes.judges import judges_bp as judges_bp, assignments_bp as assignments_bp
    from routes.entries import bp as entries_bp
    from routes.draw_assignments import bp as draw_assignments_bp
    from routes.run_results import bp as run_results_bp
    from routes.payouts import bp as payouts_bp
    from routes.vet_reports import bp as vet_reports_bp
    from routes.ticket_orders import bp as ticket_orders_bp

    app.register_blueprint(clock_bp)
    app.register_blueprint(rodeos_bp)
    app.register_blueprint(rodeo_events_bp)
    app.register_blueprint(performances_bp)
    app.register_blueprint(contestants_bp)
    app.register_blueprint(contracts_bp)
    app.register_blueprint(animals_bp)
    app.register_blueprint(judges_bp)
    app.register_blueprint(assignments_bp)
    app.register_blueprint(entries_bp)
    app.register_blueprint(draw_assignments_bp)
    app.register_blueprint(run_results_bp)
    app.register_blueprint(payouts_bp)
    app.register_blueprint(vet_reports_bp)
    app.register_blueprint(ticket_orders_bp)
