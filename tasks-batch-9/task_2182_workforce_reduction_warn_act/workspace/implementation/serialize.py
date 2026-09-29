"""Public representations of each stored record."""
from core import public
from domain import blocking_window_end_utc


def plan_out(rec):
    return public(rec)


def site_out(rec):
    return public(rec)


def employee_out(rec):
    return public(rec)


def selection_out(rec):
    return public(rec)


def rule_out(rec):
    return public(rec)


def analysis_out(rec):
    return public(rec)


def disclosure_out(rec):
    return public(rec)


def notice_out(rec):
    return public(rec)


def offer_out(rec):
    data = public(rec)
    data["blocking_window_end_utc"] = blocking_window_end_utc(rec)
    return data


def restriction_out(rec):
    return public(rec)
