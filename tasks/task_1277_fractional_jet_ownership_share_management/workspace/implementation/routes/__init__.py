"""Route registration."""


def register_routes(app):
    from routes.clock import bp as clock_bp
    from routes.programs import bp as programs_bp
    from routes.classes import bp as classes_bp
    from routes.aircraft import bp as aircraft_bp
    from routes.owners import bp as owners_bp
    from routes.shares import bp as shares_bp
    from routes.bookings import bp as bookings_bp
    from routes.invoices import bp as invoices_bp
    from routes.listings import bp as listings_bp
    from routes.maintenance import bp as maintenance_bp
    from routes.exits import bp as exits_bp

    app.register_blueprint(clock_bp)
    app.register_blueprint(programs_bp)
    app.register_blueprint(classes_bp)
    app.register_blueprint(aircraft_bp)
    app.register_blueprint(owners_bp)
    app.register_blueprint(shares_bp)
    app.register_blueprint(bookings_bp)
    app.register_blueprint(invoices_bp)
    app.register_blueprint(listings_bp)
    app.register_blueprint(maintenance_bp)
    app.register_blueprint(exits_bp)
