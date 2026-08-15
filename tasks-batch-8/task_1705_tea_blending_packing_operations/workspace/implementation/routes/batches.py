"""Blend batches: recipe lock, allocation, blending, flavoring, QC, release,
cancel, recall (PRD 3.4, 3.5)."""
from decimal import Decimal

from flask import Blueprint, request

import store
from auth import ALL_ROLES, authenticate, authorize
from errors import (
    ERR_ALLOCATION_GRADE_TOO_LOW,
    ERR_ALLOCATION_TYPE_MISMATCH,
    ERR_ALREADY_TERMINAL,
    ERR_BATCH_NOT_FLAVORABLE,
    ERR_BATCH_NOT_RELEASABLE,
    ERR_CERT_NOT_ACTIVE,
    ERR_CERT_VOLUME_EXHAUSTED,
    ERR_DUPLICATE_LOT_ALLOCATION,
    ERR_FILL_INCOMPLETE,
    ERR_FLAVORING_DOSE_MISMATCH,
    ERR_FLAVORING_MISMATCH,
    ERR_FLAVORING_NOT_ACTIVE,
    ERR_FLAVORING_REQUIRED,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_LOT_NOT_RELEASED,
    ERR_LOT_WEIGHT_EXCEEDED,
    ERR_MOISTURE_OUT_OF_RANGE,
    ERR_RECIPE_NOT_ACTIVE,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_SINGLE_LOT_DOMINANCE,
    ERR_STALE_VERSION,
    ERR_SYNTHETIC_ON_ORGANIC,
    raise_err,
)
from services import (
    BATCH_CANCELLABLE_STATES,
    BATCH_TERMINAL_STATES,
    RELEASE_MOISTURE_GATE_PCT,
    active_allocations_of_batch,
    allocation_out,
    batch_out,
    cancel_scheduled_runs_of_batch,
    compute_final_cost_cents,
    compute_line_cost_cents,
    compute_provisional_cost_cents,
    compute_recipe_scaling,
    compute_yield_kg,
    find_valid_cert,
    flavoring_application_out,
    flavoring_applications_of_batch,
    grade_meets,
    release_batch_allocations,
    supplier_contributions,
)
from util import (
    body_json, bump, get_or_404, list_response, new_immutable_record,
    new_record, req_num, round3, success_object,
)

bp = Blueprint("batches", __name__)


def _batch_or_404(bid):
    return get_or_404(store.batches, bid, "BlendBatch")


def _guard_batch_terminal(batch):
    if batch["status"] in BATCH_TERMINAL_STATES:
        raise_err(
            ERR_ALREADY_TERMINAL,
            "BlendBatch %s is in terminal state %s" % (batch["id"], batch["status"]),
        )


def _recipe_of(batch):
    return store.recipes.get(batch["recipe_id"])


@bp.route("/tea-ops/batches", methods=["POST"])
def create_batch():
    _, role = authenticate()
    authorize(role, ["BlendMaster"])
    body = body_json()
    # Priority 3: body FK resolution when present.
    recipe_id = body.get("recipe_id")
    recipe = None
    if recipe_id is not None:
        recipe = get_or_404(store.recipes, recipe_id, "BlendRecipe")
    # Priority 6: the named recipe must be ACTIVE.
    if recipe is not None and recipe["status"] != "ACTIVE":
        raise_err(ERR_RECIPE_NOT_ACTIVE, "Referenced recipe is not ACTIVE")
    # Priority 13: field shape.
    if not isinstance(recipe_id, str) or not recipe_id:
        raise_err(ERR_INVALID_REQUEST, "recipe_id is required and must be a string")
    target_weight_kg = req_num(body, "target_weight_kg")
    if target_weight_kg <= 0:
        raise_err(ERR_INVALID_REQUEST, "target_weight_kg must be strictly positive")

    rec = new_record()
    rec.update({
        "recipe_id": recipe["id"],
        "recipe_version": None,
        "pack_format": recipe["pack_format"],
        "target_weight_kg": target_weight_kg,
        "required_components": None,
        "flavoring_kg": None,
        "allergen_tags": [],
        "measured_moisture_pct": None,
        "yield_kg": None,
        "blended_by_user_id": None,
        "provisional_cost_cents": None,
        "final_cost_cents": None,
        "actual_weight_kg": None,
        "cert_charges": [],
        "status": "DRAFT",
        "_ever_released": False,
    })
    store.batches[rec["id"]] = rec
    return success_object(batch_out(rec), 201)


@bp.route("/tea-ops/batches/<bid>", methods=["GET"])
def get_batch(bid):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    return success_object(batch_out(_batch_or_404(bid)))


@bp.route("/tea-ops/batches", methods=["GET"])
def list_batches():
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    records = list(store.batches.values())
    recipe_id = request.args.get("recipe_id")
    status = request.args.get("status")
    if recipe_id is not None:
        records = [r for r in records if r["recipe_id"] == recipe_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    return list_response(records, batch_out)


@bp.route("/tea-ops/batches/<bid>/lock-recipe", methods=["POST"])
def lock_recipe(bid):
    _, role = authenticate()
    authorize(role, ["BlendMaster"])
    batch = _batch_or_404(bid)
    _guard_batch_terminal(batch)
    if batch["status"] != "DRAFT":
        raise_err(ERR_INVALID_STATE, "Batch is not DRAFT")
    recipe = _recipe_of(batch)
    if recipe is None or recipe["status"] != "ACTIVE":
        raise_err(ERR_RECIPE_NOT_ACTIVE, "Referenced recipe is not ACTIVE")

    # recipe_component_scaling: flavoring reserved BEFORE leaf normalization.
    required, flavoring_kg = compute_recipe_scaling(
        batch["target_weight_kg"], recipe["components"], recipe["flavoring_pct"]
    )
    batch["recipe_version"] = recipe["version"]
    batch["required_components"] = required
    batch["flavoring_kg"] = flavoring_kg
    batch["status"] = "RECIPE_LOCKED"
    bump(batch)
    return success_object(batch_out(batch))


@bp.route("/tea-ops/batches/<bid>/allocations", methods=["POST"])
def create_allocation(bid):
    _, role = authenticate()
    authorize(role, ["BlendMaster"])
    batch = _batch_or_404(bid)
    body = body_json()
    # Priority 3: body FK resolution.
    lot_id = body.get("lot_id")
    lot = None
    if lot_id is not None:
        lot = get_or_404(store.leaf_lots, lot_id, "LeafLot")
    # Priority 4: OCC on the batch version (PRD 2.7).
    expected = body.get("expected_batch_version")
    if isinstance(expected, int) and not isinstance(expected, bool):
        if expected != batch["version"]:
            raise_err(
                ERR_STALE_VERSION,
                "expected_batch_version does not match the current version",
            )
    # Priority 5: terminal guard.
    _guard_batch_terminal(batch)
    # Priority 6: allocation window is between recipe lock and finalization;
    # the lot must currently be RELEASED.
    if batch["status"] != "RECIPE_LOCKED":
        raise_err(
            ERR_INVALID_STATE,
            "Allocations require the batch in RECIPE_LOCKED",
        )
    if lot is not None and lot["status"] != "RELEASED":
        raise_err(ERR_LOT_NOT_RELEASED, "Allocated lot is not RELEASED")
    # Priority 13: field shape.
    if not isinstance(lot_id, str) or not lot_id:
        raise_err(ERR_INVALID_REQUEST, "lot_id is required and must be a string")
    allocated_kg = req_num(body, "allocated_kg")
    if allocated_kg <= 0:
        raise_err(ERR_INVALID_REQUEST, "allocated_kg must be strictly positive")
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise_err(
            ERR_INVALID_REQUEST,
            "expected_batch_version is required and must be an integer",
        )
    # Priority 10 (PRD 3.4 order): remaining weight, leaf-type match, grade
    # minimum, duplicate lot.
    if allocated_kg > lot["remaining_weight_kg"]:
        raise_err(
            ERR_LOT_WEIGHT_EXCEEDED,
            "allocated_kg exceeds the lot's remaining_weight_kg",
        )
    recipe = _recipe_of(batch)
    matching = [c for c in (recipe["components"] if recipe else [])
                if c["leaf_type"] == lot["leaf_type"]]
    if not matching:
        raise_err(
            ERR_ALLOCATION_TYPE_MISMATCH,
            "Lot leaf_type matches no recipe component",
        )
    if not any(grade_meets(lot["composite_grade"], c["min_grade"]) for c in matching):
        raise_err(
            ERR_ALLOCATION_GRADE_TOO_LOW,
            "Lot composite_grade below the matched component's min_grade",
        )
    for a in active_allocations_of_batch(batch["id"]):
        if a["lot_id"] == lot["id"]:
            raise_err(
                ERR_DUPLICATE_LOT_ALLOCATION,
                "Lot already has an ACTIVE allocation in this batch",
            )

    rec = new_record()
    rec.update({
        "batch_id": batch["id"],
        "lot_id": lot["id"],
        "allocated_kg": allocated_kg,
        "line_cost_cents": compute_line_cost_cents(
            allocated_kg, lot["cost_per_kg_cents"]
        ),
        "status": "ACTIVE",
    })
    store.allocations[rec["id"]] = rec

    lot["remaining_weight_kg"] = lot["remaining_weight_kg"] - allocated_kg
    if lot["remaining_weight_kg"] == 0:
        # System auto-transition: RELEASED -> DEPLETED at exactly zero.
        lot["status"] = "DEPLETED"
    bump(lot)
    bump(batch)
    return success_object(allocation_out(rec), 201)


@bp.route("/tea-ops/batches/<bid>/allocations", methods=["GET"])
def list_batch_allocations(bid):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    batch = _batch_or_404(bid)
    records = [a for a in store.allocations.values() if a["batch_id"] == batch["id"]]
    return list_response(records, allocation_out)


@bp.route("/tea-ops/batches/<bid>/finalize-allocation", methods=["POST"])
def finalize_allocation(bid):
    _, role = authenticate()
    authorize(role, ["BlendMaster"])
    batch = _batch_or_404(bid)
    _guard_batch_terminal(batch)
    if batch["status"] != "RECIPE_LOCKED":
        raise_err(ERR_INVALID_STATE, "Batch is not RECIPE_LOCKED")

    allocations = active_allocations_of_batch(batch["id"])
    components = batch["required_components"] or []

    # Exact fill per component (3-decimal comparison).
    component_fill = []
    for comp in components:
        covered = Decimal("0")
        contributing = []
        for a in allocations:
            lot = store.leaf_lots[a["lot_id"]]
            if lot["leaf_type"] != comp["leaf_type"]:
                continue
            if not grade_meets(lot["composite_grade"], comp["min_grade"]):
                continue
            covered += a["allocated_kg"]
            contributing.append(a)
        if round3(covered) != round3(comp["required_kg"]):
            raise_err(
                ERR_FILL_INCOMPLETE,
                "Component %s allocated total != required_kg exactly"
                % comp["leaf_type"],
            )
        component_fill.append((comp, contributing))

    # Single-lot dominance ceiling for components over 25.0 kg.
    for comp, contributing in component_fill:
        if comp["required_kg"] > Decimal("25.0"):
            for a in contributing:
                # share > 0.70 violates; exactly 0.70 is allowed.
                if a["allocated_kg"] * 100 > comp["required_kg"] * 70:
                    raise_err(
                        ERR_SINGLE_LOT_DOMINANCE,
                        "One lot supplies over 70 percent of component %s"
                        % comp["leaf_type"],
                    )

    # Every allocated lot must currently be RELEASED or DEPLETED.
    for a in allocations:
        lot = store.leaf_lots[a["lot_id"]]
        if lot["status"] not in ("RELEASED", "DEPLETED"):
            raise_err(
                ERR_INVALID_STATE,
                "Allocated lot %s is not RELEASED or DEPLETED" % lot["id"],
            )

    batch["provisional_cost_cents"] = compute_provisional_cost_cents(batch["id"])
    batch["status"] = "ALLOCATED"
    bump(batch)
    return success_object(batch_out(batch))


@bp.route("/tea-ops/batches/<bid>/blend", methods=["POST"])
def blend_batch(bid):
    uid, role = authenticate()
    authorize(role, ["BlendMaster"])
    batch = _batch_or_404(bid)
    _guard_batch_terminal(batch)
    if batch["status"] != "ALLOCATED":
        raise_err(ERR_INVALID_STATE, "Batch is not ALLOCATED")
    body = body_json()
    measured = req_num(body, "measured_moisture_pct")
    if measured <= 0 or measured > 100:
        raise_err(ERR_INVALID_REQUEST, "measured_moisture_pct must be > 0 and <= 100")

    batch["measured_moisture_pct"] = measured
    batch["yield_kg"] = compute_yield_kg(batch["id"])
    batch["blended_by_user_id"] = uid
    batch["status"] = "BLENDED"
    bump(batch)
    return success_object(batch_out(batch))


@bp.route("/tea-ops/batches/<bid>/apply-flavoring", methods=["POST"])
def apply_flavoring(bid):
    uid, role = authenticate()
    authorize(role, ["BlendMaster"])
    batch = _batch_or_404(bid)
    body = body_json()
    # Priority 3: body FK resolution.
    flavoring_id = body.get("flavoring_id")
    flavoring = None
    if flavoring_id is not None:
        flavoring = get_or_404(store.flavorings, flavoring_id, "Flavoring")
    # Priority 5: terminal guard.
    _guard_batch_terminal(batch)
    # Priority 6: batch must be BLENDED under a flavored recipe.
    recipe = _recipe_of(batch)
    if batch["status"] != "BLENDED" or recipe is None \
            or recipe["flavoring_id"] is None:
        raise_err(
            ERR_BATCH_NOT_FLAVORABLE,
            "Batch is not BLENDED or the recipe has no flavoring",
        )
    # Priority 13: field shape.
    if not isinstance(flavoring_id, str) or not flavoring_id:
        raise_err(ERR_INVALID_REQUEST, "flavoring_id is required and must be a string")
    applied_kg = req_num(body, "applied_kg")
    # Priority 8: organic flavoring rule.
    if recipe["certification_target"] == "ORGANIC" \
            and not flavoring["natural_certified"]:
        raise_err(
            ERR_SYNTHETIC_ON_ORGANIC,
            "A non-natural flavoring may not be applied to an ORGANIC recipe",
        )
    # Priority 10: flavoring identity and exact dose.
    if flavoring_id != recipe["flavoring_id"]:
        raise_err(
            ERR_FLAVORING_MISMATCH,
            "flavoring_id does not equal the recipe's flavoring reference",
        )
    if round3(applied_kg) != round3(batch["flavoring_kg"]):
        raise_err(
            ERR_FLAVORING_DOSE_MISMATCH,
            "applied_kg must equal the batch's flavoring_kg exactly",
        )
    # Priority 11: flavoring liveness.
    if flavoring["status"] != "ACTIVE":
        raise_err(ERR_FLAVORING_NOT_ACTIVE, "Referenced flavoring is not ACTIVE")

    rec = new_immutable_record()
    rec.update({
        "batch_id": batch["id"],
        "flavoring_id": flavoring["id"],
        "applied_kg": applied_kg,
        "applied_by_user_id": uid,
        "flavoring_cost_cents": compute_line_cost_cents(
            applied_kg, flavoring["cost_per_kg_cents"]
        ),
    })
    store.flavoring_applications[rec["id"]] = rec

    batch["allergen_tags"] = list(flavoring["allergen_tags"])
    batch["status"] = "FLAVORED"
    bump(batch)
    return success_object(flavoring_application_out(rec), 201)


@bp.route("/tea-ops/batches/<bid>/flavoring-applications", methods=["GET"])
def list_batch_flavoring_applications(bid):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    batch = _batch_or_404(bid)
    return list_response(
        flavoring_applications_of_batch(batch["id"]), flavoring_application_out
    )


@bp.route("/tea-ops/batches/<bid>/submit-qc", methods=["POST"])
def submit_qc(bid):
    _, role = authenticate()
    authorize(role, ["BlendMaster"])
    batch = _batch_or_404(bid)
    _guard_batch_terminal(batch)
    recipe = _recipe_of(batch)
    flavored = recipe is not None and recipe["flavoring_id"] is not None
    applications = flavoring_applications_of_batch(batch["id"])

    if batch["status"] == "BLENDED":
        # Unflavored door: flavored recipes must apply flavoring first.
        if flavored:
            raise_err(
                ERR_FLAVORING_REQUIRED,
                "Recipe names a flavoring; it must be applied before QC",
            )
    elif batch["status"] == "FLAVORED":
        if len(applications) != 1:
            raise_err(
                ERR_INVALID_STATE,
                "Exactly one flavoring application must exist for the batch",
            )
    elif batch["status"] == "ON_HOLD":
        # Rework door: every allocated lot back in RELEASED / DEPLETED.
        for a in active_allocations_of_batch(batch["id"]):
            lot = store.leaf_lots[a["lot_id"]]
            if lot["status"] not in ("RELEASED", "DEPLETED"):
                raise_err(
                    ERR_INVALID_STATE,
                    "Allocated lot %s is not RELEASED or DEPLETED" % lot["id"],
                )
        if flavored and len(applications) != 1:
            raise_err(
                ERR_INVALID_STATE,
                "Exactly one flavoring application must exist for the batch",
            )
    else:
        raise_err(
            ERR_INVALID_STATE,
            "Batch cannot enter QC_REVIEW from %s" % batch["status"],
        )
    batch["status"] = "QC_REVIEW"
    bump(batch)
    return success_object(batch_out(batch))


@bp.route("/tea-ops/batches/<bid>/release", methods=["POST"])
def release_batch(bid):
    uid, role = authenticate()
    authorize(role, ["QAManager"])
    batch = _batch_or_404(bid)
    _guard_batch_terminal(batch)
    # Priority 6.
    if batch["status"] != "QC_REVIEW":
        raise_err(ERR_BATCH_NOT_RELEASABLE, "Batch is not in QC_REVIEW")
    # Priority 7: segregation of duties vs the blend master.
    if uid == batch["blended_by_user_id"]:
        raise_err(
            ERR_SEGREGATION_OF_DUTIES,
            "Releaser must differ from the operator who blended the batch",
        )
    # Priority 8: moisture gate, then certification chain.
    if batch["measured_moisture_pct"] > RELEASE_MOISTURE_GATE_PCT:
        raise_err(
            ERR_MOISTURE_OUT_OF_RANGE,
            "Batch measured_moisture_pct exceeds the 7.0 release gate",
        )
    recipe = _recipe_of(batch)
    cert_target = recipe["certification_target"] if recipe else "CONVENTIONAL"
    contributions = supplier_contributions(batch)
    supplier_certs = {}
    if cert_target != "CONVENTIONAL":
        for supplier_id, _kg in contributions:
            cert = find_valid_cert(supplier_id, cert_target)
            if cert is None:
                raise_err(
                    ERR_CERT_NOT_ACTIVE,
                    "No ACTIVE, currently-valid %s certificate for supplier %s"
                    % (cert_target, supplier_id),
                )
            supplier_certs[supplier_id] = cert
        for supplier_id, kg in contributions:
            cert = supplier_certs[supplier_id]
            remaining = cert["total_volume_kg"] - cert["consumed_volume_kg"]
            if remaining < kg:
                raise_err(
                    ERR_CERT_VOLUME_EXHAUSTED,
                    "Certificate remaining volume is below the contributed kg",
                )

    # certificate_volume_ledger: charge on the FIRST transition into RELEASED.
    if not batch["_ever_released"]:
        charges = []
        for supplier_id, kg in contributions:
            cert = supplier_certs.get(supplier_id)
            if cert is None:
                continue
            cert["consumed_volume_kg"] = cert["consumed_volume_kg"] + kg
            bump(cert)
            charges.append({"certificate_id": cert["id"], "charged_kg": kg})
        batch["cert_charges"] = charges
        batch["_ever_released"] = True

    batch["final_cost_cents"] = compute_final_cost_cents(
        batch["id"], batch["provisional_cost_cents"]
    )
    batch["actual_weight_kg"] = batch["yield_kg"] + batch["flavoring_kg"]
    batch["status"] = "RELEASED"
    bump(batch)
    return success_object(batch_out(batch))


@bp.route("/tea-ops/batches/<bid>/cancel", methods=["POST"])
def cancel_batch(bid):
    _, role = authenticate()
    authorize(role, ["BlendMaster"])
    batch = _batch_or_404(bid)
    _guard_batch_terminal(batch)
    if batch["status"] not in BATCH_CANCELLABLE_STATES:
        raise_err(
            ERR_INVALID_STATE,
            "Batch cannot be cancelled from %s" % batch["status"],
        )
    batch["status"] = "CANCELLED"
    bump(batch)
    release_batch_allocations(batch)
    return success_object(batch_out(batch))


@bp.route("/tea-ops/batches/<bid>/recall", methods=["POST"])
def recall_batch(bid):
    _, role = authenticate()
    authorize(role, ["QAManager"])
    batch = _batch_or_404(bid)
    _guard_batch_terminal(batch)
    if batch["status"] != "RELEASED":
        raise_err(ERR_INVALID_STATE, "Only a RELEASED batch can be recalled")
    batch["status"] = "RECALLED"
    bump(batch)
    # COMPENSATION: restore every recorded cert charge; clear the ledger.
    for charge in batch["cert_charges"]:
        cert = store.certificates.get(charge["certificate_id"])
        if cert is not None:
            cert["consumed_volume_kg"] = (
                cert["consumed_volume_kg"] - charge["charged_kg"]
            )
            bump(cert)
    batch["cert_charges"] = []
    # CASCADE: SCHEDULED runs referencing this batch -> CANCELLED
    # (IN_PROGRESS runs untouched).
    cancel_scheduled_runs_of_batch(batch)
    return success_object(batch_out(batch))
