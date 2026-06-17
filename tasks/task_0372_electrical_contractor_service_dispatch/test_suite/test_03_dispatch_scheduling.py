"""Dispatch creation, scheduling gates, and technician time-window overlap.

Queue A (Difficulty): resource_temporal_overlap, boundary_precision (dispatch window).
Queue B (Corner): zone/on-call gating, OCC stale version on dispatch, reschedule, queue.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, TEST_USERS,
    make_customer, make_technician, make_membership_plan, enroll_membership,
    make_job, current_job_version, quote_and_accept, dispatch_tech,
)

DISP = TEST_USERS["dispatcher_headers"]


def _make_quoted_outlet_job(zone_prefix, email, flat=10000):
    cust = make_customer(email=email, service_zip=zone_prefix + "01")
    job = make_job(cust["id"], scope="OUTLET", job_class="SERVICE", priority="STANDARD")
    quote_and_accept(job["id"], cust["id"], pricing_mode="FLAT_RATE", flat_rate_cents=flat)
    return cust, job


# ─── Queue A: resource_temporal_overlap ───────────────────────────────────
def test_overlap_technician_halfopen_on_create(api):
    """PRD §3.4: "The new arrival window must not overlap any existing active dispatch on
    the same technician; an overlap is rejected with `ERR_TECH_DOUBLE_BOOKED`."
    PRD §3.4: "Two windows on the same technician conflict precisely when the new window's
    start is earlier than the existing window's end and the existing window's start is
    earlier than the new window's end."

    Design: Difficulty/resource_temporal_overlap/overlap_technician_halfopen_on_create
    """
    tech = make_technician(service_zone="720", license_class="JOURNEYMAN", hourly_rate_cents=10000)
    _, jobA = _make_quoted_outlet_job("720", "ro1a@x.com")
    dispatch_tech(jobA["id"], tech["id"], "2026-07-16T09:00:00Z", "2026-07-16T11:00:00Z")
    _, jobB = _make_quoted_outlet_job("720", "ro1b@x.com")
    vB = current_job_version(jobB["id"])
    resp = api.create_dispatch(
        {"job_id": jobB["id"], "technician_id": tech["id"],
         "window_start": "2026-07-16T10:00:00Z", "window_end": "2026-07-16T12:00:00Z",
         "expected_job_version": vB},
        DISP,
    )
    validate_error(resp, ApiErrorId.ERR_TECH_DOUBLE_BOOKED.value)  # [10,12) overlaps [09,11)


def test_overlap_ignores_cancelled_dispatch(api):
    """PRD §3.4: "Only existing dispatches whose `status` is `ASSIGNED`, `EN_ROUTE`, or
    `ON_SITE` are considered when checking for conflicts; dispatches in `CANCELLED` or
    `CLEARED` are ignored."

    Design: Difficulty/resource_temporal_overlap/overlap_technician_halfopen_on_create
    """
    tech = make_technician(service_zone="721", license_class="JOURNEYMAN", hourly_rate_cents=10000)
    _, jobA = _make_quoted_outlet_job("721", "ro1c@x.com")
    dispA = dispatch_tech(jobA["id"], tech["id"], "2026-07-21T09:00:00Z", "2026-07-21T11:00:00Z")
    api.cancel_dispatch(dispA["id"], DISP)  # frees the window
    _, jobB = _make_quoted_outlet_job("721", "ro1d@x.com")
    # an overlapping window now succeeds because the only conflicting dispatch is CANCELLED.
    dispB = dispatch_tech(jobB["id"], tech["id"], "2026-07-21T10:00:00Z", "2026-07-21T12:00:00Z")
    assert dispB["status"] == "ASSIGNED"


def test_overlap_technician_recheck_on_reschedule(api):
    """PRD §3.4: "A dispatcher may reschedule an assigned or en-route dispatch by supplying
    a new `window_start` and `window_end`; the window is updated, the `eta` is reset to the
    new `window_start`, and the overlap check is re-run against the technician's other active
    dispatches."

    Design: Difficulty/resource_temporal_overlap/overlap_technician_recheck_on_reschedule
    """
    tech = make_technician(service_zone="730", license_class="JOURNEYMAN", hourly_rate_cents=10000)
    _, jobA = _make_quoted_outlet_job("730", "ro2a@x.com")
    dispatch_tech(jobA["id"], tech["id"], "2026-07-17T09:00:00Z", "2026-07-17T10:00:00Z")
    _, jobB = _make_quoted_outlet_job("730", "ro2b@x.com")
    dispB = dispatch_tech(jobB["id"], tech["id"], "2026-07-17T11:00:00Z", "2026-07-17T12:00:00Z")

    resp = api.reschedule_dispatch(
        dispB["id"], {"window_start": "2026-07-17T09:30:00Z", "window_end": "2026-07-17T10:30:00Z"}, DISP
    )
    validate_error(resp, ApiErrorId.ERR_TECH_DOUBLE_BOOKED.value)
    # reschedule rejected -> window unchanged
    current = validate_success(api.get_dispatch(dispB["id"], DISP), 200)
    assert current["window_start"].startswith("2026-07-17T11:00:00")


def test_reschedule_to_clear_window_succeeds(api):
    """PRD §3.4: "A dispatcher may reschedule an assigned or en-route dispatch by supplying
    a new `window_start` and `window_end`; the window is updated, the `eta` is reset to the
    new `window_start`, and the overlap check is re-run against the technician's other active
    dispatches."

    Design: Difficulty/resource_temporal_overlap/overlap_technician_recheck_on_reschedule
    """
    tech = make_technician(service_zone="731", license_class="JOURNEYMAN", hourly_rate_cents=10000)
    _, jobA = _make_quoted_outlet_job("731", "ro2c@x.com")
    dispatch_tech(jobA["id"], tech["id"], "2026-07-22T09:00:00Z", "2026-07-22T10:00:00Z")  # A [09,10)
    _, jobB = _make_quoted_outlet_job("731", "ro2d@x.com")
    dispB = dispatch_tech(jobB["id"], tech["id"], "2026-07-22T11:00:00Z", "2026-07-22T12:00:00Z")  # B [11,12)
    # reschedule B to a window that does NOT collide with A -> overlap check passes.
    resp = api.reschedule_dispatch(
        dispB["id"], {"window_start": "2026-07-22T14:00:00Z", "window_end": "2026-07-22T15:00:00Z"}, DISP)
    data = validate_success(resp, 200)
    assert data["window_start"].startswith("2026-07-22T14:00:00")


# ─── Queue A: boundary_precision (dispatch window adjacency vs overlap) ────
def test_boundary_dispatch_adjacent_ok_overlap_rejected(api):
    """PRD §3.4: "Two windows that merely touch — where the new window's start equals an
    existing window's end — do not conflict."
    PRD §3.4: "Two windows on the same technician conflict precisely when the new window's
    start is earlier than the existing window's end and the existing window's start is
    earlier than the new window's end."

    Design: Difficulty/boundary_precision_check/boundary_dispatch_adjacent_ok_overlap_rejected
    """
    tech = make_technician(service_zone="710", license_class="JOURNEYMAN", hourly_rate_cents=10000)
    _, jobA = _make_quoted_outlet_job("710", "bp2a@x.com")
    dispatch_tech(jobA["id"], tech["id"], "2026-07-13T09:00:00Z", "2026-07-13T10:00:00Z")  # A [09,10)

    # B starts exactly at A's end -> adjacency, no conflict.
    _, jobB = _make_quoted_outlet_job("710", "bp2b@x.com")
    dispB = dispatch_tech(jobB["id"], tech["id"], "2026-07-13T10:00:00Z", "2026-07-13T11:00:00Z")
    assert dispB["status"] == "ASSIGNED"

    # C starts one second before A's end -> overlaps A.
    _, jobC = _make_quoted_outlet_job("710", "bp2c@x.com")
    vC = current_job_version(jobC["id"])
    resp = api.create_dispatch(
        {"job_id": jobC["id"], "technician_id": tech["id"],
         "window_start": "2026-07-13T09:59:59Z", "window_end": "2026-07-13T10:30:00Z",
         "expected_job_version": vC},
        DISP,
    )
    validate_error(resp, ApiErrorId.ERR_TECH_DOUBLE_BOOKED.value)


def test_boundary_dispatch_exact_touch_does_not_conflict(api):
    """PRD §3.4: "Two windows that merely touch — where the new window's start equals an
    existing window's end — do not conflict."
    PRD §3.4: "The double-booking test treats windows as half-open intervals spanning from
    `window_start` up to but not including `window_end`."

    Design: Difficulty/boundary_precision_check/boundary_dispatch_adjacent_ok_overlap_rejected
    """
    tech = make_technician(service_zone="711", license_class="JOURNEYMAN", hourly_rate_cents=10000)
    _, jobA = _make_quoted_outlet_job("711", "bp2d@x.com")
    dispatch_tech(jobA["id"], tech["id"], "2026-07-23T08:00:00Z", "2026-07-23T09:00:00Z")  # A [08,09)
    # B begins exactly when A ends -> half-open intervals do not overlap.
    _, jobB = _make_quoted_outlet_job("711", "bp2e@x.com")
    dispB = dispatch_tech(jobB["id"], tech["id"], "2026-07-23T09:00:00Z", "2026-07-23T10:00:00Z")
    assert dispB["status"] == "ASSIGNED"


# ─── Queue B: dispatch gating corners ─────────────────────────────────────
def test_zone_mismatch_on_dispatch(api):
    """PRD §3.4: "The assigned technician's `service_zone` must match the job's zone, derived
    from the customer's `service_zip` prefix; a mismatch is rejected with `ERR_ZONE_MISMATCH`."

    Design: Corner/validations/zone_mismatch_on_dispatch
    """
    cust = make_customer(email="zm@x.com", service_zip="34001")
    tech = make_technician(service_zone="999", license_class="JOURNEYMAN", hourly_rate_cents=9000)
    job = make_job(cust["id"], scope="OUTLET", job_class="SERVICE")
    quote_and_accept(job["id"], cust["id"], pricing_mode="FLAT_RATE", flat_rate_cents=10000)
    v = current_job_version(job["id"])
    resp = api.create_dispatch(
        {"job_id": job["id"], "technician_id": tech["id"],
         "window_start": "2026-08-11T09:00:00Z", "window_end": "2026-08-11T10:00:00Z",
         "expected_job_version": v},
        DISP,
    )
    validate_error(resp, ApiErrorId.ERR_ZONE_MISMATCH.value)


def test_emergency_requires_on_call_tech(api):
    """PRD §3.4: "When the job's `priority` is `EMERGENCY`, the assigned technician's
    `on_call` flag must be true; assigning a technician who is not on call is rejected with
    `ERR_TECH_NOT_ON_CALL`."

    Design: Corner/validations/emergency_requires_on_call_tech
    """
    cust = make_customer(email="oc@x.com", service_zip="35001")
    tech = make_technician(service_zone="350", license_class="JOURNEYMAN", hourly_rate_cents=9000, on_call=False)
    job = make_job(cust["id"], scope="OUTLET", job_class="SERVICE", priority="EMERGENCY")
    quote_and_accept(job["id"], cust["id"], pricing_mode="FLAT_RATE", flat_rate_cents=10000)
    v = current_job_version(job["id"])
    resp = api.create_dispatch(
        {"job_id": job["id"], "technician_id": tech["id"],
         "window_start": "2026-08-12T09:00:00Z", "window_end": "2026-08-12T10:00:00Z",
         "expected_job_version": v},
        DISP,
    )
    validate_error(resp, ApiErrorId.ERR_TECH_NOT_ON_CALL.value)


def test_stale_version_on_dispatch_create(api):
    """PRD §2.5: "when a client submits a request to create a dispatch, the supplied
    `expected_job_version` must equal the target job's current `version`. If another writer
    has already scheduled a dispatch — which bubbles the job to `SCHEDULED` and increments
    its version — a second create carrying the older version is rejected with
    `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/validations/stale_version_on_dispatch_create
    """
    cust = make_customer(email="sd@x.com", service_zip="33001")
    tech = make_technician(service_zone="330", license_class="JOURNEYMAN", hourly_rate_cents=9000)
    job = make_job(cust["id"], scope="OUTLET", job_class="SERVICE")
    v0 = job["version"]
    # creating + accepting an estimate bumps the job version beyond v0+1 (create bumps, accept bumps)
    est = validate_success(api.create_estimate(
        {"job_id": job["id"], "pricing_mode": "FLAT_RATE", "expected_job_version": v0, "flat_rate_cents": 10000},
        DISP), 201)
    v1 = est["version"]
    api.send_estimate(est["id"], DISP)
    from test_helpers import make_customer_headers
    api.accept_estimate(est["id"], make_customer_headers(cust["id"]))
    # v1 is now stale (accept advanced it).
    resp = api.create_dispatch(
        {"job_id": job["id"], "technician_id": tech["id"],
         "window_start": "2026-08-10T09:00:00Z", "window_end": "2026-08-10T10:00:00Z",
         "expected_job_version": v1},
        DISP,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)


def test_reschedule_updates_eta_and_window(api):
    """PRD §3.4: "the window is updated, the `eta` is reset to the new `window_start`, and
    the overlap check is re-run against the technician's other active dispatches."

    Design: Corner/endpoints/reschedule_updates_eta_and_window
    """
    cust = make_customer(email="re@x.com", service_zip="41001")
    tech = make_technician(service_zone="410", license_class="JOURNEYMAN", hourly_rate_cents=9000)
    job = make_job(cust["id"], scope="OUTLET", job_class="SERVICE")
    quote_and_accept(job["id"], cust["id"], pricing_mode="FLAT_RATE", flat_rate_cents=10000)
    disp = dispatch_tech(job["id"], tech["id"], "2026-08-15T09:00:00Z", "2026-08-15T10:00:00Z")
    resp = api.reschedule_dispatch(
        disp["id"], {"window_start": "2026-08-15T14:00:00Z", "window_end": "2026-08-15T15:00:00Z"}, DISP
    )
    data = validate_success(resp, 200)
    assert data["window_start"].startswith("2026-08-15T14:00:00")
    assert data["eta"].startswith("2026-08-15T14:00:00")


def test_dispatch_queue_ranks_emergency_then_priority_then_created_at(api):
    """PRD §3.10: "Candidates are ranked by three keys applied in strict order: first,
    `EMERGENCY`-priority jobs rank ahead of `STANDARD` jobs; second, among jobs of equal
    priority, jobs belonging to a member whose plan has `priority_dispatch` set true rank
    ahead of jobs that do not; and third, remaining ties are broken by `created_at` ascending
    so that the older job comes first."

    Design: Corner/calculations/dispatch_ranking_emergency_then_priority_then_created_at
    """
    plan = make_membership_plan(name="Prio", tier="PREMIER", monthly_fee_cents=3000,
                                labor_discount_pct=0.10, priority_dispatch=True)
    mem = make_customer(full_name="DR Mem", email="drm@x.com", service_zip="31901", phone="1")
    enroll_membership(mem["id"], plan["id"])
    non = make_customer(full_name="DR Non", email="drn@x.com", service_zip="31902", phone="2")

    mjob = make_job(mem["id"], scope="OUTLET", job_class="SERVICE", priority="STANDARD")
    quote_and_accept(mjob["id"], mem["id"], pricing_mode="FLAT_RATE", flat_rate_cents=10000)
    njob = make_job(non["id"], scope="OUTLET", job_class="SERVICE", priority="EMERGENCY")
    quote_and_accept(njob["id"], non["id"], pricing_mode="FLAT_RATE", flat_rate_cents=10000)

    resp = api.get_dispatch_queue(DISP, params={"zone": "319"})
    data = validate_success(resp, 200)
    ids = [row["id"] for row in data]
    assert len(data) == 2
    assert ids[0] == njob["id"]  # EMERGENCY ranks first despite being created second
    assert ids[1] == mjob["id"]
