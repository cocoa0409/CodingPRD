"""Composite setup helpers for the mass-tort claims pipeline.

Each fixture builds a named lifecycle state from scratch using only PRD-declared
endpoints (the harness restarts the server before every test, so nothing is
carried over). Setup calls use get_success_data() so setup failures surface as
clear "Setup failed" errors.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    DEFAULT_CLOCK_UTC,
    PREPARE_USER_ID,
    APPROVER_USER_ID,
    TEST_DEFAULTS,
)
from .factories import (
    create_program_payload,
    create_tier_matrix_payload,
    create_claimant_payload,
    create_claim_payload,
    create_medical_record_payload,
    create_lien_payload,
    create_appeal_payload,
    waive_lien_payload,
    appeal_rationale_payload,
)
from .test_users import TEST_USERS, make_claimant_headers, make_disbursement_approver_headers

ADMIN = TEST_USERS["program_admin_headers"]
INTAKE = TEST_USERS["intake_specialist_headers"]
RECORDS = TEST_USERS["records_analyst_headers"]
LIEN = TEST_USERS["lien_analyst_headers"]
APPROVER = TEST_USERS["disbursement_approver_headers"]


# ---------------------------------------------------------------------------
# Tier 1: single-entity creation and state progression
# ---------------------------------------------------------------------------

def create_program(qsf_principal_cents=TEST_DEFAULTS["QSF_PRINCIPAL_CENTS"], **overrides):
    """Create a settlement program. Returns the program dict (clock at default)."""
    payload = create_program_payload(qsf_principal_cents=qsf_principal_cents, **overrides)
    return get_success_data(api_client.create_program(payload, ADMIN))


def create_published_matrix(pid, **overrides):
    """Create a tier-matrix row and publish it. Returns the PUBLISHED row."""
    row = get_success_data(api_client.create_tier_matrix(pid, create_tier_matrix_payload(**overrides), ADMIN))
    return get_success_data(api_client.publish_tier_matrix(pid, row["id"], ADMIN))


def create_claimant(pid, **overrides):
    """Register a claimant under the given program."""
    return get_success_data(api_client.create_claimant(pid, create_claimant_payload(**overrides), INTAKE))


def create_submitted_claim(pid, claimant_id):
    """File a claim; it starts in SUBMITTED (PRD §3.2)."""
    return get_success_data(api_client.create_claim(pid, create_claim_payload(claimant_id), INTAKE))


def create_eligibility_passed_claim(pid, claimant_id):
    """File a claim and screen it to ELIGIBILITY_PASSED."""
    claim = create_submitted_claim(pid, claimant_id)
    return get_success_data(api_client.screen_eligibility(pid, claim["id"], INTAKE))


def create_claim_in_records_pending(pid, claimant_id, record_overrides=None):
    """ELIGIBILITY_PASSED claim + first medical-record upload -> RECORDS_PENDING."""
    claim = create_eligibility_passed_claim(pid, claimant_id)
    record = get_success_data(
        api_client.create_medical_record(pid, claim["id"], create_medical_record_payload(**(record_overrides or {})), RECORDS)
    )
    return claim["id"], record


def get_claim_version(pid, cid, headers=ADMIN) -> int:
    """Read the claim's current optimistic-concurrency version (PRD §2.6)."""
    return get_success_data(api_client.get_claim(pid, cid, headers))["version"]


# ---------------------------------------------------------------------------
# Tier 2: claim walked to INJURY_VERIFIED (records accepted + verified)
# ---------------------------------------------------------------------------

def create_injury_verified_claim(pid, claimant_id, severities=(70, 65), qualifying_index=0):
    """Claim with two uploaded records, both ACCEPTED, injury verified.

    severities: severity_score for each record; the max ACCEPTED score drives
    matrix placement (PRD §3.4). qualifying_index selects which record carries
    confirms_qualifying_injury=True.
    """
    claim = create_eligibility_passed_claim(pid, claimant_id)
    cid = claim["id"]
    record_ids = []
    for i, sev in enumerate(severities):
        rec = get_success_data(
            api_client.create_medical_record(
                pid, cid,
                create_medical_record_payload(
                    provider_name=f"Provider {i}",
                    record_type="DIAGNOSTIC" if i == qualifying_index else "TREATMENT",
                    severity_score=sev,
                    confirms_qualifying_injury=(i == qualifying_index),
                ),
                RECORDS,
            )
        )
        record_ids.append(rec["id"])
    for rid in record_ids:
        get_success_data(api_client.accept_medical_record(pid, cid, rid, RECORDS))
    claim = get_success_data(api_client.verify_injury(pid, cid, RECORDS))
    return claim, record_ids


# ---------------------------------------------------------------------------
# Tier 3: claim walked to TIER_ASSIGNED
# ---------------------------------------------------------------------------

def assign_tier_with_fresh_version(pid, cid, tmid, headers=ADMIN):
    """Assign tier, threading the current claim version for OCC (PRD §2.6)."""
    version = get_claim_version(pid, cid, headers)
    return get_success_data(
        api_client.assign_tier(pid, cid, {"tier_matrix_id": tmid, "expected_claim_version": version}, headers)
    )


def create_tier_assigned_claim(
    base_award_cents=TEST_DEFAULTS["BASE_AWARD_CENTS"],
    represented_by_counsel=False,
    severities=(70, 65),
    severity_min=0,
    severity_max=100,
    qsf_principal_cents=TEST_DEFAULTS["QSF_PRINCIPAL_CENTS"],
    injury_category="QUALIFYING_CAT_A",
    claimant_overrides=None,
):
    """Full pipeline to TIER_ASSIGNED.

    Returns dict(program, matrix, claimant, claim). gross_award_cents on the
    returned claim equals base_award_cents (PRD §3.4).
    """
    program = create_program(qsf_principal_cents=qsf_principal_cents)
    pid = program["id"]
    matrix = create_published_matrix(
        pid,
        injury_category=injury_category,
        severity_score_min=severity_min,
        severity_score_max=severity_max,
        base_award_cents=base_award_cents,
    )
    claimant = create_claimant(
        pid,
        injury_category=injury_category,
        represented_by_counsel=represented_by_counsel,
        **(claimant_overrides or {}),
    )
    claim, _records = create_injury_verified_claim(pid, claimant["id"], severities=severities)
    claim = assign_tier_with_fresh_version(pid, claim["id"], matrix["id"])
    return {"program": program, "matrix": matrix, "claimant": claimant, "claim": claim}


def create_claim_with_two_published_tiers(
    low_award=3_000_000,
    high_award=8_000_000,
    low_range=(0, 49),
    high_range=(50, 100),
    severities=(30, 25),
    represented_by_counsel=False,
):
    """TIER_ASSIGNED claim on the LOW tier with a PUBLISHED HIGH tier available
    for appeals (PRD §3.6). Claimant category QUALIFYING_CAT_A throughout.
    Returns dict(program, matrix_low, matrix_high, claimant, claim).
    """
    program = create_program()
    pid = program["id"]
    matrix_low = create_published_matrix(
        pid, severity_score_min=low_range[0], severity_score_max=low_range[1], base_award_cents=low_award
    )
    matrix_high = create_published_matrix(
        pid, severity_score_min=high_range[0], severity_score_max=high_range[1], base_award_cents=high_award
    )
    claimant = create_claimant(pid, represented_by_counsel=represented_by_counsel)
    claim, _records = create_injury_verified_claim(pid, claimant["id"], severities=severities)
    claim = assign_tier_with_fresh_version(pid, claim["id"], matrix_low["id"])
    return {
        "program": program,
        "matrix_low": matrix_low,
        "matrix_high": matrix_high,
        "claimant": claimant,
        "claim": claim,
    }


# ---------------------------------------------------------------------------
# Tier 3b: liens on a TIER_ASSIGNED claim
# ---------------------------------------------------------------------------

def add_lien(pid, cid, **overrides):
    """Identify a lien. The first lien moves the claim to LIENS_PENDING (PRD §3.5)."""
    return get_success_data(api_client.create_lien(pid, cid, create_lien_payload(**overrides), LIEN))


def add_lien_in_state(pid, cid, target_state, resolve_final_demand_cents=None, **overrides):
    """Create a lien and walk it to IDENTIFIED / NOTIFIED / IN_NEGOTIATION /
    RESOLVED / WAIVED / DISPUTED. RESOLVED uses the negotiated path unless the
    lien is still NOTIFIED and resolve_final_demand_cents is None.
    """
    lien = add_lien(pid, cid, **overrides)
    lid = lien["id"]
    if target_state == "IDENTIFIED":
        return get_success_data(api_client.get_lien(pid, cid, lid, LIEN))
    if target_state == "WAIVED":
        return get_success_data(api_client.waive_lien(pid, cid, lid, waive_lien_payload(), LIEN))
    lien = get_success_data(api_client.notify_lien(pid, cid, lid, LIEN))
    if target_state == "NOTIFIED":
        return lien
    lien = get_success_data(api_client.begin_lien_negotiation(pid, cid, lid, LIEN))
    if target_state == "IN_NEGOTIATION":
        return lien
    if target_state == "DISPUTED":
        # ClaimantRole ownership is checked against the claim's claimant_id.
        claim = get_success_data(api_client.get_claim(pid, cid, ADMIN))
        return get_success_data(
            api_client.dispute_lien(pid, cid, lid, make_claimant_headers(claim["claimant_id"]))
        )
    if target_state == "RESOLVED":
        version = get_claim_version(pid, cid, LIEN)
        payload = {"expected_claim_version": version}
        if resolve_final_demand_cents is not None:
            payload["final_demand_cents"] = resolve_final_demand_cents
        return get_success_data(api_client.resolve_lien(pid, cid, lid, payload, LIEN))
    raise ValueError(f"Unsupported lien target_state: {target_state}")


def create_claim_in_liens_pending(**kwargs):
    """TIER_ASSIGNED claim plus one identified lien -> claim is LIENS_PENDING.
    Returns dict from create_tier_assigned_claim plus 'lien'.

    Lien-creation fields (lien_type, holder_name, asserted_amount_cents —
    PRD §3.5) are routed to the lien identify call; every other kwarg
    configures the claim pipeline via create_tier_assigned_claim.
    """
    lien_overrides = {
        k: kwargs.pop(k)
        for k in ("lien_type", "holder_name", "asserted_amount_cents")
        if k in kwargs
    }
    ctx = create_tier_assigned_claim(**kwargs)
    lien = add_lien(ctx["program"]["id"], ctx["claim"]["id"], **lien_overrides)
    ctx["lien"] = lien
    ctx["claim"] = get_success_data(api_client.get_claim(ctx["program"]["id"], ctx["claim"]["id"], ADMIN))
    return ctx


# ---------------------------------------------------------------------------
# Tier 4: claim walked to LIENS_RESOLVED and READY_FOR_DISBURSEMENT
# ---------------------------------------------------------------------------

def create_liens_resolved_claim(lien_action="waive", resolve_final_demand_cents=None, **kwargs):
    """Claim in LIENS_RESOLVED with a single lien dispositioned.

    lien_action: "waive" (final_demand 0) or "resolve" (negotiated path with
    resolve_final_demand_cents, defaulting to the asserted amount).
    Returns ctx dict with keys program, matrix, claimant, claim, lien.
    """
    ctx = create_claim_in_liens_pending(**kwargs)
    pid, cid, lid = ctx["program"]["id"], ctx["claim"]["id"], ctx["lien"]["id"]
    if lien_action == "waive":
        lien = get_success_data(api_client.waive_lien(pid, cid, lid, waive_lien_payload(), LIEN))
    else:
        get_success_data(api_client.notify_lien(pid, cid, lid, LIEN))
        get_success_data(api_client.begin_lien_negotiation(pid, cid, lid, LIEN))
        version = get_claim_version(pid, cid, LIEN)
        final = resolve_final_demand_cents
        if final is None:
            final = ctx["lien"]["asserted_amount_cents"]
        lien = get_success_data(
            api_client.resolve_lien(pid, cid, lid, {"expected_claim_version": version, "final_demand_cents": final}, LIEN)
        )
    claim = get_success_data(api_client.finalize_liens(pid, cid, LIEN))
    ctx["lien"] = lien
    ctx["claim"] = claim
    return ctx


def create_ready_for_disbursement_claim(prepare_user_id=PREPARE_USER_ID, **kwargs):
    """Claim in READY_FOR_DISBURSEMENT with spawned PENDING disbursements.

    Returns ctx dict with keys program, matrix, claimant, claim, lien,
    disbursements (list, in waterfall creation order), prepare_user_id.
    """
    ctx = create_liens_resolved_claim(**kwargs)
    pid, cid = ctx["program"]["id"], ctx["claim"]["id"]
    claim = get_success_data(
        api_client.prepare_disbursement(pid, cid, make_disbursement_approver_headers(prepare_user_id))
    )
    disbursements, _meta = _list_all_disbursements(pid, cid)
    ctx["claim"] = claim
    ctx["disbursements"] = disbursements
    ctx["prepare_user_id"] = prepare_user_id
    return ctx


def _list_all_disbursements(pid, cid):
    resp = api_client.list_disbursements(pid, cid, make_disbursement_approver_headers(APPROVER_USER_ID))
    body = resp.json()
    assert resp.status_code == 200, f"Setup failed listing disbursements: HTTP {resp.status_code}"
    assert isinstance(body.get("data"), list), "Setup failed: disbursement list response data is not a list"
    return body["data"], body.get("meta", {})


# ---------------------------------------------------------------------------
# Tier 5: terminal states — DISBURSED and CLOSED
# ---------------------------------------------------------------------------

def create_disbursed_claim(prepare_user_id=PREPARE_USER_ID, approver_user_id=APPROVER_USER_ID, **kwargs):
    """Full lifecycle to DISBURSED: every disbursement approved (by a user other
    than the prepare caller, per PRD §2.10) and released.
    Returns ctx dict with claim in DISBURSED and disbursements list.
    """
    ctx = create_ready_for_disbursement_claim(prepare_user_id=prepare_user_id, **kwargs)
    pid, cid = ctx["program"]["id"], ctx["claim"]["id"]
    approver_headers = make_disbursement_approver_headers(approver_user_id)
    released = []
    for d in ctx["disbursements"]:
        get_success_data(api_client.approve_disbursement(pid, cid, d["id"], approver_headers))
        released.append(get_success_data(api_client.release_disbursement(pid, cid, d["id"], approver_headers)))
    ctx["disbursements"] = released
    ctx["claim"] = get_success_data(api_client.get_claim(pid, cid, ADMIN))
    ctx["approver_user_id"] = approver_user_id
    return ctx


def create_closed_claim(**kwargs):
    """Full lifecycle to CLOSED; seals the immutable closing statement (PRD §3.8)."""
    ctx = create_disbursed_claim(**kwargs)
    pid, cid = ctx["program"]["id"], ctx["claim"]["id"]
    ctx["claim"] = get_success_data(api_client.close_claim(pid, cid, ADMIN))
    return ctx


# ---------------------------------------------------------------------------
# Appeals
# ---------------------------------------------------------------------------

def file_appeal(pid, cid, claimant_id, appealed_tmid, requested_tmid, **overrides):
    """File an appeal as the owning claimant (PRD §3.6). Returns the FILED appeal."""
    payload = create_appeal_payload(appealed_tmid, requested_tmid, **overrides)
    return get_success_data(api_client.create_appeal(pid, cid, payload, make_claimant_headers(claimant_id)))


def create_claim_with_open_appeal(**kwargs):
    """TIER_ASSIGNED claim with one appeal in FILED state and active_appeal_id set.
    Returns ctx dict with keys program, matrix_low, matrix_high, claimant, claim, appeal.
    """
    ctx = create_claim_with_two_published_tiers(**kwargs)
    pid, cid = ctx["program"]["id"], ctx["claim"]["id"]
    appeal = file_appeal(pid, cid, ctx["claimant"]["id"], ctx["matrix_low"]["id"], ctx["matrix_high"]["id"])
    ctx["appeal"] = appeal
    ctx["claim"] = get_success_data(api_client.get_claim(pid, cid, ADMIN))
    return ctx


def create_claim_with_appeal_under_review(**kwargs):
    """TIER_ASSIGNED claim with an appeal advanced to UNDER_REVIEW."""
    ctx = create_claim_with_open_appeal(**kwargs)
    pid, cid, aid = ctx["program"]["id"], ctx["claim"]["id"], ctx["appeal"]["id"]
    ctx["appeal"] = get_success_data(api_client.begin_appeal_review(pid, cid, aid, ADMIN))
    return ctx
