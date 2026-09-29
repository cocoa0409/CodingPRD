"""Blueprint registry."""


def register(app):
    from routes.reads import bp as reads_bp
    from routes.enroll import bp as enroll_bp
    from routes.billing import bp as billing_bp
    from routes.lab import bp as lab_bp
    from routes.clinical import bp as clinical_bp
    from routes.registry import bp as registry_bp
    from routes.tanks import bp as tanks_bp
    from routes.holds import bp as holds_bp
    from routes.ops import bp as ops_bp

    for bp in (reads_bp, enroll_bp, billing_bp, lab_bp, clinical_bp, registry_bp,
               tanks_bp, holds_bp, ops_bp):
        app.register_blueprint(bp)
