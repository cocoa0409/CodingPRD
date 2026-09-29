"""Supplement facts panels: drafting, the construction check and print lock (PRD 3.5)."""

import re

from flask import Blueprint

import auth
import calc
import cascade
import db
import errors
import response
import serialize
import validate
from errors import fail
from routes.helpers import PREFIX, fk_row, listing, path_row

bp = Blueprint("label_panels", __name__)

READ_ROLES = (
    auth.ROLE_SPECIALIST,
    auth.ROLE_APPROVAL,
    auth.ROLE_QA,
    auth.ROLE_AUDITOR,
)

OCCUPYING_STATUSES = ("DRAFT", "VALIDATED", "LOCKED")
SERVING_SIZE_RE = re.compile(calc.SERVING_SIZE_PATTERN)


def _window_collision(product_id, start, end, exclude_id):
    """Closed-closed intersection with the incoming window widened by the buffer."""
    low = calc.add_days(start, -calc.CHANGEOVER_BUFFER_DAYS)
    high = calc.add_days(end, calc.CHANGEOVER_BUFFER_DAYS)
    for other in cascade.panels_of(product_id):
        if other["panel_status"] not in OCCUPYING_STATUSES:
            continue
        if exclude_id is not None and other["id"] == exclude_id:
            continue
        if low <= other["effective_until"] and other["effective_from"] <= high:
            return True
    return False


@bp.route(PREFIX + "/label-panels", methods=["POST"])
@auth.endpoint([auth.ROLE_SPECIALIST])
def create_panel():
    body = validate.body()
    product_id = validate.req_str(body, "product_id")
    expected_version = validate.req_int(body, "expected_product_version")
    panel_format = validate.req_enum(body, "panel_format", calc.PANEL_FORMATS)
    serving_size_text = validate.req_str(body, "serving_size_text")
    serving_weight_g = validate.req_number(body, "serving_weight_g", gt=0)
    servings_declared = validate.req_int(body, "servings_per_container_declared", ge=1)
    effective_from = validate.req_date(body, "effective_from")
    effective_until = validate.req_date(body, "effective_until")
    declared_codes = validate.req_str_array(body, "declared_warning_codes")
    disclaimer_text = validate.opt_str(body, "disclaimer_text")
    supersedes_id = validate.opt_str(body, "supersedes_panel_id")

    product = fk_row("products", product_id, errors.ERR_PRODUCT_NOT_FOUND)

    superseded = None
    if supersedes_id is not None:
        superseded = db.get("panels", supersedes_id)
        if superseded is None or superseded["product_id"] != product_id:
            fail(
                errors.ERR_PANEL_NOT_FOUND,
                "supersedes_panel_id does not name a panel of this product.",
            )

    if effective_from > effective_until:
        fail(errors.ERR_INVALID_DATE_RANGE, "effective_from must not follow effective_until.")

    if expected_version != product["version"]:
        fail(
            errors.ERR_STALE_PRODUCT_VERSION,
            "expected_product_version %s does not match the product's current version %s."
            % (expected_version, product["version"]),
        )

    if product["label_posture"] == "FROZEN":
        fail(errors.ERR_PRODUCT_LABEL_FROZEN, "A FROZEN product may not receive a new panel.")

    if _window_collision(product_id, effective_from, effective_until, supersedes_id):
        fail(
            errors.ERR_PANEL_WINDOW_OVERLAP,
            "The buffered effective window collides with another live panel.",
        )

    row = db.base_fields()
    row.update(
        {
            "product_id": product_id,
            "supersedes_panel_id": supersedes_id,
            "panel_format": panel_format,
            "serving_size_text": serving_size_text,
            "serving_weight_g": serving_weight_g,
            "servings_per_container_declared": servings_declared,
            "effective_from": effective_from,
            "effective_until": effective_until,
            "declared_warning_codes": list(declared_codes),
            "disclaimer_text": disclaimer_text,
            "panel_status": "DRAFT",
            "required_warning_codes": [],
            "panel_lines_required": None,
            "panel_lines_allowed": None,
            "panel_total_dv_coverage_pct": None,
            "validated_at": None,
            "locked_at": None,
        }
    )
    db.insert("panels", row)

    if superseded is not None and superseded["panel_status"] in ("VALIDATED", "LOCKED"):
        superseded["panel_status"] = "SUPERSEDED"
        db.touch(superseded)
        if product["lifecycle_status"] == "LABEL_LOCKED":
            # A label revision reopens the product until the replacement panel is locked.
            product["lifecycle_status"] = "DRAFT"

    db.touch(product)
    return response.object_response(serialize.panel(row), 201)


@bp.route(PREFIX + "/label-panels/<row_id>", methods=["GET"])
@auth.endpoint(READ_ROLES)
def get_panel(row_id):
    row = path_row("panels", row_id, errors.ERR_PANEL_NOT_FOUND)
    return response.object_response(serialize.panel(row))


@bp.route(PREFIX + "/label-panels", methods=["GET"])
@auth.endpoint(READ_ROLES)
def list_panels():
    return listing(
        "panels",
        serialize.panel,
        filters=("product_id", "panel_status", "supersedes_panel_id"),
    )


@bp.route(PREFIX + "/label-panels/<row_id>", methods=["PATCH"])
@auth.endpoint([auth.ROLE_SPECIALIST])
def amend_panel(row_id):
    row = path_row("panels", row_id, errors.ERR_PANEL_NOT_FOUND)
    body = validate.body()

    sentinel = object()
    serving_size_text = validate.opt_str(
        body, "serving_size_text", default=sentinel, allow_null=False
    )
    serving_weight_g = validate.opt_number(
        body, "serving_weight_g", default=sentinel, gt=0, allow_null=False
    )
    servings_declared = validate.opt_int(
        body, "servings_per_container_declared", default=sentinel, ge=1, allow_null=False
    )
    effective_from = validate.opt_date(
        body, "effective_from", default=sentinel, allow_null=False
    )
    effective_until = validate.opt_date(
        body, "effective_until", default=sentinel, allow_null=False
    )
    declared_codes = validate.opt_str_array(
        body, "declared_warning_codes", default=sentinel
    )
    disclaimer_text = validate.opt_str(body, "disclaimer_text", default=sentinel)

    merged_from = row["effective_from"] if effective_from is sentinel else effective_from
    merged_until = row["effective_until"] if effective_until is sentinel else effective_until
    if merged_from > merged_until:
        fail(errors.ERR_INVALID_DATE_RANGE, "effective_from must not follow effective_until.")

    if row["panel_status"] != "DRAFT":
        fail(errors.ERR_PANEL_STATE_INVALID, "Only a DRAFT panel may be amended.")

    if serving_size_text is not sentinel:
        row["serving_size_text"] = serving_size_text
    if serving_weight_g is not sentinel:
        row["serving_weight_g"] = serving_weight_g
    if servings_declared is not sentinel:
        row["servings_per_container_declared"] = servings_declared
    if effective_from is not sentinel:
        row["effective_from"] = effective_from
    if effective_until is not sentinel:
        row["effective_until"] = effective_until
    if declared_codes is not sentinel:
        row["declared_warning_codes"] = list(declared_codes)
    if disclaimer_text is not sentinel:
        row["disclaimer_text"] = disclaimer_text
    db.touch(row)
    return response.object_response(serialize.panel(row))


@bp.route(PREFIX + "/label-panels/<row_id>/validate", methods=["POST"])
@auth.endpoint([auth.ROLE_SPECIALIST])
def validate_panel(row_id):
    row = path_row("panels", row_id, errors.ERR_PANEL_NOT_FOUND)
    product = db.get("products", row["product_id"])

    if row["panel_status"] != "DRAFT":
        fail(errors.ERR_PANEL_STATE_INVALID, "Only a DRAFT panel may be validated.")
    if product is not None and product["label_posture"] == "FROZEN":
        fail(errors.ERR_PRODUCT_LABEL_FROZEN, "A FROZEN product may not have a panel validated.")

    if not SERVING_SIZE_RE.match(row["serving_size_text"] or ""):
        fail(
            errors.ERR_SERVING_SIZE_FORMAT_INVALID,
            "serving_size_text does not match the printed-serving pattern.",
        )

    computed_servings = calc.servings_from_weight(
        product["net_quantity_g"], row["serving_weight_g"]
    )
    declared = row["servings_per_container_declared"]
    if declared != computed_servings or declared != product["servings_per_container"]:
        fail(
            errors.ERR_SERVING_COUNT_MISMATCH,
            "servings_per_container_declared must equal both the computed count %s and the "
            "product's servings_per_container %s."
            % (computed_servings, product["servings_per_container"]),
        )

    required = cascade.required_warning_codes(row["product_id"])
    declared_codes = set(row["declared_warning_codes"] or [])
    missing = [code for code in required if code not in declared_codes]
    if missing:
        fail(
            errors.ERR_MANDATORY_WARNING_MISSING,
            "The panel omits mandatory warning codes: %s." % ", ".join(missing),
        )

    disclaimer_needed = cascade.has_disclaimer_obligation(row["product_id"])
    if disclaimer_needed and row["disclaimer_text"] != calc.FDA_DISCLAIMER:
        fail(
            errors.ERR_DISCLAIMER_MISSING,
            "The verbatim FDA disclaimer is required once a structure/function or "
            "general-wellbeing claim is approved.",
        )

    # %DV is refreshed for every ACTIVE line before the coverage total is summed.
    lines = cascade.active_lines(row["product_id"])
    for line in lines:
        cascade.recompute_line_dv(line)

    lines_sorted = sorted(lines, key=lambda l: l["panel_position"])
    coverage = 0
    dagger = 0
    for line in lines_sorted:
        if line["dv_established"]:
            coverage += line["percent_dv_declared"]
        else:
            dagger = 1

    disclaimer_line = 1 if disclaimer_needed else 0
    lines_required = (
        calc.HEADER_BLOCK_LINES + len(lines) + dagger + len(required) + disclaimer_line
    )
    lines_allowed = calc.panel_lines_allowed(row["panel_format"], product["net_quantity_g"])
    if lines_required > lines_allowed:
        fail(
            errors.ERR_PANEL_LINE_BUDGET_EXCEEDED,
            "The panel needs %s printed lines but only %s are allowed."
            % (lines_required, lines_allowed),
        )

    if not lines:
        fail(
            errors.ERR_PRODUCT_HAS_NO_ACTIVE_LINES,
            "The panel's product carries no ACTIVE supplement-facts line.",
        )

    row["required_warning_codes"] = required
    row["panel_total_dv_coverage_pct"] = coverage
    row["panel_lines_required"] = lines_required
    row["panel_lines_allowed"] = lines_allowed
    row["panel_status"] = "VALIDATED"
    row["validated_at"] = db.now()
    db.touch(row)
    return response.object_response(serialize.panel(row))


@bp.route(PREFIX + "/label-panels/<row_id>/lock", methods=["POST"])
@auth.endpoint([auth.ROLE_APPROVAL])
def lock_panel(row_id):
    row = path_row("panels", row_id, errors.ERR_PANEL_NOT_FOUND)
    product = db.get("products", row["product_id"])

    if row["panel_status"] != "VALIDATED":
        fail(errors.ERR_PANEL_STATE_INVALID, "Only a VALIDATED panel may be locked for print.")
    if product is not None and product["label_posture"] == "FROZEN":
        fail(errors.ERR_PRODUCT_LABEL_FROZEN, "A FROZEN product may not have a panel locked.")

    for line in cascade.active_lines(row["product_id"]):
        ingredient = db.get("ingredients", line["ingredient_id"])
        if ingredient is None or ingredient["eligibility_status"] not in calc.LABEL_CLEARED_STATES:
            fail(
                errors.ERR_INGREDIENT_NOT_ELIGIBLE,
                "Every ingredient on an ACTIVE line must be GRANDFATHERED or NDI_ACKNOWLEDGED.",
            )

    row["panel_status"] = "LOCKED"
    row["locked_at"] = db.now()
    db.touch(row)

    if product is not None:
        if product["lifecycle_status"] == "DRAFT":
            product["lifecycle_status"] = "LABEL_LOCKED"
        db.touch(product)

    return response.object_response(serialize.panel(row))
