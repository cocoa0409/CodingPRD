"""Core services: entity construction, serialization, classification recompute,
settlement waterfall, and cascade helpers."""

import uuid
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import clock
import errors
from db import db
from util import fmt_dt, now_wall_iso

MAINT_CPM_CENTS = Decimal("12.5")
EARLY_FEE_RATE = Decimal("0.10")
QUOTE_TTL_DAYS = 7
DEFAULT_THRESHOLD = 3
LANE_MIN_COMMITMENT_CENTS = 50000
BAY_BUFFER_HOURS = 2
REQUIRED_DOC_TYPES = {"W9", "OPERATING_AUTHORITY", "INSURANCE_CERTIFICATE"}


def new_id():
    return str(uuid.uuid4())


def base_entity():
    ts = now_wall_iso()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }


def touch(entity):
    """Bump version and refresh updated_at."""
    entity["version"] += 1
    entity["updated_at"] = now_wall_iso()


def round_half_up_cents(value):
    """Round a Decimal (or numeric) to whole integer cents, half-up."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Compliance / classification
# ---------------------------------------------------------------------------

def evaluate_doc_expiry(doc):
    """VERIFIED -> EXPIRED when logical clock >= expires_on. Returns True if mutated."""
    if doc["status"] == "VERIFIED" and clock.now() >= doc["_expires_on"]:
        doc["status"] = "EXPIRED"
        touch(doc)
        return True
    return False


def recompute_classification(operator):
    """Recompute classification_status from this operator's documents.

    VERIFIED: every required doc_type has a doc with status VERIFIED and
    expires_on strictly after the current logical clock.
    FLAGGED: any required doc is REJECTED, or a required VERIFIED doc has
    reached/passed its expires_on.
    Otherwise PENDING_REVIEW.
    """
    docs = [d for d in db.compliance_documents.values()
            if d["owner_operator_id"] == operator["id"]]
    # lazy expiry evaluation first
    for d in docs:
        evaluate_doc_expiry(d)

    now = clock.now()
    flagged = False
    all_satisfied = True
    for req in REQUIRED_DOC_TYPES:
        req_docs = [d for d in docs if d["doc_type"] == req]
        # A VERIFIED, unexpired document satisfies the type — a verified,
        # unexpired replacement restores the required set even when an older
        # REJECTED/EXPIRED document of the same type is on file (PRD 3.2:
        # "A FLAGGED operator returns to VERIFIED only when a replacement
        # required document is verified and unexpired").
        if any(d["status"] == "VERIFIED" and d["_expires_on"] > now for d in req_docs):
            continue
        all_satisfied = False
        if any(d["status"] in ("REJECTED", "EXPIRED") for d in req_docs):
            flagged = True

    if flagged:
        new_status = "FLAGGED"
    elif all_satisfied:
        new_status = "VERIFIED"
    else:
        new_status = "PENDING_REVIEW"

    if new_status != operator["classification_status"]:
        operator["classification_status"] = new_status
        touch(operator)
    return operator["classification_status"]


# ---------------------------------------------------------------------------
# Settlement waterfall
# ---------------------------------------------------------------------------

def compute_guarantee_top_up(lease, week_start, gross_revenue_cents, load_declined_flag,
                             force_ineligible=False):
    """guarantee_top_up per calculations.guarantee_top_up."""
    if force_ineligible:
        return 0
    eligible = (
        lease["status"] == "ACTIVE"
        and not load_declined_flag
        and any(
            lane["status"] == "ACCEPTED"
            and lane["_start_date"] <= week_start < lane["_end_date"]
            for lane in db.lane_assignments.values()
            if lane["lease_id"] == lease["id"]
        )
    )
    if not eligible:
        return 0
    return max(0, lease["min_revenue_guarantee_weekly_cents"] - gross_revenue_cents)


def run_waterfall(settlement, lease, escrow, maintenance_basis="provisional",
                  maintenance_override_cents=None, guarantee_forced_zero=False):
    """Recompute all computed lines of a settlement in place.

    maintenance_basis: "provisional" (reserve accrual) or "final" (actual billed).
    maintenance_override_cents: clerk override substituted for the maintenance
    line on reissue (provisional basis).
    guarantee_forced_zero: default-declaration cascade strips guarantee.
    """
    fuel_cents = round_half_up_cents(
        Decimal(str(settlement["fuel_gallons"])) * Decimal(settlement["fuel_price_cents_per_gallon"])
    )
    settlement["fuel_deduction_cents"] = fuel_cents

    if maintenance_override_cents is not None:
        maintenance_cents = maintenance_override_cents
    elif maintenance_basis == "final":
        week_start = settlement["_week_start_date"]
        week_end = week_start + timedelta(days=7)
        total = 0
        for wo in db.maintenance_work_orders.values():
            if (
                wo["lease_id"] == lease["id"]
                and wo["status"] == "COMPLETED"
                and wo.get("billed_to") == "OPERATOR"
                and wo.get("_completed_at") is not None
                and week_start <= wo["_completed_at"] < week_end
            ):
                total += wo["actual_cost_cents"]
        maintenance_cents = total
    else:
        maintenance_cents = round_half_up_cents(
            Decimal(settlement["miles_driven"]) * MAINT_CPM_CENTS
        )
    settlement["maintenance_deduction_cents"] = maintenance_cents

    top_up = compute_guarantee_top_up(
        lease,
        settlement["_week_start_date"],
        settlement["gross_revenue_cents"],
        settlement["load_declined_flag"],
        force_ineligible=guarantee_forced_zero,
    )
    settlement["guarantee_top_up_cents"] = top_up

    funds = settlement["gross_revenue_cents"] + top_up
    remaining = funds
    remaining = max(0, remaining - fuel_cents)
    remaining = max(0, remaining - settlement["insurance_weekly_cents"])
    remaining = max(0, remaining - maintenance_cents)

    cap_room = max(0, lease["escrow_cap_cents"] - escrow["balance_cents"])
    escrow_contribution = min(lease["escrow_weekly_contribution_cents"], cap_room, remaining)
    settlement["escrow_contribution_cents"] = escrow_contribution
    remaining -= escrow_contribution

    lease_payment_applied = min(lease["weekly_payment_cents"], remaining)
    settlement["lease_payment_applied_cents"] = lease_payment_applied
    remaining -= lease_payment_applied

    settlement["net_pay_cents"] = max(0, remaining)
    settlement["payment_short_flag"] = lease_payment_applied < lease["weekly_payment_cents"]
