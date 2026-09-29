"""Editorial inventory (PRD 3.3)."""
from flask import Blueprint

import config
import lookup
import serializers
import validation as v
from clock import clock, format_datetime
from db import db, new_entity
from errors import fail
from middleware import auth
from response import mark_created, object_response

bp = Blueprint("articles", __name__)


@bp.post("/articles")
@auth(config.ROLE_REVENUE)
def create_article():
    data = v.body()
    headline = v.get_string(data, "headline", required=True, min_len=1, max_len=240)
    section = v.get_string(data, "section", required=True, min_len=1, max_len=40)
    content_type = v.get_enum(data, "content_type", config.CONTENT_TYPES, required=True)
    access_class = v.get_enum(data, "access_class", config.ACCESS_CLASSES, default="METERED")
    published_at = v.get_datetime(data, "published_at")

    if not v.is_lower_slug(section):
        fail("ERR_INVALID_REQUEST", "Field 'section' must be a lowercase slug.")

    article = new_entity()
    article.update(
        {
            "headline": headline,
            "content_type": content_type,
            "section": section,
            "access_class": access_class,
            "published_at": format_datetime(published_at or clock.now()),
            "_published_dt": published_at or clock.now(),
        }
    )
    db.articles[article["id"]] = article
    mark_created(article)
    return object_response(serializers.article(article), 201)


@bp.get("/articles/<article_id>")
@auth(config.ROLE_REVENUE, config.ROLE_OPS, config.ROLE_READER)
def read_article(article_id):
    return object_response(serializers.article(lookup.article(article_id)))
