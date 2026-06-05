"""Enrollment validations: window membership, period/coverage overlap, priority
ordering of competing failures, the Medigap guaranteed-issue window, and OCC.
"""
from test_helpers import (
    validate_success, validate_error, set_clock, create_beneficiary, create_plan,
    create_period, setup_beneficiary_with_active_part_b, file_part_c, confirm_part_c,
    read_beneficiary_version,
    create_part_b_enrollment_payload, create_part_c_enrollment_payload, confirm_part_c_payload,
    create_part_d_enrollment_payload, create_medigap_policy_payload,
    create_enrollment_period_payload, ApiErrorId, TEST_USERS,
)

ADMIN = TEST_USERS["enrollment_admin_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]


# ─── Priority-pair conflicts (PRD §3.11 fixed order) ──────────────────────────

def test_enrollment_locked_beats_outside_window(api):
    """PRD §3.11: "then that the beneficiary's enrollment_lock is false
    (ERR_ENROLLMENT_LOCKED, HTTP 409); then that the clock falls within the period
    window (ERR_OUTSIDE_ENROLLMENT_WINDOW, HTTP 422)"
    PRD §3.1: "While enrollment_lock is true, no new Part B, Part C, Part D, or Medigap
    enrollment may be created for that beneficiary - such attempts are rejected with
    ERR_ENROLLMENT_LOCKED (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/enrollment_locked_safety_beats_outside_window_temporal
    """
    set_clock("2024-06-01T00:00:00.000Z")
    ben = create_beneficiary(full_name="Donald K")
    validate_success(api.establish_part_a(ben["id"], ADMIN), 200)
    aep = create_period(ben["id"], "AEP", aep_year=2024)
    ma = create_plan(name="MA X", part_type="PART_C", monthly_premium_cents=0,
                     star_rating=3.5, includes_drug_coverage=False)
    validate_success(api.fraud_hold(ben["id"], COMPLIANCE), 200)
    # Clock outside the AEP window (Oct 15 - Dec 7, 2024) AND beneficiary is locked.
    set_clock("2025-03-01T00:00:00.000Z")
    res = api.create_part_c_enrollment(
        create_part_c_enrollment_payload(ben["id"], ma["id"], aep["id"]), ADMIN)
    validate_error(res, ApiErrorId.ERR_ENROLLMENT_LOCKED.value)


def test_wrong_period_type_beats_not_five_star(api):
    """PRD §3.11: "then that the period is of the type required for the enrollment kind
    (ERR_WRONG_PERIOD_TYPE, HTTP 422); ... then the five-star plan check for SEP_5STAR
    enrollments (ERR_NOT_FIVE_STAR, HTTP 422)"
    PRD §3.6: "The justifying period may be an IEP, AEP, or SEP_5STAR period; a Part C
    filing under any other period type is rejected with ERR_WRONG_PERIOD_TYPE
    (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/wrong_period_type_referential_beats_not_five_star_constraint
    """
    set_clock("2024-06-01T00:00:00.000Z")
    ben, _iep, _pbe = setup_beneficiary_with_active_part_b()
    gi = create_period(ben["id"], "GI_MEDIGAP", source_event_date="2024-05-01T00:00:00.000Z")
    ma = create_plan(name="MA Mid", part_type="PART_C", monthly_premium_cents=0,
                     star_rating=3.5, includes_drug_coverage=False)
    res = api.create_part_c_enrollment(
        create_part_c_enrollment_payload(ben["id"], ma["id"], gi["id"]), ADMIN)
    validate_error(res, ApiErrorId.ERR_WRONG_PERIOD_TYPE.value)


# ─── Temporal overlap: closed (period) vs half-open (medigap) ─────────────────

def test_second_iep_collides_closed_interval_adjacency(api):
    """PRD §3.4: "A newly created IEP or AEP period for a beneficiary may not overlap an
    existing period of the same type for that same beneficiary. Overlap here uses
    closed-interval semantics on [window_start, window_end]: two periods that merely
    touch at a single instant - where one period's window_end equals the other's
    window_start - do collide, and the create is rejected with ERR_PERIOD_OVERLAP
    (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/enrollment_period_closed_interval_adjacency_collides
    """
    set_clock("2024-06-01T00:00:00.000Z")
    ben = create_beneficiary(full_name="Margaret H")
    create_period(ben["id"], "IEP")
    # A second IEP derives the identical window from the same DOB -> overlap.
    res = api.create_enrollment_period(
        ben["id"], create_enrollment_period_payload("IEP"), ADMIN)
    validate_error(res, ApiErrorId.ERR_PERIOD_OVERLAP.value)


def test_medigap_half_open_adjacency_allowed(api):
    """PRD §3.9: "Under half-open semantics, two policies that merely touch at a single
    instant - where one policy's coverage_end equals the next policy's coverage_start -
    do not overlap and are allowed; a genuine overlap is rejected with
    ERR_MEDIGAP_OVERLAP (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/medigap_half_open_interval_adjacency_allowed
    """
    set_clock("2026-01-15T00:00:00.000Z")
    ben = create_beneficiary(full_name="Radia P")
    gi1 = create_period(ben["id"], "GI_MEDIGAP", source_event_date="2026-01-10T00:00:00.000Z")
    validate_success(api.create_medigap_policy(
        create_medigap_policy_payload(ben["id"], gi1["id"],
                                      "2026-01-15T00:00:00.000Z", "2026-07-15T00:00:00.000Z"),
        ADMIN), 201)
    gi2 = create_period(ben["id"], "GI_MEDIGAP", source_event_date="2026-07-10T00:00:00.000Z")
    set_clock("2026-07-12T00:00:00.000Z")
    # New policy starts exactly where the first ends -> half-open adjacency, allowed.
    res = api.create_medigap_policy(
        create_medigap_policy_payload(ben["id"], gi2["id"],
                                      "2026-07-15T00:00:00.000Z", "2027-07-15T00:00:00.000Z"),
        ADMIN)
    mp2 = validate_success(res, 201)
    assert mp2["status"] == "ISSUED"


# ─── Medigap guaranteed-issue 63-day boundary ─────────────────────────────────

def test_medigap_application_day64_expired(api):
    """PRD §3.9: "The application is accepted only when the system clock at the moment
    of application falls within the 63-day window that runs from the period's
    source_event_date: the clock must be at or after source_event_date and at or before
    source_event_date plus 63 days (day 63 inclusive). An application landing outside
    that window is rejected with ERR_GI_WINDOW_EXPIRED (HTTP 422)"

    Design: Difficulty/boundary_precision_check/medigap_gi_window_day63_inclusive_vs_day64_expired
    """
    set_clock("2026-01-01T00:00:00.000Z")
    ben = create_beneficiary(full_name="Dennis R")
    gi = create_period(ben["id"], "GI_MEDIGAP", source_event_date="2026-01-01T00:00:00.000Z")
    # source_event_date + 64 days = 2026-03-06 -> outside the 63-day window.
    set_clock("2026-03-06T00:00:00.000Z")
    res = api.create_medigap_policy(
        create_medigap_policy_payload(ben["id"], gi["id"],
                                      "2026-03-06T00:00:00.000Z", "2027-03-06T00:00:00.000Z"),
        ADMIN)
    validate_error(res, ApiErrorId.ERR_GI_WINDOW_EXPIRED.value)


# ─── Single-failure validation cases (corner) ─────────────────────────────────

def test_period_beneficiary_mismatch_on_part_b_create(api):
    """PRD §3.11: "first that the enrollment_period_id belongs to the same
    beneficiary_id named on the enrollment, failing with
    ERR_PERIOD_BENEFICIARY_MISMATCH (HTTP 422)"

    Design: Corner/validations/period_beneficiary_mismatch_on_partb_create
    """
    set_clock("2024-06-01T00:00:00.000Z")
    ben_a = create_beneficiary(full_name="BenA")
    ben_b = create_beneficiary(full_name="BenB")
    iep_b = create_period(ben_b["id"], "IEP")
    res = api.create_part_b_enrollment(
        create_part_b_enrollment_payload(ben_a["id"], iep_b["id"]), ADMIN)
    validate_error(res, ApiErrorId.ERR_PERIOD_BENEFICIARY_MISMATCH.value)


def test_part_b_outside_iep_window(api):
    """PRD §3.11: "A creation attempted while the clock lies outside that interval is
    rejected with ERR_OUTSIDE_ENROLLMENT_WINDOW (HTTP 422)."

    Design: Corner/validations/partb_outside_iep_window_returns_outside_enrollment_window
    """
    set_clock("2024-06-01T00:00:00.000Z")
    ben = create_beneficiary(full_name="EarlyB")
    iep = create_period(ben["id"], "IEP")
    # IEP for an Aug-1959 birth: window_start = May 1; set clock to Jan 2024 (before).
    set_clock("2024-01-01T00:00:00.000Z")
    res = api.create_part_b_enrollment(
        create_part_b_enrollment_payload(ben["id"], iep["id"]), ADMIN)
    validate_error(res, ApiErrorId.ERR_OUTSIDE_ENROLLMENT_WINDOW.value)


def test_standalone_part_d_on_active_mapd_conflict(api):
    """PRD §3.7: "A standalone Part D enrollment is forbidden when the beneficiary
    already holds an ACTIVE PartCEnrollment whose plan bundles drug coverage
    (includes_drug_coverage true): a member cannot stack a standalone drug plan on top
    of an MAPD, and the attempt is rejected with ERR_DRUG_COVERAGE_CONFLICT (HTTP 409)."

    Design: Corner/validations/standalone_partd_on_active_mapd_returns_drug_coverage_conflict
    """
    from test_helpers import setup_confirmed_part_c
    set_clock("2024-06-01T00:00:00.000Z")
    ben, iep, _mapd, _pce = setup_confirmed_part_c(
        plan_overrides={"name": "MAPD C", "monthly_premium_cents": 0, "star_rating": 4.0,
                        "includes_drug_coverage": True})
    pdp = create_plan(name="PDP Std", part_type="PART_D", monthly_premium_cents=2000,
                      star_rating=3.0, includes_drug_coverage=True)
    res = api.create_part_d_enrollment(
        create_part_d_enrollment_payload(ben["id"], pdp["id"], iep["id"]), ADMIN)
    validate_error(res, ApiErrorId.ERR_DRUG_COVERAGE_CONFLICT.value)


def test_sep_5star_with_four_star_plan_rejected(api):
    """PRD §3.11: "a SEP_5STAR period may justify a Part C enrollment only if the chosen
    plan's star_rating is exactly 5.0 ... A non-five-star plan used under a five-star
    period is rejected with ERR_NOT_FIVE_STAR (HTTP 422)."

    Design: Corner/validations/sep_5star_with_four_star_plan_returns_not_five_star
    """
    set_clock("2024-06-01T00:00:00.000Z")
    ben, _iep, _pbe = setup_beneficiary_with_active_part_b()
    sep = create_period(ben["id"], "SEP_5STAR", aep_year=2024)
    ma = create_plan(name="MA Four", part_type="PART_C", monthly_premium_cents=0,
                     star_rating=4.0, includes_drug_coverage=False)
    # SEP_5STAR window: Dec 8 2024 - Nov 30 2025; clock inside.
    set_clock("2025-03-01T00:00:00.000Z")
    res = api.create_part_c_enrollment(
        create_part_c_enrollment_payload(ben["id"], ma["id"], sep["id"]), ADMIN)
    validate_error(res, ApiErrorId.ERR_NOT_FIVE_STAR.value)


def test_gi_medigap_period_missing_source_event_date(api):
    """PRD §3.4: "Creating a GI_MEDIGAP period without a source_event_date is rejected
    with ERR_MISSING_SOURCE_EVENT_DATE (HTTP 422)"

    Design: Corner/validations/gi_medigap_period_missing_source_event_date
    """
    set_clock("2026-01-01T00:00:00.000Z")
    ben = create_beneficiary(full_name="GiB")
    res = api.create_enrollment_period(
        ben["id"], create_enrollment_period_payload("GI_MEDIGAP"), ADMIN)
    validate_error(res, ApiErrorId.ERR_MISSING_SOURCE_EVENT_DATE.value)


# ─── Optimistic concurrency on Part C confirm ─────────────────────────────────

def test_occ_correct_version_confirm_succeeds(api):
    """PRD §2.6: "The confirm request must carry expected_beneficiary_version, a
    required field whose value is the beneficiary's version as the client last observed
    it. The server compares that value against the beneficiary's current version."
    PRD §3.6: "Confirmation itself increments both the PartCEnrollment.version of the
    newly confirmed enrollment and the Beneficiary.version"

    Design: Corner/cross_cutting_complexity_layers/occ_correct_beneficiary_version_confirm_succeeds
    """
    set_clock("2024-06-01T00:00:00.000Z")
    ben, iep, _pbe = setup_beneficiary_with_active_part_b()
    ma = create_plan(name="MA Occ", part_type="PART_C", monthly_premium_cents=0,
                     star_rating=4.0, includes_drug_coverage=False)
    pce = file_part_c(ben["id"], ma["id"], iep["id"])
    ver = read_beneficiary_version(ben["id"])
    res = api.confirm_part_c_enrollment(pce["id"], confirm_part_c_payload(ver), ADMIN)
    confirmed = validate_success(res, 200)
    assert confirmed["status"] == "ACTIVE"
    ben_after = validate_success(api.get_beneficiary(ben["id"], ADMIN), 200)
    assert ben_after["version"] == ver + 1


def test_occ_stale_version_confirm_rejected(api):
    """PRD §2.6: "If another writer has advanced the beneficiary's version since the
    client last read it ... the client's view of which enrollment is active is stale,
    and the confirm is rejected with ERR_STALE_VERSION (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_beneficiary_version_confirm_returns_stale_version
    """
    set_clock("2024-06-01T00:00:00.000Z")
    ben, iep, _pbe = setup_beneficiary_with_active_part_b()
    ma = create_plan(name="MA Stale", part_type="PART_C", monthly_premium_cents=0,
                     star_rating=4.0, includes_drug_coverage=False)
    pce = file_part_c(ben["id"], ma["id"], iep["id"])
    stale = read_beneficiary_version(ben["id"])
    # Bump beneficiary version via a fraud-hold / clear-hold cycle.
    validate_success(api.fraud_hold(ben["id"], COMPLIANCE), 200)
    validate_success(api.clear_hold(ben["id"], COMPLIANCE), 200)
    res = api.confirm_part_c_enrollment(pce["id"], confirm_part_c_payload(stale), ADMIN)
    validate_error(res, ApiErrorId.ERR_STALE_VERSION.value)
