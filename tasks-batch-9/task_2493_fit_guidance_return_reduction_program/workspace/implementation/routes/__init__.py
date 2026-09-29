"""Flask blueprints, one module per resource family."""

from routes.cases import bp as cases_bp
from routes.charts import bp as charts_bp
from routes.clock_control import bp as clock_bp
from routes.customers import bp as customers_bp
from routes.feedback import bp as feedback_bp
from routes.interventions import bp as interventions_bp
from routes.items import bp as items_bp
from routes.mappings import bp as mappings_bp
from routes.ops_runs import bp as ops_runs_bp
from routes.order_lines import bp as order_lines_bp
from routes.policies import bp as policies_bp
from routes.specs import bp as specs_bp
from routes.vendors import bp as vendors_bp

ALL_BLUEPRINTS = (
    vendors_bp,
    items_bp,
    specs_bp,
    charts_bp,
    mappings_bp,
    customers_bp,
    policies_bp,
    order_lines_bp,
    cases_bp,
    feedback_bp,
    interventions_bp,
    ops_runs_bp,
    clock_bp,
)
