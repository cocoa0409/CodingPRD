"""Power design, approval, energization and metering (PRD §3.4)."""

from flask import Blueprint

import refs
from auth import authorize
from errors import ApiError
from response import created, ok, ok_list, paginate, pagination, serialize
from rollups import (
    cabinet_of,
    cascade_power_change,
    circuits_of_cabinet,
    contract_of,
    derated_kw,
    energized_power,
    recompute_row,
    row_of,
    set_energized_power,
    zero_power,
)
from store import (
    BREAKER_HEADROOM_RATIO,
    CIRCUIT_STATUSES,
    DENSITY_TOLERANCE_RATIO,
    FEED_SIDES,
    OPERATIONAL_CABINET_STATUSES,
    PHASES,
    POWER_OVERPROVISION_CAP_RATIO,
    REDUNDANCY_ROLES,
    base_row,
    now,
    store,
    touch,
)
from util import dec, q3
from validate import (
    json_body,
    qfilter,
    req_datetime,
    req_enum,
    req_int,
    req_number,
    req_string,
)

bp = Blueprint("power", __name__)

READ_ROLES = ("ProvisioningEngineer", "FacilityManager", "BillingOperator", "CustomerAdmin")
APPROVAL_CABINET_STATUSES = ("RESERVED", "INSTALLED", "ACTIVE")


@bp.route("/power-circuits", methods=["POST"])
def create_circuit():
    authorize("ProvisioningEngineer")
    body = json_body()
    cabinet = refs.body_fk(body, "cabinet_id", refs.CABINET)

    cabinet_id = req_string(body, "cabinet_id")
    circuit_code = req_string(body, "circuit_code")
    feed_side = req_enum(body, "feed_side", FEED_SIDES)
    redundancy_role = req_enum(body, "redundancy_role", REDUNDANCY_ROLES)
    breaker_amps = req_int(body, "breaker_amps", minimum=1)
    volts = req_int(body, "volts", minimum=1)
    phase = req_enum(body, "phase", PHASES)

    for existing in circuits_of_cabinet(cabinet_id):
        if existing["circuit_code"] == circuit_code:
            raise ApiError("ERR_INVALID_REQUEST", "circuit_code must be unique within the cabinet")

    circuit = base_row()
    circuit.update(
        {
            "cabinet_id": cabinet_id,
            "circuit_code": circuit_code,
            "feed_side": feed_side,
            "redundancy_role": redundancy_role,
            "breaker_amps": breaker_amps,
            "volts": volts,
            "phase": phase,
            # Pinned from the breaker plate at design time; every later step
            # consumes this rounded figure and never the raw product.
            "derated_kw": derated_kw(breaker_amps, volts, phase),
            "allocated_kw": 0.0,
            "cooling_contribution_kw": 0.0,
            "status": "DESIGNED",
            "energized_at": None,
            "meter_intervals": [],
        }
    )
    store.circuits[circuit["id"]] = circuit
    # A DESIGNED circuit allocates nothing, so no rollup moves here.
    return created(serialize(circuit))


def _breaker_projection(cabinet, circuit):
    """Sum of derated_kw over the cabinet's PRIMARY circuits already committed,
    plus this circuit's own derated capacity (zero when REDUNDANT)."""
    total = dec("0")
    for other in circuits_of_cabinet(cabinet["id"]):
        if other["id"] == circuit["id"]:
            continue
        if other["redundancy_role"] != "PRIMARY":
            continue
        if other["status"] not in ("APPROVED", "ENERGIZED"):
            continue
        total = total + dec(other["derated_kw"])
    if circuit["redundancy_role"] == "PRIMARY":
        total = total + dec(circuit["derated_kw"])
    return q3(total)


def _breaker_gate(cabinet, circuit):
    projection = dec(_breaker_projection(cabinet, circuit))
    ceiling = q3(dec(cabinet["rated_power_kw"]) * dec(BREAKER_HEADROOM_RATIO))
    if projection > dec(ceiling):
        raise ApiError(
            "ERR_CABINET_BREAKER_OVERSUBSCRIBED",
            "projected breaker load %s exceeds the %s kW headroom ceiling" % (projection, ceiling),
        )


@bp.route("/power-circuits/<circuit_id>/state", methods=["POST"])
def circuit_state(circuit_id):
    authorize("ProvisioningEngineer", "FacilityManager")
    circuit = refs.path_row(refs.CIRCUIT, circuit_id)
    body = json_body()
    to_state = req_enum(body, "to_state", CIRCUIT_STATUSES)
    current = circuit["status"]
    cabinet = cabinet_of(circuit)

    if current == "DESIGNED" and to_state == "APPROVED":
        if cabinet["status"] not in APPROVAL_CABINET_STATUSES:
            raise ApiError(
                "ERR_CABINET_NOT_OPERATIONAL",
                "approval requires a RESERVED, INSTALLED or ACTIVE cabinet",
            )
        _breaker_gate(cabinet, circuit)
        circuit["status"] = "APPROVED"
        touch(circuit)

    elif current == "DESIGNED" and to_state == "BLOCKED":
        circuit["status"] = "BLOCKED"
        touch(circuit)

    elif current == "BLOCKED" and to_state == "DESIGNED":
        circuit["status"] = "DESIGNED"
        touch(circuit)

    elif current == "ENERGIZED" and to_state == "DE_ENERGIZED":
        circuit["status"] = "DE_ENERGIZED"
        zero_power(circuit)
        touch(circuit)
        # Exact compensation of the energize cascade (PRD §2.8, §3.4).
        cascade_power_change(cabinet, force=True)

    elif current == "DE_ENERGIZED" and to_state == "REMOVED":
        circuit["status"] = "REMOVED"
        touch(circuit)

    else:
        raise ApiError(
            "ERR_INVALID_STATE", "circuit cannot move from %s to %s" % (current, to_state)
        )

    return ok(serialize(circuit))


@bp.route("/power-circuits/<circuit_id>/energize", methods=["POST"])
def energize(circuit_id):
    authorize("ProvisioningEngineer")
    circuit = refs.path_row(refs.CIRCUIT, circuit_id)
    cabinet = cabinet_of(circuit)
    row = row_of(cabinet)
    body = json_body()

    # Rule 10 — the row's optimistic-concurrency guard, before any business rule.
    expected = req_int(body, "expected_row_version")
    if expected != row["version"]:
        raise ApiError(
            "ERR_STALE_ROW_VERSION",
            "expected_row_version %s does not match the row's current version %s"
            % (expected, row["version"]),
        )

    if circuit["status"] not in ("APPROVED", "DE_ENERGIZED"):
        raise ApiError(
            "ERR_INVALID_STATE",
            "only an APPROVED or DE_ENERGIZED circuit may be energized",
        )
    if row["decommission_flag"]:
        raise ApiError(
            "ERR_ROW_NOT_ACCEPTING_SPACE", "the row is flagged for decommissioning"
        )
    if cabinet["status"] not in OPERATIONAL_CABINET_STATUSES:
        raise ApiError(
            "ERR_CABINET_NOT_OPERATIONAL", "energization requires an INSTALLED or ACTIVE cabinet"
        )

    contract = contract_of(cabinet)
    allocated_new, cooling_new = energized_power(circuit, cabinet)

    # Four numeric projections, each computed as though this circuit were
    # already energized, each permitting equality, in a fixed order.
    projected_cooling = q3(dec(row["cooling_load_kw"]) + dec(cooling_new))
    if dec(projected_cooling) > dec(row["cooling_capacity_kw"]):
        raise ApiError(
            "ERR_COOLING_CAPACITY_EXCEEDED",
            "projected cooling load %s exceeds the row's %s kW capacity"
            % (projected_cooling, row["cooling_capacity_kw"]),
        )

    _breaker_gate(cabinet, circuit)

    if (
        contract is not None
        and contract["redundancy_requirement"] == "TWO_N"
        and circuit["redundancy_role"] == "PRIMARY"
    ):
        standby = [
            c
            for c in circuits_of_cabinet(cabinet["id"])
            if c["redundancy_role"] == "REDUNDANT"
            and c["feed_side"] != circuit["feed_side"]
            and c["status"] in ("APPROVED", "ENERGIZED")
        ]
        if not standby:
            raise ApiError(
                "ERR_REDUNDANT_FEED_MISSING",
                "a TWO_N contract requires an opposite-side REDUNDANT feed first",
            )

    projected_allocated = q3(dec(row["allocated_power_kw"]) + dec(allocated_new))
    density_ceiling = q3(dec(row["density_ceiling_kw"]) * dec(DENSITY_TOLERANCE_RATIO))
    if dec(projected_allocated) > dec(density_ceiling):
        raise ApiError(
            "ERR_ROW_DENSITY_LIMIT_EXCEEDED",
            "projected row load %s exceeds the %s kW density tolerance"
            % (projected_allocated, density_ceiling),
        )
    if dec(projected_allocated) > dec(row["max_row_power_kw"]):
        raise ApiError(
            "ERR_ROW_POWER_LIMIT_EXCEEDED",
            "projected row load %s exceeds the busway limit of %s kW"
            % (projected_allocated, row["max_row_power_kw"]),
        )

    if contract is not None:
        if contract["credit_hold"]:
            raise ApiError(
                "ERR_CREDIT_HOLD_ACTIVE", "a contract on credit hold cannot energize new power"
            )
        projected_provisioned = q3(dec(contract["provisioned_power_kw"]) + dec(allocated_new))
        commit_ceiling = q3(dec(contract["power_commit_kw"]) * dec(POWER_OVERPROVISION_CAP_RATIO))
        if dec(projected_provisioned) > dec(commit_ceiling):
            raise ApiError(
                "ERR_POWER_COMMIT_EXCEEDED",
                "projected provisioned power %s exceeds the %s kW cap"
                % (projected_provisioned, commit_ceiling),
            )

    circuit["status"] = "ENERGIZED"
    set_energized_power(circuit, cabinet)
    circuit["energized_at"] = now()
    touch(circuit)
    cascade_power_change(cabinet, force=True)
    return ok(serialize(circuit))


@bp.route("/power-circuits/<circuit_id>/readings", methods=["POST"])
def append_reading(circuit_id):
    authorize("FacilityManager", "BillingOperator")
    circuit = refs.path_row(refs.CIRCUIT, circuit_id)
    body = json_body()
    interval_start = req_datetime(body, "interval_start")
    interval_end = req_datetime(body, "interval_end")
    kwh = req_number(body, "kwh", minimum=0)
    peak_kw = req_number(body, "peak_kw", minimum=0)
    if interval_end <= interval_start:
        raise ApiError(
            "ERR_BILLING_PERIOD_INVALID", "interval_end must be strictly after interval_start"
        )

    circuit["meter_intervals"].append(
        {
            "interval_start": interval_start,
            "interval_end": interval_end,
            "kwh": kwh,
            "peak_kw": peak_kw,
        }
    )
    touch(circuit)

    cabinet = cabinet_of(circuit)
    row = row_of(cabinet) if cabinet is not None else None
    if row is not None:
        # Metering moves measured_peak_kw and therefore stranded_measured_kw
        # without any electrical work taking place.
        recompute_row(row)
    return created(serialize(circuit))


@bp.route("/power-circuits/<circuit_id>", methods=["GET"])
def get_circuit(circuit_id):
    actor = authorize(*READ_ROLES)
    circuit = refs.path_row(refs.CIRCUIT, circuit_id)
    actor.scope_circuit(circuit)
    return ok(serialize(circuit))


@bp.route("/power-circuits", methods=["GET"])
def list_circuits():
    actor = authorize(*READ_ROLES)
    actor.require_customer()
    actor.scope_query(("cabinet", "cabinet_id"))
    limit, offset = pagination()
    rows = qfilter(
        list(store.circuits.values()), "cabinet_id", "status", "feed_side", "redundancy_role"
    )
    items, total = paginate(rows, limit, offset)
    return ok_list(items, limit, offset, total)
