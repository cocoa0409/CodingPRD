"""The logical UTC clock (PRD 2.4)."""
import config
import envelope
import store
import util
from reqctx import endpoint, field


def register(app):
    @app.route("/clinic/_clock/set_current_utc", methods=["POST"])
    @endpoint(
        roles=[config.ROLE_CLINIC_ADMIN],
        specs=[field("to_iso8601", "datetime", True)],
    )
    def set_current_utc(ctx):
        store.set_now(ctx.get("to_iso8601"))
        return envelope.ok({"current_utc": util.fmt_dt(store.now())})
