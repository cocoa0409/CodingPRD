"""Multi-leg connection-buffer check (PRD 3.7, scaffold validation priority 9).

Legs ordered by leg_order. For each adjacent pair, the next leg's scheduled
departure minute minus the inbound leg's scheduled arrival minute must be at
least the owning operator's default_connection_buffer_min, accounting for
next-day rollover when a route's arrive_minute < depart_minute.
"""
import db


def _route_for_service_date(service_date_id):
    sd = db.service_dates[service_date_id]
    return db.routes[sd["route_id"]]


def connection_buffer_ok(legs):
    """legs: list of leg records (with service_date_id, leg_order). Returns True
    if every adjacent pair satisfies the operator's connection buffer."""
    if len(legs) <= 1:
        return True

    ordered = sorted(legs, key=lambda lg: lg["leg_order"])

    for i in range(len(ordered) - 1):
        cur = ordered[i]
        nxt = ordered[i + 1]
        cur_route = _route_for_service_date(cur["service_date_id"])
        nxt_route = _route_for_service_date(nxt["service_date_id"])

        # Operator of the inbound (current) leg owns the buffer policy.
        operator = db.operators[cur_route["operator_id"]]
        buffer_min = operator["default_connection_buffer_min"]

        cur_arrive = cur_route["arrive_minute_of_day"]
        cur_depart = cur_route["depart_minute_of_day"]
        # Next-day rollover: arrival earlier than departure -> arrival is +1 day.
        if cur_arrive < cur_depart:
            cur_arrive += 1440

        nxt_depart = nxt_route["depart_minute_of_day"]
        gap = nxt_depart - cur_arrive
        if gap < buffer_min:
            return False
    return True
