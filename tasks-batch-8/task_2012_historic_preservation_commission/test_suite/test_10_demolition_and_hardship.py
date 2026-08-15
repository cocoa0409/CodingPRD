"""Demolition delays: approval cascades, the half-open overlap check, lazy
expiry, postponements, and economic-hardship review (PRD §3.7, §3.9)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    accept_application,
    assert_instant_equal,
    begin_review,
    create_district,
    create_hardship_review_payload,
    create_meeting,
    create_owner,
    create_property,
    decide_by_commissioner,
    get_application,
    get_district,
    get_property,
    get_success_data,
    make_applicant_headers,
    pay_assessed_fee,
    schedule_hearing,
    set_clock,
    setup_approved_demolition,
    submit_application,
    validate_error,
    validate_paginated,
    validate_success,
    verified_item,
    work_item,
)

STAFF = TEST_USERS["staff_headers"]
COMMISSIONER = TEST_USERS["commissioner_headers"]


class TestDemolitionCompletionCensusChain:
    def _setup_completed_demolition(self, api):
        """P1 (CONTRIBUTING) and P2 (NON_CONTRIBUTING) in one LOCAL district;
        P1's DEMOLITION application approved at hearing, fee paid, certificate
        issued and completed."""
        set_clock("2026-08-01T00:00:00Z")
        district = create_district(name="Old Town", significance_tier="LOCAL")
        owner = create_owner()
        p1 = create_property(
            owner["id"], district_id=district["id"],
            contributing_status="CONTRIBUTING", assessed_value_cents=5_000_000,
        )
        p2 = create_property(
            owner["id"], district_id=district["id"],
            contributing_status="NON_CONTRIBUTING", assessed_value_cents=4_000_000,
        )
        submitted = submit_application(
            p1["id"], owner["id"],
            application_type="DEMOLITION", is_visible_from_public_way=True,
            work_items=[work_item("DEMOLITION", "raze structure", 800000)],
        )
        begin_review(submitted["id"])
        accepted = accept_application(
            submitted["id"], [verified_item("DEMOLITION", 800000)], "staff-1"
        )
        meeting = create_meeting()
        hearing = schedule_hearing(accepted["id"], meeting["id"])
        validate_success(api.open_hearing(hearing["id"], COMMISSIONER))
        decide_by_commissioner(accepted["id"], {"outcome": "APPROVE"})

        pay_assessed_fee(accepted["id"], owner["id"])  # 47400 incl. surcharge
        certificate = get_success_data(
            api.create_certificate({"application_id": accepted["id"]}, STAFF), 201
        )
        get_success_data(
            api.verify_conditions(certificate["id"], {"conditions_met_count": 0}, STAFF)
        )
        set_clock("2026-08-20T00:00:00Z")
        completed = validate_success(
            api.complete_certificate(
                certificate["id"], {"commenced_at": "2026-08-20T00:00:00Z"}, STAFF
            )
        )
        return {"district": district, "owner": owner, "p1": p1, "p2": p2,
                "application": accepted, "certificate": completed}

    def test_demolition_completion_demolishes_property(self, api):
        """PRD §3.9: "A successful completion stamps `completed_at` and moves
        the certificate to `COMPLETED`."
        PRD §3.9: "When the underlying application was a demolition, completion
        is also the moment the building leaves the inventory: the property's
        `listing_status` advances from `DEMOLITION_PENDING` to `DEMOLISHED`,
        the district's `contributing_count` drops by one if and only if the
        property was `CONTRIBUTING`, its `total_inventory_count` drops by one,
        and the `preservation_posture` is recomputed per §2.9."

        Design: Difficulty/transitive_cascade/demolition_completion_census_chain
        """
        ctx = self._setup_completed_demolition(api)
        assert ctx["certificate"]["status"] == "COMPLETED"
        assert get_property(ctx["p1"]["id"])["listing_status"] == "DEMOLISHED"
        assert get_property(ctx["p2"]["id"])["listing_status"] == "INVENTORY"

    def test_demolition_completion_updates_district_census(self, api):
        """PRD §3.9: "When the underlying application was a demolition,
        completion is also the moment the building leaves the inventory: the
        property's `listing_status` advances from `DEMOLITION_PENDING` to
        `DEMOLISHED`, the district's `contributing_count` drops by one if and
        only if the property was `CONTRIBUTING`, its `total_inventory_count`
        drops by one, and the `preservation_posture` is recomputed per §2.9."
        PRD §2.9: "The `preservation_posture` is `AT_RISK` exactly when the
        inventory is non-empty and strictly fewer than half of its properties
        are contributing — that is, when `total_inventory_count` is greater
        than zero and twice `contributing_count` is strictly less than
        `total_inventory_count`; otherwise it is `STABLE`, including for an
        empty district."

        Design: Difficulty/transitive_cascade/demolition_completion_census_chain
        """
        ctx = self._setup_completed_demolition(api)
        district = get_district(ctx["district"]["id"])
        # Was 1 contributing of 2 (STABLE); after P1's demolition 0 of 1, and
        # 0 * 2 < 1 makes the posture AT_RISK.
        assert district["contributing_count"] == 0
        assert district["total_inventory_count"] == 1
        assert district["preservation_posture"] == "AT_RISK"


class TestDemolitionDelayHalfOpenOverlap:
    def _setup_two_pending_demolitions(self, api):
        """Two DEMOLITION applications on the same property, both heard in one
        meeting; D1 approved at 2026-08-01 creating delay [2026-08-01,
        2026-10-30), then the clock advances to 2026-10-29 with D2's hearing
        opened."""
        set_clock("2026-08-01T00:00:00Z")
        district = create_district(name="Old Town", significance_tier="LOCAL")
        owner = create_owner()
        prop = create_property(owner["id"], district_id=district["id"],
                               assessed_value_cents=6_000_000)

        d1 = submit_application(
            prop["id"], owner["id"], application_type="DEMOLITION",
            is_visible_from_public_way=True,
            work_items=[work_item("DEMOLITION", "raze main", 500000)],
        )
        begin_review(d1["id"])
        accept_application(d1["id"], [verified_item("DEMOLITION", 500000)], "staff-1")

        d2 = submit_application(
            prop["id"], owner["id"], application_type="DEMOLITION",
            is_visible_from_public_way=True,
            work_items=[work_item("DEMOLITION", "raze garage", 200000)],
        )
        begin_review(d2["id"])
        accept_application(d2["id"], [verified_item("DEMOLITION", 200000)], "staff-1")

        meeting = create_meeting(agenda_capacity=2)
        h1 = schedule_hearing(d1["id"], meeting["id"])
        h2 = schedule_hearing(d2["id"], meeting["id"])

        validate_success(api.open_hearing(h1["id"], COMMISSIONER))
        decide_by_commissioner(d1["id"], {"outcome": "APPROVE"})

        set_clock("2026-10-29T00:00:00Z")  # delay1 still ACTIVE (ends 2026-10-30)
        validate_success(api.open_hearing(h2["id"], COMMISSIONER))
        return {"district": district, "owner": owner, "property": prop,
                "d1": d1, "d2": d2, "meeting": meeting}

    def test_demolition_delay_overlap_rejected(self, api):
        """PRD §3.7: "And before any of this commits, the overlap check runs:
        the new delay window, the half-open interval from `delay_start_at` up
        to but not including its provisional end, must not overlap any other
        `ACTIVE` delay on the same property; because the interval is half-open,
        adjacency — one window ending exactly where another begins — is
        permitted."
        PRD §3.7: "A failing overlap check rejects the entire decision with
        `ERR_DEMOLITION_DELAY_OVERLAP` and no approval is recorded."

        Design: Difficulty/resource_temporal_overlap/demolition_delay_half_open_overlap
        """
        ctx = self._setup_two_pending_demolitions(api)
        # D2's window [2026-10-29, 2027-01-27) properly overlaps D1's
        # [2026-08-01, 2026-10-30).
        response = api.decide_application(ctx["d2"]["id"], {"outcome": "APPROVE"}, COMMISSIONER)
        validate_error(response, ApiErrorId.ERR_DEMOLITION_DELAY_OVERLAP)
        assert get_application(ctx["d2"]["id"])["status"] == "HEARING_OPEN"

    def test_overlap_rejection_records_no_second_delay(self, api):
        """PRD §3.7: "A failing overlap check rejects the entire decision with
        `ERR_DEMOLITION_DELAY_OVERLAP` and no approval is recorded."

        Design: Difficulty/resource_temporal_overlap/demolition_delay_half_open_overlap
        """
        ctx = self._setup_two_pending_demolitions(api)
        validate_error(
            api.decide_application(ctx["d2"]["id"], {"outcome": "APPROVE"}, COMMISSIONER),
            ApiErrorId.ERR_DEMOLITION_DELAY_OVERLAP,
        )
        delays, meta = validate_paginated(
            api.list_demolition_delays(STAFF, params={"property_id": ctx["property"]["id"]})
        )
        assert meta["total_count"] == 1, "no second delay may be persisted"


def test_delay_lazy_expiry_at_provisional_end(api):
    """PRD §3.7: "The delay's `provisional_delay_end` is its `delay_start_at`
    plus the base days plus thirty days for each granted postponement."
    PRD §3.7: "Whenever the logical clock is consulted on the delay — any read
    of it, or any action upon it — and that clock has reached or passed the
    effective end, the delay's status moves from `ACTIVE` to `EXPIRED` as part
    of answering."
    PRD §3.7: "its `base_delay_days` is drawn from the district's significance
    tier — ninety days for `LOCAL`, one hundred eighty days for `LANDMARK`,
    three hundred sixty-five days for `ICONIC` — and its `postponement_count`
    starts at zero."

    Design: Corner/state_machines/delay_lazy_expiry_at_end_boundary
    """
    ctx = setup_approved_demolition(approve_clock="2026-08-01T00:00:00Z")
    delay = ctx["delay"]
    assert delay["status"] == "ACTIVE"
    assert delay["postponement_count"] == 0
    # 2026-08-01 + 90 days = 2026-10-30.
    assert_instant_equal(
        delay["provisional_delay_end"], "2026-10-30T00:00:00Z", "provisional_delay_end"
    )

    set_clock("2026-10-30T00:00:00Z")  # the effective end instant itself
    refreshed = validate_success(api.get_demolition_delay(delay["id"], STAFF))
    assert refreshed["status"] == "EXPIRED"


def test_postponement_extends_delay_and_limit_enforced(api):
    """PRD §3.7: "Staff may postpone an `ACTIVE` delay at most twice — a third
    attempt, when `postponement_count` has already reached two, is rejected
    with `ERR_POSTPONEMENT_LIMIT_REACHED` — and each postponement raises
    `postponement_count` by one and recomputes the provisional end thirty days
    further out."

    Design: Corner/calculations/postponement_extends_delay_and_limit_enforced
    """
    ctx = setup_approved_demolition(approve_clock="2026-08-01T00:00:00Z")
    delay_id = ctx["delay"]["id"]

    first = validate_success(api.postpone_delay(delay_id, STAFF))
    assert first["postponement_count"] == 1

    second = validate_success(api.postpone_delay(delay_id, STAFF))
    assert second["postponement_count"] == 2
    # 2026-08-01 + 90 days + 2 x 30 days = 2026-12-29.
    assert_instant_equal(
        second["provisional_delay_end"], "2026-12-29T00:00:00Z", "provisional_delay_end"
    )

    third = api.postpone_delay(delay_id, STAFF)
    validate_error(third, ApiErrorId.ERR_POSTPONEMENT_LIMIT_REACHED)


def test_hardship_grant_replaces_delay_end(api):
    """PRD §3.7: "The filing window is bounded on both sides: `filed_at` must
    be strictly after the application's `decided_at` and no later than thirty
    days before the delay's `provisional_delay_end` — the cutoff instant itself
    is included."
    PRD §3.7: "A `GRANT` outcome moves the review to `GRANTED` and lifts the
    delay: the linked demolition delay moves from `ACTIVE` to
    `LIFTED_BY_HARDSHIP`, and its `final_delay_end` is set to the hardship's
    `decided_at` plus ten days, replacing the provisional end from that moment
    forward."

    Design: Corner/calculations/hardship_grant_replaces_delay_end
    """
    ctx = setup_approved_demolition(approve_clock="2026-08-01T00:00:00Z")
    delay = ctx["delay"]
    assert_instant_equal(
        delay["provisional_delay_end"], "2026-10-30T00:00:00Z", "provisional_delay_end"
    )

    # Filed strictly after decided_at (2026-08-01) and at or before the
    # 2026-09-30 cutoff.
    set_clock("2026-09-01T00:00:00Z")
    review = validate_success(
        api.create_hardship_review(
            create_hardship_review_payload(ctx["application"]["id"]),
            make_applicant_headers(ctx["owner"]["id"]),
        ),
        201,
    )
    validate_success(api.hear_hardship_review(review["id"], COMMISSIONER))

    set_clock("2026-09-10T00:00:00Z")
    decided = validate_success(
        api.decide_hardship_review(
            review["id"], {"outcome": "GRANT", "findings": "No reasonable return"},
            COMMISSIONER,
        )
    )
    assert decided["status"] == "GRANTED"

    lifted = validate_success(api.get_demolition_delay(delay["id"], STAFF))
    assert lifted["status"] == "LIFTED_BY_HARDSHIP"
    # decided_at 2026-09-10 + 10 days = 2026-09-20.
    assert_instant_equal(lifted["final_delay_end"], "2026-09-20T00:00:00Z", "final_delay_end")
    assert_instant_equal(
        lifted["provisional_delay_end"], "2026-10-30T00:00:00Z",
        "provisional_delay_end remains recorded",
    )


def test_hardship_filed_after_cutoff_lapsed(api):
    """PRD §3.7: "The filing window is bounded on both sides: `filed_at` must
    be strictly after the application's `decided_at` and no later than thirty
    days before the delay's `provisional_delay_end` — the cutoff instant itself
    is included."
    PRD §3.7: "A filing at or before the approval instant, or after the cutoff,
    is rejected with `ERR_HARDSHIP_WINDOW_LAPSED`."

    Design: Corner/validations/hardship_file_after_cutoff_lapsed
    """
    ctx = setup_approved_demolition(approve_clock="2026-08-01T00:00:00Z")
    # Provisional end 2026-10-30; cutoff = 2026-09-30. Filing at 2026-10-01 is
    # past the cutoff.
    set_clock("2026-10-01T00:00:00Z")
    response = api.create_hardship_review(
        create_hardship_review_payload(ctx["application"]["id"]),
        make_applicant_headers(ctx["owner"]["id"]),
    )
    validate_error(response, ApiErrorId.ERR_HARDSHIP_WINDOW_LAPSED)
