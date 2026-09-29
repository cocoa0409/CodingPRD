from routes import (
    clock_routes,
    cycles,
    committees,
    proposals,
    analyses,
    comments,
    hearings,
    rules,
    jurisdictions,
    local_amendments,
    interpretations,
    training,
)

BLUEPRINTS = (
    clock_routes.bp,
    cycles.bp,
    committees.bp,
    proposals.bp,
    analyses.bp,
    comments.bp,
    hearings.bp,
    rules.bp,
    jurisdictions.bp,
    local_amendments.bp,
    interpretations.bp,
    training.bp,
)


def register(app):
    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)
