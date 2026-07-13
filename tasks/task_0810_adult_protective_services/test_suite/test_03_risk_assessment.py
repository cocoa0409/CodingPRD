"""Risk assessment: the PRELIMINARY vs COMPREHENSIVE dual variant, the weighted
formula with its caps and tier boundary, capacity-determination mutation, and
the optimistic-concurrency stale-version guard."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, TEST_USERS,
    risk_assessment_payload,
)
from test_helpers import fixtures as fx

CASEWORKER = TEST_USERS["caseworker_headers"]


def _assess(api, client_id, assessment_type, levels, expected_version):
    payload = risk_assessment_payload(assessment_type, expected_version, **levels)
    return api.create_risk_assessment(client_id, payload, CASEWORKER)


def test_preliminary_assessment_stores_preliminary_score_only(api):
    """PRD §3.3: "A `PRELIMINARY` assessment — the intake-screening variant built
    from reporter-supplied factors — records its capped score into the client's
    `preliminary_risk_score` only; it does not set the authoritative `risk_level`
    and does not mirror anything onto the case."

    Design: Difficulty/dual_variant_calc/risk_preliminary_vs_comprehensive_diverge
    """
    client = fx.new_client()
    resp = _assess(api, client["id"], "PRELIMINARY",
                   dict(isolation_level=2, cognitive_impairment_level=2,
                        financial_vulnerability_level=1, caregiver_dependency_level=0,
                        prior_report_count=1),
                   client["version"])
    data = validate_success(resp)
    assert data["preliminary_risk_score"] == 57, f"expected 57, got {data['preliminary_risk_score']}"
    assert data["risk_level"] is None, "PRELIMINARY must not set the authoritative risk_level"


def test_comprehensive_assessment_sets_authoritative_risk_level(api):
    """PRD §3.3: "A `COMPREHENSIVE` assessment ... records its capped score into
    the client's `comprehensive_risk_score`, sets the derived tier as the
    authoritative client `risk_level`, and mirrors that same `risk_level` onto
    the open case."

    Design: Difficulty/dual_variant_calc/risk_preliminary_vs_comprehensive_diverge
    """
    client = fx.new_client()
    prelim = validate_success(_assess(api, client["id"], "PRELIMINARY",
                                      dict(isolation_level=2, cognitive_impairment_level=2,
                                           financial_vulnerability_level=1, caregiver_dependency_level=0,
                                           prior_report_count=1),
                                      client["version"]))
    version_now = fx.get_client(client["id"])["version"]
    resp = _assess(api, client["id"], "COMPREHENSIVE",
                   dict(isolation_level=3, cognitive_impairment_level=3,
                        financial_vulnerability_level=2, caregiver_dependency_level=2,
                        prior_report_count=1),
                   version_now)
    data = validate_success(resp)
    assert data["comprehensive_risk_score"] == 100, f"expected 100, got {data['comprehensive_risk_score']}"
    assert data["risk_level"] == "HIGH"
    assert data["preliminary_risk_score"] != data["comprehensive_risk_score"]
    assert prelim["preliminary_risk_score"] == 57


def test_risk_score_capped_at_100(api):
    """PRD §3.3: "the raw score is capped so that the stored score is the smaller
    of the raw score and 100."

    Design: Difficulty/combinatorial_formula/risk_score_nonlinear_cap_and_tier
    """
    client = fx.new_client()
    resp = _assess(api, client["id"], "COMPREHENSIVE",
                   dict(isolation_level=3, cognitive_impairment_level=3,
                        financial_vulnerability_level=3, caregiver_dependency_level=3,
                        prior_report_count=8),
                   client["version"])
    data = validate_success(resp)
    assert data["comprehensive_risk_score"] == 100, (
        f"raw 137 (with prior capped at 5) must cap to 100; got {data['comprehensive_risk_score']}"
    )


def test_risk_score_high_tier_selected(api):
    """PRD §3.3: "a score of 70 or higher is `HIGH`".

    Design: Difficulty/combinatorial_formula/risk_score_nonlinear_cap_and_tier
    """
    client = fx.new_client()
    resp = _assess(api, client["id"], "COMPREHENSIVE",
                   dict(isolation_level=3, cognitive_impairment_level=3,
                        financial_vulnerability_level=3, caregiver_dependency_level=3,
                        prior_report_count=8),
                   client["version"])
    data = validate_success(resp)
    assert data["risk_level"] == "HIGH"


def test_risk_level_high_at_exactly_70(api):
    """PRD §3.3: "the tier boundaries are inclusive at their lower edge, so a
    score of exactly 70 is `HIGH` and a score of exactly 40 is `MODERATE`."

    Design: Difficulty/boundary_precision_check/risk_score_high_threshold_exactly_70
    """
    client = fx.new_client()
    resp = _assess(api, client["id"], "COMPREHENSIVE",
                   dict(isolation_level=3, cognitive_impairment_level=2,
                        financial_vulnerability_level=0, caregiver_dependency_level=2,
                        prior_report_count=0),
                   client["version"])
    data = validate_success(resp)
    assert data["comprehensive_risk_score"] == 70, f"expected exactly 70, got {data['comprehensive_risk_score']}"
    assert data["risk_level"] == "HIGH"


def test_risk_level_moderate_just_below_70(api):
    """PRD §3.3: "a score from 40 up to but not including 70 is `MODERATE` ...
    the tier boundaries are inclusive at their lower edge, so a score of exactly
    70 is `HIGH`". A score of 69 (one below the boundary) is therefore MODERATE.

    Design: Difficulty/boundary_precision_check/risk_score_high_threshold_exactly_70
    """
    client = fx.new_client()
    resp = _assess(api, client["id"], "COMPREHENSIVE",
                   dict(isolation_level=3, cognitive_impairment_level=1,
                        financial_vulnerability_level=3, caregiver_dependency_level=0,
                        prior_report_count=0),
                   client["version"])
    data = validate_success(resp)
    assert data["comprehensive_risk_score"] == 69, f"expected 69, got {data['comprehensive_risk_score']}"
    assert data["risk_level"] == "MODERATE"


def test_occ_stale_client_version_rejected(api):
    """PRD §2.7: "when the submitted `expected_client_version` does not equal the
    client's current `version`, the request is rejected with
    `ERR_STALE_CLIENT_VERSION` (HTTP 412)."

    Design: Corner/errors/occ_stale_client_version_rejected
    """
    client = fx.new_client()
    stale_version = client["version"]  # version 1
    fx.add_capacity_determination(client["id"], "IMPAIRED")  # bumps version to 2
    resp = _assess(api, client["id"], "COMPREHENSIVE",
                   dict(isolation_level=2, cognitive_impairment_level=2,
                        financial_vulnerability_level=1, caregiver_dependency_level=0,
                        prior_report_count=0),
                   stale_version)
    validate_error(resp, ApiErrorId.ERR_STALE_CLIENT_VERSION.value)


def test_client_version_increments_on_capacity_determination(api):
    """PRD §3.3: "a caseworker records a determination by supplying
    `determination`, which sets the client's `capacity_status` to either
    `INTACT` or `IMPAIRED` and increments the client's `version` by one."

    Design: Corner/cross_cutting/client_version_increments_on_capacity_determination
    """
    client = fx.new_client()
    assert client["version"] == 1
    resp = api.capacity_determination(client["id"], {"determination": "INTACT"}, CASEWORKER)
    data = validate_success(resp)
    assert data["version"] == 2, f"expected version 2 after one mutation, got {data['version']}"
    assert data["capacity_status"] == "INTACT"
