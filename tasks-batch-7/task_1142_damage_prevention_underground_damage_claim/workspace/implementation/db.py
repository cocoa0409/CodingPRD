"""In-memory data store. Starts empty on every boot."""

import threading


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.excavators = {}
        self.locators = {}
        self.locate_tickets = {}
        self.locate_responses = {}
        self.damage_cases = {}
        self.evidence_items = {}
        self.timeline_events = {}
        self.fault_allocations = {}
        self.cost_line_items = {}
        self.claim_invoices = {}
        self.payments = {}
        self.disputes = {}
        self.subrogation_cases = {}
        self.regulatory_reports = {}
        self.violation_records = {}
        self.training_courses = {}
        self.training_assignments = {}
        # sequence counters for human references
        self.ticket_seq = 0
        self.case_seq = 0
        # insertion order counter for deterministic list ordering (created_at ties)
        self.insert_seq = 0

    def next_ticket_number(self):
        self.ticket_seq += 1
        return f"TCK-{self.ticket_seq}"

    def next_case_number(self):
        self.case_seq += 1
        return f"DC-{self.case_seq}"

    def next_insert_seq(self):
        self.insert_seq += 1
        return self.insert_seq


db = Store()
