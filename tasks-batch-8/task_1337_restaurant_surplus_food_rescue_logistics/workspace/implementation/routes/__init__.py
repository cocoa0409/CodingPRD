"""Route registration."""


def register_routes(app):
    from routes.clock import bp as clock_bp
    from routes.donors import bp as donors_bp
    from routes.agencies import bp as agencies_bp
    from routes.drivers import bp as drivers_bp
    from routes.coolers import bp as coolers_bp
    from routes.offers import bp as offers_bp
    from routes.runs import bp as runs_bp
    from routes.strikes import bp as strikes_bp
    from routes.rate_cards import bp as rate_cards_bp

    app.register_blueprint(clock_bp)
    app.register_blueprint(donors_bp)
    app.register_blueprint(agencies_bp)
    app.register_blueprint(drivers_bp)
    app.register_blueprint(coolers_bp)
    app.register_blueprint(offers_bp)
    app.register_blueprint(runs_bp)
    app.register_blueprint(strikes_bp)
    app.register_blueprint(rate_cards_bp)
