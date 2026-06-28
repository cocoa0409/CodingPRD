"""Force-majeure cutoff / landfall window rules and additional-insured certificates.

Queue A:
  resource_temporal_overlap / force_majeure_bound_at_or_after_cutoff_barred
  resource_temporal_overlap / force_majeure_landfall_outside_closed_event_window_barred
  cross_entity_state_dependency / certificate_issue_requires_active_liability_coverage
"""
from test_helpers import (
    validate_success, validate_error, make_policyholder_headers, TEST_USERS,
)
from test_helpers import fixtures as FX

_admin = TEST_USERS["admin_headers"]
_uw = TEST_USERS["underwriter_headers"]
_adj = TEST_USERS["adjuster_headers"]
_ph = make_policyholder_headers("ph-1")


def _force_majeure_setup(peril_overrides, claimed=1000000):
    """In-force CANCELLATION policy + ACTIVE peril + FORCE_MAJEURE claim with one document.

    Returns (policy_id, claim_id, peril_id).
    """
    canc = FX.create_cancellation_product()
    venue = FX.create_venue()
    peril = FX.create_active_peril(**peril_overrides)
    policy = FX.create_quoted_policy()
    FX.add_event_profile(policy["id"], venue["id"], expected_attendance=150,
                         event_start_at="2026-08-01T18:00:00Z",
                         event_end_at="2026-08-01T23:00:00Z")
    coverage = FX.add_coverage(policy["id"], canc["id"])
    FX.bind_policy(policy["id"])
    FX.pay_policy(policy["id"], 65000)
    FX.activate_coverage(policy["id"])
    claim = FX.file_claim(policy["id"], coverage["id"], "FORCE_MAJEURE", claimed,
                          force_majeure_event_id=peril["id"])
    FX.attach_document(policy["id"], claim["id"], doc_type="POLICE_REPORT",
                       file_uri="s3://docs/storm.pdf")
    return policy["id"], claim["id"], peril["id"]


def test_force_majeure_bound_at_or_after_cutoff_barred(api):
    """PRD §3.7: "the policy's `bind_at` must be strictly before the peril's `cutoff_at` —
    a policy bound at or after the cutoff is rejected with `ERR_BOUND_AFTER_CUTOFF`, which
    is the named-storm cutoff rule".

    Design: Difficulty/resource_temporal_overlap/force_majeure_bound_at_or_after_cutoff_barred
    """
    # Default clock 2026-01-01T00:00:00Z is the bind_at; cutoff exactly at that instant.
    pid, cid, _ = _force_majeure_setup(
        {"peril_name": "Hurricane Della", "peril_type": "NAMED_STORM",
         "cutoff_at": "2026-01-01T00:00:00Z", "landfall_at": "2026-08-01T19:00:00Z"})
    res = api.approve_claim(pid, cid, _adj)
    validate_error(res, "ERR_BOUND_AFTER_CUTOFF", 422)
    refreshed = validate_success(api.get_claim(pid, cid, _uw), 200)
    assert refreshed["status"] == "SUBMITTED"


def test_force_majeure_bound_strictly_before_cutoff_payout_allowed(api):
    """PRD §3.7: "the policy's `bind_at` must be strictly before the peril's `cutoff_at` —
    a policy bound at or after the cutoff is rejected with `ERR_BOUND_AFTER_CUTOFF`".
    PRD §3.7: "the peril's `landfall_at` must fall within the
    `event_start_at`-to-`event_end_at` window of some event profile on the policy".

    Design: Difficulty/resource_temporal_overlap/force_majeure_bound_at_or_after_cutoff_barred
    """
    # bind_at is the default clock 2026-01-01; cutoff is strictly later, landfall inside window.
    pid, cid, _ = _force_majeure_setup(
        {"peril_name": "Hurricane Foxtrot", "peril_type": "NAMED_STORM",
         "cutoff_at": "2026-07-01T00:00:00Z", "landfall_at": "2026-08-01T19:00:00Z"})
    approved = validate_success(api.approve_claim(pid, cid, _adj), 200)
    assert approved["status"] == "APPROVED"


def test_force_majeure_landfall_outside_closed_event_window_barred(api):
    """PRD §3.7: "the peril's `landfall_at` must fall within the
    `event_start_at`-to-`event_end_at` window of some event profile on the policy, or
    `ERR_LANDFALL_OUTSIDE_WINDOW` is returned."

    Design: Difficulty/resource_temporal_overlap/force_majeure_landfall_outside_closed_event_window_barred
    """
    # cutoff in the future (so the cutoff check passes); landfall AFTER the event window.
    pid, cid, _ = _force_majeure_setup(
        {"peril_name": "Hurricane Echo", "peril_type": "NAMED_STORM",
         "cutoff_at": "2026-07-01T00:00:00Z", "landfall_at": "2026-08-02T12:00:00Z"})
    res = api.approve_claim(pid, cid, _adj)
    validate_error(res, "ERR_LANDFALL_OUTSIDE_WINDOW", 422)
    refreshed = validate_success(api.get_claim(pid, cid, _uw), 200)
    assert refreshed["status"] == "SUBMITTED"


def test_force_majeure_landfall_before_event_window_barred(api):
    """PRD §3.7: "the peril's `landfall_at` must fall within the
    `event_start_at`-to-`event_end_at` window of some event profile on the policy, or
    `ERR_LANDFALL_OUTSIDE_WINDOW` is returned."

    Design: Difficulty/resource_temporal_overlap/force_majeure_landfall_outside_closed_event_window_barred
    """
    # cutoff in the future (passes); landfall BEFORE the event window start (outside).
    pid, cid, _ = _force_majeure_setup(
        {"peril_name": "Hurricane Golf", "peril_type": "NAMED_STORM",
         "cutoff_at": "2026-07-01T00:00:00Z", "landfall_at": "2026-07-31T12:00:00Z"})
    res = api.approve_claim(pid, cid, _adj)
    validate_error(res, "ERR_LANDFALL_OUTSIDE_WINDOW", 422)
    refreshed = validate_success(api.get_claim(pid, cid, _uw), 200)
    assert refreshed["status"] == "SUBMITTED"


def test_certificate_issue_requires_active_liability_coverage(api):
    """PRD §3.8: "it requires the policy to hold at least one `ACTIVE` coverage line whose
    product `coverage_type` is `LIABILITY`, or `ERR_NO_LIABILITY_COVERAGE` is returned."

    Design: Difficulty/cross_entity_state_dependency/certificate_issue_requires_active_liability_coverage
    """
    # Bound policy whose only coverage is CANCELLATION; one REQUESTED certificate.
    canc = FX.create_cancellation_product()
    venue = FX.create_venue()
    policy = FX.create_quoted_policy()
    FX.add_event_profile(policy["id"], venue["id"], expected_attendance=150)
    FX.add_coverage(policy["id"], canc["id"])
    cert = FX.add_certificate(policy["id"], venue["id"], additional_insured_name="Grand Hall LLC")
    FX.bind_policy(policy["id"])
    res = api.issue_certificate(policy["id"], cert["id"], _uw)
    validate_error(res, "ERR_NO_LIABILITY_COVERAGE", 422)
    certs = validate_success(api.list_certificates(policy["id"], _uw), 200)
    requested = next(c for c in certs if c["id"] == cert["id"])
    assert requested["status"] == "REQUESTED"


def test_certificate_issue_succeeds_with_active_liability_coverage(api):
    """PRD §3.8: "An `UnderwritingAgent` issues a requested certificate, advancing it from
    `REQUESTED` to `ISSUED`."
    PRD §3.8: "it requires the policy to hold at least one `ACTIVE` coverage line whose
    product `coverage_type` is `LIABILITY`, or `ERR_NO_LIABILITY_COVERAGE` is returned."

    Design: Difficulty/cross_entity_state_dependency/certificate_issue_requires_active_liability_coverage
    """
    liab = FX.create_liability_product()
    venue = FX.create_venue()
    policy = FX.create_quoted_policy()
    FX.add_event_profile(policy["id"], venue["id"], expected_attendance=150)
    FX.add_coverage(policy["id"], liab["id"])
    cert = FX.add_certificate(policy["id"], venue["id"], additional_insured_name="Grand Hall LLC")
    FX.bind_policy(policy["id"])
    issued = validate_success(api.issue_certificate(policy["id"], cert["id"], _uw), 200)
    assert issued["status"] == "ISSUED"
