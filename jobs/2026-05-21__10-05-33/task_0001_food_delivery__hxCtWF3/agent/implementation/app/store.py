"""In-memory data store. Single-threaded model — Flask runs with threaded=False."""
from collections import defaultdict


class Store:
    def __init__(self):
        self.restaurants: dict[str, dict] = {}
        self.menu_items: dict[str, dict] = {}
        self.customers: dict[str, dict] = {}
        self.customer_phone: dict[str, str] = {}  # phone -> id
        self.riders: dict[str, dict] = {}
        self.rider_phone: dict[str, str] = {}
        self.orders: dict[str, dict] = {}
        self.assignments: dict[str, dict] = {}
        self.route_groups: dict[str, dict] = {}
        self.returns: dict[str, dict] = {}
        self.fines: dict[str, dict] = {}
        self.work_orders: dict[str, dict] = {}
        # secondary indexes (rebuilt as needed by callers)
        self.assignments_by_order: dict[str, list[str]] = defaultdict(list)

    def reset(self):
        self.__init__()
