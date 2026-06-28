"""Cross-cutting domain services: lazy quote expiry, ownership, serialization."""
from clock import parse_iso8601
from db import store, touch
from errors import err

# Public (response) field sets per entity. Internal bookkeeping fields
# (prefixed with _ or otherwise not in §1.1) are stripped before responding.

CUSTOMER_FIELDS = ["id", "email", "full_name", "state_code", "annual_income_cents",
                   "created_at", "updated_at", "version"]
PROJECT_FIELDS = ["id", "customer_id", "address_line", "status", "active_quote_id",
                  "linear_feet", "door_count", "created_at", "updated_at", "version"]
MEASURE_FIELDS = ["id", "project_id", "scheduled_for", "status", "linear_feet",
                  "door_count", "door_style", "finish_code",
                  "created_at", "updated_at", "version"]
QUOTE_FIELDS = ["id", "project_id", "measure_id", "scope", "status",
                "estimate_total_cents", "firm_total_cents", "addons_total_cents",
                "expires_at", "is_active", "created_at", "updated_at", "version"]
ADDON_FIELDS = ["id", "quote_id", "kind", "unit_price_cents", "quantity", "status",
                "price_cents", "created_at", "updated_at", "version"]
CHANGE_ORDER_FIELDS = ["id", "quote_id", "delta_linear_feet", "delta_door_count",
                       "rush", "status", "price_delta_cents", "lead_time_delta_days",
                       "created_at", "updated_at", "version"]
MATERIAL_ORDER_FIELDS = ["id", "project_id", "quote_id", "status",
                         "base_lead_time_days", "ready_at", "lead_extension_days",
                         "created_at", "updated_at", "version"]
CREW_FIELDS = ["id", "name", "daily_job_capacity", "skill_finishes", "is_active",
               "created_at", "updated_at", "version"]
INSTALL_JOB_FIELDS = ["id", "project_id", "material_order_id", "crew_id",
                      "window_start", "window_end", "status", "install_day",
                      "created_at", "updated_at", "version"]
WARRANTY_CLAIM_FIELDS = ["id", "project_id", "description", "status", "covered",
                         "filed_at", "created_at", "updated_at", "version"]
FINANCING_FIELDS = ["id", "project_id", "customer_id", "amount_cents", "term_months",
                    "status", "monthly_payment_cents", "dti_ratio",
                    "created_at", "updated_at", "version"]


def view(entity, fields):
    return {f: entity.get(f) for f in fields}


def get_or_404(table, _id):
    ent = table.get(_id)
    if ent is None:
        raise err("ERR_NOT_FOUND", "Resource not found")
    return ent


def expire_quote_if_due(quote):
    """Lazily expire a QUOTED quote whose expires_at <= now (PRD §3.5).

    Marks EXPIRED, clears is_active, clears the project's active_quote_id if it
    pointed here. Returns the quote.
    """
    if quote["status"] != "QUOTED":
        return quote
    expires_at = quote.get("expires_at")
    if not expires_at:
        return quote
    now = store.clock.now
    if now >= parse_iso8601(expires_at):
        quote["status"] = "EXPIRED"
        quote["is_active"] = False
        touch(store, quote)
        proj = store.projects.get(quote["project_id"])
        if proj is not None and proj.get("active_quote_id") == quote["id"]:
            proj["active_quote_id"] = None
            touch(store, proj)
    return quote


def expire_project_active_quote(project):
    """Lazily expire the project's active quote when reading the project."""
    aq = project.get("active_quote_id")
    if aq:
        q = store.quotes.get(aq)
        if q is not None:
            expire_quote_if_due(q)
    return project


def assert_project_owner(project, user_id, role):
    """Customer-scoped ownership check (PRD §2.1). Non-customers are unaffected
    here; their role permission was already validated upstream."""
    if role == "Customer" and project.get("customer_id") != user_id:
        raise err("ERR_NOT_PROJECT_OWNER", "Acting customer does not own the project")
