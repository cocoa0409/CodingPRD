"""The 7 calculations (SCAFFOLD §1.3, PRD §3.2 / §3.4 / §3.6 / §3.7).

1. compute_recipe_cost     -> services/product.py (recompute_recipe_cost)
2. depletion_variance      -> here (depletion_variance for a CountLine)
3. resolve_closing_units   -> here (resolve_closing_units)
4. keg_yield               -> here (keg_yield)
5. reconcile_invoice       -> here (reconcile_invoice)
6. reorder_quantity        -> here (reorder_quantity)
7. menu_engineering        -> here (menu_engineering)
"""
import math
from decimal import Decimal

from db import db
from errors import (ApiError, ERR_NOT_A_KEG, ERR_VALIDATION, ERR_NO_ACTIVE_PAR,
                    ERR_EMPTY_MENU, ERR_WEIGHT_BELOW_TARE)
from money import D, round_cents, round_half_up, to_number
from services.product import active_par

# Constants (SCAFFOLD §1.3)
DEFAULT_LINE_LOSS_PCT = Decimal("0.05")
TIER1_THRESHOLD_CENTS = 30000
TIER2_THRESHOLD_CENTS = 40000
TAX_RATE = Decimal("0.0875")
POPULARITY_FACTOR = Decimal("0.70")


# -- 3. resolve_closing_units -------------------------------------------------

def resolve_closing_units(count_line, product):
    """UNITS -> counted_units. WEIGHT -> net/density(1dp)/volume(3dp).
    gross <= tare => ERR_WEIGHT_BELOW_TARE (PRD §3.7)."""
    if count_line["count_method"] == "UNITS":
        return to_number(round_half_up(D(count_line["counted_units"]), 3))
    # WEIGHT
    gross = D(count_line["gross_weight_g"])
    tare = D(product["empty_container_weight_g"])
    net = gross - tare
    if net <= 0:
        raise ApiError(ERR_WEIGHT_BELOW_TARE, 422,
                       "gross_weight_g must exceed the product's empty_container_weight_g.")
    remaining_ml = round_half_up(net / D(product["density_g_per_ml"]), 1)
    closing = round_half_up(remaining_ml / D(product["container_volume_ml"]), 3)
    return to_number(closing)


# -- 4. keg_yield -------------------------------------------------------------

def keg_yield(product, pour_size_ml, line_loss_pct):
    """servings_theoretical = floor(volume / pour); servings_net = floor(volume *
    (1-loss) / pour); cost_per_serving = round_half_up(unit_cost / servings_net).
    Non-keg -> ERR_NOT_A_KEG; servings_net == 0 -> ERR_VALIDATION (PRD §3.2)."""
    if product["container_type"] != "KEG":
        raise ApiError(ERR_NOT_A_KEG, 422, "keg-yield requires a KEG product.")
    vol = D(product["container_volume_ml"])
    pour = D(pour_size_ml)
    loss = D(line_loss_pct)
    servings_theoretical = int(math.floor(vol / pour))
    servings_net = int(math.floor((vol * (Decimal(1) - loss)) / pour))
    if servings_net == 0:
        raise ApiError(ERR_VALIDATION, 422, "servings_net is zero; cannot divide.")
    cost_per_serving = round_cents(D(product["unit_cost_cents"]) / D(servings_net))
    return {
        "servings_theoretical": servings_theoretical,
        "servings_net": servings_net,
        "cost_per_serving_cents": cost_per_serving,
    }


# -- 6. reorder_quantity ------------------------------------------------------

def reorder_quantity(product):
    """Requires ACTIVE par (else ERR_NO_ACTIVE_PAR). on_hand >= reorder_point ->
    not triggered, qty 0. Else triggered, raw = ceil(par_level - on_hand),
    suggested_qty = ceil(raw/case_pack)*case_pack (PRD §3.2)."""
    par = active_par(product["id"])
    if par is None:
        raise ApiError(ERR_NO_ACTIVE_PAR, 422, "Product has no ACTIVE par setting.")
    on_hand = D(product["on_hand_units"])
    reorder_point = D(par["reorder_point_units"])
    par_level = D(par["par_level_units"])
    if on_hand >= reorder_point:
        triggered = False
        suggested = 0
    else:
        triggered = True
        raw = int(math.ceil(par_level - on_hand))
        case_pack = int(product["case_pack"])
        suggested = int(math.ceil(D(raw) / D(case_pack))) * case_pack
    return {
        "triggered": triggered,
        "suggested_qty": suggested,
        "par_level_units": to_number(par_level),
        "on_hand_units": to_number(on_hand),
    }


# -- 5. reconcile_invoice -----------------------------------------------------

def reconcile_invoice(invoice):
    """extensions -> subtotal -> discount(tier on subtotal) -> tax((sub-disc)*rate)
    -> total (PRD §3.6). Order is pinned. Mutates invoice + lines in place."""
    lines = [il for il in db.invoice_lines.values() if il["invoice_id"] == invoice["id"]]
    lines.sort(key=lambda il: (il["created_at"], il["_seq"]))
    subtotal = 0
    for il in lines:
        ext = int(il["received_qty"]) * int(il["unit_cost_cents"])
        il["extension_cents"] = ext
        subtotal += ext
    if subtotal >= TIER2_THRESHOLD_CENTS:
        discount_pct = Decimal("0.05")
    elif subtotal >= TIER1_THRESHOLD_CENTS:
        discount_pct = Decimal("0.03")
    else:
        discount_pct = Decimal("0.00")
    discount = round_cents(D(subtotal) * discount_pct)
    tax = round_cents(D(subtotal - discount) * TAX_RATE)
    total = subtotal - discount + tax + int(invoice["freight_cents"])
    invoice["subtotal_cents"] = subtotal
    invoice["discount_cents"] = discount
    invoice["tax_cents"] = tax
    invoice["invoice_total_cents"] = total


# -- 7. menu_engineering ------------------------------------------------------

def menu_engineering():
    """Classify ACTIVE menu items on PUBLISHED recipes into STAR/PLOWHORSE/
    PUZZLE/DOG. Requires >=1 such item with total units_sold >= 1 else
    ERR_EMPTY_MENU. pop_threshold = 0.70 * (1/n). margins exact (PRD §3.4)."""
    universe = []
    for mi in db.menu_items.values():
        if mi["status"] != "ACTIVE":
            continue
        recipe = db.recipes.get(mi["recipe_id"])
        if recipe is None or recipe["status"] != "PUBLISHED":
            continue
        universe.append(mi)
    n = len(universe)
    total_units = sum(int(mi["units_sold"]) for mi in universe)
    if n < 1 or total_units < 1:
        raise ApiError(ERR_EMPTY_MENU, 422,
                       "Menu-engineering requires >= 1 ACTIVE item on a PUBLISHED recipe with cumulative units_sold >= 1.")
    pop_threshold = POPULARITY_FACTOR * (Decimal(1) / Decimal(n))
    margins = {}
    margin_sum = Decimal(0)
    for mi in universe:
        recipe = db.recipes.get(mi["recipe_id"])
        margin = D(mi["menu_price_cents"]) - D(recipe["recipe_cost_cents"])
        margins[mi["id"]] = margin
        margin_sum += margin
    avg_margin = margin_sum / Decimal(n)  # exact rational
    for mi in universe:
        pop_index = round_half_up(D(mi["units_sold"]) / D(total_units), 4)
        high_pop = pop_index >= pop_threshold
        high_margin = margins[mi["id"]] >= avg_margin
        if high_pop and high_margin:
            cls = "STAR"
        elif high_pop and not high_margin:
            cls = "PLOWHORSE"
        elif (not high_pop) and high_margin:
            cls = "PUZZLE"
        else:
            cls = "DOG"
        mi["menu_class"] = cls
    return universe
