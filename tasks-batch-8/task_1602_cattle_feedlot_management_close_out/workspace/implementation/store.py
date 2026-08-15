"""In-memory data store. Starts empty on every boot; no seeding."""
import itertools
import uuid

owners = {}
pens = {}
lots = {}
rations = {}
pen_assignments = {}
ration_assignments = {}
feed_calls = {}
health_events = {}
death_losses = {}
insurance_claims = {}
hedge_positions = {}
close_outs = {}
invoices = {}

_seq = itertools.count(1)


def next_seq():
    return next(_seq)


def new_id():
    return str(uuid.uuid4())
