"""Route blueprints, one module per PRD workflow section."""

from routes import commerce, compounding, design, lab, masterdata, production, skus

BLUEPRINTS = (
    masterdata.bp,
    compounding.bp,
    design.bp,
    skus.bp,
    lab.bp,
    production.bp,
    commerce.bp,
)

__all__ = ["BLUEPRINTS"]
