"""Advance-care-planning billing claims (PRD 3.11)."""

from flask import Blueprint

import calc
import cascades
import config
from envelope import created, listing, ok
from errors import (
    ERR_ATTESTATION_REQUIRED, ERR_CONCURRENT_CARE_OVERLAP,
    ERR_INSUFFICIENT_DOCUMENTED_TIME, ERR_VALIDATION, api_error,
)
from ladder import (
    apply_filters, auth, field, fk, freeze_gate, pagination, paginate,
    path_row, query_filters, raw_body, state, touch, validate,
)
from store import ordered, store

bp = Blueprint("claims", __name__)


@bp.post("/palliative/claims")
def create_claim():
    auth([config.ROLE_BILLING, config.ROLE_ADMIN])
    body = raw_body()
    data = validate(body, [
        field("patient_id", "string", required=True),
        field("service_date", "datetime", required=True),
        field("documented_minutes", "integer", required=True, lo=0, hi=240),
        field("modality", "enum", required=True, enum=config.MODALITIES),
        field("conference_id", "string"),
        field("concurrent_care_carve_out", "boolean", default=False),
    ])
    patient = fk(store.patients, data["patient_id"])
    conference = fk(store.conferences, data["conference_id"])
    freeze_gate(patient)

    if data["documented_minutes"] < config.ACP_FIRST_UNIT_MIN_MINUTES:
        raise api_error(ERR_INSUFFICIENT_DOCUMENTED_TIME)

    carve_out = bool(data["concurrent_care_carve_out"])
    service_date = data["service_date"]
    for election in cascades.rows_for_patient(store.hospice_elections, patient["id"]):
        if election["status"] != "ELECTED":
            continue
        start, end = election["current_period_start"], election["current_period_end"]
        if start is None or end is None:
            continue
        if start <= service_date < end:
            if not (carve_out and election["concurrent_care_carve_out"]):
                raise api_error(ERR_CONCURRENT_CARE_OVERLAP)

    units = calc.acp_billable_units(data["documented_minutes"])
    allowed, modifier = calc.claim_allowed_amount_cents(
        units, data["modality"], patient["acp_paid_cents_ytd"])
    pct, responsibility, net = calc.claim_net_payable_cents(allowed)

    row = store.new_row({
        "patient_id": patient["id"],
        "conference_id": conference["id"] if conference else None,
        "service_date": service_date,
        "documented_minutes": data["documented_minutes"],
        "modality": data["modality"],
        "concurrent_care_carve_out": carve_out,
        "billable_units": units,
        "modifier_code": modifier,
        "allowed_amount_cents": allowed,
        "coinsurance_pct": pct,
        "patient_responsibility_cents": responsibility,
        "net_payable_cents": net,
        "documentation_attested": False,
        "attested_by_user_id": None,
        "denial_reason": None,
        "status": "DRAFT",
    })
    store.claims[row["id"]] = row
    return created(row)


@bp.post("/palliative/claims/<cid>/attest")
def attest_claim(cid):
    ctx = auth([config.ROLE_BILLING, config.ROLE_ADMIN])
    claim = path_row(store.claims, cid)
    body = raw_body()
    validate(body, [field("attestation_statement", "string", required=True)])
    # Permitted after a patient's death — no records-freeze gate here.
    state(claim["status"] in ("DRAFT", "DENIED"))
    if claim["conference_id"] is not None:
        conference = store.conferences.get(claim["conference_id"])
        if conference is None or not conference["attestation_complete"]:
            raise api_error(ERR_ATTESTATION_REQUIRED)
    claim["documentation_attested"] = True
    claim["attested_by_user_id"] = ctx.user_id
    claim["status"] = "ATTESTED"
    touch(claim)
    return ok(claim)


@bp.post("/palliative/claims/<cid>/submit")
def submit_claim(cid):
    auth([config.ROLE_BILLING, config.ROLE_ADMIN])
    claim = path_row(store.claims, cid)
    body = raw_body()
    validate(body, [field("submission_note", "string")])
    # Permitted after a patient's death — no records-freeze gate here.
    state(claim["status"] == "ATTESTED" and claim["documentation_attested"])
    claim["status"] = "SUBMITTED"
    touch(claim)
    patient = store.patients.get(claim["patient_id"])
    if patient is not None:
        cascades.recompute_claim_ledgers(patient)
    return ok(claim)


@bp.post("/palliative/claims/<cid>/adjudicate")
def adjudicate_claim(cid):
    auth([config.ROLE_ADMIN])
    claim = path_row(store.claims, cid)
    body = raw_body()
    data = validate(body, [
        field("outcome", "enum", required=True, enum=config.ADJUDICATION_OUTCOMES),
        field("denial_reason", "enum", enum=config.DENIAL_REASONS),
    ])
    if data["outcome"] == "DENIED" and data["denial_reason"] is None:
        raise api_error(ERR_VALIDATION, "denial_reason is required for a DENIED outcome.")
    # Permitted after a patient's death — no records-freeze gate here.
    state(claim["status"] == "SUBMITTED")

    if data["outcome"] == "PAID":
        claim["status"] = "PAID"
    else:
        claim["status"] = "DENIED"
        claim["denial_reason"] = data["denial_reason"]
        claim["documentation_attested"] = False
        claim["attested_by_user_id"] = None
    touch(claim)
    patient = store.patients.get(claim["patient_id"])
    if patient is not None:
        cascades.recompute_claim_ledgers(patient)
    return ok(claim)


@bp.get("/palliative/claims/<cid>")
def read_claim(cid):
    auth([config.ROLE_BILLING, config.ROLE_ADMIN])
    return ok(path_row(store.claims, cid))


@bp.get("/palliative/claims")
def list_claims():
    auth([config.ROLE_BILLING, config.ROLE_ADMIN])
    limit, offset = pagination()
    rows = apply_filters(ordered(store.claims.values()),
                         query_filters(["patient_id", "conference_id", "status"]))
    page, total = paginate(rows, limit, offset)
    return listing(page, limit, offset, total)
