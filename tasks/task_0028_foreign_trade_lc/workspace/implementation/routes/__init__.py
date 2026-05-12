"""Register all route blueprints."""


def register_routes(app):
    from .reference_data import bp as ref_bp
    from .lc import bp as lc_bp
    from .amendments import bp as am_bp
    from .presentations import bp as pres_bp
    from .examinations import bp as exam_bp
    from .settlements import bp as set_bp
    from .reimbursements import bp as reim_bp
    from .swift_messages import bp as swift_bp
    from .external_events import bp as ext_bp
    from .clock import bp as clk_bp

    app.register_blueprint(ref_bp)
    app.register_blueprint(lc_bp)
    app.register_blueprint(am_bp)
    app.register_blueprint(pres_bp)
    app.register_blueprint(exam_bp)
    app.register_blueprint(set_bp)
    app.register_blueprint(reim_bp)
    app.register_blueprint(swift_bp)
    app.register_blueprint(ext_bp)
    app.register_blueprint(clk_bp)
