"""Row -> response body projections."""
from db import db, public


def standard_out(row):
    criteria_count = sum(1 for c in db.criteria.values()
                         if c["standard_id"] == row["id"])
    return public(row, {"criteria_count": criteria_count})


def criterion_out(row):
    return public(row)


def product_out(row):
    return public(row)


def component_out(row):
    return public(row)


def environment_out(row):
    scheduled = sum(1 for r in db.runs.values()
                    if r["environment_id"] == row["id"]
                    and r["status"] in ("SCHEDULED", "COMPLETED"))
    return public(row, {"scheduled_run_count": scheduled})


def run_out(row):
    return public(row)


def assessment_out(row):
    return public(row)


def report_out(row):
    return public(row)


def train_out(row):
    return public(row)


def issue_out(row):
    return public(row)


def questionnaire_out(row):
    return public(row)


def complaint_out(row):
    return public(row)
