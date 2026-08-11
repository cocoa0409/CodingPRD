"""Work orders, parts consumption, warranty coverages and callback claims."""

import calc
import cascade
import common
import serialize
from core import (
    ApiError, F, add_days, cents, d, db, endpoint, parse_instant, whole_days_between,
)

from datetime import timedelta

WORK_ORDER_SCOPES = ["NEW_WELL", "PUMP_REPLACEMENT", "PRESSURE_TANK",
                     "TREATMENT_INSTALL", "REPAIR", "MAINTENANCE"]
TRAVEL_BUFFER = timedelta(minutes=calc.TRAVEL_BUFFER_MINUTES)


def _wo_owner(ctx):
    work_order = ctx.path["work_order_id"]
    prop = db.get("Property", work_order["property_id"])
    return common.account_of_property(prop)


def _wo_technician(ctx):
    return ctx.path["work_order_id"]["assigned_technician_id"]


def _fulfillment_gate(*allowed):
    def check(ctx):
        work_order = ctx.path["work_order_id"]
        if work_order["fulfillment_status"] not in allowed:
            raise ApiError("ERR_WORK_ORDER_INVALID_FULFILLMENT_STATE",
                           "The fulfilment axis is not in a state that permits this.")
    return check


# ==========================================================================
# 4.14 Work orders
# ==========================================================================

@endpoint("POST", "/water-service/work-orders", ["Dispatcher", "PlatformAdmin"],
          code=201, fields=[
              F("property_id", "string"),
              F("well_profile_id", "string"),
              F("assigned_technician_id", "string"),
              F("scope", "string", enum=WORK_ORDER_SCOPES),
              F("quote_id", "string", required=False),
              F("emergency_ticket_id", "string", required=False),
          ])
def create_work_order(ctx):
    common.resolve("Property", ctx.body["property_id"])
    common.resolve("WellProfile", ctx.body["well_profile_id"])
    common.resolve("Technician", ctx.body["assigned_technician_id"])
    quote = common.resolve_opt("Quote", ctx.body["quote_id"])
    ticket = common.resolve_opt("EmergencyTicket", ctx.body["emergency_ticket_id"])

    if (quote is None) == (ticket is None):
        raise ApiError("ERR_WORK_ORDER_ORIGIN_CONFLICT",
                       "Exactly one of quote_id or emergency_ticket_id is required.")
    if quote is not None and quote["status"] != "APPROVED":
        raise ApiError("ERR_QUOTE_NOT_APPROVED", "The quote is not APPROVED.")
    if ticket is not None:
        if common.rows_where("WorkOrder", emergency_ticket_id=ticket["id"]):
            raise ApiError("ERR_EMERGENCY_TICKET_ALREADY_LINKED",
                           "The ticket already founded a work order.")

    row = ctx.new("WorkOrder", {
        "property_id": ctx.body["property_id"],
        "well_profile_id": ctx.body["well_profile_id"],
        "quote_id": quote["id"] if quote else None,
        "emergency_ticket_id": ticket["id"] if ticket else None,
        "assigned_technician_id": ctx.body["assigned_technician_id"],
        "origin_callback_claim_id": None,
        "pipeline": "EMERGENCY" if ticket else "SCHEDULED",
        "scope": ctx.body["scope"],
        "fulfillment_status": "DRAFT",
        "billing_status": "NOT_BILLABLE",
        "scheduled_start_at": None,
        "scheduled_end_at": None,
        "actual_start_at": None,
        "actual_end_at": None,
        "actual_labor_minutes": None,
        "billable_minutes": None,
        "labor_rate_cents_per_hour": None,
        "labor_charge_cents": 0,
        "parts_charge_cents": 0,
        "callback_eligibility": "NONE",
        "callback_attempt_count": 0,
        "hold_reason": None,
    })
    if quote is not None:
        quote["status"] = "CONSUMED"
        ctx.touch(quote)
    return serialize.dump(row)


@endpoint("GET", "/water-service/work-orders/<work_order_id>",
          ["PlatformAdmin", "Dispatcher", "Technician", "Estimator", "BillingClerk",
           "ComplianceOfficer", "CustomerContact"], read=True,
          path_params=[("work_order_id", "WorkOrder")],
          scope=common.scope(customer=_wo_owner, technician=_wo_technician))
def read_work_order(ctx):
    return serialize.dump(ctx.path["work_order_id"])


@endpoint("GET", "/water-service/work-orders",
          ["PlatformAdmin", "Dispatcher", "Technician", "Estimator", "BillingClerk",
           "ComplianceOfficer"], read=True, paginated=True,
          filters=["property_id", "well_profile_id", "quote_id", "emergency_ticket_id",
                   "assigned_technician_id", "origin_callback_claim_id", "pipeline",
                   "fulfillment_status", "billing_status"])
def list_work_orders(ctx):
    return db.all("WorkOrder")


def _schedule_regulatory(ctx):
    work_order = ctx.path["work_order_id"]
    permit_ok = work_order["scope"] not in calc.PERMIT_REQUIRED_SCOPES
    if not permit_ok and work_order["pipeline"] == "EMERGENCY":
        permit_ok = True
    if not permit_ok:
        for permit in db.all("Permit"):
            if permit["work_order_id"] == work_order["id"] \
                    and permit["status"] in ("APPROVED", "APPROVED_WITH_CONDITIONS"):
                permit_ok = True
                break
    if not permit_ok:
        raise ApiError("ERR_PERMIT_REQUIRED_NOT_APPROVED",
                       "This scope needs an approved permit before scheduling.")
    technician = db.get("Technician", work_order["assigned_technician_id"])
    if technician is None or technician["tier"] not in calc.SCOPE_TIERS[work_order["scope"]]:
        raise ApiError("ERR_TECHNICIAN_TIER_INSUFFICIENT",
                       "The technician's tier is insufficient for this scope.")


def _schedule_date_range(ctx):
    if not ctx.body["scheduled_end_at"] > ctx.body["scheduled_start_at"]:
        raise ApiError("ERR_INVALID_DATE_RANGE",
                       "scheduled_end_at must be strictly after scheduled_start_at.")


@endpoint("POST", "/water-service/work-orders/<work_order_id>/schedule", ["Dispatcher"],
          path_params=[("work_order_id", "WorkOrder")],
          g5=_fulfillment_gate("DRAFT", "HELD"), g6=_schedule_regulatory,
          fields=[F("scheduled_start_at", "datetime"),
                  F("scheduled_end_at", "datetime")],
          g8_post=_schedule_date_range)
def schedule_work_order(ctx):
    work_order = ctx.path["work_order_id"]
    start = ctx.body["scheduled_start_at"]
    end = ctx.body["scheduled_end_at"]

    # The travel buffer expands the CANDIDATE only, on both sides.
    buffered_lo = start - TRAVEL_BUFFER
    buffered_hi = end + TRAVEL_BUFFER
    others = [w for w in db.all("WorkOrder")
              if w["id"] != work_order["id"]
              and w["assigned_technician_id"] == work_order["assigned_technician_id"]
              and w["fulfillment_status"] in ("SCHEDULED", "IN_PROGRESS")
              and w["scheduled_start_at"] is not None
              and w["scheduled_end_at"] is not None]
    others.sort(key=lambda w: (w["scheduled_start_at"], w["created_at"], w["_seq"]))
    for other in others:
        if buffered_lo < other["scheduled_end_at"] \
                and other["scheduled_start_at"] < buffered_hi:
            raise ApiError("ERR_TECHNICIAN_SCHEDULE_CONFLICT",
                           "The technician's calendar collides with this window.")

    day = start.date()
    count = 0
    for other in db.all("WorkOrder"):
        if other["id"] == work_order["id"]:
            continue
        if other["well_profile_id"] != work_order["well_profile_id"]:
            continue
        if other["fulfillment_status"] not in ("SCHEDULED", "IN_PROGRESS"):
            continue
        if other["scheduled_start_at"] is not None \
                and other["scheduled_start_at"].date() == day:
            count += 1
    if count >= calc.WELL_DAILY_WORK_ORDER_CAP:
        raise ApiError("ERR_WELL_SERVICE_WINDOW_CONFLICT",
                       "The well already carries a job on that day.")

    work_order["scheduled_start_at"] = start
    work_order["scheduled_end_at"] = end
    work_order["hold_reason"] = None
    work_order["fulfillment_status"] = "SCHEDULED"
    ctx.touch(work_order)
    return serialize.dump(work_order)


@endpoint("POST", "/water-service/work-orders/<work_order_id>/start", ["Technician"],
          path_params=[("work_order_id", "WorkOrder")],
          scope=common.scope(technician=_wo_technician),
          g5=_fulfillment_gate("SCHEDULED"))
def start_work_order(ctx):
    work_order = ctx.path["work_order_id"]
    work_order["actual_start_at"] = db.clock
    work_order["fulfillment_status"] = "IN_PROGRESS"
    ctx.touch(work_order)
    return serialize.dump(work_order)


@endpoint("POST", "/water-service/work-orders/<work_order_id>/parts-consumption",
          ["Technician"], code=201, path_params=[("work_order_id", "WorkOrder")],
          scope=common.scope(technician=_wo_technician),
          g5=_fulfillment_gate("IN_PROGRESS"),
          fields=[F("part_catalog_item_id", "string"),
                  F("quantity", "integer", nonneg=True)])
def post_parts(ctx):
    work_order = ctx.path["work_order_id"]
    part = common.resolve("PartCatalogItem", ctx.body["part_catalog_item_id"])
    quantity = ctx.body["quantity"]
    ticket = db.get("EmergencyTicket", work_order["emergency_ticket_id"]) \
        if work_order["emergency_ticket_id"] else None

    if ticket is not None and ticket["cause_class"] == "NON_WELL_CAUSE":
        raise ApiError("ERR_NON_WELL_CAUSE_BLOCKS_PARTS",
                       "A non-well cause forbids parts consumption.")
    if ticket is not None and ticket["authorization_status"] == "PENDING":
        raise ApiError("ERR_AUTHORIZATION_REQUIRED",
                       "Customer authorisation is required before consuming parts.")
    if part["status"] != "ACTIVE":
        raise ApiError("ERR_PART_DISCONTINUED", "The catalog part is discontinued.")
    if quantity > calc.PART_MAX_LINE_QUANTITY:
        raise ApiError("ERR_QUANTITY_EXCEEDS_LIMIT", "The quantity exceeds the limit.")
    if part["on_hand_qty"] < quantity:
        raise ApiError("ERR_PART_OUT_OF_STOCK", "The part is out of stock.")

    snapshot = part["unit_cost_cents"]
    if work_order["quote_id"]:
        for line in common.active_quote_lines(work_order["quote_id"]):
            if line["part_catalog_item_id"] == part["id"] \
                    and line["unit_cost_cents_pinned"] is not None:
                snapshot = line["unit_cost_cents_pinned"]
                break
    markup, unit_price = calc.parts_unit_price_cents(snapshot)
    extended = unit_price * quantity

    if ticket is not None and ticket["authorization_status"] == "PRE_AUTHORIZED":
        cumulative = sum(e["extended_price_cents"]
                         for e in common.posted_entries(work_order["id"]))
        cumulative += extended + work_order["labor_charge_cents"]
        if cumulative > ticket["preauth_cap_cents"]:
            raise ApiError("ERR_PREAUTH_CAP_EXCEEDED",
                           "The pre-authorisation ceiling would be exceeded.")

    row = ctx.new("PartsConsumptionEntry", {
        "work_order_id": work_order["id"],
        "part_catalog_item_id": part["id"],
        "quantity": quantity,
        "unit_cost_cents_snapshot": snapshot,
        "markup_pct_applied": float(markup),
        "unit_price_cents": unit_price,
        "extended_price_cents": extended,
        "status": "POSTED",
        "posted_at": db.clock,
    })
    part["on_hand_qty"] = part["on_hand_qty"] - quantity
    ctx.touch(part)
    return serialize.dump(row)


@endpoint("GET", "/water-service/work-orders/<work_order_id>/parts-consumption",
          ["PlatformAdmin", "Dispatcher", "Technician", "BillingClerk"], read=True,
          paginated=True, path_params=[("work_order_id", "WorkOrder")])
def work_order_parts(ctx):
    return common.rows_where("PartsConsumptionEntry",
                             work_order_id=ctx.path["work_order_id"]["id"])


@endpoint("POST", "/water-service/work-orders/<work_order_id>/complete", ["Technician"],
          path_params=[("work_order_id", "WorkOrder")],
          scope=common.scope(technician=_wo_technician),
          g5=_fulfillment_gate("IN_PROGRESS"),
          fields=[F("actual_labor_minutes", "integer", minimum=0, maximum=720)])
def complete_work_order(ctx):
    work_order = ctx.path["work_order_id"]
    ticket = db.get("EmergencyTicket", work_order["emergency_ticket_id"]) \
        if work_order["emergency_ticket_id"] else None
    if work_order["pipeline"] == "EMERGENCY" and ticket is not None \
            and ticket["authorization_status"] == "PENDING":
        raise ApiError("ERR_AUTHORIZATION_REQUIRED",
                       "Customer authorisation is required before completion.")
    work_order["actual_labor_minutes"] = ctx.body["actual_labor_minutes"]
    cascade.complete_work_order(ctx, work_order)
    return serialize.dump(work_order)


@endpoint("POST", "/water-service/work-orders/<work_order_id>/cancel",
          ["Dispatcher", "PlatformAdmin"], path_params=[("work_order_id", "WorkOrder")],
          g5=_fulfillment_gate("DRAFT", "SCHEDULED", "IN_PROGRESS"))
def cancel_work_order(ctx):
    work_order = ctx.path["work_order_id"]
    if work_order["fulfillment_status"] == "IN_PROGRESS":
        for entry in common.posted_entries(work_order["id"]):
            entry["status"] = "REVERSED"
            ctx.touch(entry)
            part = db.get("PartCatalogItem", entry["part_catalog_item_id"])
            if part is not None:
                part["on_hand_qty"] = part["on_hand_qty"] + entry["quantity"]
                ctx.touch(part)
    work_order["fulfillment_status"] = "CANCELLED"
    ctx.touch(work_order)
    return serialize.dump(work_order)


def _write_off_gate(ctx):
    work_order = ctx.path["work_order_id"]
    # The billing axis is checked BEFORE the fulfilment axis (PRD 2.6).
    if work_order["billing_status"] != "NOT_BILLABLE":
        raise ApiError("ERR_WORK_ORDER_INVALID_BILLING_STATE",
                       "The billing axis is not NOT_BILLABLE.")
    if work_order["fulfillment_status"] != "CANCELLED":
        raise ApiError("ERR_WORK_ORDER_INVALID_FULFILLMENT_STATE",
                       "The fulfilment axis is not CANCELLED.")


@endpoint("POST", "/water-service/work-orders/<work_order_id>/write-off",
          ["BillingClerk"], path_params=[("work_order_id", "WorkOrder")],
          g5=_write_off_gate)
def write_off_work_order(ctx):
    work_order = ctx.path["work_order_id"]
    work_order["billing_status"] = "WRITTEN_OFF"
    ctx.touch(work_order)
    return serialize.dump(work_order)


@endpoint("GET", "/water-service/work-orders/<work_order_id>/warranty-coverages",
          ["PlatformAdmin", "Dispatcher", "Technician", "BillingClerk",
           "CustomerContact"], read=True, paginated=True,
          path_params=[("work_order_id", "WorkOrder")])
def work_order_coverages(ctx):
    return common.rows_where("WarrantyCoverage",
                             work_order_id=ctx.path["work_order_id"]["id"])


@endpoint("POST", "/water-service/work-orders/<work_order_id>/callback-claims",
          ["CustomerContact"], code=201,
          path_params=[("work_order_id", "WorkOrder")],
          scope=common.scope(customer=_wo_owner),
          g5=_fulfillment_gate("COMPLETED"),
          fields=[F("warranty_coverage_id", "string"),
                  F("complaint_class", "string", enum=["PART", "LABOR"]),
                  F("description", "string")])
def raise_callback_claim(ctx):
    work_order = ctx.path["work_order_id"]
    coverage = common.resolve("WarrantyCoverage", ctx.body["warranty_coverage_id"])
    if work_order["callback_eligibility"] == "CONSUMED":
        raise ApiError("ERR_CALLBACK_ALREADY_CONSUMED",
                       "This work order's callback has already been consumed.")

    complaint_class = ctx.body["complaint_class"]
    days = whole_days_between(coverage["starts_at"], db.clock)
    in_warranty = (calc.coverage_state(coverage) == "ACTIVE"
                   and days <= calc.WARRANTY_WINDOW_DAYS[complaint_class])

    claim = ctx.new("CallbackClaim", {
        "warranty_coverage_id": coverage["id"],
        "original_work_order_id": work_order["id"],
        "remedy_work_order_id": None,
        "complaint_class": complaint_class,
        "description": ctx.body["description"],
        "status": "SUBMITTED" if in_warranty else "REJECTED_OUT_OF_WARRANTY",
        "submitted_at": db.clock,
        "adjudicated_by_user_id": None,
        "days_since_coverage_start": days,
    })
    coverage["claim_count"] = coverage["claim_count"] + 1
    ctx.touch(coverage)
    work_order["callback_attempt_count"] = work_order["callback_attempt_count"] + 1
    if not in_warranty:
        work_order["callback_eligibility"] = "EXPIRED"
    ctx.touch(work_order)

    if not in_warranty:
        # PRD 2.11 rung 3: the compliance record persists behind the error.
        raise ApiError("ERR_CALLBACK_OUT_OF_WARRANTY",
                       "The coverage is out of window for this complaint class.",
                       persist=True)
    return serialize.dump(claim)


@endpoint("GET", "/water-service/work-orders/<work_order_id>/callback-claims",
          ["PlatformAdmin", "Dispatcher", "Technician", "BillingClerk",
           "CustomerContact"], read=True, paginated=True,
          path_params=[("work_order_id", "WorkOrder")])
def work_order_claims(ctx):
    return common.rows_where("CallbackClaim",
                             original_work_order_id=ctx.path["work_order_id"]["id"])


@endpoint("GET", "/water-service/work-orders/<work_order_id>/invoices",
          ["PlatformAdmin", "Dispatcher", "BillingClerk", "CustomerContact"],
          read=True, paginated=True, path_params=[("work_order_id", "WorkOrder")])
def work_order_invoices(ctx):
    return common.rows_where("Invoice", work_order_id=ctx.path["work_order_id"]["id"])


@endpoint("GET", "/water-service/work-orders/<work_order_id>/maintenance-visits",
          ["PlatformAdmin", "Dispatcher", "Technician"], read=True, paginated=True,
          path_params=[("work_order_id", "WorkOrder")])
def work_order_visits(ctx):
    return common.rows_where("MaintenanceVisit",
                             work_order_id=ctx.path["work_order_id"]["id"])


# ==========================================================================
# 4.15 Parts consumption entries
# ==========================================================================

@endpoint("GET",
          "/water-service/parts-consumption-entries/<parts_consumption_entry_id>",
          ["PlatformAdmin", "Technician", "BillingClerk", "Dispatcher"], read=True,
          path_params=[("parts_consumption_entry_id", "PartsConsumptionEntry")])
def read_entry(ctx):
    return serialize.dump(ctx.path["parts_consumption_entry_id"])


@endpoint("GET", "/water-service/parts-consumption-entries",
          ["PlatformAdmin", "Technician", "BillingClerk", "Dispatcher"], read=True,
          paginated=True, filters=["work_order_id", "part_catalog_item_id", "status"])
def list_entries(ctx):
    return db.all("PartsConsumptionEntry")


# ==========================================================================
# 4.16 Warranty coverages
# ==========================================================================

@endpoint("GET", "/water-service/warranty-coverages/<warranty_coverage_id>",
          ["PlatformAdmin", "Technician", "BillingClerk", "Dispatcher",
           "CustomerContact"], read=True,
          path_params=[("warranty_coverage_id", "WarrantyCoverage")])
def read_coverage(ctx):
    return serialize.dump(ctx.path["warranty_coverage_id"])


@endpoint("GET", "/water-service/warranty-coverages",
          ["PlatformAdmin", "Technician", "BillingClerk", "Dispatcher"], read=True,
          paginated=True, filters=["work_order_id", "parts_consumption_entry_id",
                                   "superseded_by_id", "coverage_class", "status"])
def list_coverages(ctx):
    return db.all("WarrantyCoverage")


@endpoint("POST", "/water-service/warranty-coverages/<warranty_coverage_id>/void",
          ["PlatformAdmin"],
          path_params=[("warranty_coverage_id", "WarrantyCoverage")],
          g5=common.state_gate("warranty_coverage_id", "status", ("ACTIVE",),
                               "ERR_WARRANTY_ALREADY_SUPERSEDED"))
def void_coverage(ctx):
    coverage = ctx.path["warranty_coverage_id"]
    for claim in common.rows_where("CallbackClaim", warranty_coverage_id=coverage["id"]):
        if claim["status"] == "APPROVED_WARRANTY":
            raise ApiError("ERR_WARRANTY_ALREADY_SUPERSEDED",
                           "An approved claim stands against this coverage.")
    coverage["status"] = "VOIDED"
    ctx.touch(coverage)
    return serialize.dump(coverage)


# ==========================================================================
# 4.17 Callback claims
# ==========================================================================

@endpoint("GET", "/water-service/callback-claims/<callback_claim_id>",
          ["PlatformAdmin", "Technician", "Dispatcher", "BillingClerk",
           "CustomerContact"], read=True,
          path_params=[("callback_claim_id", "CallbackClaim")])
def read_claim(ctx):
    return serialize.dump(ctx.path["callback_claim_id"])


@endpoint("GET", "/water-service/callback-claims",
          ["PlatformAdmin", "Technician", "Dispatcher", "BillingClerk"], read=True,
          paginated=True, filters=["warranty_coverage_id", "original_work_order_id",
                                   "remedy_work_order_id", "status", "complaint_class"])
def list_claims(ctx):
    return db.all("CallbackClaim")


DECISIONS = ["REVIEW", "APPROVE", "REJECT"]
DECISION_FROM = {"REVIEW": ("SUBMITTED",), "APPROVE": ("UNDER_REVIEW",),
                 "REJECT": ("UNDER_REVIEW",)}


def _adjudicate_state(ctx):
    from core import peek_json
    claim = ctx.path["callback_claim_id"]
    raw = peek_json()
    ctx.raw_body = raw
    decision = raw.get("decision") if isinstance(raw, dict) else None
    allowed = DECISION_FROM.get(decision, ("SUBMITTED", "UNDER_REVIEW"))
    if claim["status"] not in allowed:
        raise ApiError("ERR_CALLBACK_CLAIM_INVALID_STATE",
                       "The claim is not in a state that permits this decision.")


def _adjudicator_conflict(ctx):
    claim = ctx.path["callback_claim_id"]
    original = db.get("WorkOrder", claim["original_work_order_id"])
    if original is not None and ctx.user_id == original["assigned_technician_id"]:
        raise ApiError("ERR_CALLBACK_ADJUDICATOR_CONFLICT",
                       "The assigned technician may not adjudicate this claim.")


@endpoint("POST", "/water-service/callback-claims/<callback_claim_id>/adjudicate",
          ["Technician"], path_params=[("callback_claim_id", "CallbackClaim")],
          g5=_adjudicate_state, g6=_adjudicator_conflict,
          fields=[F("decision", "string", enum=DECISIONS)])
def adjudicate_claim(ctx):
    claim = ctx.path["callback_claim_id"]
    decision = ctx.body["decision"]
    if decision == "APPROVE":
        coverage = db.get("WarrantyCoverage", claim["warranty_coverage_id"])
        if coverage is not None \
                and coverage["claim_count"] > calc.CALLBACK_MAX_PER_COVERAGE:
            raise ApiError("ERR_CALLBACK_LIMIT_REACHED",
                           "This coverage has reached its callback limit.")
        claim["status"] = "APPROVED_WARRANTY"
        original = db.get("WorkOrder", claim["original_work_order_id"])
        if original is not None:
            original["callback_eligibility"] = "ELIGIBLE"
            ctx.touch(original)
    elif decision == "REJECT":
        claim["status"] = "REJECTED_NOT_DEFECT"
    else:
        claim["status"] = "UNDER_REVIEW"
    claim["adjudicated_by_user_id"] = ctx.user_id
    ctx.touch(claim)
    return serialize.dump(claim)


def _remedy_state(ctx):
    claim = ctx.path["callback_claim_id"]
    if claim["status"] != "APPROVED_WARRANTY" or claim["remedy_work_order_id"]:
        raise ApiError("ERR_CALLBACK_CLAIM_INVALID_STATE",
                       "A remedy work order cannot be raised from this claim.")


@endpoint("POST",
          "/water-service/callback-claims/<callback_claim_id>/remedy-work-order",
          ["Dispatcher"], code=201,
          path_params=[("callback_claim_id", "CallbackClaim")], g5=_remedy_state,
          fields=[F("assigned_technician_id", "string"),
                  F("scope", "string", enum=WORK_ORDER_SCOPES)])
def raise_remedy_work_order(ctx):
    claim = ctx.path["callback_claim_id"]
    common.resolve("Technician", ctx.body["assigned_technician_id"])
    original = db.get("WorkOrder", claim["original_work_order_id"])
    row = ctx.new("WorkOrder", {
        "property_id": original["property_id"],
        "well_profile_id": original["well_profile_id"],
        "quote_id": None,
        "emergency_ticket_id": None,
        "assigned_technician_id": ctx.body["assigned_technician_id"],
        "origin_callback_claim_id": claim["id"],
        "pipeline": "SCHEDULED",
        "scope": ctx.body["scope"],
        "fulfillment_status": "DRAFT",
        "billing_status": "NOT_BILLABLE",
        "scheduled_start_at": None,
        "scheduled_end_at": None,
        "actual_start_at": None,
        "actual_end_at": None,
        "actual_labor_minutes": None,
        "billable_minutes": None,
        "labor_rate_cents_per_hour": None,
        "labor_charge_cents": 0,
        "parts_charge_cents": 0,
        "callback_eligibility": "NONE",
        "callback_attempt_count": 0,
        "hold_reason": None,
    })
    claim["remedy_work_order_id"] = row["id"]
    ctx.touch(claim)
    return serialize.dump(row)
