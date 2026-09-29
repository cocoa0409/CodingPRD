"""People, sites, applications, assets, observations and dependency edges."""

from flask import Blueprint

from constants import (
    ALL_ROLES,
    APPROVAL_LEVELS,
    ASSET_KINDS,
    EDGE_KINDS,
    NODE_KINDS,
    ORG_ROLES,
    READ_ROLES,
    REPLICATION_MODES,
    ROLE_AUDIT_LIAISON,
    ROLE_BUSINESS_OWNER,
    ROLE_COORDINATOR,
    ROLE_IT_OPERATOR,
    ROLE_PLATFORM_ADMIN,
    SITE_ROLES,
    STAKEHOLDER_STATUSES,
    TIER_AGREEMENT_STATUSES,
    TIER_RPO_CAP,
    TIER_RTO_CAP,
    TIERS,
)
from db import db, new_row, now, touch
from errors import ApiError
from middleware import actor_id, endpoint
from response import created, ok, ok_list
import services
from validation import (
    body,
    check_fk,
    filter_value,
    lookup_path,
    paginate,
    v_dt,
    v_enum,
    v_enum_array,
    v_int,
    v_str,
)

bp = Blueprint("estate", __name__)


def _duplicate(code, table_name, field):
    for row in getattr(db, table_name).values():
        if row[field] == code:
            raise ApiError("ERR_DUPLICATE_CODE", "%s '%s' is already in use." % (field, code))


# --------------------------------------------------------------------------- #
# Stakeholders
# --------------------------------------------------------------------------- #

@bp.post("/stakeholders")
@endpoint([ROLE_PLATFORM_ADMIN], skip_identity=True)
def create_stakeholder():
    payload = body()
    full_name = v_str(payload, "full_name")
    email = v_str(payload, "email")
    org_roles = v_enum_array(payload, "org_roles", ORG_ROLES)
    level = v_enum(payload, "approval_authority_level", APPROVAL_LEVELS,
                   required=False, default="LEVEL_1")
    _duplicate(email, "stakeholders", "email")

    row = new_row()
    row.update({
        "full_name": full_name,
        "email": email,
        "org_roles": org_roles,
        "approval_authority_level": level,
        "status": "ACTIVE",
    })
    db.stakeholders[row["id"]] = row
    return created(row)


@bp.patch("/stakeholders/<row_id>")
@endpoint([ROLE_PLATFORM_ADMIN], skip_identity=True)
def patch_stakeholder(row_id):
    person = lookup_path("stakeholders", row_id)
    payload = body()
    status = v_enum(payload, "status", STAKEHOLDER_STATUSES, required=False)
    level = v_enum(payload, "approval_authority_level", APPROVAL_LEVELS, required=False)
    org_roles = v_enum_array(payload, "org_roles", ORG_ROLES, required=False)

    was_active = person["status"] == "ACTIVE"
    if status is not None:
        person["status"] = status
    if level is not None:
        person["approval_authority_level"] = level
    if org_roles is not None:
        person["org_roles"] = org_roles
    touch(person)

    # CASCADE C -- hop 1 is the status move, hops 2-4 follow inside this request.
    if was_active and person["status"] == "SUSPENDED":
        services.cascade_owner_suspended(person)
    return ok(person)


@bp.get("/stakeholders/<row_id>")
@endpoint(READ_ROLES)
def get_stakeholder(row_id):
    return ok(lookup_path("stakeholders", row_id))


@bp.get("/stakeholders")
@endpoint(READ_ROLES)
def list_stakeholders():
    status = filter_value("status", STAKEHOLDER_STATUSES)
    rows = [r for r in db.stakeholders.values()
            if status is None or r["status"] == status]
    page, meta = paginate(rows)
    return ok_list(page, meta)


# --------------------------------------------------------------------------- #
# Sites
# --------------------------------------------------------------------------- #

@bp.post("/sites")
@endpoint([ROLE_PLATFORM_ADMIN])
def create_site():
    payload = body()
    name = v_str(payload, "name")
    site_code = v_str(payload, "site_code")
    role = v_enum(payload, "role", SITE_ROLES)
    usable = v_int(payload, "usable_capacity_units", minimum=0)
    _duplicate(site_code, "sites", "site_code")

    row = new_row()
    row.update({
        "name": name,
        "site_code": site_code,
        "role": role,
        "usable_capacity_units": usable,
        "reserved_capacity_units": 0,
    })
    db.sites[row["id"]] = row
    return created(row)


@bp.get("/sites/<row_id>")
@endpoint(READ_ROLES)
def get_site(row_id):
    return ok(lookup_path("sites", row_id))


@bp.get("/sites")
@endpoint(READ_ROLES)
def list_sites():
    role = filter_value("role", SITE_ROLES)
    rows = [r for r in db.sites.values() if role is None or r["role"] == role]
    page, meta = paginate(rows)
    return ok_list(page, meta)


# --------------------------------------------------------------------------- #
# Applications
# --------------------------------------------------------------------------- #

@bp.post("/applications")
@endpoint([ROLE_COORDINATOR, ROLE_PLATFORM_ADMIN])
def create_application():
    payload = body()
    check_fk(payload, "business_owner_id", "stakeholders")
    check_fk(payload, "primary_site_id", "sites")

    name = v_str(payload, "name")
    app_code = v_str(payload, "app_code")
    business_owner_id = v_str(payload, "business_owner_id")
    primary_site_id = v_str(payload, "primary_site_id")
    criticality = v_int(payload, "criticality_weight", minimum=1, maximum=10)
    _duplicate(app_code, "applications", "app_code")

    row = new_row()
    row.update({
        "name": name,
        "app_code": app_code,
        "business_owner_id": business_owner_id,
        "primary_site_id": primary_site_id,
        "recovery_group_id": None,
        "criticality_weight": criticality,
        "tier_agreement_status": "DRAFT",
        "tier": None,
        "rto_minutes": None,
        "rpo_minutes": None,
        "proposed_tier": None,
        "proposed_rto_minutes": None,
        "proposed_rpo_minutes": None,
        "proposed_by_id": None,
        "retier_count": 0,
    })
    db.applications[row["id"]] = row
    return created(row)


@bp.get("/applications/<row_id>")
@endpoint(READ_ROLES)
def get_application(row_id):
    return ok(lookup_path("applications", row_id))


@bp.get("/applications")
@endpoint(READ_ROLES)
def list_applications():
    owner = filter_value("business_owner_id")
    site = filter_value("primary_site_id")
    group = filter_value("recovery_group_id")
    proposer = filter_value("proposed_by_id")
    status = filter_value("tier_agreement_status", TIER_AGREEMENT_STATUSES)
    rows = []
    for row in db.applications.values():
        if owner is not None and row["business_owner_id"] != owner:
            continue
        if site is not None and row["primary_site_id"] != site:
            continue
        if group is not None and row["recovery_group_id"] != group:
            continue
        if proposer is not None and row["proposed_by_id"] != proposer:
            continue
        if status is not None and row["tier_agreement_status"] != status:
            continue
        rows.append(row)
    page, meta = paginate(rows)
    return ok_list(page, meta)


@bp.post("/applications/<row_id>/tier-proposals")
@endpoint([ROLE_COORDINATOR, ROLE_PLATFORM_ADMIN])
def create_tier_proposal(row_id):
    app = lookup_path("applications", row_id)
    payload = body()
    proposed_tier = v_enum(payload, "proposed_tier", TIERS)
    rto = v_int(payload, "proposed_rto_minutes", minimum=0)
    rpo = v_int(payload, "proposed_rpo_minutes", minimum=0)
    v_str(payload, "rationale", required=False)

    # rank 13 -- a proposal is accepted from DRAFT, CHANGES_REQUESTED and AGREED.
    if app["tier_agreement_status"] not in ("DRAFT", "CHANGES_REQUESTED", "AGREED"):
        raise ApiError(
            "ERR_INVALID_APPLICATION_TIER_STATE",
            "A tier proposal is not accepted from %s." % app["tier_agreement_status"],
        )
    # rank 33 then rank 34 -- the RTO ceiling is evaluated before the RPO ceiling.
    if rto > TIER_RTO_CAP[proposed_tier]:
        raise ApiError("ERR_TIER_RTO_EXCEEDS_CAP",
                       "proposed_rto_minutes exceeds the cap for %s." % proposed_tier)
    if rpo > TIER_RPO_CAP[proposed_tier]:
        raise ApiError("ERR_TIER_RPO_EXCEEDS_CAP",
                       "proposed_rpo_minutes exceeds the cap for %s." % proposed_tier)

    retier = app["tier_agreement_status"] == "AGREED"
    app["proposed_tier"] = proposed_tier
    app["proposed_rto_minutes"] = rto
    app["proposed_rpo_minutes"] = rpo
    app["proposed_by_id"] = actor_id()
    app["tier_agreement_status"] = "TIER_PROPOSED"
    if retier:
        app["retier_count"] = app["retier_count"] + 1
    touch(app)

    if retier:
        # CASCADE A hops 2-6.
        services.cascade_application_retiered(app)
    return created(app)


@bp.post("/applications/<row_id>/tier-decisions")
@endpoint([ROLE_BUSINESS_OWNER])
def create_tier_decision(row_id):
    app = lookup_path("applications", row_id)
    payload = body()
    action = v_enum(payload, "action", ("AGREE", "REQUEST_CHANGES"))
    v_str(payload, "decision_note", required=False)

    if app["tier_agreement_status"] != "TIER_PROPOSED":
        raise ApiError(
            "ERR_INVALID_APPLICATION_TIER_STATE",
            "A tier decision requires tier_agreement_status TIER_PROPOSED.",
        )
    # rank 17 -- segregation of duties, only on AGREE.
    if action == "AGREE" and app["proposed_by_id"] == actor_id():
        raise ApiError("ERR_SOD_TIER_PROPOSER",
                       "The proposer of a tier may not agree it.")
    # rank 46 -- deliberately the very bottom of the ladder.
    if app["business_owner_id"] != actor_id():
        raise ApiError("ERR_NOT_APPLICATION_OWNER",
                       "Only the application's own business owner may decide the tier.")

    if action == "AGREE":
        app["tier_agreement_status"] = "AGREED"
        app["tier"] = app["proposed_tier"]
        app["rto_minutes"] = app["proposed_rto_minutes"]
        app["rpo_minutes"] = app["proposed_rpo_minutes"]
        touch(app)
        group = db.recovery_groups.get(app["recovery_group_id"])
        if group is not None:
            services.refresh_projection(group)
    else:
        app["tier_agreement_status"] = "CHANGES_REQUESTED"
        touch(app)
    return created(app)


@bp.post("/applications/<row_id>/group-assignments")
@endpoint([ROLE_COORDINATOR])
def assign_application(row_id):
    app = lookup_path("applications", row_id)
    payload = body()
    check_fk(payload, "recovery_group_id", "recovery_groups")
    group_id = v_str(payload, "recovery_group_id")

    app["recovery_group_id"] = group_id
    touch(app)
    group = db.recovery_groups[group_id]
    touch(group)                       # declared: increments the group's version by 1
    services.refresh_projection(group)
    return created(app)


# --------------------------------------------------------------------------- #
# Assets
# --------------------------------------------------------------------------- #

@bp.post("/assets")
@endpoint([ROLE_IT_OPERATOR, ROLE_COORDINATOR])
def create_asset():
    payload = body()
    check_fk(payload, "site_id", "sites")

    name = v_str(payload, "name")
    asset_code = v_str(payload, "asset_code")
    asset_kind = v_enum(payload, "asset_kind", ASSET_KINDS)
    site_id = v_str(payload, "site_id")
    replication_mode = v_enum(payload, "replication_mode", REPLICATION_MODES)
    restore_minutes = v_int(payload, "restore_minutes", minimum=0)
    txn_rate = v_int(payload, "expected_txn_rate_per_minute",
                     required=False, default=0, minimum=0)
    _duplicate(asset_code, "assets", "asset_code")

    row = new_row()
    row.update({
        "name": name,
        "asset_code": asset_code,
        "asset_kind": asset_kind,
        "site_id": site_id,
        "recovery_group_id": None,
        "replication_mode": replication_mode,
        "restore_minutes": restore_minutes,
        "expected_txn_rate_per_minute": txn_rate,
    })
    db.assets[row["id"]] = row
    return created(row)


@bp.get("/assets/<row_id>")
@endpoint(READ_ROLES)
def get_asset(row_id):
    return ok(lookup_path("assets", row_id))


@bp.get("/assets")
@endpoint(READ_ROLES)
def list_assets():
    site = filter_value("site_id")
    group = filter_value("recovery_group_id")
    kind = filter_value("asset_kind", ASSET_KINDS)
    rows = []
    for row in db.assets.values():
        if site is not None and row["site_id"] != site:
            continue
        if group is not None and row["recovery_group_id"] != group:
            continue
        if kind is not None and row["asset_kind"] != kind:
            continue
        rows.append(row)
    page, meta = paginate(rows)
    return ok_list(page, meta)


@bp.post("/assets/<row_id>/group-assignments")
@endpoint([ROLE_COORDINATOR])
def assign_asset(row_id):
    asset = lookup_path("assets", row_id)
    payload = body()
    check_fk(payload, "recovery_group_id", "recovery_groups")
    group_id = v_str(payload, "recovery_group_id")

    asset["recovery_group_id"] = group_id
    touch(asset)
    group = db.recovery_groups[group_id]
    touch(group)
    services.refresh_projection(group)
    return created(asset)


@bp.post("/assets/<row_id>/replication-observations")
@endpoint([ROLE_IT_OPERATOR])
def append_observation(row_id):
    asset = lookup_path("assets", row_id)
    payload = body()
    observed_at = v_dt(payload, "observed_at")
    lag = v_int(payload, "replication_lag_seconds", minimum=0)
    txn = v_int(payload, "unreplicated_txn_count", minimum=0)

    # rank 45 -- a measurement dated after the logical clock is nonsense.
    if observed_at > now():
        raise ApiError("ERR_OBSERVATION_IN_FUTURE",
                       "observed_at must be at or before the current logical clock.")

    # An append-only log row: id and created_at only, no updated_at and no version.
    row = new_row(common_fields=False)
    row.update({
        "asset_id": asset["id"],
        "observed_at": observed_at,
        "replication_lag_seconds": lag,
        "unreplicated_txn_count": txn,
        "recorded_by_user_id": actor_id(),
    })
    db.observations[row["id"]] = row
    return created(row)


@bp.get("/assets/<row_id>/replication-observations")
@endpoint(READ_ROLES)
def list_observations(row_id):
    asset = lookup_path("assets", row_id)
    rows = [o for o in db.observations.values() if o["asset_id"] == asset["id"]]
    # The single exception to created_at ASC: newest observed_at first (PRD 2.3).
    page, meta = paginate(
        rows,
        key=lambda o: (o["observed_at"], o["created_at"], o["_seq"]),
        reverse=True,
    )
    return ok_list(page, meta)


# --------------------------------------------------------------------------- #
# Dependency edges
# --------------------------------------------------------------------------- #

_NODE_TABLE = {"APPLICATION": "applications", "ASSET": "assets"}


def _check_node_fk(payload, kind_field, id_field):
    """Rank 5 for a polymorphic reference: the discriminator picks the register."""
    kind = payload.get(kind_field)
    if isinstance(kind, str) and kind in _NODE_TABLE:
        check_fk(payload, id_field, _NODE_TABLE[kind])


@bp.post("/dependency-edges")
@endpoint([ROLE_COORDINATOR])
def create_dependency_edge():
    payload = body()
    _check_node_fk(payload, "from_node_kind", "from_node_id")
    _check_node_fk(payload, "to_node_kind", "to_node_id")

    from_kind = v_enum(payload, "from_node_kind", NODE_KINDS)
    from_id = v_str(payload, "from_node_id")
    to_kind = v_enum(payload, "to_node_kind", NODE_KINDS)
    to_id = v_str(payload, "to_node_id")
    edge_kind = v_enum(payload, "edge_kind", EDGE_KINDS)

    # rank 27
    if from_id == to_id:
        raise ApiError("ERR_SELF_DEPENDENCY", "An edge may not join a node to itself.")
    # rank 28 -- SOFT edges are exempt from cycle detection entirely.
    if edge_kind == "HARD" and services.hard_edge_creates_cycle(from_id, to_id):
        raise ApiError("ERR_DEPENDENCY_CYCLE",
                       "The edge would close a directed cycle among HARD edges.")
    # rank 29
    for existing in db.dependency_edges.values():
        if (existing["from_node_id"] == from_id
                and existing["to_node_id"] == to_id
                and existing["edge_kind"] == edge_kind):
            raise ApiError("ERR_DUPLICATE_DEPENDENCY_EDGE",
                           "An identical dependency edge already exists.")

    row = new_row()
    row.update({
        "from_node_kind": from_kind,
        "from_node_id": from_id,
        "to_node_kind": to_kind,
        "to_node_id": to_id,
        "edge_kind": edge_kind,
    })
    db.dependency_edges[row["id"]] = row

    if edge_kind == "HARD":
        for group in services.groups_containing_both(from_id, to_id):
            touch(group)               # declared: increments the group's version by 1
            services.refresh_projection(group)
    return created(row)


@bp.get("/dependency-edges/<row_id>")
@endpoint(READ_ROLES)
def get_dependency_edge(row_id):
    return ok(lookup_path("dependency_edges", row_id))


@bp.get("/dependency-edges")
@endpoint(READ_ROLES)
def list_dependency_edges():
    from_id = filter_value("from_node_id")
    to_id = filter_value("to_node_id")
    kind = filter_value("edge_kind", EDGE_KINDS)
    rows = []
    for row in db.dependency_edges.values():
        if from_id is not None and row["from_node_id"] != from_id:
            continue
        if to_id is not None and row["to_node_id"] != to_id:
            continue
        if kind is not None and row["edge_kind"] != kind:
            continue
        rows.append(row)
    page, meta = paginate(rows)
    return ok_list(page, meta)
