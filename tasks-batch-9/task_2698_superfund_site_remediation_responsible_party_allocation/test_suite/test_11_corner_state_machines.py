"""Lifecycle probes: initial states, valid cycles, and refused transitions.

These exercise the state dimensions themselves — what a freshly opened round
looks like before anyone votes, which transitions may be repeated and which may
not, how the party election loop cycles, and how a conditional cascade reads
the target round's own state before deciding what to touch.
"""
from test_helpers import ApiErrorId, api_client, factories
from test_helpers.assertions import (
    assert_percentage,
    assert_percentages_sum_to_100,
    is_iso8601_timestamp,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    add_verified_waste_in,
    adopt_round,
    create_investigation,
    create_listed_site,
    create_participating_party,
    create_party,
    create_site,
    issue_notice,
    list_site_on_npl,
    open_balloting,
    open_round,
    read_party,
    read_round,
    read_site,
    record_defunct,
    set_clock,
    share_for,
    site_version,
)
from test_helpers.test_users import (
    FACILITATOR_ID,
    TEST_USERS,
    make_prp_representative_headers,
)

AUTHOR = TEST_USERS["author_pm_headers"]
FACILITATOR = TEST_USERS["facilitator_headers"]


def _sablewood_fresh_round():
    """A listed site with two participating parties and one never-noticed party.

    Party A claims 3,960 verified tons of class II waste and party B 40 verified
    tons of class IV, so the volumetric and toxicity factors both have a basis
    while ownership has none. Party D is named but never noticed.
    """
    set_clock("2027-02-01T09:00:00Z")
    site = create_listed_site(
        name="Sablewood Creosote Yard", epa_region=4, hrs_score=45.90
    )
    prp_a = create_participating_party(
        site["id"],
        legal_name="Sablewood Timber Co",
        party_type="OWNER_OPERATOR",
        viability_score=77,
    )
    prp_b = create_participating_party(
        site["id"],
        legal_name="Creek Road Tie Yard LLC",
        party_type="GENERATOR",
        viability_score=23,
    )
    prp_d = create_party(
        site["id"],
        legal_name="Unlocated Successor Trust",
        party_type="ARRANGER",
        viability_score=5,
    )
    add_verified_waste_in(site["id"], prp_a["id"], 3960, "II", "A", 1973)
    add_verified_waste_in(site["id"], prp_b["id"], 40, "IV", "B", 1990)
    create_investigation(
        site["id"], exposure_medium="SOIL", scope_summary="OU-1 creosote in soil"
    )
    site_v = site_version(site["id"], FACILITATOR)
    round_response = api_client.create_allocation_round(
        site["id"],
        factories.allocation_round_payload(
            expected_site_version=site_v,
            weight_volume_bp=5000,
            weight_toxicity_bp=3000,
            weight_ownership_bp=2000,
        ),
        FACILITATOR,
    )
    return {
        "site": site,
        "site_version_before": site_v,
        "prp_a": prp_a,
        "prp_b": prp_b,
        "prp_d": prp_d,
        "response": round_response,
    }


class TestNewAllocationRoundInitialState:
    def test_a_new_round_opens_in_drafting_as_round_number_one(self):
        """Nothing is voted, resolved or stamped when a round is first opened.

        PRD: "A new round begins with `status` `DRAFTING`, stamps the opening facilitator's identifier as `facilitator_user_id`, and takes a `round_number` of 1 for the site's first round and otherwise the site's previous highest round number plus 1 — **counting superseded and failed rounds**, so numbers are never reused."

        Design: Corner/state_machines/corner_new_allocation_round_starts_in_drafting_with_one_share_per_noticed_party
        """
        world = _sablewood_fresh_round()
        allocation_round = validate_success(world["response"], 201)

        assert allocation_round["status"] == "DRAFTING"
        assert allocation_round["round_number"] == 1
        assert allocation_round["facilitator_user_id"] == FACILITATOR_ID
        assert allocation_round["share_count"] == 2
        assert allocation_round["balloted_count"] == 0
        assert_percentage(
            allocation_round["accept_share_pct"], 0.00, "accept_share_pct"
        )
        assert allocation_round["adopted_at"] in (None, "")

        # Nothing is stamped into the three settlement buckets before adoption.
        assert_percentage(
            allocation_round["allocated_share_total_pct"],
            0.00,
            "allocated_share_total_pct",
        )
        assert_percentage(allocation_round["orphan_share_pct"], 0.00, "orphan_share_pct")
        assert_percentage(
            allocation_round["settled_share_pct"], 0.00, "settled_share_pct"
        )

        site = read_site(world["site"]["id"])
        assert site["version"] == world["site_version_before"] + 1
        assert site["adopted_round_id"] in (None, "")

    def test_one_pending_share_is_minted_per_candidate_party_in_creation_order(self):
        """A party that has never been noticed is not a candidate and gets no share.

        PRD: "Opening the round also mints one allocation share per candidate party. The candidate set is exactly those parties of the site whose `status` is anything other than `IDENTIFIED` — that is, `NOTIFIED`, `PARTICIPATING`, `RECALCITRANT`, `ORPHAN`, `SETTLED` or `DE_MINIMIS_SETTLED` — captured at the instant the round is opened, and enumerated in party `created_at` ascending order, never by `id`."

        Design: Corner/state_machines/corner_new_allocation_round_starts_in_drafting_with_one_share_per_noticed_party
        """
        world = _sablewood_fresh_round()
        allocation_round = validate_success(world["response"], 201)

        shares, meta = validate_paginated(
            api_client.list_round_shares(allocation_round["id"], AUTHOR)
        )
        assert meta["total_count"] == 2
        assert [share["prp_id"] for share in shares] == [
            world["prp_a"]["id"],
            world["prp_b"]["id"],
        ]

        share_a, share_b = shares
        assert_percentage(share_a["provisional_pct"], 99.28, "provisional_pct A")
        assert_percentage(share_b["provisional_pct"], 0.72, "provisional_pct B")
        assert_percentages_sum_to_100(
            [share["provisional_pct"] for share in shares]
        )
        for share in shares:
            assert share["allocation_round_id"] == allocation_round["id"]
            assert share["disposition"] == "PENDING"
            assert share["ballot"] in (None, "")
            assert share["ballot_rationale"] in (None, "")
            assert share["ballot_cast_at"] in (None, "")
            assert share["final_pct"] is None
            assert share["pre_settlement_final_pct"] is None

        assert world["prp_d"]["id"] not in [share["prp_id"] for share in shares]
        assert read_party(world["prp_d"]["id"])["status"] == "IDENTIFIED"


class TestNplListingIsNotIdempotent:
    def test_re_listing_an_already_listed_site_is_refused_and_changes_nothing(self):
        """Listing runs once from PROPOSED; a repeat is a refused transition.

        PRD: "Listing is permitted only from `PROPOSED`, and only when the site's `hrs_score` is at least 28.50 — a score of exactly 28.50 qualifies."

        Design: Corner/state_machines/corner_second_npl_listing_of_a_listed_site_returns_4XX
        """
        set_clock("2027-01-04T08:00:00Z")
        site = create_site(
            name="Cinder Ridge Coal Gasification", epa_region=3, hrs_score=51.80
        )
        validate_success(
            api_client.list_on_npl(
                site["id"],
                factories.listing_payload(listing_reference="FR-2027-CRH-0104"),
                AUTHOR,
            )
        )
        listed = read_site(site["id"])
        assert listed["listing_status"] == "LISTED"
        version_after_listing = listed["version"]

        second = api_client.list_on_npl(
            site["id"],
            factories.listing_payload(listing_reference="FR-2027-CRH-9999"),
            AUTHOR,
        )
        validate_error(second, ApiErrorId.ERR_INVALID_STATE_TRANSITION, 409)

        after = read_site(site["id"])
        assert after["listing_status"] == "LISTED"
        assert after["listing_reference"] == "FR-2027-CRH-0104"
        assert after["version"] == version_after_listing


def _ferrous_bend_balloting_round():
    """A two-party round in balloting with party A's ACCEPT already recorded."""
    set_clock("2027-02-01T09:00:00Z")
    site = create_site(name="Ferrous Bend Smelter", epa_region=5, hrs_score=49.30)
    site = list_site_on_npl(site["id"], listing_reference="FR-2027-FBS-0201")
    prp_a = create_participating_party(
        site["id"],
        legal_name="Ferrous Bend Metals",
        party_type="OWNER_OPERATOR",
        viability_score=79,
    )
    prp_b = create_participating_party(
        site["id"],
        legal_name="Bend Radiator Shop",
        party_type="GENERATOR",
        viability_score=18,
    )
    add_verified_waste_in(site["id"], prp_a["id"], 3960, "II", "A", 1965)
    add_verified_waste_in(site["id"], prp_b["id"], 40, "IV", "B", 1984)
    create_investigation(
        site["id"],
        exposure_medium="SOIL",
        scope_summary="OU-1 lead and arsenic in soil",
    )
    allocation_round = open_round(site["id"])
    open_balloting(allocation_round["id"])
    validate_success(
        api_client.cast_ballot(
            allocation_round["id"],
            factories.ballot_payload(ballot="ACCEPT"),
            make_prp_representative_headers(prp_a["id"]),
        )
    )
    return {
        "site": site,
        "prp_a": prp_a,
        "prp_b": prp_b,
        "round": allocation_round,
    }


class TestSecondBallotByTheSameParty:
    def test_a_party_that_has_already_voted_cannot_vote_again(self):
        """The stored ballot keeps its original value even though the retry flips it.

        PRD: "A party that has already voted on this round cannot vote again while the round remains open, and a second attempt is refused with `ERR_BALLOT_ALREADY_CAST`; reopening the round clears the record and restores the right to vote."

        Design: Corner/state_machines/corner_second_ballot_by_the_same_party_returns_4XX
        """
        world = _ferrous_bend_balloting_round()
        round_id = world["round"]["id"]

        retry = api_client.cast_ballot(
            round_id,
            factories.ballot_payload(
                ballot="REJECT", ballot_rationale="Changed our mind."
            ),
            make_prp_representative_headers(world["prp_a"]["id"]),
        )
        validate_error(retry, ApiErrorId.ERR_BALLOT_ALREADY_CAST, 409)

        share_a = share_for(round_id, world["prp_a"]["id"])
        assert share_a["ballot"] == "ACCEPT"
        assert share_a["ballot_rationale"] in (None, "")

        after = read_round(round_id)
        assert after["balloted_count"] == 1
        assert_percentage(after["accept_share_pct"], 99.28, "accept_share_pct")
        assert after["status"] == "BALLOTING"
        assert after["adopted_at"] in (None, "")
        assert read_site(world["site"]["id"])["adopted_round_id"] in (None, "")


def _grimsby_adopted_round():
    """A two-party round adopted on two acceptances, final shares 99.28 / 0.72."""
    set_clock("2027-02-01T09:00:00Z")
    site = create_site(name="Grimsby Flats Refinery", epa_region=6, hrs_score=53.60)
    site = list_site_on_npl(site["id"], listing_reference="FR-2027-GFR-0201")
    prp_a = create_participating_party(
        site["id"],
        legal_name="Grimsby Petroleum Co",
        party_type="OWNER_OPERATOR",
        viability_score=90,
    )
    prp_b = create_participating_party(
        site["id"],
        legal_name="Flats Tank Cleaning LLC",
        party_type="TRANSPORTER",
        viability_score=21,
    )
    add_verified_waste_in(site["id"], prp_a["id"], 3960, "II", "A", 1967)
    add_verified_waste_in(site["id"], prp_b["id"], 40, "IV", "C", 1985)
    create_investigation(
        site["id"],
        exposure_medium="GROUNDWATER",
        scope_summary="OU-1 benzene in groundwater",
    )
    allocation_round = open_round(site["id"])
    adopt_round(allocation_round["id"], [prp_a["id"], prp_b["id"]])
    return {
        "site": site,
        "prp_a": prp_a,
        "prp_b": prp_b,
        "round": read_round(allocation_round["id"]),
    }


class TestReopeningAnAdoptedRound:
    def test_an_adopted_round_cannot_be_reopened(self):
        """Reopening runs backwards from balloting or failure, never from adoption.

        PRD: "Both `ADOPTED` and `SUPERSEDED` are terminal."

        Design: Corner/state_machines/corner_reopening_an_adopted_round_returns_4XX
        """
        world = _grimsby_adopted_round()
        adopted = world["round"]
        assert adopted["status"] == "ADOPTED"

        refusal = api_client.reopen_round(
            adopted["id"],
            factories.reopening_payload(
                revision_note="Counsel wants another look after adoption."
            ),
            FACILITATOR,
        )
        validate_error(refusal, ApiErrorId.ERR_INVALID_STATE_TRANSITION, 409)

        after = read_round(adopted["id"])
        assert after["status"] == "ADOPTED"
        assert after["version"] == adopted["version"]
        assert after["revision_note"] in (None, "")

    def test_the_refused_reopening_clears_nothing_it_would_have_cleared(self):
        """Every field a successful reopening would have wiped survives untouched.

        PRD: "Reopening clears `ballot`, `ballot_rationale` and `ballot_cast_at` on every share, resets `balloted_count` to 0 and `accept_share_pct` to 0.00, re-derives `provisional_pct` against current data, and mints shares for any party that has entered the candidate set since the round was opened."

        Design: Corner/state_machines/corner_reopening_an_adopted_round_returns_4XX
        """
        world = _grimsby_adopted_round()
        round_id = world["round"]["id"]

        api_client.reopen_round(
            round_id,
            factories.reopening_payload(
                revision_note="Counsel wants another look after adoption."
            ),
            FACILITATOR,
        )

        after = read_round(round_id)
        assert after["balloted_count"] == 2
        assert_percentage(after["accept_share_pct"], 100.00, "accept_share_pct")
        assert_percentage(
            after["allocated_share_total_pct"], 100.00, "allocated_share_total_pct"
        )

        share_a = share_for(round_id, world["prp_a"]["id"])
        share_b = share_for(round_id, world["prp_b"]["id"])
        assert_percentage(share_a["final_pct"], 99.28, "final_pct A")
        assert_percentage(share_b["final_pct"], 0.72, "final_pct B")
        for share in (share_a, share_b):
            assert share["disposition"] == "ALLOCATED"
            assert share["ballot"] == "ACCEPT"
            assert is_iso8601_timestamp(share["ballot_cast_at"])

        assert read_site(world["site"]["id"])["adopted_round_id"] == round_id


def _hobble_brook_noticed_party():
    """One listed site with a single noticed party awaiting its election."""
    set_clock("2027-01-04T08:00:00Z")
    site = create_site(name="Hobble Brook Tannery", epa_region=1, hrs_score=38.40)
    site = list_site_on_npl(site["id"], listing_reference="FR-2027-HBT-0104")
    party = create_party(
        site["id"],
        legal_name="Hobble Leather Works",
        party_type="OWNER_OPERATOR",
        viability_score=58,
    )
    noticed = issue_notice(party["id"], notice_reference="GNL-2027-3001")
    return {"site": site, "party": noticed}


def _record_election(prp_id, election, response_note):
    return api_client.record_response(
        prp_id,
        factories.response_payload(election=election, response_note=response_note),
        make_prp_representative_headers(prp_id),
    )


class TestPartyElectionCycle:
    def test_declining_then_participating_cycles_through_recalcitrant(self):
        """The election loop runs both ways, one version increment per hand.

        PRD: "Both directions remain open afterwards: a recalcitrant party may later elect to participate (`RECALCITRANT → PARTICIPATING`), and a participating party may later decline (`PARTICIPATING → RECALCITRANT`), so the re-election loop may run as many times as the negotiation requires."

        Design: Corner/state_machines/corner_prp_decline_then_participate_cycles_through_recalcitrant
        """
        world = _hobble_brook_noticed_party()
        prp_id = world["party"]["id"]
        noticed_version = world["party"]["version"]
        assert world["party"]["status"] == "NOTIFIED"

        declined = validate_success(
            _record_election(prp_id, "DECLINE", "We dispute successor liability.")
        )
        assert declined["status"] == "RECALCITRANT"
        assert declined["version"] == noticed_version + 1

        rejoined = validate_success(
            _record_election(prp_id, "PARTICIPATE", "Withdrawing our objection.")
        )
        assert rejoined["status"] == "PARTICIPATING"
        assert rejoined["version"] == noticed_version + 2

    def test_the_election_cycle_never_disturbs_the_notice_reference(self):
        """Electing and re-electing rewrites posture only, not the notice or the figures.

        PRD: "Issuing the general notice letter moves the party `IDENTIFIED → NOTIFIED` and stamps the reference the manager supplies as `notice_reference`."

        Design: Corner/state_machines/corner_prp_decline_then_participate_cycles_through_recalcitrant
        """
        world = _hobble_brook_noticed_party()
        prp_id = world["party"]["id"]

        declined = validate_success(
            _record_election(prp_id, "DECLINE", "We dispute successor liability.")
        )
        assert declined["notice_reference"] == "GNL-2027-3001"

        rejoined = validate_success(
            _record_election(prp_id, "PARTICIPATE", "Withdrawing our objection.")
        )
        assert rejoined["notice_reference"] == "GNL-2027-3001"

        final = read_party(prp_id)
        assert final["notice_reference"] == "GNL-2027-3001"
        assert final["contribution_protection"] is False
        assert final["de_minimis_eligible"] is False
        assert_percentage(
            final["volumetric_share_pct"], 0.00, "volumetric_share_pct"
        )


def _thistle_row_balloting_round():
    """Three participating parties in a balloting round, A's ACCEPT already cast.

    Verified volumes of 3,000 class I, 1,000 class III and 40 class IV tons give
    provisional weights of 80.97, 18.35 and 0.68 percent.
    """
    set_clock("2027-02-01T09:00:00Z")
    site = create_site(
        name="Thistle Row Pesticide Depot", epa_region=7, hrs_score=46.70
    )
    site = list_site_on_npl(site["id"], listing_reference="FR-2027-TRP-0201")
    prp_a = create_participating_party(
        site["id"],
        legal_name="Thistle Agro Supply",
        party_type="OWNER_OPERATOR",
        viability_score=86,
    )
    prp_b = create_participating_party(
        site["id"],
        legal_name="Row Street Blenders Inc",
        party_type="GENERATOR",
        viability_score=11,
    )
    prp_c = create_participating_party(
        site["id"],
        legal_name="Depot Cartage LLC",
        party_type="TRANSPORTER",
        viability_score=37,
    )
    add_verified_waste_in(site["id"], prp_a["id"], 3000, "I", "A", 1970)
    add_verified_waste_in(site["id"], prp_b["id"], 1000, "III", "B", 1977)
    add_verified_waste_in(site["id"], prp_c["id"], 40, "IV", "C", 1982)
    create_investigation(
        site["id"],
        exposure_medium="SOIL",
        scope_summary="OU-1 organochlorine pesticides in soil",
    )
    allocation_round = open_round(site["id"])
    open_balloting(allocation_round["id"])
    validate_success(
        api_client.cast_ballot(
            allocation_round["id"],
            factories.ballot_payload(ballot="ACCEPT"),
            make_prp_representative_headers(prp_a["id"]),
        )
    )
    return {
        "site": site,
        "prp_a": prp_a,
        "prp_b": prp_b,
        "prp_c": prp_c,
        "round": allocation_round,
    }


class TestDefunctPartyAutoAbstains:
    def test_a_defunct_party_has_its_ballot_stamped_abstain_in_a_balloting_round(self):
        """The abstention is recorded and counted, but it carries no accept weight.

        PRD: "In any round of the site that is still `DRAFTING` or `BALLOTING`, that party's share instead has its `ballot` stamped `ABSTAIN` — a conditional cascade that touches only rounds not yet adopted — and the round's `balloted_count` and `accept_share_pct` are recomputed accordingly."

        Design: Corner/state_machines/corner_defunct_party_auto_abstains_its_ballot_only_in_a_non_adopted_round
        """
        world = _thistle_row_balloting_round()
        round_id = world["round"]["id"]

        orphaned = record_defunct(
            world["prp_b"]["id"],
            defunct_reason="Dissolved in 1998; no assets and no successor.",
        )
        assert orphaned["status"] == "ORPHAN"

        share_b = share_for(round_id, world["prp_b"]["id"])
        assert share_b["ballot"] == "ABSTAIN"
        assert share_b["disposition"] == "PENDING"
        assert share_b["final_pct"] is None

        after = read_round(round_id)
        assert after["balloted_count"] == 2
        assert_percentage(after["accept_share_pct"], 80.97, "accept_share_pct")
        assert after["status"] == "BALLOTING"

        assert share_for(round_id, world["prp_c"]["id"])["ballot"] in (None, "")

    def test_the_orphan_bucket_stays_empty_while_the_round_is_unadopted(self):
        """Percentages move into the orphan bucket only at adoption.

        PRD: "In the site's adopted allocation round, that party's share captures its current `final_pct` into `pre_settlement_final_pct`, sets `final_pct` to 0.00, and moves its `disposition` from `ALLOCATED` to `ORPHANED`; the round's `orphan_share_pct` rises by exactly that amount while `allocated_share_total_pct` falls by the same amount."

        Design: Corner/state_machines/corner_defunct_party_auto_abstains_its_ballot_only_in_a_non_adopted_round
        """
        world = _thistle_row_balloting_round()
        round_id = world["round"]["id"]

        record_defunct(
            world["prp_b"]["id"],
            defunct_reason="Dissolved in 1998; no assets and no successor.",
        )

        after = read_round(round_id)
        assert_percentage(after["orphan_share_pct"], 0.00, "orphan_share_pct")
        assert_percentage(
            after["allocated_share_total_pct"], 0.00, "allocated_share_total_pct"
        )
        assert share_for(round_id, world["prp_b"]["id"])[
            "pre_settlement_final_pct"
        ] is None

        site = read_site(world["site"]["id"])
        assert site["orphan_write_off_cents"] == 0
        assert site["unrecovered_cost_cents"] == 0
        assert site["adopted_round_id"] in (None, "")
