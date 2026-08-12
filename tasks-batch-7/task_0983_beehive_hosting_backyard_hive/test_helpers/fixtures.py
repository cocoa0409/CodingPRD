"""Composite setup helpers for multi-step test prerequisites.

Setup helpers use get_success_data() (lenient) so a setup failure surfaces as
a clear "Setup failed" message instead of a confusing assertion error.

Identity threading: Host is entity-backed, so every host-scoped call uses
make_host_headers(host["id"]); Beekeeper/ApiaryManager/PlatformOps are opaque
operator ids (PRD §2.1).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    BEEKEEPER_1,
    MANAGER_1,
    TEST_DEFAULTS,
)
from .factories import (
    create_agreement_payload,
    create_enrollment_payload,
    create_harvest_payload,
    create_host_payload,
    create_hive_payload,
    create_inspection_payload,
    create_removal_job_payload,
    create_season_payload,
    create_site_payload,
    create_subscription_payload,
    create_swarm_event_payload,
    create_treatment_payload,
    decide_removal_payload,
    rollover_payload,
    sign_waiver_payload,
)
from .test_users import (
    TEST_USERS,
    make_beekeeper_headers,
    make_host_headers,
    make_manager_headers,
    make_ops_headers,
)

OPS = TEST_USERS["ops_headers"]
ANON = TEST_USERS["anonymous_headers"]
MGR = TEST_USERS["manager_headers"]
BK1 = TEST_USERS["beekeeper_headers"]


# ---------------------------------------------------------------------------
# Tier 1: single-entity state progression
# ---------------------------------------------------------------------------

def create_host(**overrides) -> dict:
    """Register a host (Anonymous self-service). Returns APPLICANT host."""
    res = api_client.create_host(create_host_payload(**overrides), ANON)
    return get_success_data(res)


def activate_host(host: dict, waiver_version: str = TEST_DEFAULTS["WAIVER_VERSION"]) -> dict:
    """Sign the liability waiver as the host: APPLICANT -> ACTIVE."""
    res = api_client.sign_waiver(
        host["id"], sign_waiver_payload(waiver_version=waiver_version),
        make_host_headers(host["id"]),
    )
    return get_success_data(res)


def create_active_host(**overrides) -> dict:
    """Host registered and waiver-signed (ACTIVE). Returns host dict."""
    host = create_host(**overrides)
    return activate_host(host)


def create_site_for(host: dict, **overrides) -> dict:
    """Create a site owned by the host. Returns CLEAR site."""
    res = api_client.create_site(
        create_site_payload(host["id"], **overrides),
        make_host_headers(host["id"]),
    )
    return get_success_data(res)


def create_agreement_for(host: dict, site: dict, **overrides) -> dict:
    """PlatformOps creates an agreement (PENDING_SIGNATURE)."""
    res = api_client.create_agreement(
        create_agreement_payload(host["id"], site["id"], **overrides), OPS,
    )
    return get_success_data(res)


def sign_agreement_for(agreement: dict, host: dict) -> dict:
    """Owning host signs: PENDING_SIGNATURE -> ACTIVE."""
    res = api_client.sign_agreement(
        agreement["id"], make_host_headers(host["id"]),
    )
    return get_success_data(res)


def create_season(**overrides) -> dict:
    """Create the genesis season (OPEN)."""
    res = api_client.create_season(create_season_payload(**overrides), OPS)
    return get_success_data(res)


def set_clock(to_iso8601: str):
    res = api_client.set_clock(to_iso8601, OPS)
    get_success_data(res)


def rollover_season(season_id: str, at: str = None, **overrides) -> dict:
    """Close the OPEN season (optionally moving the logical clock first) and
    return the successor season."""
    if at is not None:
        set_clock(at)
    res = api_client.rollover_season(season_id, rollover_payload(**overrides), OPS)
    return get_success_data(res)


# ---------------------------------------------------------------------------
# Tier 2: entity hierarchy (host -> site -> agreement -> hive)
# ---------------------------------------------------------------------------

def setup_host_with_site(host_overrides=None, site_overrides=None) -> tuple:
    """ACTIVE host + one CLEAR site. Returns (host, site)."""
    host = create_active_host(**(host_overrides or {}))
    site = create_site_for(host, **(site_overrides or {}))
    return host, site


def setup_signed_agreement(
    host_overrides=None,
    site_overrides=None,
    agreement_overrides=None,
) -> tuple:
    """ACTIVE host + CLEAR site + ACTIVE (signed) agreement.

    Returns (host, site, agreement_after_sign).
    """
    host, site = setup_host_with_site(host_overrides, site_overrides)
    agreement = create_agreement_for(host, site, **(agreement_overrides or {}))
    agreement = sign_agreement_for(agreement, host)
    return host, site, agreement


def setup_hive_scenario(
    host_overrides=None,
    site_overrides=None,
    agreement_overrides=None,
    manager: str = MANAGER_1,
) -> dict:
    """ACTIVE host + CLEAR site + ACTIVE agreement + one installed hive.

    Returns {"host", "site", "agreement", "hive"}.
    """
    host, site, agreement = setup_signed_agreement(
        host_overrides, site_overrides, agreement_overrides,
    )
    hive = get_success_data(api_client.create_hive(
        create_hive_payload(site["id"], agreement["id"]),
        make_manager_headers(manager),
    ))
    return {"host": host, "site": site, "agreement": agreement, "hive": hive}


# ---------------------------------------------------------------------------
# Tier 3: inspection / treatment / harvest lifecycle shortcuts
# ---------------------------------------------------------------------------

def record_inspection(hive_id: str, beekeeper: str = BEEKEEPER_1, **overrides) -> dict:
    """Record a DRAFT inspection as the given beekeeper."""
    res = api_client.create_inspection(
        create_inspection_payload(hive_id, **overrides),
        make_beekeeper_headers(beekeeper),
    )
    return get_success_data(res)


def submit_inspection(inspection_id: str, beekeeper: str = BEEKEEPER_1) -> dict:
    res = api_client.submit_inspection(
        inspection_id, make_beekeeper_headers(beekeeper),
    )
    return get_success_data(res)


def verify_inspection(inspection_id: str, manager: str = MANAGER_1) -> dict:
    res = api_client.verify_inspection(
        inspection_id, make_manager_headers(manager),
    )
    return get_success_data(res)


def create_and_verify_inspection(
    hive_id: str,
    beekeeper: str = BEEKEEPER_1,
    manager: str = MANAGER_1,
    **overrides,
) -> dict:
    """Record -> submit -> verify. Returns the VERIFIED inspection."""
    insp = record_inspection(hive_id, beekeeper=beekeeper, **overrides)
    submit_inspection(insp["id"], beekeeper=beekeeper)
    return verify_inspection(insp["id"], manager=manager)


def record_harvest(hive_id: str, beekeeper: str = BEEKEEPER_1, **overrides) -> dict:
    """Record a harvest (RECORDED)."""
    res = api_client.create_harvest(
        create_harvest_payload(hive_id, **overrides),
        make_beekeeper_headers(beekeeper),
    )
    return get_success_data(res)


def approve_harvest(harvest_id: str, manager: str = MANAGER_1) -> dict:
    res = api_client.approve_harvest(harvest_id, make_manager_headers(manager))
    return get_success_data(res)


def setup_hive_with_verified_inspection(
    inspection_overrides=None,
    manager: str = MANAGER_1,
    **scenario_kwargs,
) -> dict:
    """Hive scenario plus one VERIFIED inspection.

    Returns {"host", "site", "agreement", "hive", "inspection"}.
    """
    ctx = setup_hive_scenario(manager=manager, **scenario_kwargs)
    insp = create_and_verify_inspection(
        ctx["hive"]["id"], manager=manager, **(inspection_overrides or {}),
    )
    ctx["inspection"] = insp
    return ctx


def create_completed_treatment(
    hive_id: str,
    manager: str = MANAGER_1,
    beekeeper: str = BEEKEEPER_1,
    **overrides,
) -> dict:
    """Schedule -> start -> complete a treatment. Returns COMPLETED treatment."""
    treatment = get_success_data(api_client.create_treatment(
        create_treatment_payload(hive_id, **overrides),
        make_manager_headers(manager),
    ))
    get_success_data(api_client.start_treatment(
        treatment["id"], make_beekeeper_headers(beekeeper),
    ))
    return get_success_data(api_client.complete_treatment(
        treatment["id"], make_beekeeper_headers(beekeeper),
    ))


# ---------------------------------------------------------------------------
# Tier 4: subscriptions, invoices, education
# ---------------------------------------------------------------------------

def create_subscription_for(host: dict, plan: str = "BASIC") -> dict:
    """PlatformOps creates a subscription (ACTIVE; first invoice issued)."""
    res = api_client.create_subscription(
        create_subscription_payload(host["id"], plan), OPS,
    )
    return get_success_data(res)


def list_invoices_for(subscription_id: str) -> list:
    res = api_client.list_invoices(
        OPS, params={"subscription_id": subscription_id},
    )
    body = res.json()
    assert res.status_code == 200, f"Setup failed listing invoices: {res.text}"
    return body["data"]


def first_invoice_for(subscription_id: str) -> dict:
    invoices = list_invoices_for(subscription_id)
    assert invoices, "Setup failed: subscription has no invoices"
    return invoices[0]


def pay_invoice_as_host(invoice_id: str, host: dict) -> dict:
    res = api_client.pay_invoice(invoice_id, make_host_headers(host["id"]))
    return get_success_data(res)


def create_subscription_paid(host: dict, plan: str = "BASIC") -> tuple:
    """Subscription whose first invoice is PAID by the host.

    Returns (subscription, first_invoice).
    """
    sub = create_subscription_for(host, plan)
    inv = first_invoice_for(sub["id"])
    pay_invoice_as_host(inv["id"], host)
    return sub, inv


def enroll(host: dict, course_code: str) -> dict:
    res = api_client.create_enrollment(
        create_enrollment_payload(host["id"], course_code),
        make_host_headers(host["id"]),
    )
    return get_success_data(res)


def complete_enrollment(enrollment_id: str, quiz_score: int) -> dict:
    res = api_client.complete_enrollment(
        enrollment_id, {"quiz_score": quiz_score}, OPS,
    )
    return get_success_data(res)


def complete_course(host: dict, course_code: str, quiz_score: int = 90) -> dict:
    """Enroll and complete a course with a passing score. Returns enrollment."""
    enr = enroll(host, course_code)
    return complete_enrollment(enr["id"], quiz_score)


def get_host_balance(host: dict) -> int:
    host_now = get_success_data(api_client.get_host(host["id"], OPS))
    return host_now["balance_due_cents"]


# ---------------------------------------------------------------------------
# Tier 5: allocations / season settlement
# ---------------------------------------------------------------------------

def get_allocation_for(hive_id: str, season_id: str) -> dict:
    """Look up the (season, hive) HoneyAllocation via the filtered list."""
    res = api_client.list_allocations(
        OPS, params={"hive_id": hive_id, "season_id": season_id},
    )
    body = res.json()
    assert res.status_code == 200, f"Setup failed listing allocations: {res.text}"
    assert body["data"], "Setup failed: no allocation for (season, hive)"
    return body["data"][0]


def get_allocation(allocation_id: str) -> dict:
    return get_success_data(api_client.get_allocation(allocation_id, OPS))


def setup_allocation_scenario(
    plan: str = None,
    with_education: bool = False,
    base_bps: int = TEST_DEFAULTS["HOST_SHARE_BASE_BPS"],
    harvests: tuple = ((10.000, 19.6),),
    inspection_schedule=None,
    manager: str = MANAGER_1,
    beekeeper: str = BEEKEEPER_1,
) -> dict:
    """Season + host/site/agreement/hive + verified inspection(s) + harvests
    recorded and APPROVED, so the (season, hive) allocation exists (PROJECTED).

    ``harvests`` is a tuple of (gross_kg, moisture_pct) recorded on successive
    days starting 2026-06-15; one fresh verified inspection precedes each
    harvest (default healthy readings), keeping the 30-day freshness window.

    Returns {"season", "host", "site", "agreement", "hive", "subscription",
    "harvest_ids", "allocation"}.
    """
    season = create_season()
    host = create_active_host()
    if with_education:
        complete_course(host, "HOST-101")
    site = create_site_for(host)
    agreement = create_agreement_for(host, site, host_share_base_bps=base_bps)
    agreement = sign_agreement_for(agreement, host)
    subscription = None
    if plan is not None:
        subscription, _inv = create_subscription_paid(host, plan)
    hive = get_success_data(api_client.create_hive(
        create_hive_payload(site["id"], agreement["id"]),
        make_manager_headers(manager),
    ))

    harvest_ids = []
    if inspection_schedule is None:
        # Default: one verified inspection per harvest, 14 days before it.
        inspection_schedule = [None] * len(harvests)
    day = 15
    for (gross, moisture), insp_kw in zip(harvests, inspection_schedule):
        insp_kw = dict(insp_kw or {})
        # Per-harvest collected_on override (optional) — pops so it isn't
        # forwarded as an inspection field.
        collected_on = insp_kw.pop(
            "collected_on", f"2026-06-{day:02d}T00:00:00Z"
        )
        insp_overrides = {"inspected_at": f"2026-06-{day - 14:02d}T00:00:00Z"}
        insp_overrides.update(insp_kw)
        create_and_verify_inspection(
            hive["id"], beekeeper=beekeeper, manager=manager, **insp_overrides,
        )
        harv = record_harvest(
            hive["id"],
            beekeeper=beekeeper,
            collected_on=collected_on,
            gross_kg=gross,
            moisture_pct=moisture,
        )
        approve_harvest(harv["id"], manager=manager)
        harvest_ids.append(harv["id"])
        day += 1

    allocation = get_allocation_for(hive["id"], season["id"])
    return {
        "season": season,
        "host": host,
        "site": site,
        "agreement": agreement,
        "hive": hive,
        "subscription": subscription,
        "harvest_ids": harvest_ids,
        "allocation": allocation,
    }


def setup_finalized_allocation(**kwargs) -> dict:
    """Allocation scenario carried through season rollover (FINALIZED)."""
    ctx = setup_allocation_scenario(**kwargs)
    rollover_season(ctx["season"]["id"], at="2026-10-20T00:00:00Z")
    ctx["allocation"] = get_allocation(ctx["allocation"]["id"])
    return ctx


# ---------------------------------------------------------------------------
# Swarm / removal helpers
# ---------------------------------------------------------------------------

def report_swarm(host: dict, site: dict, **overrides) -> dict:
    res = api_client.create_swarm_event(
        create_swarm_event_payload(site["id"], **overrides),
        make_host_headers(host["id"]),
    )
    return get_success_data(res)


def request_removal(host: dict, hive_id: str, **overrides) -> dict:
    res = api_client.create_removal_job(
        create_removal_job_payload(hive_id, **overrides),
        make_host_headers(host["id"]),
    )
    return get_success_data(res)


def decide_removal(job_id: str, decision: str, manager: str = MANAGER_1, **overrides) -> dict:
    res = api_client.decide_removal_job(
        job_id, decide_removal_payload(decision, **overrides),
        make_manager_headers(manager),
    )
    return get_success_data(res)


def setup_approved_removal(manager: str = MANAGER_1, **scenario_kwargs) -> dict:
    """Hive scenario plus an APPROVED removal job for the hive.

    Returns scenario dict with extra key "job".
    """
    ctx = setup_hive_scenario(manager=manager, **scenario_kwargs)
    job = request_removal(ctx["host"], ctx["hive"]["id"])
    job = decide_removal(job["id"], "APPROVE", manager=manager)
    ctx["job"] = job
    return ctx
