"""Offer creation guards, the cyclic negotiation loop, and OCC on revise."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    setup_open_opening, setup_interviewing_application, setup_offer_extended,
    setup_placement_pre_start,
    create_candidate_entity, create_application_entity,
    screen_application, submit_application,
    create_site_visit_entity, complete_site_visit,
    create_offer_payload,
    make_account_manager_headers, make_recruiter_headers, make_client_contact_headers,
)


# --------------------------------------------------------------------------
# Offer creation guards
# --------------------------------------------------------------------------
def test_offer_without_completed_site_visit_rejected(api):
    """PRD §3.5: "Creating the offer is also what advances the application
    INTERVIEWING → OFFER_STAGE, which ... requires a COMPLETED site visit on that
    application, failing with ERR_NO_COMPLETED_SITE_VISIT otherwise."

    Design: Corner/validations/offer_without_completed_site_visit_blocked
    """
    ctx = setup_interviewing_application()
    resp = api.create_offer(
        create_offer_payload(ctx["app_id"]), make_account_manager_headers(ctx["am_id"])
    )
    validate_error(resp, ApiErrorId.ERR_NO_COMPLETED_SITE_VISIT.value)


def test_offer_comp_above_band_rejected(api):
    """PRD §3.5: "The offered base_salary_cents must fall within the opening's band,
    at least comp_min_cents and at most comp_max_cents; a value outside that band is
    rejected with ERR_COMP_OUT_OF_RANGE."

    Design: Corner/validations/comp_out_of_range_isolated
    """
    ctx = setup_interviewing_application()  # comp band 20,000,000-30,000,000
    sv = create_site_visit_entity(ctx["rec_id"], ctx["app_id"], ctx["rec_id"])
    complete_site_visit(ctx["rec_id"], sv["id"])
    resp = api.create_offer(
        create_offer_payload(ctx["app_id"], base_salary_cents=35_000_000),
        make_account_manager_headers(ctx["am_id"]),
    )
    validate_error(resp, ApiErrorId.ERR_COMP_OUT_OF_RANGE.value)


def test_specialty_mismatch_on_submit_rejected(api):
    """PRD §3.3: "the candidate's specialty must equal the opening's specialty,
    otherwise it is rejected with ERR_SPECIALTY_MISMATCH."

    Design: Corner/validations/specialty_mismatch_on_submit
    """
    ctx = setup_open_opening()  # CARDIOLOGY opening
    cand = create_candidate_entity(ctx["rec_id"], specialty="PSYCHIATRY")
    app = create_application_entity(ctx["rec_id"], cand["id"], ctx["opening_id"])
    screen_application(ctx["rec_id"], app["id"])
    resp = api.advance_application(app["id"], "SUBMIT", make_recruiter_headers(ctx["rec_id"]))
    validate_error(resp, ApiErrorId.ERR_SPECIALTY_MISMATCH.value)


def test_second_accept_on_accepted_offer_rejected(api):
    """PRD §2.10: "State legality — the target resource is in a state from which the
    requested transition is defined, else ERR_INVALID_STATE."
    PRD §3.5: "A Recruiter, acting for the candidate, accepts an extended offer
    (EXTENDED → ACCEPTED)".

    Design: Corner/state_machines/offer_accept_from_accepted_invalid
    """
    ctx = setup_placement_pre_start()  # offer already ACCEPTED
    resp = api.transition_offer(
        ctx["offer_id"], "ACCEPT", make_recruiter_headers(ctx["rec_id"])
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# --------------------------------------------------------------------------
# priority: offer state legality beats comp-range
# --------------------------------------------------------------------------
def test_offer_on_submitted_app_with_bad_comp_reports_invalid_state(api):
    """PRD §2.10: "a stale-version revise is rejected before its state legality or
    comp range is examined." (state legality is priority 8, comp range priority 11)
    PRD §3.5: "Creating the offer is also what advances the application
    INTERVIEWING → OFFER_STAGE".

    Design: Difficulty/priority_pair_validation_conflict/offer_state_beats_comp_range
    """
    ctx = setup_open_opening()
    cand = create_candidate_entity(ctx["rec_id"])
    app = create_application_entity(ctx["rec_id"], cand["id"], ctx["opening_id"])
    screen_application(ctx["rec_id"], app["id"])
    submit_application(ctx["rec_id"], app["id"])  # app now SUBMITTED, not INTERVIEWING
    resp = api.create_offer(
        create_offer_payload(app["id"], base_salary_cents=35_000_000),  # also out of range
        make_account_manager_headers(ctx["am_id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_offer_on_submitted_app_with_in_range_comp_still_invalid_state(api):
    """PRD §2.10: "State legality — the target resource is in a state from which the
    requested transition is defined, else ERR_INVALID_STATE."
    PRD §3.5: "Creating the offer is also what advances the application
    INTERVIEWING → OFFER_STAGE".

    Design: Difficulty/priority_pair_validation_conflict/offer_state_beats_comp_range
    """
    ctx = setup_open_opening()
    cand = create_candidate_entity(ctx["rec_id"])
    app = create_application_entity(ctx["rec_id"], cand["id"], ctx["opening_id"])
    screen_application(ctx["rec_id"], app["id"])
    submit_application(ctx["rec_id"], app["id"])  # SUBMITTED
    resp = api.create_offer(
        create_offer_payload(app["id"], base_salary_cents=25_000_000),  # in range
        make_account_manager_headers(ctx["am_id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# --------------------------------------------------------------------------
# cyclic negotiation + OCC
# --------------------------------------------------------------------------
def test_offer_revise_after_counter_returns_to_extended(api):
    """PRD §3.5: "The account manager answers a counter by revising it back
    COUNTERED → EXTENDED with fresh terms."

    Design: Difficulty/non_linear_state_machine/offer_cyclic_negotiation_round
    """
    ctx = setup_offer_extended()
    countered = validate_success(
        api.transition_offer(
            ctx["offer_id"], "COUNTER", make_client_contact_headers(ctx["client_id"])
        )
    )
    revised = validate_success(
        api.revise_offer(
            ctx["offer_id"],
            {"expected_offer_version": countered["version"], "base_salary_cents": 26_000_000},
            make_account_manager_headers(ctx["am_id"]),
        )
    )
    assert revised["status"] == "EXTENDED"


def test_offer_revise_increments_round_number(api):
    """PRD §3.5: "A successful revise increments round_number by one, recomputes
    offered_first_year_comp_cents from the current base and sign-on figures".

    Design: Difficulty/non_linear_state_machine/offer_cyclic_negotiation_round
    """
    ctx = setup_offer_extended()
    assert ctx["offer"]["round_number"] == 1
    countered = validate_success(
        api.transition_offer(
            ctx["offer_id"], "COUNTER", make_client_contact_headers(ctx["client_id"])
        )
    )
    revised = validate_success(
        api.revise_offer(
            ctx["offer_id"],
            {"expected_offer_version": countered["version"], "base_salary_cents": 26_000_000},
            make_account_manager_headers(ctx["am_id"]),
        )
    )
    assert revised["round_number"] == 2


def test_offer_revise_with_stale_version_rejected(api):
    """PRD §2.6: "If expected_offer_version does not equal the target offer's current
    version, the revise is rejected with ERR_STALE_VERSION (HTTP 412), and no terms
    change."

    Design: Corner/validations/offer_revise_stale_version_rejected
    """
    ctx = setup_offer_extended()
    stale_version = ctx["offer"]["version"]  # version before the client counter
    validate_success(
        api.transition_offer(
            ctx["offer_id"], "COUNTER", make_client_contact_headers(ctx["client_id"])
        )
    )
    resp = api.revise_offer(
        ctx["offer_id"],
        {"expected_offer_version": stale_version, "base_salary_cents": 26_000_000},
        make_account_manager_headers(ctx["am_id"]),
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)
