"""Obligation proposal, review cycle, registration, interest, and ownership."""
from test_helpers import (
    api_client, validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    create_obligation_payload, register_obligation_payload, accrue_interest_payload,
    setup_certified_district, propose_submit_bond, register_bond,
    create_developer_entity, propose_submit_note, district_version,
    make_admin_headers, make_developer_headers, ADMIN_1_ID,
)

ADMIN = TEST_USERS["municipal_admin_headers"]
SINGLE = [("School", "SCHOOL", 0.05)]


# ─── Difficulty: non-linear state machine — obligation review revision cycle ─

def test_obligation_return_resubmit_register_reaches_registered():
    """PRD 3.3: "A reviewing `MunicipalAdmin` may bounce a proposal back for
    revision, returning it from `UNDER_REVIEW` to `PROPOSED`".
    PRD 3.3: "Registration advances the obligation from `UNDER_REVIEW` to
    `REGISTERED` and requires four things: the obligation is in `UNDER_REVIEW`, else
    `ERR_OBLIGATION_NOT_IN_REVIEW`".
    PRD 3.3: "On success the obligation's `seniority` is derived from its type — a
    `BOND` becomes `SENIOR`, a `DEVELOPER_NOTE` becomes `SUBORDINATE`".

    Design: Difficulty/non_linear_state_machine/obligation_review_revision_cycle
    """
    ctx = setup_certified_district(bodies=SINGLE, base_eav_cents=100_000_000)
    d_id = ctx["district"]["id"]
    ob = propose_submit_bond(d_id, principal_cents=5_000_000, interest_rate_bps=0,
                             issue_tax_year=2026, final_maturity_tax_year=2035)
    api_client.return_obligation(ob["id"], ADMIN)      # UNDER_REVIEW -> PROPOSED
    api_client.submit_obligation(ob["id"], ADMIN)      # PROPOSED -> UNDER_REVIEW
    registered = validate_success(api_client.register_obligation(
        ob["id"], register_obligation_payload(1, district_version(d_id)),
        make_admin_headers(ADMIN_1_ID)))
    assert registered["status"] == "REGISTERED"
    assert registered["seniority"] == "SENIOR"


def test_obligation_return_sends_under_review_back_to_proposed():
    """PRD 3.3: "Submitting an obligation advances it from `PROPOSED` to
    `UNDER_REVIEW`".
    PRD 3.3: "A reviewing `MunicipalAdmin` may bounce a proposal back for revision,
    returning it from `UNDER_REVIEW` to `PROPOSED`".

    Design: Difficulty/non_linear_state_machine/obligation_review_revision_cycle
    """
    ctx = setup_certified_district(bodies=SINGLE, base_eav_cents=100_000_000)
    d_id = ctx["district"]["id"]
    ob = propose_submit_bond(d_id, principal_cents=5_000_000)
    assert ob["status"] == "UNDER_REVIEW"
    returned = validate_success(api_client.return_obligation(ob["id"], ADMIN))
    assert returned["status"] == "PROPOSED"
    resubmitted = validate_success(api_client.submit_obligation(ob["id"], ADMIN))
    assert resubmitted["status"] == "UNDER_REVIEW"


# ─── Corner: entities / state machines ─────────────────────────────────────

def test_register_sets_seniority_and_principal_remaining():
    """PRD 3.3: "On success the obligation's `seniority` is derived from its type — a
    `BOND` becomes `SENIOR`, a `DEVELOPER_NOTE` becomes `SUBORDINATE`; its
    `principal_remaining_cents` is initialized to the full `principal_cents`".

    Design: Corner/entities/obligation_register_sets_seniority_computed
    """
    ctx = setup_certified_district(bodies=SINGLE, base_eav_cents=100_000_000)
    d_id = ctx["district"]["id"]
    ob = propose_submit_bond(d_id, principal_cents=5_000_000)
    registered = validate_success(api_client.register_obligation(
        ob["id"], register_obligation_payload(1, district_version(d_id)),
        make_admin_headers(ADMIN_1_ID)))
    assert registered["seniority"] == "SENIOR"
    assert registered["status"] == "REGISTERED"
    assert registered["principal_remaining_cents"] == 5_000_000


def test_register_proposed_obligation_returns_not_in_review():
    """PRD 3.3: "Registration advances the obligation from `UNDER_REVIEW` to
    `REGISTERED` and requires four things: the obligation is in `UNDER_REVIEW`, else
    `ERR_OBLIGATION_NOT_IN_REVIEW`".

    Design: Corner/state_machines/register_from_proposed_returns_not_in_review
    """
    ctx = setup_certified_district(bodies=SINGLE, base_eav_cents=100_000_000)
    d_id = ctx["district"]["id"]
    ob = validate_success(api_client.create_obligation(
        create_obligation_payload(d_id, "BOND", principal_cents=5_000_000,
                                  final_maturity_tax_year=2035), ADMIN),
        expected_status=201)
    resp = api_client.register_obligation(
        ob["id"], register_obligation_payload(1, district_version(d_id)),
        make_admin_headers(ADMIN_1_ID))
    validate_error(resp, ApiErrorId.ERR_OBLIGATION_NOT_IN_REVIEW, expected_status=409)


def test_submit_rejected_obligation_returns_invalid_state():
    """PRD 3.3: "Submitting anything not in `PROPOSED` is rejected with
    `ERR_OBLIGATION_INVALID_STATE`."

    Design: Corner/state_machines/submit_rejected_obligation_returns_invalid_state
    """
    ctx = setup_certified_district(bodies=SINGLE, base_eav_cents=100_000_000)
    d_id = ctx["district"]["id"]
    ob = propose_submit_bond(d_id, principal_cents=5_000_000)
    api_client.reject_obligation(ob["id"], ADMIN)      # UNDER_REVIEW -> REJECTED
    resp = api_client.submit_obligation(ob["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_OBLIGATION_INVALID_STATE, expected_status=409)


# ─── Corner: calculations — interest accrual ───────────────────────────────

def test_accrue_interest_one_year_updates_accrued_and_outstanding():
    """PRD 3.3: "Each accrual computes the period's interest as the
    `principal_remaining_cents` multiplied by `interest_rate_bps`, divided by ten
    thousand, rounded half up to whole cents".
    PRD 3.3: "That period interest is added to `accrued_interest_cents`, and
    `outstanding_balance_cents` is reset to the sum of `principal_remaining_cents` and
    `accrued_interest_cents`."

    Design: Corner/calculations/obligation_interest_accrual_correct
    """
    ctx = setup_certified_district(bodies=SINGLE, base_eav_cents=100_000_000)
    d_id = ctx["district"]["id"]
    ob = register_bond(d_id, principal_cents=20_000_000, interest_rate_bps=500,
                       final_maturity_tax_year=2040, priority_rank=1)
    accrued = validate_success(api_client.accrue_interest(
        ob["id"], accrue_interest_payload(2026), ADMIN))
    assert accrued["accrued_interest_cents"] == 1_000_000
    assert accrued["outstanding_balance_cents"] == 21_000_000


# ─── Corner: validations — bond maturity within term ───────────────────────

def test_register_bond_maturity_beyond_expiration_rejected():
    """PRD 3.3: "the `final_maturity_tax_year` is no later than the district's
    `expiration_tax_year`, else `ERR_BOND_MATURITY_OUT_OF_TERM`".

    Design: Corner/validations/register_bond_maturity_out_of_term
    """
    ctx = setup_certified_district(bodies=SINGLE, base_eav_cents=100_000_000,
                                   base_tax_year=2025, term_years=23)  # expiration 2048
    d_id = ctx["district"]["id"]
    ob = propose_submit_bond(d_id, principal_cents=5_000_000,
                             final_maturity_tax_year=2049)
    resp = api_client.register_obligation(
        ob["id"], register_obligation_payload(1, district_version(d_id)),
        make_admin_headers(ADMIN_1_ID))
    validate_error(resp, ApiErrorId.ERR_BOND_MATURITY_OUT_OF_TERM, expected_status=409)


# ─── Corner: rbac — developer ownership ────────────────────────────────────

def test_developer_submitting_others_note_unauthorized():
    """PRD 3.3: "a `Developer` may submit only its own `DEVELOPER_NOTE` (ownership
    again compares `X-User-ID` to the note's `developer_id`)".
    PRD 2.1: "A developer acting on an obligation whose `developer_id` is not its own
    is rejected with `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/developer_submit_others_obligation_unauthorized
    """
    ctx = setup_certified_district(bodies=SINGLE, base_eav_cents=100_000_000)
    d_id = ctx["district"]["id"]
    dev_a = create_developer_entity(legal_name="Dev A", contact_email="a@x.com")
    dev_b = create_developer_entity(legal_name="Dev B", contact_email="b@x.com")
    note = validate_success(api_client.create_obligation(
        create_obligation_payload(d_id, "DEVELOPER_NOTE", developer_id=dev_a["id"],
                                  principal_cents=3_000_000, final_maturity_tax_year=2035),
        make_developer_headers(dev_a["id"])), expected_status=201)
    resp = api_client.submit_obligation(note["id"], make_developer_headers(dev_b["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, expected_status=403)


# ─── Corner: endpoints — developer reverse lookup ──────────────────────────

def test_developer_obligations_reverse_lookup():
    """PRD 2.1: "Proposes and submits developer-note obligations for its own account
    and views its own obligations."

    Design: Corner/endpoints/developer_obligations_reverse_lookup
    """
    ctx = setup_certified_district(bodies=SINGLE, base_eav_cents=100_000_000)
    d_id = ctx["district"]["id"]
    dev = create_developer_entity(legal_name="Rev Dev", contact_email="r@x.com")
    note = validate_success(api_client.create_obligation(
        create_obligation_payload(d_id, "DEVELOPER_NOTE", developer_id=dev["id"],
                                  principal_cents=3_000_000, final_maturity_tax_year=2035),
        make_developer_headers(dev["id"])), expected_status=201)
    data = validate_success(api_client.get_developer_obligations(
        dev["id"], make_developer_headers(dev["id"])))
    ids = [o["id"] for o in data]
    assert note["id"] in ids
    match = next(o for o in data if o["id"] == note["id"])
    assert match["developer_id"] == dev["id"]


# ─── Corner: OCC — stale district version on register ──────────────────────

def test_register_second_obligation_with_stale_district_version_rejected():
    """PRD 2.6: "Registering an obligation must carry `expected_district_version`
    matching the current `version` of the obligation's `TifDistrict`."
    PRD 2.6: "if the district's `version` has advanced since the client last read it
    — because another obligation was registered or the district otherwise mutated —
    the registration is rejected with `ERR_STALE_DISTRICT_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_register_stale_district_version
    """
    ctx = setup_certified_district(bodies=SINGLE, base_eav_cents=100_000_000)
    d_id = ctx["district"]["id"]
    d_ver = ctx["version"]
    ob_a = propose_submit_bond(d_id, principal_cents=5_000_000)
    ob_b = propose_submit_bond(d_id, principal_cents=6_000_000)
    validate_success(api_client.register_obligation(
        ob_a["id"], register_obligation_payload(1, d_ver), make_admin_headers(ADMIN_1_ID)))
    resp = api_client.register_obligation(
        ob_b["id"], register_obligation_payload(2, d_ver), make_admin_headers(ADMIN_1_ID))
    validate_error(resp, ApiErrorId.ERR_STALE_DISTRICT_VERSION, expected_status=412)
