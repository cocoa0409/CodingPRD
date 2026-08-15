"""Route registration."""


def register_routes(app):
    from routes.license_types import bp as license_types_bp
    from routes.role_requirements import bp as role_requirements_bp
    from routes.employees import bp as employees_bp
    from routes.licenses import bp as licenses_bp
    from routes.ce_activities import bp as ce_activities_bp
    from routes.renewal_requests import bp as renewal_requests_bp
    from routes.disciplinary_events import bp as disciplinary_events_bp
    from routes.exclusion_screenings import bp as exclusion_screenings_bp
    from routes.audit_packages import bp as audit_packages_bp
    from routes.reports import bp as reports_bp
    from routes.clock import bp as clock_bp

    app.register_blueprint(license_types_bp)
    app.register_blueprint(role_requirements_bp)
    app.register_blueprint(employees_bp)
    app.register_blueprint(licenses_bp)
    app.register_blueprint(ce_activities_bp)
    app.register_blueprint(renewal_requests_bp)
    app.register_blueprint(disciplinary_events_bp)
    app.register_blueprint(exclusion_screenings_bp)
    app.register_blueprint(audit_packages_bp)
    app.register_blueprint(reports_bp)
    app.register_blueprint(clock_bp)
