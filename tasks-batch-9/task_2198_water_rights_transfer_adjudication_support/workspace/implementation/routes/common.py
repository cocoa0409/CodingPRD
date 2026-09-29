"""Shared route helpers: existence lookups (priority 3/4/7), ownership
resolution (priority 5), sorting and pagination."""
import db
import derive
import response
import validate
from errors import ApiError

# ---------------------------------------------------------------------------
# Existence lookups
# ---------------------------------------------------------------------------

def _lookup(store, key, error_id, label):
    if not isinstance(key, str) or not key:
        raise ApiError(error_id, "%s not found." % label)
    row = store.get(key)
    if row is None:
        raise ApiError(error_id, "%s '%s' not found." % (label, key))
    return row


def get_claimant(cid):
    return _lookup(db.claimants, cid, "ERR_CLAIMANT_NOT_FOUND", "Claimant")


def get_right(rid):
    return _lookup(db.water_rights, rid, "ERR_WATER_RIGHT_NOT_FOUND", "WaterRight")


def get_pod(pid):
    return _lookup(
        db.points_of_diversion, pid, "ERR_POINT_OF_DIVERSION_NOT_FOUND",
        "PointOfDiversion",
    )


def get_use_record(rid):
    return _lookup(
        db.beneficial_use_records, rid, "ERR_BENEFICIAL_USE_RECORD_NOT_FOUND",
        "BeneficialUseRecord",
    )


def get_study(sid):
    return _lookup(db.hcu_studies, sid, "ERR_HCU_STUDY_NOT_FOUND", "HcuStudy")


def get_app(aid):
    return _lookup(
        db.transfer_applications, aid, "ERR_TRANSFER_APPLICATION_NOT_FOUND",
        "TransferApplication",
    )


def get_analysis(aid):
    return _lookup(
        db.injury_analyses, aid, "ERR_INJURY_ANALYSIS_NOT_FOUND", "InjuryAnalysis"
    )


def get_protest(pid):
    return _lookup(db.protests, pid, "ERR_PROTEST_NOT_FOUND", "Protest")


def get_condition(cid):
    return _lookup(
        db.approval_conditions, cid, "ERR_APPROVAL_CONDITION_NOT_FOUND",
        "ApprovalCondition",
    )


def get_account(aid):
    return _lookup(
        db.water_bank_accounts, aid, "ERR_WATER_BANK_ACCOUNT_NOT_FOUND",
        "WaterBankAccount",
    )


def get_lease(lid):
    return _lookup(
        db.lease_assignments, lid, "ERR_LEASE_ASSIGNMENT_NOT_FOUND",
        "LeaseAssignment",
    )


def get_docket(did):
    return _lookup(
        db.decree_dockets, did, "ERR_DECREE_DOCKET_NOT_FOUND", "DecreeDocket"
    )


def get_claim(cid):
    return _lookup(
        db.adjudication_claims, cid, "ERR_ADJUDICATION_CLAIM_NOT_FOUND",
        "AdjudicationClaim",
    )


# ---------------------------------------------------------------------------
# Sorting + pagination
# ---------------------------------------------------------------------------

def sort_created_asc(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def sort_created_desc(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]), reverse=True)


def sort_by(rows, keyfn):
    return sorted(rows, key=lambda r: (keyfn(r), r["created_at"], r["_seq"]))


def emit(rows, projector, limit=None, offset=None):
    """Paginate + project. When limit/offset are omitted the full set is
    returned but the pagination meta is still populated."""
    total = len(rows)
    if limit is None:
        limit, offset = validate.pagination()
    window = rows[offset:offset + limit]
    return response.list_response(
        [projector(r) for r in window], limit, offset, total
    )


# ---------------------------------------------------------------------------
# Ownership resolution (priority 5)
# ---------------------------------------------------------------------------

def owner_precheck(caller, body, key, store, owner_fn):
    """Priority 5 sits above body well-formedness (6) and body foreign-key
    existence (7), so ownership is judged on the raw payload whenever the
    referenced parent can already be resolved. When it cannot, the later
    existence rule reports the missing row instead."""
    if caller.role != "Claimant":
        return
    raw = body.get(key)
    if not isinstance(raw, str):
        return
    parent = store.get(raw)
    if parent is None:
        return
    owner = owner_fn(parent)
    if owner is None or caller.user_id != owner:
        raise ApiError(
            "ERR_NOT_RESOURCE_OWNER",
            "Claimant may only act on resources it owns.",
        )


def right_owner(right):
    return right["claimant_id"]


def app_owner(app):
    return derive.app_owner_claimant_id(app)


def pod_owner(pod):
    right = db.water_rights.get(pod["water_right_id"])
    return right["claimant_id"] if right else None


def study_owner(study):
    right = db.water_rights.get(study["water_right_id"])
    return right["claimant_id"] if right else None


def analysis_owner(analysis):
    app = db.transfer_applications.get(analysis["transfer_application_id"])
    return app_owner(app) if app else None


def condition_owner(condition):
    return derive.condition_owner_claimant_id(condition)


def account_owner(account):
    return account["claimant_id"]


def lease_owner(lease):
    account = db.water_bank_accounts.get(lease["water_bank_account_id"])
    return account["claimant_id"] if account else None


def claim_owner(claim):
    right = db.water_rights.get(claim["water_right_id"])
    return right["claimant_id"] if right else None


def protest_owner(protest):
    return protest["protestant_claimant_id"]
