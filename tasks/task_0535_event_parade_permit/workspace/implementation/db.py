"""In-memory data store. All state is process-local and starts empty on boot."""


class DB:
    def __init__(self):
        self.applicants = {}
        self.venues = {}
        self.closure_schedules = {}
        self.applications = {}
        self.route_segments = {}
        self.reviews = {}
        self.conditions = {}
        self.cois = {}
        self.deposits = {}
        self.invoices = {}
        self.debriefs = {}


db = DB()
