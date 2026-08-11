"""Quotes, quote lines and permits."""

import calc
import common
import serialize
from core import ApiError, F, cents, d, db, endpoint

QUOTE_SCOPES = ["NEW_WELL", "PUMP_REPLACEMENT", "PRESSURE_TANK", "TREATMENT_INSTALL",
                "REPAIR"]
TIERS = ["APPRENTICE", "JOURNEYMAN", "MASTER"]


def _quote_owner(ctx):
    quote = ctx.path["quote_id"]
    prop = db.get("Property", quote["property_id"])
    return common.account_of_property(prop)


# ==========================================================================
# 4.11 Quotes
# ==========================================================================

@endpoint("POST", "/water-service/quotes", ["Estimator", "PlatformAdmin"], code=201,
          fields=[
              F("property_id", "string"),
              F("well_profile_id", "string"),
              F("inspection_id", "string"),
              F("scope", "string", enum=QUOTE_SCOPES),
              F("estimated_labor_minutes", "integer", minimum=15, maximum=720),
              F("estimated_start_at", "datetime"),
              F("quoted_technician_tier", "string", enum=TIERS),
          ])
def create_quote(ctx):
    common.resolve("Property", ctx.body["property_id"])
    common.resolve("WellProfile", ctx.body["well_profile_id"])
    common.resolve("Inspection", ctx.body["inspection_id"])
    row = ctx.new("Quote", {
        "property_id": ctx.body["property_id"],
        "well_profile_id": ctx.body["well_profile_id"],
        "inspection_id": ctx.body["inspection_id"],
        "scope": ctx.body["scope"],
        "status": "DRAFT",
        "estimated_labor_minutes": ctx.body["estimated_labor_minutes"],
        "estimated_start_at": ctx.body["estimated_start_at"],
        "quoted_technician_tier": ctx.body["quoted_technician_tier"],
        "parts_subtotal_cents": 0,
        "labor_subtotal_cents": 0,
        "permit_fee_cents": 0,
        "tax_cents": 0,
        "total_cents": 0,
        "sent_at": None,
        "approved_at": None,
        "approved_total_cents": None,
    })
    return serialize.dump(row)


@endpoint("GET", "/water-service/quotes/<quote_id>",
          ["PlatformAdmin", "Estimator", "Dispatcher", "BillingClerk", "CustomerContact"],
          read=True, path_params=[("quote_id", "Quote")],
          scope=common.scope(customer=_quote_owner))
def read_quote(ctx):
    return serialize.dump(ctx.path["quote_id"])


@endpoint("GET", "/water-service/quotes",
          ["PlatformAdmin", "Estimator", "Dispatcher", "BillingClerk"], read=True,
          paginated=True,
          filters=["property_id", "well_profile_id", "inspection_id", "status", "scope"])
def list_quotes(ctx):
    return db.all("Quote")


@endpoint("POST", "/water-service/quotes/<quote_id>/lines", ["Estimator"], code=201,
          path_params=[("quote_id", "Quote")],
          g5=common.state_gate("quote_id", "status", ("DRAFT", "REVISION_REQUIRED"),
                               "ERR_QUOTE_INVALID_STATE"),
          occ=("expected_quote_version", "ERR_STALE_QUOTE_VERSION",
               lambda c: c.path["quote_id"]),
          fields=[
              F("part_catalog_item_id", "string"),
              F("quantity", "integer", nonneg=True),
              F("expected_quote_version", "integer"),
          ])
def add_quote_line(ctx):
    quote = ctx.path["quote_id"]
    part = common.resolve("PartCatalogItem", ctx.body["part_catalog_item_id"])
    if part["status"] != "ACTIVE":
        raise ApiError("ERR_PART_DISCONTINUED", "The catalog part is discontinued.")
    if ctx.body["quantity"] > calc.PART_MAX_LINE_QUANTITY:
        raise ApiError("ERR_QUANTITY_EXCEEDS_LIMIT", "The quantity exceeds the limit.")
    well = db.get("WellProfile", quote["well_profile_id"])
    failure = common.pump_yield_check(part, well) if well is not None else None
    if failure:
        raise ApiError(failure, "The pump does not clear the well's yield gate.")
    row = ctx.new("QuoteLine", {
        "quote_id": quote["id"],
        "part_catalog_item_id": part["id"],
        "superseded_by_line_id": None,
        "quantity": ctx.body["quantity"],
        "unit_cost_cents_pinned": None,
        "markup_pct_applied": None,
        "unit_price_cents": None,
        "extended_price_cents": None,
        "status": "ACTIVE",
        "origin": "ESTIMATOR",
    })
    ctx.touch(quote)
    return serialize.dump(row)


@endpoint("GET", "/water-service/quotes/<quote_id>/lines",
          ["PlatformAdmin", "Estimator", "Dispatcher", "BillingClerk", "CustomerContact"],
          read=True, paginated=True, path_params=[("quote_id", "Quote")])
def quote_lines(ctx):
    return common.rows_where("QuoteLine", quote_id=ctx.path["quote_id"]["id"])


@endpoint("POST", "/water-service/quotes/<quote_id>/price", ["Estimator"],
          path_params=[("quote_id", "Quote")],
          g5=common.state_gate("quote_id", "status", ("DRAFT", "REVISION_REQUIRED"),
                               "ERR_QUOTE_INVALID_STATE"))
def price_quote(ctx):
    quote = ctx.path["quote_id"]
    lines = common.active_quote_lines(quote["id"])
    if not lines:
        raise ApiError("ERR_QUOTE_HAS_NO_ACTIVE_LINES",
                       "The quote carries no ACTIVE line.")
    parts = 0
    for line in lines:
        if line["unit_cost_cents_pinned"] is None:
            part = db.get("PartCatalogItem", line["part_catalog_item_id"])
            line["unit_cost_cents_pinned"] = part["unit_cost_cents"]
        calc.price_line(line, line["unit_cost_cents_pinned"])
        parts += line["extended_price_cents"]
        ctx.touch(line)
    band = calc.labor_time_band(quote["estimated_start_at"])
    rate = calc.labor_rate_cents_per_hour(quote["quoted_technician_tier"], band)
    minutes = calc.billable_minutes(quote["estimated_labor_minutes"])
    labor = calc.labor_charge_cents(rate, minutes)
    permit = common.quote_permit_fee(quote["id"])
    tax = cents(d(parts) * calc.TAX_RATE_PCT / d(100))
    quote["parts_subtotal_cents"] = parts
    quote["labor_subtotal_cents"] = labor
    quote["permit_fee_cents"] = permit
    quote["tax_cents"] = tax
    quote["total_cents"] = parts + labor + permit + tax
    quote["status"] = "PRICED"
    ctx.touch(quote)
    return serialize.dump(quote)


@endpoint("POST", "/water-service/quotes/<quote_id>/send", ["Estimator"],
          path_params=[("quote_id", "Quote")],
          g5=common.state_gate("quote_id", "status", ("PRICED",),
                               "ERR_QUOTE_INVALID_STATE"))
def send_quote(ctx):
    quote = ctx.path["quote_id"]
    quote["status"] = "SENT"
    quote["sent_at"] = db.clock
    ctx.touch(quote)
    return serialize.dump(quote)


@endpoint("POST", "/water-service/quotes/<quote_id>/approve", ["CustomerContact"],
          path_params=[("quote_id", "Quote")], scope=common.scope(customer=_quote_owner),
          g5=common.state_gate("quote_id", "status", ("SENT",),
                               "ERR_QUOTE_INVALID_STATE"))
def approve_quote(ctx):
    quote = ctx.path["quote_id"]
    inspection = db.get("Inspection", quote["inspection_id"])
    if inspection is None or inspection["status"] != "COMPLETED" \
            or inspection["completed_at"] is None \
            or (db.clock - inspection["completed_at"]).total_seconds() \
            > calc.INSPECTION_VALIDITY_DAYS * 86400:
        raise ApiError("ERR_INSPECTION_STALE", "The cited inspection is stale.")
    prop = db.get("Property", quote["property_id"])
    account = db.get("Account", prop["account_id"]) if prop else None
    if account is not None and account["credit_hold"]:
        raise ApiError("ERR_ACCOUNT_ON_CREDIT_HOLD", "The account is on credit hold.")

    well = db.get("WellProfile", quote["well_profile_id"])
    offending = []
    for line in common.active_quote_lines(quote["id"]):
        part = db.get("PartCatalogItem", line["part_catalog_item_id"])
        if part is None or part["category"] != "PUMP":
            continue
        if common.pump_yield_check(part, well) is not None:
            offending.append(line)
    if offending:
        # PRD 2.11 rung 2: the supersede persists behind the error.
        for line in offending:
            line["status"] = "SUPERSEDED_BY_YIELD"
            ctx.touch(line)
        quote["status"] = "REVISION_REQUIRED"
        ctx.touch(quote)
        raise ApiError("ERR_QUOTE_LINE_YIELD_EXCEEDED",
                       "A pump line no longer clears the yield gate.", persist=True)

    quote["status"] = "APPROVED"
    quote["approved_at"] = db.clock
    quote["approved_total_cents"] = quote["total_cents"]
    ctx.touch(quote)
    return serialize.dump(quote)


@endpoint("POST", "/water-service/quotes/<quote_id>/decline", ["CustomerContact"],
          path_params=[("quote_id", "Quote")], scope=common.scope(customer=_quote_owner),
          g5=common.state_gate("quote_id", "status", ("SENT",),
                               "ERR_QUOTE_INVALID_STATE"))
def decline_quote(ctx):
    quote = ctx.path["quote_id"]
    quote["status"] = "DECLINED"
    ctx.touch(quote)
    return serialize.dump(quote)


@endpoint("POST", "/water-service/quotes/<quote_id>/expire", ["PlatformAdmin"],
          path_params=[("quote_id", "Quote")],
          g5=common.state_gate("quote_id", "status", ("SENT",),
                               "ERR_QUOTE_INVALID_STATE"))
def expire_quote(ctx):
    quote = ctx.path["quote_id"]
    elapsed = (db.clock - quote["sent_at"]).total_seconds()
    if not elapsed > calc.QUOTE_VALIDITY_DAYS * 86400:
        raise ApiError("ERR_QUOTE_INVALID_STATE",
                       "The validity window has not closed yet.")
    quote["status"] = "EXPIRED"
    ctx.touch(quote)
    return serialize.dump(quote)


# ==========================================================================
# 4.12 Quote lines
# ==========================================================================

@endpoint("GET", "/water-service/quote-lines/<quote_line_id>",
          ["PlatformAdmin", "Estimator", "Dispatcher", "BillingClerk", "CustomerContact"],
          read=True, path_params=[("quote_line_id", "QuoteLine")])
def read_quote_line(ctx):
    return serialize.dump(ctx.path["quote_line_id"])


@endpoint("GET", "/water-service/quote-lines",
          ["PlatformAdmin", "Estimator", "Dispatcher", "BillingClerk"], read=True,
          paginated=True, filters=["quote_id", "part_catalog_item_id",
                                   "superseded_by_line_id", "status", "origin"])
def list_quote_lines(ctx):
    return db.all("QuoteLine")


def _quote_line_state(ctx):
    line = ctx.path["quote_line_id"]
    quote = db.get("Quote", line["quote_id"])
    if line["status"] != "ACTIVE" or quote is None \
            or quote["status"] not in ("DRAFT", "REVISION_REQUIRED"):
        raise ApiError("ERR_QUOTE_LINE_INVALID_STATE",
                       "The line cannot be removed in this state.")


@endpoint("DELETE", "/water-service/quote-lines/<quote_line_id>", ["Estimator"],
          path_params=[("quote_line_id", "QuoteLine")], g5=_quote_line_state)
def remove_quote_line(ctx):
    line = ctx.path["quote_line_id"]
    line["status"] = "REMOVED"
    ctx.touch(line)
    ctx.touch(db.get("Quote", line["quote_id"]))
    return serialize.dump(line)


# ==========================================================================
# 4.18 Permits
# ==========================================================================

@endpoint("POST", "/water-service/permits",
          ["ComplianceOfficer", "Estimator", "PlatformAdmin"], code=201, fields=[
              F("well_profile_id", "string"),
              F("jurisdiction_code", "string", one_of=list(calc.JURISDICTION_TIER)),
              F("scope", "string", enum=QUOTE_SCOPES),
              F("quote_id", "string", required=False),
              F("work_order_id", "string", required=False),
              F("expedited", "boolean", required=False, default=False),
              F("post_hoc", "boolean", required=False, default=False),
          ])
def create_permit(ctx):
    common.resolve("WellProfile", ctx.body["well_profile_id"])
    common.resolve_opt("Quote", ctx.body["quote_id"])
    common.resolve_opt("WorkOrder", ctx.body["work_order_id"])
    row = ctx.new("Permit", {
        "well_profile_id": ctx.body["well_profile_id"],
        "work_order_id": ctx.body["work_order_id"],
        "quote_id": ctx.body["quote_id"],
        "jurisdiction_code": ctx.body["jurisdiction_code"],
        "jurisdiction_tier": None,
        "scope": ctx.body["scope"],
        "expedited": ctx.body["expedited"],
        "fee_cents": 0,
        "status": "DRAFT",
        "filed_at": None,
        "mandated_alternate_part_id": None,
        "superseded_quote_line_id": None,
        "condition_text": None,
        "post_hoc": ctx.body["post_hoc"],
    })
    return serialize.dump(row)


@endpoint("GET", "/water-service/permits/<permit_id>",
          ["PlatformAdmin", "ComplianceOfficer", "Estimator", "Dispatcher",
           "BillingClerk"], read=True, path_params=[("permit_id", "Permit")])
def read_permit(ctx):
    return serialize.dump(ctx.path["permit_id"])


@endpoint("GET", "/water-service/permits",
          ["PlatformAdmin", "ComplianceOfficer", "Estimator", "Dispatcher",
           "BillingClerk"], read=True, paginated=True,
          filters=["well_profile_id", "work_order_id", "quote_id",
                   "mandated_alternate_part_id", "superseded_quote_line_id", "status",
                   "jurisdiction_code", "scope"])
def list_permits(ctx):
    return db.all("Permit")


def _permit_file_regulatory(ctx):
    permit = ctx.path["permit_id"]
    well = db.get("WellProfile", permit["well_profile_id"])
    if well is None or permit["jurisdiction_code"] != well["jurisdiction_code"]:
        raise ApiError("ERR_PERMIT_JURISDICTION_MISMATCH",
                       "The permit jurisdiction does not match the well's.")
    if permit["post_hoc"]:
        work_order = db.get("WorkOrder", permit["work_order_id"])
        if work_order is None or work_order["fulfillment_status"] != "COMPLETED" \
                or work_order["actual_end_at"] is None \
                or (db.clock - work_order["actual_end_at"]).total_seconds() \
                > calc.POST_HOC_PERMIT_WINDOW_DAYS * 86400:
            raise ApiError("ERR_POST_HOC_PERMIT_WINDOW_EXPIRED",
                           "The post-hoc filing window has expired.")


@endpoint("POST", "/water-service/permits/<permit_id>/file", ["ComplianceOfficer"],
          path_params=[("permit_id", "Permit")],
          g5=common.state_gate("permit_id", "status", ("DRAFT",),
                               "ERR_PERMIT_INVALID_STATE"),
          g6=_permit_file_regulatory)
def file_permit(ctx):
    permit = ctx.path["permit_id"]
    for other in db.all("Permit"):
        if other["id"] == permit["id"]:
            continue
        if other["well_profile_id"] == permit["well_profile_id"] \
                and other["scope"] == permit["scope"] \
                and other["status"] in ("FILED", "APPROVED", "APPROVED_WITH_CONDITIONS"):
            raise ApiError("ERR_PERMIT_ALREADY_ON_FILE",
                           "A permit for this well and scope is already on file.")
    well = db.get("WellProfile", permit["well_profile_id"])
    tier, fee = calc.permit_fee_cents(well["jurisdiction_code"], permit["scope"],
                                      permit["expedited"])
    permit["jurisdiction_tier"] = tier
    permit["fee_cents"] = fee
    permit["filed_at"] = db.clock
    permit["status"] = "FILED"
    ctx.touch(permit)
    return serialize.dump(permit)


@endpoint("POST", "/water-service/permits/<permit_id>/approve", ["ComplianceOfficer"],
          path_params=[("permit_id", "Permit")],
          g5=common.state_gate("permit_id", "status", ("FILED",),
                               "ERR_PERMIT_INVALID_STATE"),
          fields=[
              F("mandated_alternate_part_id", "string", required=False),
              F("superseded_quote_line_id", "string", required=False),
              F("condition_text", "string", required=False),
          ])
def approve_permit(ctx):
    permit = ctx.path["permit_id"]
    part_id = ctx.body["mandated_alternate_part_id"]
    line_id = ctx.body["superseded_quote_line_id"]
    if part_id is None and line_id is None:
        permit["status"] = "APPROVED"
        ctx.touch(permit)
        return serialize.dump(permit)
    if part_id is None or line_id is None:
        raise ApiError("ERR_VALIDATION",
                       "A mandated alternate needs both the part and the line.")

    part = common.resolve("PartCatalogItem", part_id)
    line = common.resolve("QuoteLine", line_id)
    if line["quote_id"] != permit["quote_id"] or line["status"] != "ACTIVE":
        raise ApiError("ERR_QUOTE_LINE_INVALID_STATE",
                       "The superseded line is not an ACTIVE line of this permit's quote.")
    if part["status"] != "ACTIVE":
        raise ApiError("ERR_PART_DISCONTINUED", "The mandated alternate is discontinued.")
    old_part = db.get("PartCatalogItem", line["part_catalog_item_id"])
    if old_part is None or part["category"] != old_part["category"]:
        raise ApiError("ERR_PART_CATEGORY_MISMATCH",
                       "The mandated alternate is of a different category.")

    # hop 1
    permit["condition_text"] = ctx.body["condition_text"]
    permit["mandated_alternate_part_id"] = part["id"]
    permit["superseded_quote_line_id"] = line["id"]
    permit["status"] = "APPROVED_WITH_CONDITIONS"
    ctx.touch(permit)

    # hop 2
    alternate = ctx.new("QuoteLine", {
        "quote_id": line["quote_id"],
        "part_catalog_item_id": part["id"],
        "superseded_by_line_id": None,
        "quantity": line["quantity"],
        "unit_cost_cents_pinned": None,
        "markup_pct_applied": None,
        "unit_price_cents": None,
        "extended_price_cents": None,
        "status": "ACTIVE",
        "origin": "PERMIT_MANDATED_ALTERNATE",
    })
    line["status"] = "SUPERSEDED"
    line["superseded_by_line_id"] = alternate["id"]
    ctx.touch(line)

    # hop 3
    quote = db.get("Quote", line["quote_id"])
    left_approved = False
    if quote is not None:
        if quote["status"] == "APPROVED":
            quote["status"] = "REVISION_REQUIRED"
            left_approved = True
        common.reprice_quote(ctx, quote)

    # hop 4
    if left_approved:
        for work_order in common.rows_where("WorkOrder", quote_id=quote["id"]):
            if work_order["fulfillment_status"] == "SCHEDULED":
                work_order["fulfillment_status"] = "HELD"
                work_order["hold_reason"] = "PERMIT_CONDITION_REVISION"
                work_order["scheduled_start_at"] = None
                work_order["scheduled_end_at"] = None
                ctx.touch(work_order)
    return serialize.dump(permit)


@endpoint("POST", "/water-service/permits/<permit_id>/reject", ["ComplianceOfficer"],
          path_params=[("permit_id", "Permit")],
          g5=common.state_gate("permit_id", "status", ("FILED",),
                               "ERR_PERMIT_INVALID_STATE"))
def reject_permit(ctx):
    permit = ctx.path["permit_id"]
    permit["status"] = "REJECTED"
    ctx.touch(permit)
    return serialize.dump(permit)


@endpoint("POST", "/water-service/permits/<permit_id>/refile-draft",
          ["ComplianceOfficer"], path_params=[("permit_id", "Permit")],
          g5=common.state_gate("permit_id", "status", ("REJECTED",),
                               "ERR_PERMIT_INVALID_STATE"))
def refile_permit(ctx):
    permit = ctx.path["permit_id"]
    permit["status"] = "DRAFT"
    permit["filed_at"] = None
    permit["fee_cents"] = 0
    ctx.touch(permit)
    return serialize.dump(permit)


@endpoint("POST", "/water-service/permits/<permit_id>/withdraw", ["ComplianceOfficer"],
          path_params=[("permit_id", "Permit")],
          g5=common.state_gate("permit_id", "status", ("FILED",),
                               "ERR_PERMIT_INVALID_STATE"))
def withdraw_permit(ctx):
    permit = ctx.path["permit_id"]
    permit["status"] = "WITHDRAWN"
    ctx.touch(permit)
    return serialize.dump(permit)
