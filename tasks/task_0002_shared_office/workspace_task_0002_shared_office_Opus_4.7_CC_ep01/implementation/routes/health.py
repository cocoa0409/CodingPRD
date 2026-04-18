from flask import Blueprint

from response import success

bp = Blueprint("health", __name__)


@bp.route("/health", methods=["GET"])
def health():
    return success({"status": "ok"})
