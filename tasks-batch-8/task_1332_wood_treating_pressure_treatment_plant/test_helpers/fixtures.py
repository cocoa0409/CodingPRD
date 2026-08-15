"""Composite setup helpers for the wood-treating plant API.

Every helper builds preconditions from scratch using only PRD-declared
endpoints (each test runs against a fresh server). Setup calls use the
lenient `get_success_data` validator so failures surface as clear
"Setup step failed" errors.

The use_category retention lookup values are not stated in the PRD, so
assay-driving helpers read the charge's server-computed
`target_retention_pcf` and derive pass/fail inputs from it at runtime.
"""
from decimal import Decimal

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    CLOCK_NOW,
    CUSTOM_TREAT_UPLIFT,
    DRIP_ENTER,
    DRIP_EXIT_OK,
    FINDING_DEDUCTION,
    BASE_FEE_CENTS,
    INITIAL_COMPLIANCE_SCORE,
    SLOT_END,
    SLOT_START,
    TERM_MULTIPLIER,
    round_half_up,
)
from .factories import (
    create_assay_payload,
    create_charge_payload,
    create_cycle_payload,
    create_customer_payload,
    create_cylinder_payload,
    create_drip_log_payload,
    create_inspection_payload,
    create_plant_payload,
    create_preservative_payload,
    create_slot_payload,
    create_warranty_payload,
)
from .test_users import TEST_USERS

OP = TEST_USERS["plant_operator_headers"]
LAB = TEST_USERS["lab_technician_headers"]
QM = TEST_USERS["quality_manager_headers"]
INSP = TEST_USERS["inspector_headers"]
CO = TEST_USERS["compliance_officer_headers"]
AR = TEST_USERS["accounts_receivable_headers"]


# ---------------------------------------------------------------------------
# Administrative hooks (PRD §2.10)
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str = CLOCK_NOW):
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, CO))


def force_charge_state(charge_id: str, target_status: str) -> dict:
    return get_success_data(
        api_client.force_charge_state(charge_id, {"target_status": target_status}, CO)
    )


# ---------------------------------------------------------------------------
# Basic entity creators
# ---------------------------------------------------------------------------

def setup_plant(**overrides) -> dict:
    return get_success_data(api_client.create_plant(create_plant_payload(**overrides), CO))


def setup_cylinder(plant_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_cylinder(plant_id, create_cylinder_payload(**overrides), OP)
    )


def setup_preservative(plant_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_preservative(plant_id, create_preservative_payload(**overrides), LAB)
    )


def setup_customer(**overrides) -> dict:
    return get_success_data(api_client.create_customer(create_customer_payload(**overrides), AR))


def setup_closed_customer(**overrides) -> dict:
    """A customer account driven to CLOSED (zero balance, no open charges)."""
    customer = setup_customer(**overrides)
    return get_success_data(api_client.close_customer(customer["id"], AR))


def book_treatment_slot(plant_id: str, cylinder_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_slot(plant_id, cylinder_id, create_slot_payload(**overrides), OP)
    )


def setup_shop(max_volume_mbf: float = 50.0, with_slot: bool = True, **preservative_overrides) -> dict:
    """Plant (LICENSED) + one cylinder + one preservative + logical clock set
    to CLOCK_NOW + a wide TREATMENT slot covering the clock. Returns a dict of
    the created entities."""
    plant = setup_plant()
    cylinder = setup_cylinder(plant["id"], max_volume_mbf=max_volume_mbf)
    preservative = setup_preservative(plant["id"], **preservative_overrides)
    set_clock(CLOCK_NOW)
    slot = None
    if with_slot:
        slot = book_treatment_slot(plant["id"], cylinder["id"])
    return {"plant": plant, "cylinder": cylinder, "preservative": preservative, "slot": slot}


# ---------------------------------------------------------------------------
# Readers
# ---------------------------------------------------------------------------

def get_charge(plant_id: str, charge_id: str) -> dict:
    return get_success_data(api_client.get_charge(plant_id, charge_id, OP))


def get_plant(plant_id: str) -> dict:
    return get_success_data(api_client.get_plant(plant_id, CO))


def get_cylinder(plant_id: str, cylinder_id: str) -> dict:
    return get_success_data(api_client.get_cylinder(plant_id, cylinder_id, OP))


def get_customer(customer_id: str) -> dict:
    return get_success_data(api_client.get_customer(customer_id, AR))


def list_pieces(plant_id: str, charge_id: str) -> list:
    data, _meta = _list(api_client.list_pieces(plant_id, charge_id, OP))
    return data


def _list(response):
    from prd_bench_local_runner.testing import validate_paginated

    return validate_paginated(response)


# ---------------------------------------------------------------------------
# Charge loading and cycle execution
# ---------------------------------------------------------------------------

def load_charge(plant_id: str, cylinder_id: str, **overrides) -> dict:
    """Stage+load a charge; lands in IN_CYLINDER (PRD §3.5)."""
    return get_success_data(
        api_client.load_charge(plant_id, cylinder_id, create_charge_payload(**overrides), OP)
    )


def incise_all_pieces(plant_id: str, charge_id: str):
    for piece in list_pieces(plant_id, charge_id):
        get_success_data(api_client.incise_piece(plant_id, charge_id, piece["id"], OP))


def run_cycle_to_complete(plant_id: str, cylinder_id: str, preservative_id: str,
                          gross_absorption_pcf: float = 0.85, **cycle_overrides) -> dict:
    """Schedule → start → begin-drain → complete. Returns the COMPLETE cycle."""
    cycle = get_success_data(
        api_client.create_cycle(
            plant_id, cylinder_id,
            create_cycle_payload(preservative_id, **cycle_overrides), OP,
        )
    )
    get_success_data(api_client.start_cycle(plant_id, cylinder_id, cycle["id"], OP))
    get_success_data(api_client.begin_drain(plant_id, cylinder_id, cycle["id"], OP))
    return get_success_data(
        api_client.complete_cycle(
            plant_id, cylinder_id, cycle["id"],
            {"gross_absorption_pcf": gross_absorption_pcf}, OP,
        )
    )


def setup_cycle_complete_charge(shop: dict, incise_all: bool = False,
                                gross_absorption_pcf: float = 0.85,
                                **charge_overrides) -> tuple:
    """Load a charge (optionally incising every piece while IN_CYLINDER) and
    run one full cycle. Returns (charge in CYCLE_COMPLETE, cycle)."""
    plant_id = shop["plant"]["id"]
    cyl_id = shop["cylinder"]["id"]
    charge = load_charge(plant_id, cyl_id, **charge_overrides)
    if incise_all:
        incise_all_pieces(plant_id, charge["id"])
    cycle = run_cycle_to_complete(
        plant_id, cyl_id, shop["preservative"]["id"], gross_absorption_pcf
    )
    return get_charge(plant_id, charge["id"]), cycle


# ---------------------------------------------------------------------------
# Assay driving — outcome-safe values derived from the server's own target
# ---------------------------------------------------------------------------

def assay_threshold_bounds(target_retention_pcf: float) -> tuple:
    """Return (lower_bound, upper_bound) for the pass threshold, covering both
    an unrounded 0.90 * target and a 3-decimal-rounded variant (PRD §2.6, §3.7)."""
    raw = 0.9 * float(target_retention_pcf)
    rounded = float(round_half_up(raw, 3))
    return min(raw, rounded), max(raw, rounded)


def assay_values_for_outcome(target_retention_pcf: float, outcome: str) -> tuple:
    """(mean, min_sample) values that land unambiguously in the requested
    outcome region for any threshold interpretation (PRD §3.7)."""
    target = float(target_retention_pcf)
    lo, hi = assay_threshold_bounds(target)
    if outcome == "PASS":
        return target, hi
    if outcome == "FAIL_MARGINAL":
        mean = float(round_half_up(target - 0.001, 3))
        min_sample = float(round_half_up(lo - 0.001, 3))
        return mean, min_sample
    if outcome == "FAIL_GROSS":
        mean = float(round_half_up(lo - 0.001, 3))
        min_sample = float(round_half_up(lo - 0.002, 3))
        return mean, min_sample
    raise ValueError(f"unknown outcome {outcome!r}")


def record_assay_for_outcome(plant_id: str, charge_id: str, cycle_id: str,
                             outcome: str = "PASS") -> dict:
    """Record an assay whose mean/min are derived from the charge's live
    target_retention_pcf so the verdict is deterministic (PRD §3.7)."""
    charge = get_charge(plant_id, charge_id)
    mean, min_sample = assay_values_for_outcome(charge["target_retention_pcf"], outcome)
    return get_success_data(
        api_client.record_assay(
            plant_id, charge_id,
            create_assay_payload(cycle_id, mean, min_sample), LAB,
        )
    )


def setup_assayed_charge(shop: dict, outcome: str = "PASS", **charge_overrides) -> tuple:
    """Charge driven to ASSAYED_PASS / ASSAYED_FAIL. Returns (charge, cycle, assay)."""
    charge, cycle = setup_cycle_complete_charge(shop, **charge_overrides)
    assay = record_assay_for_outcome(shop["plant"]["id"], charge["id"], cycle["id"], outcome)
    return get_charge(shop["plant"]["id"], charge["id"]), cycle, assay


# ---------------------------------------------------------------------------
# Drip pad, tagging, release
# ---------------------------------------------------------------------------

def log_drip_pad(plant_id: str, charge_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_drip_log(plant_id, charge_id, create_drip_log_payload(**overrides), OP)
    )


def setup_tagged_charge(shop: dict, **charge_overrides) -> dict:
    """Charge driven to TAGGED: full cycle, PASS assay, clean 24h+ drip dwell,
    tag. Returns the TAGGED charge."""
    charge, _cycle, _assay = setup_assayed_charge(shop, outcome="PASS", **charge_overrides)
    plant_id = shop["plant"]["id"]
    log_drip_pad(plant_id, charge["id"])
    return get_success_data(api_client.tag_charge(plant_id, charge["id"], OP))


def setup_released_charge(shop: dict, warranty_term_years: int = 25,
                          **charge_overrides) -> tuple:
    """Charge driven to RELEASED via warranty registration. Returns
    (warranty, released charge)."""
    if charge_overrides.get("ownership_type") == "CUSTOM_TREAT" and "customer_id" not in charge_overrides:
        charge_overrides["customer_id"] = setup_customer()["id"]
    tagged = setup_tagged_charge(shop, **charge_overrides)
    plant_id = shop["plant"]["id"]
    warranty = get_success_data(
        api_client.register_warranty(
            plant_id, tagged["id"],
            create_warranty_payload(tagged["version"], warranty_term_years=warranty_term_years),
            OP,
        )
    )
    return warranty, get_charge(plant_id, tagged["id"])


# ---------------------------------------------------------------------------
# Inspections and plant governance
# ---------------------------------------------------------------------------

def setup_inspection(plant_id: str, charges_in_scope=None, severity: str = "MINOR",
                     window: tuple = None) -> dict:
    start, end = window or ("2026-08-01T00:00:00Z", "2027-01-01T00:00:00Z")
    return get_success_data(
        api_client.create_inspection(
            plant_id,
            create_inspection_payload(
                inspection_window_start=start,
                inspection_window_end=end,
                charges_in_scope=charges_in_scope or [],
                severity=severity,
            ),
            INSP,
        )
    )


def drive_inspection_to_findings(plant_id: str, inspection_id: str,
                                 findings_count: int = 1, severity: str = "CRITICAL") -> dict:
    """Begin (clock is inside the wide window) and issue findings."""
    get_success_data(api_client.begin_inspection(plant_id, inspection_id, INSP))
    return get_success_data(
        api_client.issue_findings(
            plant_id, inspection_id,
            {"findings_count": findings_count, "severity": severity}, INSP,
        )
    )


def drive_plant_score_to_zero(plant_id: str):
    """Five CRITICAL findings (5 x 200 = 1000) drive the score to exactly 0
    (PRD §2.5, §3.9)."""
    for _ in range(INITIAL_COMPLIANCE_SCORE // FINDING_DEDUCTION["CRITICAL"]):
        inspection = setup_inspection(plant_id, severity="CRITICAL")
        drive_inspection_to_findings(plant_id, inspection["id"], severity="CRITICAL")


# ---------------------------------------------------------------------------
# Expectation helpers implementing the PRD's pinned arithmetic (§3.6–§3.8)
# ---------------------------------------------------------------------------

def expected_provisional_retention(gross_absorption_pcf: float, solution_assay_pct: float,
                                   piece_factors: list) -> float:
    """PRD §3.6: charge-level provisional is the average of the per-piece
    contributions, rounded half-up to 3 decimals after all multiplications."""
    contributions = [
        Decimal(str(gross_absorption_pcf)) * (Decimal(str(solution_assay_pct)) / 100) * Decimal(str(f))
        for f in piece_factors
    ]
    averaged = sum(contributions) / Decimal(len(contributions))
    return float(round_half_up(averaged, 3))


def expected_final_retention_uniform(mean_retention_pcf: float, piece_volumes_cuft: list) -> float:
    """PRD §3.7: with a uniform species factor each piece's retention equals the
    recorded mean; each per-piece contribution (retention x volume) is rounded
    to 4 decimals before summing; the final ratio rounds half-up to 3 decimals."""
    mean = Decimal(str(mean_retention_pcf))
    volumes = [Decimal(str(v)) for v in piece_volumes_cuft]
    contributions = [round_half_up(mean * v, 4) for v in volumes]
    return float(round_half_up(sum(contributions) / sum(volumes), 3))


def piece_volume_cuft(length_ft: float, width_in: float, thickness_in: float) -> float:
    """PRD §3.7: length_ft x width_in x thickness_in / 12."""
    return float(Decimal(str(length_ft)) * Decimal(str(width_in)) * Decimal(str(thickness_in)) / 12)


def expected_registration_fee_cents(use_category: str, volume_mbf: float,
                                    is_custom_treat: bool, warranty_term_years: int) -> int:
    """PRD §3.8 pinned order: base -> volume discount -> custom uplift ->
    term multiplier, rounding half-up to whole cents at each step."""
    fee = Decimal(BASE_FEE_CENTS[use_category])
    if volume_mbf <= 10:
        discount = Decimal("0")
    elif volume_mbf <= 50:
        discount = Decimal("0.05")
    else:
        discount = Decimal("0.12")
    fee = round_half_up(fee * (1 - discount), 0)
    uplift = CUSTOM_TREAT_UPLIFT if is_custom_treat else Decimal("0")
    fee = round_half_up(fee * (1 + uplift), 0)
    fee = round_half_up(fee * TERM_MULTIPLIER[str(warranty_term_years)], 0)
    return int(fee)
