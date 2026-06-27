"""Award creation, segregation of duties, OCC, and the protest cascade.

Covers queue-A difficulty instances for the award/protest cascades and the
performance-index conservation under termination; queue-B corner instances for award
eligibility, segregation of duties, OCC on the award, protest compensation, set-aside
eligibility, and the inclusive size-standard boundary.
"""
import pytest
from test_helpers import (
    validate_success, validate_error,
    TEST_USERS, make_co_headers, make_vendor_headers, get_success_data,
    set_clock, create_active_vendor,
    create_draft_solicitation_with_factors, open_solicitation,
    create_scored_draft_proposal, submit_proposal, evaluate_proposal,
    setup_evaluated_two_proposals, setup_protested_award_under_review,
    setup_active_ffp_contract,
    create_award_payload, create_protest_payload, create_proposal_payload,
    create_cpars_payload,
)

CO = TEST_USERS["co_headers"]


# ─── Award cascade (transitive depth-2) ────────────────────────────
def test_award_cascade_winner_awarded_loser_rejected(api):
    """PRD §3.4: "The winning proposal is driven from `ACCEPTABLE` to `AWARDED`. Every
    other proposal of that solicitation that is in `ACCEPTABLE`, `UNACCEPTABLE`, or
    `SUBMITTED` status cascades to `REJECTED`."

    Design: Difficulty/transitive_cascade/award_create_cascade_reject_losers
    """
    ctx = setup_evaluated_two_proposals()
    award = validate_success(
        api.create_award(
            create_award_payload(ctx["sol"]["id"], ctx["winner_proposal"]["id"],
                                 ctx["sol_version"]),
            make_co_headers("co_award"),
        ),
        201,
    )
    assert award["status"] == "AWARDED", f"expected AWARDED, got {award['status']}"
    winner = validate_success(api.get_proposal(ctx["winner_proposal"]["id"], CO), 200)
    loser = validate_success(api.get_proposal(ctx["loser_proposal"]["id"], CO), 200)
    assert winner["status"] == "AWARDED", f"expected winner AWARDED, got {winner['status']}"
    assert loser["status"] == "REJECTED", f"expected loser REJECTED, got {loser['status']}"


def test_award_cascade_solicitation_awarded_with_winning_id(api):
    """PRD §3.4: "The solicitation is driven from `EVALUATED` to `AWARDED`, its
    `winning_proposal_id` is set to the awarded proposal, and its `version` increments."

    Design: Difficulty/transitive_cascade/award_create_cascade_reject_losers
    """
    ctx = setup_evaluated_two_proposals()
    get_success_data(
        api.create_award(
            create_award_payload(ctx["sol"]["id"], ctx["winner_proposal"]["id"],
                                 ctx["sol_version"]),
            make_co_headers("co_award"),
        )
    )
    sol = validate_success(api.get_solicitation(ctx["sol"]["id"], CO), 200)
    assert sol["status"] == "AWARDED", f"expected sol AWARDED, got {sol['status']}"
    assert sol["winning_proposal_id"] == ctx["winner_proposal"]["id"], (
        f"expected winning_proposal_id {ctx['winner_proposal']['id']}, "
        f"got {sol['winning_proposal_id']}"
    )


def test_award_visible_immediately_after_creation(api):
    """PRD §2.5: "when an award is made, the awarding operation does not merely create the
    `Award`: it drives the solicitation to `AWARDED` and records its winning proposal,
    drives the winning proposal to `AWARDED`, and reclassifies every other still-live
    proposal of that solicitation as `REJECTED`."

    Immediate consistency: the cascade is observable in the same response (the
    award is AWARDED) and on the immediately-following reads.

    Design: Difficulty/transitive_cascade/award_create_cascade_reject_losers
    """
    ctx = setup_evaluated_two_proposals()
    award = validate_success(
        api.create_award(
            create_award_payload(ctx["sol"]["id"], ctx["winner_proposal"]["id"],
                                 ctx["sol_version"]),
            make_co_headers("co_award"),
        ),
        201,
    )
    assert award["status"] == "AWARDED"
    sol = validate_success(api.get_solicitation(ctx["sol"]["id"], CO), 200)
    winner = validate_success(api.get_proposal(ctx["winner_proposal"]["id"], CO), 200)
    loser = validate_success(api.get_proposal(ctx["loser_proposal"]["id"], CO), 200)
    assert sol["status"] == "AWARDED"
    assert winner["status"] == "AWARDED"
    assert loser["status"] == "REJECTED"


# ─── Award eligibility / segregation / OCC ─────────────────────────
def test_award_to_unacceptable_proposal_rejected(api):
    """PRD §3.4: "The named proposal must belong to the named solicitation and must be in
    `ACCEPTABLE` status; a proposal that is not eligible on either count is rejected with
    `ERR_PROPOSAL_NOT_ELIGIBLE`."

    Design: Corner/validations/error_proposal_not_eligible_on_award
    """
    set_clock("2026-02-01T00:00:00Z")
    va = create_active_vendor("ACCV00000001", employee_count=5)
    vb = create_active_vendor("BADV00000001", employee_count=5)
    sol, factors = create_draft_solicitation_with_factors(
        factors=[("Technical", "TECHNICAL", 0.60),
                 ("Past Performance", "PAST_PERFORMANCE", 0.40),
                 ("Price", "PRICE", 0.0)],
        open_at="2026-02-01T00:00:00Z", close_at="2026-02-05T00:00:00Z",
    )
    open_solicitation(sol["id"])
    p_acc = create_scored_draft_proposal(
        sol["id"], va["id"], 50000000,
        [(factors["TECHNICAL"]["id"], 90), (factors["PAST_PERFORMANCE"]["id"], 80),
         (factors["PRICE"]["id"], 100)],
    )
    submit_proposal(p_acc["id"], va["id"])
    p_bad = create_scored_draft_proposal(
        sol["id"], vb["id"], 45000000,
        [(factors["TECHNICAL"]["id"], 90), (factors["PAST_PERFORMANCE"]["id"], 50),
         (factors["PRICE"]["id"], 100)],
    )
    submit_proposal(p_bad["id"], vb["id"])
    set_clock("2026-02-05T00:00:00Z")
    get_success_data(api.close_solicitation(sol["id"], CO))
    evaluate_proposal(p_acc["id"])
    evaluate_proposal(p_bad["id"])
    finalized = get_success_data(api.finalize_evaluation(sol["id"], make_co_headers("co_chair")))

    res = api.create_award(
        create_award_payload(sol["id"], p_bad["id"], finalized["version"]),
        make_co_headers("co_award"),
    )
    validate_error(res, "ERR_PROPOSAL_NOT_ELIGIBLE", expected_status=409)


def test_award_by_evaluation_chair_segregation_of_duties(api):
    """PRD §3.4: "An award attempted by the evaluation chair is rejected with
    `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/rbac/segregation_of_duties_excluded_by_implicit_coverage
    """
    set_clock("2026-02-01T00:00:00Z")
    vendor = create_active_vendor("SODV00000001", employee_count=5)
    sol, factors = create_draft_solicitation_with_factors(
        open_at="2026-02-01T00:00:00Z", close_at="2026-02-05T00:00:00Z"
    )
    open_solicitation(sol["id"])
    prop = create_scored_draft_proposal(
        sol["id"], vendor["id"], 50000000,
        [(factors["TECHNICAL"]["id"], 90), (factors["PRICE"]["id"], 100)],
    )
    submit_proposal(prop["id"], vendor["id"])
    set_clock("2026-02-05T00:00:00Z")
    get_success_data(api.close_solicitation(sol["id"], CO))
    evaluate_proposal(prop["id"])
    finalized = get_success_data(api.finalize_evaluation(sol["id"], make_co_headers("co_same")))
    # Same operator id finalized AND attempts the award.
    res = api.create_award(
        create_award_payload(sol["id"], prop["id"], finalized["version"]),
        make_co_headers("co_same"),
    )
    validate_error(res, "ERR_SEGREGATION_OF_DUTIES", expected_status=403)


def test_award_stale_solicitation_version_rejected(api):
    """PRD §2.7: "If that value does not match the target solicitation's current
    `version`, the create is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_award_create_stale_solicitation_version
    """
    set_clock("2026-02-01T00:00:00Z")
    vendor = create_active_vendor("OCCA00000001", employee_count=5)
    sol, factors = create_draft_solicitation_with_factors(
        open_at="2026-02-01T00:00:00Z", close_at="2026-02-05T00:00:00Z"
    )
    open_solicitation(sol["id"])
    prop = create_scored_draft_proposal(
        sol["id"], vendor["id"], 50000000,
        [(factors["TECHNICAL"]["id"], 90), (factors["PRICE"]["id"], 100)],
    )
    submit_proposal(prop["id"], vendor["id"])
    set_clock("2026-02-05T00:00:00Z")
    get_success_data(api.close_solicitation(sol["id"], CO))
    evaluate_proposal(prop["id"])
    finalized = get_success_data(api.finalize_evaluation(sol["id"], make_co_headers("co_chair")))
    stale = finalized["version"] - 1
    res = api.create_award(
        create_award_payload(sol["id"], prop["id"], stale),
        make_co_headers("co_award"),
    )
    validate_error(res, "ERR_STALE_VERSION", expected_status=412)


# ─── Solicitation cancel cascade ───────────────────────────────────
def test_cancel_open_solicitation_cascades_proposal_withdrawn(api):
    """PRD §3.2: "When an `OPEN` solicitation is cancelled, every proposal of that
    solicitation in `SUBMITTED`, `UNDER_EVALUATION`, `ACCEPTABLE`, or `UNACCEPTABLE`
    status cascades to `WITHDRAWN`."

    Design: Corner/state_machines/cancel_open_solicitation_cascades_proposals_withdrawn
    """
    set_clock("2026-02-01T00:00:00Z")
    vendor = create_active_vendor("CANC00000001", employee_count=5)
    sol, factors = create_draft_solicitation_with_factors(
        open_at="2026-02-01T00:00:00Z", close_at="2026-03-01T00:00:00Z"
    )
    open_solicitation(sol["id"])
    prop = create_scored_draft_proposal(
        sol["id"], vendor["id"], 40000000,
        [(factors["TECHNICAL"]["id"], 90), (factors["PRICE"]["id"], 100)],
    )
    submit_proposal(prop["id"], vendor["id"])
    cancelled = validate_success(api.cancel_solicitation(sol["id"], CO), 200)
    assert cancelled["status"] == "CANCELLED", f"expected CANCELLED, got {cancelled['status']}"
    after = validate_success(api.get_proposal(prop["id"], CO), 200)
    assert after["status"] == "WITHDRAWN", f"expected WITHDRAWN, got {after['status']}"


# ─── Protest compensation ──────────────────────────────────────────
def test_protest_denied_restores_award(api):
    """PRD §3.6: "Resolving to `DENIED` drives the protest to `DENIED` and restores the
    award from `PROTESTED` back to `AWARDED`."

    Design: Corner/state_machines/protest_denied_restores_award
    """
    ctx = setup_protested_award_under_review(with_contract=False,
                                             winner_uei="DWIN00000001",
                                             loser_uei="DLOS00000001")
    get_success_data(api.resolve_protest(ctx["protest"]["id"], {"outcome": "DENIED"}, CO))
    award = validate_success(api.get_award(ctx["award"]["id"], CO), 200)
    assert award["status"] == "AWARDED", (
        f"expected award restored to AWARDED, got {award['status']}"
    )


def test_protest_sustained_vacates_terminates_freezes(api):
    """PRD §3.6: "The award is driven to `VACATED`." PRD §3.6: "If a contract had been
    created for the vacated award, that contract's `lifecycle_status` is driven from
    `ACTIVE` to `TERMINATED` and its CLINs and invoices freeze." PRD §3.6: "Resolving to
    `SUSTAINED` drives the protest to `SUSTAINED` and vacates the award."

    Design: Difficulty/transitive_cascade/protest_sustained_vacate_terminate_freeze
    """
    ctx = setup_protested_award_under_review(with_contract=True,
                                             winner_uei="WINN00000001",
                                             loser_uei="LOSE00000001")
    resolved = validate_success(
        api.resolve_protest(ctx["protest"]["id"], {"outcome": "SUSTAINED"}, CO), 200
    )
    assert resolved["status"] == "SUSTAINED", f"expected SUSTAINED, got {resolved['status']}"
    award = validate_success(api.get_award(ctx["award"]["id"], CO), 200)
    assert award["status"] == "VACATED", f"expected VACATED, got {award['status']}"
    contract = validate_success(api.get_contract(ctx["contract"]["id"], CO), 200)
    assert contract["lifecycle_status"] == "TERMINATED", (
        f"expected contract TERMINATED, got {contract['lifecycle_status']}"
    )


def test_protest_sustained_reverts_solicitation_and_proposal(api):
    """PRD §3.6: "The previously awarded proposal reverts from `AWARDED` to `ACCEPTABLE`".
    PRD §3.6: "The solicitation's `winning_proposal_id` is cleared back to `null` and the
    solicitation's status reverts from `AWARDED` to `EVALUATED`."

    Design: Difficulty/transitive_cascade/protest_sustained_vacate_terminate_freeze
    """
    ctx = setup_protested_award_under_review(with_contract=True,
                                             winner_uei="WINN00000002",
                                             loser_uei="LOSE00000002")
    get_success_data(api.resolve_protest(ctx["protest"]["id"], {"outcome": "SUSTAINED"}, CO))
    sol = validate_success(api.get_solicitation(ctx["sol"]["id"], CO), 200)
    winner = validate_success(api.get_proposal(ctx["winner_proposal"]["id"], CO), 200)
    assert sol["status"] == "EVALUATED", (
        f"expected solicitation reverted to EVALUATED, got {sol['status']}"
    )
    assert sol["winning_proposal_id"] is None, (
        f"expected winning_proposal_id cleared, got {sol['winning_proposal_id']}"
    )
    assert winner["status"] == "ACCEPTABLE", (
        f"expected awarded proposal reverted to ACCEPTABLE, got {winner['status']}"
    )


def test_protester_not_offeror_rejected(api):
    """PRD §3.6: "The protester must be a non-winning offeror of the protested award's
    solicitation — that is, a proposal with that vendor's id must exist for the
    solicitation and must not be the solicitation's `winning_proposal_id`; a protester who
    is not such an offeror is rejected with `ERR_PROTESTER_NOT_OFFEROR`."

    Design: Corner/validations/error_protester_not_offeror
    """
    set_clock("2026-02-01T00:00:00Z")
    outsider = create_active_vendor("OUTS00000001", employee_count=5)
    ctx = setup_active_ffp_contract(
        base_value_cents=50000000, with_clin=False,
        vendor_uei="PNOW00000001", total_price_cents=50000000,
        close_at="2026-02-05T00:00:00Z",
    )
    res = api.create_protest(
        create_protest_payload(ctx["award"]["id"], outsider["id"], "I want in"),
        make_vendor_headers(outsider["id"]),
    )
    validate_error(res, "ERR_PROTESTER_NOT_OFFEROR", expected_status=422)


# ─── Performance index conservation under termination ──────────────
def test_performance_index_excludes_terminated_contract(api):
    """PRD §3.7: "The qualifying set is the vendor's contracts whose `lifecycle_status` is
    either `ACTIVE` or `CLOSED`; contracts that are `TERMINATED` are excluded so that a
    vacated award does not drag the index down".

    Design: Difficulty/compensating_invariant/performance_index_unchanged_when_contract_terminated
    """
    set_clock("2026-02-01T00:00:00Z")
    # --- First contract -> CLOSED with VERY_GOOD (index 85.00). ---
    a = setup_active_ffp_contract(
        base_value_cents=40000000, with_clin=False,
        vendor_uei="PERF00000001", total_price_cents=40000000,
        close_at="2026-02-05T00:00:00Z",
        chair_id="co_chair_A", award_user_id="co_award_A",
    )
    vendor_id = a["vendor"]["id"]
    ctrA = a["contract"]["id"]
    get_success_data(api.create_cpars(ctrA, create_cpars_payload("VERY_GOOD"), CO))
    get_success_data(api.complete_contract(ctrA, CO))
    get_success_data(api.closeout_contract(ctrA, CO))

    # --- Second contract for the same vendor -> TERMINATED via sustained protest. ---
    # Build a two-proposal solicitation where PERF vendor wins and a rival can protest.
    set_clock("2026-02-01T00:00:00Z")
    rival = create_active_vendor("RIVL00000001", employee_count=30)
    solB, factorsB = create_draft_solicitation_with_factors(
        open_at="2026-02-01T00:00:00Z", close_at="2026-02-05T00:00:00Z"
    )
    open_solicitation(solB["id"])
    pB_win = create_scored_draft_proposal(
        solB["id"], vendor_id, 30000000,
        [(factorsB["TECHNICAL"]["id"], 95), (factorsB["PRICE"]["id"], 100)],
    )
    submit_proposal(pB_win["id"], vendor_id)
    pB_riv = create_scored_draft_proposal(
        solB["id"], rival["id"], 35000000,
        [(factorsB["TECHNICAL"]["id"], 80), (factorsB["PRICE"]["id"], 100)],
    )
    submit_proposal(pB_riv["id"], rival["id"])
    set_clock("2026-02-05T00:00:00Z")
    get_success_data(api.close_solicitation(solB["id"], CO))
    evaluate_proposal(pB_win["id"])
    evaluate_proposal(pB_riv["id"])
    finalizedB = get_success_data(api.finalize_evaluation(solB["id"], make_co_headers("co_chair_B")))
    awardB = get_success_data(
        api.create_award(create_award_payload(solB["id"], pB_win["id"], finalizedB["version"]),
                         make_co_headers("co_award_B"))
    )
    ctrB = get_success_data(api.create_contract(
        {"award_id": awardB["id"], "contract_type": "FFP", "base_value_cents": 30000000}, CO))["id"]
    get_success_data(api.create_cpars(ctrB, create_cpars_payload("SATISFACTORY"), CO))
    protB = get_success_data(
        api.create_protest(create_protest_payload(awardB["id"], rival["id"], "improper award"),
                           make_vendor_headers(rival["id"]))
    )
    get_success_data(api.begin_review(protB["id"], CO))
    get_success_data(api.resolve_protest(protB["id"], {"outcome": "SUSTAINED"}, CO))

    contractB = validate_success(api.get_contract(ctrB, CO), 200)
    assert contractB["lifecycle_status"] == "TERMINATED", (
        f"expected contract B TERMINATED, got {contractB['lifecycle_status']}"
    )
    vendor = validate_success(api.get_vendor(vendor_id, CO), 200)
    assert vendor["performance_index"] == 85.00, (
        f"expected 85.00 (only the non-TERMINATED CLOSED contract's VERY_GOOD=85 counts; "
        f"the TERMINATED contract's SATISFACTORY=70 excluded), got {vendor['performance_index']}"
    )


def test_performance_index_unchanged_alias_assertion(api):
    """PRD §3.7: "contracts that are `TERMINATED` are excluded so that a vacated award
    does not drag the index down".

    Second assertion of the conserved-quantity invariant: the lone CLOSED contract's
    rating determines the index even after a sibling award is vacated.

    Design: Difficulty/compensating_invariant/performance_index_unchanged_when_contract_terminated
    """
    set_clock("2026-02-01T00:00:00Z")
    a = setup_active_ffp_contract(
        base_value_cents=40000000, with_clin=False,
        vendor_uei="PERF00000003", total_price_cents=40000000,
        close_at="2026-02-05T00:00:00Z",
        chair_id="co_chair_X", award_user_id="co_award_X",
    )
    vendor_id = a["vendor"]["id"]
    ctrA = a["contract"]["id"]
    get_success_data(api.create_cpars(ctrA, create_cpars_payload("EXCEPTIONAL"), CO))
    get_success_data(api.complete_contract(ctrA, CO))
    get_success_data(api.closeout_contract(ctrA, CO))

    set_clock("2026-02-01T00:00:00Z")
    rival = create_active_vendor("RIVL00000002", employee_count=30)
    solB, factorsB = create_draft_solicitation_with_factors(
        open_at="2026-02-01T00:00:00Z", close_at="2026-02-05T00:00:00Z"
    )
    open_solicitation(solB["id"])
    pB_win = create_scored_draft_proposal(
        solB["id"], vendor_id, 30000000,
        [(factorsB["TECHNICAL"]["id"], 95), (factorsB["PRICE"]["id"], 100)],
    )
    submit_proposal(pB_win["id"], vendor_id)
    pB_riv = create_scored_draft_proposal(
        solB["id"], rival["id"], 35000000,
        [(factorsB["TECHNICAL"]["id"], 80), (factorsB["PRICE"]["id"], 100)],
    )
    submit_proposal(pB_riv["id"], rival["id"])
    set_clock("2026-02-05T00:00:00Z")
    get_success_data(api.close_solicitation(solB["id"], CO))
    evaluate_proposal(pB_win["id"])
    evaluate_proposal(pB_riv["id"])
    finalizedB = get_success_data(api.finalize_evaluation(solB["id"], make_co_headers("co_chair_Y")))
    awardB = get_success_data(
        api.create_award(create_award_payload(solB["id"], pB_win["id"], finalizedB["version"]),
                         make_co_headers("co_award_Y"))
    )
    ctrB = get_success_data(api.create_contract(
        {"award_id": awardB["id"], "contract_type": "FFP", "base_value_cents": 30000000}, CO))["id"]
    get_success_data(api.create_cpars(ctrB, create_cpars_payload("SATISFACTORY"), CO))
    protB = get_success_data(
        api.create_protest(create_protest_payload(awardB["id"], rival["id"], "improper award"),
                           make_vendor_headers(rival["id"]))
    )
    get_success_data(api.begin_review(protB["id"], CO))
    get_success_data(api.resolve_protest(protB["id"], {"outcome": "SUSTAINED"}, CO))

    vendor = validate_success(api.get_vendor(vendor_id, CO), 200)
    assert vendor["performance_index"] == 100.00, (
        f"expected 100.00 (only the CLOSED contract's EXCEPTIONAL=100 counts), "
        f"got {vendor['performance_index']}"
    )


# ─── Set-aside eligibility ─────────────────────────────────────────
def test_set_aside_certification_missing_rejected(api):
    """PRD §3.3: "If the `set_aside_type` is one of the named programs — `EIGHT_A`,
    `SDVOSB`, `WOSB`, or `HUBZONE` — the vendor must hold the matching certification in
    its `set_aside_certifications`. A vendor that fails either form of the set-aside test
    is rejected with `ERR_SET_ASIDE_INELIGIBLE`."

    Design: Corner/errors/error_set_aside_ineligible_certification_missing
    """
    set_clock("2026-02-01T00:00:00Z")
    vendor = create_active_vendor("NCRT00000001", employee_count=5,
                                  set_aside_certifications=["WOSB"])
    sol, factors = create_draft_solicitation_with_factors(
        set_aside_type="SDVOSB",
        open_at="2026-02-01T00:00:00Z", close_at="2026-03-01T00:00:00Z",
    )
    open_solicitation(sol["id"])
    prop = create_scored_draft_proposal(
        sol["id"], vendor["id"], 40000000,
        [(factors["TECHNICAL"]["id"], 90), (factors["PRICE"]["id"], 100)],
    )
    res = api.submit_proposal(prop["id"], make_vendor_headers(vendor["id"]))
    validate_error(res, "ERR_SET_ASIDE_INELIGIBLE", expected_status=422)


def test_size_standard_inclusive_boundary_eligible(api):
    """PRD §3.3: "If the solicitation's `set_aside_type` is `SMALL_BUSINESS`, the vendor's
    `employee_count` must be at most the solicitation's `naics_size_threshold` (the
    comparison is inclusive)."

    employee_count == naics_size_threshold (500 == 500) is eligible.

    Design: Difficulty/boundary_precision_check/size_standard_inclusive_boundary
    """
    set_clock("2026-02-01T00:00:00Z")
    vendor = create_active_vendor("EX5000000001", employee_count=500)
    sol, factors = create_draft_solicitation_with_factors(
        set_aside_type="SMALL_BUSINESS", naics_size_threshold=500,
        open_at="2026-02-01T00:00:00Z", close_at="2026-03-01T00:00:00Z",
    )
    open_solicitation(sol["id"])
    prop = create_scored_draft_proposal(
        sol["id"], vendor["id"], 50000000,
        [(factors["TECHNICAL"]["id"], 90), (factors["PRICE"]["id"], 100)],
    )
    submitted = validate_success(api.submit_proposal(prop["id"], make_vendor_headers(vendor["id"])), 200)
    assert submitted["status"] == "SUBMITTED", (
        f"employee_count 500 == threshold 500 is inclusive/eligible; "
        f"expected SUBMITTED, got {submitted['status']}"
    )


def test_size_standard_one_over_threshold_ineligible(api):
    """PRD §3.3: "the vendor's `employee_count` must be at most the solicitation's
    `naics_size_threshold` (the comparison is inclusive)." PRD §3.3: "A vendor that fails
    either form of the set-aside test is rejected with `ERR_SET_ASIDE_INELIGIBLE`."

    Boundary partner: employee_count == threshold + 1 (501 > 500) is ineligible.

    Design: Difficulty/boundary_precision_check/size_standard_inclusive_boundary
    """
    set_clock("2026-02-01T00:00:00Z")
    vendor = create_active_vendor("EX5010000001", employee_count=501)
    sol, factors = create_draft_solicitation_with_factors(
        set_aside_type="SMALL_BUSINESS", naics_size_threshold=500,
        open_at="2026-02-01T00:00:00Z", close_at="2026-03-01T00:00:00Z",
    )
    open_solicitation(sol["id"])
    prop = create_scored_draft_proposal(
        sol["id"], vendor["id"], 50000000,
        [(factors["TECHNICAL"]["id"], 90), (factors["PRICE"]["id"], 100)],
    )
    res = api.submit_proposal(prop["id"], make_vendor_headers(vendor["id"]))
    validate_error(res, "ERR_SET_ASIDE_INELIGIBLE", expected_status=422)
