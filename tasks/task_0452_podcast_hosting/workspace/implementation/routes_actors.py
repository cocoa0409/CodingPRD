"""Actor registration: publishers, advertisers, listeners (PRD §3.1)."""

import common
import db
import errors
import serialize
from common import new_common
from response import success
from routehelpers import auth_and_role, body


def register(app):
    @app.route("/publishers", methods=["POST"])
    def create_publisher():
        # Roles: PlatformAdmin only.
        auth_and_role(["PlatformAdmin"])
        data = body()
        name = common.require_str(data, "name")
        payout_email = common.require_str(data, "payout_email")
        # revenue_share_pct optional, default 0.70, range [0.0, 1.0] inclusive.
        share = common.optional_number(data, "revenue_share_pct", 0.70)
        if share < 0.0 or share > 1.0:
            raise errors.err(errors.ERR_INVALID_REQUEST, "revenue_share_pct must be between 0.0 and 1.0")
        rec = new_common()
        rec.update({
            "name": name,
            "payout_email": payout_email,
            "revenue_share_pct": share,
        })
        db.db.publishers[rec["id"]] = rec
        return success(serialize.publisher(rec), status=201)

    @app.route("/advertisers", methods=["POST"])
    def create_advertiser():
        # Roles: PlatformAdmin only.
        auth_and_role(["PlatformAdmin"])
        data = body()
        name = common.require_str(data, "name")
        billing_email = common.require_str(data, "billing_email")
        rec = new_common()
        rec.update({"name": name, "billing_email": billing_email})
        db.db.advertisers[rec["id"]] = rec
        return success(serialize.advertiser(rec), status=201)

    @app.route("/listeners", methods=["POST"])
    def create_listener():
        # Roles: PlatformAdmin, Listener (self-register).
        auth_and_role(["PlatformAdmin", "Listener"])
        data = body()
        email = common.require_str(data, "email")
        display_name = common.require_str(data, "display_name")
        rec = new_common()
        rec.update({"email": email, "display_name": display_name})
        db.db.listeners[rec["id"]] = rec
        return success(serialize.listener(rec), status=201)
