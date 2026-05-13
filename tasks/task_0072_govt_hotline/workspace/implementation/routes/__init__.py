"""Route registration. Imports each blueprint and attaches it to the Flask app."""


def register_routes(app):
    from routes.departments import bp as departments_bp
    from routes.handlers import bp as handlers_bp
    from routes.category_rules import bp as category_rules_bp
    from routes.work_orders import bp as work_orders_bp
    from routes.assignments import bp as assignments_bp
    from routes.surveys import bp as surveys_bp
    from routes.supervision import bp as supervision_bp
    from routes.stats import bp as stats_bp
    from routes.audit import bp as audit_bp
    from routes.sync_events import bp as sync_events_bp
    from routes.admin import bp as admin_bp

    app.register_blueprint(departments_bp)
    app.register_blueprint(handlers_bp)
    app.register_blueprint(category_rules_bp)
    app.register_blueprint(work_orders_bp)
    app.register_blueprint(assignments_bp)
    app.register_blueprint(surveys_bp)
    app.register_blueprint(supervision_bp)
    app.register_blueprint(stats_bp)
    app.register_blueprint(audit_bp)
    app.register_blueprint(sync_events_bp)
    app.register_blueprint(admin_bp)
