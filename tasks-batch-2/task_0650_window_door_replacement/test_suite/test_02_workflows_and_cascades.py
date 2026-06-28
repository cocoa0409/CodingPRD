"""State-machine workflows, revision cycles, and multi-hop cascades:
quote revision loop, service-ticket reopen cycle, accept production cascade,
project-cancel cascade, referral settlement.
"""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    factories as F,
    fixtures as FX,
    ApiErrorId,
    TEST_USERS,
    make_homeowner_headers,
)

SALES = TEST_USERS["sales_consultant_headers"]
OPS = TEST_USERS["operations_coordinator_headers"]
TECH = TEST_USERS["service_tech_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]


# ---------------------------------------------------------------------------
# Quote revision loop and service-ticket repair cycle
# ---------------------------------------------------------------------------

def test_quote_reject_then_revision_draft_cycle(api):
    """PRD §3.4: "The reverse fork is rejection: a `Homeowner` rejects a `SENT`
    quote, moving it to `REJECTED`."
    PRD §3.3: "To re-quote after a rejection, the consultant may pass an optional
    `supersede_quote_id` referencing a previously rejected quote; this creates a
    brand-new `DRAFT` quote as a revision while leaving the prior `REJECTED`
    quote untouched."

    Design: Difficulty/non_linear_state_machine/quote_reject_then_revision_draft_cycle
    """
    base = FX.setup_sent_quote(api)
    pid, qid, ho_id = base["project"]["id"], base["quote"]["id"], base["homeowner"]["id"]
    rejected = validate_success(api.reject_quote(pid, qid, make_homeowner_headers(ho_id)), 200)
    assert rejected["status"] == "REJECTED", rejected["status"]
    revision = validate_success(
        api.create_quote(pid, F.create_quote_payload(pid, base["consultation"]["id"], supersede_quote_id=qid), SALES),
        201,
    )
    assert revision["status"] == "DRAFT", revision["status"]


def test_quote_reject_leaves_prior_quote_unchanged(api):
    """PRD §3.4: "A `REJECTED` quote is the entry point for the revision loop
    described above: a new `DRAFT` is created from it, and the rejected quote
    itself is left unchanged."

    Design: Difficulty/non_linear_state_machine/quote_reject_then_revision_draft_cycle
    """
    base = FX.setup_sent_quote(api)
    pid, qid, ho_id = base["project"]["id"], base["quote"]["id"], base["homeowner"]["id"]
    get_success_data(api.reject_quote(pid, qid, make_homeowner_headers(ho_id)))
    get_success_data(api.create_quote(pid, F.create_quote_payload(pid, base["consultation"]["id"], supersede_quote_id=qid), SALES))
    prior = validate_success(api.get_quote_nested(pid, qid, SALES), 200)
    assert prior["status"] == "REJECTED", prior["status"]


def test_service_ticket_resolved_reopen_redispatch_cycle(api):
    """PRD §3.9: "A `Homeowner` who owns the project may reopen a `RESOLVED`
    ticket, moving it to `REOPENED`, should the fix fail to hold; from there a
    tech can dispatch it again, forming a repair cycle."

    Design: Difficulty/non_linear_state_machine/service_ticket_resolved_reopen_redispatch_cycle
    """
    base = FX.setup_resolved_ticket(api, category="WARRANTY")
    pid, tid, ho_id = base["project"]["id"], base["ticket"]["id"], base["homeowner"]["id"]
    reopened = validate_success(api.reopen_service_ticket(pid, tid, make_homeowner_headers(ho_id)), 200)
    assert reopened["status"] == "REOPENED", reopened["status"]
    redispatched = validate_success(api.dispatch_service_ticket(pid, tid, TECH), 200)
    assert redispatched["status"] == "DISPATCHED", redispatched["status"]


def test_warranty_ticket_resolves_to_zero_charge(api):
    """PRD §3.9: "A `WARRANTY` ticket is always billed at 0 cents."

    Design: Difficulty/non_linear_state_machine/service_ticket_resolved_reopen_redispatch_cycle
    """
    base = FX.setup_dispatched_ticket(api, category="WARRANTY")
    resolved = validate_success(api.resolve_service_ticket(base["project"]["id"], base["ticket"]["id"], TECH), 200)
    assert resolved["status"] == "RESOLVED", resolved["status"]
    assert resolved["charge_cents"] == 0, resolved["charge_cents"]


# ---------------------------------------------------------------------------
# Multi-hop cascades from accept and cancel
# ---------------------------------------------------------------------------

def test_quote_accept_settles_referral_and_credits_referrer(api):
    """PRD §3.10: "When the referred project reaches `CONTRACTED` — that is, a
    quote on it is accepted — any `PENDING` referral pointing at it transitions
    to `SETTLED`: the system computes `reward_amount_cents` and recomputes the
    referring homeowner's `referral_credit_cents`."
    PRD §3.10: "The reward is 2 percent of the referred project's accepted
    quote's `estimate_total_cents`, rounded half-up to whole cents, then capped
    so it cannot exceed 50,000 cents (the $500 reward cap)."

    Design: Difficulty/transitive_cascade/quote_accept_settles_referral_credits_referrer_depth3
    """
    scen = FX.setup_pending_referral_to_sent_referred(api)
    referred = scen["referred"]
    referral = scen["referral"]
    referrer_ho_id = scen["referrer"]["homeowner"]["id"]
    # Accept the referred project's quote -> CONTRACTED -> referral settles.
    get_success_data(api.accept_quote(
        referred["project"]["id"], referred["quote"]["id"],
        F.accept_quote_payload(scen["referred_quote_version"]),
        make_homeowner_headers(referred["homeowner"]["id"]),
    ))
    settled = validate_success(api.get_referral(referral["id"], SALES), 200)
    assert settled["status"] == "SETTLED", settled["status"]
    assert settled["reward_amount_cents"] == 1680, settled["reward_amount_cents"]
    referrer = validate_success(api.get_homeowner(referrer_ho_id, SALES), 200)
    assert referrer["referral_credit_cents"] == 1680, referrer["referral_credit_cents"]


def test_quote_accept_referred_reaches_contracted(api):
    """PRD §3.4: "Hop one sets the project's `accepted_quote_id` to this quote's
    `id` and recomputes the project's status to `CONTRACTED`."

    Design: Difficulty/transitive_cascade/quote_accept_settles_referral_credits_referrer_depth3
    """
    scen = FX.setup_pending_referral_to_sent_referred(api)
    referred = scen["referred"]
    get_success_data(api.accept_quote(
        referred["project"]["id"], referred["quote"]["id"],
        F.accept_quote_payload(scen["referred_quote_version"]),
        make_homeowner_headers(referred["homeowner"]["id"]),
    ))
    proj = validate_success(api.get_project(referred["project"]["id"], SALES), 200)
    assert proj["status"] == "CONTRACTED", proj["status"]
    assert proj["accepted_quote_id"] == referred["quote"]["id"], proj["accepted_quote_id"]


def test_project_cancel_cascades_manufacture_and_install(api):
    """PRD §3.1: "every non-terminal manufacture order — any in `QUEUED` or
    `IN_BUILD` — is cancelled (hop 2)."
    PRD §3.1: "every `SCHEDULED` install job is cancelled and the crew-day
    capacity it consumed is released (hop 3)."

    Design: Difficulty/transitive_cascade/project_cancel_cascades_manufacture_and_install_depth3
    """
    # CONTRACTED project, manufacture IN_BUILD, then schedule install (goods need
    # not be READY to schedule). Cancel project; both children cancel.
    base = FX.setup_manufacture_in_build(api)
    pid = base["project"]["id"]
    crew = FX.create_crew(api)
    job = get_success_data(api.create_install_job(
        pid, F.create_install_job_payload(pid, crew["id"], "2026-05-10T08:00:00Z", "2026-05-10T17:00:00Z"), OPS))
    cancelled = validate_success(api.cancel_project(pid, OPS), 200)
    assert cancelled["status"] == "CANCELLED", cancelled["status"]
    mo = validate_success(api.get_manufacture_order(base["manufacture"]["id"], OPS), 200)
    assert mo["status"] == "CANCELLED", mo["status"]
    job_after = validate_success(api.get_install_job(job["id"], OPS), 200)
    assert job_after["status"] == "CANCELLED", job_after["status"]


def test_project_cancel_moves_project_to_cancelled(api):
    """PRD §3.1: "Cancellation runs a conditional cascade that touches only
    non-terminal children: the project moves to `CANCELLED` (hop 1)."

    Design: Difficulty/transitive_cascade/project_cancel_cascades_manufacture_and_install_depth3
    """
    base = FX.setup_manufacture_in_build(api)
    cancelled = validate_success(api.cancel_project(base["project"]["id"], OPS), 200)
    assert cancelled["status"] == "CANCELLED", cancelled["status"]
    mo = validate_success(api.get_manufacture_order(base["manufacture"]["id"], OPS), 200)
    assert mo["status"] == "CANCELLED", mo["status"]


# ---------------------------------------------------------------------------
# Conserved-quantity invariants (crew capacity, referral credit)
# ---------------------------------------------------------------------------

def test_crew_capacity_released_on_install_cancel_allows_new_same_day_job(api):
    """PRD §3.7: "A `SCHEDULED` job may instead be cancelled by the coordinator,
    which moves it to `CANCELLED` and releases the crew-day capacity it had
    consumed."
    PRD §3.7: "the sum of their `opening_count` plus the new job's must not
    exceed the crew's `daily_capacity_openings`; equality with the capacity is
    allowed, but exceeding it is rejected with `ERR_CREW_CAPACITY_EXCEEDED`."

    Design: Difficulty/compensating_invariant/crew_capacity_released_on_install_cancel_invariant
    """
    # Crew capacity 1. Job1 on P1 consumes it. Cancel job1 -> capacity restored.
    # A new same-day job on P2 (opening_count 1) then schedules successfully.
    crew = FX.create_crew(api, daily_capacity_openings=1)
    base1 = FX.setup_accepted_quote(api)
    p1 = base1["project"]["id"]
    job1 = get_success_data(api.create_install_job(
        p1, F.create_install_job_payload(p1, crew["id"], "2026-05-10T08:00:00Z", "2026-05-10T12:00:00Z"), OPS))
    base2 = FX.setup_accepted_quote(api)
    p2 = base2["project"]["id"]

    cancelled = validate_success(api.cancel_install_job(p1, job1["id"], OPS), 200)
    assert cancelled["status"] == "CANCELLED", cancelled["status"]
    job2 = validate_success(api.create_install_job(
        p2, F.create_install_job_payload(p2, crew["id"], "2026-05-10T13:00:00Z", "2026-05-10T17:00:00Z"), OPS), 201)
    assert job2["status"] == "SCHEDULED", job2["status"]
    assert job2["opening_count"] == 1, job2["opening_count"]


def test_crew_capacity_consumed_blocks_new_job_until_cancel(api):
    """PRD §3.7: "the sum of their `opening_count` plus the new job's must not
    exceed the crew's `daily_capacity_openings`; equality with the capacity is
    allowed, but exceeding it is rejected with `ERR_CREW_CAPACITY_EXCEEDED`."
    PRD §3.7: "A `SCHEDULED` job may instead be cancelled by the coordinator,
    which moves it to `CANCELLED` and releases the crew-day capacity it had
    consumed."

    Confirms the conserved quantity is genuinely consumed: while job1 holds the
    crew's only slot a same-day job2 is rejected; cancelling job1 releases it.

    Design: Difficulty/compensating_invariant/crew_capacity_released_on_install_cancel_invariant
    """
    crew = FX.create_crew(api, daily_capacity_openings=1)
    base1 = FX.setup_accepted_quote(api)
    p1 = base1["project"]["id"]
    job1 = get_success_data(api.create_install_job(
        p1, F.create_install_job_payload(p1, crew["id"], "2026-05-10T08:00:00Z", "2026-05-10T12:00:00Z"), OPS))
    base2 = FX.setup_accepted_quote(api)
    p2 = base2["project"]["id"]
    # Before cancelling, the same-day slot is full -> rejected.
    blocked = api.create_install_job(
        p2, F.create_install_job_payload(p2, crew["id"], "2026-05-10T13:00:00Z", "2026-05-10T17:00:00Z"), OPS)
    validate_error(blocked, ApiErrorId.ERR_CREW_CAPACITY_EXCEEDED.value, 409)
    # Cancel releases capacity -> the same job now schedules.
    get_success_data(api.cancel_install_job(p1, job1["id"], OPS))
    job2 = validate_success(api.create_install_job(
        p2, F.create_install_job_payload(p2, crew["id"], "2026-05-10T13:00:00Z", "2026-05-10T17:00:00Z"), OPS), 201)
    assert job2["status"] == "SCHEDULED", job2["status"]


def test_referral_credit_conserved_across_settle_and_void(api):
    """PRD §3.10: "The reward is 2 percent of the referred project's accepted
    quote's `estimate_total_cents`, rounded half-up to whole cents, then capped
    so it cannot exceed 50,000 cents (the $500 reward cap)."
    PRD §3.10: "if the referred project is cancelled before it ever reaches
    `CONTRACTED`, the `PENDING` referral is voided to `VOID` and no reward is
    paid."

    Design: Difficulty/compensating_invariant/referral_credit_conserved_settle_then_void_other_referral
    """
    referrer = FX.setup_completed_referrer(api)
    referrer_ho_id = referrer["homeowner"]["id"]
    pref_id = referrer["project"]["id"]

    # Referral A: referred project A taken to SENT, referral created, then accepted -> SETTLED (reward 1680).
    referred_a = FX.setup_sent_quote(api)
    ref_a = get_success_data(api.create_referral(F.create_referral_payload(pref_id, referred_a["project"]["id"]), SALES))
    get_success_data(api.accept_quote(
        referred_a["project"]["id"], referred_a["quote"]["id"],
        F.accept_quote_payload(referred_a["quote_version"]),
        make_homeowner_headers(referred_a["homeowner"]["id"]),
    ))

    # Referral B: referred project B left at SENT (QUOTING), referral created, then project B cancelled -> VOID.
    referred_b = FX.setup_sent_quote(api)
    ref_b = get_success_data(api.create_referral(F.create_referral_payload(pref_id, referred_b["project"]["id"]), SALES))
    get_success_data(api.cancel_project(referred_b["project"]["id"], OPS))

    settled = validate_success(api.get_referral(ref_a["id"], SALES), 200)
    assert settled["status"] == "SETTLED", settled["status"]
    assert settled["reward_amount_cents"] == 1680, settled["reward_amount_cents"]
    voided = validate_success(api.get_referral(ref_b["id"], SALES), 200)
    assert voided["status"] == "VOID", voided["status"]
    assert voided["reward_amount_cents"] == 0, voided["reward_amount_cents"]
    referrer_after = validate_success(api.get_homeowner(referrer_ho_id, SALES), 200)
    assert referrer_after["referral_credit_cents"] == 1680, referrer_after["referral_credit_cents"]


def test_voided_referral_contributes_zero_to_referral_credit(api):
    """PRD §3.10: "if the referred project is cancelled before it ever reaches
    `CONTRACTED`, the `PENDING` referral is voided to `VOID` and no reward is
    paid."
    PRD §3.1: "A homeowner's `referral_credit_cents` is a derived total: it is
    the sum of `reward_amount_cents` across every `SETTLED` referral on which
    this homeowner is the referrer ... it begins at 0."

    Isolates the VOID contribution: a referrer whose only referral is voided
    keeps a referral_credit_cents of 0.

    Design: Difficulty/compensating_invariant/referral_credit_conserved_settle_then_void_other_referral
    """
    referrer = FX.setup_completed_referrer(api)
    referrer_ho_id = referrer["homeowner"]["id"]
    pref_id = referrer["project"]["id"]
    referred = FX.setup_sent_quote(api)
    ref = get_success_data(api.create_referral(F.create_referral_payload(pref_id, referred["project"]["id"]), SALES))
    get_success_data(api.cancel_project(referred["project"]["id"], OPS))
    voided = validate_success(api.get_referral(ref["id"], SALES), 200)
    assert voided["status"] == "VOID", voided["status"]
    assert voided["reward_amount_cents"] == 0, voided["reward_amount_cents"]
    referrer_after = validate_success(api.get_homeowner(referrer_ho_id, SALES), 200)
    assert referrer_after["referral_credit_cents"] == 0, referrer_after["referral_credit_cents"]


# ---------------------------------------------------------------------------
# Cascades, supersession, expiry, OCC version bump
# ---------------------------------------------------------------------------

def test_newly_created_quote_initial_state_is_draft(api):
    """PRD §3.3: "A quote opens in `DRAFT`."
    PRD §2.4: "the `version` field starts at 1 and increases by exactly 1 on
    every mutation."

    Design: Corner/state_machines/newly_created_quote_initial_state_is_draft
    """
    base = FX.setup_measured_consultation(api)
    pid, cons_id = base["project"]["id"], base["consultation"]["id"]
    quote = validate_success(api.create_quote(pid, F.create_quote_payload(pid, cons_id), SALES), 201)
    assert quote["status"] == "DRAFT", quote["status"]
    assert quote["version"] == 1, quote["version"]


def test_reject_quote_cancels_submitted_financing(api):
    """PRD §3.4: "a `Homeowner` rejects a `SENT` quote, moving it to `REJECTED`,
    cancelling any `SUBMITTED` financing application on that quote (its status
    becomes `CANCELLED`)."

    Design: Corner/state_machines/reject_quote_cancels_submitted_financing_cross_entity
    """
    base = FX.setup_sent_quote(api)
    pid, qid, ho_id = base["project"]["id"], base["quote"]["id"], base["homeowner"]["id"]
    fin = get_success_data(api.create_financing(pid, qid, F.create_financing_payload(qid, requested_amount_cents=50_000, term_months=24), make_homeowner_headers(ho_id)))
    rejected = validate_success(api.reject_quote(pid, qid, make_homeowner_headers(ho_id)), 200)
    assert rejected["status"] == "REJECTED", rejected["status"]
    fin_after = validate_success(api.get_financing(fin["id"], SALES), 200)
    assert fin_after["status"] == "CANCELLED", fin_after["status"]


def test_quote_accept_supersedes_other_sent_quotes(api):
    """PRD §3.4: "Hop three sets every other `SENT` quote on the same project to
    `SUPERSEDED`."

    Design: Corner/cross_cutting_complexity_layers/quote_accept_supersedes_other_sent_quotes_cascade
    """
    base = FX.setup_measured_consultation(api)
    pid, cons_id, ho_id = base["project"]["id"], base["consultation"]["id"], base["homeowner"]["id"]
    qa = get_success_data(api.create_quote(pid, F.create_quote_payload(pid, cons_id), SALES))
    qa = get_success_data(api.send_quote(pid, qa["id"], SALES))
    qb = get_success_data(api.create_quote(pid, F.create_quote_payload(pid, cons_id), SALES))
    qb = get_success_data(api.send_quote(pid, qb["id"], SALES))
    accepted = validate_success(api.accept_quote(pid, qa["id"], F.accept_quote_payload(qa["version"]), make_homeowner_headers(ho_id)), 200)
    assert accepted["status"] == "ACCEPTED", accepted["status"]
    qb_after = validate_success(api.get_quote_nested(pid, qb["id"], SALES), 200)
    assert qb_after["status"] == "SUPERSEDED", qb_after["status"]


def test_permit_reinspection_failed_to_approved_cycle(api):
    """PRD §3.8: "A failed permit is not terminal: the coordinator may
    re-approve it, moving it from `INSPECTION_FAILED` back to `APPROVED` and
    resetting `inspection_due_at` to the current clock plus the jurisdiction
    window again, ready for a re-inspection."

    Design: Corner/state_machines/permit_reinspection_failed_to_approved_cycle
    """
    base = FX.setup_completed_project_to_failed_permit(api)
    pid, permit_id = base["project"]["id"], base["permit"]["id"]
    reapproved = validate_success(api.approve_permit(pid, permit_id, OPS), 200)
    assert reapproved["status"] == "APPROVED", reapproved["status"]


def test_immediate_consistency_accept_reflected_on_project_read(api):
    """PRD §3.4: "Hop one sets the project's `accepted_quote_id` to this quote's
    `id` and recomputes the project's status to `CONTRACTED`."

    Design: Corner/consistency_model/immediate_consistency_accept_reflects_project_contracted_in_same_response_chain
    """
    base = FX.setup_accepted_quote(api)
    proj = validate_success(api.get_project(base["project"]["id"], SALES), 200)
    assert proj["status"] == "CONTRACTED", proj["status"]
    assert proj["accepted_quote_id"] == base["quote"]["id"], proj["accepted_quote_id"]


def test_occ_correct_version_accept_bumps_version(api):
    """PRD §3.4: "A successful acceptance increments the quote's `version` by
    one, moves the quote to `ACCEPTED`."

    Design: Corner/cross_cutting_complexity_layers/occ_correct_version_accept_succeeds_and_bumps_version
    """
    base = FX.setup_sent_quote(api)
    pid, qid, ho_id = base["project"]["id"], base["quote"]["id"], base["homeowner"]["id"]
    sent_version = base["quote_version"]
    accepted = validate_success(api.accept_quote(pid, qid, F.accept_quote_payload(sent_version), make_homeowner_headers(ho_id)), 200)
    assert accepted["status"] == "ACCEPTED", accepted["status"]
    assert accepted["version"] == sent_version + 1, accepted["version"]


def test_scheduled_action_mark_ready_at_lead_time_boundary(api):
    """PRD §3.6: "The coordinator later marks the order ready, moving it from
    `IN_BUILD` to `READY`, which requires the order to be `IN_BUILD` and the
    current logical clock to have reached or passed `ready_at` — that is, the
    lead time must have elapsed."

    Design: Corner/cross_cutting_complexity_layers/scheduled_action_manufacture_ready_at_lead_time_gate
    """
    # CASEMENT lead 35d from default 2026-04-01 -> ready_at 2026-05-06. Set clock
    # exactly to ready_at; mark-ready succeeds.
    base = FX.setup_manufacture_in_build(api)
    pid, mo_id = base["project"]["id"], base["manufacture"]["id"]
    assert base["manufacture"]["lead_time_days"] == 35, base["manufacture"]["lead_time_days"]
    get_success_data(api.set_clock(F.set_clock_payload("2026-05-06T00:00:00Z"), ADMIN))
    ready = validate_success(api.mark_ready(pid, mo_id, OPS), 200)
    assert ready["status"] == "READY", ready["status"]
    assert ready["lead_time_days"] == 35, ready["lead_time_days"]
