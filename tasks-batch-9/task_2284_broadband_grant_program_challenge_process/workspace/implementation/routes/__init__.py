"""Blueprint registration."""

from routes import (applications, awards, challenges, clock, compliance_audits,
                    environmental_reviews, location_claims, locations, milestones,
                    programs, score_sheets, subgrantees)

BLUEPRINTS = (
    clock.bp,
    programs.bp,
    locations.bp,
    challenges.bp,
    subgrantees.bp,
    applications.bp,
    location_claims.bp,
    score_sheets.bp,
    awards.bp,
    environmental_reviews.bp,
    milestones.bp,
    compliance_audits.bp,
)


def register_all(app):
    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)
