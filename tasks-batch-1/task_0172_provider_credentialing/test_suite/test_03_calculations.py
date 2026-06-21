"""Derived calculations: expirable banding, readiness score, peer-review tally,
re-credentialing due date, and enrollment effective date.

Covers difficulty-design rules `dual_variant_calc`, `combinatorial_formula`, and
`boundary_precision_check` (expirable side), plus corner-design `calculations`
instances.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success, validate_error, validate_paginated,
    make_system_admin_headers, make_specialist_headers,
    make_compliance_officer_headers, make_enrollment_coordinator_headers,
    make_peer_reviewer_headers, make_medical_director_headers,
    ApiErrorId,
    create_org_payload, create_provider_payload, create_credential_item_payload,
    create_verification_request_payload, complete_verification_payload,
    create_sanctions_source_payload, create_sanctions_screening_payload,
    create_enrollment_payload, cast_vote_payload,
)
import test_helpers.fixtures as fx

ADMIN = make_system_admin_headers("admin-1")
SPEC = make_specialist_headers("spec-1")
COMP = make_compliance_officer_headers("comp-1")
ENR = make_enrollment_coordinator_headers("enr-1")


def _org():
    return validate_success(api_client.create_org(create_org_payload(), ADMIN), 201)


def _provider_with_item(org_id, expiration_date):
    provider = validate_success(api_client.create_provider(create_provider_payload(org_id), SPEC), 201)
    item = validate_success(api_client.create_credential_item(
        provider["id"], create_credential_item_payload(expiration_date=expiration_date), SPEC), 201)
    return provider, item


# =========================================================================
# Expirable band boundary (window = 90, inclusive on EXPIRING_SOON side)
# =========================================================================
def test_expirable_band_window_boundary_is_expiring_soon():
    """PRD §2.8: "a credential with days remaining exactly equal to the window
    (90 by default) is `EXPIRING_SOON`, while days remaining equal to the window
    plus one (91 by default) is `VALID`."

    Design: Difficulty/boundary_precision_check/expirable_band_window_boundary_on_clock
    """
    org = _org()
    provider, item = _provider_with_item(org["id"], "2026-05-30T00:00:00.000Z")
    validate_success(api_client.set_clock({"to_iso8601": "2026-03-01T00:00:00.000Z"}, ADMIN), 200)
    refreshed = validate_success(api_client.get_credential_item(item["id"], SPEC), 200)
    assert refreshed["expirable_band"] == "EXPIRING_SOON"


def test_expirable_band_window_boundary_via_listing():
    """PRD §2.8: "a credential with days remaining exactly equal to the window
    (90 by default) is `EXPIRING_SOON`, while days remaining equal to the window
    plus one (91 by default) is `VALID`."

    Design: Difficulty/boundary_precision_check/expirable_band_window_boundary_on_clock
    """
    org = _org()
    provider, item = _provider_with_item(org["id"], "2026-05-30T00:00:00.000Z")
    validate_success(api_client.set_clock({"to_iso8601": "2026-03-01T00:00:00.000Z"}, ADMIN), 200)
    listing = api_client.list_credential_items(provider["id"], SPEC)
    data, _meta = validate_paginated(listing)
    assert data[0]["expirable_band"] == "EXPIRING_SOON"


def test_expirable_band_window_plus_one_is_valid():
    """PRD §2.8: "days remaining equal to the window plus one (91 by default) is
    `VALID`."

    Design: Corner/calculations/expirable_band_window_plus_one_is_valid
    """
    org = _org()
    provider, item = _provider_with_item(org["id"], "2026-05-31T00:00:00.000Z")
    validate_success(api_client.set_clock({"to_iso8601": "2026-03-01T00:00:00.000Z"}, ADMIN), 200)
    refreshed = validate_success(api_client.get_credential_item(item["id"], SPEC), 200)
    assert refreshed["expirable_band"] == "VALID"


# =========================================================================
# Readiness score (combinatorial mode (a))
# =========================================================================
def test_readiness_score_nonlinear_two_thirds_verified():
    """PRD §3.7: "The verified ratio is V divided by T. ... first compute the base
    as 100 multiplied by the verified ratio, rounded half-up to two decimal
    places; then subtract the integer sanction penalty and the integer
    re-credentialing penalty from that base; and finally clamp the result at a
    floor of zero".

    Design: Difficulty/combinatorial_formula/readiness_score_nonlinear_mode_a
    """
    org = _org()
    validate_success(api_client.set_clock({"to_iso8601": "2026-03-01T00:00:00.000Z"}, ADMIN), 200)
    provider = validate_success(api_client.create_provider(create_provider_payload(org["id"]), SPEC), 201)
    items = []
    for it, ident, ref in (
        ("STATE_LICENSE", "LIC-1", "https://lic.example/1"),
        ("DEA_REGISTRATION", "DEA-1", "https://dea.example/1"),
        ("BOARD_CERTIFICATION", "BRD-1", "https://brd.example/1"),
    ):
        ci = validate_success(api_client.create_credential_item(
            provider["id"],
            create_credential_item_payload(item_type=it, identifier=ident,
                                           expiration_date="2030-01-01T00:00:00.000Z"),
            SPEC), 201)
        items.append((ci, ref))
    validate_success(api_client.submit_application(provider["id"], SPEC), 200)
    validate_success(api_client.begin_verification(provider["id"], SPEC), 200)
    outcomes = ["PASS", "PASS", "FAIL"]
    for (ci, ref), outcome in zip(items, outcomes):
        vr = validate_success(api_client.create_verification_request(
            ci["id"], create_verification_request_payload(source_reference=ref), SPEC), 201)
        validate_success(api_client.complete_verification_request(
            vr["id"], complete_verification_payload(outcome), SPEC), 200)
    final = validate_success(api_client.finalize_verification(provider["id"], SPEC), 200)
    assert final["readiness_score"] == pytest.approx(66.67, abs=0.001)
    assert final["credentialing_status"] == "CONDITIONAL"


def test_readiness_score_full_verified_is_100():
    """PRD §3.7: "The verified ratio is V divided by T. ... first compute the base
    as 100 multiplied by the verified ratio, rounded half-up to two decimal
    places".

    Design: Corner/calculations/readiness_score_full_verified_is_100
    """
    org_id, provider, item = fx.setup_provider_ready_for_review()
    final = validate_success(api_client.get_provider(provider["id"], SPEC), 200)
    assert final["readiness_score"] == pytest.approx(100.0, abs=0.001)


def test_readiness_score_sanction_penalty_capped():
    """PRD §3.7: "A sanction penalty is taken as the smaller of 40 and the
    provider's `sanction_score` multiplied by 5."

    Design: Corner/calculations/readiness_score_sanction_penalty_capped
    """
    org = _org()
    source = validate_success(api_client.create_sanctions_source(
        create_sanctions_source_payload(org["id"], source_code="OIG_LEIE", severity_weight=10),
        COMP), 201)
    provider = validate_success(api_client.create_provider(create_provider_payload(org["id"]), SPEC), 201)
    item = validate_success(api_client.create_credential_item(
        provider["id"], create_credential_item_payload(), SPEC), 201)
    validate_success(api_client.submit_application(provider["id"], SPEC), 200)
    validate_success(api_client.begin_verification(provider["id"], SPEC), 200)
    vr = validate_success(api_client.create_verification_request(
        item["id"], create_verification_request_payload(), SPEC), 201)
    validate_success(api_client.complete_verification_request(
        vr["id"], complete_verification_payload("PASS"), SPEC), 200)
    validate_success(api_client.create_sanctions_screening(
        provider["id"], create_sanctions_screening_payload(source["id"], "HIT"), COMP), 201)
    final = validate_success(api_client.finalize_verification(provider["id"], SPEC), 200)
    assert final["readiness_score"] == pytest.approx(60.0, abs=0.001)


# =========================================================================
# Peer-review tally — chair double-on-tie (combinatorial mode (c))
# =========================================================================
def test_peer_review_tally_chair_double_on_tie():
    """PRD §3.5: "if the chair voted, take the chair's `vote_weight`; if the
    non-chair base is tied (`base_yes` equals `base_no`), the chair's weight
    counts double — that is, the chair's `vote_weight` multiplied by 2 — on
    whichever side the chair voted".

    Design: Difficulty/combinatorial_formula/peer_review_tally_eval_order_mode_c
    """
    ctx = fx.setup_file_under_review()
    file_id = ctx["file"]["id"]
    # Non-chair base: rev-2 YES, rev-3 NO -> tie 1-1
    validate_success(api_client.cast_vote(
        file_id, cast_vote_payload(ctx["rev2"]["id"], "YES"),
        make_peer_reviewer_headers("rev-2")), 201)
    validate_success(api_client.cast_vote(
        file_id, cast_vote_payload(ctx["rev3"]["id"], "NO"),
        make_peer_reviewer_headers("rev-3")), 201)
    # Chair votes YES -> doubled on tie -> tally_yes = 1 + 2 = 3, tally_no = 1
    validate_success(api_client.cast_vote(
        file_id, cast_vote_payload(ctx["chair"]["id"], "YES"),
        make_medical_director_headers("md-1")), 201)
    file = validate_success(api_client.get_credentialing_file(
        file_id, make_medical_director_headers("md-1")), 200)
    assert file["tally_yes"] == 3
    assert file["tally_no"] == 1


# =========================================================================
# Re-credentialing due date — rolling variant (dual_variant #1)
# =========================================================================
def test_recred_due_date_rolling_from_completion():
    """PRD §3.7: "In the default rolling variant — used at first clearing ... the
    base is the `credentialing_completed_date` of *this* clearing, so the next
    due date rolls forward from the most recent clearing."
    PRD §3.5: "its `credentialing_completed_date` is set to `current_utc`, and its
    `recred_due_date` is computed as described in §3.7."

    Design: Difficulty/dual_variant_calc/recred_due_rolling_variant_on_provider
    """
    ctx = fx.setup_cleared_provider(clock="2026-03-01T00:00:00.000Z")
    provider = validate_success(api_client.get_provider(ctx["provider"]["id"], SPEC), 200)
    assert provider["credentialing_status"] == "CLEARED"
    assert provider["credentialing_completed_date"] == "2026-03-01T00:00:00.000Z"
    assert provider["recred_due_date"] == "2029-02-28T00:00:00.000Z"


# =========================================================================
# Enrollment effective date — retroactive vs prospective (dual_variant #2)
# =========================================================================
def test_enrollment_effective_retroactive_vs_prospective():
    """PRD §3.6: "When `retroactive_allowed` is true, the enrollment is
    backdated: its `effective_date` is set to the provider's
    `credentialing_completed_date` (the retroactive variant). When
    `retroactive_allowed` is false, the enrollment is forward-dated: its
    `effective_date` is set to the organization's `current_utc` at the moment of
    activation (the prospective variant)."

    Design: Difficulty/dual_variant_calc/enrollment_effective_retroactive_vs_prospective_on_payerenrollment
    """
    ctx = fx.setup_cleared_provider(clock="2026-03-01T00:00:00.000Z")
    provider_id = ctx["provider"]["id"]
    # Advance the clock to 2026-06-01 so the prospective anchor differs from completion.
    validate_success(api_client.set_clock({"to_iso8601": "2026-06-01T00:00:00.000Z"}, ADMIN), 200)
    retro_payer = fx.create_payer(ctx["org_id"], name="Retro Plan",
                                  retroactive_allowed=True, panel_capacity=5)
    prosp_payer = fx.create_payer(ctx["org_id"], name="Prosp Plan",
                                  retroactive_allowed=False, panel_capacity=5)

    en_retro = validate_success(api_client.create_payer_enrollment(
        provider_id, create_enrollment_payload(retro_payer["id"]), ENR), 201)
    validate_success(api_client.submit_enrollment(en_retro["id"], ENR), 200)
    en_prosp = validate_success(api_client.create_payer_enrollment(
        provider_id, create_enrollment_payload(prosp_payer["id"]), ENR), 201)
    validate_success(api_client.submit_enrollment(en_prosp["id"], ENR), 200)

    retro = validate_success(api_client.activate_enrollment(en_retro["id"], ENR), 200)
    prosp = validate_success(api_client.activate_enrollment(en_prosp["id"], ENR), 200)
    assert retro["effective_date"] == "2026-03-01T00:00:00.000Z"
    assert prosp["effective_date"] == "2026-06-01T00:00:00.000Z"
    assert retro["effective_date"] != prosp["effective_date"]
