"""Practitioner registration and read."""

from flask import Blueprint

import config
import ladder
from store import db, make_row
from services import serializers

bp = Blueprint("practitioners", __name__)


@bp.route("/practitioners", methods=["POST"])
def create_practitioner():
    def handler(ctx):
        row = make_row(
            full_name=ctx.body["full_name"],
            credential=ctx.body["credential"],
            npi=ctx.body.get("npi"),
            licensed_state_codes=ctx.body["licensed_state_codes"],
            is_active=ctx.body.get("is_active", True)
            if ctx.body.get("is_active") is not None
            else True,
        )
        db.practitioners[row["id"]] = row
        return serializers.practitioner(row)

    return ladder.run(
        {
            "roles": [config.ROLE_PRACTICE_ADMIN],
            "shape": [
                ("full_name", "string", True),
                ("credential", "string", True),
                ("licensed_state_codes", "array", True, {"of": "string"}),
                ("npi", "string", False),
                ("is_active", "bool", False),
            ],
            "enums": {"credential": config.CREDENTIALS},
            "handler": handler,
            "status": 201,
        }
    )


@bp.route("/practitioners/<pid>", methods=["GET"])
def get_practitioner(pid):
    return ladder.run(
        {
            "roles": list(config.ALL_ROLES),
            "path": [("practitioner", pid)],
            "handler": lambda ctx: serializers.practitioner(ctx.path["practitioner"]),
        }
    )
