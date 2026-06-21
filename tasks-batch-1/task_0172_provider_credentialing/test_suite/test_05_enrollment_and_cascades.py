"""Payer enrollment lifecycle, panel capacity, cross-entity gates, the
clock-driven cascades, the re-credentialing cyclic loop, and compensating
invariants.

Covers difficulty-design rules `transitive_cascade`, `cross_entity_state_dependency`,
`resource_temporal_overlap`, `compensating_invariant`, `non_linear_state_machine`
(recred loop), `priority_pair_validation_conflict` (open-review state beats safety),
plus the corner `validations`, `scheduled_actions`, and `transitive_cascade`
instances on the enrollment and clock paths.
"""
from test_helpers import (
    api_client,
    validate_success, validate_error, validate_paginated,
    make_system_admin_headers, make_specialist_headers,
    make_medical_director_headers, make_enrollment_coordinator_headers,
    make_compliance_officer_headers,
    ApiErrorId,
    create_org_payload, create_provider_payload, create_credential_item_payload,
    create_enrollment_payload, terminate_enrollment_payload,
    create_sanctions_screening_payload,
)
import test_helpers.fixtures as fx

ADMIN = make_system_admin_headers("admin-1")
SPEC = make_specialist_headers("spec-1")
MD = make_medical_director_headers("md-1")
ENR = make_enrollment_coordinator_headers("enr-1")
COMP = make_compliance_officer_headers("comp-1")


# =========================================================================
# Enrollment lifecycle preconditions
# =========================================================================
def test_terminate_requested_enrollment_returns_not_active():
    """PRD §3.6: "A manual termination by an `EnrollmentCoordinator` is permitted
    only when the enrollment is currently `ACTIVE` (otherwise
    `ERR_ENROLLMENT_NOT_ACTIVE`)".

    Design: Corner/state_machines/terminate_terminal_enrollment_returns_not_active
    """
    org = validate_success(api_client.create_org(create_org_payload(), ADMIN), 201)
    provider = validate_success(api_client.create_provider(create_provider_payload(org["id"]), SPEC), 201)
    payer = fx.create_payer(org["id"], panel_capacity=5)
    enrollment = validate_success(api_client.create_payer_enrollment(
        provider["id"], create_enrollment_payload(payer["id"]), ENR), 201)
    resp = api_client.terminate_enrollment(
        enrollment["id"], terminate_enrollment_payload("n/a"), ENR)
    validate_error(resp, ApiErrorId.ERR_ENROLLMENT_NOT_ACTIVE.value)


def test_terminate_without_reason_returns_reason_required():
    """PRD §3.6: "and requires a non-empty `termination_reason` (otherwise
    `ERR_TERMINATION_REASON_REQUIRED`, HTTP 400)."

    Design: Corner/validations/terminate_without_reason_returns_reason_required
    """
    ctx = fx.setup_active_enrollment(panel_capacity=5)
    resp = api_client.terminate_enrollment(
        ctx["enrollment"]["id"], terminate_enrollment_payload(""), ENR)
    validate_error(resp, ApiErrorId.ERR_TERMINATION_REASON_REQUIRED.value)


def test_enrollment_submit_requires_provider_cleared():
    """PRD §3.6: "Submitting an enrollment to the payer moves it from `REQUESTED`
    to `SUBMITTED` and is permitted only when it is currently `REQUESTED`
    (otherwise `ERR_ENROLLMENT_NOT_REQUESTED`) and when the provider's
    `credentialing_status` is `CLEARED` (otherwise `ERR_PROVIDER_NOT_CLEARED`)."

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
    validate_error(resp, ApiErrorId.ERR_PROVIDER_NOT_CLEARED.value)


def test_referenced_payer_not_found_on_enrollment():
    """PRD §2.5: "When a request body carries a reference such as `payer_id`,
    `reviewer_id`, or `sanctions_source_id`, that reference must resolve to an
    existing resource that belongs to the same organization as the operation's
    context; a missing or cross-organization reference is rejected with
    `ERR_REFERENCED_RESOURCE_NOT_FOUND` (HTTP 404)."

    Design: Corner/validations/referenced_payer_not_found_on_enrollment
    """
    org = validate_success(api_client.create_org(create_org_payload(), ADMIN), 201)
    provider = validate_success(api_client.create_provider(create_provider_payload(org["id"]), SPEC), 201)
    resp = api_client.create_payer_enrollment(
        provider["id"],
        create_enrollment_payload("00000000-0000-4000-8000-000000000000"), ENR)
    validate_error(resp, ApiErrorId.ERR_REFERENCED_RESOURCE_NOT_FOUND.value)


# =========================================================================
# Cross-entity state gate: open-review requires provider READY
# =========================================================================
def test_open_review_requires_provider_ready():
    """PRD §3.5: "This is permitted only when the file is currently `ASSEMBLING`
    (otherwise `ERR_FILE_NOT_ASSEMBLING`), when the parent provider's
    `application_status` is `READY_FOR_REVIEW` (otherwise
    `ERR_PROVIDER_NOT_READY`)".

    Design: Difficulty/cross_entity_state_dependency/open_review_requires_provider_ready
    """
    org_id, provider, item = fx.setup_provider_submitted()  # only SUBMITTED, no sanctions
    file = validate_success(api_client.create_credentialing_file(provider["id"], SPEC), 201)
    resp = api_client.open_review(file["id"], MD)
    validate_error(resp, ApiErrorId.ERR_PROVIDER_NOT_READY.value)


def test_open_review_state_beats_business_safety():
    """PRD §3.5: "This is permitted only when the file is currently `ASSEMBLING`
    (otherwise `ERR_FILE_NOT_ASSEMBLING`), when the parent provider's
    `application_status` is `READY_FOR_REVIEW` (otherwise `ERR_PROVIDER_NOT_READY`),
    and when the provider's `credentialing_status` is not `EXCLUDED` (otherwise
    `ERR_PROVIDER_EXCLUDED`, HTTP 403)."
    PRD §2.6: "the target resource being in the state required for the requested
    transition (the transition-specific `ERR_*_NOT_*` codes); and then the
    remaining business checks."

    Design: Difficulty/priority_pair_validation_conflict/open_review_state_beats_business_safety
    """
    org = validate_success(api_client.create_org(create_org_payload(), ADMIN), 201)
    source = fx.create_sanctions_source(org["id"], source_code="OIG_LEIE", severity_weight=3)
    provider = validate_success(api_client.create_provider(create_provider_payload(org["id"]), SPEC), 201)
    validate_success(api_client.create_credential_item(
        provider["id"], create_credential_item_payload(), SPEC), 201)
    validate_success(api_client.submit_application(provider["id"], SPEC), 200)
    # Provider is only SUBMITTED (not READY_FOR_REVIEW) AND has an open OIG HIT (EXCLUDED).
    validate_success(api_client.create_sanctions_screening(
        provider["id"], create_sanctions_screening_payload(source["id"], "HIT"), COMP), 201)
    file = validate_success(api_client.create_credentialing_file(provider["id"], SPEC), 201)
    resp = api_client.open_review(file["id"], MD)
    # Higher-priority state error must win over the safety error.
    validate_error(resp, ApiErrorId.ERR_PROVIDER_NOT_READY.value)


# =========================================================================
# Panel capacity
# =========================================================================
def test_panel_at_capacity_blocks_activate():
    """PRD §3.6: "and when the count of currently `ACTIVE` enrollments on the
    target payer is strictly less than that payer's `panel_capacity` (otherwise
    `ERR_PANEL_AT_CAPACITY`, HTTP 409)."

    Design: Corner/validations/panel_at_capacity_blocks_activate
    """
    org = validate_success(api_client.create_org(create_org_payload(), ADMIN), 201)
    validate_success(api_client.set_clock({"to_iso8601": "2026-03-01T00:00:00.000Z"}, ADMIN), 200)
    # Payer with capacity 1, already filled by provider P1's ACTIVE enrollment.
    ctx1 = fx.setup_active_enrollment(org_id=org["id"], clock=None, panel_capacity=1,
                                      payer_name="Plan 1cap", npi="1111111111",
                                      caqh_id="CAQH-1", license_identifier="LIC-1")
    payer_id = ctx1["payer"]["id"]
    # A second CLEARED provider P2 in the SAME org, reusing the existing committee
    # so reviewers are not re-registered, with a distinct NPI.
    reviewers = (ctx1["chair"], ctx1["rev2"], ctx1["rev3"])
    ctx2 = fx.setup_cleared_provider(org_id=org["id"], clock=None, spec_user_id="spec-2",
                                     npi="2222222222", caqh_id="CAQH-2",
                                     license_identifier="LIC-2", reviewers=reviewers)
    en2 = validate_success(api_client.create_payer_enrollment(
        ctx2["provider"]["id"], create_enrollment_payload(payer_id), ENR), 201)
    validate_success(api_client.submit_enrollment(en2["id"], ENR), 200)
    resp = api_client.activate_enrollment(en2["id"], ENR)
    validate_error(resp, ApiErrorId.ERR_PANEL_AT_CAPACITY.value)


# =========================================================================
# Compensating invariants
# =========================================================================
def test_panel_slot_freed_after_activate_then_terminate():
    """PRD §3.6: "Terminating an enrollment moves it from `ACTIVE` to
    `TERMINATED` and frees one panel slot on the payer."

    Design: Difficulty/compensating_invariant/panel_slot_conservation_activate_then_terminate
    """
    ctx = fx.setup_active_enrollment(panel_capacity=1, payer_name="Plan 1cap")
    payer_id = ctx["payer"]["id"]
    terminated = validate_success(api_client.terminate_enrollment(
        ctx["enrollment"]["id"], terminate_enrollment_payload("provider left network"), ENR), 200)
    assert terminated["status"] == "TERMINATED"
    listing = api_client.list_payer_enrollments(ENR, params={"payer_id": payer_id})
    data, _meta = validate_paginated(listing)
    active = [e for e in data if e["status"] == "ACTIVE"]
    assert len(active) == 0, f"panel slot not freed; ACTIVE count = {len(active)}"


def test_sanction_score_freed_after_hit_then_resolve():
    """PRD §3.4: "On resolution the screening moves to `RESOLVED`, and the
    provider's `sanction_score` is recomputed. If that recomputation brings the
    score to zero and the provider has no `LAPSED` credential items, the provider
    is no longer held in the `EXCLUDED` posture."

    Design: Difficulty/compensating_invariant/sanction_score_conservation_hit_then_resolve
    """
    ctx = fx.setup_open_hit_screening(severity_weight=3)
    # Confirm the HIT excluded the provider first.
    before = validate_success(api_client.get_provider(ctx["provider"]["id"], COMP), 200)
    assert before["sanction_score"] == 3
    assert before["credentialing_status"] == "EXCLUDED"
    resolved = validate_success(api_client.resolve_sanctions_screening(
        ctx["screening"]["id"],
        {"resolution_note": "false positive confirmed against full SSN"}, COMP), 200)
    assert resolved["status"] == "RESOLVED"
    after = validate_success(api_client.get_provider(ctx["provider"]["id"], COMP), 200)
    assert after["sanction_score"] == 0
    assert after["credentialing_status"] == "PENDING"


# =========================================================================
# Transitive cascades
# =========================================================================
def test_sanctions_hit_excludes_provider():
    """PRD §3.4: "Recording a `HIT` recomputes the score and the provider's
    posture, which drives the provider toward the `EXCLUDED` posture whenever the
    score is above zero."
    PRD §3.4: "A provider's `sanction_score` is the sum of the `severity_weight`
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
    assert provider["credentialing_status"] == "EXCLUDED"


def test_clock_lapse_demotes_provider_and_terminates_enrollment():
    """PRD §2.7: "Every credential item's `expirable_band` is recomputed against
    the new clock, and an item may transition into `LAPSED`."
    PRD §2.7: "a newly `LAPSED` item demotes a previously `CLEARED` provider to
    `CONDITIONAL`."
    PRD §3.6: "when a provider's `credentialing_status` leaves `CLEARED` —
    demoted to `CONDITIONAL` or `EXCLUDED` — each of that provider's `ACTIVE`
    enrollments is terminated by the system, with its `termination_reason` set
    automatically to `CREDENTIALING_LAPSED`".

    Design: Difficulty/transitive_cascade/clock_lapse_demotes_provider_terminates_enrollment_depth3
    """
    org = validate_success(api_client.create_org(create_org_payload(), ADMIN), 201)
    # Provider CLEARED at 2026-03-01 with a license expiring 2026-04-15.
    ctx = fx.setup_active_enrollment(org_id=org["id"], clock="2026-03-01T00:00:00.000Z",
                                     license_expiration="2026-04-15T00:00:00.000Z",
                                     panel_capacity=5)
    item_id = ctx["item"]["id"]
    enrollment_id = ctx["enrollment"]["id"]
    provider_id = ctx["provider"]["id"]
    # Advance the clock past the license expiry so it lapses.
    validate_success(api_client.set_clock({"to_iso8601": "2026-05-01T00:00:00.000Z"}, ADMIN), 200)
    item = validate_success(api_client.get_credential_item(item_id, SPEC), 200)
    assert item["expirable_band"] == "LAPSED"
    provider = validate_success(api_client.get_provider(provider_id, SPEC), 200)
    assert provider["credentialing_status"] == "CONDITIONAL"
    enrollment = validate_success(api_client.get_payer_enrollment(enrollment_id, ENR), 200)
    assert enrollment["status"] == "TERMINATED"


# =========================================================================
# Re-credentialing cyclic loop + clock demotion threshold
# =========================================================================
def test_clock_advance_to_recred_due_demotes_to_conditional():
    """PRD §2.7: "Any provider whose `recred_state` is `CURRENT` and whose
    `recred_due_date` is now at or before `current_utc` transitions to
    `RECRED_DUE`, and its posture is recomputed to `CONDITIONAL`."

    Design: Corner/cross_cutting_complexity_layers/clock_recred_demotion_threshold
    """
    org = validate_success(api_client.create_org(create_org_payload(), ADMIN), 201)
    # Cleared at 2026-03-01 -> recred_due 2029-02-28. Use a far-future license so
    # only the recred lapse (not an expiry) drives the demotion.
    ctx = fx.setup_cleared_provider(org_id=org["id"], clock="2026-03-01T00:00:00.000Z",
                                    license_expiration="2035-01-01T00:00:00.000Z")
    provider_id = ctx["provider"]["id"]
    validate_success(api_client.set_clock({"to_iso8601": "2029-02-28T00:00:00.000Z"}, ADMIN), 200)
    provider = validate_success(api_client.get_provider(provider_id, SPEC), 200)
    assert provider["recred_state"] == "RECRED_DUE"
    assert provider["credentialing_status"] == "CONDITIONAL"


def test_recred_cyclic_loop_start_recredentialing():
    """PRD §3.7: "Starting re-credentialing moves `recred_state` to
    `IN_RECREDENTIALING`, resets `application_status` to `IN_VERIFICATION`".

    Design: Difficulty/non_linear_state_machine/provider_recred_cyclic_loop
    """
    org = validate_success(api_client.create_org(create_org_payload(), ADMIN), 201)
    ctx = fx.setup_cleared_provider(org_id=org["id"], clock="2026-03-01T00:00:00.000Z",
                                    license_expiration="2035-01-01T00:00:00.000Z")
    provider_id = ctx["provider"]["id"]
    # Advance past the recred_due_date so recred_state flips to RECRED_DUE.
    validate_success(api_client.set_clock({"to_iso8601": "2029-03-01T00:00:00.000Z"}, ADMIN), 200)
    provider = validate_success(api_client.start_recredentialing(provider_id, SPEC), 200)
    assert provider["recred_state"] == "IN_RECREDENTIALING"
    assert provider["application_status"] == "IN_VERIFICATION"


# =========================================================================
# Resource temporal overlap
# =========================================================================
def test_credential_item_interval_overlap_rejected():
    """PRD §3.3: "Any interior overlap — where the first item's issue date
    precedes the second's expiration date *and* the second item's issue date
    precedes the first's expiration date, both strictly — is a conflict and is
    rejected with `ERR_CREDENTIAL_INTERVAL_OVERLAP` (HTTP 409)."

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
    resp = api_client.create_credential_item(
        provider["id"],
        create_credential_item_payload(
            item_type="STATE_LICENSE", identifier="LIC-2",
            issued_date="2026-06-01T00:00:00.000Z",
            expiration_date="2027-06-01T00:00:00.000Z"),
        SPEC)
    validate_error(resp, ApiErrorId.ERR_CREDENTIAL_INTERVAL_OVERLAP.value)


def test_duplicate_payer_enrollment_ongoing_singleton_rejected():
    """PRD §3.6: "any non-terminal enrollment — one whose status is `REQUESTED`,
    `SUBMITTED`, or `ACTIVE` — occupies an open-ended window, so any second
    non-terminal enrollment with the same payer overlaps it and is rejected with
    `ERR_DUPLICATE_PAYER_ENROLLMENT` (HTTP 409), regardless of any date
    arithmetic."

    Design: Difficulty/resource_temporal_overlap/duplicate_payer_enrollment_ongoing_singleton
    """
    org = validate_success(api_client.create_org(create_org_payload(), ADMIN), 201)
    provider = validate_success(api_client.create_provider(create_provider_payload(org["id"]), SPEC), 201)
    payer = fx.create_payer(org["id"], name="Plan P", panel_capacity=5)
    validate_success(api_client.create_payer_enrollment(
        provider["id"], create_enrollment_payload(payer["id"]), ENR), 201)
    resp = api_client.create_payer_enrollment(
        provider["id"], create_enrollment_payload(payer["id"]), ENR)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_PAYER_ENROLLMENT.value)
