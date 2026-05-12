"""Classification suggestion endpoint."""

from flask import Blueprint

from errors import APIError, ERR_INVALID_REQUEST
from middleware import require_roles
from response import success_object
from services.calculations import classification_suggest
from services.common import get_body
from services.serializers import serialize_hs_code


bp = Blueprint("classification", __name__)


@bp.route("/classification/suggest", methods=["POST"])
@require_roles("Declarant")
def suggest():
    body = get_body()
    pd = body.get("product_description")
    if not isinstance(pd, str):
        raise APIError(ERR_INVALID_REQUEST, "product_description required", 400)

    matches = classification_suggest(pd)
    suggestions = [serialize_hs_code(m["hs_code"]) for m in matches]
    scores = [m["score"] for m in matches]
    return success_object({"suggestions": suggestions, "scores": scores}, status=200)
