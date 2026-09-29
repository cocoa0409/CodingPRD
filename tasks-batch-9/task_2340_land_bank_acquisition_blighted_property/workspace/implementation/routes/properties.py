"""Parcel registry, county data feeds, title actions, hearings and adjacency."""
import calculations as calc
import serializers as ser
import services as svc
from db import base_record, db, now, ordered, touch
from errors import ApiError, bad_request
from middleware import ROLES, STAFF_ROLES, authenticate
from response import list_response, object_response
from validation import (field_bool, field_datetime, field_enum, field_int,
                        field_number, field_str, get_body, paginate,
                        query_enum, query_int, query_str)

GRADES = ("A", "B", "C", "D", "F")
PARCEL_ID_PATTERN = r"^APN-[0-9]{4,8}$"


def register(app):
    # ------------------------------------------------------------ registry --
    @app.route("/land-bank/properties", methods=["POST"])
    def create_property():
        authenticate("IntakeOfficer")
        body = get_body()
        parcel_id = field_str(body, "parcel_id", pattern=PARCEL_ID_PATTERN)
        address = field_str(body, "address", max_len=200)
        situs_ward = field_int(body, "situs_ward", minimum=1, maximum=9)
        lot_area_sqft = field_int(body, "lot_area_sqft", minimum=100)
        assessed_value_cents = field_int(body, "assessed_value_cents", minimum=0)
        structure_present = field_bool(body, "structure_present")
        grade = field_enum(body, "structure_condition_grade", GRADES)
        vacancy_months = field_int(body, "vacancy_months", minimum=0)

        for existing in db.properties.values():
            if existing["parcel_id"] == parcel_id:
                raise ApiError("ERR_PARCEL_ID_DUPLICATE")

        record = base_record()
        record.update({
            "parcel_id": parcel_id,
            "address": address,
            "situs_ward": situs_ward,
            "lot_area_sqft": lot_area_sqft,
            "assessed_value_cents": assessed_value_cents,
            "structure_present": structure_present,
            "structure_condition_grade": grade,
            "vacancy_months": vacancy_months,
            "nuisance_complaint_count": 0,
            "open_code_violation_count": 0,
            "delinquent_tax_balance_cents": 0,
            "pre_acquisition_delinquency_cents": 0,
            "custody_status": "PROSPECT",
            "title_status": "CLOUDED",
            "acquisition_channel": None,
            "acquired_at": None,
            "acquisition_cost_cents": 0,
            "intake_blight_score": None,
            "current_blight_score": 0,
            "secured": False,
            "last_mow_at": None,
            "demolished_at": None,
            "owner_of_record_applicant_id": None,
            "listed_at": None,
        })
        db.properties[record["id"]] = record
        return object_response(ser.property_out(record), 201)

    @app.route("/land-bank/properties/<property_id>", methods=["GET"])
    def read_property(property_id):
        authenticate(*ROLES)
        prop = svc.get_property(property_id)
        return object_response(ser.property_out(prop))

    @app.route("/land-bank/properties", methods=["GET"])
    def list_properties():
        authenticate(*STAFF_ROLES)
        custody = query_enum("custody_status",
                             ("PROSPECT", "ACQUIRED", "LISTED", "CONVEYED", "REVERTED"))
        title = query_enum("title_status", ("CLOUDED", "QUIET_TITLE_FILED", "CLEAR"))
        ward = query_int("situs_ward", 1, 9)
        owner = query_str("owner_of_record_applicant_id")
        records = ordered(list(db.properties.values()))
        if custody is not None:
            records = [r for r in records if r["custody_status"] == custody]
        if title is not None:
            records = [r for r in records if r["title_status"] == title]
        if ward is not None:
            records = [r for r in records if r["situs_ward"] == ward]
        if owner is not None:
            records = [r for r in records if r["owner_of_record_applicant_id"] == owner]
        items, meta = paginate(records, ser.property_out)
        return list_response(items, meta)

    # --------------------------------------------------------- data feeds --
    @app.route("/land-bank/properties/<property_id>/code-violation-report",
               methods=["POST"])
    def code_violation_report(property_id):
        authenticate("IntakeOfficer")
        body = get_body()
        violations = field_int(body, "open_code_violation_count", minimum=0)
        complaints = field_int(body, "nuisance_complaint_count", minimum=0)
        prop = svc.get_property(property_id)
        prop["open_code_violation_count"] = violations
        prop["nuisance_complaint_count"] = complaints
        svc.refresh_blight(prop)
        svc.refresh_owner_of(prop)
        return object_response(ser.property_out(prop))

    @app.route("/land-bank/properties/<property_id>/tax-roll-posting",
               methods=["POST"])
    def tax_roll_posting(property_id):
        authenticate("CountyTreasurer")
        body = get_body()
        balance = field_int(body, "delinquent_tax_balance_cents", minimum=0)
        field_int(body, "tax_year", minimum=1900, maximum=2200)
        prop = svc.get_property(property_id)
        prop["delinquent_tax_balance_cents"] = balance
        touch(prop)
        svc.refresh_owner_of(prop)
        return object_response(ser.property_out(prop))

    @app.route("/land-bank/properties/<property_id>/owner-of-record",
               methods=["POST"])
    def owner_of_record(property_id):
        authenticate("IntakeOfficer")
        body = get_body()
        applicant_id = field_str(body, "applicant_id")
        prop = svc.get_property(property_id)
        applicant = svc.get_applicant(applicant_id)
        if prop["custody_status"] != "PROSPECT":
            raise ApiError("ERR_PROPERTY_NOT_IN_INVENTORY")
        prop["owner_of_record_applicant_id"] = applicant["id"]
        touch(prop)
        svc.refresh_applicant(applicant)
        return object_response(ser.property_out(prop))

    @app.route("/land-bank/properties/<property_id>/list", methods=["POST"])
    def list_property_for_disposition(property_id):
        authenticate("DispositionOfficer")
        prop = svc.get_property(property_id)
        if prop["custody_status"] not in ("ACQUIRED", "REVERTED"):
            raise ApiError("ERR_PROPERTY_NOT_IN_INVENTORY")
        for order in svc.orders_of_property(prop["id"]):
            if order["work_type"] == "DEMOLITION" and order["status"] == "SCHEDULED":
                raise ApiError("ERR_PROPERTY_NOT_IN_INVENTORY")
        if prop["title_status"] != "CLEAR":
            raise ApiError("ERR_TITLE_NOT_CLEAR")
        prop["custody_status"] = "LISTED"
        prop["listed_at"] = now()
        touch(prop)
        return object_response(ser.property_out(prop))

    @app.route("/land-bank/properties/<property_id>/price-quote", methods=["GET"])
    def price_quote(property_id):
        authenticate("DispositionOfficer", "Applicant")
        program = query_str("program")
        if program is None or program not in calc.PROGRAMS:
            raise bad_request("Query parameter 'program' is required and must name a program.")
        prop = svc.get_property(property_id)
        return object_response(calc.disposition_price_quote(prop, program))

    # ------------------------------------------------------ title actions --
    @app.route("/land-bank/properties/<property_id>/title-actions",
               methods=["POST"])
    def create_title_action(property_id):
        authenticate("IntakeOfficer")
        body = get_body()
        action_type = field_enum(
            body, "action_type",
            ("QUIET_TITLE_SUIT", "TAX_DEED_CONFIRMATION", "LIEN_RELEASE"),
        )
        prop = svc.get_property(property_id)
        actions = [a for a in db.title_actions.values()
                   if a["property_id"] == prop["id"]]
        for action in actions:
            if action["status"] == "FILED":
                raise ApiError("ERR_TITLE_ACTION_OPEN")
        record = base_record()
        record.update({
            "property_id": prop["id"],
            "action_type": action_type,
            "round_no": len(actions) + 1,
            "filed_at": now(),
            "defect_count": 0,
            "status": "FILED",
            "adjudicated_at": None,
        })
        db.title_actions[record["id"]] = record
        prop["title_status"] = "QUIET_TITLE_FILED"
        touch(prop)
        return object_response(ser.title_action_out(record), 201)

    @app.route("/land-bank/properties/<property_id>/title-actions",
               methods=["GET"])
    def list_title_actions(property_id):
        authenticate("IntakeOfficer", "BoardClerk", "DispositionOfficer",
                     "CountyTreasurer")
        status = query_enum("status", ("FILED", "CLEARED", "DEFECT_REMAINS"))
        prop = svc.get_property(property_id)
        records = ordered([a for a in db.title_actions.values()
                           if a["property_id"] == prop["id"]])
        if status is not None:
            records = [r for r in records if r["status"] == status]
        items, meta = paginate(records, ser.title_action_out)
        return list_response(items, meta)

    @app.route("/land-bank/title-actions/<action_id>/adjudicate",
               methods=["POST"])
    def adjudicate_title_action(action_id):
        authenticate("IntakeOfficer")
        body = get_body()
        outcome = field_enum(body, "outcome", ("CLEARED", "DEFECT_REMAINS"))
        defect_count = field_int(body, "defect_count", required=False, minimum=0)
        if outcome == "CLEARED" and defect_count not in (None, 0):
            raise bad_request("A CLEARED outcome may not carry a non-zero defect_count.")
        if outcome == "DEFECT_REMAINS" and (defect_count is None or defect_count < 1):
            raise bad_request("A DEFECT_REMAINS outcome requires defect_count of at least 1.")
        action = svc.get_title_action(action_id)
        if action["status"] != "FILED":
            raise ApiError("ERR_TITLE_ACTION_ALREADY_ADJUDICATED")
        prop = svc.get_property(action["property_id"])
        action["adjudicated_at"] = now()
        if outcome == "CLEARED":
            action["status"] = "CLEARED"
            action["defect_count"] = 0
            prop["title_status"] = "CLEAR"
        else:
            action["status"] = "DEFECT_REMAINS"
            action["defect_count"] = defect_count
            prop["title_status"] = "CLOUDED"
        touch(action)
        touch(prop)
        if outcome == "CLEARED":
            svc.restore_suspended_applications(prop["id"])
        return object_response(ser.title_action_out(action))

    # ---------------------------------------------------- reuse hearings ---
    @app.route("/land-bank/properties/<property_id>/reuse-hearings",
               methods=["POST"])
    def create_reuse_hearing(property_id):
        authenticate("DispositionOfficer")
        body = get_body()
        hearing_at = field_datetime(body, "hearing_at")
        comment_count = field_int(body, "comment_count", minimum=0)
        support_count = field_int(body, "support_count", minimum=0)
        summary = field_str(body, "summary", max_len=500)
        if support_count > comment_count:
            raise bad_request("support_count may not exceed comment_count.")
        prop = svc.get_property(property_id)
        record = base_record(versioned=False)
        record.update({
            "property_id": prop["id"],
            "hearing_at": hearing_at,
            "comment_count": comment_count,
            "support_count": support_count,
            "support_ratio": calc.hearing_support_ratio(support_count, comment_count),
            "summary": summary,
        })
        db.hearings[record["id"]] = record
        return object_response(ser.hearing_out(record), 201)

    @app.route("/land-bank/properties/<property_id>/reuse-hearings",
               methods=["GET"])
    def list_reuse_hearings(property_id):
        authenticate("IntakeOfficer", "BoardClerk", "DispositionOfficer",
                     "InventoryManager", "Applicant")
        prop = svc.get_property(property_id)
        records = sorted(
            [h for h in db.hearings.values() if h["property_id"] == prop["id"]],
            key=lambda h: (h["hearing_at"], h["created_at"], h["_seq"]),
            reverse=True,
        )
        items, meta = paginate(records, ser.hearing_out)
        return list_response(items, meta)

    # ------------------------------------------------------- adjacencies ---
    @app.route("/land-bank/parcel-adjacencies", methods=["POST"])
    def create_adjacency():
        user_id, _role = authenticate("IntakeOfficer")
        body = get_body()
        property_id = field_str(body, "property_id")
        adjacent_property_id = field_str(body, "adjacent_property_id")
        shared_boundary_feet = field_number(body, "shared_boundary_feet",
                                            exclusive_minimum=0)
        if property_id == adjacent_property_id:
            raise ApiError("ERR_SELF_ADJACENCY")
        for edge in db.adjacencies.values():
            pair = {edge["property_id"], edge["adjacent_property_id"]}
            if pair == {property_id, adjacent_property_id}:
                raise ApiError("ERR_ADJACENCY_DUPLICATE")
        left = svc.get_property(property_id)
        right = svc.get_property(adjacent_property_id)
        record = base_record(versioned=False)
        record.update({
            "property_id": left["id"],
            "adjacent_property_id": right["id"],
            "shared_boundary_feet": shared_boundary_feet,
            "recorded_by_user_id": user_id,
        })
        db.adjacencies[record["id"]] = record
        svc.refresh_blight(left)
        svc.refresh_blight(right)
        return object_response(ser.adjacency_out(record), 201)

    @app.route("/land-bank/properties/<property_id>/adjacencies",
               methods=["GET"])
    def list_adjacencies(property_id):
        authenticate("IntakeOfficer", "BoardClerk", "DispositionOfficer",
                     "InventoryManager", "Applicant")
        prop = svc.get_property(property_id)
        records = ordered([
            e for e in db.adjacencies.values()
            if prop["id"] in (e["property_id"], e["adjacent_property_id"])
        ])
        items, meta = paginate(records, ser.adjacency_out)
        return list_response(items, meta)
