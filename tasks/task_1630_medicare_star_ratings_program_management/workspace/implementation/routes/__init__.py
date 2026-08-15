"""Route registration."""

from routes import (
    care_gaps,
    clock,
    complaint_cases,
    cutpoint_sets,
    incentive_payouts,
    measure_performances,
    measures,
    members,
    provider_groups,
    rating_cycles,
    rating_forecasts,
    survey_vendors,
    survey_waves,
)


def register_routes(app):
    clock.register(app)
    rating_cycles.register(app)
    measures.register(app)
    cutpoint_sets.register(app)
    measure_performances.register(app)
    members.register(app)
    care_gaps.register(app)
    provider_groups.register(app)
    incentive_payouts.register(app)
    survey_vendors.register(app)
    survey_waves.register(app)
    complaint_cases.register(app)
    rating_forecasts.register(app)
