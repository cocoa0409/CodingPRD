"""The acceptance decision and the six gates an ACCEPT must clear."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_spot,
    classify_issue_advertiser,
    create_order,
    create_order_payload,
    create_rate_class,
    create_station,
    decide_classification,
    file_complaint,
    hourly_spots,
    list_file_entries,
    make_advertiser_agent_headers,
    order_decision_payload,
    read_order,
    read_station,
    set_clock,
    setup_candidate_order,
    setup_issue_order,
    submit_order,
    validate_error,
    validate_paginated,
    validate_success,
    withdraw_rate_class,
)

OFFICER_ALPHA = TEST_USERS["officer_alpha_headers"]
OFFICER_BETA = TEST_USERS["officer_beta_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]
ACCEPT = order_decision_payload("ACCEPT")


def test_candidate_order_without_an_authorization_clause_is_refused_at_acceptance(api):
    """PRD §3.5: "When the ordering advertiser is `CLASSIFIED_CANDIDATE`, the
    `sponsorship_disclosure_text` must additionally contain the literal string
    `AUTHORIZED BY` somewhere within it, or the acceptance fails with
    `ERR_DISCLOSURE_AUTHORIZATION_MISSING` (HTTP 422)."
    PRD §3.5: "That candidate-only authorisation requirement is deliberately *not* part
    of the four-branch grading above, because at submission time the advertiser may
    still have been under review and its classification unknown."

    Design: Corner/validations/candidate_order_without_authorized_by_clause_rejected_at_acceptance
    """
    built = setup_candidate_order(
        call_sign="WAUT-TV",
        market_code="DMA-125",
        station_overrides={"licensee_name": "Authorization Media LLC", "daily_political_seconds_cap": 300},
        include_authorization=False,
        spots=hourly_spots(1),
        submit=True,
    )
    order = built["order"]
    assert order["disclosure_status"] == "CONFORMING", (
        "the four-branch grading passes even without the authorisation clause"
    )

    validate_error(
        api.decide_order(order["id"], ACCEPT, OFFICER_BETA),
        ApiErrorId.ERR_DISCLOSURE_AUTHORIZATION_MISSING,
    )
    assert read_order(order["id"])["status"] == "SUBMITTED"


def test_acceptance_is_refused_while_the_advertiser_is_still_under_review(api):
    """PRD §3.5: "The ordering advertiser must have reached a terminal classification of
    either `CLASSIFIED_CANDIDATE` or `CLASSIFIED_ISSUE`, or the acceptance fails with
    `ERR_ADVERTISER_NOT_CLASSIFIED` (HTTP 409) — an advertiser still `SUBMITTED`,
    `UNDER_REVIEW` or `INFO_REQUESTED`, or one that ended in `CLASSIFICATION_REJECTED`,
    cannot buy."
    PRD §3.5: "Finally the acceptance files a public political file entry of
    `event_type` `ORDER_ACCEPTED` against the order, in `PENDING` posting state, and
    increments the station's `pending_file_entry_count` by one."

    Design: Corner/validations/acceptance_rejected_while_the_advertiser_is_still_under_review
    """
    built = setup_issue_order(
        call_sign="WUNR-TV",
        market_code="DMA-126",
        station_overrides={
            "licensee_name": "Under Review Media",
            "political_file_posting_deadline_hours": 24,
            "daily_political_seconds_cap": 300,
        },
        classification="REVIEW",
        spots=hourly_spots(1),
        submit=True,
    )
    order, advertiser, station = built["order"], built["advertiser"], built["station"]

    validate_error(
        api.decide_order(order["id"], ACCEPT, OFFICER_BETA),
        ApiErrorId.ERR_ADVERTISER_NOT_CLASSIFIED,
    )

    decide_classification(advertiser["id"], "CLASSIFY_ISSUE", "Non-candidate issue advocacy")
    accepted = validate_success(api.decide_order(order["id"], ACCEPT, OFFICER_BETA))
    assert accepted["status"] == "ACCEPTED"
    assert accepted["payment_status"] == "INVOICED"
    assert read_station(station["id"])["pending_file_entry_count"] == 1


def _station_with_both_buyers(call_sign, market_code, licensee_name):
    """One station carrying a submitted issue order and a submitted candidate order."""
    built = setup_candidate_order(
        call_sign=call_sign,
        market_code=market_code,
        station_overrides={
            "licensee_name": licensee_name,
            "political_file_posting_deadline_hours": 24,
            "daily_political_seconds_cap": 300,
        },
        spots=[
            {
                "air_date": "2026-08-20",
                "start_offset_seconds": 30000,
                "duration_seconds": 30,
                "program_code": "EN-C",
            }
        ],
        submit=True,
    )
    issue_advertiser = classify_issue_advertiser(
        built["station"]["id"], legal_name="Empire Growth Fund"
    )
    issue_order = create_order(
        built["station"]["id"],
        issue_advertiser["id"],
        built["rate_class"]["id"],
        payment_terms="PREPAY",
        sponsorship_disclosure_text="PAID FOR BY Empire Growth Fund",
        election_id=built["election"]["id"],
    )
    add_spot(
        issue_order["id"],
        issue_advertiser["id"],
        air_date="2026-08-20",
        start_offset_seconds=0,
        program_code="EN-I",
    )
    issue_order = submit_order(issue_order["id"], issue_advertiser["id"])
    built["issue_advertiser"] = issue_advertiser
    built["issue_order"] = issue_order
    return built


def test_restricted_posture_blocks_the_issue_buy_but_still_admits_the_candidate(api):
    """PRD §3.5: "When the ordering advertiser is `CLASSIFIED_ISSUE`, the station's
    posture must additionally not be `RESTRICTED`, or the acceptance fails with
    `ERR_STATION_POSTURE_RESTRICTED` (HTTP 409); this is the asymmetry that lets a
    lapsed station keep honouring candidate buys while it stops taking new issue
    advertising."
    PRD §3.1: "If that larger number is 2 or more, the posture is `FROZEN`. Otherwise,
    if it is 1 or more, the posture is `RESTRICTED`. Otherwise the posture is `OPEN`."

    Design: Corner/validations/restricted_posture_blocks_the_issue_order_but_still_admits_the_candidate_order
    """
    built = _station_with_both_buyers("WRES-TV", "DMA-127", "Restricted Posture Media")
    station = built["station"]

    file_complaint(
        station["id"],
        complainant_name="Ida Brennan",
        allegation_code="DISCLOSURE_DEFECT",
        narrative="Sponsorship identification was illegible.",
    )

    gated = read_station(station["id"])
    assert gated["open_complaint_count"] == 1
    assert gated["compliance_posture"] == "RESTRICTED"

    validate_error(
        api.decide_order(built["issue_order"]["id"], ACCEPT, OFFICER_BETA),
        ApiErrorId.ERR_STATION_POSTURE_RESTRICTED,
    )
    assert read_order(built["issue_order"]["id"])["status"] == "SUBMITTED"

    candidate_accepted = validate_success(
        api.decide_order(built["order"]["id"], ACCEPT, OFFICER_BETA)
    )
    assert candidate_accepted["status"] == "ACCEPTED", (
        "statutory candidate access survives a restricted posture"
    )


def test_acceptance_is_refused_while_the_station_posture_is_frozen(api):
    """PRD §3.5: "The station's `compliance_posture` must not be `FROZEN`, or the
    acceptance fails with `ERR_STATION_POSTURE_FROZEN` (HTTP 409)."
    PRD §3.5: "The order must be sitting in `SUBMITTED`; anything else fails with
    `ERR_ORDER_NOT_SUBMITTED` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/order_acceptance_depends_on_station_compliance_posture_not_being_frozen
    """
    built = setup_candidate_order(
        call_sign="WFRZ-TV",
        market_code="DMA-901",
        station_overrides={
            "licensee_name": "Frozen Post Media LLC",
            "political_file_posting_deadline_hours": 24,
            "daily_political_seconds_cap": 300,
        },
        spots=hourly_spots(1),
        submit=True,
    )
    station, order = built["station"], built["order"]

    file_complaint(
        station["id"],
        complainant_name="Ida Brennan",
        allegation_code="FILE_TIMELINESS",
        narrative="Political file entries were not posted within one business day.",
    )
    file_complaint(
        station["id"],
        complainant_name="Owen Tsai",
        allegation_code="LUC_OVERCHARGE",
        narrative="Candidate spots were billed above the lowest unit charge.",
    )

    validate_error(
        api.decide_order(order["id"], ACCEPT, OFFICER_BETA),
        ApiErrorId.ERR_STATION_POSTURE_FROZEN,
    )

    refreshed = read_order(order["id"])
    assert refreshed["status"] == "SUBMITTED"
    assert refreshed["payment_status"] == "UNBILLED"


def test_two_open_complaints_freeze_the_station_and_file_no_entry(api):
    """PRD §3.1: "Take the station's current count of overdue political file entries and
    its current count of open complaints, and consider **the larger of those two
    numbers** — never their sum. If that larger number is 2 or more, the posture is
    `FROZEN`."
    PRD §3.9: "Filing stamps `filed_at` with the logical clock, derives
    `response_due_at` as 240 hours — ten days — after that instant, opens the complaint
    in `OPEN` with `remedy_code`, `cure_due_at`, `responded_at`, `response_text` and
    `responded_by_user_id` all null and `late_response` false, then increments the
    station's `open_complaint_count` by one and recomputes its `compliance_posture`."

    Design: Difficulty/cross_entity_state_dependency/order_acceptance_depends_on_station_compliance_posture_not_being_frozen
    """
    built = setup_candidate_order(
        call_sign="WFR2-TV",
        market_code="DMA-902",
        station_overrides={
            "licensee_name": "Frozen Post Media LLC",
            "political_file_posting_deadline_hours": 24,
            "daily_political_seconds_cap": 300,
        },
        spots=hourly_spots(1),
        submit=True,
    )
    station, order = built["station"], built["order"]

    file_complaint(station["id"], complainant_name="Ida Brennan", allegation_code="FILE_TIMELINESS")
    file_complaint(station["id"], complainant_name="Owen Tsai", allegation_code="LUC_OVERCHARGE")

    frozen = read_station(station["id"])
    assert frozen["open_complaint_count"] == 2
    assert frozen["overdue_file_entry_count"] == 0
    assert frozen["compliance_posture"] == "FROZEN", (
        "two open complaints alone reach the freeze threshold"
    )

    validate_error(
        api.decide_order(order["id"], ACCEPT, OFFICER_BETA),
        ApiErrorId.ERR_STATION_POSTURE_FROZEN,
    )

    _rows, meta = validate_paginated(
        api.list_file_entries(ADMIN, params={"station_id": station["id"]})
    )
    assert meta["total_count"] == 0, "a refused acceptance files nothing"


def test_issue_advertiser_presented_on_net_30_is_refused_at_acceptance(api):
    """PRD §3.5: "And when the ordering advertiser is `CLASSIFIED_ISSUE`, the order's
    `payment_terms` must be `PREPAY`; an issue advertiser presented on `NET_30` is
    refused with `ERR_PAYMENT_TERMS_NOT_PERMITTED` (HTTP 422)."

    Design: Corner/validations/issue_advertiser_order_with_net30_terms_rejected_at_acceptance
    """
    built = setup_issue_order(
        call_sign="WTRP-TV",
        market_code="DMA-124",
        station_overrides={"licensee_name": "Terms Policy Broadcasting", "daily_political_seconds_cap": 300},
        order_overrides={"payment_terms": "NET_30"},
        spots=hourly_spots(1),
        submit=True,
    )
    order, station = built["order"], built["station"]

    validate_error(
        api.decide_order(order["id"], ACCEPT, OFFICER_BETA),
        ApiErrorId.ERR_PAYMENT_TERMS_NOT_PERMITTED,
    )

    refreshed = read_order(order["id"])
    assert refreshed["status"] == "SUBMITTED"
    assert refreshed["payment_status"] == "UNBILLED"
    _rows, meta = validate_paginated(
        api.list_file_entries(ADMIN, params={"order_id": order["id"]})
    )
    assert meta["total_count"] == 0


def test_withdrawn_rate_class_blocks_acceptance_but_keeps_existing_charges(api):
    """PRD §3.3: "Withdrawal is one-way and it does not disturb existing charges: spots
    already priced from the class keep their `charged_rate_cents`. What withdrawal
    blocks is new use — adding a spot to a draft order priced from a withdrawn class, or
    accepting an order that names one, both fail with `ERR_RATE_CLASS_WITHDRAWN` (HTTP
    409)."
    PRD §3.3: "A class is created with `status` `ACTIVE`, and the only other value it
    can take is `WITHDRAWN`, reached when a `PlatformAdmin` withdraws the class from
    sale."

    Design: Corner/validations/withdrawn_rate_class_blocks_both_new_spots_and_acceptance
    """
    built = setup_issue_order(
        call_sign="WWDR-TV",
        market_code="DMA-128",
        station_overrides={"licensee_name": "Withdrawn Rate Media", "daily_political_seconds_cap": 300},
        spots=hourly_spots(1),
        submit=True,
    )
    order, rate_class, spot = built["order"], built["rate_class"], built["spots"][0]

    withdrawn = withdraw_rate_class(rate_class["id"])
    assert withdrawn["status"] == "WITHDRAWN"

    validate_error(
        api.decide_order(order["id"], ACCEPT, OFFICER_BETA),
        ApiErrorId.ERR_RATE_CLASS_WITHDRAWN,
    )

    assert read_order(order["id"])["status"] == "SUBMITTED"
    kept = validate_success(api.get_spot(spot["id"], ADMIN))
    assert kept["charged_rate_cents"] == 100000, "an existing charge survives withdrawal"


def test_order_naming_another_stations_rate_class_is_refused(api):
    """PRD §2.7: "Beyond existence, the platform enforces **single-station scoping** on
    order creation: the referenced rate class, the referenced advertiser and the
    referenced election must every one of them belong to the same station named in the
    request body's `station_id`. Any divergence is rejected with
    `ERR_RATE_CLASS_STATION_MISMATCH` (HTTP 422)."

    Design: Corner/validations/order_creation_rejected_when_the_rate_class_belongs_to_another_station
    """
    set_clock("2026-08-05T09:00:00Z")
    station_a = create_station(
        call_sign="WSTA-TV", licensee_name="Station A Licensee", market_code="DMA-129"
    )
    station_b = create_station(
        call_sign="WSTB-TV", licensee_name="Station B Licensee", market_code="DMA-130"
    )
    class_b = create_rate_class(station_b["id"], class_code="RC-EN-B")
    advertiser = classify_issue_advertiser(station_a["id"], legal_name="Empire Growth Fund")

    validate_error(
        api.create_order(
            create_order_payload(station_a["id"], advertiser["id"], class_b["id"]),
            make_advertiser_agent_headers(advertiser["id"]),
        ),
        ApiErrorId.ERR_RATE_CLASS_STATION_MISMATCH,
    )

    for station in (station_a, station_b):
        _rows, meta = validate_paginated(
            api.list_orders(ADMIN, params={"station_id": station["id"]})
        )
        assert meta["total_count"] == 0, "no order row survives the scoping failure"


def test_payment_due_at_is_immediate_on_prepay_and_thirty_days_out_on_net_30(api):
    """PRD §3.5: "The order's `payment_due_at` is computed: on `PREPAY` terms it is the
    `accepted_at` instant itself, so the money is due immediately; on `NET_30` terms it
    is 30 days after `accepted_at`."
    PRD §3.5: "It stamps `accepted_at` with the logical clock and `accepted_by_user_id`
    with the acting `X-User-ID`. It advances the settlement dimension `UNBILLED →
    INVOICED`."

    Design: Corner/calculations/payment_due_at_is_acceptance_instant_for_prepay_and_thirty_days_later_for_net30
    """
    built = _station_with_both_buyers("WTRM2-TV", "DMA-118", "Terms Broadcasting LLC")

    prepay = validate_success(api.decide_order(built["issue_order"]["id"], ACCEPT, OFFICER_BETA))
    assert prepay["accepted_at"] == "2026-08-05T09:00:00.000Z"
    assert prepay["payment_due_at"] == "2026-08-05T09:00:00.000Z"
    assert prepay["payment_status"] == "INVOICED"
    assert prepay["accepted_by_user_id"] == "officer-beta"

    net_30 = validate_success(api.decide_order(built["order"]["id"], ACCEPT, OFFICER_BETA))
    assert net_30["payment_due_at"] == "2026-09-04T09:00:00.000Z"
    assert net_30["payment_status"] == "INVOICED"


def test_acceptance_cascade_is_visible_immediately_in_the_same_response_and_in_reads(api):
    """PRD §3.5: "When the advertiser's `entitled_to_luc` flag is true and the order
    names a non-null `election_id`, it computes and records a lowest-unit-charge
    determination of variant `PROVISIONAL` for the pair of that election and that rate
    class — superseding whatever prior active `PROVISIONAL` determination existed for
    the same pair — and then applies that figure as a cap."
    PRD §3.7: "If the candidate set comes out empty, the determination falls back to the
    rate card. Its `luc_cents` becomes the card unit rate for the class —
    `posted_rate_cents` multiplied by that class's daypart multiplier, rounded half up
    to whole cents — its `basis` reads `POSTED_RATE_FALLBACK`, its `basis_spot_id` is
    null, and its `qualifying_spot_count` is zero."
    PRD §3.9: "The entry also captures `disclosure_snapshot`, a copy of the order's
    `sponsorship_disclosure_text` as it read at `event_occurred_at`, so that the file
    preserves what was actually announced rather than what the order says today."

    Design: Corner/consistency_model/acceptance_cascade_is_visible_immediately_in_the_same_response_and_in_reads
    """
    built = setup_candidate_order(
        call_sign="WIMM-TV",
        market_code="DMA-146",
        station_overrides={
            "licensee_name": "Immediate Media LLC",
            "political_file_posting_deadline_hours": 24,
            "daily_political_seconds_cap": 300,
        },
        spots=hourly_spots(1),
        submit=True,
    )
    station, election = built["station"], built["election"]
    rate_class, spot = built["rate_class"], built["spots"][0]

    accepted = validate_success(api.decide_order(built["order"]["id"], ACCEPT, OFFICER_BETA))
    assert accepted["payment_status"] == "INVOICED"
    assert accepted["accepted_at"] == "2026-08-05T09:00:00.000Z"
    assert accepted["payment_due_at"] == "2026-09-04T09:00:00.000Z"

    entries = list_file_entries(station_id=station["id"])
    assert len(entries) == 1
    entry = entries[0]
    assert entry["event_type"] == "ORDER_ACCEPTED"
    assert entry["posting_status"] == "PENDING"
    assert entry["due_at"] == "2026-08-06T09:00:00.000Z"
    assert entry["disclosure_snapshot"] == (
        "PAID FOR BY Rivera For Senate; AUTHORIZED BY Rivera For Senate"
    )

    determinations, _meta = validate_paginated(
        api.list_luc_determinations(
            ADMIN,
            params={
                "election_id": election["id"],
                "rate_class_id": rate_class["id"],
                "variant": "PROVISIONAL",
            },
        )
    )
    assert len(determinations) == 1
    assert determinations[0]["luc_cents"] == 100000
    assert determinations[0]["basis"] == "POSTED_RATE_FALLBACK"
    assert determinations[0]["variant"] == "PROVISIONAL"

    priced_spot = validate_success(api.get_spot(spot["id"], ADMIN))
    assert priced_spot["charged_rate_cents"] == 100000
    assert priced_spot["luc_capped"] is False, "the cap does not strictly lower the charge"

    assert read_station(station["id"])["pending_file_entry_count"] == 1
