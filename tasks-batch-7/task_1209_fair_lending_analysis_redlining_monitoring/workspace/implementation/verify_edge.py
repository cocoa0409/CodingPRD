"""Edge-case verification: tiers/cascades, cycle effects, supersede, funds."""
import json
import os
import urllib.request

BASE = "http://127.0.0.1:%s" % os.environ["SMOKE_PORT"]
FAILS = []


def call(method, path, role=None, uid=None, body=None, qs=None):
    url = BASE + path
    if qs:
        url += "?" + "&".join("%s=%s" % kv for kv in qs.items())
    data = None
    headers = {"Content-Type": "application/json"}
    if role:
        headers["X-User-Role"] = role
    if uid:
        headers["X-User-ID"] = uid
    if body is not None:
        data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def check(name, cond, detail=""):
    if not cond:
        FAILS.append(name)
        print("FAIL", name, detail)
    else:
        print("ok  ", name)


def mk_app(mid, bid, oid, grp, out, cs, rate, dec, prod="CONVENTIONAL"):
    s, a = call("POST", "/fair-lending/applications", "LendingDataOps", "do1",
                {"market_id": mid, "branch_id": bid, "loan_officer_id": oid,
                 "product_type": prod, "applicant_group": grp, "outcome": out,
                 "note_rate_bps": rate, "loan_amount_cents": 100000, "credit_score": cs,
                 "dti_pct": 30.0, "application_date": "2026-01-01", "decision_date": dec})
    assert s == 201, a
    return a["data"]["id"]


s, m = call("POST", "/fair-lending/markets", "BankAdmin", "ba1",
            {"name": "Edge", "msa_code": "E1", "protected_group_population_share": 0.5,
             "peer_group_code": "PG"})
mid = m["data"]["id"]
s, b = call("POST", "/fair-lending/branches", "BankAdmin", "ba1",
            {"market_id": mid, "name": "B", "tract_minority_pct": 20, "opened_on": "2020-01-01"})
bid = b["data"]["id"]
s, o = call("POST", "/fair-lending/loan-officers", "BankAdmin", "ba1",
            {"branch_id": bid, "full_name": "Risky"})
oid = o["data"]["id"]

# Drive officer to RED: exception_approval_rate contributes 35*min(1, r/0.10).
# With A = max(1, validated count): use 1 validated app; approve 1 exception ->
# rate 1.0 -> 35 pts. overrides: 1 confirmed -> 40 pts. dispersion 0.
# score = 75 -> RED.
a1 = mk_app(mid, bid, oid, "CONTROL", "ORIGINATED", 700, 400, "2026-01-15")
call("POST", "/fair-lending/applications/%s/validate" % a1, "LendingDataOps", "do1")
s, e1 = call("POST", "/fair-lending/pricing-exceptions", "LoanOfficer", oid,
             {"application_id": a1, "kind": "RATE_ABOVE_CAP", "requested_rate_bps": 450,
              "justification": "j"})
e1id = e1["data"]["id"]
# second pending exception on another validated app (to observe escalation)
a2 = mk_app(mid, bid, oid, "CONTROL", "ORIGINATED", 710, 420, "2026-01-16")
call("POST", "/fair-lending/applications/%s/validate" % a2, "LendingDataOps", "do1")
s, e2 = call("POST", "/fair-lending/pricing-exceptions", "LoanOfficer", oid,
             {"application_id": a2, "kind": "FEE_WAIVER", "requested_rate_bps": 420,
              "justification": "j"})
e2id = e2["data"]["id"]
s, ov = call("POST", "/fair-lending/underwriting-overrides", "LoanOfficer", oid,
             {"application_id": a1, "original_decision": "DENY", "overridden_decision": "APPROVE",
              "justification": "j"})
ovid = ov["data"]["id"]

# approve e1 (A=2, exc rate 0.5 -> 35pts) then confirm override (ovr 0.5 -> 40pts) -> 75 RED
s, ap = call("POST", "/fair-lending/pricing-exceptions/%s/approve" % e1id, "FairLendingOfficer", "of1")
check("approve e1", s == 200, ap)
s, o1 = call("GET", "/fair-lending/loan-officers/%s" % oid, "BankAdmin", "ba1")
check("tier WATCH after exc (42.14)", o1["data"]["monitoring_tier"] == "WATCH", o1["data"])
check("score 42.14 (35 exc + 7.14 dispersion)", o1["data"]["risk_score"] == 42.14, o1["data"])
s, co = call("POST", "/fair-lending/underwriting-overrides/%s/confirm" % ovid, "FairLendingOfficer", "of1")
check("confirm override", s == 200, co)
s, o1 = call("GET", "/fair-lending/loan-officers/%s" % oid, "BankAdmin", "ba1")
check("tier RED at 82.14", o1["data"]["monitoring_tier"] == "RED" and o1["data"]["risk_score"] == 82.14,
      o1["data"])
# e2 should have escalated REQUESTED -> ESCALATED
s, e2g = call("GET", "/fair-lending/pricing-exceptions/%s" % e2id, "FairLendingOfficer", "of1")
check("e2 ESCALATED on RED crossing", e2g["data"]["status"] == "ESCALATED", e2g["data"])

# ESCALATED approve requires director
s, bad = call("POST", "/fair-lending/pricing-exceptions/%s/approve" % e2id, "FairLendingOfficer", "of1")
check("escalated needs director", s == 403 and bad["data"]["error_id"] == "ERR_DIRECTOR_APPROVAL_REQUIRED", bad)
s, ok = call("POST", "/fair-lending/pricing-exceptions/%s/approve" % e2id, "ComplianceDirector", "cd1")
check("director approves escalated", s == 200 and ok["data"]["status"] == "APPROVED", ok)

# rescind e2 drops count, risk recomputes down; e1 already APPROVED.
s, rs = call("POST", "/fair-lending/pricing-exceptions/%s/rescind" % e2id, "FairLendingOfficer", "of1")
check("rescind 200", s == 200 and rs["data"]["status"] == "RESCINDED", rs)
s, o1 = call("GET", "/fair-lending/loan-officers/%s" % oid, "BankAdmin", "ba1")
check("rescind decrements", o1["data"]["approved_exception_count"] == 1, o1["data"])

# --- expiry: e1 was created at logical 2026-05-01; advance 31 days, cycle ---
s, e3 = call("POST", "/fair-lending/pricing-exceptions", "LoanOfficer", oid,
             {"application_id": a1, "kind": "RATE_BELOW_FLOOR", "requested_rate_bps": 380,
              "justification": "j"})
check("new exception 201", s == 201, e3)
e3id = e3["data"]["id"]
# exactly 30 days: no expiry
call("POST", "/_clock/set_current_utc", "BankAdmin", "ba1", {"to_iso8601": "2026-05-31T00:00:00Z"})
s, cyc = call("POST", "/fair-lending/monitoring/run-cycle", "ComplianceDirector", "cd1")
check("30 days no expiry", e3id not in cyc["data"]["expired_exception_ids"], cyc["data"])
# 31 days: expires
call("POST", "/_clock/set_current_utc", "BankAdmin", "ba1", {"to_iso8601": "2026-06-01T00:00:00Z"})
s, cyc = call("POST", "/fair-lending/monitoring/run-cycle", "ComplianceDirector", "cd1")
check("31 days expiry", e3id in cyc["data"]["expired_exception_ids"], cyc["data"])
s, a1g = call("GET", "/fair-lending/applications/%s" % a1, "BankAdmin", "ba1")
check("has_exception NONE after expiry", a1g["data"]["has_exception"] == "NONE", a1g["data"])

# --- CAP overdue + extend + privilege forfeiture ---
# Build: run with adverse ratio -> auto finding -> substantiate (kind PRICING
# avoids matched-pair requirement via manual finding instead) — simpler: manual
# finding on a COMPUTED run.
s, run = call("POST", "/fair-lending/analysis-runs", "FairLendingAnalyst", "an1",
              {"market_id": mid, "product_type": "CONVENTIONAL", "prohibited_basis": "SEX",
               "period_start": "2026-01-01", "period_end": "2026-04-01"})
rid = run["data"]["id"]
call("POST", "/fair-lending/analysis-runs/%s/lock" % rid, "FairLendingAnalyst", "an1")
s, c = call("POST", "/fair-lending/analysis-runs/%s/compute" % rid, "FairLendingAnalyst", "an1")
check("compute ok", s == 200, c)
s, mf = call("POST", "/fair-lending/findings", "FairLendingAnalyst", "an1",
             {"analysis_run_id": rid, "kind": "MANUAL", "notes": "manual look"})
mfid = mf["data"]["id"]
check("manual finding created", s == 201 and mf["data"]["source"] == "MANUAL", mf)
call("POST", "/fair-lending/findings/%s/begin-review" % mfid, "FairLendingAnalyst", "an1")
# SoD: creator an1 cannot substantiate
s, bad = call("POST", "/fair-lending/findings/%s/substantiate" % mfid, "FairLendingOfficer", "an1",
              {"harmed_application_ids": [a1]})
check("manual substantiate SoD", s == 403 and bad["data"]["error_id"] == "ERR_SOD_VIOLATION", bad)
s, sub = call("POST", "/fair-lending/findings/%s/substantiate" % mfid, "FairLendingOfficer", "of1",
              {"harmed_application_ids": [a1, a2]})
check("substantiate 200", s == 200, sub)
fver = sub["data"]["version"]

# CAP with past-due date, EXECUTING, then advance clock -> OVERDUE
s, cap = call("POST", "/fair-lending/corrective-action-plans", "FairLendingAnalyst", "an1",
              {"finding_id": mfid, "title": "T", "pool_cents": 1000, "due_date": "2026-06-10",
               "expected_finding_version": fver})
capid = cap["data"]["id"]
# second CAP supersedes the DRAFT; give it the near due date for overdue tests
s, dup = call("POST", "/fair-lending/corrective-action-plans", "FairLendingAnalyst", "an1",
              {"finding_id": mfid, "title": "T2", "pool_cents": 100, "due_date": "2026-06-10",
               "expected_finding_version": fver + 1})
check("CAP while DRAFT ok (supersede)", s == 201, dup)  # drafting supersedes DRAFT
dupid = dup["data"]["id"]
# now dup is DRAFT, capid SUPERSEDED
s, capg = call("GET", "/fair-lending/corrective-action-plans/%s" % capid, "ComplianceDirector", "cd1")
check("old cap superseded", capg["data"]["status"] == "SUPERSEDED", capg["data"])
call("POST", "/fair-lending/corrective-action-plans/%s/submit" % dupid, "FairLendingAnalyst", "an1")
s, tri = call("POST", "/fair-lending/corrective-action-plans", "FairLendingAnalyst", "an1",
              {"finding_id": mfid, "title": "T3", "pool_cents": 100, "due_date": "2026-07-01",
               "expected_finding_version": fver + 2})
check("CAP_ACTIVE 409", s == 409 and tri["data"]["error_id"] == "ERR_CAP_ACTIVE", tri)
s, ap = call("POST", "/fair-lending/corrective-action-plans/%s/approve" % dupid, "FairLendingOfficer", "of1")
check("approve 200", s == 200 and ap["data"]["remaining_cents"] == 0, ap)
# manual payment over budget
s, mp = call("POST", "/fair-lending/remediation-payments", "RemediationSpecialist", "rs1",
             {"corrective_action_plan_id": dupid, "application_id": a1, "amount_cents": 5})
check("over budget 422", s == 422 and mp["data"]["error_id"] == "ERR_CAP_BUDGET_EXCEEDED", mp)
# payee not in scope
a3 = mk_app(mid, bid, oid, "CONTROL", "ORIGINATED", 720, 430, "2026-02-01")
call("POST", "/fair-lending/applications/%s/validate" % a3, "LendingDataOps", "do1")
s, mp = call("POST", "/fair-lending/remediation-payments", "RemediationSpecialist", "rs1",
             {"corrective_action_plan_id": dupid, "application_id": a3, "amount_cents": 0})
check("payee not in scope 422", s == 422 and mp["data"]["error_id"] == "ERR_PAYEE_NOT_IN_CAP_SCOPE", mp)
# void one payment -> funds return
s, pays = call("GET", "/fair-lending/remediation-payments", "RemediationSpecialist", "rs1",
               qs={"corrective_action_plan_id": dupid})
p1 = pays["data"][0]
s, vd = call("POST", "/fair-lending/remediation-payments/%s/void" % p1["id"], "RemediationSpecialist", "rs1",
             {"reason": "duplicate"})
check("void 200", s == 200 and vd["data"]["status"] == "VOIDED", vd)
s, capg = call("GET", "/fair-lending/corrective-action-plans/%s" % dupid, "ComplianceDirector", "cd1")
check("remaining restored after void", capg["data"]["remaining_cents"] == p1["amount_cents"], capg["data"])
# manual payment now fits within restored remaining
s, mp = call("POST", "/fair-lending/remediation-payments", "RemediationSpecialist", "rs1",
             {"corrective_action_plan_id": dupid, "application_id": a1, "amount_cents": p1["amount_cents"]})
check("manual payment 201", s == 201 and mp["data"]["origin"] == "MANUAL", mp)
mpid = mp["data"]["id"]

# overdue flip: due 2026-06-10, clock 2026-06-01 (not overdue); advance to 06-11
s, cyc = call("POST", "/fair-lending/monitoring/run-cycle", "ComplianceDirector", "cd1")
check("not overdue yet", dupid not in cyc["data"]["overdue_cap_ids"], cyc["data"])
call("POST", "/_clock/set_current_utc", "BankAdmin", "ba1", {"to_iso8601": "2026-06-11T00:00:00Z"})
s, cyc = call("POST", "/fair-lending/monitoring/run-cycle", "ComplianceDirector", "cd1")
check("overdue flip", dupid in cyc["data"]["overdue_cap_ids"], cyc["data"])
# extend with past date -> 400
s, ext = call("POST", "/fair-lending/corrective-action-plans/%s/extend" % dupid,
              "ComplianceDirector", "cd1", {"new_due_date": "2026-06-01"})
check("extend past 400", s == 400 and ext["data"]["error_id"] == "ERR_INVALID_REQUEST", ext)
s, ext = call("POST", "/fair-lending/corrective-action-plans/%s/extend" % dupid,
              "ComplianceDirector", "cd1", {"new_due_date": "2026-12-31"})
check("extend 200 EXECUTING", s == 200 and ext["data"]["status"] == "EXECUTING"
      and ext["data"]["due_date"] == "2026-12-31", ext)

# disburse + mark-returned clawback
s, dd = call("POST", "/fair-lending/remediation-payments/%s/disburse" % mpid, "RemediationSpecialist", "rs2")
check("manual disburse 200", s == 200 and dd["data"]["status"] == "DISBURSED", dd)
s, mr = call("POST", "/fair-lending/remediation-payments/%s/mark-returned" % mpid,
             "RemediationSpecialist", "rs2", {"reason": "bounced"})
check("mark-returned 200", s == 200 and mr["data"]["status"] == "RETURNED", mr)
s, capg = call("GET", "/fair-lending/corrective-action-plans/%s" % dupid, "ComplianceDirector", "cd1")
check("clawback counters", capg["data"]["disbursed_cents"] == 0
      and capg["data"]["remaining_cents"] == 50, capg["data"])

# disburse both auto payments -> complete -> finding CLOSED
s, pays = call("GET", "/fair-lending/remediation-payments", "RemediationSpecialist", "rs1",
               qs={"corrective_action_plan_id": dupid, "status": "PENDING"})
for p in pays["data"]:
    s, dd = call("POST", "/fair-lending/remediation-payments/%s/disburse" % p["id"],
                 "RemediationSpecialist", "rs2")
    check("disburse pending", s == 200, dd)
s, capg = call("GET", "/fair-lending/corrective-action-plans/%s" % dupid, "ComplianceDirector", "cd1")
check("cap COMPLETED", capg["data"]["status"] == "COMPLETED", capg["data"])
s, fg = call("GET", "/fair-lending/findings/%s" % mfid, "ComplianceDirector", "cd1")
check("finding CLOSED", fg["data"]["status"] == "CLOSED", fg["data"])

# --- self-test violation -> remediated path ---
s, st = call("POST", "/fair-lending/self-tests", "FairLendingAnalyst", "an1",
             {"market_id": mid, "analysis_run_id": rid,
              "window_start": "2026-01-01", "window_end": "2026-03-31"})
stid = st["data"]["id"]
s, cl = call("POST", "/fair-lending/self-tests/%s/close" % stid, "FairLendingOfficer", "of1",
             {"outcome": "VIOLATION_FOUND"})
check("close VIOLATION 200", s == 200 and cl["data"]["status"] == "CLOSED_VIOLATION", cl)
s, mr = call("POST", "/fair-lending/self-tests/%s/mark-remediated" % stid, "FairLendingOfficer", "of1")
check("mark-remediated 200", s == 200 and mr["data"]["status"] == "REMEDIATED", mr)

# --- privilege forfeiture on a fresh self-test ---
s, run2 = call("POST", "/fair-lending/analysis-runs", "FairLendingAnalyst", "an1",
               {"market_id": mid, "product_type": "FHA", "prohibited_basis": "AGE",
                "period_start": "2026-01-01", "period_end": "2026-04-01"})
rid2 = run2["data"]["id"]
a4 = mk_app(mid, bid, oid, "CONTROL", "ORIGINATED", 730, 440, "2026-01-20", prod="FHA")
call("POST", "/fair-lending/applications/%s/validate" % a4, "LendingDataOps", "do1")
call("POST", "/fair-lending/analysis-runs/%s/lock" % rid2, "FairLendingAnalyst", "an1")
call("POST", "/fair-lending/analysis-runs/%s/compute" % rid2, "FairLendingAnalyst", "an1")
s, mf2 = call("POST", "/fair-lending/findings", "FairLendingAnalyst", "an1",
              {"analysis_run_id": rid2, "kind": "MANUAL", "notes": "x"})
mf2id = mf2["data"]["id"]
call("POST", "/fair-lending/findings/%s/begin-review" % mf2id, "FairLendingAnalyst", "an1")
call("POST", "/fair-lending/findings/%s/substantiate" % mf2id, "FairLendingOfficer", "of1",
     {"harmed_application_ids": [a4]})
s, st2 = call("POST", "/fair-lending/self-tests", "FairLendingAnalyst", "an1",
              {"market_id": mid, "analysis_run_id": rid2,
               "window_start": "2026-04-01", "window_end": "2026-06-30"})
st2id = st2["data"]["id"]
call("POST", "/fair-lending/self-tests/%s/designate-privileged" % st2id, "ComplianceDirector", "cd1")
s, cl = call("POST", "/fair-lending/self-tests/%s/close" % st2id, "FairLendingOfficer", "of1",
             {"outcome": "VIOLATION_FOUND"})
check("close violation privileged", s == 200 and cl["data"]["status"] == "CLOSED_VIOLATION", cl)
s, cyc = call("POST", "/fair-lending/monitoring/run-cycle", "ComplianceDirector", "cd1")
check("cycle1 no forfeit", st2id not in cyc["data"]["privilege_lost_self_test_ids"], cyc["data"])
s, cyc = call("POST", "/fair-lending/monitoring/run-cycle", "ComplianceDirector", "cd1")
check("cycle2 forfeit", st2id in cyc["data"]["privilege_lost_self_test_ids"], cyc["data"])
s, stg = call("GET", "/fair-lending/self-tests/%s" % st2id, "ComplianceDirector", "cd1")
check("PRIVILEGE_LOST + DISCLOSABLE", stg["data"]["status"] == "PRIVILEGE_LOST"
      and stg["data"]["disclosure_status"] == "DISCLOSABLE", stg["data"])

# --- matched-pair selector ranking ---
s, run3 = call("POST", "/fair-lending/analysis-runs", "FairLendingAnalyst", "an1",
               {"market_id": mid, "product_type": "VA", "prohibited_basis": "RACE",
                "period_start": "2026-01-01", "period_end": "2026-04-01"})
rid3 = run3["data"]["id"]
targ = mk_app(mid, bid, oid, "PROTECTED_1", "DENIED", 700, 500, "2026-01-25", prod="VA")
call("POST", "/fair-lending/applications/%s/validate" % targ, "LendingDataOps", "do1")
c1 = mk_app(mid, bid, oid, "CONTROL", "ORIGINATED", 710, 500, "2026-01-26", prod="VA")
call("POST", "/fair-lending/applications/%s/validate" % c1, "LendingDataOps", "do1")
c2 = mk_app(mid, bid, oid, "CONTROL", "ORIGINATED", 705, 500, "2026-01-27", prod="VA")
call("POST", "/fair-lending/applications/%s/validate" % c2, "LendingDataOps", "do1")
call("POST", "/fair-lending/analysis-runs/%s/lock" % rid3, "FairLendingAnalyst", "an1")
call("POST", "/fair-lending/analysis-runs/%s/compute" % rid3, "FairLendingAnalyst", "an1")
s, mf3 = call("POST", "/fair-lending/findings", "FairLendingAnalyst", "an1",
              {"analysis_run_id": rid3, "kind": "DENIAL_DISPARITY", "notes": "x"})
mf3id = mf3["data"]["id"]
call("POST", "/fair-lending/findings/%s/begin-review" % mf3id, "FairLendingAnalyst", "an1")
s, f3g = call("GET", "/fair-lending/findings/%s" % mf3id, "FairLendingAnalyst", "an1")
# selector picks nearest credit score: c2 (705, diff 5) over c1 (710, diff 10)
s, mp = call("POST", "/fair-lending/matched-pair-reviews", "FairLendingAnalyst", "an1",
             {"finding_id": mf3id, "target_application_id": targ,
              "expected_finding_version": f3g["data"]["version"]})
check("selector 201", s == 201 and mp["data"]["selector_used"] is True, mp)
check("selector nearest", mp["data"]["control_application_id"] == c2, mp["data"])
# second review supersedes the first
s, f3g = call("GET", "/fair-lending/findings/%s" % mf3id, "FairLendingAnalyst", "an1")
s, mp2 = call("POST", "/fair-lending/matched-pair-reviews", "FairLendingAnalyst", "an1",
              {"finding_id": mf3id, "target_application_id": targ,
               "control_application_id": c1, "expected_finding_version": f3g["data"]["version"]})
check("second review 201", s == 201, mp2)
s, mp1g = call("GET", "/fair-lending/matched-pair-reviews/%s" % mp["data"]["id"], "FairLendingAnalyst", "an1")
check("first review superseded", mp1g["data"]["status"] == "SUPERSEDED", mp1g["data"])
# incomparable control: credit diff > 40
c3 = mk_app(mid, bid, oid, "CONTROL", "ORIGINATED", 800, 500, "2026-01-28", prod="VA")
call("POST", "/fair-lending/applications/%s/validate" % c3, "LendingDataOps", "do1")
s, f3g = call("GET", "/fair-lending/findings/%s" % mf3id, "FairLendingAnalyst", "an1")
s, bad = call("POST", "/fair-lending/matched-pair-reviews", "FairLendingAnalyst", "an1",
              {"finding_id": mf3id, "target_application_id": targ,
               "control_application_id": c3, "expected_finding_version": f3g["data"]["version"]})
check("not comparable 422", s == 422 and bad["data"]["error_id"] == "ERR_MATCH_NOT_COMPARABLE", bad)
# dispute -> re-review cycle
call("POST", "/fair-lending/matched-pair-reviews/%s/submit-initial" % mp2["data"]["id"],
     "FairLendingAnalyst", "an1", {"outcome": "DIFFERENTIAL_TREATMENT"})
s, dis = call("POST", "/fair-lending/matched-pair-reviews/%s/dispute" % mp2["data"]["id"],
              "LoanOfficer", oid, {"reason": "disagree"})
check("dispute 200", s == 200 and dis["data"]["status"] == "DISPUTED", dis)
s, re = call("POST", "/fair-lending/matched-pair-reviews/%s/submit-initial" % mp2["data"]["id"],
             "FairLendingAnalyst", "an2", {"outcome": "COMPARABLE_TREATMENT"})
check("re-review overwrites", s == 200 and re["data"]["initial_reviewer_user_id"] == "an2"
      and re["data"]["initial_outcome"] == "COMPARABLE_TREATMENT", re)
s, cf = call("POST", "/fair-lending/matched-pair-reviews/%s/confirm" % mp2["data"]["id"],
             "FairLendingOfficer", "of1")
check("confirm after re-review", s == 200 and cf["data"]["status"] == "CONFIRMED", cf)

# --- finding supersede semantics + reopen loop ---
s, fA = call("POST", "/fair-lending/findings", "FairLendingAnalyst", "an1",
             {"analysis_run_id": rid3, "kind": "MANUAL", "notes": "A"})
fA_id = fA["data"]["id"]
s, r3g = call("GET", "/fair-lending/analysis-runs/%s" % rid3, "FairLendingAnalyst", "an1")
before = r3g["data"]["open_finding_count"]
s, fB = call("POST", "/fair-lending/findings", "FairLendingAnalyst", "an1",
             {"analysis_run_id": rid3, "kind": "MANUAL", "notes": "B",
              "supersedes_finding_id": fA_id})
check("supersede create 201", s == 201, fB)
s, r3g = call("GET", "/fair-lending/analysis-runs/%s" % rid3, "FairLendingAnalyst", "an1")
check("open count net zero on supersede", r3g["data"]["open_finding_count"] == before, r3g["data"])
s, fAg = call("GET", "/fair-lending/findings/%s" % fA_id, "FairLendingAnalyst", "an1")
check("superseded pointer", fAg["data"]["status"] == "SUPERSEDED"
      and fAg["data"]["superseded_by_finding_id"] == fB["data"]["id"], fAg["data"])
# refute -> reopen loop
fB_id = fB["data"]["id"]
call("POST", "/fair-lending/findings/%s/begin-review" % fB_id, "FairLendingAnalyst", "an1")
s, rf = call("POST", "/fair-lending/findings/%s/refute" % fB_id, "FairLendingOfficer", "of1",
             {"reason": "explainable"})
check("refute 200", s == 200 and rf["data"]["refute_reason"] == "explainable", rf)
s, ro = call("POST", "/fair-lending/findings/%s/reopen" % fB_id, "FairLendingAnalyst", "an1",
             {"reason": "new info"})
check("reopen 200 count 1", s == 200 and ro["data"]["reopen_count"] == 1
      and ro["data"]["status"] == "UNDER_REVIEW", ro)

# --- high-value CAP requires director ---
s, fH = call("POST", "/fair-lending/findings", "FairLendingAnalyst", "an1",
             {"analysis_run_id": rid3, "kind": "MANUAL", "notes": "H"})
fH_id = fH["data"]["id"]
call("POST", "/fair-lending/findings/%s/begin-review" % fH_id, "FairLendingAnalyst", "an1")
s, subH = call("POST", "/fair-lending/findings/%s/substantiate" % fH_id, "FairLendingOfficer", "of1",
               {"harmed_application_ids": [targ]})
s, capH = call("POST", "/fair-lending/corrective-action-plans", "FairLendingAnalyst", "an1",
               {"finding_id": fH_id, "title": "big", "pool_cents": 25000000,
                "due_date": "2027-01-01",
                "expected_finding_version": subH["data"]["version"]})
capH_id = capH["data"]["id"]
call("POST", "/fair-lending/corrective-action-plans/%s/submit" % capH_id, "FairLendingAnalyst", "an1")
s, bad = call("POST", "/fair-lending/corrective-action-plans/%s/approve" % capH_id,
              "FairLendingOfficer", "of1")
check("high-value needs director", s == 403
      and bad["data"]["error_id"] == "ERR_DIRECTOR_APPROVAL_REQUIRED", bad)
s, ok = call("POST", "/fair-lending/corrective-action-plans/%s/approve" % capH_id,
             "ComplianceDirector", "cd1")
check("director approves high-value", s == 200, ok)
# below threshold: 24999999 allowed for officer
s, fL = call("POST", "/fair-lending/findings", "FairLendingAnalyst", "an1",
             {"analysis_run_id": rid3, "kind": "MANUAL", "notes": "L"})
fL_id = fL["data"]["id"]
call("POST", "/fair-lending/findings/%s/begin-review" % fL_id, "FairLendingAnalyst", "an1")
s, subL = call("POST", "/fair-lending/findings/%s/substantiate" % fL_id, "FairLendingOfficer", "of1",
               {"harmed_application_ids": [targ]})
s, capL = call("POST", "/fair-lending/corrective-action-plans", "FairLendingAnalyst", "an1",
               {"finding_id": fL_id, "title": "small", "pool_cents": 24999999,
                "due_date": "2027-01-01",
                "expected_finding_version": subL["data"]["version"]})
capL_id = capL["data"]["id"]
call("POST", "/fair-lending/corrective-action-plans/%s/submit" % capL_id, "FairLendingAnalyst", "an1")
s, ok = call("POST", "/fair-lending/corrective-action-plans/%s/approve" % capL_id,
             "FairLendingOfficer", "of1")
check("officer approves below threshold", s == 200, ok)

# --- pagination meta ---
s, lst = call("GET", "/fair-lending/applications", "BankAdmin", "ba1", qs={"limit": "3", "offset": "0"})
check("pagination meta", s == 200 and lst["meta"]["limit"] == 3 and lst["meta"]["offset"] == 0
      and lst["meta"]["has_more"] is True and len(lst["data"]) == 3, lst["meta"])
s, lst2 = call("GET", "/fair-lending/applications", "BankAdmin", "ba1",
               qs={"limit": "3", "offset": str(lst["meta"]["total_count"])})
check("pagination tail", lst2["meta"]["has_more"] is False and lst2["data"] == [], lst2["meta"])
s, badl = call("GET", "/fair-lending/applications", "BankAdmin", "ba1", qs={"limit": "0"})
check("limit 0 -> 400", s == 400 and badl["data"]["error_id"] == "ERR_INVALID_REQUEST", badl)
s, badl = call("GET", "/fair-lending/applications", "BankAdmin", "ba1", qs={"limit": "101"})
check("limit 101 -> 400", s == 400, badl)

print()
if FAILS:
    print("FAILURES: %d" % len(FAILS))
    for f in FAILS:
        print(" -", f)
    raise SystemExit(1)
print("ALL EDGE CHECKS PASSED")
