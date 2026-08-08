"""Medication reconciliation and discrepancy governance (PRD 3.5)."""
from flask import Blueprint

import constants as C
import domain
import envelope
import guards as G
import store
from errors import ApiError
from store import DB, serialize

bp = Blueprint("medrec", __name__)


def _episode_of(recon):
    return DB["episodes"][recon["episode_id"]]


# ------------------------------------------------------------------ open it
@bp.post("/tcm/episodes/<episode_id>/med-reconciliations")
def open_med_reconciliation(episode_id):
    user_id, _role = G.auth(["Clinician"])
    episode = G.get_episode(episode_id)
    G.require_open_records(episode)

    if domain.episode_medrec(episode) is not None:
        raise ApiError("ERR_INVALID_STATE", "This episode already has a medication reconciliation.")

    row = store.new_row(
        "med_reconciliations",
        {
            "episode_id": episode["id"],
            "status": "OPEN",
            "discrepancy_count": 0,
            "resolved_count": 0,
            "unresolved_count": 0,
            "deferred_count": 0,
            "blocking_unresolved_count": 0,
            "completed_at": None,
            "reopen_count": 0,
            "performed_by_user_id": user_id,
        },
    )
    return envelope.created(serialize(row))


@bp.get("/tcm/med-reconciliations/<med_reconciliation_id>")
def read_med_reconciliation(med_reconciliation_id):
    G.auth(C.ALL_ROLES)
    return envelope.ok(serialize(G.get_row("med_reconciliations", med_reconciliation_id)))


@bp.get("/tcm/med-reconciliations")
def list_med_reconciliations():
    G.auth(C.ALL_ROLES)
    limit, offset = G.pagination()
    f = G.filters("episode_id", "status")

    def keep(row):
        return all(row.get(key) == value for key, value in f.items())

    rows = store.sorted_rows("med_reconciliations", keep)
    page = rows[offset : offset + limit]
    return envelope.listing([serialize(r) for r in page], limit, offset, len(rows))


# ------------------------------------------------------- append a line item
@bp.post("/tcm/med-reconciliations/<med_reconciliation_id>/discrepancies")
def append_discrepancy(med_reconciliation_id):
    G.auth(["Clinician"])
    data = G.body()
    medication_name = G.req_string(data, "medication_name")
    discrepancy_type = G.req_string(data, "discrepancy_type")
    severity = G.req_string(data, "severity")
    expected_version = G.req_int(data, "expected_med_reconciliation_version")
    G.enum(discrepancy_type, C.DISCREPANCY_TYPES, "discrepancy_type")
    G.enum(severity, C.DISCREPANCY_SEVERITIES, "severity")

    recon = G.get_row("med_reconciliations", med_reconciliation_id)
    episode = _episode_of(recon)
    G.require_open_records(episode)

    if expected_version != recon["version"]:
        raise ApiError("ERR_STALE_VERSION")

    row = store.new_row(
        "discrepancies",
        {
            "med_reconciliation_id": recon["id"],
            "medication_name": medication_name,
            "discrepancy_type": discrepancy_type,
            "severity": severity,
            "status": "UNRESOLVED",
            "resolution_note": None,
            "disposition_at": None,
        },
    )
    if recon["status"] == "OPEN":
        recon["status"] = "IN_REVIEW"
    store.touch(recon)
    domain.recompute_medrec_counters(recon)
    return envelope.created(serialize(row))


@bp.get("/tcm/discrepancies/<discrepancy_id>")
def read_discrepancy(discrepancy_id):
    G.auth(C.ALL_ROLES)
    return envelope.ok(serialize(G.get_row("discrepancies", discrepancy_id)))


@bp.get("/tcm/discrepancies")
def list_discrepancies():
    G.auth(C.ALL_ROLES)
    limit, offset = G.pagination()
    f = G.filters("med_reconciliation_id", "severity", "status")

    def keep(row):
        return all(row.get(key) == value for key, value in f.items())

    rows = store.sorted_rows("discrepancies", keep)
    page = rows[offset : offset + limit]
    return envelope.listing([serialize(r) for r in page], limit, offset, len(rows))


@bp.post("/tcm/discrepancies/<discrepancy_id>/disposition")
def disposition_discrepancy(discrepancy_id):
    G.auth(["Clinician"])
    data = G.body()
    disposition = G.req_string(data, "disposition")
    resolution_note = G.opt_string(data, "resolution_note")
    G.enum(disposition, C.DISCREPANCY_DISPOSITIONS, "disposition")

    item = G.get_row("discrepancies", discrepancy_id)
    recon = DB["med_reconciliations"][item["med_reconciliation_id"]]
    episode = _episode_of(recon)
    G.require_open_records(episode)

    if item["status"] != "UNRESOLVED":
        raise ApiError("ERR_INVALID_STATE", "Only an UNRESOLVED line item may be dispositioned.")
    if recon["status"] not in ("OPEN", "IN_REVIEW"):
        raise ApiError("ERR_INVALID_STATE", "The parent reconciliation is not open for review.")
    if disposition == "DEFERRED" and item["severity"] not in C.DEFERRABLE_DISCREPANCY_SEVERITIES:
        raise ApiError("ERR_DEFERRAL_NOT_PERMITTED")

    item["status"] = disposition
    item["resolution_note"] = resolution_note
    item["disposition_at"] = store.now()
    store.touch(item)
    domain.recompute_medrec_counters(recon)
    return envelope.ok(serialize(item))


@bp.post("/tcm/discrepancies/<discrepancy_id>/reopen")
def reopen_discrepancy(discrepancy_id):
    G.auth(["Clinician"])
    item = G.get_row("discrepancies", discrepancy_id)
    recon = DB["med_reconciliations"][item["med_reconciliation_id"]]
    episode = _episode_of(recon)
    G.require_open_records(episode)

    if item["status"] not in ("RESOLVED", "DEFERRED"):
        raise ApiError("ERR_INVALID_STATE", "Only a dispositioned line item may be reopened.")

    item["status"] = "UNRESOLVED"
    store.touch(item)
    domain.recompute_medrec_counters(recon)
    return envelope.ok(serialize(item))


# ------------------------------------------------------------ complete it
@bp.post("/tcm/med-reconciliations/<med_reconciliation_id>/complete")
def complete_med_reconciliation(med_reconciliation_id):
    G.auth(["Clinician"])
    recon = G.get_row("med_reconciliations", med_reconciliation_id)
    episode = _episode_of(recon)
    G.require_open_records(episode)

    if recon["status"] == "OPEN":
        if recon["discrepancy_count"] != 0:
            raise ApiError("ERR_INVALID_STATE", "The reconciliation cannot be completed from OPEN.")
    elif recon["status"] == "IN_REVIEW":
        if recon["blocking_unresolved_count"] != 0:
            raise ApiError("ERR_BLOCKING_DISCREPANCY_UNRESOLVED")
    else:
        raise ApiError("ERR_INVALID_STATE", "The reconciliation is already completed.")

    recon["status"] = "COMPLETED"
    recon["completed_at"] = store.now()
    store.touch(recon)
    domain.set_medrec_complete(episode, True)
    return envelope.ok(serialize(recon))


@bp.post("/tcm/med-reconciliations/<med_reconciliation_id>/reopen")
def reopen_med_reconciliation(med_reconciliation_id):
    G.auth(["Clinician"])
    recon = G.get_row("med_reconciliations", med_reconciliation_id)
    episode = _episode_of(recon)
    G.require_open_records(episode)

    if recon["status"] != "COMPLETED":
        raise ApiError("ERR_INVALID_STATE", "Only a COMPLETED reconciliation may be reopened.")

    recon["status"] = "IN_REVIEW"
    recon["completed_at"] = None
    recon["reopen_count"] += 1
    store.touch(recon)
    domain.set_medrec_complete(episode, False)
    return envelope.ok(serialize(recon))
