"""Route registration."""


def register_routes(app):
    from routes.ops import bp as ops_bp
    from routes.clients import bp as clients_bp
    from routes.banners import bp as banners_bp
    from routes.compliance import bp as compliance_bp
    from routes.slots import bp as slots_bp
    from routes.billing import bp as billing_bp

    app.register_blueprint(ops_bp)
    app.register_blueprint(clients_bp)
    app.register_blueprint(banners_bp)
    app.register_blueprint(compliance_bp)
    app.register_blueprint(slots_bp)
    app.register_blueprint(billing_bp)
