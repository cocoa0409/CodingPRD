"""Blueprint registration for all resource groups."""


def register_routes(app):
    from routes.clock import bp as clock_bp
    from routes.productions import bp as productions_bp
    from routes.sequences import bp as sequences_bp
    from routes.assessments import bp as assessments_bp
    from routes.performers import bp as performers_bp
    from routes.certifications import bp as certifications_bp
    from routes.rehearsals import bp as rehearsals_bp
    from routes.meetings import bp as meetings_bp
    from routes.signoffs import bp as signoffs_bp
    from routes.equipment import bp as equipment_bp
    from routes.inspections import bp as inspections_bp
    from routes.permits import bp as permits_bp
    from routes.adjustments import bp as adjustments_bp
    from routes.incidents import bp as incidents_bp
    from routes.executions import bp as executions_bp
    from routes.reviews import bp as reviews_bp

    for bp in (
        clock_bp,
        productions_bp,
        sequences_bp,
        assessments_bp,
        performers_bp,
        certifications_bp,
        rehearsals_bp,
        meetings_bp,
        signoffs_bp,
        equipment_bp,
        inspections_bp,
        permits_bp,
        adjustments_bp,
        incidents_bp,
        executions_bp,
        reviews_bp,
    ):
        app.register_blueprint(bp)
