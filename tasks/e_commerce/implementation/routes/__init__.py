def register_routes(app):
    from .shops import bp as shops_bp
    from .products import bp as products_bp
    from .promotions import bp as promotions_bp
    from .orders import orders_bp
    from .refunds import refunds_bp
    from .settlements import settlements_bp
    app.register_blueprint(shops_bp)
    app.register_blueprint(products_bp)
    app.register_blueprint(promotions_bp)
    app.register_blueprint(orders_bp)
    app.register_blueprint(refunds_bp)
    app.register_blueprint(settlements_bp)
