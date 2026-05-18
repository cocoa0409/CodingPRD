"""Route registration aggregator."""
from __future__ import annotations

from flask import Flask

from .consumers import bp_consumers
from .credit_freezes import bp_credit_freezes
from .credit_locks import bp_credit_locks
from .credit_reports import bp_credit_reports
from .disputes import bp_disputes
from .furnishers import bp_furnishers
from .hard_inquiries import bp_hard_inquiries
from .regulatory import bp_regulatory
from .result_notices import bp_result_notices
from .system_ops import bp_system_ops
from .tradeline_items import bp_tradeline_items


def register_all_routes(app: Flask) -> None:
    app.register_blueprint(bp_consumers)
    app.register_blueprint(bp_furnishers)
    app.register_blueprint(bp_credit_reports)
    app.register_blueprint(bp_tradeline_items)
    app.register_blueprint(bp_disputes)
    app.register_blueprint(bp_result_notices)
    app.register_blueprint(bp_regulatory)
    app.register_blueprint(bp_credit_freezes)
    app.register_blueprint(bp_credit_locks)
    app.register_blueprint(bp_hard_inquiries)
    app.register_blueprint(bp_system_ops)
