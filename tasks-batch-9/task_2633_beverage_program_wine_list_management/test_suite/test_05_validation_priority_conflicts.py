"""Validation-priority conflicts: which of two applicable errors is reported.

Both scenarios below are requests that violate two independent rules at once,
so the response is decided by the ladder in the PRD's order-of-validation
section rather than by the shape of the request.  A publish at a frozen venue
whose target version is still a draft pits a state precondition against a
fiscal gate that share HTTP 409, so only the ``error_id`` discriminates; an
allocation receipt into an undersized bin from a distributor that has just been
put on hold pits a 422 compliance-safety check against a 409 capacity check.

Each test also drives the losing condition on its own, to prove the loser is a
real rule that fires once the winner stops applying.
"""
from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import assertions, factories as f, fixtures as fx
from test_helpers.api_client import api_client
from test_helpers.api_errors import (
    ERR_BIN_CAPACITY_EXCEEDED,
    ERR_DISTRIBUTOR_COMPLIANCE_HOLD,
    ERR_LIST_VERSION_NOT_IN_REVIEW,
    ERR_VENUE_PROGRAM_FROZEN,
)
from test_helpers.test_users import BEVERAGE_DIRECTOR_HEADERS, sommelier_headers

CLOCK = "2026-09-01T12:00:00Z"

_TARGETS = f.cogs_targets(SPARKLING=30.0, WHITE=25.0, ROSE=28.0, RED=28.0,
                          DESSERT=32.0, FORTIFIED=35.0)


def _harbor_room():
    return fx.create_venue(name="Harbor Room", venue_code="HRB",
                           cogs_target_pct_by_category=dict(_TARGETS),
                           priority_rank=1)


def _monte_bello():
    return fx.create_wine(producer="Ridge", cuvee="Monte Bello",
                          vintage_year=2019, category="RED",
                          reference_cost_cents=2400, bottle_size_ml=750,
                          case_pack=6, is_allocated=False)


def _read(getter, entity_id):
    return validate_success(getter(entity_id, BEVERAGE_DIRECTOR_HEADERS))


def _frozen_venue_with_a_second_draft():
    """Drive one venue to FROZEN through a real pour-cost run, then leave a
    fresh DRAFT version behind it.

    The published list carries one by-the-glass RED entry at 2875 cents a
    glass (2400 * 100 / 28.0 / 3 pours = 2857, lifted to the next quarter).
    Its slot sells 2 pours and pours 1 education glass, so the period's actual
    population books 2400 cents of cost against 5750 cents of revenue (41.74
    per cent) while the theoretical population sees only the sale row, 1600
    against 5750 (27.83 per cent).  The spread is 13.91 points, far above the
    6.00 freeze boundary.
    """
    fx.set_clock(CLOCK)
    venue = _harbor_room()
    bin_ = fx.create_bin(venue, bin_code="A1", zone="CELLAR",
                         capacity_bottles=48, temperature_controlled=True)
    wine = _monte_bello()
    lot = fx.create_lot(venue, wine, bin_, bottles_received=12,
                        unit_cost_cents=2400,
                        received_at="2026-08-10T00:00:00Z")
    wine_list = fx.create_wine_list(venue, name="Dinner List")
    first_draft = fx.create_draft_version(wine_list, venue)
    glass_entry = fx.add_entry(first_draft, wine, venue, sort_rank=1,
                               by_the_glass=True, pour_size_ml=177,
                               par_bottles=6, education_verified=False)
    live = fx.publish_version(first_draft, venue)
    slot = fx.open_slot(venue, glass_entry, lot, slot_index=1,
                        preservation_method="ARGON")
    fx.close_slot(slot, venue, pours_sold=2, staff_education_pours=1)
    frozen = fx.run_pour_cost(venue, "2026-09-01T00:00:00Z",
                              "2026-09-02T00:00:00Z")
    second_draft = fx.create_draft_version(wine_list, venue)
    bottle_entry = fx.add_entry(second_draft, wine, venue, sort_rank=1,
                                by_the_glass=False, par_bottles=6,
                                education_verified=False)
    return {"venue": frozen, "wine_list": wine_list, "live": live,
            "glass_entry": glass_entry, "draft": second_draft,
            "bottle_entry": bottle_entry}


class TestPublishAtFrozenVenue:
    """Publishing a DRAFT version at a FROZEN venue breaks the state
    precondition and the fiscal gate at the same time, and both refusals are
    HTTP 409, so only the error_id says which rung of the ladder answered."""

    def test_draft_state_is_reported_before_the_frozen_posture(self):
        """Publishing a version that never left DRAFT at a venue whose 13.91
        point spread has frozen the programme reports the state precondition,
        not the freeze.

        "Three preconditions guard it, and their order matters. The version must be in `IN_REVIEW`, otherwise `ERR_LIST_VERSION_NOT_IN_REVIEW`."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_business_fiscal_on_publish_at_frozen_venue
        """
        chain = _frozen_venue_with_a_second_draft()
        assertions.assert_decimal_equals(chain["venue"]["last_variance_pct"],
                                         13.91, "Venue.last_variance_pct")
        assert chain["venue"]["program_posture"] == "FROZEN", (
            "a 13.91 point spread is strictly above 6.00, so the venue freezes")

        response = api_client.publish_list_version(chain["draft"]["id"],
                                                   BEVERAGE_DIRECTOR_HEADERS)

        validate_error(response, ERR_LIST_VERSION_NOT_IN_REVIEW)
        version = _read(api_client.get_list_version, chain["draft"]["id"])
        assert version["state"] == "DRAFT", (
            "a refused publication leaves the version in DRAFT")
        assertions.assert_null_fields(version, "published_at",
                                      "published_by_user_id")
        wine_list = _read(api_client.get_wine_list, chain["wine_list"]["id"])
        assert wine_list["published_version_no"] == 1, (
            "version 1 is still the live list")

    def test_frozen_posture_surfaces_once_the_version_reaches_review(self):
        """Submitting the same version for review removes the state objection,
        and the next publication attempt is refused by the fiscal gate alone.

        "And the venue behind this version, reached through the version's wine list, must not be in `FROZEN` posture, otherwise `ERR_VENUE_PROGRAM_FROZEN`."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_business_fiscal_on_publish_at_frozen_venue
        """
        chain = _frozen_venue_with_a_second_draft()
        validate_error(
            api_client.publish_list_version(chain["draft"]["id"],
                                            BEVERAGE_DIRECTOR_HEADERS),
            ERR_LIST_VERSION_NOT_IN_REVIEW)

        submitted = validate_success(api_client.submit_list_version(
            chain["draft"]["id"], sommelier_headers(chain["venue"]["id"])))
        assert submitted["state"] == "IN_REVIEW", (
            "submission must be legal at a frozen venue")

        response = api_client.publish_list_version(chain["draft"]["id"],
                                                   BEVERAGE_DIRECTOR_HEADERS)

        validate_error(response, ERR_VENUE_PROGRAM_FROZEN)
        version = _read(api_client.get_list_version, chain["draft"]["id"])
        assert version["state"] == "IN_REVIEW", (
            "both refusals leave the version awaiting review")
        assertions.assert_null_fields(version, "published_at")
        wine_list = _read(api_client.get_wine_list, chain["wine_list"]["id"])
        assert wine_list["published_version_no"] == 1, (
            "the frozen venue never took a second live version")

    def test_core_band_entry_is_still_accepted_at_the_frozen_venue(self):
        """The draft's entry priced into CORE, so the band guard that refuses
        the top two bands never fired while the draft was being built.

        "A venue that is either `RESTRICTED` or `FROZEN` cannot accept a new list entry whose computed price band lands in the top two bands; that refusal is `ERR_VENUE_PROGRAM_RESTRICTED` (HTTP 409) and it is evaluated only after the entry's price has been computed, because the band is an output of the pricing rule rather than an input to it."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_business_fiscal_on_publish_at_frozen_venue
        """
        chain = _frozen_venue_with_a_second_draft()

        entry = _read(api_client.get_list_entry, chain["bottle_entry"]["id"])

        assert entry["price_band"] == "CORE", (
            "2400 cents of RED against a 28.0 target prices to 8600 cents, "
            "which is CORE and therefore outside the top two bands")


def _granted_claim_and_a_two_bottle_bin():
    """A GRANTED 6-bottle claim aimed at a bin that holds 2, whose distributor
    has since been put on licence hold."""
    fx.set_clock(CLOCK)
    venue = _harbor_room()
    tiny_bin = fx.create_bin(venue, bin_code="TINY", zone="CELLAR",
                             capacity_bottles=2, temperature_controlled=True)
    distributor = fx.create_distributor(name="Coastal Selections",
                                        license_number="LIC-88120",
                                        allocation_tier="A",
                                        on_time_delivery_pct=96.5)
    fx.review_distributor(distributor, "CLEARED",
                          note="Licence verified 2026-08.")
    wine = _monte_bello()
    offer = fx.create_offer(distributor, wine, offered_bottles=6,
                            unit_cost_cents=4500,
                            response_deadline="2026-09-30T00:00:00Z")
    claim = fx.file_claim(offer, venue, 6)
    fx.allocate(offer)
    fx.review_distributor(distributor, "HOLD",
                          note="Licence suspended pending audit.")
    return {"venue": venue, "bin": tiny_bin, "distributor": distributor,
            "wine": wine, "offer": offer, "claim": claim}


def _receive(chain):
    return api_client.receive_claim(
        chain["claim"]["id"],
        f.receive_claim_payload(chain["bin"]["id"], CLOCK),
        sommelier_headers(chain["venue"]["id"]))


def _lots_of_claim(claim_id):
    return assertions.get_all(api_client.list_inventory_lots,
                              BEVERAGE_DIRECTOR_HEADERS,
                              params={"source_claim_id": claim_id})


class TestAllocationReceiptOnHeldDistributor:
    """Receiving six bottles from a held distributor into a two-bottle bin
    breaks a compliance-safety rule and a capacity rule at once; the safety
    rung of the ladder answers, and the capacity rung answers only once the
    licence is clear again."""

    def test_licence_hold_answers_before_the_bin_capacity(self):
        """The receipt is refused for the distributor's licence hold, not for
        the bin that cannot hold six bottles, and nothing physical moves.

        "Compliance safety: distributor hold, offer block, prohibited by-your-own-bottle category."

        Design: Difficulty/priority_pair_validation_conflict/business_safety_beats_business_constraint_on_allocation_receipt
        """
        chain = _granted_claim_and_a_two_bottle_bin()

        response = _receive(chain)

        validate_error(response, ERR_DISTRIBUTOR_COMPLIANCE_HOLD)
        claim = _read(api_client.get_allocation_claim, chain["claim"]["id"])
        assertions.assert_fields_equal(claim, {
            "state": "GRANTED",
            "granted_bottles": 6,
        }, "AllocationClaim")
        bin_ = _read(api_client.get_cellar_bin, chain["bin"]["id"])
        assertions.assert_fields_equal(bin_, {
            "bottles_stored": 0,
            "bin_state": "ACTIVE",
        }, "CellarBin")
        assert _lots_of_claim(chain["claim"]["id"]) == [], (
            "a refused receipt must create no inventory lot")
        offer = _read(api_client.get_allocation_offer, chain["offer"]["id"])
        assertions.assert_fields_equal(offer, {
            "compliance_state": "BLOCKED",
            "fulfillment_state": "ALLOCATED",
        }, "AllocationOffer")

    def test_bin_capacity_surfaces_once_the_licence_is_cleared_again(self):
        """With the licence cleared and the offer unblocked, the same receipt
        is refused by the capacity rule the first attempt never reached.

        "Six checks guard it: the claim must be in `GRANTED` or `PARTIALLY_GRANTED` (`ERR_CLAIM_NOT_GRANTED`, HTTP 409); the offer's compliance dimension must not be `BLOCKED` (`ERR_OFFER_COMPLIANCE_BLOCKED`); the distributor must not stand in `HOLD` (`ERR_DISTRIBUTOR_COMPLIANCE_HOLD`); `received_at` must not be later than the logical clock (`ERR_RECEIVED_AT_IN_FUTURE`, HTTP 422); the nominated bin must belong to the claiming venue (`ERR_LOT_VENUE_MISMATCH`, HTTP 422); the bin's zone must not be `RESERVE` unless the wine is flagged allocated (`ERR_BIN_ZONE_MISMATCH`); and the bin's `bottles_stored` plus the incoming bottles must not exceed its `capacity_bottles` (`ERR_BIN_CAPACITY_EXCEEDED`, HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/business_safety_beats_business_constraint_on_allocation_receipt
        """
        chain = _granted_claim_and_a_two_bottle_bin()
        validate_error(_receive(chain), ERR_DISTRIBUTOR_COMPLIANCE_HOLD)

        fx.review_distributor(chain["distributor"], "CLEARED",
                              note="Audit closed, licence restored.")
        offer = _read(api_client.get_allocation_offer, chain["offer"]["id"])
        assert offer["compliance_state"] == "CLEARED", (
            "clearing the distributor unblocks its offers")

        response = _receive(chain)

        validate_error(response, ERR_BIN_CAPACITY_EXCEEDED)
        claim = _read(api_client.get_allocation_claim, chain["claim"]["id"])
        assert claim["state"] == "GRANTED", (
            "the claim is still awaiting delivery")
        assert _lots_of_claim(chain["claim"]["id"]) == [], (
            "no lot may exist while the receipt keeps failing")
