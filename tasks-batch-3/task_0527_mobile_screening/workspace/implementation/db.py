"""In-memory data store. Starts empty on every boot; no seeding."""
import uuid
import itertools


class DB:
    def __init__(self):
        self.mobile_units = {}
        self.staff = {}
        self.sponsors = {}
        self.grants = {}
        self.events = {}
        self.participants = {}
        self.appointments = {}
        self.referrals = {}
        self.charges = {}
        self.reminders = {}
        self._seq = itertools.count(1)

    def next_seq(self):
        # monotonic creation sequence to give a stable ascending sort even
        # when created_at timestamps tie under the logical clock
        return next(self._seq)


db = DB()


def new_id():
    return str(uuid.uuid4())
