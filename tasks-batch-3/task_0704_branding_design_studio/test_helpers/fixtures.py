"""Composite setup helpers.

Each helper builds a multi-step precondition state from scratch using only
PRD-declared endpoints, so a test can focus on its assertion. Setup calls use
get_success_data() (lenient) so a setup failure surfaces clearly.

The harness restarts the server (empty DB) before every test, so every helper
starts from nothing: it creates its own studio, client, project, etc.

Identity threading: the Client role is entity-backed. After a fixture creates a
Client, every ownership-gated Client call (moodboard/concept/deliverable/
change-order approve/reject/request-revision/accept) uses
make_client_headers(client["id"]) — never the shared Client constant.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import TEST_USERS, make_client_headers
from .factories import (
    create_studio_payload,
    create_client_payload,
    create_project_payload,
    create_moodboard_payload,
    create_concept_payload,
    create_milestone_payload,
    create_invoice_payload,
    create_deliverable_payload,
    create_license_payload,
    create_change_order_payload,
    create_retainer_payload,
    create_care_cycle_payload,
)

SO = TEST_USERS["studio_ops_headers"]
DES = TEST_USERS["designer_headers"]
BO = TEST_USERS["billing_ops_headers"]


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------
def set_clock(iso: str, headers=None):
    return get_success_data(api_client.set_clock(iso, headers or BO))


# ---------------------------------------------------------------------------
# Tier 0: base entities
# ---------------------------------------------------------------------------
def create_studio(**overrides) -> dict:
    return get_success_data(api_client.create_studio(create_studio_payload(**overrides), SO))


def create_active_client(studio_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_client(studio_id, create_client_payload(**overrides), SO)
    )


def create_draft_project(studio_id, client_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_project(studio_id, create_project_payload(client_id, **overrides), SO)
    )


def add_milestone(studio_id, project_id, amount_cents, sequence_index, **overrides) -> dict:
    return get_success_data(
        api_client.create_milestone(
            studio_id, project_id,
            create_milestone_payload(amount_cents, sequence_index, **overrides),
            SO,
        )
    )


# ---------------------------------------------------------------------------
# Tier 1 / 2: Project state progression
# ---------------------------------------------------------------------------
def setup_studio_client(tax_rate=0.0, license_markup_pct=0.0, studio_name="Studio"):
    """Create a studio (tax_rate/markup configurable) and an ACTIVE client.
    Returns (studio, client)."""
    studio = create_studio(name=studio_name, tax_rate=tax_rate, license_markup_pct=license_markup_pct)
    client = create_active_client(studio["id"])
    return studio, client


def setup_draft_project_with_milestones(
    milestone_amounts, deposit_pct=0.30, service_type="LOGO",
    tax_rate=0.0, license_markup_pct=0.0,
):
    """Studio + ACTIVE client + DRAFT project with one milestone per amount in
    milestone_amounts (sequence_index 1..N). Returns (studio, client, project,
    [milestones])."""
    studio, client = setup_studio_client(tax_rate=tax_rate, license_markup_pct=license_markup_pct)
    project = create_draft_project(
        studio["id"], client["id"], deposit_pct=deposit_pct, service_type=service_type
    )
    milestones = [
        add_milestone(studio["id"], project["id"], amt, idx + 1)
        for idx, amt in enumerate(milestone_amounts)
    ]
    return studio, client, project, milestones


def create_and_activate_project(
    milestone_amounts, deposit_pct=0.30, service_type="LOGO",
    tax_rate=0.0, license_markup_pct=0.0, deposit_cents=0,
):
    """Studio + client + project + milestones, optionally a deposit, then
    activate to DISCOVERY. Returns (studio, client, project_after_activate,
    [milestones])."""
    studio, client, project, milestones = setup_draft_project_with_milestones(
        milestone_amounts, deposit_pct=deposit_pct, service_type=service_type,
        tax_rate=tax_rate, license_markup_pct=license_markup_pct,
    )
    if deposit_cents:
        get_success_data(
            api_client.record_deposit(studio["id"], project["id"], {"amount_cents": deposit_cents}, BO)
        )
    project = get_success_data(api_client.activate_project(studio["id"], project["id"], SO))
    return studio, client, project, milestones


def _approve_moodboard(studio_id, project_id, client_id):
    mb = get_success_data(
        api_client.create_moodboard(studio_id, project_id, create_moodboard_payload(), DES)
    )
    get_success_data(api_client.submit_moodboard(studio_id, project_id, mb["id"], DES))
    get_success_data(
        api_client.approve_moodboard(studio_id, project_id, mb["id"], make_client_headers(client_id))
    )
    return mb


def create_project_in_concept(
    milestone_amounts, deposit_pct=0.30, service_type="LOGO",
    tax_rate=0.0, license_markup_pct=0.0, deposit_cents=0,
):
    """Activate a project, approve a moodboard, advance DISCOVERY->CONCEPT.
    Returns (studio, client, project_in_concept, [milestones])."""
    studio, client, project, milestones = create_and_activate_project(
        milestone_amounts, deposit_pct=deposit_pct, service_type=service_type,
        tax_rate=tax_rate, license_markup_pct=license_markup_pct, deposit_cents=deposit_cents,
    )
    _approve_moodboard(studio["id"], project["id"], client["id"])
    project = get_success_data(api_client.advance_project(studio["id"], project["id"], SO))
    return studio, client, project, milestones


def create_presented_concept(studio_id, project_id, client_id, **concept_overrides):
    """In a CONCEPT-stage project, create + present a concept. Returns the
    PRESENTED concept dict."""
    con = get_success_data(
        api_client.create_concept(studio_id, project_id, create_concept_payload(**concept_overrides), DES)
    )
    con = get_success_data(api_client.present_concept(studio_id, project_id, con["id"], DES))
    return con


def create_project_in_delivery(
    milestone_amounts, deposit_pct=0.30, service_type="LOGO",
    tax_rate=0.0, license_markup_pct=0.0, deposit_cents=0,
):
    """Project through CONCEPT, approve a concept, advance CONCEPT->DELIVERY.
    Returns (studio, client, project_in_delivery, [milestones])."""
    studio, client, project, milestones = create_project_in_concept(
        milestone_amounts, deposit_pct=deposit_pct, service_type=service_type,
        tax_rate=tax_rate, license_markup_pct=license_markup_pct, deposit_cents=deposit_cents,
    )
    con = get_success_data(
        api_client.create_concept(studio["id"], project["id"], create_concept_payload(), DES)
    )
    get_success_data(api_client.present_concept(studio["id"], project["id"], con["id"], DES))
    get_success_data(
        api_client.approve_concept(studio["id"], project["id"], con["id"], make_client_headers(client["id"]))
    )
    project = get_success_data(api_client.advance_project(studio["id"], project["id"], SO))
    return studio, client, project, milestones


def create_project_in_handoff(
    milestone_amounts, deposit_pct=0.0, service_type="LOGO",
    tax_rate=0.0, deposit_cents=0, asset_type="BRAND_GUIDE",
):
    """Project in DELIVERY + one required deliverable ACCEPTED + deposit covered,
    then advance DELIVERY->HANDOFF. Returns (studio, client, project_in_handoff,
    [milestones], deliverable)."""
    studio, client, project, milestones = create_project_in_delivery(
        milestone_amounts, deposit_pct=deposit_pct, service_type=service_type,
        tax_rate=tax_rate, deposit_cents=deposit_cents,
    )
    deliverable = get_success_data(
        api_client.create_deliverable(
            studio["id"], project["id"],
            create_deliverable_payload(asset_type, is_required_for_handoff=True), DES,
        )
    )
    get_success_data(api_client.deliver_deliverable(studio["id"], project["id"], deliverable["id"], DES))
    get_success_data(
        api_client.accept_deliverable(
            studio["id"], project["id"], deliverable["id"], make_client_headers(client["id"])
        )
    )
    project = get_success_data(api_client.advance_project(studio["id"], project["id"], SO))
    return studio, client, project, milestones, deliverable


# ---------------------------------------------------------------------------
# Tier 3: Invoice lifecycle shortcuts
# ---------------------------------------------------------------------------
def issue_invoice(studio_id, milestone_id, due_date="2026-04-01T00:00:00Z"):
    return get_success_data(
        api_client.create_invoice(studio_id, create_invoice_payload(milestone_id, due_date), BO)
    )


def setup_project_with_issued_invoice(
    amount_cents=40000, deposit_pct=0.0, tax_rate=0.0, deposit_cents=0,
    due_date="2026-04-01T00:00:00Z",
):
    """Project in DELIVERY with a single milestone of amount_cents and one ISSUED
    invoice on it. Returns (studio, client, project, milestone, invoice)."""
    studio, client, project, milestones = create_project_in_delivery(
        [amount_cents], deposit_pct=deposit_pct, tax_rate=tax_rate, deposit_cents=deposit_cents,
    )
    milestone = milestones[0]
    invoice = issue_invoice(studio["id"], milestone["id"], due_date)
    return studio, client, project, milestone, invoice


# ---------------------------------------------------------------------------
# Tier 4: Change-order helpers
# ---------------------------------------------------------------------------
def propose_change_order(studio_id, project_id, delta_cents, expected_project_version, **overrides):
    return get_success_data(
        api_client.create_change_order(
            studio_id,
            create_change_order_payload(project_id, delta_cents, expected_project_version, **overrides),
            SO,
        )
    )


def approve_change_order(studio_id, change_order_id, client_id):
    return get_success_data(
        api_client.approve_change_order(studio_id, change_order_id, make_client_headers(client_id))
    )


# ---------------------------------------------------------------------------
# Tier 5: Retainer / care-cycle helpers
# ---------------------------------------------------------------------------
def create_active_retainer(
    studio_id=None, client_id=None, monthly_fee_cents=100000, included_hours=10,
    tier1_rate_cents=5000, tier2_rate_cents=8000,
):
    """Create a studio+client (unless provided) and an ACTIVE retainer.
    Returns (studio_id, client_id, retainer)."""
    if studio_id is None or client_id is None:
        studio = create_studio()
        client = create_active_client(studio["id"])
        studio_id, client_id = studio["id"], client["id"]
    retainer = get_success_data(
        api_client.create_retainer(
            studio_id,
            create_retainer_payload(
                client_id, monthly_fee_cents=monthly_fee_cents, included_hours=included_hours,
                tier1_rate_cents=tier1_rate_cents, tier2_rate_cents=tier2_rate_cents,
            ),
            SO,
        )
    )
    return studio_id, client_id, retainer


def open_care_cycle(studio_id, retainer_id, period_start, period_end, hours_used=0):
    return get_success_data(
        api_client.create_care_cycle(
            studio_id, retainer_id,
            create_care_cycle_payload(period_start, period_end, hours_used=hours_used),
            SO,
        )
    )


def setup_open_care_cycle(
    monthly_fee_cents=100000, included_hours=10, tier1_rate_cents=5000, tier2_rate_cents=8000,
    period_start="2026-03-01T00:00:00Z", period_end="2026-04-01T00:00:00Z",
    hours_used=0, clock_start="2026-03-01T00:00:00Z",
):
    """Set the clock, create an ACTIVE retainer, and open one care cycle.
    Returns (studio_id, retainer, care_cycle)."""
    set_clock(clock_start, SO)
    studio_id, client_id, retainer = create_active_retainer(
        monthly_fee_cents=monthly_fee_cents, included_hours=included_hours,
        tier1_rate_cents=tier1_rate_cents, tier2_rate_cents=tier2_rate_cents,
    )
    cc = open_care_cycle(studio_id, retainer["id"], period_start, period_end, hours_used=hours_used)
    return studio_id, retainer, cc


def setup_closed_care_cycle(
    monthly_fee_cents=100000, included_hours=10, tier1_rate_cents=5000, tier2_rate_cents=8000,
    period_start="2026-03-01T00:00:00Z", period_end="2026-04-01T00:00:00Z", hours_used=0,
):
    """Open a care cycle then advance the clock to period_end and close it.
    Returns (studio_id, retainer, closed_care_cycle)."""
    studio_id, retainer, cc = setup_open_care_cycle(
        monthly_fee_cents=monthly_fee_cents, included_hours=included_hours,
        tier1_rate_cents=tier1_rate_cents, tier2_rate_cents=tier2_rate_cents,
        period_start=period_start, period_end=period_end, hours_used=hours_used,
    )
    set_clock(period_end, SO)
    cc = get_success_data(api_client.close_care_cycle(studio_id, retainer["id"], cc["id"], SO))
    return studio_id, retainer, cc
