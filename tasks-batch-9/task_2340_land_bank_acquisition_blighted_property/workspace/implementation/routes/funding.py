"""Funding sources, TIF recapture and the acquisition packet workflow."""
import calculations as calc
import serializers as ser
import services as svc
from db import base_record, db, now, ordered, touch
from errors import ApiError, bad_request
from middleware import STAFF_ROLES, authenticate
from response import list_response, object_response
from validation import (field_datetime, field_enum, field_int, field_str,
                        get_body, paginate, present, query_enum, query_str)

CHANNELS = ("TAX_FORECLOSURE", "DONATION", "NEGOTIATED_PURCHASE")
PACKET_STATUSES = ("DUE_DILIGENCE", "ON_HOLD_FUNDING", "BOARD_APPROVED",
                   "CLOSED", "DECLINED")


def register(app):
    # ---------------------------------------------------- funding sources --
    @app.route("/land-bank/funding-sources", methods=["POST"])
    def create_funding_source():
        authenticate("BoardClerk")
        body = get_body()
        name = field_str(body, "name", max_len=120)
        source_type = field_enum(body, "source_type",
                                 ("GRANT", "TIF_RECAPTURE", "GENERAL_FUND"))
        authorized = field_int(body, "authorized_cents", minimum=1)
        restriction = field_enum(body, "restriction",
                                 ("ANY", "ACQUISITION_ONLY", "DEMOLITION_ONLY"))
        expires_on = field_datetime(body, "expires_on")
        record = base_record()
        record.update({
            "name": name,
            "source_type": source_type,
            "authorized_cents": authorized,
            "restriction": restriction,
            "expires_on": expires_on,
            "committed_cents": 0,
            "disbursed_cents": 0,
            "available_cents": authorized,
            "reserve_floor_cents": calc.reserve_floor_cents(authorized),
            "open_run_count": 0,
            "status": "ACTIVE",
            "recaptured_cents": 0,
        })
        db.funding_sources[record["id"]] = record
        return object_response(ser.funding_source_out(record), 201)

    @app.route("/land-bank/funding-sources/<source_id>", methods=["GET"])
    def read_funding_source(source_id):
        authenticate(*STAFF_ROLES)
        fs = svc.get_funding_source(source_id)
        return object_response(ser.funding_source_out(fs))

    @app.route("/land-bank/funding-sources/<source_id>/demolition-runs",
               methods=["GET"])
    def list_source_runs(source_id):
        authenticate("BoardClerk", "InventoryManager", "CountyTreasurer")
        status = query_enum("status", ("PLANNED", "EXECUTED", "VOID"))
        fs = svc.get_funding_source(source_id)
        records = sorted(
            [r for r in db.runs.values() if r["funding_source_id"] == fs["id"]],
            key=lambda r: r["run_sequence"],
        )
        if status is not None:
            records = [r for r in records if r["status"] == status]
        items, meta = paginate(records, ser.run_out)
        return list_response(items, meta)

    @app.route("/land-bank/funding-sources/<source_id>/tif-recapture",
               methods=["POST"])
    def tif_recapture(source_id):
        authenticate("CountyTreasurer")
        body = get_body()
        recapture = field_int(body, "recapture_cents", minimum=0)
        field_int(body, "tax_year", minimum=1900, maximum=2200)
        fs = svc.get_funding_source(source_id)
        fs["authorized_cents"] = fs["authorized_cents"] + recapture
        fs["recaptured_cents"] = fs["recaptured_cents"] + recapture
        svc.refresh_funding(fs)
        return object_response(ser.funding_source_out(fs))

    # ------------------------------------------------- acquisition packets --
    @app.route("/land-bank/acquisition-packets", methods=["POST"])
    def create_packet():
        user_id, _role = authenticate("IntakeOfficer")
        body = get_body()
        property_id = field_str(body, "property_id")
        funding_source_id = field_str(body, "funding_source_id")
        channel = field_enum(body, "channel", CHANNELS)
        offer_price = field_int(body, "offer_price_cents", minimum=0)
        title_fee = field_int(body, "title_search_fee_cents", minimum=0)
        case_no = field_str(body, "foreclosure_case_no", required=False)
        donor_name = field_str(body, "donor_name", required=False)

        if channel == "TAX_FORECLOSURE":
            if case_no is None:
                raise bad_request("foreclosure_case_no is required for a TAX_FORECLOSURE packet.")
            if donor_name is not None:
                raise bad_request("donor_name is not permitted for a TAX_FORECLOSURE packet.")
        elif channel == "DONATION":
            if donor_name is None:
                raise bad_request("donor_name is required for a DONATION packet.")
            if case_no is not None:
                raise bad_request("foreclosure_case_no is not permitted for a DONATION packet.")
            if offer_price != 0:
                raise bad_request("offer_price_cents must be exactly 0 for a DONATION packet.")
        else:
            if case_no is not None or donor_name is not None:
                raise bad_request(
                    "A NEGOTIATED_PURCHASE packet carries neither foreclosure_case_no nor donor_name.")

        prop = svc.get_property(property_id)
        fs = svc.get_funding_source(funding_source_id)
        if not svc.restriction_admits(fs, "ACQUISITION"):
            raise ApiError("ERR_FUNDING_RESTRICTION_VIOLATION")

        record = base_record()
        record.update({
            "property_id": prop["id"],
            "funding_source_id": fs["id"],
            "channel": channel,
            "offer_price_cents": offer_price,
            "title_search_fee_cents": title_fee,
            "foreclosure_case_no": case_no,
            "donor_name": donor_name,
            "status": "DUE_DILIGENCE",
            "committed_cents": 0,
            "initiated_by_user_id": user_id,
            "closed_by_user_id": None,
            "resolution_no": None,
            "deed_reference": None,
            "declined_reason": None,
            "hold_reason": None,
        })
        db.packets[record["id"]] = record
        return object_response(ser.packet_out(record), 201)

    @app.route("/land-bank/acquisition-packets/<packet_id>", methods=["GET"])
    def read_packet(packet_id):
        authenticate("IntakeOfficer", "BoardClerk", "CountyTreasurer")
        packet = svc.get_packet(packet_id)
        return object_response(ser.packet_out(packet))

    @app.route("/land-bank/acquisition-packets", methods=["GET"])
    def list_packets():
        authenticate("IntakeOfficer", "BoardClerk", "CountyTreasurer")
        property_id = query_str("property_id")
        funding_source_id = query_str("funding_source_id")
        status = query_enum("status", PACKET_STATUSES)
        records = ordered(list(db.packets.values()))
        if property_id is not None:
            records = [r for r in records if r["property_id"] == property_id]
        if funding_source_id is not None:
            records = [r for r in records if r["funding_source_id"] == funding_source_id]
        if status is not None:
            records = [r for r in records if r["status"] == status]
        items, meta = paginate(records, ser.packet_out)
        return list_response(items, meta)

    @app.route("/land-bank/acquisition-packets/<packet_id>/board-approval",
               methods=["POST"])
    def board_approve_packet(packet_id):
        authenticate("BoardClerk")
        body = get_body()
        resolution_no = field_str(body, "resolution_no")
        packet = svc.get_packet(packet_id)
        if packet["status"] != "DUE_DILIGENCE":
            raise ApiError("ERR_PACKET_INVALID_STATE")
        fs = svc.get_funding_source(packet["funding_source_id"])
        amount = packet["offer_price_cents"] + packet["title_search_fee_cents"]
        if not svc.restriction_admits(fs, "ACQUISITION"):
            raise ApiError("ERR_FUNDING_RESTRICTION_VIOLATION")
        if fs["status"] != "ACTIVE":
            raise ApiError("ERR_FUNDING_CONSTRAINED")
        if fs["available_cents"] < amount:
            raise ApiError("ERR_FUNDING_INSUFFICIENT")
        packet["status"] = "BOARD_APPROVED"
        packet["resolution_no"] = resolution_no
        packet["committed_cents"] = amount
        touch(packet)
        svc.refresh_funding(fs)
        return object_response(ser.packet_out(packet))

    @app.route("/land-bank/acquisition-packets/<packet_id>/close",
               methods=["POST"])
    def close_packet(packet_id):
        user_id, _role = authenticate("IntakeOfficer")
        body = get_body()
        deed_reference = field_str(body, "deed_reference")
        packet = svc.get_packet(packet_id)
        if packet["status"] != "BOARD_APPROVED":
            raise ApiError("ERR_PACKET_INVALID_STATE")
        prop = svc.get_property(packet["property_id"])
        if prop["custody_status"] != "PROSPECT":
            raise ApiError("ERR_PROPERTY_NOT_IN_INVENTORY")
        if user_id == packet["initiated_by_user_id"]:
            raise ApiError("ERR_SEGREGATION_OF_DUTIES")
        fs = svc.get_funding_source(packet["funding_source_id"])
        amount = packet["offer_price_cents"] + packet["title_search_fee_cents"]

        packet["status"] = "CLOSED"
        packet["deed_reference"] = deed_reference
        packet["closed_by_user_id"] = user_id
        packet["committed_cents"] = 0
        touch(packet)

        prop["custody_status"] = "ACQUIRED"
        prop["acquisition_channel"] = packet["channel"]
        prop["acquired_at"] = now()
        prop["acquisition_cost_cents"] = amount
        prop["pre_acquisition_delinquency_cents"] = prop["delinquent_tax_balance_cents"]
        svc.stamp_intake_score(prop)
        svc.refresh_blight(prop)
        svc.refresh_funding(fs)
        return object_response(ser.packet_out(packet))

    @app.route("/land-bank/acquisition-packets/<packet_id>/decline",
               methods=["POST"])
    def decline_packet(packet_id):
        authenticate("IntakeOfficer")
        body = get_body()
        declined_reason = field_str(body, "declined_reason")
        packet = svc.get_packet(packet_id)
        if packet["status"] not in ("DUE_DILIGENCE", "ON_HOLD_FUNDING",
                                   "BOARD_APPROVED"):
            raise ApiError("ERR_PACKET_INVALID_STATE")
        fs = svc.get_funding_source(packet["funding_source_id"])
        packet["status"] = "DECLINED"
        packet["declined_reason"] = declined_reason
        packet["committed_cents"] = 0
        packet["hold_reason"] = None
        touch(packet)
        svc.refresh_funding(fs)
        return object_response(ser.packet_out(packet))

    # -------------------------------------------------------- contractors --
    @app.route("/land-bank/contractors", methods=["POST"])
    def create_contractor():
        authenticate("InventoryManager")
        body = get_body()
        name = field_str(body, "name", max_len=120)
        license_expires_on = field_datetime(body, "license_expires_on")
        crews = field_int(body, "max_concurrent_crews", minimum=1)
        specialties = body.get("specialties")
        if not isinstance(specialties, list) or len(specialties) == 0:
            raise bad_request("Field 'specialties' must be a non-empty array.")
        for item in specialties:
            if not isinstance(item, str) or item not in calc.WORK_TYPES:
                raise bad_request("Field 'specialties' contains an unsupported work type.")
        debarred = False
        if present(body, "debarred"):
            value = body["debarred"]
            if not isinstance(value, bool):
                raise bad_request("Field 'debarred' must be a boolean.")
            debarred = value
        record = base_record()
        record.update({
            "name": name,
            "license_expires_on": license_expires_on,
            "max_concurrent_crews": crews,
            "specialties": list(specialties),
            "debarred": debarred,
        })
        db.contractors[record["id"]] = record
        return object_response(ser.contractor_out(record), 201)
