import os
from flask import Flask
from errors import ApiError
from response import error_response

app = Flask(__name__)
app.url_map.strict_slashes = False

# Register blueprints
from routes.shops import bp as shops_bp
from routes.customers import bp as customers_bp
from routes.motors import bp as motors_bp
from routes.work_orders import bp as wo_bp
from routes.quotes import bp as quotes_bp
from routes.invoices import bp as invoices_bp
from routes.pool import bp as pool_bp
from routes.warranty import bp as warranty_bp
from routes.clock import bp as clock_bp

for bp in (shops_bp, customers_bp, motors_bp, wo_bp, quotes_bp, invoices_bp, pool_bp, warranty_bp, clock_bp):
    app.register_blueprint(bp)


@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e.error_id, e.http_status, e.message)


@app.errorhandler(404)
def handle_404(e):
    return error_response("ERR_NOT_FOUND", 404, "Resource not found")


@app.errorhandler(405)
def handle_405(e):
    return error_response("ERR_NOT_FOUND", 404, "Method not allowed")


@app.errorhandler(Exception)
def handle_generic(e):
    import traceback
    traceback.print_exc()
    return error_response("ERR_INTERNAL", 500, str(e))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
