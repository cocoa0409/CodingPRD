"""Composite setup helpers.

Every test starts against an empty database, so every helper here builds its
preconditions from scratch using only endpoints the PRD declares. All setup
calls use the lenient ``get_success_data`` validator so a broken precondition
surfaces as a setup failure rather than as a confusing assertion failure.
"""

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import api_client
from .constants import (
    DIMENSIONAL_WINDOW,
    HARDNESS_WINDOW,
    MECHANISM_WINDOW,
    PROCESS_STAGE_ORDER,
    SALT_SPRAY_WINDOW,
    TORQUE_WINDOW,
)
from .test_users import TEST_USERS, make_claimant_headers

CM = TEST_USERS["channel_manager_headers"]
PP = TEST_USERS["production_planner_headers"]
QE = TEST_USERS["quality_engineer_headers"]
WA = TEST_USERS["warranty_administrator_headers"]
BP = TEST_USERS["brand_protection_analyst_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]


# ===========================================================================
# Tier 1 — single-resource creators
# ===========================================================================


def set_clock(current_utc: str) -> None:
    """Move the logical UTC clock. Only PlatformAdmin may do this."""
    get_success_data(api_client.set_clock(f.clock_payload(current_utc), ADMIN))


def create_sku(**overrides) -> dict:
    return get_success_data(api_client.create_tool_sku(f.tool_sku_payload(**overrides), CM))


def create_furnace(**overrides) -> dict:
    return get_success_data(
        api_client.create_heat_treat_furnace(f.heat_treat_furnace_payload(**overrides), PP)
    )


def create_chamber(**overrides) -> dict:
    return get_success_data(
        api_client.create_salt_spray_chamber(f.salt_spray_chamber_payload(**overrides), QE)
    )


def create_lot(sku_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_production_lot(f.production_lot_payload(sku_id, **overrides), PP)
    )


def create_program(**overrides) -> dict:
    return get_success_data(
        api_client.create_warranty_program(f.warranty_program_payload(**overrides), WA)
    )


def create_claimant(**overrides) -> dict:
    return get_success_data(api_client.create_claimant(f.claimant_payload(**overrides), WA))


def create_claim(claimant_id: str, sku_id: str, program_id: str, headers=None, **overrides) -> dict:
    return get_success_data(
        api_client.create_warranty_claim(
            f.warranty_claim_payload(claimant_id, sku_id, program_id, **overrides),
            headers or WA,
        )
    )


def add_claim_line(claim_id: str, headers=None, **overrides) -> dict:
    return get_success_data(
        api_client.add_claim_line(claim_id, f.claim_line_payload(**overrides), headers or WA)
    )


def create_report(sku_id: str, headers=None, **overrides) -> dict:
    return get_success_data(
        api_client.create_counterfeit_report(
            f.counterfeit_report_payload(sku_id, **overrides), headers or BP
        )
    )


def confirm_report(report_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.confirm_counterfeit_report(report_id, f.confirm_report_payload(**overrides), BP)
    )


def dismiss_report(report_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.dismiss_counterfeit_report(report_id, f.dismiss_report_payload(**overrides), BP)
    )


def create_pack(primary_sku_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_pack_configuration(
            f.pack_configuration_payload(primary_sku_id, **overrides), CM
        )
    )


def add_pack_member(pack_id: str, sku_id: str, quantity: int = 1) -> dict:
    return get_success_data(
        api_client.add_pack_member(pack_id, f.pack_member_payload(sku_id, quantity), CM)
    )


def book_stock(sku_id: str, units_received: int) -> dict:
    return get_success_data(
        api_client.create_stock_receipt(
            sku_id, f.stock_receipt_payload(units_received=units_received), CM
        )
    )


def read_sku(sku_id: str) -> dict:
    return get_success_data(api_client.get_tool_sku(sku_id, CM))


def read_lot(lot_id: str) -> dict:
    return get_success_data(api_client.get_production_lot(lot_id, PP))


def read_program(program_id: str) -> dict:
    return get_success_data(api_client.get_warranty_program(program_id, WA))


def read_claimant(claimant_id: str) -> dict:
    return get_success_data(api_client.get_claimant(claimant_id, WA))


def read_claim(claim_id: str) -> dict:
    return get_success_data(api_client.get_warranty_claim(claim_id, WA))


def read_test_run(run_id: str) -> dict:
    return get_success_data(api_client.get_test_run(run_id, QE))


def read_campaign(campaign_id: str) -> dict:
    return get_success_data(api_client.get_furnace_campaign(campaign_id, PP))


def read_pack(pack_id: str) -> dict:
    return get_success_data(api_client.get_pack_configuration(pack_id, CM))


# ===========================================================================
# Tier 2 — small hierarchies and state progression
# ===========================================================================


def schedule_campaign(lot_id: str, furnace_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_furnace_campaign(
            f.furnace_campaign_payload(lot_id, furnace_id, **overrides), PP
        )
    )


def complete_campaign(campaign_id: str, soak_minutes: int = 120) -> dict:
    return get_success_data(
        api_client.complete_furnace_campaign(
            campaign_id, f.campaign_complete_payload(soak_minutes=soak_minutes), PP
        )
    )


def advance_lot(lot_id: str, target_process_status: str) -> dict:
    return get_success_data(
        api_client.advance_production_lot(lot_id, f.advance_payload(target_process_status), PP)
    )


def advance_lot_to(lot_id: str, target_process_status: str, current="FORGED") -> dict:
    """Walk the routing dimension one immediate successor at a time."""
    start = PROCESS_STAGE_ORDER.index(current)
    stop = PROCESS_STAGE_ORDER.index(target_process_status)
    data = None
    for stage in PROCESS_STAGE_ORDER[start + 1 : stop + 1]:
        data = advance_lot(lot_id, stage)
    return data if data is not None else read_lot(lot_id)


def schedule_test_run(lot_id: str, test_type: str, specimen_count: int, window, chamber_id=None):
    payload = f.make_test_run_payload(
        lot_id,
        test_type=test_type,
        specimen_count=specimen_count,
        window_start=window[0],
        window_end=window[1],
    )
    if chamber_id is not None:
        payload["chamber_id"] = chamber_id
    return get_success_data(api_client.create_test_run(payload, QE))


def submit_results(run_id: str, readings) -> dict:
    return get_success_data(
        api_client.submit_test_run_results(run_id, f.make_test_results_payload(readings), QE)
    )


def setup_sku_and_lot(sku_overrides=None, lot_overrides=None):
    """One SKU plus one freshly opened lot against it: FORGED / DRAFT /
    IN_PROCESS."""
    sku = create_sku(**(sku_overrides or {}))
    lot = create_lot(sku["id"], **(lot_overrides or {}))
    return sku, lot


def setup_sku_with_stock(units_received: int = 10, sku_overrides=None) -> dict:
    """One SKU with finished units booked in from an outside source."""
    sku = create_sku(**(sku_overrides or {}))
    book_stock(sku["id"], units_received)
    return read_sku(sku["id"])


def setup_lot_with_completed_campaign(
    sku_overrides=None,
    lot_overrides=None,
    furnace_overrides=None,
    charge_kg=800,
    soak_minutes=120,
    campaign_overrides=None,
):
    """SKU + qualified furnace + lot + one COMPLETED heat-treat campaign, which
    is the precondition for the step into HEAT_TREATED."""
    sku_overrides = dict(sku_overrides or {})
    sku = create_sku(**sku_overrides)
    furnace_kwargs = dict(furnace_overrides or {})
    furnace_kwargs.setdefault("alloy_grades_supported", [sku["alloy_grade"]])
    furnace = create_furnace(**furnace_kwargs)
    lot = create_lot(sku["id"], **(lot_overrides or {}))
    campaign = schedule_campaign(
        lot["id"], furnace["id"], charge_kg=charge_kg, **(campaign_overrides or {})
    )
    campaign = complete_campaign(campaign["id"], soak_minutes=soak_minutes)
    return {"sku": sku, "furnace": furnace, "lot": lot, "campaign": campaign}


def setup_lot_at_stage(
    target_process_status: str,
    sku_overrides=None,
    lot_overrides=None,
    furnace_overrides=None,
):
    """SKU + furnace + lot walked up the routing dimension to a named stage,
    with the heat-treat campaign already COMPLETED."""
    ctx = setup_lot_with_completed_campaign(
        sku_overrides=sku_overrides,
        lot_overrides=lot_overrides,
        furnace_overrides=furnace_overrides,
    )
    if target_process_status != "FORGED":
        advance_lot_to(ctx["lot"]["id"], target_process_status)
    ctx["lot"] = read_lot(ctx["lot"]["id"])
    return ctx


# ===========================================================================
# Tier 3 — full qualification lifecycle
# ===========================================================================

DEFAULT_HARDNESS_READINGS = (52.0, 53.0)
DEFAULT_TORQUE_READINGS = (130.0, 128.5)
DEFAULT_DIMENSIONAL_READINGS = (0.04, -0.06, 0.10)
DEFAULT_SALT_SPRAY_READINGS = (120.0, 144.0)
DEFAULT_MECHANISM_READINGS = (6000.0, 6200.0)


def setup_lot_ready_for_certification(
    sku_overrides=None,
    lot_overrides=None,
    furnace_overrides=None,
    chamber_overrides=None,
    hardness_readings=DEFAULT_HARDNESS_READINGS,
    torque_readings=DEFAULT_TORQUE_READINGS,
    dimensional_readings=DEFAULT_DIMENSIONAL_READINGS,
    salt_spray_readings=DEFAULT_SALT_SPRAY_READINGS,
    mechanism_readings=DEFAULT_MECHANISM_READINGS,
):
    """Drive a lot all the way to the certification gate.

    SKU -> furnace -> chamber -> lot -> campaign -> complete -> advance through
    HEAT_TREATED, MACHINED, PLATED and ASSEMBLED -> one run of every mandatory
    test type for the SKU's tool_family, with results recorded. A PLIER battery
    substitutes MECHANISM_CYCLE for PROOF_TORQUE.

    Returns a dict with the sku, furnace, chamber, lot, campaign and a `runs`
    mapping keyed by test_type.
    """
    ctx = setup_lot_with_completed_campaign(
        sku_overrides=sku_overrides,
        lot_overrides=lot_overrides,
        furnace_overrides=furnace_overrides,
    )
    chamber = create_chamber(**(chamber_overrides or {}))
    ctx["chamber"] = chamber
    lot_id = ctx["lot"]["id"]
    family = ctx["sku"]["tool_family"]

    advance_lot_to(lot_id, "ASSEMBLED")

    runs = {}
    runs["HARDNESS"] = schedule_test_run(
        lot_id, "HARDNESS", len(hardness_readings), HARDNESS_WINDOW
    )
    submit_results(runs["HARDNESS"]["id"], hardness_readings)

    if family in ("WRENCH", "SOCKET"):
        runs["PROOF_TORQUE"] = schedule_test_run(
            lot_id, "PROOF_TORQUE", len(torque_readings), TORQUE_WINDOW
        )
        submit_results(runs["PROOF_TORQUE"]["id"], torque_readings)

    runs["DIMENSIONAL"] = schedule_test_run(
        lot_id, "DIMENSIONAL", len(dimensional_readings), DIMENSIONAL_WINDOW
    )
    submit_results(runs["DIMENSIONAL"]["id"], dimensional_readings)

    runs["SALT_SPRAY"] = schedule_test_run(
        lot_id,
        "SALT_SPRAY",
        len(salt_spray_readings),
        SALT_SPRAY_WINDOW,
        chamber_id=chamber["id"],
    )
    submit_results(runs["SALT_SPRAY"]["id"], salt_spray_readings)

    if family == "PLIER":
        runs["MECHANISM_CYCLE"] = schedule_test_run(
            lot_id, "MECHANISM_CYCLE", len(mechanism_readings), MECHANISM_WINDOW
        )
        submit_results(runs["MECHANISM_CYCLE"]["id"], mechanism_readings)

    ctx["runs"] = runs
    ctx["lot"] = read_lot(lot_id)
    return ctx


def certify_lot(lot_id: str) -> dict:
    return get_success_data(api_client.certify_production_lot(lot_id, QE))


def setup_certified_lot(**kwargs):
    """A fully CERTIFIED lot and its SKU."""
    ctx = setup_lot_ready_for_certification(**kwargs)
    ctx["lot"] = certify_lot(ctx["lot"]["id"])
    return ctx


def release_lot(lot_id: str, sku_id: str) -> dict:
    """Release reads the parent SKU's current version first, since the release
    body must carry it."""
    sku = read_sku(sku_id)
    return get_success_data(
        api_client.release_production_lot(lot_id, f.release_payload(sku["version"]), PP)
    )


def setup_released_lot(**kwargs):
    """A CERTIFIED lot released into finished stock, so the SKU carries the
    lot's unit_count on hand."""
    ctx = setup_certified_lot(**kwargs)
    ctx["lot"] = release_lot(ctx["lot"]["id"], ctx["sku"]["id"])
    ctx["sku"] = read_sku(ctx["sku"]["id"])
    return ctx


def setup_rejected_lot(
    sku_overrides=None,
    lot_overrides=None,
    failing_test_type="HARDNESS",
    failing_readings=(40.0, 41.0),
    extra_scheduled_runs=(),
):
    """Drive a lot to REJECTED / QUARANTINED by failing a mandatory test.

    ``extra_scheduled_runs`` is a sequence of ``(test_type, specimen_count,
    window)`` tuples scheduled before the failure so the tear-down cascade has
    sibling rows to void.
    """
    ctx = setup_lot_with_completed_campaign(
        sku_overrides=sku_overrides, lot_overrides=lot_overrides
    )
    lot_id = ctx["lot"]["id"]
    advance_lot_to(lot_id, "MACHINED")
    extras = []
    for test_type, specimen_count, window in extra_scheduled_runs:
        extras.append(schedule_test_run(lot_id, test_type, specimen_count, window))
    failing_run = schedule_test_run(
        lot_id, failing_test_type, len(failing_readings), HARDNESS_WINDOW
    )
    ctx["failing_run"] = submit_results(failing_run["id"], failing_readings)
    ctx["extra_runs"] = extras
    ctx["lot"] = read_lot(lot_id)
    return ctx


# ===========================================================================
# Tier 4 — accumulation and threshold targeting
# ===========================================================================


def setup_sku_with_confirmed_reports(reports, sku_overrides=None):
    """Create a SKU and file/confirm counterfeit reports so its
    brand_risk_score lands on a chosen total.

    ``reports`` is a sequence of dicts, each accepting ``evidence_grade``,
    ``unit_estimate``, ``seller_handle`` and an ``action`` of ``"confirm"``,
    ``"dismiss"`` or ``"open"``.
    """
    sku = create_sku(**(sku_overrides or {}))
    filed = []
    for index, spec in enumerate(reports):
        spec = dict(spec)
        action = spec.pop("action", "confirm")
        spec.setdefault("seller_handle", f"seller-{index + 1}")
        report = create_report(sku["id"], **spec)
        if action == "confirm":
            report = confirm_report(report["id"])
        elif action == "dismiss":
            report = dismiss_report(report["id"])
        filed.append(report)
    return read_sku(sku["id"]), filed


def setup_lot_with_committed_specimens(specimen_pool_total: int, committed: int, **kwargs):
    """A lot at MACHINED with a HARDNESS run holding ``committed`` specimens in
    specimens_committed, used to sit exactly on the pool boundary."""
    ctx = setup_lot_with_completed_campaign(
        lot_overrides={"specimen_pool_total": specimen_pool_total}, **kwargs
    )
    lot_id = ctx["lot"]["id"]
    advance_lot_to(lot_id, "MACHINED")
    ctx["committed_run"] = schedule_test_run(lot_id, "HARDNESS", committed, HARDNESS_WINDOW)
    ctx["lot"] = read_lot(lot_id)
    return ctx


# ===========================================================================
# Tier 5 — warranty lifecycle
# ===========================================================================


def setup_warranty_scenario(
    sku_overrides=None,
    program_overrides=None,
    claimant_overrides=None,
    claim_overrides=None,
    units_received=10,
    lines=(),
    sku_id=None,
):
    """SKU with finished stock + funded programme + claimant + one claim, with
    optional replacement lines already attached.

    Pass ``sku_id`` to hang the warranty rows off an existing SKU, for example
    one whose stock came from a released production lot rather than a receipt.

    Returns a dict with sku, program, claimant, claim and lines.
    """
    if sku_id is None:
        sku = create_sku(**(sku_overrides or {}))
        if units_received:
            book_stock(sku["id"], units_received)
    else:
        sku = read_sku(sku_id)
    program = create_program(**(program_overrides or {}))
    claimant = create_claimant(**(claimant_overrides or {}))
    claim = create_claim(
        claimant["id"], sku["id"], program["id"], **(claim_overrides or {})
    )
    added = []
    for line in lines:
        added.append(add_claim_line(claim["id"], **line))
    return {
        "sku": read_sku(sku["id"]),
        "program": read_program(program["id"]),
        "claimant": read_claimant(claimant["id"]),
        "claim": read_claim(claim["id"]),
        "lines": added,
        "claimant_headers": make_claimant_headers(claimant["id"]),
    }


def hold_claim(claim_id: str, headers, **overrides) -> dict:
    return get_success_data(
        api_client.hold_warranty_claim(claim_id, f.hold_payload(**overrides), headers)
    )


def clear_hold(claim_id: str, headers, **overrides) -> dict:
    return get_success_data(
        api_client.clear_hold_warranty_claim(claim_id, f.clear_hold_payload(**overrides), headers)
    )


def approve_claim(claim_id: str, program_id: str, headers) -> dict:
    """Approval must carry the programme version as last read, so re-read it
    immediately before approving."""
    program = read_program(program_id)
    return get_success_data(
        api_client.approve_warranty_claim(
            claim_id, f.approve_claim_payload(program["version"]), headers
        )
    )


def fulfill_claim(claim_id: str, headers, **overrides) -> dict:
    return get_success_data(
        api_client.fulfill_warranty_claim(claim_id, f.fulfill_payload(**overrides), headers)
    )


def revoke_claim(claim_id: str, headers, **overrides) -> dict:
    return get_success_data(
        api_client.revoke_warranty_claim(claim_id, f.revoke_payload(**overrides), headers)
    )


def setup_approved_claim(approver_headers=None, **scenario_kwargs):
    """A warranty scenario driven through to APPROVED."""
    scenario_kwargs.setdefault("lines", ({"component_code": "HANDLE"},))
    ctx = setup_warranty_scenario(**scenario_kwargs)
    ctx["claim"] = approve_claim(
        ctx["claim"]["id"], ctx["program"]["id"], approver_headers or WA
    )
    ctx["sku"] = read_sku(ctx["sku"]["id"])
    ctx["program"] = read_program(ctx["program"]["id"])
    return ctx


def setup_fulfilled_claim(approver_headers=None, **scenario_kwargs):
    """A warranty scenario driven through to FULFILLED."""
    ctx = setup_approved_claim(approver_headers=approver_headers, **scenario_kwargs)
    ctx["claim"] = fulfill_claim(ctx["claim"]["id"], approver_headers or WA)
    ctx["sku"] = read_sku(ctx["sku"]["id"])
    ctx["program"] = read_program(ctx["program"]["id"])
    return ctx


def setup_certified_sku_pack(pack_type="RETAIL_DISPLAY", quantity=2, sku_overrides=None):
    """A CERTIFIED SKU plus a DRAFT pack whose single member is that SKU, which
    is what makes the pack's certification gate pass."""
    ctx = setup_certified_lot(sku_overrides=sku_overrides)
    pack = create_pack(ctx["sku"]["id"], pack_code="PK-1", pack_type=pack_type)
    member = add_pack_member(pack["id"], ctx["sku"]["id"], quantity)
    ctx["pack"] = read_pack(pack["id"])
    ctx["member"] = member
    return ctx
