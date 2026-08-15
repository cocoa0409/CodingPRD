"""Smoke test driving the pinned literals from SCAFFOLD_DIFFICULTY_DESIGN.yaml and
SCAFFOLD_CORNER_DESIGN.yaml against a running server. Not part of the build
contract; used only to self-verify. Requires: server on $PORT (default 10000).
"""
import os
import sys
import uuid

import requests

BASE = f"http://127.0.0.1:{os.environ.get('PORT', '10000')}"

COORD = {"X-User-ID": "coord-1", "X-User-Role": "ApCoordinator"}
REGISTRAR = {"X-User-ID": "reg-1", "X-User-Role": "Registrar"}


def as_student(sid):
    return {"X-User-ID": sid, "X-User-Role": "Student"}


def as_teacher(tid):
    return {"X-User-ID": tid, "X-User-Role": "Teacher"}


FAILS = []


def check(name, cond, extra=""):
    if cond:
        print(f"  ok: {name}")
    else:
        print(f"FAIL: {name} {extra}")
        FAILS.append(name)


def call(method, path, headers, json=None, params=None):
    return requests.request(method, BASE + path, headers=headers, json=json,
                            params=params, timeout=10)


def err_id(resp):
    try:
        return resp.json()["data"]["error_id"]
    except Exception:
        return f"<no error_id: {resp.status_code} {resp.text[:200]}>"


def make_open_cycle(name="CYCLE-2027", budget=100000000, fee_late=4000,
                    unused=1500, reduction=3600, rebate_bp=900):
    r = call("POST", "/exam-cycles", COORD, json={
        "name": name,
        "registration_deadline_at": "2026-11-01T12:00:00Z",
        "order_deadline_at": "2026-11-15T12:00:00Z",
        "score_release_at": "2027-07-05T12:00:00Z",
        "exam_window_start_at": "2027-05-03T00:00:00Z",
        "exam_window_end_at": "2027-05-21T23:59:59Z",
        "late_fee_cents": fee_late, "unused_exam_penalty_cents": unused,
        "fee_reduction_cents": reduction, "budget_cap_cents": budget,
        "rebate_rate_bp": rebate_bp})
    assert r.status_code == 201, r.text
    cid = r.json()["data"]["id"]
    r2 = call("POST", f"/exam-cycles/{cid}/open", COORD)
    assert r2.status_code == 200, r2.text
    return cid


def make_course(cy, code="AP_CALC_BC", fee=9800, threshold=3, program="AP"):
    r = call("POST", "/courses", COORD, json={
        "cycle_id": cy, "subject_code": code, "program": program,
        "exam_fee_cents": fee, "credit_threshold": threshold})
    assert r.status_code == 201, r.text
    return r.json()["data"]["id"]


def make_student(name="Stu", grade=11, sg="GEN"):
    r = call("POST", "/students", COORD, json={
        "full_name": name, "grade_level": grade, "subgroup_code": sg})
    assert r.status_code == 201, r.text
    return r.json()["data"]["id"]


def make_teacher(name="T", email="t@x.edu"):
    r = call("POST", "/teachers", COORD, json={"full_name": name, "email": email})
    assert r.status_code == 201, r.text
    return r.json()["data"]["id"]


def authorize(tid, cid):
    r = call("POST", "/teacher-authorizations", COORD,
             json={"teacher_id": tid, "course_id": cid})
    assert r.status_code == 201, r.text
    ta = r.json()["data"]["id"]
    r2 = call("POST", f"/teacher-authorizations/{ta}/complete-training", as_teacher(tid))
    assert r2.status_code == 200, r2.text
    return ta


def register(sid, cid):
    r = call("POST", "/registrations", as_student(sid),
             json={"student_id": sid, "course_id": cid})
    assert r.status_code == 201, r.text
    return r.json()["data"]["id"]


def set_clock(ts):
    r = call("POST", "/_clock/set_current_utc", COORD, json={"to_iso8601": ts})
    assert r.status_code == 200, r.text
    return r


# ---------------------------------------------------------------------------
print("== auth & envelope ==")
r = call("GET", f"/courses/{uuid.uuid4()}", {})
check("401 without headers", r.status_code == 401 and err_id(r) == "ERR_UNAUTHENTICATED")
r = call("GET", f"/courses/{uuid.uuid4()}", {"X-User-ID": "x", "X-User-Role": "Wizard"})
check("401 unrecognized role", r.status_code == 401 and err_id(r) == "ERR_UNAUTHENTICATED")
r = call("GET", f"/courses/{uuid.uuid4()}", COORD)
check("404 unknown id", r.status_code == 404 and err_id(r) == "ERR_NOT_FOUND"
      and r.json()["response_type"] == "error")
r = call("POST", "/courses", as_student("s1"), json={})
check("403 role not allowed", r.status_code == 403 and err_id(r) == "ERR_FORBIDDEN")

print("== cycle / course creation ==")
r = call("POST", "/exam-cycles", COORD, json={
    "name": "CYCLE-2027", "registration_deadline_at": "2026-11-01T12:00:00Z",
    "order_deadline_at": "2026-11-15T12:00:00Z", "score_release_at": "2027-07-05T12:00:00Z",
    "exam_window_start_at": "2027-05-03T00:00:00Z", "exam_window_end_at": "2027-05-21T23:59:59Z",
    "late_fee_cents": 4000, "unused_exam_penalty_cents": 1500,
    "fee_reduction_cents": 3600, "budget_cap_cents": 100000000, "rebate_rate_bp": 900})
check("cycle 201", r.status_code == 201, r.text)
cy = r.json()["data"]["id"]
d = r.json()["data"]
check("cycle SETUP v1 counts 0", d["status"] == "SETUP" and d["version"] == 1
      and d["registered_exam_count"] == 0 and d["rebate_cents"] == 0)
check("created_at == updated_at", d["created_at"] == d["updated_at"])
check("envelope object", r.json()["response_type"] == "object"
      and r.json()["meta"]["api_request_id"].startswith("req_"))

r = call("POST", "/registrations", as_student("nobody"), json={"student_id": "nobody", "course_id": "x"})
# student doesn't resolve -> but SETUP state gate: student FK first (422)
check("reg bad student 422", r.status_code == 422 and err_id(r) == "ERR_REFERENCE_NOT_FOUND")

r = call("POST", "/courses", COORD, json={
    "cycle_id": cy, "subject_code": "AP_CALC_BC", "program": "APX",
    "exam_fee_cents": 9800, "credit_threshold": 3})
check("bad program 400", r.status_code == 400 and err_id(r) == "ERR_INVALID_REQUEST")
r = call("POST", "/courses", COORD, json={
    "cycle_id": cy, "subject_code": "AP_CALC_BC", "program": "AP",
    "exam_fee_cents": 9800, "credit_threshold": 6})
check("AP threshold 6 -> 400", r.status_code == 400)
r = call("POST", "/courses", COORD, json={
    "cycle_id": cy, "subject_code": "AP_CALC_BC", "program": "AP",
    "exam_fee_cents": 9800, "credit_threshold": 3, "status": "ACTIVE"})
check("extra field status -> 400", r.status_code == 400 and err_id(r) == "ERR_INVALID_REQUEST")

co = make_course(cy)
r = call("GET", f"/courses/{co}", COORD)
check("course SUSPENDED count 0", r.json()["data"]["status"] == "SUSPENDED"
      and r.json()["data"]["authorized_teacher_count"] == 0)

s1 = make_student("Stu A", 11, "GEN")
r = call("POST", "/registrations", as_student(s1), json={"student_id": s1, "course_id": co})
check("registration while SETUP -> 409 INVALID_STATE",
      r.status_code == 409 and err_id(r) == "ERR_INVALID_STATE")
r = call("POST", f"/exam-cycles/{cy}/open", COORD)
check("open 200", r.status_code == 200 and r.json()["data"]["status"] == "OPEN"
      and r.json()["data"]["version"] == 2)
r = call("POST", f"/exam-cycles/{cy}/open", COORD)
check("re-open -> 409", r.status_code == 409 and err_id(r) == "ERR_INVALID_STATE")

r = call("POST", "/registrations", as_student(s1), json={"student_id": s1})
check("missing course_id 400", r.status_code == 400 and err_id(r) == "ERR_INVALID_REQUEST")
s2 = make_student("Stu B", 11, "GEN")
r = call("POST", "/registrations", as_student(s1), json={"student_id": s2, "course_id": co})
check("register for another -> 403", r.status_code == 403 and err_id(r) == "ERR_FORBIDDEN")
r = call("POST", "/registrations", as_student(s1), json={"student_id": s1, "course_id": str(uuid.uuid4())})
check("unknown course -> 422", r.status_code == 422 and err_id(r) == "ERR_REFERENCE_NOT_FOUND")

print("== teacher authorization loop ==")
t1 = make_teacher("T One", "t1@x.edu")
t2 = make_teacher("T Two", "t2@x.edu")
r = call("POST", "/teacher-authorizations", COORD, json={"teacher_id": t1, "course_id": co})
ta1 = r.json()["data"]["id"]
check("TA PENDING", r.json()["data"]["status"] == "PENDING_TRAINING"
      and r.json()["data"]["training_completed_at"] is None)
r = call("POST", "/teacher-authorizations", COORD, json={"teacher_id": t1, "course_id": co})
check("dup TA -> 409", r.status_code == 409 and err_id(r) == "ERR_DUPLICATE_AUTHORIZATION")
r = call("POST", f"/teacher-authorizations/{ta1}/complete-training", as_teacher(t2))
check("other teacher attest -> 403", r.status_code == 403 and err_id(r) == "ERR_FORBIDDEN")
r = call("POST", f"/teacher-authorizations/{ta1}/complete-training", COORD)
check("coordinator attest -> 403", r.status_code == 403 and err_id(r) == "ERR_FORBIDDEN")
r = call("POST", "/_clock/set_current_utc", COORD, json={"to_iso8601": "2026-09-01T00:00:00Z"})
check("clock set echoes current_utc", r.json()["data"]["current_utc"] == "2026-09-01T00:00:00Z")
r = call("POST", f"/teacher-authorizations/{ta1}/complete-training", as_teacher(t1))
check("attest -> AUTHORIZED", r.json()["data"]["status"] == "AUTHORIZED")
check("authorized_until = +730d", r.json()["data"]["authorized_until"] == "2028-08-31T00:00:00Z",
      r.json()["data"]["authorized_until"])
r = call("GET", f"/courses/{co}", COORD)
check("course ACTIVE count 1", r.json()["data"]["status"] == "ACTIVE"
      and r.json()["data"]["authorized_teacher_count"] == 1)
r = call("POST", f"/teacher-authorizations/{ta1}/complete-training", as_teacher(t1))
check("attest while AUTHORIZED -> 409", r.status_code == 409)

# expiry boundary
r = call("POST", "/_clock/set_current_utc", COORD, json={"to_iso8601": "2028-08-30T00:00:00Z"})
r = call("GET", f"/teacher-authorizations/{ta1}", COORD)
check("day before boundary still AUTHORIZED", r.json()["data"]["status"] == "AUTHORIZED")
r = call("POST", "/_clock/set_current_utc", COORD, json={"to_iso8601": "2028-08-31T00:00:00Z"})
r = call("GET", f"/teacher-authorizations/{ta1}", COORD)
check("AT boundary -> EXPIRED", r.json()["data"]["status"] == "EXPIRED")
r = call("GET", f"/courses/{co}", COORD)
check("course SUSPENDED after expiry", r.json()["data"]["status"] == "SUSPENDED")
r = call("POST", f"/teacher-authorizations/{ta1}/complete-training", as_teacher(t1))
check("retrain -> AUTHORIZED", r.json()["data"]["status"] == "AUTHORIZED"
      and r.json()["data"]["authorized_until"] == "2030-08-31T00:00:00Z")
r = call("GET", f"/courses/{co}", COORD)
check("course ACTIVE again", r.json()["data"]["status"] == "ACTIVE")
call("POST", "/_clock/set_current_utc", COORD, json={"to_iso8601": "2026-08-01T00:00:00Z"})

print("== registrations, balances, FRA lifecycle ==")
r1 = register(s1, co)
r = call("GET", f"/registrations/{r1}", COORD)
d = r.json()["data"]
check("fresh reg REGISTERED x PENDING v1", d["registration_status"] == "REGISTERED"
      and d["score_status"] == "PENDING" and d["version"] == 1)
check("fee snapshot 9800 not late", d["fee_cents"] == 9800 and d["is_late"] is False
      and d["late_fee_applied_cents"] == 0 and d["subsidy_cents"] == 0
      and d["net_fee_cents"] == 9800 and d["accommodation_type"] == "NONE")
r = call("POST", "/registrations", as_student(s1), json={"student_id": s1, "course_id": co})
check("duplicate registration -> 409", r.status_code == 409
      and err_id(r) == "ERR_DUPLICATE_REGISTRATION")

# FRA lifecycle: submit -> deny -> resubmit -> approve (balance 9800 -> 6200)
r = call("POST", "/fee-reduction-applications", as_student(s1), json={
    "student_id": s1, "cycle_id": cy, "eligibility_basis": "REDUCED_LUNCH",
    "annual_income_cents": 4200000})
fra = r.json()["data"]["id"]
check("FRA SUBMITTED", r.status_code == 201 and r.json()["data"]["status"] == "SUBMITTED")
r = call("POST", "/fee-reduction-applications", as_student(s1), json={
    "student_id": s1, "cycle_id": cy, "eligibility_basis": "OTHER", "annual_income_cents": 0})
check("duplicate application -> 409", r.status_code == 409
      and err_id(r) == "ERR_DUPLICATE_APPLICATION")
r = call("GET", f"/students/{s1}/statement", as_student(s1))
check("provisional 9800 / projected 6200 while SUBMITTED",
      r.json()["data"]["balance_cents"] == 9800
      and r.json()["data"]["projected_balance_cents"] == 6200, r.text)
r = call("GET", f"/students/{s1}/statement", as_student(s2))
check("other's statement -> 403", r.status_code == 403)
r = call("POST", f"/fee-reduction-applications/{fra}/approve", as_teacher(t1))
check("teacher approve -> 403", r.status_code == 403)
r = call("POST", f"/fee-reduction-applications/{fra}/deny", COORD)
check("deny -> DENIED", r.json()["data"]["status"] == "DENIED")
r = call("GET", f"/students/{s1}/statement", COORD)
check("denied: balance 9800 projected 9800", r.json()["data"]["balance_cents"] == 9800
      and r.json()["data"]["projected_balance_cents"] == 9800)
r = call("POST", f"/fee-reduction-applications/{fra}/resubmit", as_student(s2))
check("resubmit by other -> 403", r.status_code == 403)
r = call("POST", f"/fee-reduction-applications/{fra}/resubmit", as_student(s1))
check("resubmit -> SUBMITTED", r.json()["data"]["status"] == "SUBMITTED")
r = call("GET", f"/students/{s1}/statement", COORD)
check("projected 6200 again after resubmit", r.json()["data"]["projected_balance_cents"] == 6200)
r = call("POST", f"/fee-reduction-applications/{fra}/approve", COORD)
check("approve -> APPROVED", r.json()["data"]["status"] == "APPROVED")
r = call("GET", f"/registrations/{r1}", COORD)
check("subsidy retroactive 3600 net 6200", r.json()["data"]["subsidy_cents"] == 3600
      and r.json()["data"]["net_fee_cents"] == 6200)
r = call("GET", f"/students/{s1}/statement", REGISTRAR)
check("balance 6200 after approve", r.json()["data"]["balance_cents"] == 6200)
r = call("GET", f"/exam-cycles/{cy}", COORD)
check("rebate 1 x round(6200*.09)=558", r.json()["data"]["rebate_cents"] == 558, r.text)
check("registered_exam_count 1", r.json()["data"]["registered_exam_count"] == 1)

# student list scoping
r = call("GET", "/registrations", as_student(s2))
check("student list shows only own (0)", r.json()["data"] == []
      and r.json()["meta"]["total_count"] == 0)
r = call("GET", f"/registrations/{r1}", as_student(s2))
check("student GET other's reg -> 403", r.status_code == 403)
r = call("GET", "/registrations", as_student(s1))
check("own list 1", len(r.json()["data"]) == 1)

print("== late registration boundary ==")
call("POST", "/_clock/set_current_utc", COORD, json={"to_iso8601": "2026-11-01T12:00:00Z"})
r = call("POST", "/registrations", as_student(s2), json={"student_id": s2, "course_id": co})
check("AT deadline is on time", r.json()["data"]["is_late"] is False)
r2id = r.json()["data"]["id"]
call("POST", f"/registrations/{r2id}/cancel", as_student(s2))
call("POST", "/_clock/set_current_utc", COORD, json={"to_iso8601": "2026-11-01T12:00:01Z"})
r = call("POST", "/registrations", as_student(s2), json={"student_id": s2, "course_id": co})
check("1s past deadline is late, late fee 4000", r.json()["data"]["is_late"] is True
      and r.json()["data"]["late_fee_applied_cents"] == 4000
      and r.json()["data"]["net_fee_cents"] == 13800)
r2id = r.json()["data"]["id"]
call("POST", f"/registrations/{r2id}/cancel", COORD)
call("POST", "/_clock/set_current_utc", COORD, json={"to_iso8601": "2026-08-01T00:00:00Z"})

print("== exam order: OCC, adjustments, budget, freeze ==")
r = call("POST", "/exam-orders", COORD, json={"cycle_id": cy})
order = r.json()["data"]["id"]
check("order DRAFT v1", r.json()["data"]["status"] == "DRAFT" and r.json()["data"]["version"] == 1)
check("order live estimate 6200 (1 reg, subsidy 3600)",
      r.json()["data"]["estimate_total_cents"] == 6200, r.text)
lines = r.json()["data"]["lines"]
check("lines has the course", any(l["course_id"] == co and l["ordered_count"] == 1
                                  for l in lines), str(lines))
r = call("POST", "/exam-orders", COORD, json={"cycle_id": cy})
check("second order -> 409", r.status_code == 409 and err_id(r) == "ERR_ORDER_ALREADY_EXISTS")
r = call("PATCH", f"/exam-orders/{order}", COORD,
         json={"expected_exam_order_version": 5, "adjustments": []})
check("stale version -> 412", r.status_code == 412 and err_id(r) == "ERR_STALE_VERSION")
r = call("PATCH", f"/exam-orders/{order}", COORD,
         json={"adjustments": [{"course_id": co, "delta": 2}]})
check("missing expected version -> 400", r.status_code == 400)
r = call("PATCH", f"/exam-orders/{order}", COORD,
         json={"expected_exam_order_version": 1, "adjustments": [{"course_id": co, "delta": -2}]})
check("negative quantity -> 422", r.status_code == 422 and err_id(r) == "ERR_NEGATIVE_QUANTITY")
r = call("PATCH", f"/exam-orders/{order}", COORD,
         json={"expected_exam_order_version": 1, "adjustments": [{"course_id": co, "delta": 2}]})
check("PATCH ok -> v2 ordered 3", r.status_code == 200 and r.json()["data"]["version"] == 2
      and any(l["course_id"] == co and l["ordered_count"] == 3 for l in r.json()["data"]["lines"]))
check("estimate 3*9800-3600 = 25800", r.json()["data"]["estimate_total_cents"] == 25800, r.text)
r = call("PATCH", f"/exam-orders/{order}", COORD,
         json={"expected_exam_order_version": 1, "adjustments": [{"course_id": co, "delta": 2}]})
check("replay stale -> 412", r.status_code == 412)

# budget gate: new cycle with tiny cap
cy2 = make_open_cycle("CYCLE-BUDGET", budget=20000)
co2 = make_course(cy2)
sx = make_student("B Kid", 10, "GEN")
register(sx, co2)
register(make_student("B Kid2", 10, "GEN"), co2)
register(make_student("B Kid3", 12, "FRL"), co2)
r = call("POST", "/exam-orders", COORD, json={"cycle_id": cy2})
ord2 = r.json()["data"]["id"]
check("estimate 29400 pre-submit", r.json()["data"]["estimate_total_cents"] == 29400)
r = call("POST", f"/exam-orders/{ord2}/submit", COORD)
check("over budget -> 422 BUDGET_EXCEEDED", r.status_code == 422
      and err_id(r) == "ERR_BUDGET_EXCEEDED")
r = call("GET", f"/exam-orders/{ord2}", COORD)
check("order stays DRAFT", r.json()["data"]["status"] == "DRAFT")

# submit / lock / reconcile flow on the budget cycle (raise cap via new cycle)
cy3 = make_open_cycle("CYCLE-FLOW")
co3 = make_course(cy3)
t3 = make_teacher("T Three", "t3@x.edu")
call("POST", "/teacher-authorizations", COORD, json={"teacher_id": t3, "course_id": co3})
f1, f2, f3 = make_student("F1"), make_student("F2"), make_student("F3")
fr1 = register(f1, co3)
fr2 = register(f2, co3)
fr3 = register(f3, co3)
r = call("POST", "/exam-orders", COORD, json={"cycle_id": cy3})
ord3 = r.json()["data"]["id"]
r = call("POST", f"/exam-orders/{ord3}/submit", COORD)
check("submit freezes 29400", r.json()["data"]["estimate_total_cents"] == 29400
      and r.json()["data"]["submitted_late"] is False
      and r.json()["data"]["status"] == "SUBMITTED")
check("frozen lines ordered 3", any(l["ordered_count"] == 3 for l in r.json()["data"]["lines"]))
# late registration after submit does not move the estimate
f4 = make_student("F4")
fr4 = register(f4, co3)
r = call("GET", f"/exam-orders/{ord3}", COORD)
check("estimate frozen at 29400", r.json()["data"]["estimate_total_cents"] == 29400)
r = call("GET", f"/courses/{co3}", COORD)
check("live registered_count 4", r.json()["data"]["registered_count"] == 4)
# PATCH on SUBMITTED with current version -> 409 (state beats constraint)
v = r2 = call("GET", f"/exam-orders/{ord3}", COORD).json()["data"]["version"]
r = call("PATCH", f"/exam-orders/{ord3}", COORD,
         json={"expected_exam_order_version": v, "adjustments": [{"course_id": co3, "delta": -5}]})
check("PATCH SUBMITTED -> 409 INVALID_STATE", r.status_code == 409
      and err_id(r) == "ERR_INVALID_STATE")
# lock gate: teacher still PENDING_TRAINING
r = call("POST", f"/exam-orders/{ord3}/lock", COORD)
check("lock w/o authorized teacher -> 422", r.status_code == 422
      and err_id(r) == "ERR_TEACHER_NOT_AUTHORIZED")
ta3 = db_ta = call("POST", "/teacher-authorizations", COORD,
                   json={"teacher_id": t3, "course_id": co3})
# ta row already exists (created above), so this was a duplicate; complete training on the original
ta_list = call("GET", f"/teacher-authorizations?teacher_id={t3}&course_id={co3}", COORD).json()["data"]
ta3_id = ta_list[0]["id"]
call("POST", f"/teacher-authorizations/{ta3_id}/complete-training", as_teacher(t3))
r = call("POST", f"/exam-orders/{ord3}/lock", COORD)
check("lock ok after training", r.status_code == 200 and r.json()["data"]["status"] == "LOCKED"
      and r.json()["data"]["locked_at"] is not None)
# reconcile blocked: fr4 still REGISTERED
r = call("POST", f"/exam-orders/{ord3}/reconcile", COORD)
check("reconcile with unresolved -> 409", r.status_code == 409
      and err_id(r) == "ERR_INVALID_STATE")
call("POST", f"/registrations/{fr4}/cancel", COORD)
r = call("POST", f"/exam-orders/{ord3}/reconcile", COORD)
check("reconcile with REGISTERED f1..f3 -> 409", r.status_code == 409)

print("== sessions, proctors, administer ==")
# sessions for co3
r = call("POST", "/exam-sessions", COORD, json={
    "course_id": co3, "room_name": "GYM", "room_capacity": 3,
    "start_at": "2027-05-05T09:00:00Z", "end_at": "2027-05-05T11:00:00Z"})
check("session create capacity 3 == 3 REGISTERED ok", r.status_code == 201, r.text)
se3 = r.json()["data"]["id"]
check("seats_reserved 3", r.json()["data"]["seats_reserved"] == 3)
r = call("POST", "/exam-sessions", COORD, json={
    "course_id": co3, "room_name": "LAB", "room_capacity": 5,
    "start_at": "2027-05-06T09:00:00Z", "end_at": "2027-05-06T11:00:00Z"})
check("second session -> 409 DUPLICATE_SESSION", r.status_code == 409
      and err_id(r) == "ERR_DUPLICATE_SESSION")
# new registration would overflow capacity 3
f5 = make_student("F5")
r = call("POST", "/registrations", as_student(f5), json={"student_id": f5, "course_id": co3})
check("4th reg over capacity -> 422 SESSION_FULL", r.status_code == 422
      and err_id(r) == "ERR_SESSION_FULL")
# room conflict: adjacency allowed, overlap rejected
co4 = make_course(cy3, code="AP_BIOLOGY")
t4 = make_teacher("T Four", "t4@x.edu")
authorize(t4, co4)
r = call("POST", "/exam-sessions", COORD, json={
    "course_id": co4, "room_name": "GYM", "room_capacity": 5,
    "start_at": "2027-05-05T11:00:00Z", "end_at": "2027-05-05T12:00:00Z"})
check("adjacent session (11:00 == end) allowed", r.status_code == 201, r.text)
se4 = r.json()["data"]["id"]
co5 = make_course(cy3, code="AP_CHEM")
t5 = make_teacher("T Five", "t5@x.edu")
authorize(t5, co5)
r = call("POST", "/exam-sessions", COORD, json={
    "course_id": co5, "room_name": "GYM", "room_capacity": 5,
    "start_at": "2027-05-05T10:59:00Z", "end_at": "2027-05-05T12:00:00Z"})
check("1-minute overlap -> 409 ROOM_CONFLICT", r.status_code == 409
      and err_id(r) == "ERR_ROOM_CONFLICT")
r = call("POST", "/exam-sessions", COORD, json={
    "course_id": co5, "room_name": "GYM", "room_capacity": 5,
    "start_at": "2027-04-20T10:00:00Z", "end_at": "2027-04-20T12:00:00Z"})
check("outside window -> 422", r.status_code == 422 and err_id(r) == "ERR_OUTSIDE_EXAM_WINDOW")
r = call("POST", "/exam-sessions", COORD, json={
    "course_id": co5, "room_name": "X", "room_capacity": 5,
    "start_at": "2027-05-05T09:00:00Z", "end_at": "2027-05-05T09:00:00Z"})
check("end == start -> 400", r.status_code == 400 and err_id(r) == "ERR_INVALID_REQUEST")

# proctors: t3 is authorized for co3 -> subject conflict on se3; t2 holds no authorizations
r = call("POST", "/proctor-assignments", COORD, json={"session_id": se3, "teacher_id": t3})
check("subject conflict -> 422", r.status_code == 422
      and err_id(r) == "ERR_PROCTOR_SUBJECT_CONFLICT")
r = call("POST", "/proctor-assignments", COORD, json={"session_id": se3, "teacher_id": t2})
pa1 = r.json()["data"]["id"]
check("proctor assign ok", r.status_code == 201, r.text)
# t2 on se4 (11:00-12:00) vs se3 (09:00-11:00): gap 0 < 30 -> overlap
r = call("POST", "/proctor-assignments", COORD, json={"session_id": se4, "teacher_id": t2})
check("0-min gap -> 409 PROCTOR_OVERLAP", r.status_code == 409
      and err_id(r) == "ERR_PROCTOR_OVERLAP", err_id(r))
r = call("POST", "/proctor-assignments", COORD, json={"session_id": se3, "teacher_id": t2})
check("duplicate proctor -> 409", r.status_code == 409 and err_id(r) == "ERR_DUPLICATE_PROCTOR")
# 30-minute gap allowed: co5 session 11:30-12:30 in another room
r = call("POST", "/exam-sessions", COORD, json={
    "course_id": co5, "room_name": "OTHER", "room_capacity": 5,
    "start_at": "2027-05-05T11:30:00Z", "end_at": "2027-05-05T12:30:00Z"})
se5 = r.json()["data"]["id"]
r = call("POST", "/proctor-assignments", COORD, json={"session_id": se5, "teacher_id": t2})
check("30-min gap allowed", r.status_code == 201, r.text)
pa5 = r.json()["data"]["id"]
# 29-minute gap rejected for t4 (authorized in co4, so not for se4): use se4 11:00 with t4? t4 conflict.
# release -> allowed again
r = call("POST", f"/proctor-assignments/{pa1}/release", COORD)
check("release ok", r.json()["data"]["status"] == "RELEASED")
r = call("POST", f"/proctor-assignments/{pa1}/release", COORD)
check("re-release -> 409", r.status_code == 409)
r = call("POST", "/proctor-assignments", COORD, json={"session_id": se4, "teacher_id": t2})
check("assign after release ok (t2's se3 hold released; se5 gap 30+ ok? se5 11:30 vs se4 11:00-12:00 overlap!)", r.status_code, r.text)
# Actually se4 11:00-12:00 overlaps se5 11:30-12:30 which t2 still holds -> 409 expected
check("assign se4 blocked by se5 overlap", r.status_code == 409
      and err_id(r) == "ERR_PROCTOR_OVERLAP")
# release se5 assignment, then se4 works
call("POST", f"/proctor-assignments/{pa5}/release", COORD)
r = call("POST", "/proctor-assignments", COORD, json={"session_id": se4, "teacher_id": t2})
check("assign after releases ok", r.status_code == 201, r.text)
pa2 = r.json()["data"]["id"]

# administer: too early
r = call("POST", f"/exam-sessions/{se3}/administer", COORD,
         json={"present_registration_ids": [fr1]})
check("administer before end -> 422", r.status_code == 422
      and err_id(r) == "ERR_SESSION_NOT_ENDED")
call("POST", "/_clock/set_current_utc", COORD, json={"to_iso8601": "2027-05-05T11:00:00Z"})
r = call("POST", f"/exam-sessions/{se3}/administer", COORD,
         json={"present_registration_ids": [fr1, str(uuid.uuid4())]})
check("administer unknown id -> 422 REF_NOT_FOUND", r.status_code == 422
      and err_id(r) == "ERR_REFERENCE_NOT_FOUND")
r = call("POST", f"/exam-sessions/{se3}/administer", COORD,
         json={"present_registration_ids": [fr1, fr2]})
check("administer ok", r.status_code == 200 and r.json()["data"]["status"] == "ADMINISTERED"
      and r.json()["data"]["seats_reserved"] == 0)
r = call("GET", f"/registrations/{fr3}", COORD)
check("absentee NO_SHOW x NO_SCORE", r.json()["data"]["registration_status"] == "NO_SHOW"
      and r.json()["data"]["score_status"] == "NO_SCORE")
r = call("POST", f"/exam-sessions/{se3}/administer", COORD, json={"present_registration_ids": []})
check("re-administer -> 409", r.status_code == 409)

# reconcile now: f1,f2 SAT; f3 NO_SHOW; f4 CANCELLED -> all resolved
r = call("POST", f"/exam-orders/{ord3}/reconcile", COORD)
check("reconcile ok", r.status_code == 200, r.text)
check("final == 29400 + 1 unused x 1500 = 30900",
      r.json()["data"]["final_total_cents"] == 30900, r.text)

print("== irregularities, score release, transcript ==")
# cy3 session se3 ADMINISTERED; fr1, fr2 SAT x PENDING
r = call("POST", "/irregularity-reports", as_teacher(t4), json={
    "session_id": se3, "category": "MISCONDUCT", "details": "nope"})
check("file w/o assignment -> 403", r.status_code == 403 and err_id(r) == "ERR_FORBIDDEN")
# give t4 an assignment on se3? se3 is ADMINISTERED (not assignable). Use t-proctor on se4.
# Instead: create a fresh course/session flow below for irregularities. Here: release-scores gates.
r = call("POST", f"/exam-cycles/{cy3}/release-scores", REGISTRAR,
         json={"scores": [{"registration_id": fr1, "score": 4}]})
check("release before score_release_at -> 422", r.status_code == 422
      and err_id(r) == "ERR_SCORES_NOT_YET_AVAILABLE")
call("POST", "/_clock/set_current_utc", COORD, json={"to_iso8601": "2027-07-05T12:00:00Z"})
r = call("POST", f"/exam-cycles/{cy3}/release-scores", REGISTRAR,
         json={"scores": [{"registration_id": fr1, "score": 4},
                          {"registration_id": fr2, "score": 6}]})
check("out-of-range score -> 400 transactional", r.status_code == 400
      and err_id(r) == "ERR_INVALID_REQUEST")
r = call("GET", f"/registrations/{fr1}", COORD)
check("nothing written", r.json()["data"]["score_status"] == "PENDING"
      and r.json()["data"]["score"] is None)
r = call("POST", f"/exam-cycles/{cy3}/release-scores", REGISTRAR,
         json={"scores": [{"registration_id": fr1, "score": 4},
                          {"registration_id": fr3, "score": 3}]})
check("NO_SCORE record -> 409 INVALID_STATE", r.status_code == 409
      and err_id(r) == "ERR_INVALID_STATE")
r = call("POST", f"/exam-cycles/{cy3}/release-scores", REGISTRAR,
         json={"scores": [{"registration_id": fr1, "score": 4},
                          {"registration_id": fr2, "score": 2}]})
check("release ok", r.status_code == 200 and r.json()["data"]["released_count"] == 2)
check("released ids", set(r.json()["data"]["released_registration_ids"]) == {fr1, fr2})
r = call("GET", f"/registrations/{fr1}", COORD)
check("fr1 RELEASED score 4", r.json()["data"]["score_status"] == "RELEASED"
      and r.json()["data"]["score"] == 4)
r = call("POST", f"/registrations/{fr2}/post-to-transcript", REGISTRAR)
check("score 2 < threshold 3 -> 422", r.status_code == 422
      and err_id(r) == "ERR_SCORE_BELOW_THRESHOLD")
r = call("POST", f"/registrations/{fr1}/post-to-transcript", REGISTRAR)
check("post ok -> POSTED", r.status_code == 200
      and r.json()["data"]["score_status"] == "POSTED")
r = call("POST", f"/registrations/{fr1}/post-to-transcript", REGISTRAR)
check("re-post -> 409", r.status_code == 409)
r = call("GET", f"/students/{f1}/statement", COORD)
check("transcript_posted_count 1", r.json()["data"]["transcript_posted_count"] == 1)

print("== irregularity lifecycle (fresh cycle) ==")
cy6 = make_open_cycle("CYCLE-IRR")
co6 = make_course(cy6)
t_instr = make_teacher("T Instr", "i@x.edu")
authorize(t_instr, co6)
t_proc = make_teacher("T Proc", "p@x.edu")
g1, g2 = make_student("G1"), make_student("G2")
gr1 = register(g1, co6)
gr2 = register(g2, co6)
r = call("POST", "/exam-sessions", COORD, json={
    "course_id": co6, "room_name": "LAB", "room_capacity": 5,
    "start_at": "2027-05-05T09:00:00Z", "end_at": "2027-05-05T11:00:00Z"})
se6 = r.json()["data"]["id"]
r = call("POST", "/proctor-assignments", COORD, json={"session_id": se6, "teacher_id": t_proc})
pa6 = r.json()["data"]["id"]
call("POST", "/_clock/set_current_utc", COORD, json={"to_iso8601": "2027-05-05T12:00:00Z"})
r = call("POST", "/irregularity-reports", as_teacher(t_proc), json={
    "session_id": se6, "category": "TIMING_ERROR", "details": "early"})
check("file on SCHEDULED -> 409", r.status_code == 409 and err_id(r) == "ERR_INVALID_STATE")
call("POST", f"/exam-sessions/{se6}/administer", COORD,
     json={"present_registration_ids": [gr1, gr2]})
r = call("POST", "/irregularity-reports", as_teacher(t_instr), json={
    "session_id": se6, "category": "TIMING_ERROR", "details": "x"})
check("non-proctor files -> 403", r.status_code == 403)
r = call("POST", "/irregularity-reports", as_teacher(t_proc), json={
    "session_id": se6, "category": "TIMING_ERROR", "details": "ended early"})
ir1 = r.json()["data"]["id"]
check("filed; proctor id from caller", r.status_code == 201
      and r.json()["data"]["proctor_teacher_id"] == t_proc)
r = call("GET", f"/exam-sessions/{se6}", COORD)
check("session UNDER_INVESTIGATION", r.json()["data"]["status"] == "UNDER_INVESTIGATION")
r = call("GET", f"/registrations/{gr1}", COORD)
check("gr1 HELD", r.json()["data"]["score_status"] == "HELD")
call("POST", "/_clock/set_current_utc", COORD, json={"to_iso8601": "2027-07-05T12:00:00Z"})
r = call("POST", f"/exam-cycles/{cy6}/release-scores", REGISTRAR,
         json={"scores": [{"registration_id": gr1, "score": 4}]})
check("release on HELD -> 409 IRREGULARITY_OPEN", r.status_code == 409
      and err_id(r) == "ERR_IRREGULARITY_OPEN")
r = call("POST", f"/irregularity-reports/{ir1}/resolve", COORD)
check("resolve ok", r.json()["data"]["status"] == "RESOLVED")
r = call("GET", f"/exam-sessions/{se6}", COORD)
check("session back to ADMINISTERED", r.json()["data"]["status"] == "ADMINISTERED")
r = call("GET", f"/registrations/{gr1}", COORD)
check("gr1 PENDING again", r.json()["data"]["score_status"] == "PENDING")
# second report then cancel-scores
r = call("POST", "/irregularity-reports", as_teacher(t_proc), json={
    "session_id": se6, "category": "SECURITY_BREACH", "details": "phone seen"})
ir2 = r.json()["data"]["id"]
r = call("POST", f"/irregularity-reports/{ir2}/cancel-scores", COORD)
check("cancel-scores ok", r.json()["data"]["status"] == "SCORES_CANCELLED")
r = call("GET", f"/exam-sessions/{se6}", COORD)
check("session INVALIDATED", r.json()["data"]["status"] == "INVALIDATED")
r = call("GET", f"/registrations/{gr1}", COORD)
check("gr1 VOID", r.json()["data"]["score_status"] == "VOID")
r = call("POST", f"/exam-cycles/{cy6}/release-scores", REGISTRAR,
         json={"scores": [{"registration_id": gr1, "score": 4}]})
check("release VOID -> 409 INVALID_STATE", r.status_code == 409
      and err_id(r) == "ERR_INVALID_STATE")

print("== clock sweep cascade depth 3 ==")
cy7 = make_open_cycle("CYCLE-CASCADE")
co7 = make_course(cy7)
tc1 = make_teacher("TC1", "c1@x.edu")
tc2 = make_teacher("TC2", "c2@x.edu")
r = call("POST", "/teacher-authorizations", COORD, json={"teacher_id": tc1, "course_id": co7})
ta7 = r.json()["data"]["id"]
call("POST", "/_clock/set_current_utc", COORD, json={"to_iso8601": "2026-09-01T00:00:00Z"})
call("POST", f"/teacher-authorizations/{ta7}/complete-training", as_teacher(tc1))
h1 = make_student("H1")
hr1 = register(h1, co7)
r = call("POST", "/exam-sessions", COORD, json={
    "course_id": co7, "room_name": "CASCADE-LAB", "room_capacity": 5,
    "start_at": "2027-05-05T09:00:00Z", "end_at": "2027-05-05T11:00:00Z"})
se7 = r.json()["data"]["id"]
r = call("POST", "/proctor-assignments", COORD, json={"session_id": se7, "teacher_id": tc2})
pa7 = r.json()["data"]["id"]
call("POST", "/_clock/set_current_utc", COORD, json={"to_iso8601": "2028-08-31T00:00:00Z"})
r = call("GET", f"/teacher-authorizations/{ta7}", COORD)
check("TA EXPIRED", r.json()["data"]["status"] == "EXPIRED")
r = call("GET", f"/courses/{co7}", COORD)
check("course SUSPENDED", r.json()["data"]["status"] == "SUSPENDED")
r = call("GET", f"/exam-sessions/{se7}", COORD)
check("session CANCELLED by cascade", r.json()["data"]["status"] == "CANCELLED"
      and r.json()["data"]["seats_reserved"] == 0)
r = call("GET", f"/proctor-assignments/{pa7}", COORD)
check("proctor RELEASED by cascade", r.json()["data"]["status"] == "RELEASED")
r = call("GET", f"/registrations/{hr1}", COORD)
check("registration untouched", r.json()["data"]["registration_status"] == "REGISTERED")

print("== rebate pinned rounding (285 vs 284) ==")
cy8 = make_open_cycle("CYCLE-REBATE")
co8 = make_course(cy8, fee=1050)
for i in range(3):
    register(make_student(f"R{i}"), co8)
r = call("GET", f"/exam-cycles/{cy8}", COORD)
check("rebate 3 x round_half_up(1050*900/10000) = 285",
      r.json()["data"]["rebate_cents"] == 285, r.text)

print("== equity report ==")
cyA = make_open_cycle("CYCLE-2026")
coA = make_course(cyA)
cyB = make_open_cycle("CYCLE-2027B")
coB = make_course(cyB)
gs = [make_student(f"G{i}", 11, "GEN") for i in range(4)]
fs = [make_student(f"F{i}", 11, "FRL") for i in range(4)]
register(gs[3], coA)
for s in (gs[0], gs[1], gs[2], fs[0]):
    register(s, coB)
r = call("GET", f"/exam-cycles/{cyB}/equity-report?compare_to_cycle_id={cyA}", COORD)
d = r.json()["data"]
gen = next((s for s in d["subgroups"] if s["subgroup_code"] == "GEN"), None)
frl = next((s for s in d["subgroups"] if s["subgroup_code"] == "FRL"), None)
check("GEN 4 students 3 participants 75.0", gen and gen["students"] == 4
      and gen["participants"] == 3 and gen["participation_rate"] == 75.0, str(d))
check("FRL 4 students 1 participant 25.0", frl and frl["students"] == 4
      and frl["participants"] == 1 and frl["participation_rate"] == 25.0)
check("total 4, growth 3, gap 50.0", d["total_exams"] == 4 and d["growth_exams"] == 3
      and d["access_gap_pct"] == 50.0)
r = call("GET", f"/exam-cycles/{cyB}/equity-report", as_student(gs[0]))
check("equity student -> 403", r.status_code == 403)
r = call("GET", f"/exam-cycles/{cyB}/equity-report", COORD)
check("growth null without compare", r.json()["data"]["growth_exams"] is None)

print("== pagination ==")
r = call("GET", "/registrations?limit=2&offset=0", COORD)
m = r.json()["meta"]
total = m["total_count"]
check("page1 limit2", len(r.json()["data"]) == 2 and m["has_more"] == (total > 2)
      and m["limit"] == 2 and m["offset"] == 0)
r = call("GET", f"/registrations?limit=2&offset=2", COORD)
m2 = r.json()["meta"]
check("page2", m2["offset"] == 2 and m2["total_count"] == total)
r = call("GET", "/registrations?limit=0", COORD)
check("limit 0 -> 400", r.status_code == 400)
r = call("GET", "/registrations?limit=101", COORD)
check("limit 101 -> 400", r.status_code == 400)

print("== late order submit ==")
cy9 = make_open_cycle("CYCLE-LATE")
co9 = make_course(cy9)
k1 = make_student("K1")
kr1 = register(k1, co9)
r = call("POST", "/exam-orders", COORD, json={"cycle_id": cy9})
ord9 = r.json()["data"]["id"]
call("POST", "/_clock/set_current_utc", COORD, json={"to_iso8601": "2026-11-15T12:00:00Z"})
r = call("POST", f"/exam-orders/{ord9}/submit", COORD)
check("AT deadline not late", r.json()["data"]["submitted_late"] is False
      and r.json()["data"]["estimate_total_cents"] == 9800, r.text)

print()
if FAILS:
    print(f"{len(FAILS)} FAILURES: {FAILS}")
    sys.exit(1)
print("ALL SMOKE CHECKS PASSED")
