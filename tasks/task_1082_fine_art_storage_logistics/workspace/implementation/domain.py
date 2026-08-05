"""Cross-entity domain logic: cascades, conserved ledgers, lookups."""
import store
from store import db, touch
from errors import err


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------
def _by_seq(records):
    return sorted(records, key=lambda r: r["_seq"])


def placements_for(artwork_id, status=None):
    out = [p for p in db["storage_placements"].values()
           if p["artwork_id"] == artwork_id and (status is None or p["status"] == status)]
    return _by_seq(out)


def active_placement_for(artwork_id):
    ps = placements_for(artwork_id, "ACTIVE")
    return ps[0] if ps else None


def suspended_placement_for(artwork_id):
    ps = placements_for(artwork_id, "SUSPENDED")
    return ps[0] if ps else None


def finalized_appraisals_for(artwork_id):
    return [a for a in db["appraisals"].values()
            if a["artwork_id"] == artwork_id and a["status"] == "FINALIZED"]


def active_policy_for(artwork_id):
    for p in _by_seq(list(db["policies"].values())):
        if p["artwork_id"] == artwork_id and p["status"] == "ACTIVE":
            return p
    return None


def carnet_for_loan(loan_id, statuses=None):
    for c in _by_seq(list(db["carnets"].values())):
        if c["loan_id"] == loan_id and (statuses is None or c["status"] in statuses):
            return c
    return None


# ---------------------------------------------------------------------------
# Conserved ledger: vault occupancy
# ---------------------------------------------------------------------------
def vault_slot_delta(vault, delta):
    vault["occupied_slots"] += delta
    touch(vault)


# ---------------------------------------------------------------------------
# Custody cascades driven by other entities
# ---------------------------------------------------------------------------
def artwork_go_on_loan(artwork):
    """Custody IN_STORAGE -> ON_LOAN; suspend ACTIVE placement, free a slot."""
    artwork["custody_status"] = "ON_LOAN"
    touch(artwork)
    placement = active_placement_for(artwork["id"])
    if placement is not None:
        placement["status"] = "SUSPENDED"
        touch(placement)
        vault = db["vaults"].get(placement["vault_id"])
        if vault is not None:
            vault_slot_delta(vault, -1)


def artwork_return_from_loan(artwork):
    """Custody ON_LOAN -> IN_STORAGE; reactivate SUSPENDED placement, take a slot."""
    placement = suspended_placement_for(artwork["id"])
    if placement is not None:
        vault = db["vaults"].get(placement["vault_id"])
        if vault is not None and vault["occupied_slots"] >= vault["capacity_slots"]:
            raise err("ERR_VAULT_FULL", "vault is full; cannot reactivate placement")
        placement["status"] = "ACTIVE"
        touch(placement)
        if vault is not None:
            vault_slot_delta(vault, 1)
    artwork["custody_status"] = "IN_STORAGE"
    touch(artwork)


# ---------------------------------------------------------------------------
# Condition cascade: crossing into MAJOR_DAMAGE
# ---------------------------------------------------------------------------
def cascade_major_damage(artwork):
    """Cancel APPROVED/ACTIVE loans for the artwork; discharge their carnets."""
    for loan in _by_seq(list(db["loans"].values())):
        if loan["artwork_id"] != artwork["id"]:
            continue
        if loan["status"] in ("APPROVED", "ACTIVE"):
            loan["status"] = "CANCELLED"
            touch(loan)
            carnet = carnet_for_loan(loan["id"], statuses=("ISSUED", "ACTIVATED"))
            if carnet is not None:
                carnet["status"] = "DISCHARGED"
                touch(carnet)
