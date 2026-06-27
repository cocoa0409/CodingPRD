"""Customers (PRD §3.3)."""
from db import db, make_common
from middleware import require_roles
from routes.common import lookup, respond
from services import serialize_generic
from validation import (
    get_json,
    require_string,
    require_enum,
    optional_enum,
    optional_bool,
)


def register(app):

    @app.route("/customers", methods=["POST"])
    @require_roles("DealerAdmin", "SalesRep", "FinanceManager")
    def create_customer():
        body = get_json()
        name = require_string(body, "name")
        customer_type = require_enum(body, "customer_type",
                                     {"RETAIL", "COMMERCIAL_AG", "GOVERNMENT"})
        credit_tier = optional_enum(body, "credit_tier",
                                    {"PRIME", "STANDARD", "SUBPRIME"},
                                    default="STANDARD")
        tax_exempt = optional_bool(body, "tax_exempt", default=False)

        customer = {
            "name": name,
            "customer_type": customer_type,
            "credit_tier": credit_tier,
            "tax_exempt": tax_exempt,
        }
        make_common(customer)
        db.customers[customer["id"]] = customer
        return respond(serialize_generic(customer), status=201)

    @app.route("/customers/<customer_id>", methods=["GET"])
    @require_roles("DealerAdmin", "SalesRep", "FinanceManager",
                   "ServiceAdvisor", "AuctionClerk")
    def get_customer(customer_id):
        customer = lookup(db.customers, customer_id)
        return respond(serialize_generic(customer))
