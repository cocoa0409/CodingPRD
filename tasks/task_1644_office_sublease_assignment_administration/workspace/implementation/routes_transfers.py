"""TransferRequest and DemisedArea endpoints."""
from flask import Blueprint

import db
from db import store, new_id, touch, new_common, iso_logical, parse_iso
from errors import ApiError
from response import ok, created, paginate
from middleware import get_context, require_roles, ADMIN_READ
from validation import parse_body, require_path_entity
from domain import (
    compute_consent_deadline, compute_measurement, compute_rent_differential,
    get_certified_area, get_consent_review, get_credit_review,
    get_recognition_agreement, get_sublease_agreement, get_conditions_for_review,
    grant_consent, decrement_lease_open_count, void_recognition_agreements,
    count_open_transfers, NON_TERMINAL_TRANSFER_STATUSES,
)

bp = Blueprint("transfers", __name__)

TRANSFER_TYPES = ["SUBLEASE", "ASSIGNMENT"]


# ---------------------------------------------------------------------------
# TransferRequest — create
# ---------------------------------------------------------------------------

@bp.post("/sublease-admin/leases/<lease_id>/transfer-requests")
def create_transfer_request(lease_id):
    uid, role, _ = get_context()
    require_roles(["TenantRepBroker"])
    body = parse_body({
        "counterparty_id": ("string", True, None),
        "transfer_type": ("enum", True, TRANSFER_TYPES),
        "proposed_rent_per_rsf_annual_cents": ("integer", True, None),
        "term_start": ("string", True, None),
        "term_end": ("string", True, None),
        "marketing_period_days": ("integer", True, None),
        "expected_lease_version": ("integer", True, None),
    }, allow_empty=False)

    # Existence (priority 3)
    lease = require_path_entity(store.leases, lease_id)

    # FK referential integrity (priority 4)
    counterparty = store.parties.get(body["counterparty_id"])
    if counterparty is None:
        raise ApiError("ERR_FK_MISMATCH", 422, "Referenced counterparty does not exist")
    expected_kind = "SUBTENANT" if body["transfer_type"] == "SUBLEASE" else "ASSIGNEE"
    if counterparty["party_kind"] != expected_kind:
        raise ApiError("ERR_FK_MISMATCH", 422,
                       "counterparty kind %s does not match transfer_type %s"
                       % (counterparty["party_kind"], body["transfer_type"]))

    # Uniqueness (priority 8): one non-terminal transfer per lease
    open_count = count_open_transfers(lease_id)
    if open_count > 0:
        raise ApiError("ERR_DUPLICATE_ACTIVE", 409,
                       "Lease already has a non-terminal transfer request")

    # Fiscal coherence (priority 10)
    if body["proposed_rent_per_rsf_annual_cents"] <= 0:
        raise ApiError("ERR_FISCAL_INCOHERENT", 422,
                       "proposed_rent_per_rsf_annual_cents must be strictly positive")

    # OCC (priority 13)
    if body["expected_lease_version"] != lease["version"]:
        raise ApiError("ERR_STALE_LEASE_VERSION", 412,
                       "Lease version has advanced since last read")

    transfer = {
        "id": new_id(),
        "lease_id": lease_id,
        "counterparty_id": body["counterparty_id"],
        "broker_user_id": uid,
        "transfer_type": body["transfer_type"],
        "proposed_rent_per_rsf_annual_cents": body["proposed_rent_per_rsf_annual_cents"],
        "term_start": body["term_start"],
        "term_end": body["term_end"],
        "marketing_period_days": body["marketing_period_days"],
        "status": "DRAFT",
        "submitted_at": None,
        "consent_deadline": None,
        "reminder_sent_at": None,
        "consent_granted_at": None,
        "liability_released": None,
        "annual_rent_differential_cents": None,
        "effective_at": None,
    }
    new_common(transfer)
    store.transfer_requests[transfer["id"]] = transfer
    # OCC anchor: increment lease version (open_transfer_count NOT incremented)
    touch(lease)
    return created(transfer)


# ---------------------------------------------------------------------------
# TransferRequest — read
# ---------------------------------------------------------------------------

@bp.get("/sublease-admin/transfer-requests/<transfer_id>")
def get_transfer_request(transfer_id):
    uid, role, _ = get_context()
    require_roles(ADMIN_READ)
    return ok(require_path_entity(store.transfer_requests, transfer_id))


@bp.get("/sublease-admin/transfer-requests")
def list_transfer_requests():
    uid, role, _ = get_context()
    require_roles(ADMIN_READ)
    rows = list(store.transfer_requests.values())
    for f in ("lease_id", "status", "transfer_type", "counterparty_id"):
        rows = paginate.filter(rows, f)
    return ok(paginate(rows), rtype="array", pagination=paginate)


# ---------------------------------------------------------------------------
# TransferRequest — submit
# ---------------------------------------------------------------------------

@bp.post("/sublease-admin/transfer-requests/<transfer_id>/submit")
def submit_transfer_request(transfer_id):
    uid, role, _ = get_context()
    require_roles(["TenantRepBroker"])
    transfer = require_path_entity(store.transfer_requests, transfer_id)

    # State (priority 5)
    if transfer["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Submit requires the transfer to be DRAFT")

    lease = store.leases[transfer["lease_id"]]

    # Temporal window (priority 7)
    now = db.LOGICAL_CLOCK
    term_start_dt = parse_iso(transfer["term_start"])
    term_end_dt = parse_iso(transfer["term_end"])
    if term_start_dt <= now:
        raise ApiError("ERR_TEMPORAL_WINDOW", 422,
                       "term_start must be strictly after the current time")
    if term_end_dt <= term_start_dt:
        raise ApiError("ERR_TEMPORAL_WINDOW", 422,
                       "term_end must be strictly after term_start")

    # Package completeness (priority 9)
    if transfer["marketing_period_days"] < 30:
        raise ApiError("ERR_PACKAGE_INCOMPLETE", 422,
                       "marketing_period_days must be >= 30")
    certified = get_certified_area(transfer["id"])
    if certified is None:
        raise ApiError("ERR_PACKAGE_INCOMPLETE", 422,
                       "A certified non-superseded DemisedArea is required")

    # Lease must be ACTIVE
    if lease["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Lease is not ACTIVE")

    # --- Apply side effects ---
    transfer["status"] = "SUBMITTED"
    transfer["submitted_at"] = iso_logical(now)
    deadline_dt = compute_consent_deadline(now, lease["consent_window_business_days"])
    transfer["consent_deadline"] = iso_logical(deadline_dt)
    touch(transfer)

    # Mint ConsentReview (PENDING)
    review = {
        "id": new_id(),
        "transfer_request_id": transfer["id"],
        "reviewer_landlord_id": None,
        "decision": "PENDING",
        "denial_reason_code": None,
        "release_of_assignor": False,
        "conditions_imposed_count": 0,
        "decided_at": None,
        "rescinded_at": None,
    }
    new_common(review)
    store.consent_reviews[review["id"]] = review

    # Mint CreditReview (PENDING)
    credit = {
        "id": new_id(),
        "transfer_request_id": transfer["id"],
        "attesting_broker_user_id": None,
        "reviewed_credit_rating_bps": None,
        "outcome": "PENDING",
        "minimum_pass_bps": 6000,
        "attested_at": None,
    }
    new_common(credit)
    store.credit_reviews[credit["id"]] = credit

    # Increment lease counters
    lease["open_transfer_count"] = lease.get("open_transfer_count", 0) + 1
    touch(lease)

    return ok(transfer)


# ---------------------------------------------------------------------------
# TransferRequest — withdraw
# ---------------------------------------------------------------------------

@bp.post("/sublease-admin/transfer-requests/<transfer_id>/withdraw")
def withdraw_transfer_request(transfer_id):
    uid, role, _ = get_context()
    require_roles(["TenantRepBroker"])
    transfer = require_path_entity(store.transfer_requests, transfer_id)

    # State check
    withdrawable = ("DRAFT", "SUBMITTED", "CONSENT_PENDING", "CONSENT_GRANTED",
                    "DEEMED_APPROVED", "DOCUMENTED")
    if transfer["status"] not in withdrawable:
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Withdraw is not permitted from status %s" % transfer["status"])

    # Duty segregation: withdrawing broker must be the originating broker
    if uid != transfer["broker_user_id"]:
        raise ApiError("ERR_DUTY_SEGREGATION", 403,
                       "Only the originating broker may withdraw the transfer")

    # DOCUMENTED withdraw requires recognition not fully executed
    if transfer["status"] == "DOCUMENTED":
        ra = get_recognition_agreement(transfer["id"])
        if ra is not None and ra["status"] == "FULLY_EXECUTED":
            raise ApiError("ERR_INVALID_STATE", 409,
                           "Cannot withdraw after recognition is fully executed")

    lease = store.leases[transfer["lease_id"]]
    prev_status = transfer["status"]

    transfer["status"] = "WITHDRAWN"
    touch(transfer)

    if prev_status in ("SUBMITTED", "CONSENT_PENDING", "CONSENT_GRANTED",
                       "DEEMED_APPROVED", "DOCUMENTED"):
        decrement_lease_open_count(lease)
        void_recognition_agreements(transfer)

    if prev_status == "DOCUMENTED":
        # Compensation cascade
        sa = get_sublease_agreement(transfer["id"])
        if sa is not None and sa["status"] == "EXECUTED":
            sa["status"] = "TERMINATED"
            touch(sa)
        for ro in store.restoration_obligations.values():
            if (ro["transfer_request_id"] == transfer["id"]
                    and ro["status"] in ("OPEN", "ESCROW_POSTED")):
                ro["status"] = "WAIVED"
                touch(ro)

    return ok(transfer)


# ---------------------------------------------------------------------------
# TransferRequest — remind
# ---------------------------------------------------------------------------

@bp.post("/sublease-admin/transfer-requests/<transfer_id>/remind")
def remind_transfer_request(transfer_id):
    uid, role, _ = get_context()
    require_roles(["Tenant"])
    transfer = require_path_entity(store.transfer_requests, transfer_id)
    lease = store.leases[transfer["lease_id"]]

    # Deemed approval disabled takes precedence over premature reminder
    if not lease.get("deemed_approval_enabled"):
        raise ApiError("ERR_DEEMED_APPROVAL_DISABLED", 409,
                       "Lease does not have a deemed-approval provision")

    # Reminder eligibility (priority 12)
    if transfer["status"] not in ("SUBMITTED", "CONSENT_PENDING"):
        raise ApiError("ERR_REMINDER_PREMATURE", 409,
                       "Remind requires transfer in SUBMITTED or CONSENT_PENDING")
    review = get_consent_review(transfer["id"])
    if review is None or review["decision"] != "PENDING":
        raise ApiError("ERR_REMINDER_PREMATURE", 409,
                       "Consent review is no longer PENDING")
    if transfer.get("reminder_sent_at") is not None:
        raise ApiError("ERR_REMINDER_PREMATURE", 409,
                       "A reminder has already been recorded")
    now = db.LOGICAL_CLOCK
    deadline_dt = parse_iso(transfer["consent_deadline"])
    if now <= deadline_dt:
        raise ApiError("ERR_REMINDER_PREMATURE", 409,
                       "Reminder may only be sent after the consent deadline")

    transfer["reminder_sent_at"] = iso_logical(now)
    touch(transfer)
    return ok(transfer)


# ---------------------------------------------------------------------------
# TransferRequest — document
# ---------------------------------------------------------------------------

@bp.post("/sublease-admin/transfer-requests/<transfer_id>/document")
def document_transfer_request(transfer_id):
    uid, role, _ = get_context()
    require_roles(["TenantRepBroker"])
    body = parse_body({
        "executed_rent_per_rsf_annual_cents": ("integer", True, None),
        "restoration_allocations": ("allocations", False, None),
    }, allow_empty=False)

    transfer = require_path_entity(store.transfer_requests, transfer_id)

    # State check
    if transfer["status"] not in ("CONSENT_GRANTED", "DEEMED_APPROVED"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Document requires transfer in CONSENT_GRANTED or DEEMED_APPROVED")

    lease = store.leases[transfer["lease_id"]]

    # Package completeness: certified non-superseded measurement must exist
    certified = get_certified_area(transfer["id"])
    if certified is None:
        raise ApiError("ERR_PACKAGE_INCOMPLETE", 422,
                       "A certified non-superseded DemisedArea is required for documentation")

    # Fiscal coherence
    if body["executed_rent_per_rsf_annual_cents"] <= 0:
        raise ApiError("ERR_FISCAL_INCOHERENT", 422,
                       "executed_rent_per_rsf_annual_cents must be strictly positive")

    # Check RENT_RESET_TO_MARKET acceptance
    rent_reset_accepted = False
    review = get_consent_review(transfer["id"])
    accepted_restoration_conditions = []
    if review is not None:
        for cond in get_conditions_for_review(review["id"]):
            if cond["condition_kind"] == "RENT_RESET_TO_MARKET" and cond["status"] == "ACCEPTED":
                rent_reset_accepted = True
            if cond["condition_kind"] == "RESTORATION_REQUIRED" and cond["status"] == "ACCEPTED":
                accepted_restoration_conditions.append(cond)

    if not rent_reset_accepted:
        if body["executed_rent_per_rsf_annual_cents"] != transfer["proposed_rent_per_rsf_annual_cents"]:
            raise ApiError("ERR_FISCAL_INCOHERENT", 422,
                           "executed_rent must equal proposed rent unless RENT_RESET_TO_MARKET was accepted")

    # Restoration allocations validation
    allocations = body.get("restoration_allocations", [])
    if accepted_restoration_conditions:
        if len(allocations) < len(accepted_restoration_conditions):
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "restoration_allocations must cover all accepted RESTORATION_REQUIRED conditions")
        for alloc in allocations[:len(accepted_restoration_conditions)]:
            if alloc["responsible_party"] != "TENANT" and alloc["escrow_amount_cents"] <= 0:
                raise ApiError("ERR_FISCAL_INCOHERENT", 422,
                               "escrow_amount_cents must be > 0 when responsible_party != TENANT")

    now = db.LOGICAL_CLOCK

    # Create SubleaseAgreement for SUBLEASE
    sublease_agreement_id = None
    if transfer["transfer_type"] == "SUBLEASE":
        sa = {
            "id": new_id(),
            "transfer_request_id": transfer["id"],
            "demised_area_id": certified["id"],
            "executed_rent_per_rsf_annual_cents": body["executed_rent_per_rsf_annual_cents"],
            "status": "EXECUTED",
            "executed_at": iso_logical(now),
        }
        new_common(sa)
        store.sublease_agreements[sa["id"]] = sa
        sublease_agreement_id = sa["id"]

    # Create RecognitionAgreement (always)
    ra = {
        "id": new_id(),
        "transfer_request_id": transfer["id"],
        "sublease_agreement_id": sublease_agreement_id,
        "landlord_signed_at": None,
        "counterparty_signed_at": None,
        "status": "DRAFTED",
    }
    new_common(ra)
    store.recognition_agreements[ra["id"]] = ra

    # Create RestorationObligations from accepted RESTORATION_REQUIRED conditions
    for i, cond in enumerate(accepted_restoration_conditions):
        alloc = allocations[i] if i < len(allocations) else {"responsible_party": "TENANT", "escrow_amount_cents": 0}
        ro = {
            "id": new_id(),
            "transfer_request_id": transfer["id"],
            "responsible_party": alloc["responsible_party"],
            "escrow_amount_cents": alloc["escrow_amount_cents"],
            "status": "OPEN",
            "completed_at": None,
        }
        new_common(ro)
        # Auto-advance to ESCROW_POSTED if escrow > 0
        if ro["escrow_amount_cents"] > 0:
            ro["status"] = "ESCROW_POSTED"
        store.restoration_obligations[ro["id"]] = ro

    # Recompute differential on documented basis if rent was reset
    if rent_reset_accepted:
        spread = body["executed_rent_per_rsf_annual_cents"] - lease["base_rent_per_rsf_annual_cents"]
        transfer["annual_rent_differential_cents"] = max(0, spread) * certified["rentable_sf"]

    # Transition transfer
    transfer["status"] = "DOCUMENTED"
    touch(transfer)

    receipt = {
        "transfer_request_id": transfer["id"],
        "sublease_agreement_id": sublease_agreement_id,
        "recognition_agreement_id": ra["id"],
    }
    return created(receipt)


# ---------------------------------------------------------------------------
# TransferRequest — reverse-reachability reads
# ---------------------------------------------------------------------------

@bp.get("/sublease-admin/transfer-requests/<transfer_id>/consent-review")
def get_transfer_consent_review(transfer_id):
    uid, role, _ = get_context()
    require_roles(ADMIN_READ)
    require_path_entity(store.transfer_requests, transfer_id)
    review = get_consent_review(transfer_id)
    rows = [review] if review else []
    return ok(paginate(rows), rtype="array", pagination=paginate)


@bp.get("/sublease-admin/transfer-requests/<transfer_id>/credit-review")
def get_transfer_credit_review(transfer_id):
    uid, role, _ = get_context()
    require_roles(ADMIN_READ)
    require_path_entity(store.transfer_requests, transfer_id)
    review = get_credit_review(transfer_id)
    rows = [review] if review else []
    return ok(paginate(rows), rtype="array", pagination=paginate)


@bp.get("/sublease-admin/transfer-requests/<transfer_id>/demised-areas")
def get_transfer_demised_areas(transfer_id):
    uid, role, _ = get_context()
    require_roles(ADMIN_READ)
    require_path_entity(store.transfer_requests, transfer_id)
    rows = [a for a in store.demised_areas.values()
            if a["transfer_request_id"] == transfer_id]
    return ok(paginate(rows), rtype="array", pagination=paginate)


@bp.get("/sublease-admin/transfer-requests/<transfer_id>/recognition-agreement")
def get_transfer_recognition_agreement(transfer_id):
    uid, role, _ = get_context()
    require_roles(ADMIN_READ)
    require_path_entity(store.transfer_requests, transfer_id)
    ra = get_recognition_agreement(transfer_id)
    rows = [ra] if ra else []
    return ok(paginate(rows), rtype="array", pagination=paginate)


@bp.get("/sublease-admin/transfer-requests/<transfer_id>/restoration-obligations")
def get_transfer_restoration_obligations(transfer_id):
    uid, role, _ = get_context()
    require_roles(ADMIN_READ)
    require_path_entity(store.transfer_requests, transfer_id)
    rows = [r for r in store.restoration_obligations.values()
            if r["transfer_request_id"] == transfer_id]
    return ok(paginate(rows), rtype="array", pagination=paginate)


@bp.get("/sublease-admin/transfer-requests/<transfer_id>/settlements")
def get_transfer_settlements(transfer_id):
    uid, role, _ = get_context()
    require_roles(ADMIN_READ)
    require_path_entity(store.transfer_requests, transfer_id)
    rows = [s for s in store.settlements.values()
            if s["transfer_request_id"] == transfer_id]
    return ok(paginate(rows), rtype="array", pagination=paginate)


# ---------------------------------------------------------------------------
# DemisedArea — create
# ---------------------------------------------------------------------------

@bp.post("/sublease-admin/transfer-requests/<transfer_id>/demised-areas")
def create_demised_area(transfer_id):
    uid, role, _ = get_context()
    require_roles(["TenantRepBroker"])
    body = parse_body({
        "measurement_standard": ("enum", True, ["METHOD_A", "METHOD_B"]),
        "usable_sf": ("integer", True, None),
        "supersedes_id": ("string", False, None),
    }, allow_empty=False)

    transfer = require_path_entity(store.transfer_requests, transfer_id)
    lease = store.leases[transfer["lease_id"]]
    building = store.buildings[lease["building_id"]]

    if body["usable_sf"] <= 0:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "usable_sf must be strictly positive")

    # Revision integrity
    supersedes_id = body.get("supersedes_id")
    if supersedes_id is not None:
        prior = store.demised_areas.get(supersedes_id)
        if prior is None:
            raise ApiError("ERR_NOT_FOUND", 404,
                           "Referenced DemisedArea not found: %s" % supersedes_id)
        if prior["status"] != "CERTIFIED" or prior["superseded_by_id"] is not None:
            raise ApiError("ERR_MEASUREMENT_SUPERSEDED", 409,
                           "Revision must chain off the current CERTIFIED tip")

    # Compute provisional values
    rentable_sf, prorata_share_bps, is_partial_floor = compute_measurement(
        body["usable_sf"], body["measurement_standard"],
        building["loss_factor_bps"], building["total_rentable_sf"],
        lease["leased_rsf"],
    )

    area = {
        "id": new_id(),
        "lease_id": transfer["lease_id"],
        "transfer_request_id": transfer["id"],
        "measurement_standard": body["measurement_standard"],
        "usable_sf": body["usable_sf"],
        "rentable_sf": rentable_sf,
        "prorata_share_bps": prorata_share_bps,
        "is_partial_floor": is_partial_floor,
        "supersedes_id": supersedes_id,
        "superseded_by_id": None,
        "status": "DRAFT",
    }
    new_common(area)
    store.demised_areas[area["id"]] = area
    return created(area)


# ---------------------------------------------------------------------------
# DemisedArea — read
# ---------------------------------------------------------------------------

def _recompute_if_draft(area):
    """Return a copy with recomputed values if DRAFT; otherwise return as-is."""
    if area["status"] != "DRAFT":
        return area
    lease = store.leases.get(area["lease_id"])
    if lease is None:
        return area
    building = store.buildings.get(lease["building_id"])
    if building is None:
        return area
    result = dict(area)
    rentable_sf, prorata_share_bps, is_partial_floor = compute_measurement(
        area["usable_sf"], area["measurement_standard"],
        building["loss_factor_bps"], building["total_rentable_sf"],
        lease["leased_rsf"],
    )
    result["rentable_sf"] = rentable_sf
    result["prorata_share_bps"] = prorata_share_bps
    result["is_partial_floor"] = is_partial_floor
    return result


@bp.get("/sublease-admin/demised-areas/<area_id>")
def get_demised_area(area_id):
    uid, role, _ = get_context()
    require_roles(ADMIN_READ)
    area = require_path_entity(store.demised_areas, area_id)
    return ok(_recompute_if_draft(area))


@bp.get("/sublease-admin/demised-areas")
def list_demised_areas():
    uid, role, _ = get_context()
    require_roles(ADMIN_READ)
    rows = [_recompute_if_draft(a) for a in store.demised_areas.values()]
    for f in ("lease_id", "transfer_request_id", "supersedes_id", "superseded_by_id", "status"):
        rows = paginate.filter(rows, f)
    return ok(paginate(rows), rtype="array", pagination=paginate)


# ---------------------------------------------------------------------------
# DemisedArea — certify
# ---------------------------------------------------------------------------

@bp.post("/sublease-admin/demised-areas/<area_id>/certify")
def certify_demised_area(area_id):
    uid, role, _ = get_context()
    require_roles(["TenantRepBroker"])
    area = require_path_entity(store.demised_areas, area_id)

    # Superseded records cannot be certified
    if area["status"] == "SUPERSEDED":
        raise ApiError("ERR_MEASUREMENT_SUPERSEDED", 409,
                       "Cannot certify a SUPERSEDED measurement")

    # Must be DRAFT
    if area["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Certify requires the measurement to be DRAFT")

    # Parent transfer must be in DRAFT, SUBMITTED, or CONSENT_PENDING
    transfer = store.transfer_requests.get(area["transfer_request_id"])
    if transfer is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Parent transfer not found")
    if transfer["status"] not in ("DRAFT", "SUBMITTED", "CONSENT_PENDING"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Certify requires the parent transfer in DRAFT, SUBMITTED, or CONSENT_PENDING")

    # Compute and freeze values
    lease = store.leases[area["lease_id"]]
    building = store.buildings[lease["building_id"]]
    rentable_sf, prorata_share_bps, is_partial_floor = compute_measurement(
        area["usable_sf"], area["measurement_standard"],
        building["loss_factor_bps"], building["total_rentable_sf"],
        lease["leased_rsf"],
    )
    area["rentable_sf"] = rentable_sf
    area["prorata_share_bps"] = prorata_share_bps
    area["is_partial_floor"] = is_partial_floor
    area["status"] = "CERTIFIED"
    touch(area)

    # Supersede prior record
    if area.get("supersedes_id"):
        prior = store.demised_areas.get(area["supersedes_id"])
        if prior is not None:
            prior["status"] = "SUPERSEDED"
            prior["superseded_by_id"] = area["id"]
            touch(prior)

    return ok(area)
