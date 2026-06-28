"""Mutation bookkeeping: refresh updated_at and bump version (PRD 2.4 / 2.5).

Entities that carry the full quartet (id, created_at, updated_at, version):
Location, ServiceType, Product, Room, Technician, Member, Membership,
Reservation, RetailSale. Every mutation — including cascades — refreshes
updated_at and increments version by exactly 1.
"""
from clock import clock


def touch(entity):
    entity["updated_at"] = clock.get()
    entity["version"] = entity["version"] + 1
    return entity
