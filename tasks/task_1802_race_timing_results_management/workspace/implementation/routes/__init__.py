def register_blueprints(app):
    from . import (
        clock_routes,
        races,
        waves,
        timing_points,
        registrations,
        chips,
        timing_reads,
        results,
        result_flags,
        protests,
        corrections,
    )

    for mod in (
        clock_routes,
        races,
        waves,
        timing_points,
        registrations,
        chips,
        timing_reads,
        results,
        result_flags,
        protests,
        corrections,
    ):
        app.register_blueprint(mod.bp)
