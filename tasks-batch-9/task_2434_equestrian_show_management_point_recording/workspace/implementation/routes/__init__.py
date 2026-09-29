"""Blueprint registry."""

from routes.classes import bp as classes_bp
from routes.entries import bp as entries_bp
from routes.grounds import bp as grounds_bp
from routes.reads import bp as reads_bp
from routes.registry import bp as registry_bp
from routes.shows import bp as shows_bp

BLUEPRINTS = (
    reads_bp,
    shows_bp,
    grounds_bp,
    classes_bp,
    entries_bp,
    registry_bp,
)
