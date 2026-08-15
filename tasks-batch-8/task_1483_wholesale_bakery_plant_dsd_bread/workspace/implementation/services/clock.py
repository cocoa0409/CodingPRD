"""Logical clock service."""

from datetime import datetime, timezone

from db import DB
from helpers import parse_iso_datetime


def get_clock():
    return DB.clock


def set_clock(to_iso8601):
    DB.clock = parse_iso_datetime(to_iso8601, "to_iso8601")
    return DB.clock
