"""Route registration."""


def register_routes(app):
    from routes.staff import bp as staff_bp
    from routes.cases import bp as cases_bp
    from routes.assignments import bp as assignments_bp
    from routes.interviews import bp as interviews_bp
    from routes.evidence import bp as evidence_bp
    from routes.determinations import bp as determinations_bp
    from routes.remediation import bp as remediation_bp
    from routes.monitoring import bp as monitoring_bp
    from routes.retaliation import bp as retaliation_bp
    from routes.holds import bp as holds_bp
    from routes.reports import bp as reports_bp
    from routes.misc import bp as misc_bp

    app.register_blueprint(staff_bp)
    app.register_blueprint(cases_bp)
    app.register_blueprint(assignments_bp)
    app.register_blueprint(interviews_bp)
    app.register_blueprint(evidence_bp)
    app.register_blueprint(determinations_bp)
    app.register_blueprint(remediation_bp)
    app.register_blueprint(monitoring_bp)
    app.register_blueprint(retaliation_bp)
    app.register_blueprint(holds_bp)
    app.register_blueprint(reports_bp)
    app.register_blueprint(misc_bp)
