"""Smoke part 2 — requires a FRESH server (per-test isolation semantics)."""
import os
import sys
import requests

BASE = f"http://127.0.0.1:{os.environ.get('PORT', '10000')}"
COORD = {"X-User-ID": "coord-1", "X-User-Role": "ApCoordinator"}
REGISTRAR = {"X-User-ID": "reg-1", "X-User-Role": "Registrar"}
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
        return f"<{resp.status_code} {resp.text[:150]}>"


def student_headers(sid):
    return {"X-User-ID": sid, "X-User-Role": "Student"}


def teacher_headers(tid):
    return {"X-User-ID": tid, "X-User-Role": "Teacher"}


def cycle(name="CYCLE-2027", budget=100000000):
    r = call("POST", "/exam-cycles", COORD, json={
        "name": name, "registration_deadline_at": "2026-11-01T12:00:00Z",
        "order_deadline_at": "2026-11-15T12:00:00Z", "score_release_at": "2027-07-05T12:00:00Z",
        "exam_window_start_at": "2027-05-03T00:00:00Z", "exam_window_end_at": "2027-05-21T23:59:59Z",
        "late_fee_cents": 4000, "unused_exam_penalty_cents": 1500,
        "fee_reduction_cents": 3600, "budget_cap_cents": budget, "rebate_rate_bp": 900})
    cid = r.json()["data"]["id"]
    call("POST", f"/exam-cycles/{cid}/open", COORD)
    return cid


def course(cy, code="AP_CALC_BC", fee=9800, threshold=3, program="AP"):
    return call("POST", "/courses", COORD, json={
        "cycle_id": cy, "subject_code": code, "program": program,
        "exam_fee_cents": fee, "credit_threshold": threshold}).json()["data"]["id"]


def student(name, grade=11, sg="GEN"):
    return call("POST", "/students", COORD, json={
        "full_name": name, "grade_level": grade, "subgroup_code": sg}).json()["data"]["id"]


def teacher(name):
    return call("POST", "/teachers", COORD,
                json={"full_name": name, "email": f"{name}@x.edu"}).json()["data"]["id"]


def authorize(tid, cid):
    ta = call("POST", "/teacher-authorizations", COORD,
              json={"teacher_id": tid, "course_id": cid}).json()["data"]["id"]
    call("POST", f"/teacher-authorizations/{ta}/complete-training", teacher_headers(tid))
    return ta


def register(sid, cid):
    return call("POST", "/registrations", student_headers(sid),
                json={"student_id": sid, "course_id": cid})


def clock(ts):
    call("POST", "/_clock/set_current_utc", COORD, json={"to_iso8601": ts})


print("== equity report (exactly 8 students; must run first) ==")
cyA = cycle("CYCLE-2026")
coA = course(cyA)
cyB = cycle("CYCLE-2027B")
coB = course(cyB)
gs = [student(f"G{i}", 11, "GEN") for i in range(4)]
fs = [student(f"F{i}", 11, "FRL") for i in range(4)]
register(gs[3], coA)
for s in (gs[0], gs[1], gs[2], fs[0]):
    register(s, coB)
r = call("GET", f"/exam-cycles/{cyB}/equity-report?compare_to_cycle_id={cyA}", COORD)
d = r.json()["data"]
gen = next(s for s in d["subgroups"] if s["subgroup_code"] == "GEN")
frl = next(s for s in d["subgroups"] if s["subgroup_code"] == "FRL")
check("GEN 4/3/75.0", gen["students"] == 4 and gen["participants"] == 3
      and gen["participation_rate"] == 75.0, str(gen))
check("FRL 4/1/25.0", frl["students"] == 4 and frl["participants"] == 1
      and frl["participation_rate"] == 25.0, str(frl))
check("totals 4 / growth 3 / gap 50.0", d["total_exams"] == 4
      and d["growth_exams"] == 3 and d["access_gap_pct"] == 50.0, str(d))
check("IEP/ELL absent (no students)", all(s["subgroup_code"] in ("GEN", "FRL")
                                          for s in d["subgroups"]))

print("== rebate pinned rounding: 285 (on-time regs at default clock) ==")
cy = cycle("CYCLE-REBATE")
co = course(cy, fee=1050)
for i in range(3):
    register(student(f"R{i}"), co)
r = call("GET", f"/exam-cycles/{cy}", COORD)
check("rebate 285", r.json()["data"]["rebate_cents"] == 285, r.json()["data"]["rebate_cents"])

print("== order submit deadline boundary (A on time, B late by 1s) ==")
cy2 = cycle("CYCLE-B2")
co2 = course(cy2)
register(student("LB"), co2)
ordB = call("POST", "/exam-orders", COORD, json={"cycle_id": cy2}).json()["data"]["id"]
clock("2026-11-15T12:00:01Z")
r = call("POST", f"/exam-orders/{ordB}/submit", COORD)
check("1s past -> submitted_late true, estimate 13800",
      r.json()["data"]["submitted_late"] is True
      and r.json()["data"]["estimate_total_cents"] == 13800, r.text)
check("frozen line late_fee_total 4000",
      r.json()["data"]["lines"][0]["late_fee_total_cents"] == 4000
      and r.json()["data"]["lines"][0]["line_total_cents"] == 13800)

print("== multibranch invoice: estimate 37800 ==")
clock("2026-08-01T00:00:00Z")  # reset: sA/sC register on time
cy3 = cycle("CYCLE-MULTI")
co3 = course(cy3)
sA, sB, sC = student("MA"), student("MB"), student("MC", 12, "FRL")
register(sA, co3)
register(sC, co3)
r = call("POST", "/fee-reduction-applications", student_headers(sC), json={
    "student_id": sC, "cycle_id": cy3, "eligibility_basis": "REDUCED_LUNCH",
    "annual_income_cents": 4200000})
fra = r.json()["data"]["id"]
call("POST", f"/fee-reduction-applications/{fra}/approve", COORD)
clock("2026-11-10T00:00:00Z")
r = register(sB, co3)
rB = r.json()["data"]["id"]
check("rB late +4000", r.json()["data"]["is_late"] is True
      and r.json()["data"]["late_fee_applied_cents"] == 4000)
ord3 = call("POST", "/exam-orders", COORD, json={"cycle_id": cy3}).json()["data"]["id"]
clock("2026-11-20T00:00:00Z")
r = call("POST", f"/exam-orders/{ord3}/submit", COORD)
check("submitted_late true", r.json()["data"]["submitted_late"] is True)
check("estimate 37800", r.json()["data"]["estimate_total_cents"] == 37800, r.text)
# lock + administer + reconcile with subsidy and late + unused
tI = teacher("MI")
authorize(tI, co3)
r = call("POST", f"/exam-orders/{ord3}/lock", COORD)
check("lock ok", r.status_code == 200, r.text)
se = call("POST", "/exam-sessions", COORD, json={
    "course_id": co3, "room_name": "MULTI-GYM", "room_capacity": 5,
    "start_at": "2027-05-05T09:00:00Z", "end_at": "2027-05-05T11:00:00Z"}).json()["data"]["id"]
clock("2027-05-05T12:00:00Z")
# sA and sC sit; sB no-show
rA = call("GET", f"/registrations?student_id={sA}&course_id={co3}", COORD).json()["data"][0]["id"]
rC = call("GET", f"/registrations?student_id={sC}&course_id={co3}", COORD).json()["data"][0]["id"]
call("POST", f"/exam-sessions/{se}/administer", COORD,
     json={"present_registration_ids": [rA, rC]})
r = call("POST", f"/exam-orders/{ord3}/reconcile", COORD)
# final: 3x9800 + 3x4000 (late) + 1 unused x 1500 - 3600 subsidy = 39300
check("final 39300", r.json()["data"]["final_total_cents"] == 39300, r.text)

print("== parallel dimensions independent ==")
clock("2027-07-05T12:00:00Z")
r = call("POST", f"/exam-cycles/{cy3}/release-scores", REGISTRAR,
         json={"scores": [{"registration_id": rA, "score": 4}]})
check("release ok", r.status_code == 200, r.text)
r = call("POST", f"/registrations/{rA}/post-to-transcript", REGISTRAR)
check("rA SAT x POSTED score 4", r.json()["data"]["registration_status"] == "SAT"
      and r.json()["data"]["score_status"] == "POSTED" and r.json()["data"]["score"] == 4)
r = call("GET", f"/registrations/{rB}", COORD)
check("rB NO_SHOW x NO_SCORE untouched", r.json()["data"]["registration_status"] == "NO_SHOW"
      and r.json()["data"]["score_status"] == "NO_SCORE")

print("== capacity equality + SESSION_FULL (isolated cycle) ==")
cy4 = cycle("CYCLE-CAP")
co41 = course(cy4, "AP_CALC_BC")
co42 = course(cy4, "AP_BIOLOGY")
t41 = teacher("CAPT")
authorize(t41, co41)
authorize(t41, co42)
q1, q2, q3 = student("Q1"), student("Q2"), student("Q3", 12, "FRL")
register(q1, co41)
register(q2, co41)
register(q1, co42)
register(q3, co42)
se41 = call("POST", "/exam-sessions", COORD, json={
    "course_id": co41, "room_name": "CAP-GYM", "room_capacity": 2,
    "start_at": "2027-05-05T09:00:00Z", "end_at": "2027-05-05T11:00:00Z"}).json()["data"]["id"]
r = call("GET", f"/exam-sessions/{se41}", COORD)
check("capacity 2 == 2 REGISTERED fits; seats 2", r.json()["data"]["seats_reserved"] == 2)
r = register(q3, co41)
check("3rd reg -> ERR_SESSION_FULL", r.status_code == 422
      and err_id(r) == "ERR_SESSION_FULL", err_id(r))
r = call("POST", "/exam-sessions", COORD, json={
    "course_id": co42, "room_name": "CAP-LAB", "room_capacity": 1,
    "start_at": "2027-05-06T09:00:00Z", "end_at": "2027-05-06T11:00:00Z"})
check("capacity 1 < 2 -> ERR_ROOM_CAPACITY_INSUFFICIENT", r.status_code == 422
      and err_id(r) == "ERR_ROOM_CAPACITY_INSUFFICIENT")

print("== proctor 29-minute gap rejected ==")
cy5 = cycle("CYCLE-PROC")
co51 = course(cy5, "AP_CALC_BC")
co52 = course(cy5, "AP_BIOLOGY")
co53 = course(cy5, "AP_CHEM")
ta_auth = teacher("PAUTH")
p = teacher("PPROC")
for c in (co51, co52, co53):
    authorize(ta_auth, c)
s51 = call("POST", "/exam-sessions", COORD, json={
    "course_id": co51, "room_name": "P1", "room_capacity": 5,
    "start_at": "2027-05-05T09:00:00Z", "end_at": "2027-05-05T10:00:00Z"}).json()["data"]["id"]
s52 = call("POST", "/exam-sessions", COORD, json={
    "course_id": co52, "room_name": "P2", "room_capacity": 5,
    "start_at": "2027-05-05T10:30:00Z", "end_at": "2027-05-05T12:00:00Z"}).json()["data"]["id"]
s53 = call("POST", "/exam-sessions", COORD, json={
    "course_id": co53, "room_name": "P3", "room_capacity": 5,
    "start_at": "2027-05-05T10:29:00Z", "end_at": "2027-05-05T12:00:00Z"}).json()["data"]["id"]
call("POST", "/proctor-assignments", COORD, json={"session_id": s51, "teacher_id": p})
r = call("POST", "/proctor-assignments", COORD, json={"session_id": s52, "teacher_id": p})
check("30-min gap allowed", r.status_code == 201, r.text)
r = call("POST", "/proctor-assignments", COORD, json={"session_id": s53, "teacher_id": p})
check("29-min gap -> 409 PROCTOR_OVERLAP", r.status_code == 409
      and err_id(r) == "ERR_PROCTOR_OVERLAP")

print("== safety beats temporal (subject conflict masks overlap) ==")
# ta_auth is AUTHORIZED for co51..53 and holds no proctor rows yet; assign ta_auth to s51:
r = call("POST", "/proctor-assignments", COORD, json={"session_id": s51, "teacher_id": ta_auth})
check("conflict on own course -> 422 SUBJECT_CONFLICT", r.status_code == 422
      and err_id(r) == "ERR_PROCTOR_SUBJECT_CONFLICT")
# p holds s51 + s52; ta_auth assign to s52 would both conflict (co52) and overlap -> 422
r = call("POST", "/proctor-assignments", COORD, json={"session_id": s52, "teacher_id": ta_auth})
check("conflict beats overlap -> 422", r.status_code == 422
      and err_id(r) == "ERR_PROCTOR_SUBJECT_CONFLICT")

print("== register/cancel conservation ==")
clock("2026-08-01T00:00:00Z")  # reset: on-time registrations pin 9800/882
cy6 = cycle("CYCLE-CONS")
co6 = course(cy6)
t6 = teacher("CT")
authorize(t6, co6)
u1 = student("U1")
register(u1, co6)
se6 = call("POST", "/exam-sessions", COORD, json={
    "course_id": co6, "room_name": "CONS-GYM", "room_capacity": 5,
    "start_at": "2027-05-05T09:00:00Z", "end_at": "2027-05-05T11:00:00Z"}).json()["data"]["id"]
ord6 = call("POST", "/exam-orders", COORD, json={"cycle_id": cy6}).json()["data"]["id"]
r = call("GET", f"/students/{u1}/statement", COORD)
bal0 = r.json()["data"]["balance_cents"]
r = call("GET", f"/exam-cycles/{cy6}", COORD)
reb0 = r.json()["data"]["rebate_cents"]
u2 = student("U2")
r = register(u2, co6)
ur2 = r.json()["data"]["id"]
call("POST", f"/registrations/{ur2}/cancel", student_headers(u2))
r = call("GET", f"/students/{u1}/statement", COORD)
check("u1 balance unchanged 9800", r.json()["data"]["balance_cents"] == 9800 == bal0)
r = call("GET", f"/exam-cycles/{cy6}", COORD)
check("rebate back to 882", r.json()["data"]["rebate_cents"] == 882 == reb0, r.text)
r = call("GET", f"/exam-sessions/{se6}", COORD)
check("seats back to 1, still SCHEDULED", r.json()["data"]["seats_reserved"] == 1
      and r.json()["data"]["status"] == "SCHEDULED")
r = call("GET", f"/exam-orders/{ord6}", COORD)
check("estimate back to 9800", r.json()["data"]["estimate_total_cents"] == 9800)
r = call("GET", f"/registrations/{ur2}", COORD)
check("cancelled reg CANCELLED x VOID", r.json()["data"]["registration_status"] == "CANCELLED"
      and r.json()["data"]["score_status"] == "VOID")
r = call("POST", f"/registrations/{ur2}/cancel", COORD)
check("double cancel -> 409", r.status_code == 409)

print("== student balance variants diverge ==")
clock("2026-08-01T00:00:00Z")
cy7 = cycle("CYCLE-BAL")
co7 = course(cy7)
w1 = student("W1")
register(w1, co7)
call("POST", "/fee-reduction-applications", student_headers(w1), json={
    "student_id": w1, "cycle_id": cy7, "eligibility_basis": "INCOME",
    "annual_income_cents": 100})
r = call("GET", f"/students/{w1}/statement", COORD)
check("provisional 9800 vs projected 6200", r.json()["data"]["balance_cents"] == 9800
      and r.json()["data"]["projected_balance_cents"] == 6200)

print()
if FAILS:
    print(f"{len(FAILS)} FAILURES: {FAILS}")
    sys.exit(1)
print("ALL SMOKE-2 CHECKS PASSED")
