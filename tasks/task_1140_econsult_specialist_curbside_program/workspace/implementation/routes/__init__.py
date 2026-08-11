def register_routes(app):
    from routes import (
        admin,
        panel,
        consults,
        responses,
        reviews,
        conversions,
        claims,
        measurements,
    )
    for module in (admin, panel, consults, responses, reviews, conversions, claims, measurements):
        app.register_blueprint(module.bp)
