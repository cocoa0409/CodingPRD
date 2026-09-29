"""Shared route plumbing: path resolution, posture/phase gates, list paging."""

import envelope
import logical_clock
import shape
import store
import txn
from errors import ApiError

ALL = None  # placeholder replaced below to avoid a circular import at module load


def _find(collection, key, error_id):
    if not isinstance(key, str) or not key:
        raise ApiError(error_id)
    record = collection.get(key)
    if record is None:
        raise ApiError(error_id)
    return record


def get_site(site_id):
    return _find(store.sites, site_id, "ERR_SITE_NOT_FOUND")


def get_prp(prp_id):
    return _find(store.prps, prp_id, "ERR_PRP_NOT_FOUND")


def get_waste(waste_id):
    return _find(store.waste_in_records, waste_id, "ERR_WASTE_IN_RECORD_NOT_FOUND")


def get_ri(ri_id):
    return _find(
        store.remedial_investigations, ri_id, "ERR_REMEDIAL_INVESTIGATION_NOT_FOUND"
    )


def get_rod(rod_id):
    return _find(store.records_of_decision, rod_id, "ERR_RECORD_OF_DECISION_NOT_FOUND")


def get_alternative(alt_id):
    return _find(
        store.remedy_alternatives, alt_id, "ERR_REMEDY_ALTERNATIVE_NOT_FOUND"
    )


def get_round(round_id):
    return _find(store.allocation_rounds, round_id, "ERR_ALLOCATION_ROUND_NOT_FOUND")


def get_decree(decree_id):
    return _find(store.consent_decrees, decree_id, "ERR_CONSENT_DECREE_NOT_FOUND")


def get_contract(contract_id):
    return _find(
        store.remediation_contracts, contract_id, "ERR_REMEDIATION_CONTRACT_NOT_FOUND"
    )


def get_action(action_id):
    return _find(
        store.cost_recovery_actions, action_id, "ERR_COST_RECOVERY_ACTION_NOT_FOUND"
    )


# --- gates ----------------------------------------------------------------

def deny_frozen(site):
    """Priority 8 (PRD 2.6): a frozen site rejects the request before the target
    entity's own state is examined."""
    if site["cost_posture"] == "FROZEN":
        raise ApiError("ERR_SITE_COST_FROZEN")


def deny_restricted(site):
    """Priority 9."""
    if site["cost_posture"] == "RESTRICTED":
        raise ApiError("ERR_SITE_COST_RESTRICTED")


def state(condition):
    """Priority 10."""
    if not condition:
        raise ApiError("ERR_INVALID_STATE_TRANSITION")


def deny_deleted(site):
    """Priority 11: DELETED_FROM_NPL is terminal and while a site sits there
    every write scoped under it is refused."""
    if site["listing_status"] == "DELETED_FROM_NPL":
        raise ApiError("ERR_SITE_PHASE_INVALID")


def require_phase(site, allowed):
    if site["listing_status"] not in allowed:
        raise ApiError("ERR_SITE_PHASE_INVALID")


def identity(actor, expected_id):
    """Priority 6: the role is correct and the endpoint permits it, but the
    identity does not match the target."""
    if actor.user_id != expected_id:
        raise ApiError("ERR_ACTOR_IDENTITY_MISMATCH")


# --- record construction --------------------------------------------------

def new_record(fields, mutable=True):
    instant = logical_clock.now()
    record = {
        "id": store.new_id(),
        "seq": store.next_seq(),
        "created_at": instant,
    }
    if mutable:
        record["updated_at"] = instant
        record["version"] = 1
    record.update(fields)
    return record


# --- responses ------------------------------------------------------------

def respond(record, serializer, status=200):
    txn.commit()
    return envelope.obj(serializer(record), status)


def respond_raw(payload, status=200):
    txn.commit()
    return envelope.obj(payload, status)


def listing(rows, serializer):
    limit, offset = shape.pagination()
    total = len(rows)
    page = rows[offset : offset + limit]
    return envelope.arr([serializer(r) for r in page], limit, offset, total)


def paged(rows, serializer, limit, offset):
    total = len(rows)
    page = rows[offset : offset + limit]
    return envelope.arr([serializer(r) for r in page], limit, offset, total)
