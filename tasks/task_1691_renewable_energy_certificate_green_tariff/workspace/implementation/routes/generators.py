"""Generator endpoints, lifecycle transitions and the mint run."""

from flask import Blueprint

from errors import raise_err, ERR_VALIDATION, ERR_STALE_VERSION, \
    ERR_GENERATOR_NOT_ACTIVE, ERR_INVALID_GENERATOR_STATE
from store import STORE, new_id, next_seq, now_ts
from util import auth, require_role, forbidden, ok_object, paginate, serialize, \
    body_json, req_str, req_int, opt_str, opt_int, req_enum, parse_date, \
    get_or_404, TECHNOLOGIES
from services import generator_cumulative_accepted_kwh, generator_account, touch

bp = Blueprint("generators", __name__)

GEN_STATUSES = {"REGISTERED", "VERIFICATION", "ACTIVE", "REJECTED", "SUSPENDED", "DECOMMISSIONED"}


def serialize_generator(g):
    out = serialize(g)
    out["cumulative_accepted_kwh"] = generator_cumulative_accepted_kwh(g["id"])
    return out


@bp.post("/greenpower/generators")
def create_generator():
    uid, role = auth()
    require_role(role, "RegistryAdmin")
    body = body_json()
    legal_name = req_str(body, "legal_name")
    facility_code = req_str(body, "facility_code")
    technology = req_enum(body, "technology", TECHNOLOGIES)
    nameplate = req_int(body, "nameplate_capacity_kw")
    if nameplate <= 0:
        raise_err(ERR_VALIDATION, "nameplate_capacity_kw must be a positive integer")
    region_code = req_str(body, "region_code")
    commissioning_date = parse_date(req_str(body, "commissioning_date"), "commissioning_date")
    for other in STORE["generators"].values():
        if other["facility_code"] == facility_code:
            raise_err(ERR_VALIDATION, "facility_code must be unique across all generators")
    now = now_ts()
    gen = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "legal_name": legal_name,
        "facility_code": facility_code,
        "technology": technology,
        "nameplate_capacity_kw": nameplate,
        "region_code": region_code,
        "commissioning_date": commissioning_date,
        "status": "REGISTERED",
        "rejection_reason": None,
        "carryover_kwh": 0,
        "lifetime_minted_mwh": 0,
        "next_serial": 1,
        "_carryover_year": None,
        "_seq": next_seq(),
    }
    STORE["generators"][gen["id"]] = gen
    return ok_object(serialize_generator(gen), 201)


def list_with_serializer(records, filters, serializer):
    items = sorted(records, key=lambda r: (r.get("created_at", ""), r.get("_seq", 0)))
    for key, val in filters.items():
        if val is None:
            continue
        items = [r for r in items if str(r.get(key)) == val]
    from util import pagination_params, ok_list
    limit, offset = pagination_params()
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list([serializer(r) for r in page], limit, offset, total)


@bp.get("/greenpower/generators")
def list_generators():
    auth()
    from flask import request
    filters = {
        "status": request.args.get("status"),
        "technology": request.args.get("technology"),
        "region_code": request.args.get("region_code"),
    }
    return list_with_serializer(list(STORE["generators"].values()), filters,
                                serialize_generator)


@bp.get("/greenpower/generators/<gid>")
def get_generator(gid):
    auth()
    gen = get_or_404(STORE["generators"], gid, "Generator")
    return ok_object(serialize_generator(gen))


@bp.patch("/greenpower/generators/<gid>")
def patch_generator(gid):
    uid, role = auth()
    require_role(role, "RegistryAdmin")
    body = body_json()
    expected = req_int(body, "expected_generator_version")
    legal_name = opt_str(body, "legal_name")
    nameplate = opt_int(body, "nameplate_capacity_kw")
    if nameplate is not None and nameplate <= 0:
        raise_err(ERR_VALIDATION, "nameplate_capacity_kw must be a positive integer")
    region_code = opt_str(body, "region_code")
    gen = get_or_404(STORE["generators"], gid, "Generator")
    if expected != gen["version"]:
        raise_err(ERR_STALE_VERSION, "expected_generator_version does not match the current generator version")
    if legal_name is not None:
        gen["legal_name"] = legal_name
    if nameplate is not None:
        gen["nameplate_capacity_kw"] = nameplate
    if region_code is not None:
        gen["region_code"] = region_code
    touch(gen)
    return ok_object(serialize_generator(gen))


def _lifecycle(gid, allowed_from, to_state, role_required, clear_rejection=False,
               set_reason=False):
    uid, role = auth()
    require_role(role, role_required)
    # Ownership is a raw-value match against the path id (auth stage precedes
    # existence in the validation pipeline).
    if role_required == "GeneratorOperator" and uid != gid:
        forbidden("A GeneratorOperator may only act on their own generator")
    gen = get_or_404(STORE["generators"], gid, "Generator")
    if gen["status"] not in allowed_from:
        raise_err(ERR_INVALID_GENERATOR_STATE,
                  "Generator is %s; this transition requires %s"
                  % (gen["status"], " or ".join(allowed_from)))
    if set_reason:
        body = body_json()
        gen["rejection_reason"] = opt_str(body, "reason")
    if clear_rejection:
        gen["rejection_reason"] = None
    gen["status"] = to_state
    touch(gen)
    return gen


@bp.post("/greenpower/generators/<gid>/submit-verification")
def submit_verification(gid):
    gen = _lifecycle(gid, ("REGISTERED", "REJECTED"), "VERIFICATION",
                     "GeneratorOperator", clear_rejection=True)
    return ok_object(serialize_generator(gen))


@bp.post("/greenpower/generators/<gid>/verify")
def verify_generator(gid):
    gen = _lifecycle(gid, ("VERIFICATION",), "ACTIVE", "RegistryAdmin")
    # Auto-create the generator's GENERATOR account in the same mutation.
    now = now_ts()
    acct = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "account_type": "GENERATOR",
        "owner_name": gen["legal_name"],
        "generator_id": gen["id"],
        "program_id": None,
        "status": "ACTIVE",
        "failure_strikes": 0,
        "_seq": next_seq(),
    }
    STORE["accounts"][acct["id"]] = acct
    return ok_object(serialize_generator(gen))


@bp.post("/greenpower/generators/<gid>/reject-verification")
def reject_verification(gid):
    gen = _lifecycle(gid, ("VERIFICATION",), "REJECTED", "RegistryAdmin",
                     set_reason=True)
    return ok_object(serialize_generator(gen))


@bp.post("/greenpower/generators/<gid>/suspend")
def suspend_generator(gid):
    gen = _lifecycle(gid, ("ACTIVE",), "SUSPENDED", "RegistryAdmin")
    return ok_object(serialize_generator(gen))


@bp.post("/greenpower/generators/<gid>/reinstate")
def reinstate_generator(gid):
    gen = _lifecycle(gid, ("SUSPENDED",), "ACTIVE", "RegistryAdmin")
    return ok_object(serialize_generator(gen))


@bp.post("/greenpower/generators/<gid>/decommission")
def decommission_generator(gid):
    gen = _lifecycle(gid, ("ACTIVE", "SUSPENDED"), "DECOMMISSIONED", "RegistryAdmin")
    return ok_object(serialize_generator(gen))


@bp.post("/greenpower/generators/<gid>/mint-run")
def mint_run(gid):
    uid, role = auth()
    require_role(role, "RegistryAdmin")
    gen = get_or_404(STORE["generators"], gid, "Generator")
    if gen["status"] != "ACTIVE":
        raise_err(ERR_GENERATOR_NOT_ACTIVE, "Mint run requires an ACTIVE generator")

    pending = [
        r for r in STORE["readings"].values()
        if r["generator_id"] == gid and r["status"] == "ACCEPTED" and not r["minted"]
    ]
    pending.sort(key=lambda r: (r["_period_start_dt"], r["created_at"], r["_seq"]))

    if not pending:
        return ok_object({
            "minted_count": 0,
            "total_minted_mwh": 0,
            "carryover_kwh": gen["carryover_kwh"],
            "certificate_ids": [],
        })

    # Group into YYYY-MM vintage buckets, preserving chronological order.
    buckets = {}
    for r in pending:
        bucket = "%04d-%02d" % (r["_period_start_dt"].year, r["_period_start_dt"].month)
        buckets.setdefault(bucket, []).append(r)

    account = generator_account(gid)
    carry = gen["carryover_kwh"]
    carry_year = gen["_carryover_year"]
    certificate_ids = []
    total_minted = 0
    now = now_ts()

    for bucket in sorted(buckets.keys()):
        readings = buckets[bucket]
        bucket_year = int(bucket[:4])
        pool = sum(r["metered_kwh"] for r in readings)
        if carry and carry_year == bucket_year:
            pool += carry
        # else: pending carry from a different calendar year is discarded.
        whole = pool // 1000
        if whole > 0:
            serial_start = gen["next_serial"]
            cert = {
                "id": new_id(),
                "created_at": now,
                "updated_at": now,
                "version": 1,
                "generator_id": gid,
                "account_id": account["id"] if account else None,
                "vintage_month": bucket,
                "region_code": gen["region_code"],
                "technology": gen["technology"],
                "serial_prefix": "%s-%s" % (gen["facility_code"], bucket),
                "serial_start": serial_start,
                "serial_end": serial_start + whole - 1,
                "quantity_mwh": whole,
                "status": "ACTIVE",
                "_seq": next_seq(),
            }
            STORE["certificates"][cert["id"]] = cert
            gen["next_serial"] += whole
            gen["lifetime_minted_mwh"] += whole
            certificate_ids.append(cert["id"])
            total_minted += whole
        carry = pool - whole * 1000
        carry_year = bucket_year
        for r in readings:
            r["minted"] = True
            r["minted_vintage_month"] = bucket
            touch(r)

    gen["carryover_kwh"] = carry
    gen["_carryover_year"] = carry_year
    touch(gen)

    return ok_object({
        "minted_count": len(certificate_ids),
        "total_minted_mwh": total_minted,
        "carryover_kwh": carry,
        "certificate_ids": certificate_ids,
    })
