"""In-memory data store. Starts empty on every boot; no seeding."""
import itertools
import uuid

customers = {}
units = {}
quotes = {}
quote_lines = {}
rental_contracts = {}
meter_readings = {}
fuel_events = {}
service_calls = {}
technicians = {}
operators = {}
certifications = {}
lease_contracts = {}
lease_inspections = {}
reconditioning_orders = {}

_seq = itertools.count(1)


def next_seq():
    return next(_seq)


def new_id():
    return str(uuid.uuid4())
