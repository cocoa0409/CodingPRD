"""Agency referrals: the SENT resolve/reject fork, validation precedence on referral
creation, consent gating, the conserved open_referral_count ledger, invalid-state
rejection, and case-referral reverse lookup."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId,
    triaged_case, referred_case, sent_referral, new_agency,
    TEST_USERS,
)

ADMIN = TEST_USERS["office_admin_headers"]
CASEWORKER = TEST_USERS["caseworker_headers"]


# --- Difficulty: non_linear_state_machine / referral_branch_resolve_vs_reject ---

def test_referral_resolve_branch_outcome(api):
    """PRD §3.5: "the parent case is returned from `AWAITING_AGENCY` to `IN_PROGRESS`
    with its `last_agency_outcome` set to `RESOLVED`, resuming the service clock".

    Design: Difficulty/non_linear_state_machine/referral_branch_resolve_vs_reject
    """
    s = sent_referral(api)
    ref = validate_success(api.resolve_referral(s["ref_id"], {"response_summary": "done"}, CASEWORKER))
    assert ref["status"] == "RESOLVED"
    case = validate_success(api.get_case(s["case_id"], CASEWORKER))
    assert case["last_agency_outcome"] == "RESOLVED"
    assert case["reject_count"] == 0, "resolve branch must not touch reject_count"
    assert case["status"] == "IN_PROGRESS"


def test_referral_reject_branch_outcome(api):
    """PRD §3.5: "here `last_agency_outcome` is set to `REJECTED` and the case's
    `reject_count` is additionally incremented by one."

    Design: Difficulty/non_linear_state_machine/referral_branch_resolve_vs_reject
    """
    s = sent_referral(api)
    ref = validate_success(api.reject_referral(s["ref_id"], {"reason": "not us"}, CASEWORKER))
    assert ref["status"] == "REJECTED"
    case = validate_success(api.get_case(s["case_id"], CASEWORKER))
    assert case["last_agency_outcome"] == "REJECTED"
    assert case["reject_count"] == 1, "reject branch must increment reject_count to 1"


# --- Difficulty: priority_pair_validation_conflict / referral_state_beats_consent ---

def test_referral_on_new_case_state_error_wins(api):
    """PRD §2.6: "State — the target resource is in a state that permits the requested
    transition (per the workflow rules in §3), else the entity-specific conflict error
    (409): `ERR_CASE_INVALID_STATE`, `ERR_REFERRAL_INVALID_STATE`, `ERR_EVENT_INVALID_STATE`,
    or `ERR_REGISTRATION_INVALID_STATE`."
    PRD §3.5: "Referral creation is only valid from `IN_PROGRESS` and requires two
    safety gates: the case's constituent must have `data_sharing_consent` set to true,
    else `ERR_CONSENT_REQUIRED`".

    Design: Difficulty/priority_pair_validation_conflict/referral_state_beats_consent
    """
    # A NEW (un-triaged) case whose constituent has data_sharing_consent=false.
    from test_helpers import new_representative, new_constituent, new_case
    rep = new_representative(api)
    con = new_constituent(api, rep["id"], data_sharing_consent=False)
    agency = new_agency(api, status="ACTIVE")
    case = new_case(api, con["id"], category="TAX")
    resp = api.create_referral(case["id"], {"agency_id": agency["id"]}, CASEWORKER)
    validate_error(resp, ApiErrorId.ERR_CASE_INVALID_STATE)


def test_referral_on_new_case_not_consent_error(api):
    """PRD §3.5: "Referral creation is only valid from `IN_PROGRESS`".
    PRD §2.6: "State — the target resource is in a state that permits the requested
    transition (per the workflow rules in §3), else the entity-specific conflict error (409)".

    Design: Difficulty/priority_pair_validation_conflict/referral_state_beats_consent
    """
    from test_helpers import new_representative, new_constituent, new_case
    rep = new_representative(api)
    con = new_constituent(api, rep["id"], data_sharing_consent=False)
    agency = new_agency(api, status="ACTIVE")
    case = new_case(api, con["id"], category="TAX")
    resp = api.create_referral(case["id"], {"agency_id": agency["id"]}, CASEWORKER)
    err = validate_error(resp, ApiErrorId.ERR_CASE_INVALID_STATE)
    assert err["error_id"] != "ERR_CONSENT_REQUIRED", "state check must pre-empt the consent gate"
    still = validate_success(api.get_case(case["id"], CASEWORKER))
    assert still["status"] == "NEW", "rejected referral must not transition the case"


# --- Difficulty: priority_pair_validation_conflict / referral_consent_beats_agency_inactive ---

def test_referral_consent_beats_agency_inactive_error(api):
    """PRD §2.6: "The relative priority among these is: consent before
    purged-constituent, before agency-inactive, before template-mismatch, before
    duplicate-registration, before venue-conflict, before representative-conflict,
    before event-full, before stale-version".

    Design: Difficulty/priority_pair_validation_conflict/referral_consent_beats_agency_inactive
    """
    s = triaged_case(api, category="BENEFITS", window=96, consent=False)
    agency = new_agency(api, status="INACTIVE")
    resp = api.create_referral(s["case_id"], {"agency_id": agency["id"]}, CASEWORKER)
    validate_error(resp, ApiErrorId.ERR_CONSENT_REQUIRED)


def test_referral_consent_beats_agency_inactive_not_agency_error(api):
    """PRD §3.5: "the case's constituent must have `data_sharing_consent` set to true,
    else `ERR_CONSENT_REQUIRED`; and the referenced agency must be `ACTIVE`, else
    `ERR_AGENCY_INACTIVE`."

    Design: Difficulty/priority_pair_validation_conflict/referral_consent_beats_agency_inactive
    """
    s = triaged_case(api, category="BENEFITS", window=96, consent=False)
    agency = new_agency(api, status="INACTIVE")
    resp = api.create_referral(s["case_id"], {"agency_id": agency["id"]}, CASEWORKER)
    err = validate_error(resp, ApiErrorId.ERR_CONSENT_REQUIRED)
    assert err["error_id"] != "ERR_AGENCY_INACTIVE", "consent gate must pre-empt agency-inactive"
    still = validate_success(api.get_case(s["case_id"], CASEWORKER))
    assert still["status"] == "IN_PROGRESS", "rejected referral must not transition the case"


# --- Difficulty: cross_entity_state_dependency / case_referral_gated_by_constituent_consent ---

def test_referral_blocked_without_consent(api):
    """PRD §3.5: "Referral creation is only valid from `IN_PROGRESS` and requires two
    safety gates: the case's constituent must have `data_sharing_consent` set to true,
    else `ERR_CONSENT_REQUIRED`".

    Design: Difficulty/cross_entity_state_dependency/case_referral_gated_by_constituent_consent
    """
    s = triaged_case(api, category="HOUSING", window=120, consent=False)
    agency = new_agency(api, status="ACTIVE")
    resp = api.create_referral(s["case_id"], {"agency_id": agency["id"]}, CASEWORKER)
    validate_error(resp, ApiErrorId.ERR_CONSENT_REQUIRED)


def test_referral_allowed_after_consent_granted(api):
    """PRD §3.5: "On success the case moves from `IN_PROGRESS` to `AWAITING_AGENCY`,
    its `paused_since` is set to the current clock ... and a new **agency referral** is
    created linking the case's `case_id` and the `agency_id`, starting in `status` `DRAFT`."

    Design: Difficulty/cross_entity_state_dependency/case_referral_gated_by_constituent_consent
    """
    s = triaged_case(api, category="HOUSING", window=120, consent=False)
    agency = new_agency(api, status="ACTIVE")
    validate_error(api.create_referral(s["case_id"], {"agency_id": agency["id"]}, CASEWORKER),
                   ApiErrorId.ERR_CONSENT_REQUIRED)
    validate_success(api.update_constituent(s["con_id"], {"data_sharing_consent": True}, ADMIN))
    ref = validate_success(api.create_referral(s["case_id"], {"agency_id": agency["id"]}, CASEWORKER),
                           expected_status=201)
    assert ref["status"] == "DRAFT"
    case = validate_success(api.get_case(s["case_id"], CASEWORKER))
    assert case["status"] == "AWAITING_AGENCY"


# --- Difficulty: compensating_invariant / agency_open_referral_count_conserved ---

def test_agency_count_incremented_on_send(api):
    """PRD §3.5: "Sending stamps `sent_at` with the current clock and increments the
    agency's `open_referral_count` by one."

    Design: Difficulty/compensating_invariant/agency_open_referral_count_conserved
    """
    s = sent_referral(api)
    agency = validate_success(api.get_agency(s["agency_id"], ADMIN))
    assert agency["open_referral_count"] == 1, "send must raise the ledger to 1"


def test_agency_count_restored_after_resolve(api):
    """PRD §3.5: "`closed_reason` is set to `RESOLVED`, the agency's `open_referral_count`
    is decremented by one, and the parent case is returned from `AWAITING_AGENCY` to
    `IN_PROGRESS`".

    Design: Difficulty/compensating_invariant/agency_open_referral_count_conserved
    """
    s = sent_referral(api)
    validate_success(api.resolve_referral(s["ref_id"], {"response_summary": "closed"}, CASEWORKER))
    agency = validate_success(api.get_agency(s["agency_id"], ADMIN))
    assert agency["open_referral_count"] == 0, "resolve must restore the ledger to its pre-send value 0"


# --- Corner: state_machines / referral_resolve_from_draft_rejected ---

def test_referral_resolve_from_draft_rejected(api):
    """PRD §3.5: "Both branches are valid only from `SENT`; an attempt from any other
    state yields `ERR_REFERRAL_INVALID_STATE`."

    Design: Corner/state_machines/referral_resolve_from_draft_rejected
    """
    s = referred_case(api)  # referral in DRAFT (not sent)
    resp = api.resolve_referral(s["ref_id"], {}, CASEWORKER)
    validate_error(resp, ApiErrorId.ERR_REFERRAL_INVALID_STATE)
    agency = validate_success(api.get_agency(s["agency_id"], ADMIN))
    assert agency["open_referral_count"] == 0, "DRAFT referral must not touch the ledger"


# --- Corner: endpoints / referrals_reverse_lookup_by_case ---

def test_referrals_reverse_lookup_by_case(api):
    """PRD §3.5: "Referrals of a case can be listed as a nested reverse lookup on
    `case_id`".

    Design: Corner/endpoints/referrals_reverse_lookup_by_case
    """
    s = referred_case(api)
    resp = api.list_case_referrals(s["case_id"], CASEWORKER)
    data, _meta = validate_paginated(resp)
    assert len(data) == 1, f"expected 1 referral, got {len(data)}"
    assert data[0]["id"] == s["ref_id"]
    assert data[0]["case_id"] == s["case_id"]
