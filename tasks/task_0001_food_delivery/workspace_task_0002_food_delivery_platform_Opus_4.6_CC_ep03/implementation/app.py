import os
from flask import Flask
from models.database import db


def create_app():
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///delivery.db'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    db.init_app(app)

    from routes.restaurants import bp as restaurants_bp
    from routes.riders import bp as riders_bp
    from routes.customers import bp as customers_bp
    from routes.orders import bp as orders_bp
    from routes.assignments import bp as assignments_bp
    from routes.returns import bp as returns_bp
    from routes.fines import bp as fines_bp
    from routes.work_orders import bp as work_orders_bp
    from routes.clock import bp as clock_bp

    app.register_blueprint(restaurants_bp)
    app.register_blueprint(riders_bp)
    app.register_blueprint(customers_bp)
    app.register_blueprint(orders_bp)
    app.register_blueprint(assignments_bp)
    app.register_blueprint(returns_bp)
    app.register_blueprint(fines_bp)
    app.register_blueprint(work_orders_bp)
    app.register_blueprint(clock_bp)

    with app.app_context():
        db.create_all()

    return app


if __name__ == '__main__':
    app = create_app()
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port, debug=False)
