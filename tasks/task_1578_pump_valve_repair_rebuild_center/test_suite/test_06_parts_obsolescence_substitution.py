"""Parts catalog: obsolescence cascades, supersession integrity, and
substitution validation at quote issuance."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    add_ro_in_quote_in_progress,
    api_client,
    create_part,
    create_quote_for_ro,
    get_part,
    get_quote,
    get_repair_order,
    get_success_data,
    issue_quote,
    issue_quote_for,
    quote_part_line,
    setup_issued_quote_shop,
    setup_quote_in_progress_shop,
    validate_error,
)

SM = TEST_USERS["service_manager_headers"]


class TestObsolescenceCascade:
    def test_mark_obsolete_forces_issued_quote_into_revision(self, api):
        """PRD §3.5: "First, every quote in `DRAFT`, `ISSUED`, or `REVISION_REQUESTED` whose `part_lines` contain the part has those lines flagged `substitution_required`."
        PRD §3.5: "Second, every such quote still `ISSUED` is forced `ISSUED` → `REVISION_REQUESTED`, and its repair order's `quote_attention_required` flag is set true — the customer sees a revision request they never asked for."
        PRD §3.5: "Marking a part obsolete moves it `ACTIVE` → `OBSOLETE`; an optional `superseded_by_id` may record the replacement part, but that target must exist, be `ACTIVE`, and not be the part itself, and any violation is rejected with `ERR_SUPERSEDES_NOT_ACTIVE`."

        Design: Difficulty/transitive_cascade/part_obsolescence_forces_quote_revision_cascade
        """
        part = create_part(part_number="TRIM-9", description="Valve trim",
                           unit_price_cents=5000)
        shop = setup_issued_quote_shop(
            quote_over={"labor_hours": 2,
                        "part_lines": [quote_part_line(part["id"], 1, 5000)]})
        assert shop["quote"]["status"] == "ISSUED"

        obsolete = get_success_data(api_client.mark_part_obsolete(part["id"], {}, SM))
        assert obsolete["status"] == "OBSOLETE"

        quote = get_quote(shop["quote"]["id"])
        assert quote["status"] == "REVISION_REQUESTED", "cascade link 2 forces the fork"
        assert quote["part_lines"][0]["substitution_required"] is True, (
            "cascade link 1 flags the affected line"
        )

        ro = get_repair_order(shop["ro"]["id"])
        assert ro["quote_attention_required"] is True, "cascade link 2 flags the order"
        assert ro["status"] == "QUOTE_IN_PROGRESS", "the order itself does not move"

    def test_obsolescence_flags_draft_lines_without_forcing_revision(self, api):
        """PRD §3.5: "First, every quote in `DRAFT`, `ISSUED`, or `REVISION_REQUESTED` whose `part_lines` contain the part has those lines flagged `substitution_required`."
        PRD §3.5: "Second, every such quote still `ISSUED` is forced `ISSUED` → `REVISION_REQUESTED`, and its repair order's `quote_attention_required` flag is set true — the customer sees a revision request they never asked for."
        PRD §3.3: "The `capacity_window_id` and `assembled_by_id` fields remain null until quote approval and assembly logging respectively, while `invoiced_total_cents` and `closed_at` remain null until closeout, and `quote_attention_required` stays false unless parts obsolescence forces a quote revision (§3.5)."

        Design: Difficulty/transitive_cascade/part_obsolescence_forces_quote_revision_cascade
        """
        affected = create_part(part_number="TRIM-10", description="Valve trim",
                               unit_price_cents=5000)
        unrelated = create_part(part_number="BOLT-10", description="Bolt set",
                                unit_price_cents=900)

        # Order 1: quote still DRAFT containing the affected part.
        shop = setup_quote_in_progress_shop()
        draft = create_quote_for_ro(
            shop["ro"]["id"], shop["window"]["id"], labor_hours=1,
            part_lines=[quote_part_line(affected["id"], 1, 5000)])

        # Order 2: ISSUED quote with no line on the affected part.
        ro2 = add_ro_in_quote_in_progress(shop)
        issued_other = issue_quote_for(
            shop, ro=ro2,
            quote_over={"labor_hours": 1,
                        "part_lines": [quote_part_line(unrelated["id"], 4, 900)]})

        get_success_data(api_client.mark_part_obsolete(affected["id"], {}, SM))

        # DRAFT quote: line flagged, but the forced fork only applies to ISSUED.
        draft_after = get_quote(draft["id"])
        assert draft_after["status"] == "DRAFT"
        assert draft_after["part_lines"][0]["substitution_required"] is True
        assert get_repair_order(shop["ro"]["id"])["quote_attention_required"] is False

        # The quote without the part is untouched entirely.
        other_after = get_quote(issued_other["id"])
        assert other_after["status"] == "ISSUED"
        assert get_repair_order(ro2["id"])["quote_attention_required"] is False


class TestSubstitutionAtIssue:
    def test_substitution_target_must_be_obsolete(self, api):
        """PRD §3.6: "Issuance validates every part line: a line referencing an `OBSOLETE` part without a valid substitution is rejected with `ERR_PART_OBSOLETE`; a line whose `substitution_for_part_id` references a part that is not `OBSOLETE` is rejected with `ERR_SUBSTITUTION_TARGET_NOT_OBSOLETE`; and a line substituting an obsolete part whose `aftermarket_allowed` is false is rejected with `ERR_SUBSTITUTION_NOT_ALLOWED`."

        Design: Corner/validations/substitution_target_must_be_obsolete
        """
        oem = create_part(part_number="TRIM-A", description="OEM trim",
                          unit_price_cents=5000, aftermarket_allowed=True)
        sub = create_part(part_number="TRIM-AM", description="Aftermarket trim",
                          unit_price_cents=4000)
        shop = setup_quote_in_progress_shop()
        quote = create_quote_for_ro(
            shop["ro"]["id"], shop["window"]["id"], labor_hours=1,
            part_lines=[quote_part_line(sub["id"], 1, 4000,
                                        substitution_for_part_id=oem["id"])])

        resp = api_client.issue_quote(quote["id"], SM)
        validate_error(resp, ApiErrorId.ERR_SUBSTITUTION_TARGET_NOT_OBSOLETE)
        assert get_quote(quote["id"])["status"] == "DRAFT"

    def test_substitution_requires_aftermarket_allowed(self, api):
        """PRD §3.6: "a line substituting an obsolete part whose `aftermarket_allowed` is false is rejected with `ERR_SUBSTITUTION_NOT_ALLOWED`."

        Design: Corner/validations/substitution_requires_aftermarket_allowed
        """
        oem = create_part(part_number="DISC-O", description="OEM disc",
                          unit_price_cents=5000, aftermarket_allowed=False)
        sub = create_part(part_number="DISC-AM", description="Aftermarket disc",
                          unit_price_cents=4000)
        get_success_data(api_client.mark_part_obsolete(oem["id"], {}, SM))

        shop = setup_quote_in_progress_shop()
        quote = create_quote_for_ro(
            shop["ro"]["id"], shop["window"]["id"], labor_hours=1,
            part_lines=[quote_part_line(sub["id"], 1, 4000,
                                        substitution_for_part_id=oem["id"])])

        resp = api_client.issue_quote(quote["id"], SM)
        validate_error(resp, ApiErrorId.ERR_SUBSTITUTION_NOT_ALLOWED)
        assert get_quote(quote["id"])["status"] == "DRAFT"

    def test_obsolete_part_without_substitution_rejected_at_issue(self, api):
        """PRD §3.6: "Issuance validates every part line: a line referencing an `OBSOLETE` part without a valid substitution is rejected with `ERR_PART_OBSOLETE`; a line whose `substitution_for_part_id` references a part that is not `OBSOLETE` is rejected with `ERR_SUBSTITUTION_TARGET_NOT_OBSOLETE`; and a line substituting an obsolete part whose `aftermarket_allowed` is false is rejected with `ERR_SUBSTITUTION_NOT_ALLOWED`."
        PRD §3.5: "First, every quote in `DRAFT`, `ISSUED`, or `REVISION_REQUESTED` whose `part_lines` contain the part has those lines flagged `substitution_required`."

        Design: Corner/validations/obsolete_part_without_substitution_rejected_at_issue
        """
        part = create_part(part_number="SEAT-O", description="OEM seat",
                           unit_price_cents=5000)
        shop = setup_quote_in_progress_shop()
        quote = create_quote_for_ro(
            shop["ro"]["id"], shop["window"]["id"], labor_hours=1,
            part_lines=[quote_part_line(part["id"], 1, 5000)])

        # The part goes obsolete after composition: the open line is flagged.
        get_success_data(api_client.mark_part_obsolete(part["id"], {}, SM))

        resp = api_client.issue_quote(quote["id"], SM)
        validate_error(resp, ApiErrorId.ERR_PART_OBSOLETE)
        after = get_quote(quote["id"])
        assert after["status"] == "DRAFT"
        assert after["part_lines"][0]["substitution_required"] is True


class TestSupersessionIntegrity:
    def test_supersede_target_must_be_active(self, api):
        """PRD §3.5: "Marking a part obsolete moves it `ACTIVE` → `OBSOLETE`; an optional `superseded_by_id` may record the replacement part, but that target must exist, be `ACTIVE`, and not be the part itself, and any violation is rejected with `ERR_SUPERSEDES_NOT_ACTIVE`."

        Design: Corner/validations/mark_obsolete_supersede_target_must_be_active
        """
        p1 = create_part(part_number="GSK-1", description="Gasket v1",
                         unit_price_cents=900)
        p2 = create_part(part_number="GSK-2", description="Gasket v2",
                         unit_price_cents=950)
        get_success_data(api_client.mark_part_obsolete(p2["id"], {}, SM))
        assert get_part(p2["id"])["status"] == "OBSOLETE"

        resp = api_client.mark_part_obsolete(p1["id"], {"superseded_by_id": p2["id"]}, SM)
        validate_error(resp, ApiErrorId.ERR_SUPERSEDES_NOT_ACTIVE)
        assert get_part(p1["id"])["status"] == "ACTIVE", "the failed call changes nothing"
