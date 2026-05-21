"""Travel & Expense Reimbursement API server entry point."""
from __future__ import annotations

import os

from flask import Flask

from core.envelope import register_error_handlers
from routes.employees import bp as employees_bp
from routes.expense_lines import bp as expense_lines_bp
from routes.expense_reports import bp as expense_reports_bp
from routes.oop_approvals import bp as oop_approvals_bp
from routes.per_diem_rates import bp as per_diem_rates_bp
from routes.receipts import bp as receipts_bp
from routes.system import bp as system_bp
from routes.trips import bp as trips_bp
from routes.virtual_cards import bp as virtual_cards_bp


def create_app() -> Flask:
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(employees_bp)
    app.register_blueprint(per_diem_rates_bp)
    app.register_blueprint(trips_bp)
    app.register_blueprint(virtual_cards_bp)
    app.register_blueprint(expense_reports_bp)
    app.register_blueprint(expense_lines_bp)
    app.register_blueprint(receipts_bp)
    app.register_blueprint(oop_approvals_bp)
    app.register_blueprint(system_bp)

    register_error_handlers(app)
    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
