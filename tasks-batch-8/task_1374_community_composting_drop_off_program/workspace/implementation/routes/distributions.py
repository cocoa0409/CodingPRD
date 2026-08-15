"""CompostDistribution and DistributionAllocation endpoints."""

from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint, request

import db
import errors
from middleware import require_roles
from response import success_object, success_list
from routes.helpers import (
    body, require_fields, require_number, require_int, occ_check,
    get_program_or_404, get_batch_or_404, get_distribution_or_404,
    get_allocation_or_404, get_participant_or_404,
    paginate, sort_created,
)
from services import credits
from services.programs import touch
from services.serializers import (
    distribution as serialize_distribution,
    allocation as serialize_allocation,
)

bp = Blueprint("distributions", __name__)

READ_ROLES = ("ProgramAdmin", "Participant", "MunicipalAuditor")


# ---------------------------------------------------------------------------
# CompostDistribution
# ---------------------------------------------------------------------------

@bp.route("/programs/<program_id>/distributions", methods=["POST"])
def create_distribution(program_id):
    require_roles("ProgramAdmin")
    program = get_program_or_404(program_id)
    data = body()
    require_fields(data, "batch_id")
    batch = db.batches.get(data["batch_id"])
    if not batch:
        errors.raise_err(errors.ERR_NOT_FOUND, "ProcessingBatch not found")
    # Verify the batch's partner belongs to this program
    partner = db.partners.get(batch["partner_id"])
    if not partner or partner["program_id"] != program_id:
        errors.raise_err(errors.ERR_NOT_FOUND, "ProcessingBatch not found in program")
    if batch["status"] != "CLOSED_ACCEPTED":
        errors.raise_err(
            errors.ERR_INVALID_STATE,
            "Distribution requires a CLOSED_ACCEPTED batch",
        )

    now = db.iso_now()
    distribution = {
        "id": db.new_id(),
        "program_id": program["id"],
        "batch_id": batch["id"],
        "total_pool_kg": batch["finished_compost_kg"],
        "allocated_kg": 0.0,
        "status": "OPEN",
        "opened_at": db.clock_now(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.distributions[distribution["id"]] = distribution
    return success_object(serialize_distribution(distribution), status=201)


@bp.route("/programs/<program_id>/distributions", methods=["GET"])
def list_distributions(program_id):
    require_roles(*READ_ROLES)
    get_program_or_404(program_id)
    items = [d for d in db.distributions.values() if d["program_id"] == program_id]
    if request.args.get("status"):
        items = [d for d in items if d["status"] == request.args["status"]]
    items = sort_created(items)
    page, limit, offset, total = paginate(items)
    return success_list([serialize_distribution(d) for d in page], limit, offset, total)


@bp.route("/programs/<program_id>/distributions/<distribution_id>", methods=["GET"])
def get_distribution(program_id, distribution_id):
    require_roles(*READ_ROLES)
    get_program_or_404(program_id)
    distribution = get_distribution_or_404(distribution_id, program_id)
    return success_object(serialize_distribution(distribution))


@bp.route("/programs/<program_id>/distributions/<distribution_id>/close", methods=["POST"])
def close_distribution(program_id, distribution_id):
    require_roles("ProgramAdmin")
    get_program_or_404(program_id)
    distribution = get_distribution_or_404(distribution_id, program_id)
    if distribution["status"] != "OPEN":
        errors.raise_err(errors.ERR_INVALID_STATE, "Distribution must be OPEN to close")
    pending = any(
        a["distribution_id"] == distribution["id"] and a["status"] == "REQUESTED"
        for a in db.allocations.values()
    )
    if pending:
        errors.raise_err(
            errors.ERR_DISTRIBUTION_HAS_PENDING_REQUESTS,
            "Distribution close blocked by REQUESTED allocations",
        )
    distribution["status"] = "CLOSED"
    touch(distribution)
    return success_object(serialize_distribution(distribution))


@bp.route("/programs/<program_id>/distributions/<distribution_id>/cancel", methods=["POST"])
def cancel_distribution(program_id, distribution_id):
    require_roles("ProgramAdmin")
    get_program_or_404(program_id)
    distribution = get_distribution_or_404(distribution_id, program_id)
    if distribution["status"] != "OPEN":
        errors.raise_err(errors.ERR_INVALID_STATE, "Distribution must be OPEN to cancel")
    distribution["status"] = "CANCELLED"
    for a in db.allocations.values():
        if a["distribution_id"] == distribution["id"] and a["status"] == "REQUESTED":
            a["status"] = "CANCELLED"
            participant = db.participants.get(a["participant_id"])
            if participant and a["credits_redeemed"]:
                credits.refund(participant["id"], a["credits_redeemed"])
    touch(distribution)
    return success_object(serialize_distribution(distribution))


@bp.route("/distributions", methods=["GET"])
def list_distributions_flat():
    require_roles(*READ_ROLES)
    items = list(db.distributions.values())
    if request.args.get("program_id"):
        items = [d for d in items if d["program_id"] == request.args["program_id"]]
    if request.args.get("batch_id"):
        items = [d for d in items if d["batch_id"] == request.args["batch_id"]]
    if request.args.get("status"):
        items = [d for d in items if d["status"] == request.args["status"]]
    items = sort_created(items)
    page, limit, offset, total = paginate(items)
    return success_list([serialize_distribution(d) for d in page], limit, offset, total)


@bp.route("/distributions/<distribution_id>", methods=["GET"])
def get_distribution_flat(distribution_id):
    require_roles(*READ_ROLES)
    distribution = get_distribution_or_404(distribution_id)
    return success_object(serialize_distribution(distribution))


# ---------------------------------------------------------------------------
# DistributionAllocation
# ---------------------------------------------------------------------------

@bp.route("/programs/<program_id>/distributions/<distribution_id>/allocations", methods=["POST"])
def create_allocation(program_id, distribution_id):
    require_roles("Participant")
    get_program_or_404(program_id)
    distribution = get_distribution_or_404(distribution_id, program_id)
    data = body()
    require_fields(data, "participant_id", "requested_kg", "credits_redeemed")
    participant_id = data["participant_id"]
    if not isinstance(participant_id, str):
        errors.raise_err(errors.ERR_INVALID_REQUEST, "participant_id must be a string")
    requested_kg = require_number(data, "requested_kg")
    credits_redeemed = require_int(data, "credits_redeemed")
    if credits_redeemed < 0:
        errors.raise_err(
            errors.ERR_INVALID_REQUEST, "credits_redeemed must be >= 0")

    # Priority 4: OCC on distribution version
    occ_check(
        distribution,
        data.get("expected_distribution_version"),
        "expected_distribution_version",
    )

    if distribution["status"] != "OPEN":
        errors.raise_err(errors.ERR_INVALID_STATE, "Distribution must be OPEN for allocation requests")

    participant = db.participants.get(participant_id)
    if not participant or participant["program_id"] != program_id:
        errors.raise_err(errors.ERR_NOT_FOUND, "Participant not found in program")

    # Priority 12: affordability
    if requested_kg <= 0 or credits_redeemed > participant["bucket_credit_balance"]:
        errors.raise_err(
            errors.ERR_INSUFFICIENT_BUCKET_CREDITS,
            "credits_redeemed exceeds participant.bucket_credit_balance or requested_kg not positive",
        )

    now = db.iso_now()
    allocation = {
        "id": db.new_id(),
        "distribution_id": distribution["id"],
        "participant_id": participant_id,
        "requested_kg": requested_kg,
        "credits_redeemed": credits_redeemed,
        "allocation_kg": None,
        "status": "REQUESTED",
        "created_at": now,
    }
    db.allocations[allocation["id"]] = allocation
    # PRD §3.6: a request is a credit "spend" and a later cancel "refunds
    # credits_redeemed ... without counting a redemption" — so the credits are
    # escrowed at request time (redeemed now, refunded on cancel), keeping
    # §2.8's invariant balance == granted - redeemed - expired true at all
    # times and preventing double-spend across concurrent requests.
    if credits_redeemed:
        credits.redeem(participant["id"], credits_redeemed)
    # Requesting an allocation increments the distribution's version
    touch(distribution)
    return success_object(serialize_allocation(allocation), status=201)


@bp.route("/programs/<program_id>/distributions/<distribution_id>/allocations", methods=["GET"])
def list_allocations(program_id, distribution_id):
    require_roles(*READ_ROLES)
    get_program_or_404(program_id)
    get_distribution_or_404(distribution_id, program_id)
    items = [a for a in db.allocations.values() if a["distribution_id"] == distribution_id]
    if request.args.get("participant_id"):
        items = [a for a in items if a["participant_id"] == request.args["participant_id"]]
    if request.args.get("status"):
        items = [a for a in items if a["status"] == request.args["status"]]
    items = sort_created(items)
    page, limit, offset, total = paginate(items)
    return success_list([serialize_allocation(a) for a in page], limit, offset, total)


def _fair_share_kg(distribution, allocation):
    """distribution_fair_share calculation (PRD §3.6)."""
    pool_remaining = Decimal(str(distribution["total_pool_kg"])) - Decimal(
        str(distribution["allocated_kg"])
    )
    participant = db.participants[allocation["participant_id"]]
    related = [
        a for a in db.allocations.values()
        if a["distribution_id"] == distribution["id"] and a["status"] in ("REQUESTED", "DISTRIBUTED")
    ]
    total_households = sum(
        db.participants[a["participant_id"]]["household_size"] for a in related
    )
    if total_households == 0:
        errors.raise_err(
            errors.ERR_DISTRIBUTION_NO_REQUESTS,
            "Fair-share run with zero REQUESTED allocations",
        )
    household_share = pool_remaining * Decimal(str(participant["household_size"])) / Decimal(
        str(total_households)
    )
    credit_cap = Decimal(str(allocation["credits_redeemed"]))
    requested_pending = [
        a for a in db.allocations.values()
        if a["distribution_id"] == distribution["id"] and a["status"] == "REQUESTED"
    ]
    equal_split = pool_remaining / Decimal(str(len(requested_pending)))
    result = min(
        Decimal(str(allocation["requested_kg"])),
        min(household_share, credit_cap),
        equal_split,
    )
    return result.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


@bp.route(
    "/programs/<program_id>/distributions/<distribution_id>/allocations/<allocation_id>/distribute",
    methods=["POST"],
)
def distribute_allocation(program_id, distribution_id, allocation_id):
    require_roles("ProgramAdmin")
    get_program_or_404(program_id)
    distribution = get_distribution_or_404(distribution_id, program_id)
    allocation = get_allocation_or_404(allocation_id, distribution_id)
    if distribution["status"] != "OPEN":
        errors.raise_err(errors.ERR_INVALID_STATE, "Parent distribution must be OPEN")
    if allocation["status"] != "REQUESTED":
        errors.raise_err(errors.ERR_INVALID_STATE, "Allocation must be REQUESTED to distribute")

    allocation_kg = _fair_share_kg(distribution, allocation)
    if Decimal(str(distribution["allocated_kg"])) + allocation_kg > Decimal(
        str(distribution["total_pool_kg"])
    ):
        errors.raise_err(
            errors.ERR_DISTRIBUTION_POOL_EXHAUSTED,
            "Allocation would exceed distribution.total_pool_kg",
        )

    # Credits were already escrowed at request time (redeemed then, refunded
    # on cancel), so a successful grant leaves the ledger untouched here —
    # the net effect matches PRD §3.6 ("debits credits_redeemed from the
    # participant's bucket_credit_balance, adds the same amount to
    # bucket_credits_redeemed_total") observed across request+grant.
    allocation["allocation_kg"] = float(allocation_kg)
    allocation["status"] = "DISTRIBUTED"
    distribution["allocated_kg"] = db.round_kg(
        float(distribution["allocated_kg"]) + float(allocation_kg)
    )
    touch(distribution)
    return success_object(serialize_allocation(allocation))


@bp.route(
    "/programs/<program_id>/distributions/<distribution_id>/allocations/<allocation_id>/cancel",
    methods=["POST"],
)
def cancel_allocation(program_id, distribution_id, allocation_id):
    require_roles("ProgramAdmin")
    get_program_or_404(program_id)
    get_distribution_or_404(distribution_id, program_id)
    allocation = get_allocation_or_404(allocation_id, distribution_id)
    if allocation["status"] != "REQUESTED":
        errors.raise_err(errors.ERR_INVALID_STATE, "Allocation must be REQUESTED to cancel")
    allocation["status"] = "CANCELLED"
    participant = db.participants.get(allocation["participant_id"])
    if participant and allocation["credits_redeemed"]:
        credits.refund(participant["id"], allocation["credits_redeemed"])
    return success_object(serialize_allocation(allocation))


@bp.route("/allocations", methods=["GET"])
def list_allocations_flat():
    require_roles(*READ_ROLES)
    items = list(db.allocations.values())
    if request.args.get("distribution_id"):
        items = [a for a in items if a["distribution_id"] == request.args["distribution_id"]]
    if request.args.get("participant_id"):
        items = [a for a in items if a["participant_id"] == request.args["participant_id"]]
    if request.args.get("status"):
        items = [a for a in items if a["status"] == request.args["status"]]
    items = sort_created(items)
    page, limit, offset, total = paginate(items)
    return success_list([serialize_allocation(a) for a in page], limit, offset, total)


@bp.route("/allocations/<allocation_id>", methods=["GET"])
def get_allocation_flat(allocation_id):
    require_roles(*READ_ROLES)
    allocation = get_allocation_or_404(allocation_id)
    return success_object(serialize_allocation(allocation))
