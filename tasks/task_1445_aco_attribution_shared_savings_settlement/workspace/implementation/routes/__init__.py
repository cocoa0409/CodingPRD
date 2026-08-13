def register_routes(app):
    from routes import (periods, parties, attribution, claims, quality,
                        finance, settlements, appeals, clock)
    app.register_blueprint(periods.bp)
    app.register_blueprint(parties.bp)
    app.register_blueprint(attribution.bp)
    app.register_blueprint(claims.bp)
    app.register_blueprint(quality.bp)
    app.register_blueprint(finance.bp)
    app.register_blueprint(settlements.bp)
    app.register_blueprint(appeals.bp)
    app.register_blueprint(clock.bp)
