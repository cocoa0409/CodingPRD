"""Fee-schedule closed-interval overlap and OCC, plus enrollment half-open interval
semantics (boundary-touch accepted vs interior overlap rejected).

Translates the resource_temporal_overlap difficulty instances plus the
fee-schedule OCC and enrollment-overlap corner instances.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    make_account_manager_headers, make_credentialing_specialist_headers,
    create_enrollment_payload,
)
from test_helpers import fixtures as fx

AM = make_account_manager_headers()
CRED = make_credentialing_specialist_headers()


# ---- Difficulty: resource_temporal_overlap / fee schedule closed-interval overlap ----
def _practice_with_active_fs1_and_draft_fs2(api, fs2_effective, fs2_end):
    """Practice with FS1 [2026-01-01,2026-06-30] ACTIVE and a DRAFT FS2 with a line.
    Returns (practice_current_version, fs2_id)."""
    fx.set_clock(api, "2026-06-01T00:00:00Z")
    prac = fx.new_practice(api)
    fx.new_active_fee_schedule(api, prac["id"], prac["version"], prices={"99213": 10000},
                               effective_date="2026-01-01T00:00:00Z", end_date="2026-06-30T00:00:00Z")
    practice_now = validate_success(api.get_practice(prac["id"], AM), 200)
    fs2 = fx.new_fee_schedule_with_lines(api, prac["id"], prices={"99213": 11000},
                                         effective_date=fs2_effective, end_date=fs2_end)
    return practice_now["version"], fs2["id"]


def test_fee_schedule_shared_endpoint_overlap_rejected(api):
    """PRD §3.1: "no other `ACTIVE` fee schedule for the same practice has an effective
    interval that overlaps this one; overlap is evaluated on the closed-closed
    `[effective_date, end_date]` intervals (an open-ended schedule extends without upper
    bound), and a collision is rejected with `ERR_FEE_SCHEDULE_OVERLAP` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/fee_schedule_closed_interval_shared_endpoint_overlap_rejected
    """
    prac_v, fs2_id = _practice_with_active_fs1_and_draft_fs2(
        api, fs2_effective="2026-06-30T00:00:00Z", fs2_end="2026-12-31T00:00:00Z")
    resp = api.activate_fee_schedule(fs2_id, {"expected_practice_version": prac_v}, AM)
    validate_error(resp, ApiErrorId.ERR_FEE_SCHEDULE_OVERLAP.value)


def test_fee_schedule_overlap_leaves_fs2_draft(api):
    """PRD §3.1: "Activating a draft fee schedule moves it from `DRAFT` to `ACTIVE`.
    Activation is permitted only when the schedule is in `DRAFT`, has at least one
    `FeeScheduleLine`, and when no other `ACTIVE` fee schedule for the same practice has
    an effective interval that overlaps this one"

    Design: Difficulty/resource_temporal_overlap/fee_schedule_closed_interval_shared_endpoint_overlap_rejected
    """
    prac_v, fs2_id = _practice_with_active_fs1_and_draft_fs2(
        api, fs2_effective="2026-06-30T00:00:00Z", fs2_end="2026-12-31T00:00:00Z")
    api.activate_fee_schedule(fs2_id, {"expected_practice_version": prac_v}, AM)
    fs2 = validate_success(api.get_fee_schedule(fs2_id, AM), 200)
    assert fs2["status"] == "DRAFT", fs2["status"]


# ---- Difficulty: resource_temporal_overlap / enrollment half-open boundary touch ----
def _provider_payer_with_terminating_e1(api):
    """Practice/payer/provider with E1 [2026-01-01, 2026-06-01) created. Returns
    (provider_id, payer_id)."""
    fx.set_clock(api, "2026-06-01T00:00:00Z")
    prac = fx.new_practice(api)
    payer = fx.new_payer(api)
    prov = fx.new_provider(api, prac["id"])
    fx.new_enrollment(api, prov["id"], payer["id"], effective_date="2026-01-01T00:00:00Z",
                      termination_date="2026-06-01T00:00:00Z")
    return prov["id"], payer["id"]


def test_enrollment_half_open_boundary_touch_accepted(api):
    """PRD §3.2: "the platform rejects it with `ERR_ENROLLMENT_PERIOD_OVERLAP` (HTTP 409)
    if any existing non-`TERMINATED` enrollment for the same provider-and-payer pair has
    a participation period that overlaps the new one, where overlap is evaluated on
    half-open `[effective_date, termination_date)` intervals."
    PRD §3.2: "A new enrollment starts in `PENDING`."

    Design: Difficulty/resource_temporal_overlap/enrollment_half_open_boundary_touch_accepted
    """
    prov_id, payer_id = _provider_payer_with_terminating_e1(api)
    resp = api.create_enrollment(
        create_enrollment_payload(prov_id, payer_id, effective_date="2026-06-01T00:00:00Z"), CRED)
    data = validate_success(resp, 201)
    assert data["status"] == "PENDING", data["status"]


def test_enrollment_half_open_boundary_echoes_effective_date(api):
    """PRD §2.4: "All timestamps the platform records — `created_at`, `updated_at`,
    `submission_date`, `submitted_date`, `first_sent_date`,
    `credentialing_expiration_date`, `effective_date`, `end_date`, `termination_date`,
    `service_date`, and `denial_date` — are expressed in the same ISO 8601 UTC format"

    Design: Difficulty/resource_temporal_overlap/enrollment_half_open_boundary_touch_accepted
    """
    prov_id, payer_id = _provider_payer_with_terminating_e1(api)
    data = validate_success(api.create_enrollment(
        create_enrollment_payload(prov_id, payer_id, effective_date="2026-06-01T00:00:00Z"), CRED), 201)
    assert data["effective_date"] == "2026-06-01T00:00:00.000Z", data["effective_date"]


# ---- Corner: cross_cutting / OCC stale practice version on fee-schedule activation ----
def test_fee_schedule_activate_stale_practice_returns_stale_version(api):
    """PRD §2.6: "activating a fee schedule requires the request to carry
    `expected_practice_version`, which must equal the owning practice's current
    `version`. Activation reshapes the practice's active-schedule set and advances
    `Practice.version`; a stale `expected_practice_version` means another activation has
    already altered that set since the client last read the practice, and the activation
    is rejected."

    Design: Corner/cross_cutting/occ_fee_schedule_activate_stale_practice_returns_stale_version
    """
    fx.set_clock(api, "2026-06-01T00:00:00Z")
    prac = fx.new_practice(api)
    stale_version = prac["version"]  # captured before FS1 activation advances it
    fx.new_active_fee_schedule(api, prac["id"], stale_version, prices={"99213": 10000},
                               effective_date="2026-01-01T00:00:00Z", end_date="2026-06-30T00:00:00Z")
    fs2 = fx.new_fee_schedule_with_lines(api, prac["id"], prices={"99213": 11000},
                                         effective_date="2026-07-01T00:00:00Z",
                                         end_date="2026-12-31T00:00:00Z")
    resp = api.activate_fee_schedule(fs2["id"], {"expected_practice_version": stale_version}, AM)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)
    got = validate_success(api.get_fee_schedule(fs2["id"], AM), 200)
    assert got["status"] == "DRAFT", got["status"]


# ---- Corner: validations / enrollment interior period overlap ----
def test_enrollment_interior_period_overlap_rejected(api):
    """PRD §3.2: "the platform rejects it with `ERR_ENROLLMENT_PERIOD_OVERLAP` (HTTP 409)
    if any existing non-`TERMINATED` enrollment for the same provider-and-payer pair has
    a participation period that overlaps the new one, where overlap is evaluated on
    half-open `[effective_date, termination_date)` intervals."

    Design: Corner/validations/enrollment_period_overlap_interior_rejected
    """
    prac = fx.new_practice(api)
    payer = fx.new_payer(api)
    prov = fx.new_provider(api, prac["id"])
    fx.new_enrollment(api, prov["id"], payer["id"], effective_date="2026-01-01T00:00:00Z")
    resp = api.create_enrollment(
        create_enrollment_payload(prov["id"], payer["id"], effective_date="2026-03-01T00:00:00Z"),
        CRED)
    validate_error(resp, ApiErrorId.ERR_ENROLLMENT_PERIOD_OVERLAP.value)
