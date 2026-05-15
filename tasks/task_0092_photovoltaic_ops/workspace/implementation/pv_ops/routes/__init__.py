"""Flask blueprint registration."""
from __future__ import annotations

from flask import Flask


def register_routes(app: Flask) -> None:
    from pv_ops.routes.ops_hooks import bp as ops_bp
    from pv_ops.routes.equipment import bp as equipment_bp
    from pv_ops.routes.suppliers import bp as suppliers_bp
    from pv_ops.routes.readings import bp as readings_bp
    from pv_ops.routes.alarms import bp as alarms_bp
    from pv_ops.routes.patrols import bp as patrols_bp
    from pv_ops.routes.defects import bp as defects_bp
    from pv_ops.routes.work_orders import bp as work_orders_bp
    from pv_ops.routes.spare_parts import bp as spare_parts_bp
    from pv_ops.routes.settlement import bp as settlement_bp
    from pv_ops.routes.subsidy import bp as subsidy_bp
    from pv_ops.routes.audit import bp as audit_bp

    app.register_blueprint(ops_bp)
    app.register_blueprint(equipment_bp)
    app.register_blueprint(suppliers_bp)
    app.register_blueprint(readings_bp)
    app.register_blueprint(alarms_bp)
    app.register_blueprint(patrols_bp)
    app.register_blueprint(defects_bp)
    app.register_blueprint(work_orders_bp)
    app.register_blueprint(spare_parts_bp)
    app.register_blueprint(settlement_bp)
    app.register_blueprint(subsidy_bp)
    app.register_blueprint(audit_bp)
