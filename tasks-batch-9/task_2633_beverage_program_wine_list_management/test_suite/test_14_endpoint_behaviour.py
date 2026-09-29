"""Endpoint behaviour corners of the beverage-program API.

Each test here pins what one endpoint actually does to the records it touches:
the partial semantics and the draft-only window of the list-entry PATCH, the
freeze an investigation escalation imposes, the reprint acknowledgement's
threshold and its clearing effect, the three parents a by-the-glass slot links
in a single call, and the on-demand recomputation of the par report.
"""
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures
from test_helpers.api_client import api_client
from test_helpers.api_errors import (
    ERR_INVESTIGATION_NOT_ACTIONABLE,
    ERR_LIST_VERSION_NOT_DRAFT,
    ERR_LIST_VERSION_NOT_REPRINT_PENDING,
)
from test_helpers.assertions import assert_decimal_equals
from test_helpers.test_users import (
    BEVERAGE_DIRECTOR_HEADERS,
    CONTROLLER_HEADERS,
    sommelier_headers,
)

CATEGORY_TARGETS = {
    "SPARKLING": 30.0,
    "WHITE": 25.0,
    "ROSE": 28.0,
    "RED": 28.0,
    "DESSERT": 32.0,
    "FORTIFIED": 35.0,
}

LOT_RECEIVED_AT = "2026-08-10T00:00:00Z"


def _venue(**overrides):
    return fixtures.create_venue(cogs_target_pct_by_category=CATEGORY_TARGETS,
                                 **overrides)


def _wine(category="RED", reference_cost_cents=2400, **overrides):
    return fixtures.create_wine(category=category,
                                reference_cost_cents=reference_cost_cents,
                                bottle_size_ml=750, case_pack=6,
                                is_allocated=False, **overrides)


def _par_report(venue, headers=None, **params):
    response = api_client.get_par_report(
        venue["id"], headers or sommelier_headers(venue["id"]),
        params=params or None)
    return validate_success(response)


class TestListEntryPatch:
    """The list-entry PATCH is a true partial update and closes the moment its
    parent version leaves DRAFT."""

    @staticmethod
    def _setup():
        fixtures.set_clock("2026-09-01T12:00:00Z")
        venue = _venue()
        wine = _wine()
        chain = fixtures.setup_draft_version(venue)
        entry = fixtures.add_entry(chain["version"], wine, venue, sort_rank=1,
                                   by_the_glass=False, par_bottles=6,
                                   tasting_note="Youthful.",
                                   education_verified=False)
        return venue, chain["version"], entry

    def test_patch_keeps_the_stored_value_of_every_omitted_field(self):
        """Amending only par_bottles leaves the tasting note, the education flag
        and the print order exactly as they were stored.

        "The editable fields are `by_the_glass`, `pour_size_ml`, `tasting_note`, `education_verified`, `par_bottles` and `sort_rank`."

        Design: Corner/endpoints/list_entry_patch_applies_partial_update_only_while_draft
        """
        venue, _version, entry = self._setup()

        patched = validate_success(api_client.patch_list_entry(
            entry["id"], {"par_bottles": 12}, sommelier_headers(venue["id"])))
        assert patched["par_bottles"] == 12
        assert patched["tasting_note"] == "Youthful."
        assert patched["education_verified"] is False
        assert patched["sort_rank"] == 1
        assert patched["by_the_glass"] is False
        assert patched["pour_size_ml"] is None

    def test_patch_never_reprices_the_bottle(self):
        """Neither accepted PATCH moves the frozen bottle price or its band.

        "What editing never does is re-price the bottle: `bottle_price_cents` and `price_band` are frozen at creation and no patch moves them."

        Design: Corner/endpoints/list_entry_patch_applies_partial_update_only_while_draft
        """
        venue, _version, entry = self._setup()
        headers = sommelier_headers(venue["id"])

        first = validate_success(api_client.patch_list_entry(
            entry["id"], {"par_bottles": 12}, headers))
        second = validate_success(api_client.patch_list_entry(
            entry["id"], {"education_verified": True, "sort_rank": 4}, headers))

        for stage in (first, second):
            assert stage["bottle_price_cents"] == entry["bottle_price_cents"], (
                "bottle_price_cents is frozen at creation, got %r"
                % (stage["bottle_price_cents"],))
            assert stage["price_band"] == entry["price_band"]

    def test_patching_education_verified_rescores_the_entry(self):
        """Signing off staff education re-runs the contest score to the flat
        five-point education weight, and each PATCH is one version increment.

        "Changing `education_verified` re-runs the contest score."

        Design: Corner/endpoints/list_entry_patch_applies_partial_update_only_while_draft
        """
        venue, _version, entry = self._setup()
        headers = sommelier_headers(venue["id"])

        validate_success(api_client.patch_list_entry(
            entry["id"], {"par_bottles": 12}, headers))
        patched = validate_success(api_client.patch_list_entry(
            entry["id"], {"education_verified": True, "sort_rank": 4}, headers))

        assert patched["education_verified"] is True
        assert patched["sort_rank"] == 4
        assert patched["par_bottles"] == 12
        assert_decimal_equals(patched["contest_points"], 5.00,
                              "contest_points")
        assert patched["version"] == entry["version"] + 2, (
            "two accepted PATCHes are two mutations: %r" % (patched["version"],))
        assert patched["updated_at"].startswith("2026-09-01T12:00:00"), patched

    def test_patch_is_refused_once_the_version_is_published(self):
        """The identical body that was accepted on the draft is a 409 after
        publication, and the stored par level does not move.

        "Editing an entry is permitted only while its version is still `DRAFT`; otherwise `ERR_LIST_VERSION_NOT_DRAFT`."

        Design: Corner/endpoints/list_entry_patch_applies_partial_update_only_while_draft
        """
        venue, version, entry = self._setup()
        headers = sommelier_headers(venue["id"])

        validate_success(api_client.patch_list_entry(
            entry["id"], {"par_bottles": 12}, headers))
        fixtures.publish_version(version, venue)

        response = api_client.patch_list_entry(
            entry["id"], {"par_bottles": 24}, headers)
        validate_error(response, ERR_LIST_VERSION_NOT_DRAFT)

        unchanged = validate_success(
            api_client.get_list_entry(entry["id"], BEVERAGE_DIRECTOR_HEADERS))
        assert unchanged["par_bottles"] == 12, unchanged


ESCALATION_NOTE = "Backbar pours untracked for two services; escalating to group."


class TestInvestigationEscalation:
    """Escalating the controller's file freezes a venue whose measured variance
    on its own only warrants RESTRICTED."""

    @staticmethod
    def _setup():
        fixtures.set_clock("2026-09-01T10:00:00Z")
        venue = _venue()
        bin_ = fixtures.create_bin(venue, bin_code="A1", zone="CELLAR",
                                   capacity_bottles=48,
                                   temperature_controlled=True)
        wine = _wine()
        lot = fixtures.create_lot(venue, wine, bin_, bottles_received=12,
                                  unit_cost_cents=2400,
                                  received_at=LOT_RECEIVED_AT)
        chain = fixtures.setup_draft_version(venue)
        entry = fixtures.add_entry(chain["version"], wine, venue, sort_rank=1,
                                   by_the_glass=True, pour_size_ml=177,
                                   par_bottles=6, education_verified=False)
        fixtures.publish_version(chain["version"], venue)

        first = fixtures.open_slot(venue, entry, lot, slot_index=1,
                                   preservation_method="ARGON")
        fixtures.close_slot(first, venue, pours_sold=3)
        fixtures.set_clock("2026-09-01T14:00:00Z")
        second = fixtures.open_slot(venue, entry, lot, slot_index=2,
                                    preservation_method="ARGON")
        fixtures.close_slot(second, venue, pours_sold=2,
                            staff_education_pours=1)

        fixtures.run_pour_cost(venue, "2026-09-01T10:00:00Z",
                               "2026-09-01T14:00:01Z")
        investigations = fixtures.open_investigations(venue)
        assert len(investigations) == 1, investigations
        return venue, investigations[0]

    def test_escalation_freezes_a_venue_whose_variance_is_only_restricted(self):
        """A 5.56-point spread leaves the venue RESTRICTED; escalating its
        investigation drives the posture to FROZEN on the state change alone.

        "Escalation moves the file `OPEN → ESCALATED` and recomputes the venue's posture, which necessarily becomes `FROZEN` because an escalated investigation now exists — and that freeze is what stops list publication and event confirmation at the venue until the file is closed."

        Design: Corner/endpoints/escalate_investigation_sets_note_and_freezes_the_venue
        """
        venue, investigation = self._setup()

        assert investigation["state"] == "OPEN", investigation
        assert_decimal_equals(investigation["triggered_variance_pct"], 5.56,
                              "triggered_variance_pct")
        assert investigation["period_start"].startswith("2026-09-01T10:00:00")
        assert investigation["period_end"].startswith("2026-09-01T14:00:01")
        before = fixtures.get_venue(venue)
        assert before["program_posture"] == "RESTRICTED", before

        escalated = validate_success(api_client.escalate_investigation(
            investigation["id"], f.note_payload(ESCALATION_NOTE),
            CONTROLLER_HEADERS))
        assert escalated["state"] == "ESCALATED", escalated
        assert escalated["escalation_note"] == ESCALATION_NOTE

        after = fixtures.get_venue(venue)
        assert after["program_posture"] == "FROZEN", after
        assert_decimal_equals(after["last_variance_pct"], 5.56,
                              "last_variance_pct")

    def test_a_second_escalation_is_refused_rather_than_being_a_no_op(self):
        """Escalating an already-escalated file is a 409 and leaves the stored
        note as the first escalation wrote it.

        "Escalating it is controller-exclusive, carries a mandatory `note` stored as `escalation_note`, and requires the investigation to be in `OPEN`; an already-escalated or already-resolved file is refused with `ERR_INVESTIGATION_NOT_ACTIONABLE` (HTTP 409)."

        Design: Corner/endpoints/escalate_investigation_sets_note_and_freezes_the_venue
        """
        venue, investigation = self._setup()
        validate_success(api_client.escalate_investigation(
            investigation["id"], f.note_payload(ESCALATION_NOTE),
            CONTROLLER_HEADERS))

        response = api_client.escalate_investigation(
            investigation["id"], f.note_payload("Escalating again."),
            CONTROLLER_HEADERS)
        validate_error(response, ERR_INVESTIGATION_NOT_ACTIONABLE)

        unchanged = validate_success(api_client.get_variance_investigation(
            investigation["id"], CONTROLLER_HEADERS))
        assert unchanged["state"] == "ESCALATED", unchanged
        assert unchanged["escalation_note"] == ESCALATION_NOTE

    def test_resolving_explained_thaws_the_venue_to_its_variance_alone(self):
        """Closing the file as EXPLAINED leaves last_variance_pct at 5.56, so the
        venue falls back from FROZEN to RESTRICTED rather than to OPEN.

        "An `EXPLAINED` resolution accepts the variance as real: the venue's `last_variance_pct` is left as it is and the posture is recomputed from that figure alone, so a venue frozen only because this file was escalated thaws to whatever its variance alone implies once no other escalated file remains — `RESTRICTED` if the variance is above 3.00 and at most 6.00, `OPEN` if it is at or below 3.00, and still `FROZEN` if the variance itself exceeds 6.00."

        Design: Corner/endpoints/escalate_investigation_sets_note_and_freezes_the_venue
        """
        venue, investigation = self._setup()
        validate_success(api_client.escalate_investigation(
            investigation["id"], f.note_payload(ESCALATION_NOTE),
            CONTROLLER_HEADERS))

        resolved = validate_success(api_client.resolve_investigation(
            investigation["id"],
            f.resolve_investigation_payload(
                "EXPLAINED",
                "Education pours were real and correctly recorded."),
            CONTROLLER_HEADERS))
        assert resolved["state"] == "RESOLVED_EXPLAINED", resolved
        assert resolved["resolved_at"].startswith("2026-09-01T14:00:00"), resolved

        after = fixtures.get_venue(venue)
        assert after["program_posture"] == "RESTRICTED", after
        assert_decimal_equals(after["last_variance_pct"], 5.56,
                              "last_variance_pct")


class TestMarkReprinted:
    """A live version reaches REPRINT_PENDING only on the second stale entry,
    and only from there may the reprint be acknowledged."""

    @staticmethod
    def _setup():
        fixtures.set_clock("2026-09-01T12:00:00Z")
        venue = _venue()
        wine_a = _wine(category="RED", reference_cost_cents=2400)
        wine_b = _wine(category="WHITE", reference_cost_cents=3000)
        chain = fixtures.setup_draft_version(venue)
        entry_a = fixtures.add_entry(chain["version"], wine_a, venue,
                                     sort_rank=1, by_the_glass=False,
                                     par_bottles=6)
        entry_b = fixtures.add_entry(chain["version"], wine_b, venue,
                                     sort_rank=2, by_the_glass=False,
                                     par_bottles=6)
        version = fixtures.publish_version(chain["version"], venue)
        return venue, wine_a, wine_b, version, entry_a, entry_b

    def test_mark_reprinted_is_refused_on_a_clean_published_version(self):
        """A version with nothing stale on it has no reprint obligation to clear.

        "That acknowledgement requires the version to be in `REPRINT_PENDING` — otherwise `ERR_LIST_VERSION_NOT_REPRINT_PENDING` (HTTP 409) — and moves it `REPRINT_PENDING → PUBLISHED`."

        Design: Corner/endpoints/mark_reprinted_requires_reprint_pending_and_clears_stale_flags
        """
        venue, _wine_a, _wine_b, version, _entry_a, _entry_b = self._setup()
        assert version["state"] == "PUBLISHED", version

        response = api_client.mark_reprinted_list_version(
            version["id"], sommelier_headers(venue["id"]))
        validate_error(response, ERR_LIST_VERSION_NOT_REPRINT_PENDING)

    def test_one_stale_entry_stays_below_the_reprint_threshold(self):
        """A single superseded vintage is tolerated as an errata: the version
        stays PUBLISHED and the acknowledgement is still refused.

        "Each affected version recounts its `stale_entry_count` and rewrites `reprint_required`, which is true exactly when the stale count has reached two entries and false below that."

        Design: Corner/endpoints/mark_reprinted_requires_reprint_pending_and_clears_stale_flags
        """
        venue, wine_a, _wine_b, version, entry_a, _entry_b = self._setup()

        _wine(category="RED", reference_cost_cents=2600, vintage_year=2020,
              predecessor_wine_id=wine_a["id"])

        stale_entry = validate_success(
            api_client.get_list_entry(entry_a["id"], BEVERAGE_DIRECTOR_HEADERS))
        assert stale_entry["vintage_stale"] is True, stale_entry
        current = validate_success(api_client.get_list_version(
            version["id"], BEVERAGE_DIRECTOR_HEADERS))
        assert current["stale_entry_count"] == 1, current
        assert current["reprint_required"] is False, current
        assert current["state"] == "PUBLISHED", current

        response = api_client.mark_reprinted_list_version(
            version["id"], sommelier_headers(venue["id"]))
        validate_error(response, ERR_LIST_VERSION_NOT_REPRINT_PENDING)

    def test_the_second_stale_entry_forces_a_reprint_the_acknowledgement_clears(self):
        """The second vintage change drives the version to REPRINT_PENDING, and
        the acknowledgement returns it to PUBLISHED with every flag cleared.

        "It stamps `printed_at` with the logical clock, clears `vintage_stale` to false on every entry of the version, resets `stale_entry_count` to 0 and sets `reprint_required` back to false."

        Design: Corner/endpoints/mark_reprinted_requires_reprint_pending_and_clears_stale_flags
        """
        venue, wine_a, wine_b, version, entry_a, entry_b = self._setup()

        _wine(category="RED", reference_cost_cents=2600, vintage_year=2020,
              predecessor_wine_id=wine_a["id"])
        _wine(category="WHITE", reference_cost_cents=3200, vintage_year=2022,
              predecessor_wine_id=wine_b["id"])

        pending = validate_success(api_client.get_list_version(
            version["id"], BEVERAGE_DIRECTOR_HEADERS))
        assert pending["stale_entry_count"] == 2, pending
        assert pending["reprint_required"] is True, pending
        assert pending["state"] == "REPRINT_PENDING", pending

        reprinted = validate_success(api_client.mark_reprinted_list_version(
            version["id"], sommelier_headers(venue["id"])))
        assert reprinted["state"] == "PUBLISHED", reprinted
        assert reprinted["printed_at"].startswith("2026-09-01T12:00:00"), reprinted
        assert reprinted["stale_entry_count"] == 0, reprinted
        assert reprinted["reprint_required"] is False, reprinted

        for entry_id in (entry_a["id"], entry_b["id"]):
            entry = validate_success(
                api_client.get_list_entry(entry_id, BEVERAGE_DIRECTOR_HEADERS))
            assert entry["vintage_stale"] is False, entry


class TestBtgSlotCreationLinks:
    """One slot creation links a venue, a list entry and a lot, and the link is
    directional: it reserves a bottle without depleting it."""

    @staticmethod
    def _setup():
        fixtures.set_clock("2026-09-01T12:00:00Z")
        venue = _venue()
        bin_ = fixtures.create_bin(venue, bin_code="A1", zone="CELLAR",
                                   capacity_bottles=48,
                                   temperature_controlled=True)
        wine = _wine()
        lot = fixtures.create_lot(venue, wine, bin_, bottles_received=6,
                                  unit_cost_cents=2400,
                                  received_at=LOT_RECEIVED_AT)
        chain = fixtures.setup_draft_version(venue)
        entry = fixtures.add_entry(chain["version"], wine, venue, sort_rank=1,
                                   by_the_glass=True, pour_size_ml=177,
                                   par_bottles=6, education_verified=False)
        fixtures.publish_version(chain["version"], venue)
        return venue, lot, entry

    def test_opening_a_slot_commits_a_bottle_without_depleting_the_lot(self):
        """The created slot names all three parents and snapshots the entry's
        pour target, while the lot's bottles_on_hand does not move.

        "On the inventory side the lot's `bottles_committed` rises by 1 while its `bottles_on_hand` is deliberately left alone — the bottle is spoken for but has not yet left the cellar's books."

        Design: Corner/endpoints/btg_slot_creation_links_venue_entry_and_lot_in_one_call
        """
        venue, lot, entry = self._setup()

        slot = validate_success(api_client.create_btg_slot(
            f.btg_slot_payload(venue["id"], entry["id"], lot["id"],
                               slot_index=1, preservation_method="ARGON"),
            sommelier_headers(venue["id"])), 201)
        assert slot["venue_id"] == venue["id"]
        assert slot["list_entry_id"] == entry["id"]
        assert slot["lot_id"] == lot["id"]
        assert slot["slot_index"] == 1
        assert slot["state"] == "OPEN"
        assert slot["effective_pours"] == 3, (
            "effective_pours is copied from the entry at open time: %r" % (slot,))

        stored_lot = validate_success(
            api_client.get_inventory_lot(lot["id"], BEVERAGE_DIRECTOR_HEADERS))
        assert stored_lot["bottles_committed"] == 1, stored_lot
        assert stored_lot["bottles_on_hand"] == 6, (
            "opening a slot reserves, it does not deplete: %r" % (stored_lot,))
        assert stored_lot["state"] == "ON_HAND", stored_lot

        rows, meta = validate_paginated(api_client.list_depletion_entries(
            BEVERAGE_DIRECTOR_HEADERS, params={"btg_slot_id": slot["id"]}))
        assert rows == [] and meta["total_count"] == 0, (
            "an open slot has recognised nothing yet: %r" % (rows,))

        unchanged_entry = validate_success(
            api_client.get_list_entry(entry["id"], BEVERAGE_DIRECTOR_HEADERS))
        assert_decimal_equals(unchanged_entry["contest_points"], 0.00,
                              "contest_points")
        assert unchanged_entry["availability_state"] == "AVAILABLE", unchanged_entry

    def test_the_slot_resolves_from_the_entry_side_and_the_lot_side(self):
        """Both declared slot filters find the same single rail position.

        "Slots may be listed filtered by `venue_id`, `list_entry_id`, `lot_id` and `state`."

        Design: Corner/endpoints/btg_slot_creation_links_venue_entry_and_lot_in_one_call
        """
        venue, lot, entry = self._setup()
        slot = fixtures.open_slot(venue, entry, lot, slot_index=1,
                                  preservation_method="ARGON")

        by_entry, _meta = validate_paginated(api_client.list_btg_slots(
            CONTROLLER_HEADERS, params={"list_entry_id": entry["id"]}))
        assert [row["id"] for row in by_entry] == [slot["id"]], by_entry

        by_lot, _meta = validate_paginated(api_client.list_btg_slots(
            CONTROLLER_HEADERS, params={"lot_id": lot["id"], "state": "OPEN"}))
        assert [row["id"] for row in by_lot] == [slot["id"]], by_lot


class TestParReportRecomputesOnDemand:
    """The par report is derived at read time, so an approved write-off changes
    the answer the same URL gives."""

    @staticmethod
    def _setup():
        fixtures.set_clock("2026-09-01T12:00:00Z")
        venue = _venue()
        bin_ = fixtures.create_bin(venue, bin_code="A1", zone="CELLAR",
                                   capacity_bottles=48,
                                   temperature_controlled=True)
        wine = _wine()
        lot = fixtures.create_lot(venue, wine, bin_, bottles_received=12,
                                  unit_cost_cents=2400,
                                  received_at=LOT_RECEIVED_AT)
        chain = fixtures.setup_draft_version(venue)
        entry = fixtures.add_entry(chain["version"], wine, venue, sort_rank=1,
                                   by_the_glass=False, par_bottles=12)
        fixtures.publish_version(chain["version"], venue)
        write_off = fixtures.submit_write_off(
            venue, lot, bottles=8, reason_code="TEMPERATURE",
            narrative="Cellar cooling failure over the weekend.")
        assert write_off["state"] == "SUBMITTED", write_off
        return venue, lot, entry, write_off

    def test_a_submitted_write_off_moves_no_par_numbers(self):
        """While the loss is only proposed the report still sees all 12 bottles.

        "Nothing moves in inventory or in either ledger until a controller acts."

        Design: Corner/endpoints/par_report_recomputes_after_a_write_off_rather_than_caching
        """
        venue, _lot, entry, _write_off = self._setup()

        report = _par_report(venue)
        assert report["line_count"] == 1, report
        assert report["urgent_line_count"] == 0, report
        line = report["lines"][0]
        assert line["list_entry_id"] == entry["id"]
        assert line["bottles_on_hand"] == 12
        assert line["deficit_bottles"] == 0
        assert line["reorder_bottles"] == 0
        assert line["is_urgent"] is False

    def test_the_same_url_answers_differently_after_the_approval(self):
        """Approving the write-off drops the lot to four bottles, and the next
        read of the same report reorders two cases and flags the line urgent.

        "On approval the write-off moves `SUBMITTED → APPROVED`, records `approved_by_user_id` as the acting `X-User-ID`, and computes `cogs_cents` by pricing the written-off bottles out of that one nominated lot under the venue's costing method."

        Design: Corner/endpoints/par_report_recomputes_after_a_write_off_rather_than_caching
        """
        venue, lot, entry, write_off = self._setup()
        _par_report(venue)

        approved = validate_success(
            api_client.approve_write_off(write_off["id"], CONTROLLER_HEADERS))
        assert approved["state"] == "APPROVED", approved
        assert approved["cogs_cents"] == 19200, (
            "8 bottles priced out of the nominated lot at 2400 cents: %r"
            % (approved,))

        stored_lot = validate_success(
            api_client.get_inventory_lot(lot["id"], BEVERAGE_DIRECTOR_HEADERS))
        assert stored_lot["bottles_on_hand"] == 4, stored_lot

        report = _par_report(venue)
        assert report["generated_at"].startswith("2026-09-01T12:00:00"), report
        assert report["line_count"] == 1, report
        assert report["urgent_line_count"] == 1, report
        line = report["lines"][0]
        assert line["bottles_on_hand"] == 4, line
        assert line["deficit_bottles"] == 8, line
        assert line["reorder_bottles"] == 12, line
        assert line["is_urgent"] is True, line

        urgent = _par_report(venue, headers=BEVERAGE_DIRECTOR_HEADERS,
                             urgent_only="true")
        assert [row["list_entry_id"] for row in urgent["lines"]] == [entry["id"]]

        still_listed = validate_success(
            api_client.get_list_entry(entry["id"], BEVERAGE_DIRECTOR_HEADERS))
        assert still_listed["availability_state"] == "AVAILABLE", (
            "four bottles remain on hand, so no availability flip occurred: %r"
            % (still_listed,))
