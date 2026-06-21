"""Corner-coverage tests for optimistic-concurrency control on lottery-run
and offer-accept (PRD §2.4), the clock-driven expire-offers batch sweep
(PRD §3.5), and the immediate-consistency guarantee on lottery-run side
effects (PRD §2.7).
"""
from test_helpers import (
    set_clock,
    create_district,
    create_school,
    create_window,
    open_window,
    register_family,
    create_student,
    create_application,
    submit_application,
    advance_window_to_lottery_run,
    list_offers_for_application,
    get_offer,
    get_window,
    decline_offer,
    expire_offers,
    get_application,
    api_client,
    TEST_USERS,
    make_guardian_headers,
    validate_error,
    validate_error_is_one_of,
    validate_success,
    ApiErrorId,
)
from test_helpers.factories import (
    run_lottery_payload,
    accept_offer_payload,
)


# =====================================================================
# Corner / cross_cutting — second run-lottery with stale version
# =====================================================================

def test_second_run_lottery_with_stale_window_version_returns_stale_version(api):
    """PRD §2.4: "Two write operations are guarded by optimistic concurrency.
    Running the lottery — that is, transitioning an `EnrollmentWindow` from
    `CLOSED` to `LOTTERY_RUN` — requires the request body to carry
    `expected_window_version` as a non-optional field whose value must
    equal the target window's current `version`. If the value does not
    match (typically because another administrator has already advanced the
    window through close-or-run since the client last read it), the request
    is rejected with `ERR_STALE_VERSION` and HTTP 412, and no lottery is
    run."

    Two strictly sequential run-lottery calls: the first reads version V
    and runs the lottery (window advances to V+1, status becomes
    LOTTERY_RUN). The second still carries expected_window_version=V and
    must be rejected with ERR_STALE_VERSION.

    Design: Corner/cross_cutting_complexity_layers/occ_window_run_lottery_stale_version_rejected
    """
    set_clock("2026-01-01T00:00:00Z")
    district = create_district(code="DOC", name="Oc", poverty_index_pct=0.00)
    school = create_school(district["id"], code="SOC", name="Ocs",
                           school_type="MAGNET", grade_min=0, grade_max=12,
                           total_seats=5)
    window = create_window(district["id"], cycle_label="2026-27-OC")
    family = register_family(district["id"], guardian_email="oc@x.com",
                             residence_zone_code="ZOC", poverty_flag=False)
    student = create_student(family["id"], grade_for_cycle=5)
    set_clock("2026-01-03T00:00:00Z")
    open_window(window["id"])
    app = create_application(family["id"], window["id"], student["id"],
                             school["id"], choice_rank=1)
    submit_application(family["id"], app["id"])
    # Drive window to CLOSED and the clock past lottery_runs_at WITHOUT
    # using the composite helper, so we can capture the pre-run version.
    set_clock("2026-02-01T00:00:00Z")
    res_close = api.close_window(window["id"], TEST_USERS["district_admin_headers"])
    validate_success(res_close, 200)
    set_clock("2026-02-02T00:00:00Z")
    w_pre = get_window(window["id"])
    v_pre = w_pre["version"]
    # First run-lottery — succeeds.
    res1 = api.run_lottery(
        window["id"], run_lottery_payload(v_pre),
        TEST_USERS["district_admin_headers"],
    )
    validate_success(res1, 200)
    # Second run-lottery with the SAME (now stale) version.
    # PRD §2.4 says OCC mismatch is rejected with ERR_STALE_VERSION, but
    # PRD §2.6 fixes validation precedence so that state checks run before
    # version checks. After the first run, the window is in LOTTERY_RUN, so
    # the state check (window must be CLOSED) fires first and yields
    # ERR_INVALID_STATE — a faithful PRD reader may correctly emit either.
    res2 = api.run_lottery(
        window["id"], run_lottery_payload(v_pre),
        TEST_USERS["district_admin_headers"],
    )
    validate_error_is_one_of(
        res2,
        [ApiErrorId.ERR_STALE_VERSION.value, ApiErrorId.ERR_INVALID_STATE.value],
    )


# =====================================================================
# Corner / cross_cutting — offer accept after decline cascade with stale
# offer version
# =====================================================================

def test_accept_offer_with_stale_version_after_decline_cascade(api):
    """PRD §2.4: "Accepting an offer similarly requires the request body to
    carry `expected_offer_version` as a non-optional field equal to the
    target offer's current `version`; a mismatch — which most often arises
    when the offer has just been expired by a clock-driven sweep that
    bumped its version — is rejected with `ERR_STALE_VERSION` and HTTP 412
    before the acceptance takes effect."
    PRD §3.5: "Declination moves an `OFFERED` offer to `DECLINED`, advances
    the linked application from `ACCEPTED` to `DECLINED`, and triggers the
    waitlist-promotion cascade."

    Guardian captures Offer.version V before declining; after decline the
    Offer is DECLINED and its version has advanced. A subsequent accept
    request carrying the stale V must be rejected with either
    ERR_STALE_VERSION (OCC fires first) or ERR_INVALID_STATE (the state
    check fires first) — PRD does not commit to which check runs first.

    Design: Corner/cross_cutting_complexity_layers/offer_accept_stale_version_after_decline_cascade
    """
    set_clock("2026-01-01T00:00:00Z")
    district = create_district(code="DOA", name="Oa", poverty_index_pct=0.00)
    school = create_school(district["id"], code="SOA", name="Oas",
                           school_type="MAGNET", grade_min=0, grade_max=12,
                           total_seats=5)
    window = create_window(district["id"], cycle_label="2026-27-OA")
    family = register_family(district["id"], guardian_email="oa@x.com",
                             residence_zone_code="ZOA", poverty_flag=False)
    student = create_student(family["id"], grade_for_cycle=5)
    set_clock("2026-01-03T00:00:00Z")
    open_window(window["id"])
    app = create_application(family["id"], window["id"], student["id"],
                             school["id"], choice_rank=1)
    submit_application(family["id"], app["id"])
    advance_window_to_lottery_run(window["id"])
    offers = list_offers_for_application(app["id"], family_id=family["id"])
    off = offers[0]
    v_pre = off["version"]
    decline_offer(family["id"], off["id"])
    # Accept with the pre-decline (now stale) version.
    res = api.accept_offer(
        off["id"],
        accept_offer_payload(v_pre),
        make_guardian_headers(family["id"]),
    )
    actual = validate_error_is_one_of(
        res,
        [ApiErrorId.ERR_STALE_VERSION.value, ApiErrorId.ERR_INVALID_STATE.value],
    )
    assert actual in (
        ApiErrorId.ERR_STALE_VERSION.value, ApiErrorId.ERR_INVALID_STATE.value
    ), f"unexpected error_id: {actual!r}"


# =====================================================================
# Corner / cross_cutting — clock-driven expire-offers sweep cascades
# =====================================================================

def test_expire_offers_sweep_expires_past_due_and_promotes_waitlist(api):
    """PRD §3.5: "A `DistrictAdmin` may trigger a batch sweep against a
    window to expire any `OFFERED` offer whose `respond_by` has been passed
    by the clock. The sweep returns a small object reporting `expired_count`
    (how many offers transitioned to `EXPIRED`) and `promoted_count` (how
    many waitlist entries were promoted as a consequence). Each expired
    offer cascades exactly like a declination: the linked application
    moves to `DECLINED`, the top `ACTIVE` waitlist entry on that school is
    promoted, a new offer is minted with `source` set to
    `WAITLIST_PROMOTION`, and queue ranks below the promoted entry shift
    down by one."

    Design: Corner/cross_cutting_complexity_layers/scheduled_clock_expire_offers_batch
    """
    set_clock("2026-01-01T00:00:00Z")
    district = create_district(code="DSC", name="Sc", poverty_index_pct=0.00)
    school = create_school(district["id"], code="SSC", name="Scs",
                           school_type="MAGNET", grade_min=0, grade_max=12,
                           total_seats=1)
    window = create_window(district["id"], cycle_label="2026-27-SC")
    fam_a = register_family(district["id"], guardian_email="sc1@x.com",
                            residence_zone_code="ZSC", poverty_flag=True)
    fam_b = register_family(district["id"], guardian_email="sc2@x.com",
                            residence_zone_code="ZSC", poverty_flag=False)
    stu_a = create_student(fam_a["id"], grade_for_cycle=4)
    stu_b = create_student(fam_b["id"], grade_for_cycle=4)
    set_clock("2026-01-03T00:00:00Z")
    open_window(window["id"])
    app_a = create_application(fam_a["id"], window["id"], stu_a["id"],
                               school["id"], choice_rank=1)
    submit_application(fam_a["id"], app_a["id"])
    app_b = create_application(fam_b["id"], window["id"], stu_b["id"],
                               school["id"], choice_rank=1)
    submit_application(fam_b["id"], app_b["id"])
    advance_window_to_lottery_run(window["id"])
    # Lottery has run; A's offer is at offered_at = 2026-02-02. Advance
    # well past respond_by (=2026-02-09) so the sweep finds it expired.
    set_clock("2026-02-10T00:00:00Z")
    expire_offers(window["id"])
    after_a = get_application(app_a["id"])
    after_b = get_application(app_b["id"])
    assert after_a["status"] == "DECLINED", (
        f"Expired offer must cascade application A to DECLINED; "
        f"got {after_a['status']!r}"
    )
    assert after_b["status"] == "ACCEPTED", (
        f"Top waitlist entry must be promoted to ACCEPTED; "
        f"got {after_b['status']!r}"
    )


# =====================================================================
# Corner / consistency_model — immediate consistency after run-lottery
# =====================================================================

def test_immediate_consistency_lottery_run_application_status_visible(api):
    """PRD §2.7: "the lottery-weight calculation runs over every `SUBMITTED`
    application in the window, the seat-assignment calculation partitions
    per-school applications into accepted and waitlisted sets, each accepted
    application transitions from `SUBMITTED` to `ACCEPTED` with a freshly
    created `Offer` whose `source` is `LOTTERY`."

    Immediately after the run-lottery call returns 200, a follow-up GET on
    the application must reflect the new ACCEPTED status, and a follow-up
    GET on the offers list must include the freshly created OFFERED Offer.

    Design: Corner/consistency_model/immediate_consistency_lottery_run_returns_full_state
    """
    set_clock("2026-01-01T00:00:00Z")
    district = create_district(code="DIM", name="Im", poverty_index_pct=0.00)
    school = create_school(district["id"], code="SIM", name="Ims",
                           school_type="MAGNET", grade_min=0, grade_max=12,
                           total_seats=5)
    window = create_window(district["id"], cycle_label="2026-27-IM")
    family = register_family(district["id"], guardian_email="im@x.com",
                             residence_zone_code="ZIM", poverty_flag=False)
    student = create_student(family["id"], grade_for_cycle=4)
    set_clock("2026-01-03T00:00:00Z")
    open_window(window["id"])
    app = create_application(family["id"], window["id"], student["id"],
                             school["id"], choice_rank=1)
    submit_application(family["id"], app["id"])
    advance_window_to_lottery_run(window["id"])
    # Immediate follow-up GET — no sleep, no retry.
    after = get_application(app["id"])
    assert after["status"] == "ACCEPTED", (
        f"Immediately after run-lottery returns, Application.status must "
        f"be ACCEPTED; got {after['status']!r}"
    )
    offers = list_offers_for_application(app["id"], family_id=family["id"])
    assert len(offers) == 1, (
        f"Immediately after run-lottery returns, Offer must be queryable; "
        f"got {offers!r}"
    )
    assert offers[0]["source"] == "LOTTERY"
    assert offers[0]["status"] == "OFFERED"
