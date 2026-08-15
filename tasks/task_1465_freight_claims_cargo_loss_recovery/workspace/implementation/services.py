"""Shared business logic: mutation bookkeeping, ratios, events, the
limitation-of-liability pipeline, reserve sizing, and clock-driven sweeps."""

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from db import STORE, iso, new_id, next_seq, now

TERMINAL_CLAIM_STATES = {
    "PAID", "CLOSED_WITH_PAYMENT", "CLOSED_NO_PAYMENT", "WITHDRAWN", "TIME_BARRED",
}
WORKING_CLAIM_STATES = {
    "DRAFT", "SUBMITTED", "ACKNOWLEDGED", "UNDER_REVIEW", "OFFERED", "DECLINED", "APPEALED",
}
SALVAGE_EXECUTABLE_STATES = {"UNDER_REVIEW", "OFFERED", "DECLINED", "APPEALED"}

TIER_2_CAP_CENTS = 10000000
LANE_ALERT_THRESHOLD_BP = 1500
MAX_RESERVE_MULTIPLE = 2
BASIS_POINT_DENOMINATOR = 10000
SUBROGATION_RATIO_CAP_BP = 10000


def touch(record):
    """Refresh updated_at and bump version on any mutation (PRD 2.4)."""
    record["updated_at"] = iso(now())
    record["version"] = record.get("version", 1) + 1


def touch_claim(claim):
    touch(claim)
    claim["concurrency_token"] = claim["version"]


def round_half_up_int(numerator, denominator):
    if denominator <= 0:
        denominator = 1
    return int((Decimal(numerator) / Decimal(denominator)).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP))


def recompute_carrier_ratio(carrier):
    carrier["claim_ratio_bp"] = round_half_up_int(
        carrier["claims_paid_count"] * BASIS_POINT_DENOMINATOR,
        max(carrier["claims_filed_count"], 1),
    )


def recompute_lane_ratio(lane):
    lane["lane_claim_ratio_bp"] = round_half_up_int(
        lane["claims_count"] * BASIS_POINT_DENOMINATOR,
        max(lane["shipments_count"], 1),
    )


def bump_carrier_counters(carrier, filed_delta=0, paid_delta=0):
    carrier["claims_filed_count"] = max(0, carrier["claims_filed_count"] + filed_delta)
    carrier["claims_paid_count"] = max(0, carrier["claims_paid_count"] + paid_delta)
    recompute_carrier_ratio(carrier)
    touch(carrier)


def bump_lane_counters(lane, shipments_delta=0, claims_delta=0):
    lane["shipments_count"] = max(0, lane["shipments_count"] + shipments_delta)
    lane["claims_count"] = max(0, lane["claims_count"] + claims_delta)
    recompute_lane_ratio(lane)
    touch(lane)


def add_event(claim_id, kind, actor_user_id, payload=None):
    event = {
        "id": new_id(),
        "claim_id": claim_id,
        "event_kind": kind,
        "actor_user_id": actor_user_id,
        "event_at": iso(now()),
        "payload_json": payload or {},
        "created_at": iso(now()),
        "_seq": next_seq(),
    }
    STORE["events"][event["id"]] = event
    return event


def find_assignment(carrier_id, lane_id, ship_date_dt):
    """Assignment whose window covers ship_date; ties -> earliest created_at."""
    candidates = [
        a for a in STORE["assignments"].values()
        if a["carrier_id"] == carrier_id
        and a["lane_id"] == lane_id
        and a["_effective_from_dt"] <= ship_date_dt < a["_effective_to_dt"]
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda a: a.get("_seq", 0))
    return candidates[0]


def liability_pipeline(claim, shipment, carrier, negligence_flag=None):
    """Pinned five-step pipeline: basis -> model cap -> lane discount -> negligence.

    Returns (basis_cents, carrier_limit_cents_pre_discount, lane_discount_pct,
             computed_liability_cents). Floor at each multiplication step.
    """
    basis = min(claim["claimed_amount_cents"], shipment["declared_value_cents"])
    model = carrier["liability_model"]
    if model == "FULL_VALUE":
        cap = basis
    elif model == "RELEASED_RATE":
        cap = min(basis, shipment["total_weight_lbs"] * (carrier.get("released_rate_cents_per_lb") or 0))
    elif model == "PER_PACKAGE":
        cap = min(basis, shipment["package_count"] * (carrier.get("per_package_cap_cents") or 0))
    elif model == "PER_POUND":
        cap = min(basis, shipment["total_weight_lbs"] * (carrier.get("per_pound_cap_cents") or 0))
    else:
        cap = basis
    carrier_limit_cents = cap

    lane_discount_pct = 0
    assignment = find_assignment(shipment["carrier_id"], shipment["lane_id"],
                                 shipment["_ship_date_dt"])
    if assignment is not None and assignment["contracted_discount_pct"] > 0:
        lane_discount_pct = assignment["contracted_discount_pct"]
        cap = (cap * (100 - lane_discount_pct)) // 100

    if negligence_flag in ("SHIPPER_FAULT", "ACT_OF_GOD"):
        cap = 0

    return basis, carrier_limit_cents, lane_discount_pct, max(cap, 0)


def settlement_authority_tier(amount_cents, carrier):
    if amount_cents <= carrier["max_auto_settle_cents"]:
        return "TIER_1"
    if amount_cents <= TIER_2_CAP_CENTS:
        return "TIER_2"
    return "TIER_3"


def role_authority_tier(role):
    return {
        "ClaimsAdjuster": 1,
        "ClaimsManager": 2,
        "FinanceController": 3,
    }.get(role, 0)


def suggested_reserve_cents(claim, shipment, carrier, lane):
    base = Decimal(claim["net_exposure_cents"])
    if shipment["commodity_class"] == "HIGH_VALUE":
        base *= Decimal("1.20")
    if shipment.get("is_concealed_damage"):
        base *= Decimal("1.10")
    if carrier["claim_ratio_bp"] > LANE_ALERT_THRESHOLD_BP:
        base *= Decimal("1.15")
    if lane["lane_claim_ratio_bp"] > lane["baseline_claim_ratio_bp"]:
        base *= Decimal("1.05")
    cap = Decimal(claim["computed_liability_cents"] * MAX_RESERVE_MULTIPLE)
    return int(min(base, cap).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def active_open_reserve(claim_id):
    for reserve in STORE["reserves"].values():
        if reserve["claim_id"] == claim_id and reserve["state"] == "OPEN":
            return reserve
    return None


def claims_for_shipment(shipment_id):
    return [c for c in STORE["claims"].values() if c["shipment_id"] == shipment_id]


def revert_shipment_after_withdraw(shipment, withdrawn_claim_id):
    """Shipment returns CLAIMED -> DELIVERED if no other claim is non-terminal."""
    if shipment["status"] != "CLAIMED":
        return
    others = [
        c for c in claims_for_shipment(shipment["id"])
        if c["id"] != withdrawn_claim_id and c["filing_status"] not in TERMINAL_CLAIM_STATES
    ]
    if not others:
        shipment["status"] = "DELIVERED"
        touch(shipment)


def close_shipment_if_all_terminal(shipment):
    """CLAIMED -> CLOSED once every claim on the shipment is terminal."""
    if shipment["status"] != "CLAIMED":
        return
    claims = claims_for_shipment(shipment["id"])
    if claims and all(c["filing_status"] in TERMINAL_CLAIM_STATES for c in claims):
        shipment["status"] = "CLOSED"
        touch(shipment)


def execute_salvage(claim, salvage, actor_user_id):
    """SCHEDULED -> EXECUTED; posts the salvage credit to the claim."""
    salvage["state"] = "EXECUTED"
    salvage["net_credit_cents"] = max(
        salvage["gross_proceeds_cents"] - salvage["handling_cost_cents"], 0)
    touch(salvage)
    claim["salvage_credit_cents"] += salvage["net_credit_cents"]
    claim["net_exposure_cents"] = max(
        claim["computed_liability_cents"] - claim["salvage_credit_cents"], 0)
    add_event(claim["id"], "SALVAGE_POSTED", actor_user_id, {
        "salvage_id": salvage["id"],
        "net_credit_cents": salvage["net_credit_cents"],
    })
    touch_claim(claim)


def run_scheduled_sweeps():
    """Clock-driven transitions, run after every logical-clock advance."""
    current = now()

    # Time-barring.
    for claim in list(STORE["claims"].values()):
        deadline = claim.get("_filing_deadline_dt")
        if deadline is None:
            continue
        if claim["filing_status"] == "SUBMITTED" and current > deadline:
            claim["filing_status"] = "TIME_BARRED"
            carrier = STORE["carriers"].get(claim["carrier_id"])
            if carrier is not None:
                bump_carrier_counters(carrier, filed_delta=-1)
            add_event(claim["id"], "TIME_BARRED", "system", {
                "filing_deadline_at": claim["filing_deadline_at"],
            })
            touch_claim(claim)
            shipment = STORE["shipments"].get(claim["shipment_id"])
            if shipment is not None:
                close_shipment_if_all_terminal(shipment)
        elif (claim["filing_status"] == "ACKNOWLEDGED"
              and current > deadline + timedelta(days=365)):
            claim["filing_status"] = "TIME_BARRED"
            add_event(claim["id"], "TIME_BARRED", "system", {
                "filing_deadline_at": claim["filing_deadline_at"],
            })
            touch_claim(claim)
            shipment = STORE["shipments"].get(claim["shipment_id"])
            if shipment is not None:
                close_shipment_if_all_terminal(shipment)

    # Offer expiry: OFFERED settlements older than 14 days.
    for settlement in list(STORE["settlements"].values()):
        if (settlement["state"] == "OFFERED"
                and current > settlement["_created_dt"] + timedelta(days=14)):
            settlement["state"] = "EXPIRED"
            touch(settlement)
            claim = STORE["claims"].get(settlement["claim_id"])
            if claim is not None and claim["filing_status"] == "OFFERED":
                claim["filing_status"] = "UNDER_REVIEW"
                touch_claim(claim)

    # Salvage auto-execution once scheduled_at is reached.
    for salvage in list(STORE["salvage"].values()):
        if salvage["state"] == "SCHEDULED" and current >= salvage["_scheduled_at_dt"]:
            claim = STORE["claims"].get(salvage["claim_id"])
            if claim is not None and claim["filing_status"] in SALVAGE_EXECUTABLE_STATES:
                execute_salvage(claim, salvage, "system")

    # Acknowledgment-lateness sweep (strictly greater than due).
    for claim in list(STORE["claims"].values()):
        due = claim.get("_ack_due_dt")
        if (claim["filing_status"] == "SUBMITTED"
                and claim["acknowledged_at"] is None
                and due is not None
                and current > due
                and not claim["acknowledgment_late"]):
            claim["acknowledgment_late"] = True
            add_event(claim["id"], "ACK_LATE_FLAGGED", "system", {
                "acknowledgment_due_at": claim["acknowledgment_due_at"],
            })
            touch_claim(claim)
