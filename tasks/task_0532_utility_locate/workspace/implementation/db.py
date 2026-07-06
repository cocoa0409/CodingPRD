"""In-memory data store. Empty on every boot (no seeding)."""
from clock import Clock


class DB:
    def __init__(self):
        self.excavators = {}
        self.member_utilities = {}
        self.locate_techs = {}
        self.locate_tickets = {}
        self.utility_notifications = {}
        self.positive_responses = {}
        self.locate_assignments = {}
        self.mark_outs = {}
        self.meet_requests = {}
        self.damage_reports = {}
        self.clock = Clock()
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = DB()


def reset():
    global db
    db = DB()
