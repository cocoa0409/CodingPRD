"""Cross-cutting layers: optimistic concurrency, re-derivation and selectors.

Each test translates one instance of the corner design index's
``cross_cutting_complexity_layers`` section. The three version-pinned writes of
PRD §2.6 are exercised against the side effects that move the parent row.
"""

from test_helpers import (
    ApiClient,
    ApiErrorId,
    DISCLOSURE_OFFICER,
    DISCLOSURE_OFFICER_USER_ID,
    IR_ADMIN,
    assertions,
    factories,
    fixtures,
    make_investor_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

DEFAULT_CLOCK = "2026-08-01T00:00:00Z"


def test_estimate_write_refuses_a_stale_contact_version(api: ApiClient):
    """PRD §2.6: "Filing a consensus estimate requires `expected_contact_version`, carrying the client's last observed `version` of the analyst `Contact` named by `contact_id`."
    PRD §2.6: "If it does not equal that contact's current `version`, the submission is rejected with `ERR_STALE_CONTACT_VERSION` (HTTP 412)."
    PRD §3.3: "A successful grant increments the contact's `version` by 1 and touches nothing else."
    PRD §3.7: "Filing also increments the analyst contact's `version` by 1 — which is why a client that files twice in a row must re-read the contact between filings to obtain a fresh `expected_contact_version`."

    Design: Corner/cross_cutting_complexity_layers/estimate_write_refuses_a_stale_contact_version
    """
    fixtures.set_clock(api, DEFAULT_CLOCK)
    company = fixtures.create_company(
        api, ticker="OCC", legal_name="Contact Version Corp", shares_outstanding=1000000
    )
    analyst = fixtures.create_analyst(
        api,
        company["id"],
        display_name="Stale Version Analyst",
        email="occ@bank.test",
        nda_on_file=True,
        coverage_status="INITIATED",
    )
    analyst_id = analyst["id"]
    investor_headers = make_investor_headers(analyst_id)
    version_before_grant = analyst["version"]
    assert version_before_grant == 1

    # The grant advances the analyst row, so the version read a moment ago is stale.
    fixtures.grant_model_access(api, analyst_id, DISCLOSURE_OFFICER)
    granted = fixtures.read_contact(api, analyst_id)
    assert granted["model_access_status"] == "GRANTED"
    assert granted["version"] == version_before_grant + 1

    body = factories.estimate_payload(
        analyst_id,
        version_before_grant,
        metric="REVENUE",
        period_label="FY2026",
        value=1500.0000,
    )
    refused = api.create_estimate(body, investor_headers)
    validate_error(refused, ApiErrorId.STALE_CONTACT_VERSION.value, 412)

    rows, meta = validate_paginated(api.list_contact_estimates(analyst_id, headers=IR_ADMIN))
    assert rows == []
    assert meta["total_count"] == 0
    assert fixtures.read_contact(api, analyst_id)["version"] == granted["version"], (
        "a refused filing must not move the contact row"
    )

    # The identical body succeeds once the client re-reads the contact.
    body["expected_contact_version"] = granted["version"]
    accepted = validate_success(api.create_estimate(body, investor_headers), 201)
    assert accepted["status"] == "ACCEPTED"
    assert accepted["contact_id"] == analyst_id
    assertions.assert_ts_equals(accepted["submitted_at"], DEFAULT_CLOCK, "submitted_at")

    after = fixtures.read_contact(api, analyst_id)
    assert after["version"] == granted["version"] + 1, (
        "the accepted filing bumps the contact again, so the just-used version is now stale too"
    )


def test_position_write_refuses_a_stale_company_version(api: ApiClient):
    """PRD §2.6: "Recording a new share position requires `expected_company_version`, carrying the client's last observed `version` of the issuer the holder sits under."
    PRD §2.6: "If it does not equal that issuer's current `version`, the write is rejected with `ERR_STALE_COMPANY_VERSION` (HTTP 412)."
    PRD §3.3: "The second, caused by the first, re-derives the issuer's `disclosure_posture` per §2.7, stamps `posture_recomputed_at`, and increments the issuer's `version` by 1."
    PRD §2.7: "The second source is activist pressure, read from the `threat_level` of every contact of that issuer whose `activist_flag` is true; the threat level of a contact that is not flagged as an activist is ignored entirely."
    PRD §3.2: "A position write that survives every check re-derives `ownership_pct` and `target_tier`, then re-derives the issuer's `disclosure_posture` and stamps `posture_recomputed_at`, incrementing both the contact's `version` and the issuer's `version` by 1."

    Design: Corner/cross_cutting_complexity_layers/position_write_refuses_a_stale_company_version
    """
    fixtures.set_clock(api, DEFAULT_CLOCK)
    company = fixtures.create_company(
        api, ticker="OCP", legal_name="Company Version Corp", shares_outstanding=1000000
    )
    holder = fixtures.create_holder(
        api, company["id"], 10000, display_name="Position Holder", email="ocp1@funds.test"
    )
    watchlisted = fixtures.create_holder(
        api, company["id"], 5000, display_name="Watchlist Holder", email="ocp2@funds.test"
    )
    observed_company_version = fixtures.company_version(api, company["id"])

    # A servicing call on an unrelated, non-activist contact still bumps the issuer.
    fixtures.set_threat_level(api, watchlisted["id"], "WATCH", IR_ADMIN)
    moved_on = fixtures.read_company(api, company["id"])
    assert moved_on["disclosure_posture"] == "OPEN"
    assert moved_on["version"] > observed_company_version

    refused = api.update_position(
        holder["id"], factories.position_payload(30000, observed_company_version), IR_ADMIN
    )
    validate_error(refused, ApiErrorId.STALE_COMPANY_VERSION.value, 412)

    untouched = fixtures.read_contact(api, holder["id"])
    assert untouched["shares_held"] == 10000
    assert untouched["ownership_pct"] == assertions.approx_4dp(1.0000)
    assert untouched["target_tier"] == "TIER_2"
    assert untouched["version"] == holder["version"]

    accepted = validate_success(
        api.update_position(
            holder["id"],
            factories.position_payload(30000, moved_on["version"]),
            IR_ADMIN,
        )
    )
    assert accepted["shares_held"] == 30000
    assert accepted["ownership_pct"] == assertions.approx_4dp(3.0000)
    assert accepted["target_tier"] == "TIER_2"
    assert accepted["version"] == holder["version"] + 1
    assert fixtures.read_company(api, company["id"])["version"] == moved_on["version"] + 1


def test_review_refuses_a_stale_inquiry_version(api: ApiClient):
    """PRD §2.6: "Deciding a response-draft review requires `expected_inquiry_version`, carrying the client's last observed `version` of the draft's parent `InquiryTicket`."
    PRD §2.6: "If it does not equal that inquiry's current `version`, the review is rejected with `ERR_STALE_INQUIRY_VERSION` (HTTP 412)."
    PRD §3.6: "Both branches stamp the acting user as `reviewer_user_id` and increment both the draft's `version` and the parent inquiry's `version` by 1."
    PRD §3.6: "A successful submission increments the draft's `version` by 1 and drives the parent inquiry `DRAFTING` → `AWAITING_APPROVAL`, incrementing the inquiry's `version` by 1."
    PRD §3.6: "The parent inquiry remains in `DRAFTING` throughout — revision touches only the draft's own `version`."

    Design: Corner/cross_cutting_complexity_layers/review_refuses_a_stale_inquiry_version
    """
    fixtures.set_clock(api, DEFAULT_CLOCK)
    company = fixtures.create_company(
        api, ticker="OCI", legal_name="Inquiry Version Corp", shares_outstanding=1000000
    )
    holder = fixtures.create_holder(
        api, company["id"], 20000, display_name="Inquiry Version Holder", email="oci@funds.test"
    )
    inquiry = fixtures.create_routed_inquiry(
        api, company["id"], holder["id"], subject="Please confirm the record date."
    )
    inquiry_id = inquiry["id"]
    draft = fixtures.create_draft(api, inquiry_id)
    draft_id = draft["id"]
    fixtures.submit_for_review(api, draft_id)

    version_at_first_review = fixtures.inquiry_version(api, inquiry_id)
    first = validate_success(
        api.review_draft(
            draft_id,
            factories.review_payload(
                "REQUEST_CHANGES", version_at_first_review, "Tighten the second paragraph."
            ),
            DISCLOSURE_OFFICER,
        )
    )
    assert first["status"] == "CHANGES_REQUESTED"
    assert fixtures.read_inquiry(api, inquiry_id)["status"] == "DRAFTING"

    # Back round the cycle: the revise leaves the inquiry alone, the resubmit bumps it.
    fixtures.revise_draft(api, draft_id, body_text="A tighter second paragraph.")
    fixtures.submit_for_review(api, draft_id)

    refused = api.review_draft(
        draft_id,
        factories.review_payload("APPROVE", version_at_first_review, "Cleared."),
        DISCLOSURE_OFFICER,
    )
    validate_error(refused, ApiErrorId.STALE_INQUIRY_VERSION.value, 412)
    still_in_review = fixtures.read_draft(api, draft_id)
    assert still_in_review["status"] == "IN_REVIEW"
    assert fixtures.read_inquiry(api, inquiry_id)["status"] == "AWAITING_APPROVAL"

    version_now = fixtures.inquiry_version(api, inquiry_id)
    assert version_now == version_at_first_review + 2, (
        "the first decision and the resubmission each advanced the inquiry once"
    )

    approved = validate_success(
        api.review_draft(
            draft_id,
            factories.review_payload("APPROVE", version_now, "Cleared."),
            DISCLOSURE_OFFICER,
        )
    )
    assert approved["status"] == "APPROVED"
    assert approved["reviewer_user_id"] == DISCLOSURE_OFFICER_USER_ID
    assert fixtures.inquiry_version(api, inquiry_id) == version_now + 1


def test_posture_is_fully_re_derived_not_latched(api: ApiClient):
    """PRD §2.7: "The second source is activist pressure, read from the `threat_level` of every contact of that issuer whose `activist_flag` is true; the threat level of a contact that is not flagged as an activist is ignored entirely."
    PRD §2.7: "If the issuer is inside its blackout window, or if any flagged activist of that issuer carries threat level `CRITICAL`, the posture is `BLACKOUT`."
    PRD §2.7: "Otherwise, if any flagged activist carries threat level `ELEVATED`, the posture is `RESTRICTED`."
    PRD §2.7: "Otherwise the posture is `OPEN`."
    PRD §2.7: "Whenever the posture is re-derived, `posture_recomputed_at` is stamped with the logical clock's current instant."
    PRD §3.3: "The second, caused by the first, re-derives the issuer's `disclosure_posture` per §2.7, stamps `posture_recomputed_at`, and increments the issuer's `version` by 1."

    Design: Corner/cross_cutting_complexity_layers/posture_is_fully_re_derived_not_latched
    """
    fixtures.set_clock(api, DEFAULT_CLOCK)
    company = fixtures.create_company(
        api, ticker="DFR", legal_name="Derived Posture Corp", shares_outstanding=1000000
    )
    company_id = company["id"]
    activist = fixtures.create_holder(
        api,
        company_id,
        20000,
        display_name="Activist Holder",
        email="dfr1@funds.test",
        activist_flag=True,
    )
    ordinary = fixtures.create_holder(
        api, company_id, 20000, display_name="Ordinary Holder", email="dfr2@funds.test"
    )
    assert fixtures.read_company(api, company_id)["disclosure_posture"] == "OPEN"

    # The posture follows the flagged activist's current level in both directions.
    for level, expected_posture in (
        ("CRITICAL", "BLACKOUT"),
        ("ELEVATED", "RESTRICTED"),
        ("WATCH", "OPEN"),
    ):
        fixtures.set_threat_level(api, activist["id"], level, DISCLOSURE_OFFICER)
        issuer = fixtures.read_company(api, company_id)
        assert issuer["disclosure_posture"] == expected_posture, (
            f"threat level {level} must re-derive the posture, not latch the previous one"
        )
        assertions.assert_ts_equals(
            issuer["posture_recomputed_at"], DEFAULT_CLOCK, "posture_recomputed_at"
        )
        assert fixtures.read_contact(api, activist["id"])["threat_level"] == level

    # An unflagged contact at CRITICAL contributes nothing to the derivation.
    fixtures.set_threat_level(api, ordinary["id"], "CRITICAL", DISCLOSURE_OFFICER)
    assert fixtures.read_contact(api, ordinary["id"])["threat_level"] == "CRITICAL"
    assert fixtures.read_contact(api, ordinary["id"])["activist_flag"] is False
    unmoved = fixtures.read_company(api, company_id)
    assert unmoved["disclosure_posture"] == "OPEN"
    assertions.assert_ts_equals(
        unmoved["posture_recomputed_at"], DEFAULT_CLOCK, "posture_recomputed_at"
    )

    # The operator refresh re-derives from the same two sources and agrees.
    refreshed = fixtures.recompute_posture(api, company_id)
    assert refreshed["disclosure_posture"] == "OPEN"


def test_allocation_tie_is_broken_by_the_larger_position(api: ApiClient):
    """PRD §3.8: "The eligible candidates are ranked by `final_priority_score` descending, then — for equal scores — by the requesting contact's `shares_held` descending, then by the request's own creation timestamp ascending, compared at millisecond precision."
    PRD §3.8: "Identifiers are never used as a tiebreaker."
    PRD §3.8: "Add an engagement term equal to the contact's `ownership_pct` multiplied by 4, rounded half up to 2 decimal places and then capped at 20 — the rounding happening before the term is added, and the cap meaning that any holder above five percent of the register contributes exactly 20."
    PRD §3.8: "Remaining capacity is the event's `capacity_slots` minus its current `allocated_count`, and the first that many rows of the ranked eligible list transition `REQUESTED` → `ALLOCATED`."
    PRD §3.8: "Every other eligible row, and every threshold-deferred row, transitions `REQUESTED` → `WAITLISTED`."
    PRD §3.8: "A request that lands on `WAITLISTED` also stores its `final_priority_score` and increments its own `version` by 1, but `allocated_at` stays null — a waitlisted request has never been given a time — and it increases the event's `waitlisted_count` by 1 instead."

    Design: Corner/cross_cutting_complexity_layers/allocation_tie_is_broken_by_the_larger_position
    """
    fixtures.set_clock(api, DEFAULT_CLOCK)
    company = fixtures.create_company(
        api, ticker="SEL", legal_name="Selector Policy Corp", shares_outstanding=1000000
    )
    bigger = fixtures.create_holder(
        api,
        company["id"],
        120000,
        display_name="Bigger Fund",
        email="sel1@funds.test",
        nda_on_file=True,
    )
    smaller = fixtures.create_holder(
        api,
        company["id"],
        100000,
        display_name="Smaller Fund",
        email="sel2@funds.test",
        nda_on_file=True,
    )
    # Both stakes are above five percent, so both engagement terms hit the cap of 20
    # and both contacts sit in TIER_1: the two final scores are identical.
    assert bigger["target_tier"] == "TIER_1"
    assert smaller["target_tier"] == "TIER_1"
    assert bigger["ownership_pct"] == assertions.approx_4dp(12.0000)
    assert smaller["ownership_pct"] == assertions.approx_4dp(10.0000)

    # The smaller holder lodges its bid FIRST, so a creation-order selector would win it.
    event, requests = fixtures.build_open_event_with_requests(
        api,
        company["id"],
        [
            (smaller["id"], "2026-09-01T09:00:00Z", "2026-09-01T09:30:00Z"),
            (bigger["id"], "2026-09-01T10:00:00Z", "2026-09-01T10:30:00Z"),
        ],
        capacity_slots=1,
    )
    smaller_request, bigger_request = requests

    summary = fixtures.allocate_event(api, event["id"])
    assert summary["event_id"] == event["id"]
    assert summary["event_status"] == "LOCKED"
    assert summary["evaluated_count"] == 2
    assert summary["allocated_count"] == 1
    assert summary["waitlisted_count"] == 1
    assert summary["threshold_deferred_count"] == 0

    winner = fixtures.read_meeting_request(api, bigger_request["id"])
    loser = fixtures.read_meeting_request(api, smaller_request["id"])
    assert winner["final_priority_score"] == assertions.approx_2dp(99.60)
    assert loser["final_priority_score"] == assertions.approx_2dp(99.60)
    assert winner["status"] == "ALLOCATED", "the larger position breaks the score tie"
    assert loser["status"] == "WAITLISTED"
    assertions.assert_ts_equals(winner["allocated_at"], DEFAULT_CLOCK, "allocated_at")
    assert winner["promoted_from_waitlist"] is False
    assert loser["allocated_at"] is None

    locked = fixtures.read_event(api, event["id"])
    assert locked["status"] == "LOCKED"
    assert locked["allocated_count"] == 1
    assert locked["waitlisted_count"] == 1
    assert locked["request_ledger_total"] == 2
