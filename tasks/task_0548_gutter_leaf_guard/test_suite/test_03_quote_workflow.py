"""Quote lifecycle: the revision cycle, the cross-entity present gate, terminal
lockdown, presentation idempotency, expiry, supersession, and the optimistic
concurrency check on quote creation.
"""
from test_helpers import (
    ApiErrorId,
    complete_appointment,
    create_appointment,
    create_lead,
    create_product,
    create_quote,
    create_quote_payload,
    create_sales_rep,
    get_lead_version,
    set_clock,
    setup_accepted_quote,
    setup_draft_quote,
    setup_presented_quote,
    validate_error,
    validate_success,
)


def _fresh_quote_context():
    product = create_product()
    rep = create_sales_rep()
    lead = create_lead(rep["id"])
    appt = create_appointment(lead["id"], rep["id"])
    return product, rep, lead, appt


# --------------------------------------------------------- revision cycle
def test_quote_revision_cycle_status_transitions(api, admin_headers):
    """PRD §3.5: "It may be sent back for revision as `REVISION_REQUESTED`, and
    from there returned to `DRAFT`; that reset restores `linear_feet` to
    `estimated_linear_feet`, recomputes the provisional total, and clears
    `presented_at`, so the quote can be re-presented later — the revision loop is
    `REVISION_REQUESTED` to `DRAFT` to `PRESENTED`."

    Design: Difficulty/non_linear_state_machine/quote_revision_cycle
    """
    scenario = setup_presented_quote(
        estimated_linear_feet=180, color="COPPER", measured_linear_feet=210,
        downspout_count=2, discount_pct=0.10, appt_via_confirmed=True,
    )
    qid = scenario["quote"]["id"]
    assert scenario["quote"]["status"] == "PRESENTED"
    r1 = validate_success(
        api.transition_quote(qid, {"to_status": "REVISION_REQUESTED"}, admin_headers)
    )
    assert r1["status"] == "REVISION_REQUESTED"
    r2 = validate_success(api.transition_quote(qid, {"to_status": "DRAFT"}, admin_headers))
    assert r2["status"] == "DRAFT"
    r3 = validate_success(api.present_quote(qid, admin_headers))
    assert r3["status"] == "PRESENTED"


def test_quote_revision_cycle_reprices_along_the_loop(api, admin_headers):
    """PRD §3.5: "that reset restores `linear_feet` to `estimated_linear_feet`,
    recomputes the provisional total, and clears `presented_at`, so the quote can
    be re-presented later — the revision loop is `REVISION_REQUESTED` to `DRAFT`
    to `PRESENTED`."

    Design: Difficulty/non_linear_state_machine/quote_revision_cycle
    """
    scenario = setup_presented_quote(
        estimated_linear_feet=180, color="COPPER", measured_linear_feet=210,
        downspout_count=2, discount_pct=0.10, appt_via_confirmed=True,
    )
    qid = scenario["quote"]["id"]
    assert scenario["quote"]["total_cents"] == 654750  # FINAL from measured 210
    validate_success(
        api.transition_quote(qid, {"to_status": "REVISION_REQUESTED"}, admin_headers)
    )
    back = validate_success(api.transition_quote(qid, {"to_status": "DRAFT"}, admin_headers))
    assert back["total_cents"] == 588600  # reset to PROVISIONAL from estimated 180
    re_presented = validate_success(api.present_quote(qid, admin_headers))
    assert re_presented["total_cents"] == 654750  # FINAL recomputed on re-present


# ------------------------------------------- present requires appointment done
def test_present_rejected_while_appointment_not_completed(api, admin_headers):
    """PRD §3.5: "The present action advances the quote from `DRAFT` to
    `PRESENTED`, and it is permitted only when the backing appointment (identified
    by the quote's `appointment_id`) has reached `COMPLETED`; otherwise it is
    rejected with `ERR_APPOINTMENT_NOT_COMPLETED`."

    Design: Difficulty/cross_entity_state_dependency/present_requires_appointment_completed
    """
    scenario = setup_draft_quote(estimated_linear_feet=180, complete_appt=False)
    resp = api.present_quote(scenario["quote"]["id"], admin_headers)
    validate_error(resp, ApiErrorId.ERR_APPOINTMENT_NOT_COMPLETED)


def test_present_succeeds_once_appointment_completed(api, admin_headers):
    """PRD §3.5: "The present action advances the quote from `DRAFT` to
    `PRESENTED`, and it is permitted only when the backing appointment (identified
    by the quote's `appointment_id`) has reached `COMPLETED`; otherwise it is
    rejected with `ERR_APPOINTMENT_NOT_COMPLETED`."

    Design: Difficulty/cross_entity_state_dependency/present_requires_appointment_completed
    """
    scenario = setup_draft_quote(estimated_linear_feet=180, complete_appt=False)
    complete_appointment(scenario["appointment"]["id"], 200, via_confirmed=True)
    presented = validate_success(api.present_quote(scenario["quote"]["id"], admin_headers))
    assert presented["status"] == "PRESENTED"
    assert presented["total_cents"] == 570000  # measured 200 WHITE, tier T2


# ----------------------------------------------------- terminal / idempotency
def test_accepted_quote_rejects_further_transition(api, admin_headers):
    """PRD §3.5: "A quote's terminal states are `ACCEPTED`, `DECLINED`, and
    `SUPERSEDED`."
    PRD §2.6: "`ERR_INVALID_STATE` for a plain illegal transition"

    Design: Corner/state_machines/quote_terminal_accepted_lockdown
    """
    scenario = setup_accepted_quote(estimated_linear_feet=200, measured_linear_feet=200)
    resp = api.transition_quote(scenario["quote"]["id"], {"to_status": "DECLINED"}, admin_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    still = validate_success(api.get_quote(scenario["quote"]["id"], admin_headers))
    assert still["status"] == "ACCEPTED"


def test_present_twice_second_call_is_invalid_state(api, admin_headers):
    """PRD §3.5: "The present action advances the quote from `DRAFT` to
    `PRESENTED`, and it is permitted only when the backing appointment (identified
    by the quote's `appointment_id`) has reached `COMPLETED`; otherwise it is
    rejected with `ERR_APPOINTMENT_NOT_COMPLETED`."
    PRD §2.6: "`ERR_INVALID_STATE` for a plain illegal transition"

    Design: Corner/state_machines/present_twice_second_is_invalid_state
    """
    scenario = setup_presented_quote(estimated_linear_feet=200, measured_linear_feet=200)
    resp = api.present_quote(scenario["quote"]["id"], admin_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_quote_accept_after_validity_window_returns_expired(api, admin_headers):
    """PRD §3.5: "Acceptance is allowed only while the quote is still valid: the
    current logical-clock time must be no later than `presented_at` plus 30 days,
    the quote validity window; an attempt after that window is rejected with
    `ERR_QUOTE_EXPIRED`."

    Design: Corner/state_machines/quote_accept_after_expiry_returns_expired
    """
    # Presented at the default logical clock (2026-05-01); accept 45 days later.
    scenario = setup_presented_quote(estimated_linear_feet=200, measured_linear_feet=200)
    set_clock("2026-06-15T00:00:00Z")
    resp = api.transition_quote(scenario["quote"]["id"], {"to_status": "ACCEPTED"}, admin_headers)
    validate_error(resp, ApiErrorId.ERR_QUOTE_EXPIRED)


# --------------------------------------------------- supersede / concurrency
def test_new_quote_supersedes_prior_draft_quote(api, admin_headers):
    """PRD §3.4: "Creating the quote advances the owning lead from
    `APPOINTMENT_SET` to `QUOTED`, supersedes any prior quote for that same lead
    that is still in `DRAFT`, `PRESENTED`, or `REVISION_REQUESTED` by moving it to
    `SUPERSEDED`, and increments the lead's `version` by one (which is exactly why
    a stale `expected_lead_version` is refused)."

    Design: Corner/cross_cutting/quote_supersede_on_new_quote
    """
    product, rep, lead, appt = _fresh_quote_context()
    q1 = create_quote(lead["id"], appt["id"], rep["id"], product["id"], "WHITE", 100)
    create_quote(lead["id"], appt["id"], rep["id"], product["id"], "COPPER", 120)
    q1_after = validate_success(api.get_quote(q1["id"], admin_headers))
    assert q1_after["status"] == "SUPERSEDED"


def test_quote_create_with_stale_lead_version_returns_412(api, admin_headers):
    """PRD §2.7: "If `expected_lead_version` does not equal the lead's current
    `version`, the creation is rejected with `ERR_STALE_VERSION` (HTTP 412), and
    no quote is created."

    Design: Corner/cross_cutting/quote_create_stale_lead_version_returns_412
    """
    product, rep, lead, appt = _fresh_quote_context()
    observed_version = get_lead_version(lead["id"])
    # First create succeeds and advances the lead's version.
    create_quote(
        lead["id"], appt["id"], rep["id"], product["id"], "WHITE", 100,
        expected_lead_version=observed_version,
    )
    # Second create still carries the now-stale version.
    stale_payload = create_quote_payload(
        lead["id"], appt["id"], rep["id"], product["id"], "WHITE", 120, observed_version,
    )
    resp = api.create_quote(stale_payload, admin_headers)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
