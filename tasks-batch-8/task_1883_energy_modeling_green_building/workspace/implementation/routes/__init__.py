"""Route registration."""


def register_routes(app):
    from routes.clock import bp as clock_bp
    from routes.team_members import bp as team_members_bp
    from routes.credit_library import bp as credit_library_bp
    from routes.projects import bp as projects_bp
    from routes.energy_models import bp as energy_models_bp
    from routes.credit_attempts import bp as credit_attempts_bp
    from routes.review_comments import bp as review_comments_bp
    from routes.commissioning import bp as commissioning_bp
    from routes.incentives import bp as incentives_bp
    from routes.analyses import bp as analyses_bp
    from routes.performance_reports import bp as performance_reports_bp

    app.register_blueprint(clock_bp)
    app.register_blueprint(team_members_bp)
    app.register_blueprint(credit_library_bp)
    app.register_blueprint(projects_bp)
    app.register_blueprint(energy_models_bp)
    app.register_blueprint(credit_attempts_bp)
    app.register_blueprint(review_comments_bp)
    app.register_blueprint(commissioning_bp)
    app.register_blueprint(incentives_bp)
    app.register_blueprint(analyses_bp)
    app.register_blueprint(performance_reports_bp)
