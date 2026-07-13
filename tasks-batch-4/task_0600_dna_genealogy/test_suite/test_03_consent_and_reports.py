"""Consent windows, withdrawal, and the consent-gated ancestry / health reports."""

import pytest

from test_helpers import (
    ApiErrorId,
    UNKNOWN_UUID,
    CLOCK_START,
    validate_success,
    validate_error,
    validate_paginated,
    assert_report,
    assert_consent_grant,
    assert_composition,
    assert_instant_equals,
    make_customer_headers,
    make_lab_technician_headers,
    make_privacy_officer_headers,
    factories as f,
    fixtures as fx,
)

LAB = make_lab_technician_headers()
OFFICER = make_privacy_officer_headers()

# Four populations whose PROVISIONAL shares round to 33.22 / 33.22 / 33.22 / 0.33 (sum 99.99),
# leaving a 0.01 residual, and whose sub-1.00% member (SAS) the FINAL variant prunes.
SPLIT_SCORES = [
    {"population": "AFR", "raw_score": 100},
    {"population": "EAS", "raw_score": 100},
    {"population": "EUR", "raw_score": 100},
    {"population": "SAS", "raw_score": 1},
]

PROVISIONAL_COMPOSITION = [
    {"population": "AFR", "share_pct": 33.23},
    {"population": "EAS", "share_pct": 33.22},
    {"population": "EUR", "share_pct": 33.22},
    {"population": "SAS", "share_pct": 0.33},
]

FINAL_COMPOSITION = [
    {"population": "AFR", "share_pct": 33.34},
    {"population": "EAS", "share_pct": 33.33},
    {"population": "EUR", "share_pct": 33.33},
]


# ═══════════════════════════════════════════════════════════════════════════
# Consent windows: closed-interval overlap and the cooling-off buffer
# ═══════════════════════════════════════════════════════════════════════════

def _setup_customer_with_health_grant(email):
    fx.set_clock(CLOCK_START)
    customer = fx.create_customer(email=email, display_name="Otto")
    grant = fx.grant_consent(
        customer["id"],
        "HEALTH_TRAITS",
        effective_from="2026-05-01T00:00:00Z",
        effective_until="2026-06-01T00:00:00Z",
    )
    return customer, grant


def test_new_grant_touching_an_active_grants_endpoint_is_rejected(api):
    """PRD §3.6: "Because both intervals are closed, two grants that merely touch at an
    endpoint — where the new grant's `effective_from` equals an existing grant's
    `effective_until` — *do* intersect, and the request is rejected with
    `ERR_CONSENT_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/consent_closed_interval_touching_endpoint_rejected
    """
    customer, _grant = _setup_customer_with_health_grant("o@dna.test")

    resp = api.create_consent_grant(
        f.create_consent_payload(
            customer["id"],
            "HEALTH_TRAITS",
            effective_from="2026-06-01T00:00:00Z",
            effective_until="2026-07-01T00:00:00Z",
        ),
        make_customer_headers(customer["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_CONSENT_OVERLAP.value, 409)


def test_a_rejected_overlapping_grant_leaves_the_original_grant_alone(api):
    """PRD §3.6: "A new grant is created in `ACTIVE` status with `withdrawn_at` null, and the
    customer's three consent booleans are recomputed immediately."
    PRD §2.9: "`health_opt_in` is true exactly when an `ACTIVE` grant of scope
    `HEALTH_TRAITS` covers the current logical-clock instant; `matching_opt_in` and
    `research_opt_in` are the corresponding booleans for the `RELATIVE_MATCHING` and
    `RESEARCH` scopes."

    Design: Difficulty/resource_temporal_overlap/consent_closed_interval_touching_endpoint_rejected
    """
    customer, grant = _setup_customer_with_health_grant("o2@dna.test")
    headers = make_customer_headers(customer["id"])

    resp = api.create_consent_grant(
        f.create_consent_payload(
            customer["id"],
            "HEALTH_TRAITS",
            effective_from="2026-06-01T00:00:00Z",
            effective_until="2026-07-01T00:00:00Z",
        ),
        headers,
    )
    validate_error(resp, ApiErrorId.ERR_CONSENT_OVERLAP.value, 409)

    grants, meta = validate_paginated(
        api.list_consent_grants(
            headers, params={"customer_id": customer["id"], "scope": "HEALTH_TRAITS"}
        )
    )
    assert meta["total_count"] == 1, f"Expected exactly 1 grant, got {meta['total_count']}"
    assert grants[0]["id"] == grant["id"]
    assert grants[0]["status"] == "ACTIVE"
    assert fx.read_customer(customer["id"])["health_opt_in"] is True


def test_regrant_inside_the_cooling_off_window_is_rejected(api):
    """PRD §3.6: "Second, the **cooling-off buffer**: if any `WITHDRAWN` grant exists for the
    same customer and the same scope, the new grant's `effective_from` must be at least 24
    hours after the latest `withdrawn_at` among them. The boundary is inclusive — a new
    window beginning exactly 24 hours after the withdrawal is accepted, and anything earlier
    is rejected with `ERR_CONSENT_COOLING_OFF`."

    Design: Corner/validations/consent_regrant_inside_cooling_off_window_rejected
    """
    fx.set_clock(CLOCK_START)
    customer = fx.create_customer(email="cool@dna.test", display_name="Cool")
    headers = make_customer_headers(customer["id"])
    grant = fx.grant_consent(customer["id"], "RESEARCH")

    fx.set_clock("2026-05-02T00:00:00Z")
    fx.withdraw_consent(grant["id"], customer["id"])

    fx.set_clock("2026-05-02T23:00:00Z")
    # 23 hours after the withdrawal — one hour short of the 24-hour buffer.
    resp = api.create_consent_grant(
        f.create_consent_payload(
            customer["id"],
            "RESEARCH",
            effective_from="2026-05-02T23:00:00Z",
            effective_until="2026-12-31T00:00:00Z",
        ),
        headers,
    )
    validate_error(resp, ApiErrorId.ERR_CONSENT_COOLING_OFF.value, 409)

    grants, meta = validate_paginated(
        api.list_consent_grants(
            headers, params={"customer_id": customer["id"], "scope": "RESEARCH"}
        )
    )
    assert meta["total_count"] == 1
    assert grants[0]["status"] == "WITHDRAWN"
    assert fx.read_customer(customer["id"])["research_opt_in"] is False


def test_withdrawing_an_already_withdrawn_grant_is_rejected(api):
    """PRD §3.6: "Withdrawal moves a grant `ACTIVE → WITHDRAWN` — an `ACTIVE` grant is
    required, or `ERR_INVALID_STATE` — stamps `withdrawn_at` with the logical clock, and then
    does the work that gives withdrawal its teeth."

    Design: Corner/state_machines/withdraw_already_withdrawn_consent_returns_invalid_state
    """
    fx.set_clock(CLOCK_START)
    customer = fx.create_customer(email="ww@dna.test", display_name="Ww")
    grant = fx.grant_consent(customer["id"], "RESEARCH")
    withdrawn = fx.withdraw_consent(grant["id"], customer["id"])
    assert_consent_grant(withdrawn)

    # A privacy officer may withdraw on the customer's behalf; the terminal state still holds.
    resp = api.withdraw_consent_grant(grant["id"], OFFICER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)

    after = fx.read_consent_grant(grant["id"], customer["id"])
    assert after["status"] == "WITHDRAWN"
    assert_instant_equals(after["withdrawn_at"], CLOCK_START, "withdrawn_at")
    assert fx.read_customer(customer["id"])["research_opt_in"] is False


# ═══════════════════════════════════════════════════════════════════════════
# Ethnicity composition: pinned rounding order and the FINAL pruning
# ═══════════════════════════════════════════════════════════════════════════

def _setup_ethnicity_customer(email, display_name, with_research=False, markers=None):
    fx.set_clock(CLOCK_START)
    participant = fx.setup_dna_ready_customer(
        email=email,
        display_name=display_name,
        tier="PLUS",
        chip_version="V5",
        population_scores=SPLIT_SCORES,
        genotype_markers=markers or [1, 2, 3],
    )
    if with_research:
        fx.grant_consent(participant["customer"]["id"], "RESEARCH")
    return participant


def test_provisional_and_final_variants_produce_different_compositions(api):
    """PRD §3.7: "- **`PROVISIONAL`**: every population in the sample's `population_scores`
    is in scope, including sub-one-percent trace populations. Shares are computed over the
    full raw total. This variant is always permitted once the customer is genotyped."
    PRD §3.7: "Then **drop every entry whose provisional share is below 1.00 percent**, and
    re-run the entire three-step procedure — raw total, per-entry rounding, residual
    assignment — over only the surviving entries."

    Design: Difficulty/dual_variant_calc/ethnicity_provisional_vs_final_composition_diverges
    """
    p = _setup_ethnicity_customer("a@dna.test", "Ann", with_research=True)
    customer_id = p["customer"]["id"]
    headers = make_customer_headers(customer_id)

    v1 = fx.read_customer_version(customer_id)
    provisional = validate_success(
        api.generate_report(
            customer_id,
            f.generate_report_payload(v1, report_type="ETHNICITY", variant="PROVISIONAL"),
            headers,
        ),
        201,
    )
    assert_report(provisional)
    assert_composition(provisional["composition"], PROVISIONAL_COMPOSITION)
    assert provisional["residual_population"] == "AFR"

    v2 = fx.read_customer_version(customer_id)
    final = validate_success(
        api.generate_report(
            customer_id,
            f.generate_report_payload(v2, report_type="ETHNICITY", variant="FINAL"),
            headers,
        ),
        201,
    )
    # SAS is pruned at 0.33% and the remaining three are renormalized over 300 instead of 301.
    assert_composition(final["composition"], FINAL_COMPOSITION)
    assert final["residual_population"] == "AFR"


def test_a_second_report_of_the_same_type_supersedes_the_first(api):
    """PRD §3.7: "A report is created in `DRAFT` status and auto-published within the same
    request once its content has been computed, so the persisted result the client sees is
    already `PUBLISHED` with `generated_at` stamped from the logical clock. When a report of
    the same `report_type` was already `PUBLISHED` for that customer, that older report
    transitions `PUBLISHED → SUPERSEDED`."
    PRD §3.7: "The sample's identifier is recorded on the report as `sample_id`."

    Design: Difficulty/dual_variant_calc/ethnicity_provisional_vs_final_composition_diverges
    """
    p = _setup_ethnicity_customer("a2@dna.test", "Ann2", with_research=True)
    customer_id = p["customer"]["id"]
    sample_id = p["sample"]["id"]

    provisional = fx.publish_report(customer_id, "ETHNICITY", "PROVISIONAL")
    assert provisional["status"] == "PUBLISHED"

    final = fx.publish_report(customer_id, "ETHNICITY", "FINAL")
    assert final["status"] == "PUBLISHED"

    assert fx.read_report(provisional["id"], customer_id)["status"] == "SUPERSEDED", (
        "The older report of the same report_type must be superseded"
    )
    assert provisional["sample_id"] == sample_id
    assert final["sample_id"] == sample_id


def test_ethnicity_residual_goes_to_the_largest_raw_score(api):
    """PRD §3.7: "If that residual is not zero, it must be absorbed: the winner is the
    in-scope entry with the **largest raw score**, breaking any tie by taking the
    alphabetically lowest population code."
    PRD §3.7: "The winner's share has the residual added to it, rounded half up to 2 decimal
    places, and the winner's population code is recorded on the report as
    `residual_population`."

    Design: Difficulty/combinatorial_formula/ethnicity_round_then_sum_residual_to_largest_raw_score_mode_b
    """
    p = _setup_ethnicity_customer("round@dna.test", "Rita", markers=[1, 2])
    customer_id = p["customer"]["id"]

    report = fx.publish_report(customer_id, "ETHNICITY", "PROVISIONAL")

    # AFR / EAS / EUR tie on raw_score 100; the alphabetically lowest code takes the residual.
    assert report["residual_population"] == "AFR", (
        f"Expected AFR to absorb the residual, got {report['residual_population']}"
    )
    afr = next(e for e in report["composition"] if e["population"] == "AFR")
    assert afr["share_pct"] == pytest.approx(33.23, abs=0.001), (
        f"Expected AFR 33.22 + 0.01 residual == 33.23, got {afr['share_pct']}"
    )


def test_ethnicity_shares_are_rounded_per_entry_before_summing(api):
    """PRD §3.7: "Then, **for each entry individually, round its share to 2 decimal places
    before summing anything** — a share is that entry's raw score divided by the raw total,
    multiplied by 100, rounded half up to 2 decimal places. Do not sum the unrounded shares
    and round once at the end; the two procedures give different answers, and only the first
    is correct here."
    PRD §3.7: "The shares sum to exactly 100.00 by construction, and the mechanism that
    guarantees that is worth spelling out precisely, because the rounding order is pinned."

    Design: Difficulty/combinatorial_formula/ethnicity_round_then_sum_residual_to_largest_raw_score_mode_b
    """
    p = _setup_ethnicity_customer("round2@dna.test", "Rita2", markers=[1, 2])
    report = fx.publish_report(p["customer"]["id"], "ETHNICITY", "PROVISIONAL")

    # Rounding each of the four shares first gives 99.99, so a 0.01 residual exists.
    # Summing the unrounded shares and rounding once would give 100.00 and AFR == 33.22.
    assert_composition(report["composition"], PROVISIONAL_COMPOSITION)
    total = sum(e["share_pct"] for e in report["composition"])
    assert total == pytest.approx(100.00, abs=0.001)


# ═══════════════════════════════════════════════════════════════════════════
# Health-trait reports, revocation, and the report gates
# ═══════════════════════════════════════════════════════════════════════════

def test_withdrawing_health_consent_revokes_the_published_health_report_only(api):
    """PRD §3.6: "- **`HEALTH_TRAITS`**: every report belonging to that customer whose
    `report_type` is `HEALTH_TRAIT` and whose `status` is `PUBLISHED` transitions to
    `REVOKED`."
    PRD §3.7: "The report's `trait_count` is the number of entries in the source sample's
    `genotype_markers` whose value is at most 12."

    Design: Corner/state_machines/health_consent_withdrawal_revokes_published_health_report
    """
    fx.set_clock(CLOCK_START)
    p = fx.setup_dna_ready_customer(
        email="h@dna.test", display_name="Hal", tier="PLUS", genotype_markers=[1, 2, 20]
    )
    customer_id = p["customer"]["id"]
    grant = fx.grant_consent(customer_id, "HEALTH_TRAITS")

    health = fx.publish_report(customer_id, "HEALTH_TRAIT", "PROVISIONAL")
    assert health["trait_count"] == 2, (
        f"Markers 1 and 2 are at most 12; marker 20 is not. Got trait_count "
        f"{health['trait_count']}"
    )
    assert health["composition"] == []
    assert health["residual_population"] is None

    ethnicity = fx.publish_report(customer_id, "ETHNICITY", "PROVISIONAL")

    validate_success(
        api.withdraw_consent_grant(grant["id"], make_customer_headers(customer_id))
    )

    assert fx.read_report(health["id"], customer_id)["status"] == "REVOKED"
    assert fx.read_report(ethnicity["id"], customer_id)["status"] == "PUBLISHED", (
        "An ETHNICITY report is not gated by HEALTH_TRAITS consent and must survive"
    )
    assert fx.read_customer(customer_id)["health_opt_in"] is False


def _setup_no_sample_customer(email):
    fx.set_clock(CLOCK_START)
    customer = fx.create_customer(email=email, display_name="Nia")
    fx.create_subscription(customer["id"], "PLUS")
    return customer


def test_missing_dna_is_reported_before_missing_consent(api):
    """PRD §2.6: "Because the consent gate sits below the DNA-readiness check, a customer
    with no genotyped sample and no consent hears about the missing DNA first."
    PRD §3.7: "If no eligible sample exists, the customer is not genotyped and the request
    fails with `ERR_DNA_NOT_READY` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/dna_not_ready_beats_consent_required_on_health_report
    """
    customer = _setup_no_sample_customer("n@dna.test")
    version = fx.read_customer_version(customer["id"])

    # This request violates BOTH the DNA-readiness rule and the HEALTH_TRAITS consent gate.
    resp = api.generate_report(
        customer["id"],
        f.generate_report_payload(version, report_type="HEALTH_TRAIT", variant="PROVISIONAL"),
        make_customer_headers(customer["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_DNA_NOT_READY.value, 409)


def test_a_report_rejected_for_missing_dna_creates_nothing(api):
    """PRD §3.7: "If no eligible sample exists, the customer is not genotyped and the request
    fails with `ERR_DNA_NOT_READY` (HTTP 409)."
    PRD §2.6: "Checks are evaluated in the following order, and the first failure
    short-circuits the request:"

    Design: Difficulty/priority_pair_validation_conflict/dna_not_ready_beats_consent_required_on_health_report
    """
    customer = _setup_no_sample_customer("n2@dna.test")
    headers = make_customer_headers(customer["id"])
    version = fx.read_customer_version(customer["id"])

    resp = api.generate_report(
        customer["id"],
        f.generate_report_payload(version, report_type="HEALTH_TRAIT", variant="PROVISIONAL"),
        headers,
    )
    validate_error(resp, ApiErrorId.ERR_DNA_NOT_READY.value, 409)

    reports, meta = validate_paginated(
        api.list_reports(headers, params={"customer_id": customer["id"]})
    )
    assert meta["total_count"] == 0, "A short-circuited report request must persist nothing"
    assert reports == []
    assert fx.read_customer(customer["id"])["dna_status"] == "NO_SAMPLE"


def _setup_dna_ready_locked_customer(email):
    fx.set_clock(CLOCK_START)
    p = fx.setup_dna_ready_customer(email=email, display_name="Lee", tier="PLUS")
    fx.lock_subscription(p["subscription"]["id"])
    return p


def test_missing_consent_is_reported_before_the_subscription_lock(api):
    """PRD §2.6: "Then the specific business rules, in the order laid out below:
    barcode-already-activated, DNA readiness, extraction-attempts exhaustion, the empty-batch
    guard, the consent gate, sample readiness for batching, instrument availability,
    consent-window overlap, the consent cooling-off buffer, instrument-window overlap,
    barcode mismatch, tree cycle detection, the tier person limit, the one-open-privacy-request
    rule, subscription access lock, and finally insufficient store credit."
    PRD §3.7: "A `HEALTH_TRAIT` report additionally requires live `HEALTH_TRAITS` consent,
    and the `FINAL` variant additionally requires live `RESEARCH` consent; either missing
    gives `ERR_CONSENT_REQUIRED`."

    Design: Difficulty/priority_pair_validation_conflict/consent_required_beats_subscription_locked_on_health_report
    """
    p = _setup_dna_ready_locked_customer("l@dna.test")
    customer_id = p["customer"]["id"]
    version = fx.read_customer_version(customer_id)

    # The customer is DNA_READY, holds no HEALTH_TRAITS grant, and their access is LOCKED.
    resp = api.generate_report(
        customer_id,
        f.generate_report_payload(version, report_type="HEALTH_TRAIT", variant="PROVISIONAL"),
        make_customer_headers(customer_id),
    )
    validate_error(resp, ApiErrorId.ERR_CONSENT_REQUIRED.value, 403)


def test_the_consent_rejection_leaves_the_locked_subscription_untouched(api):
    """PRD §3.7: "The owning subscription's `access_status` must be `ACTIVE` or `GRACE`, and
    — additionally, for a `HEALTH_TRAIT` report — its `tier` must be `PLUS` or `PRO`, since
    health reporting is not an entitlement of the `FREE` tier; a failure of either yields
    `ERR_SUBSCRIPTION_LOCKED`."
    PRD §3.7: "A `HEALTH_TRAIT` report additionally requires live `HEALTH_TRAITS` consent,
    and the `FINAL` variant additionally requires live `RESEARCH` consent; either missing
    gives `ERR_CONSENT_REQUIRED`."

    Design: Difficulty/priority_pair_validation_conflict/consent_required_beats_subscription_locked_on_health_report
    """
    p = _setup_dna_ready_locked_customer("l2@dna.test")
    customer_id = p["customer"]["id"]
    sub_id = p["subscription"]["id"]
    version = fx.read_customer_version(customer_id)

    resp = api.generate_report(
        customer_id,
        f.generate_report_payload(version, report_type="HEALTH_TRAIT", variant="PROVISIONAL"),
        make_customer_headers(customer_id),
    )
    validate_error(resp, ApiErrorId.ERR_CONSENT_REQUIRED.value, 403)

    sub = fx.read_subscription(sub_id, customer_id)
    assert sub["access_status"] == "LOCKED", "The rejected report must not change the subscription"
    assert sub["billing_status"] == "PAST_DUE"


# ═══════════════════════════════════════════════════════════════════════════
# Report OCC and identifier resolution
# ═══════════════════════════════════════════════════════════════════════════

def test_report_generation_with_a_stale_customer_version_is_rejected(api):
    """PRD §2.7: "A request to `POST /dna/customers/{id}/reports` must carry the field
    `expected_customer_version` in its payload, holding the `version` of the target Customer
    as the client last observed it. If that value does not equal the Customer's current
    `version` — because some other writer has advanced it since the client last read the
    record — the request is rejected with `ERR_STALE_VERSION` (HTTP 412)."
    PRD §3.7: "Publishing a report also advances the *customer's* own `version` by one —
    which means a client that wants to generate a second report must re-read the customer to
    obtain a fresh version, exactly as the stale-version guard of Section 2.7 intends."

    Design: Corner/cross_cutting/stale_expected_customer_version_on_report_returns_stale_version
    """
    fx.set_clock(CLOCK_START)
    p = fx.setup_dna_ready_customer(email="occ@dna.test", display_name="Occ", tier="PLUS")
    customer_id = p["customer"]["id"]
    headers = make_customer_headers(customer_id)

    observed = fx.read_customer_version(customer_id)

    first = validate_success(
        api.generate_report(
            customer_id,
            f.generate_report_payload(observed, report_type="ETHNICITY", variant="PROVISIONAL"),
            headers,
        ),
        201,
    )

    # The publish bumped Customer.version; the client is still holding the pre-bump value.
    stale = api.generate_report(
        customer_id,
        f.generate_report_payload(observed, report_type="ETHNICITY", variant="PROVISIONAL"),
        headers,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION.value, 412)

    assert fx.read_report(first["id"], customer_id)["status"] == "PUBLISHED"
    _reports, meta = validate_paginated(
        api.list_reports(headers, params={"customer_id": customer_id})
    )
    assert meta["total_count"] == 1, f"Expected exactly 1 report, got {meta['total_count']}"


def test_unknown_customer_on_report_generation_resolves_before_any_business_rule(api):
    """PRD §2.5: "Paths that name a resource are resolved before anything else is
    considered."
    PRD §2.6: "3. Existence of every identifier in the path, left to right (the 404 family)."
    PRD §2.6: "7. The stale-version check on the two concurrency-guarded operations
    (`ERR_STALE_VERSION`)."

    Design: Corner/validations/existence_check_precedes_state_check_on_unknown_customer_report
    """
    real = fx.create_customer(email="nf@dna.test", display_name="Nf")

    resp = api.generate_report(
        UNKNOWN_UUID,
        f.generate_report_payload(
            real["version"], report_type="ETHNICITY", variant="PROVISIONAL"
        ),
        make_customer_headers(real["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_CUSTOMER_NOT_FOUND.value, 404)
