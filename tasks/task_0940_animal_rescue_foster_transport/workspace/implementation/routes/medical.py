"""Veterinary work, restricted funding draws and health certificates."""

from flask import Blueprint, request

import auth
import calc
import clock
import derive
import envelope
import gates
import services
from errors import ApiError
from routing import listing, must, query_filters, latch_all
from store import DB, touch
from validation import Field, parse_body

bp = Blueprint("medical", __name__)


@bp.post("/rescue/animals/<animal_id>/medical-records")
def order_procedure(animal_id):
    auth.authenticate(["PlatformAdmin", "Veterinarian"])
    body = parse_body(request, [
        Field("procedure_type", "string", required=True, enum="procedure_type"),
        Field("expense_category", "string", required=True, enum="expense_category"),
        Field("cost_cents", "integer", required=True, fmt="gte0"),
        Field("scheduled_at", "datetime", required=True),
        Field("funding_required", "boolean", default=False),
    ])
    animal = must("Animal", animal_id)
    gates.run_gates(gates.gate1_org_id(animal=animal), animal=animal, gate2=True)
    record = DB.insert("MedicalRecord", {
        "animal_id": animal["id"],
        "procedure_type": body["procedure_type"],
        "expense_category": body["expense_category"],
        "cost_cents": body["cost_cents"],
        "funding_required": body["funding_required"],
        "scheduled_at": body["scheduled_at"],          # (b) echoed byte-verbatim
        "completed_at": None,
        "status": "ORDERED",
        "funded_contribution_ids": [],
        "funded_amount_cents": 0,
        "admin_overhead_cents": 0,
    })
    return envelope.created(derive.medical_record(record))


@bp.get("/rescue/medical-records/<record_id>")
def read_medical_record(record_id):
    auth.authenticate(["PlatformAdmin", "Veterinarian", "FinanceOfficer"])
    return envelope.ok(derive.medical_record(must("MedicalRecord", record_id)))


@bp.get("/rescue/medical-records")
def list_medical_records():
    auth.authenticate(["PlatformAdmin", "Veterinarian", "FinanceOfficer"])
    return listing("MedicalRecord", DB.all("MedicalRecord"),
                   query_filters(["animal_id", "procedure_type", "status"]))


@bp.post("/rescue/medical-records/<record_id>/complete")
def complete_procedure(record_id):
    auth.authenticate(["PlatformAdmin", "Veterinarian"])
    body = parse_body(request, [Field("funding_contribution_ids", "array", default=None)])
    named = body["funding_contribution_ids"]
    if named is not None:
        for cid in named:
            if not isinstance(cid, str):
                raise ApiError("ERR_VALIDATION", "funding_contribution_ids must be strings.")
    record = must("MedicalRecord", record_id)
    named_rows = [must("Contribution", cid) for cid in (named or [])]
    animal = DB.get("Animal", record["animal_id"])
    # Completing an already-ordered record is NOT inside gate 2's scope.
    gates.check_gate1(gates.gate1_org_id(animal=animal))

    if record["status"] != "ORDERED":
        raise ApiError("ERR_INVALID_STATE", "The record is already COMPLETED.")

    # Rung 33: every explicitly named contribution must be category-eligible.
    # This sits ABOVE the sufficiency check, so an ineligible nomination reports
    # the mismatch rather than an insufficiency.
    for c in named_rows:
        eligible_category = (c["restriction_category"] == record["expense_category"]
                             or c["restriction_category"] == "UNRESTRICTED")
        wrong_animal = (c["designated_animal_id"] is not None
                        and c["designated_animal_id"] != record["animal_id"])
        if not eligible_category or wrong_animal:
            raise ApiError("ERR_RESTRICTED_FUND_CATEGORY_MISMATCH",
                           "A named contribution is not eligible to fund this record.")

    drawn_lines = []
    overhead = 0
    if record["funding_required"]:
        pool = calc.medical_eligible_pool(record, named if named is not None else None)
        # Rung 45: the eligible pool must cover cost_cents IN FULL.  There are no
        # partial draws and no partial completions.
        if sum(derive.available_cents(c) for c in pool) < record["cost_cents"]:
            raise ApiError("ERR_INSUFFICIENT_RESTRICTED_FUNDS",
                           "The eligible contribution pool does not cover the cost.")
        remaining = record["cost_cents"]
        for c in pool:
            if remaining <= 0:
                break
            line = min(derive.available_cents(c), remaining)
            if line <= 0:
                continue
            services.draw_contribution(c, line)
            remaining -= line
            # ROUNDING ORDER IS PINNED: overhead is rounded per draw line and
            # only then summed.
            overhead += calc.medical_admin_overhead(line)
            drawn_lines.append(c["id"])

    record["status"] = "COMPLETED"
    record["completed_at"] = clock.stamp()             # (c) clock-derived
    if record["funding_required"]:
        record["funded_contribution_ids"] = drawn_lines
        record["funded_amount_cents"] = record["cost_cents"]
        record["admin_overhead_cents"] = overhead
    touch(record)

    if animal is not None:
        if record["procedure_type"] == "SPAY_NEUTER":
            animal["alteration_status"] = "ALTERED"
        if record["procedure_type"] == "VACCINE_RABIES":
            animal["rabies_vaccinated_at"] = record["completed_at"]
        touch(animal)
    # The organization's balances are derived roll-ups, so the unfunded cost and
    # the per-line overhead land on unrestricted_balance_cents by derivation.
    return envelope.ok(derive.medical_record(record))


# =====================================================================
#  Health certificates
# =====================================================================

@bp.post("/rescue/animals/<animal_id>/health-certificates")
def issue_certificate(animal_id):
    auth.authenticate(["PlatformAdmin", "Veterinarian"])
    body = parse_body(request, [
        Field("issued_at", "datetime", required=True),
        Field("destination_state", "string", required=True, fmt="state"),
        Field("vet_license_number", "string", required=True),
    ])
    animal = must("Animal", animal_id)
    gates.run_gates(gates.gate1_org_id(animal=animal), animal=animal, gate2=True)
    window = calc.cvi_window_days(animal["species"])
    issued_raw = body["issued_at"]
    cert = DB.insert("HealthCertificate", {
        "animal_id": animal["id"],
        "issued_at": issued_raw,                       # (b) echoed byte-verbatim
        "destination_state": body["destination_state"],
        "vet_license_number": body["vet_license_number"],
        "window_days": window,
        # (c) derived instant, rendered in the style of issued_at
        "expires_at": clock.derive(clock.plus_days(clock.parse(issued_raw), window), issued_raw),
        "status": "VALID",
    })
    derive.expire_certificate(cert)
    return envelope.created(derive.health_certificate(cert))


@bp.get("/rescue/health-certificates/<cert_id>")
def read_certificate(cert_id):
    auth.authenticate(["PlatformAdmin", "Veterinarian", "TransportDispatcher", "Driver"])
    return envelope.ok(derive.health_certificate(must("HealthCertificate", cert_id)))


@bp.get("/rescue/health-certificates")
def list_certificates():
    auth.authenticate(["PlatformAdmin", "Veterinarian", "TransportDispatcher", "Driver"])
    rows = latch_all("HealthCertificate")
    return listing("HealthCertificate", rows,
                   query_filters(["animal_id", "status", "destination_state"]))
