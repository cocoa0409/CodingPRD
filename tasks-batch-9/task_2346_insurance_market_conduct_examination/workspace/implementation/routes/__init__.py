"""Blueprints for every endpoint of the service, all mounted under /market-conduct."""

from routes.clock import bp as clock_bp
from routes.collaborations import bp as collaborations_bp
from routes.criticisms import bp as criticisms_bp
from routes.cycles import bp as cycles_bp
from routes.data_calls import bp as data_calls_bp
from routes.examinations import bp as examinations_bp
from routes.file_samples import bp as file_samples_bp
from routes.insurers import bp as insurers_bp
from routes.orders import bp as orders_bp
from routes.plans import bp as plans_bp
from routes.scope_areas import bp as scope_areas_bp

BLUEPRINTS = (
    insurers_bp,
    cycles_bp,
    examinations_bp,
    scope_areas_bp,
    data_calls_bp,
    file_samples_bp,
    criticisms_bp,
    plans_bp,
    orders_bp,
    collaborations_bp,
    clock_bp,
)
