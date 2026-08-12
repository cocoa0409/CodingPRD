"""Route registration."""


def register_routes(app):
    from routes.projects import bp as projects_bp
    from routes.packages import bp as packages_bp
    from routes.bids import bp as bids_bp
    from routes.gaps import bp as gaps_bp
    from routes.subcontracts import bp as subcontracts_bp
    from routes.compliance import bp as compliance_bp
    from routes.sov import bp as sov_bp
    from routes.change_orders import bp as change_orders_bp

    app.register_blueprint(projects_bp)
    app.register_blueprint(packages_bp)
    app.register_blueprint(bids_bp)
    app.register_blueprint(gaps_bp)
    app.register_blueprint(subcontracts_bp)
    app.register_blueprint(compliance_bp)
    app.register_blueprint(sov_bp)
    app.register_blueprint(change_orders_bp)
