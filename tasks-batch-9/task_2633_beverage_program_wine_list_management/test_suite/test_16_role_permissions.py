"""Role authority on the beverage program: which role owns which write, how a
right-role/wrong-entity refusal differs from a wrong-role refusal, and where the
four-eyes rule keys on the acting user id rather than on the role.

Every test in this file translates one instance of the `rbac` section of
SCAFFOLD_CORNER_DESIGN.yaml.
"""
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_client import api_client
from test_helpers.api_errors import (
    ERR_FORBIDDEN_ROLE,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_VENUE_SCOPE_VIOLATION,
    ERR_WRITE_OFF_NOT_APPROVED,
)
from test_helpers.test_users import (
    BEVERAGE_DIRECTOR_HEADERS,
    COMPLIANCE_OFFICER_HEADERS,
    CONTROLLER_HEADERS,
    distributor_rep_headers,
    second_controller_headers,
    second_director_headers,
    sommelier_headers,
)

CLOCK = "2026-09-01T12:00:00Z"

# The venue used throughout this file, with the RED target at 28.00 percent.
CATEGORY_TARGETS = {
    "SPARKLING": 30.0,
    "WHITE": 25.0,
    "ROSE": 28.0,
    "RED": 28.0,
    "DESSERT": 32.0,
    "FORTIFIED": 35.0,
}


def _venue(**overrides):
    return fx.create_venue(cogs_target_pct_by_category=dict(CATEGORY_TARGETS),
                           **overrides)


def _wine(**overrides):
    base = {
        "producer": "Ridge",
        "cuvee": "Monte Bello",
        "vintage_year": 2019,
        "category": "RED",
        "reference_cost_cents": 2400,
        "bottle_size_ml": 750,
        "case_pack": 6,
        "is_allocated": False,
    }
    base.update(overrides)
    return fx.create_wine(**base)


def _draft_with_one_entry(venue=None, wine=None):
    """Venue + RED wine + wine list + DRAFT version carrying one entry."""
    venue = venue or _venue()
    wine = wine or _wine()
    wine_list = fx.create_wine_list(venue)
    version = fx.create_draft_version(wine_list, venue)
    entry = fx.add_entry(version, wine, venue, sort_rank=1,
                         by_the_glass=False, par_bottles=6)
    return {"venue": venue, "wine": wine, "wine_list": wine_list,
            "version": version, "entry": entry}


def _stocked_venue(bottles=12, unit_cost_cents=2400):
    """Venue + bin A1 + RED wine + one ON_HAND lot received before the clock."""
    venue = _venue()
    bin_ = fx.create_bin(venue, bin_code="A1", zone="CELLAR",
                         capacity_bottles=48, temperature_controlled=True)
    wine = _wine()
    lot = fx.create_lot(venue, wine, bin_, bottles_received=bottles,
                        unit_cost_cents=unit_cost_cents,
                        received_at="2026-08-10T00:00:00Z")
    return {"venue": venue, "bin": bin_, "wine": wine, "lot": lot}


class TestDirectorExclusivePublicationAndPourCost:
    """Publication and the pour-cost run belong to the BeverageDirector alone,
    even though the sommelier owns everything upstream of them."""

    @staticmethod
    def _in_review():
        fx.set_clock(CLOCK)
        chain = _draft_with_one_entry()
        chain["version"] = fx.submit_version(chain["version"], chain["venue"])
        return chain

    def test_sommelier_cannot_publish_the_version_it_submitted(self):
        """The sommelier who submitted a version cannot publish it, because
        publication is not on the sommelier's role list at all.

        "Publication is director-exclusive and carries no body."

        Design: Corner/rbac/director_publishes_and_runs_pour_cost_others_cannot_do_either
        """
        chain = self._in_review()
        venue_id = chain["venue"]["id"]
        response = api_client.publish_list_version(chain["version"]["id"],
                                                   sommelier_headers(venue_id))
        validate_error(response, ERR_FORBIDDEN_ROLE)
        after = validate_success(
            api_client.get_list_version(chain["version"]["id"],
                                        BEVERAGE_DIRECTOR_HEADERS))
        assert after["state"] == "IN_REVIEW", after["state"]
        assert after["published_at"] is None, after["published_at"]

    def test_controller_cannot_publish_a_reviewed_version(self):
        """A Controller never builds or publishes lists, so its publish attempt
        is refused on the role.

        "Publication is director-exclusive and carries no body."

        Design: Corner/rbac/director_publishes_and_runs_pour_cost_others_cannot_do_either
        """
        chain = self._in_review()
        response = api_client.publish_list_version(chain["version"]["id"],
                                                   CONTROLLER_HEADERS)
        validate_error(response, ERR_FORBIDDEN_ROLE)
        after = validate_success(
            api_client.get_list_version(chain["version"]["id"],
                                        BEVERAGE_DIRECTOR_HEADERS))
        assert after["state"] == "IN_REVIEW", after["state"]
        assert after["published_at"] is None, after["published_at"]

    def test_compliance_officer_cannot_publish_a_reviewed_version(self):
        """The compliance officer is read-only outside licence clearance, so it
        cannot publish a reviewed version either.

        "Publication is director-exclusive and carries no body."

        Design: Corner/rbac/director_publishes_and_runs_pour_cost_others_cannot_do_either
        """
        chain = self._in_review()
        response = api_client.publish_list_version(chain["version"]["id"],
                                                   COMPLIANCE_OFFICER_HEADERS)
        validate_error(response, ERR_FORBIDDEN_ROLE)
        after = validate_success(
            api_client.get_list_version(chain["version"]["id"],
                                        BEVERAGE_DIRECTOR_HEADERS))
        assert after["state"] == "IN_REVIEW", after["state"]
        assert after["published_at"] is None, after["published_at"]

    def test_controller_pour_cost_run_is_refused_on_role_before_the_period_check(self):
        """A Controller's pour-cost run is refused for the role even when the
        supplied period is also inverted, and the venue's variance is untouched.

        "Authorization is evaluated after the request is authenticated and before any payload or state check, and a caller outside the listed roles receives `ERR_FORBIDDEN_ROLE` with HTTP 403."

        Design: Corner/rbac/director_publishes_and_runs_pour_cost_others_cannot_do_either
        """
        chain = self._in_review()
        venue_id = chain["venue"]["id"]
        response = api_client.create_pour_cost_run(
            venue_id,
            f.pour_cost_run_payload("2026-09-01T14:00:00Z", "2026-09-01T10:00:00Z"),
            CONTROLLER_HEADERS)
        validate_error(response, ERR_FORBIDDEN_ROLE)
        venue = fx.get_venue(venue_id)
        assert float(venue["last_variance_pct"]) == 0.00, venue["last_variance_pct"]
        assert venue["last_pour_cost_run_at"] is None, venue["last_pour_cost_run_at"]

    def test_director_publishes_the_reviewed_version(self):
        """The director, whose id differs from the sommelier submitter, publishes
        the version and the logical clock is stamped onto it.

        "It stamps `published_at` and `printed_at` with the logical clock and `published_by_user_id` with the acting `X-User-ID`."

        Design: Corner/rbac/director_publishes_and_runs_pour_cost_others_cannot_do_either
        """
        chain = self._in_review()
        published = validate_success(
            api_client.publish_list_version(chain["version"]["id"],
                                            BEVERAGE_DIRECTOR_HEADERS))
        assert published["state"] == "PUBLISHED", published["state"]
        assert published["published_at"].startswith("2026-09-01T12:00:00"), (
            published["published_at"])
        assert published["printed_at"].startswith("2026-09-01T12:00:00"), (
            published["printed_at"])
        assert published["version_no"] == 1, published["version_no"]


BOGUS_WINE_ID = "00000000-0000-4000-8000-000000000000"


class TestSommelierExclusiveVenueWrites:
    """Building a list is the sommelier's exclusive act. A wrong role is refused
    with ERR_FORBIDDEN_ROLE; the right role at the wrong venue is refused with
    ERR_VENUE_SCOPE_VIOLATION, and that refusal precedes body FK resolution."""

    @staticmethod
    def _two_venues_and_a_draft():
        fx.set_clock(CLOCK)
        chain = _draft_with_one_entry()
        chain["other_venue"] = _venue()
        chain["expected"] = fx.current_version(api_client.get_list_version,
                                               chain["version"]["id"])
        return chain

    def test_director_cannot_add_an_entry_to_a_draft_version(self):
        """Adding a wine to a draft is sommelier-exclusive, so the director who
        will later publish the list still cannot compose it.

        "Adding a wine to a draft is a sommelier's job and is the single richest computation in the system."

        Design: Corner/rbac/sommelier_owns_venue_writes_and_peers_cannot_reach_them
        """
        chain = self._two_venues_and_a_draft()
        payload = f.list_entry_payload(chain["wine"]["id"], chain["expected"],
                                       sort_rank=2, by_the_glass=False,
                                       par_bottles=6)
        response = api_client.create_list_entry(chain["version"]["id"], payload,
                                                BEVERAGE_DIRECTOR_HEADERS)
        validate_error(response, ERR_FORBIDDEN_ROLE)
        version = validate_success(
            api_client.get_list_version(chain["version"]["id"],
                                        BEVERAGE_DIRECTOR_HEADERS))
        assert version["entry_count"] == 1, version["entry_count"]

    def test_controller_cannot_patch_a_draft_entry(self):
        """A Controller is refused on the entry PATCH for its role, and the
        entry's tasting note is left exactly as the sommelier wrote it.

        "Authorization is evaluated after the request is authenticated and before any payload or state check, and a caller outside the listed roles receives `ERR_FORBIDDEN_ROLE` with HTTP 403."

        Design: Corner/rbac/sommelier_owns_venue_writes_and_peers_cannot_reach_them
        """
        chain = self._two_venues_and_a_draft()
        before = chain["entry"]["tasting_note"]
        response = api_client.patch_list_entry(
            chain["entry"]["id"], {"tasting_note": "Controller edit attempt."},
            CONTROLLER_HEADERS)
        validate_error(response, ERR_FORBIDDEN_ROLE)
        after = validate_success(
            api_client.get_list_entry(chain["entry"]["id"],
                                      BEVERAGE_DIRECTOR_HEADERS))
        assert after["tasting_note"] == before, after["tasting_note"]

    def test_foreign_sommelier_hears_venue_scope_before_the_body_wine_lookup(self):
        """A sommelier of another venue posting an entry with a deliberately
        nonexistent wine_id hears about scope, not about the missing wine.

        "A sommelier acting on anything that resolves to a different venue is rejected with `ERR_VENUE_SCOPE_VIOLATION` (HTTP 403), and that rejection is evaluated before any existence check on foreign keys carried in the request body."

        Design: Corner/rbac/sommelier_owns_venue_writes_and_peers_cannot_reach_them
        """
        chain = self._two_venues_and_a_draft()
        payload = f.list_entry_payload(BOGUS_WINE_ID, chain["expected"],
                                       sort_rank=3, by_the_glass=False,
                                       par_bottles=6)
        response = api_client.create_list_entry(
            chain["version"]["id"], payload,
            sommelier_headers(chain["other_venue"]["id"]))
        validate_error(response, ERR_VENUE_SCOPE_VIOLATION)
        version = validate_success(
            api_client.get_list_version(chain["version"]["id"],
                                        BEVERAGE_DIRECTOR_HEADERS))
        assert version["entry_count"] == 1, version["entry_count"]

    def test_controller_cannot_quote_corkage(self):
        """The corkage quote is a sommelier-only capability, so a Controller
        asking for one is refused on the role.

        "Authorization is evaluated after the request is authenticated and before any payload or state check, and a caller outside the listed roles receives `ERR_FORBIDDEN_ROLE` with HTTP 403."

        Design: Corner/rbac/sommelier_owns_venue_writes_and_peers_cannot_reach_them
        """
        chain = self._two_venues_and_a_draft()
        response = api_client.quote_corkage(
            chain["venue"]["id"],
            f.corkage_payload(byo_bottle_count=1, bottles_purchased_from_list=2,
                              party_size=4, byo_categories=["RED"]),
            CONTROLLER_HEADERS)
        validate_error(response, ERR_FORBIDDEN_ROLE)

    def test_owning_sommelier_patches_its_own_entry(self):
        """The venue's own sommelier amends the entry it created, and every
        refusal above left the version's entry count untouched.

        "The editable fields are `by_the_glass`, `pour_size_ml`, `tasting_note`, `education_verified`, `par_bottles` and `sort_rank`."

        Design: Corner/rbac/sommelier_owns_venue_writes_and_peers_cannot_reach_them
        """
        chain = self._two_venues_and_a_draft()
        patched = validate_success(api_client.patch_list_entry(
            chain["entry"]["id"],
            {"tasting_note": "Cassis, graphite, cedar.",
             "education_verified": True},
            sommelier_headers(chain["venue"]["id"])))
        assert patched["education_verified"] is True, patched["education_verified"]
        assert patched["tasting_note"] == "Cassis, graphite, cedar.", (
            patched["tasting_note"])
        version = validate_success(
            api_client.get_list_version(chain["version"]["id"],
                                        BEVERAGE_DIRECTOR_HEADERS))
        assert version["entry_count"] == 1, version["entry_count"]


class TestControllerExclusiveFiscalApprovals:
    """Approval, rejection and reversal of a spoilage write-off are the
    Controller's alone, and the role check runs ahead of the state check."""

    @staticmethod
    def _submitted_write_off():
        fx.set_clock(CLOCK)
        chain = _stocked_venue(bottles=12, unit_cost_cents=2400)
        chain["write_off"] = fx.submit_write_off(
            chain["venue"], chain["lot"], bottles=2, reason_code="CORKED",
            narrative="Two corked bottles found in the cellar.")
        return chain

    def test_director_cannot_approve_a_write_off(self):
        """The director who owns every other approval in the system cannot sign
        off a loss the cellar absorbs.

        "A `Controller` is the group financial controller: the sole approver, rejecter and reverser of spoilage write-offs, the sole settler and voider of wine dinners, and the sole handler of pour-cost variance investigations."

        Design: Corner/rbac/controller_owns_fiscal_approvals_and_others_cannot_approve
        """
        chain = self._submitted_write_off()
        response = api_client.approve_write_off(chain["write_off"]["id"],
                                               BEVERAGE_DIRECTOR_HEADERS)
        validate_error(response, ERR_FORBIDDEN_ROLE)
        after = validate_success(api_client.get_spoilage_write_off(
            chain["write_off"]["id"], BEVERAGE_DIRECTOR_HEADERS))
        assert after["state"] == "SUBMITTED", after["state"]
        assert after["cogs_cents"] == 0, after["cogs_cents"]

    def test_sommelier_cannot_reject_a_write_off_it_proposed(self):
        """Proposing a write-off is shared with the sommelier but resolving one
        is not, so the sommelier cannot reject its own proposal.

        "A `Controller` is the group financial controller: the sole approver, rejecter and reverser of spoilage write-offs, the sole settler and voider of wine dinners, and the sole handler of pour-cost variance investigations."

        Design: Corner/rbac/controller_owns_fiscal_approvals_and_others_cannot_approve
        """
        chain = self._submitted_write_off()
        response = api_client.reject_write_off(
            chain["write_off"]["id"],
            f.note_payload("Sommelier self-reject attempt."),
            sommelier_headers(chain["venue"]["id"]))
        validate_error(response, ERR_FORBIDDEN_ROLE)
        after = validate_success(api_client.get_spoilage_write_off(
            chain["write_off"]["id"], BEVERAGE_DIRECTOR_HEADERS))
        assert after["state"] == "SUBMITTED", after["state"]
        assert after["cogs_cents"] == 0, after["cogs_cents"]

    def test_compliance_officer_reversal_is_refused_on_the_role_not_the_state(self):
        """The compliance officer reversing a write-off that is not even APPROVED
        hears about its role, because the role check precedes the state check.

        "Authorization is evaluated after the request is authenticated and before any payload or state check, and a caller outside the listed roles receives `ERR_FORBIDDEN_ROLE` with HTTP 403."

        Design: Corner/rbac/controller_owns_fiscal_approvals_and_others_cannot_approve
        """
        chain = self._submitted_write_off()
        response = api_client.reverse_write_off(
            chain["write_off"]["id"],
            f.note_payload("Compliance reversal attempt."),
            COMPLIANCE_OFFICER_HEADERS)
        validate_error(response, ERR_FORBIDDEN_ROLE)

    def test_controller_reversal_of_an_unapproved_write_off_hits_the_state_check(self):
        """The same reversal by the Controller passes the role check and is then
        refused for the state, and the lot has given up nothing.

        "It is controller-exclusive, carries a mandatory `note` stored as `resolution_note`, and requires the write-off to be in `APPROVED` (`ERR_WRITE_OFF_NOT_APPROVED`, HTTP 409) and the lot to be either `ON_HAND` or `DEPLETED` — a lot that has already gone terminally `WRITTEN_OFF` is frozen and the reversal is refused with `ERR_LOT_NOT_ON_HAND`."

        Design: Corner/rbac/controller_owns_fiscal_approvals_and_others_cannot_approve
        """
        chain = self._submitted_write_off()
        response = api_client.reverse_write_off(
            chain["write_off"]["id"], f.note_payload("Reverse before approval."),
            CONTROLLER_HEADERS)
        validate_error(response, ERR_WRITE_OFF_NOT_APPROVED)
        lot = validate_success(api_client.get_inventory_lot(
            chain["lot"]["id"], BEVERAGE_DIRECTOR_HEADERS))
        assert lot["bottles_on_hand"] == 12, lot["bottles_on_hand"]

    def test_controller_approves_the_write_off_and_the_cost_lands(self):
        """The Controller approves the write-off, the two bottles are priced out
        of the nominated lot and the lot gives them up.

        "On approval the write-off moves `SUBMITTED → APPROVED`, records `approved_by_user_id` as the acting `X-User-ID`, and computes `cogs_cents` by pricing the written-off bottles out of that one nominated lot under the venue's costing method."

        Design: Corner/rbac/controller_owns_fiscal_approvals_and_others_cannot_approve
        """
        chain = self._submitted_write_off()
        approved = validate_success(api_client.approve_write_off(
            chain["write_off"]["id"], CONTROLLER_HEADERS))
        assert approved["state"] == "APPROVED", approved["state"]
        assert approved["cogs_cents"] == 4800, approved["cogs_cents"]
        lot = validate_success(api_client.get_inventory_lot(
            chain["lot"]["id"], BEVERAGE_DIRECTOR_HEADERS))
        assert lot["bottles_on_hand"] == 10, lot["bottles_on_hand"]


class TestComplianceOfficerOwnsLicenceClearance:
    """Licence clearance is the compliance officer's only write, and it is the
    only role that has it -- not even the director who registered the house."""

    @staticmethod
    def _pending_distributor():
        fx.set_clock(CLOCK)
        distributor = fx.create_distributor(name="Coastal Selections",
                                            license_number="LIC-0001",
                                            allocation_tier="A")
        wine = _wine(cuvee="Monte Bello", reference_cost_cents=5000,
                     is_allocated=True)
        return {"distributor": distributor, "wine": wine}

    def test_controller_cannot_record_a_compliance_review(self):
        """A Controller recording a licence decision is refused, and the
        distributor stays where its registration left it.

        "Licence clearance belongs to the `ComplianceOfficer` alone."

        Design: Corner/rbac/compliance_officer_owns_licence_clearance_and_cannot_trade
        """
        chain = self._pending_distributor()
        response = api_client.create_compliance_review(
            chain["distributor"]["id"],
            f.compliance_review_payload("CLEARED", note="Controller attempt."),
            CONTROLLER_HEADERS)
        validate_error(response, ERR_FORBIDDEN_ROLE)
        after = validate_success(api_client.get_distributor(
            chain["distributor"]["id"], BEVERAGE_DIRECTOR_HEADERS))
        assert after["compliance_state"] == "PENDING_REVIEW", (
            after["compliance_state"])

    def test_director_cannot_record_a_compliance_review(self):
        """The director owns distributor master data but not its licence
        standing, so its own review attempt is refused on the role.

        "Licence clearance belongs to the `ComplianceOfficer` alone."

        Design: Corner/rbac/compliance_officer_owns_licence_clearance_and_cannot_trade
        """
        chain = self._pending_distributor()
        response = api_client.create_compliance_review(
            chain["distributor"]["id"],
            f.compliance_review_payload("CLEARED", note="Director attempt."),
            BEVERAGE_DIRECTOR_HEADERS)
        validate_error(response, ERR_FORBIDDEN_ROLE)
        after = validate_success(api_client.get_distributor(
            chain["distributor"]["id"], BEVERAGE_DIRECTOR_HEADERS))
        assert after["compliance_state"] == "PENDING_REVIEW", (
            after["compliance_state"])

    def test_compliance_officer_cannot_post_an_allocation_offer(self):
        """The role that clears a distributor cannot then trade on its behalf:
        the offer POST is refused on the role, before any scope comparison.

        "Authorization is evaluated after the request is authenticated and before any payload or state check, and a caller outside the listed roles receives `ERR_FORBIDDEN_ROLE` with HTTP 403."

        Design: Corner/rbac/compliance_officer_owns_licence_clearance_and_cannot_trade
        """
        chain = self._pending_distributor()
        payload = f.allocation_offer_payload(
            chain["distributor"]["id"], chain["wine"]["id"],
            offered_bottles=10, unit_cost_cents=5000,
            response_deadline="2026-09-30T00:00:00Z")
        response = api_client.create_allocation_offer(payload,
                                                      COMPLIANCE_OFFICER_HEADERS)
        validate_error(response, ERR_FORBIDDEN_ROLE)
        offers, meta = validate_paginated(
            api_client.list_allocation_offers(BEVERAGE_DIRECTOR_HEADERS))
        assert meta["total_count"] == 0, meta["total_count"]
        assert offers == [], offers

    def test_compliance_officer_records_the_clearance(self):
        """The officer's own review clears the distributor and stores the note it
        supplied.

        "A decision of `CLEARED` moves a distributor `PENDING_REVIEW → CLEARED` or `HOLD → CLEARED`; a decision of `HOLD` moves it `PENDING_REVIEW → HOLD` or `CLEARED → HOLD`."

        Design: Corner/rbac/compliance_officer_owns_licence_clearance_and_cannot_trade
        """
        chain = self._pending_distributor()
        note = "Licence LIC-0001 verified against the state register."
        reviewed = validate_success(api_client.create_compliance_review(
            chain["distributor"]["id"],
            f.compliance_review_payload("CLEARED", note=note),
            COMPLIANCE_OFFICER_HEADERS))
        assert reviewed["compliance_state"] == "CLEARED", (
            reviewed["compliance_state"])
        assert reviewed["last_review_note"] == note, reviewed["last_review_note"]

    def test_compliance_officer_is_read_capable_but_write_limited(self):
        """The officer can read the distributor it just cleared, so the refusals
        above are role-scoped rather than a blanket lockout.

        "A `ComplianceOfficer` is the alcohol-licensing compliance officer and the only authority over distributor licence clearance and holds; it is read-only everywhere else, and its reviews move only the compliance dimension of an offer."

        Design: Corner/rbac/compliance_officer_owns_licence_clearance_and_cannot_trade
        """
        chain = self._pending_distributor()
        read = validate_success(api_client.get_distributor(
            chain["distributor"]["id"], COMPLIANCE_OFFICER_HEADERS))
        assert read["id"] == chain["distributor"]["id"], read["id"]
        assert read["compliance_state"] == "PENDING_REVIEW", (
            read["compliance_state"])


class TestDistributorRepIsConfinedToItsOwnOffers:
    """The distributor rep is the only actor outside the restaurant group: it
    posts and reads its own offers and is absent from every venue-side endpoint,
    including the reads the other four roles share."""

    @staticmethod
    def _venue_and_house():
        fx.set_clock(CLOCK)
        venue = _venue()
        bin_ = fx.create_bin(venue, bin_code="A1", zone="CELLAR",
                             capacity_bottles=48, temperature_controlled=True)
        distributor = fx.create_distributor(name="Coastal Selections",
                                            license_number="LIC-0001",
                                            allocation_tier="A")
        wine = _wine(reference_cost_cents=5000, is_allocated=True)
        return {"venue": venue, "bin": bin_, "distributor": distributor,
                "wine": wine}

    @staticmethod
    def _post_own_offer(chain):
        payload = f.allocation_offer_payload(
            chain["distributor"]["id"], chain["wine"]["id"],
            offered_bottles=10, unit_cost_cents=5000,
            response_deadline="2026-09-30T00:00:00Z")
        return api_client.create_allocation_offer(
            payload, distributor_rep_headers(chain["distributor"]["id"]))

    def test_rep_posts_an_offer_for_its_own_distributor(self):
        """The rep's own offer is created with both dimensions at their declared
        initial values, the licence dimension still awaiting a check.

        "`compliance_state` tracks the licence dimension and is initialised to `PENDING_LICENSE_CHECK`, with one exception — when the offering distributor's standing is already `CLEARED` at the moment the offer is posted, the offer's `compliance_state` is set to `CLEARED` at creation."

        Design: Corner/rbac/distributor_rep_cannot_write_or_read_venue_side_resources
        """
        chain = self._venue_and_house()
        offer = validate_success(self._post_own_offer(chain), 201)
        assert offer["fulfillment_state"] == "OPEN", offer["fulfillment_state"]
        assert offer["compliance_state"] == "PENDING_LICENSE_CHECK", (
            offer["compliance_state"])

    def test_rep_cannot_create_an_inventory_lot_or_a_cellar_bin(self):
        """Both venue-side writes are refused on the role, and the cellar is left
        with nothing but the bin the sommelier built.

        "A distributor representative appears on no write endpoint under cellar bins, inventory lots, list versions, by-the-glass slots, spoilage write-offs or wine dinner events; those attempts return `ERR_FORBIDDEN_ROLE`."

        Design: Corner/rbac/distributor_rep_cannot_write_or_read_venue_side_resources
        """
        chain = self._venue_and_house()
        rep = distributor_rep_headers(chain["distributor"]["id"])
        lot_payload = f.inventory_lot_payload(
            chain["venue"]["id"], chain["wine"]["id"], chain["bin"]["id"],
            bottles_received=6, unit_cost_cents=5000,
            received_at="2026-08-20T00:00:00Z")
        validate_error(api_client.create_inventory_lot(lot_payload, rep),
                       ERR_FORBIDDEN_ROLE)
        validate_error(
            api_client.create_cellar_bin(
                chain["venue"]["id"],
                f.cellar_bin_payload(bin_code="B2", zone="CELLAR",
                                     capacity_bottles=24),
                rep),
            ERR_FORBIDDEN_ROLE)
        lots, lot_meta = validate_paginated(
            api_client.list_inventory_lots(BEVERAGE_DIRECTOR_HEADERS))
        assert lot_meta["total_count"] == 0, lot_meta["total_count"]
        assert lots == [], lots
        bins, bin_meta = validate_paginated(api_client.list_cellar_bins(
            BEVERAGE_DIRECTOR_HEADERS,
            params={"venue_id": chain["venue"]["id"]}))
        assert bin_meta["total_count"] == 1, bin_meta["total_count"]
        assert [row["bin_code"] for row in bins] == ["A1"], bins

    def test_rep_cannot_read_venue_side_list_entries(self):
        """The rep is excluded from the venue-side reads as well, unlike the
        other four roles which all appear on the list-entries collection.

        "Authorization is evaluated after the request is authenticated and before any payload or state check, and a caller outside the listed roles receives `ERR_FORBIDDEN_ROLE` with HTTP 403."

        Design: Corner/rbac/distributor_rep_cannot_write_or_read_venue_side_resources
        """
        chain = self._venue_and_house()
        response = api_client.list_list_entries(
            distributor_rep_headers(chain["distributor"]["id"]))
        validate_error(response, ERR_FORBIDDEN_ROLE)

    def test_rep_can_read_its_own_offer(self):
        """The rep reads the offer it posted, so the refusals above are scoped to
        the endpoints the role is absent from and not a blanket lockout.

        "Authorization is evaluated after the request is authenticated and before any payload or state check, and a caller outside the listed roles receives `ERR_FORBIDDEN_ROLE` with HTTP 403."

        Design: Corner/rbac/distributor_rep_cannot_write_or_read_venue_side_resources
        """
        chain = self._venue_and_house()
        offer = validate_success(self._post_own_offer(chain), 201)
        read = validate_success(api_client.get_allocation_offer(
            offer["id"], distributor_rep_headers(chain["distributor"]["id"])))
        assert read["id"] == offer["id"], read["id"]
        assert read["unallocated_bottles"] == 10, read["unallocated_bottles"]


class TestSegregationOfDutiesKeysOnTheActingUserId:
    """The four-eyes rule compares X-User-ID against the recorded submitter, so a
    different user of the very same role succeeds where the submitter is
    refused."""

    @staticmethod
    def _draft_submitted_by(headers):
        fx.set_clock(CLOCK)
        chain = _draft_with_one_entry()
        chain["submitted"] = validate_success(
            api_client.submit_list_version(chain["version"]["id"], headers))
        return chain

    def test_a_director_may_submit_a_draft_for_review(self):
        """Submission is genuinely shared with the director, and it records that
        director as the submitter.

        "On success the version moves `DRAFT → IN_REVIEW`, `submitted_by_user_id` is set to the acting `X-User-ID`, overwriting whatever a previous submission recorded, and the version's own `version` increments by 1."

        Design: Corner/rbac/same_user_cannot_publish_own_submission_or_approve_own_write_off
        """
        second = second_director_headers()
        chain = self._draft_submitted_by(second)
        submitted = chain["submitted"]
        assert submitted["state"] == "IN_REVIEW", submitted["state"]
        assert submitted["submitted_by_user_id"] == second["X-User-ID"], (
            submitted["submitted_by_user_id"])

    def test_a_director_cannot_publish_its_own_submission(self):
        """The director that submitted the version is refused on publication by
        identity even though its role is on the endpoint and the state is right.

        "Publishing a list version and approving or rejecting a spoilage write-off are both refused with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403) when the acting `X-User-ID` equals the identifier recorded as the submitter on the object being acted on."

        Design: Corner/rbac/same_user_cannot_publish_own_submission_or_approve_own_write_off
        """
        second = second_director_headers()
        chain = self._draft_submitted_by(second)
        response = api_client.publish_list_version(chain["version"]["id"], second)
        validate_error(response, ERR_SEGREGATION_OF_DUTIES)
        after = validate_success(api_client.get_list_version(
            chain["version"]["id"], BEVERAGE_DIRECTOR_HEADERS))
        assert after["state"] == "IN_REVIEW", after["state"]
        assert after["published_at"] is None, after["published_at"]

    def test_a_second_director_publishes_the_same_version(self):
        """A different director publishes the very same submission, proving the
        rule compares user ids rather than roles.

        "The acting `X-User-ID` must differ from the recorded `submitted_by_user_id`, otherwise `ERR_SEGREGATION_OF_DUTIES` — a director who both submits and tries to publish is blocked by identity, not by role."

        Design: Corner/rbac/same_user_cannot_publish_own_submission_or_approve_own_write_off
        """
        chain = self._draft_submitted_by(second_director_headers())
        published = validate_success(api_client.publish_list_version(
            chain["version"]["id"], BEVERAGE_DIRECTOR_HEADERS))
        assert published["state"] == "PUBLISHED", published["state"]
        assert published["published_by_user_id"] == (
            BEVERAGE_DIRECTOR_HEADERS["X-User-ID"]), (
                published["published_by_user_id"])

    def test_a_controller_cannot_approve_its_own_write_off(self):
        """A Controller may propose a write-off, and that is exactly why it is
        then refused on the approval of that same proposal.

        "Because proposing a write-off is shared between the sommelier and the controller while approval is controller-exclusive, a controller who proposes a write-off cannot approve or reject it."

        Design: Corner/rbac/same_user_cannot_publish_own_submission_or_approve_own_write_off
        """
        fx.set_clock(CLOCK)
        chain = _stocked_venue(bottles=12, unit_cost_cents=2400)
        write_off = validate_success(api_client.create_spoilage_write_off(
            f.write_off_payload(
                chain["venue"]["id"], chain["lot"]["id"], bottles=2,
                reason_code="CORKED",
                narrative="Controller-submitted spoilage after a cellar audit."),
            CONTROLLER_HEADERS), 201)
        response = api_client.approve_write_off(write_off["id"],
                                                CONTROLLER_HEADERS)
        validate_error(response, ERR_SEGREGATION_OF_DUTIES)
        lot = validate_success(api_client.get_inventory_lot(
            chain["lot"]["id"], BEVERAGE_DIRECTOR_HEADERS))
        assert lot["bottles_on_hand"] == 12, lot["bottles_on_hand"]

    def test_a_second_controller_approves_the_same_write_off(self):
        """A different Controller approves the proposal the first one filed, and
        the cost lands on the nominated lot.

        "On approval the write-off moves `SUBMITTED → APPROVED`, records `approved_by_user_id` as the acting `X-User-ID`, and computes `cogs_cents` by pricing the written-off bottles out of that one nominated lot under the venue's costing method."

        Design: Corner/rbac/same_user_cannot_publish_own_submission_or_approve_own_write_off
        """
        fx.set_clock(CLOCK)
        chain = _stocked_venue(bottles=12, unit_cost_cents=2400)
        write_off = validate_success(api_client.create_spoilage_write_off(
            f.write_off_payload(
                chain["venue"]["id"], chain["lot"]["id"], bottles=2,
                reason_code="CORKED",
                narrative="Controller-submitted spoilage after a cellar audit."),
            CONTROLLER_HEADERS), 201)
        second = second_controller_headers()
        approved = validate_success(
            api_client.approve_write_off(write_off["id"], second))
        assert approved["state"] == "APPROVED", approved["state"]
        assert approved["cogs_cents"] == 4800, approved["cogs_cents"]
        assert approved["approved_by_user_id"] == second["X-User-ID"], (
            approved["approved_by_user_id"])
        lot = validate_success(api_client.get_inventory_lot(
            chain["lot"]["id"], BEVERAGE_DIRECTOR_HEADERS))
        assert lot["bottles_on_hand"] == 10, lot["bottles_on_hand"]
