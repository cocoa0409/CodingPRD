"""Questionnaires and control assessments (PRD 3.4)."""

from decimal import Decimal

from flask import Blueprint

import auth
import calc
import cascade
import clock
import store
from common import (ALL, arg, eq, list_scope, need, need_respondent, paged,
                    respondent_of, scoped_child, start, PREFIX)
from errors import fail
from response import ok, ok_list
from validate import body, fbool, fenum, fint, fstr, validate

bp = Blueprint("questionnaires", __name__)

OPEN_STATES = ("DRAFT", "SUBMITTED", "UNDER_ASSESSMENT", "RETURNED_FOR_CLARIFICATION")
GAPS = ("NONE", "MINOR", "MAJOR", "CRITICAL")
VARIANTS = ("ONBOARDING_PROVISIONAL", "REFRESH_FINAL")
SUBMIT_STATES = ("PROSPECT", "DD_IN_PROGRESS", "PENDING_COMMITTEE", "APPROVED",
                 "REFRESH_DUE", "UNDER_REFRESH", "REFRESH_OVERDUE", "RESTRICTED")
VARIANT_STATES = {
    "ONBOARDING_PROVISIONAL": ("PROSPECT", "DD_IN_PROGRESS", "PENDING_COMMITTEE"),
    "REFRESH_FINAL": ("APPROVED", "REFRESH_DUE", "UNDER_REFRESH",
                      "REFRESH_OVERDUE", "RESTRICTED"),
}


@bp.post(PREFIX + "/respondents/<respondent_id>/questionnaires")
def create_questionnaire(respondent_id):
    start(("RespondentContact", "ComplianceAnalyst"), respondent_id)
    resp = need_respondent(respondent_id)
    data = body()
    validate(data, [
        fstr("questionnaire_version", True, 1, 40),
        fint("expected_respondent_version", True, 0),
        fbool("declared_nested_activity", False),
        fint("declared_downstream_count", False, 0),
    ])
    if int(data["expected_respondent_version"]) != int(resp["version"]):
        fail("ERR_STALE_RESPONDENT_VERSION",
             "expected_respondent_version does not match the respondent version.")
    cascade.guard_not_closed(resp)
    for row in store.questionnaires_of(resp["id"]):
        if row["state"] in OPEN_STATES or row["state"] == "ASSESSED":
            row["state"] = "SUPERSEDED"
            store.touch(row)
    new_row = store.insert("questionnaires", {
        "respondent_bank_id": resp["id"],
        "questionnaire_version": data["questionnaire_version"],
        "state": "DRAFT",
        "submitted_at": None,
        "assessed_at": None,
        "assessed_by_user_id": None,
        "clarification_rounds": 0,
        "declared_nested_activity": bool(data.get("declared_nested_activity", False)),
        "declared_downstream_count": int(data.get("declared_downstream_count") or 0),
        "computed_control_score": None,
        "control_score_variant": "NONE",
    })
    store.touch(resp)
    return ok(new_row, 201)


@bp.get(PREFIX + "/questionnaires")
def list_questionnaires():
    ctx = start(ALL)
    scope_id = list_scope(ctx)
    rows = store.all_rows("questionnaires")
    rows = eq(rows, "respondent_bank_id", scope_id)
    rows = eq(rows, "state", arg("state"))
    rows.sort(key=lambda r: r["_seq"])
    rows.sort(key=lambda r: r["questionnaire_version"], reverse=True)
    page, limit, offset, total = paged(rows)
    return ok_list(page, limit, offset, total)


@bp.get(PREFIX + "/questionnaires/<questionnaire_id>")
def read_questionnaire(questionnaire_id):
    ctx = start(ALL)
    return ok(scoped_child("questionnaires", questionnaire_id, ctx))


@bp.post(PREFIX + "/questionnaires/<questionnaire_id>/submission")
def submit(questionnaire_id):
    ctx = start(("RespondentContact",))
    row = scoped_child("questionnaires", questionnaire_id, ctx)
    resp = store.get("respondents", row["respondent_bank_id"])
    if resp["dd_state"] not in SUBMIT_STATES:
        fail("ERR_INVALID_RESPONDENT_STATE",
             "The respondent's dd_state does not permit a submission.")
    cascade.guard_not_closed(resp)
    if row["state"] not in ("DRAFT", "RETURNED_FOR_CLARIFICATION"):
        fail("ERR_INVALID_QUESTIONNAIRE_STATE",
             "Only a draft or returned questionnaire may be submitted.")
    if int(row["declared_downstream_count"]) != 0 and not row["declared_nested_activity"]:
        fail("ERR_INVALID_QUESTIONNAIRE_STATE",
             "A declared downstream count requires declared_nested_activity true.")
    _require_all_domains(row)
    row["state"] = "SUBMITTED"
    store.set_dt(row, "submitted_at", clock.now())
    store.touch(row)
    return ok(row)


def _require_all_domains(questionnaire):
    present = {r["control_domain"] for r in store.controls_of(questionnaire["id"])}
    for domain in calc.CONTROL_DOMAINS:
        if domain not in present:
            fail("ERR_CONTROL_DOMAINS_INCOMPLETE",
                 "Control domain %s has no assessment row." % domain)


@bp.post(PREFIX + "/questionnaires/<questionnaire_id>/assessment-decision")
def assessment_decision(questionnaire_id):
    ctx = start(("ComplianceAnalyst",))
    row = need("questionnaires", questionnaire_id)
    data = body()
    validate(data, [
        fenum("action", ("ASSESS", "RETURN"), True),
        fenum("variant", VARIANTS, False),
        fstr("clarification_note", False, 0, 2000),
    ])
    resp = store.get("respondents", row["respondent_bank_id"])
    if data["action"] == "ASSESS":
        variant = data.get("variant")
        if variant is None:
            fail("ERR_INVALID_REQUEST_BODY", "variant is required to assess.")
        if resp["dd_state"] not in VARIANT_STATES[variant]:
            fail("ERR_INVALID_RESPONDENT_STATE",
                 "Variant %s is not permitted while dd_state is %s."
                 % (variant, resp["dd_state"]))
        cascade.guard_not_closed(resp)
        if row["state"] not in ("SUBMITTED", "UNDER_ASSESSMENT"):
            fail("ERR_INVALID_QUESTIONNAIRE_STATE",
                 "Only a submitted questionnaire may be assessed.")
        _require_all_domains(row)
        rows = {r["control_domain"]: r for r in store.controls_of(row["id"])}
        # §2.9 priority 33: a questionnaire "may only be assessed under the
        # refresh-final variant when every row carries an assessed_rating".  Under
        # ONBOARDING_PROVISIONAL a null assessed_rating is legal and credits the
        # row's self_rating instead (§3.4).
        if variant == "REFRESH_FINAL":
            for domain in calc.CONTROL_DOMAINS:
                if rows[domain].get("assessed_rating") is None:
                    fail("ERR_CONTROL_DOMAINS_INCOMPLETE",
                         "Control domain %s carries no assessed_rating." % domain)
        if row["declared_nested_activity"]:
            nested_row = rows["NESTED_CONTROLS"]
            if nested_row.get("assessed_rating") is None \
                    or int(nested_row["assessed_rating"]) < 2:
                fail("ERR_CONTROL_DOMAINS_INCOMPLETE",
                     "Declared nested activity requires a NESTED_CONTROLS rating of at "
                     "least 2.")
        if ctx.user_id == resp["id"]:
            fail("ERR_SEGREGATION_OF_DUTIES",
                 "The assessor may not be the respondent itself.")
        score = calc.control_score(row, variant)
        row["computed_control_score"] = score
        row["control_score_variant"] = variant
        row["assessed_by_user_id"] = ctx.user_id
        store.set_dt(row, "assessed_at", clock.now())
        row["state"] = "ASSESSED"
        store.touch(row)
        resp["control_score"] = score
        store.touch(resp)
    else:
        cascade.guard_not_closed(resp)
        if row["state"] != "UNDER_ASSESSMENT":
            fail("ERR_INVALID_QUESTIONNAIRE_STATE",
                 "Only a questionnaire under assessment may be returned.")
        if int(row["clarification_rounds"]) > 2:
            fail("ERR_ROUNDS_EXHAUSTED", "The clarification budget is exhausted.")
        rows = store.controls_of(row["id"])
        substantive = any(r["gap_severity"] in ("MAJOR", "CRITICAL")
                          or r.get("assessed_rating") is None for r in rows)
        if not substantive:
            fail("ERR_INVALID_QUESTIONNAIRE_STATE",
                 "A return requires a material gap or a missing assessed rating.")
        row["clarification_rounds"] = int(row["clarification_rounds"]) + 1
        row["state"] = "RETURNED_FOR_CLARIFICATION"
        store.touch(row)
    return ok(row)


# ------------------------------------------------------ control assessments ---

@bp.post(PREFIX + "/questionnaires/<questionnaire_id>/control-assessments")
def create_control(questionnaire_id):
    ctx = start(("RespondentContact", "ComplianceAnalyst"))
    parent = scoped_child("questionnaires", questionnaire_id, ctx)
    data = body()
    validate(data, [
        fenum("control_domain", calc.CONTROL_DOMAINS, True),
        fint("self_rating", True, 1, 5),
        fstr("evidence_note", False, 0, 500),
    ])
    resp = store.get("respondents", parent["respondent_bank_id"])
    cascade.guard_not_closed(resp)
    promote = False
    if parent["state"] in ("DRAFT", "RETURNED_FOR_CLARIFICATION"):
        pass
    elif parent["state"] == "SUBMITTED" and ctx.role == "ComplianceAnalyst":
        promote = True
    else:
        fail("ERR_INVALID_QUESTIONNAIRE_STATE",
             "This questionnaire state accepts no new control-assessment row.")
    for row in store.controls_of(parent["id"]):
        if row["control_domain"] == data["control_domain"]:
            fail("ERR_DUPLICATE_RESOURCE",
                 "Control domain %s already has a row." % data["control_domain"])
    row = store.insert("control_assessments", {
        "questionnaire_id": parent["id"],
        "control_domain": data["control_domain"],
        "self_rating": int(data["self_rating"]),
        "assessed_rating": None,
        "domain_weight": calc.DOMAIN_WEIGHTS[data["control_domain"]].quantize(
            Decimal("0.0001")),
        "gap_severity": "NONE",
        "remediation_required": False,
        "evidence_note": data.get("evidence_note") or "",
    })
    if promote:
        parent["state"] = "UNDER_ASSESSMENT"
        store.touch(parent)
    return ok(row, 201)


@bp.get(PREFIX + "/control-assessments")
def list_controls():
    ctx = start(ALL)
    rows = store.all_rows("control_assessments")
    if ctx.is_contact:
        mine = {q["id"] for q in store.questionnaires_of(ctx.user_id)}
        rows = [r for r in rows if r["questionnaire_id"] in mine]
    rows = eq(rows, "questionnaire_id", arg("questionnaire_id"))
    rows = eq(rows, "control_domain", arg("control_domain"))
    rows = eq(rows, "gap_severity", arg("gap_severity"))
    order = {domain: index for index, domain in enumerate(calc.CONTROL_DOMAINS)}
    rows.sort(key=lambda r: (order.get(r["control_domain"], 99), r["_seq"]))
    page, limit, offset, total = paged(rows)
    return ok_list(page, limit, offset, total)


@bp.get(PREFIX + "/control-assessments/<control_id>")
def read_control(control_id):
    ctx = start(ALL)
    return ok(scoped_child("control_assessments", control_id, ctx))


@bp.patch(PREFIX + "/control-assessments/<control_id>")
def overlay_control(control_id):
    start(("ComplianceAnalyst",))
    row = need("control_assessments", control_id)
    data = body()
    validate(data, [
        fint("assessed_rating", False, 1, 5),
        fenum("gap_severity", GAPS, False),
        fbool("remediation_required", False),
        fstr("evidence_note", False, 0, 500),
    ])
    parent = store.get("questionnaires", row["questionnaire_id"])
    resp = store.get("respondents", parent["respondent_bank_id"])
    cascade.guard_not_closed(resp)
    if parent["state"] not in ("SUBMITTED", "UNDER_ASSESSMENT",
                              "RETURNED_FOR_CLARIFICATION"):
        fail("ERR_INVALID_QUESTIONNAIRE_STATE",
             "This questionnaire state accepts no assessor overlay.")
    if data.get("assessed_rating") is not None:
        row["assessed_rating"] = int(data["assessed_rating"])
    if data.get("remediation_required") is not None:
        row["remediation_required"] = bool(data["remediation_required"])
    if data.get("gap_severity") is not None:
        row["gap_severity"] = data["gap_severity"]
        if data["gap_severity"] in ("MAJOR", "CRITICAL"):
            row["remediation_required"] = True
    if data.get("evidence_note") is not None:
        row["evidence_note"] = data["evidence_note"]
    store.touch(row)
    if parent["state"] == "SUBMITTED":
        parent["state"] = "UNDER_ASSESSMENT"
        store.touch(parent)
    return ok(row)
