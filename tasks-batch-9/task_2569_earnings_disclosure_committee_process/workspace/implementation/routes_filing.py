"""Filings, post-filing corrections and control deficiencies."""
from decimal import Decimal

from flask import Blueprint, request

import calc
from authz import ALL_ROLES, ROLE_COMPLIANCE_ADMIN, authorize, gate_action, require_action
from core import TouchLog, bad, dec, public, store, success_object
from helpers import apply_eq, paged, sort_created_asc
from validate import (
    as_bool,
    as_enum,
    as_number,
    as_string,
    body_of,
    enum_filter,
    opt_number,
    pagination,
    present,
    req_present,
    str_filter,
)

bp = Blueprint("filing", __name__)

FILING_STATUSES = ("SUBMITTED", "AMENDED_SUPERSEDED")
CORRECTION_STATUSES = ("DRAFT", "ASSESSED", "RESCINDED", "CLOSED")
CLASSIFICATIONS = ("IMMATERIAL", "REVISION", "RESTATEMENT")
DEFICIENCY_STATUSES = ("OPEN", "MITIGATED", "REVERSED")
SEVERITIES = ("DEFICIENCY", "SIGNIFICANT_DEFICIENCY", "MATERIAL_WEAKNESS")
CORRECTION_READ_ROLES = [
    "ComplianceAdmin",
    "DisclosureCommitteeChair",
    "Controller",
    "LegalCounsel",
    "CertifyingOfficer",
]


def _cycle_corrections(cycle):
    rows = []
    for filing in store.where("filing", cycle_id=cycle["id"]):
        rows.extend(store.where("correction", filing_id=filing["id"]))
    return rows


# -------------------------------------------------------------------- filings

@bp.get("/disclosure/filings")
def list_filings():
    authorize(request, ALL_ROLES)
    limit, offset = pagination(request.args)
    rows = store.all_rows("filing")
    rows = apply_eq(rows, "cycle_id", str_filter(request.args, "cycle_id"))
    rows = apply_eq(rows, "document_id", str_filter(request.args, "document_id"))
    rows = apply_eq(rows, "amends_filing_id", str_filter(request.args, "amends_filing_id"))
    rows = apply_eq(rows, "status", enum_filter(request.args, "status", FILING_STATUSES))
    return paged(sort_created_asc(rows), limit, offset)


@bp.get("/disclosure/filings/<filing_id>")
def get_filing(filing_id):
    authorize(request, ALL_ROLES)
    return success_object(public(store.must_get("filing", filing_id)))


@bp.post("/disclosure/filings")
def create_filing():
    authorize(request, [ROLE_COMPLIANCE_ADMIN])
    body = body_of(request)
    cycle = None
    document = None
    amended = None
    if present(body, "cycle_id"):
        cycle = store.must_get("cycle", body["cycle_id"])
    if present(body, "document_id"):
        document = store.must_get("document", body["document_id"])
    if present(body, "amends_filing_id"):
        amended = store.must_get("filing", body["amends_filing_id"])
    if cycle is None:
        req_present(body, "cycle_id")
    if document is None:
        req_present(body, "document_id")
    amending = amended is not None

    if cycle["status"] == "ABANDONED":
        bad("ERR_ENTITY_TERMINAL", "cycle is ABANDONED")
    if document["status"] in ("FILED", "SUPERSEDED"):
        bad("ERR_ENTITY_TERMINAL", "document is %s" % document["status"])
    if amending:
        if cycle["status"] not in ("FILED", "AMENDED"):
            bad("ERR_INVALID_STATE", "an amending filing requires a FILED or AMENDED cycle")
        if dec(cycle["unresolved_deficiency_weight"]) > Decimal("0.00"):
            bad("ERR_DEFICIENCY_OPEN", "the cycle carries unresolved deficiency weight")
    elif cycle["status"] != "FILING_READY":
        bad("ERR_INVALID_STATE", "an original filing requires a FILING_READY cycle")

    if (
        document["cycle_id"] != cycle["id"]
        or document["doc_type"] != "PERIODIC_FILING"
        or document["status"] != "APPROVED"
    ):
        bad(
            "ERR_FILING_DOCUMENT_INVALID",
            "document_id must name an APPROVED PERIODIC_FILING on the same cycle",
        )
    if amending and (amended["cycle_id"] != cycle["id"] or amended["status"] != "SUBMITTED"):
        bad(
            "ERR_AMENDMENT_TARGET_INVALID",
            "amends_filing_id must name a SUBMITTED filing on the same cycle",
        )
    if not calc.certifications_complete(cycle):
        bad(
            "ERR_CERTIFICATIONS_INCOMPLETE",
            "unsigned certifications: %s" % ", ".join(calc.unsigned_cert_types(cycle)),
        )

    log = TouchLog()
    filed_utc = store.clock.now_iso()
    accession_label = calc.filing_accession(cycle)
    late_flag = calc.parse_instant(filed_utc) > calc.parse_instant(cycle["statutory_deadline_utc"])
    row = store.new_row(
        "filing",
        {
            "cycle_id": cycle["id"],
            "document_id": document["id"],
            "amends_filing_id": amended["id"] if amending else None,
            "form_type": cycle["form_type"],
            "accession_label": accession_label,
            "filed_utc": filed_utc,
            "late_flag": late_flag,
            "status": "SUBMITTED",
        },
    )
    document["status"] = "FILED"
    log.touch(document)
    if amending:
        amended["status"] = "AMENDED_SUPERSEDED"
        log.touch(amended)
        cycle["status"] = "AMENDED"
    else:
        cycle["status"] = "FILED"
    log.touch(cycle)
    return success_object(public(row), 201)


# ---------------------------------------------------------------- corrections

@bp.get("/disclosure/corrections")
def list_corrections():
    authorize(request, CORRECTION_READ_ROLES)
    limit, offset = pagination(request.args)
    rows = store.all_rows("correction")
    rows = apply_eq(rows, "filing_id", str_filter(request.args, "filing_id"))
    rows = apply_eq(rows, "status", enum_filter(request.args, "status", CORRECTION_STATUSES))
    rows = apply_eq(
        rows, "classification", enum_filter(request.args, "classification", CLASSIFICATIONS)
    )
    return paged(sort_created_asc(rows), limit, offset)


@bp.get("/disclosure/corrections/<correction_id>")
def get_correction(correction_id):
    authorize(request, CORRECTION_READ_ROLES)
    return success_object(public(store.must_get("correction", correction_id)))


@bp.get("/disclosure/corrections/<correction_id>/control-deficiencies")
def list_deficiencies(correction_id):
    authorize(request, CORRECTION_READ_ROLES)
    limit, offset = pagination(request.args)
    store.must_get("correction", correction_id)
    rows = store.where("deficiency", correction_id=correction_id)
    rows = apply_eq(rows, "status", enum_filter(request.args, "status", DEFICIENCY_STATUSES))
    rows = apply_eq(rows, "severity", enum_filter(request.args, "severity", SEVERITIES))
    return paged(sort_created_asc(rows), limit, offset)


@bp.post("/disclosure/filings/<filing_id>/corrections")
def create_correction(filing_id):
    authorize(request, [ROLE_COMPLIANCE_ADMIN])
    filing = store.must_get("filing", filing_id)
    body = body_of(request)
    description = as_string(req_present(body, "description"), "description", 400)
    error_amount = as_number(req_present(body, "error_amount"), "error_amount")
    current_income = as_number(
        req_present(body, "current_period_pretax_income"), "current_period_pretax_income"
    )
    prior_income = as_number(
        req_present(body, "prior_period_pretax_income"), "prior_period_pretax_income"
    )
    if abs(dec(current_income)) <= Decimal("0"):
        bad("ERR_INVALID_REQUEST", "'current_period_pretax_income' must be non-zero")
    if abs(dec(prior_income)) <= Decimal("0"):
        bad("ERR_INVALID_REQUEST", "'prior_period_pretax_income' must be non-zero")
    cumulative = opt_number(body, "cumulative_prior_uncorrected_amount", 0)

    if filing["status"] == "AMENDED_SUPERSEDED":
        bad("ERR_ENTITY_TERMINAL", "the filing is AMENDED_SUPERSEDED")

    log = TouchLog()
    row = store.new_row(
        "correction",
        {
            "filing_id": filing["id"],
            "description": description,
            "error_amount": error_amount,
            "current_period_pretax_income": current_income,
            "prior_period_pretax_income": prior_income,
            "cumulative_prior_uncorrected_amount": cumulative,
            "method": None,
            "materiality_pct": None,
            "classification": None,
            "status": "DRAFT",
        },
    )
    cycle = store.get("cycle", filing["cycle_id"])
    if cycle is not None:
        if cycle["restatement_stage"] == "NONE":
            cycle["restatement_stage"] = "UNDER_EVALUATION"
        log.touch(cycle)
    return success_object(public(row), 201)


@bp.post("/disclosure/corrections/<correction_id>/transitions")
def transition_correction(correction_id):
    actor = authorize(request, [ROLE_COMPLIANCE_ADMIN])
    body = body_of(request)
    gate_action(actor, "correction", body)
    correction = store.must_get("correction", correction_id)
    action = require_action("correction", body)

    log = TouchLog()
    filing = store.get("filing", correction["filing_id"])
    cycle = store.get("cycle", filing["cycle_id"]) if filing is not None else None

    if action == "ASSESS":
        method = "ROLLOVER"
        if present(body, "method"):
            method = as_enum(body["method"], "method", ("ROLLOVER", "IRON_CURTAIN"))
        materiality_pct, classification = calc.correction_materiality(correction, method)
        likelihood_pct = None
        magnitude_amount = None
        compensating = None
        if classification in ("REVISION", "RESTATEMENT"):
            likelihood_pct = as_number(
                req_present(body, "likelihood_pct"), "likelihood_pct", minimum=0, maximum=100
            )
            magnitude_amount = as_number(
                req_present(body, "magnitude_amount"), "magnitude_amount", minimum=0
            )
            compensating = as_bool(
                req_present(body, "compensating_control_present"), "compensating_control_present"
            )

        if correction["status"] in ("RESCINDED", "CLOSED"):
            bad("ERR_ENTITY_TERMINAL", "the correction is %s" % correction["status"])
        if correction["status"] != "DRAFT":
            bad("ERR_INVALID_STATE", "ASSESS requires a DRAFT correction")

        correction["method"] = method
        correction["materiality_pct"] = materiality_pct
        correction["classification"] = classification
        correction["status"] = "ASSESSED"
        log.touch(correction)
        if classification in ("REVISION", "RESTATEMENT"):
            deficiency = store.new_row(
                "deficiency",
                {
                    "correction_id": correction["id"],
                    "likelihood_pct": likelihood_pct,
                    "magnitude_amount": magnitude_amount,
                    "compensating_control_present": compensating,
                    "severity_score": 0.0,
                    "severity": "DEFICIENCY",
                    "deficiency_weight": 0.0,
                    "status": "OPEN",
                    "remediation_note": None,
                },
            )
            calc.score_deficiency(deficiency, correction)
            if cycle is not None:
                calc.recompute_unresolved_deficiency_weight(cycle)
                if (
                    classification == "RESTATEMENT"
                    and dec(cycle["unresolved_deficiency_weight"]) > Decimal("0.00")
                    and cycle["restatement_stage"] == "UNDER_EVALUATION"
                ):
                    cycle["restatement_stage"] = "RESTATEMENT_DECLARED"
                log.touch(cycle)
        elif cycle is not None:
            log.touch(cycle)
        return success_object(public(correction))

    # RESCIND
    if correction["status"] in ("RESCINDED", "CLOSED"):
        bad("ERR_ENTITY_TERMINAL", "the correction is %s" % correction["status"])
    if correction["status"] != "ASSESSED":
        bad("ERR_INVALID_STATE", "RESCIND requires an ASSESSED correction")
    deficiencies = store.where("deficiency", correction_id=correction["id"])
    if any(d["status"] != "OPEN" for d in deficiencies):
        bad(
            "ERR_DEFICIENCY_ALREADY_MITIGATED",
            "a deficiency of this correction is no longer OPEN",
        )

    correction["status"] = "RESCINDED"
    correction["method"] = None
    correction["materiality_pct"] = None
    correction["classification"] = None
    log.touch(correction)
    for deficiency in deficiencies:
        if deficiency["status"] == "OPEN":
            deficiency["status"] = "REVERSED"
            log.touch(deficiency)
    if cycle is not None:
        calc.recompute_unresolved_deficiency_weight(cycle)
        siblings = _cycle_corrections(cycle)
        weight_clear = dec(cycle["unresolved_deficiency_weight"]) == Decimal("0.00")
        if (
            cycle["restatement_stage"] == "RESTATEMENT_DECLARED"
            and weight_clear
            and not any(c["status"] == "ASSESSED" for c in siblings)
        ):
            cycle["restatement_stage"] = "NONE"
        elif cycle["restatement_stage"] == "UNDER_EVALUATION" and not any(
            c["status"] in ("DRAFT", "ASSESSED") for c in siblings
        ):
            cycle["restatement_stage"] = "NONE"
        log.touch(cycle)
    return success_object(public(correction))


@bp.post("/disclosure/control-deficiencies/<deficiency_id>/mitigate")
def mitigate_deficiency(deficiency_id):
    authorize(request, [ROLE_COMPLIANCE_ADMIN])
    deficiency = store.must_get("deficiency", deficiency_id)
    body = body_of(request)
    remediation_note = as_string(req_present(body, "remediation_note"), "remediation_note", 2000)

    if deficiency["status"] != "OPEN":
        bad("ERR_DEFICIENCY_ALREADY_MITIGATED", "the deficiency is %s" % deficiency["status"])

    log = TouchLog()
    deficiency["status"] = "MITIGATED"
    deficiency["remediation_note"] = remediation_note
    log.touch(deficiency)
    correction = store.get("correction", deficiency["correction_id"])
    filing = store.get("filing", correction["filing_id"]) if correction is not None else None
    cycle = store.get("cycle", filing["cycle_id"]) if filing is not None else None
    if correction is not None:
        remaining = [
            d
            for d in store.where("deficiency", correction_id=correction["id"])
            if d["status"] == "OPEN"
        ]
        if not remaining and correction["status"] == "ASSESSED":
            correction["status"] = "CLOSED"
            log.touch(correction)
    if cycle is not None:
        calc.recompute_unresolved_deficiency_weight(cycle)
        siblings = _cycle_corrections(cycle)
        if (
            cycle["restatement_stage"] == "RESTATEMENT_DECLARED"
            and dec(cycle["unresolved_deficiency_weight"]) == Decimal("0.00")
            and any(c["status"] == "CLOSED" for c in siblings)
        ):
            cycle["restatement_stage"] = "REMEDIATED"
        log.touch(cycle)
    return success_object(public(deficiency))
