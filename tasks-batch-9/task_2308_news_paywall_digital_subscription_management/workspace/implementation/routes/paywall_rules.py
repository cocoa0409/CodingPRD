"""Dynamic paywall rules (PRD 3.3)."""
from flask import Blueprint, request

import config
import lookup
import serializers
import validation as v
from db import db, new_entity
from errors import fail
from middleware import auth
from response import listing, mark_created, object_response
from services.paywall import ranked_rules, specificity_score

bp = Blueprint("paywall_rules", __name__)


@bp.post("/paywall-rules")
@auth(config.ROLE_REVENUE)
def create_paywall_rule():
    data = v.body()
    name = v.get_string(data, "name", required=True, min_len=1, max_len=120)
    action = v.get_enum(data, "action", config.RULE_ACTIONS, required=True)
    priority = v.get_int(data, "priority", required=True, minimum=1, maximum=999)
    content_type_match = v.get_enum(
        data, "content_type_match", config.CONTENT_TYPE_MATCHES, default="ANY"
    )
    section_match = v.get_string(data, "section_match", min_len=1, max_len=40, default="ANY")
    propensity_band_match = v.get_enum(
        data, "propensity_band_match", config.PROPENSITY_BAND_MATCHES, default="ANY"
    )
    meter_allowance_override = v.get_int(data, "meter_allowance_override", default=None)
    status = v.get_enum(data, "status", config.RULE_STATUSES, default="ACTIVE")

    if section_match != "ANY" and not v.is_lower_slug(section_match):
        fail("ERR_INVALID_REQUEST", "Field 'section_match' must be a lowercase slug or ANY.")
    for existing in db.paywall_rules.values():
        if (
            existing["content_type_match"] == content_type_match
            and existing["section_match"] == section_match
            and existing["propensity_band_match"] == propensity_band_match
            and existing["priority"] == priority
        ):
            fail(
                "ERR_INVALID_REQUEST",
                "Field 'priority' must be unique across the three matcher values.",
            )

    rule = new_entity()
    rule.update(
        {
            "name": name,
            "status": status,
            "content_type_match": content_type_match,
            "section_match": section_match,
            "propensity_band_match": propensity_band_match,
            "action": action,
            "meter_allowance_override": meter_allowance_override,
            "priority": priority,
            "specificity_score": specificity_score(
                content_type_match, section_match, propensity_band_match
            ),
        }
    )
    db.paywall_rules[rule["id"]] = rule
    mark_created(rule)
    return object_response(serializers.paywall_rule(rule), 201)


@bp.get("/paywall-rules")
@auth(config.ROLE_REVENUE, config.ROLE_OPS)
def list_paywall_rules():
    rows = ranked_rules(list(db.paywall_rules.values()))
    for param in ("status", "content_type_match", "propensity_band_match"):
        value = request.args.get(param)
        if value:
            rows = [r for r in rows if r[param] == value]
    return listing(rows, serializers.paywall_rule)


@bp.get("/paywall-rules/<rule_id>")
@auth(config.ROLE_REVENUE, config.ROLE_OPS)
def read_paywall_rule(rule_id):
    return object_response(serializers.paywall_rule(lookup.paywall_rule(rule_id)))
