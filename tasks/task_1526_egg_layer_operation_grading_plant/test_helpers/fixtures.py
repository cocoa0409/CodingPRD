"""Composite setup helpers for the layer-farm and grading-plant workflows (PRD §3).

Every helper builds its preconditions from scratch through PRD-declared
endpoints: the harness restarts the API server before each test, so each test
starts against an empty database and must construct all of its own state.
Setup calls use get_success_data so failures surface as clear setup errors
rather than confusing assertion failures downstream.
"""
from prd_bench_local_runner.testing import get_success_data

from . import factories
from .api_client import api_client
from .constants import DEFAULT_PLACEMENT_DATE
from .test_users import TEST_USERS

# Shared role headers (all roles are opaque; the segregation-of-duties pairs
# below differ in X-User-ID: grader-1 vs qa-1).
ADMIN = TEST_USERS["platform_admin_headers"]
FARM_MANAGER = TEST_USERS["farm_manager_headers"]
GRADER = TEST_USERS["quality_grader_headers"]
QA_MANAGER = TEST_USERS["qa_manager_headers"]
CONTRACT_MANAGER = TEST_USERS["contract_manager_headers"]
COMPLIANCE_OFFICER = TEST_USERS["compliance_officer_headers"]


# ---------------------------------------------------------------- clock / ops
def set_clock(to_iso8601: str) -> dict:
    """Drive the server's logical clock (PRD §2.4)."""
    return get_success_data(api_client.set_current_utc({"to_iso8601": to_iso8601}, ADMIN))


def run_daily_ops() -> dict:
    """Run the daily ops checkpoint; returns the summary object (PRD §2.4)."""
    return get_success_data(api_client.run_daily_ops(ADMIN))


# ---------------------------------------------------------------- readers
def get_farm(farm_id: str) -> dict:
    return get_success_data(api_client.get_farm(farm_id, ADMIN))


def get_house(house_id: str) -> dict:
    return get_success_data(api_client.get_house(house_id, ADMIN))


def get_flock(flock_id: str) -> dict:
    return get_success_data(api_client.get_flock(flock_id, FARM_MANAGER))


def get_feed_delivery(delivery_id: str) -> dict:
    return get_success_data(api_client.get_feed_delivery(delivery_id, FARM_MANAGER))


def get_lot(lot_id: str) -> dict:
    return get_success_data(api_client.get_lot(lot_id, QA_MANAGER))


def get_contract(contract_id: str) -> dict:
    return get_success_data(api_client.get_contract(contract_id, CONTRACT_MANAGER))


def get_settlement(settlement_id: str) -> dict:
    return get_success_data(api_client.get_settlement(settlement_id, CONTRACT_MANAGER))


def get_grading_run(run_id: str) -> dict:
    return get_success_data(api_client.get_grading_run(run_id, QA_MANAGER))


def get_salmonella_test(test_id: str) -> dict:
    return get_success_data(api_client.get_salmonella_test(test_id, QA_MANAGER))


def get_recall(recall_id: str) -> dict:
    return get_success_data(api_client.get_recall(recall_id, COMPLIANCE_OFFICER))


def get_disposition(disposition_id: str) -> dict:
    return get_success_data(api_client.get_disposition(disposition_id, FARM_MANAGER))


def lots_of_run(run_id: str) -> list:
    """All lots created by one grading run."""
    return get_success_data(
        api_client.list_lots(QA_MANAGER, params={"grading_run_id": run_id})
    )


# ------------------------------------------------------- tier 2: hierarchy
def setup_farm(**overrides) -> dict:
    return get_success_data(
        api_client.create_farm(factories.farm_payload(**overrides), ADMIN)
    )


def setup_house(farm_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_house(factories.house_payload(farm_id, **overrides), FARM_MANAGER)
    )


def setup_farm_house(farm_overrides=None, house_overrides=None) -> dict:
    farm = setup_farm(**(farm_overrides or {}))
    house = setup_house(farm["id"], **(house_overrides or {}))
    return {"farm": farm, "house": house}


def place_flock(house_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_flock(factories.flock_payload(house_id, **overrides), FARM_MANAGER)
    )


def setup_farm_house_flock(
    placement_date=DEFAULT_PLACEMENT_DATE,
    farm_overrides=None,
    house_overrides=None,
    flock_overrides=None,
) -> dict:
    """Farm + house + one flock just placed (status PLACED)."""
    ctx = setup_farm_house(farm_overrides, house_overrides)
    ov = dict(flock_overrides or {})
    ov.setdefault("placement_date", placement_date)
    ctx["flock"] = place_flock(ctx["house"]["id"], **ov)
    return ctx


# ------------------------------------------- tier 1: state progression
def setup_laying_flock(
    placement_date=DEFAULT_PLACEMENT_DATE,
    clock_iso=None,
    **kwargs,
) -> dict:
    """Farm + house + flock advanced to LAYING by one daily ops run (PRD §3.2).

    With the default placement date (2026-01-05) the flock is past eighteen
    weeks of age at the startup clock, so a single ops run walks it through
    PLACED -> GROWING -> LAYING.
    """
    ctx = setup_farm_house_flock(placement_date=placement_date, **kwargs)
    if clock_iso is not None:
        set_clock(clock_iso)
    run_daily_ops()
    ctx["flock"] = get_flock(ctx["flock"]["id"])
    assert ctx["flock"]["status"] == "LAYING", (
        f"setup expected LAYING flock, got {ctx['flock']['status']}"
    )
    return ctx


def setup_two_laying_flocks(**kwargs) -> dict:
    """One farm with two houses, each holding a LAYING flock."""
    farm = setup_farm(**(kwargs.get("farm_overrides") or {}))
    house1 = setup_house(farm["id"], house_code="H1")
    house2 = setup_house(farm["id"], house_code="H2")
    flock_a = place_flock(house1["id"])
    flock_b = place_flock(
        house2["id"], breed_code="ISA_WHITE", breed_peak_rate_pct=94.0
    )
    run_daily_ops()
    return {
        "farm": farm,
        "house1": get_house(house1["id"]),
        "house2": get_house(house2["id"]),
        "flock_a": get_flock(flock_a["id"]),
        "flock_b": get_flock(flock_b["id"]),
    }


# ------------------------------------------------- production / feed
def record_feed_delivery(farm_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_feed_delivery(
            factories.feed_delivery_payload(farm_id, **overrides), FARM_MANAGER
        )
    )


def record_production_days(flock_id: str, days: list) -> list:
    """Record one production day per dict of payload overrides (PRD §3.3)."""
    out = []
    for day in days:
        out.append(
            get_success_data(
                api_client.create_production_day(
                    factories.production_day_payload(flock_id, **day), FARM_MANAGER
                )
            )
        )
    return out


def setup_laying_flock_with_production(production_days=None, **kwargs) -> dict:
    """LAYING flock with production days recorded (default: one 240-egg day)."""
    ctx = setup_laying_flock(**kwargs)
    days = (
        production_days
        if production_days is not None
        else [{"lay_date": "2026-07-31", "eggs_collected": 240}]
    )
    ctx["production_days"] = record_production_days(ctx["flock"]["id"], days)
    ctx["flock"] = get_flock(ctx["flock"]["id"])
    return ctx


# ------------------------------------------------- grading runs / lots
def confirm_grading_run(flock_id, grade="A", eggs_to_grade=240, submit_counts=None):
    """Open -> submit -> confirm a grading run (PRD §3.4).

    Submitter and confirmer differ in X-User-ID, satisfying the segregation
    of duties pair. Returns (confirmed run, lots created by the confirm).
    """
    run = get_success_data(
        api_client.create_grading_run(
            factories.grading_run_payload(
                flock_id, grade=grade, eggs_to_grade=eggs_to_grade
            ),
            GRADER,
        )
    )
    counts = (
        submit_counts
        if submit_counts is not None
        else factories.grading_submit_payload(large_count=eggs_to_grade)
    )
    get_success_data(api_client.submit_grading_run(run["id"], counts, GRADER))
    run = get_success_data(api_client.confirm_grading_run(run["id"], QA_MANAGER))
    return run, lots_of_run(run["id"])


def setup_confirmed_lot(
    grade="A", eggs_to_grade=240, submit_counts=None, **kwargs
) -> dict:
    """LAYING flock + production + one confirmed grading run -> FRESH lots."""
    ctx = setup_laying_flock_with_production(**kwargs)
    ctx["run"], ctx["lots"] = confirm_grading_run(
        ctx["flock"]["id"], grade, eggs_to_grade, submit_counts
    )
    ctx["flock"] = get_flock(ctx["flock"]["id"])
    return ctx


# ------------------------------------------------- contracts / shipping
def setup_active_contract(farm_id: str, **overrides) -> dict:
    contract = get_success_data(
        api_client.create_contract(
            factories.contract_payload(farm_id, **overrides), CONTRACT_MANAGER
        )
    )
    return get_success_data(api_client.activate_contract(contract["id"], CONTRACT_MANAGER))


def release_allocate_ship(lot_id: str, contract_id: str) -> dict:
    """Walk a lot RELEASED -> ALLOCATED -> SHIPPED against one contract."""
    get_success_data(api_client.release_lot(lot_id, QA_MANAGER))
    get_success_data(
        api_client.allocate_lot(lot_id, {"contract_id": contract_id}, CONTRACT_MANAGER)
    )
    return get_success_data(api_client.ship_lot(lot_id, CONTRACT_MANAGER))


def setup_allocated_lots(contract_overrides=None, **kwargs) -> dict:
    """Confirmed lots, all RELEASED and ALLOCATED to one ACTIVE contract."""
    ctx = setup_confirmed_lot(**kwargs)
    ctx["contract"] = setup_active_contract(
        ctx["farm"]["id"], **(contract_overrides or {})
    )
    for lot in ctx["lots"]:
        get_success_data(api_client.release_lot(lot["id"], QA_MANAGER))
        get_success_data(
            api_client.allocate_lot(
                lot["id"], {"contract_id": ctx["contract"]["id"]}, CONTRACT_MANAGER
            )
        )
    ctx["lots"] = [get_lot(lot["id"]) for lot in ctx["lots"]]
    ctx["contract"] = get_contract(ctx["contract"]["id"])
    return ctx


def setup_shipped_lots(**kwargs) -> dict:
    """Confirmed lots, all RELEASED + ALLOCATED + SHIPPED to one ACTIVE contract."""
    ctx = setup_allocated_lots(**kwargs)
    for lot in ctx["lots"]:
        get_success_data(api_client.ship_lot(lot["id"], CONTRACT_MANAGER))
    ctx["lots"] = [get_lot(lot["id"]) for lot in ctx["lots"]]
    ctx["contract"] = get_contract(ctx["contract"]["id"])
    return ctx


# ------------------------------------------------- settlements
def create_draft_settlement(
    contract_id: str,
    period_start="2026-07-20",
    period_end="2026-07-26",
    market_index_cents=140,
) -> dict:
    """Create a DRAFT settlement, reading the contract's current version for
    the optimistic-concurrency guard (PRD §2.7)."""
    contract = get_contract(contract_id)
    payload = factories.settlement_payload(
        contract_id,
        contract["version"],
        period_start=period_start,
        period_end=period_end,
    )
    if market_index_cents is not None:
        payload["market_index_cents"] = market_index_cents
    return get_success_data(api_client.create_settlement(payload, CONTRACT_MANAGER))


def setup_shipped_lot_settlement(
    period_start="2026-07-20",
    period_end="2026-07-26",
    market_index_cents=140,
    **kwargs,
) -> dict:
    """Shipped lot(s) plus a DRAFT settlement covering the ship date."""
    ctx = setup_shipped_lots(**kwargs)
    ctx["settlement"] = create_draft_settlement(
        ctx["contract"]["id"], period_start, period_end, market_index_cents
    )
    return ctx


# ------------------------------------------------- salmonella tests
def create_collected_salmonella_test(
    flock_id: str,
    scheduled_date="2026-08-01",
    test_type="ENVIRONMENTAL",
    collector_headers=None,
) -> dict:
    """Schedule (QualityGrader) then collect a salmonella test (PRD §3.7)."""
    test = get_success_data(
        api_client.create_salmonella_test(
            factories.salmonella_test_payload(
                flock_id, scheduled_date=scheduled_date, test_type=test_type
            ),
            GRADER,
        )
    )
    return get_success_data(
        api_client.collect_salmonella_test(test["id"], collector_headers or GRADER)
    )


def record_test_result(test_id: str, result: str, recorder_headers=None) -> dict:
    """Record a lab result as QAManager (distinct operator id from the
    default collector, satisfying the segregation-of-duties pair)."""
    return get_success_data(
        api_client.record_salmonella_result(
            test_id, {"result": result}, recorder_headers or QA_MANAGER
        )
    )


# ------------------------------------------------- compliance audits
def walk_audit_to_findings(
    farm_id: str,
    audit_date="2026-08-01",
    standard="FDA_EGG_SAFETY",
    findings_count=0,
    corrective_actions_open=0,
) -> dict:
    """Schedule -> start -> record-findings (PRD §3.8)."""
    audit = get_success_data(
        api_client.create_compliance_audit(
            factories.audit_payload(farm_id, standard=standard, audit_date=audit_date),
            COMPLIANCE_OFFICER,
        )
    )
    get_success_data(api_client.start_compliance_audit(audit["id"], COMPLIANCE_OFFICER))
    return get_success_data(
        api_client.record_audit_findings(
            audit["id"],
            factories.record_findings_payload(
                findings_count=findings_count,
                corrective_actions_open=corrective_actions_open,
            ),
            COMPLIANCE_OFFICER,
        )
    )


def create_failed_audit(
    farm_id: str, audit_date="2026-08-01", standard="USDA_CAGE_FREE"
) -> dict:
    """Walk an audit through to CLOSED_FAILED; farm posture goes SUSPENDED."""
    audit = walk_audit_to_findings(
        farm_id,
        audit_date=audit_date,
        standard=standard,
        findings_count=2,
        corrective_actions_open=0,
    )
    return get_success_data(
        api_client.close_compliance_audit(
            audit["id"], {"outcome": "FAILED"}, COMPLIANCE_OFFICER
        )
    )


# ------------------------------------------------- depopulation / turnover
def setup_depopulating_flock(**kwargs) -> dict:
    """LAYING flock moved to DEPOPULATING (house cascades to DEPOPULATING)."""
    ctx = setup_laying_flock(**kwargs)
    ctx["flock"] = get_success_data(
        api_client.depopulate_flock(ctx["flock"]["id"], FARM_MANAGER)
    )
    return ctx


def complete_disposition(
    flock_id: str, hen_count: int, method="RENDERING", revenue_cents=0
) -> dict:
    """Plan then complete a spent-hen disposition (PRD §3.9)."""
    disp = get_success_data(
        api_client.create_disposition(
            factories.disposition_payload(
                flock_id, method=method, hen_count=hen_count, revenue_cents=revenue_cents
            ),
            FARM_MANAGER,
        )
    )
    return get_success_data(api_client.complete_disposition(disp["id"], FARM_MANAGER))


def setup_depleted_flock(revenue_cents=5000, **kwargs) -> dict:
    """Flock fully depopulated: all hens disposed -> DEPLETED; house CLEANING."""
    ctx = setup_depopulating_flock(**kwargs)
    ctx["disposition"] = complete_disposition(
        ctx["flock"]["id"],
        ctx["flock"]["current_hen_count"],
        revenue_cents=revenue_cents,
    )
    ctx["flock"] = get_flock(ctx["flock"]["id"])
    ctx["house"] = get_house(ctx["house"]["id"])
    assert ctx["flock"]["status"] == "DEPLETED", (
        f"setup expected DEPLETED flock, got {ctx['flock']['status']}"
    )
    return ctx
