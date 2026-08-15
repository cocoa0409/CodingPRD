"""Offer acceptance: window boundaries, rate pinning, consistency, and hangar OCC."""
from test_helpers import (
    ApiErrorId,
    accept_offer_payload,
    add_hangar,
    add_rate_schedule,
    api_client,
    create_airport,
    create_inspection_payload,
    create_offer_payload,
    extend_offer,
    get_application,
    get_hangar,
    get_offer,
    make_applicant_headers,
    parse_instant,
    set_clock,
    setup_lease,
    setup_offer,
    submit_application,
    validate_error,
    validate_paginated,
    validate_success,
)


def _accept_raw(offer_id, hangar_version, application, **overrides):
    """Issue an acceptance call without asserting success (for failure paths)."""
    overrides.setdefault("expected_hangar_version", hangar_version)
    overrides.setdefault("aircraft_n_number", application["aircraft_n_number"])
    return api_client.accept_offer(
        offer_id, accept_offer_payload(**overrides),
        make_applicant_headers(application["id"]),
    )


def test_accept_one_ms_before_deadline_succeeds(api, manager_headers):
    """PRD §3.3: "On the acceptance path, the applicant must act strictly before the `acceptance_deadline`; an acceptance attempted at exactly the deadline, or at any later instant, is rejected with `ERR_OFFER_WINDOW_EXPIRED` (HTTP 409)."
    PRD §3.3: "A created offer lands in `OPEN` status with `offer_sent_at` set to the server timestamp and its `acceptance_deadline` exactly `offer_acceptance_window_hours` hours later."

    Design: Difficulty/boundary_precision_check/offer_acceptance_deadline_exact_boundary_expired
    """
    ctx = setup_offer(airport_overrides={"airport_code": "KBND"}, size_class="T_HANGAR",
                      rate=90000, hangar_code="T-11", applicant_name="Bo Boundary1")
    offer = ctx["offer"]
    # 72-hour window from the default clock 2026-08-01T00:00:00Z.
    assert parse_instant(offer["acceptance_deadline"]) == parse_instant("2026-08-04T00:00:00Z")

    set_clock("2026-08-03T23:59:59.999Z")  # one millisecond before the deadline
    resp = _accept_raw(offer["id"], ctx["hangar"]["version"], ctx["application"])
    lease = validate_success(resp, expected_status=201)
    assert lease["status"] == "ACTIVE"
    assert get_offer(offer["id"])["status"] == "ACCEPTED"


def test_accept_at_exact_deadline_rejected(api, manager_headers):
    """PRD §3.3: "Consequently, at the exact deadline instant the offer row is still `OPEN` in storage, and an acceptance at that instant fails on the window rule rather than on a state check."

    Design: Difficulty/boundary_precision_check/offer_acceptance_deadline_exact_boundary_expired
    """
    ctx = setup_offer(airport_overrides={"airport_code": "KBN2"}, size_class="T_HANGAR",
                      rate=90000, hangar_code="T-12", applicant_name="Bo Boundary2")
    offer = ctx["offer"]
    assert parse_instant(offer["acceptance_deadline"]) == parse_instant("2026-08-04T00:00:00Z")

    set_clock("2026-08-04T00:00:00Z")  # exactly the deadline
    resp = _accept_raw(offer["id"], ctx["hangar"]["version"], ctx["application"])
    validate_error(resp, ApiErrorId.ERR_OFFER_WINDOW_EXPIRED)
    # Lazy expiry: the sweep flips the row only strictly after the deadline.
    assert get_offer(offer["id"])["status"] == "OPEN"


def test_expired_offer_accept_reports_not_open(api, manager_headers):
    """PRD §2.9: "Every request passes through an ordered validation pipeline; when several checks would fail at once, the earliest check in this ordering determines the response."
    PRD §2.9: "Fifth, resource state preconditions: each transition endpoint requires its target resource to be in a specific state, reported with the per-resource identifiers named throughout §3 — `ERR_APPLICATION_NOT_QUEUED`, `ERR_APPLICATION_NOT_WITHDRAWABLE`, `ERR_OFFER_NOT_OPEN`, `ERR_FINDING_NOT_OPEN`, `ERR_CASE_NOT_FILED`, `ERR_INSPECTION_NOT_OPEN`, `ERR_LEASE_NOT_AUDITABLE`, `ERR_LEASE_NOT_DELINQUENT`, `ERR_LEASE_NOT_EVICTED`, `ERR_LEASE_NOT_ACTIVE`, and `ERR_AIRPORT_NOT_SUSPENDED` — with an otherwise unclassified state failure surfacing as `ERR_INVALID_STATE` (HTTP 409). Sixth, time-window checks on the offer-acceptance and cure windows."
    PRD §3.4: "Beyond the concurrency guard, acceptance requires the offer to be `OPEN` (`ERR_OFFER_NOT_OPEN`), the logical clock to be strictly before the `acceptance_deadline` (`ERR_OFFER_WINDOW_EXPIRED`), the hangar's posture to still reflect this offer's reservation (`ERR_HANGAR_NOT_AVAILABLE`), and the insurance coverage to satisfy the minimum of §3.7 (`ERR_INSUFFICIENT_COVERAGE`, HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/state_vs_business_temporal_on_expired_offer_accept
    """
    ctx = setup_offer(airport_overrides={"airport_code": "KPRI"}, size_class="T_HANGAR",
                      rate=90000, hangar_code="T-5", applicant_name="Pri Priority")
    offer = ctx["offer"]
    # Strictly past the 2026-08-04 deadline: the sweep flips the offer EXPIRED,
    # so the accept attempt fails both the state check and the window check;
    # the state check is earlier in the pipeline.
    set_clock("2026-08-05T00:00:00Z")

    resp = _accept_raw(offer["id"], ctx["hangar"]["version"], ctx["application"])
    validate_error(resp, ApiErrorId.ERR_OFFER_NOT_OPEN)


def test_sweep_marks_offer_expired_and_application_expired(api, manager_headers):
    """PRD §3.3: "When the sweep does expire an offer, the application moves to `EXPIRED_OFFER` and the hangar's posture is recomputed, returning to `AVAILABLE` when no other lease or offer holds it."

    Design: Difficulty/priority_pair_validation_conflict/state_vs_business_temporal_on_expired_offer_accept
    """
    ctx = setup_offer(airport_overrides={"airport_code": "KPR3"}, size_class="T_HANGAR",
                      rate=90000, hangar_code="T-6", applicant_name="Pri Priority")
    set_clock("2026-08-05T00:00:00Z")

    assert get_offer(ctx["offer"]["id"])["status"] == "EXPIRED"
    assert get_application(ctx["application"]["id"])["status"] == "EXPIRED_OFFER"
    assert get_hangar(ctx["hangar"]["id"])["posture"] == "AVAILABLE"


def test_accept_with_insufficient_insurance_coverage_rejected(api, manager_headers):
    """PRD §3.7: "A lease is insurance-compliant at an instant exactly when some certificate for it is in `VALID` status, its window contains the instant, and its `liability_coverage_cents` is at least 100000000 cents — one million dollars of liability coverage. Lease activation enforces the same minimum (`ERR_INSUFFICIENT_COVERAGE`)."

    Design: Corner/validations/accept_with_insufficient_insurance_coverage_rejected
    """
    ctx = setup_offer(airport_overrides={"airport_code": "KCOV"}, size_class="T_HANGAR",
                      rate=90000, hangar_code="T-160", applicant_name="Cov Erage")
    resp = _accept_raw(ctx["offer"]["id"], ctx["hangar"]["version"], ctx["application"],
                       insurance_liability_coverage_cents=99999999)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_COVERAGE)
    assert get_offer(ctx["offer"]["id"])["status"] == "OPEN"
    assert get_application(ctx["application"]["id"])["status"] == "OFFERED"


def test_offer_timestamps_use_default_logical_clock(api, manager_headers):
    """PRD §2.5: "Before any clock-setting call, the logical clock reads exactly 2026-08-01T00:00:00Z and must not fall back to wall-clock time."
    PRD §3.3: "A created offer lands in `OPEN` status with `offer_sent_at` set to the server timestamp and its `acceptance_deadline` exactly `offer_acceptance_window_hours` hours later."

    Design: Corner/cross_cutting_layers/clock_default_and_monotonic_sweep_side_effects
    """
    ctx = setup_offer(airport_overrides={"airport_code": "KCLK"}, size_class="T_HANGAR",
                      rate=90000, hangar_code="T-250", applicant_name="Cl Ock")
    offer = ctx["offer"]
    assert parse_instant(offer["offer_sent_at"]) == parse_instant("2026-08-01T00:00:00Z"), (
        f"offer_sent_at must be stamped from the default logical clock, got {offer['offer_sent_at']}"
    )
    # 72 hours after 2026-08-01T00:00:00Z.
    assert parse_instant(offer["acceptance_deadline"]) == parse_instant("2026-08-04T00:00:00Z")


def test_accept_response_and_hangar_immediately_consistent(api, manager_headers):
    """PRD §3.4: "On success — responded with 201 — the offer becomes `ACCEPTED`; the new lease is created in `ACTIVE` status with `tenant_name` copied from the application's `applicant_name`, `base_monthly_rate_cents` copied from the offer's `quoted_monthly_rate_cents`, `lease_start_date` set to the server timestamp, and `last_escalation_anniversary` zero; the first rent charge is created pro-rated per §3.5; the insurance certificate is created in `VALID` status; the aircraft is created `BASED` and marked primary; and the hangar's `posture` becomes `LEASED` with its `version` incremented by one."

    Design: Corner/consistency_model/immediate_consistency_lease_graph_visible_in_same_request
    """
    ctx = setup_offer(airport_overrides={"airport_code": "KIMM"}, size_class="T_HANGAR",
                      rate=90000, hangar_code="T-260", applicant_name="Im Mediate")
    hangar_before = ctx["hangar"]

    resp = _accept_raw(ctx["offer"]["id"], hangar_before["version"], ctx["application"])
    lease = validate_success(resp, expected_status=201)
    assert lease["base_monthly_rate_cents"] == 90000
    assert lease["current_monthly_rate_cents"] == 90000
    assert lease["status"] == "ACTIVE"

    hangar_after = get_hangar(hangar_before["id"])
    assert hangar_after["posture"] == "LEASED"
    assert hangar_after["version"] == hangar_before["version"] + 1, (
        "acceptance increments the hangar's version by one"
    )


def test_overlap_offer_pins_latest_effective_from(api, manager_headers):
    """PRD §3.1: "Selection happens when an offer pins its quoted rate and at lease renewal: among the airport's `ACTIVE` schedules for the hangar's size class whose window contains the offer instant, the winner is the one with the latest `effective_from`, with `created_at` ascending as the final tie-break."
    PRD §3.3: "The offer pins `rate_schedule_id` to the selected schedule and copies that schedule's rate into `quoted_monthly_rate_cents`, which is immutable thereafter."

    Design: Difficulty/dual_variant_calc/rate_schedule_selection_overlap_latest_effective_from_wins
    """
    airport = create_airport(airport_code="KOVR", escalation_pct=0.03,
                             escalation_policy="ANNIVERSARY_COMPOUND")
    schedule_old = add_rate_schedule(airport["id"], size_class="T_HANGAR",
                                     monthly_rate_cents=100000,
                                     effective_from="2026-07-01T00:00:00Z", effective_to="OPEN")
    hangar = add_hangar(airport["id"], hangar_code="B-1", size_class="T_HANGAR",
                        door_type="BIFOLD")
    application = submit_application(airport["id"], applicant_name="Olive Overlap")
    schedule_new = add_rate_schedule(airport["id"], size_class="T_HANGAR",
                                     monthly_rate_cents=120000,
                                     effective_from="2026-08-01T00:00:00Z", effective_to="OPEN")

    # Offer instant is the default clock 2026-08-01T00:00:00Z, contained by
    # both windows; the later effective_from wins.
    offer = extend_offer(airport["id"], hangar["id"], application["id"])
    assert offer["quoted_monthly_rate_cents"] == 120000, (
        f"overlapped instant must quote the latest-effective_from schedule, got {offer['quoted_monthly_rate_cents']}"
    )
    assert offer["rate_schedule_id"] == schedule_new["id"]
    assert offer["status"] == "OPEN"
    assert schedule_old["id"] != schedule_new["id"]


def test_overlapping_schedules_both_remain_active(api, manager_headers):
    """PRD §3.1: "When a newer schedule is created for the same airport and size class with exactly the same `effective_from` as an existing one, the older schedule is marked `SUPERSEDED`; overlapping schedules with different start instants instead both remain `ACTIVE` and are resolved at selection time."

    Design: Difficulty/dual_variant_calc/rate_schedule_selection_overlap_latest_effective_from_wins
    """
    airport = create_airport(airport_code="KOV2", escalation_pct=0.03,
                             escalation_policy="ANNIVERSARY_COMPOUND")
    add_rate_schedule(airport["id"], size_class="T_HANGAR", monthly_rate_cents=100000,
                      effective_from="2026-07-01T00:00:00Z", effective_to="OPEN")
    hangar = add_hangar(airport["id"], hangar_code="B-2", size_class="T_HANGAR",
                        door_type="BIFOLD")
    application = submit_application(airport["id"], applicant_name="Olive Overlap")
    add_rate_schedule(airport["id"], size_class="T_HANGAR", monthly_rate_cents=120000,
                      effective_from="2026-08-01T00:00:00Z", effective_to="OPEN")

    schedules, meta = validate_paginated(
        api_client.list_rate_schedules(manager_headers,
                                       params={"airport_id": airport["id"],
                                               "size_class": "T_HANGAR"})
    )
    assert meta["total_count"] == 2
    assert all(s["status"] == "ACTIVE" for s in schedules), (
        "overlapping schedules with different start instants both remain ACTIVE"
    )

    offer = extend_offer(airport["id"], hangar["id"], application["id"])
    assert offer["quoted_monthly_rate_cents"] == 120000


def test_offer_at_adjacency_boundary_quotes_later_schedule(api, manager_headers):
    """PRD §3.1: "A schedule is created with its `airport_id`, the `size_class` it prices (one of `T_HANGAR`, `BOX`, `EXECUTIVE`, `CORPORATE`), a `monthly_rate_cents` that must be greater than zero, and a half-open coverage window running from `effective_from` (inclusive) to `effective_to` (exclusive); an open-ended schedule supplies the explicit string `'OPEN'` as `effective_to`, the only sanctioned null-equivalent. Two schedules whose windows merely abut — one's `effective_to` equal to the other's `effective_from` — do not overlap: the boundary instant belongs to the later schedule."

    Design: Difficulty/resource_temporal_overlap/rate_schedule_half_open_interval_adjacency
    """
    airport = create_airport(airport_code="KHOP")
    add_rate_schedule(airport["id"], size_class="T_HANGAR", monthly_rate_cents=90000,
                      effective_from="2026-07-01T00:00:00Z",
                      effective_to="2026-08-10T00:00:00Z")
    add_rate_schedule(airport["id"], size_class="T_HANGAR", monthly_rate_cents=95000,
                      effective_from="2026-08-10T00:00:00Z", effective_to="OPEN")
    hangar = add_hangar(airport["id"], hangar_code="T-40", size_class="T_HANGAR")
    application = submit_application(airport["id"], applicant_name="Hal Open")

    set_clock("2026-08-10T00:00:00Z")  # exactly the abutting instant
    offer = extend_offer(airport["id"], hangar["id"], application["id"])
    assert offer["quoted_monthly_rate_cents"] == 95000, (
        f"the boundary instant belongs to the later schedule, got {offer['quoted_monthly_rate_cents']}"
    )


def test_offer_before_adjacency_boundary_quotes_earlier_schedule(api, manager_headers):
    """PRD §3.1: "A schedule is created with its `airport_id`, the `size_class` it prices (one of `T_HANGAR`, `BOX`, `EXECUTIVE`, `CORPORATE`), a `monthly_rate_cents` that must be greater than zero, and a half-open coverage window running from `effective_from` (inclusive) to `effective_to` (exclusive); an open-ended schedule supplies the explicit string `'OPEN'` as `effective_to`, the only sanctioned null-equivalent. Two schedules whose windows merely abut — one's `effective_to` equal to the other's `effective_from` — do not overlap: the boundary instant belongs to the later schedule."

    Design: Difficulty/resource_temporal_overlap/rate_schedule_half_open_interval_adjacency
    """
    airport = create_airport(airport_code="KHO2")
    add_rate_schedule(airport["id"], size_class="T_HANGAR", monthly_rate_cents=90000,
                      effective_from="2026-07-01T00:00:00Z",
                      effective_to="2026-08-10T00:00:00Z")
    add_rate_schedule(airport["id"], size_class="T_HANGAR", monthly_rate_cents=95000,
                      effective_from="2026-08-10T00:00:00Z", effective_to="OPEN")
    hangar = add_hangar(airport["id"], hangar_code="T-41", size_class="T_HANGAR")
    application = submit_application(airport["id"], applicant_name="Hal Open")

    set_clock("2026-08-09T00:00:00Z")  # strictly inside the earlier window
    offer = extend_offer(airport["id"], hangar["id"], application["id"])
    assert offer["quoted_monthly_rate_cents"] == 90000, (
        f"an instant before the boundary prices from the earlier schedule, got {offer['quoted_monthly_rate_cents']}"
    )


def test_occ_stale_hangar_version_on_accept(api, manager_headers):
    """PRD §2.7: "Accepting a hangar offer requires the request to carry `expected_hangar_version`, the `version` of the hangar as the client last observed it. If the hangar's current `version` no longer matches — for example because a prior acceptance already advanced the version and flipped the hangar's posture — the acceptance is rejected with `ERR_STALE_VERSION` (HTTP 412)."
    PRD §3.6: "On close the inspection becomes `CLOSED`, the hangar's `condition_rating` adopts this inspection's rating — the latest `CLOSED` inspection always wins — the hangar's `version` increments, and its `posture` is recomputed under the compound rule of §2.8."

    Design: Corner/cross_cutting_layers/occ_stale_hangar_version_on_accept
    """
    ctx = setup_offer(airport_overrides={"airport_code": "KOCC"}, size_class="T_HANGAR",
                      rate=90000, hangar_code="T-230", applicant_name="Oc C")
    stale_version = ctx["hangar"]["version"]

    # Closing an inspection mutates the hangar and increments its version,
    # making the client's captured version stale.
    inspection = validate_success(
        api_client.create_inspection(
            ctx["hangar"]["id"],
            create_inspection_payload(condition_rating="FAIR",
                                      maintenance_responsibility="AIRPORT",
                                      deficiency_note="cosmetic"),
            manager_headers,
        ),
        expected_status=201,
    )
    validate_success(api_client.close_inspection(inspection["id"], {}, manager_headers))
    assert get_hangar(ctx["hangar"]["id"])["version"] == stale_version + 1

    resp = _accept_raw(ctx["offer"]["id"], stale_version, ctx["application"])
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
    assert get_offer(ctx["offer"]["id"])["status"] == "OPEN"
