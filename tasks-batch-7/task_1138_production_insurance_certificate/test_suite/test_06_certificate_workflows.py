"""Certificate issuance gates: state, OCC, posture priority, window
containment, and count conservation across void/expire (PRD §2.8, §2.9, §3.5)."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    create_certificate_payload,
    set_logical_clock, create_production, create_and_bind_policy,
    activate_production, get_production_version,
    setup_active_production_with_bound_policy,
    setup_production_with_issued_certificate,
    create_draft_certificate, issue_certificate, report_claim,
    TEST_USERS,
)

BROKER = TEST_USERS["broker_headers"]
PM = TEST_USERS["production_manager_headers"]
ADJ = TEST_USERS["claims_adjuster_headers"]
OP = TEST_USERS["platform_operator_headers"]


def _setup_restricted_with_voided_cert():
    """ACTIVE production -> cert created then voided (terminal), then an open
    INJURY claim drives posture to RESTRICTED. Returns (prod, cert, version)."""
    prod, policy = setup_active_production_with_bound_policy()
    cert = create_draft_certificate(
        prod["id"], certificate_type="LOCATION",
        additional_insured_name="Lot Owner")
    validate_success(api_client.void_certificate(prod["id"], cert["id"], BROKER), 200)
    claim = report_claim(prod["id"], policy["id"], claim_type="INJURY",
                         loss_amount_cents=200000)
    validate_success(api_client.acknowledge_claim(prod["id"], claim["id"], ADJ), 200)
    version = get_production_version(prod["id"])
    return prod, cert, version


# ─── Priority: state (5) beats posture (8) (difficulty) ───

def test_issue_voided_cert_on_restricted_posture_returns_invalid_state(api):
    """PRD §2.9: "Inbound requests are validated in a fixed order, and the
    first failure wins — a response never reports more than one error, and an
    earlier failure masks everything after it."
    PRD §2.9 step 5: "On action endpoints, the target entity must currently sit
    in a valid source state for the requested transition; otherwise
    `ERR_INVALID_STATE` (409)."
    PRD §2.9 step 8: "Posture gating on certificate issuance, foreign travel
    approval, and bond issuance, per §2.7."

    The certificate is VOIDED (state violation) and posture is RESTRICTED
    (posture violation); the earlier state check must win.

    Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_on_certificate_issue
    """
    prod, cert, version = _setup_restricted_with_voided_cert()
    res = api.issue_certificate(prod["id"], cert["id"],
                                {"expected_production_version": version}, BROKER)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_issue_issued_cert_on_restricted_posture_returns_invalid_state(api):
    """PRD §2.9: "Inbound requests are validated in a fixed order, and the
    first failure wins — a response never reports more than one error, and an
    earlier failure masks everything after it."
    PRD §2.9 step 5: "On action endpoints, the target entity must currently sit
    in a valid source state for the requested transition; otherwise
    `ERR_INVALID_STATE` (409)."

    Companion pair-case: the certificate is ISSUED (not a valid source state
    for issuance) while posture is RESTRICTED; the state check still wins.

    Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_on_certificate_issue
    """
    prod, policy, cert = setup_production_with_issued_certificate()
    claim = report_claim(prod["id"], policy["id"], claim_type="INJURY",
                         loss_amount_cents=200000)
    validate_success(api.acknowledge_claim(prod["id"], claim["id"], ADJ), 200)
    version = get_production_version(prod["id"])
    res = api.issue_certificate(prod["id"], cert["id"],
                                {"expected_production_version": version}, BROKER)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


# ─── Invalid transition (corner) ──────────────────────

def test_certificate_issue_invalid_from_issued(api):
    """PRD §2.9 step 5: "On action endpoints, the target entity must currently
    sit in a valid source state for the requested transition; otherwise
    `ERR_INVALID_STATE` (409)."
    PRD §3.5: "Issuance — `DRAFT` → `ISSUED`, by a `BrokerAgent`"

    Design: Corner/state_machines/certificate_issue_invalid_from_issued
    """
    prod, policy, cert = setup_production_with_issued_certificate()
    assert cert["status"] == "ISSUED"
    version = get_production_version(prod["id"])
    res = api.issue_certificate(prod["id"], cert["id"],
                                {"expected_production_version": version}, BROKER)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


# ─── Coverage line not bound (corner) ─────────────────

def test_certificate_coverage_line_not_bound(api):
    """PRD §3.5: "Every coverage line listed on the certificate must be backed
    by at least one policy on this production in `BOUND`, `ENDORSED_PENDING`,
    or `ACTIVE`, or the refusal is `ERR_COVERAGE_LINE_NOT_BOUND`."

    Design: Corner/validations/certificate_coverage_line_not_bound
    """
    prod, policy = setup_active_production_with_bound_policy()
    cert = create_draft_certificate(prod["id"], certificate_type="EQUIPMENT_RENTAL",
                                    coverage_lines=["EQUIPMENT"])
    version = get_production_version(prod["id"])
    res = api.issue_certificate(prod["id"], cert["id"],
                                {"expected_production_version": version}, BROKER)
    validate_error(res, "ERR_COVERAGE_LINE_NOT_BOUND", expected_status=422)


# ─── OCC stale version on issue (corner) ──────────────

def test_occ_stale_version_on_certificate_issue(api):
    """PRD §2.8: "If the production's current `version` no longer matches —
    for example because another writer has just bound a policy, revoked an
    endorsement, or flagged a clearance item, any of which may have moved
    `coverage_posture` — the issuance is rejected with `ERR_STALE_VERSION`
    (HTTP 412)."
    PRD §3.1: "Binding has two further consequences beyond the policy row
    itself: the owning production's `version` increments, and the production's
    `coverage_posture` is recomputed."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_version_on_certificate_issue
    """
    prod, policy = setup_active_production_with_bound_policy()
    cert = create_draft_certificate(
        prod["id"], certificate_type="LOCATION", additional_insured_name="Owner")
    stale_version = get_production_version(prod["id"])
    # Bind a second policy: a write that unambiguously increments the
    # production's version, making the captured version stale.
    create_and_bind_policy(prod["id"], coverage_line="EQUIPMENT",
                           carrier_code="TRAVELERS")
    res = api.issue_certificate(prod["id"], cert["id"],
                                {"expected_production_version": stale_version}, BROKER)
    validate_error(res, "ERR_STALE_VERSION", expected_status=412)


# ─── Window upper-exclusive boundary (difficulty) ─────

def test_cert_location_end_equal_policy_expiry_rejected(api):
    """PRD §3.5: "A `location_start` exactly equal to a policy's
    `effective_date` is allowed; a `location_end` exactly equal to a policy's
    `expiry_date` is not, because it would touch the policy window's exclusive
    upper boundary."
    PRD §3.5: "The coverage window itself is validated against two envelopes,
    and a violation of either is `ERR_CERT_WINDOW_OUTSIDE_POLICY` (HTTP 422)."

    Policy window [2026-05-01, 2026-06-30); certificate [2026-06-01, 2026-06-30]
    lands its end exactly on the exclusive upper bound.

    Design: Difficulty/boundary_precision_check/certificate_window_upper_exclusive_boundary
    """
    prod, policy = setup_active_production_with_bound_policy(
        production_overrides={"principal_photography_end": "2026-06-30T00:00:00Z"},
        policy_overrides={"expiry_date": "2026-06-30T00:00:00Z"})
    cert = create_draft_certificate(
        prod["id"], certificate_type="LOCATION", additional_insured_name="Lot Owner",
        location_start="2026-06-01T00:00:00Z", location_end="2026-06-30T00:00:00Z")
    version = get_production_version(prod["id"])
    res = api.issue_certificate(prod["id"], cert["id"],
                                {"expected_production_version": version}, BROKER)
    validate_error(res, "ERR_CERT_WINDOW_OUTSIDE_POLICY", expected_status=422)


def test_cert_allowed_boundary_touches_issue_successfully(api):
    """PRD §3.5: "the certificate window must lie within the production's outer
    envelope, which runs from `principal_photography_start` to thirty days past
    `principal_photography_end` — a `location_end` landing exactly on that
    thirtieth day is allowed, touching the outer boundary."
    PRD §2.10: "A certificate's `certificate_number` is not client-supplied at
    all: it is minted by the server at issuance time in the format
    `CERT-<prod>-<seq>`"

    Certificate [policy.effective_date, principal_photography_end + 30 days]
    touches both allowed inclusive boundaries and must issue.

    Design: Difficulty/boundary_precision_check/certificate_window_upper_exclusive_boundary
    """
    prod, policy = setup_active_production_with_bound_policy(
        production_overrides={
            "principal_photography_start": "2026-06-01T00:00:00Z",
            "principal_photography_end": "2026-06-30T00:00:00Z"},
        policy_overrides={"effective_date": "2026-06-01T00:00:00Z",
                          "expiry_date": "2026-12-31T00:00:00Z"})
    cert = create_draft_certificate(
        prod["id"], certificate_type="LOCATION", additional_insured_name="Lot Owner",
        location_start="2026-06-01T00:00:00Z", location_end="2026-07-30T00:00:00Z")
    version = get_production_version(prod["id"])
    issued = validate_success(
        api.issue_certificate(prod["id"], cert["id"],
                              {"expected_production_version": version}, BROKER), 200)
    assert issued["status"] == "ISSUED"
    assert isinstance(issued["certificate_number"], str)
    assert issued["certificate_number"].startswith("CERT-")


# ─── Window subset check (difficulty) ─────────────────

def test_cert_window_past_production_envelope_rejected(api):
    """PRD §3.5: "First, the certificate window must lie within the
    production's outer envelope, which runs from `principal_photography_start`
    to thirty days past `principal_photography_end`"
    PRD §3.5: "The coverage window itself is validated against two envelopes,
    and a violation of either is `ERR_CERT_WINDOW_OUTSIDE_POLICY` (HTTP 422)."

    Photography ends 2026-08-01, so the outer envelope ends 2026-08-31; the
    certificate's location_end of 2026-10-01 overshoots it.

    Design: Difficulty/resource_temporal_overlap/certificate_window_subset_check
    """
    prod, policy = setup_active_production_with_bound_policy(
        production_overrides={
            "principal_photography_start": "2026-06-01T00:00:00Z",
            "principal_photography_end": "2026-08-01T00:00:00Z"},
        policy_overrides={"effective_date": "2026-06-01T00:00:00Z"})
    cert = create_draft_certificate(
        prod["id"], certificate_type="LOCATION", additional_insured_name="Far Lot",
        location_start="2026-06-01T00:00:00Z", location_end="2026-10-01T00:00:00Z")
    version = get_production_version(prod["id"])
    res = api.issue_certificate(prod["id"], cert["id"],
                                {"expected_production_version": version}, BROKER)
    validate_error(res, "ERR_CERT_WINDOW_OUTSIDE_POLICY", expected_status=422)


def test_cert_window_outside_policy_window_rejected(api):
    """PRD §3.5: "for each coverage line on the certificate, the certificate
    window must lie within the intersection of every bound policy's
    `effective_date`-to-`expiry_date` window on that line."
    PRD §3.5: "The coverage window itself is validated against two envelopes,
    and a violation of either is `ERR_CERT_WINDOW_OUTSIDE_POLICY` (HTTP 422)."

    The certificate starts 2026-06-05, ten days before the policy's
    effective_date of 2026-06-15 — inside the production envelope but outside
    the policy window.

    Design: Difficulty/resource_temporal_overlap/certificate_window_subset_check
    """
    prod, policy = setup_active_production_with_bound_policy(
        production_overrides={
            "principal_photography_start": "2026-06-01T00:00:00Z",
            "principal_photography_end": "2026-08-01T00:00:00Z"},
        policy_overrides={"effective_date": "2026-06-15T00:00:00Z"})
    cert = create_draft_certificate(
        prod["id"], certificate_type="LOCATION", additional_insured_name="Early Lot",
        location_start="2026-06-05T00:00:00Z", location_end="2026-06-20T00:00:00Z")
    version = get_production_version(prod["id"])
    res = api.issue_certificate(prod["id"], cert["id"],
                                {"expected_production_version": version}, BROKER)
    validate_error(res, "ERR_CERT_WINDOW_OUTSIDE_POLICY", expected_status=422)


# ─── Certificate count conservation (difficulty) ──────

def test_certificate_count_conserved_across_wrap_expire(api):
    """PRD §3.9: "A successful wrap ripples outward: every `ISSUED` certificate
    auto-expires, every `ACTIVE` foreign travel extension auto-expires, an
    `ISSUED` completion bond auto-transitions to `RELEASED`, and for each
    `ACTIVE` policy a payroll audit is scheduled in `SCHEDULED` status so the
    final premium can be struck (§3.10)."

    Two certificates are issued (forward action: DRAFT -> ISSUED keeps the
    count at two), then wrap auto-expires both (compensating action: ISSUED ->
    EXPIRED still keeps the count at two).

    Design: Difficulty/compensating_invariant/certificate_count_conservation_across_void_expire
    """
    prod, policy = setup_active_production_with_bound_policy(
        production_overrides={"principal_photography_end": "2026-06-30T00:00:00Z"})
    cert_a = issue_certificate(prod["id"], create_draft_certificate(
        prod["id"], certificate_type="LOCATION", additional_insured_name="A Owner",
        location_start="2026-06-01T00:00:00Z",
        location_end="2026-06-15T00:00:00Z")["id"])
    cert_b = issue_certificate(prod["id"], create_draft_certificate(
        prod["id"], certificate_type="VENDOR",
        location_start="2026-06-16T00:00:00Z",
        location_end="2026-06-30T00:00:00Z")["id"])
    assert cert_a["status"] == "ISSUED" and cert_b["status"] == "ISSUED"

    _, meta_before = validate_paginated(api.list_certificates(prod["id"], BROKER))
    assert meta_before["total_count"] == 2

    validate_success(api.wrap_production(prod["id"], PM), 200)

    _, meta_after = validate_paginated(api.list_certificates(prod["id"], BROKER))
    assert meta_after["total_count"] == 2
    cert_a_after = validate_success(api.get_certificate(prod["id"], cert_a["id"], BROKER), 200)
    cert_b_after = validate_success(api.get_certificate(prod["id"], cert_b["id"], BROKER), 200)
    assert cert_a_after["status"] == "EXPIRED"
    assert cert_b_after["status"] == "EXPIRED"


def test_certificate_count_conserved_across_clock_expire(api):
    """PRD §2.5: "an issued certificate expires once the clock passes
    `location_end`"

    The forward action (issue) adds no row, and the compensating clock-driven
    expiry changes only the status mix — the certificate still exists and the
    production's certificate count stays at one.

    Design: Difficulty/compensating_invariant/certificate_count_conservation_across_void_expire
    """
    prod, policy, cert = setup_production_with_issued_certificate(
        cert_overrides={"certificate_type": "LOCATION",
                        "additional_insured_name": "Owner",
                        "location_start": "2026-06-01T00:00:00Z",
                        "location_end": "2026-06-15T00:00:00Z"})
    assert cert["status"] == "ISSUED"

    set_logical_clock("2026-06-16T00:00:00Z")

    fetched = validate_success(api.get_certificate(prod["id"], cert["id"], BROKER), 200)
    assert fetched["status"] == "EXPIRED"
    _, meta = validate_paginated(api.list_certificates(prod["id"], BROKER))
    assert meta["total_count"] == 1
