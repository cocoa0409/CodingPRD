"""Airline Frequent Flyer API — Flask application factory."""

from flask import Flask, request

from .errors import register_error_handlers
from .routes.clock import clock_bp
from .routes.members import members_bp
from .routes.flights import flights_bp
from .routes.segments import segments_bp
from .routes.upgrade_requests import upgrade_requests_bp
from .routes.award_bookings import award_bookings_bp
from .routes.certificates import certificates_bp
from .routes.status_match import status_match_bp
from .routes.gifts import gifts_bp
from .routes.ledger_routes import ledger_bp
from .routes.membership_years import membership_years_bp
from .routes.sweeps import sweeps_bp
from .store import store


def create_app() -> Flask:
    app = Flask(__name__)
    app.json.sort_keys = False

    register_error_handlers(app)

    # PRD §2.11: critical-section serialisation. The single shared
    # in-memory store has only one writer at a time so the check-then-
    # mutate sequences (flight cancel vs confirm, gift idempotency,
    # upgrade-inventory decrement, status-match cooling-off flip) act
    # atomically on the shared state.
    @app.before_request
    def _acquire_store_lock():
        if request.method != "GET":
            store.lock.acquire()

    @app.teardown_request
    def _release_store_lock(exc):
        if request.method != "GET":
            try:
                store.lock.release()
            except RuntimeError:
                pass

    # Test-only reset endpoint so the conftest can wipe state between
    # tests without leaking entities across test cases.
    @app.post("/__test__/reset")
    def _reset_state():
        with store.lock:
            store.members.clear()
            store.flights.clear()
            store.segments.clear()
            store.points_transactions.clear()
            store.upgrade_requests.clear()
            store.award_bookings.clear()
            store.companion_certificates.clear()
            store.status_match_requests.clear()
            store.membership_years.clear()
            store.waitlist_seq_by_flight_cabin.clear()
            store.member_email_index.clear()
            store.gift_idempotency.clear()
            store._ins_seq = 0
        # Reset the logical clock so each test starts at real wall time.
        from .timeutil import clock
        clock._pinned = None
        return {"ok": True}, 200

    app.register_blueprint(clock_bp)
    app.register_blueprint(members_bp)
    app.register_blueprint(flights_bp)
    app.register_blueprint(segments_bp)
    app.register_blueprint(upgrade_requests_bp)
    app.register_blueprint(award_bookings_bp)
    app.register_blueprint(certificates_bp)
    app.register_blueprint(status_match_bp)
    app.register_blueprint(gifts_bp)
    app.register_blueprint(ledger_bp)
    app.register_blueprint(membership_years_bp)
    app.register_blueprint(sweeps_bp)

    return app
