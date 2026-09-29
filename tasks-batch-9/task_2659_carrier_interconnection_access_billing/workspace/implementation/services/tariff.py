"""Tariff window arithmetic. Tariff windows are half-open: they include the
effective instant and exclude the expiry instant (PRD 2.8)."""
from store import db, ordered


def covers(filing, instant):
    return filing["effective_date"] <= instant < filing["expiry_date"]


def windows_intersect(a_start, a_end, b_start, b_end):
    """Half-open [start, end) intersection: adjacency is not overlap."""
    return a_start < b_end and b_start < a_end


def effective_filing_for(rate_element, instant):
    """The EFFECTIVE filing for the rate element whose half-open window covers
    the instant."""
    for filing in ordered(db.tariff_filings):
        if filing["rate_element"] != rate_element:
            continue
        if filing["status"] != "EFFECTIVE":
            continue
        if covers(filing, instant):
            return filing
    return None
