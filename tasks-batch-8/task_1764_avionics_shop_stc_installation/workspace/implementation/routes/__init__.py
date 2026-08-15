from routes.clock_routes import bp as clock_bp
from routes.customers import bp as customers_bp
from routes.aircraft import bp as aircraft_bp
from routes.work_orders import bp as work_orders_bp
from routes.panel_designs import bp as panel_designs_bp
from routes.equipment_orders import bp as equipment_orders_bp
from routes.install_tasks import bp as install_tasks_bp
from routes.test_events import bp as test_events_bp
from routes.regulatory_packages import bp as regulatory_packages_bp
from routes.weight_balance import bp as weight_balance_bp

ALL_BLUEPRINTS = [
    clock_bp,
    customers_bp,
    aircraft_bp,
    work_orders_bp,
    panel_designs_bp,
    equipment_orders_bp,
    install_tasks_bp,
    test_events_bp,
    regulatory_packages_bp,
    weight_balance_bp,
]
