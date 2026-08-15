"""Composite setup helpers.

Every helper builds preconditions from scratch using only PRD-declared
endpoints (each test runs against a freshly restarted server with an empty
database). Setup calls use get_success_data so failures surface as clear
"Setup failed" errors. Actor-recording calls (prototype submit/approve,
signoff submit/review) take explicit user ids so segregation-of-duties tests
can control identities.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_damage_claim_payload,
    create_fixture_prototype_payload,
    create_install_delivery_payload,
    create_install_signoff_payload,
    create_production_wave_payload,
    create_rollout_program_payload,
    create_staging_reservation_payload,
    create_store_kit_config_payload,
)
from .test_users import (
    TEST_USERS,
    make_fixture_engineer_headers,
    make_install_crew_lead_headers,
    make_program_manager_headers,
    make_store_manager_headers,
)

PM = TEST_USERS["program_manager_headers"]
FE = TEST_USERS["fixture_engineer_headers"]
CC = TEST_USERS["config_coordinator_headers"]
PP = TEST_USERS["production_planner_headers"]
WL = TEST_USERS["warehouse_lead_headers"]
ICL = TEST_USERS["install_crew_lead_headers"]
HA = TEST_USERS["hotline_agent_headers"]
SM = TEST_USERS["store_manager_headers"]
PA = TEST_USERS["platform_admin_headers"]


def _fail(step, resp):
    raise AssertionError(
        f"Setup failed at {step}: HTTP {resp.status_code} {resp.text}"
    )


def _ok(step, resp, expected_status=None):
    if expected_status is not None and resp.status_code != expected_status:
        _fail(step, resp)
    data = get_success_data(resp)
    if isinstance(data, dict) and data.get("status") is not None:
        return data
    return data


# ---------------------------------------------------------------------------
# Tier 1 — program stand-up
# ---------------------------------------------------------------------------

def create_program(name="P-1", budget_total_cents=1_000_000,
                   contingency_budget_cents=100_000, **overrides):
    """Create a rollout program (born DRAFT). Returns the program dict."""
    resp = api_client.create_rollout_program(
        create_rollout_program_payload(
            program_name=name,
            budget_total_cents=budget_total_cents,
            contingency_budget_cents=contingency_budget_cents,
            **overrides,
        ),
        PM,
    )
    return _ok("create_rollout_program", resp, expected_status=201)


def activate_program(program_id):
    resp = api_client.activate_program(program_id, PM)
    return _ok("activate_program", resp)


def create_active_program(name="P-1", budget_total_cents=1_000_000,
                          contingency_budget_cents=100_000, **overrides):
    """Create + activate. Returns the ACTIVE program dict."""
    program = create_program(
        name, budget_total_cents, contingency_budget_cents, **overrides)
    return activate_program(program["id"])


# ---------------------------------------------------------------------------
# Tier 1 — prototype lifecycle
# ---------------------------------------------------------------------------

def create_prototype(program_id, fixture_code="GONDOLA-4FT", bom_lines=None,
                     target_cost_cents=999_999):
    """Create a DRAFT prototype."""
    resp = api_client.create_fixture_prototype(
        create_fixture_prototype_payload(
            program_id, fixture_code=fixture_code, bom_lines=bom_lines,
            target_cost_cents=target_cost_cents,
        ),
        FE,
    )
    return _ok("create_fixture_prototype", resp, expected_status=201)


def submit_prototype(prototype_id, submitter_user_id="eng-1"):
    """Submit for engineering review; records submitter_user_id."""
    resp = api_client.submit_prototype_review(
        prototype_id, make_fixture_engineer_headers(submitter_user_id))
    return _ok("submit_prototype_review", resp)


def approve_prototype(prototype_id, approver_user_id="pm-1"):
    """Approve a prototype under review (approver must differ from submitter)."""
    resp = api_client.approve_prototype(
        prototype_id, make_program_manager_headers(approver_user_id))
    return _ok("approve_prototype", resp)


def create_approved_prototype(program_id, fixture_code="GONDOLA-4FT",
                              bom_lines=None, target_cost_cents=999_999,
                              submitter_user_id="eng-1",
                              approver_user_id="pm-1"):
    """Create -> submit-review -> approve. Returns the APPROVED prototype."""
    proto = create_prototype(program_id, fixture_code, bom_lines,
                             target_cost_cents)
    submit_prototype(proto["id"], submitter_user_id)
    return approve_prototype(proto["id"], approver_user_id)


# ---------------------------------------------------------------------------
# Tier 1/2 — kits and waves
# ---------------------------------------------------------------------------

def create_kit(program_id, prototype_id, store_code="STORE-0001",
               config_lines=None):
    """Create a DRAFT kit. config_lines=None omits the field (defaults empty)."""
    resp = api_client.create_store_kit_config(
        create_store_kit_config_payload(
            program_id, prototype_id, store_code=store_code,
            config_lines=config_lines,
        ),
        CC,
    )
    return _ok("create_store_kit_config", resp, expected_status=201)


def freeze_kit(kit_id):
    resp = api_client.freeze_kit(kit_id, CC)
    return _ok("freeze_kit", resp)


def create_frozen_kit(program_id, prototype_id, store_code="STORE-0001",
                      config_lines=None):
    """Create + freeze. config_lines must be non-empty for the freeze gate."""
    kit = create_kit(program_id, prototype_id, store_code, config_lines)
    return freeze_kit(kit["id"])


def create_wave(program_id, wave_label="WAVE-1", start_date="2026-09-01",
                end_date="2026-09-10", capacity_units=100):
    resp = api_client.create_production_wave(
        create_production_wave_payload(
            program_id, wave_label=wave_label, start_date=start_date,
            end_date=end_date, capacity_units=capacity_units,
        ),
        PP,
    )
    return _ok("create_production_wave", resp, expected_status=201)


def commit_wave(wave_id):
    resp = api_client.commit_wave(wave_id, PP)
    return _ok("commit_wave", resp)


def complete_wave(wave_id):
    resp = api_client.complete_wave(wave_id, PP)
    return _ok("complete_wave", resp)


def create_committed_wave(program_id, wave_label="WAVE-1",
                         start_date="2026-09-01", end_date="2026-09-10",
                         capacity_units=100):
    wave = create_wave(program_id, wave_label, start_date, end_date,
                       capacity_units)
    return commit_wave(wave["id"])


def release_kit(kit_id, wave_id):
    resp = api_client.release_kit(kit_id, {"wave_id": wave_id}, CC)
    return _ok("release_kit", resp)


def create_released_kit(program_id, prototype_id, wave_id,
                        store_code="STORE-0001", config_lines=None):
    kit = create_frozen_kit(program_id, prototype_id, store_code, config_lines)
    return release_kit(kit["id"], wave_id)


# ---------------------------------------------------------------------------
# Tier 2 — the ubiquitous released-kit scenario
# ---------------------------------------------------------------------------

def setup_released_scenario(program_name="P-REL", budget_total_cents=2_000_000,
                            contingency_budget_cents=100_000,
                            recalled_part_numbers=None,
                            attic_valuation_method=None,
                            fixture_code="GONDOLA-8FT", bom_lines=None,
                            target_cost_cents=999_999,
                            store_code="STORE-0001", config_lines=None,
                            wave_label="WAVE-1", wave_start_date="2026-09-01",
                            wave_end_date="2026-09-10", wave_capacity=200):
    """Program ACTIVE + prototype APPROVED + kit FROZEN+RELEASED on a
    COMMITTED wave. Returns dict(program, prototype, kit, wave)."""
    program_overrides = {}
    if recalled_part_numbers is not None:
        program_overrides["recalled_part_numbers"] = recalled_part_numbers
    if attic_valuation_method is not None:
        program_overrides["attic_valuation_method"] = attic_valuation_method
    program = create_active_program(
        program_name, budget_total_cents, contingency_budget_cents,
        **program_overrides)
    prototype = create_approved_prototype(
        program["id"], fixture_code=fixture_code, bom_lines=bom_lines,
        target_cost_cents=target_cost_cents)
    kit = create_frozen_kit(program["id"], prototype["id"], store_code,
                            config_lines)
    wave = create_committed_wave(program["id"], wave_label, wave_start_date,
                                wave_end_date, wave_capacity)
    kit = release_kit(kit["id"], wave["id"])
    return {"program": program, "prototype": prototype, "kit": kit,
            "wave": wave}


# ---------------------------------------------------------------------------
# Tier 3 — deliveries, signoffs, fulfillment
# ---------------------------------------------------------------------------

def create_delivery(kit_id, crew_code="CREW-1", delivery_date="2026-09-12",
                    estimated_install_hours=4):
    """Schedule a delivery for a RELEASED kit (born SCHEDULED)."""
    resp = api_client.create_install_delivery(
        create_install_delivery_payload(
            kit_id, crew_code=crew_code, delivery_date=delivery_date,
            estimated_install_hours=estimated_install_hours,
        ),
        ICL,
    )
    return _ok("create_install_delivery", resp, expected_status=201)


def dispatch_delivery(delivery_id):
    resp = api_client.dispatch_delivery(delivery_id, ICL)
    return _ok("dispatch_delivery", resp)


def confirm_delivery(delivery_id):
    resp = api_client.confirm_delivery(delivery_id, ICL)
    return _ok("confirm_delivery", resp)


def create_delivered_delivery(kit_id, crew_code="CREW-1",
                              delivery_date="2026-09-12",
                              estimated_install_hours=4):
    """Create -> dispatch -> confirm. Returns the DELIVERED delivery."""
    delivery = create_delivery(kit_id, crew_code, delivery_date,
                               estimated_install_hours)
    dispatch_delivery(delivery["id"])
    return confirm_delivery(delivery["id"])


def setup_delivered_scenario(crew_code="CREW-1", delivery_date="2026-09-12",
                             estimated_install_hours=4, **scenario_kwargs):
    """Released-kit scenario + a DELIVERED delivery for the kit."""
    ctx = setup_released_scenario(**scenario_kwargs)
    delivery = create_delivered_delivery(
        ctx["kit"]["id"], crew_code, delivery_date, estimated_install_hours)
    ctx["delivery"] = delivery
    return ctx


def create_signoff(delivery_id, photo_urls=None, notes=None,
                   submitter_user_id="crew-1"):
    """Submit a photo signoff for a DELIVERED delivery (born SUBMITTED)."""
    resp = api_client.create_install_signoff(
        create_install_signoff_payload(delivery_id, photo_urls=photo_urls,
                                       notes=notes),
        make_install_crew_lead_headers(submitter_user_id),
    )
    return _ok("create_install_signoff", resp, expected_status=201)


def approve_signoff(signoff_id, approver_user_id="sm-1"):
    resp = api_client.approve_install_signoff(
        signoff_id, make_store_manager_headers(approver_user_id))
    return _ok("approve_install_signoff", resp)


def reject_signoff(signoff_id, reason, reviewer_user_id="sm-1"):
    resp = api_client.reject_install_signoff(
        signoff_id, {"reason": reason},
        make_store_manager_headers(reviewer_user_id))
    return _ok("reject_install_signoff", resp)


def get_kit_ledger(kit_id):
    """Fetch the single attic stock ledger auto-created for a fulfilled kit."""
    resp = api_client.list_attic_stock_ledgers(PM, params={"kit_id": kit_id})
    data = _ok("list_attic_stock_ledgers", resp)
    assert isinstance(data, list) and len(data) == 1, (
        f"Setup failed: expected exactly one ledger for kit {kit_id}, "
        f"got {data}"
    )
    return data[0]


def setup_fulfilled_scenario(signoff_submitter_user_id="crew-1",
                             signoff_approver_user_id="sm-1",
                             **scenario_kwargs):
    """Full chain through signoff approval: kit FULFILLED, delivery COMPLETE,
    attic ledger auto-created. Returns dict(..., delivery, signoff, ledger)."""
    ctx = setup_delivered_scenario(**scenario_kwargs)
    signoff = create_signoff(ctx["delivery"]["id"],
                             submitter_user_id=signoff_submitter_user_id)
    signoff = approve_signoff(signoff["id"], signoff_approver_user_id)
    ledger = get_kit_ledger(ctx["kit"]["id"])
    ctx["signoff"] = signoff
    ctx["ledger"] = ledger
    return ctx


# ---------------------------------------------------------------------------
# Tier 5 — closeout
# ---------------------------------------------------------------------------

def setup_closeout_pending_scenario(**scenario_kwargs):
    """Fulfilled scenario + wave COMPLETE + initiate-closeout.

    Returns the context with the program in CLOSEOUT_PENDING and one ACTIVE
    attic ledger still outstanding.
    """
    ctx = setup_fulfilled_scenario(**scenario_kwargs)
    complete_wave(ctx["wave"]["id"])
    resp = api_client.initiate_closeout(ctx["program"]["id"], PM)
    program = _ok("initiate_closeout", resp)
    ctx["program"] = program
    return ctx


# ---------------------------------------------------------------------------
# Misc — reservations, claims, clock
# ---------------------------------------------------------------------------

def create_reservation(kit_id, staging_bay_code="BAY-1",
                       start_ts="2026-09-05T10:00:00Z",
                       end_ts="2026-09-05T12:00:00Z"):
    resp = api_client.create_staging_reservation(
        create_staging_reservation_payload(
            kit_id, staging_bay_code=staging_bay_code, start_ts=start_ts,
            end_ts=end_ts,
        ),
        WL,
    )
    return _ok("create_staging_reservation", resp, expected_status=201)


def create_claim(delivery_id, part_number="PN-600", claim_type="DAMAGED",
                 replacement_component_count=1, replacement_cost_cents=100):
    resp = api_client.create_damage_claim(
        create_damage_claim_payload(
            delivery_id, part_number=part_number, claim_type=claim_type,
            replacement_component_count=replacement_component_count,
            replacement_cost_cents=replacement_cost_cents,
        ),
        HA,
    )
    return _ok("create_damage_claim", resp, expected_status=201)


def set_clock(to_iso8601):
    """Advance the logical clock (PlatformAdmin). Returns the response data."""
    resp = api_client.set_current_utc({"to_iso8601": to_iso8601}, PA)
    return _ok("set_current_utc", resp)
