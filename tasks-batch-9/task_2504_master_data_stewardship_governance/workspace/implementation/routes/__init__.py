"""Flask blueprints, one module per top-level collection."""

from routes import (change_requests, clock, consumer_subscriptions, domains,
                    master_records, merge_proposals, quality_findings,
                    quality_rules, scorecard_runs, source_registrations,
                    source_systems, steward_assignments, stewards)

BLUEPRINTS = (
    domains.bp,
    source_systems.bp,
    stewards.bp,
    source_registrations.bp,
    steward_assignments.bp,
    quality_rules.bp,
    scorecard_runs.bp,
    quality_findings.bp,
    master_records.bp,
    merge_proposals.bp,
    change_requests.bp,
    consumer_subscriptions.bp,
    clock.bp,
)
