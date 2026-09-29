"""Quote pricing and the order money roll-up (PRD Sections 3.3, 3.4 and 3.8).

Two pricing variants share one per-line arithmetic: QUOTED (the index pinned on
the quote at issue) and INVOICED (the index effective on the delivery date).
"""
import db
import calculations as calc
from services import lookup


def line_basis(product, put_up, requested_length_ft, parallel_set_size):
    return calc.cut_charge_and_billable_length(product, put_up, requested_length_ft, parallel_set_size)


def price_quote(quote, index_entry):
    """Compute -- without writing anything -- every line value and the roll-up.

    Issue must be able to test segregation of duties on the subtotal it computes
    in this very request before it writes anything at all.
    """
    branch = db.branches[quote["branch_id"]]
    lines = lookup.quote_lines_of(quote["id"])
    computed = []
    for line in lines:
        product = db.products[line["product_id"]]
        basis = line_basis(product, line["put_up"], line["requested_length_ft"], line["parallel_set_size"])
        priced = calc.price_line(
            product, index_entry, basis["billable_length_ft"],
            line["parallel_set_size"], basis["cut_charge_cents_total"],
        )
        computed.append({
            "line": line,
            "billable_length_ft": basis["billable_length_ft"],
            "reel_count": basis["reel_count"],
            "cut_charge_cents_total": basis["cut_charge_cents_total"],
            "deposit_cents_total": basis["deposit_cents_total"],
            "parallel_set_size": line["parallel_set_size"],
            "copper_adder_cents_per_ft": priced["copper_adder_cents_per_ft"],
            "metal_cents": priced["metal_cents"],
            "base_cents": priced["base_cents"],
            "extended_cents": priced["extended_cents"],
        })
    rollup = calc.order_money_rollup(computed, branch)
    return computed, rollup


def apply_quote_pricing(quote, index_entry, computed, rollup):
    """Write the QUOTED variant onto the quote and each of its lines."""
    for item in computed:
        line = item["line"]
        line["billable_length_ft"] = item["billable_length_ft"]
        line["reel_count"] = item["reel_count"]
        line["cut_charge_cents_total"] = item["cut_charge_cents_total"]
        line["deposit_cents_total"] = item["deposit_cents_total"]
        line["copper_adder_cents_per_ft"] = item["copper_adder_cents_per_ft"]
        line["metal_cents"] = item["metal_cents"]
        line["base_cents"] = item["base_cents"]
        line["quoted_extended_cents"] = item["extended_cents"]
        db.touch(line)

    quote["copper_index_entry_id"] = index_entry["id"]
    quote["line_subtotal_cents"] = rollup["line_subtotal_cents"]
    quote["physical_reel_count"] = rollup["physical_reel_count"]
    quote["gross_freight_cents"] = rollup["gross_freight_cents"]
    quote["rebate_pct"] = rollup["rebate_pct"]
    quote["rebate_cents"] = rollup["rebate_cents"]
    quote["freight_cents"] = rollup["freight_cents"]
    quote["quoted_total_cents"] = rollup["total_cents"]
    quote["deposit_quoted_cents"] = rollup["deposit_total_cents"]


def clear_quote_pricing(quote):
    """Reprice erasure: the line structure survives, only its pricing is discarded."""
    quote["copper_index_entry_id"] = None
    quote["issued_at"] = None
    quote["valid_until"] = None
    quote["issued_by_user_id"] = None
    quote["line_subtotal_cents"] = 0
    quote["physical_reel_count"] = 0
    quote["gross_freight_cents"] = 0
    quote["rebate_pct"] = 0
    quote["rebate_cents"] = 0
    quote["freight_cents"] = 0
    quote["quoted_total_cents"] = 0
    quote["deposit_quoted_cents"] = 0
    for line in lookup.quote_lines_of(quote["id"]):
        line["copper_adder_cents_per_ft"] = 0
        line["metal_cents"] = 0
        line["base_cents"] = 0
        line["cut_charge_cents_total"] = 0
        line["deposit_cents_total"] = 0
        line["quoted_extended_cents"] = 0
        db.touch(line)


def price_order_invoiced(order, index_entry):
    """The INVOICED variant over the order's lines, plus the six-step roll-up."""
    branch = db.branches[order["branch_id"]]
    lines = lookup.order_lines_of(order["id"])
    computed = []
    for line in lines:
        product = db.products[line["product_id"]]
        basis = line_basis(product, line["put_up"], line["requested_length_ft"], line["parallel_set_size"])
        priced = calc.price_line(
            product, index_entry, line["billable_length_ft"],
            line["parallel_set_size"], basis["cut_charge_cents_total"],
        )
        computed.append({
            "line": line,
            "reel_count": basis["reel_count"],
            "parallel_set_size": line["parallel_set_size"],
            "deposit_cents_total": basis["deposit_cents_total"],
            "extended_cents": priced["extended_cents"],
        })
    rollup = calc.order_money_rollup(computed, branch)
    return computed, rollup
