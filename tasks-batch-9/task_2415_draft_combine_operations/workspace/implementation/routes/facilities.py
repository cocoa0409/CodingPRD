"""Facility inventory: medical stations and interview rooms (PRD 3.1)."""

from flask import Blueprint

import auth
import constants as K
import logic
import respond
import validate
from db import db

bp = Blueprint("facilities", __name__)


@bp.post("/medical-stations")
def create_station():
    auth.begin(["LeagueDraftAdmin"])
    data = validate.body()
    station_code = validate.string(data, "station_code")
    exam_type = validate.enum(data, "exam_type", K.EXAM_TYPES)
    buffer_minutes = validate.integer(
        data, "turnaround_buffer_minutes", required=False, minimum=0, maximum=60
    )
    status = validate.enum(
        data, "status", K.FACILITY_STATUSES, required=False, default="AVAILABLE"
    )
    rec = db.insert(
        db.medical_stations,
        "MedicalStation",
        {
            "station_code": station_code,
            "exam_type": exam_type,
            "turnaround_buffer_minutes": 15 if buffer_minutes is None else buffer_minutes,
            "status": status,
        },
    )
    return respond.created(rec)


@bp.get("/medical-stations/<station_id>")
def get_station(station_id):
    auth.begin(["LeagueDraftAdmin", "CombineMedicalExaminer"])
    return respond.one(logic.path_lookup(db.medical_stations, station_id))


@bp.post("/interview-rooms")
def create_room():
    auth.begin(["LeagueDraftAdmin"])
    data = validate.body()
    room_code = validate.string(data, "room_code")
    capacity = validate.integer(
        data, "concurrent_capacity", required=False, minimum=1, maximum=8
    )
    status = validate.enum(
        data, "status", K.FACILITY_STATUSES, required=False, default="AVAILABLE"
    )
    rec = db.insert(
        db.interview_rooms,
        "InterviewRoom",
        {
            "room_code": room_code,
            "concurrent_capacity": 2 if capacity is None else capacity,
            "status": status,
        },
    )
    return respond.created(rec)


@bp.get("/interview-rooms/<room_id>")
def get_room(room_id):
    auth.begin(["LeagueDraftAdmin", "ClubGM"])
    return respond.one(logic.path_lookup(db.interview_rooms, room_id))
