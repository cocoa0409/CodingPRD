"""Fantasy Football League API server entry point."""
from __future__ import annotations

import os

from flask import Flask

from core.envelope import register_error_handlers
from routes.drafts import bp as drafts_bp
from routes.keepers import bp as keepers_bp
from routes.leagues import bp as leagues_bp
from routes.matchups import bp as matchups_bp
from routes.players import bp as players_bp
from routes.teams import bp as teams_bp
from routes.trades import bp as trades_bp
from routes.waivers import bp as waivers_bp


def create_app() -> Flask:
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(leagues_bp)
    app.register_blueprint(teams_bp)
    app.register_blueprint(players_bp)
    app.register_blueprint(drafts_bp)
    app.register_blueprint(keepers_bp)
    app.register_blueprint(waivers_bp)
    app.register_blueprint(trades_bp)
    app.register_blueprint(matchups_bp)

    register_error_handlers(app)
    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
