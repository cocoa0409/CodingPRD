"""Role walls, optimistic concurrency and immediate consistency.

Every test in this module drives state exclusively through the API's own
endpoints and asserts the full observable outcome the PRD fixes: the HTTP
status, the error identifier and the post-state of every entity involved.
"""

from test_helpers import (
    ARCHIVE_RESEARCHER,
    CLEARANCE_SUPERVISOR,
    LEGAL_COUNSEL,
    LEGAL_COUNSEL_USER_ID,
    PRODUCTION_ADMIN,
    REVIEWING_COUNSEL,
    REVIEWING_COUNSEL_USER_ID,
    add_source_candidate,
    assert_asset_dimensions,
    assert_license_money_ledger,
    assert_posture,
    assert_production_counters,
    create_archive,
    create_archive_payload,
    create_archive_with_rate_card,
    create_asset,
    create_asset_with_selected_source,
    create_asset_payload,
    create_eo_review_payload,
    create_fair_use_analysis_payload,
    create_license,
    create_license_payload,
    create_negotiation_round_payload,
    create_production_in_clearance,
    create_production_payload,
    create_rate_card_payload,
    create_source_candidate_payload,
    get_asset,
    get_chart,
    get_license,
    get_license_version,
    get_production,
    get_production_version,
    make_rights_holder_rep_headers,
    open_eo_application,
    pin_chart,
    pin_clearance_chart_payload,
    post_licensor_round,
    record_eo_review,
    run_sweep,
    select_source_payload,
    set_clock,
    setup_fair_use_cleared_production,
    state_payload,
    submit_eo_application,
    validate_error,
    validate_paginated,
    validate_success,
)

# A 45-second BROADCAST / WORLD / 12-month ALL_MEDIA_WINDOW licence on the
# standard card of PRD §3.3: two billable units, tier-2 at 1.25, broadcast at
# 1.15, world at 1.50, a term factor of exactly 1 for a twelve-month term and an
# all-media window multiplier of 1.00 — 60000 * 2 * 1.25 * 1.15 * 1.50 = 258750,
# which clears the all-media fee floor of 150000.
TWELVE_MONTH_TERM = {
    "term_months": 12,
    "term_start_date": "2026-08-15",
    "term_end_date": "2027-08-15",
}
TWELVE_MONTH_FEE_CENTS = 258750

SWEEP_REPORT_ID_LISTS = (
    "activated_license_ids",
    "expired_license_ids",
    "expiring_license_ids",
    "lapsed_asset_ids",
    "suspended_delivery_package_ids",
    "remediated_eo_application_ids",
)


# ─── Module-private setup chains ─────────────────────────────────────────────


def _setup_traced_asset(api):
    """A production in CLEARANCE, an ACTIVE archive with its ACTIVE card, and one
    45-second footage asset carrying one AVAILABLE source candidate."""
    production = create_production_in_clearance(api)
    archive, card = create_archive_with_rate_card(api)
    asset = create_asset(api, production["id"], title="Kerbside")
    candidate = add_source_candidate(api, asset["id"], archive["id"])
    return {
        "production": production,
        "archive": archive,
        "rate_card": card,
        "asset": asset,
        "source_candidate": candidate,
    }


def _setup_draft_footage_license(api):
    """A DRAFT twelve-month footage licence over an asset with a SELECTED source."""
    production = create_production_in_clearance(api)
    archive, card = create_archive_with_rate_card(api)
    asset, candidate = create_asset_with_selected_source(
        api, production["id"], archive["id"], title="Dawn skyline")
    license_row = create_license(api, production["id"], asset["id"], archive["id"],
                                **TWELVE_MONTH_TERM)
    return {
        "production": production,
        "archive": archive,
        "rate_card": card,
        "asset": asset,
        "source_candidate": candidate,
        "license": license_row,
    }


def _setup_draft_license_with_second_archive(api):
    """The DRAFT footage licence of archive A, plus an unrelated ACTIVE archive B
    whose representative is the wrong-holder identity."""
    scenario = _setup_draft_footage_license(api)
    scenario["other_archive"] = create_archive(api, name="Getty Reels",
                                               holder_type="NEWS_ARCHIVE")
    return scenario


def _setup_submitted_eo_over_a_fair_use_chart(api):
    """A SUBMITTED E&O application whose chart pins a FAIR_USE row backed by an
    ISSUED opinion letter that the default `LegalCounsel` operator authored."""
    scenario = setup_fair_use_cleared_production(api, issuer_headers=LEGAL_COUNSEL)
    scenario["chart"] = pin_chart(api, scenario["production"]["id"], "v1 pre-E&O")
    application = open_eo_application(api, scenario["production"]["id"],
                                     scenario["chart"]["id"])
    scenario["eo_application"] = submit_eo_application(api, application["id"])
    return scenario


def _rounds_of(api, license_id):
    rows, meta = validate_paginated(
        api.list_negotiation_rounds(license_id, CLEARANCE_SUPERVISOR,
                                    params={"limit": 100}))
    return rows, meta


# ─── rbac / exclusive_operations_are_unauthorized_for_every_other_role ───────


def test_opening_a_production_file_is_refused_for_a_clearance_supervisor(api):
    """A ClearanceSupervisor may not open the production file.

    PRD §4 lists `ProductionAdmin` as the only authorized role for
    `POST /productions`, and PRD §2.1: "A request that authenticates successfully
    but whose role does not appear in the target operation's authorized-role list
    is rejected with `ERR_UNAUTHORIZED` (HTTP 403)." PRD §2.1 also states of the
    `ProductionAdmin` that "Opening a production file and driving a production to
    `CLEARANCE` or `ABANDONED` are reserved to this role alone."

    Design: Corner/rbac/exclusive_operations_are_unauthorized_for_every_other_role
    """
    response = api.create_production(
        create_production_payload(title="Not My Job"), CLEARANCE_SUPERVISOR)
    validate_error(response, "ERR_UNAUTHORIZED")


def test_recording_a_source_candidate_is_refused_for_a_clearance_supervisor(api):
    """Logging a source candidate is the ArchiveResearcher's exclusive act.

    PRD §2.1, on the `ArchiveResearcher`: "Recording a source candidate against an
    asset is reserved to this role alone." PRD §4 accordingly lists
    `ArchiveResearcher` as the only authorized role for
    `POST /assets/{id}/source-candidates`, and PRD §2.1: "A request that
    authenticates successfully but whose role does not appear in the target
    operation's authorized-role list is rejected with `ERR_UNAUTHORIZED` (HTTP
    403)."

    Design: Corner/rbac/exclusive_operations_are_unauthorized_for_every_other_role
    """
    scenario = _setup_traced_asset(api)

    response = api.create_source_candidate(
        scenario["asset"]["id"],
        create_source_candidate_payload(scenario["archive"]["id"]),
        CLEARANCE_SUPERVISOR)
    validate_error(response, "ERR_UNAUTHORIZED")

    rows, meta = validate_paginated(
        api.list_asset_source_candidates(scenario["asset"]["id"], ARCHIVE_RESEARCHER,
                                         params={"limit": 100}))
    assert meta["total_count"] == 1, (
        "the refused call must not have written a candidate row")
    assert [row["id"] for row in rows] == [scenario["source_candidate"]["id"]]


def test_suspending_an_archive_is_refused_for_a_production_admin(api):
    """Suspending an archive is the ClearanceSupervisor's exclusive act.

    PRD §2.1, on the `ClearanceSupervisor`: "Renewing a licence, suspending or
    reinstating an archive, driving a production to `LOCKED` or `DELIVERED`, and
    recording the `UNDERWRITING` review are reserved to this role alone." PRD §4
    lists `ClearanceSupervisor` as the only authorized role for
    `POST /archives/{id}/state`, and PRD §2.1: "A request that authenticates
    successfully but whose role does not appear in the target operation's
    authorized-role list is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/exclusive_operations_are_unauthorized_for_every_other_role
    """
    scenario = _setup_traced_asset(api)
    archive_id = scenario["archive"]["id"]
    version_before = validate_success(
        api.get_archive(archive_id, CLEARANCE_SUPERVISOR))["version"]

    response = api.set_archive_state(
        archive_id, state_payload("SUSPENDED", reason="Dispute"), PRODUCTION_ADMIN)
    validate_error(response, "ERR_UNAUTHORIZED")

    archive = validate_success(api.get_archive(archive_id, CLEARANCE_SUPERVISOR))
    assert archive["status"] == "ACTIVE", (
        "PRD §3.2: a new archive is ACTIVE, and the refused suspension changes nothing")
    assert archive["version"] == version_before, (
        "PRD §2.4: `version` moves only on a mutation of the row, and the refused "
        "request mutated nothing")


def test_opening_a_fair_use_analysis_is_refused_for_a_clearance_supervisor(api):
    """Authoring the four-factor analysis is LegalCounsel's exclusive act.

    PRD §2.1, on `LegalCounsel`: "Opening a fair-use analysis, attaching an opinion
    letter, driving an opinion letter's status, and recording the `LEGAL` review
    are reserved to this role alone." PRD §4 lists `LegalCounsel` as the only
    authorized role for `POST /assets/{id}/fair-use-analyses`, and PRD §2.1: "A
    request that authenticates successfully but whose role does not appear in the
    target operation's authorized-role list is rejected with `ERR_UNAUTHORIZED`
    (HTTP 403)."

    Design: Corner/rbac/exclusive_operations_are_unauthorized_for_every_other_role
    """
    scenario = _setup_traced_asset(api)

    response = api.create_fair_use_analysis(
        scenario["asset"]["id"], create_fair_use_analysis_payload(), CLEARANCE_SUPERVISOR)
    validate_error(response, "ERR_UNAUTHORIZED")

    rows, meta = validate_paginated(
        api.list_asset_fair_use_analyses(scenario["asset"]["id"], LEGAL_COUNSEL,
                                         params={"limit": 100}))
    assert meta["total_count"] == 0 and rows == [], (
        "the refused call must not have opened an analysis")
    assert_asset_dimensions(get_asset(api, scenario["asset"]["id"]), "UNCLEARED",
                            rights_basis="UNDETERMINED")


# ─── rbac / shared_operations_succeed_for_each_declared_role ─────────────────


def test_registering_an_archive_is_shared_by_the_researcher_and_the_admin(api):
    """Both declared roles may register a rights holder, with identical semantics.

    PRD §3.2: "Either an `ArchiveResearcher` or a `ProductionAdmin` registers one,
    supplying the holder's `name` and its `holder_type`, drawn from `FILM_ARCHIVE`,
    `NEWS_ARCHIVE`, `STUDIO`, `RECORD_LABEL`, `MUSIC_PUBLISHER` and `INDIVIDUAL`."
    PRD §3.2 also fixes the birth state: "A new archive is `ACTIVE` with `version`
    at 1."

    Design: Corner/rbac/shared_operations_succeed_for_each_declared_role
    """
    by_researcher = validate_success(
        api.create_archive(
            create_archive_payload(name="Researcher Archive", holder_type="FILM_ARCHIVE"),
            ARCHIVE_RESEARCHER),
        201)
    by_admin = validate_success(
        api.create_archive(
            create_archive_payload(name="Admin Archive", holder_type="NEWS_ARCHIVE"),
            PRODUCTION_ADMIN),
        201)

    assert by_researcher["id"] != by_admin["id"]
    for archive in (by_researcher, by_admin):
        assert archive["status"] == "ACTIVE"
        assert archive["version"] == 1
        assert archive["mfn_policy"] == "NONE", (
            "PRD §3.2: the optional mfn_policy takes either NONE or RATE_MFN, "
            "defaulting to NONE")


def test_logging_an_asset_is_shared_by_the_researcher_and_the_admin(api):
    """Both declared roles may log an asset into the production.

    PRD §3.1: "Assets are logged into the production by an `ArchiveResearcher` or a
    `ProductionAdmin` as archive research turns up usable material, and only while
    the production is in `DEVELOPMENT` or `CLEARANCE`." PRD §3.1 also fixes the
    birth state: "A freshly logged asset is stamped with `licensing_status` of
    `UNCLEARED`, `lapse_count` of zero, `selected_source_candidate_id` of null, and
    a `rights_basis` of `UNDETERMINED`."

    Design: Corner/rbac/shared_operations_succeed_for_each_declared_role
    """
    production = create_production_in_clearance(api)

    by_researcher = validate_success(
        api.create_asset(production["id"],
                         create_asset_payload(title="Asset by researcher"),
                         ARCHIVE_RESEARCHER),
        201)
    by_admin = validate_success(
        api.create_asset(production["id"],
                         create_asset_payload(title="Asset by admin"),
                         PRODUCTION_ADMIN),
        201)

    assert by_researcher["id"] != by_admin["id"]
    for asset in (by_researcher, by_admin):
        assert_asset_dimensions(asset, "UNCLEARED", depiction_status="NOT_REQUIRED",
                                rights_basis="UNDETERMINED", lapse_count=0)
        assert asset["selected_source_candidate_id"] is None
        assert asset["duration_seconds"] == 45

    assert_production_counters(get_production(api, production["id"]), 2, 0, 2)


def test_publishing_a_rate_card_is_shared_by_the_holders_own_rep(api):
    """The holder's own RightsHolderRep may publish the archive's rate card.

    PRD §3.2: "A card is published by an `ArchiveResearcher` or by the holder's own
    `RightsHolderRep`." PRD §2.1 fixes that rep's identity: "When `X-User-Role` is
    `RightsHolderRep`, `X-User-ID` is the `id` of the acting `Archive`." PRD §3.2
    also fixes the single-active-card guarantee: "an archive has **at most one**
    card in `ACTIVE` at any instant, which is what makes the phrase 'the archive's
    rate card' a deterministic single row."

    Design: Corner/rbac/shared_operations_succeed_for_each_declared_role
    """
    archive = create_archive(api)
    rep_headers = make_rights_holder_rep_headers(archive["id"])

    card = validate_success(
        api.create_rate_card(archive["id"], create_rate_card_payload(), rep_headers), 201)
    assert card["status"] == "ACTIVE"
    assert card["archive_id"] == archive["id"]
    assert card["base_rate_per_30s_cents"] == 60000
    assert card["version"] == 1

    rows, meta = validate_paginated(
        api.list_archive_rate_cards(archive["id"], rep_headers, params={"limit": 100}))
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [card["id"]]
    assert rows[0]["status"] == "ACTIVE"


def test_selecting_the_source_is_shared_by_the_researcher_and_the_supervisor(api):
    """Both declared roles may select the source element, with identical effects.

    PRD §3.2: "Choosing the element the licence will be cut against is a separate,
    deliberate act available to an `ArchiveResearcher` or a `ClearanceSupervisor`."
    PRD §3.2 fixes the effect: "On success the chosen candidate's
    `selection_status` becomes `SELECTED`, any candidate that was previously
    `SELECTED` is demoted to `REJECTED`, the asset's
    `selected_source_candidate_id` is set to the chosen candidate, and the asset's
    `version` increments."

    Design: Corner/rbac/shared_operations_succeed_for_each_declared_role
    """
    production = create_production_in_clearance(api)
    archive, _card = create_archive_with_rate_card(api)

    first = create_asset(api, production["id"], title="Selected by researcher")
    second = create_asset(api, production["id"], title="Selected by supervisor")
    first_candidate = add_source_candidate(api, first["id"], archive["id"])
    second_candidate = add_source_candidate(api, second["id"], archive["id"])
    version_before = {
        first["id"]: get_asset(api, first["id"])["version"],
        second["id"]: get_asset(api, second["id"])["version"],
    }

    validate_success(
        api.select_source(first["id"], select_source_payload(first_candidate["id"]),
                          ARCHIVE_RESEARCHER))
    validate_success(
        api.select_source(second["id"], select_source_payload(second_candidate["id"]),
                          CLEARANCE_SUPERVISOR))

    for asset, candidate in ((first, first_candidate), (second, second_candidate)):
        reread = get_asset(api, asset["id"])
        assert reread["selected_source_candidate_id"] == candidate["id"]
        assert reread["version"] == version_before[asset["id"]] + 1
        rows, _meta = validate_paginated(
            api.list_asset_source_candidates(asset["id"], ARCHIVE_RESEARCHER,
                                             params={"limit": 100}))
        assert [row["selection_status"] for row in rows] == ["SELECTED"]


def test_opening_a_licence_is_shared_by_the_admin_and_the_supervisor(api):
    """Both declared roles may open a licence, and the price is role-independent.

    PRD §3.3: "A licence covers exactly one rights leg of exactly one asset with
    exactly one holder, and it is opened by a `ProductionAdmin` or a
    `ClearanceSupervisor` while the production is still in `DEVELOPMENT` or
    `CLEARANCE`." PRD §3.3 fixes the price and the birth state: "That product is
    rounded half up to an integer number of cents exactly once, and only then is
    `rate_card_fee_cents` taken as the larger of that rounded product and the
    window's fee floor", "A newly created licence lands in `DRAFT`", and creation
    "moves the asset's dimension A from `UNCLEARED → IN_NEGOTIATION` because a
    licence for the asset now exists in `DRAFT`". PRD §2.9: "Licences in `DRAFT`,
    `QUOTED` or `COUNTERED` have a null `executed_fee_cents` and are excluded."

    Design: Corner/rbac/shared_operations_succeed_for_each_declared_role
    """
    production = create_production_in_clearance(api)
    archive, _card = create_archive_with_rate_card(api)
    first, _c1 = create_asset_with_selected_source(
        api, production["id"], archive["id"], title="Licensed by admin")
    second, _c2 = create_asset_with_selected_source(
        api, production["id"], archive["id"], title="Licensed by supervisor")

    by_admin = validate_success(
        api.create_license(
            create_license_payload(production["id"], first["id"], archive["id"],
                                   **TWELVE_MONTH_TERM),
            PRODUCTION_ADMIN),
        201)
    by_supervisor = validate_success(
        api.create_license(
            create_license_payload(production["id"], second["id"], archive["id"],
                                   **TWELVE_MONTH_TERM),
            CLEARANCE_SUPERVISOR),
        201)

    for license_row in (by_admin, by_supervisor):
        assert license_row["status"] == "DRAFT"
        assert license_row["rate_card_fee_cents"] == TWELVE_MONTH_FEE_CENTS
        assert license_row["current_proposed_fee_cents"] == TWELVE_MONTH_FEE_CENTS
        assert license_row["billable_units"] == 2
        assert license_row["round_count"] == 0
        assert license_row["executed_fee_cents"] is None

    for asset in (first, second):
        assert_asset_dimensions(get_asset(api, asset["id"]), "IN_NEGOTIATION",
                                rights_basis="UNDETERMINED")

    reread = get_production(api, production["id"])
    assert reread["committed_fee_cents"] == 0
    assert_production_counters(reread, 2, 0, 2)


# ─── rbac / segregation_of_duties_blocks_the_counsel_who_issued_the_letter ───


def test_the_counsel_who_issued_the_pinned_letter_cannot_record_the_legal_review(api):
    """The lawyer whose opinion the chart relies upon may not sign off on relying on it.

    PRD §3.7: "First, **segregation of duties**: the `X-User-ID` recording the legal
    review must differ from every `issued_by_user_id` among the opinion letters
    listed in the chart's `pinned_opinion_letter_ids`, because the lawyer whose
    opinion is being relied upon may not also sign off on relying upon it; and the
    operator who recorded one branch may not record the other. Either violation is
    refused with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)." PRD §3.5: "the acting
    operator's `X-User-ID` is captured as `issued_by_user_id`."

    Design: Corner/rbac/segregation_of_duties_blocks_the_counsel_who_issued_the_letter
    """
    scenario = _setup_submitted_eo_over_a_fair_use_chart(api)
    letter = scenario["opinion_letter"]
    application_id = scenario["eo_application"]["id"]

    assert letter["issued_by_user_id"] == LEGAL_COUNSEL_USER_ID
    assert letter["status"] == "ISSUED"
    assert get_chart(api, scenario["chart"]["id"])["pinned_opinion_letter_ids"] == \
        [letter["id"]], (
            "PRD §3.7: pinned_opinion_letter_ids collects the id of every opinion "
            "letter in ISSUED that backs a pinned row whose rights_basis is FAIR_USE")

    response = api.create_eo_review(
        application_id, create_eo_review_payload("LEGAL", "PASS"), LEGAL_COUNSEL)
    validate_error(response, "ERR_SEGREGATION_OF_DUTIES")

    reread = validate_success(api.get_eo_application(application_id, CLEARANCE_SUPERVISOR))
    assert reread["status"] == "SUBMITTED"
    assert reread["legal_review_status"] == "PENDING"
    assert reread["underwriting_review_status"] == "PENDING"
    assert reread["version"] == scenario["eo_application"]["version"]


def test_a_second_counsel_records_the_identical_legal_review(api):
    """A counsel who issued no pinned letter records the very same review.

    PRD §3.7: "the `X-User-ID` recording the legal review must differ from every
    `issued_by_user_id` among the opinion letters listed in the chart's
    `pinned_opinion_letter_ids`". PRD §3.7 fixes the accepted outcome: "An accepted
    review sets its dimension to `PASSED` or `FAILED` according to the `outcome`,
    stamps the acting `X-User-ID` into `legal_reviewer_user_id` or
    `underwriting_reviewer_user_id`, and increments the application's `version`.
    The first review of either type also moves the application `SUBMITTED →
    IN_REVIEW`."

    Design: Corner/rbac/segregation_of_duties_blocks_the_counsel_who_issued_the_letter
    """
    scenario = _setup_submitted_eo_over_a_fair_use_chart(api)
    application_id = scenario["eo_application"]["id"]

    assert scenario["opinion_letter"]["issued_by_user_id"] == LEGAL_COUNSEL_USER_ID
    record_eo_review(api, application_id, "LEGAL", "PASS", REVIEWING_COUNSEL)

    reread = validate_success(api.get_eo_application(application_id, CLEARANCE_SUPERVISOR))
    assert reread["status"] == "IN_REVIEW"
    assert reread["legal_review_status"] == "PASSED"
    assert reread["legal_reviewer_user_id"] == REVIEWING_COUNSEL_USER_ID
    assert reread["underwriting_review_status"] == "PENDING"
    assert reread["version"] == scenario["eo_application"]["version"] + 1


# ─── rbac / entity_backed_rep_cannot_quote_on_another_archives_license ───────


def test_a_rep_of_another_archive_cannot_post_a_round_on_this_licence(api):
    """The rep of archive B may not touch archive A's licence.

    PRD §2.1: "A rep appending a negotiation round to a licence, driving a licence's
    status, reading a single licence, or listing an archive's rate cards may only do
    so where that `archive_id` equals its own `X-User-ID`; any other target is
    refused with `ERR_ARCHIVE_OWNERSHIP_MISMATCH` (HTTP 403)."

    Design: Corner/rbac/entity_backed_rep_cannot_quote_on_another_archives_license
    """
    scenario = _setup_draft_license_with_second_archive(api)
    license_row = scenario["license"]

    response = api.create_negotiation_round(
        license_row["id"],
        create_negotiation_round_payload(240000, license_row["version"],
                                         party="LICENSOR"),
        make_rights_holder_rep_headers(scenario["other_archive"]["id"]))
    validate_error(response, "ERR_ARCHIVE_OWNERSHIP_MISMATCH")

    reread = get_license(api, license_row["id"])
    assert reread["status"] == "DRAFT"
    assert reread["round_count"] == 0
    assert reread["current_proposed_fee_cents"] == TWELVE_MONTH_FEE_CENTS
    assert reread["version"] == license_row["version"]
    rows, meta = _rounds_of(api, license_row["id"])
    assert meta["total_count"] == 0 and rows == []


def test_a_rights_holder_rep_cannot_post_a_producer_round(api):
    """A rep may only put the holder's side of the money on the table.

    PRD §2.12 rung 33: "The round's `party` matches the acting role: `LICENSOR`
    requires `RightsHolderRep`, `PRODUCER` requires `ProductionAdmin` or
    `ClearanceSupervisor` — otherwise `ERR_PARTY_ROLE_MISMATCH`." PRD §3.4: "Any
    other pairing of party and acting role is refused with
    `ERR_PARTY_ROLE_MISMATCH` (HTTP 403)."

    Design: Corner/rbac/entity_backed_rep_cannot_quote_on_another_archives_license
    """
    scenario = _setup_draft_footage_license(api)
    license_row = scenario["license"]

    response = api.create_negotiation_round(
        license_row["id"],
        create_negotiation_round_payload(240000, license_row["version"],
                                         party="PRODUCER"),
        make_rights_holder_rep_headers(scenario["archive"]["id"]))
    validate_error(response, "ERR_PARTY_ROLE_MISMATCH")

    reread = get_license(api, license_row["id"])
    assert reread["status"] == "DRAFT"
    assert reread["round_count"] == 0
    assert reread["version"] == license_row["version"]
    rows, meta = _rounds_of(api, license_row["id"])
    assert meta["total_count"] == 0 and rows == []


def test_a_clearance_supervisor_cannot_post_a_licensor_round(api):
    """The production's own side may not quote for the holder.

    PRD §3.4: "A round whose `party` is `LICENSOR` may only be posted by a
    `RightsHolderRep`; a round whose `party` is `PRODUCER` may only be posted by a
    `ProductionAdmin` or a `ClearanceSupervisor`. Any other pairing of party and
    acting role is refused with `ERR_PARTY_ROLE_MISMATCH` (HTTP 403)."

    Design: Corner/rbac/entity_backed_rep_cannot_quote_on_another_archives_license
    """
    scenario = _setup_draft_footage_license(api)
    license_row = scenario["license"]

    response = api.create_negotiation_round(
        license_row["id"],
        create_negotiation_round_payload(240000, license_row["version"],
                                         party="LICENSOR"),
        CLEARANCE_SUPERVISOR)
    validate_error(response, "ERR_PARTY_ROLE_MISMATCH")

    reread = get_license(api, license_row["id"])
    assert reread["status"] == "DRAFT"
    assert reread["round_count"] == 0
    assert reread["version"] == license_row["version"]
    rows, meta = _rounds_of(api, license_row["id"])
    assert meta["total_count"] == 0 and rows == []


def test_the_licences_own_holder_posts_the_licensor_round(api):
    """The rep whose X-User-ID is the licence's archive_id quotes successfully.

    PRD §3.4: "A `RightsHolderRep` posting a `LICENSOR` round must additionally be
    the licence's own holder, meaning its `X-User-ID` equals the licence's
    `archive_id`", "A `LICENSOR` round posted against a licence in `DRAFT` advances
    it `DRAFT → QUOTED`", and "The round is created with `round_number` equal to the
    licence's `round_count` before the round plus one, so the first round is round
    1. The licence's `round_count` increases by one, its
    `current_proposed_fee_cents` is overwritten with this round's
    `proposed_fee_cents` — the standing proposal is always simply the most recent
    one, regardless of which side made it — and its `version` increments."

    Design: Corner/rbac/entity_backed_rep_cannot_quote_on_another_archives_license
    """
    scenario = _setup_draft_license_with_second_archive(api)
    license_row = scenario["license"]

    round_row = validate_success(
        api.create_negotiation_round(
            license_row["id"],
            create_negotiation_round_payload(TWELVE_MONTH_FEE_CENTS,
                                             license_row["version"], party="LICENSOR"),
            make_rights_holder_rep_headers(scenario["archive"]["id"])),
        201)

    assert round_row["round_number"] == 1
    assert round_row["party"] == "LICENSOR"
    assert round_row["proposed_fee_cents"] == TWELVE_MONTH_FEE_CENTS
    assert round_row["license_status_after"] == "QUOTED"
    assert round_row["license_version_after"] == license_row["version"] + 1

    reread = get_license(api, license_row["id"])
    assert reread["status"] == "QUOTED"
    assert reread["round_count"] == 1
    assert reread["current_proposed_fee_cents"] == TWELVE_MONTH_FEE_CENTS
    assert reread["version"] == license_row["version"] + 1

    rows, meta = _rounds_of(api, license_row["id"])
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [round_row["id"]]


# ─── complexity_layers / stale_production_version_blocks_the_second_chart_pin ─


def test_a_second_pin_on_the_pre_pin_production_version_is_refused(api):
    """Pinning bumps the production's version, so the second writer is stale.

    PRD §2.7: "Pinning a clearance chart requires `expected_production_version` on
    every request; the field is not optional and its absence is a malformed
    request. Its value must equal the target `Production`'s current `version`. If
    any writer has advanced the production's `version` since the client last read
    it — a new asset logged, a licence executed, a posture recomputation, an
    earlier chart pinned — the pin is rejected with
    `ERR_STALE_PRODUCTION_VERSION` (HTTP 412)."

    Design: Corner/complexity_layers/stale_production_version_blocks_the_second_chart_pin
    """
    production = create_production_in_clearance(api)
    shared_version = get_production_version(api, production["id"])

    first_chart = validate_success(
        api.pin_clearance_chart(
            production["id"],
            pin_clearance_chart_payload(shared_version, "writer one"),
            CLEARANCE_SUPERVISOR),
        201)
    assert first_chart["status"] == "PINNED"
    assert get_production_version(api, production["id"]) == shared_version + 1

    response = api.pin_clearance_chart(
        production["id"],
        pin_clearance_chart_payload(shared_version, "writer two"),
        LEGAL_COUNSEL)
    validate_error(response, "ERR_STALE_PRODUCTION_VERSION")

    assert get_chart(api, first_chart["id"])["status"] == "PINNED"
    rows, meta = validate_paginated(
        api.list_production_clearance_charts(production["id"], CLEARANCE_SUPERVISOR,
                                            params={"limit": 100}))
    assert meta["total_count"] == 1, "the refused pin must not have written a chart"
    assert [row["id"] for row in rows] == [first_chart["id"]]
    assert get_production_version(api, production["id"]) == shared_version + 1


def test_the_refreshed_pin_succeeds_and_supersedes_the_earlier_chart(api):
    """Re-reading the production unblocks the identical pin, which supersedes.

    PRD §2.7: "The stale-version rejection forces that second writer to re-read the
    production before pinning." PRD §3.7: "The new chart's `status` is `PINNED`,
    every earlier chart of the same production moves to `SUPERSEDED` whether it
    stood in `PINNED` or `STALE`, the production's posture is recomputed, and the
    production's `version` increments — which is why two clients cannot pin
    back-to-back charts without the second re-reading first."

    Design: Corner/complexity_layers/stale_production_version_blocks_the_second_chart_pin
    """
    production = create_production_in_clearance(api)
    shared_version = get_production_version(api, production["id"])

    first_chart = validate_success(
        api.pin_clearance_chart(
            production["id"],
            pin_clearance_chart_payload(shared_version, "writer one"),
            CLEARANCE_SUPERVISOR),
        201)
    validate_error(
        api.pin_clearance_chart(
            production["id"],
            pin_clearance_chart_payload(shared_version, "writer two"),
            LEGAL_COUNSEL),
        "ERR_STALE_PRODUCTION_VERSION")

    fresh_version = get_production_version(api, production["id"])
    assert fresh_version == shared_version + 1

    second_chart = validate_success(
        api.pin_clearance_chart(
            production["id"],
            pin_clearance_chart_payload(fresh_version, "writer two retry"),
            LEGAL_COUNSEL),
        201)
    assert second_chart["status"] == "PINNED"
    assert get_chart(api, first_chart["id"])["status"] == "SUPERSEDED"
    assert get_production_version(api, production["id"]) == fresh_version + 1

    rows, meta = validate_paginated(
        api.list_production_clearance_charts(production["id"], CLEARANCE_SUPERVISOR,
                                            params={"status": "PINNED", "limit": 100}))
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [second_chart["id"]]


# ─── complexity_layers / stale_license_version_blocks_the_counter_round ──────


def test_a_counter_on_the_pre_quote_licence_version_is_refused(api):
    """A producer countering on the version it read before the quote landed is stale.

    PRD §2.7: "Appending a negotiation round requires `expected_license_version` on
    every request; it too is mandatory. Its value must equal the target `License`'s
    current `version`. Where it does not, the round is rejected with
    `ERR_STALE_LICENSE_VERSION` (HTTP 412). Each round overwrites
    `current_proposed_fee_cents`, so a writer working from an outdated view of the
    deal would replace a counter-offer it never saw; the stale-version check makes
    that rejection deterministic and points the writer at `license_version_after`
    on the last round it did see."

    Design: Corner/complexity_layers/stale_license_version_blocks_the_counter_round
    """
    scenario = _setup_draft_footage_license(api)
    license_row = scenario["license"]
    creation_version = license_row["version"]

    quote = validate_success(
        api.create_negotiation_round(
            license_row["id"],
            create_negotiation_round_payload(300000, creation_version, party="LICENSOR"),
            make_rights_holder_rep_headers(scenario["archive"]["id"])),
        201)
    assert quote["license_status_after"] == "QUOTED"
    assert quote["license_version_after"] == creation_version + 1

    response = api.create_negotiation_round(
        license_row["id"],
        create_negotiation_round_payload(200000, creation_version, party="PRODUCER"),
        CLEARANCE_SUPERVISOR)
    validate_error(response, "ERR_STALE_LICENSE_VERSION")

    reread = get_license(api, license_row["id"])
    assert reread["status"] == "QUOTED"
    assert reread["current_proposed_fee_cents"] == 300000
    assert reread["round_count"] == 1
    assert reread["version"] == creation_version + 1
    assert reread["rate_card_fee_cents"] == TWELVE_MONTH_FEE_CENTS

    rows, meta = _rounds_of(api, license_row["id"])
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [quote["id"]]


def test_the_counter_lands_once_the_producer_re_reads_the_licence(api):
    """The refreshed version carried by the last round is what the counter must send.

    PRD §2.7: "the stale-version check makes that rejection deterministic and
    points the writer at `license_version_after` on the last round it did see."
    PRD §3.4: "A `PRODUCER` round posted against a licence in `QUOTED` advances it
    `QUOTED → COUNTERED`", and "its `current_proposed_fee_cents` is overwritten
    with this round's `proposed_fee_cents` — the standing proposal is always simply
    the most recent one, regardless of which side made it — and its `version`
    increments."

    Design: Corner/complexity_layers/stale_license_version_blocks_the_counter_round
    """
    scenario = _setup_draft_footage_license(api)
    license_row = scenario["license"]
    creation_version = license_row["version"]

    post_licensor_round(api, license_row["id"], scenario["archive"]["id"], 300000)
    validate_error(
        api.create_negotiation_round(
            license_row["id"],
            create_negotiation_round_payload(200000, creation_version, party="PRODUCER"),
            CLEARANCE_SUPERVISOR),
        "ERR_STALE_LICENSE_VERSION")

    fresh_version = get_license_version(api, license_row["id"])
    assert fresh_version == creation_version + 1

    counter = validate_success(
        api.create_negotiation_round(
            license_row["id"],
            create_negotiation_round_payload(200000, fresh_version, party="PRODUCER"),
            CLEARANCE_SUPERVISOR),
        201)
    assert counter["round_number"] == 2
    assert counter["license_status_after"] == "COUNTERED"
    assert counter["license_version_after"] == creation_version + 2

    reread = get_license(api, license_row["id"])
    assert reread["status"] == "COUNTERED"
    assert reread["current_proposed_fee_cents"] == 200000
    assert reread["round_count"] == 2
    assert reread["version"] == creation_version + 2
    assert reread["rate_card_fee_cents"] == TWELVE_MONTH_FEE_CENTS

    _rows, meta = _rounds_of(api, license_row["id"])
    assert meta["total_count"] == 2


# ─── complexity_layers / sweep_epoch_is_monotonic_across_repeated_checkpoints ─


def test_the_sweep_epoch_advances_by_exactly_one_per_run(api):
    """Three consecutive sweeps read 1, 2, 3 with no gaps and no reuse.

    PRD §3.1: a new production is born "with `asset_count`, `cleared_asset_count`,
    `open_asset_count`, `committed_fee_cents` and `sweep_epoch` all at zero".
    PRD §3.8: the sweep "takes no request body, reads the date part of the logical
    clock, and considers only licences whose `production_id` equals the swept
    production. It first increases the production's `sweep_epoch` by one".

    Design: Corner/complexity_layers/sweep_epoch_is_monotonic_across_repeated_checkpoints
    """
    set_clock(api, "2026-08-20T00:00:00Z")
    production = create_production_in_clearance(api)
    before = get_production(api, production["id"])
    assert before["sweep_epoch"] == 0

    first = run_sweep(api, production["id"], CLEARANCE_SUPERVISOR)
    second = run_sweep(api, production["id"], PRODUCTION_ADMIN)
    third = run_sweep(api, production["id"], CLEARANCE_SUPERVISOR)

    assert [first["sweep_epoch"], second["sweep_epoch"], third["sweep_epoch"]] == [1, 2, 3]

    after = get_production(api, production["id"])
    assert after["sweep_epoch"] == 3
    assert after["version"] > before["version"], (
        "PRD §2.4: advancing the epoch mutates the production row")


def test_repeated_sweeps_of_an_empty_production_report_nothing_touched(api):
    """Every checkpoint answers with an empty report and unchanged derived state.

    PRD §3.8: "The sweep answers with a report of exactly what it did:
    `sweep_epoch` for the epoch just reached, `activated_license_ids`,
    `expired_license_ids` and `expiring_license_ids` for the three licence steps,
    `lapsed_asset_ids` for the assets that lost coverage,
    `suspended_delivery_package_ids` and `remediated_eo_application_ids` for hops
    (c) and (d), plus the resulting `production_posture` and
    `committed_fee_cents`. Apart from `sweep_epoch`, which advances on every call,
    a sweep is idempotent at a fixed clock instant: running it twice without moving
    the clock produces no further state change and empty id lists on the second
    run." PRD §2.8 rule 1: "If the production has no assets at all, posture is
    `OPEN`."

    Design: Corner/complexity_layers/sweep_epoch_is_monotonic_across_repeated_checkpoints
    """
    set_clock(api, "2026-08-20T00:00:00Z")
    production = create_production_in_clearance(api)

    for _run in range(3):
        report = run_sweep(api, production["id"], CLEARANCE_SUPERVISOR)
        assert report["production_posture"] == "OPEN"
        assert report["committed_fee_cents"] == 0
        for field in SWEEP_REPORT_ID_LISTS:
            assert report[field] == [], f"{field} must be empty, got {report[field]!r}"

    reread = get_production(api, production["id"])
    assert_posture(reread, "OPEN")
    assert reread["committed_fee_cents"] == 0
    assert_production_counters(reread, 0, 0, 0)


# ─── consistency_model / every_write_returns_its_recomputed_derived_fields ────


def test_execution_settles_the_asset_and_the_production_inside_the_request(api):
    """The execution response and the very next reads already carry every consequence.

    PRD §2.10: "Clearance state is immediately consistent: every derived value a
    request touches is recomputed inside that request, and the response reflects
    the settled result. There is no deferred or eventual recomputation anywhere in
    the system." PRD §3.4: "Step one establishes this licence's own base with no
    most-favored-nations input whatsoever: the base fee is the larger of
    `current_proposed_fee_cents` and `rate_card_fee_cents`", and "Executing the
    single `FOOTAGE` leg of an archival-footage asset completes its required set
    and moves the asset `IN_NEGOTIATION → CLEARED`, setting `rights_basis` to
    `LICENSED`, raising `cleared_asset_count` by one and lowering
    `open_asset_count` by one". PRD §2.9: "executing a licence adds its
    `executed_fee_cents`" to the production's `committed_fee_cents`.

    Design: Corner/consistency_model/every_write_returns_its_recomputed_derived_fields_immediately
    """
    scenario = _setup_draft_footage_license(api)
    license_row = scenario["license"]
    post_licensor_round(api, license_row["id"], scenario["archive"]["id"],
                        TWELVE_MONTH_FEE_CENTS)

    executed = validate_success(
        api.set_license_state(license_row["id"], state_payload("EXECUTED"),
                              CLEARANCE_SUPERVISOR))
    assert executed["status"] == "EXECUTED"
    assert executed["executed_fee_cents"] == TWELVE_MONTH_FEE_CENTS
    assert executed["mfn_requested"] is False, (
        "PRD §3.3: when the client omits mfn_requested, the server sets it to true "
        "where the named archive's mfn_policy is RATE_MFN, and to false otherwise")
    assert executed["mfn_benchmark_fee_cents"] == 0, (
        "PRD §3.4: if mfn_requested on this licence is false, "
        "mfn_benchmark_fee_cents is 0")
    assert executed["mfn_topup_cents"] == 0

    asset = get_asset(api, scenario["asset"]["id"])
    assert_asset_dimensions(asset, "CLEARED", depiction_status="NOT_REQUIRED",
                            rights_basis="LICENSED", lapse_count=0)

    production = get_production(api, scenario["production"]["id"])
    assert production["committed_fee_cents"] == TWELVE_MONTH_FEE_CENTS
    assert_production_counters(production, 1, 1, 0)
    assert_posture(production, "OPEN")
    assert_license_money_ledger(api, scenario["production"]["id"], CLEARANCE_SUPERVISOR)


def test_no_derived_field_needs_a_second_read_to_settle(api):
    """A repeated read with no intervening write returns byte-identical derived state.

    PRD §2.10: "Clearance state is immediately consistent: every derived value a
    request touches is recomputed inside that request, and the response reflects
    the settled result. There is no deferred or eventual recomputation anywhere in
    the system."

    Design: Corner/consistency_model/every_write_returns_its_recomputed_derived_fields_immediately
    """
    scenario = _setup_draft_footage_license(api)
    license_row = scenario["license"]
    post_licensor_round(api, license_row["id"], scenario["archive"]["id"],
                        TWELVE_MONTH_FEE_CENTS)
    validate_success(
        api.set_license_state(license_row["id"], state_payload("EXECUTED"),
                              CLEARANCE_SUPERVISOR))

    first_asset = get_asset(api, scenario["asset"]["id"])
    first_production = get_production(api, scenario["production"]["id"])
    first_license = get_license(api, license_row["id"])

    second_asset = get_asset(api, scenario["asset"]["id"])
    second_production = get_production(api, scenario["production"]["id"])
    second_license = get_license(api, license_row["id"])

    for field in ("licensing_status", "rights_basis", "depiction_status",
                  "lapse_count", "version", "updated_at"):
        assert first_asset[field] == second_asset[field], (
            f"Asset.{field} moved between two reads with no write in between")
    for field in ("posture", "committed_fee_cents", "asset_count",
                  "cleared_asset_count", "open_asset_count", "sweep_epoch",
                  "version", "updated_at"):
        assert first_production[field] == second_production[field], (
            f"Production.{field} moved between two reads with no write in between")
    for field in ("status", "executed_fee_cents", "mfn_topup_cents",
                  "mfn_benchmark_fee_cents", "rate_card_fee_cents", "version",
                  "updated_at"):
        assert first_license[field] == second_license[field], (
            f"License.{field} moved between two reads with no write in between")

    assert second_asset["licensing_status"] == "CLEARED"
    assert second_asset["rights_basis"] == "LICENSED"
    assert second_production["committed_fee_cents"] == TWELVE_MONTH_FEE_CENTS
    assert second_production["posture"] == "OPEN"
