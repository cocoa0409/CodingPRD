"""In-memory data store. Each table is a dict keyed by id (UUID string)."""

import threading
import uuid


_lock = threading.RLock()

# Tables
stores = {}
recipes = {}
ingredients = {}
recipe_ingredients = {}        # id -> RecipeIngredient row
store_orders = {}
order_lines = {}               # id -> OrderLine row
production_batches = {}
vehicles = {}
delivery_routes = {}
inventory_batches = {}
replenishment_rules = {}
loss_records = {}
audit_log_entries = []         # ordered list (append-only)

# Equipment-class capacity reservations: { (target_delivery_date, equipment_class) : minutes_reserved }
equipment_reservations = {}


def new_id():
    return str(uuid.uuid4())


def lock():
    return _lock


def reset_all():
    with _lock:
        stores.clear()
        recipes.clear()
        ingredients.clear()
        recipe_ingredients.clear()
        store_orders.clear()
        order_lines.clear()
        production_batches.clear()
        vehicles.clear()
        delivery_routes.clear()
        inventory_batches.clear()
        replenishment_rules.clear()
        loss_records.clear()
        audit_log_entries.clear()
        equipment_reservations.clear()
