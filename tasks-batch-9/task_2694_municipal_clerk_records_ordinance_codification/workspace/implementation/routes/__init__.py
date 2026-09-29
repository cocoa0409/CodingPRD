"""Blueprint registry.  One module per aggregate family."""
from routes.meetings import bp as meetings_bp
from routes.packets import bp as packets_bp
from routes.minutes import bp as minutes_bp
from routes.instruments import bp as instruments_bp
from routes.notices import bp as notices_bp
from routes.codification import bp as codification_bp
from routes.records import bp as records_bp
from routes.retention import bp as retention_bp

blueprints = (
    meetings_bp,
    packets_bp,
    minutes_bp,
    instruments_bp,
    notices_bp,
    codification_bp,
    records_bp,
    retention_bp,
)
