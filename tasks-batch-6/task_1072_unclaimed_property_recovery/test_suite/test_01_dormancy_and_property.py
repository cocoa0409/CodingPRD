"""Property recording: escheat-state priority, dormancy-date calculation and its
exact-date boundary, and the pre-date not-yet-dormant rejection.

Translates queue A (dual_variant_calc/dormancy divergence, boundary_precision/
dormancy exact date) and queue B (escheat priority, system fields, not-yet-dormant).
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, factories as f, fixtures,
    assert_property,
)
from test_helpers.test_users import make_holder_headers

ADMIN = fixtures.ADMIN


# ---------------------------------------------------------------------------
# Difficulty/dual_variant_calc/dormancy_date_basis_divergence
# ---------------------------------------------------------------------------
def _two_basis_properties(api):
    holder = fixtures.create_holder(api, incorporation_state="NY")
    hh = make_holder_headers(holder["id"])
    pt_act = fixtures.create_property_type(api, code="AC01", dormancy_basis="LAST_ACTIVITY",
                                           dormancy_period_years=3, interest_bearing=True,
                                           due_diligence_required=True, due_diligence_min_days=60)
    pt_iss = fixtures.create_property_type(api, code="MO02", dormancy_basis="ISSUANCE",
                                           dormancy_period_years=3, interest_bearing=False)
    p_act = validate_success(api.create_property(f.create_property_payload(
        holder["id"], pt_act["id"], owner_name="Jane Doe", owner_last_known_state="CA",
        amount_cents=100000, last_activity_date="2020-01-01T00:00:00Z",
        issue_date="2018-06-01T00:00:00Z"), hh), 201)
    p_iss = validate_success(api.create_property(f.create_property_payload(
        holder["id"], pt_iss["id"], owner_name="Jane Doe", owner_last_known_state="CA",
        amount_cents=100000, last_activity_date="2020-01-01T00:00:00Z",
        issue_date="2018-06-01T00:00:00Z"), hh), 201)
    return p_act, p_iss


def test_dormancy_date_uses_last_activity_anchor(api):
    """PRD §3.2: "The anchor for that computation depends on the type's dormancy_basis:
    when the basis is LAST_ACTIVITY, the anchor is the property's last_activity_date;
    when the basis is ISSUANCE, the anchor is the property's issue_date (which must
    therefore be present for issuance-based types)."
    PRD §3.2: "The dormancy date is that anchor advanced forward by exactly the number
    of calendar years in the type's dormancy_period_years."

    last_activity_date 2020-01-01 + 3 years -> 2023-01-01.

    Design: Difficulty/dual_variant_calc/dormancy_date_basis_divergence
    """
    p_act, _ = _two_basis_properties(api)
    assert_property(p_act)
    assert p_act["dormancy_date"].startswith("2023-01-01"), \
        f"LAST_ACTIVITY anchor 2020-01-01 + 3y must be 2023-01-01, got {p_act['dormancy_date']}"


def test_dormancy_date_issuance_anchor_diverges(api):
    """PRD §3.2: "Note that for one and the same property carrying both dates, the
    issuance basis and the last-activity basis generally yield different dormancy dates,
    because they start from different anchors."
    PRD §3.2: "when the basis is ISSUANCE, the anchor is the property's issue_date".

    issue_date 2018-06-01 + 3 years -> 2021-06-01, distinct from the last-activity 2023-01-01.

    Design: Difficulty/dual_variant_calc/dormancy_date_basis_divergence
    """
    p_act, p_iss = _two_basis_properties(api)
    assert p_iss["dormancy_date"].startswith("2021-06-01"), \
        f"ISSUANCE anchor 2018-06-01 + 3y must be 2021-06-01, got {p_iss['dormancy_date']}"
    assert p_iss["dormancy_date"] != p_act["dormancy_date"], \
        "issuance and last-activity bases must yield different dormancy dates"


# ---------------------------------------------------------------------------
# Difficulty/boundary_precision_check/dormancy_exact_date_boundary
# ---------------------------------------------------------------------------
def _active_property_dormant_2023(api):
    holder = fixtures.create_holder(api)
    hh = make_holder_headers(holder["id"])
    pt = fixtures.create_property_type(api, code="AC01", dormancy_basis="LAST_ACTIVITY",
                                       dormancy_period_years=3, interest_bearing=False)
    prop = validate_success(api.create_property(f.create_property_payload(
        holder["id"], pt["id"], owner_last_known_state="CA", amount_cents=50000,
        last_activity_date="2020-01-01T00:00:00Z"), hh), 201)
    return holder, hh, prop


def test_dormancy_at_exact_date_is_dormant(api):
    """PRD §3.2: "The transition succeeds only when the current logical-clock instant is
    at or after the property's dormancy_date; the boundary is inclusive, so a property is
    dormant exactly at its dormancy date."

    dormancy_date 2023-01-01; at clock == 2023-01-01 evaluate-dormancy sets DORMANT.

    Design: Difficulty/boundary_precision_check/dormancy_exact_date_boundary
    """
    holder, hh, prop = _active_property_dormant_2023(api)
    fixtures.set_clock(api, "2023-01-01T00:00:00Z")
    data = validate_success(api.evaluate_dormancy(prop["id"], hh), 200)
    assert data["status"] == "DORMANT", f"exactly-at dormancy_date must be DORMANT, got {data['status']}"


def test_dormancy_day_after_date_is_dormant(api):
    """PRD §3.2: "The transition succeeds only when the current logical-clock instant is
    at or after the property's dormancy_date; the boundary is inclusive, so a property is
    dormant exactly at its dormancy date."

    One day past the dormancy_date (2023-01-02) is also at-or-after, so DORMANT.

    Design: Difficulty/boundary_precision_check/dormancy_exact_date_boundary
    """
    holder, hh, prop = _active_property_dormant_2023(api)
    fixtures.set_clock(api, "2023-01-02T00:00:00Z")
    data = validate_success(api.evaluate_dormancy(prop["id"], hh), 200)
    assert data["status"] == "DORMANT"


# ---------------------------------------------------------------------------
# Corner/entities/property_escheat_state_priority_rule
# ---------------------------------------------------------------------------
def test_escheat_state_priority_rule(api):
    """PRD §2.7: "the system computes its escheat_state ... by a fixed priority rule: if
    the property's owner_last_known_state is present and non-empty, the escheat jurisdiction
    is that state; otherwise it falls back to the incorporation jurisdiction of the holding
    institution (the holder's incorporation_state)."

    NY-incorporated holder: with owner_last_known_state TX -> escheat_state TX; when omitted
    -> escheat_state NY (holder fallback).

    Design: Corner/entities/property_escheat_state_priority_rule
    """
    holder = fixtures.create_holder(api, incorporation_state="NY")
    hh = make_holder_headers(holder["id"])
    pt = fixtures.create_property_type(api, code="MO02", dormancy_basis="ISSUANCE")
    p_tx = validate_success(api.create_property(f.create_property_payload(
        holder["id"], pt["id"], owner_name="TX Owner", owner_last_known_state="TX",
        amount_cents=50000, last_activity_date="2020-01-01T00:00:00Z",
        issue_date="2020-01-01T00:00:00Z"), hh), 201)
    payload = f.create_property_payload(holder["id"], pt["id"], owner_name="Unknown Owner",
                                        amount_cents=50000,
                                        last_activity_date="2020-01-01T00:00:00Z",
                                        issue_date="2020-01-01T00:00:00Z")
    payload.pop("owner_last_known_state", None)
    p_ny = validate_success(api.create_property(payload, hh), 201)
    assert p_tx["escheat_state"] == "TX", f"present state must win, got {p_tx['escheat_state']}"
    assert p_ny["escheat_state"] == "NY", f"omitted state must fall back to holder NY, got {p_ny['escheat_state']}"


# ---------------------------------------------------------------------------
# Corner/entities/property_system_fields_ignored_on_create
# ---------------------------------------------------------------------------
def test_property_created_active_with_server_set_fields(api):
    """PRD §3.2: "A new property is created in status ACTIVE."
    PRD §3.6: "the system snapshots the claim's gross value in claim_amount_cents from the
    property's remitted_amount_cents at that moment" — the freshly created property carries a
    remitted_amount_cents of 0 until escheat.
    PRD §2.4: "version — an integer that starts at 1 on creation and increments by one on
    every mutation."

    Design: Corner/entities/property_system_fields_ignored_on_create
    """
    holder = fixtures.create_holder(api)
    hh = make_holder_headers(holder["id"])
    pt = fixtures.create_property_type(api, code="MO02", dormancy_basis="ISSUANCE")
    prop = validate_success(api.create_property(f.create_property_payload(
        holder["id"], pt["id"], owner_name="Jane", owner_last_known_state="CA",
        amount_cents=50000, last_activity_date="2020-01-01T00:00:00Z",
        issue_date="2020-01-01T00:00:00Z"), hh), 201)
    assert prop["status"] == "ACTIVE"
    assert prop["remitted_amount_cents"] == 0
    assert prop["version"] == 1


# ---------------------------------------------------------------------------
# Corner/validations/evaluate_dormancy_before_date_returns_not_yet_dormant
# ---------------------------------------------------------------------------
def test_evaluate_dormancy_before_date_rejected(api):
    """PRD §3.2: "Attempting the transition before that instant is rejected with
    ERR_NOT_YET_DORMANT (HTTP 409), and this dormancy-evaluation action is defined only
    from the ACTIVE state."

    dormancy_date 2023-01-01; at clock 2022-12-31 (one day before) the request is rejected
    and the property stays ACTIVE.

    Design: Corner/validations/evaluate_dormancy_before_date_returns_not_yet_dormant
    """
    holder, hh, prop = _active_property_dormant_2023(api)
    fixtures.set_clock(api, "2022-12-31T00:00:00Z")
    validate_error(api.evaluate_dormancy(prop["id"], hh), ApiErrorId.ERR_NOT_YET_DORMANT.value)
    after = validate_success(api.get_property(prop["id"], hh), 200)
    assert after["status"] == "ACTIVE", "property must remain ACTIVE after a rejected evaluate"
