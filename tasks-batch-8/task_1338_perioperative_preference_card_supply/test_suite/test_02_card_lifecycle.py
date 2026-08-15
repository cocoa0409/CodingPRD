"""Preference card lifecycle: publish/supersede, OCC, retire, line immutability."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_card_line,
    api_client,
    get_success_data,
    make_draft_card,
    make_published_card,
    make_supply_item,
    make_surgeon,
    make_case,
    publish_card,
    validate_error,
    validate_paginated,
    validate_success,
)

ANALYST = TEST_USERS["analyst_headers"]
ANY = TEST_USERS["any_headers"]


def _glove_item(**kw):
    defaults = dict(sku="GLOVE-PR", name="Gloves pair", unit_cost_cents=250,
                    substitute_group="GLOVES", initial_on_hand=100)
    defaults.update(kw)
    return make_supply_item(**defaults)


class TestPublishSupersedesPriorActive:
    def test_publish_supersedes_prior_active_version(self):
        """PRD §3.2: "On success the published card's `version` increments by
        one, and any other `ACTIVE` card for the same surgeon-and-procedure
        pair transitions `ACTIVE → SUPERSEDED` with its own `version`
        incremented by one."

        Design: Corner/state_machines/publish_supersedes_prior_active_version
        """
        surgeon = make_surgeon(full_name="Dr. Sup")
        item = _glove_item()
        v1 = make_published_card(surgeon["id"], "TKA",
                                 [{"supply_item_id": item["id"], "quantity": 1}])
        c2 = make_draft_card(surgeon["id"], "TKA")
        add_card_line(c2["id"], item["id"], quantity=3, designation="OPEN",
                      pick_sequence=1)
        v2 = publish_card(c2["id"])
        assert v2["status"] == "ACTIVE"

        v1_after = get_success_data(api_client.get_preference_card(v1["id"], ANY))
        assert v1_after["status"] == "SUPERSEDED"

    def test_exactly_one_active_card_per_pair(self):
        """PRD §3.2: "Publishing is the act that makes a `DRAFT` card
        operative, moving it `DRAFT → ACTIVE`. ... any other `ACTIVE` card for
        the same surgeon-and-procedure pair transitions `ACTIVE → SUPERSEDED`"
        PRD §3.2: "Cards may be listed with `surgeon_id`, `procedure_name`,
        and `status` filters."

        Design: Corner/state_machines/publish_supersedes_prior_active_version
        """
        surgeon = make_surgeon(full_name="Dr. OneActive")
        item = _glove_item()
        make_published_card(surgeon["id"], "TKA",
                            [{"supply_item_id": item["id"], "quantity": 1}])
        c2 = make_draft_card(surgeon["id"], "TKA")
        add_card_line(c2["id"], item["id"], quantity=3)
        publish_card(c2["id"])

        resp = api_client.list_preference_cards(
            ANY, params={"surgeon_id": surgeon["id"], "procedure_name": "TKA",
                         "status": "ACTIVE"}
        )
        rows, meta = validate_paginated(resp)
        assert meta["total_count"] == 1
        assert len(rows) == 1


class TestPublishGuards:
    def test_publish_empty_card_rejected(self):
        """PRD §3.2: "Beyond the OCC check, publish enforces, in the global
        validation order: the card is `DRAFT` (`ERR_CARD_NOT_DRAFT`), it has at
        least one line (`ERR_CARD_EMPTY`)"

        Design: Corner/state_machines/publish_empty_card_rejected
        """
        surgeon = make_surgeon(full_name="Dr. Empty")
        card = make_draft_card(surgeon["id"], "TKA")
        resp = api_client.publish_preference_card(
            card["id"], {"expected_card_version": card["version"]}, ANALYST
        )
        validate_error(resp, ApiErrorId.ERR_CARD_EMPTY)
        after = get_success_data(api_client.get_preference_card(card["id"], ANY))
        assert after["status"] == "DRAFT"

    def test_line_add_to_active_card_returns_card_not_draft(self):
        """PRD §3.2: "Each line references its `card_id` — the card must still
        be `DRAFT`, or the add is rejected with `ERR_CARD_NOT_DRAFT`"

        Design: Corner/validations/line_add_to_active_card_returns_card_not_draft
        """
        surgeon = make_surgeon(full_name="Dr. Lock")
        item_a = _glove_item()
        item_b = make_supply_item(sku="SUTURE-KIT", name="Suture kit",
                                  unit_cost_cents=1000, substitute_group="SUTURE",
                                  initial_on_hand=50)
        card = make_published_card(surgeon["id"], "TKA",
                                   [{"supply_item_id": item_a["id"], "quantity": 1}])
        resp = api_client.create_preference_card_line(
            {"card_id": card["id"], "supply_item_id": item_b["id"],
             "quantity": 1, "designation": "HOLD"},
            ANALYST,
        )
        validate_error(resp, ApiErrorId.ERR_CARD_NOT_DRAFT)
        # Card still has exactly one line.
        lines, meta = validate_paginated(
            api_client.list_preference_card_lines(ANY, params={"card_id": card["id"]})
        )
        assert meta["total_count"] == 1


class TestRetireCard:
    def test_retire_card_with_inflight_case_rejected(self):
        """PRD §3.2: "Retiring an `ACTIVE` card is blocked while any case
        pinned to it is in `SCHEDULED`, `PICKING_RELEASED`, or `IN_PROGRESS` —
        such an attempt is rejected with `ERR_CARD_IN_USE`."

        Design: Corner/state_machines/retire_card_with_inflight_case_rejected
        """
        surgeon = make_surgeon(full_name="Dr. Ret")
        item = _glove_item()
        card = make_published_card(surgeon["id"], "TKA",
                                   [{"supply_item_id": item["id"], "quantity": 1}])
        make_case(surgeon["id"], card["id"], scheduled_start="2026-09-05T08:00:00Z",
                  expected_duration_min=60, room="OR-1")
        resp = api_client.retire_preference_card(card["id"], ANALYST)
        validate_error(resp, ApiErrorId.ERR_CARD_IN_USE)
        after = get_success_data(api_client.get_preference_card(card["id"], ANY))
        assert after["status"] == "ACTIVE"


class TestOccPublish:
    def test_occ_publish_stale_version_rejected(self):
        """PRD §2.6: "Publishing a card requires the request to carry
        `expected_card_version`, holding the card `version` the client last
        observed. If it does not equal the card's current `version` — for
        example because another writer added a line in the meantime, which
        itself increments `version` — the publish is rejected with
        `ERR_STALE_VERSION` (HTTP 412)"

        Design: Corner/cross_cutting/occ_publish_stale_version_rejected
        """
        surgeon = make_surgeon(full_name="Dr. Occ")
        item_a = _glove_item()
        item_b = make_supply_item(sku="SUTURE-KIT", name="Suture kit",
                                  unit_cost_cents=1000, substitute_group="SUTURE",
                                  initial_on_hand=50)
        card = make_draft_card(surgeon["id"], "TKA")
        add_card_line(card["id"], item_a["id"], quantity=1, designation="OPEN",
                      pick_sequence=1)
        stale_v = get_success_data(
            api_client.get_preference_card(card["id"], ANY)
        )["version"]
        add_card_line(card["id"], item_b["id"], quantity=1, designation="HOLD",
                      pick_sequence=2)
        resp = api_client.publish_preference_card(
            card["id"], {"expected_card_version": stale_v}, ANALYST
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    def test_occ_publish_retry_with_fresh_version_succeeds(self):
        """PRD §2.6: "the client must re-read the card and retry against the
        current version."

        Design: Corner/cross_cutting/occ_publish_stale_version_rejected
        """
        surgeon = make_surgeon(full_name="Dr. Occ2")
        item_a = _glove_item()
        item_b = make_supply_item(sku="SUTURE-KIT", name="Suture kit",
                                  unit_cost_cents=1000, substitute_group="SUTURE",
                                  initial_on_hand=50)
        card = make_draft_card(surgeon["id"], "TKA")
        add_card_line(card["id"], item_a["id"], quantity=1, designation="OPEN",
                      pick_sequence=1)
        stale_v = get_success_data(
            api_client.get_preference_card(card["id"], ANY)
        )["version"]
        add_card_line(card["id"], item_b["id"], quantity=1, designation="HOLD",
                      pick_sequence=2)
        resp = api_client.publish_preference_card(
            card["id"], {"expected_card_version": stale_v}, ANALYST
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

        fresh_v = get_success_data(
            api_client.get_preference_card(card["id"], ANY)
        )["version"]
        ok = api_client.publish_preference_card(
            card["id"], {"expected_card_version": fresh_v}, ANALYST
        )
        data = validate_success(ok)
        assert data["status"] == "ACTIVE"
