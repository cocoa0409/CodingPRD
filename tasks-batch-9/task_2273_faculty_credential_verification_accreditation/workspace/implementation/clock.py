"""The logical clock (PRD 2.4). No wall-clock read drives any temporal rule."""

import util
from db import store


def current_instant():
    return store.clock_dt


def current_date():
    return store.clock_dt.date()


def current_text():
    return store.clock_text


def set_clock(text, parsed):
    store.clock_dt = parsed
    store.clock_text = text


def stamp():
    """The logical-clock instant rendered as an audit timestamp."""
    return util.dt_to_iso(store.clock_dt)
