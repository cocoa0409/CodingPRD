"""Alterations, defaults, loss events, reversion, estoppel, sweep and clock."""

from flask import Blueprint

import auth
import calc
import cascades
import serialize
import store
import validate as v
from errors import ApiError
from response import object_response
from validate import rhu

bp = Blueprint("ops", __name__)

SCOPE_CODES = {"COSMETIC", "STRUCTURAL_ALTERATION", "REDEVELOPMENT"}
USE_CODES = {"RETAIL_MIXED", "INDUSTRIAL_LOGISTICS", "RESIDENTIAL_RENTAL",
             "LIFE_SCIENCE_LAB"}
DEFAULT_TYPES = {"MONETARY_RENT_ARREARS", "PERCENTAGE_RENT_UNDERPAYMENT",
                 "INSURANCE_LAPSE", "UNPERMITTED_USE", "UNAUTHORIZED_TRANSFER"}
MONETARY_GROUNDS = {"MONETARY_RENT_ARREARS", "PERCENTAGE_RENT_UNDERPAYMENT"}
EVENT_TYPES = {"CASUALTY", "CONDEMNATION"}
LOSS_SCOPES = {"TOTAL", "PARTIAL", "TEMPORARY"}
ALLOCATION_METHODS = {"BONUS_VALUE", "PRO_RATA_VALUE"}
STRUCTURAL_SCOPES = {"STRUCTURAL_ALTERATION", "REDEVELOPMENT"}


# ===========================================================================
# Alterations
# ===========================================================================
def _approved_windows(lease_id, exclude_id=None):
    rows = []
    for row in store.by_lease(store.alterations, lease_id):
        if row["status"] == "APPROVED" and row["id"] != exclude_id:
            rows.append(row)
    return rows


@bp.post("/leases/<lease_id>/alteration-requests")
def create_alteration(lease_id):
    lease = cascades.fetch("lease", lease_id)
    user_id, role = auth.require({"GroundTenant"})
    auth.owns_lease(user_id, role, lease)
    payload = v.body()

    scope_code = v.req_enum(payload, "scope_code", SCOPE_CODES)
    proposed_use = v.req_enum(payload, "proposed_use_code", USE_CODES)
    requested_gfa = v.req_area(payload, "requested_gfa_sqft")
    window_start = v.req_dt(payload, "construction_window_start")
    window_end = v.req_dt(payload, "construction_window_end")
    estimated_cost = v.req_money(payload, "estimated_cost_cents")

    cascades.require_operative(lease)

    for row in _approved_windows(lease_id):
        if cascades.overlaps(window_start, window_end,
                             row["construction_window_start"],
                             row["construction_window_end"]):
            raise ApiError("ERR_INTERVAL_OVERLAP",
                           "The construction window intersects a window "
                           "already approved on this lease.")

    if not window_start < window_end:
        raise ApiError("ERR_CHRONOLOGY_VIOLATION",
                       "construction_window_start must be strictly before "
                       "construction_window_end.")

    if proposed_use != lease["permitted_use_code"]:
        raise ApiError("ERR_USE_NOT_PERMITTED",
                       "The proposed use differs from the use the lease "
                       "permits.")

    record = {
        "lease_id": lease_id,
        "scope_code": scope_code,
        "proposed_use_code": proposed_use,
        "requested_gfa_sqft": requested_gfa,
        "construction_window_start": window_start,
        "construction_window_end": window_end,
        "estimated_cost_cents": estimated_cost,
        "status": "SUBMITTED",
        "decided_by_user_id": None,
    }
    store.stamp(record)
    store.alterations[record["id"]] = record
    return object_response(serialize.alteration(record), 201)


@bp.post("/alteration-requests/<alteration_id>/decision")
def decide_alteration(alteration_id):
    alteration = cascades.fetch("alteration", alteration_id)
    user_id, role = auth.require({"AssetManager"})
    payload = v.body()
    decision = v.req_enum(payload, "decision", {"APPROVE", "REJECT"})
    v.opt_str(payload, "conditions_note", default=None, max_len=2000)
    lease = store.leases.get(alteration["lease_id"])

    if alteration["status"] != "SUBMITTED":
        raise cascades.invalid_state(
            "The alteration request is in %s and cannot be decided."
            % alteration["status"]
        )

    if decision == "REJECT":
        # Nothing else moves: the envelope and the lease are untouched.
        alteration["status"] = "REJECTED"
        alteration["decided_by_user_id"] = user_id
        store.touch(alteration)
        return object_response(serialize.alteration(alteration), 200)

    if lease is None or lease["lease_status"] != "ACTIVE":
        raise cascades.invalid_state(
            "Approval requires the lease tenancy axis to be exactly ACTIVE."
        )

    for event in store.by_lease(store.loss_events, lease["id"]):
        if (event["event_type"] == "CASUALTY"
                and event["status"] in ("REPORTED", "ADJUSTED")):
            raise ApiError("ERR_CROSS_ENTITY_BLOCKED",
                           "An open casualty on the lease blocks new "
                           "alteration consent.")

    for row in _approved_windows(lease["id"], exclude_id=alteration["id"]):
        if cascades.overlaps(alteration["construction_window_start"],
                             alteration["construction_window_end"],
                             row["construction_window_start"],
                             row["construction_window_end"]):
            raise ApiError("ERR_INTERVAL_OVERLAP",
                           "The construction window intersects a window "
                           "already approved on this lease.")

    if alteration["requested_gfa_sqft"] > lease["gfa_unallocated_sqft"]:
        raise ApiError("ERR_GFA_ENVELOPE_EXCEEDED",
                       "The development envelope cannot accommodate the "
                       "requested area.")

    if alteration["proposed_use_code"] != lease["permitted_use_code"]:
        raise ApiError("ERR_USE_NOT_PERMITTED",
                       "The proposed use no longer matches the use in force "
                       "under the lease.")

    if alteration["scope_code"] in STRUCTURAL_SCOPES:
        expires_at = lease.get("insurance_expires_at")
        if (lease["insurance_status"] != "ACTIVE"
                or not lease["lessor_additional_insured"]
                or lease["builders_risk_limit_cents"]
                < alteration["estimated_cost_cents"]
                or expires_at is None
                or expires_at < alteration["construction_window_end"]):
            raise ApiError("ERR_INSURANCE_DEFICIENT",
                           "Builders-risk cover is not in place for the whole "
                           "construction window.")

    alteration["status"] = "APPROVED"
    alteration["decided_by_user_id"] = user_id
    store.touch(alteration)

    lease["gfa_allocated_sqft"] = (
        lease["gfa_allocated_sqft"] + alteration["requested_gfa_sqft"]
    )
    cascades.rederive_envelope(lease)
    store.touch(lease)
    return object_response(serialize.alteration(alteration), 200)


@bp.post("/alteration-requests/<alteration_id>/revoke-approval")
def revoke_alteration(alteration_id):
    alteration = cascades.fetch("alteration", alteration_id)
    auth.require({"AssetManager"})
    payload = v.body()
    v.req_str(payload, "reason_code")
    lease = store.leases.get(alteration["lease_id"])

    if alteration["status"] != "APPROVED":
        raise cascades.invalid_state(
            "Only an APPROVED alteration request can have its approval "
            "revoked; this one is in %s." % alteration["status"]
        )
    if lease is None or lease["lease_status"] not in ("ACTIVE", "IN_DEFAULT"):
        raise cascades.invalid_state(
            "Revocation requires the lease tenancy axis to be ACTIVE or "
            "IN_DEFAULT."
        )

    alteration["status"] = "APPROVAL_REVOKED"
    store.touch(alteration)

    lease["gfa_allocated_sqft"] = (
        lease["gfa_allocated_sqft"] - alteration["requested_gfa_sqft"]
    )
    cascades.rederive_envelope(lease)
    store.touch(lease)
    return object_response(serialize.alteration(alteration), 200)


# ===========================================================================
# Default notices
# ===========================================================================
def _serve_notice(lease, default_type, claimed_amount, served_by_user_id):
    """Shared by hand service and by sweep phase one."""
    served_at = store.now()
    mortgage_rows = cascades.lease_mortgages(lease["id"])
    lessee_deadline, mortgagee_deadline = calc.cure_deadlines(
        served_at, default_type, mortgage_rows
    )

    record = {
        "lease_id": lease["id"],
        "default_type": default_type,
        "claimed_amount_cents": claimed_amount,
        "served_at": served_at,
        "served_by_user_id": served_by_user_id,
        "mortgagee_notified_at": served_at,
        "lessee_cure_deadline": lessee_deadline,
        "mortgagee_cure_deadline": mortgagee_deadline,
        "status": "SERVED",
        "cured_by": None,
        "terminated_by_user_id": None,
    }
    store.stamp(record)
    store.notices[record["id"]] = record

    for mortgage in mortgage_rows:
        if mortgage["status"] == "RECORDED":
            mortgage["status"] = "NOTICE_SERVED"
            mortgage["mortgagee_notified_at"] = served_at
            store.touch(mortgage)

    lease["lease_status"] = "IN_DEFAULT"
    store.touch(lease)
    return record


@bp.post("/leases/<lease_id>/default-notices")
def serve_default_notice(lease_id):
    lease = cascades.fetch("lease", lease_id)
    user_id, role = auth.require({"AssetManager", "LeaseAccountant"})
    payload = v.body()
    default_type = v.req_enum(payload, "default_type", DEFAULT_TYPES)
    claimed_amount = v.opt_money(payload, "claimed_amount_cents", 0)

    if lease["lease_status"] in cascades.NON_OPERATIVE:
        cascades.require_operative(lease)
    if lease["lease_status"] != "ACTIVE":
        raise cascades.invalid_state(
            "Service of a default notice requires the lease tenancy axis to "
            "be exactly ACTIVE."
        )
    if default_type in MONETARY_GROUNDS:
        if claimed_amount <= 0:
            raise cascades.invalid_state(
                "A monetary ground requires claimed_amount_cents strictly "
                "greater than 0."
            )
        if claimed_amount > lease["arrears_balance_cents"]:
            raise cascades.invalid_state(
                "claimed_amount_cents may not exceed the lease arrears "
                "balance of %d cents." % lease["arrears_balance_cents"]
            )
    if default_type == "INSURANCE_LAPSE" and lease["insurance_status"] != "LAPSED":
        raise cascades.invalid_state(
            "An INSURANCE_LAPSE ground requires the lease insurance_status to "
            "be LAPSED."
        )
    for mortgage in cascades.lease_mortgages(lease_id):
        if mortgage["status"] == "RECORDED" and not (
                mortgage.get("notice_email") or "").strip():
            raise cascades.invalid_state(
                "Every mortgage still in RECORDED must carry a notice_email "
                "before a default may be served."
            )

    record = _serve_notice(lease, default_type, claimed_amount, user_id)
    return object_response(serialize.notice(record), 201)


@bp.post("/default-notices/<notice_id>/lessee-cure")
def lessee_cure(notice_id):
    notice = cascades.fetch("notice", notice_id)
    lease = store.leases.get(notice["lease_id"])
    user_id, role = auth.require({"GroundTenant"})
    auth.owns_lease(user_id, role, lease)
    payload = v.body()
    payment_at = v.opt_dt(payload, "payment_at")
    cure_amount = v.opt_money(payload, "cure_amount_cents", 0)

    if notice["status"] != "SERVED":
        raise cascades.invalid_state(
            "The notice is in %s and cannot be cured by the tenant."
            % notice["status"]
        )

    if payment_at is not None and payment_at < notice["served_at"]:
        raise ApiError("ERR_CHRONOLOGY_VIOLATION",
                       "payment_at must be at or after the notice served_at.")

    if store.now() > notice["lessee_cure_deadline"]:
        raise ApiError("ERR_CURE_WINDOW_CLOSED",
                       "The tenant cure window has closed.")

    monetary = notice["default_type"] in MONETARY_GROUNDS
    if monetary and cure_amount < lease["arrears_balance_cents"]:
        raise cascades.invalid_state(
            "A monetary cure must clear the ledger: cure_amount_cents must be "
            "at least the arrears balance of %d cents."
            % lease["arrears_balance_cents"]
        )
    if (notice["default_type"] == "INSURANCE_LAPSE"
            and lease["insurance_status"] != "ACTIVE"):
        raise cascades.invalid_state(
            "An INSURANCE_LAPSE cure requires a fresh endorsement restoring "
            "insurance_status to ACTIVE."
        )

    notice["status"] = "LESSEE_CURED"
    notice["cured_by"] = "LESSEE"
    store.touch(notice)

    if monetary:
        remaining = lease["arrears_balance_cents"] - cure_amount
        lease["arrears_balance_cents"] = max(0, remaining)
    lease["lease_status"] = "ACTIVE"
    store.touch(lease)

    # The tenant cured before the lender had to act: the register keeps no
    # trace of a served notice.
    for mortgage in cascades.lease_mortgages(lease["id"]):
        if mortgage["status"] in ("NOTICE_SERVED", "CURING"):
            mortgage["status"] = "RECORDED"
            mortgage["mortgagee_notified_at"] = None
            store.touch(mortgage)

    return object_response(serialize.notice(notice), 200)


@bp.post("/default-notices/<notice_id>/mortgagee-cure")
def mortgagee_cure(notice_id):
    notice = cascades.fetch("notice", notice_id)
    payload = v.body()
    mortgage = None
    if v.fk_present(payload, "mortgage_id"):
        mortgage = cascades.fetch("mortgage", v.fk_value(payload, "mortgage_id"))

    auth.require({"MortgageeAgent"})

    action = v.req_enum(payload, "action", {"ELECT", "COMPLETE"})
    v.req_str(payload, "mortgage_id")
    cure_amount = v.opt_money(payload, "cure_amount_cents", 0)
    lease = store.leases.get(notice["lease_id"])

    if mortgage["lease_id"] != notice["lease_id"]:
        raise ApiError("ERR_MORTGAGE_LEASE_MISMATCH",
                       "That mortgage does not encumber the notice's lease.")

    if action == "ELECT":
        if notice["status"] != "LESSEE_CURE_LAPSED":
            raise cascades.invalid_state(
                "A mortgagee cure election requires the notice to be in "
                "LESSEE_CURE_LAPSED; it is in %s." % notice["status"]
            )
        if mortgage["status"] != "NOTICE_SERVED":
            raise cascades.invalid_state(
                "The electing mortgage must be in NOTICE_SERVED; it is in %s."
                % mortgage["status"]
            )
    else:
        if notice["status"] != "MORTGAGEE_CURING":
            raise cascades.invalid_state(
                "Completion requires the notice to be in MORTGAGEE_CURING; it "
                "is in %s." % notice["status"]
            )

    deadline = notice.get("mortgagee_cure_deadline")
    if deadline is not None and store.now() > deadline:
        raise ApiError("ERR_CURE_WINDOW_CLOSED",
                       "The mortgagee cure window has closed.")

    if action == "ELECT":
        notice["status"] = "MORTGAGEE_CURING"
        store.touch(notice)
        mortgage["status"] = "CURING"
        store.touch(mortgage)
        return object_response(serialize.notice(notice), 200)

    monetary = notice["default_type"] in MONETARY_GROUNDS
    if monetary and cure_amount < lease["arrears_balance_cents"]:
        raise cascades.invalid_state(
            "A monetary cure must clear the ledger: cure_amount_cents must be "
            "at least the arrears balance of %d cents."
            % lease["arrears_balance_cents"]
        )

    notice["status"] = "MORTGAGEE_CURED"
    notice["cured_by"] = "MORTGAGEE"
    store.touch(notice)

    # Engaged and cured: mortgagee_notified_at is left in place.
    mortgage["status"] = "RECORDED"
    store.touch(mortgage)

    if monetary:
        lease["arrears_balance_cents"] = max(
            0, lease["arrears_balance_cents"] - cure_amount
        )
    lease["lease_status"] = "ACTIVE"
    store.touch(lease)
    return object_response(serialize.notice(notice), 200)


@bp.post("/default-notices/<notice_id>/terminate")
def terminate_on_default(notice_id):
    notice = cascades.fetch("notice", notice_id)
    user_id, role = auth.require({"AssetManager", "LeaseAccountant"})
    lease = store.leases.get(notice["lease_id"])

    if lease is None or lease["lease_status"] != "IN_DEFAULT":
        raise cascades.invalid_state(
            "Termination requires the lease tenancy axis to be IN_DEFAULT."
        )
    if notice["status"] == "MORTGAGEE_CURE_LAPSED":
        pass
    elif notice["status"] == "LESSEE_CURE_LAPSED":
        encumbered = [
            m for m in cascades.lease_mortgages(lease["id"])
            if m["status"] in ("RECORDED", "NOTICE_SERVED", "CURING")
        ]
        if encumbered:
            raise cascades.invalid_state(
                "An encumbered lease must give its lender the mortgagee cure "
                "window before termination."
            )
    else:
        raise cascades.invalid_state(
            "The notice is in %s and is not terminable." % notice["status"]
        )

    if user_id == notice["served_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "The user who served the notice may not terminate on "
                       "it.")

    effective_at = store.now()
    notice["status"] = "TERMINATION_EFFECTED"
    notice["terminated_by_user_id"] = user_id
    store.touch(notice)
    cascades.terminate_lease(lease, effective_at)
    return object_response(serialize.notice(notice), 200)


# ===========================================================================
# Casualty, condemnation and the proceeds waterfall
# ===========================================================================
@bp.post("/leases/<lease_id>/loss-events")
def report_loss_event(lease_id):
    lease = cascades.fetch("lease", lease_id)
    user_id, role = auth.require({"GroundTenant", "AssetManager"})
    auth.owns_lease(user_id, role, lease)
    payload = v.body()

    event_type = v.req_enum(payload, "event_type", EVENT_TYPES)
    scope_code = v.req_enum(payload, "scope_code", LOSS_SCOPES)
    occurred_at = v.req_dt(payload, "occurred_at")
    damage_estimate = v.opt_money(payload, "damage_estimate_cents", 0)
    damaged_area = v.opt_area(payload, "damaged_area_sqft", 0)

    record = {
        "lease_id": lease_id,
        "event_type": event_type,
        "scope_code": scope_code,
        "occurred_at": occurred_at,
        "damage_estimate_cents": damage_estimate,
        "damaged_area_sqft": damaged_area,
        "distributable_pool_cents": None,
        "allocation_method": None,
        "status": "REPORTED",
        "rent_abatement_bps": None,
        "allocated_arrears_cents": 0,
        "allocated_mortgagee_cents": 0,
        "allocated_lessee_cents": 0,
        "allocated_lessor_cents": 0,
        "lessee_share_bps": None,
        "allocation_detail": [],
    }
    store.stamp(record)
    store.loss_events[record["id"]] = record
    return object_response(serialize.loss_event(record), 201)


@bp.post("/loss-events/<event_id>/adjust")
def adjust_loss_event(event_id):
    event = cascades.fetch("loss_event", event_id)
    auth.require({"AssetManager"})
    payload = v.body()
    pool = v.req_money(payload, "distributable_pool_cents")
    method = v.req_enum(payload, "allocation_method", ALLOCATION_METHODS)
    abatement = v.opt_bps(payload, "rent_abatement_bps")
    lease = store.leases.get(event["lease_id"])

    if event["status"] != "REPORTED":
        raise cascades.invalid_state(
            "The loss event is in %s and cannot be adjusted." % event["status"]
        )
    if pool <= 0:
        raise ApiError("ERR_AMOUNT_NOT_RECONCILED",
                       "distributable_pool_cents must be greater than 0.")
    if event["event_type"] == "CASUALTY":
        if lease["insurance_status"] != "ACTIVE":
            raise ApiError("ERR_INSURANCE_DEFICIENT",
                           "A casualty adjustment requires insurance_status "
                           "ACTIVE.")
        if pool > lease["property_all_risk_limit_cents"]:
            raise ApiError("ERR_INSURANCE_DEFICIENT",
                           "The pool exceeds the property all-risk limit "
                           "carried by the policy.")

    event["distributable_pool_cents"] = pool
    event["allocation_method"] = method
    event["rent_abatement_bps"] = abatement
    event["status"] = "ADJUSTED"
    store.touch(event)
    return object_response(serialize.loss_event(event), 200)


@bp.post("/loss-events/<event_id>/election")
def elect_on_loss_event(event_id):
    event = cascades.fetch("loss_event", event_id)
    lease = store.leases.get(event["lease_id"])
    user_id, role = auth.require({"GroundTenant"})
    auth.owns_lease(user_id, role, lease)
    payload = v.body()
    election = v.req_enum(payload, "election", {"RESTORE", "TERMINATE"})

    if event["status"] != "ADJUSTED":
        raise cascades.invalid_state(
            "The loss event is in %s and carries no election." % event["status"]
        )
    if event["event_type"] != "CASUALTY":
        raise ApiError("ERR_ELECTION_NOT_AVAILABLE",
                       "A condemnation is involuntary and carries no "
                       "restoration-or-termination election.")

    if election == "RESTORE":
        event["rent_abatement_bps"] = calc.rent_abatement_bps(
            event["damaged_area_sqft"] or 0, lease["total_permitted_gfa_sqft"]
        )
        event["status"] = "RESTORATION_ELECTED"
        store.touch(event)
        return object_response(serialize.loss_event(event), 200)

    if not calc.casualty_termination_available(
            event["damage_estimate_cents"] or 0,
            lease["improvements_value_cents"]):
        raise ApiError("ERR_ELECTION_NOT_AVAILABLE",
                       "The damage estimate is below half of the agreed "
                       "improvements value.")

    event["rent_abatement_bps"] = None
    event["status"] = "TERMINATION_ELECTED"
    store.touch(event)
    cascades.terminate_lease(lease, store.now())
    return object_response(serialize.loss_event(event), 200)


@bp.post("/loss-events/<event_id>/allocate")
def allocate_proceeds(event_id):
    event = cascades.fetch("loss_event", event_id)
    auth.require({"LeaseAccountant"})
    lease = store.leases.get(event["lease_id"])

    available = (
        (event["event_type"] == "CONDEMNATION" and event["status"] == "ADJUSTED")
        or (event["event_type"] == "CASUALTY"
            and event["status"] == "RESTORATION_ELECTED")
        or event["status"] == "ALLOCATION_RESCINDED"
    )
    if not available:
        raise cascades.invalid_state(
            "The loss event is in %s and the waterfall is not available."
            % event["status"]
        )

    pool = event.get("distributable_pool_cents")
    if pool is None or pool <= 0:
        raise ApiError("ERR_AMOUNT_NOT_RECONCILED",
                       "distributable_pool_cents must be non-null and greater "
                       "than 0 before the waterfall can run.")

    remaining = pool

    # Bucket one -- the lessor's arrears.
    arrears_paid = min(remaining, lease["arrears_balance_cents"])
    remaining -= arrears_paid
    lease["arrears_balance_cents"] = lease["arrears_balance_cents"] - arrears_paid

    # Bucket two -- mortgage payoff, in recording priority.
    payable = [
        m for m in cascades.lease_mortgages(lease["id"])
        if m["status"] in ("RECORDED", "NOTICE_SERVED", "CURING",
                           "NEW_LEASE_ELIGIBLE")
    ]
    payable = cascades.mortgages_by_priority(payable)
    detail = []
    prior_statuses = {}
    for mortgage in payable:
        prior_statuses[mortgage["id"]] = mortgage["status"]
        payment = min(remaining, mortgage["outstanding_principal_cents"])
        remaining -= payment
        # A low-priority mortgage can legitimately record a 0-cent entry.
        detail.append({"mortgage_id": mortgage["id"], "amount_cents": payment})
        mortgage["outstanding_principal_cents"] = (
            mortgage["outstanding_principal_cents"] - payment
        )
        if mortgage["outstanding_principal_cents"] == 0:
            mortgage["status"] = "EXTINGUISHED"
        store.touch(mortgage)
    mortgagee_total = sum(entry["amount_cents"] for entry in detail)

    # Bucket three -- the lessee's improvements share, computed on the full
    # pool and only then capped by what remains.
    share_bps = calc.lessee_share_bps(event, lease)
    indicated = rhu(pool * share_bps, 10000)
    lessee_paid = min(remaining, indicated)
    remaining -= lessee_paid

    # Bucket four -- the lessor's residual absorbs every remaining cent.
    lessor_paid = remaining

    event["lessee_share_bps"] = share_bps
    event["allocated_arrears_cents"] = arrears_paid
    event["allocated_mortgagee_cents"] = mortgagee_total
    event["allocated_lessee_cents"] = lessee_paid
    event["allocated_lessor_cents"] = lessor_paid
    event["allocation_detail"] = detail
    event["_pre_alloc_statuses"] = prior_statuses
    event["status"] = "ALLOCATED"
    store.touch(event)
    store.touch(lease)
    return object_response(serialize.loss_event(event), 200)


@bp.post("/loss-events/<event_id>/rescind-allocation")
def rescind_allocation(event_id):
    event = cascades.fetch("loss_event", event_id)
    auth.require({"LeaseAccountant"})
    payload = v.body()
    v.req_str(payload, "reason_code")
    lease = store.leases.get(event["lease_id"])

    if event["status"] != "ALLOCATED":
        raise cascades.invalid_state(
            "Only an ALLOCATED loss event can be rescinded; this one is in %s."
            % event["status"]
        )

    lease["arrears_balance_cents"] = (
        lease["arrears_balance_cents"] + (event["allocated_arrears_cents"] or 0)
    )

    prior_statuses = event.get("_pre_alloc_statuses") or {}
    for entry in reversed(event.get("allocation_detail") or []):
        mortgage = store.mortgages.get(entry["mortgage_id"])
        if mortgage is None:
            continue
        mortgage["outstanding_principal_cents"] = (
            mortgage["outstanding_principal_cents"] + entry["amount_cents"]
        )
        restored = prior_statuses.get(mortgage["id"])
        if restored is not None:
            mortgage["status"] = restored
        store.touch(mortgage)

    event["allocated_arrears_cents"] = 0
    event["allocated_mortgagee_cents"] = 0
    event["allocated_lessee_cents"] = 0
    event["allocated_lessor_cents"] = 0
    event["lessee_share_bps"] = None
    event["allocation_detail"] = []
    event["_pre_alloc_statuses"] = {}
    event["status"] = "ALLOCATION_RESCINDED"
    store.touch(event)
    store.touch(lease)
    return object_response(serialize.loss_event(event), 200)


# ===========================================================================
# Reversion
# ===========================================================================
@bp.post("/leases/<lease_id>/reversion-assessments")
def open_reversion_assessment(lease_id):
    lease = cascades.fetch("lease", lease_id)
    auth.require({"AssetManager"})

    if cascades.assessment_for_lease(lease_id) is not None:
        raise ApiError("ERR_DUPLICATE_RECORD",
                       "That lease already carries a reversion assessment.")

    record = cascades.open_assessment(lease)
    return object_response(serialize.assessment(record), 201)


@bp.post("/reversion-assessments/<assessment_id>/inspection")
def record_inspection(assessment_id):
    assessment = cascades.fetch("assessment", assessment_id)
    user_id, role = auth.require({"AssetManager"})
    payload = v.body()
    structural = v.req_score(payload, "structural_condition_score")
    envelope = v.req_score(payload, "envelope_condition_score")
    systems = v.req_score(payload, "systems_condition_score")

    if assessment["status"] != "PENDING_INSPECTION":
        raise cascades.invalid_state(
            "The assessment is in %s and cannot record an inspection."
            % assessment["status"]
        )

    weighted = calc.weighted_condition_score_bps(
        assessment["required_standard_code"], structural, envelope, systems
    )
    assessment["structural_condition_score"] = structural
    assessment["envelope_condition_score"] = envelope
    assessment["systems_condition_score"] = systems
    assessment["inspected_by_user_id"] = user_id
    assessment["weighted_score_bps"] = weighted
    assessment["deficiency_bps"] = 10000 - weighted
    assessment["status"] = "INSPECTED"
    store.touch(assessment)
    return object_response(serialize.assessment(assessment), 200)


@bp.post("/reversion-assessments/<assessment_id>/holdback")
def apply_holdback(assessment_id):
    assessment = cascades.fetch("assessment", assessment_id)
    user_id, role = auth.require({"LeaseAccountant", "AssetManager"})
    payload = v.body()
    acknowledged = v.req_money(payload, "acknowledged_holdback_cents")
    lease = store.leases.get(assessment["lease_id"])

    if assessment["status"] != "INSPECTED":
        raise cascades.invalid_state(
            "A holdback requires the assessment to be INSPECTED; it is in %s."
            % assessment["status"]
        )
    passing = calc.passing_score_bps(assessment["required_standard_code"])
    if assessment["weighted_score_bps"] >= passing:
        raise ApiError("ERR_STANDARD_MET_NO_HOLDBACK",
                       "The premises met the condition standard; no holdback "
                       "may be applied.")
    if user_id == assessment["inspected_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "The inspector may not apply the holdback.")

    computed = calc.holdback_cents(
        lease["deposit_held_cents"], lease["improvements_value_cents"],
        assessment["deficiency_bps"],
    )
    if acknowledged != computed:
        raise ApiError(
            "ERR_AMOUNT_NOT_RECONCILED",
            "acknowledged_holdback_cents must equal the computed holdback of "
            "%d cents exactly." % computed,
        )

    assessment["holdback_cents"] = computed
    assessment["status"] = "HOLDBACK_APPLIED"
    store.touch(assessment)

    lease["deposit_applied_cents"] = lease["deposit_applied_cents"] + computed
    lease["deposit_held_cents"] = lease["deposit_held_cents"] - computed
    store.touch(lease)
    return object_response(serialize.assessment(assessment), 200)


@bp.post("/reversion-assessments/<assessment_id>/close")
def close_reversion(assessment_id):
    assessment = cascades.fetch("assessment", assessment_id)
    auth.require({"AssetManager"})
    lease = store.leases.get(assessment["lease_id"])

    if assessment["status"] == "INSPECTED":
        passing = calc.passing_score_bps(assessment["required_standard_code"])
        if assessment["weighted_score_bps"] < passing:
            raise cascades.invalid_state(
                "The premises fell short of the standard; a holdback must be "
                "applied before the reversion can be closed."
            )
    elif assessment["status"] != "HOLDBACK_APPLIED":
        raise cascades.invalid_state(
            "The assessment is in %s and cannot be closed."
            % assessment["status"]
        )
    if lease is None or lease["lease_status"] != "EXPIRED":
        raise cascades.invalid_state(
            "Closing the reversion requires the lease tenancy axis to be "
            "EXPIRED."
        )

    released = lease["deposit_held_cents"]
    assessment["deposit_released_cents"] = released
    assessment["status"] = "CLOSED"
    store.touch(assessment)

    lease["deposit_refunded_cents"] = lease["deposit_refunded_cents"] + released
    lease["deposit_held_cents"] = 0
    lease["lease_status"] = "REVERTED"
    store.touch(lease)
    return object_response(serialize.assessment(assessment), 200)


# ===========================================================================
# Estoppel certificates
# ===========================================================================
@bp.post("/estoppel-certificates")
def issue_certificate():
    payload = v.body()
    lease = None
    mortgage = None
    if v.fk_present(payload, "lease_id"):
        lease = cascades.fetch("lease", v.fk_value(payload, "lease_id"))
    if v.fk_present(payload, "requested_by_mortgage_id"):
        mortgage = cascades.fetch(
            "mortgage", v.fk_value(payload, "requested_by_mortgage_id"))

    user_id, role = auth.require({"LessorAdmin", "MortgageeAgent"})

    lease_id = v.req_str(payload, "lease_id")
    mortgage_id = v.req_str(payload, "requested_by_mortgage_id")
    expected_version = v.req_int(payload, "expected_lease_version")

    if mortgage["lease_id"] != lease_id:
        raise ApiError("ERR_MORTGAGE_LEASE_MISMATCH",
                       "That mortgage encumbers a different lease.")

    if expected_version != lease["version"]:
        raise ApiError(
            "ERR_STALE_LEASE_VERSION",
            "expected_lease_version %d does not match the lease version %d."
            % (expected_version, lease["version"]),
        )

    for revaluation in store.by_lease(store.revaluations, lease_id):
        if revaluation["status"] == "ARBITRATION_REFERRED":
            raise ApiError("ERR_CROSS_ENTITY_BLOCKED",
                           "The rent is under arbitration; no certificate may "
                           "be issued.")

    expires_at = lease.get("insurance_expires_at")
    if (lease["insurance_status"] == "LAPSED"
            or expires_at is None or expires_at <= store.now()):
        raise ApiError("ERR_INSURANCE_DEFICIENT",
                       "The lease insurance is deficient; no certificate may "
                       "be issued.")

    issued_at = store.now()
    # The lease is written by the issuance, so its version advances first and
    # the certificate records the post-increment figure.
    store.touch(lease)

    for existing in store.by_lease(store.certificates, lease_id):
        if (existing["requested_by_mortgage_id"] == mortgage_id
                and existing["status"] == "ISSUED"):
            existing["status"] = "SUPERSEDED"
            store.touch(existing)

    record = {
        "lease_id": lease_id,
        "requested_by_mortgage_id": mortgage_id,
        "certified_annual_base_rent_cents":
            lease["current_annual_base_rent_cents"],
        "certified_arrears_cents": lease["arrears_balance_cents"],
        "certified_rent_status": lease["rent_status"],
        "certified_lease_version": lease["version"],
        "status": "ISSUED",
        "issued_at": issued_at,
        "issued_by_user_id": user_id,
    }
    store.stamp(record)
    store.certificates[record["id"]] = record
    return object_response(serialize.certificate(record), 201)


# ===========================================================================
# The scheduled administration sweep
# ===========================================================================
@bp.post("/administration-runs")
def administration_run():
    auth.require({"LessorAdmin"})
    now = store.now()

    counts = {
        "insurance_lapses_raised": 0,
        "cure_windows_lapsed": 0,
        "revaluations_flagged": 0,
        "mortgages_extinguished": 0,
        "leases_expired": 0,
    }
    affected = []

    def mark(lease_id):
        if lease_id not in affected:
            affected.append(lease_id)

    # Phase one -- insurance.
    for lease in store.sort_rows(list(store.leases.values())):
        expires_at = lease.get("insurance_expires_at")
        if (lease["lease_status"] == "ACTIVE" and expires_at is not None
                and expires_at <= now):
            lease["insurance_status"] = "LAPSED"
            _serve_notice(lease, "INSURANCE_LAPSE", 0, "SYSTEM")
            counts["insurance_lapses_raised"] += 1
            mark(lease["id"])

    # Phase two -- cure windows.
    for notice in store.sort_rows(list(store.notices.values())):
        if (notice["status"] == "SERVED"
                and now > notice["lessee_cure_deadline"]):
            notice["status"] = "LESSEE_CURE_LAPSED"
            store.touch(notice)
            counts["cure_windows_lapsed"] += 1
            mark(notice["lease_id"])
        deadline = notice.get("mortgagee_cure_deadline")
        if (notice["status"] in ("LESSEE_CURE_LAPSED", "MORTGAGEE_CURING")
                and deadline is not None and now > deadline):
            notice["status"] = "MORTGAGEE_CURE_LAPSED"
            store.touch(notice)
            counts["cure_windows_lapsed"] += 1
            mark(notice["lease_id"])

    # Phase three -- revaluation diary.
    for lease in store.sort_rows(list(store.leases.values())):
        if (lease["rent_status"] in ("BASE_ONLY", "RESET_APPLIED")
                and lease["next_revaluation_date"] is not None
                and lease["next_revaluation_date"] <= now):
            lease["rent_status"] = "REVALUATION_DUE"
            store.touch(lease)
            counts["revaluations_flagged"] += 1
            mark(lease["id"])

    # Phase four -- election windows.
    for mortgage in store.sort_rows(list(store.mortgages.values())):
        deadline = mortgage.get("new_lease_election_deadline")
        if (mortgage["status"] == "NEW_LEASE_ELIGIBLE"
                and deadline is not None and now > deadline):
            mortgage["status"] = "EXTINGUISHED"
            store.touch(mortgage)
            counts["mortgages_extinguished"] += 1
            mark(mortgage["lease_id"])

    # Phase five -- expiry.
    for lease in store.sort_rows(list(store.leases.values())):
        if (lease["lease_status"] in ("ACTIVE", "IN_DEFAULT")
                and lease["expiration_date"] is not None
                and lease["expiration_date"] <= now):
            cascades.expire_lease(lease)
            if cascades.assessment_for_lease(lease["id"]) is None:
                cascades.open_assessment(lease)
            counts["leases_expired"] += 1
            mark(lease["id"])

    data = {"run_at": store.iso(now)}
    data.update(counts)
    data["affected_lease_ids"] = affected
    return object_response(data, 200)
