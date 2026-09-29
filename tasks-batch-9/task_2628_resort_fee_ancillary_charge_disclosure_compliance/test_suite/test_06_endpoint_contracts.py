"""Endpoint surfaces: a computed read, a conditional action, a link, a table."""
from test_helpers import (
    ApiErrorId,
    CLOCK_START,
    NON_EXISTENT_UUID,
    PUBLISHED_TOTAL_MANDATORY_FEE_CENTS_PER_NIGHT,
    add_booking,
    add_channel,
    add_draft_profile,
    add_inquiry,
    assert_stamped_at_clock,
    create_guest_complaint_payload,
    create_jurisdiction,
    deploy_profile,
    find_line_by_sequence,
    is_valid_uuid,
    make_guest_headers,
    read_booking,
    read_disclosure_summary,
    read_folio_lines,
    read_property,
    setup_confirmed_booking,
    setup_deployed_profile,
    setup_posted_folio,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import ADMIN, AGENT, COMPLIANCE

PARTIAL_DISCLOSURE_MAP = {"RESORT": 6000, "DESTINATION": 5980}
GAP_UNDER_PARTIAL_MAP = 5572
CAPABLE_GDS = {
    "name": "WorldGDS Terminal",
    "channel_type": "GDS",
    "supports_total_price_display": True,
    "supports_itemization": True,
}
CONFIRMATION_ONLY_PROFILE = {
    "first_quote_shows_total": True,
    "itemized_at_first_quote": False,
    "disclosure_placement": "CONFIRMATION_ONLY",
}
# The summary fields that PRD 3.1 also declares as computed fields of the
# Property row itself: "A freshly created property reads with
# `min_channel_disclosure_score` null, `disclosure_posture` `COMPLIANT`,
# `open_disclosure_obligation_count` 0, `published_fee_program_count` 0 and
# `aggregate_disclosure_gap_cents` 0".  The per-night mandatory burden is a
# summary-only figure with no declared counterpart on the property row.
SUMMARY_FIELDS = (
    "disclosure_posture",
    "min_channel_disclosure_score",
    "open_disclosure_obligation_count",
    "published_fee_program_count",
    "aggregate_disclosure_gap_cents",
)


def test_the_disclosure_summary_re_derives_what_the_property_row_stores(api):
    """Nine computed fields agree with the stored row and change nothing.

    PRD 2.9: "It returns `property_id`, `disclosure_posture`,
    `min_channel_disclosure_score`, `open_disclosure_obligation_count`,
    `deployed_profile_count` (the number of the property's profiles currently in
    `DEPLOYED`), `flagged_profile_count` (the number currently in `FLAGGED`),
    `published_fee_program_count`, `total_mandatory_fee_cents_per_night` (the
    per-night mandatory burden carried by the property's `PUBLISHED` fee
    programs, summed across them, and 0 when the property has none) and
    `aggregate_disclosure_gap_cents`. Every field it reports must equal the
    denormalised counterpart stored on the property row".

    Design: Corner/endpoints/disclosure_summary_recomputes_every_counter_on_read
    """
    env = setup_confirmed_booking(
        booking_overrides={"disclosed_fee_amounts": PARTIAL_DISCLOSURE_MAP}
    )
    booking = read_booking(env["booking"]["id"])
    assert booking["disclosure_status"] == "PENDING_AUDIT"
    assert booking["quote_disclosure_gap_cents"] == GAP_UNDER_PARTIAL_MAP

    summary = read_disclosure_summary(env["property"]["id"], COMPLIANCE)
    assert summary["property_id"] == env["property"]["id"]
    assert summary["disclosure_posture"] == "COMPLIANT"
    assert summary["min_channel_disclosure_score"] == 100
    assert summary["deployed_profile_count"] == 1
    assert summary["flagged_profile_count"] == 0
    assert summary["published_fee_program_count"] == 1
    assert summary["total_mandatory_fee_cents_per_night"] == (
        PUBLISHED_TOTAL_MANDATORY_FEE_CENTS_PER_NIGHT
    )
    assert summary["open_disclosure_obligation_count"] == 0
    # The gap of a merely PENDING_AUDIT booking is outside the input set.
    assert summary["aggregate_disclosure_gap_cents"] == 0

    stored = read_property(env["property"]["id"])
    for field in SUMMARY_FIELDS:
        assert summary[field] == stored[field], field

    # A pure read leaves no trace and repeats itself exactly.
    again = read_disclosure_summary(env["property"]["id"], COMPLIANCE)
    assert again == summary
    assert read_property(env["property"]["id"])["version"] == stored["version"]

    # A docket is an obligation of its own that carries no booking gap.
    add_inquiry(env)
    with_docket = read_disclosure_summary(env["property"]["id"], COMPLIANCE)
    assert with_docket["open_disclosure_obligation_count"] == 1
    assert with_docket["aggregate_disclosure_gap_cents"] == 0
    assert with_docket["deployed_profile_count"] == 1


def test_an_audit_always_stamps_the_clock_and_flags_only_under_sixty(api):
    """One endpoint, two outcomes, decided by the recomputed score alone.

    PRD 3.3: "A `ComplianceOfficer` may audit a profile at any time. Auditing
    always recomputes the `disclosure_score` from current inputs and stamps
    `last_audited_at` with the logical clock. When the audited profile is
    `DEPLOYED` and the recomputed score is strictly below 60, the profile
    transitions `DEPLOYED → FLAGGED`". PRD 3.3 on the property side: "0 if the
    profile is `FLAGGED`, regardless of its stored `disclosure_score`".

    Design: Corner/endpoints/audit_stamps_the_clock_and_flags_only_below_the_threshold
    """
    env = setup_deployed_profile()
    terminal = add_channel(env, "gds_channel", **CAPABLE_GDS)
    weak = deploy_profile(
        env,
        profile=add_draft_profile(env, channel=terminal, **CONFIRMATION_ONLY_PROFILE),
    )
    assert weak["disclosure_score"] == 53
    # Deployment already stamps the audit clock: "the profile's `disclosure_score`
    # is recomputed and its `last_audited_at` is stamped with the current logical
    # clock" (PRD 3.3, taking a path live).
    assert_stamped_at_clock(weak["last_audited_at"], CLOCK_START, "last_audited_at")
    before = read_property(env["property"]["id"])
    assert before["min_channel_disclosure_score"] == 53
    assert before["disclosure_posture"] == "NON_COMPLIANT"
    assert before["open_disclosure_obligation_count"] == 0

    flagged = validate_success(api.audit_profile(weak["id"], COMPLIANCE))
    assert flagged["status"] == "FLAGGED"
    assert flagged["disclosure_score"] == 53
    assert_stamped_at_clock(flagged["last_audited_at"], CLOCK_START, "last_audited_at")
    after_flag = read_property(env["property"]["id"])
    assert after_flag["min_channel_disclosure_score"] == 0
    assert after_flag["disclosure_posture"] == "NON_COMPLIANT"
    assert after_flag["open_disclosure_obligation_count"] == 1

    # The same call on a compliant path stamps the clock and moves nothing.
    unchanged = validate_success(
        api.audit_profile(env["profile"]["id"], COMPLIANCE)
    )
    assert unchanged["status"] == "DEPLOYED"
    assert unchanged["disclosure_score"] == 100
    assert_stamped_at_clock(
        unchanged["last_audited_at"], CLOCK_START, "last_audited_at"
    )
    after_clean = read_property(env["property"]["id"])
    assert after_clean["min_channel_disclosure_score"] == 0
    assert after_clean["open_disclosure_obligation_count"] == 1

    # FLAGGED has no audit edge, so the conditional action never repeats.
    validate_error(
        api.audit_profile(weak["id"], COMPLIANCE), ApiErrorId.ERR_INVALID_STATE, 409
    )


def _stranger_folio_lines(api, env):
    """Itemise a second stay on the same path and return its ledger lines."""
    stranger = add_booking(env)
    validate_success(api.confirm_booking(stranger["id"], AGENT))
    validate_success(api.check_in_booking(stranger["id"], AGENT))
    folios = validate_success(api.list_booking_folios(stranger["id"], AGENT))
    other_folio = folios[0] if isinstance(folios, list) else folios["items"][0]
    validate_success(api.itemize_folio(other_folio["id"], AGENT))
    return read_folio_lines(other_folio["id"])


def test_filing_a_complaint_records_one_link_and_computes_no_money_yet(api):
    """The row echoes both identifiers and leaves every entitlement at zero.

    PRD 3.7: "Alongside its `booking_id` the row carries a `status` starting at
    `SUBMITTED`, a computed `refund_variant` defaulting to null, computed
    `disputed_amount_cents`, `disclosed_amount_cents` and
    `refund_entitlement_cents` all defaulting to 0, a system
    `refunded_amount_cents` defaulting to 0, a system `dismissal_reason_code`
    defaulting to null ... and the two system attribution fields
    `investigated_by_user_id` and `adjudicated_by_user_id`, both null at
    creation. At creation the four entitlement fields deliberately stay at their
    defaults — the entitlement arithmetic runs **only** at substantiation —
    while the property's `open_disclosure_obligation_count` is recomputed
    immediately".

    Design: Corner/endpoints/complaint_creation_links_one_booking_to_one_fee_line
    """
    env = setup_posted_folio()
    booking = env["booking"]
    guest = make_guest_headers(booking["id"])
    lines = read_folio_lines(env["folio"]["id"])
    disputed = find_line_by_sequence(lines, 3)
    assert disputed["line_type"] == "MANDATORY_FEE"
    assert read_property(env["property"]["id"])["open_disclosure_obligation_count"] == 0

    def complain(folio_line_id, headers=guest):
        return api.create_guest_complaint(
            booking["id"],
            create_guest_complaint_payload(
                folio_line_id,
                complaint_reason="MANDATORY_NOT_AVOIDABLE",
                narrative="Nobody told me the destination charge could be waived.",
            ),
            headers,
        )

    # A line from another stay is a body-reference the booking does not own.
    stranger_line = find_line_by_sequence(_stranger_folio_lines(api, env), 2)
    validate_error(
        complain(stranger_line["id"]), ApiErrorId.ERR_FOLIO_LINE_NOT_ON_BOOKING, 422
    )
    # Existence is checked at rank 8, long before the ownership rule at rank 25.
    validate_error(
        complain(NON_EXISTENT_UUID), ApiErrorId.ERR_FOLIO_LINE_NOT_FOUND, 404
    )

    filed = validate_success(complain(disputed["id"]), 201)
    assert filed["booking_id"] == booking["id"]
    assert filed["folio_line_id"] == disputed["id"]
    assert filed["complaint_reason"] == "MANDATORY_NOT_AVOIDABLE"
    assert filed["status"] == "SUBMITTED"
    assert filed["refund_variant"] is None
    assert filed["disputed_amount_cents"] == 0
    assert filed["disclosed_amount_cents"] == 0
    assert filed["refund_entitlement_cents"] == 0
    assert filed["refunded_amount_cents"] == 0
    assert filed["dismissal_reason_code"] is None
    assert filed["investigated_by_user_id"] is None
    assert filed["adjudicated_by_user_id"] is None
    assert is_valid_uuid(filed["id"])

    rows, meta = validate_paginated(
        api.list_guest_complaints(AGENT, {"booking_id": booking["id"], "limit": 100})
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [filed["id"]]

    # The obligation lands immediately while the booking's own audit is untouched.
    assert read_property(env["property"]["id"])["open_disclosure_obligation_count"] == 1
    assert read_booking(booking["id"])["disclosure_status"] == "PENDING_AUDIT"

    # Nothing makes the link exclusive, so a second allegation is its own row.
    again = validate_success(complain(disputed["id"], AGENT), 201)
    assert again["id"] != filed["id"]
    assert again["folio_line_id"] == disputed["id"]
    assert read_property(env["property"]["id"])["open_disclosure_obligation_count"] == 2


SECOND_COUNTY = {
    "code": "US-AZ-MARICOPA",
    "name": "Maricopa County, Arizona",
    "occupancy_tax_rate_bps": 1250,
}


def test_a_taxability_rule_reads_back_and_lists_exactly_as_declared(api):
    """An omitted rate stays null, both authors are indistinguishable, filters bite.

    PRD 3.1: "An optional `tax_rate_bps` overrides the jurisdiction's default for
    that fee code; it defaults to null, and when null the jurisdiction's
    `occupancy_tax_rate_bps` applies. When supplied it must itself lie between 0
    and 5000 inclusive. Either a `PlatformAdmin` or a `ComplianceOfficer` may
    declare a rule, and rules are immutable and undeletable — there is no edit
    and no delete route ... Rules are listable with optional `jurisdiction_id`,
    `fee_code` and `taxability` filters."

    Design: Corner/endpoints/taxability_rule_create_read_and_list_round_trip
    """
    county = create_jurisdiction()
    neighbour = create_jurisdiction(**SECOND_COUNTY)

    # The rate is left out of the body entirely rather than sent as null.
    deferred = validate_success(
        api.create_taxability_rule(
            {
                "jurisdiction_id": county["id"],
                "fee_code": "RESORT",
                "taxability": "TAXABLE",
            },
            ADMIN,
        ),
        201,
    )
    assert deferred["jurisdiction_id"] == county["id"]
    assert deferred["fee_code"] == "RESORT"
    assert deferred["taxability"] == "TAXABLE"
    assert deferred["tax_rate_bps"] is None
    assert deferred["version"] == 1
    assert is_valid_uuid(deferred["id"])
    assert_stamped_at_clock(deferred["created_at"], CLOCK_START, "created_at")

    overriding = validate_success(
        api.create_taxability_rule(
            {
                "jurisdiction_id": county["id"],
                "fee_code": "PARKING",
                "taxability": "TAXABLE_IF_MANDATORY",
                "tax_rate_bps": 400,
            },
            COMPLIANCE,
        ),
        201,
    )
    assert overriding["tax_rate_bps"] == 400
    assert overriding["version"] == 1
    # The officer's rule and the admin's rule carry the same shape; no author.
    assert set(overriding) == set(deferred)
    assert [key for key in deferred if key.endswith("_by_user_id")] == []

    elsewhere = validate_success(
        api.create_taxability_rule(
            {
                "jurisdiction_id": neighbour["id"],
                "fee_code": "RESORT",
                "taxability": "EXEMPT",
            },
            ADMIN,
        ),
        201,
    )

    assert validate_success(api.get_taxability_rule(deferred["id"], ADMIN)) == deferred
    assert (
        validate_success(api.get_taxability_rule(overriding["id"], COMPLIANCE))
        == overriding
    )

    by_county, meta = validate_paginated(
        api.list_taxability_rules(ADMIN, {"jurisdiction_id": county["id"], "limit": 100})
    )
    assert meta["total_count"] == 2
    assert {row["id"] for row in by_county} == {deferred["id"], overriding["id"]}

    by_code, meta = validate_paginated(
        api.list_taxability_rules(ADMIN, {"fee_code": "RESORT", "limit": 100})
    )
    assert meta["total_count"] == 2
    assert {row["id"] for row in by_code} == {deferred["id"], elsewhere["id"]}

    both, meta = validate_paginated(
        api.list_taxability_rules(
            ADMIN,
            {"jurisdiction_id": county["id"], "fee_code": "PARKING", "limit": 100},
        )
    )
    assert meta["total_count"] == 1
    assert both[0] == overriding

    # A filter that matches nothing is an empty page, never a 404.
    exempt, meta = validate_paginated(
        api.list_taxability_rules(
            ADMIN, {"jurisdiction_id": county["id"], "taxability": "EXEMPT"}
        )
    )
    assert exempt == []
    assert meta["total_count"] == 0
    assert meta["has_more"] is False

    first, meta = validate_paginated(
        api.list_taxability_rules(
            ADMIN, {"jurisdiction_id": county["id"], "limit": 1, "offset": 0}
        )
    )
    assert len(first) == 1
    assert meta["total_count"] == 2
    assert meta["has_more"] is True

    second, meta = validate_paginated(
        api.list_taxability_rules(
            ADMIN, {"jurisdiction_id": county["id"], "limit": 1, "offset": 1}
        )
    )
    assert len(second) == 1
    assert second[0]["id"] != first[0]["id"]
    assert meta["has_more"] is False
