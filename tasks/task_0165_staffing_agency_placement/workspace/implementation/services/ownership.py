"""Entity-backed ownership checks (PRD 2.1).

Client (X-User-ID == Client.id) may act on:
  - job orders whose client_id == X-User-ID
  - submissions/interviews/placements/timesheets/invoices reachable from those
    job orders (and from the client directly, for invoices)

Candidate (X-User-ID == Candidate.id) may act on:
  - placements whose candidate_id == X-User-ID
  - timesheets of those placements

An ownership violation surfaces as ERR_UNAUTHORIZED (403).
"""

import db
import errors
from errors import ApiError


def _deny():
    raise ApiError(errors.ERR_UNAUTHORIZED, 403, "Actor does not own the targeted resource.")


# --- reachability resolvers: each returns the owning client_id / candidate_id ---

def job_order_client(job_order):
    return job_order["client_id"]


def submission_client(submission):
    jo = db.job_orders.get(submission["job_order_id"])
    return jo["client_id"] if jo else None


def interview_client(interview):
    sub = db.submissions.get(interview["submission_id"])
    return submission_client(sub) if sub else None


def placement_client(placement):
    return placement.get("client_id")


def timesheet_client(timesheet):
    pl = db.placements.get(timesheet["placement_id"])
    return placement_client(pl) if pl else None


def invoice_client(invoice):
    return invoice["client_id"]


# --- enforcement entry points used by routes ---

def client_owns(user_id, owning_client_id):
    if owning_client_id != user_id:
        _deny()


def candidate_owns_placement(user_id, placement):
    if placement["candidate_id"] != user_id:
        _deny()


def candidate_owns_timesheet(user_id, timesheet):
    pl = db.placements.get(timesheet["placement_id"])
    if pl is None or pl["candidate_id"] != user_id:
        _deny()
