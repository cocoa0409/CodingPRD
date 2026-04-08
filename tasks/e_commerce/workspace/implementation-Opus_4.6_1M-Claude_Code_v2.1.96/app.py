import os
from flask import Flask
from db import init_db, close_db
from errors import APIError
from response import error_response

app = Flask(__name__)


@app.errorhandler(APIError)
def handle_api_error(e):
    return error_response(e.error_id, e.message, e.status_code)


@app.errorhandler(400)
def handle_400(e):
    return error_response("ERR_INVALID_REQUEST", "Bad request.", 400)


@app.errorhandler(404)
def handle_404(e):
    return error_response("ERR_INVALID_REQUEST", "Not found.", 404)


@app.errorhandler(405)
def handle_405(e):
    return error_response("ERR_INVALID_REQUEST", "Method not allowed.", 405)


@app.teardown_appcontext
def teardown(e=None):
    close_db(e)


from routes.shops import bp as shops_bp
from routes.products import bp as products_bp
from routes.promotions import bp as promotions_bp
from routes.orders import bp as orders_bp
from routes.refunds import bp as refunds_bp
from routes.settlements import bp as settlements_bp

app.register_blueprint(shops_bp)
app.register_blueprint(products_bp)
app.register_blueprint(promotions_bp)
app.register_blueprint(orders_bp)
app.register_blueprint(refunds_bp)
app.register_blueprint(settlements_bp)

with app.app_context():
    init_db()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
