"""The error catalogue: every rejection reachable through the declared endpoints.

This file pins the refusal side of the contract -- the per-resource not-found
ladder, the three authentication/authorisation rungs, the referential checks
that guard a by-the-glass slot and an inventory lot, the slot-linked write-off
shape, the offer/claim lifecycle refusals, the empty-version and duplicate-wine
rules, the post-pricing fiscal gate at a RESTRICTED venue, and pour-plan
membership.  Every assertion here is an error_id (cross-checked against the
registered HTTP status map) or the state the system must be left in afterwards.
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
    ERR_BIN_NOT_FOUND,
    ERR_BIN_ZONE_MISMATCH,
    ERR_CLAIM_NOT_FOUND,
    ERR_CLAIM_NOT_WITHDRAWABLE,
    ERR_DEPLETION_ENTRY_NOT_FOUND,
    ERR_DISTRIBUTOR_NOT_FOUND,
    ERR_DISTRIBUTOR_SCOPE_VIOLATION,
    ERR_DUPLICATE_LIST_ENTRY_WINE,
    ERR_EMPTY_LIST_VERSION,
    ERR_ENTRY_NOT_BY_THE_GLASS,
    ERR_EVENT_NOT_FOUND,
    ERR_FORBIDDEN_ROLE,
    ERR_INVESTIGATION_NOT_FOUND,
    ERR_LIST_ENTRY_NOT_FOUND,
    ERR_LOT_VENUE_MISMATCH,
    ERR_NO_ELIGIBLE_CLAIMS,
    ERR_OFFER_NOT_FOUND,
    ERR_OFFER_NOT_OPEN,
    ERR_POUR_PLAN_ENTRY_MISMATCH,
    ERR_SLOT_NOT_FOUND,
    ERR_SLOT_WINE_MISMATCH,
    ERR_SLOT_WRITE_OFF_INVALID,
    ERR_UNAUTHENTICATED,
    ERR_VENUE_NOT_FOUND,
    ERR_VENUE_PROGRAM_RESTRICTED,
    ERR_WINE_LIST_NOT_FOUND,
    ERR_WRITE_OFF_NOT_FOUND,
    ERR_WRITE_OFF_NOT_SUBMITTED,
)
from test_helpers.assertions import depletion_entries_for, get_all
from test_helpers.test_users import (
    BEVERAGE_DIRECTOR_HEADERS,
    CONTROLLER_HEADERS,
    NO_AUTH_HEADERS,
    UNKNOWN_ROLE_HEADERS,
    distributor_rep_headers,
    second_controller_headers,
    sommelier_headers,
)

# The single unknown identifier every not-found leg reuses.
UNKNOWN_ID = "00000000-0000-4000-8000-000000000000"

# Venue targets used throughout: RED at 28.0 makes a 2400-cent wine price to
# 8600 (CORE) and a 5000-cent wine price to 17900 (PREMIUM).
HRB_TARGETS = f.cogs_targets(30.0, WHITE=25.0, ROSE=28.0, RED=28.0,
                             DESSERT=32.0, FORTIFIED=35.0)


def _error_with_message(response, error_id):
    """Assert the error envelope carries the id plus a human-readable message."""
    data = validate_error(response, error_id)
    message = data.get("message")
    assert isinstance(message, str) and message.strip(), (
        "expected a non-empty human-readable message alongside %s, got %r"
        % (error_id, message))
    return data


class TestPerResourceNotFoundCatalogue:
    """Twelve single-resource reads of one unknown UUID, one leg per resource
    type, proving the 404 catalogue is resource-specific and not one shared
    handler."""

    def test_unknown_venue_read_reports_venue_not_found(self):
        """Reading an unknown venue reports the venue-specific 404.

        "The not-found catalogue is per resource type: `ERR_VENUE_NOT_FOUND`, `ERR_DISTRIBUTOR_NOT_FOUND`, `ERR_WINE_NOT_FOUND`, `ERR_BIN_NOT_FOUND`, `ERR_OFFER_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_LOT_NOT_FOUND`, `ERR_DEPLETION_ENTRY_NOT_FOUND`, `ERR_WINE_LIST_NOT_FOUND`, `ERR_LIST_VERSION_NOT_FOUND`, `ERR_LIST_ENTRY_NOT_FOUND`, `ERR_SLOT_NOT_FOUND`, `ERR_WRITE_OFF_NOT_FOUND`, `ERR_EVENT_NOT_FOUND` and `ERR_INVESTIGATION_NOT_FOUND` — each HTTP 404."

        Design: Corner/errors/every_path_resource_returns_its_own_not_found_error
        """
        _error_with_message(api_client.get_venue(UNKNOWN_ID, CONTROLLER_HEADERS),
                            ERR_VENUE_NOT_FOUND)

    def test_unknown_distributor_read_reports_distributor_not_found(self):
        """Reading an unknown distributor reports the distributor-specific 404.

        "The not-found catalogue is per resource type: `ERR_VENUE_NOT_FOUND`, `ERR_DISTRIBUTOR_NOT_FOUND`, `ERR_WINE_NOT_FOUND`, `ERR_BIN_NOT_FOUND`, `ERR_OFFER_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_LOT_NOT_FOUND`, `ERR_DEPLETION_ENTRY_NOT_FOUND`, `ERR_WINE_LIST_NOT_FOUND`, `ERR_LIST_VERSION_NOT_FOUND`, `ERR_LIST_ENTRY_NOT_FOUND`, `ERR_SLOT_NOT_FOUND`, `ERR_WRITE_OFF_NOT_FOUND`, `ERR_EVENT_NOT_FOUND` and `ERR_INVESTIGATION_NOT_FOUND` — each HTTP 404."

        Design: Corner/errors/every_path_resource_returns_its_own_not_found_error
        """
        _error_with_message(
            api_client.get_distributor(UNKNOWN_ID, CONTROLLER_HEADERS),
            ERR_DISTRIBUTOR_NOT_FOUND)

    def test_unknown_cellar_bin_read_reports_bin_not_found(self):
        """Reading an unknown cellar bin reports the bin-specific 404.

        "The not-found catalogue is per resource type: `ERR_VENUE_NOT_FOUND`, `ERR_DISTRIBUTOR_NOT_FOUND`, `ERR_WINE_NOT_FOUND`, `ERR_BIN_NOT_FOUND`, `ERR_OFFER_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_LOT_NOT_FOUND`, `ERR_DEPLETION_ENTRY_NOT_FOUND`, `ERR_WINE_LIST_NOT_FOUND`, `ERR_LIST_VERSION_NOT_FOUND`, `ERR_LIST_ENTRY_NOT_FOUND`, `ERR_SLOT_NOT_FOUND`, `ERR_WRITE_OFF_NOT_FOUND`, `ERR_EVENT_NOT_FOUND` and `ERR_INVESTIGATION_NOT_FOUND` — each HTTP 404."

        Design: Corner/errors/every_path_resource_returns_its_own_not_found_error
        """
        _error_with_message(
            api_client.get_cellar_bin(UNKNOWN_ID, CONTROLLER_HEADERS),
            ERR_BIN_NOT_FOUND)

    def test_unknown_allocation_offer_read_reports_offer_not_found(self):
        """Reading an unknown allocation offer reports the offer-specific 404.

        "The not-found catalogue is per resource type: `ERR_VENUE_NOT_FOUND`, `ERR_DISTRIBUTOR_NOT_FOUND`, `ERR_WINE_NOT_FOUND`, `ERR_BIN_NOT_FOUND`, `ERR_OFFER_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_LOT_NOT_FOUND`, `ERR_DEPLETION_ENTRY_NOT_FOUND`, `ERR_WINE_LIST_NOT_FOUND`, `ERR_LIST_VERSION_NOT_FOUND`, `ERR_LIST_ENTRY_NOT_FOUND`, `ERR_SLOT_NOT_FOUND`, `ERR_WRITE_OFF_NOT_FOUND`, `ERR_EVENT_NOT_FOUND` and `ERR_INVESTIGATION_NOT_FOUND` — each HTTP 404."

        Design: Corner/errors/every_path_resource_returns_its_own_not_found_error
        """
        _error_with_message(
            api_client.get_allocation_offer(UNKNOWN_ID, CONTROLLER_HEADERS),
            ERR_OFFER_NOT_FOUND)

    def test_unknown_allocation_claim_read_reports_claim_not_found(self):
        """Reading an unknown allocation claim reports the claim-specific 404.

        "The not-found catalogue is per resource type: `ERR_VENUE_NOT_FOUND`, `ERR_DISTRIBUTOR_NOT_FOUND`, `ERR_WINE_NOT_FOUND`, `ERR_BIN_NOT_FOUND`, `ERR_OFFER_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_LOT_NOT_FOUND`, `ERR_DEPLETION_ENTRY_NOT_FOUND`, `ERR_WINE_LIST_NOT_FOUND`, `ERR_LIST_VERSION_NOT_FOUND`, `ERR_LIST_ENTRY_NOT_FOUND`, `ERR_SLOT_NOT_FOUND`, `ERR_WRITE_OFF_NOT_FOUND`, `ERR_EVENT_NOT_FOUND` and `ERR_INVESTIGATION_NOT_FOUND` — each HTTP 404."

        Design: Corner/errors/every_path_resource_returns_its_own_not_found_error
        """
        _error_with_message(
            api_client.get_allocation_claim(UNKNOWN_ID, CONTROLLER_HEADERS),
            ERR_CLAIM_NOT_FOUND)

    def test_unknown_depletion_entry_read_reports_depletion_entry_not_found(self):
        """Reading an unknown ledger entry reports the ledger-specific 404.

        "The not-found catalogue is per resource type: `ERR_VENUE_NOT_FOUND`, `ERR_DISTRIBUTOR_NOT_FOUND`, `ERR_WINE_NOT_FOUND`, `ERR_BIN_NOT_FOUND`, `ERR_OFFER_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_LOT_NOT_FOUND`, `ERR_DEPLETION_ENTRY_NOT_FOUND`, `ERR_WINE_LIST_NOT_FOUND`, `ERR_LIST_VERSION_NOT_FOUND`, `ERR_LIST_ENTRY_NOT_FOUND`, `ERR_SLOT_NOT_FOUND`, `ERR_WRITE_OFF_NOT_FOUND`, `ERR_EVENT_NOT_FOUND` and `ERR_INVESTIGATION_NOT_FOUND` — each HTTP 404."

        Design: Corner/errors/every_path_resource_returns_its_own_not_found_error
        """
        _error_with_message(
            api_client.get_depletion_entry(UNKNOWN_ID, CONTROLLER_HEADERS),
            ERR_DEPLETION_ENTRY_NOT_FOUND)

    def test_unknown_wine_list_read_reports_wine_list_not_found(self):
        """Reading an unknown wine list reports the wine-list-specific 404.

        "The not-found catalogue is per resource type: `ERR_VENUE_NOT_FOUND`, `ERR_DISTRIBUTOR_NOT_FOUND`, `ERR_WINE_NOT_FOUND`, `ERR_BIN_NOT_FOUND`, `ERR_OFFER_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_LOT_NOT_FOUND`, `ERR_DEPLETION_ENTRY_NOT_FOUND`, `ERR_WINE_LIST_NOT_FOUND`, `ERR_LIST_VERSION_NOT_FOUND`, `ERR_LIST_ENTRY_NOT_FOUND`, `ERR_SLOT_NOT_FOUND`, `ERR_WRITE_OFF_NOT_FOUND`, `ERR_EVENT_NOT_FOUND` and `ERR_INVESTIGATION_NOT_FOUND` — each HTTP 404."

        Design: Corner/errors/every_path_resource_returns_its_own_not_found_error
        """
        _error_with_message(
            api_client.get_wine_list(UNKNOWN_ID, CONTROLLER_HEADERS),
            ERR_WINE_LIST_NOT_FOUND)

    def test_unknown_list_entry_read_reports_list_entry_not_found(self):
        """Reading an unknown list entry reports the list-entry-specific 404.

        "The not-found catalogue is per resource type: `ERR_VENUE_NOT_FOUND`, `ERR_DISTRIBUTOR_NOT_FOUND`, `ERR_WINE_NOT_FOUND`, `ERR_BIN_NOT_FOUND`, `ERR_OFFER_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_LOT_NOT_FOUND`, `ERR_DEPLETION_ENTRY_NOT_FOUND`, `ERR_WINE_LIST_NOT_FOUND`, `ERR_LIST_VERSION_NOT_FOUND`, `ERR_LIST_ENTRY_NOT_FOUND`, `ERR_SLOT_NOT_FOUND`, `ERR_WRITE_OFF_NOT_FOUND`, `ERR_EVENT_NOT_FOUND` and `ERR_INVESTIGATION_NOT_FOUND` — each HTTP 404."

        Design: Corner/errors/every_path_resource_returns_its_own_not_found_error
        """
        _error_with_message(
            api_client.get_list_entry(UNKNOWN_ID, CONTROLLER_HEADERS),
            ERR_LIST_ENTRY_NOT_FOUND)

    def test_unknown_btg_slot_read_reports_slot_not_found(self):
        """Reading an unknown by-the-glass slot reports the slot-specific 404.

        "The not-found catalogue is per resource type: `ERR_VENUE_NOT_FOUND`, `ERR_DISTRIBUTOR_NOT_FOUND`, `ERR_WINE_NOT_FOUND`, `ERR_BIN_NOT_FOUND`, `ERR_OFFER_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_LOT_NOT_FOUND`, `ERR_DEPLETION_ENTRY_NOT_FOUND`, `ERR_WINE_LIST_NOT_FOUND`, `ERR_LIST_VERSION_NOT_FOUND`, `ERR_LIST_ENTRY_NOT_FOUND`, `ERR_SLOT_NOT_FOUND`, `ERR_WRITE_OFF_NOT_FOUND`, `ERR_EVENT_NOT_FOUND` and `ERR_INVESTIGATION_NOT_FOUND` — each HTTP 404."

        Design: Corner/errors/every_path_resource_returns_its_own_not_found_error
        """
        _error_with_message(
            api_client.get_btg_slot(UNKNOWN_ID, CONTROLLER_HEADERS),
            ERR_SLOT_NOT_FOUND)

    def test_unknown_write_off_read_reports_write_off_not_found(self):
        """Reading an unknown spoilage write-off reports the write-off 404.

        "The not-found catalogue is per resource type: `ERR_VENUE_NOT_FOUND`, `ERR_DISTRIBUTOR_NOT_FOUND`, `ERR_WINE_NOT_FOUND`, `ERR_BIN_NOT_FOUND`, `ERR_OFFER_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_LOT_NOT_FOUND`, `ERR_DEPLETION_ENTRY_NOT_FOUND`, `ERR_WINE_LIST_NOT_FOUND`, `ERR_LIST_VERSION_NOT_FOUND`, `ERR_LIST_ENTRY_NOT_FOUND`, `ERR_SLOT_NOT_FOUND`, `ERR_WRITE_OFF_NOT_FOUND`, `ERR_EVENT_NOT_FOUND` and `ERR_INVESTIGATION_NOT_FOUND` — each HTTP 404."

        Design: Corner/errors/every_path_resource_returns_its_own_not_found_error
        """
        _error_with_message(
            api_client.get_spoilage_write_off(UNKNOWN_ID, CONTROLLER_HEADERS),
            ERR_WRITE_OFF_NOT_FOUND)

    def test_unknown_wine_dinner_event_read_reports_event_not_found(self):
        """Reading an unknown wine dinner event reports the event-specific 404.

        "The not-found catalogue is per resource type: `ERR_VENUE_NOT_FOUND`, `ERR_DISTRIBUTOR_NOT_FOUND`, `ERR_WINE_NOT_FOUND`, `ERR_BIN_NOT_FOUND`, `ERR_OFFER_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_LOT_NOT_FOUND`, `ERR_DEPLETION_ENTRY_NOT_FOUND`, `ERR_WINE_LIST_NOT_FOUND`, `ERR_LIST_VERSION_NOT_FOUND`, `ERR_LIST_ENTRY_NOT_FOUND`, `ERR_SLOT_NOT_FOUND`, `ERR_WRITE_OFF_NOT_FOUND`, `ERR_EVENT_NOT_FOUND` and `ERR_INVESTIGATION_NOT_FOUND` — each HTTP 404."

        Design: Corner/errors/every_path_resource_returns_its_own_not_found_error
        """
        _error_with_message(
            api_client.get_wine_dinner_event(UNKNOWN_ID, CONTROLLER_HEADERS),
            ERR_EVENT_NOT_FOUND)

    def test_unknown_variance_investigation_read_reports_investigation_not_found(self):
        """Reading an unknown variance investigation reports its own 404.

        "The not-found catalogue is per resource type: `ERR_VENUE_NOT_FOUND`, `ERR_DISTRIBUTOR_NOT_FOUND`, `ERR_WINE_NOT_FOUND`, `ERR_BIN_NOT_FOUND`, `ERR_OFFER_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_LOT_NOT_FOUND`, `ERR_DEPLETION_ENTRY_NOT_FOUND`, `ERR_WINE_LIST_NOT_FOUND`, `ERR_LIST_VERSION_NOT_FOUND`, `ERR_LIST_ENTRY_NOT_FOUND`, `ERR_SLOT_NOT_FOUND`, `ERR_WRITE_OFF_NOT_FOUND`, `ERR_EVENT_NOT_FOUND` and `ERR_INVESTIGATION_NOT_FOUND` — each HTTP 404."

        Design: Corner/errors/every_path_resource_returns_its_own_not_found_error
        """
        _error_with_message(
            api_client.get_variance_investigation(UNKNOWN_ID, CONTROLLER_HEADERS),
            ERR_INVESTIGATION_NOT_FOUND)


class TestOfferPostingAuthLadder:
    """The three auth rungs on the DistributorRep-exclusive offer endpoint:
    missing/unknown headers, an unauthorised role, and a rep acting for a
    distributor that is not its own."""

    @staticmethod
    def _setup():
        fx.set_clock("2026-09-01T00:00:00Z")
        distributor_a = fx.create_distributor(allocation_tier="A")
        distributor_b = fx.create_distributor(allocation_tier="B")
        wine = fx.create_wine(reference_cost_cents=2400, is_allocated=True)
        payload = f.allocation_offer_payload(
            distributor_a["id"], wine["id"], offered_bottles=10,
            unit_cost_cents=3000, response_deadline="2026-09-30T00:00:00Z")
        return {"distributor_a": distributor_a, "distributor_b": distributor_b,
                "wine": wine, "payload": payload}

    @staticmethod
    def _offers():
        return get_all(api_client.list_allocation_offers, BEVERAGE_DIRECTOR_HEADERS)

    def test_offer_post_without_any_identity_headers_is_unauthenticated(self):
        """An offer posted with no X-User-ID and no X-User-Role is refused before any payload check.

        "If either header is absent or empty, or if `X-User-Role` is not one of the five roles the system recognises, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/errors/missing_header_wrong_role_and_foreign_distributor_all_rejected
        """
        setup = self._setup()
        response = api_client.create_allocation_offer(setup["payload"],
                                                     NO_AUTH_HEADERS)
        _error_with_message(response, ERR_UNAUTHENTICATED)
        assert self._offers() == [], "a rejected post must create no offer"

    def test_offer_post_with_undeclared_role_is_unauthenticated(self):
        """A role string outside the five declared roles is a 401, not a 403.

        "If either header is absent or empty, or if `X-User-Role` is not one of the five roles the system recognises, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/errors/missing_header_wrong_role_and_foreign_distributor_all_rejected
        """
        setup = self._setup()
        response = api_client.create_allocation_offer(setup["payload"],
                                                     UNKNOWN_ROLE_HEADERS)
        _error_with_message(response, ERR_UNAUTHENTICATED)
        assert self._offers() == [], "a rejected post must create no offer"

    def test_controller_posting_an_offer_is_forbidden_by_role(self):
        """Offer creation is DistributorRep-exclusive, so a Controller is refused on role.

        "If the header pair is well formed but the declared role is not authorised for the target operation, the rejection is `ERR_FORBIDDEN_ROLE` (HTTP 403)."

        Design: Corner/errors/missing_header_wrong_role_and_foreign_distributor_all_rejected
        """
        setup = self._setup()
        response = api_client.create_allocation_offer(setup["payload"],
                                                     CONTROLLER_HEADERS)
        _error_with_message(response, ERR_FORBIDDEN_ROLE)
        assert self._offers() == [], "a rejected post must create no offer"

    def test_rep_posting_for_another_distributor_violates_distributor_scope(self):
        """A rep of distributor B may not post an offer whose body names distributor A.

        "When `X-User-Role` is `DistributorRep`, `X-User-ID` is the `id` of the acting `Distributor`; posting an allocation offer or filtering the offer collection for a `distributor_id` other than `X-User-ID` is rejected with `ERR_DISTRIBUTOR_SCOPE_VIOLATION` (HTTP 403)."

        Design: Corner/errors/missing_header_wrong_role_and_foreign_distributor_all_rejected
        """
        setup = self._setup()
        response = api_client.create_allocation_offer(
            setup["payload"], distributor_rep_headers(setup["distributor_b"]["id"]))
        _error_with_message(response, ERR_DISTRIBUTOR_SCOPE_VIOLATION)
        assert self._offers() == [], "a rejected post must create no offer"

    def test_rep_filtering_offers_for_another_distributor_violates_distributor_scope(self):
        """The same 403 guards the offer collection filter, not only the create.

        "When `X-User-Role` is `DistributorRep`, `X-User-ID` is the `id` of the acting `Distributor`; posting an allocation offer or filtering the offer collection for a `distributor_id` other than `X-User-ID` is rejected with `ERR_DISTRIBUTOR_SCOPE_VIOLATION` (HTTP 403)."

        Design: Corner/errors/missing_header_wrong_role_and_foreign_distributor_all_rejected
        """
        setup = self._setup()
        response = api_client.list_allocation_offers(
            distributor_rep_headers(setup["distributor_b"]["id"]),
            params={"distributor_id": setup["distributor_a"]["id"]})
        _error_with_message(response, ERR_DISTRIBUTOR_SCOPE_VIOLATION)

    def test_own_rep_posting_the_same_body_creates_the_only_offer(self):
        """The identical body succeeds for distributor A's own rep and is the only offer created.

        "On creation, `unallocated_bottles` is set to the full `offered_bottles`, `claim_count` to 0, and `allocated_at` to null."

        "`compliance_state` tracks the licence dimension and is initialised to `PENDING_LICENSE_CHECK`, with one exception — when the offering distributor's standing is already `CLEARED` at the moment the offer is posted, the offer's `compliance_state` is set to `CLEARED` at creation."

        Design: Corner/errors/missing_header_wrong_role_and_foreign_distributor_all_rejected
        """
        setup = self._setup()
        response = api_client.create_allocation_offer(
            setup["payload"], distributor_rep_headers(setup["distributor_a"]["id"]))
        offer = validate_success(response, 201)
        assert offer["fulfillment_state"] == "OPEN"
        assert offer["compliance_state"] == "PENDING_LICENSE_CHECK"
        assert offer["unallocated_bottles"] == 10
        assert offer["claim_count"] == 0
        assert offer["allocated_at"] is None
        offers = self._offers()
        assert [row["id"] for row in offers] == [offer["id"]], (
            "exactly one AllocationOffer must exist, got %r" % (offers,))


class TestBtgSlotOpenReferentialChecks:
    """Opening a rail slot joins a list entry and a lot that must agree on the
    wine, and the entry must be in the by-the-glass rotation."""

    @staticmethod
    def _setup():
        fx.set_clock("2026-09-01T12:00:00Z")
        venue = fx.create_venue(cogs_target_pct_by_category=HRB_TARGETS)
        bin_ = fx.create_bin(venue, capacity_bottles=48)
        wine_a = fx.create_wine(reference_cost_cents=2400, category="RED")
        wine_b = fx.create_wine(reference_cost_cents=2400, category="RED")
        lot_a = fx.create_lot(venue, wine_a, bin_, bottles_received=6,
                              unit_cost_cents=2400,
                              received_at="2026-08-10T00:00:00Z")
        lot_b = fx.create_lot(venue, wine_b, bin_, bottles_received=6,
                              unit_cost_cents=2400,
                              received_at="2026-08-10T00:00:00Z")
        draft = fx.setup_draft_version(venue)
        version = draft["version"]
        entry_a = fx.add_entry(version, wine_a, venue, sort_rank=1,
                               by_the_glass=True, pour_size_ml=177,
                               par_bottles=6, education_verified=False)
        entry_b = fx.add_entry(version, wine_b, venue, sort_rank=2,
                               by_the_glass=False, par_bottles=6)
        fx.publish_version(version, venue)
        return {"venue": venue, "bin": bin_, "wine_a": wine_a, "wine_b": wine_b,
                "lot_a": lot_a, "lot_b": lot_b, "version": version,
                "entry_a": entry_a, "entry_b": entry_b}

    @staticmethod
    def _open_slot(setup, entry, lot, slot_index):
        venue_id = setup["venue"]["id"]
        payload = f.btg_slot_payload(venue_id, entry["id"], lot["id"],
                                     slot_index, "ARGON")
        return api_client.create_btg_slot(payload, sommelier_headers(venue_id))

    @staticmethod
    def _committed(lot):
        return validate_success(
            api_client.get_inventory_lot(lot["id"],
                                        BEVERAGE_DIRECTOR_HEADERS))["bottles_committed"]

    def test_glass_entry_pointed_at_another_wines_lot_is_a_wine_mismatch(self):
        """A rail slot may not pour wine B's bottle against wine A's listing.

        "That lot must hold the same wine as the list entry and belong to the same venue as the slot, or the request is `ERR_SLOT_WINE_MISMATCH` (HTTP 422)."

        Design: Corner/errors/btg_slot_open_rejects_wrong_wine_and_bottle_only_entry
        """
        setup = self._setup()
        response = self._open_slot(setup, setup["entry_a"], setup["lot_b"], 1)
        _error_with_message(response, ERR_SLOT_WINE_MISMATCH)
        assert self._committed(setup["lot_b"]) == 0, (
            "a rejected open must not reserve a bottle")

    def test_bottle_only_entry_with_its_own_lot_is_not_by_the_glass(self):
        """A bottle-only listing cannot be put on the rail even with its own lot.

        "The list entry must actually be in the rotation, since pouring a bottle-only listing by the glass makes no sense: `ERR_ENTRY_NOT_BY_THE_GLASS` (HTTP 422)."

        Design: Corner/errors/btg_slot_open_rejects_wrong_wine_and_bottle_only_entry
        """
        setup = self._setup()
        response = self._open_slot(setup, setup["entry_b"], setup["lot_b"], 2)
        _error_with_message(response, ERR_ENTRY_NOT_BY_THE_GLASS)
        assert self._committed(setup["lot_b"]) == 0, (
            "a rejected open must not reserve a bottle")

    def test_bottle_only_entry_on_a_foreign_lot_reports_the_wine_mismatch_first(self):
        """When both referential rules fail, slot wine agreement is reported before by-the-glass eligibility.

        "Referential consistency between the records a request joins: bin and lot venue agreement, slot wine agreement, by-the-glass eligibility, pour-plan membership, slot write-off shape, pinned-version freshness."

        Design: Corner/errors/btg_slot_open_rejects_wrong_wine_and_bottle_only_entry
        """
        setup = self._setup()
        response = self._open_slot(setup, setup["entry_b"], setup["lot_a"], 3)
        _error_with_message(response, ERR_SLOT_WINE_MISMATCH)
        assert self._committed(setup["lot_a"]) == 0, (
            "a rejected open must not reserve a bottle")

    def test_matching_glass_entry_and_lot_opens_the_slot(self):
        """The agreeing entry-and-lot pair opens, freezing three saleable pours and committing one bottle.

        "Divide the wine's `bottle_size_ml` by the entry's `pour_size_ml` and discard any fraction to get the gross pour count, then subtract one pour as the spoilage allowance every open bottle concedes; the remainder is `effective_pours`."

        "On the inventory side the lot's `bottles_committed` rises by 1 while its `bottles_on_hand` is deliberately left alone — the bottle is spoken for but has not yet left the cellar's books."

        Design: Corner/errors/btg_slot_open_rejects_wrong_wine_and_bottle_only_entry
        """
        setup = self._setup()
        slot = validate_success(
            self._open_slot(setup, setup["entry_a"], setup["lot_a"], 4), 201)
        assert slot["effective_pours"] == 3
        assert slot["state"] == "OPEN"
        assert self._committed(setup["lot_a"]) == 1
        assert self._committed(setup["lot_b"]) == 0


class TestLotRoutingChecks:
    """Where bottles may land: a bin must belong to the lot's own venue, and a
    RESERVE bin accepts allocated wine only."""

    @staticmethod
    def _setup():
        fx.set_clock("2026-09-01T12:00:00Z")
        venue_1 = fx.create_venue(cogs_target_pct_by_category=HRB_TARGETS)
        venue_2 = fx.create_venue(cogs_target_pct_by_category=HRB_TARGETS)
        bin_cellar = fx.create_bin(venue_1, zone="CELLAR", capacity_bottles=48)
        bin_reserve = fx.create_bin(venue_1, zone="RESERVE", capacity_bottles=12)
        bin_other_venue = fx.create_bin(venue_2, zone="CELLAR", capacity_bottles=24)
        wine_a = fx.create_wine(reference_cost_cents=2400, category="RED",
                                is_allocated=False)
        wine_r = fx.create_wine(reference_cost_cents=5000, category="RED",
                                is_allocated=True)
        lot_a = fx.create_lot(venue_1, wine_a, bin_cellar, bottles_received=6,
                              unit_cost_cents=2400,
                              received_at="2026-08-10T00:00:00Z")
        return {"venue_1": venue_1, "venue_2": venue_2,
                "bin_cellar": bin_cellar, "bin_reserve": bin_reserve,
                "bin_other_venue": bin_other_venue,
                "wine_a": wine_a, "wine_r": wine_r, "lot_a": lot_a}

    @staticmethod
    def _post_lot(setup, wine, bin_, unit_cost_cents):
        venue_id = setup["venue_1"]["id"]
        payload = f.inventory_lot_payload(
            venue_id, wine["id"], bin_["id"], bottles_received=6,
            unit_cost_cents=unit_cost_cents, received_at="2026-08-10T00:00:00Z")
        return api_client.create_inventory_lot(payload, sommelier_headers(venue_id))

    @staticmethod
    def _bin(bin_):
        return validate_success(
            api_client.get_cellar_bin(bin_["id"], BEVERAGE_DIRECTOR_HEADERS))

    def test_direct_receipt_into_another_venues_bin_is_a_lot_venue_mismatch(self):
        """A receipt for venue HRB may not be stored in a bin belonging to venue GDN.

        "The same future-receipt, venue-agreement, reserve-zone and capacity checks apply and carry the same error identifiers."

        Design: Corner/errors/lot_routing_rejects_foreign_venue_bin_and_reserve_zone
        """
        setup = self._setup()
        response = self._post_lot(setup, setup["wine_a"],
                                  setup["bin_other_venue"], 2400)
        _error_with_message(response, ERR_LOT_VENUE_MISMATCH)
        assert self._bin(setup["bin_other_venue"])["bottles_stored"] == 0, (
            "a rejected receipt must not store bottles")

    def test_non_allocated_wine_into_a_reserve_bin_is_a_zone_mismatch(self):
        """A wine that is not distributor-allocated may not be routed into a RESERVE bin.

        "The `RESERVE` zone is reserved in the literal sense: only a wine flagged as distributor-allocated may be stored there, and routing a non-allocated wine into a reserve bin is refused with `ERR_BIN_ZONE_MISMATCH`."

        Design: Corner/errors/lot_routing_rejects_foreign_venue_bin_and_reserve_zone
        """
        setup = self._setup()
        response = self._post_lot(setup, setup["wine_a"], setup["bin_reserve"], 2400)
        _error_with_message(response, ERR_BIN_ZONE_MISMATCH)
        assert self._bin(setup["bin_reserve"])["bottles_stored"] == 0, (
            "a rejected receipt must not store bottles")

    def test_the_same_reserve_bin_accepts_an_allocated_wine(self):
        """The identical routing succeeds once the wine is flagged allocated, and the bin's occupancy is recomputed.

        "The `RESERVE` zone is reserved in the literal sense: only a wine flagged as distributor-allocated may be stored there, and routing a non-allocated wine into a reserve bin is refused with `ERR_BIN_ZONE_MISMATCH`."

        "Three computed fields describe occupancy: `bottles_stored` is the sum of `bottles_on_hand` across the lots sitting in this bin whose state is `ON_HAND` and starts at 0; `utilization_pct` is `bottles_stored` multiplied by 100, divided by `capacity_bottles`, rounded half up to two decimals, and starts at 0.00; and `bin_state` is `FULL` when `bottles_stored` equals `capacity_bottles` exactly and `ACTIVE` in every other case, starting at `ACTIVE`."

        Design: Corner/errors/lot_routing_rejects_foreign_venue_bin_and_reserve_zone
        """
        setup = self._setup()
        lot = validate_success(
            self._post_lot(setup, setup["wine_r"], setup["bin_reserve"], 5000), 201)
        assert lot["state"] == "ON_HAND"
        reserve_bin = self._bin(setup["bin_reserve"])
        assert reserve_bin["bottles_stored"] == 6
        assert float(reserve_bin["utilization_pct"]) == 50.00
        assert reserve_bin["bin_state"] == "ACTIVE"

    def test_controller_write_off_naming_a_foreign_venue_is_a_lot_venue_mismatch(self):
        """A Controller-proposed write-off must still name the lot's own venue, so the rule is reachable without the sommelier scope check.

        "At proposal time the venue named must be the lot's own venue (`ERR_LOT_VENUE_MISMATCH`), the lot must be `ON_HAND` (`ERR_LOT_NOT_ON_HAND`), and the bottles proposed must not exceed the lot's `bottles_on_hand` less its `bottles_committed` (`ERR_INSUFFICIENT_BOTTLES`)."

        Design: Corner/errors/lot_routing_rejects_foreign_venue_bin_and_reserve_zone
        """
        setup = self._setup()
        payload = f.write_off_payload(setup["venue_2"]["id"], setup["lot_a"]["id"],
                                      bottles=1, reason_code="BREAKAGE",
                                      narrative="Wrong venue on the paperwork.")
        response = api_client.create_spoilage_write_off(payload, CONTROLLER_HEADERS)
        _error_with_message(response, ERR_LOT_VENUE_MISMATCH)
        assert get_all(api_client.list_spoilage_write_offs, CONTROLLER_HEADERS) == [], (
            "a rejected proposal must create no write-off row")


class TestSlotLinkedWriteOffAndDoubleApproval:
    """A write-off that resolves an expired rail slot is valid only for that
    slot's own lot and exactly one bottle, and once approved it cannot be
    approved twice."""

    @staticmethod
    def _setup():
        fx.set_clock("2026-09-01T12:00:00Z")
        venue = fx.create_venue(cogs_target_pct_by_category=HRB_TARGETS)
        wine = fx.create_wine(reference_cost_cents=2400, category="RED")
        chain = fx.setup_published_entry(venue=venue, wine=wine, pour_size_ml=177,
                                        bottles_received=6, unit_cost_cents=2400,
                                        received_at="2026-08-10T00:00:00Z")
        slot = fx.open_slot(venue, chain["entry"], chain["lot"], slot_index=1,
                            preservation_method="VACUUM")
        fx.set_clock("2026-09-06T12:00:00Z")
        closed = fx.close_slot(slot, venue, pours_sold=2)
        chain["slot"] = closed
        return chain

    @staticmethod
    def _lot(chain):
        return validate_success(
            api_client.get_inventory_lot(chain["lot"]["id"], BEVERAGE_DIRECTOR_HEADERS))

    @staticmethod
    def _slot(chain):
        return validate_success(
            api_client.get_btg_slot(chain["slot"]["id"], BEVERAGE_DIRECTOR_HEADERS))

    @staticmethod
    def _submit(chain, bottles):
        payload = f.write_off_payload(
            chain["venue"]["id"], chain["lot"]["id"], bottles=bottles,
            reason_code="PRESERVATION_EXPIRY",
            narrative="Oxidised backbar bottle from an expired slot.",
            btg_slot_id=chain["slot"]["id"])
        return api_client.create_spoilage_write_off(
            payload, sommelier_headers(chain["venue"]["id"]))

    def test_closing_after_expiry_records_the_pours_but_books_nothing(self):
        """A slot closed after its preservation window expires spoils the whole bottle and writes no ledger entry.

        "When the clock is strictly after `preservation_expires_at`, the slot instead moves `OPEN → EXPIRED`: the submitted pour counts are recorded as submitted, `spoiled_pours` is set to the slot's full `effective_pours`, and — this is the important divergence — **no ledger entry is written, no revenue is recognised, and neither venue ledger moves.**"

        Design: Corner/errors/write_off_slot_link_and_double_approval_rejected
        """
        chain = self._setup()
        slot = self._slot(chain)
        assert slot["state"] == "EXPIRED"
        assert slot["pours_sold"] == 2
        assert slot["spoiled_pours"] == 3
        assert depletion_entries_for(BEVERAGE_DIRECTOR_HEADERS,
                                     venue_id=chain["venue"]["id"]) == []
        venue = fx.get_venue(chain["venue"])
        assert venue["cogs_ledger_cents"] == 0
        assert venue["revenue_ledger_cents"] == 0

    def test_slot_linked_write_off_of_two_bottles_is_invalid(self):
        """A slot-linked write-off is exactly one bottle -- the bottle the expired slot holds.

        "When a `btg_slot_id` is supplied, all three of the following must hold or the proposal is refused with `ERR_SLOT_WRITE_OFF_INVALID` (HTTP 422): the named slot is in state `EXPIRED`, its `lot_id` is the same lot named in the body, and `bottles` is exactly 1."

        Design: Corner/errors/write_off_slot_link_and_double_approval_rejected
        """
        chain = self._setup()
        _error_with_message(self._submit(chain, 2), ERR_SLOT_WRITE_OFF_INVALID)
        assert get_all(api_client.list_spoilage_write_offs, CONTROLLER_HEADERS) == [], (
            "a rejected proposal must create no write-off row")
        assert self._lot(chain)["bottles_on_hand"] == 6

    def test_one_bottle_slot_linked_write_off_is_created_submitted(self):
        """The one-bottle version of the same proposal is accepted and books nothing yet.

        "The write-off is created in state `SUBMITTED` with `submitted_by_user_id` set to the acting `X-User-ID`, `cogs_cents` initialised to 0, and `approved_by_user_id` and `resolution_note` both null."

        Design: Corner/errors/write_off_slot_link_and_double_approval_rejected
        """
        chain = self._setup()
        write_off = validate_success(self._submit(chain, 1), 201)
        assert write_off["state"] == "SUBMITTED"
        assert write_off["cogs_cents"] == 0
        assert write_off["submitted_by_user_id"] == chain["venue"]["id"]
        assert write_off["approved_by_user_id"] is None
        assert write_off["resolution_note"] is None
        assert self._lot(chain)["bottles_on_hand"] == 6

    def test_approval_prices_the_bottle_and_releases_the_expired_slot(self):
        """Approving the slot-linked write-off costs one bottle out of the lot and hands the committed bottle back.

        "On approval the write-off moves `SUBMITTED → APPROVED`, records `approved_by_user_id` as the acting `X-User-ID`, and computes `cogs_cents` by pricing the written-off bottles out of that one nominated lot under the venue's costing method."

        "Finally, when the approved write-off named a `btg_slot_id`, that slot moves `EXPIRED → WRITTEN_OFF` and the bottle it was holding is released, decrementing the lot's `bottles_committed` by 1."

        Design: Corner/errors/write_off_slot_link_and_double_approval_rejected
        """
        chain = self._setup()
        write_off = validate_success(self._submit(chain, 1), 201)
        approved = validate_success(
            api_client.approve_write_off(write_off["id"], CONTROLLER_HEADERS))
        assert approved["state"] == "APPROVED"
        assert approved["cogs_cents"] == 2400
        lot = self._lot(chain)
        assert lot["bottles_on_hand"] == 5
        assert lot["bottles_committed"] == 0
        assert self._slot(chain)["state"] == "WRITTEN_OFF"
        entries = depletion_entries_for(BEVERAGE_DIRECTOR_HEADERS,
                                       write_off_id=write_off["id"])
        assert len(entries) == 1, "expected exactly one SPOILAGE entry, got %r" % (entries,)
        assert entries[0]["reason"] == "SPOILAGE"
        assert entries[0]["bottles"] == 1
        assert entries[0]["cogs_cents"] == 2400

    def test_second_approval_of_the_same_write_off_is_rejected(self):
        """An already-approved write-off cannot be approved again, even by another Controller.

        "Four preconditions guard it, in this order: the write-off is in `SUBMITTED`, otherwise `ERR_WRITE_OFF_NOT_SUBMITTED` (HTTP 409); the acting `X-User-ID` differs from `submitted_by_user_id`, otherwise `ERR_SEGREGATION_OF_DUTIES`; the lot is `ON_HAND`, otherwise `ERR_LOT_NOT_ON_HAND`; and the bottles fit within what the lot can give up, otherwise `ERR_INSUFFICIENT_BOTTLES`."

        Design: Corner/errors/write_off_slot_link_and_double_approval_rejected
        """
        chain = self._setup()
        write_off = validate_success(self._submit(chain, 1), 201)
        validate_success(
            api_client.approve_write_off(write_off["id"], CONTROLLER_HEADERS))
        response = api_client.approve_write_off(write_off["id"],
                                                second_controller_headers())
        _error_with_message(response, ERR_WRITE_OFF_NOT_SUBMITTED)
        assert self._lot(chain)["bottles_on_hand"] == 5
        entries = depletion_entries_for(BEVERAGE_DIRECTOR_HEADERS,
                                        write_off_id=write_off["id"])
        assert len(entries) == 1, (
            "the refused second approval must write no further ledger entry, got %r"
            % (entries,))


class TestOfferAndClaimLifecycleErrors:
    """The three lifecycle refusals on the allocation path: allocating before
    anyone claims, claiming after the waterfall has run, and withdrawing the
    same claim twice."""

    @staticmethod
    def _setup():
        fx.set_clock("2026-09-01T00:00:00Z")
        venue_1 = fx.create_venue(cogs_target_pct_by_category=HRB_TARGETS,
                                  priority_rank=1)
        venue_2 = fx.create_venue(cogs_target_pct_by_category=HRB_TARGETS,
                                  priority_rank=2)
        distributor = fx.create_distributor(allocation_tier="A")
        wine = fx.create_wine(reference_cost_cents=5000, category="RED",
                              is_allocated=True)
        offer = fx.create_offer(distributor, wine, offered_bottles=10,
                                unit_cost_cents=5000,
                                response_deadline="2026-09-30T00:00:00Z")
        return {"venue_1": venue_1, "venue_2": venue_2,
                "distributor": distributor, "wine": wine, "offer": offer}

    @staticmethod
    def _offer(setup):
        return validate_success(
            api_client.get_allocation_offer(setup["offer"]["id"],
                                            BEVERAGE_DIRECTOR_HEADERS))

    def test_allocating_an_offer_with_no_claims_is_refused(self):
        """A waterfall with nothing to divide is refused and leaves the offer untouched.

        "It is refused when the fulfilment dimension is not `OPEN` (`ERR_OFFER_NOT_OPEN`), when the offer's compliance dimension reads `BLOCKED` (`ERR_OFFER_COMPLIANCE_BLOCKED`, HTTP 422), and when no claim on the offer sits in `REQUESTED` (`ERR_NO_ELIGIBLE_CLAIMS`, HTTP 422)."

        Design: Corner/errors/offer_and_claim_lifecycle_errors_are_all_reachable
        """
        setup = self._setup()
        response = api_client.allocate_offer(setup["offer"]["id"],
                                             BEVERAGE_DIRECTOR_HEADERS)
        _error_with_message(response, ERR_NO_ELIGIBLE_CLAIMS)
        offer = self._offer(setup)
        assert offer["fulfillment_state"] == "OPEN"
        assert offer["allocated_at"] is None
        assert offer["version"] == setup["offer"]["version"]

    def test_an_under_subscribed_pool_grants_the_single_claim_in_full(self):
        """Six bottles asked of a ten-bottle pool are granted in full and the offer moves to ALLOCATED.

        "When total demand is less than or equal to the pool, every claim is granted exactly what it asked for and the offer's `unallocated_bottles` becomes the pool less the total demand."

        "Alongside the claim writes, the offer records `allocated_at` as the logical clock, recomputes `unallocated_bottles`, and increments its own `version` by 1."

        Design: Corner/errors/offer_and_claim_lifecycle_errors_are_all_reachable
        """
        setup = self._setup()
        claim = fx.file_claim(setup["offer"], setup["venue_1"], 6)
        allocated = validate_success(
            api_client.allocate_offer(setup["offer"]["id"],
                                      BEVERAGE_DIRECTOR_HEADERS))
        assert allocated["fulfillment_state"] == "ALLOCATED"
        assert allocated["unallocated_bottles"] == 4
        assert allocated["compliance_state"] == "PENDING_LICENSE_CHECK"
        assert allocated["allocated_at"].startswith("2026-09-01T00:00:00"), (
            "allocated_at must be stamped from the logical clock, got %r"
            % (allocated["allocated_at"],))
        granted = validate_success(
            api_client.get_allocation_claim(claim["id"], BEVERAGE_DIRECTOR_HEADERS))
        assert granted["state"] == "GRANTED"
        assert granted["granted_bottles"] == 6
        assert granted["remainder_awarded"] is False

    def test_claiming_against_an_allocated_offer_is_refused(self):
        """Once the waterfall has run the offer is closed to claims even though bottles remain unallocated.

        "A claim is refused when the offer's fulfilment dimension is anything other than `OPEN` (`ERR_OFFER_NOT_OPEN`, HTTP 409); when this venue already holds a claim on this offer in *any* state, including a withdrawn or rejected one (`ERR_DUPLICATE_CLAIM`, HTTP 409); when `requested_bottles` exceeds the offer's `offered_bottles` (`ERR_REQUEST_EXCEEDS_OFFER`, HTTP 422); when the logical clock has reached or passed the offer's `response_deadline`, so that only an instant strictly earlier than the deadline is accepted (`ERR_OFFER_DEADLINE_PASSED`, HTTP 422); and when the distributor behind the offer stands in `HOLD` (`ERR_DISTRIBUTOR_COMPLIANCE_HOLD`, HTTP 422)."

        Design: Corner/errors/offer_and_claim_lifecycle_errors_are_all_reachable
        """
        setup = self._setup()
        fx.file_claim(setup["offer"], setup["venue_1"], 6)
        validate_success(api_client.allocate_offer(setup["offer"]["id"],
                                                  BEVERAGE_DIRECTOR_HEADERS))
        offer = self._offer(setup)
        assert offer["unallocated_bottles"] == 4
        venue_2_id = setup["venue_2"]["id"]
        payload = f.allocation_claim_payload(venue_2_id, 4, offer["version"])
        response = api_client.create_allocation_claim(
            setup["offer"]["id"], payload, sommelier_headers(venue_2_id))
        _error_with_message(response, ERR_OFFER_NOT_OPEN)

    def test_withdrawing_the_same_claim_twice_is_refused(self):
        """A claim already WITHDRAWN cannot be withdrawn again.

        "Withdrawing is available to the claiming `VenueSommelier` and only while the claim is in `REQUESTED`, `GRANTED` or `PARTIALLY_GRANTED`; anything else is `ERR_CLAIM_NOT_WITHDRAWABLE` (HTTP 409)."

        Design: Corner/errors/offer_and_claim_lifecycle_errors_are_all_reachable
        """
        setup = self._setup()
        claim = fx.file_claim(setup["offer"], setup["venue_1"], 6)
        validate_success(api_client.allocate_offer(setup["offer"]["id"],
                                                  BEVERAGE_DIRECTOR_HEADERS))
        venue_1_id = setup["venue_1"]["id"]
        withdrawn = validate_success(
            api_client.withdraw_claim(claim["id"], sommelier_headers(venue_1_id)))
        assert withdrawn["state"] == "WITHDRAWN"
        response = api_client.withdraw_claim(claim["id"],
                                             sommelier_headers(venue_1_id))
        _error_with_message(response, ERR_CLAIM_NOT_WITHDRAWABLE)


class TestEmptyVersionAndDuplicateWine:
    """A version with no entries cannot enter review, and one wine may appear at
    most once on a version."""

    @staticmethod
    def _setup():
        fx.set_clock("2026-09-01T12:00:00Z")
        venue = fx.create_venue(cogs_target_pct_by_category=HRB_TARGETS)
        wine = fx.create_wine(reference_cost_cents=2400, category="RED")
        draft = fx.setup_draft_version(venue)
        return {"venue": venue, "wine": wine, "wine_list": draft["wine_list"],
                "version": draft["version"]}

    @staticmethod
    def _version(setup):
        return validate_success(
            api_client.get_list_version(setup["version"]["id"],
                                        BEVERAGE_DIRECTOR_HEADERS))

    def test_submitting_an_empty_draft_is_refused(self):
        """A draft carrying no entries cannot be submitted for review.

        "It requires the version to be in `DRAFT` (`ERR_LIST_VERSION_NOT_DRAFT`) and to carry at least one entry, an empty version being refused with `ERR_EMPTY_LIST_VERSION` (HTTP 422)."

        Design: Corner/errors/empty_submit_and_duplicate_wine_on_one_version_rejected
        """
        setup = self._setup()
        venue_id = setup["venue"]["id"]
        response = api_client.submit_list_version(setup["version"]["id"],
                                                  sommelier_headers(venue_id))
        _error_with_message(response, ERR_EMPTY_LIST_VERSION)
        version = self._version(setup)
        assert version["state"] == "DRAFT"
        assert version["entry_count"] == 0

    def test_the_first_entry_is_priced_and_counted(self):
        """A 2400-cent RED at a 28.0 percent target prints at 8600 cents in the CORE band.

        "Independently, take the venue's target percentage for this wine's category out of `cogs_target_pct_by_category`, multiply the cost by 100, divide by that percentage and round half up to whole cents; call this the target candidate."

        "That price then fixes the entry's `price_band`: `VALUE` at 6000 cents or below, `CORE` above 6000 and at most 12000, `PREMIUM` above 12000 and at most 25000, and `RESERVE` above 25000."

        Design: Corner/errors/empty_submit_and_duplicate_wine_on_one_version_rejected
        """
        setup = self._setup()
        entry = fx.add_entry(setup["version"], setup["wine"], setup["venue"],
                             sort_rank=1, by_the_glass=False, par_bottles=6)
        assert entry["bottle_price_cents"] == 8600
        assert entry["price_band"] == "CORE"
        assert self._version(setup)["entry_count"] == 1

    def test_the_same_wine_twice_on_one_version_is_a_duplicate(self):
        """A second listing of the same wine is refused even with a current OCC token and a different sort_rank.

        "Entries may be added only while the owning version is in `DRAFT` — otherwise `ERR_LIST_VERSION_NOT_DRAFT` (HTTP 409) — and a wine may appear at most once per version, a repeat being `ERR_DUPLICATE_LIST_ENTRY_WINE` (HTTP 409)."

        Design: Corner/errors/empty_submit_and_duplicate_wine_on_one_version_rejected
        """
        setup = self._setup()
        fx.add_entry(setup["version"], setup["wine"], setup["venue"],
                     sort_rank=1, by_the_glass=False, par_bottles=6)
        venue_id = setup["venue"]["id"]
        current = self._version(setup)["version"]
        payload = f.list_entry_payload(setup["wine"]["id"], current, sort_rank=2,
                                       by_the_glass=True, pour_size_ml=177,
                                       par_bottles=6)
        response = api_client.create_list_entry(setup["version"]["id"], payload,
                                                sommelier_headers(venue_id))
        _error_with_message(response, ERR_DUPLICATE_LIST_ENTRY_WINE)
        after = self._version(setup)
        assert after["version"] == current, (
            "a refused duplicate must not bump the version's version integer")
        assert after["entry_count"] == 1

    def test_submitting_a_non_empty_draft_records_the_submitter(self):
        """Once the version carries an entry the same submit succeeds and records the acting sommelier.

        "On success the version moves `DRAFT → IN_REVIEW`, `submitted_by_user_id` is set to the acting `X-User-ID`, overwriting whatever a previous submission recorded, and the version's own `version` increments by 1."

        Design: Corner/errors/empty_submit_and_duplicate_wine_on_one_version_rejected
        """
        setup = self._setup()
        fx.add_entry(setup["version"], setup["wine"], setup["venue"],
                     sort_rank=1, by_the_glass=False, par_bottles=6)
        venue_id = setup["venue"]["id"]
        submitted = validate_success(
            api_client.submit_list_version(setup["version"]["id"],
                                           sommelier_headers(venue_id)))
        assert submitted["state"] == "IN_REVIEW"
        assert submitted["submitted_by_user_id"] == venue_id
        assert submitted["revision_round"] == 0


class TestRestrictedPostureBlocksPremiumEntry:
    """A venue driven to RESTRICTED posture by a pour-cost run refuses a new
    entry whose computed band is PREMIUM while still accepting a CORE one.

    The posture is reached only through declared endpoints: two by-the-glass
    bottles are poured out of one 2400-cent lot at a 2875-cent glass price, one
    of them with a staff-education pour, so the actual population carries
    4800 cents of cost against 14375 of revenue (33.39 percent) while the
    theoretical population carries 4000 against the same revenue (27.83
    percent) -- a variance of 5.56 points.
    """

    @staticmethod
    def _setup():
        fx.set_clock("2026-09-01T10:00:00Z")
        venue = fx.create_venue(cogs_target_pct_by_category=HRB_TARGETS)
        wine_core = fx.create_wine(reference_cost_cents=2400, category="RED")
        wine_premium = fx.create_wine(reference_cost_cents=5000, category="RED")
        chain = fx.setup_published_entry(venue=venue, wine=wine_core,
                                        pour_size_ml=177, bottles_received=12,
                                        unit_cost_cents=2400,
                                        received_at="2026-08-10T00:00:00Z")
        slot_1 = fx.open_slot(venue, chain["entry"], chain["lot"], slot_index=1)
        fx.close_slot(slot_1, venue, pours_sold=3)
        fx.set_clock("2026-09-01T14:00:00Z")
        slot_2 = fx.open_slot(venue, chain["entry"], chain["lot"], slot_index=2)
        fx.close_slot(slot_2, venue, pours_sold=2, staff_education_pours=1)
        after_run = fx.run_pour_cost(venue, "2026-09-01T10:00:00Z",
                                     "2026-09-01T14:00:01Z")
        version_2 = fx.create_draft_version(chain["wine_list"], venue)
        return {"venue": venue, "wine_core": wine_core,
                "wine_premium": wine_premium, "chain": chain,
                "after_run": after_run, "version_2": version_2}

    @staticmethod
    def _post_entry(setup, wine, par_bottles):
        venue_id = setup["venue"]["id"]
        version = validate_success(
            api_client.get_list_version(setup["version_2"]["id"],
                                        BEVERAGE_DIRECTOR_HEADERS))
        payload = f.list_entry_payload(wine["id"], version["version"], sort_rank=1,
                                       by_the_glass=False, par_bottles=par_bottles)
        response = api_client.create_list_entry(setup["version_2"]["id"], payload,
                                                sommelier_headers(venue_id))
        return response, version["version"]

    def test_the_pour_cost_run_leaves_the_venue_restricted(self):
        """A 5.56-point spread puts the venue in RESTRICTED posture, above 3.00 and at or below 6.00.

        "The variance is then the theoretical percentage subtracted from the actual percentage and rounded half up to two decimals again — computed from the two **already-rounded** percentages, not from the raw ratios."

        "It is `RESTRICTED` when `last_variance_pct` is strictly greater than 3.00 and at most 6.00 and no investigation is escalated."

        Design: Corner/errors/premium_entry_at_restricted_venue_returns_program_restricted
        """
        setup = self._setup()
        assert float(setup["after_run"]["last_variance_pct"]) == 5.56, (
            "expected a 5.56 point variance, got %r"
            % (setup["after_run"]["last_variance_pct"],))
        assert setup["after_run"]["program_posture"] == "RESTRICTED"
        assert fx.get_venue(setup["venue"])["program_posture"] == "RESTRICTED"

    def test_a_premium_priced_entry_is_refused_at_a_restricted_venue(self):
        """The 5000-cent wine prices into PREMIUM and is refused by the fiscal gate after pricing.

        "A venue that is either `RESTRICTED` or `FROZEN` cannot accept a new list entry whose computed price band lands in the top two bands; that refusal is `ERR_VENUE_PROGRAM_RESTRICTED` (HTTP 409) and it is evaluated only after the entry's price has been computed, because the band is an output of the pricing rule rather than an input to it."

        Design: Corner/errors/premium_entry_at_restricted_venue_returns_program_restricted
        """
        setup = self._setup()
        response, before_version = self._post_entry(setup, setup["wine_premium"], 4)
        _error_with_message(response, ERR_VENUE_PROGRAM_RESTRICTED)
        after = validate_success(
            api_client.get_list_version(setup["version_2"]["id"],
                                        BEVERAGE_DIRECTOR_HEADERS))
        assert after["version"] == before_version, (
            "a refused entry must not bump the version's version integer")
        assert after["entry_count"] == 0

    def test_a_core_priced_entry_is_accepted_at_the_same_restricted_venue(self):
        """The same endpoint and the same posture accept the 2400-cent wine, which prices into CORE.

        "A venue that is either `RESTRICTED` or `FROZEN` cannot accept a new list entry whose computed price band lands in the top two bands; that refusal is `ERR_VENUE_PROGRAM_RESTRICTED` (HTTP 409) and it is evaluated only after the entry's price has been computed, because the band is an output of the pricing rule rather than an input to it."

        Design: Corner/errors/premium_entry_at_restricted_venue_returns_program_restricted
        """
        setup = self._setup()
        response, _before = self._post_entry(setup, setup["wine_core"], 6)
        entry = validate_success(response, 201)
        assert entry["bottle_price_cents"] == 8600
        assert entry["price_band"] == "CORE"
        after = validate_success(
            api_client.get_list_version(setup["version_2"]["id"],
                                        BEVERAGE_DIRECTOR_HEADERS))
        assert after["entry_count"] == 1
        entries, _meta = validate_paginated(
            api_client.list_list_entries(
                BEVERAGE_DIRECTOR_HEADERS,
                params={"list_version_id": setup["version_2"]["id"]}))
        assert [row["id"] for row in entries] == [entry["id"]]


class TestPourPlanMembership:
    """A pour-plan line must name an entry of the event's own pinned version.

    Both wine lists belong to the same venue and both versions are PUBLISHED,
    so the entry named by the rejected plan is real, live and same-venue -- the
    check under test is ownership, not existence.  A line whose pours_per_seat
    is below 1 is refused with the same identifier.
    """

    WINDOW = {"starts_at": "2026-10-10T18:00:00Z",
              "ends_at": "2026-10-10T21:00:00Z",
              "seat_count": 24}

    @staticmethod
    def _setup():
        fx.set_clock("2026-09-01T12:00:00Z")
        venue = fx.create_venue(cogs_target_pct_by_category=HRB_TARGETS)
        wine_x = fx.create_wine(category="RED", reference_cost_cents=2400)
        wine_y = fx.create_wine(category="RED", reference_cost_cents=2400)
        list_1 = fx.create_wine_list(venue, name="Dinner List")
        list_2 = fx.create_wine_list(venue, name="Terrace List")
        version_1 = fx.create_draft_version(list_1, venue)
        entry_x = fx.add_entry(version_1, wine_x, venue, sort_rank=1,
                               by_the_glass=False, par_bottles=6)
        version_1 = fx.publish_version(version_1, venue)
        version_2 = fx.create_draft_version(list_2, venue)
        entry_y = fx.add_entry(version_2, wine_y, venue, sort_rank=1,
                               by_the_glass=False, par_bottles=6)
        version_2 = fx.publish_version(version_2, venue)
        return {"venue": venue, "version_1": version_1, "version_2": version_2,
                "entry_x": entry_x, "entry_y": entry_y}

    @classmethod
    def _post_event(cls, setup, name, line):
        venue_id = setup["venue"]["id"]
        payload = f.wine_dinner_event_payload(venue_id, setup["version_1"]["id"],
                                              [line], name=name, **cls.WINDOW)
        return api_client.create_wine_dinner_event(payload,
                                                   sommelier_headers(venue_id))

    @staticmethod
    def _events(setup):
        venue_id = setup["venue"]["id"]
        return get_all(api_client.list_wine_dinner_events,
                       sommelier_headers(venue_id),
                       params={"venue_id": venue_id})

    def test_a_line_naming_an_entry_of_another_version_is_a_mismatch(self):
        """Entry Y is published and same-venue but lives on the other version, so the plan is refused.

        "Every line's entry must belong to the event's own list version; a line naming an entry from another version, or a line whose `pours_per_seat` is below 1, is refused with `ERR_POUR_PLAN_ENTRY_MISMATCH` (HTTP 422)."

        Design: Corner/errors/pour_plan_line_from_another_version_returns_entry_mismatch
        """
        setup = self._setup()
        response = self._post_event(setup, "Cross Wired",
                                    f.pour_plan_line(setup["entry_y"]["id"], 2))
        _error_with_message(response, ERR_POUR_PLAN_ENTRY_MISMATCH)
        assert self._events(setup) == [], (
            "a refused pour plan must not leave a wine dinner event behind")

    def test_a_line_with_zero_pours_per_seat_is_the_same_mismatch(self):
        """Entry X belongs to the pinned version, but pours_per_seat 0 is below 1 and carries the same error id.

        "Every line's entry must belong to the event's own list version; a line naming an entry from another version, or a line whose `pours_per_seat` is below 1, is refused with `ERR_POUR_PLAN_ENTRY_MISMATCH` (HTTP 422)."

        Design: Corner/errors/pour_plan_line_from_another_version_returns_entry_mismatch
        """
        setup = self._setup()
        response = self._post_event(setup, "Zero Pours",
                                    f.pour_plan_line(setup["entry_x"]["id"], 0))
        _error_with_message(response, ERR_POUR_PLAN_ENTRY_MISMATCH)
        assert self._events(setup) == [], (
            "a refused pour plan must not leave a wine dinner event behind")

    def test_the_correct_plan_is_accepted_after_both_refusals(self):
        """Both refusals left the window free, so the same window is bookable with entry X.

        "A new event starts in state `PLANNED` with `pinned_version_no` set to the referenced version's `version_no`, `pinned_version_stale` false, and all five pricing fields — `beverage_cost_per_seat_cents`, `provisional_gross_cents`, `tier_discount_pct`, `final_ticket_price_cents` and `projected_pour_cost_pct` — null."

        Design: Corner/errors/pour_plan_line_from_another_version_returns_entry_mismatch
        """
        setup = self._setup()
        validate_error(self._post_event(setup, "Cross Wired",
                                        f.pour_plan_line(setup["entry_y"]["id"], 2)),
                       ERR_POUR_PLAN_ENTRY_MISMATCH)
        validate_error(self._post_event(setup, "Zero Pours",
                                        f.pour_plan_line(setup["entry_x"]["id"], 0)),
                       ERR_POUR_PLAN_ENTRY_MISMATCH)
        event = validate_success(
            self._post_event(setup, "Correct Plan",
                             f.pour_plan_line(setup["entry_x"]["id"], 2)), 201)
        assert event["state"] == "PLANNED"
        assert event["pinned_version_no"] == setup["version_1"]["version_no"]
        assert event["pinned_version_stale"] is False
        for field in ("beverage_cost_per_seat_cents", "provisional_gross_cents",
                      "tier_discount_pct", "final_ticket_price_cents",
                      "projected_pour_cost_pct"):
            assert event[field] is None, (
                "a PLANNED event must leave %s null, got %r" % (field, event[field]))
        assert [row["id"] for row in self._events(setup)] == [event["id"]]
