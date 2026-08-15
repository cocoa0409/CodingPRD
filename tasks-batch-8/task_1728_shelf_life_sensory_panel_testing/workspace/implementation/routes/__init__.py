from routes import (
    admin, clients, studies, arms, timepoints, chambers, samples, panelists,
    sessions, assignments, scores, labresults, recommendations, reports,
    claims,
)

LAB_BLUEPRINTS = (
    clients.bp,
    studies.bp,
    arms.bp,
    timepoints.bp,
    chambers.bp,
    samples.bp,
    panelists.bp,
    sessions.bp,
    assignments.bp,
    scores.bp,
    labresults.bp,
    recommendations.bp,
    reports.bp,
    claims.bp,
)


def register_routes(app):
    for bp in LAB_BLUEPRINTS:
        app.register_blueprint(bp, url_prefix="/sensory-lab")
    app.register_blueprint(admin.bp)
