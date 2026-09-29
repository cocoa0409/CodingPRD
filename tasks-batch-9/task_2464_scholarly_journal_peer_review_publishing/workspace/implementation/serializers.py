"""Output shaping. Stored rows already carry the declared field names, so most
entities serialize as-is; the manuscript's derived fields are computed on read
so they can never drift from the screenings and reviews they summarise.
"""

import calc
from db import public


def journal_out(row):
    return public(row)


def editor_out(row):
    return public(row)


def author_out(row):
    return public(row)


def reviewer_out(row):
    return public(row)


def manuscript_out(row):
    data = public(row)
    data["integrity_status"] = calc.integrity_status(row)
    data["formatting_status"] = calc.formatting_status(row)
    data["submitted_review_count"] = calc.submitted_review_count(row)
    return data


def screening_out(row):
    return public(row)


def assignment_out(row):
    return public(row)


def invitation_out(row):
    return public(row)


def review_out(row):
    return public(row)


def decision_out(row):
    return public(row)


def appeal_out(row):
    return public(row)


def ethics_case_out(row):
    return public(row)


def production_job_out(row):
    return public(row)


def invoice_out(row):
    return public(row)


def many(rows, shaper):
    return [shaper(row) for row in rows]
