"""Maintenance orders and demolition prioritization runs."""
import calculations as calc
import serializers as ser
import services as svc
from clock import days, hours
from db import base_record, db, now, ordered, touch
from errors import ApiError, bad_request
from middleware import STAFF_ROLES, authenticate
from response import list_response, object_response
from validation import (field_datetime, field_enum, field_int, field_str,
                        get_body, paginate, present, query_enum, query_str)

BUFFER = hours(calc.DEMOLITION_BUFFER_HOURS)


def register(app):
    @app.route("/land-bank/properties/<property_id>/maintenance-orders",
               methods=["POST"])
    def create_order(property_id):
        authenticate("InventoryManager")
        body = get_body()
        work_type = field_enum(body, "work_type", calc.WORK_TYPES)
        contractor_id = field_str(body, "contractor_id")
        funding_source_id = field_str(body, "funding_source_id")
        window_start = field_datetime(body, "window_start")
        window_end = field_datetime(body, "window_end")
        openings_count = field_int(body, "openings_count", required=False, minimum=1)
        if work_type == "SECURE" and openings_count is None:
            raise bad_request("openings_count is required for SECURE work.")
        if work_type != "SECURE" and openings_count is not None:
            raise bad_request("openings_count is only permitted for SECURE work.")
        expected_version = field_int(body, "expected_property_version")

        if window_end <= window_start:
            raise ApiError("ERR_WINDOW_INVALID")

        prop = svc.get_property(property_id)
        contractor = svc.get_contractor(contractor_id)
        fs = svc.get_funding_source(funding_source_id)

        if expected_version != prop["version"]:
            raise ApiError("ERR_STALE_PROPERTY_VERSION")

        if prop["custody_status"] not in svc.INVENTORY_CUSTODY:
            raise ApiError("ERR_PROPERTY_NOT_IN_INVENTORY")

        if contractor["debarred"]:
            raise ApiError("ERR_CONTRACTOR_DEBARRED")
        if work_type not in contractor["specialties"]:
            raise ApiError("ERR_CONTRACTOR_SPECIALTY_MISMATCH")
        if window_end > contractor["license_expires_on"]:
            raise ApiError("ERR_CONTRACTOR_LICENSE_EXPIRED")

        scheduled_here = [o for o in svc.orders_of_property(prop["id"])
                          if o["status"] == "SCHEDULED"]
        for other in ordered(scheduled_here):
            if svc.intersects(window_start, window_end,
                              other["window_start"], other["window_end"]):
                raise ApiError("ERR_PROPERTY_WINDOW_CONFLICT")
        for other in ordered(scheduled_here):
            if work_type == "DEMOLITION":
                demo_start, demo_end = window_start, window_end
                other_start, other_end = other["window_start"], other["window_end"]
            elif other["work_type"] == "DEMOLITION":
                demo_start, demo_end = other["window_start"], other["window_end"]
                other_start, other_end = window_start, window_end
            else:
                continue
            if other_start < demo_end + BUFFER and demo_start - BUFFER < other_end:
                raise ApiError("ERR_DEMOLITION_BUFFER_VIOLATION")

        overlapping = 0
        for other in db.orders.values():
            if other["status"] != "SCHEDULED":
                continue
            if other["contractor_id"] != contractor["id"]:
                continue
            if svc.intersects(window_start, window_end,
                              other["window_start"], other["window_end"]):
                overlapping += 1
        if overlapping >= contractor["max_concurrent_crews"]:
            raise ApiError("ERR_CONTRACTOR_CAPACITY_EXCEEDED")

        if work_type == "DEMOLITION" and not prop["structure_present"]:
            raise ApiError("ERR_DEMOLITION_REQUIRES_STRUCTURE")

        if not svc.restriction_admits(fs, "MAINTENANCE", work_type):
            raise ApiError("ERR_FUNDING_RESTRICTION_VIOLATION")

        estimate = calc.maintenance_order_estimate(
            work_type, prop["lot_area_sqft"], prop["structure_condition_grade"],
            openings_count,
        )
        if fs["available_cents"] < estimate:
            raise ApiError("ERR_FUNDING_INSUFFICIENT")

        record = base_record()
        record.update({
            "property_id": prop["id"],
            "contractor_id": contractor["id"],
            "funding_source_id": fs["id"],
            "demolition_run_id": None,
            "work_type": work_type,
            "window_start": window_start,
            "window_end": window_end,
            "openings_count": openings_count,
            "estimated_cost_cents": estimate,
            "actual_cost_cents": None,
            "status": "SCHEDULED",
            "completed_at": None,
            "cancelled_reason": None,
        })
        db.orders[record["id"]] = record
        touch(prop)
        svc.refresh_funding(fs)
        return object_response(ser.order_out(record), 201)

    @app.route("/land-bank/maintenance-orders/<order_id>", methods=["GET"])
    def read_order(order_id):
        authenticate(*STAFF_ROLES)
        order = svc.get_order(order_id)
        return object_response(ser.order_out(order))

    @app.route("/land-bank/maintenance-orders", methods=["GET"])
    def list_orders():
        authenticate(*STAFF_ROLES)
        property_id = query_str("property_id")
        contractor_id = query_str("contractor_id")
        funding_source_id = query_str("funding_source_id")
        run_id = query_str("demolition_run_id")
        status = query_enum("status", ("SCHEDULED", "COMPLETED", "CANCELLED"))
        work_type = query_enum("work_type", calc.WORK_TYPES)
        records = ordered(list(db.orders.values()))
        if property_id is not None:
            records = [r for r in records if r["property_id"] == property_id]
        if contractor_id is not None:
            records = [r for r in records if r["contractor_id"] == contractor_id]
        if funding_source_id is not None:
            records = [r for r in records if r["funding_source_id"] == funding_source_id]
        if run_id is not None:
            records = [r for r in records if r["demolition_run_id"] == run_id]
        if status is not None:
            records = [r for r in records if r["status"] == status]
        if work_type is not None:
            records = [r for r in records if r["work_type"] == work_type]
        items, meta = paginate(records, ser.order_out)
        return list_response(items, meta)

    @app.route("/land-bank/maintenance-orders/<order_id>/complete",
               methods=["POST"])
    def complete_order(order_id):
        authenticate("InventoryManager")
        body = get_body()
        actual_cost = field_int(body, "actual_cost_cents", minimum=0)
        order = svc.get_order(order_id)
        if order["status"] != "SCHEDULED":
            raise ApiError("ERR_ORDER_NOT_SCHEDULED")
        fs = svc.get_funding_source(order["funding_source_id"])
        if fs["status"] == "EXPIRED":
            raise ApiError("ERR_FUNDING_SOURCE_EXPIRED")
        prop = svc.get_property(order["property_id"])

        order["status"] = "COMPLETED"
        order["actual_cost_cents"] = actual_cost
        order["completed_at"] = now()
        touch(order)

        if order["work_type"] == "SECURE":
            prop["secured"] = True
        elif order["work_type"] == "MOW":
            prop["last_mow_at"] = now()
        else:
            prop["demolished_at"] = now()
            prop["structure_present"] = False
        svc.refresh_blight(prop)
        svc.refresh_funding(fs)
        return object_response(ser.order_out(order))

    @app.route("/land-bank/maintenance-orders/<order_id>/cancel",
               methods=["POST"])
    def cancel_order(order_id):
        authenticate("InventoryManager")
        body = get_body()
        cancelled_reason = field_str(body, "cancelled_reason")
        order = svc.get_order(order_id)
        if order["status"] != "SCHEDULED":
            raise ApiError("ERR_ORDER_NOT_SCHEDULED")
        fs = svc.get_funding_source(order["funding_source_id"])
        order["status"] = "CANCELLED"
        order["cancelled_reason"] = cancelled_reason
        touch(order)
        if order["demolition_run_id"]:
            run = db.runs.get(order["demolition_run_id"])
            if run is not None:
                run["orders_created_count"] = max(0, run["orders_created_count"] - 1)
                touch(run)
        svc.refresh_funding(fs)
        return object_response(ser.order_out(order))

    # --------------------------------------------------- demolition runs ---
    @app.route("/land-bank/demolition-runs", methods=["POST"])
    def create_run():
        authenticate("InventoryManager")
        body = get_body()
        funding_source_id = field_str(body, "funding_source_id")
        budget_cents = field_int(body, "budget_cents", minimum=1)
        ward_filter = field_int(body, "situs_ward_filter", required=False,
                                minimum=1, maximum=9)
        expected_version = field_int(body, "expected_funding_source_version")
        fs = svc.get_funding_source(funding_source_id)
        if expected_version != fs["version"]:
            raise ApiError("ERR_STALE_FUNDING_SOURCE_VERSION")
        if not svc.restriction_admits(fs, "DEMOLITION_RUN"):
            raise ApiError("ERR_FUNDING_RESTRICTION_VIOLATION")
        if budget_cents > fs["available_cents"]:
            raise ApiError("ERR_RUN_BUDGET_EXCEEDS_AVAILABLE")

        allocation = svc.allocate_run(budget_cents, ward_filter)
        prior_runs = len(svc.runs_of_source(fs["id"]))
        record = base_record()
        record.update({
            "funding_source_id": fs["id"],
            "run_sequence": prior_runs + 1,
            "budget_cents": budget_cents,
            "situs_ward_filter": ward_filter,
            "dropped_property_ids": [],
            "orders_created_count": 0,
            "status": "PLANNED",
            "executed_at": None,
        })
        record.update(allocation)
        db.runs[record["id"]] = record
        fs["open_run_count"] = fs["open_run_count"] + 1
        svc.refresh_funding(fs)
        return object_response(ser.run_out(record), 201)

    @app.route("/land-bank/demolition-runs/<run_id>/execute", methods=["POST"])
    def execute_run(run_id):
        authenticate("InventoryManager")
        run = svc.get_run(run_id)
        if run["status"] != "PLANNED":
            raise ApiError("ERR_RUN_NOT_PLANNED")
        if run["properties_selected_count"] == 0:
            raise ApiError("ERR_EMPTY_RUN")
        fs = svc.get_funding_source(run["funding_source_id"])

        survivors = []
        dropped = []
        for property_id in run["selected_property_ids"]:
            prop = db.properties.get(property_id)
            if prop is None:
                dropped.append(property_id)
                continue
            svc.refresh_blight(prop, bump_version=False)
            if (
                prop["custody_status"] not in ("ACQUIRED", "LISTED")
                or prop["title_status"] != "CLEAR"
                or svc.has_demolition_order(prop["id"])
            ):
                dropped.append(property_id)
            else:
                survivors.append(prop)

        estimates = run.get("_estimates", {})
        if survivors:
            for prop in survivors:
                svc.create_run_order(run, prop, estimates.get(prop["id"], 0))
                touch(prop)
            run["status"] = "EXECUTED"
            run["orders_created_count"] = len(survivors)
        else:
            run["status"] = "VOID"
            run["orders_created_count"] = 0
        run["dropped_property_ids"] = dropped
        run["executed_at"] = now()
        touch(run)
        fs["open_run_count"] = max(0, fs["open_run_count"] - 1)
        svc.refresh_funding(fs)
        return object_response(ser.run_out(run))
