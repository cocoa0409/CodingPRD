"""Blueprint registration."""

from flask import Blueprint


def register_routes(app):
    from routes.owners import owners_bp
    from routes.hearing_officers import officers_bp
    from routes.properties import properties_bp
    from routes.assessments import assessments_bp
    from routes.exemption_applications import exemptions_bp
    from routes.appeals import appeals_bp
    from routes.tax_bills import tax_bills_bp
    from routes.deferral_plans import deferrals_bp
    from routes.clock import clock_bp
    from routes._test_reset import test_reset_bp

    for bp in (
        owners_bp,
        officers_bp,
        properties_bp,
        assessments_bp,
        exemptions_bp,
        appeals_bp,
        tax_bills_bp,
        deferrals_bp,
        clock_bp,
        test_reset_bp,
    ):
        app.register_blueprint(bp)
