"""Route registration."""


def register_routes(app):
    from routes.students import bp as students_bp
    from routes.recipients import bp as recipients_bp
    from routes.holds import bp as holds_bp
    from routes.identity import bp as identity_bp
    from routes.orders import bp as orders_bp
    from routes.line_items import bp as line_items_bp
    from routes.payments import bp as payments_bp
    from routes.consent import bp as consent_bp
    from routes.verification import bp as verification_bp
    from routes.retrievals import bp as retrievals_bp
    from routes.reissues import bp as reissues_bp
    from routes.clearinghouse import bp as clearinghouse_bp
    from routes.admin import bp as admin_bp

    app.register_blueprint(students_bp)
    app.register_blueprint(recipients_bp)
    app.register_blueprint(holds_bp)
    app.register_blueprint(identity_bp)
    app.register_blueprint(orders_bp)
    app.register_blueprint(line_items_bp)
    app.register_blueprint(payments_bp)
    app.register_blueprint(consent_bp)
    app.register_blueprint(verification_bp)
    app.register_blueprint(retrievals_bp)
    app.register_blueprint(reissues_bp)
    app.register_blueprint(clearinghouse_bp)
    app.register_blueprint(admin_bp)
