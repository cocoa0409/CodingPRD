"""VFD authorization routes: issue (with optional supersede), get, list, revoke."""

from flask import Blueprint, request

import errors
import util
import clock
from db import store
from middleware import require_roles
from response import success_object
from services import core
from routes.onboarding import _paginate

bp = Blueprint("vfd", __name__)


def _active_vcp_covers(vet_id, producer_id):
    for vcp in store.vcp_verifications.values():
        if (
            vcp.get("vet_id") == vet_id
            and vcp.get("producer_id") == producer_id
            and vcp.get("status") == "ACTIVE"
        ):
            return True
    return False


@bp.post("/vfd/vfd-authorizations")
def create_vfd():
    user_id, _ = require_roles("Veterinarian")
    body = util.get_json_body()

    producer_id = util.require_field(body, "producer_id")
    animal_group_id = util.require_field(body, "animal_group_id")
    vet_id = util.require_field(body, "vet_id")
    drug_id = util.require_field(body, "drug_id")
    authorized_animal_count = util.require_int(body, "authorized_animal_count")
    feed_duration_days = util.require_int(body, "feed_duration_days")
    expiration_date = util.require_field(body, "expiration_date")
    extra_label_intended = body.get("extra_label_intended", False)
    supersedes_id = body.get("supersedes_id")
    expected_version = body.get("expected_vfd_authorization_version")

    # existence, left-to-right (body order)
    producer = core.get_producer(producer_id)
    group = core.get_animal_group(animal_group_id)
    vet = core.get_vet(vet_id)
    drug = core.get_drug(drug_id)
    exp_dt = util.parse_iso(expiration_date, "expiration_date")

    old_vfd = None
    if supersedes_id is not None:
        old_vfd = core.get_vfd(supersedes_id)

    # entity-backed identity: caller must be the issuing vet
    if user_id != vet_id:
        raise errors.forbidden("X-User-ID must equal vet_id of issuing veterinarian")

    # priority 6: extra-label
    if extra_label_intended is True:
        raise errors.ApiError(errors.ERR_EXTRA_LABEL_USE,
                              "Extra-label use of a VFD drug is prohibited", 422)

    # priority 7: species/class pair on label
    pair = f"{group['species']}:{group['production_class']}"
    if pair not in drug.get("allowed_species_classes", []):
        raise errors.ApiError(errors.ERR_SPECIES_CLASS_MISMATCH,
                              "Animal group species:class not on drug label", 422)

    # priority 8: VCPR active covering (vet, producer)
    if not _active_vcp_covers(vet_id, producer_id):
        raise errors.ApiError(errors.ERR_VCPR_NOT_VERIFIED,
                              "No ACTIVE VCPR covering (vet, producer)", 422)

    # priority 12: duration <= 6 months
    issued_on = clock.now()
    # 6 months ~ 183 days is ambiguous; use calendar month arithmetic
    month = issued_on.month + 6
    year = issued_on.year + (month - 1) // 12
    month = (month - 1) % 12 + 1
    day = min(issued_on.day, [31, 29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28,
                              31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1])
    max_exp = issued_on.replace(year=year, month=month, day=day)
    if exp_dt > max_exp:
        raise errors.ApiError(errors.ERR_VFD_DURATION_EXCEEDED,
                              "VFD expiration_date more than 6 months past issued_on", 422)

    # priority 15: producer active
    if producer["status"] != "ACTIVE":
        raise errors.ApiError(errors.ERR_PRODUCER_SUSPENDED,
                              "Producer status is SUSPENDED or DEBARRED", 409)

    # priority 16: vet active
    if vet["status"] != "ACTIVE":
        raise errors.ApiError(errors.ERR_VET_INACTIVE,
                              "Veterinarian status is SUSPENDED or REVOKED", 409)

    # supersede flow
    if old_vfd is not None:
        if old_vfd["status"] not in ("ISSUED", "PARTIALLY_USED"):
            raise errors.invalid_state(
                "supersedes_id must point to a VFD in ISSUED or PARTIALLY_USED")
        # priority 18: OCC
        if expected_version is None:
            raise errors.invalid_request(
                "expected_vfd_authorization_version is required when superseding")
        if isinstance(expected_version, bool) or not isinstance(expected_version, int):
            raise errors.invalid_request("expected_vfd_authorization_version must be an integer")
        if expected_version != old_vfd["version"]:
            raise errors.ApiError(errors.ERR_STALE_VERSION,
                                  "expected_vfd_authorization_version does not match current VFD version",
                                  412)

    vfd = util.new_entity({
        "producer_id": producer_id,
        "animal_group_id": animal_group_id,
        "vet_id": vet_id,
        "drug_id": drug_id,
        "authorized_animal_count": authorized_animal_count,
        "remaining_animal_count": authorized_animal_count,
        "feed_duration_days": feed_duration_days,
        "issued_on": util.logical_now_iso(),
        "expiration_date": expiration_date,
        "extra_label_intended": bool(extra_label_intended),
        "status": "ISSUED",
    })
    store.vfd_authorizations[vfd["id"]] = vfd

    if old_vfd is not None:
        # supersede: old -> SUPERSEDED, remaining zeroed, cascade cancels open orders
        core.cascade_vfd_terminal(old_vfd, "SUPERSEDED")
        old_vfd["remaining_animal_count"] = 0
        old_vfd["superseded_by_id"] = vfd["id"]
        # cascade_vfd_terminal already bumped version once; just refresh timestamp
        old_vfd["updated_at"] = util.logical_now_iso()

    return success_object(vfd, 201)


@bp.get("/vfd/vfd-authorizations/<vid>")
def get_vfd(vid):
    require_roles("Inspector", "Veterinarian", "FeedMillOperator", "Producer")
    return success_object(core.get_vfd(vid))


@bp.get("/vfd/vfd-authorizations")
def list_vfds():
    require_roles("Inspector", "Veterinarian", "FeedMillOperator", "Producer")
    items = list(store.vfd_authorizations.values())
    for param in ("producer_id", "vet_id", "drug_id", "animal_group_id", "superseded_by_id", "status"):
        val = request.args.get(param)
        if val is not None:
            items = [v for v in items if v.get(param) == val]
    return _paginate(items)


@bp.get("/vfd/producers/<pid>/vfd-authorizations")
def list_vfds_for_producer(pid):
    require_roles("Inspector", "Veterinarian", "FeedMillOperator", "Producer")
    core.get_producer(pid)
    items = [v for v in store.vfd_authorizations.values() if v.get("producer_id") == pid]
    status = request.args.get("status")
    if status is not None:
        items = [v for v in items if v.get("status") == status]
    return _paginate(items)


@bp.post("/vfd/vfd-authorizations/<vid>/revoke")
def revoke_vfd(vid):
    user_id, _ = require_roles("Veterinarian")
    vfd = core.get_vfd(vid)
    if user_id != vfd.get("vet_id"):
        raise errors.forbidden("X-User-ID must equal vfd.vet_id")
    if vfd["status"] not in ("ISSUED", "PARTIALLY_USED"):
        raise errors.invalid_state("VFD must be ISSUED or PARTIALLY_USED to revoke")
    core.cascade_vfd_terminal(vfd, "REVOKED")
    return success_object(vfd)
