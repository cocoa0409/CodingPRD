"""Creation, retrieval, and reverse-FK listing across the peer entities."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId,
    create_party_payload, create_neutral_payload, create_deposit_payload,
    create_exchange_payload, create_award_payload, create_hearing_payload,
    add_candidate_payload,
)
from test_helpers.fixtures import (
    ADMIN, create_case, create_neutral, add_two_parties, open_selection,
    case_version, setup_hearing_case,
)

ADM = ADMIN


# ---- Party --------------------------------------------------------------

def test_create_party_returns_201_with_strike_defaults(api):
    """PRD 3.1: "A new party begins with `strikes_used` of 0 and `strikes_remaining`
    equal to the case's `strikes_per_party`."

    Design: Corner/entities/create_party_returns_201_with_strike_defaults
    """
    case = create_case(api, claim_amount_cents=500_000, strikes_per_party=2)
    resp = api.create_party(create_party_payload(
        case_id=case["id"], role="CLAIMANT", display_name="Cl", share_pct=100), ADM)
    data = validate_success(resp, 201)
    assert data["strikes_used"] == 0
    assert data["strikes_remaining"] == 2


def test_create_party_case_not_found(api):
    """PRD 2.8: "every foreign-key reference in the body resolves to a real resource ...
    the first one that does not resolve produces `ERR_NOT_FOUND` (404)".

    Design: Corner/entities/create_party_case_not_found
    """
    resp = api.create_party(create_party_payload(
        case_id="00000000-0000-0000-0000-000000000000", role="CLAIMANT",
        display_name="X", share_pct=100), ADM)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_list_parties_of_case_reverse_fk(api):
    """PRD 4 (endpoint): "List parties of a case". PRD 3.1: "A `CaseAdministrator` adds a
    **Party** to a case by supplying the party's `case_id`".

    Design: Corner/entities/list_parties_of_case_reverse_fk
    """
    case = create_case(api, claim_amount_cents=500_000)
    pA, pB = add_two_parties(api, case["id"])
    data = validate_success(api.list_case_parties(case["id"], ADM), 200)
    ids = {p["id"] for p in data}
    assert pA["id"] in ids and pB["id"] in ids
    assert len(data) == 2


# ---- Neutral ------------------------------------------------------------

def test_create_neutral_returns_201_active_roster(api):
    """PRD 3.2: "A new neutral joins with `roster_status` of `ACTIVE`".

    Design: Corner/entities/create_neutral_returns_201_active_roster
    """
    resp = api.create_neutral(create_neutral_payload(
        full_name="Judge X", neutral_type="ARBITRATOR", hourly_rate_cents=50_000), ADM)
    data = validate_success(resp, 201)
    assert data["roster_status"] == "ACTIVE"


def test_list_neutrals_filtered_by_roster_status(api):
    """PRD 4 (endpoint): "List roster (paginated; optional roster_status filter)". PRD
    3.2: "roster management can move a neutral among `ACTIVE`, `SUSPENDED`, and
    `RETIRED`."

    Design: Corner/entities/list_neutrals_filtered_by_roster_status
    """
    validate_success(api.create_neutral(create_neutral_payload(full_name="Active One"), ADM), 201)
    susp = validate_success(api.create_neutral(create_neutral_payload(full_name="Susp One"), ADM), 201)
    validate_success(api.transition_neutral(susp["id"], {"roster_status": "SUSPENDED"}, ADM), 200)
    data, _ = validate_paginated(api.list_neutrals(ADM, params={"roster_status": "SUSPENDED"}))
    assert all(n["roster_status"] == "SUSPENDED" for n in data)
    assert any(n["id"] == susp["id"] for n in data)


def test_neutral_roster_transition_to_suspended(api):
    """PRD 3.2: "roster management can move a neutral among `ACTIVE`, `SUSPENDED`, and
    `RETIRED`."

    Design: Corner/endpoints/neutral_roster_transition_to_suspended
    """
    n = validate_success(api.create_neutral(create_neutral_payload(full_name="Susp Target"), ADM), 201)
    data = validate_success(api.transition_neutral(n["id"], {"roster_status": "SUSPENDED"}, ADM), 200)
    assert data["roster_status"] == "SUSPENDED"


# ---- Candidate ----------------------------------------------------------

def _selection_case(api):
    n = create_neutral(api)
    case = create_case(api, claim_amount_cents=500_000)
    add_two_parties(api, case["id"])
    open_selection(api, case["id"])
    return case, n


def test_create_candidate_returns_201_proposed(api):
    """PRD 3.3: "Adding a candidate names the case in the path and supplies the roster
    `neutral_id` to propose; the new candidate enters `PROPOSED`."

    Design: Corner/entities/create_candidate_returns_201_proposed
    """
    case, n = _selection_case(api)
    v = case_version(api, case["id"])
    resp = api.add_candidate(case["id"], add_candidate_payload(
        neutral_id=n["id"], expected_case_version=v), ADM)
    data = validate_success(resp, 201)
    assert data["status"] == "PROPOSED"
    assert data["neutral_id"] == n["id"]


def test_add_candidate_neutral_not_found(api):
    """PRD 2.8: "every foreign-key reference in the body resolves to a real resource ...
    produces `ERR_NOT_FOUND` (404)".

    Design: Corner/entities/add_candidate_neutral_not_found
    """
    case, _ = _selection_case(api)
    v = case_version(api, case["id"])
    resp = api.add_candidate(case["id"], add_candidate_payload(
        neutral_id="00000000-0000-0000-0000-000000000000", expected_case_version=v), ADM)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_list_candidacies_of_neutral_reverse_fk(api):
    """PRD 4 (endpoint): "List candidacies of a neutral". PRD 3.3: "Adding a candidate
    names the case in the path and supplies the roster `neutral_id`".

    Design: Corner/entities/list_candidacies_of_neutral_reverse_fk
    """
    case, n = _selection_case(api)
    v = case_version(api, case["id"])
    cand = validate_success(api.add_candidate(case["id"], add_candidate_payload(
        neutral_id=n["id"], expected_case_version=v), ADM), 201)
    data = validate_success(api.list_neutral_candidates(n["id"], ADM), 200)
    assert len(data) == 1
    assert data[0]["id"] == cand["id"]


# ---- Hearing ------------------------------------------------------------

def test_create_hearing_returns_201_scheduled_with_duration(api):
    """PRD 3.6: "A new hearing is `SCHEDULED`, and the system records its
    `duration_hours` as the length of the interval in hours".

    Design: Corner/entities/create_hearing_returns_201_scheduled_with_duration
    """
    ctx = setup_hearing_case(api, clock="2026-06-01T00:00:00Z")
    resp = api.create_hearing(ctx["case"]["id"], create_hearing_payload(
        hearing_type="EVIDENTIARY", start_at="2026-06-20T09:00:00Z",
        end_at="2026-06-20T12:00:00Z", location="Room A"), ADM)
    data = validate_success(resp, 201)
    assert data["status"] == "SCHEDULED"
    assert data["duration_hours"] == 3


# ---- Exchange -----------------------------------------------------------

def test_create_exchange_returns_201_pending_and_reverse_fk_list(api):
    """PRD 3.7: "A new exchange is `PENDING`, and its `submitted_at` is null until it is
    submitted." PRD 4 (endpoint): "List exchanges of a case".

    Design: Corner/entities/create_exchange_returns_201_pending_and_reverse_fk_list
    """
    case = create_case(api, claim_amount_cents=500_000)
    ex = validate_success(api.create_exchange(case["id"], create_exchange_payload(
        exchange_type="EXHIBITS", due_at="2026-06-10T00:00:00Z"), ADM), 201)
    assert ex["status"] == "PENDING"
    data = validate_success(api.list_case_exchanges(case["id"], ADM), 200)
    found = [e for e in data if e["id"] == ex["id"]]
    assert found and found[0]["status"] == "PENDING"


# ---- Deposit ------------------------------------------------------------

def test_create_deposit_returns_201_requested_and_filtered_list(api):
    """PRD 3.8: "a new deposit is `REQUESTED` with a null `paid_at`." PRD 4 (endpoint):
    "List deposits (paginated; optional case_id filter)".

    Design: Corner/entities/create_deposit_returns_201_requested_and_filtered_list
    """
    case = create_case(api, claim_amount_cents=500_000)
    dep = validate_success(api.create_deposit(create_deposit_payload(
        case_id=case["id"], amount_cents=100_000), ADM), 201)
    assert dep["status"] == "REQUESTED"
    data, _ = validate_paginated(api.list_deposits(ADM, params={"case_id": case["id"]}))
    found = [d for d in data if d["id"] == dep["id"]]
    assert found and found[0]["status"] == "REQUESTED"


# ---- Award --------------------------------------------------------------

def test_create_award_returns_201_draft_and_reverse_fk_list(api):
    """PRD 3.9: "A `CaseAdministrator` drafts an **Award** for a case that is in
    `HEARING` ... A new award is `DRAFT` with a null `issued_at`." PRD 4 (endpoint):
    "List awards of a case".

    Design: Corner/entities/create_award_returns_201_draft_and_reverse_fk_list
    """
    ctx = setup_hearing_case(api, claim_amount_cents=2_000_000)
    aw = validate_success(api.create_award(ctx["case"]["id"], create_award_payload(
        award_type="MONETARY", award_amount_cents=500_000), ADM), 201)
    assert aw["status"] == "DRAFT"
    data = validate_success(api.list_case_awards(ctx["case"]["id"], ADM), 200)
    found = [a for a in data if a["id"] == aw["id"]]
    assert found and found[0]["status"] == "DRAFT"
