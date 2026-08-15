"""Auth header extraction, role checking, ownership scoping (PRD 2.1, 2.9)."""

from functools import wraps

from flask import g, request

import db
from errors import unauthenticated, unauthorized, ownership

ROLES = {"ServiceWriter", "YardManager", "EnvironmentalOfficer", "Accountant", "Owner"}


def authenticate():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise unauthenticated()
    g.user_id = uid
    g.user_role = role


def require_roles(*roles):
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            authenticate()
            if g.user_role not in roles:
                raise unauthorized()
            return fn(*args, **kwargs)

        return wrapper

    return deco


def check_owner_vessel(vessel):
    if g.user_role == "Owner" and vessel["owner_user_id"] != g.user_id:
        raise ownership("Owner may act only on vessels whose owner_user_id matches X-User-ID")


def check_owner_job(job):
    if g.user_role == "Owner":
        vessel = db.vessels.get(job["vessel_id"])
        if vessel is None or vessel["owner_user_id"] != g.user_id:
            raise ownership("Owner may act only on resources of their own vessels")


def check_owner_work_order(wo):
    if g.user_role == "Owner":
        job = db.jobs.get(wo["job_id"])
        if job is None:
            raise ownership()
        check_owner_job(job)
