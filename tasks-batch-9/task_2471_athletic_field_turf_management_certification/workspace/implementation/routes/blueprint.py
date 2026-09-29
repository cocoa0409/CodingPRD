"""The two blueprints: the /turf service and the out-of-band clock route."""

from flask import Blueprint

bp = Blueprint("turf", __name__, url_prefix="/turf")
clock_bp = Blueprint("clock", __name__)
