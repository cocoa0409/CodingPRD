"""Composite setup helpers for multi-step test prerequisites (PRD §3 workflows).

Every helper builds its preconditions from scratch using only PRD-declared
endpoints (the server is restarted before each test, so each test starts
against an empty database). get_success_data() is used internally so setup
failures surface as clear errors rather than confusing assertion failures.

Identity threading: ownership-gated Client calls use make_client_headers(client_id);
assignment-gated Engineer calls use make_engineer_headers(engineer_id).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import DEFAULT_CLOCK_ISO, DEFAULT_SESSION_START, DEFAULT_UPC, DEFAULT_ISRC
from .factories import (
    create_client_payload, create_engineer_payload, create_platform_profile_payload,
    create_rush_tier_rule_payload, create_project_payload, create_session_slot_payload,
    create_source_asset_payload, create_deliverable_payload, create_metadata_tag_payload,
    create_qc_report_payload, create_credit_adjustment_payload, create_archive_payload,
)
from .test_users import TEST_USERS, make_client_headers, make_engineer_headers

MANAGER = TEST_USERS["manager_headers"]
QA = TEST_USERS["qa_headers"]


# ─── Tier 0: primitives ────────────────────────────────

def set_logical_clock(to_iso8601=DEFAULT_CLOCK_ISO):
    """Advance the server logical clock (PRD §2.11)."""
    res = api_client.set_clock({"to_iso8601": to_iso8601}, MANAGER)
    get_success_data(res)


def make_engineer(hourly_rate_cents=80000, capacity_minutes_per_day=480,
                  tier="STAFF", display_name=None) -> dict:
    payload = create_engineer_payload(
        tier=tier, hourly_rate_cents=hourly_rate_cents,
        capacity_minutes_per_day=capacity_minutes_per_day,
        **({"display_name": display_name} if display_name else {}),
    )
    return get_success_data(api_client.create_engineer(payload, MANAGER))


def make_platform_profile(**overrides) -> dict:
    return get_success_data(api_client.create_platform_profile(
        create_platform_profile_payload(**overrides), MANAGER))


def make_rush_tier_rule(tier="STANDARD", multiplier_bp=10000, sla_hours=72,
                        surcharge_breach_cents=0, included_revision_rounds=1,
                        per_round_cents=10000) -> dict:
    return get_success_data(api_client.create_rush_tier_rule(
        create_rush_tier_rule_payload(
            tier=tier, multiplier_bp=multiplier_bp, sla_hours=sla_hours,
            surcharge_breach_cents=surcharge_breach_cents,
            included_revision_rounds=included_revision_rounds,
            per_round_cents=per_round_cents), MANAGER))


def make_client(credit_cents=None, **overrides) -> dict:
    """Create a client; optionally seed account credit via a manual adjustment."""
    client = get_success_data(api_client.create_client(
        create_client_payload(**overrides), MANAGER))
    if credit_cents:
        adj = get_success_data(api_client.create_credit_adjustment(
            client["id"],
            create_credit_adjustment_payload(amount_cents=credit_cents, reason="seed"),
            MANAGER))
        client = adj
    return client


def make_project(client_id, profile_id, title=None, upc=DEFAULT_UPC,
                 scheduled_start_at=DEFAULT_SESSION_START,
                 scheduled_duration_minutes=60, rush_tier="STANDARD") -> dict:
    """Create a DRAFT project as its owning client (PRD §3.3)."""
    overrides = {
        "scheduled_start_at": scheduled_start_at,
        "scheduled_duration_minutes": scheduled_duration_minutes,
        "rush_tier": rush_tier,
    }
    if upc is not None:
        overrides["upc"] = upc
    if title:
        overrides["title"] = title
    payload = create_project_payload(client_id, profile_id, **overrides)
    return get_success_data(api_client.create_project(payload, make_client_headers(client_id)))


def activate_client(client_id) -> dict:
    """PROSPECT/SUSPENDED → ACTIVE (PRD §3.1)."""
    return get_success_data(api_client.activate_client(client_id, MANAGER))


def current_client_version(client_id) -> int:
    return get_success_data(api_client.get_client(client_id, MANAGER))["version"]


def current_project_version(project_id) -> int:
    return get_success_data(api_client.get_project(project_id, MANAGER))["version"]


# ─── Tier 1: booking ───────────────────────────────────

def book_project(project_id, client_id) -> dict:
    """DRAFT → BOOKED with a fresh expected_client_version (PRD §2.9, §3.3)."""
    version = current_client_version(client_id)
    return get_success_data(api_client.book_project(
        project_id, {"expected_client_version": version}, make_client_headers(client_id)))


# ─── Tier 2: composite studio / project states ─────────

def setup_booked_project(credit_cents=500000, engineer_rate=80000,
                         engineer_capacity=480, profile_overrides=None,
                         rush_tier="STANDARD", rule_overrides=None,
                         project_overrides=None, client_overrides=None) -> dict:
    """Studio config (engineer + profile + rush rule) plus an ACTIVE client with
    a BOOKED project. Returns a context dict with all created entities."""
    set_logical_clock()
    engineer = make_engineer(hourly_rate_cents=engineer_rate,
                             capacity_minutes_per_day=engineer_capacity)
    profile = make_platform_profile(**(profile_overrides or {}))
    rule_kwargs = {"tier": rush_tier}
    rule_kwargs.update(rule_overrides or {})
    rule = make_rush_tier_rule(**rule_kwargs)
    client = make_client(credit_cents=credit_cents, **(client_overrides or {}))
    proj_kwargs = {"rush_tier": rush_tier}
    proj_kwargs.update(project_overrides or {})
    project = make_project(client["id"], profile["id"], **proj_kwargs)
    client = activate_client(client["id"])
    project = book_project(project["id"], client["id"])
    return {
        "engineer": engineer, "profile": profile, "rule": rule,
        "client": client, "project": project,
    }


def setup_project_in_mastering(credit_cents=500000, engineer_rate=80000,
                               profile_overrides=None, rush_tier="STANDARD",
                               rule_overrides=None, project_overrides=None,
                               asset_overrides=None) -> dict:
    """Booked project walked through intake + QC into MASTERING with round 1 OPEN.
    Returns context including round1 and its deadline."""
    ctx = setup_booked_project(
        credit_cents=credit_cents, engineer_rate=engineer_rate,
        profile_overrides=profile_overrides, rush_tier=rush_tier,
        rule_overrides=rule_overrides, project_overrides=project_overrides)
    eng_headers = make_engineer_headers(ctx["engineer"]["id"])
    project_id = ctx["project"]["id"]

    get_success_data(api_client.begin_intake(project_id, eng_headers))
    asset = get_success_data(api_client.upload_source_asset(
        project_id,
        create_source_asset_payload(
            sample_rate_hz=ctx["profile"]["required_sample_rate_hz"],
            bit_depth=ctx["profile"]["required_bit_depth"],
            **(asset_overrides or {})),
        eng_headers))
    get_success_data(api_client.qc_pass_source_asset(asset["id"], eng_headers))
    get_success_data(api_client.complete_project_qc(project_id, eng_headers))
    project = get_success_data(api_client.start_mastering(project_id, eng_headers))

    round_id = project["current_revision_round_id"]
    round1 = get_success_data(api_client.get_revision_round(round_id, MANAGER))
    ctx.update({"project": project, "asset": asset, "round1": round1})
    return ctx


def submit_current_round(ctx) -> dict:
    """Engineer submits the project's current OPEN round with a fresh
    expected_project_version (PRD §2.9, §3.6). Project moves MASTERING → REVISION."""
    project_id = ctx["project"]["id"]
    round_id = ctx["round1"]["id"] if "round1" in ctx else ctx["round"]["id"]
    version = current_project_version(project_id)
    round_after = get_success_data(api_client.submit_round(
        project_id, round_id, {"expected_project_version": version},
        make_engineer_headers(ctx["engineer"]["id"])))
    return round_after


def setup_project_in_revision(**kwargs) -> dict:
    """Project in REVISION with the current round SUBMITTED."""
    ctx = setup_project_in_mastering(**kwargs)
    ctx["round1"] = submit_current_round(ctx)
    ctx["project"] = get_success_data(
        api_client.get_project(ctx["project"]["id"], MANAGER))
    return ctx


def reject_current_round(ctx, round_key="round1") -> dict:
    """Client rejects the SUBMITTED round; a new round opens (PRD §3.6).
    Returns the fresh context with project + new current round."""
    project_id = ctx["project"]["id"]
    client_id = ctx["client"]["id"]
    get_success_data(api_client.reject_round(
        project_id, ctx[round_key]["id"], {}, make_client_headers(client_id)))
    project = get_success_data(api_client.get_project(project_id, MANAGER))
    new_round = get_success_data(
        api_client.get_revision_round(project["current_revision_round_id"], MANAGER))
    ctx["project"] = project
    ctx["round"] = new_round
    ctx.pop("round1", None)
    return ctx


def approve_current_round(ctx, round_key="round1") -> dict:
    """Client approves the SUBMITTED round: final quote runs and the client's
    ledger is debited (PRD §3.6). Project moves REVISION → APPROVED."""
    project_id = ctx["project"]["id"]
    client_id = ctx["client"]["id"]
    round_id = ctx[round_key]["id"]
    round_after = get_success_data(api_client.approve_round(
        project_id, round_id, make_client_headers(client_id)))
    project = get_success_data(api_client.get_project(project_id, MANAGER))
    client = get_success_data(api_client.get_client(client_id, MANAGER))
    ctx.update({"project": project, "client": client, round_key: round_after})
    return ctx


def setup_project_approved(**kwargs) -> dict:
    """Project APPROVED after its first submitted round is approved."""
    ctx = setup_project_in_revision(**kwargs)
    return approve_current_round(ctx)


# ─── Tier 3: deliverable lifecycle ─────────────────────

def make_deliverable(ctx, **overrides) -> dict:
    """Create a BUILDING deliverable against the project's current round, with
    measured characteristics matching the project's platform profile by default."""
    project = ctx["project"]
    profile = ctx["profile"]
    round_id = project.get("current_revision_round_id") or ctx["round1"]["id"]
    profile_defaults = {
        "integrated_lufs": profile["integrated_lufs"],
        "true_peak_dbtp": profile["true_peak_dbtp"],
        "loudness_range_lu": profile["loudness_range_lu"],
        "sample_rate_hz": profile["required_sample_rate_hz"],
        "bit_depth": profile["required_bit_depth"],
    }
    profile_defaults.update(overrides)
    payload = create_deliverable_payload(round_id, **profile_defaults)
    return get_success_data(api_client.create_deliverable(
        project["id"], payload, make_engineer_headers(ctx["engineer"]["id"])))


def submit_deliverable_to_qc(ctx, deliverable_id) -> dict:
    """BUILDING → QC_PENDING (PRD §3.7)."""
    return get_success_data(api_client.submit_deliverable_qc(
        deliverable_id, make_engineer_headers(ctx["engineer"]["id"])))


def record_qc_report(deliverable_id, check_code="LOUDNESS_IN_TOL", passed=True,
                     measured_value=-14.0, tolerance=0.5) -> dict:
    return get_success_data(api_client.create_qc_report(
        deliverable_id,
        create_qc_report_payload(check_code=check_code, passed=passed,
                                 measured_value=measured_value, tolerance=tolerance),
        QA))


def qc_pass_deliverable(deliverable_id) -> dict:
    """QC_PENDING → READY (QA verdict, PRD §3.7)."""
    return get_success_data(api_client.qc_pass_deliverable(deliverable_id, QA))


def setup_ready_deliverable(ctx, deliverable_overrides=None,
                            report_overrides=None) -> dict:
    """Deliverable walked to READY: create → submit-qc → passing report → qc-pass."""
    deliverable = make_deliverable(ctx, **(deliverable_overrides or {}))
    submit_deliverable_to_qc(ctx, deliverable["id"])
    record_qc_report(deliverable["id"], **(report_overrides or {}))
    deliverable = qc_pass_deliverable(deliverable["id"])
    ctx["deliverable"] = deliverable
    return ctx


def setup_verified_deliverable(ctx, deliverable_overrides=None,
                               report_overrides=None, tag_overrides=None) -> dict:
    """READY deliverable embedded with metadata and QA-verified → VERIFIED (PRD §3.7)."""
    ctx = setup_ready_deliverable(ctx, deliverable_overrides, report_overrides)
    deliverable = ctx["deliverable"]
    tag_kwargs = {"isrc": DEFAULT_ISRC}
    project_upc = ctx["project"].get("upc")
    if project_upc:
        tag_kwargs["upc"] = project_upc
    tag_kwargs.update(tag_overrides or {})
    tag = get_success_data(api_client.embed_metadata(
        deliverable["id"], tag_kwargs, make_engineer_headers(ctx["engineer"]["id"])))
    deliverable = get_success_data(api_client.verify_deliverable_metadata(
        deliverable["id"], QA))
    ctx.update({"deliverable": deliverable, "tag": tag})
    return ctx


# ─── Tier 4: delivery / archive / recall ───────────────

def setup_project_delivering(**kwargs) -> dict:
    """Project APPROVED → DELIVERING with a VERIFIED deliverable in place (PRD §3.8)."""
    ctx = setup_project_approved(**kwargs)
    ctx = setup_verified_deliverable(ctx)
    ctx["project"] = get_success_data(api_client.deliver_project(
        ctx["project"]["id"], make_engineer_headers(ctx["engineer"]["id"])))
    return ctx


def setup_project_delivered(**kwargs) -> dict:
    """Project DELIVERING → DELIVERED (PRD §3.8)."""
    ctx = setup_project_delivering(**kwargs)
    ctx["project"] = get_success_data(api_client.finalize_delivery(
        ctx["project"]["id"], make_engineer_headers(ctx["engineer"]["id"])))
    return ctx


def setup_archived_project(storage_class="HOT", archive_size_bytes=1073741824,
                           **kwargs) -> dict:
    """Full lifecycle through ARCHIVED with an ArchiveBundle created (PRD §3.8)."""
    ctx = setup_project_delivered(**kwargs)
    bundle = get_success_data(api_client.archive_project(
        ctx["project"]["id"],
        create_archive_payload(storage_class=storage_class,
                               archive_size_bytes=archive_size_bytes),
        MANAGER))
    ctx["project"] = get_success_data(
        api_client.get_project(ctx["project"]["id"], MANAGER))
    ctx["bundle"] = bundle
    return ctx


def setup_recalled_project(storage_class="HOT", archive_size_bytes=1073741824,
                           **kwargs) -> dict:
    """Archived project recalled by its owning client; bundle NONE → PENDING (PRD §3.8)."""
    ctx = setup_archived_project(storage_class=storage_class,
                                 archive_size_bytes=archive_size_bytes, **kwargs)
    bundle = get_success_data(api_client.recall_project(
        ctx["project"]["id"], make_client_headers(ctx["client"]["id"])))
    ctx["bundle"] = bundle
    ctx["project"] = get_success_data(
        api_client.get_project(ctx["project"]["id"], MANAGER))
    return ctx


# ─── Tier 5: session slots ─────────────────────────────

def make_held_slot(engineer_id, slot_start_at="2026-05-11T10:00:00Z",
                   slot_end_at="2026-05-11T11:00:00Z", project_id=None) -> dict:
    """Create a HELD session slot as a studio manager (PRD §3.4)."""
    payload = create_session_slot_payload(
        engineer_id, slot_start_at=slot_start_at, slot_end_at=slot_end_at)
    if project_id:
        payload["project_id"] = project_id
    return get_success_data(api_client.create_session_slot(payload, MANAGER))
