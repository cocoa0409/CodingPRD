"""Package quotes, quote lines and two-stage laundromat financing (PRD 3.8)."""

from decimal import Decimal

from flask import g

import lookup
import response
import validate
from db import base_row, bump, db, order_created_asc, order_created_desc
from errors import (ERR_DISTRIBUTOR_NOT_AUTHORIZED, ERR_DISTRIBUTOR_STATE_INVALID,
                    ERR_INVALID_REQUEST, ERR_OWNERSHIP_VIOLATION,
                    ERR_PAYMENT_MODULE_NOT_SUPPORTED, ERR_QUOTE_HAS_NO_LINES,
                    ERR_QUOTE_STATE_INVALID, ERR_STALE_QUOTE_VERSION, fail)
from middleware import (CHANNEL_MANAGER, DISTRIBUTOR, acting_distributor, endpoint)
from services import calc
from services.cascades import lines_of_quote

QUOTE_STATES = ["DRAFT", "SUBMITTED", "REVISION_REQUESTED", "APPROVED", "DECLINED"]
FINANCING_PROGRAMS = ["NONE", "TERM_36", "TERM_60"]
LINE_MODULES = ["NONE", "COIN", "CARD", "MOBILE"]
EDITABLE_STATES = ("DRAFT", "REVISION_REQUESTED")


def _own_quote(quote):
    """Rules 22 then 23 for the Distributor role; operators are unscoped."""
    if g.role != DISTRIBUTOR:
        return
    distributor = acting_distributor()
    if quote["distributor_id"] != distributor["id"]:
        fail(ERR_OWNERSHIP_VIOLATION, "This quote belongs to another distributor.")


def _rollup(quote):
    lines = lines_of_quote(quote["id"])
    quote.update(calc.quote_rollup(lines, quote["package_discount_pct"],
                                   quote["freight_cents"]))


def _check_expected_version(quote, expected):
    if expected != quote["version"]:
        fail(ERR_STALE_QUOTE_VERSION,
             "expected_quote_version %s does not match the quote's version %s."
             % (expected, quote["version"]))


def _provisional_financing(quote, distributor):
    if quote["financing_program"] == "NONE":
        return
    _, fee, principal = calc.principal_and_fee(quote["total_cents"],
                                               quote["down_payment_cents"])
    apr = calc.apr_bp(quote["financing_program"], quote["stated_credit_score"],
                      distributor["distributor_state"])
    quote["origination_fee_cents"] = fee
    quote["financed_principal_cents"] = principal
    quote["provisional_apr_bp"] = apr
    quote["provisional_monthly_payment_cents"] = calc.monthly_payment_cents(
        principal, apr, quote["financing_program"])


def _final_financing(quote, distributor):
    if quote["financing_program"] == "NONE":
        return
    standing = distributor["distributor_state"] if distributor is not None else "NONE"
    apr = calc.apr_bp(quote["financing_program"], quote["verified_credit_score"],
                      standing)
    quote["final_apr_bp"] = apr
    quote["monthly_payment_cents"] = calc.monthly_payment_cents(
        quote["financed_principal_cents"], apr, quote["financing_program"])


def register(app):
    @app.post("/clm/quotes")
    @endpoint([DISTRIBUTOR])
    def create_quote():
        body = validate.parse_body()
        distributor_id = body.id_ref("distributor_id")
        customer_name = body.string("customer_name", 1, 160)
        laundromat_site_code = body.string("laundromat_site_code", 1, 32)
        stated_credit_score = body.integer("stated_credit_score", minimum=300,
                                           maximum=850)
        financing_program = body.enum("financing_program", FINANCING_PROGRAMS,
                                      required=False, default="NONE")
        down_payment_cents = body.integer("down_payment_cents", minimum=0,
                                          required=False, default=0)
        package_discount_pct = body.decimal("package_discount_pct",
                                            minimum=Decimal("0.00"),
                                            maximum=Decimal("15.00"),
                                            required=False,
                                            default=Decimal("0.00"))
        freight_cents = body.integer("freight_cents", minimum=0, required=False,
                                     default=0)
        distributor = lookup.distributor(distributor_id)   # rule 21
        acting_distributor()                               # rule 22
        if distributor["id"] != g.user_id:                 # rule 23
            fail(ERR_OWNERSHIP_VIOLATION,
                 "A distributor may only draft its own quotes.")
        if distributor["distributor_state"] == "TERMINATED":   # rule 29
            fail(ERR_DISTRIBUTOR_STATE_INVALID,
                 "A TERMINATED distributor may not draft quotes.")

        row = base_row()
        row.update({
            "distributor_id": distributor["id"],
            "customer_name": customer_name,
            "laundromat_site_code": laundromat_site_code,
            "stated_credit_score": stated_credit_score,
            "verified_credit_score": None,
            "financing_program": financing_program,
            "down_payment_cents": down_payment_cents,
            "package_discount_pct": package_discount_pct,
            "freight_cents": freight_cents,
            "quote_state": "DRAFT",
            "line_count": 0,
            "line_subtotal_cents": 0,
            "discount_cents": 0,
            "total_cents": freight_cents,
            "origination_fee_cents": 0,
            "financed_principal_cents": 0,
            "provisional_apr_bp": None,
            "provisional_monthly_payment_cents": None,
            "final_apr_bp": None,
            "monthly_payment_cents": None,
            "decided_by_user_id": None,
            "revision_round": 0,
        })
        db.quotes[row["id"]] = row
        return response.created(row)

    @app.get("/clm/quotes/<quote_id>")
    @endpoint([CHANNEL_MANAGER, DISTRIBUTOR])
    def read_quote(quote_id):
        quote = lookup.quote(quote_id)   # rule 13
        _own_quote(quote)                # rules 22, 23
        return response.ok(quote)

    @app.get("/clm/quotes")
    @endpoint([CHANNEL_MANAGER, DISTRIBUTOR])
    def list_quotes():
        limit, offset = validate.q_pagination()
        distributor_id = validate.q_str("distributor_id")
        quote_state = validate.q_enum("quote_state", QUOTE_STATES)
        rows = list(db.quotes.values())
        if g.role == DISTRIBUTOR:
            rows = [r for r in rows if r["distributor_id"] == g.user_id]
        if distributor_id is not None:
            rows = [r for r in rows if r["distributor_id"] == distributor_id]
        if quote_state is not None:
            rows = [r for r in rows if r["quote_state"] == quote_state]
        rows = order_created_desc(rows)
        page, total = validate.paginate(rows, limit, offset)
        return response.listing(page, limit, offset, total)

    @app.post("/clm/quotes/<quote_id>/lines")
    @endpoint([DISTRIBUTOR])
    def create_quote_line(quote_id):
        body = validate.parse_body()
        model_id = body.id_ref("model_id")
        quantity = body.integer("quantity", minimum=1, maximum=50)
        payment_module = body.enum("payment_module", LINE_MODULES, required=False,
                                   default="NONE")
        line_discount_pct = body.decimal("line_discount_pct",
                                         minimum=Decimal("0.00"),
                                         maximum=Decimal("20.00"),
                                         required=False, default=Decimal("0.00"))
        expected_quote_version = body.integer("expected_quote_version")
        quote = lookup.quote(quote_id)          # rule 13
        model = lookup.model(model_id)          # rule 16
        _own_quote(quote)                       # rules 22, 23
        if quote["quote_state"] not in EDITABLE_STATES:      # rule 30
            fail(ERR_QUOTE_STATE_INVALID,
                 "Lines may only be added to a DRAFT or REVISION_REQUESTED quote.")
        _check_expected_version(quote, expected_quote_version)   # rule 32
        # rule 42: payment-module compatibility
        if (payment_module != "NONE"
                and payment_module not in model["payment_module_options"]):
            fail(ERR_PAYMENT_MODULE_NOT_SUPPORTED,
                 "Model %s does not offer the %s payment module."
                 % (model["model_code"], payment_module))

        surcharge = calc.SURCHARGE_CENTS[payment_module]
        line = base_row(versioned=False)
        line.update({
            "quote_id": quote["id"],
            "model_id": model["id"],
            "quantity": quantity,
            "payment_module": payment_module,
            "line_discount_pct": line_discount_pct,
            "unit_price_cents": model["list_price_cents"],
            "payment_surcharge_cents": surcharge,
            "line_total_cents": calc.quote_line_total_cents(
                model["list_price_cents"], surcharge, quantity, line_discount_pct),
        })
        db.quote_lines[line["id"]] = line
        _rollup(quote)
        bump(quote)
        return response.created(line)

    @app.delete("/clm/quotes/<quote_id>/lines/<line_id>")
    @endpoint([DISTRIBUTOR])
    def delete_quote_line(quote_id, line_id):
        body = validate.parse_body()
        expected_quote_version = body.integer("expected_quote_version")
        quote = lookup.quote(quote_id)               # rule 13
        line = lookup.quote_line_of(quote, line_id)  # rule 14
        _own_quote(quote)                            # rules 22, 23
        if quote["quote_state"] not in EDITABLE_STATES:       # rule 30
            fail(ERR_QUOTE_STATE_INVALID,
                 "Lines may only be removed from a DRAFT or REVISION_REQUESTED quote.")
        _check_expected_version(quote, expected_quote_version)   # rule 32
        db.quote_lines.pop(line["id"], None)
        _rollup(quote)
        bump(quote)
        return response.ok(quote)

    @app.get("/clm/quote-lines/<line_id>")
    @endpoint([CHANNEL_MANAGER, DISTRIBUTOR])
    def read_quote_line(line_id):
        return response.ok(lookup.quote_line(line_id))

    @app.get("/clm/quote-lines")
    @endpoint([CHANNEL_MANAGER, DISTRIBUTOR])
    def list_quote_lines():
        limit, offset = validate.q_pagination()
        quote_id = validate.q_str("quote_id")
        model_id = validate.q_str("model_id")
        rows = list(db.quote_lines.values())
        if quote_id is not None:
            rows = [r for r in rows if r["quote_id"] == quote_id]
        if model_id is not None:
            rows = [r for r in rows if r["model_id"] == model_id]
        rows = order_created_asc(rows)
        page, total = validate.paginate(rows, limit, offset)
        return response.listing(page, limit, offset, total)

    @app.post("/clm/quotes/<quote_id>/submit")
    @endpoint([DISTRIBUTOR])
    def submit_quote(quote_id):
        validate.parse_body()
        quote = lookup.quote(quote_id)   # rule 13
        _own_quote(quote)                # rules 22, 23
        if quote["quote_state"] not in EDITABLE_STATES:      # rule 30
            fail(ERR_QUOTE_STATE_INVALID,
                 "Only a DRAFT or REVISION_REQUESTED quote may be submitted.")
        distributor = db.distributors.get(quote["distributor_id"])
        if quote["line_count"] < 1:                          # rule 53
            fail(ERR_QUOTE_HAS_NO_LINES,
                 "A quote must carry at least one line before submission.")
        if distributor is None or distributor["distributor_state"] != "AUTHORIZED":
            fail(ERR_DISTRIBUTOR_NOT_AUTHORIZED,             # rule 54
                 "Quote submission requires an AUTHORIZED distributor.")
        if (quote["financing_program"] != "NONE"
                and quote["down_payment_cents"] >= quote["total_cents"]):
            fail(ERR_INVALID_REQUEST,
                 "down_payment_cents must be strictly less than total_cents.")

        quote["quote_state"] = "SUBMITTED"
        _provisional_financing(quote, distributor)
        bump(quote)
        return response.ok(quote)

    @app.post("/clm/quotes/<quote_id>/decision")
    @endpoint([CHANNEL_MANAGER])
    def decide_quote(quote_id):
        body = validate.parse_body()
        decision = body.enum("decision", ["APPROVE", "DECLINE", "REQUEST_REVISION"])
        body.string("note", maxlen=1000, required=False)
        verified_credit_score = body.integer(
            "verified_credit_score", minimum=300, maximum=850,
            required=(decision == "APPROVE"))
        quote = lookup.quote(quote_id)   # rule 13
        if quote["quote_state"] != "SUBMITTED":              # rule 30
            fail(ERR_QUOTE_STATE_INVALID,
                 "Only a SUBMITTED quote may be decided.")

        quote["decided_by_user_id"] = g.user_id
        if decision == "APPROVE":
            quote["verified_credit_score"] = verified_credit_score
            quote["quote_state"] = "APPROVED"
            _final_financing(quote, db.distributors.get(quote["distributor_id"]))
        elif decision == "DECLINE":
            quote["quote_state"] = "DECLINED"
        else:
            quote["quote_state"] = "REVISION_REQUESTED"
            quote["revision_round"] = quote["revision_round"] + 1
            quote["provisional_apr_bp"] = None
            quote["provisional_monthly_payment_cents"] = None
        bump(quote)
        return response.ok(quote)
