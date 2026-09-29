"""Every calculation rule of the domain (scaffold section 1.3, PRD section 3).

Money is whole integer cents throughout and is rounded half up (away from zero)
only at the points the specification names.  Throughput arithmetic floors and
never rounds.
"""

from errors import ApiError
from store import (
    change_orders_of,
    links_of,
    ramps_of,
    runs_of,
    segments_of,
    sort_key,
    spare_lines_of,
    touch,
    zones_of,
)

# --- constants ------------------------------------------------------------
SLA_MINUTES_BY_TIER = {"BASIC": 480, "PREMIUM": 240, "CRITICAL": 60}

ESCALATION_TIER_1_MAX_CENTS = 250000000
ESCALATION_TIER_1_BPS = 150
ESCALATION_TIER_2_MAX_CENTS = 500000000
ESCALATION_TIER_2_BPS = 220
ESCALATION_TIER_3_BPS = 300

MERGE_DERATE_BPS_PER_EXTRA_INPUT = 400
SORTATION_DIVERT_LOSS_BPS = 300
SORTATION_DIVERT_MIN_OUTBOUND = 3

COVERAGE_FACTOR_BPS = {"CRITICAL": 10000, "MAJOR": 6000, "MINOR": 0}
CRITICALITY_RANK = {"CRITICAL": 0, "MAJOR": 1}

RAMP_SUSTAIN_MINUTES = {50: 30, 75: 60, 100: 120}
RAMP_STEPS = (50, 75, 100)

FAT_MARGIN_PCT = 105
FAT_MAX_DEFECTS = 2
FAT_MAX_ATTEMPTS = 3

LD_BPS_PER_SHORTFALL_PCT = 50
LD_CAP_BPS = 500

SLA_BREACH_BPS = 25

RETENTION_BPS = 500
DISPUTE_WINDOW_DAYS = 30

CHANGE_ORDER_MAX_ROUNDS = 3


# --- arithmetic primitives ------------------------------------------------
def round_half_up_div(numerator, denominator):
    """Exact integer division rounded half up (ties away from zero)."""
    if denominator < 0:
        numerator, denominator = -numerator, -denominator
    if numerator >= 0:
        return (2 * numerator + denominator) // (2 * denominator)
    return -((-2 * numerator + denominator) // (2 * denominator))


def bps_round_half_up(amount, bps):
    return round_half_up_div(amount * bps, 10000)


def bps_floor(amount, bps):
    return (amount * bps) // 10000


def ceil_div(numerator, denominator):
    return -((-numerator) // denominator)


# --- contract value ------------------------------------------------------
def escalation_tier_bps(subtotal_cents):
    if subtotal_cents <= ESCALATION_TIER_1_MAX_CENTS:
        return ESCALATION_TIER_1_BPS
    if subtotal_cents <= ESCALATION_TIER_2_MAX_CENTS:
        return ESCALATION_TIER_2_BPS
    return ESCALATION_TIER_3_BPS


def contract_value_recompute(project, including_order_id=None):
    """Returns (subtotal, escalation_fee_cents, contract_value_cents).

    The escalation tier is ALWAYS keyed on the pre-fee subtotal.  Only APPROVED
    change orders enter the subtotal, plus the order being approved in this very
    request.
    """
    subtotal = project["contract_base_cents"]
    for order in change_orders_of(project["id"]):
        if order["status"] == "APPROVED" or order["id"] == including_order_id:
            subtotal += order["price_delta_cents"]
    fee = bps_round_half_up(subtotal, escalation_tier_bps(subtotal))
    return subtotal, fee, subtotal + fee


# --- flow graph / simulation ---------------------------------------------
def check_share_integrity(project):
    """Step 0 of the simulation, also the freeze's share gate."""
    segments = segments_of(project["id"])
    links = links_of(project["id"])

    source_total = 0
    for segment in segments:
        is_source = segment["inbound_link_count"] == 0
        share = segment["source_share_bps"]
        if is_source:
            if share is None:
                raise ApiError(
                    "ERR_SOURCE_SHARE_INVALID",
                    "Segment %s has no inbound link and must declare source_share_bps."
                    % segment["segment_code"],
                )
            source_total += share
        elif share is not None:
            raise ApiError(
                "ERR_SOURCE_SHARE_INVALID",
                "Segment %s has inbound links and must not declare source_share_bps."
                % segment["segment_code"],
            )
    if source_total != 10000:
        raise ApiError(
            "ERR_SOURCE_SHARE_INVALID",
            "Source share total is %d basis points; exactly 10000 is required." % source_total,
        )

    outbound = {}
    for link in links:
        outbound.setdefault(link["from_segment_id"], []).append(link)
    for segment in segments:
        own = outbound.get(segment["id"], [])
        if not own:
            continue
        total = sum(link["split_share_bps"] for link in own)
        if total != 10000:
            raise ApiError(
                "ERR_SPLIT_SHARE_INVALID",
                "Outbound split shares of segment %s total %d basis points; exactly 10000 is "
                "required." % (segment["segment_code"], total),
            )


def _topological_order(segments, links):
    """Upstream before downstream; ties broken by earlier created_at."""
    by_id = {s["id"]: s for s in segments}
    indegree = {s["id"]: 0 for s in segments}
    successors = {s["id"]: [] for s in segments}
    for link in links:
        if link["from_segment_id"] in by_id and link["to_segment_id"] in by_id:
            indegree[link["to_segment_id"]] += 1
            successors[link["from_segment_id"]].append(link["to_segment_id"])

    ready = [s for s in segments if indegree[s["id"]] == 0]
    ready.sort(key=sort_key)
    order = []
    while ready:
        node = ready.pop(0)
        order.append(node)
        for successor_id in successors[node["id"]]:
            indegree[successor_id] -= 1
            if indegree[successor_id] == 0:
                ready.append(by_id[successor_id])
                ready.sort(key=sort_key)
    if len(order) != len(segments):
        placed = {s["id"] for s in order}
        order.extend([s for s in segments if s["id"] not in placed])
    return order


def compute_simulation(project, method):
    """Runs calculations.line_throughput_simulation and writes the segments."""
    segments = segments_of(project["id"])
    links = links_of(project["id"])

    inbound_links = {}
    for link in links:
        inbound_links.setdefault(link["to_segment_id"], []).append(link)

    by_id = {s["id"]: s for s in segments}
    flow = {}

    # Step 1 - flow share propagation in topological order.
    for segment in _topological_order(segments, links):
        if segment["inbound_link_count"] == 0:
            flow[segment["id"]] = segment["source_share_bps"] or 0
        else:
            total = 0
            for link in inbound_links.get(segment["id"], []):
                upstream_flow = flow.get(link["from_segment_id"], 0)
                total += (upstream_flow * link["split_share_bps"]) // 10000
            flow[segment["id"]] = total

    # Step 2 - capacity derate, flooring after each substep.
    derated = {}
    for segment in segments:
        cap = segment["rated_capacity_cph"]
        if method == "DEGRADED_AVAILABILITY":
            cap = (cap * segment["availability_pct"]) // 100
        if segment["equipment_class"] == "MERGE":
            cap = bps_floor(
                cap,
                10000 - MERGE_DERATE_BPS_PER_EXTRA_INPUT * (segment["inbound_link_count"] - 1),
            )
        elif (
            segment["equipment_class"] == "SORTATION"
            and segment["outbound_link_count"] >= SORTATION_DIVERT_MIN_OUTBOUND
        ):
            cap = bps_floor(cap, 10000 - SORTATION_DIVERT_LOSS_BPS)
        derated[segment["id"]] = cap

    # Persist the refreshed per-segment figures.
    for segment in segments:
        new_flow = flow.get(segment["id"], 0)
        new_derated = derated.get(segment["id"], 0)
        if segment["flow_share_bps"] != new_flow or segment["derated_capacity_cph"] != new_derated:
            segment["flow_share_bps"] = new_flow
            segment["derated_capacity_cph"] = new_derated
            touch(segment)

    # Step 3 - per-segment system rate, then the system minimum.
    best = None
    best_key = None
    effective = 0
    for segment in segments:
        share = flow.get(segment["id"], 0)
        if share <= 0:
            continue
        rate = (derated[segment["id"]] * 10000) // share
        key = (rate, derated[segment["id"]], segment["_created_dt"], segment["_seq"])
        if best_key is None or key < best_key:
            best_key = key
            best = segment
            effective = rate

    if best is None:
        effective = 0
        bottleneck_code = None
        bottleneck_availability = None
    else:
        bottleneck_code = best["segment_code"]
        bottleneck_availability = best["availability_pct"]

    shortfall = max(0, project["required_throughput_cph"] - effective)
    return {
        "effective_throughput_cph": effective,
        "bottleneck_segment_code": bottleneck_code,
        "bottleneck_availability_pct": bottleneck_availability,
        "shortfall_cph": shortfall,
    }


def has_cycle_with(project_id, from_segment_id, to_segment_id):
    """True when adding from -> to would close a cycle."""
    if from_segment_id == to_segment_id:
        return True
    adjacency = {}
    for link in links_of(project_id):
        adjacency.setdefault(link["from_segment_id"], []).append(link["to_segment_id"])
    # A cycle appears iff `from` is already reachable from `to`.
    seen = set()
    stack = [to_segment_id]
    while stack:
        node = stack.pop()
        if node == from_segment_id:
            return True
        if node in seen:
            continue
        seen.add(node)
        stack.extend(adjacency.get(node, []))
    return False


# --- spares waterfall ----------------------------------------------------
def spare_line_targets(line):
    requested = line["unit_cost_cents"] * line["min_stock_qty"]
    weighted = bps_round_half_up(requested, COVERAGE_FACTOR_BPS[line["criticality"]])
    return requested, weighted


def run_spares_waterfall(project):
    lines = spare_lines_of(project["id"])

    # Compensating reset first, so a run is idempotent in the conserved quantity.
    for line in lines:
        if line["status"] in ("ALLOCATED", "PARTIAL", "UNFUNDED"):
            line["allocated_cents"] = 0
            line["status"] = "DRAFT"
            touch(line)
    project["spares_allocated_cents"] = 0
    project["spares_unallocated_cents"] = project["spares_budget_cents"]

    candidates = [
        line
        for line in lines
        if line["status"] == "DRAFT" and line["criticality"] in ("CRITICAL", "MAJOR")
    ]
    candidates.sort(
        key=lambda line: (
            CRITICALITY_RANK[line["criticality"]],
            -line["lead_time_days"],
            line["_created_dt"],
            line["_seq"],
        )
    )

    remaining = project["spares_budget_cents"]
    allocated_total = 0
    for line in candidates:
        requested, weighted = spare_line_targets(line)
        allocated = min(weighted, remaining)
        remaining -= allocated
        if allocated == weighted and allocated > 0:
            status = "ALLOCATED"
        elif 0 < allocated < weighted:
            status = "PARTIAL"
        else:
            status = "UNFUNDED"
        if (
            line["requested_cents"] != requested
            or line["weighted_target_cents"] != weighted
            or line["allocated_cents"] != allocated
            or line["status"] != status
        ):
            line["requested_cents"] = requested
            line["weighted_target_cents"] = weighted
            line["allocated_cents"] = allocated
            line["status"] = status
            touch(line)
        allocated_total += allocated

    project["spares_allocated_cents"] = allocated_total
    project["spares_unallocated_cents"] = remaining


def fundable_spare_lines(project):
    return [
        line
        for line in spare_lines_of(project["id"])
        if line["criticality"] in ("CRITICAL", "MAJOR")
    ]


# --- ramp / FAT ----------------------------------------------------------
def ramp_evaluation(project, step_pct, measured_cph, sustained_minutes):
    target = ceil_div(project["required_throughput_cph"] * step_pct, 100)
    minimum = RAMP_SUSTAIN_MINUTES[step_pct]
    verdict = "PASS" if (measured_cph >= target and sustained_minutes >= minimum) else "FAIL"
    return target, minimum, verdict


def ramp_sequence_satisfied(project, step_pct):
    ramps = ramps_of(project["id"])
    for lower in RAMP_STEPS:
        if lower >= step_pct:
            break
        if not any(r["step_pct"] == lower and r["verdict"] == "PASS" for r in ramps):
            return False
    return True


def fat_target_for(project):
    return ceil_div(project["required_throughput_cph"] * FAT_MARGIN_PCT, 100)


def fat_result(measured_cph, defect_count, target_cph):
    if measured_cph >= target_cph and defect_count <= FAT_MAX_DEFECTS:
        return "PASS"
    return "FAIL"


# --- acceptance / damages -------------------------------------------------
def passing_full_rate_ramp(project):
    """The PASS step_pct == 100 ramp with the greatest created_at."""
    candidates = [
        r for r in ramps_of(project["id"]) if r["step_pct"] == 100 and r["verdict"] == "PASS"
    ]
    if not candidates:
        return None
    return candidates[-1]


def acceptance_ready(project):
    ramps = ramps_of(project["id"])
    for step in RAMP_STEPS:
        if not any(r["step_pct"] == step and r["verdict"] == "PASS" for r in ramps):
            return False
    for zone in zones_of(project["id"]):
        if zone["ops_status"] != "CUTOVER_COMPLETE":
            return False
    return True


def degraded_complete_run(project):
    candidates = [
        r
        for r in runs_of(project["id"])
        if r["method"] == "DEGRADED_AVAILABILITY" and r["status"] == "COMPLETE"
    ]
    if not candidates:
        return None
    return candidates[-1]


def current_degraded_run(project):
    """A COMPLETE DEGRADED_AVAILABILITY run whose snapshot is current."""
    run = degraded_complete_run(project)
    if run is None:
        return None
    if run["design_version_at_run"] != project["design_version"]:
        return None
    return run


def retention_amount(project):
    return bps_round_half_up(project["contract_value_cents"], RETENTION_BPS)


def liquidated_damages(project, certificate, basis, observed_cph):
    if basis == "OBSERVED_AVAILABILITY":
        availability = certificate.get("bottleneck_availability_pct")
        if availability:
            basis_cph = (observed_cph * 100) // availability
        else:
            basis_cph = observed_cph
    else:
        basis_cph = observed_cph
    required = project["required_throughput_cph"]
    shortfall_pct = max(0, ((required - basis_cph) * 100) // required)
    raw = bps_round_half_up(
        project["contract_value_cents"] * shortfall_pct, LD_BPS_PER_SHORTFALL_PCT
    )
    cap = bps_round_half_up(project["contract_value_cents"], LD_CAP_BPS)
    return min(raw, cap)


def sla_response_credit(project, elapsed_minutes):
    if elapsed_minutes > SLA_MINUTES_BY_TIER[project["service_tier"]]:
        return bps_round_half_up(project["contract_value_cents"], SLA_BREACH_BPS)
    return 0
