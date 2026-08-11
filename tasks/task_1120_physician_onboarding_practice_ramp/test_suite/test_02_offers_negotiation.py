"""Offer negotiation lifecycle: initial state, invalid transitions, terminal
lockdown, the negotiation cycle loop, round limit, amendment window, and OCC."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    create_physician, create_case, create_offer, extend_offer, accept_offer,
    execute_offer, get_case, get_offer,
    create_offer_payload, setup_active_guarantee, make_physician_headers,
)

RECRUITER = TEST_USERS["recruiter_headers"]
CONTRACT_ADMIN = TEST_USERS["contract_admin_headers"]
DIRECTOR = TEST_USERS["onboarding_director_headers"]
FINANCE = TEST_USERS["finance_analyst_headers"]


def _case_version(case_id):
    return get_case(case_id)["version"]


# --- Queue B: state machine corners ------------------------------------------

def test_offer_initial_state_is_draft(api):
    """PRD §3.2: "A new offer starts in `DRAFT` with `negotiation_round` 0, and its creation increments the case's `version`."
    PRD §3.2: "an offer outside `EXTENDED`/`COUNTERED` yields `ERR_NEGOTIATION_NOT_OPEN`, a clock at or past `expires_at` yields `ERR_OFFER_EXPIRED`, and another physician's offer yields `ERR_FORBIDDEN`."

    Design: Corner/state_machines/offer_initial_state_is_draft
    """
    physician = create_physician(full_name="Dr. Gil", specialty="INTERNAL_MEDICINE")
    case = create_case(physician["id"])
    offer = create_offer(case)
    assert offer["status"] == "DRAFT"
    assert offer["negotiation_round"] == 0
    resp = api.accept_offer(offer["id"], make_physician_headers(physician["id"]))
    validate_error(resp, ApiErrorId.ERR_NEGOTIATION_NOT_OPEN)


def test_offer_execute_from_draft_rejected(api):
    """PRD §3.2: "The offer must be `ACCEPTED` (else `ERR_OFFER_NOT_ACCEPTED`)"
    PRD §3.2: "Execution provisions the entire downstream apparatus."

    Design: Corner/state_machines/offer_execute_from_draft_rejected
    """
    physician = create_physician(full_name="Dr. Han", specialty="INTERNAL_MEDICINE")
    case = create_case(physician["id"])
    offer = create_offer(case)
    resp = api.execute_offer(offer["id"], CONTRACT_ADMIN)
    validate_error(resp, ApiErrorId.ERR_OFFER_NOT_ACCEPTED)
    guarantees = get_success_data(
        api.list_income_guarantees(FINANCE, params={"onboarding_case_id": case["id"]})
    )
    assert guarantees == [], "no guarantee may be provisioned when execute is rejected"


def test_offer_withdraw_terminal_lockdown(api):
    """PRD §3.2: "A `Recruiter` may withdraw an offer with an optional `reason` from `DRAFT`, `EXTENDED`, `COUNTERED`, or `ACCEPTED`, ending it at `WITHDRAWN`"
    PRD §3.2: "Extending from any other state is rejected with `ERR_OFFER_NOT_EXTENDABLE`."

    Design: Corner/state_machines/offer_withdraw_terminal_lockdown
    """
    physician = create_physician(full_name="Dr. Ivy", specialty="INTERNAL_MEDICINE")
    case = create_case(physician["id"])
    offer = create_offer(case)
    offer = extend_offer(offer["id"])
    resp = api.withdraw_offer(offer["id"], {"reason": "candidate ghosted"}, RECRUITER)
    data = validate_success(resp, 200)
    assert data["status"] == "WITHDRAWN"
    resp = api.extend_offer(offer["id"], {}, RECRUITER)
    validate_error(resp, ApiErrorId.ERR_OFFER_NOT_EXTENDABLE)


def test_negotiation_round_limit_sixth_counter(api):
    """PRD §3.2: "the negotiation-round limit applies: at most five counters, so the fifth counter — the one moving round 4 to 5 — succeeds and the sixth is rejected with `ERR_NEGOTIATION_ROUND_LIMIT` (HTTP 422)."

    Design: Corner/validations/negotiation_round_limit_sixth_counter
    """
    physician = create_physician(full_name="Dr. Wes", specialty="INTERNAL_MEDICINE")
    case = create_case(physician["id"])
    offer = create_offer(case)
    headers = make_physician_headers(physician["id"])
    offer = extend_offer(offer["id"])
    round_seen = 0
    for _ in range(5):
        data = validate_success(api.counter_offer(offer["id"], {}, headers), 200)
        round_seen = data["negotiation_round"]
        offer = extend_offer(offer["id"])
    assert round_seen == 5, f"the fifth counter must succeed with negotiation_round 5, got {round_seen}"
    resp = api.counter_offer(offer["id"], {}, headers)
    validate_error(resp, ApiErrorId.ERR_NEGOTIATION_ROUND_LIMIT)
    assert get_offer(offer["id"])["negotiation_round"] == 5


def test_second_active_offer_rejected(api):
    """PRD §3.2: "A case may hold at most one non-terminal offer at a time: drafting a second offer while a `DRAFT`, `EXTENDED`, `COUNTERED`, or `ACCEPTED` offer still exists is rejected with `ERR_ACTIVE_OFFER_EXISTS` (HTTP 409)."

    Design: Corner/validations/second_active_offer_rejected
    """
    physician = create_physician(full_name="Dr. Cal", specialty="INTERNAL_MEDICINE")
    case = create_case(physician["id"])
    first = create_offer(case)
    resp = api.create_offer(
        create_offer_payload(case["id"], _case_version(case["id"]), base_salary_cents=24000000),
        RECRUITER,
    )
    validate_error(resp, ApiErrorId.ERR_ACTIVE_OFFER_EXISTS)
    assert get_offer(first["id"])["status"] == "DRAFT"


def test_amendment_blocked_after_guarantee_active(api):
    """PRD §3.2: "drafting against a case that already has an `EXECUTED` offer is an amendment, and it is permitted only while the case's income guarantee is still `DRAFT` and every ramp milestone is still `PENDING`; otherwise the create is rejected with `ERR_AMENDMENT_WINDOW_CLOSED` (HTTP 409)."

    Design: Corner/validations/amendment_blocked_after_guarantee_active
    """
    ctx = setup_active_guarantee(full_name="Dr. Bea")
    case_id = ctx["case"]["id"]
    assert ctx["guarantee"]["status"] == "ACTIVE"
    resp = api.create_offer(
        create_offer_payload(
            case_id, _case_version(case_id),
            guarantee_monthly_cents=2100000, proposed_start_date="2027-07-01",
            expires_at="2027-12-01T00:00:00Z",
        ),
        RECRUITER,
    )
    validate_error(resp, ApiErrorId.ERR_AMENDMENT_WINDOW_CLOSED)


# --- Queue A: negotiation cycle ----------------------------------------------

def test_offer_negotiation_cycle_loop_rounds(api):
    """PRD §3.2: "The physician answers an `EXTENDED` offer with a counter, optionally attaching a `physician_note`, which moves the offer `EXTENDED` → `COUNTERED` and increments `negotiation_round`."
    PRD §3.2: "A `Recruiter` extends a `DRAFT` offer, moving it to `EXTENDED`, and may later re-extend a `COUNTERED` offer back to `EXTENDED` with revised terms — any term fields supplied on the re-extension overwrite the prior terms."

    Design: Difficulty/non_linear_state_machine/offer_negotiation_cycle_loop
    """
    physician = create_physician(full_name="Dr. Fay", specialty="INTERNAL_MEDICINE")
    case = create_case(physician["id"])
    offer = create_offer(case)
    headers = make_physician_headers(physician["id"])
    extend_offer(offer["id"])

    data = validate_success(
        api.counter_offer(offer["id"], {"physician_note": "need more base"}, headers), 200
    )
    assert data["status"] == "COUNTERED"
    assert data["negotiation_round"] == 1

    data = validate_success(
        api.extend_offer(offer["id"], {"base_salary_cents": 26000000}, RECRUITER), 200
    )
    assert data["status"] == "EXTENDED", "the cycle hop COUNTERED -> EXTENDED must be legal"
    assert data["base_salary_cents"] == 26000000, "re-extension terms must overwrite prior terms"

    data = validate_success(
        api.counter_offer(offer["id"], {"physician_note": "and guarantee"}, headers), 200
    )
    assert data["negotiation_round"] == 2


def test_offer_negotiation_cycle_loop_executed_terms(api):
    """PRD §3.2: "may later re-extend a `COUNTERED` offer back to `EXTENDED` with revised terms — any term fields supplied on the re-extension overwrite the prior terms."
    PRD §3.2: "the server creates: an IncomeGuarantee in `DRAFT` whose `monthly_guarantee_cents` and `term_months` are copied from the offer's `guarantee_monthly_cents` and `guarantee_term_months`"

    Design: Difficulty/non_linear_state_machine/offer_negotiation_cycle_loop
    """
    physician = create_physician(full_name="Dr. Fay", specialty="INTERNAL_MEDICINE")
    case = create_case(physician["id"])
    offer = create_offer(case)
    headers = make_physician_headers(physician["id"])
    extend_offer(offer["id"])
    validate_success(api.counter_offer(offer["id"], {}, headers), 200)
    extend_offer(offer["id"], base_salary_cents=26000000)
    validate_success(api.counter_offer(offer["id"], {}, headers), 200)
    extend_offer(offer["id"], guarantee_monthly_cents=2100000)

    data = validate_success(api.accept_offer(offer["id"], headers), 200)
    assert data["status"] == "ACCEPTED"
    data = validate_success(api.execute_offer(offer["id"], CONTRACT_ADMIN), 200)
    assert data["status"] == "EXECUTED"

    guarantees = get_success_data(
        api.list_income_guarantees(FINANCE, params={"onboarding_case_id": case["id"]})
    )
    assert len(guarantees) == 1
    assert guarantees[0]["monthly_guarantee_cents"] == 2100000, (
        "the executed contract must carry the revised guarantee terms into the provisioned guarantee"
    )


# --- Queue B: OCC on offer creation ------------------------------------------

def test_offer_create_amendment_stale_version_412(api):
    """PRD §2.8: "The offer-creation endpoint (`POST /onboarding/offers`) requires the request to carry `expected_onboarding_case_version`, the case `version` the client last observed. If the case's current `version` no longer matches — for example because another writer has executed an amendment that legitimately superseded the prior executed offer and advanced the case — the create is rejected with `ERR_STALE_VERSION` (HTTP 412) rather than letting the stale reader act on a case it has not observed."

    Design: Corner/cross_cutting_layers/offer_create_amendment_stale_version_412
    """
    physician = create_physician(full_name="Dr. Len")
    case = create_case(physician["id"])
    offer = create_offer(case)
    offer = extend_offer(offer["id"])
    offer = accept_offer(offer["id"], physician["id"])
    version_before_execute = _case_version(case["id"])
    execute_offer(offer["id"])

    amendment_payload = create_offer_payload(
        case["id"], version_before_execute,
        base_salary_cents=26000000, guarantee_monthly_cents=2100000,
        panel_capacity=1100, proposed_start_date="2027-07-01",
        expires_at="2027-01-01T00:00:00Z",
    )
    resp = api.create_offer(amendment_payload, RECRUITER)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    amendment_payload["expected_onboarding_case_version"] = _case_version(case["id"])
    data = validate_success(api.create_offer(amendment_payload, RECRUITER), 201)
    assert data["status"] == "DRAFT", (
        "the amendment window is open while the guarantee is DRAFT and all milestones PENDING"
    )
    assert get_offer(offer["id"])["status"] == "EXECUTED", (
        "the original offer remains EXECUTED until the amendment itself executes"
    )
