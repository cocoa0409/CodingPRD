"""Post-implementation adherence measurement (PRD §3.8)."""
from flask import Blueprint, request

import const
import validate
from common import base_record, now, touch
from db import db
from errors import ApiError
from middleware import authenticate, get_measurement, get_order_set
from response import created, ok, paginate
from services import calc, domain

bp = Blueprint("adherence", __name__)


def _rows(data):
    rows = validate.array(data, "unit_observations", required=True, min_len=1)
    parsed = []
    for row in rows:
        if not isinstance(row, dict):
            raise ApiError("ERR_INVALID_REQUEST", "unit_observations entries must be objects")
        unit_code = validate.string(row, "unit_code", required=True)
        eligible = validate.integer(row, "eligible_orders", required=True)
        adherent = validate.integer(row, "adherent_orders", required=True)
        unintended = validate.integer(row, "unintended_events", required=True)
        parsed.append({
            "unit_code": unit_code,
            "eligible_orders": eligible,
            "adherent_orders": adherent,
            "unintended_events": unintended,
        })
    return parsed


@bp.post("/cds/order-sets/<cid>/adherence-measurements")
def create_measurement(cid):
    authenticate(("CommitteeChair", "InformaticsBuilder", "ClinicalSponsor"))
    order_set = get_order_set(cid)
    data = validate.body()

    period_start = validate.instant(data, "measurement_period_start", required=True)
    period_end = validate.instant(data, "measurement_period_end", required=True)
    rows = _rows(data)

    if not period_start < period_end:
        raise ApiError(
            "ERR_INVALID_WINDOW_BOUNDS",
            "measurement_period_end must be strictly after measurement_period_start",
        )

    for row in rows:
        if row["eligible_orders"] < 0 or row["adherent_orders"] < 0 or row["unintended_events"] < 0:
            raise ApiError("ERR_INVALID_OBSERVATION_COUNTS", "Observation counts may not be negative")
        if row["adherent_orders"] > row["eligible_orders"]:
            raise ApiError(
                "ERR_INVALID_OBSERVATION_COUNTS",
                "adherent_orders may not exceed eligible_orders",
            )

    included = [r for r in rows if r["eligible_orders"] > 0]
    excluded = [r for r in rows if r["eligible_orders"] == 0]

    measurement = base_record()
    measurement.update({
        "order_set_id": order_set["id"],
        "measurement_period_start": period_start,
        "measurement_period_end": period_end,
        "unit_observations": rows,
        "included_unit_count": len(included),
        "excluded_unit_count": len(excluded),
        "measurement_state": "PROVISIONAL" if included else "INSUFFICIENT_DATA",
        "adherence_pct_per_protocol": calc.per_protocol_pct(rows),
        "adherence_pct_intention_to_treat": None,
        "unintended_event_count": sum(r["unintended_events"] for r in rows),
        "unintended_event_rate_per_100": None,
        "verdict": None,
        "finalized_at": None,
    })
    db.adherence_measurements[measurement["id"]] = measurement
    return created(measurement)


@bp.get("/cds/order-sets/<cid>/adherence-measurements")
def list_measurements(cid):
    authenticate(const.ANY_ROLE)
    order_set = get_order_set(cid)
    records = [
        m for m in db.adherence_measurements.values() if m["order_set_id"] == order_set["id"]
    ]
    for field in ("measurement_state", "verdict"):
        value = request.args.get(field)
        if value:
            records = [r for r in records if r.get(field) == value]
    return paginate(records)


@bp.post("/cds/adherence-measurements/<cid>/finalize")
def finalize(cid):
    authenticate(("CommitteeChair",))
    measurement = get_measurement(cid)
    data = validate.body()
    verdict = validate.enum(data, "verdict", const.VERDICTS, required=True)
    validate.string(data, "finalization_note")

    if measurement["measurement_state"] != "PROVISIONAL":
        raise ApiError("ERR_MEASUREMENT_NOT_PROVISIONAL", "Measurement is not PROVISIONAL")

    rows = measurement["unit_observations"]
    itt = calc.intention_to_treat_pct(rows)
    rate = calc.unintended_rate_per_100(rows)

    if not calc.verdict_supported(verdict, itt, rate):
        raise ApiError(
            "ERR_ADHERENCE_VERDICT_UNSUPPORTED",
            "The submitted verdict is not supported by the computed adherence figures",
        )

    measurement["adherence_pct_intention_to_treat"] = itt
    measurement["unintended_event_rate_per_100"] = rate
    measurement["measurement_state"] = "FINALIZED"
    measurement["verdict"] = verdict
    measurement["finalized_at"] = now()
    touch(measurement)

    order_set = db.order_sets.get(measurement["order_set_id"])
    if order_set is not None:
        order_set["latest_adherence_pct"] = itt
        if verdict == "RETIRE" and order_set["publication_state"] == "PUBLISHED":
            order_set["publication_state"] = "EXPIRING"
        touch(order_set)

        if verdict == "RETIRE":
            task = domain.governing_task("ORDER_SET", order_set["id"])
            if task is not None and task["state"] == "PENDING":
                task["state"] = "OVERDUE"
                touch(task)

    return ok(measurement)
