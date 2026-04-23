import threading


class Storage:
    def __init__(self):
        self.lock = threading.RLock()
        self.restaurants = {}
        self.menu_items = {}
        self.riders = {}
        self.customers = {}
        self.orders = {}
        self.assignments = {}
        self.route_groups = {}
        self.fines = {}
        self.returns = {}
        self.work_orders = {}

    def clear(self):
        with self.lock:
            self.restaurants.clear()
            self.menu_items.clear()
            self.riders.clear()
            self.customers.clear()
            self.orders.clear()
            self.assignments.clear()
            self.route_groups.clear()
            self.fines.clear()
            self.returns.clear()
            self.work_orders.clear()


db = Storage()
