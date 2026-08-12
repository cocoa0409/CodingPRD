"""End-to-end exercise of the main workflows against a live server."""
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
        FAILS.append("%s: %s" % (name, detail))
        print("FAIL", name, detail)
    else:
        print("ok  ", name)


# Setup: market, branch, officer
s, m = call("POST", "/fair-lending/markets", "BankAdmin", "ba1",
            {"name": "Metro", "msa_code": "M1", "protected_group_population_share": 0.5,
             "peer_group_code": "PG1"})
check("market 201", s == 201, m)
mid = m["data"]["id"]
s, b = call("POST", "/fair-lending/branches", "BankAdmin", "ba1",
            {"market_id": mid, "name": "Main", "tract_minority_pct": 55.0,
             "opened_on": "2020-01-01"})
check("branch 201", s == 201, b)
bid = b["data"]["id"]
s, o = call("POST", "/fair-lending/loan-officers", "BankAdmin", "ba1",
            {"branch_id": bid, "full_name": "Officer One"})
check("officer 201", s == 201 and o["data"]["monitoring_tier"] == "GREEN", o)
oid = o["data"]["id"]

# Applications: control 4 originated of 5; protected 1 originated of 4 (net)
# net rates: control 4/5=0.8, protected 1/4=0.25 -> ratio 0.3125 -> ADVERSE + flag
# raw: control 4/6, protected 1/5 -> (0.2)/(0.6667)=0.3000 -> flag
apps = []
specs = [
    ("CONTROL", "ORIGINATED", 400), ("CONTROL", "ORIGINATED", 410),
    ("CONTROL", "ORIGINATED", 420), ("CONTROL", "ORIGINATED", 430),
    ("CONTROL", "DENIED", 440), ("CONTROL", "WITHDRAWN", 450),
    ("PROTECTED_1", "ORIGINATED", 405), ("PROTECTED_1", "DENIED", 415),
    ("PROTECTED_2", "DENIED", 425), ("PROTECTED_1", "DENIED", 435),
    ("PROTECTED_2", "WITHDRAWN", 445),
]
for grp, out, cs in specs:
    s, a = call("POST", "/fair-lending/applications", "LendingDataOps", "do1",
                {"market_id": mid, "branch_id": bid, "loan_officer_id": oid,
                 "product_type": "CONVENTIONAL", "applicant_group": grp, "outcome": out,
                 "note_rate_bps": 400 if grp == "CONTROL" else 430,
                 "loan_amount_cents": 1000000, "credit_score": cs, "dti_pct": 35.0,
                 "application_date": "2026-01-05", "decision_date": "2026-02-10"})
    check("app 201 %s/%s" % (grp, out), s == 201, a)
    apps.append(a["data"]["id"])

# officer identity for LoanOfficer role = officer id
s, r = call("POST", "/fair-lending/applications/%s/validate" % apps[0], "LoanOfficer", oid)
check("validate wrong role 403", s == 403 and r["data"]["error_id"] == "ERR_UNAUTHORIZED_ROLE", r)
for aid in apps:
    s, a = call("POST", "/fair-lending/applications/%s/validate" % aid, "LendingDataOps", "do1")
    check("validate 200", s == 200 and a["data"]["status"] == "VALIDATED", a)

# officer validated count
s, o2 = call("GET", "/fair-lending/loan-officers/%s" % oid, "BankAdmin", "ba1")
check("validated count 11", o2["data"]["validated_application_count"] == 11, o2["data"])

# Analysis run
s, run = call("POST", "/fair-lending/analysis-runs", "FairLendingAnalyst", "an1",
              {"market_id": mid, "product_type": "CONVENTIONAL", "prohibited_basis": "RACE",
               "period_start": "2026-01-01", "period_end": "2026-04-01"})
check("run 201", s == 201 and run["data"]["status"] == "DRAFT", run)
rid = run["data"]["id"]

# scope overlap
s, dup = call("POST", "/fair-lending/analysis-runs", "FairLendingAnalyst", "an1",
              {"market_id": mid, "product_type": "CONVENTIONAL", "prohibited_basis": "RACE",
               "period_start": "2026-03-01", "period_end": "2026-06-01"})
check("overlap 409", s == 409 and dup["data"]["error_id"] == "ERR_SCOPE_OVERLAP", dup)
# adjacency allowed
s, adj = call("POST", "/fair-lending/analysis-runs", "FairLendingAnalyst", "an1",
              {"market_id": mid, "product_type": "CONVENTIONAL", "prohibited_basis": "RACE",
               "period_start": "2026-04-01", "period_end": "2026-07-01"})
check("adjacency 201", s == 201, adj)
rid2 = adj["data"]["id"]

s, l = call("POST", "/fair-lending/analysis-runs/%s/lock" % rid, "FairLendingAnalyst", "an1")
check("lock 200 count 11", s == 200 and l["data"]["snapshot_application_count"] == 11, l)

# staleness: correct an app after clock advance
s, _ = call("POST", "/_clock/set_current_utc", "BankAdmin", "ba1",
            {"to_iso8601": "2026-05-02T00:00:00Z"})
s, cor = call("PUT", "/fair-lending/applications/%s" % apps[4], "LendingDataOps", "do1",
              {"expected_application_version": 2, "outcome": "ORIGINATED"})
check("correct 200 revert", s == 200 and cor["data"]["status"] == "RECEIVED", cor)
s, c = call("POST", "/fair-lending/analysis-runs/%s/compute" % rid, "FairLendingAnalyst", "an1")
check("stale 409", s == 409 and c["data"]["error_id"] == "ERR_STALE_DATASET", c)

# unlock, re-validate, re-lock
s, u = call("POST", "/fair-lending/analysis-runs/%s/unlock" % rid, "FairLendingAnalyst", "an1")
check("unlock 200", s == 200 and u["data"]["status"] == "DRAFT", u)
s, _ = call("POST", "/fair-lending/applications/%s/validate" % apps[4], "LendingDataOps", "do1")
check("revalidate 200", s == 200)
s, l = call("POST", "/fair-lending/analysis-runs/%s/lock" % rid, "FairLendingAnalyst", "an1")
check("relock 200", s == 200, l)
s, c = call("POST", "/fair-lending/analysis-runs/%s/compute" % rid, "FairLendingAnalyst", "an1")
# control now 5/5 originated (net 1.0), protected 1/4 (0.25) -> ratio 0.25 ADVERSE
check("compute 200", s == 200 and c["data"]["status"] == "COMPUTED", c)
check("net ratio 0.25", c["data"]["impact_ratio_net"] == 0.25, c["data"])
check("classification ADVERSE", c["data"]["adverse_classification"] == "ADVERSE", c["data"])
check("screening flag", c["data"]["screening_flag"] is True, c["data"])
# pricing: protected mean 430, control mean 400 -> +30 bps > 15 -> pricing finding
check("pricing unadj 30", c["data"]["pricing_disparity_unadjusted_bps"] == 30.0, c["data"])
check("open findings 2", c["data"]["open_finding_count"] == 2, c["data"])

s, fs = call("GET", "/fair-lending/findings", "FairLendingAnalyst", "an1", qs={"analysis_run_id": rid})
check("2 auto findings", s == 200 and fs["meta"]["total_count"] == 2, fs)
denial = [f for f in fs["data"] if f["kind"] == "DENIAL_DISPARITY"][0]
check("auto finding fields", denial["source"] == "AUTO" and denial["threshold_value"] == 0.8
      and denial["created_by_user_id"] == "system", denial)
fid = denial["id"]

# begin review -> run UNDER_REVIEW
s, f2 = call("POST", "/fair-lending/findings/%s/begin-review" % fid, "FairLendingAnalyst", "an1")
check("begin-review 200", s == 200 and f2["data"]["status"] == "UNDER_REVIEW", f2)
s, r3 = call("GET", "/fair-lending/analysis-runs/%s" % rid, "FairLendingAnalyst", "an1")
check("run UNDER_REVIEW", r3["data"]["status"] == "UNDER_REVIEW", r3["data"])

# substantiate without confirmed matched pair -> 409
s, sub = call("POST", "/fair-lending/findings/%s/substantiate" % fid, "FairLendingOfficer", "of1",
              {"harmed_application_ids": []})
check("substantiate no pair 409", s == 409 and sub["data"]["error_id"] == "ERR_NO_CONFIRMED_MATCHED_PAIR", sub)

# matched pair: target = protected DENIED (apps[7]), control supplied = control ORIGINATED (apps[1])
fver = f2["data"]["version"]
s, mp = call("POST", "/fair-lending/matched-pair-reviews", "FairLendingAnalyst", "an1",
             {"finding_id": fid, "target_application_id": apps[7],
              "control_application_id": apps[1], "expected_finding_version": fver})
check("mp create 201", s == 201 and mp["data"]["selector_used"] is False, mp)
mpid = mp["data"]["id"]

# OCC stale
s, stale = call("POST", "/fair-lending/matched-pair-reviews", "FairLendingAnalyst", "an1",
                {"finding_id": fid, "target_application_id": apps[8],
                 "control_application_id": apps[0], "expected_finding_version": 1})
check("mp stale 412", s == 412 and stale["data"]["error_id"] == "ERR_STALE_VERSION", stale)

# submit initial, confirm with SoD
s, si = call("POST", "/fair-lending/matched-pair-reviews/%s/submit-initial" % mpid,
             "FairLendingAnalyst", "an1", {"outcome": "DIFFERENTIAL_TREATMENT", "notes": "x"})
check("submit-initial 200", s == 200 and si["data"]["status"] == "INITIAL_REVIEWED", si)
s, bad = call("POST", "/fair-lending/matched-pair-reviews/%s/confirm" % mpid,
              "FairLendingOfficer", "an1")
check("confirm SoD 403", s == 403 and bad["data"]["error_id"] == "ERR_SOD_VIOLATION", bad)
s, cf = call("POST", "/fair-lending/matched-pair-reviews/%s/confirm" % mpid,
             "FairLendingOfficer", "of1")
check("confirm 200", s == 200 and cf["data"]["status"] == "CONFIRMED", cf)

# dispute is only from INITIAL_REVIEWED; now CONFIRMED -> terminal
s, dis = call("POST", "/fair-lending/matched-pair-reviews/%s/dispute" % mpid,
              "LoanOfficer", oid, {"reason": "no"})
check("dispute terminal 409", s == 409 and dis["data"]["error_id"] == "ERR_ALREADY_TERMINAL", dis)

# substantiate with harmed ids (protected DENIED: apps 7,8,9)
s, sub = call("POST", "/fair-lending/findings/%s/substantiate" % fid, "FairLendingOfficer", "of1",
              {"harmed_application_ids": [apps[7], apps[8], apps[9]]})
check("substantiate 200", s == 200 and sub["data"]["status"] == "SUBSTANTIATED", sub)
fver = sub["data"]["version"]

# CAP create, submit, approve (pool 100001 cents / 3 -> residual to first)
s, cap = call("POST", "/fair-lending/corrective-action-plans", "FairLendingAnalyst", "an1",
              {"finding_id": fid, "title": "Fix", "pool_cents": 100001,
               "due_date": "2026-12-31", "expected_finding_version": fver})
check("cap 201", s == 201 and cap["data"]["remaining_cents"] == 100001, cap)
capid = cap["data"]["id"]
s, _ = call("POST", "/fair-lending/corrective-action-plans/%s/submit" % capid, "FairLendingAnalyst", "an1")
s, ap = call("POST", "/fair-lending/corrective-action-plans/%s/approve" % capid, "FairLendingOfficer", "of1")
check("cap approve EXECUTING", s == 200 and ap["data"]["status"] == "EXECUTING", ap)
check("cap remaining 0", ap["data"]["remaining_cents"] == 0, ap["data"])

s, pays = call("GET", "/fair-lending/remediation-payments", "RemediationSpecialist", "rs1",
               qs={"corrective_action_plan_id": capid})
amts = [p["amount_cents"] for p in pays["data"]]
# share = round_half_up(100001/3)=33334; residual = 100001-100002 = -1 -> first gets 33333
check("allocation waterfall", sorted(amts) == [33333, 33334, 33334], amts)
first_pay = [p for p in pays["data"] if p["application_id"] == apps[7]][0]
check("residual to first harmed", first_pay["amount_cents"] == 33333, first_pay)

# disburse SoD: approver was of1; disburser must differ
s, dd = call("POST", "/fair-lending/remediation-payments/%s/disburse" % first_pay["id"],
             "RemediationSpecialist", "of1")
check("disburse SoD 403", s == 403 and dd["data"]["error_id"] == "ERR_SOD_VIOLATION", dd)
s, dd = call("POST", "/fair-lending/remediation-payments/%s/disburse" % first_pay["id"],
             "RemediationSpecialist", "rs1")
check("disburse 200", s == 200 and dd["data"]["status"] == "DISBURSED", dd)

# disburse remaining two -> CAP COMPLETED -> finding CLOSED -> run open count drops
for p in pays["data"]:
    if p["id"] != first_pay["id"]:
        s, dd = call("POST", "/fair-lending/remediation-payments/%s/disburse" % p["id"],
                     "RemediationSpecialist", "rs1")
        check("disburse all 200", s == 200, dd)
s, cap2 = call("GET", "/fair-lending/corrective-action-plans/%s" % capid, "ComplianceDirector", "cd1")
check("cap COMPLETED", cap2["data"]["status"] == "COMPLETED", cap2["data"])
check("cap disbursed 100001", cap2["data"]["disbursed_cents"] == 100001, cap2["data"])
s, f3 = call("GET", "/fair-lending/findings/%s" % fid, "FairLendingOfficer", "of1")
check("finding CLOSED", f3["data"]["status"] == "CLOSED", f3["data"])
s, r4 = call("GET", "/fair-lending/analysis-runs/%s" % rid, "FairLendingOfficer", "of1")
check("run open count 1", r4["data"]["open_finding_count"] == 1, r4["data"])

# finalize blocked: pricing finding still open
s, fin = call("POST", "/fair-lending/analysis-runs/%s/finalize" % rid, "FairLendingOfficer", "of1")
check("finalize blocked 409", s == 409 and fin["data"]["error_id"] == "ERR_FINDINGS_OPEN", fin)

# refute pricing finding then finalize
s, fs = call("GET", "/fair-lending/findings", "FairLendingAnalyst", "an1",
             qs={"analysis_run_id": rid, "status": "FLAGGED"})
pfid = fs["data"][0]["id"]
call("POST", "/fair-lending/findings/%s/begin-review" % pfid, "FairLendingAnalyst", "an1")
s, ref = call("POST", "/fair-lending/findings/%s/refute" % pfid, "FairLendingOfficer", "of1",
              {"reason": "justified by volume pricing"})
check("refute 200", s == 200 and ref["data"]["status"] == "REFUTED", ref)
s, fin = call("POST", "/fair-lending/analysis-runs/%s/finalize" % rid, "FairLendingOfficer", "of1")
check("finalize 200", s == 200 and fin["data"]["status"] == "FINALIZED", fin)

# frozen: correction now blocked
s, cor = call("PUT", "/fair-lending/applications/%s" % apps[0], "LendingDataOps", "do1",
              {"expected_application_version": 2, "dti_pct": 30.0})
check("frozen 409", s == 409 and cor["data"]["error_id"] == "ERR_APPLICATION_LOCKED", cor)

# archive releases scope overlap
s, ar = call("POST", "/fair-lending/analysis-runs/%s/archive" % rid, "FairLendingOfficer", "of1")
check("archive 200", s == 200 and ar["data"]["status"] == "ARCHIVED", ar)
s, dup = call("POST", "/fair-lending/analysis-runs", "FairLendingAnalyst", "an1",
              {"market_id": mid, "product_type": "CONVENTIONAL", "prohibited_basis": "RACE",
               "period_start": "2026-02-01", "period_end": "2026-03-01"})
check("overlap released after archive", s == 201, dup)
rid3 = dup["data"]["id"]

# --- pricing exception flow on the Q2 run's officer (new market data) ---
s, o3 = call("GET", "/fair-lending/loan-officers/%s" % oid, "BankAdmin", "ba1")
check("officer risk recompute fields", "risk_score" in o3["data"], o3["data"])

# new validated app for exception (decision in Q2)
s, a2 = call("POST", "/fair-lending/applications", "LendingDataOps", "do1",
             {"market_id": mid, "branch_id": bid, "loan_officer_id": oid,
              "product_type": "FHA", "applicant_group": "PROTECTED_1", "outcome": "ORIGINATED",
              "note_rate_bps": 500, "loan_amount_cents": 200000, "credit_score": 700,
              "dti_pct": 40.0, "application_date": "2026-04-05", "decision_date": "2026-04-20"})
a2id = a2["data"]["id"]
call("POST", "/fair-lending/applications/%s/validate" % a2id, "LendingDataOps", "do1")
# exception by wrong officer
s, ex = call("POST", "/fair-lending/pricing-exceptions", "LoanOfficer", "someone-else",
             {"application_id": a2id, "kind": "RATE_ABOVE_CAP", "requested_rate_bps": 550,
              "justification": "competition"})
check("exception ownership 403", s == 403 and ex["data"]["error_id"] == "ERR_OWNERSHIP_MISMATCH", ex)
s, ex = call("POST", "/fair-lending/pricing-exceptions", "LoanOfficer", oid,
             {"application_id": a2id, "kind": "RATE_ABOVE_CAP", "requested_rate_bps": 550,
              "justification": "competition"})
check("exception 201", s == 201 and ex["data"]["status"] == "REQUESTED", ex)
exid = ex["data"]["id"]
s, ap2 = call("POST", "/fair-lending/pricing-exceptions/%s/approve" % exid, "FairLendingOfficer", "of1")
check("exception approve 200", s == 200 and ap2["data"]["status"] == "APPROVED", ap2)
check("decided fields", ap2["data"]["decided_by_user_id"] == "of1" and ap2["data"]["decided_at"], ap2["data"])

# override: same decisions -> 422
s, ov = call("POST", "/fair-lending/underwriting-overrides", "LoanOfficer", oid,
             {"application_id": a2id, "original_decision": "DENY", "overridden_decision": "DENY",
              "justification": "x"})
check("override same pair 422", s == 422 and ov["data"]["error_id"] == "ERR_INVALID_DECISION_PAIR", ov)
s, ov = call("POST", "/fair-lending/underwriting-overrides", "LoanOfficer", oid,
             {"application_id": a2id, "original_decision": "DENY", "overridden_decision": "APPROVE",
              "justification": "x"})
check("override 201", s == 201 and ov["data"]["status"] == "RECORDED", ov)
ovid = ov["data"]["id"]
s, co = call("POST", "/fair-lending/underwriting-overrides/%s/confirm" % ovid, "FairLendingOfficer", "of1")
check("override confirm 200", s == 200 and co["data"]["status"] == "CONFIRMED", co)
s, o4 = call("GET", "/fair-lending/loan-officers/%s" % oid, "BankAdmin", "ba1")
check("override count 1", o4["data"]["confirmed_override_count"] == 1, o4["data"])

# scorecard
s, sc = call("GET", "/fair-lending/loan-officers/%s/risk-scorecard" % oid, "FairLendingAnalyst", "an1")
check("scorecard fields", s == 200 and "override_rate" in sc["data"] and "monitoring_tier" in sc["data"], sc)

# suspend blocks new exception
call("POST", "/fair-lending/loan-officers/%s/suspend" % oid, "ComplianceDirector", "cd1")
s, ex2 = call("POST", "/fair-lending/pricing-exceptions", "LoanOfficer", oid,
              {"application_id": a2id, "kind": "FEE_WAIVER", "requested_rate_bps": 500,
               "justification": "y"})
check("suspended 409", s == 409 and ex2["data"]["error_id"] == "ERR_OFFICER_SUSPENDED", ex2)
call("POST", "/fair-lending/loan-officers/%s/reinstate" % oid, "ComplianceDirector", "cd1")

# branch close cascades
s, b2 = call("POST", "/fair-lending/branches", "BankAdmin", "ba1",
             {"market_id": mid, "name": "Second", "tract_minority_pct": 10.0, "opened_on": "2021-01-01"})
s, o5 = call("POST", "/fair-lending/loan-officers", "BankAdmin", "ba1",
             {"branch_id": b2["data"]["id"], "full_name": "Officer Two"})
call("POST", "/fair-lending/branches/%s/close" % b2["data"]["id"], "BankAdmin", "ba1")
s, o6 = call("GET", "/fair-lending/loan-officers/%s" % o5["data"]["id"], "BankAdmin", "ba1")
check("branch close cascades", o6["data"]["status"] == "SUSPENDED", o6["data"])

# --- penetration report ---
s, pen = call("GET", "/fair-lending/markets/%s/penetration-report" % mid, "FairLendingAnalyst", "an1",
              qs={"period_start": "2026-01-01", "period_end": "2026-04-01"})
# validated apps in Q1: 11 apps; originated: 5 control + 1 protected = 6; share = 1/6 = 0.1667
check("pen share", s == 200 and pen["data"]["bank_protected_origination_share"] == 0.1667, pen["data"])
check("pen branch weighted", pen["data"]["penetration_index_branch_weighted"] == 0.3333, pen["data"])
check("pen peer null", pen["data"]["penetration_index_peer_relative"] is None
      and pen["data"]["peer_benchmark_id"] is None, pen["data"])
# benchmark + peer relative
s, bm = call("POST", "/fair-lending/peer-benchmarks", "LendingDataOps", "do1",
             {"market_id": mid, "period_start": "2026-01-01", "period_end": "2026-04-01",
              "peer_protected_origination_rate": 0.25, "peer_origination_count": 900, "source": "HMDA"})
check("benchmark 201", s == 201, bm)
s, bm2 = call("POST", "/fair-lending/peer-benchmarks", "LendingDataOps", "do1",
              {"market_id": mid, "period_start": "2026-01-01", "period_end": "2026-07-01",
               "peer_protected_origination_rate": 0.3, "peer_origination_count": 100, "source": "HMDA"})
check("benchmark conflict 409", s == 409 and bm2["data"]["error_id"] == "ERR_BENCHMARK_PERIOD_CONFLICT", bm2)
s, pen2 = call("GET", "/fair-lending/markets/%s/penetration-report" % mid, "FairLendingAnalyst", "an1",
               qs={"period_start": "2026-01-01", "period_end": "2026-04-01"})
# protected validated = 5, protected originated = 1 -> 0.2 / 0.25 = 0.8
check("pen peer relative 0.8", pen2["data"]["penetration_index_peer_relative"] == 0.8, pen2["data"])
check("pen benchmark id", pen2["data"]["peer_benchmark_id"] == bm["data"]["id"], pen2["data"])

# --- self-test + privilege gate on run2 (Q2 CONVENTIONAL RACE) ---
s, st = call("POST", "/fair-lending/self-tests", "FairLendingAnalyst", "an1",
             {"market_id": mid, "analysis_run_id": rid2,
              "window_start": "2026-01-01", "window_end": "2026-06-30"})
check("self-test 201", s == 201 and st["data"]["disclosure_status"] == "DISCLOSABLE", st)
stid = st["data"]["id"]
# closed-interval touching overlap
s, st2 = call("POST", "/fair-lending/self-tests", "FairLendingAnalyst", "an1",
              {"market_id": mid, "window_start": "2026-06-30", "window_end": "2026-12-31"})
check("self-test touch overlap 409", s == 409 and st2["data"]["error_id"] == "ERR_SELF_TEST_WINDOW_OVERLAP", st2)
s, dp = call("POST", "/fair-lending/self-tests/%s/designate-privileged" % stid, "ComplianceDirector", "cd1")
check("designate 200", s == 200 and dp["data"]["disclosure_status"] == "PRIVILEGED", dp)
# run2 lock+compute+finalize blocked by privilege gate
# need in-scope validated apps for Q2: a2 is FHA -> create CONVENTIONAL Q2 app
s, a3 = call("POST", "/fair-lending/applications", "LendingDataOps", "do1",
             {"market_id": mid, "branch_id": bid, "loan_officer_id": oid,
              "product_type": "CONVENTIONAL", "applicant_group": "CONTROL", "outcome": "ORIGINATED",
              "note_rate_bps": 410, "loan_amount_cents": 300000, "credit_score": 720,
              "dti_pct": 33.0, "application_date": "2026-04-05", "decision_date": "2026-05-10"})
a3id = a3["data"]["id"]
call("POST", "/fair-lending/applications/%s/validate" % a3id, "LendingDataOps", "do1")
call("POST", "/fair-lending/analysis-runs/%s/lock" % rid2, "FairLendingAnalyst", "an1")
s, c2 = call("POST", "/fair-lending/analysis-runs/%s/compute" % rid2, "FairLendingAnalyst", "an1")
check("run2 computed", s == 200 and c2["data"]["status"] == "COMPUTED", c2)
s, fg = call("POST", "/fair-lending/analysis-runs/%s/finalize" % rid2, "FairLendingOfficer", "of1")
check("privilege gate 409", s == 409 and fg["data"]["error_id"] == "ERR_PRIVILEGE_GATE", fg)
# close self-test NO_VIOLATION releases gate
call("POST", "/fair-lending/self-tests/%s/close" % stid, "FairLendingOfficer", "of1",
     {"outcome": "NO_VIOLATION"})
s, fg2 = call("POST", "/fair-lending/analysis-runs/%s/finalize" % rid2, "FairLendingOfficer", "of1")
check("finalize after close 200", s == 200 and fg2["data"]["status"] == "FINALIZED", fg2)

# --- board report ---
s, br = call("POST", "/fair-lending/board-reports", "FairLendingAnalyst", "an1",
             {"period_start": "2026-01-01", "period_end": "2026-04-01"})
check("report 201", s == 201 and br["data"]["status"] == "DRAFT", br)
brid = br["data"]["id"]
s, br2 = call("POST", "/fair-lending/board-reports", "FairLendingAnalyst", "an1",
              {"period_start": "2026-04-01", "period_end": "2026-09-30"})
check("not quarter 422", s == 422 and br2["data"]["error_id"] == "ERR_PERIOD_NOT_QUARTER", br2)
s, br3 = call("POST", "/fair-lending/board-reports", "FairLendingAnalyst", "an1",
              {"period_start": "2026-07-01", "period_end": "2026-10-01"})
check("period gap 409", s == 409 and br3["data"]["error_id"] == "ERR_PERIOD_GAP", br3)
s, rf = call("POST", "/fair-lending/board-reports/%s/refresh" % brid, "FairLendingAnalyst", "an1")
check("refresh 200 substantiated 1", s == 200 and rf["data"]["substantiated_finding_count"] == 1, rf["data"])
# submit by officer, approve by same -> SoD; approve by other director ok
s, sb = call("POST", "/fair-lending/board-reports/%s/submit" % brid, "FairLendingOfficer", "of1")
check("submit 200", s == 200 and sb["data"]["status"] == "SUBMITTED", sb)
s, apb = call("POST", "/fair-lending/board-reports/%s/approve" % brid, "ComplianceDirector", "of1")
check("report SoD 403", s == 403 and apb["data"]["error_id"] == "ERR_SOD_VIOLATION", apb)
s, apb = call("POST", "/fair-lending/board-reports/%s/approve" % brid, "ComplianceDirector", "cd1")
check("report approve 200", s == 200 and apb["data"]["status"] == "APPROVED", apb)
# publish blocked while the post-archive Q1 run is still DRAFT
s, pub0 = call("POST", "/fair-lending/board-reports/%s/publish" % brid, "ComplianceDirector", "cd1")
check("publish blocked 409", s == 409 and pub0["data"]["error_id"] == "ERR_REPORT_NOT_READY", pub0)
# drive the overlapping run to FINALIZED, then publish succeeds
call("POST", "/fair-lending/analysis-runs/%s/lock" % rid3, "FairLendingAnalyst", "an1")
call("POST", "/fair-lending/analysis-runs/%s/compute" % rid3, "FairLendingAnalyst", "an1")
s, f3 = call("POST", "/fair-lending/analysis-runs/%s/finalize" % rid3, "FairLendingOfficer", "of1")
check("rid3 finalize 200", s == 200, f3)
s, pub = call("POST", "/fair-lending/board-reports/%s/publish" % brid, "ComplianceDirector", "cd1")
check("publish 200", s == 200 and pub["data"]["status"] == "PUBLISHED", pub)

# --- monitoring cycle: expiry, overdue, privilege forfeiture ---
s, cyc = call("POST", "/fair-lending/monitoring/run-cycle", "ComplianceDirector", "cd1")
check("cycle 200", s == 200 and cyc["data"]["cycle_index"] == 1, cyc)
check("cycle lists", cyc["data"]["expired_exception_ids"] == [] and
      cyc["data"]["overdue_cap_ids"] == [], cyc["data"])

print()
if FAILS:
    print("FAILURES: %d" % len(FAILS))
    for f in FAILS:
        print(" -", f)
    raise SystemExit(1)
print("ALL FLOW CHECKS PASSED")
