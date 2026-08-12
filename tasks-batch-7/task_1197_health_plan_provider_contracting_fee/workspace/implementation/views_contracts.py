"""Contract lifecycle, amendment versions, paid-claim ledger loads,
termination notice creation, and the per-contract audit trail."""

from flask import Blueprint

import store
from bodycheck import DATE, INT, STR, parse_date, validate_body
from envelope import ok, ok_list
from errors import ApiError
from helpers import get_contract, sorted_by_created
from pricing import notice_period_valid, parity_check
from security import (
    ALL_ROLES, INTERNAL_ROLES, ROLE_CONTRACT_LEGAL, ROLE_CONTRACT_MANAGER,
    ROLE_CONFIG_ANALYST, ROLE_PAYMENT_INTEGRITY, ROLE_PLAN_ADMIN,
    auth, check_ownership, require_roles,
)

bp = Blueprint("contracts", __name__)


def _invalid_contract_state(action):
    return ApiError(
        "ERR_CONTRACT_INVALID_STATE", 409,
        f"Contract state does not permit {action}.",
    )


def _bump_and_audit(contract, role, user_id, event_type, detail):
    store.touch(contract)
    store.add_audit(contract["id"], event_type, role, user_id, detail)


# ---------------------------------------------------------------------------
# Read one contract
# ---------------------------------------------------------------------------
@bp.get("/contracts/<cid>")
def get_one_contract(cid):
    user_id, role = auth()
    require_roles(role, ALL_ROLES)
    contract = get_contract(cid)
    check_ownership(role, user_id, contract["provider_id"])
    return ok(dict(contract))


# ---------------------------------------------------------------------------
# Negotiation cycle and segregated signature
# ---------------------------------------------------------------------------
@bp.post("/contracts/<cid>/begin-negotiation")
def begin_negotiation(cid):
    validate_body({})
    user_id, role = auth()
    require_roles(role, [ROLE_CONTRACT_MANAGER])
    contract = get_contract(cid)
    if contract["contract_status"] != "DRAFT":
        raise _invalid_contract_state("begin-negotiation")
    contract["contract_status"] = "IN_NEGOTIATION"
    _bump_and_audit(contract, role, user_id, "CONTRACT_NEGOTIATION_STARTED",
                    "Contract moved from DRAFT to IN_NEGOTIATION.")
    return ok(dict(contract))


@bp.post("/contracts/<cid>/submit-for-signature")
def submit_for_signature(cid):
    validate_body({})
    user_id, role = auth()
    require_roles(role, [ROLE_CONTRACT_MANAGER])
    contract = get_contract(cid)
    if contract["contract_status"] != "IN_NEGOTIATION":
        raise _invalid_contract_state("submit-for-signature")
    contract["contract_status"] = "PENDING_SIGNATURE"
    contract["submitted_by_user_id"] = user_id
    _bump_and_audit(contract, role, user_id, "CONTRACT_SUBMITTED_FOR_SIGNATURE",
                    "Contract submitted for signature.")
    return ok(dict(contract))


@bp.post("/contracts/<cid>/counter-offer")
def counter_offer(cid):
    validate_body({"note": (STR, False)})
    user_id, role = auth()
    require_roles(role, [ROLE_CONTRACT_MANAGER])
    contract = get_contract(cid)
    if contract["contract_status"] != "PENDING_SIGNATURE":
        raise _invalid_contract_state("counter-offer")
    contract["contract_status"] = "IN_NEGOTIATION"
    contract["negotiation_round"] += 1
    contract["submitted_by_user_id"] = None
    _bump_and_audit(contract, role, user_id, "CONTRACT_COUNTER_OFFER",
                    "Counter-offer returned the contract to negotiation.")
    return ok(dict(contract))


@bp.post("/contracts/<cid>/sign")
def sign_contract(cid):
    validate_body({})
    user_id, role = auth()
    require_roles(role, [ROLE_CONTRACT_LEGAL])
    contract = get_contract(cid)
    if contract["contract_status"] != "PENDING_SIGNATURE":
        raise _invalid_contract_state("sign")
    if contract["submitted_by_user_id"] == user_id:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES", 409,
            "The signer must differ from the user who submitted the contract.",
        )
    contract["contract_status"] = "SIGNED"
    contract["signed_by_user_id"] = user_id
    _bump_and_audit(contract, role, user_id, "CONTRACT_SIGNED",
                    "Contract signed.")
    return ok(dict(contract))


# ---------------------------------------------------------------------------
# Configuration / testing / go-live
# ---------------------------------------------------------------------------
@bp.post("/contracts/<cid>/begin-configuration")
def begin_configuration(cid):
    validate_body({})
    user_id, role = auth()
    require_roles(role, [ROLE_CONFIG_ANALYST])
    contract = get_contract(cid)
    if contract["contract_status"] == "SIGNED":
        contract["contract_status"] = "IN_CONFIGURATION"
        _bump_and_audit(contract, role, user_id, "CONTRACT_CONFIGURATION_STARTED",
                        "Contract entered configuration.")
    elif contract["contract_status"] == "ACTIVE":
        contract["contract_status"] = "IN_CONFIGURATION"
        _bump_and_audit(contract, role, user_id,
                        "CONTRACT_AMENDMENT_CONFIGURATION_STARTED",
                        "Active contract re-entered configuration for amendment.")
    else:
        raise _invalid_contract_state("begin-configuration")
    return ok(dict(contract))


@bp.post("/contracts/<cid>/begin-testing")
def begin_testing(cid):
    validate_body({})
    user_id, role = auth()
    require_roles(role, [ROLE_CONFIG_ANALYST])
    contract = get_contract(cid)
    if contract["contract_status"] != "IN_CONFIGURATION":
        raise _invalid_contract_state("begin-testing")
    has_validated = any(
        v["contract_id"] == cid and v["version_status"] == "VALIDATED"
        for v in store.versions.values()
    )
    if not has_validated:
        raise ApiError(
            "ERR_NO_VALIDATED_VERSION", 422,
            "A VALIDATED contract version is required before testing.",
        )
    contract["contract_status"] = "IN_TESTING"
    _bump_and_audit(contract, role, user_id, "CONTRACT_TESTING_STARTED",
                    "Contract entered configuration testing.")
    return ok(dict(contract))


@bp.post("/contracts/<cid>/return-to-configuration")
def return_to_configuration(cid):
    validate_body({})
    user_id, role = auth()
    require_roles(role, [ROLE_CONFIG_ANALYST])
    contract = get_contract(cid)
    if contract["contract_status"] != "IN_TESTING":
        raise _invalid_contract_state("return-to-configuration")
    contract["contract_status"] = "IN_CONFIGURATION"
    _bump_and_audit(contract, role, user_id, "CONTRACT_RETURNED_TO_CONFIGURATION",
                    "Contract returned to configuration.")
    return ok(dict(contract))


@bp.post("/contracts/<cid>/mark-ready")
def mark_ready(cid):
    validate_body({})
    user_id, role = auth()
    require_roles(role, [ROLE_CONFIG_ANALYST])
    contract = get_contract(cid)
    if contract["contract_status"] != "IN_TESTING":
        raise _invalid_contract_state("mark-ready")
    passed = False
    for version in store.versions.values():
        if version["contract_id"] != cid or version["version_status"] != "VALIDATED":
            continue
        if any(b["contract_version_id"] == version["id"] and b["batch_status"] == "PASSED"
               for b in store.batches.values()):
            passed = True
            break
    if not passed:
        raise ApiError(
            "ERR_SIMULATION_THRESHOLD_NOT_MET", 422,
            "A PASSED simulation batch under a VALIDATED version is required.",
        )
    contract["contract_status"] = "READY_FOR_GO_LIVE"
    _bump_and_audit(contract, role, user_id, "CONTRACT_READY_FOR_GO_LIVE",
                    "Contract marked ready for go-live.")
    return ok(dict(contract))


@bp.post("/contracts/<cid>/approve-go-live")
def approve_go_live(cid):
    validate_body({})
    user_id, role = auth()
    require_roles(role, [ROLE_PLAN_ADMIN])
    contract = get_contract(cid)
    if contract["contract_status"] != "READY_FOR_GO_LIVE":
        raise _invalid_contract_state("approve-go-live")
    validated = [v for v in store.versions.values()
                 if v["contract_id"] == cid and v["version_status"] == "VALIDATED"]
    if not validated:
        raise _invalid_contract_state("approve-go-live (no VALIDATED version)")
    validated.sort(key=lambda v: (v["effective_date"], v["created_at"]))
    activating = validated[-1]
    # Fiscal gate runs to completion before any activation occurs.
    parity_check(contract, activating)

    # Cascade link 1: the VALIDATED version becomes EFFECTIVE.
    activating["version_status"] = "EFFECTIVE"
    store.touch(activating)
    store.add_audit(cid, "VERSION_EFFECTIVE", role, "system",
                    "Contract version became EFFECTIVE at go-live.")
    # Cascade link 2: any previously EFFECTIVE version is superseded.
    for other in store.versions.values():
        if (other["contract_id"] == cid and other["id"] != activating["id"]
                and other["version_status"] == "EFFECTIVE"):
            other["version_status"] = "SUPERSEDED"
            store.touch(other)
            store.add_audit(cid, "VERSION_SUPERSEDED", role, "system",
                            "Prior EFFECTIVE version was superseded.")
    # Cascade link 3: retro adjustment run when the version has retro reach.
    retro = activating.get("retro_effective_date")
    if retro and parse_date(retro, "retro_effective_date") < parse_date(
            activating["effective_date"], "effective_date"):
        run = store.stamp_new({
            "contract_version_id": activating["id"],
            "run_status": "CREATED",
            "window_start_date": retro,
            "window_end_date": activating["effective_date"],
            "adjustment_count": 0,
            "total_underpaid_cents": 0,
            "total_overpaid_cents": 0,
            "net_delta_cents": 0,
        })
        store.runs[run["id"]] = run

    contract["contract_status"] = "ACTIVE"
    store.touch(contract)
    store.add_audit(cid, "CONTRACT_GO_LIVE", role, user_id,
                    "Contract approved for go-live and activated.")
    return ok(dict(contract))


# ---------------------------------------------------------------------------
# Amendment versions (OCC-guarded creation)
# ---------------------------------------------------------------------------
@bp.post("/contracts/<cid>/versions")
def create_version(cid):
    data = validate_body({
        "version_number": (INT, True),
        "effective_date": (DATE, True),
        "retro_effective_date": (DATE, False),
        "expected_contract_version": (INT, True),
    })
    user_id, role = auth()
    require_roles(role, [ROLE_CONTRACT_MANAGER])
    contract = get_contract(cid)
    if data["expected_contract_version"] != contract["version"]:
        raise ApiError(
            "ERR_STALE_VERSION", 412,
            "expected_contract_version does not match the contract's current version.",
        )
    siblings = [v for v in store.versions.values() if v["contract_id"] == cid]
    for v in siblings:
        if v["effective_date"] == data["effective_date"]:
            raise ApiError(
                "ERR_VERSION_WINDOW_OVERLAP", 409,
                "Another version of this contract already uses this effective_date.",
            )
    retro = data["retro_effective_date"]
    if retro is not None:
        base = parse_date(contract["base_effective_date"], "base_effective_date")
        retro_d = parse_date(retro, "retro_effective_date")
        eff_d = parse_date(data["effective_date"], "effective_date")
        if not (base <= retro_d < eff_d):
            raise ApiError(
                "ERR_RETRO_WINDOW_INVALID", 422,
                "retro_effective_date must satisfy base_effective_date <= retro < effective_date.",
            )
    for v in siblings:
        if v["version_number"] == data["version_number"]:
            raise ApiError(
                "ERR_DUPLICATE_VERSION_NUMBER", 409,
                "version_number is already used on this contract.",
            )
    version = store.stamp_new({
        "contract_id": cid,
        "version_number": data["version_number"],
        "effective_date": data["effective_date"],
        "retro_effective_date": retro,
        "version_status": "DRAFT",
    })
    store.versions[version["id"]] = version
    store.touch(contract)
    store.add_audit(cid, "VERSION_CREATED", role, user_id,
                    f"Contract version {data['version_number']} created.")
    return ok(dict(version), 201)


@bp.get("/contracts/<cid>/versions")
def list_versions(cid):
    user_id, role = auth()
    require_roles(role, ALL_ROLES)
    contract = get_contract(cid)
    check_ownership(role, user_id, contract["provider_id"])
    items = [v for v in store.versions.values() if v["contract_id"] == cid]
    return ok_list([dict(v) for v in sorted_by_created(items)])


# ---------------------------------------------------------------------------
# Paid-claim ledger
# ---------------------------------------------------------------------------
@bp.post("/contracts/<cid>/paid-claims")
def create_paid_claim(cid):
    data = validate_body({
        "claim_number": (STR, True),
        "hcpcs_code": (STR, True),
        "service_category": (STR, True),
        "service_date": (DATE, True),
        "billed_cents": (INT, True),
        "paid_cents": (INT, True),
    })
    _, role = auth()
    require_roles(role, [ROLE_PAYMENT_INTEGRITY])
    contract = get_contract(cid)
    if contract["contract_status"] != "ACTIVE":
        raise _invalid_contract_state("paid-claim load (requires ACTIVE)")
    for s in store.paid_claims.values():
        if s["contract_id"] == cid and s["claim_number"] == data["claim_number"]:
            raise ApiError(
                "ERR_DUPLICATE_CLAIM_NUMBER", 409,
                "claim_number already loaded on this contract.",
            )
    snapshot = store.stamp_new({
        "contract_id": cid,
        "claim_number": data["claim_number"],
        "hcpcs_code": data["hcpcs_code"],
        "service_category": data["service_category"],
        "service_date": data["service_date"],
        "billed_cents": data["billed_cents"],
        "paid_cents": data["paid_cents"],
        "snapshot_status": "OPEN",
    })
    store.paid_claims[snapshot["id"]] = snapshot
    return ok(dict(snapshot), 201)


@bp.get("/contracts/<cid>/paid-claims")
def list_paid_claims(cid):
    _, role = auth()
    require_roles(role, INTERNAL_ROLES)
    get_contract(cid)
    items = [s for s in store.paid_claims.values() if s["contract_id"] == cid]
    return ok_list([dict(s) for s in sorted_by_created(items)])


# ---------------------------------------------------------------------------
# Termination notices (OCC-guarded creation)
# ---------------------------------------------------------------------------
@bp.post("/contracts/<cid>/termination-notices")
def create_notice(cid):
    data = validate_body({
        "notice_date": (DATE, True),
        "termination_date": (DATE, True),
        "reason": (STR, True),
        "expected_contract_version": (INT, True),
    })
    user_id, role = auth()
    require_roles(role, [ROLE_CONTRACT_MANAGER])
    contract = get_contract(cid)
    if data["expected_contract_version"] != contract["version"]:
        raise ApiError(
            "ERR_STALE_VERSION", 412,
            "expected_contract_version does not match the contract's current version.",
        )
    if contract["contract_status"] != "ACTIVE":
        raise _invalid_contract_state("termination-notice creation (requires ACTIVE)")
    if not notice_period_valid(data["notice_date"], data["termination_date"]):
        raise ApiError(
            "ERR_NOTICE_PERIOD_INSUFFICIENT", 422,
            "termination_date must be at least 90 days after notice_date.",
        )
    notice = store.stamp_new({
        "contract_id": cid,
        "notice_date": data["notice_date"],
        "termination_date": data["termination_date"],
        "reason": data["reason"],
        "notice_status": "DRAFT",
    })
    store.notices[notice["id"]] = notice
    store.touch(contract)
    store.add_audit(cid, "NOTICE_CREATED", role, user_id,
                    "Termination notice drafted.")
    return ok(dict(notice), 201)


@bp.get("/contracts/<cid>/termination-notices")
def list_notices(cid):
    _, role = auth()
    require_roles(role, INTERNAL_ROLES)
    get_contract(cid)
    items = [n for n in store.notices.values() if n["contract_id"] == cid]
    return ok_list([dict(n) for n in sorted_by_created(items)])


# ---------------------------------------------------------------------------
# Audit trail
# ---------------------------------------------------------------------------
@bp.get("/contracts/<cid>/audit-events")
def list_audit_events(cid):
    user_id, role = auth()
    require_roles(role, ALL_ROLES)
    contract = get_contract(cid)
    check_ownership(role, user_id, contract["provider_id"])
    items = [e for e in store.audit_events.values() if e["contract_id"] == cid]
    return ok_list([dict(e) for e in sorted_by_created(items)])
