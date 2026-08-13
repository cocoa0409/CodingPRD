"""Route registration."""


def register_routes(app):
    from routes.clock import bp as clock_bp
    from routes.systems import bp as systems_bp
    from routes.campuses import bp as campuses_bp
    from routes.standards import bp as standards_bp
    from routes.terms import bp as terms_bp
    from routes.ratings import bp as ratings_bp
    from routes.evidence import bp as evidence_bp
    from routes.surveys import bp as surveys_bp
    from routes.goals import bp as goals_bp
    from routes.reviewers import bp as reviewers_bp
    from routes.visits import bp as visits_bp
    from routes.findings import bp as findings_bp
    from routes.action_items import bp as action_items_bp
    from routes.interim_reports import bp as interim_reports_bp
    from routes.fees import bp as fees_bp
    from routes.invoices import bp as invoices_bp

    for bp in (
        clock_bp,
        systems_bp,
        campuses_bp,
        standards_bp,
        terms_bp,
        ratings_bp,
        evidence_bp,
        surveys_bp,
        goals_bp,
        reviewers_bp,
        visits_bp,
        findings_bp,
        action_items_bp,
        interim_reports_bp,
        fees_bp,
        invoices_bp,
    ):
        app.register_blueprint(bp)
