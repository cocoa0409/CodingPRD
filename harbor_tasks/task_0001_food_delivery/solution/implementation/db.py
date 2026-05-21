"""In-memory data store."""
from threading import RLock

LOCK = RLock()

restaurants = {}         # id -> Restaurant dict
riders = {}              # id -> Rider dict
customers = {}           # id -> Customer dict
menu_items = {}          # id -> MenuItem dict
orders = {}              # id -> Order dict
assignments = {}         # id -> Assignment dict
route_groups = {}        # id -> RouteGroup dict
fines = {}               # id -> Fine dict
returns_tbl = {}         # id -> Return dict
work_orders = {}         # id -> WorkOrder dict


def reset_all():
    restaurants.clear()
    riders.clear()
    customers.clear()
    menu_items.clear()
    orders.clear()
    assignments.clear()
    route_groups.clear()
    fines.clear()
    returns_tbl.clear()
    work_orders.clear()
