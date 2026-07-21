"""Property onboarding, renter creation, and underwriting decisions."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    TEST_USERS, assert_property, assert_renter, assert_application,
    create_property_payload, create_renter_payload, submit_application_payload,
    create_property, create_renter, submit_application,
    create_enrolled_renter,
)

ADMIN = TEST_USERS["platform_admin_headers"]
UNDERWRITER = TEST_USERS["underwriter_headers"]


# ---------------------------------------------------------------------------
# Corner: entities
# ---------------------------------------------------------------------------

def test_property_creation_returns_all_fields(api):
    """PRD §3.1: "the property's `status` field is a computed mirror of it — whenever
    the integration status is set, the listing-facing `status` is updated to the same
    value."
    PRD §2.4: "an integer `version` that starts at 1 on creation and increments by one
    on each mutation that changes the resource."

    Design: Corner/entities/property_creation_returns_all_fields
    """
    resp = api.create_property(create_property_payload(
        landlord_name="Ada", unit_label="Oak #1", full_rent_cents=90000,
        rent_due_day=1, remittance_account_ref="acct_c1", integration_status="ACTIVE"), ADMIN)
    data = validate_success(resp, 201)
    assert_property(data)
    assert data["full_rent_cents"] == 90000
    assert data["status"] == "ACTIVE"
    assert data["version"] == 1


def test_renter_created_with_system_defaults(api):
    """PRD §3.2: "On creation the renter's `risk_band` is null, its `approved_limit_cents`
    is 0, and its `autopay_enabled` flag is false."
    PRD §3.2: "A newly created renter's enrollment `status` is `PROSPECT`".

    Design: Corner/entities/renter_system_fields_ignore_client_input
    """
    prop = create_property(api, unit_label="Oak #4")
    resp = api.create_renter(create_renter_payload(prop["id"], email="c4@x.com",
                                                   full_name="C Four",
                                                   portion_rent_cents=80000), ADMIN)
    data = validate_success(resp, 201)
    assert_renter(data)
    assert data["status"] == "PROSPECT"
    assert data["approved_limit_cents"] == 0
    assert data["autopay_enabled"] is False


def test_property_missing_full_rent_returns_validation(api):
    """PRD §2.9: "then body well-formedness for write endpoints — required fields present,
    enums valid, integers of the correct type and within their declared syntactic range
    such as `rent_due_day` between 1 and 28, else `ERR_VALIDATION` (HTTP 400)".

    Design: Corner/entities/property_missing_required_field_returns_validation
    """
    resp = api.create_property({
        "landlord_name": "Ada", "unit_label": "Oak #2",
        "rent_due_day": 1, "remittance_account_ref": "acct_c2",
    }, ADMIN)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value, 400)


def test_application_prior_delinquency_defaults_zero(api):
    """PRD §3.2: "optionally a self-declared `prior_delinquency_count` of past rent
    delinquencies (a non-negative integer defaulting to 0)."
    PRD §3.2: "The **delinquency** sub-score is 100 when the prior delinquency count is 0,
    60 when it is exactly 1, and 20 otherwise."

    Design: Corner/entities/application_prior_delinquency_defaults_zero
    """
    prop = create_property(api, unit_label="Oak #3")
    renter = create_renter(prop["id"], api, email="c3@x.com", portion_rent_cents=100000)
    resp = api.submit_application(renter["id"], {
        "reported_monthly_income_cents": 300000, "requested_split_count": 2}, ADMIN)
    data = validate_success(resp, 201)
    assert data["prior_delinquency_count"] == 0
    assert data["risk_score"] == 100
    assert data["risk_band"] == "LOW"


# ---------------------------------------------------------------------------
# Difficulty: combinatorial_formula / underwriting_weighted_tiered_score
# ---------------------------------------------------------------------------

def test_underwriting_weighted_tiered_risk_score(api):
    """PRD §3.2: "The overall `risk_score` is the ratio sub-score weighted at one-half,
    plus the split sub-score weighted at one-fifth, plus the delinquency sub-score weighted
    at three-tenths, with the weighted total rounded half up to a whole integer on a
    0-to-100 scale where higher is safer."
    PRD §3.2: "its sub-score is 100 when the ratio is at least 3.0, otherwise 70 when it is
    at least 2.0, otherwise 40 when it is at least 1.5, otherwise 10."

    Design: Difficulty/combinatorial_formula/underwriting_weighted_tiered_score
    """
    prop = create_property(api, unit_label="Maple #4")
    renter = create_renter(prop["id"], api, email="r4@x.com", portion_rent_cents=100000)
    resp = api.submit_application(renter["id"], {
        "reported_monthly_income_cents": 200000, "requested_split_count": 3,
        "prior_delinquency_count": 1}, ADMIN)
    data = validate_success(resp, 201)
    # ratio 2.0 -> 70, split 3 -> 70, delinq 1 -> 60; round(0.5*70+0.2*70+0.3*60)=67
    assert data["risk_score"] == 67


def test_underwriting_weighted_band_and_limit(api):
    """PRD §3.2: "`LOW` when the score is at least 75, `MEDIUM` when it is at least 50
    (but below 75), and `HIGH` otherwise."
    PRD §3.2: "The `approved_limit_cents` is the smaller of two ceilings: the renter's
    financed portion multiplied by a band factor — 3 for a `LOW` band, 2 for a `MEDIUM`
    band, and 1 for a `HIGH` band — and one-half of the reported monthly income rounded
    half up to whole cents."

    Design: Difficulty/combinatorial_formula/underwriting_weighted_tiered_score
    """
    prop = create_property(api, unit_label="Maple #4b")
    renter = create_renter(prop["id"], api, email="r4b@x.com", portion_rent_cents=100000)
    resp = api.submit_application(renter["id"], {
        "reported_monthly_income_cents": 200000, "requested_split_count": 3,
        "prior_delinquency_count": 1}, ADMIN)
    data = validate_success(resp, 201)
    assert data["risk_band"] == "MEDIUM"
    # min(100000*2, round(200000*0.5)) = min(200000, 100000) = 100000
    assert data["approved_limit_cents"] == 100000


def test_decision_on_already_decided_application_invalid_state(api):
    """PRD §3.2: "A decision on an application that is not `SUBMITTED` is rejected with
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/decision_on_already_decided_application_invalid_state
    """
    ctx = create_enrolled_renter(api, unit_label="Oak #7")
    app_id = ctx["application"]["id"]
    resp = api.decide_application(app_id, {"decision": "DECLINE"}, UNDERWRITER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


# ---------------------------------------------------------------------------
# Difficulty: transitive_cascade / application_approval_cascade_renter_mandate
# ---------------------------------------------------------------------------

def test_approval_cascade_enrolls_renter(api):
    """PRD §3.2: "the renter's `status` becomes `ENROLLED` (from `PROSPECT` or
    `UNDERWRITING`), the renter's `approved_limit_cents` and `risk_band` are copied from
    the application, and — if the renter has no mandate yet — an autopay mandate is created
    for them in `PAUSED`."

    Design: Difficulty/transitive_cascade/application_approval_cascade_renter_mandate
    """
    ctx = create_enrolled_renter(api, unit_label="Maple #8", portion_cents=100000,
                                 income_cents=300000)
    renter = ctx["renter"]
    assert renter["status"] == "ENROLLED"
    assert renter["approved_limit_cents"] == 150000  # LOW band: min(100000*3, 150000)
    assert renter["risk_band"] == "LOW"


def test_approval_cascade_creates_paused_mandate(api):
    """PRD §3.3: "Each renter has at most one autopay mandate, created automatically in
    `PAUSED` at the moment their application is approved."

    Design: Difficulty/transitive_cascade/application_approval_cascade_renter_mandate
    """
    ctx = create_enrolled_renter(api, unit_label="Maple #8b")
    resp = api.get_renter_mandate(ctx["renter"]["id"], ADMIN)
    mandates = validate_success(resp)
    assert len(mandates) == 1
    assert mandates[0]["status"] == "PAUSED"
