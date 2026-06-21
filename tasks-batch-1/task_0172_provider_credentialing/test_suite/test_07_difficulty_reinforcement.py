"""Second tests for each difficulty-design instance.

The difficulty index requires every instance to be covered by at least two tests.
Each test here asserts a complementary, independently PRD-derivable observable of
the same scenario already exercised once in tests 01-05 (a distinct side effect,
field, or boundary neighbour), never a restatement of the first assertion.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success, validate_error, validate_paginated,
    make_system_admin_headers, make_specialist_headers,
    make_medical_director_headers, make_peer_reviewer_headers,
    make_enrollment_coordinator_headers, make_compliance_officer_headers,
    ApiErrorId,
    create_org_payload, create_provider_payload, create_credential_item_payload,
    create_enrollment_payload, terminate_enrollment_payload, cast_vote_payload,
    finalize_payload, create_sanctions_screening_payload,
    create_verification_request_payload, complete_verification_payload,
    create_sanctions_source_payload,
)
import test_helpers.fixtures as fx

ADMIN = make_system_admin_headers("admin-1")
SPEC = make_specialist_headers("spec-1")
# spec-1's opaque X-User-ID acting in a voting capacity (PRD §2.1). PRD §2.6
# evaluates role authorization before the referential/segregation checks, so a
# cast attributed to spec-1 must present a voting role for those checks to be
# reachable rather than ERR_INSUFFICIENT_PERMISSIONS.
SPEC_AS_REVIEWER = make_peer_reviewer_headers("spec-1")
MD = make_medical_director_headers("md-1")
REV2 = make_peer_reviewer_headers("rev-2")
REV3 = make_peer_reviewer_headers("rev-3")
ENR = make_enrollment_coordinator_headers("enr-1")
COMP = make_compliance_officer_headers("comp-1")


def _file_version(file_id):
    return validate_success(api_client.get_credentialing_file(file_id, MD), 200)["version"]


# =========================================================================
# dual_variant_calc
# =========================================================================
def test_recred_clearing_sets_completed_date_and_current_state():
    """PRD §3.5: "its `credentialing_completed_date` is set to `current_utc`, and
    its `recred_due_date` is computed as described in §3.7."
    PRD §3.7: "When a file is approved while the provider's `credentialing_status`
    is `CLEARED`, the loop advances from `NOT_CLEARED` to `CURRENT`, the
    `credentialing_completed_date` is set to `current_utc`".

    Design: Difficulty/dual_variant_calc/recred_due_rolling_variant_on_provider
    """
    ctx = fx.setup_cleared_provider(clock="2026-03-01T00:00:00.000Z")
    provider = validate_success(api_client.get_provider(ctx["provider"]["id"], SPEC), 200)
    assert provider["credentialing_completed_date"] == "2026-03-01T00:00:00.000Z"
    assert provider["recred_state"] == "CURRENT"


def test_enrollment_effective_dates_differ_between_payers():
    """PRD §3.6: "The two branches read different anchor timestamps and so yield
    different coverage-eligible windows for the same enrollment."
    PRD §3.6: "When `retroactive_allowed` is true, the enrollment is backdated:
    its `effective_date` is set to the provider's `credentialing_completed_date`
    (the retroactive variant)."

    Design: Difficulty/dual_variant_calc/enrollment_effective_retroactive_vs_prospective_on_payerenrollment
    """
    ctx = fx.setup_cleared_provider(clock="2026-03-01T00:00:00.000Z")
    provider_id = ctx["provider"]["id"]
    validate_success(api_client.set_clock({"to_iso8601": "2026-06-01T00:00:00.000Z"}, ADMIN), 200)
    retro_payer = fx.create_payer(ctx["org_id"], name="Retro Plan",
                                  retroactive_allowed=True, panel_capacity=5)
    en_retro = validate_success(api_client.create_payer_enrollment(
        provider_id, create_enrollment_payload(retro_payer["id"]), ENR), 201)
    validate_success(api_client.submit_enrollment(en_retro["id"], ENR), 200)
    retro = validate_success(api_client.activate_enrollment(en_retro["id"], ENR), 200)
    # Retroactive variant anchors to the completion date, not the activation clock.
    assert retro["effective_date"] == "2026-03-01T00:00:00.000Z"


# =========================================================================
# combinatorial_formula
# =========================================================================
def test_readiness_score_two_thirds_posture_conditional():
    """PRD §3.7: "Otherwise, if any credential item has `verification_state`
    `REJECTED`, the posture is `CONDITIONAL`."

    Design: Difficulty/combinatorial_formula/readiness_score_nonlinear_mode_a
    """
    org = validate_success(api_client.create_org(create_org_payload(), ADMIN), 201)
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
            create_credential_item_payload(item_type=it, identifier=ident),
            SPEC), 201)
        items.append((ci, ref))
    validate_success(api_client.submit_application(provider["id"], SPEC), 200)
    validate_success(api_client.begin_verification(provider["id"], SPEC), 200)
    for (ci, ref), outcome in zip(items, ["PASS", "PASS", "FAIL"]):
        vr = validate_success(api_client.create_verification_request(
            ci["id"], create_verification_request_payload(source_reference=ref), SPEC), 201)
        validate_success(api_client.complete_verification_request(
            vr["id"], complete_verification_payload(outcome), SPEC), 200)
    final = validate_success(api_client.finalize_verification(provider["id"], SPEC), 200)
    # The REJECTED item drives the posture to CONDITIONAL (distinct from the score).
    assert final["credentialing_status"] == "CONDITIONAL"


def test_peer_review_tally_no_side_on_tie_break():
    """PRD §3.5: "the chair's weight counts double — that is, the chair's
    `vote_weight` multiplied by 2 — on whichever side the chair voted".
    PRD §3.5: "`tally_no` is `base_no` plus the chair's contribution to the NO
    side."

    Design: Difficulty/combinatorial_formula/peer_review_tally_eval_order_mode_c
    """
    ctx = fx.setup_file_under_review()
    file_id = ctx["file"]["id"]
    validate_success(api_client.cast_vote(
        file_id, cast_vote_payload(ctx["rev2"]["id"], "YES"), REV2), 201)
    validate_success(api_client.cast_vote(
        file_id, cast_vote_payload(ctx["rev3"]["id"], "NO"), REV3), 201)
    validate_success(api_client.cast_vote(
        file_id, cast_vote_payload(ctx["chair"]["id"], "YES"), MD), 201)
    file = validate_success(api_client.get_credentialing_file(file_id, MD), 200)
    # The chair voted YES (doubled), so the NO side keeps only rev-3's single weight.
    assert file["tally_no"] == 1


# =========================================================================
# non_linear_state_machine
# =========================================================================
def test_recred_cyclic_loop_reopens_aged_credential():
    """PRD §3.7: "conditionally re-opens verification: every credential item that
    is `VERIFIED` but whose `expirable_band` is not `VALID` is returned to
    `PENDING_PSV`, so only the credentials that have aged are re-verified."

    Design: Difficulty/non_linear_state_machine/provider_recred_cyclic_loop
    """
    org = validate_success(api_client.create_org(create_org_payload(), ADMIN), 201)
    # License expires 2029-05-01: VALID through clearing, but only 61 days remain
    # at the 2029-03-01 recred start (<= the 90-day window -> EXPIRING_SOON, not
    # VALID), so re-credentialing must re-open it.
    ctx = fx.setup_cleared_provider(org_id=org["id"], clock="2026-03-01T00:00:00.000Z",
                                    license_expiration="2029-05-01T00:00:00.000Z")
    provider_id = ctx["provider"]["id"]
    item_id = ctx["item"]["id"]
    validate_success(api_client.set_clock({"to_iso8601": "2029-03-01T00:00:00.000Z"}, ADMIN), 200)
    validate_success(api_client.start_recredentialing(provider_id, SPEC), 200)
    item = validate_success(api_client.get_credential_item(item_id, SPEC), 200)
    assert item["verification_state"] == "PENDING_PSV"


def test_fork_join_deny_branch_sets_file_denied():
    """PRD §3.5: "On a `DENY`, the file moves to `DENIED`".

    Design: Difficulty/non_linear_state_machine/credentialing_file_fork_join_deny_branch
    """
    ctx = fx.setup_file_under_review()
    file_id = ctx["file"]["id"]
    for rid, hdr in ((ctx["rev2"]["id"], REV2), (ctx["rev3"]["id"], REV3), (ctx["chair"]["id"], MD)):
        validate_success(api_client.cast_vote(file_id, cast_vote_payload(rid, "NO"), hdr), 201)
    version = _file_version(file_id)
    finalized = validate_success(api_client.finalize_file(
        file_id, finalize_payload("DENY", version, decision_reason="insufficient"), MD), 200)
    assert finalized["review_status"] == "DENIED"


# =========================================================================
# transitive_cascade
# =========================================================================
def test_clock_lapse_marks_item_lapsed():
    """PRD §2.7: "Every credential item's `expirable_band` is recomputed against
    the new clock, and an item may transition into `LAPSED`."

    Design: Difficulty/transitive_cascade/clock_lapse_demotes_provider_terminates_enrollment_depth3
    """
    org = validate_success(api_client.create_org(create_org_payload(), ADMIN), 201)
    ctx = fx.setup_active_enrollment(org_id=org["id"], clock="2026-03-01T00:00:00.000Z",
                                     license_expiration="2026-04-15T00:00:00.000Z",
                                     panel_capacity=5)
    validate_success(api_client.set_clock({"to_iso8601": "2026-05-01T00:00:00.000Z"}, ADMIN), 200)
    item = validate_success(api_client.get_credential_item(ctx["item"]["id"], SPEC), 200)
    assert item["expirable_band"] == "LAPSED"


def test_sanctions_hit_raises_sanction_score():
    """PRD §3.4: "A provider's `sanction_score` is the sum of the `severity_weight`
    of the sanctions source behind every screening that is both a `HIT` and still
    `OPEN`."

    Design: Difficulty/transitive_cascade/sanctions_hit_excludes_provider_depth2
    """
    org = validate_success(api_client.create_org(create_org_payload(), ADMIN), 201)
    source = fx.create_sanctions_source(org["id"], source_code="OIG_LEIE", severity_weight=3)
    provider = validate_success(api_client.create_provider(create_provider_payload(org["id"]), SPEC), 201)
    validate_success(api_client.create_credential_item(
        provider["id"], create_credential_item_payload(), SPEC), 201)
    validate_success(api_client.submit_application(provider["id"], SPEC), 200)
    validate_success(api_client.create_sanctions_screening(
        provider["id"], create_sanctions_screening_payload(source["id"], "HIT"), COMP), 201)
    provider = validate_success(api_client.get_provider(provider["id"], COMP), 200)
    assert provider["sanction_score"] == 3


# =========================================================================
# priority_pair_validation_conflict
# =========================================================================
def test_open_review_state_error_http_409():
    """PRD §5 (error catalogue): `ERR_PROVIDER_NOT_READY` -> 409 Conflict.
    PRD §3.5: "when the parent provider's `application_status` is
    `READY_FOR_REVIEW` (otherwise `ERR_PROVIDER_NOT_READY`)".

    Design: Difficulty/priority_pair_validation_conflict/open_review_state_beats_business_safety
    """
    org = validate_success(api_client.create_org(create_org_payload(), ADMIN), 201)
    source = fx.create_sanctions_source(org["id"], source_code="OIG_LEIE", severity_weight=3)
    provider = validate_success(api_client.create_provider(create_provider_payload(org["id"]), SPEC), 201)
    validate_success(api_client.create_credential_item(
        provider["id"], create_credential_item_payload(), SPEC), 201)
    validate_success(api_client.submit_application(provider["id"], SPEC), 200)
    validate_success(api_client.create_sanctions_screening(
        provider["id"], create_sanctions_screening_payload(source["id"], "HIT"), COMP), 201)
    file = validate_success(api_client.create_credentialing_file(provider["id"], SPEC), 201)
    resp = api_client.open_review(file["id"], MD)
    # validate_error cross-checks the 409 status from the registered map.
    validate_error(resp, ApiErrorId.ERR_PROVIDER_NOT_READY.value, expected_status=409)


def test_cast_vote_referential_error_http_409():
    """PRD §5 (error catalogue): `ERR_REVIEWER_ORG_MISMATCH` -> 409 Conflict.
    PRD §3.5: "The reviewer named by `reviewer_id` must belong to the same
    organization as the file's provider; otherwise the cast is rejected with
    `ERR_REVIEWER_ORG_MISMATCH` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/cast_vote_referential_beats_safety
    """
    org1 = validate_success(api_client.create_org(create_org_payload(name="CVO-1"), ADMIN), 201)
    org2 = validate_success(api_client.create_org(create_org_payload(name="CVO-2"), ADMIN), 201)
    org_id, provider, item = fx.setup_provider_ready_for_review(org_id=org1["id"])
    cross_reviewer = fx.create_reviewer(org2["id"], "spec-1", full_name="Cross-org reviewer")
    file = validate_success(api_client.create_credentialing_file(provider["id"], SPEC), 201)
    validate_success(api_client.open_review(file["id"], MD), 200)
    # spec-1 casts as a PeerReviewer (role auth passes) using an org-2 reviewer;
    # the referential org-mismatch is the deciding 409.
    resp = api_client.cast_vote(file["id"], cast_vote_payload(cross_reviewer["id"], "YES"), SPEC_AS_REVIEWER)
    validate_error(resp, ApiErrorId.ERR_REVIEWER_ORG_MISMATCH.value, expected_status=409)


# =========================================================================
# cross_entity_state_dependency
# =========================================================================
def test_enrollment_submit_not_cleared_http_409():
    """PRD §5 (error catalogue): `ERR_PROVIDER_NOT_CLEARED` -> 409 Conflict.
    PRD §3.6: "and when the provider's `credentialing_status` is `CLEARED`
    (otherwise `ERR_PROVIDER_NOT_CLEARED`)."

    Design: Difficulty/cross_entity_state_dependency/enrollment_submit_requires_provider_cleared
    """
    org = validate_success(api_client.create_org(create_org_payload(), ADMIN), 201)
    provider = validate_success(api_client.create_provider(create_provider_payload(org["id"]), SPEC), 201)
    validate_success(api_client.create_credential_item(
        provider["id"], create_credential_item_payload(), SPEC), 201)
    payer = fx.create_payer(org["id"], panel_capacity=5)
    enrollment = validate_success(api_client.create_payer_enrollment(
        provider["id"], create_enrollment_payload(payer["id"]), ENR), 201)
    resp = api_client.submit_enrollment(enrollment["id"], ENR)
    validate_error(resp, ApiErrorId.ERR_PROVIDER_NOT_CLEARED.value, expected_status=409)


def test_open_review_provider_not_ready_isolated_no_sanctions():
    """PRD §3.5: "when the parent provider's `application_status` is
    `READY_FOR_REVIEW` (otherwise `ERR_PROVIDER_NOT_READY`)".

    Design: Difficulty/cross_entity_state_dependency/open_review_requires_provider_ready
    """
    # Provider only SUBMITTED, with NO sanctions, isolating the state gate.
    org_id, provider, item = fx.setup_provider_submitted()
    file = validate_success(api_client.create_credentialing_file(provider["id"], SPEC), 201)
    resp = api_client.open_review(file["id"], MD)
    validate_error(resp, ApiErrorId.ERR_PROVIDER_NOT_READY.value, expected_status=409)


# =========================================================================
# resource_temporal_overlap
# =========================================================================
def test_credential_item_adjacent_intervals_allowed():
    """PRD §3.3: "if one item's `expiration_date` falls exactly on another item's
    `issued_date`, the two merely touch at a single instant and do not overlap."

    Design: Difficulty/resource_temporal_overlap/credential_item_interval_overlap_closed_closed
    """
    org = validate_success(api_client.create_org(create_org_payload(), ADMIN), 201)
    provider = validate_success(api_client.create_provider(create_provider_payload(org["id"]), SPEC), 201)
    validate_success(api_client.create_credential_item(
        provider["id"],
        create_credential_item_payload(
            item_type="STATE_LICENSE", identifier="LIC-1",
            issued_date="2026-01-01T00:00:00.000Z",
            expiration_date="2026-12-31T00:00:00.000Z"),
        SPEC), 201)
    # Second license starts exactly when the first expires -> adjacency allowed.
    resp = api_client.create_credential_item(
        provider["id"],
        create_credential_item_payload(
            item_type="STATE_LICENSE", identifier="LIC-2",
            issued_date="2026-12-31T00:00:00.000Z",
            expiration_date="2027-12-31T00:00:00.000Z"),
        SPEC)
    validate_success(resp, 201)


def test_duplicate_payer_enrollment_freed_after_terminal():
    """PRD §3.6: "Only terminal enrollments — those that are `REJECTED` or
    `TERMINATED` — free the window so a new enrollment with that payer may be
    requested."

    Design: Difficulty/resource_temporal_overlap/duplicate_payer_enrollment_ongoing_singleton
    """
    ctx = fx.setup_active_enrollment(panel_capacity=5, payer_name="Plan P")
    payer_id = ctx["payer"]["id"]
    provider_id = ctx["provider"]["id"]
    # Terminate the ACTIVE enrollment, freeing the window.
    validate_success(api_client.terminate_enrollment(
        ctx["enrollment"]["id"], terminate_enrollment_payload("provider left network"), ENR), 200)
    # A fresh enrollment with the same payer is now permitted.
    resp = api_client.create_payer_enrollment(
        provider_id, create_enrollment_payload(payer_id), ENR)
    validate_success(resp, 201)


# =========================================================================
# compensating_invariant
# =========================================================================
def test_panel_slot_reusable_after_termination():
    """PRD §3.6: "Terminating an enrollment moves it from `ACTIVE` to
    `TERMINATED` and frees one panel slot on the payer."
    PRD §3.6: "when the count of currently `ACTIVE` enrollments on the target
    payer is strictly less than that payer's `panel_capacity`".

    Design: Difficulty/compensating_invariant/panel_slot_conservation_activate_then_terminate
    """
    # Capacity-1 payer: terminate frees the slot, so a re-activation succeeds.
    ctx = fx.setup_active_enrollment(panel_capacity=1, payer_name="Plan 1cap")
    payer_id = ctx["payer"]["id"]
    provider_id = ctx["provider"]["id"]
    validate_success(api_client.terminate_enrollment(
        ctx["enrollment"]["id"], terminate_enrollment_payload("provider left network"), ENR), 200)
    new_en = validate_success(api_client.create_payer_enrollment(
        provider_id, create_enrollment_payload(payer_id), ENR), 201)
    validate_success(api_client.submit_enrollment(new_en["id"], ENR), 200)
    activated = validate_success(api_client.activate_enrollment(new_en["id"], ENR), 200)
    assert activated["status"] == "ACTIVE"


def test_sanction_score_resolution_returns_screening_resolved():
    """PRD §3.4: "On resolution the screening moves to `RESOLVED`, and the
    provider's `sanction_score` is recomputed."

    Design: Difficulty/compensating_invariant/sanction_score_conservation_hit_then_resolve
    """
    ctx = fx.setup_open_hit_screening(severity_weight=3)
    resolved = validate_success(api_client.resolve_sanctions_screening(
        ctx["screening"]["id"],
        {"resolution_note": "false positive confirmed against full SSN"}, COMP), 200)
    assert resolved["status"] == "RESOLVED"
    provider = validate_success(api_client.get_provider(ctx["provider"]["id"], COMP), 200)
    assert provider["sanction_score"] == 0
