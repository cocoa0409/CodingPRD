class Store:
    def __init__(self):
        self.clear()

    def clear(self):
        self.restaurants = {}
        self.menu_items = {}
        self.customers = {}
        self.riders = {}
        self.orders = {}
        self.assignments = {}
        self.route_groups = {}
        self.returns = {}
        self.fines = {}
        self.work_orders = {}


store = Store()
