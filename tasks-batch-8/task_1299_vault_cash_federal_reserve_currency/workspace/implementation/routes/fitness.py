"""FitnessBatch endpoints."""
from flask import Blueprint, request

from db import DB, new_id, clock_date_str
from errors import ApiError
from middleware import auth, ALL_ROLES, SITE_SCOPED_STAFF_ROLES, require_site_scope
from response import ok, ok_list
from services import (
    stamp_new, touch, public, append_ledger, site_mutation,
    SHRINK_TOLERANCE_CENTS,
)
from util import body, required, as_int, as_str, pagination_args

bp = Blueprint("fitness", __name__)


def _get_batch_or_404(batch_id):
    batch = DB["fitness_batches"].get(batch_id)
    if batch is None:
        raise ApiError("ERR_FITNESS_BATCH_NOT_FOUND", 404, "Fitness batch not found")
    return batch


def _site_or_404(site_id):
    site = DB["vault_sites"].get(site_id)
    if site is None:
        raise ApiError("ERR_VAULT_SITE_NOT_FOUND", 404, "Vault site not found")
    return site


@bp.post("/vault-cash/fitness-batches")
def create_batch():
    principal = auth(["VaultCustodian"])
    data = body()
    site_id = as_str(required(data, "site_id"), "site_id")
    site = _site_or_404(site_id)
    require_site_scope(principal, site_id)
    input_unfit = as_int(required(data, "input_unfit_cents"), "input_unfit_cents")
    if site["posture"] == "FROZEN":
        raise ApiError("ERR_VAULT_FROZEN", 409, "Site posture is FROZEN")
    if input_unfit > site["on_hand_unfit_cents"]:
        raise ApiError(
            "ERR_INSUFFICIENT_UNFIT_BALANCE",
            422,
            "Fitness batch input exceeds site unfit on hand",
        )
    batch = stamp_new({
        "id": new_id(),
        "site_id": site_id,
        "input_unfit_cents": input_unfit,
        "fit_recovered_cents": 0,
        "unfit_remaining_cents": 0,
        "counterfeit_face_cents": 0,
        "shrink_cents": input_unfit,
        "status": "OPEN",
    })
    DB["fitness_batches"][batch["id"]] = batch
    # Escrow the unfit input out of the site's on-hand unfit balance.
    append_ledger(
        site_id, clock_date_str(), "FITNESS_RECLASS", -input_unfit, "UNFIT",
        note=f"Fitness batch {batch['id']} escrow",
    )
    return ok(public(batch), status=201)


@bp.get("/vault-cash/fitness-batches")
def list_batches():
    principal = auth(ALL_ROLES)
    limit, offset = pagination_args()
    site_id = request.args.get("site_id")
    status = request.args.get("status")
    rows = list(DB["fitness_batches"].values())
    if site_id is not None:
        rows = [b for b in rows if b["site_id"] == site_id]
    if status is not None:
        rows = [b for b in rows if b["status"] == status]
    if principal.role in SITE_SCOPED_STAFF_ROLES:
        rows = [b for b in rows if b["site_id"] == principal.home_site_id]
    rows.sort(key=lambda b: (b["created_at"], b["_seq"]))
    total = len(rows)
    return ok_list([public(b) for b in rows[offset:offset + limit]], total, limit, offset)


@bp.get("/vault-cash/fitness-batches/<batchId>")
def get_batch(batchId):
    principal = auth(ALL_ROLES)
    batch = _get_batch_or_404(batchId)
    require_site_scope(principal, batch["site_id"])
    return ok(public(batch))


@bp.post("/vault-cash/fitness-batches/<batchId>/sort-results")
def sort_results(batchId):
    principal = auth(["VaultCustodian"])
    batch = _get_batch_or_404(batchId)
    require_site_scope(principal, batch["site_id"])
    data = body()
    fit = as_int(required(data, "fit_recovered_cents"), "fit_recovered_cents")
    unfit = as_int(required(data, "unfit_remaining_cents"), "unfit_remaining_cents")
    counterfeit = as_int(
        required(data, "counterfeit_face_cents"), "counterfeit_face_cents"
    )
    if batch["status"] != "OPEN":
        raise ApiError(
            "ERR_BATCH_INVALID_STATE", 409, "Sort results require an OPEN batch"
        )
    if fit + unfit + counterfeit > batch["input_unfit_cents"]:
        raise ApiError(
            "ERR_SORT_EXCEEDS_INPUT", 422, "Sort buckets exceed escrowed input"
        )
    if counterfeit % 100 != 0:
        raise ApiError(
            "ERR_SORT_EXCEEDS_INPUT",
            422,
            "Counterfeit face must be a multiple of 100",
        )
    batch["fit_recovered_cents"] = fit
    batch["unfit_remaining_cents"] = unfit
    batch["counterfeit_face_cents"] = counterfeit
    batch["shrink_cents"] = batch["input_unfit_cents"] - (fit + unfit + counterfeit)
    batch["status"] = "SORTED"
    touch(batch)
    return ok(public(batch))


@bp.post("/vault-cash/fitness-batches/<batchId>/reopen")
def reopen_batch(batchId):
    principal = auth(["VaultCustodian"])
    batch = _get_batch_or_404(batchId)
    require_site_scope(principal, batch["site_id"])
    if batch["status"] != "SORTED":
        raise ApiError(
            "ERR_BATCH_INVALID_STATE", 409, "Only SORTED batches may be reopened"
        )
    batch["status"] = "OPEN"
    batch["fit_recovered_cents"] = 0
    batch["unfit_remaining_cents"] = 0
    batch["counterfeit_face_cents"] = 0
    batch["shrink_cents"] = batch["input_unfit_cents"]
    touch(batch)
    return ok(public(batch))


@bp.post("/vault-cash/fitness-batches/<batchId>/settle")
def settle_batch(batchId):
    principal = auth(["VaultCustodian"])
    batch = _get_batch_or_404(batchId)
    require_site_scope(principal, batch["site_id"])
    if batch["status"] != "SORTED":
        raise ApiError(
            "ERR_BATCH_INVALID_STATE", 409, "Only SORTED batches may be settled"
        )
    if batch["shrink_cents"] > SHRINK_TOLERANCE_CENTS:
        raise ApiError(
            "ERR_SHRINK_TOLERANCE_EXCEEDED",
            422,
            "shrink_cents exceeds the 500-cent tolerance",
        )
    site = _site_or_404(batch["site_id"])
    batch["status"] = "SETTLED"
    touch(batch)
    business_date = clock_date_str()
    # Return buckets to the site via FITNESS_RECLASS entries.
    if batch["fit_recovered_cents"]:
        append_ledger(
            site["id"], business_date, "FITNESS_RECLASS",
            batch["fit_recovered_cents"], "FIT",
            note=f"Fitness batch {batch['id']} settle fit",
        )
    if batch["unfit_remaining_cents"]:
        append_ledger(
            site["id"], business_date, "FITNESS_RECLASS",
            batch["unfit_remaining_cents"], "UNFIT",
            note=f"Fitness batch {batch['id']} settle unfit",
        )
    if batch["shrink_cents"] > 0:
        append_ledger(
            site["id"], business_date, "ADJUSTMENT",
            -batch["shrink_cents"], "FIT",
            note=f"Fitness batch {batch['id']} shrink",
        )
    if batch["counterfeit_face_cents"] > 0:
        # Auto-create a DETECTED CounterfeitCase denominated in 100-cent notes.
        case = stamp_new({
            "id": new_id(),
            "site_id": site["id"],
            "fitness_batch_id": batch["id"],
            "denomination_cents": 100,
            "note_count": batch["counterfeit_face_cents"] // 100,
            "face_value_cents": batch["counterfeit_face_cents"],
            "seized_by_staff_id": None,
            "seized_at": None,
            "reported_by_staff_id": None,
            "reported_at": None,
            "status": "DETECTED",
        })
        DB["counterfeit_cases"][case["id"]] = case
    # Ensure derived fields/posture reflect the final state.
    site_mutation(site)
    return ok(public(batch))
