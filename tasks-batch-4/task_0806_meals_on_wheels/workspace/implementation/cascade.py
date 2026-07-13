"""Cascade side-effects shared across state transitions."""
import db
import core


def cancel_scheduled_deliveries_of_plan(plan_id, within=None):
    """Cancel SCHEDULED deliveries of a plan. `within` = (start_date, end_date) dates
    to restrict cancellation to deliveries whose scheduled_date falls in [start,end]."""
    for d in db.deliveries.values():
        if d["meal_plan_id"] != plan_id or d["status"] != "SCHEDULED":
            continue
        if within is not None:
            sd = core.parse_date(d["scheduled_date"])
            start_d, end_d = within
            if sd is None or not (start_d <= sd <= end_d):
                continue
        d["status"] = "CANCELLED"
        db.touch(d)


def cancel_scheduled_deliveries_of_client(client_id):
    for d in db.deliveries.values():
        if d["client_id"] == client_id and d["status"] == "SCHEDULED":
            d["status"] = "CANCELLED"
            db.touch(d)
