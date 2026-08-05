"""Variance permits: dual-variant fee, half-open window overlap, issuance gating,
and the cross-entity block on substantiation (queue A depth + queue B corner)."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    permit_clerk_headers, code_officer_headers,
)
from test_helpers import fixtures as fx


def _new_variance(api, prop_id, **overrides):
    payload = {
        "property_id": prop_id,
        "permit_type": "CONSTRUCTION",
        "requested_start": "2026-06-01T00:00:00Z",
        "requested_end": "2026-06-05T00:00:00Z",
        "permitted_max_db": 90,
    }
    payload.update(overrides)
    return validate_success(api.create_variance_permit(payload, permit_clerk_headers()), 201)


# --- Dual-variant fee: estimate vs final (queue A) ---

def test_variance_estimate_fee_from_requested_window(api):
    """PRD §3.5: "For a `CONSTRUCTION` permit the fee is a base of $50.00 (5000 cents) plus
    $25.00 (2500 cents) per day of the window, where the number of days is the window's total
    duration in seconds divided by 86,400 and rounded **up** to the next whole day."
    PRD §3.5: "The estimate uses the requested window and requested attendees".

    Design: Difficulty/dual_variant_calc/variance_fee_estimate_vs_final
    """
    prop = fx.new_property(api, "RESIDENTIAL", address="2 Build Rd")
    var = _new_variance(api, prop["id"], permit_type="CONSTRUCTION",
                        requested_start="2026-06-01T00:00:00Z", requested_end="2026-06-11T00:00:00Z")
    assert var["fee_estimate_cents"] == 30000


def test_variance_final_fee_from_narrowed_approved_window(api):
    """PRD §3.5: "the final fee, computed at issuance, uses the approved window and approved
    attendees, so the two diverge whenever the clerk narrows the window."
    PRD §3.5: "At issuance the clerk may narrow the window by supplying `approved_start` and
    `approved_end` ... The approved window is then locked, and `fee_final_cents` is computed from it."

    Design: Difficulty/dual_variant_calc/variance_fee_estimate_vs_final
    """
    prop = fx.new_property(api, "RESIDENTIAL", address="2 Build Rd")
    var = _new_variance(api, prop["id"], permit_type="CONSTRUCTION",
                        requested_start="2026-06-01T00:00:00Z", requested_end="2026-06-11T00:00:00Z")
    issued = validate_success(api.issue_variance_permit(
        var["id"], {"approved_start": "2026-06-01T00:00:00Z", "approved_end": "2026-06-07T00:00:00Z"},
        permit_clerk_headers()), 200)
    assert issued["status"] == "ISSUED"
    assert issued["fee_final_cents"] == 20000


def test_event_variance_estimate_fee(api):
    """PRD §3.5: "For an `EVENT` permit the fee is a base of $100.00 (10000 cents) plus
    $0.50 (50 cents) per expected attendee."

    Design: Corner/calculations/variance_fee_event_formula_correct
    """
    prop = fx.new_property(api, "COMMERCIAL", address="109 Main St")
    var = _new_variance(api, prop["id"], permit_type="EVENT",
                        requested_start="2026-06-05T08:00:00Z", requested_end="2026-06-05T23:00:00Z",
                        permitted_max_db=90, expected_attendees=200)
    assert var["fee_estimate_cents"] == 20000


# --- Half-open window overlap (queue A) ---

def test_overlapping_variance_window_rejected(api):
    """PRD §3.5: "the new approved window, treated as the half-open interval from
    `approved_start` inclusive to `approved_end` exclusive, must not overlap the approved
    window of any other `ISSUED` variance on the same parcel (`ERR_VARIANCE_WINDOW_OVERLAP`)."

    Design: Difficulty/resource_temporal_overlap/variance_window_overlap_half_open
    """
    prop = fx.new_property(api, "COMMERCIAL", address="15 Site Rd")
    v1 = _new_variance(api, prop["id"], requested_start="2026-06-01T00:00:00Z", requested_end="2026-06-10T00:00:00Z")
    validate_success(api.issue_variance_permit(v1["id"], {}, permit_clerk_headers()), 200)
    v2 = _new_variance(api, prop["id"], requested_start="2026-06-05T00:00:00Z", requested_end="2026-06-15T00:00:00Z")
    resp = api.issue_variance_permit(v2["id"], {}, permit_clerk_headers())
    validate_error(resp, ApiErrorId.ERR_VARIANCE_WINDOW_OVERLAP.value)


def test_adjacent_variance_window_allowed_half_open(api):
    """PRD §3.5: "the new approved window, treated as the half-open interval from
    `approved_start` inclusive to `approved_end` exclusive, must not overlap the approved
    window of any other `ISSUED` variance on the same parcel (`ERR_VARIANCE_WINDOW_OVERLAP`)."

    Design: Difficulty/resource_temporal_overlap/variance_window_overlap_half_open
    """
    prop = fx.new_property(api, "COMMERCIAL", address="15 Site Rd")
    v1 = _new_variance(api, prop["id"], requested_start="2026-06-01T00:00:00Z", requested_end="2026-06-10T00:00:00Z")
    validate_success(api.issue_variance_permit(v1["id"], {}, permit_clerk_headers()), 200)
    v3 = _new_variance(api, prop["id"], requested_start="2026-06-10T00:00:00Z", requested_end="2026-06-20T00:00:00Z")
    issued = validate_success(api.issue_variance_permit(v3["id"], {}, permit_clerk_headers()), 200)
    assert issued["status"] == "ISSUED"


# --- Issuance gating (queue B) ---

def test_variance_db_over_cap_rejected(api):
    """PRD §3.5: "the `permitted_max_db` must not exceed the absolute ceiling of 95 decibels
    (`ERR_VARIANCE_DB_EXCEEDS_CAP`)".

    Design: Corner/validations/variance_db_exceeds_cap_rejected
    """
    prop = fx.new_property(api, "INDUSTRIAL", address="115 Main St")
    var = _new_variance(api, prop["id"], requested_start="2026-06-01T00:00:00Z",
                        requested_end="2026-06-03T00:00:00Z", permitted_max_db=100)
    resp = api.issue_variance_permit(var["id"], {}, permit_clerk_headers())
    validate_error(resp, ApiErrorId.ERR_VARIANCE_DB_EXCEEDS_CAP.value)


def test_variance_invalid_window_rejected(api):
    """PRD §3.5: "a requested window given by `requested_start` and `requested_end` (the end
    must be strictly after the start, else `ERR_INVALID_WINDOW`)".

    Design: Corner/validations/variance_invalid_window_rejected
    """
    prop = fx.new_property(api, "COMMERCIAL", address="116 Main St")
    resp = api.create_variance_permit({
        "property_id": prop["id"], "permit_type": "CONSTRUCTION",
        "requested_start": "2026-06-05T00:00:00Z", "requested_end": "2026-06-01T00:00:00Z",
        "permitted_max_db": 90,
    }, permit_clerk_headers())
    validate_error(resp, ApiErrorId.ERR_INVALID_WINDOW.value)


def test_issue_denied_variance_rejected(api):
    """PRD §3.5: "issue and deny require the permit to be `UNDER_REVIEW`, else
    `ERR_VARIANCE_NOT_UNDER_REVIEW`".

    Design: Corner/state_machines/variance_issue_from_denied_rejected
    """
    prop = fx.new_property(api, "COMMERCIAL", address="105 Main St")
    var = _new_variance(api, prop["id"], requested_start="2026-06-01T00:00:00Z", requested_end="2026-06-05T00:00:00Z")
    validate_success(api.deny_variance_permit(var["id"], {}, permit_clerk_headers()), 200)
    resp = api.issue_variance_permit(var["id"], {}, permit_clerk_headers())
    validate_error(resp, ApiErrorId.ERR_VARIANCE_NOT_UNDER_REVIEW.value)


# --- Cross-entity block on substantiation (queue A) ---

def test_issued_variance_blocks_substantiation(api):
    """PRD §3.4: "if some issued variance's approved window covers the complaint's
    `reported_at` and grants a `permitted_max_db` at least as high as the latest inspection's
    `measured_decibel`, substantiation is blocked with `ERR_VARIANCE_COVERS_COMPLAINT`."

    Design: Difficulty/cross_entity_state_dependency/substantiate_blocked_by_issued_variance
    """
    fx.config_policy(api, "COMMERCIAL", day_limit=65, night_limit=55)
    prop = fx.new_property(api, "COMMERCIAL", address="13 Gala Pl")
    var = _new_variance(api, prop["id"], permit_type="EVENT",
                        requested_start="2026-06-05T08:00:00Z", requested_end="2026-06-05T23:00:00Z",
                        permitted_max_db=92, expected_attendees=200)
    validate_success(api.issue_variance_permit(var["id"], {}, permit_clerk_headers()), 200)
    c = fx.file_complaint(api, prop["id"], "2026-06-05T12:00:00Z", noise_type="AMPLIFIED_MUSIC")
    fx.review(api, c["id"])
    fx.inspect(api, c["id"], 90, "2026-06-05T12:00:00Z")
    resp = api.substantiate_complaint(c["id"], code_officer_headers("officer-1"))
    validate_error(resp, ApiErrorId.ERR_VARIANCE_COVERS_COMPLAINT.value)


def test_blocked_substantiation_leaves_complaint_under_review(api):
    """PRD §3.4: "A `CodeOfficer` substantiates an under-review complaint, which — when all
    preconditions hold — issues an `Enforcement` and cascades posture changes onto the parcel."
    PRD §3.4: substantiation "is blocked with `ERR_VARIANCE_COVERS_COMPLAINT`."

    Design: Difficulty/cross_entity_state_dependency/substantiate_blocked_by_issued_variance
    """
    fx.config_policy(api, "COMMERCIAL", day_limit=65, night_limit=55)
    prop = fx.new_property(api, "COMMERCIAL", address="13 Gala Pl")
    var = _new_variance(api, prop["id"], permit_type="EVENT",
                        requested_start="2026-06-05T08:00:00Z", requested_end="2026-06-05T23:00:00Z",
                        permitted_max_db=92, expected_attendees=200)
    validate_success(api.issue_variance_permit(var["id"], {}, permit_clerk_headers()), 200)
    c = fx.file_complaint(api, prop["id"], "2026-06-05T12:00:00Z", noise_type="AMPLIFIED_MUSIC")
    fx.review(api, c["id"])
    fx.inspect(api, c["id"], 90, "2026-06-05T12:00:00Z")
    api.substantiate_complaint(c["id"], code_officer_headers("officer-1"))
    fresh = validate_success(api.get_complaint(c["id"], code_officer_headers()), 200)
    assert fresh["status"] == "UNDER_REVIEW"


# --- Priority-pair: state (5) beats temporal (8) (queue A) ---

def test_state_check_precedes_variance_coverage_check(api):
    """PRD §2.5: "the checks are evaluated in a fixed priority order, and the first failure
    is the one reported". PRD §2.5 lists "5. **State** — the target resource is in the correct
    state for the operation" before "8. **Temporal / interval** — variance-coverage,
    variance-window-overlap, hearing-slot-buffer, and abatement-deadline rules".

    Design: Difficulty/priority_pair_validation_conflict/substantiate_state_beats_temporal
    """
    fx.config_policy(api, "COMMERCIAL", day_limit=65, night_limit=55)
    prop = fx.new_property(api, "COMMERCIAL", address="9 Fest Sq")
    var = _new_variance(api, prop["id"], permit_type="EVENT",
                        requested_start="2026-06-05T08:00:00Z", requested_end="2026-06-05T23:00:00Z",
                        permitted_max_db=92, expected_attendees=100)
    validate_success(api.issue_variance_permit(var["id"], {}, permit_clerk_headers()), 200)
    c = fx.file_complaint(api, prop["id"], "2026-06-05T12:00:00Z", noise_type="AMPLIFIED_MUSIC", reported_decibel=90)
    # complaint left in RECEIVED (never reviewed)
    resp = api.substantiate_complaint(c["id"], code_officer_headers("officer-1"))
    validate_error(resp, ApiErrorId.ERR_COMPLAINT_NOT_UNDER_REVIEW.value)


def test_received_complaint_with_covering_variance_stays_received(api):
    """PRD §3.2: "Substantiation and dismissal both require the complaint to be in
    `UNDER_REVIEW`; attempting either from any other state is rejected with
    `ERR_COMPLAINT_NOT_UNDER_REVIEW`."

    Design: Difficulty/priority_pair_validation_conflict/substantiate_state_beats_temporal
    """
    fx.config_policy(api, "COMMERCIAL", day_limit=65, night_limit=55)
    prop = fx.new_property(api, "COMMERCIAL", address="9 Fest Sq")
    var = _new_variance(api, prop["id"], permit_type="EVENT",
                        requested_start="2026-06-05T08:00:00Z", requested_end="2026-06-05T23:00:00Z",
                        permitted_max_db=92, expected_attendees=100)
    validate_success(api.issue_variance_permit(var["id"], {}, permit_clerk_headers()), 200)
    c = fx.file_complaint(api, prop["id"], "2026-06-05T12:00:00Z", noise_type="AMPLIFIED_MUSIC", reported_decibel=90)
    api.substantiate_complaint(c["id"], code_officer_headers("officer-1"))
    fresh = validate_success(api.get_complaint(c["id"], code_officer_headers()), 200)
    assert fresh["status"] == "RECEIVED"
