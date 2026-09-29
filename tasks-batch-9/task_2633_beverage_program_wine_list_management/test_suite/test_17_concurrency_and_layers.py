"""The two optimistic-concurrency guards of the beverage program: the offer
version token a claimant must carry and the list-version token an entry writer
must carry, plus where those guards sit relative to the uniqueness checks.

Every test in this file translates one instance of the
`cross_cutting_complexity_layers` section of SCAFFOLD_CORNER_DESIGN.yaml.
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
    ERR_DUPLICATE_LIST_ENTRY_WINE,
    ERR_STALE_VERSION,
)
from test_helpers.test_users import BEVERAGE_DIRECTOR_HEADERS, sommelier_headers

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


class TestOfferVersionGuardOnClaimCreation:
    """Two venues claiming against one open offer: the second claimant's request
    is legitimate in every other respect, so only the version token can stop
    it."""

    @staticmethod
    def _open_offer():
        fx.set_clock("2026-09-01T00:00:00Z")
        harbor = _venue(priority_rank=1)
        garden = _venue(priority_rank=2)
        distributor = fx.create_distributor(name="Coastal Selections",
                                            license_number="LIC-0001",
                                            allocation_tier="A")
        wine = _wine(reference_cost_cents=5000, is_allocated=True)
        offer = fx.create_offer(distributor, wine, offered_bottles=10,
                                unit_cost_cents=5000,
                                response_deadline="2026-09-30T00:00:00Z")
        return {"harbor": harbor, "garden": garden, "distributor": distributor,
                "wine": wine, "offer": offer, "offer_version": offer["version"]}

    @staticmethod
    def _claim(offer, venue, requested_bottles, expected_offer_version):
        return api_client.create_allocation_claim(
            offer["id"],
            f.allocation_claim_payload(venue["id"], requested_bottles,
                                       expected_offer_version),
            sommelier_headers(venue["id"]))

    def test_the_first_claim_bumps_the_parent_offer_version(self):
        """Filing a claim is a write on the parent offer, so the offer's version
        advances by exactly one and its claim count rises.

        "A successful claim is created in state `REQUESTED` with `granted_bottles` 0, `raw_share` 0.0000 and `remainder_awarded` false, and it increments the parent offer's `claim_count` by 1 and the offer's `version` by 1 — which is precisely why the next claimant's guard value must be re-read."

        Design: Corner/cross_cutting_complexity_layers/occ_claim_against_stale_offer_version_returns_412
        """
        chain = self._open_offer()
        claim = validate_success(
            self._claim(chain["offer"], chain["harbor"], 4,
                        chain["offer_version"]), 201)
        assert claim["state"] == "REQUESTED", claim["state"]
        offer = validate_success(api_client.get_allocation_offer(
            chain["offer"]["id"], BEVERAGE_DIRECTOR_HEADERS))
        assert offer["version"] == chain["offer_version"] + 1, offer["version"]
        assert offer["claim_count"] == 1, offer["claim_count"]

    def test_a_claim_carrying_the_pre_claim_token_is_rejected_as_stale(self):
        """The second venue sized its request against the offer as it stood
        before the first claim, and that token no longer matches.

        "If that value does not equal the offer's current `version`, the create is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/occ_claim_against_stale_offer_version_returns_412
        """
        chain = self._open_offer()
        validate_success(self._claim(chain["offer"], chain["harbor"], 4,
                                     chain["offer_version"]), 201)
        response = self._claim(chain["offer"], chain["garden"], 3,
                               chain["offer_version"])
        validate_error(response, ERR_STALE_VERSION)

    def test_the_refused_claim_wrote_nothing_and_no_state_check_could_explain_it(self):
        """The refusal left no claim row and did not bump the offer, and the offer
        is still OPEN with its whole pool unallocated, so no state precondition
        could have produced the 412.

        "A second venue filing a claim against the same offer is normal product behaviour — the offer stays `OPEN` and the new claim would succeed — so the guard exists to stop a claimant from sizing its request against an offer whose claim population it has not observed."

        Design: Corner/cross_cutting_complexity_layers/occ_claim_against_stale_offer_version_returns_412
        """
        chain = self._open_offer()
        validate_success(self._claim(chain["offer"], chain["harbor"], 4,
                                     chain["offer_version"]), 201)
        validate_error(self._claim(chain["offer"], chain["garden"], 3,
                                   chain["offer_version"]),
                       ERR_STALE_VERSION)
        offer = validate_success(api_client.get_allocation_offer(
            chain["offer"]["id"], BEVERAGE_DIRECTOR_HEADERS))
        assert offer["version"] == chain["offer_version"] + 1, offer["version"]
        assert offer["claim_count"] == 1, offer["claim_count"]
        assert offer["fulfillment_state"] == "OPEN", offer["fulfillment_state"]
        assert offer["unallocated_bottles"] == 10, offer["unallocated_bottles"]
        claims, meta = validate_paginated(api_client.list_allocation_claims(
            BEVERAGE_DIRECTOR_HEADERS, params={"venue_id": chain["garden"]["id"]}))
        assert meta["total_count"] == 0, meta["total_count"]
        assert claims == [], claims

    def test_the_retry_with_the_refreshed_token_succeeds(self):
        """Re-reading the offer and retrying with its current version lets the
        second venue in, and bumps the offer once more.

        "Where a client needs the current value, single-resource reads of an allocation offer and of a list version both expose `version` for exactly this purpose."

        Design: Corner/cross_cutting_complexity_layers/occ_claim_against_stale_offer_version_returns_412
        """
        chain = self._open_offer()
        validate_success(self._claim(chain["offer"], chain["harbor"], 4,
                                     chain["offer_version"]), 201)
        validate_error(self._claim(chain["offer"], chain["garden"], 3,
                                   chain["offer_version"]),
                       ERR_STALE_VERSION)
        refreshed = validate_success(api_client.get_allocation_offer(
            chain["offer"]["id"], sommelier_headers(chain["garden"]["id"])))
        claim = validate_success(
            self._claim(chain["offer"], chain["garden"], 3,
                        refreshed["version"]), 201)
        assert claim["state"] == "REQUESTED", claim["state"]
        assert claim["granted_bottles"] == 0, claim["granted_bottles"]
        offer = validate_success(api_client.get_allocation_offer(
            chain["offer"]["id"], BEVERAGE_DIRECTOR_HEADERS))
        assert offer["version"] == refreshed["version"] + 1, offer["version"]
        assert offer["claim_count"] == 2, offer["claim_count"]


class TestListVersionGuardOnEntryCreation:
    """Two writers building the same DRAFT list collide because every child write
    bumps the parent version -- but a request that is both stale and duplicated
    must surface the uniqueness failure, which is checked first."""

    @staticmethod
    def _empty_draft():
        fx.set_clock("2026-09-01T12:00:00Z")
        venue = _venue()
        wine_a = _wine(cuvee="Monte Bello")
        wine_b = _wine(cuvee="Geyserville")
        wine_list = fx.create_wine_list(venue)
        version = fx.create_draft_version(wine_list, venue)
        return {"venue": venue, "wine_a": wine_a, "wine_b": wine_b,
                "wine_list": wine_list, "version": version,
                "version_token": version["version"]}

    @staticmethod
    def _add(chain, wine, sort_rank, expected):
        return api_client.create_list_entry(
            chain["version"]["id"],
            f.list_entry_payload(wine["id"], expected, sort_rank,
                                 by_the_glass=False, par_bottles=6),
            sommelier_headers(chain["venue"]["id"]))

    def _read_version(self, chain):
        return validate_success(api_client.get_list_version(
            chain["version"]["id"], BEVERAGE_DIRECTOR_HEADERS))

    def test_the_first_entry_bumps_the_draft_version(self):
        """The first entry is accepted against the freshly opened draft and moves
        both of the parent's counters.

        "Adding an entry increments the parent version's `entry_count` by 1 and its `version` by 1."

        Design: Corner/cross_cutting_complexity_layers/occ_entry_add_against_stale_list_version_returns_412
        """
        chain = self._empty_draft()
        validate_success(self._add(chain, chain["wine_a"], 1,
                                   chain["version_token"]), 201)
        version = self._read_version(chain)
        assert version["version"] == chain["version_token"] + 1, version["version"]
        assert version["entry_count"] == 1, version["entry_count"]

    def test_a_second_entry_carrying_the_stale_token_is_rejected_as_stale(self):
        """The second writer still holds the token it read before the first entry
        existed, so its perfectly legal addition is refused.

        "If that value does not equal the version's current `version`, the create is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/occ_entry_add_against_stale_list_version_returns_412
        """
        chain = self._empty_draft()
        validate_success(self._add(chain, chain["wine_a"], 1,
                                   chain["version_token"]), 201)
        response = self._add(chain, chain["wine_b"], 2, chain["version_token"])
        validate_error(response, ERR_STALE_VERSION)
        version = self._read_version(chain)
        assert version["entry_count"] == 1, version["entry_count"]
        assert version["version"] == chain["version_token"] + 1, version["version"]

    def test_a_request_that_is_both_stale_and_duplicated_reports_the_duplicate(self):
        """A request repeating wine A on the same version while also carrying the
        stale token hears about the duplicate, because uniqueness is checked at
        step 14 and the version guard only at step 15.

        "Checks are evaluated strictly in the following sequence, and the first failure is the one reported:"

        Design: Corner/cross_cutting_complexity_layers/occ_entry_add_against_stale_list_version_returns_412
        """
        chain = self._empty_draft()
        validate_success(self._add(chain, chain["wine_a"], 1,
                                   chain["version_token"]), 201)
        response = self._add(chain, chain["wine_a"], 3, chain["version_token"])
        validate_error(response, ERR_DUPLICATE_LIST_ENTRY_WINE)
        version = self._read_version(chain)
        assert version["entry_count"] == 1, version["entry_count"]
        assert version["version"] == chain["version_token"] + 1, version["version"]

    def test_the_retry_with_the_refreshed_list_version_token_succeeds(self):
        """Re-reading the version and retrying with its current token adds wine B,
        and neither refusal before it had moved the version.

        "Adding a second entry to the same `DRAFT` version is likewise legitimate on its own, so the stale-version check is the only deterministic guard against a writer building entries on an outdated view of the version's contents."

        Design: Corner/cross_cutting_complexity_layers/occ_entry_add_against_stale_list_version_returns_412
        """
        chain = self._empty_draft()
        validate_success(self._add(chain, chain["wine_a"], 1,
                                   chain["version_token"]), 201)
        validate_error(self._add(chain, chain["wine_b"], 2,
                                 chain["version_token"]), ERR_STALE_VERSION)
        validate_error(self._add(chain, chain["wine_a"], 3,
                                 chain["version_token"]),
                       ERR_DUPLICATE_LIST_ENTRY_WINE)
        refreshed = self._read_version(chain)
        assert refreshed["version"] == chain["version_token"] + 1, (
            refreshed["version"])
        entry_b = validate_success(
            self._add(chain, chain["wine_b"], 2, refreshed["version"]), 201)
        assert entry_b["wine_id"] == chain["wine_b"]["id"], entry_b["wine_id"]
        version = self._read_version(chain)
        assert version["entry_count"] == 2, version["entry_count"]
        assert version["version"] == refreshed["version"] + 1, version["version"]
