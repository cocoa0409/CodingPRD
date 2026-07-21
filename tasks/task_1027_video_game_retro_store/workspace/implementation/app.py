import os

from flask import Flask, jsonify

from errors import ApiError
from envelope import error_response

from routes.clock import bp as clock_bp
from routes.members import bp as members_bp
from routes.products import bp as products_bp
from routes.product_stocks import bp as product_stocks_bp
from routes.inventory_items import bp as inventory_items_bp
from routes.preorders import bp as preorders_bp
from routes.tradeins import bp as tradeins_bp
from routes.rentals import bp as rentals_bp
from routes.sales import bp as sales_bp
from routes.stations import bp as stations_bp
from routes.tournaments import bp as tournaments_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in (
        clock_bp,
        members_bp,
        products_bp,
        product_stocks_bp,
        inventory_items_bp,
        preorders_bp,
        tradeins_bp,
        rentals_bp,
        sales_bp,
        stations_bp,
        tournaments_bp,
    ):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return jsonify(error_response(exc.error_id, exc.message)), exc.http_status

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
