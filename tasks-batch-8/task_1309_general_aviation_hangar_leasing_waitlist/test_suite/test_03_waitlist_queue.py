"""Waitlist queue behavior: withdrawal, priority scoring, decline cycle, and offer gates."""
from test_helpers import (
    ApiErrorId,
    add_hangar,
    add_rate_schedule,
    api_client,
    create_airport,
    create_offer_payload,
    extend_offer,
    get_application,
    get_hangar,
    get_offer,
    make_applicant_headers,
    make_tenant_headers,
    accept_offer,
    set_clock,
    setup_lease,
    setup_offer,
    submit_application,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_withdraw_application_in_queued_state(api, manager_headers):
    """PRD §3.3: "An applicant may withdraw while `QUEUED` or `OFFERED` — any other state fails with `ERR_APPLICATION_NOT_WITHDRAWABLE` (HTTP 409) — moving the application to `WITHDRAWN`; withdrawing while `OFFERED` also moves the linked `OPEN` offer to `CANCELLED` and recomputes the hangar's posture toward `AVAILABLE`."

    Design: Corner/state_machines/withdraw_application_in_queued_state
    """
    airport = create_airport(airport_code="KWDR")
    application = submit_application(airport["id"], applicant_name="Will Draw",
                                     size_class_requested="BOX")
    headers = make_applicant_headers(application["id"])

    resp = api.withdraw_application(application["id"], headers)
    withdrawn = validate_success(resp)
    assert withdrawn["status"] == "WITHDRAWN"

    resp = api.withdraw_application(application["id"], headers)
    validate_error(resp, ApiErrorId.ERR_APPLICATION_NOT_WITHDRAWABLE)


def test_transfer_bonus_outranks_longer_wait(api, manager_headers):
    """PRD §3.2: "The priority score starts at one hundred base points, adds one point for every whole day the application has spent in the queue, and adds a thirty-point transfer bonus when `is_based_tenant_transfer` is true."
    PRD §3.2: "Ranking sorts by score descending and breaks ties by `created_at` ascending — the older application ranks first; because timestamps carry millisecond precision and applications are created sequentially, no further tie-break exists and a random identifier is never consulted."
    PRD §3.3: "the application must be the highest-ranked eligible `QUEUED` application for the hangar's size class per the priority score, unless `override_next_in_queue` is true (`ERR_NOT_NEXT_IN_QUEUE`, HTTP 409)".

    Design: Corner/calculations/waitlist_priority_score_transfer_bonus_and_fifo_tiebreak
    """
    airport = create_airport(airport_code="KPRI2")
    add_rate_schedule(airport["id"], size_class="T_HANGAR", monthly_rate_cents=90000)
    add_rate_schedule(airport["id"], size_class="BOX", monthly_rate_cents=80000)
    hangar_t = add_hangar(airport["id"], hangar_code="T-100", size_class="T_HANGAR")
    hangar_box = add_hangar(airport["id"], hangar_code="B-100", size_class="BOX",
                            door_type="BIFOLD")

    # Applicant A waits in the T_HANGAR queue from the default clock (2026-08-01).
    app_a = submit_application(airport["id"], applicant_name="Ann A",
                               size_class_requested="T_HANGAR")

    # Applicant B first takes a BOX lease so the later transfer claim holds an
    # ACTIVE lease at this airport (PRD §3.2 definition of the transfer flag).
    app_b0 = submit_application(airport["id"], applicant_name="Ben B",
                                size_class_requested="BOX")
    offer_b0 = extend_offer(airport["id"], hangar_box["id"], app_b0["id"])
    lease_b0 = accept_offer(offer_b0, hangar_box, app_b0)
    resp = api.create_payment(lease_b0["id"], {"amount_cents": 80000},
                              make_tenant_headers(lease_b0["id"]))
    validate_success(resp)

    # B joins the T_HANGAR queue as a transfer at 2026-08-11; at the 2026-08-20
    # ranking, A scores 100+19=119 while B scores 100+9+30=139, so B is next.
    set_clock("2026-08-11T00:00:00Z")
    app_b = submit_application(airport["id"], applicant_name="Ben B",
                               size_class_requested="T_HANGAR",
                               aircraft_n_number="N261SC",
                               is_based_tenant_transfer=True)
    set_clock("2026-08-20T00:00:00Z")

    resp = api.create_offer(
        create_offer_payload(airport_id=airport["id"], hangar_id=hangar_t["id"],
                             application_id=app_a["id"]),
        manager_headers,
    )
    validate_error(resp, ApiErrorId.ERR_NOT_NEXT_IN_QUEUE)

    offer_b = validate_success(
        api.create_offer(
            create_offer_payload(airport_id=airport["id"], hangar_id=hangar_t["id"],
                                 application_id=app_b["id"]),
            manager_headers,
        ),
        expected_status=201,
    )
    assert offer_b["status"] == "OPEN"
    assert get_application(app_b["id"])["status"] == "OFFERED"


def test_first_decline_returns_application_to_queue(api, manager_headers):
    """PRD §3.3: "Declining requires the offer to be `OPEN` (`ERR_OFFER_NOT_OPEN`, HTTP 409) and increments the application's `decline_count`. Each application has exactly one free decline in its lifetime: a first decline returns the application to `QUEUED`, with the free-decline gate expressed in the error catalogue as `ERR_REPEAT_DECLINE_NOT_ALLOWED` (HTTP 409)."

    Design: Difficulty/non_linear_state_machine/waitlist_application_offered_to_queued_cycle
    """
    ctx = setup_offer(airport_overrides={"airport_code": "KCYC"}, size_class="T_HANGAR",
                      rate=90000, hangar_code="T-1", applicant_name="Cy Cyclist")
    offer = ctx["offer"]
    application = ctx["application"]

    resp = api.decline_offer(offer["id"], make_applicant_headers(application["id"]))
    declined = validate_success(resp)
    assert declined["status"] == "DECLINED"

    after = get_application(application["id"])
    assert after["status"] == "QUEUED", (
        f"first decline must return the application to QUEUED, got {after['status']}"
    )
    assert after["decline_count"] == 1


def test_second_decline_rejects_application(api, manager_headers):
    """PRD §3.3: "A decline made when the application has already declined once — a `decline_count` of at least one at decline time — does not error; it moves the application to `REJECTED` and out of the queue. Either way the offer becomes `DECLINED` and the hangar's posture is recomputed toward `AVAILABLE`."

    Design: Difficulty/non_linear_state_machine/waitlist_application_offered_to_queued_cycle
    """
    ctx = setup_offer(airport_overrides={"airport_code": "KCY2"}, size_class="T_HANGAR",
                      rate=90000, hangar_code="T-1", applicant_name="Cy Cyclist")
    application = ctx["application"]
    headers = make_applicant_headers(application["id"])
    validate_success(api.decline_offer(ctx["offer"]["id"], headers))

    # Back in QUEUED, the sole application is next in queue for a second hangar.
    hangar2 = add_hangar(ctx["airport"]["id"], hangar_code="T-2", size_class="T_HANGAR")
    offer2 = extend_offer(ctx["airport"]["id"], hangar2["id"], application["id"])

    resp = api.decline_offer(offer2["id"], headers)
    assert validate_success(resp)["status"] == "DECLINED"
    assert get_application(application["id"])["status"] == "REJECTED"


def test_open_offer_removes_hangar_from_available_pool(api, manager_headers):
    """PRD §3.3: "The application moves from `QUEUED` to `OFFERED`, and the hangar's posture is recomputed so the open offer reserves it against other offers — though offer creation itself does not increment the hangar's `version`."
    PRD §2.8: "Only `AVAILABLE` hangars can receive new offers, and an `OPEN` offer reserves its hangar against further offers for its lifetime."
    PRD §2.8: "`AVAILABLE`: no lease on the hangar is in `ACTIVE`, `DELINQUENT`, `CURE_PERIOD`, or `EVICTION_PENDING`, and the hangar's `condition_rating` is not `OUT_OF_SERVICE`."
    PRD §3.3: "the hangar's `posture` must be `AVAILABLE` and the hangar must still be `OPERATIONAL` rather than `DECOMMISSIONED` (`ERR_HANGAR_NOT_AVAILABLE`, HTTP 409)".

    Design: Difficulty/compensating_invariant/offer_accept_cancel_conserves_available_hangar_pool
    """
    airport = create_airport(airport_code="KPOOL")
    add_rate_schedule(airport["id"], size_class="T_HANGAR", monthly_rate_cents=90000)
    hangar1 = add_hangar(airport["id"], hangar_code="T-70", size_class="T_HANGAR")
    hangar2 = add_hangar(airport["id"], hangar_code="T-71", size_class="T_HANGAR")
    application = submit_application(airport["id"], applicant_name="Polly Pool")
    extend_offer(airport["id"], hangar1["id"], application["id"])

    held = get_hangar(hangar1["id"])
    free = get_hangar(hangar2["id"])
    # The §2.8 posture derivation considers only leases and condition_rating;
    # with no occupying lease and a GOOD rating the recomputation leaves the
    # posture AVAILABLE — the open offer's reservation is behavioral (below),
    # not a distinct posture value.
    assert held["posture"] == "AVAILABLE", (
        f"posture derives only from leases and condition_rating per §2.8, got {held['posture']}"
    )
    assert held["version"] == hangar1["version"], (
        "offer creation itself must not increment the hangar's version"
    )
    assert free["posture"] == "AVAILABLE"

    # The reservation: a second offer naming the reserved hangar is rejected at
    # the availability gate, while the still-free hangar receives one — the
    # available pool is conserved across offer creation.
    app2 = submit_application(airport["id"], applicant_name="Paul Pool")
    resp = api.create_offer(
        create_offer_payload(airport_id=airport["id"], hangar_id=hangar1["id"],
                             application_id=app2["id"]),
        manager_headers,
    )
    validate_error(resp, ApiErrorId.ERR_HANGAR_NOT_AVAILABLE)

    offer2 = validate_success(
        api.create_offer(
            create_offer_payload(airport_id=airport["id"], hangar_id=hangar2["id"],
                                 application_id=app2["id"]),
            manager_headers,
        ),
        expected_status=201,
    )
    assert offer2["status"] == "OPEN"


def test_offer_expiry_restores_available_pool(api, manager_headers):
    """PRD §3.3: "The sweep, in contrast, flips an `OPEN` offer to `EXPIRED` only when the logical clock is strictly later than the deadline — a lazy expiry."
    PRD §3.3: "When the sweep does expire an offer, the application moves to `EXPIRED_OFFER` and the hangar's posture is recomputed, returning to `AVAILABLE` when no other lease or offer holds it."

    Design: Difficulty/compensating_invariant/offer_accept_cancel_conserves_available_hangar_pool
    """
    airport = create_airport(airport_code="KPO2")
    add_rate_schedule(airport["id"], size_class="T_HANGAR", monthly_rate_cents=90000)
    hangar1 = add_hangar(airport["id"], hangar_code="T-72", size_class="T_HANGAR")
    hangar2 = add_hangar(airport["id"], hangar_code="T-73", size_class="T_HANGAR")
    application = submit_application(airport["id"], applicant_name="Polly Pool")
    offer = extend_offer(airport["id"], hangar1["id"], application["id"])

    # 72h window from the default clock (2026-08-01) ends 2026-08-04; the sweep
    # at 2026-08-05 is strictly later, so the offer expires.
    set_clock("2026-08-05T00:00:00Z")

    assert get_offer(offer["id"])["status"] == "EXPIRED"
    assert get_application(application["id"])["status"] == "EXPIRED_OFFER"
    assert get_hangar(hangar1["id"])["posture"] == "AVAILABLE"
    assert get_hangar(hangar2["id"])["posture"] == "AVAILABLE"


def test_offer_on_leased_hangar_rejected(api, manager_headers):
    """PRD §3.3: "the hangar's `posture` must be `AVAILABLE` and the hangar must still be `OPERATIONAL` rather than `DECOMMISSIONED` (`ERR_HANGAR_NOT_AVAILABLE`, HTTP 409)".
    PRD §2.8: "`LEASED`: such a lease exists and `condition_rating` is not `OUT_OF_SERVICE`."

    Design: Difficulty/cross_entity_state_dependency/offer_requires_hangar_posture_available
    """
    ctx = setup_lease(airport_overrides={"airport_code": "KXSD"}, size_class="T_HANGAR",
                      rate=90000, hangar_code="T-30", applicant_name="Alice A")
    app_b = submit_application(ctx["airport"]["id"], applicant_name="Bob B",
                               size_class_requested="T_HANGAR")

    resp = api.create_offer(
        create_offer_payload(airport_id=ctx["airport"]["id"], hangar_id=ctx["hangar"]["id"],
                             application_id=app_b["id"], override_next_in_queue=True),
        manager_headers,
    )
    validate_error(resp, ApiErrorId.ERR_HANGAR_NOT_AVAILABLE)
    assert get_hangar(ctx["hangar"]["id"])["posture"] == "LEASED"


def test_rejected_offer_leaves_application_queued(api, manager_headers):
    """PRD §3.3: "Creation enforces, in pipeline order: the airport must be `ACTIVE`; the application must be `QUEUED` (`ERR_APPLICATION_NOT_QUEUED`, HTTP 409); the application must be the highest-ranked eligible `QUEUED` application for the hangar's size class per the priority score, unless `override_next_in_queue` is true (`ERR_NOT_NEXT_IN_QUEUE`, HTTP 409); the hangar's `posture` must be `AVAILABLE` and the hangar must still be `OPERATIONAL` rather than `DECOMMISSIONED` (`ERR_HANGAR_NOT_AVAILABLE`, HTTP 409); the hangar's `size_class` must equal the application's `size_class_requested` (`ERR_SIZE_CLASS_MISMATCH`, HTTP 409); and an `ACTIVE` rate schedule must cover the offer instant (`ERR_NO_ACTIVE_RATE_SCHEDULE`)."

    Design: Difficulty/cross_entity_state_dependency/offer_requires_hangar_posture_available
    """
    ctx = setup_lease(airport_overrides={"airport_code": "KXS2"}, size_class="T_HANGAR",
                      rate=90000, hangar_code="T-31", applicant_name="Alice A")
    app_b = submit_application(ctx["airport"]["id"], applicant_name="Bob B",
                               size_class_requested="T_HANGAR")

    resp = api.create_offer(
        create_offer_payload(airport_id=ctx["airport"]["id"], hangar_id=ctx["hangar"]["id"],
                             application_id=app_b["id"], override_next_in_queue=True),
        manager_headers,
    )
    validate_error(resp, ApiErrorId.ERR_HANGAR_NOT_AVAILABLE)

    # A rejected creation leaves the application queued and creates no offer.
    assert get_application(app_b["id"])["status"] == "QUEUED"
    offers, meta = validate_paginated(
        api.list_offers(manager_headers, params={"airport_id": ctx["airport"]["id"]})
    )
    assert meta["total_count"] == 1, "only the original (accepted) offer may exist"


def test_size_class_mismatch_on_offer_rejected(api, manager_headers):
    """PRD §3.3: "the hangar's `size_class` must equal the application's `size_class_requested` (`ERR_SIZE_CLASS_MISMATCH`, HTTP 409)".

    Design: Corner/validations/size_class_mismatch_on_offer_rejected
    """
    airport = create_airport(airport_code="KSZM")
    add_rate_schedule(airport["id"], size_class="BOX", monthly_rate_cents=80000)
    add_rate_schedule(airport["id"], size_class="T_HANGAR", monthly_rate_cents=90000)
    hangar = add_hangar(airport["id"], hangar_code="B-150", size_class="BOX",
                        door_type="BIFOLD")
    application = submit_application(airport["id"], applicant_name="Siz E",
                                     size_class_requested="T_HANGAR")

    # override_next_in_queue isolates the size-class rule from the
    # queue-selection rule (the T_HANGAR application cannot rank in the BOX
    # queue), so exactly one check can fail.
    resp = api.create_offer(
        create_offer_payload(airport_id=airport["id"], hangar_id=hangar["id"],
                             application_id=application["id"],
                             override_next_in_queue=True),
        manager_headers,
    )
    validate_error(resp, ApiErrorId.ERR_SIZE_CLASS_MISMATCH)
