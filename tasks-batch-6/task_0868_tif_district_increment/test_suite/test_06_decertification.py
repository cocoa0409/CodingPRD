"""District decertification: senior-debt gating, note resolution, and surplus sweep."""
from test_helpers import (
    api_client, validate_success, validate_error, ApiErrorId, TEST_USERS,
    decertify_payload,
    setup_certified_district, capture_increment, register_bond,
    register_developer_note, create_developer_entity, decertify, get_fund,
)

ADMIN = TEST_USERS["municipal_admin_headers"]
SINGLE = [("School", "SCHOOL", 0.05)]


def _bodies_by_id(district_id):
    rows = validate_success(api_client.get_district_taxing_bodies(district_id, ADMIN))
    return {r["id"]: r for r in rows}


# ─── Difficulty: transitive cascade — decertify sweep to taxing bodies ─────

def test_decertify_expiration_defeases_note_and_closes_fund():
    """PRD 3.7: "On expiration every `REGISTERED` `DEVELOPER_NOTE` of the district is
    forgiven — it transitions from `REGISTERED` to `DEFEASED`, and its
    `principal_remaining_cents`, `accrued_interest_cents`, and
    `outstanding_balance_cents` are all set to zero."
    PRD 3.7: "The fund's `lifetime_surplus_cents` increases by the total swept, its
    `balance_cents` is drawn down to zero, and its `status` becomes `CLOSED`."

    Design: Difficulty/transitive_cascade/decertify_sweep_to_taxing_bodies
    """
    ctx = setup_certified_district(surplus_policy="GROSS", base_eav_cents=100_000_000)
    d_id = ctx["district"]["id"]
    capture_increment(d_id, 2026, 112_500_013)  # fund 970,001
    dev = create_developer_entity(legal_name="Acme Dev", contact_email="a@x.com")
    note = register_developer_note(d_id, dev["id"], principal_cents=5_000_000,
                                   final_maturity_tax_year=2035, priority_rank=1)
    decertified = decertify(d_id, "EXPIRATION", 2048)
    assert decertified["status"] == "DECERTIFIED"
    updated_note = validate_success(api_client.get_obligation(note["id"], ADMIN))
    assert updated_note["status"] == "DEFEASED"
    assert updated_note["outstanding_balance_cents"] == 0
    fund = get_fund(d_id)
    assert fund["status"] == "CLOSED"
    assert fund["balance_cents"] == 0


def test_decertify_sweep_credits_taxing_bodies():
    """PRD 3.7: "creating one `SurplusDistribution` row per body with its `source`
    set to `DECERTIFICATION`, and each such row adds its `amount_cents` to the
    recipient body's `total_surplus_received_cents`."

    Design: Difficulty/transitive_cascade/decertify_sweep_to_taxing_bodies
    """
    ctx = setup_certified_district(surplus_policy="GROSS", base_eav_cents=100_000_000)
    d_id = ctx["district"]["id"]
    school, county, city = [b["id"] for b in ctx["bodies"]]
    capture_increment(d_id, 2026, 112_500_013)  # fund 970,001
    dev = create_developer_entity(legal_name="Acme Dev", contact_email="a@x.com")
    register_developer_note(d_id, dev["id"], principal_cents=5_000_000,
                            final_maturity_tax_year=2035, priority_rank=1)
    decertify(d_id, "EXPIRATION", 2048)
    bodies = _bodies_by_id(d_id)
    assert bodies[school]["total_surplus_received_cents"] == 606_251
    assert bodies[county]["total_surplus_received_cents"] == 242_500
    assert bodies[city]["total_surplus_received_cents"] == 121_250


# ─── Difficulty: cross-entity dependency — decertify blocked by senior bond ─

def test_decertify_expiration_blocked_by_outstanding_senior_bond():
    """PRD 3.7: "Regardless of type, decertification is blocked while any `SENIOR`
    bond obligation of the district is not yet in `SATISFIED` or `DEFEASED`; such an
    attempt is rejected with `ERR_SENIOR_OBLIGATION_OUTSTANDING`".

    Design: Difficulty/cross_entity_state_dependency/decertify_blocked_by_outstanding_senior_bond
    """
    ctx = setup_certified_district(bodies=SINGLE, base_eav_cents=1_000_000_000)
    d_id = ctx["district"]["id"]
    register_bond(d_id, principal_cents=20_000_000, final_maturity_tax_year=2040,
                  priority_rank=1)  # outstanding 20,000,000, never satisfied
    resp = api_client.decertify_district(
        d_id, decertify_payload("EXPIRATION", 2048), ADMIN)
    validate_error(resp, ApiErrorId.ERR_SENIOR_OBLIGATION_OUTSTANDING, expected_status=409)
    district = validate_success(api_client.get_district(d_id, ADMIN))
    assert district["status"] == "CERTIFIED"


def test_decertify_early_also_blocked_by_outstanding_senior_bond():
    """PRD 3.7: "Regardless of type, decertification is blocked while any `SENIOR`
    bond obligation of the district is not yet in `SATISFIED` or `DEFEASED`; such an
    attempt is rejected with `ERR_SENIOR_OBLIGATION_OUTSTANDING`, since senior debt
    must be cleared before the district can wind down."

    Design: Difficulty/cross_entity_state_dependency/decertify_blocked_by_outstanding_senior_bond
    """
    ctx = setup_certified_district(bodies=SINGLE, base_eav_cents=1_000_000_000)
    d_id = ctx["district"]["id"]
    register_bond(d_id, principal_cents=20_000_000, final_maturity_tax_year=2040,
                  priority_rank=1)
    resp = api_client.decertify_district(
        d_id, decertify_payload("EARLY", 2030), ADMIN)  # 2030 < expiration 2048
    validate_error(resp, ApiErrorId.ERR_SENIOR_OBLIGATION_OUTSTANDING, expected_status=409)


# ─── Corner: decertify state / term validations ───────────────────────────

def test_decertify_already_decertified_rejected():
    """PRD 3.7: "a district already in `DECERTIFIED` cannot be decertified again and
    other write attempts against it are rejected with
    `ERR_DISTRICT_ALREADY_DECERTIFIED`."

    Design: Corner/state_machines/decertify_already_decertified_rejected
    """
    ctx = setup_certified_district(bodies=SINGLE, base_eav_cents=100_000_000)
    d_id = ctx["district"]["id"]
    decertify(d_id, "EXPIRATION", 2048)
    resp = api_client.decertify_district(
        d_id, decertify_payload("EXPIRATION", 2049), ADMIN)
    validate_error(resp, ApiErrorId.ERR_DISTRICT_ALREADY_DECERTIFIED, expected_status=409)


def test_decertify_expiration_before_term_returns_term_not_expired():
    """PRD 3.7: "the `termination_tax_year` must be at least the district's
    `expiration_tax_year`, and a premature expiration attempt is rejected with
    `ERR_TERM_NOT_EXPIRED`."

    Design: Corner/validations/decertify_expiration_before_term_returns_term_not_expired
    """
    ctx = setup_certified_district(bodies=SINGLE, base_eav_cents=100_000_000)
    d_id = ctx["district"]["id"]
    resp = api_client.decertify_district(
        d_id, decertify_payload("EXPIRATION", 2030), ADMIN)  # 2030 < 2048
    validate_error(resp, ApiErrorId.ERR_TERM_NOT_EXPIRED, expected_status=409)


def test_decertify_early_after_term_returns_not_allowed():
    """PRD 3.7: "the `termination_tax_year` must be strictly less than the district's
    `expiration_tax_year`, and an early attempt on an already-expired district is
    rejected with `ERR_EARLY_TERM_NOT_ALLOWED`."

    Design: Corner/validations/decertify_early_after_term_returns_not_allowed
    """
    ctx = setup_certified_district(bodies=SINGLE, base_eav_cents=100_000_000)
    d_id = ctx["district"]["id"]
    resp = api_client.decertify_district(
        d_id, decertify_payload("EARLY", 2048), ADMIN)  # 2048 >= expiration 2048
    validate_error(resp, ApiErrorId.ERR_EARLY_TERM_NOT_ALLOWED, expected_status=409)
