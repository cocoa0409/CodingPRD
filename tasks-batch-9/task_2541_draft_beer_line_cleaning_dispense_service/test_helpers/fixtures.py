"""Composite setup helpers built only from endpoints the PRD declares.

The harness restarts the service and empties its store before every test, so each
helper below builds its preconditions from scratch: it advances the logical clock,
onboards a venue, activates a contract, registers lines, crew, chemistry and
catalogue parts, books a visit and — where the caller asks for it — opens the
visit and logs field work.  Helpers return plain dictionaries whose keys name the
rows they created so tests can read them without re-deriving anything.
"""

from typing import Any, Dict, List, Optional, Sequence

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import ApiClient
from .test_users import (
    AUDITOR_HEADERS,
    BREWER_HEADERS,
    DISPATCH_HEADERS,
    make_service_technician_headers,
    make_venue_manager_headers,
)
from .types import ContractStatus

CLOCK_EPOCH = "2026-08-01T00:00:00Z"


# ---------------------------------------------------------------------------
# Tier 1 — single-row builders
# ---------------------------------------------------------------------------
def set_clock(api: ApiClient, current_utc: str) -> None:
    """Move the logical service clock."""
    get_success_data(api.set_clock(current_utc, DISPATCH_HEADERS))


def create_account(api: ApiClient, **kwargs) -> Dict[str, Any]:
    """Onboard one venue; the account opens ACTIVE at version 1."""
    return get_success_data(api.create_account(f.account_payload(**kwargs), DISPATCH_HEADERS))


def create_brewer_program(api: ApiClient, **kwargs) -> Dict[str, Any]:
    return get_success_data(
        api.create_brewer_program(f.brewer_program_payload(**kwargs), DISPATCH_HEADERS)
    )


def create_technician(api: ApiClient, **kwargs) -> Dict[str, Any]:
    return get_success_data(api.create_technician(f.technician_payload(**kwargs), DISPATCH_HEADERS))


def create_chemical_lot(api: ApiClient, **kwargs) -> Dict[str, Any]:
    return get_success_data(
        api.create_chemical_lot(f.chemical_lot_payload(**kwargs), DISPATCH_HEADERS)
    )


def create_part(api: ApiClient, **kwargs) -> Dict[str, Any]:
    return get_success_data(api.create_part(f.part_payload(**kwargs), DISPATCH_HEADERS))


def create_beer_line(api: ApiClient, account_id: str, **kwargs) -> Dict[str, Any]:
    return get_success_data(
        api.create_beer_line(f.beer_line_payload(account_id, **kwargs), DISPATCH_HEADERS)
    )


def draft_contract(api: ApiClient, account_id: str, account_version: int, **kwargs) -> Dict[str, Any]:
    """Draft a contract against the account's current version token."""
    return get_success_data(
        api.create_contract(f.contract_payload(account_id, account_version, **kwargs), DISPATCH_HEADERS)
    )


def activate_contract(api: ApiClient, contract_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.set_contract_status(contract_id, ContractStatus.ACTIVE, DISPATCH_HEADERS)
    )


def book_visit(api: ApiClient, account_id: str, technician_id: str, **kwargs) -> Dict[str, Any]:
    return get_success_data(
        api.create_service_visit(
            f.service_visit_payload(account_id, technician_id, **kwargs), DISPATCH_HEADERS
        ),
        expected_status=201,
    )


def start_visit(api: ApiClient, visit_id: str, technician_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.start_visit(visit_id, make_service_technician_headers(technician_id))
    )


def log_cleaning_cycle(
    api: ApiClient, visit_id: str, line_id: str, lot_id: str, technician_id: str, **kwargs
) -> Dict[str, Any]:
    return get_success_data(
        api.create_cleaning_cycle(
            f.cleaning_cycle_payload(visit_id, line_id, lot_id, **kwargs),
            make_service_technician_headers(technician_id),
        ),
        expected_status=201,
    )


def log_inspection(
    api: ApiClient, visit_id: str, line_id: str, technician_id: str, **kwargs
) -> Dict[str, Any]:
    return get_success_data(
        api.create_component_inspection(
            f.component_inspection_payload(visit_id, line_id, **kwargs),
            make_service_technician_headers(technician_id),
        ),
        expected_status=201,
    )


def propose_balance(
    api: ApiClient, visit_id: str, line_id: str, line_version: int, technician_id: str, **kwargs
) -> Dict[str, Any]:
    return get_success_data(
        api.create_balance_record(
            f.balance_record_payload(visit_id, line_id, line_version, **kwargs),
            make_service_technician_headers(technician_id),
        ),
        expected_status=201,
    )


def read_glycol_loop_of(api: ApiClient, account_id: str) -> Dict[str, Any]:
    """The cascade-created loop is discoverable only by filtering the collection."""
    body = get_success_data(api.list_glycol_loops(DISPATCH_HEADERS, account_id=account_id))
    assert body, f"account {account_id} should own one glycol loop"
    return body[0]


def read_account(api: ApiClient, account_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_account(account_id, DISPATCH_HEADERS))


def read_contract(api: ApiClient, contract_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_contract(contract_id, DISPATCH_HEADERS))


def read_line(api: ApiClient, line_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_beer_line(line_id, DISPATCH_HEADERS))


def read_visit(api: ApiClient, visit_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_service_visit(visit_id, DISPATCH_HEADERS))


def read_lot(api: ApiClient, lot_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_chemical_lot(lot_id, DISPATCH_HEADERS))


def read_part(api: ApiClient, part_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_part(part_id, DISPATCH_HEADERS))


def read_program(api: ApiClient, program_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_brewer_program(program_id, DISPATCH_HEADERS))


def read_cycle(api: ApiClient, cycle_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_cleaning_cycle(cycle_id, DISPATCH_HEADERS))


def read_balance_record(api: ApiClient, record_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_balance_record(record_id, DISPATCH_HEADERS))


def read_complaint(api: ApiClient, complaint_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_quality_complaint(complaint_id, DISPATCH_HEADERS))


def read_loop(api: ApiClient, loop_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_glycol_loop(loop_id, AUDITOR_HEADERS))


# ---------------------------------------------------------------------------
# Tier 2 — venue hierarchy
# ---------------------------------------------------------------------------
DEFAULT_LINE = {
    "line_number": 1,
    "run_length_feet": 32,
    "vertical_rise_feet": 4,
    "inner_diameter_inches": 0.375,
    "beer_style_group": "ALE",
    "average_daily_throughput_liters": 12.0,
}


def onboard_venue(
    api: ApiClient,
    venue_name: str = "Harbor Taproom",
    access_window: Sequence[int] = (480, 1080),
    glycol_system_present: bool = False,
    cleaning_frequency_days: int = 21,
    contracted_line_count: int = 4,
    per_line_rate_cents: int = 4175,
    visit_base_fee_cents: int = 7500,
    effective_from: str = CLOCK_EPOCH,
    brewer_program_id: Optional[str] = None,
    lines: Optional[Sequence[Dict[str, Any]]] = (DEFAULT_LINE,),
    activate: bool = True,
) -> Dict[str, Any]:
    """Onboard a venue, draft and activate its contract, and register its lines.

    Returns ``{"account", "contract", "lines", "loop"}`` where ``loop`` is the
    cascade-created glycol loop when the venue declared a glycol system.
    """
    account = create_account(
        api,
        venue_name=venue_name,
        access_window_start_minute=access_window[0],
        access_window_end_minute=access_window[1],
        glycol_system_present=glycol_system_present,
    )
    contract = draft_contract(
        api,
        account["id"],
        account["version"],
        cleaning_frequency_days=cleaning_frequency_days,
        contracted_line_count=contracted_line_count,
        per_line_rate_cents=per_line_rate_cents,
        visit_base_fee_cents=visit_base_fee_cents,
        effective_from=effective_from,
        brewer_program_id=brewer_program_id,
    )
    if activate:
        contract = activate_contract(api, contract["id"])
    loop = read_glycol_loop_of(api, account["id"]) if glycol_system_present else None
    built_lines: List[Dict[str, Any]] = []
    for spec in lines or ():
        built_lines.append(create_beer_line(api, account["id"], **spec))
    return {
        "account": read_account(api, account["id"]),
        "contract": contract,
        "lines": built_lines,
        "loop": loop,
    }


# ---------------------------------------------------------------------------
# Tier 3 — open job on the route board
# ---------------------------------------------------------------------------
def setup_started_visit(
    api: ApiClient,
    venue_name: str = "Harbor Taproom",
    glycol_system_present: bool = False,
    cleaning_frequency_days: int = 21,
    contracted_line_count: int = 4,
    per_line_rate_cents: int = 4175,
    visit_base_fee_cents: int = 7500,
    brewer_program_id: Optional[str] = None,
    access_window: Sequence[int] = (480, 1080),
    lines: Optional[Sequence[Dict[str, Any]]] = (DEFAULT_LINE,),
    technician_spec: Optional[Dict[str, Any]] = None,
    lot_specs: Sequence[Dict[str, Any]] = ({},),
    part_specs: Sequence[Dict[str, Any]] = (),
    visit_kind: str = "ROUTINE_CLEANING",
    scheduled_date: str = "2026-08-05",
    scheduled_start_minute: int = 540,
    scheduled_end_minute: int = 660,
    visit_clock: str = "2026-08-05T09:00:00Z",
    start: bool = True,
) -> Dict[str, Any]:
    """Build a venue with an open job the crew has already started.

    The chain is: set the clock to the epoch, onboard the venue and activate its
    contract, register the lines, hire the crew, receive the chemistry, stock the
    catalogue, book the visit, advance the clock onto the visit's day and open the
    job.  Returns every row it created, keyed by name.
    """
    set_clock(api, CLOCK_EPOCH)
    venue = onboard_venue(
        api,
        venue_name=venue_name,
        access_window=access_window,
        glycol_system_present=glycol_system_present,
        cleaning_frequency_days=cleaning_frequency_days,
        contracted_line_count=contracted_line_count,
        per_line_rate_cents=per_line_rate_cents,
        visit_base_fee_cents=visit_base_fee_cents,
        brewer_program_id=brewer_program_id,
        lines=lines,
    )
    technician = create_technician(api, **(technician_spec or {}))
    lots = [create_chemical_lot(api, **spec) for spec in lot_specs]
    parts = [create_part(api, **spec) for spec in part_specs]
    visit = book_visit(
        api,
        venue["account"]["id"],
        technician["id"],
        visit_kind=visit_kind,
        scheduled_date=scheduled_date,
        scheduled_start_minute=scheduled_start_minute,
        scheduled_end_minute=scheduled_end_minute,
    )
    if visit_clock:
        set_clock(api, visit_clock)
    if start:
        visit = start_visit(api, visit["id"], technician["id"])
    ground = dict(venue)
    ground.update(
        {
            "technician": technician,
            "tech_headers": make_service_technician_headers(technician["id"]),
            "manager_headers": make_venue_manager_headers(venue["account"]["id"]),
            "lots": lots,
            "parts": parts,
            "visit": visit,
        }
    )
    ground["line"] = venue["lines"][0] if venue["lines"] else None
    ground["lot"] = lots[0] if lots else None
    ground["part"] = parts[0] if parts else None
    return ground


# ---------------------------------------------------------------------------
# Tier 4 — accumulated field work and close-out
# ---------------------------------------------------------------------------
THREE_LINE_LAYOUT = (
    {
        "line_number": 1,
        "run_length_feet": 32,
        "vertical_rise_feet": 4,
        "inner_diameter_inches": 0.375,
        "beer_style_group": "ALE",
        "average_daily_throughput_liters": 12.0,
    },
    {
        "line_number": 2,
        "run_length_feet": 32,
        "vertical_rise_feet": 4,
        "inner_diameter_inches": 0.375,
        "beer_style_group": "LAGER",
        "average_daily_throughput_liters": 10.0,
    },
    {
        "line_number": 3,
        "run_length_feet": 15,
        "vertical_rise_feet": 3,
        "inner_diameter_inches": 0.375,
        "beer_style_group": "ALE",
        "average_daily_throughput_liters": 8.0,
    },
)

#: A 32 ft / 0.375 in line cleaned with caustic at full strength grades PASS.
PASSING_CAUSTIC_CYCLE = {
    "chemical_type": "CAUSTIC",
    "contact_minutes": 20,
    "recirculation_temp_f": 96.0,
    "concentrate_liters_used": 0.31,
}

#: A 15 ft line dosed at 0.31 L reaches the top strength tier, which demands 15
#: contact minutes; logging only 14 grades the circulation a contact-time failure.
SHORT_CONTACT_CYCLE = {
    "chemical_type": "CAUSTIC",
    "contact_minutes": 14,
    "recirculation_temp_f": 96.0,
    "concentrate_liters_used": 0.18,
}


def setup_three_line_visit_with_work(
    api: ApiClient,
    cleaning_frequency_days: int = 21,
    contracted_line_count: int = 4,
    per_line_rate_cents: int = 4175,
    visit_base_fee_cents: int = 7500,
    brewer_program_id: Optional[str] = None,
    venue_name: str = "Harbor Taproom",
    third_line_cycle: Dict[str, Any] = SHORT_CONTACT_CYCLE,
    replace_faucet: bool = True,
    faucet_price_cents: int = 3195,
    faucet_brewer_funded_eligible: bool = True,
    complete_work: bool = True,
) -> Dict[str, Any]:
    """Three lines circulated on one job, one of them grading below par.

    Lines 1 and 2 are cleaned to a pass; line 3 is dosed so that its achieved
    strength demands more contact time than the crew logged.  When
    ``replace_faucet`` is set the crew also swaps a faucet on line 1, which stamps
    the part's price onto the visit's parts charge.
    """
    ground = setup_started_visit(
        api,
        venue_name=venue_name,
        cleaning_frequency_days=cleaning_frequency_days,
        contracted_line_count=contracted_line_count,
        per_line_rate_cents=per_line_rate_cents,
        visit_base_fee_cents=visit_base_fee_cents,
        brewer_program_id=brewer_program_id,
        lines=THREE_LINE_LAYOUT,
        lot_specs=({},),
        part_specs=(
            {
                "sku": "FAUCET-88",
                "component_type": "FAUCET",
                "unit_price_cents": faucet_price_cents,
                "stock_on_hand": 5,
                "brewer_funded_eligible": faucet_brewer_funded_eligible,
            },
        )
        if replace_faucet
        else (),
    )
    tech_id = ground["technician"]["id"]
    lot_id = ground["lot"]["id"]
    visit_id = ground["visit"]["id"]
    cycles = [
        log_cleaning_cycle(
            api, visit_id, ground["lines"][0]["id"], lot_id, tech_id, **PASSING_CAUSTIC_CYCLE
        ),
        log_cleaning_cycle(
            api, visit_id, ground["lines"][1]["id"], lot_id, tech_id, **PASSING_CAUSTIC_CYCLE
        ),
        log_cleaning_cycle(
            api, visit_id, ground["lines"][2]["id"], lot_id, tech_id, **third_line_cycle
        ),
    ]
    inspections = []
    if replace_faucet:
        inspections.append(
            log_inspection(
                api,
                visit_id,
                ground["lines"][0]["id"],
                tech_id,
                component_type="FAUCET",
                condition_grade="WORN",
                action_taken="REPLACED",
                part_sku_id=ground["part"]["id"],
            )
        )
    ground["cycles"] = cycles
    ground["inspections"] = inspections
    if complete_work:
        ground["visit"] = complete_work_on(api, visit_id, tech_id)
    return ground


def complete_work_on(api: ApiClient, visit_id: str, technician_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.complete_visit_work(visit_id, make_service_technician_headers(technician_id))
    )


def sign_visit(
    api: ApiClient, visit_id: str, account_id: str, signer_name: str = "Priya N."
) -> Dict[str, Any]:
    return get_success_data(
        api.record_verification(
            visit_id,
            f.verification_payload(decision="SIGN", signer_name=signer_name),
            make_venue_manager_headers(account_id),
        )
    )


def dispute_visit(
    api: ApiClient,
    visit_id: str,
    account_id: str,
    dispute_reason: str = "Line 3 was never cleaned; the parts charge is contested.",
) -> Dict[str, Any]:
    return get_success_data(
        api.record_verification(
            visit_id,
            f.verification_payload(decision="DISPUTE", dispute_reason=dispute_reason),
            make_venue_manager_headers(account_id),
        )
    )


def waive_verification(
    api: ApiClient, visit_id: str, waiver_note: str = "The venue never answered the sign-off request."
) -> Dict[str, Any]:
    return get_success_data(
        api.record_verification_waiver(visit_id, waiver_note, AUDITOR_HEADERS)
    )


# ---------------------------------------------------------------------------
# Tier 4 — complaints
# ---------------------------------------------------------------------------
def file_complaint(
    api: ApiClient, account_id: str, line_id: str, symptom: str = "FOAMY_POUR"
) -> Dict[str, Any]:
    return get_success_data(
        api.create_quality_complaint(
            f.quality_complaint_payload(account_id, line_id, symptom),
            make_venue_manager_headers(account_id),
        ),
        expected_status=201,
    )


def run_diagnostic_round(
    api: ApiClient,
    complaint_id: str,
    outcome: str = "ROOT_CAUSE_FOUND",
    finding_code: str = "LINE_SOIL",
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    return get_success_data(
        api.record_diagnostic_round(
            complaint_id,
            f.diagnostic_round_payload(outcome=outcome, finding_code=finding_code),
            headers or AUDITOR_HEADERS,
        )
    )


def close_complaint(
    api: ApiClient,
    complaint_id: str,
    disposition: str = "RESOLVED",
    measured_waste_liters: float = 4.0,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    return get_success_data(
        api.close_quality_complaint(
            complaint_id,
            f.closure_payload(disposition=disposition, measured_waste_liters=measured_waste_liters),
            headers or AUDITOR_HEADERS,
        )
    )


def reopen_complaint(
    api: ApiClient, complaint_id: str, account_id: str, reopen_reason: str = "The foam is back."
) -> Dict[str, Any]:
    return get_success_data(
        api.reopen_quality_complaint(
            complaint_id, reopen_reason, make_venue_manager_headers(account_id)
        )
    )


# ---------------------------------------------------------------------------
# Tier 4 — glycol readings
# ---------------------------------------------------------------------------
def post_cooler_readings(
    api: ApiClient,
    loop_id: str,
    temperatures: Sequence[float],
    headers: Dict[str, str],
    glycol_supply_temp_f: float = 26.0,
) -> List[Dict[str, Any]]:
    """Post one reading per temperature, oldest first."""
    readings = []
    for temp in temperatures:
        readings.append(
            get_success_data(
                api.create_cooler_reading(
                    f.cooler_reading_payload(
                        loop_id, cooler_temp_f=temp, glycol_supply_temp_f=glycol_supply_temp_f
                    ),
                    headers,
                ),
                expected_status=201,
            )
        )
    return readings


def record_glycol_maintenance(
    api: ApiClient, loop_id: str, visit_id: str, technician_id: str, **kwargs
) -> Dict[str, Any]:
    return get_success_data(
        api.record_glycol_maintenance(
            loop_id,
            f.glycol_maintenance_payload(visit_id, **kwargs),
            make_service_technician_headers(technician_id),
        )
    )


def setup_glycol_maintenance_visit(
    api: ApiClient,
    venue_name: str = "Glacier Hall",
    glycol_pct: Optional[float] = None,
    pump_psi: float = 12.0,
    bath_temp_f: float = 28.0,
) -> Dict[str, Any]:
    """A venue with a glycol system and an open GLYCOL_MAINTENANCE job.

    When ``glycol_pct`` is supplied the crew also records the loop's bath figures,
    which resets ``last_serviced_at`` to the clock's current reading.
    """
    ground = setup_started_visit(
        api,
        venue_name=venue_name,
        glycol_system_present=True,
        visit_kind="GLYCOL_MAINTENANCE",
        lot_specs=(),
        lines=(DEFAULT_LINE,),
    )
    if glycol_pct is not None:
        ground["loop"] = record_glycol_maintenance(
            api,
            ground["loop"]["id"],
            ground["visit"]["id"],
            ground["technician"]["id"],
            glycol_pct=glycol_pct,
            pump_psi=pump_psi,
            bath_temp_f=bath_temp_f,
        )
    return ground


# ---------------------------------------------------------------------------
# Tier 5 — terminal states
# ---------------------------------------------------------------------------
def setup_settled_visit(
    api: ApiClient,
    brewer_program_id: Optional[str] = None,
    cleaning_frequency_days: int = 21,
    contracted_line_count: int = 4,
    **kwargs,
) -> Dict[str, Any]:
    """A three-line job that has been closed out and signed by the venue."""
    ground = setup_three_line_visit_with_work(
        api,
        cleaning_frequency_days=cleaning_frequency_days,
        contracted_line_count=contracted_line_count,
        brewer_program_id=brewer_program_id,
        **kwargs,
    )
    ground["visit"] = sign_visit(api, ground["visit"]["id"], ground["account"]["id"])
    return ground


def suspend_account(api: ApiClient, account_id: str) -> Dict[str, Any]:
    return get_success_data(api.set_account_status(account_id, "SUSPENDED", AUDITOR_HEADERS))


def terminate_account(api: ApiClient, account_id: str) -> Dict[str, Any]:
    return get_success_data(api.set_account_status(account_id, "TERMINATED", AUDITOR_HEADERS))


def reactivate_account(api: ApiClient, account_id: str) -> Dict[str, Any]:
    return get_success_data(api.set_account_status(account_id, "ACTIVE", AUDITOR_HEADERS))


def end_program(api: ApiClient, program_id: str, end_note: str = "Season programme closed by the brewer.") -> Dict[str, Any]:
    return get_success_data(api.end_brewer_program(program_id, end_note, BREWER_HEADERS))


def adjust_program_cap(api: ApiClient, program_id: str, additional_cents: int) -> Dict[str, Any]:
    return get_success_data(api.adjust_program_cap(program_id, additional_cents, BREWER_HEADERS))


def void_cycle(api: ApiClient, cycle_id: str, void_reason: str = "Logged against the wrong line.") -> Dict[str, Any]:
    return get_success_data(api.void_cleaning_cycle(cycle_id, void_reason, AUDITOR_HEADERS))
