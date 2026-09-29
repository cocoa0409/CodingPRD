"""Frozen figures: the challenge deposit, the cure deduction and the quoted floor.

The challenge deposit is one percent of the reported value clamped at both ends.
The cure deduction counts only what was actually spent curing, and only on items
that were cured. And a preference offer's quoted minimum is derived and readable
on the very next call, with no settling step in between.
"""

from test_helpers import factories as f, fixtures as fx
from test_helpers import get_success_data, validate_paginated, validate_success
from test_helpers.test_users import make_agency_representative_headers


def _reported_appraisal_open_to_challenge(api, appraised_value_cents, method):
    """A reported valuation whose noticed neighbour is eligible to challenge it.

    The neighbouring district was served the statutory notice on the declaration
    covering this parcel, which is what gives it standing, and the clock never
    leaves the default instant, so the filing is inside the 30-day window.
    """
    ctx = {}
    ctx["agency"] = fx.make_agency(api)
    ctx["challenger"] = fx.make_transit_agency(api)
    ctx["parcel"] = fx.make_parcel(api, ctx["agency"]["id"], book_value_cents=70000000)
    ctx["appraiser"] = fx.make_appraiser(api)
    ctx["appraisal"] = fx.make_reported_appraisal(
        api,
        ctx["parcel"]["id"],
        ctx["appraiser"]["id"],
        appraised_value_cents=appraised_value_cents,
        method=method,
    )
    ctx["declaration"] = fx.make_adopted_declaration(api, ctx["parcel"]["id"])
    ctx["notices"] = fx.issue_notices(
        api, ctx["declaration"]["id"], [ctx["challenger"]["id"]], 60
    )
    return ctx


def _file_the_challenge(api, ctx, asserted_value_cents, deposit_paid_cents, grounds):
    """File the challenge as the noticed neighbour, with the deposit tendered."""
    return api.file_challenge(
        ctx["appraisal"]["id"],
        f.challenge_payload(
            asserted_value_cents, deposit_paid_cents, grounds=grounds
        ),
        make_agency_representative_headers(ctx["challenger"]["id"]),
    )


def test_01_the_challenge_deposit_is_one_percent_when_neither_clamp_bites(api):
    """At a reported value of 100,000,000 the raw one percent stands unclamped.

    "The requirement is computed as the appraised value multiplied by one
    hundredth, rounded half up to a whole cent, and then clamped: if that raw
    figure is below 100,000 cents — one thousand dollars — the requirement is
    100,000 cents, and if it is above 2,500,000 cents — twenty-five thousand
    dollars — the requirement is 2,500,000 cents."

    Design: Corner/calculations/challenge_deposit_requirement_uses_one_percent_of_appraised_value
    """
    ctx = _reported_appraisal_open_to_challenge(api, 100000000, "SALES_COMPARISON")

    response = _file_the_challenge(
        api,
        ctx,
        95000000,
        1000000,
        "Two of the four comparables are outside the industrial submarket",
    )
    challenge = validate_success(response, 201)

    assert challenge["required_deposit_cents"] == 1000000, (
        "one hundredth of 100,000,000 is 1,000,000, between the floor of 100,000 "
        f"and the ceiling of 2,500,000, got {challenge['required_deposit_cents']}"
    )
    assert challenge["deposit_paid_cents"] == 1000000, (
        f"which the tender matches exactly, got {challenge['deposit_paid_cents']}"
    )
    assert challenge["status"] == "SUBMITTED", (
        f"so the challenge is filed, got {challenge['status']!r}"
    )
    assert challenge["deposit_refunded_cents"] == 0, (
        f"with nothing yet refunded, got {challenge['deposit_refunded_cents']}"
    )
    assert challenge["deposit_forfeited_cents"] == 0, (
        f"and nothing forfeited, got {challenge['deposit_forfeited_cents']}"
    )
    assert challenge["revised_value_cents"] is None, (
        f"and no revision recorded, got {challenge['revised_value_cents']!r}"
    )

    appraisal = get_success_data(
        api.get_appraisal(ctx["appraisal"]["id"], fx.OFFICER_HEADERS)
    )
    assert appraisal["status"] == "CHALLENGED", (
        f"the report is under challenge, got {appraisal['status']!r}"
    )
    assert appraisal["challenge_count"] == 1, (
        f"for the first time, got {appraisal['challenge_count']}"
    )
    assert appraisal["appraised_value_cents"] == 100000000, (
        "and filing a challenge does not move the value, got "
        f"{appraisal['appraised_value_cents']}"
    )


def test_02_the_challenge_deposit_clamps_down_to_the_statutory_ceiling(api):
    """At 300,000,000 the raw one percent exceeds the ceiling and is capped.

    "The resulting `required_deposit_cents` is frozen on the challenge at filing
    time and never recomputed afterwards, even if the appraised value later
    changes. A `deposit_paid_cents` at or above `required_deposit_cents` is
    sufficient; one cent short is `ERR_CHALLENGE_DEPOSIT_INSUFFICIENT` (HTTP 422)."

    Design: Corner/calculations/challenge_deposit_requirement_clamps_to_max_ceiling
    """
    ctx = _reported_appraisal_open_to_challenge(api, 300000000, "INCOME")

    response = _file_the_challenge(
        api,
        ctx,
        280000000,
        2500000,
        "The capitalization rate understates industrial vacancy risk",
    )
    challenge = validate_success(response, 201)

    assert challenge["required_deposit_cents"] == 2500000, (
        "one hundredth of 300,000,000 is 3,000,000, which clamps down to the "
        f"ceiling of 2,500,000, got {challenge['required_deposit_cents']}"
    )
    assert challenge["deposit_paid_cents"] == 2500000, (
        "and a tender at the clamped requirement is sufficient, got "
        f"{challenge['deposit_paid_cents']}"
    )
    assert challenge["asserted_value_cents"] == 280000000, (
        "the asserted value is 20,000,000 clear of the 15,000,000 materiality "
        f"threshold, got {challenge['asserted_value_cents']}"
    )
    assert challenge["status"] == "SUBMITTED", (
        f"so the challenge stands, got {challenge['status']!r}"
    )

    appraisal = get_success_data(
        api.get_appraisal(ctx["appraisal"]["id"], fx.OFFICER_HEADERS)
    )
    assert appraisal["status"] == "CHALLENGED", (
        f"and the report is under challenge, got {appraisal['status']!r}"
    )
    assert appraisal["challenge_count"] == 1, (
        f"once, got {appraisal['challenge_count']}"
    )


def test_03_only_cured_items_deduct_and_only_at_their_actual_cost(api):
    """Three resolved defects sit on the parcel and exactly one moves the price.

    "Next compute the cure deduction: the sum of `actual_cure_cost_cents` over the
    title curative items on the parcel whose `status` is `CURED`, with items still
    `OPEN`, waived with an endorsement, or reserved as an easement contributing
    zero."

    Design: Corner/calculations/minimum_price_ignores_waived_and_easement_title_items_in_cure_deduction
    """
    agency = fx.make_agency(api)
    parcel = fx.make_parcel(api, agency["id"], book_value_cents=70000000)

    lien = fx.open_title_item(
        api,
        parcel["id"],
        item_type="LIEN",
        description="Recorded mechanics lien from 2019 sidewalk work",
        cure_cost_estimate_cents=400000,
    )
    encroachment = fx.open_title_item(
        api,
        parcel["id"],
        item_type="ENCROACHMENT",
        description="Neighboring loading dock encroaches 3 feet",
        cure_cost_estimate_cents=9000000,
    )
    easement = fx.open_title_item(
        api,
        parcel["id"],
        item_type="MISSING_ACCESS_EASEMENT",
        description="No recorded access easement for the rear storm line",
        cure_cost_estimate_cents=5000000,
    )
    cured = fx.cure_title_item(api, lien["id"], 250000)
    waived = fx.waive_title_item(api, encroachment["id"])
    reserved = fx.reserve_title_item_as_easement(
        api,
        easement["id"],
        easement_purpose="Storm drain access reserved to the City",
        easement_area_sqft=1800.0,
    )

    assert cured["actual_cure_cost_cents"] == 250000, (
        f"the cured lien records what was actually spent, got {cured['actual_cure_cost_cents']}"
    )
    assert cured["cure_cost_estimate_cents"] == 400000, (
        "while its original estimate is left standing, got "
        f"{cured['cure_cost_estimate_cents']}"
    )
    assert waived["actual_cure_cost_cents"] == 0, (
        f"a waived defect cost nothing to cure, got {waived['actual_cure_cost_cents']}"
    )
    assert reserved["actual_cure_cost_cents"] == 0, (
        f"and neither did a reserved easement, got {reserved['actual_cure_cost_cents']}"
    )

    appraiser = fx.make_appraiser(api)
    fx.make_accepted_appraisal(
        api, parcel["id"], appraiser["id"], appraised_value_cents=100000000
    )
    loaded = get_success_data(api.get_parcel(parcel["id"], fx.OFFICER_HEADERS))
    assert loaded["open_title_item_count"] == 0, (
        f"every defect has left OPEN, got {loaded['open_title_item_count']}"
    )
    assert loaded["disposition_ready"] is True, (
        f"so the parcel is disposition-ready, got {loaded['disposition_ready']!r}"
    )

    ctx = fx.build_authorized_declaration(
        api, {"agency": agency, "parcel": parcel, "appraiser": appraiser}
    )
    offering = fx.make_offering(api, ctx["declaration"]["id"])

    assert offering["minimum_price_cents"] == 99750000, (
        "100,000,000 with no write-down less the single 250,000 actual cure is "
        f"99,750,000, got {offering['minimum_price_cents']}"
    )
    assert offering["minimum_price_variant"] == "MARKET_FLOOR", (
        f"on the competitive-sale variant, got {offering['minimum_price_variant']!r}"
    )
    assert offering["required_deposit_cents"] == 5000000, (
        "five hundredths of 99,750,000 is 4,987,500, which is raised to the floor "
        f"of 5,000,000, got {offering['required_deposit_cents']}"
    )


def test_04_serving_notice_reports_the_declaration_and_its_notices_at_once(api):
    """The write response carries the whole round; no settling call is needed.

    "In parallel the declaration records `notice_issued_at` from the clock,
    `notice_response_window_days` from the effective window, and
    `notice_response_deadline_at` computed as `notice_issued_at` plus
    `notice_response_window_days` days; its `version` rises by 1."

    Design: Corner/consistency_model/issue_notices_response_reflects_declaration_counters_immediately
    """
    custodian = fx.make_agency(api)
    parcel = fx.make_parcel(api, custodian["id"], apn="APN-2693-121")
    declaration = fx.make_adopted_declaration(
        api, parcel["id"], resolution_number="RES-2026-221"
    )
    recipients = [
        fx.make_preference_agency(api)["id"],
        fx.make_transit_agency(api)["id"],
        fx.make_agency(
            api,
            name="Riverbend Unified School District",
            agency_type="SCHOOL_DISTRICT",
            contact_email="facilities@riverbendusd.gov",
        )["id"],
    ]

    response = api.issue_notices(
        declaration["id"],
        f.issue_notices_payload(recipients, 75),
        fx.OFFICER_HEADERS,
    )
    served = validate_success(response, 200)

    assert served["status"] == "NOTICED", (
        f"the write response already reports the new status, got {served['status']!r}"
    )
    assert served["notice_issued_at"] == "2026-08-01T00:00:00.000Z", (
        f"stamped from the clock, got {served['notice_issued_at']!r}"
    )
    assert served["notice_response_window_days"] == 75, (
        f"with the effective window recorded, got {served['notice_response_window_days']}"
    )
    assert served["notice_response_deadline_at"] == "2026-10-15T00:00:00.000Z", (
        "and 75 days after 2026-08-01 is 2026-10-15, got "
        f"{served['notice_response_deadline_at']!r}"
    )
    assert served["version"] == declaration["version"] + 1, (
        f"the declaration's version rises by one, got {served['version']}"
    )

    rows, meta = validate_paginated(
        api.list_notices(
            fx.OFFICER_HEADERS, {"declaration_id": declaration["id"], "limit": 100}
        )
    )
    assert meta["total_count"] == 3, (
        "the very next read already returns one notice per recipient, got "
        f"{meta['total_count']}"
    )
    assert sorted(row["recipient_agency_id"] for row in rows) == sorted(recipients), (
        "one for each agency named in the round, and no others"
    )
    for row in rows:
        assert row["notice_round"] == 1, (
            f"each belongs to the first round, got {row['notice_round']}"
        )
        assert row["status"] == "ISSUED", (
            f"each is outstanding, got {row['status']!r}"
        )
        assert row["responded_at"] is None, (
            f"none has been answered, got {row['responded_at']!r}"
        )
        assert row["response_type"] is None, (
            f"so no response type is recorded, got {row['response_type']!r}"
        )
        assert row["response_window_days"] == 75, (
            "each carries its own copy of the window, got "
            f"{row['response_window_days']}"
        )
        assert row["response_deadline_at"] == "2026-10-15T00:00:00.000Z", (
            "and its own deadline computed from the same instant, got "
            f"{row['response_deadline_at']!r}"
        )

    reread = get_success_data(api.get_declaration(declaration["id"], fx.OFFICER_HEADERS))
    assert reread["notice_response_deadline_at"] == served["notice_response_deadline_at"], (
        "a re-read of the declaration agrees with the write response: "
        f"{reread['notice_response_deadline_at']!r} against "
        f"{served['notice_response_deadline_at']!r}"
    )
    assert reread["preference_offer_count"] == 0, (
        "and serving notice alone opens no negotiation, got "
        f"{reread['preference_offer_count']}"
    )
    assert reread["unresolved_preference_count"] == 0, (
        f"so nothing is unresolved yet, got {reread['unresolved_preference_count']}"
    )


def test_05_expressing_interest_makes_the_new_offer_readable_immediately(api):
    """One response answers the notice and opens a fully-derived negotiation.

    "It starts in `negotiation_status` `OPEN` and `good_faith_status`
    `UNREVIEWED`, with `negotiation_opened_at` stamped from the clock and
    `negotiation_deadline_at` computed as that instant plus 90 days." "Finally the
    parent declaration's `preference_offer_count` rises by 1 and its
    `unresolved_preference_count` is recomputed."

    Design: Corner/consistency_model/express_interest_response_and_preference_offer_visible_in_same_sequence
    """
    ctx = fx.build_valued_parcel(api, appraised_value_cents=100000000)
    housing = fx.make_preference_agency(api)
    declaration = fx.make_adopted_declaration(
        api, ctx["parcel"]["id"], resolution_number="RES-2026-222"
    )
    notices = fx.issue_notices(api, declaration["id"], [housing["id"]], 60)
    notice = notices[0]

    response = api.respond_to_notice(
        notice["id"],
        f.express_interest_payload(
            "AFFORDABLE_HOUSING",
            intended_use="Sixty units of deed-restricted family housing",
        ),
        make_agency_representative_headers(housing["id"]),
    )
    answered = validate_success(response, 200)

    assert answered["status"] == "INTEREST_EXPRESSED", (
        f"the notice is answered in the affirmative, got {answered['status']!r}"
    )
    assert answered["response_type"] == "EXPRESS_INTEREST", (
        f"with the response type recorded, got {answered['response_type']!r}"
    )
    assert answered["responded_at"] == "2026-08-01T00:00:00.000Z", (
        f"stamped from the clock, got {answered['responded_at']!r}"
    )
    assert answered["claimed_preference_category"] == "AFFORDABLE_HOUSING", (
        "and the claim matching the agency's own category stored, got "
        f"{answered['claimed_preference_category']!r}"
    )

    rows, meta = validate_paginated(
        api.list_preference_offers(
            fx.OFFICER_HEADERS, {"declaration_id": declaration["id"], "limit": 100}
        )
    )
    assert meta["total_count"] == 1, (
        "the very next call already sees the negotiation the response opened, got "
        f"{meta['total_count']}"
    )
    offer = rows[0]
    assert offer["offeror_agency_id"] == housing["id"], (
        f"it belongs to the responding agency, got {offer['offeror_agency_id']!r}"
    )
    assert offer["notice_id"] == notice["id"], (
        f"and traces back to the notice that opened it, got {offer['notice_id']!r}"
    )
    assert offer["preference_category"] == "AFFORDABLE_HOUSING", (
        "carrying the claimed category forward, got "
        f"{offer['preference_category']!r}"
    )
    assert offer["negotiation_status"] == "OPEN", (
        f"the bargaining dimension opens, got {offer['negotiation_status']!r}"
    )
    assert offer["good_faith_status"] == "UNREVIEWED", (
        f"the conduct dimension is ungraded, got {offer['good_faith_status']!r}"
    )
    assert offer["negotiation_opened_at"] == "2026-08-01T00:00:00.000Z", (
        f"the opening instant is the clock, got {offer['negotiation_opened_at']!r}"
    )
    assert offer["negotiation_deadline_at"] == "2026-10-30T00:00:00.000Z", (
        "and 90 days after 2026-08-01 is 2026-10-30, got "
        f"{offer['negotiation_deadline_at']!r}"
    )
    assert offer["ah_minimum_price_cents"] == 65000000, (
        "the affordable-housing variant writes 100,000,000 down by thirty-five "
        f"hundredths, got {offer['ah_minimum_price_cents']}"
    )

    reread = get_success_data(api.get_declaration(declaration["id"], fx.OFFICER_HEADERS))
    assert reread["preference_offer_count"] == 1, (
        "the parent declaration already counts the offer, got "
        f"{reread['preference_offer_count']}"
    )
    assert reread["unresolved_preference_count"] == 1, (
        "and counts it as unresolved, got "
        f"{reread['unresolved_preference_count']}"
    )
