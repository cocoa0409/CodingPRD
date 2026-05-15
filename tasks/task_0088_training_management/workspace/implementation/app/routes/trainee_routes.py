"""Trainee endpoints."""
from __future__ import annotations

from flask import Flask, g

from ..auth import require_auth
from ..errors import ApiError
from ..store import common_fields_create, get_store
from ..services.lookups import get_trainee
from ..services.serializers import serialize_trainee
from ._helpers import created, get_json_body, ok, with_lock


def register(app: Flask) -> None:
    @app.post("/training/trainees")
    @require_auth("TrainingAdmin")
    @with_lock
    def create_trainee():
        body = get_json_body()
        employee_no = body.get("employee_no")
        full_name = body.get("full_name")
        department = body.get("department")
        job_level = body.get("job_level")
        if not isinstance(employee_no, str) or not employee_no:
            raise ApiError("ERR_REFERENCE_NOT_FOUND", "employee_no required.", http_status=422)
        if not isinstance(full_name, str) or not full_name:
            raise ApiError("ERR_REFERENCE_NOT_FOUND", "full_name required.", http_status=422)
        if not isinstance(department, str) or not department:
            raise ApiError("ERR_REFERENCE_NOT_FOUND", "department required.", http_status=422)
        try:
            jl = int(job_level)
        except (TypeError, ValueError):
            raise ApiError("ERR_REFERENCE_NOT_FOUND", "job_level must be integer.", http_status=422)
        if not (1 <= jl <= 15):
            raise ApiError("ERR_REFERENCE_NOT_FOUND", "job_level out of range.", http_status=422)

        store = get_store()
        if employee_no in store.trainee_employee_no_uniq:
            raise ApiError("ERR_REFERENCE_NOT_FOUND", "employee_no not unique.", http_status=422)

        base = common_fields_create()
        row = {
            **base,
            "employee_no": employee_no,
            "full_name": full_name,
            "department": department,
            "job_level": jl,
            "status": "ACTIVE",
        }
        store.trainees[base["id"]] = row
        store.trainee_employee_no_uniq[employee_no] = base["id"]
        return created(serialize_trainee(row))

    @app.get("/training/trainees/<tid>")
    @require_auth("TrainingAdmin", "DepartmentManager", "Trainee")
    @with_lock
    def fetch_trainee(tid):
        t = get_trainee(tid)
        if g.user_role == "Trainee" and t["id"] != g.user_id:
            raise ApiError("ERR_FORBIDDEN_ROLE", "Cannot view other trainee record.")
        return ok(serialize_trainee(t))
