"""Composite setup helpers.

Every test starts against an empty database (the harness restarts the server
before each test), so these helpers build complete precondition chains out of
PRD-declared endpoints only.

Identity threading: ArtistPortal calls are entity-backed by Artist. Whenever a
fixture submits an ArtistPortal call against an owned resource (counter a memo,
submit a tour expense, dispute or read a statement), it MUST use
make_artist_portal_headers(artist["id"]) — never the shared constant. The
same applies to segregation-of-duties tours: approve and advance-funds must be
called with two DIFFERENT operator ids, so fixtures build per-instance opaque
headers with explicit user ids rather than the shared constants.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .constants import DEFAULT_CLOCK_ISO
from .factories import (
    create_artist_payload,
    create_beat_payload,
    create_deal_memo_payload,
    create_distributor_payload,
    create_label_payload,
    create_milestone_payload,
    create_promo_campaign_payload,
    create_recording_project_payload,
    create_release_payload,
    create_revenue_report_payload,
    create_royalty_run_payload,
    create_tour_expense_payload,
    create_tour_support_payload,
    create_track_payload,
)
from .test_users import (
    TEST_USERS,
    make_artist_portal_headers,
    make_finance_headers,
    make_label_admin_headers,
)

ADMIN = TEST_USERS["label_admin_headers"]
ANR = TEST_USERS["anr_manager_headers"]
FIN = TEST_USERS["finance_headers"]
MKT = TEST_USERS["marketing_headers"]


# ---------------------------------------------------------------------------
# Tier 1: single-resource creation
# ---------------------------------------------------------------------------


def create_label(name="Test Label", **overrides):
    return get_success_data(api_client.create_label(create_label_payload(name=name, **overrides), ADMIN))


def create_artist(label_id, stage_name="Test Act", **overrides):
    payload = create_artist_payload(label_id, stage_name=stage_name, **overrides)
    return get_success_data(api_client.create_artist(payload, ANR))


def create_draft_memo(artist_id, **overrides):
    """Create a DRAFT deal memo. Returns the memo."""
    return get_success_data(api_client.create_deal_memo(artist_id, create_deal_memo_payload(**overrides), ANR))


def create_distributor(label_id, name="DSP-1", channel_type="DSP", is_active=None):
    payload = create_distributor_payload(label_id, name=name, channel_type=channel_type)
    if is_active is not None:
        payload["is_active"] = is_active
    return get_success_data(api_client.create_distributor(payload, ADMIN))


def set_clock(iso8601=DEFAULT_CLOCK_ISO):
    return get_success_data(api_client.set_clock({"to_iso8601": iso8601}, ADMIN))


def sweep_label(label_id):
    return get_success_data(api_client.sweep_label(label_id, ADMIN))


# ---------------------------------------------------------------------------
# Tier 2: memo -> contract chains
# ---------------------------------------------------------------------------


def sign_artist_via_memo(artist_id, advance_cents=0, base_royalty_rate_bps=2_000,
                         recoupment_scope="MASTER_ONLY", promo_costs_recoupable=False,
                         options_total=0, option_term_months=12, option_escalation_bps=0,
                         term_months=12, valid_until_date="2028-01-01",
                         guardian_name=None, guardian_email=None):
    """Draft -> propose -> approve -> execute. Returns (memo_after_execute_get, contract)."""
    memo = create_draft_memo(
        artist_id,
        advance_cents=advance_cents,
        base_royalty_rate_bps=base_royalty_rate_bps,
        recoupment_scope=recoupment_scope,
        promo_costs_recoupable=promo_costs_recoupable,
        options_total=options_total,
        option_term_months=option_term_months,
        option_escalation_bps=option_escalation_bps,
        term_months=term_months,
        valid_until_date=valid_until_date,
        guardian_name=guardian_name,
        guardian_email=guardian_email,
    )
    get_success_data(api_client.propose_deal_memo(memo["id"], ANR))
    get_success_data(api_client.approve_deal_memo(memo["id"], ADMIN))
    contract = get_success_data(api_client.execute_deal_memo(memo["id"], ADMIN))
    memo_after = get_success_data(api_client.get_deal_memo(memo["id"], ADMIN))
    return memo_after, contract


def setup_label_with_signed_artist(label_name="Label", stage_name="Artist",
                                   advance_cents=0, memo_overrides=None, artist_overrides=None):
    """Returns (label, artist_after_sign, memo, contract)."""
    label = create_label(label_name)
    artist = create_artist(label["id"], stage_name, **(artist_overrides or {}))
    memo, contract = sign_artist_via_memo(artist["id"], advance_cents=advance_cents,
                                          **(memo_overrides or {}))
    artist_after = get_success_data(api_client.get_artist(artist["id"], ADMIN))
    return label, artist_after, memo, contract


def disburse_advance(contract_id):
    """Fund a contract's advance. Returns the contract."""
    return get_success_data(api_client.disburse_advance(contract_id, FIN))


def get_recoupment_account(contract_id):
    """Reverse-lookup the (single) RecoupmentAccount for a contract."""
    data, _meta = validate_paginated(api_client.list_contract_recoupment_accounts(contract_id, FIN))
    assert len(data) == 1, "expected exactly one recoupment account per contract"
    return data[0]


# ---------------------------------------------------------------------------
# Tier 3: recording-project / track helpers
# ---------------------------------------------------------------------------


def create_and_start_project(contract_id, title="P-1", project_type="SINGLE",
                             budget_cents=100_000):
    """Create + start a recording project. Returns the project (status RECORDING)."""
    project = get_success_data(api_client.create_recording_project(
        contract_id,
        create_recording_project_payload(title=title, project_type=project_type,
                                         budget_cents=budget_cents),
        ANR,
    ))
    return get_success_data(api_client.start_project(project["id"], ANR))


def add_track(project_id, title="T1", isrc="USRC10000001", duration_seconds=200,
              advance_to=None, contains_sample=None, clearance_ref=None,
              version_of_track_id=None):
    """Create a track. Optionally advance to one of TRACKED/MIXED/MASTERED/CLEARED."""
    overrides = {"title": title, "duration_seconds": duration_seconds, "isrc": isrc}
    if contains_sample is not None:
        overrides["contains_sample"] = contains_sample
    if clearance_ref is not None:
        overrides["clearance_ref"] = clearance_ref
    if version_of_track_id is not None:
        overrides["version_of_track_id"] = version_of_track_id
    track = get_success_data(api_client.create_track(project_id, create_track_payload(**overrides), ANR))
    if advance_to:
        order = ["TRACKED", "MIXED", "MASTERED", "CLEARED"]
        assert advance_to in order, f"unknown advance_to target: {advance_to}"
        # PRD §3.4: advancing walks the track one step at a time, so loop until
        # the target stage is actually reached.
        while track["status"] != advance_to:
            track = get_success_data(api_client.advance_track_stage(track["id"], ANR))
    return track


def add_milestone(project_id, name="M1", sequence=1, due_date="2026-09-01",
                  payment_cents=1_000):
    """Create a PENDING milestone."""
    return get_success_data(api_client.create_milestone(
        project_id,
        create_milestone_payload(name=name, sequence=sequence, due_date=due_date,
                                 payment_cents=payment_cents),
        ANR,
    ))


def approve_milestone(milestone_id, admin_user_id=None):
    headers = make_label_admin_headers(admin_user_id) if admin_user_id else ADMIN
    return get_success_data(api_client.approve_milestone(milestone_id, headers))


def submit_and_approve_milestone(milestone_id, admin_user_id=None):
    get_success_data(api_client.submit_milestone(milestone_id, {}, ANR))
    return approve_milestone(milestone_id, admin_user_id=admin_user_id)


def pay_milestone(milestone_id):
    return get_success_data(api_client.pay_milestone(milestone_id, FIN))


def submit_approve_pay_milestone(milestone_id, admin_user_id=None):
    submit_and_approve_milestone(milestone_id, admin_user_id=admin_user_id)
    return pay_milestone(milestone_id)


# ---------------------------------------------------------------------------
# Tier 4: release pipeline
# ---------------------------------------------------------------------------


def create_release(contract_id, project_id, track_ids, release_type="SINGLE",
                   release_date="2026-09-01", title="R-1"):
    return get_success_data(api_client.create_release(
        contract_id,
        create_release_payload(project_id, track_ids, release_type=release_type,
                               release_date=release_date, title=title),
        ANR,
    ))


def assemble_and_lock_release(release_id):
    get_success_data(api_client.assemble_release(release_id, ANR))
    return get_success_data(api_client.lock_release_assets(
        release_id, {"cover_art_confirmed": True}, ANR))


def schedule_release(release_id):
    return get_success_data(api_client.schedule_release(release_id, MKT))


def deliver_release(release_id, distributor_ids):
    """Create + transmit + acknowledge deliveries. Bubbles release to DELIVERED."""
    deliveries = get_success_data(api_client.create_release_deliveries(
        release_id, {"distributor_ids": list(distributor_ids)}, MKT))
    out = []
    for d in deliveries:
        d = get_success_data(api_client.transmit_delivery(d["id"], MKT))
        d = get_success_data(api_client.acknowledge_delivery(d["id"], MKT))
        out.append(d)
    return out


def go_live_release(release_id, clock_iso):
    """Advance the clock and go live. Returns the LIVE release."""
    set_clock(clock_iso)
    return get_success_data(api_client.go_live_release(release_id, MKT))


def setup_live_single_release(label_name="Label", artist_name="Artist",
                              advance_cents=0, memo_overrides=None,
                              release_date="2026-09-01",
                              track_isrc="USRC10000001",
                              go_live_clock="2026-09-01T00:00:00Z",
                              distributor_name="DSP-1"):
    """Full pipeline: label -> artist -> contract (advance disbursed if > 0) ->
    project started -> one CLEARED track -> SINGLE release LOCKED -> SCHEDULED
    -> one ACKNOWLEDGED delivery -> clock to release date -> LIVE.

    Returns a dict with the world state:
        label, artist, memo, contract, project, track, release (final LIVE),
        distributor, deliveries (list of acknowledged deliveries), account.
    """
    memo_kw = memo_overrides or {}
    label = create_label(label_name)
    artist = create_artist(label["id"], artist_name)
    memo, contract = sign_artist_via_memo(artist["id"], advance_cents=advance_cents, **memo_kw)
    if advance_cents:
        disburse_advance(contract["id"])
    project = create_and_start_project(contract["id"], title=f"P-{label_name}")
    track = add_track(project["id"], isrc=track_isrc, advance_to="CLEARED")
    release = create_release(contract["id"], project["id"], [track["id"]],
                             release_date=release_date)
    assemble_and_lock_release(release["id"])
    schedule_release(release["id"])
    distributor = create_distributor(label["id"], name=distributor_name)
    deliveries = deliver_release(release["id"], [distributor["id"]])
    release_live = go_live_release(release["id"], go_live_clock)
    account = get_recoupment_account(contract["id"])
    return {
        "label": label,
        "artist": get_success_data(api_client.get_artist(artist["id"], ADMIN)),
        "memo": memo,
        "contract": contract,
        "project": project,
        "track": track,
        "release": release_live,
        "distributor": distributor,
        "deliveries": deliveries,
        "account": account,
    }


# ---------------------------------------------------------------------------
# Tier 5: royalty runs / statements
# ---------------------------------------------------------------------------


def add_revenue_report(label_id, distributor_id, release_id, period="2026-Q3",
                       channel="STREAMING", units=100, gross_revenue_cents=1_000,
                       note=None):
    payload = create_revenue_report_payload(
        label_id, distributor_id, release_id,
        period=period, channel=channel, units=units,
        gross_revenue_cents=gross_revenue_cents, note=note,
    )
    return get_success_data(api_client.create_revenue_report(payload, FIN))


def open_close_calculate_run(label_id, period):
    """Create + close + calculate a royalty run. Returns the CALCULATED run."""
    run = get_success_data(api_client.create_royalty_run(
        create_royalty_run_payload(label_id, period=period), FIN))
    get_success_data(api_client.close_royalty_run(run["id"], FIN))
    return get_success_data(api_client.calculate_royalty_run(run["id"], FIN))


def finalize_run(run_id):
    return get_success_data(api_client.finalize_royalty_run(run_id, FIN))


def list_run_statements(run_id):
    data, _meta = validate_paginated(api_client.list_run_statements(run_id, FIN))
    return data


def get_run_statement(run_id, contract_id=None):
    """Single-statement helper: returns the run's statement (optionally for a contract)."""
    stmts = list_run_statements(run_id)
    if contract_id is not None:
        stmts = [s for s in stmts if s["contract_id"] == contract_id]
    assert len(stmts) == 1, f"expected 1 statement, got {len(stmts)}"
    return stmts[0]


# ---------------------------------------------------------------------------
# Tier 6: tour support helpers
# ---------------------------------------------------------------------------


def setup_approved_tour_support(contract_id, tour_name="Tour",
                                requested_amount_cents=24_000,
                                approved_budget_cents=None,
                                approver_user_id="admin-1"):
    """PROPOSED -> APPROVED. Returns the APPROVED tour support."""
    ts = get_success_data(api_client.create_tour_support(
        contract_id,
        create_tour_support_payload(tour_name=tour_name,
                                    requested_amount_cents=requested_amount_cents),
        ANR,
    ))
    budget = approved_budget_cents if approved_budget_cents is not None else requested_amount_cents
    return get_success_data(api_client.approve_tour_support(
        ts["id"], {"approved_budget_cents": budget},
        make_label_admin_headers(approver_user_id)))


def advance_tour_funds(tour_support_id, amount_cents, funder_user_id="fin-1"):
    """ADVANCED. Caller differs from approver (segregation of duties)."""
    return get_success_data(api_client.advance_funds_tour_support(
        tour_support_id, {"amount_cents": amount_cents},
        make_finance_headers(funder_user_id)))


def submit_tour_expense(tour_support_id, artist_id, category="TRAVEL",
                        amount_cents=1_000, expense_date="2026-09-10"):
    """Artist submits an expense on their own tour (entity-backed identity)."""
    return get_success_data(api_client.create_tour_expense(
        tour_support_id,
        create_tour_expense_payload(category=category, amount_cents=amount_cents,
                                    expense_date=expense_date),
        make_artist_portal_headers(artist_id),
    ))


def approve_tour_expense(expense_id, finance_user_id=None):
    headers = make_finance_headers(finance_user_id) if finance_user_id else FIN
    return get_success_data(api_client.approve_tour_expense(expense_id, headers))


def setup_advanced_tour_support(contract_id, artist_id, tour_name="Tour",
                                requested_amount_cents=24_000,
                                approved_budget_cents=None,
                                advance_amount_cents=12_000,
                                approver_user_id="admin-1",
                                funder_user_id="fin-1"):
    """PROPOSED -> APPROVED -> ADVANCED. Returns the ADVANCED tour support."""
    ts = setup_approved_tour_support(
        contract_id, tour_name=tour_name,
        requested_amount_cents=requested_amount_cents,
        approved_budget_cents=approved_budget_cents,
        approver_user_id=approver_user_id,
    )
    return advance_tour_funds(ts["id"], advance_amount_cents,
                              funder_user_id=funder_user_id)
