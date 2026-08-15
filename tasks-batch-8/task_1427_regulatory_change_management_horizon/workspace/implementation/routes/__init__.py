"""Blueprint registration for all route modules."""


def register_routes(app):
    from routes import (audit_events, business_owners, clock,
                        committee_reports, controls, escalations,
                        evidence_packages, gap_analyses, impact_assessments,
                        implementation_plans, mappings, obligations,
                        policy_updates, register, regulatory_changes,
                        training_rollouts)

    app.register_blueprint(clock.bp)
    app.register_blueprint(business_owners.bp)
    app.register_blueprint(regulatory_changes.bp)
    app.register_blueprint(impact_assessments.bp)
    app.register_blueprint(gap_analyses.bp)
    app.register_blueprint(obligations.bp)
    app.register_blueprint(controls.bp)
    app.register_blueprint(mappings.bp)
    app.register_blueprint(register.bp)
    app.register_blueprint(implementation_plans.bp)
    app.register_blueprint(policy_updates.bp)
    app.register_blueprint(training_rollouts.bp)
    app.register_blueprint(evidence_packages.bp)
    app.register_blueprint(escalations.bp)
    app.register_blueprint(committee_reports.bp)
    app.register_blueprint(audit_events.bp)
