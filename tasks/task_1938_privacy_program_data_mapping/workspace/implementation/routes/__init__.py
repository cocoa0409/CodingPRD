def register_all(app):
    from routes import (applicability, activities, clock_routes, consumers,
                        notices, reference, transfers, vendors)
    for module in (clock_routes, reference, notices, vendors, activities,
                   consumers, transfers, applicability):
        app.register_blueprint(module.bp)
