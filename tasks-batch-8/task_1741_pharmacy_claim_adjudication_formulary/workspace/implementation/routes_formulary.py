from flask import Blueprint, request

import db
from errors import ApiError
from middleware import require_roles
from response import ok, ok_list
from validation import (
    bad,
    body,
    is_int,
    is_num,
    opt_bool,
    opt_int,
    paginate,
    req_enum,
    req_int,
)

bp = Blueprint("formulary", __name__)

ALL_ROLES = ("PbmAdmin", "Pharmacist", "Member", "ClinicalReviewer", "Auditor")
UPDATABLE = (
    "tier",
    "pa_required",
    "step_therapy_required",
    "step_drug_id",
    "step_therapy_lookback_days",
    "quantity_limit_per_fill",
    "max_days_supply",
    "copay_type",
    "copay_flat_cents",
    "copay_percentage",
    "rebate_eligible",
)


def _existence_checks(b):
    """Pipeline stage 4: body FKs left to right (plan, drug, step drug)."""
    plan_id = b.get("plan_id")
    if plan_id is not None and plan_id not in db.plans:
        raise ApiError("ERR_PLAN_NOT_FOUND", "Plan not found", 404)
    drug_id = b.get("drug_id")
    if drug_id is not None and drug_id not in db.drugs:
        raise ApiError("ERR_DRUG_NOT_FOUND", "Drug not found", 404)
    step_drug_id = b.get("step_drug_id")
    if step_drug_id is not None and step_drug_id not in db.drugs:
        raise ApiError("ERR_DRUG_NOT_FOUND", "Step drug not found", 404)


def _validate_terms(plan_id, drug_id, tier, pa_required, step_therapy_required,
                    step_drug_id, lookback, qty_limit, max_days, copay_type,
                    copay_flat, copay_pct, rebate_eligible, creating):
    """Pipeline stage 7 shape rules for formulary terms (merged state on update)."""
    if not isinstance(tier, int) or isinstance(tier, bool) or not (1 <= tier <= 4):
        bad("Field 'tier' must be an integer in 1..4")
    if not isinstance(pa_required, bool):
        bad("Field 'pa_required' must be a boolean")
    if not isinstance(step_therapy_required, bool):
        bad("Field 'step_therapy_required' must be a boolean")
    if step_therapy_required:
        if step_drug_id is None:
            bad("Field 'step_drug_id' is required when step_therapy_required is true")
    else:
        if step_drug_id is not None:
            bad("Field 'step_drug_id' must be null when step_therapy_required is false")
    if not isinstance(lookback, int) or isinstance(lookback, bool) or lookback <= 0:
        bad("Field 'step_therapy_lookback_days' must be a positive integer")
    if not isinstance(qty_limit, int) or isinstance(qty_limit, bool) or qty_limit <= 0:
        bad("Field 'quantity_limit_per_fill' must be a positive integer")
    if not isinstance(max_days, int) or isinstance(max_days, bool) or max_days <= 0:
        bad("Field 'max_days_supply' must be a positive integer")
    if copay_type not in ("FLAT", "PERCENTAGE"):
        bad("Field 'copay_type' must be FLAT or PERCENTAGE")
    if copay_type == "FLAT":
        if copay_flat is None or not is_int(copay_flat) or copay_flat < 0:
            bad("Field 'copay_flat_cents' is required for copay_type FLAT and must be >= 0")
        if copay_pct is not None and (not is_num(copay_pct) or not (0 <= copay_pct <= 100)):
            bad("Field 'copay_percentage' must be in 0..100")
    else:
        if copay_pct is None or not is_num(copay_pct) or not (0 <= copay_pct <= 100):
            bad("Field 'copay_percentage' is required for copay_type PERCENTAGE and must be in 0..100")
        if copay_flat is not None and (not is_int(copay_flat) or copay_flat < 0):
            bad("Field 'copay_flat_cents' must be >= 0")
    if not isinstance(rebate_eligible, bool):
        bad("Field 'rebate_eligible' must be a boolean")


@bp.route("/formulary-entries", methods=["POST"])
def create_entry():
    require_roles("PbmAdmin")
    b = body()
    _existence_checks(b)
    plan_id = b.get("plan_id")
    if not isinstance(plan_id, str):
        bad("Field 'plan_id' is required and must be a string")
    drug_id = b.get("drug_id")
    if not isinstance(drug_id, str):
        bad("Field 'drug_id' is required and must be a string")
    step_drug_id = b.get("step_drug_id")
    if step_drug_id is not None and not isinstance(step_drug_id, str):
        bad("Field 'step_drug_id' must be a string or null")
    _validate_terms(
        plan_id=plan_id,
        drug_id=drug_id,
        tier=b.get("tier"),
        pa_required=opt_bool(b, "pa_required", default=False),
        step_therapy_required=opt_bool(b, "step_therapy_required", default=False),
        step_drug_id=step_drug_id,
        lookback=opt_int(b, "step_therapy_lookback_days", default=180),
        qty_limit=b.get("quantity_limit_per_fill"),
        max_days=b.get("max_days_supply"),
        copay_type=b.get("copay_type"),
        copay_flat=b.get("copay_flat_cents"),
        copay_pct=b.get("copay_percentage"),
        rebate_eligible=opt_bool(b, "rebate_eligible", default=False),
        creating=True,
    )
    # Pipeline stage 8: (plan_id, drug_id) unique across all statuses.
    if any(
        e["plan_id"] == plan_id and e["drug_id"] == drug_id
        for e in db.formulary_entries.values()
    ):
        raise ApiError(
            "ERR_DUPLICATE_FORMULARY_ENTRY",
            "A formulary entry already exists for this plan and drug",
            409,
        )
    rec = db.base_record()
    rec.update(
        {
            "plan_id": plan_id,
            "drug_id": drug_id,
            "tier": b["tier"],
            "pa_required": opt_bool(b, "pa_required", default=False),
            "step_therapy_required": opt_bool(b, "step_therapy_required", default=False),
            "step_drug_id": step_drug_id,
            "step_therapy_lookback_days": opt_int(b, "step_therapy_lookback_days", default=180),
            "quantity_limit_per_fill": b["quantity_limit_per_fill"],
            "max_days_supply": b["max_days_supply"],
            "copay_type": b["copay_type"],
            "copay_flat_cents": b.get("copay_flat_cents"),
            "copay_percentage": b.get("copay_percentage"),
            "rebate_eligible": opt_bool(b, "rebate_eligible", default=False),
            "status": "ACTIVE",
        }
    )
    db.formulary_entries[rec["id"]] = rec
    return ok(db.public(rec), 201)


@bp.route("/formulary-entries", methods=["GET"])
def list_entries():
    require_roles(*ALL_ROLES)
    rows = list(db.formulary_entries.values())
    plan_id = request.args.get("plan_id")
    drug_id = request.args.get("drug_id")
    step_drug_id = request.args.get("step_drug_id")
    if plan_id is not None:
        rows = [r for r in rows if r["plan_id"] == plan_id]
    if drug_id is not None:
        rows = [r for r in rows if r["drug_id"] == drug_id]
    if step_drug_id is not None:
        rows = [r for r in rows if r["step_drug_id"] == step_drug_id]
    page, limit, offset, total = paginate(rows)
    return ok_list(page, limit, offset, total)


def get_entry_or_404(entry_id):
    entry = db.formulary_entries.get(entry_id)
    if entry is None:
        raise ApiError("ERR_FORMULARY_ENTRY_NOT_FOUND", "Formulary entry not found", 404)
    return entry


@bp.route("/formulary-entries/<entry_id>", methods=["GET"])
def get_entry(entry_id):
    require_roles(*ALL_ROLES)
    return ok(db.public(get_entry_or_404(entry_id)), 200)


@bp.route("/formulary-entries/<entry_id>", methods=["PUT"])
def update_entry(entry_id):
    require_roles("PbmAdmin")
    entry = get_entry_or_404(entry_id)
    b = body()
    # Pipeline stage 4: step_drug_id FK existence when supplied non-null.
    if "step_drug_id" in b and b["step_drug_id"] is not None:
        if not isinstance(b["step_drug_id"], str):
            bad("Field 'step_drug_id' must be a string or null")
        if b["step_drug_id"] not in db.drugs:
            raise ApiError("ERR_DRUG_NOT_FOUND", "Step drug not found", 404)
    # Pipeline stage 6 (OCC) before stage 7 shape: the version field itself is
    # required, and a stale expectation fails here.
    if "expected_formulary_entry_version" not in b:
        bad("Field 'expected_formulary_entry_version' is required")
    expected = b["expected_formulary_entry_version"]
    if not is_int(expected):
        bad("Field 'expected_formulary_entry_version' must be an integer")
    if expected != entry["version"]:
        raise ApiError(
            "ERR_STALE_VERSION",
            "expected_formulary_entry_version does not match the stored version",
            412,
        )
    # Merge payload over stored values, then validate the resulting terms.
    merged = {k: b[k] if k in b else entry[k] for k in UPDATABLE}
    _validate_terms(
        plan_id=entry["plan_id"],
        drug_id=entry["drug_id"],
        tier=merged["tier"],
        pa_required=merged["pa_required"],
        step_therapy_required=merged["step_therapy_required"],
        step_drug_id=merged["step_drug_id"],
        lookback=merged["step_therapy_lookback_days"],
        qty_limit=merged["quantity_limit_per_fill"],
        max_days=merged["max_days_supply"],
        copay_type=merged["copay_type"],
        copay_flat=merged["copay_flat_cents"],
        copay_pct=merged["copay_percentage"],
        rebate_eligible=merged["rebate_eligible"],
        creating=False,
    )
    entry.update(merged)
    db.touch(entry)
    return ok(db.public(entry), 200)
