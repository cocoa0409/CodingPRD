class Store:
    def __init__(self):
        self.restaurants = {}
        self.menu_items = {}
        self.riders = {}
        self.customers = {}
        self.orders = {}
        self.assignments = {}
        self.route_groups = {}
        self.returns = {}
        self.work_orders = {}
        self.fines = {}

    def reset(self):
        self.__init__()


store = Store()
