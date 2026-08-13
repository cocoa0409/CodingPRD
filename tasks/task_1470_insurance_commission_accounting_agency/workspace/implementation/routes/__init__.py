"""Route registration."""


def register_routes(app):
    from routes.clock import bp as clock_bp
    from routes.producers import bp as producers_bp
    from routes.payouts import bp as payouts_bp
    from routes.carriers import bp as carriers_bp
    from routes.products import bp as products_bp
    from routes.schedules import bp as schedules_bp
    from routes.policies import bp as policies_bp
    from routes.invoices import bp as invoices_bp
    from routes.statements import bp as statements_bp
    from routes.entries import bp as entries_bp
    from routes.chargebacks import bp as chargebacks_bp
    from routes.disclosures import bp as disclosures_bp
    from routes.taxforms import bp as taxforms_bp

    app.register_blueprint(clock_bp)
    app.register_blueprint(producers_bp)
    app.register_blueprint(payouts_bp)
    app.register_blueprint(carriers_bp)
    app.register_blueprint(products_bp)
    app.register_blueprint(schedules_bp)
    app.register_blueprint(policies_bp)
    app.register_blueprint(invoices_bp)
    app.register_blueprint(statements_bp)
    app.register_blueprint(entries_bp)
    app.register_blueprint(chargebacks_bp)
    app.register_blueprint(disclosures_bp)
    app.register_blueprint(taxforms_bp)
