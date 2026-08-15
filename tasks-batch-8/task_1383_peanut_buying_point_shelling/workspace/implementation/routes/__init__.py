"""Route blueprints."""
from routes import core, intake, ops, finance, shelling

ALL_BLUEPRINTS = [
    core.bp,
    intake.bp,
    ops.bp,
    finance.bp,
    shelling.bp,
]
