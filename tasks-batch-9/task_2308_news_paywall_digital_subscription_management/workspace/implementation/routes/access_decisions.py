"""The paywall access decision (PRD 3.3)."""
from flask import Blueprint

import config
import lookup
import middleware
import serializers
import validation as v
from clock import clock, parse_datetime
from errors import fail
from middleware import auth
from response import object_response
from services.paywall import access_decision

bp = Blueprint("access_decisions", __name__)


@bp.post("/access-decisions")
@auth(config.ROLE_READER, config.ROLE_OPS)
def create_access_decision():
    data = v.body()
    raw_reader_id = data.get("reader_id")
    if (
        middleware.is_reader()
        and isinstance(raw_reader_id, str)
        and raw_reader_id != middleware.user_id()
    ):
        fail("ERR_UNAUTHORIZED")

    reader_id = v.get_id(data, "reader_id", required=True)
    article_id = v.get_id(data, "article_id", required=True)

    reader = lookup.reader(reader_id)
    article = lookup.article(article_id)

    published_dt = article.get("_published_dt") or parse_datetime(article["published_at"])
    if published_dt > clock.now():
        fail("ERR_ARTICLE_UNPUBLISHED")

    event = access_decision(reader, article)
    return object_response(serializers.reader_event(event), 201)
