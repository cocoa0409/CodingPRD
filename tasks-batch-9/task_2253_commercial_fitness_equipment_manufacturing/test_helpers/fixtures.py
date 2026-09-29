"""Composite setup helpers.

Each test starts against an empty system, so every helper here builds its
preconditions from scratch using only the endpoints the PRD declares. All setup
calls go through get_success_data() so a broken precondition surfaces as a
"Setup step failed" message rather than a confusing assertion later.

Ownership-gated calls always thread the real entity identifier into the header
builder: a FacilityManager acts as its own facility's id and a
ServicePartnerTech acts as its own partner's id.
"""
from prd_bench_local_runner.testing import get_success_data

from . import factories as _f
from .api_client import api_client
from .constants import (
    MODEL_PRESETS,
    TEST_DEFAULTS,
)
from .test_users import (
    COMPLIANCE_OFFICER_USER_ID,
    PRODUCT_ENGINEER_USER_ID,
    TEST_USERS,
    make_compliance_officer_headers,
    make_product_engineer_headers,
    make_service_partner_tech_headers,
)

PE = TEST_USERS["product_engineer_headers"]
CO = TEST_USERS["compliance_officer_headers"]
CO_ALT = TEST_USERS["compliance_officer_alt_headers"]
OP = TEST_USERS["order_planner_headers"]
SOA = TEST_USERS["service_ops_admin_headers"]


# ─── Logical clock ─────────────────────────────────────────────────────────

def set_logical_clock(to_iso8601, headers=None) -> dict:
    """Move the server-side logical clock to a supplied instant."""
    return get_success_data(
        api_client.set_clock(_f.clock_payload(to_iso8601), headers or OP)
    )


# ─── Read helpers ──────────────────────────────────────────────────────────

def read_equipment_model(model_id, headers=None) -> dict:
    return get_success_data(api_client.get_equipment_model(model_id, headers or PE))


def read_model_revision(revision_id, headers=None) -> dict:
    return get_success_data(api_client.get_model_revision(revision_id, headers or PE))


def read_test_rig(rig_id, headers=None) -> dict:
    return get_success_data(api_client.get_test_rig(rig_id, headers or PE))


def read_test_run(run_id, headers=None) -> dict:
    return get_success_data(api_client.get_test_run(run_id, headers or PE))


def read_firmware_release(release_id, headers=None) -> dict:
    return get_success_data(api_client.get_firmware_release(release_id, headers or PE))


def read_firmware_certification(certification_id, headers=None) -> dict:
    return get_success_data(
        api_client.get_firmware_certification(certification_id, headers or PE)
    )


def read_facility(facility_id, headers=None) -> dict:
    return get_success_data(api_client.get_facility(facility_id, headers or OP))


def read_order(order_id, headers=None) -> dict:
    return get_success_data(api_client.get_order(order_id, headers or OP))


def read_order_line(line_id, headers=None) -> dict:
    return get_success_data(api_client.get_order_line(line_id, headers or OP))


def read_price_breakdown(order_id, headers=None) -> dict:
    return get_success_data(api_client.get_price_breakdown(order_id, headers or OP))


def read_service_partner(partner_id, headers=None) -> dict:
    return get_success_data(api_client.get_service_partner(partner_id, headers or SOA))


def read_install_job(job_id, headers=None) -> dict:
    return get_success_data(api_client.get_install_job(job_id, headers or OP))


def read_serialized_asset(asset_id, headers=None) -> dict:
    return get_success_data(api_client.get_serialized_asset(asset_id, headers or OP))


def read_pm_program(program_id, headers=None) -> dict:
    return get_success_data(api_client.get_pm_program(program_id, headers or SOA))


def read_maintenance_visit(visit_id, headers=None) -> dict:
    return get_success_data(api_client.get_maintenance_visit(visit_id, headers or SOA))


def list_all(list_method, params=None, headers=None) -> list:
    """Read every row of a listing, using the maximum page size."""
    query = {"limit": 100}
    if params:
        query.update(params)
    return get_success_data(list_method(headers or OP, params=query))


def read_qualification_report(revision_id, headers=None) -> dict:
    return get_success_data(
        api_client.get_qualification_report(revision_id, headers or PE)
    )


# ─── Catalogue primitives ──────────────────────────────────────────────────

def new_equipment_model(preset="T900", headers=None, **overrides) -> dict:
    """Register one equipment model from a preset catalogue entry."""
    payload = _f.equipment_model_payload(preset, **overrides)
    return get_success_data(
        api_client.create_equipment_model(payload, headers or PE), 201
    )


def new_model_revision(model, preset=None, headers=None, **overrides) -> dict:
    """Create an engineering revision, pinning the model version just read."""
    current = read_equipment_model(model["id"], headers or PE)
    preset = preset or _preset_for_model(current)
    payload = _f.revision_payload_for_preset(preset, current["id"], current["version"],
                                            **overrides)
    return get_success_data(
        api_client.create_model_revision(payload, headers or PE), 201
    )


def _preset_for_model(model: dict) -> str:
    for key, preset in MODEL_PRESETS.items():
        if preset["name"] == model["name"]:
            return key
    return "T900"


def new_test_rig(headers=None, **overrides) -> dict:
    return get_success_data(
        api_client.create_test_rig(_f.rig_payload(**overrides), headers or PE), 201
    )


def new_firmware_release(headers=None, **overrides) -> dict:
    return get_success_data(
        api_client.create_firmware_release(
            _f.firmware_release_payload(**overrides), headers or PE
        ),
        201,
    )


def submit_firmware_certification(firmware_release_id, model_revision_id,
                                  submitter_user_id=PRODUCT_ENGINEER_USER_ID,
                                  submitter_role="ProductEngineer", **overrides) -> dict:
    """Submit a firmware/revision pairing. The submitter identity matters: the
    officer who later signs off must be somebody else."""
    if submitter_role == "ProductEngineer":
        headers = make_product_engineer_headers(submitter_user_id)
    else:
        headers = make_compliance_officer_headers(submitter_user_id)
    payload = _f.firmware_certification_payload(
        firmware_release_id, model_revision_id, **overrides
    )
    return get_success_data(
        api_client.create_firmware_certification(payload, headers), 201
    )


def certify_firmware_certification(certification_id,
                                   officer_user_id=COMPLIANCE_OFFICER_USER_ID) -> dict:
    return get_success_data(
        api_client.certify_firmware_certification(
            certification_id, make_compliance_officer_headers(officer_user_id)
        )
    )


# ─── Revision progression ──────────────────────────────────────────────────

def submit_for_testing(revision_id, headers=None) -> dict:
    return get_success_data(
        api_client.submit_revision_for_testing(revision_id, headers or PE)
    )


def book_test_run(revision_id, rig_id, window_start, window_end,
                  target_cycles=300_000, headers=None) -> dict:
    payload = _f.run_payload(
        revision_id, rig_id, window_start, window_end, target_cycles
    )
    return get_success_data(api_client.create_test_run(payload, headers or PE), 201)


def start_test_run(run_id, headers=None) -> dict:
    return get_success_data(api_client.start_test_run(run_id, headers or PE))


def complete_test_run(run_id, outcome="PASSED", achieved_cycles=None,
                      failure_cycle_count=None, headers=None) -> dict:
    if outcome == "PASSED":
        payload = _f.run_pass_payload(achieved_cycles)
    else:
        payload = _f.run_fail_payload(failure_cycle_count)
    return get_success_data(api_client.complete_test_run(run_id, payload, headers or PE))


def default_run_specs(min_required_cycles: int) -> list:
    """Two passing runs whose achieved cycles land exactly on the gate."""
    first = min_required_cycles * 3 // 5
    return [
        {
            "window_start": TEST_DEFAULTS["RUN_ONE_WINDOW"][0],
            "window_end": TEST_DEFAULTS["RUN_ONE_WINDOW"][1],
            "target_cycles": first,
            "outcome": "PASSED",
            "achieved_cycles": first,
        },
        {
            "window_start": TEST_DEFAULTS["RUN_TWO_WINDOW"][0],
            "window_end": TEST_DEFAULTS["RUN_TWO_WINDOW"][1],
            "target_cycles": min_required_cycles - first,
            "outcome": "PASSED",
            "achieved_cycles": min_required_cycles - first,
        },
    ]


def accumulate_cycle_evidence(revision, rig=None, run_specs=None,
                              rig_overrides=None) -> dict:
    """Book, start and report durability runs against a revision in testing.

    Each spec may carry `stop_at` of RESERVED, RUNNING or COMPLETED (default).
    Returns {"rig": rig, "runs": [...]}.
    """
    if rig is None:
        rig = new_test_rig(**(rig_overrides or {}))
    specs = run_specs if run_specs is not None else default_run_specs(
        revision["min_required_cycles"]
    )
    runs = []
    for spec in specs:
        run = book_test_run(
            revision["id"],
            rig["id"],
            spec["window_start"],
            spec["window_end"],
            spec.get("target_cycles", 300_000),
        )
        stop_at = spec.get("stop_at", "COMPLETED")
        if stop_at in ("RUNNING", "COMPLETED"):
            run = start_test_run(run["id"])
        if stop_at == "COMPLETED":
            run = complete_test_run(
                run["id"],
                outcome=spec.get("outcome", "PASSED"),
                achieved_cycles=spec.get("achieved_cycles"),
                failure_cycle_count=spec.get("failure_cycle_count"),
            )
        runs.append(run)
    return {"rig": rig, "runs": runs}


def qualify_revision(revision_id, headers=None) -> dict:
    return get_success_data(api_client.qualify_revision(revision_id, headers or PE))


def release_revision(revision_id, officer_user_id=COMPLIANCE_OFFICER_USER_ID) -> dict:
    return get_success_data(
        api_client.release_revision(
            revision_id, make_compliance_officer_headers(officer_user_id)
        )
    )


def sunset_revision(revision_id, officer_user_id=COMPLIANCE_OFFICER_USER_ID,
                    **overrides) -> dict:
    return get_success_data(
        api_client.sunset_revision(
            revision_id,
            _f.sunset_payload(**overrides),
            make_compliance_officer_headers(officer_user_id),
        )
    )


# ─── Composite: the engineering chain ──────────────────────────────────────

def setup_qualified_revision(preset="T900", model_overrides=None, revision_overrides=None,
                             run_specs=None, rig=None, rig_overrides=None) -> dict:
    """Model → revision → durability evidence → QUALIFIED.

    Returns {"model", "revision", "rig", "runs"} with every entity freshly read.
    """
    model = new_equipment_model(preset, **(model_overrides or {}))
    revision = new_model_revision(model, preset, **(revision_overrides or {}))
    submit_for_testing(revision["id"])
    revision = read_model_revision(revision["id"])
    evidence = accumulate_cycle_evidence(
        revision, rig=rig, run_specs=run_specs, rig_overrides=rig_overrides
    )
    revision = qualify_revision(revision["id"])
    return {
        "model": read_equipment_model(model["id"]),
        "revision": revision,
        "rig": read_test_rig(evidence["rig"]["id"]),
        "runs": evidence["runs"],
    }


def setup_released_revision(preset="T900", model_overrides=None, revision_overrides=None,
                            run_specs=None, rig=None, rig_overrides=None,
                            firmware_overrides=None,
                            certification_overrides=None) -> dict:
    """Model → revision → durability evidence → QUALIFIED → RELEASED.

    A connected model additionally gets a firmware release, a submitted
    certification and an officer sign-off, because releasing a revision of a
    connected model requires at least one CERTIFIED certification.

    Returns {"model", "revision", "rig", "runs", "firmware_release",
    "certification"}.
    """
    ctx = setup_qualified_revision(
        preset, model_overrides, revision_overrides, run_specs, rig, rig_overrides
    )
    firmware_release = None
    certification = None
    if ctx["model"]["connected"]:
        fw_defaults = {"console_platform": ctx["model"]["console_platform"]}
        fw_defaults.update(firmware_overrides or {})
        firmware_release = new_firmware_release(**fw_defaults)
        certification = submit_firmware_certification(
            firmware_release["id"], ctx["revision"]["id"],
            **(certification_overrides or {})
        )
        certification = certify_firmware_certification(certification["id"])
        firmware_release = read_firmware_release(firmware_release["id"])
    revision = release_revision(ctx["revision"]["id"])
    return {
        "model": read_equipment_model(ctx["model"]["id"]),
        "revision": revision,
        "rig": ctx["rig"],
        "runs": ctx["runs"],
        "firmware_release": firmware_release,
        "certification": certification,
    }


# ─── Commercial primitives ─────────────────────────────────────────────────

def new_facility(headers=None, **overrides) -> dict:
    return get_success_data(
        api_client.create_facility(_f.facility_payload(**overrides), headers or OP), 201
    )


def suspend_facility(facility_id, headers=None, **overrides) -> dict:
    return get_success_data(
        api_client.suspend_facility(
            facility_id, _f.suspend_facility_payload(**overrides), headers or OP
        )
    )


def new_order(facility_id, headers=None, **overrides) -> dict:
    return get_success_data(
        api_client.create_order(_f.order_payload(facility_id, **overrides), headers or OP),
        201,
    )


def new_order_line(order_id, model_revision_id, quantity=1, finish_codes=None,
                   layout_zone_label=None, headers=None, **overrides) -> dict:
    payload = _f.order_line_payload(
        model_revision_id, quantity, finish_codes, layout_zone_label, **overrides
    )
    return get_success_data(
        api_client.create_order_line(order_id, payload, headers or OP), 201
    )


def quote_order(order_id, headers=None, expected_order_version=None) -> dict:
    """Re-read the order so the quote pins the version it actually priced."""
    version = expected_order_version
    if version is None:
        version = read_order(order_id)["version"]
    return get_success_data(
        api_client.quote_order(order_id, _f.quote_payload(version), headers or OP)
    )


def confirm_order(order_id, headers=None) -> dict:
    return get_success_data(api_client.confirm_order(order_id, headers or OP))


def complete_production(order_id, headers=None) -> dict:
    return get_success_data(api_client.complete_order_production(order_id, headers or OP))


def settle_order(order_id, headers=None, **overrides) -> dict:
    return get_success_data(
        api_client.settle_order(order_id, _f.settle_payload(**overrides), headers or OP)
    )


def apply_tradein_credit(order_id, amount_cents, facility_id=None,
                         expected_facility_version=None, headers=None) -> dict:
    """Apply facility trade-in credit, pinning the facility version just read."""
    version = expected_facility_version
    if version is None:
        version = read_facility(facility_id)["version"]
    payload = _f.apply_tradein_credit_payload(amount_cents, version)
    return get_success_data(
        api_client.apply_tradein_credit(order_id, payload, headers or OP)
    )


# ─── Service-network primitives ────────────────────────────────────────────

def new_service_partner(headers=None, **overrides) -> dict:
    return get_success_data(
        api_client.create_service_partner(
            _f.service_partner_payload(**overrides), headers or SOA
        ),
        201,
    )


def receive_parts(partner_id, units, headers=None) -> dict:
    return get_success_data(
        api_client.post_parts_receipt(
            partner_id, _f.parts_receipt_payload(units), headers or SOA
        )
    )


def new_install_job(order_id, service_partner_id, window_start=None, window_end=None,
                    estimated_labor_hours=None, headers=None) -> dict:
    payload = _f.install_job_payload(
        order_id, service_partner_id, window_start, window_end, estimated_labor_hours
    )
    return get_success_data(api_client.create_install_job(payload, headers or OP), 201)


def arrive_on_site(job_id, service_partner_id) -> dict:
    return get_success_data(
        api_client.arrive_install_job(
            job_id, make_service_partner_tech_headers(service_partner_id)
        )
    )


def complete_install_job(job_id, service_partner_id, actual_labor_hours=3.0,
                         punch_list_open_count=0) -> dict:
    return get_success_data(
        api_client.complete_install_job(
            job_id,
            _f.complete_install_payload(actual_labor_hours, punch_list_open_count),
            make_service_partner_tech_headers(service_partner_id),
        )
    )


def resolve_punch_list(job_id, service_partner_id, **overrides) -> dict:
    return get_success_data(
        api_client.resolve_punch_list(
            job_id,
            _f.resolve_punch_list_payload(**overrides),
            make_service_partner_tech_headers(service_partner_id),
        )
    )


def new_pm_program(facility_id, service_partner_id, tier="PRO", visit_interval_days=90,
                   headers=None) -> dict:
    payload = _f.pm_program_payload(
        facility_id, service_partner_id, tier, visit_interval_days
    )
    return get_success_data(api_client.create_pm_program(payload, headers or SOA), 201)


def activate_pm_program(program_id, headers=None) -> dict:
    return get_success_data(api_client.activate_pm_program(program_id, headers or SOA))


def setup_active_pm_program(facility_id, service_partner_id, tier="PRO",
                            visit_interval_days=90) -> dict:
    program = new_pm_program(facility_id, service_partner_id, tier, visit_interval_days)
    return activate_pm_program(program["id"])


def new_maintenance_visit(pm_program_id, serialized_asset_id, service_partner_id,
                          scheduled_date="2026-09-20T09:00:00Z", reserved_units=0) -> dict:
    payload = _f.maintenance_visit_payload(
        pm_program_id, serialized_asset_id, scheduled_date, reserved_units
    )
    return get_success_data(
        api_client.create_maintenance_visit(
            payload, make_service_partner_tech_headers(service_partner_id)
        ),
        201,
    )


def complete_maintenance_visit(visit_id, service_partner_id, labor_hours=2.0) -> dict:
    return get_success_data(
        api_client.complete_maintenance_visit(
            visit_id,
            _f.complete_visit_payload(labor_hours),
            make_service_partner_tech_headers(service_partner_id),
        )
    )


def cancel_maintenance_visit(visit_id, headers=None, **overrides) -> dict:
    return get_success_data(
        api_client.cancel_maintenance_visit(
            visit_id, _f.cancel_visit_payload(**overrides), headers or SOA
        )
    )


def report_usage(asset_id, service_partner_id, annual_usage_hours=1800.0) -> dict:
    return get_success_data(
        api_client.report_asset_usage(
            asset_id,
            _f.usage_report_payload(annual_usage_hours),
            make_service_partner_tech_headers(service_partner_id),
        )
    )


def trade_in_asset(asset_id, declared_condition_grade="A", headers=None) -> dict:
    return get_success_data(
        api_client.trade_in_asset(
            asset_id, _f.trade_in_payload(declared_condition_grade), headers or OP
        )
    )


def refurb_intake(asset_id, headers=None) -> dict:
    return get_success_data(api_client.refurb_intake_asset(asset_id, headers or SOA))


def refurb_certify(asset_id, refurb_grade="B", headers=None) -> dict:
    return get_success_data(
        api_client.refurb_certify_asset(
            asset_id, _f.refurb_certify_payload(refurb_grade), headers or SOA
        )
    )


def load_firmware(asset_id, firmware_release_id, headers=None) -> dict:
    return get_success_data(
        api_client.load_firmware(
            asset_id, _f.load_firmware_payload(firmware_release_id), headers or PE
        )
    )


# ─── Composite: the order chain ────────────────────────────────────────────

def setup_configured_order(preset="T900", quantity=1, finish_codes=None,
                           layout_zone_label=None, model_overrides=None,
                           revision_overrides=None, run_specs=None,
                           facility_overrides=None, order_overrides=None,
                           revision_ctx=None) -> dict:
    """Released revision + facility + order + one ACTIVE line, still CONFIGURING.

    Returns a context dict carrying every entity the later stages need:
    model, revision, rig, runs, firmware_release, certification, facility,
    order, lines, line, categories.
    """
    ctx = dict(
        revision_ctx
        or setup_released_revision(
            preset,
            model_overrides=model_overrides,
            revision_overrides=revision_overrides,
            run_specs=run_specs,
        )
    )
    ctx["facility"] = new_facility(**(facility_overrides or {}))
    ctx["order"] = new_order(ctx["facility"]["id"], **(order_overrides or {}))
    ctx["lines"] = []
    ctx["categories"] = []
    add_order_line(ctx, quantity=quantity, finish_codes=finish_codes,
                   layout_zone_label=layout_zone_label)
    return ctx


def add_order_line(ctx, revision=None, model=None, quantity=1, finish_codes=None,
                   layout_zone_label=None, headers=None) -> dict:
    """Add a line to the context's order and record its equipment category."""
    revision = revision or ctx["revision"]
    model = model or ctx["model"]
    line = new_order_line(
        ctx["order"]["id"], revision["id"], quantity, finish_codes,
        layout_zone_label, headers=headers,
    )
    ctx["lines"].append(line)
    ctx["line"] = ctx["lines"][0]
    if model["category"] not in ctx["categories"]:
        ctx["categories"].append(model["category"])
    ctx["order"] = read_order(ctx["order"]["id"])
    return line


def quote_ctx(ctx, headers=None) -> dict:
    ctx["order"] = quote_order(ctx["order"]["id"], headers=headers)
    return ctx["order"]


def confirm_ctx(ctx, headers=None) -> dict:
    ctx["order"] = confirm_order(ctx["order"]["id"], headers=headers)
    ctx["facility"] = read_facility(ctx["facility"]["id"])
    return ctx["order"]


def complete_production_ctx(ctx) -> dict:
    ctx["order"] = complete_production(ctx["order"]["id"])
    ctx["assets"] = list_all(
        api_client.list_serialized_assets, {"facility_id": ctx["facility"]["id"]}
    )
    if ctx["assets"]:
        ctx["asset"] = ctx["assets"][0]
    return ctx["order"]


def add_partner_ctx(ctx, **overrides) -> dict:
    """Onboard a partner certified for every category present on the order."""
    defaults = {"certified_categories": list(ctx.get("categories") or ["CARDIO"])}
    defaults.update(overrides)
    ctx["partner"] = new_service_partner(**defaults)
    return ctx["partner"]


def schedule_install_ctx(ctx, window_start=None, window_end=None,
                         estimated_labor_hours=None, partner=None) -> dict:
    partner = partner or ctx.get("partner") or add_partner_ctx(ctx)
    ctx["partner"] = partner
    ctx["install_job"] = new_install_job(
        ctx["order"]["id"], partner["id"], window_start, window_end,
        estimated_labor_hours,
    )
    ctx["partner"] = read_service_partner(partner["id"])
    return ctx["install_job"]


def arrive_ctx(ctx) -> dict:
    ctx["install_job"] = arrive_on_site(
        ctx["install_job"]["id"], ctx["partner"]["id"]
    )
    ctx["order"] = read_order(ctx["order"]["id"])
    return ctx["install_job"]


def complete_install_ctx(ctx, actual_labor_hours=3.0, punch_list_open_count=0) -> dict:
    ctx["install_job"] = complete_install_job(
        ctx["install_job"]["id"], ctx["partner"]["id"], actual_labor_hours,
        punch_list_open_count,
    )
    ctx["order"] = read_order(ctx["order"]["id"])
    ctx["facility"] = read_facility(ctx["facility"]["id"])
    ctx["partner"] = read_service_partner(ctx["partner"]["id"])
    ctx["assets"] = list_all(
        api_client.list_serialized_assets, {"facility_id": ctx["facility"]["id"]}
    )
    if ctx["assets"]:
        ctx["asset"] = ctx["assets"][0]
    return ctx["install_job"]


def setup_staged_order(**kwargs) -> dict:
    """Order chain through production complete: assets minted, still BUILT."""
    partner_overrides = kwargs.pop("partner_overrides", None)
    ctx = setup_configured_order(**kwargs)
    quote_ctx(ctx)
    confirm_ctx(ctx)
    complete_production_ctx(ctx)
    if partner_overrides is not None:
        add_partner_ctx(ctx, **partner_overrides)
    return ctx


def setup_scheduled_install(window_start=None, window_end=None,
                            estimated_labor_hours=None, partner_overrides=None,
                            **kwargs) -> dict:
    """Order chain through a SCHEDULED install job."""
    ctx = setup_staged_order(partner_overrides=partner_overrides or {}, **kwargs)
    schedule_install_ctx(ctx, window_start, window_end, estimated_labor_hours)
    return ctx


def setup_installed_order(actual_labor_hours=3.0, punch_list_open_count=0,
                          window_start=None, window_end=None,
                          estimated_labor_hours=None, partner_overrides=None,
                          **kwargs) -> dict:
    """Full order chain through install completion.

    On the zero-punch-list branch the order reaches INSTALLED and INVOICED, the
    assets reach IN_SERVICE with warranty derived, and the partner's committed
    hours are recomputed.
    """
    ctx = setup_scheduled_install(
        window_start=window_start,
        window_end=window_end,
        estimated_labor_hours=estimated_labor_hours,
        partner_overrides=partner_overrides,
        **kwargs,
    )
    arrive_ctx(ctx)
    complete_install_ctx(ctx, actual_labor_hours, punch_list_open_count)
    return ctx


def setup_in_service_asset(preset="T900", quantity=1, **kwargs) -> dict:
    """Shortcut for the service and trade-in workflows: one IN_SERVICE asset at
    an active facility, with its order INVOICED."""
    return setup_installed_order(preset=preset, quantity=quantity, **kwargs)
