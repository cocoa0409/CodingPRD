"""Document checklists: generation cascade, item workflow, archival lockdown,
and waivability (PRD §3.5, §3.9)."""
from test_helpers import (
    ADMIN,
    ApiErrorId,
    REVIEWER,
    TEMPLATE_DEPENDENT_STANDARD,
    coord,
    create_matched_senior,
    create_specialist,
    create_support_case,
    fresh_senior,
    get_checklist_for_senior,
    get_checklist_items,
    receive_and_verify_item,
    setup_campaign_with_school,
    spec_headers,
    validate_error,
    validate_success,
)


class TestMatchConfirmGeneratesChecklist:
    def _setup(self, api):
        """Senior (home language es, DEPENDENT) with a SUGGESTED link; the aid
        record is STARTED. Consent in place so the fafsa axis is readable."""
        campaign, school = setup_campaign_with_school()
        senior, aid, link, _consent = create_matched_senior(
            campaign,
            school,
            student_ref="S1",
            full_name="Ana Lee",
            dob="2009-03-04",
            home_language="es",
            aid_school_code="SC99",  # 0.85 band -> SUGGESTED
            aid_status="STARTED",
            aid_effective_date="2027-01-10",
            consent_scopes=["STATUS_DETAIL"],
            consent_before_link=True,
        )
        assert link["status"] == "SUGGESTED"
        return campaign, school, senior, link

    def test_confirm_fires_matched_cascade_and_initializes_fafsa_axis(self, api):
        """PRD §3.5: "the reviewer may confirm it, moving the link from
        `SUGGESTED` to `CONFIRMED` and firing the identical matched cascade" —
        the cascade in which "`fafsa_status` initializes from the linked aid
        record's `current_status`".

        Design: Difficulty/transitive_cascade/match_confirm_checklist_generation_depth2
        """
        _campaign, _school, senior, link = self._setup(api)
        resp = api.confirm_match_link(link["id"], REVIEWER)
        confirmed = validate_success(resp, 200)
        assert confirmed["status"] == "CONFIRMED"

        senior = fresh_senior(senior["id"])
        assert senior["match_status"] == "MATCHED"
        assert senior["fafsa_status"] == "STARTED", (
            f"fafsa axis must initialize from the linked aid record, got "
            f"{senior['fafsa_status']}"
        )
        assert senior["current_match_link_id"] == link["id"]

    def test_confirm_generates_dependent_checklist_in_home_language(self, api):
        """PRD §3.9: "The checklist copies its `language` from the senior's
        `home_language` at generation, and its `template_key` is keyed on the
        senior's `dependency_status` at that moment: `DEPENDENT_STANDARD` —
        items in the order `STUDENT_ID`, `STUDENT_TAX_RETURN`,
        `PARENT_TAX_RETURN`, `BANK_STATEMENT` — for dependent students" and
        "Each item ... starts `PENDING`."

        Design: Difficulty/transitive_cascade/match_confirm_checklist_generation_depth2
        """
        _campaign, _school, senior, link = self._setup(api)
        api.confirm_match_link(link["id"], REVIEWER)

        checklist = get_checklist_for_senior(senior["id"])
        assert checklist["language"] == "es"
        assert checklist["template_key"] == "DEPENDENT_STANDARD"
        assert checklist["status"] == "GENERATED"

        items = get_checklist_items(checklist["id"])
        assert [item["doc_type"] for item in items] == TEMPLATE_DEPENDENT_STANDARD
        assert all(item["status"] == "PENDING" for item in items)


class TestChecklistItemWorkflow:
    def _matched_senior_with_checklist(self, api):
        campaign, school = setup_campaign_with_school()
        senior, _aid, link, _c = create_matched_senior(
            campaign,
            school,
            student_ref="S1",
            full_name="Ana Lee",
            dob="2009-03-04",
            aid_status="SUBMITTED",
        )
        assert link["status"] == "AUTO_CONFIRMED"
        checklist = get_checklist_for_senior(senior["id"])
        items = get_checklist_items(checklist["id"])
        return school, senior, link, checklist, items

    def test_item_reject_resubmit_cycle_and_checklist_completion(self, api):
        """PRD §3.9: "receiving moves an item from `PENDING` — or from
        `REJECTED`, giving families a second chance — to `RECEIVED`" and "from
        `RECEIVED` the coordinator verifies to `VERIFIED` or rejects to
        `REJECTED`".
        PRD §3.9: "it starts `GENERATED`, moves to `IN_PROGRESS` when the first
        item leaves `PENDING`, reaches `COMPLETE` when every item stands in
        `VERIFIED` or `WAIVED`".

        Design: Corner/state_machines/checklist_item_reject_resubmit_cycle
        """
        school, _senior, _link, checklist, items = (
            self._matched_senior_with_checklist(api)
        )
        assert checklist["status"] == "GENERATED"

        first = items[0]["id"]
        api.receive_checklist_item(first, coord(school))
        # The first item leaving PENDING flips the checklist to IN_PROGRESS.
        resp = api.get_document_checklist(checklist["id"], ADMIN)
        assert validate_success(resp, 200)["status"] == "IN_PROGRESS"

        resp = api.reject_checklist_item(first, coord(school))
        assert validate_success(resp, 200)["status"] == "REJECTED"
        # REJECTED is not a dead end: the item can be received again.
        resp = api.receive_checklist_item(first, coord(school))
        assert validate_success(resp, 200)["status"] == "RECEIVED"
        resp = api.verify_checklist_item(first, coord(school))
        assert validate_success(resp, 200)["status"] == "VERIFIED"

        for item in items[1:]:
            receive_and_verify_item(school, item["id"])

        resp = api.get_document_checklist(checklist["id"], ADMIN)
        assert validate_success(resp, 200)["status"] == "COMPLETE", (
            "all four items VERIFIED must complete the checklist"
        )

    def test_verify_requires_received_state(self, api):
        """PRD §3.9: "from `RECEIVED` the coordinator verifies to `VERIFIED` or
        rejects to `REJECTED` (either action on a non-`RECEIVED` item draws
        `ERR_ITEM_NOT_RECEIVED`)".

        Design: Corner/state_machines/checklist_item_verify_requires_received
        """
        school, _senior, _link, _checklist, items = (
            self._matched_senior_with_checklist(api)
        )
        first = items[0]["id"]
        resp = api.verify_checklist_item(first, coord(school))
        validate_error(resp, ApiErrorId.ERR_ITEM_NOT_RECEIVED)
        remaining = get_checklist_items(items[0]["checklist_id"])
        assert remaining[0]["status"] == "PENDING", (
            "the rejected verify must not move the item out of PENDING"
        )

    def test_archived_checklist_items_are_frozen(self, api):
        """PRD §3.9: "If the senior's match link is ever invalidated, the
        checklist — whatever its state — is archived and its items freeze" and
        "any item operation against an `ARCHIVED` checklist draws
        `ERR_CHECKLIST_ARCHIVED`".

        Design: Corner/state_machines/archived_checklist_items_locked
        """
        school, _senior, link, checklist, items = (
            self._matched_senior_with_checklist(api)
        )
        api.invalidate_match_link(link["id"], REVIEWER)

        resp = api.get_document_checklist(checklist["id"], ADMIN)
        assert validate_success(resp, 200)["status"] == "ARCHIVED"

        resp = api.receive_checklist_item(items[0]["id"], coord(school))
        validate_error(resp, ApiErrorId.ERR_CHECKLIST_ARCHIVED)
        assert get_checklist_items(checklist["id"])[0]["status"] == "PENDING"

    def test_waive_non_waivable_item_rejected(self, api):
        """PRD §3.9: "an item's `waivable` flag is computed as true exactly
        when its `doc_type` is `BANK_STATEMENT` or `DEPENDENCY_OVERRIDE_FORM`"
        and "a specialist moves a `PENDING` item to `WAIVED` only if the item
        is `waivable` (else `ERR_ITEM_NOT_WAIVABLE`, HTTP 422)".

        Design: Corner/errors/waive_non_waivable_item_rejected
        """
        campaign, school = setup_campaign_with_school()
        senior, _aid, link, _c = create_matched_senior(
            campaign,
            school,
            student_ref="S1",
            full_name="Ana Lee",
            dob="2009-03-04",
            aid_status="SUBMITTED",
        )
        assert link["status"] == "AUTO_CONFIRMED"
        specialist = create_specialist(campaign)
        # The acting specialist holds a non-terminal case for this senior, so
        # only the waivability gate can fail.
        case = create_support_case(school, senior["id"], "SPECIAL_CIRCUMSTANCE")
        assert case["assigned_specialist_id"] == specialist["id"]

        checklist = get_checklist_for_senior(senior["id"])
        first = get_checklist_items(checklist["id"])[0]
        assert first["doc_type"] == "STUDENT_ID"
        assert first["waivable"] is False

        resp = api.waive_checklist_item(first["id"], spec_headers(specialist))
        validate_error(resp, ApiErrorId.ERR_ITEM_NOT_WAIVABLE)
        assert get_checklist_items(checklist["id"])[0]["status"] == "PENDING"
