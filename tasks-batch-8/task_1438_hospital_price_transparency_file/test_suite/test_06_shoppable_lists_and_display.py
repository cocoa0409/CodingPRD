"""Shoppable-service lists: entry composition, certification thresholds,
publish pinning/auto-archive, and the consumer display computation."""
from test_helpers import (
    ApiErrorId,
    certify_list,
    create_charge_record,
    create_contract,
    create_cycle,
    create_facility,
    create_payer,
    create_rate,
    create_service_item,
    create_shoppable_list,
    freeze_cycle,
    generate_machine_file,
    get_success_data,
    make_officer_headers,
    publish_cycle,
    publish_list,
    setup_published_cycle,
    setup_published_shoppable_list,
    shoppable_entry,
    validate_error,
    validate_machine_file,
    validate_paginated,
    validate_record,
    validate_success,
)
from test_helpers.fixtures import AUDITOR, CONSUMER, MANAGER, OFFICER


class TestListCreate:
    def test_shoppable_list_create_computes_entry_aggregates(self, api):
        """PRD section 3.5: "Two aggregates are computed at creation and refreshed as entries change: `entry_count` is the number of elements in `entries`, and `mandated_entry_count` counts the entries whose service item has `cms_shoppable_mandated` set."
        PRD section 3.5: "Certification moves a list `DRAFT → CERTIFIED`."

        Design: Corner/entities/shoppable_list_create_computes_entry_aggregates
        """
        fac = create_facility(name="F", cms_certification_number="CCN-E5",
                              bed_count=50)
        si1 = create_service_item(fac["id"], code="70551", description="MRI",
                                  gross_charge_cents=100000,
                                  cms_shoppable_mandated=True)
        si2 = create_service_item(fac["id"], code="70450", description="CT",
                                  gross_charge_cents=80000)
        lst = create_shoppable_list(fac["id"], [
            shoppable_entry(si1["id"], display_name="MRI", display_order=1),
            shoppable_entry(si2["id"], display_name="CT", display_order=2),
        ])
        assert lst["entry_count"] == 2
        assert lst["mandated_entry_count"] == 1
        assert lst["status"] == "DRAFT"

    def test_entry_item_must_be_shoppable_class(self, api):
        """PRD section 3.5: "Every entry's item must belong to the same facility, must not be `RETIRED` (`ERR_ITEM_RETIRED`), and must carry `service_class` `SHOPPABLE` (`ERR_ENTRY_NOT_SHOPPABLE`)."

        Design: Corner/validations/entry_item_must_be_shoppable_class
        """
        fac = create_facility(name="F", cms_certification_number="CCN-H14",
                              bed_count=50)
        anc = create_service_item(
            fac["id"], code="J2400", code_type="HCPCS",
            description="Injection", service_class="ANCILLARY",
            gross_charge_cents=1000, ancillary_inclusion="ALWAYS_BUNDLED")
        resp = api.create_shoppable_list(
            {"facility_id": fac["id"], "title": "L",
             "entries": [shoppable_entry(anc["id"], display_name="bad")]},
            OFFICER)
        validate_error(resp, ApiErrorId.ERR_ENTRY_NOT_SHOPPABLE)

    def test_bundled_item_must_be_ancillary_class(self, api):
        """PRD section 3.5: "Every item named in `bundled_ancillary_item_ids` must carry `service_class` `ANCILLARY` (`ERR_BUNDLED_ITEM_NOT_ANCILLARY`) and must not have an `ancillary_inclusion` of `SEPARATELY_PRICED` (`ERR_ANCILLARY_INCLUSION_VIOLATION`) — separately priced ancillaries can never ride inside a package."

        Design: Corner/validations/bundled_item_must_be_ancillary_class
        """
        fac = create_facility(name="F", cms_certification_number="CCN-H15",
                              bed_count=50)
        si1 = create_service_item(fac["id"], code="70551", description="MRI",
                                  gross_charge_cents=100000)
        si2 = create_service_item(fac["id"], code="70450", description="CT",
                                  gross_charge_cents=80000)
        resp = api.create_shoppable_list(
            {"facility_id": fac["id"], "title": "L",
             "entries": [shoppable_entry(
                 si1["id"], display_name="bad bundle",
                 bundled_ancillary_item_ids=[si2["id"]])]},
            OFFICER)
        validate_error(resp, ApiErrorId.ERR_BUNDLED_ITEM_NOT_ANCILLARY)

    def test_separately_priced_ancillary_cannot_be_bundled(self, api):
        """PRD section 3.5: "Every item named in `bundled_ancillary_item_ids` must carry `service_class` `ANCILLARY` (`ERR_BUNDLED_ITEM_NOT_ANCILLARY`) and must not have an `ancillary_inclusion` of `SEPARATELY_PRICED` (`ERR_ANCILLARY_INCLUSION_VIOLATION`) — separately priced ancillaries can never ride inside a package."

        Design: Corner/validations/separately_priced_ancillary_cannot_be_bundled
        """
        fac = create_facility(name="F", cms_certification_number="CCN-H16",
                              bed_count=50)
        si1 = create_service_item(fac["id"], code="70551", description="MRI",
                                  gross_charge_cents=100000)
        anc = create_service_item(
            fac["id"], code="J2400", code_type="HCPCS",
            description="Injection", service_class="ANCILLARY",
            gross_charge_cents=1000, ancillary_inclusion="SEPARATELY_PRICED")
        resp = api.create_shoppable_list(
            {"facility_id": fac["id"], "title": "L",
             "entries": [shoppable_entry(
                 si1["id"], display_name="bad bundle",
                 bundled_ancillary_item_ids=[anc["id"]])]},
            OFFICER)
        validate_error(resp, ApiErrorId.ERR_ANCILLARY_INCLUSION_VIOLATION)


class TestCertification:
    def test_certify_below_minimum_rejected(self, api):
        """PRD section 3.5: "It requires `DRAFT` status (`ERR_LIST_NOT_DRAFT`) and then evaluates two threshold checks in a fixed order: the total-count check runs first, rejecting with `ERR_SHOPPABLE_COUNT_BELOW_MINIMUM` when `entry_count` falls below the facility's `shoppable_min_entries`; only when the total passes does the mandated-count check run, rejecting with `ERR_MANDATED_COUNT_BELOW_MINIMUM` when `mandated_entry_count` falls below the facility's `mandated_min_entries`."

        Design: Difficulty/boundary_precision_check/certify_count_boundary_exactly_at_minimum
        """
        fac = create_facility(name="F", cms_certification_number="CCN-B1",
                              bed_count=100, shoppable_min_entries=2,
                              mandated_min_entries=1)
        si1 = create_service_item(fac["id"], code="70551",
                                  description="MRI brain",
                                  gross_charge_cents=100000,
                                  cms_shoppable_mandated=True)
        l1 = create_shoppable_list(
            fac["id"], [shoppable_entry(si1["id"], display_name="MRI")])
        assert l1["entry_count"] == 1
        # 1 entry < floor 2: the total-count check rejects first.
        resp = api.certify_list(l1["id"], OFFICER)
        validate_error(resp, ApiErrorId.ERR_SHOPPABLE_COUNT_BELOW_MINIMUM)
        assert resp.status_code == 422

    def test_certify_exactly_at_minimum_passes(self, api):
        """PRD section 3.5: "Both thresholds are inclusive — a count exactly equal to its floor passes."

        Design: Difficulty/boundary_precision_check/certify_count_boundary_exactly_at_minimum
        """
        fac = create_facility(name="F", cms_certification_number="CCN-B1",
                              bed_count=100, shoppable_min_entries=2,
                              mandated_min_entries=1)
        si1 = create_service_item(fac["id"], code="70551",
                                  description="MRI brain",
                                  gross_charge_cents=100000,
                                  cms_shoppable_mandated=True)
        si2 = create_service_item(fac["id"], code="70450",
                                  description="CT head",
                                  gross_charge_cents=80000)
        l2 = create_shoppable_list(fac["id"], [
            shoppable_entry(si1["id"], display_name="MRI", display_order=1),
            shoppable_entry(si2["id"], display_name="CT", display_order=2),
        ])
        # entry_count 2 >= 2 (exactly at the floor) and mandated 1 >= 1.
        lst = get_success_data(api.certify_list(l2["id"], OFFICER))
        assert lst["status"] == "CERTIFIED"

    def test_mandated_count_checked_after_total_count(self, api):
        """PRD section 3.5: "It requires `DRAFT` status (`ERR_LIST_NOT_DRAFT`) and then evaluates two threshold checks in a fixed order: the total-count check runs first, rejecting with `ERR_SHOPPABLE_COUNT_BELOW_MINIMUM` when `entry_count` falls below the facility's `shoppable_min_entries`; only when the total passes does the mandated-count check run, rejecting with `ERR_MANDATED_COUNT_BELOW_MINIMUM` when `mandated_entry_count` falls below the facility's `mandated_min_entries`."

        Design: Corner/validations/mandated_count_checked_after_total_count
        """
        fac = create_facility(name="F", cms_certification_number="CCN-H17",
                              bed_count=50, shoppable_min_entries=1,
                              mandated_min_entries=1)
        si2 = create_service_item(fac["id"], code="70450", description="CT",
                                  gross_charge_cents=80000,
                                  cms_shoppable_mandated=False)
        lst = create_shoppable_list(
            fac["id"], [shoppable_entry(si2["id"], display_name="CT")])
        # Total 1 >= 1 passes; mandated 0 < 1 fails second.
        resp = api.certify_list(lst["id"], OFFICER)
        validate_error(resp, ApiErrorId.ERR_MANDATED_COUNT_BELOW_MINIMUM)

    def test_list_double_certify_rejected(self, api):
        """PRD section 3.5: "It requires `DRAFT` status (`ERR_LIST_NOT_DRAFT`) and then evaluates two threshold checks in a fixed order: the total-count check runs first, rejecting with `ERR_SHOPPABLE_COUNT_BELOW_MINIMUM` when `entry_count` falls below the facility's `shoppable_min_entries`; only when the total passes does the mandated-count check run, rejecting with `ERR_MANDATED_COUNT_BELOW_MINIMUM` when `mandated_entry_count` falls below the facility's `mandated_min_entries`."

        Design: Corner/errors/list_double_certify_rejected
        """
        fac = create_facility(name="F", cms_certification_number="CCN-ER8",
                              bed_count=50, shoppable_min_entries=1,
                              mandated_min_entries=1)
        si = create_service_item(fac["id"], code="70551", description="MRI",
                                 gross_charge_cents=100000,
                                 cms_shoppable_mandated=True)
        lst = create_shoppable_list(
            fac["id"], [shoppable_entry(si["id"], display_name="MRI")])
        certify_list(lst["id"])
        resp = api.certify_list(lst["id"], OFFICER)
        validate_error(resp, ApiErrorId.ERR_LIST_NOT_DRAFT)


class TestListPublishGates:
    def test_list_publish_from_draft_and_display_before_publish_rejected(
            self, api):
        """PRD section 3.5: "A publish against a list in any other status is rejected with `ERR_LIST_NOT_CERTIFIED`."
        PRD section 3.5: "It is served only for a `PUBLISHED` list (`ERR_LIST_NOT_PUBLISHED`) and only while the facility's `shoppable_display_enabled` flag is on (`ERR_DISPLAY_DISABLED`)."

        Design: Corner/state_machines/list_publish_from_draft_and_display_before_publish_rejected
        """
        fac = create_facility(name="F", cms_certification_number="CCN-SM13",
                              bed_count=50, shoppable_min_entries=1,
                              mandated_min_entries=1)
        si1 = create_service_item(fac["id"], code="70551", description="MRI",
                                  gross_charge_cents=100000,
                                  cms_shoppable_mandated=True)
        lst = create_shoppable_list(
            fac["id"], [shoppable_entry(si1["id"], display_name="MRI")])
        resp = api.publish_list(lst["id"], OFFICER)
        validate_error(resp, ApiErrorId.ERR_LIST_NOT_CERTIFIED)
        certify_list(lst["id"])
        resp = api.display_list(lst["id"], CONSUMER)
        validate_error(resp, ApiErrorId.ERR_LIST_NOT_PUBLISHED)

    def test_list_publish_without_published_cycle_rejected(self, api):
        """PRD section 3.5: "Two cross-entity gates then apply: the facility must have at least one `PUBLISHED` publication cycle (`ERR_NO_PUBLISHED_CYCLE`), and every entry's `service_item_id` must have a `PUBLISHED` charge record in the facility's latest `PUBLISHED` cycle (`ERR_ENTRY_RECORD_MISSING`)."

        Design: Corner/errors/list_publish_without_published_cycle_rejected
        """
        fac = create_facility(name="F", cms_certification_number="CCN-ER6",
                              bed_count=50, shoppable_min_entries=1,
                              mandated_min_entries=1)
        si = create_service_item(fac["id"], code="70551", description="MRI",
                                 gross_charge_cents=100000,
                                 cms_shoppable_mandated=True)
        lst = create_shoppable_list(
            fac["id"], [shoppable_entry(si["id"], display_name="MRI")])
        certify_list(lst["id"])
        resp = api.publish_list(lst["id"], OFFICER)
        validate_error(resp, ApiErrorId.ERR_NO_PUBLISHED_CYCLE)

    def test_list_publish_with_unpublished_entry_record_rejected(self, api):
        """PRD section 3.5: "Two cross-entity gates then apply: the facility must have at least one `PUBLISHED` publication cycle (`ERR_NO_PUBLISHED_CYCLE`), and every entry's `service_item_id` must have a `PUBLISHED` charge record in the facility's latest `PUBLISHED` cycle (`ERR_ENTRY_RECORD_MISSING`)."

        Design: Corner/errors/list_publish_with_unpublished_entry_record_rejected
        """
        ctx = setup_published_cycle(
            facility_overrides={"name": "F",
                                "cms_certification_number": "CCN-ER7",
                                "bed_count": 50,
                                "shoppable_min_entries": 2,
                                "mandated_min_entries": 1},
            item_overrides={"code": "70551", "description": "MRI",
                            "gross_charge_cents": 100000,
                            "cms_shoppable_mandated": True})
        fac = ctx["facility"]
        # SI2 has no PUBLISHED charge record in the published cycle.
        si2 = create_service_item(fac["id"], code="70450", description="CT",
                                  gross_charge_cents=80000)
        lst = create_shoppable_list(fac["id"], [
            shoppable_entry(ctx["item"]["id"], display_name="MRI",
                            display_order=1),
            shoppable_entry(si2["id"], display_name="CT", display_order=2),
        ])
        certify_list(lst["id"])
        resp = api.publish_list(lst["id"], OFFICER)
        validate_error(resp, ApiErrorId.ERR_ENTRY_RECORD_MISSING)

    def test_shoppable_publish_auto_archives_prior_list(self, api):
        """PRD section 3.5: "Any prior `PUBLISHED` list of the same facility auto-transitions `PUBLISHED → ARCHIVED`, and the new list's `version` increments."

        Design: Corner/state_machines/shoppable_publish_auto_archives_prior_list
        """
        fac = create_facility(name="F", cms_certification_number="CCN-SM9",
                              bed_count=50, shoppable_min_entries=1,
                              mandated_min_entries=1)
        payer = create_payer(name="PA")
        contract = create_contract(fac["id"], payer["id"])
        si1 = create_service_item(fac["id"], code="70551", description="MRI",
                                  gross_charge_cents=100000,
                                  cms_shoppable_mandated=True)
        si2 = create_service_item(fac["id"], code="70450", description="CT",
                                  gross_charge_cents=80000,
                                  cms_shoppable_mandated=True)
        create_rate(contract["id"], si1["id"], rate_percent=40)
        create_rate(contract["id"], si2["id"], rate_percent=50)
        get_success_data(api.activate_contract(contract["id"], MANAGER))
        # One published cycle carrying PUBLISHED records for BOTH items.
        cycle = create_cycle(fac["id"])
        validate_record(create_charge_record(
            fac["id"], cycle["id"], si1["id"],
            discounted_cash_cents=50000)["id"])
        validate_record(create_charge_record(
            fac["id"], cycle["id"], si2["id"],
            discounted_cash_cents=40000)["id"])
        freeze_cycle(cycle["id"])
        f = generate_machine_file(cycle["id"])
        validate_machine_file(f["id"])
        publish_cycle(cycle["id"])
        l1 = create_shoppable_list(
            fac["id"], [shoppable_entry(si1["id"], display_name="MRI")])
        certify_list(l1["id"])
        l1 = publish_list(l1["id"])
        assert l1["status"] == "PUBLISHED"
        l2 = create_shoppable_list(
            fac["id"], [shoppable_entry(si2["id"], display_name="CT")])
        certify_list(l2["id"])
        l2 = publish_list(l2["id"])
        assert l2["status"] == "PUBLISHED"
        lists, _ = validate_paginated(
            api.list_shoppable_lists(fac["id"], OFFICER))
        by_id = {lst["id"]: lst for lst in lists}
        assert by_id[l1["id"]]["status"] == "ARCHIVED", \
            "publishing L2 must auto-archive the previously PUBLISHED L1"


class TestConsumerDisplay:
    def _setup_mix_weighted_display(self, api):
        """Published cycle whose record derives MIX_WEIGHTED 55000 (DISCLOSE
        40% vol 100 + DERIVED_ONLY 60% vol 300), cash 60000, gross 100000;
        single-entry published list."""
        fac = create_facility(name="F", cms_certification_number="CCN-D1",
                              bed_count=100, shoppable_min_entries=1,
                              mandated_min_entries=1)
        pa = create_payer(name="PA")
        pb = create_payer(name="PB", payer_type="MEDICARE_ADVANTAGE")
        ca = create_contract(fac["id"], pa["id"], annual_volume=100,
                             confidentiality_clause="DISCLOSE_ALLOWED")
        cb = create_contract(fac["id"], pb["id"], annual_volume=300,
                             confidentiality_clause="DERIVED_ONLY")
        si = create_service_item(fac["id"], code="70551",
                                 description="MRI brain",
                                 gross_charge_cents=100000,
                                 cms_shoppable_mandated=True)
        create_rate(ca["id"], si["id"], rate_percent=40)
        create_rate(cb["id"], si["id"], rate_percent=60)
        get_success_data(api.activate_contract(ca["id"], MANAGER))
        get_success_data(api.activate_contract(cb["id"], MANAGER))
        cycle = create_cycle(fac["id"])
        record = create_charge_record(fac["id"], cycle["id"], si["id"],
                                      discounted_cash_cents=60000)
        validate_record(record["id"])
        freeze_cycle(cycle["id"])
        f = generate_machine_file(cycle["id"])
        validate_machine_file(f["id"])
        publish_cycle(cycle["id"])
        lst = create_shoppable_list(
            fac["id"], [shoppable_entry(si["id"], display_name="MRI Brain")])
        certify_list(lst["id"])
        lst = publish_list(lst["id"])
        return lst

    def test_consumer_display_price_min_branch(self, api):
        """PRD section 3.5: "The base price is the smallest of the pinned record's `gross_charge_cents`, its `discounted_cash_cents`, and, when it is not null, its `derived_disclosure_cents`."
        PRD section 3.5: "Each entry's `package_price_cents` is computed at read time from the pinned record — never the live record."

        Design: Difficulty/combinatorial_formula/consumer_display_price_min_branch
        """
        lst = self._setup_mix_weighted_display(api)
        display = validate_success(api.display_list(lst["id"], CONSUMER))
        assert display["list_id"] == lst["id"]
        # min(100000 gross, 60000 cash, 55000 MIX_WEIGHTED derived) + 0 bundle
        assert display["entries"][0]["package_price_cents"] == 55000

    def test_consumer_display_derived_undercuts_cash(self, api):
        """PRD section 3.5: "The base price is the smallest of the pinned record's `gross_charge_cents`, its `discounted_cash_cents`, and, when it is not null, its `derived_disclosure_cents`."
        PRD section 3.5: "Each entry also carries a `stale` flag, set when the pinned record's current `version` no longer equals the pinned `record_version`, or when the pinned record has since moved to `SUPERSEDED`; `stale_any` is true when any entry is stale."

        Design: Difficulty/combinatorial_formula/consumer_display_price_min_branch
        """
        lst = self._setup_mix_weighted_display(api)
        display = validate_success(api.display_list(lst["id"], CONSUMER))
        entry = display["entries"][0]
        # The payer-derived figure (55000), not the cash price (60000), wins
        # the nested minimum.
        assert entry["package_price_cents"] == 55000
        assert entry["package_price_cents"] != 60000
        # The pinned record version still matches: nothing is stale.
        assert display["stale_any"] is False
        assert entry["stale"] is False

    def test_bundle_ancillary_per_item_floor_rounding(self, api):
        """PRD section 2.7: "In the shoppable bundle calculation, the ten-percent discount is floored per ancillary item first, and only then are the per-item contributions summed; the package total itself is never re-rounded."
        PRD section 2.7: "The alternative ordering — summing the ancillary gross amounts and flooring the discounted sum once — is forbidden, because it disagrees whenever per-item fractional remainders accumulate: two ancillary items priced at 333 cents each contribute 299 plus 299, a bundle sum of 598 cents, under the pinned order, whereas flooring ninety percent of the 666-cent sum would yield 599 cents."

        Design: Difficulty/combinatorial_formula/bundle_ancillary_per_item_floor_rounding
        """
        lst = self._setup_bundle_display(api)
        display = validate_success(api.display_list(lst["id"], CONSUMER))
        # base = min(100000, 60000, 40000) = 40000; floor(333*0.9)=299 twice.
        assert display["entries"][0]["package_price_cents"] == 40598

    def test_bundle_rounding_forbidden_order_diverges(self, api):
        """PRD section 2.7: "The alternative ordering — summing the ancillary gross amounts and flooring the discounted sum once — is forbidden, because it disagrees whenever per-item fractional remainders accumulate: two ancillary items priced at 333 cents each contribute 299 plus 299, a bundle sum of 598 cents, under the pinned order, whereas flooring ninety percent of the 666-cent sum would yield 599 cents."

        Design: Difficulty/combinatorial_formula/bundle_ancillary_per_item_floor_rounding
        """
        lst = self._setup_bundle_display(api)
        display = validate_success(api.display_list(lst["id"], CONSUMER))
        price = display["entries"][0]["package_price_cents"]
        # The forbidden sum-then-round order would yield 40000+599 = 40599.
        assert price != 40599
        # Pinned order: 40000 + 299 + 299.
        assert price == 40000 + 299 + 299

    def _setup_bundle_display(self, api):
        """Published cycle (record derived EXACT_MIN 40000, cash 60000, gross
        100000) + published list whose entry bundles two ALWAYS_BUNDLED
        ancillaries priced at 333 cents each."""
        fac = create_facility(name="F", cms_certification_number="CCN-D2",
                              bed_count=100, shoppable_min_entries=1,
                              mandated_min_entries=1)
        pa = create_payer(name="PA")
        ca = create_contract(fac["id"], pa["id"], annual_volume=100,
                             confidentiality_clause="DISCLOSE_ALLOWED")
        si = create_service_item(fac["id"], code="70551",
                                 description="MRI brain",
                                 gross_charge_cents=100000,
                                 cms_shoppable_mandated=True)
        an1 = create_service_item(fac["id"], code="J2400", code_type="HCPCS",
                                  description="Injection",
                                  service_class="ANCILLARY",
                                  gross_charge_cents=333,
                                  ancillary_inclusion="ALWAYS_BUNDLED")
        an2 = create_service_item(fac["id"], code="A4650", code_type="HCPCS",
                                  description="Supply kit",
                                  service_class="ANCILLARY",
                                  gross_charge_cents=333,
                                  ancillary_inclusion="ALWAYS_BUNDLED")
        create_rate(ca["id"], si["id"], rate_percent=40)
        get_success_data(api.activate_contract(ca["id"], MANAGER))
        cycle = create_cycle(fac["id"])
        record = create_charge_record(fac["id"], cycle["id"], si["id"],
                                      discounted_cash_cents=60000)
        validate_record(record["id"])
        freeze_cycle(cycle["id"])
        f = generate_machine_file(cycle["id"], file_format="CSV")
        validate_machine_file(f["id"])
        publish_cycle(cycle["id"])
        lst = create_shoppable_list(
            fac["id"], [shoppable_entry(
                si["id"], display_name="MRI pkg",
                bundled_ancillary_item_ids=[an1["id"], an2["id"]])])
        certify_list(lst["id"])
        return publish_list(lst["id"])

    def test_conditional_ancillary_respects_include_flag(self, api):
        """PRD section 3.5: "To that base the package adds each bundled ancillary's contribution, processed in ascending `display_order` with ties broken by the ancillary item's `created_at` ascending: an ancillary whose `ancillary_inclusion` is `ALWAYS_BUNDLED` always contributes, and one that is `CONDITIONALLY_INCLUDED` contributes only when the entry's `include_conditional_ancillaries` is set."
        PRD section 3.5: "Each contribution is the ancillary's live `gross_charge_cents` discounted by ten percent — ninety percent of the gross charge, floored per item to a whole cent — and then summed, per the pinned rounding order of §2.7."

        Design: Corner/calculations/conditional_ancillary_respects_include_flag
        """
        ctx = setup_published_shoppable_list(
            facility_overrides={"name": "F",
                                "cms_certification_number": "CCN-K6",
                                "bed_count": 50},
            cash=50000)
        fac, si = ctx["facility"], ctx["item"]
        anc = create_service_item(fac["id"], code="J2400", code_type="HCPCS",
                                  description="Injection",
                                  service_class="ANCILLARY",
                                  gross_charge_cents=1000,
                                  ancillary_inclusion="CONDITIONALLY_INCLUDED")
        # Rebuild lists carrying the conditional ancillary (the fixture's
        # default list has no bundles).
        l1 = create_shoppable_list(
            fac["id"], [shoppable_entry(
                si["id"], display_name="MRI no-cond",
                bundled_ancillary_item_ids=[anc["id"]],
                include_conditional_ancillaries=False)])
        certify_list(l1["id"])
        l1 = publish_list(l1["id"])  # auto-archives the fixture's list
        display1 = validate_success(api.display_list(l1["id"], CONSUMER))
        # Flag false: the conditional ancillary is skipped entirely.
        assert display1["entries"][0]["package_price_cents"] == 40000
        l2 = create_shoppable_list(
            fac["id"], [shoppable_entry(
                si["id"], display_name="MRI with-cond",
                bundled_ancillary_item_ids=[anc["id"]],
                include_conditional_ancillaries=True)])
        certify_list(l2["id"])
        l2 = publish_list(l2["id"])  # auto-archives L1
        display2 = validate_success(api.display_list(l2["id"], CONSUMER))
        # Flag true: 40000 + floor(1000 * 0.9) = 40900.
        assert display2["entries"][0]["package_price_cents"] == 40900

    def test_display_uses_pinned_record_and_flags_stale_after_correction(
            self, api):
        """PRD section 3.5: "On success the list pins its evidence: `pinned_records` captures, for each entry's item, the charge record selected by facility match, item match, `PUBLISHED` status, and membership in the latest `PUBLISHED` cycle by `period_start` (ties broken by `created_at` ascending), storing the `charge_record_id` and the record's `version` at pin time as `record_version`."
        PRD section 3.5: "Each entry's `package_price_cents` is computed at read time from the pinned record — never the live record."
        PRD section 3.5: "Each entry also carries a `stale` flag, set when the pinned record's current `version` no longer equals the pinned `record_version`, or when the pinned record has since moved to `SUPERSEDED`; `stale_any` is true when any entry is stale."

        Design: Corner/calculations/display_uses_pinned_record_and_flags_stale_after_correction
        """
        ctx = setup_published_shoppable_list(
            facility_overrides={"name": "F",
                                "cms_certification_number": "CCN-K7",
                                "bed_count": 50},
            cash=50000)
        lst, record, cycle = ctx["list"], ctx["record"], ctx["cycle"]
        # Publish pinned the record id together with its version at pin time
        # (record create 1, validate 2, publish cascade 3).
        assert lst["pinned_records"] == [
            {"service_item_id": ctx["item"]["id"],
             "charge_record_id": record["id"], "record_version": 3}]
        display = validate_success(api.display_list(lst["id"], CONSUMER))
        assert display["stale_any"] is False
        assert display["entries"][0]["package_price_cents"] == 40000
        # Run a full correction against the pinned record.
        discrepancy = get_success_data(api.create_discrepancy(
            {"publication_cycle_id": cycle["id"],
             "standard_charge_record_id": record["id"],
             "reporter_type": "INTERNAL", "description": "gross wrong"},
            OFFICER))
        get_success_data(api.triage_discrepancy(
            discrepancy["id"], {"outcome": "CONFIRMED"}, AUDITOR))
        get_success_data(api.propose_correction(
            discrepancy["id"], {"proposed_gross_charge_cents": 80000},
            make_officer_headers("officer-a")))
        get_success_data(api.approve_correction(
            discrepancy["id"], make_officer_headers("officer-b")))
        get_success_data(api.apply_correction(
            discrepancy["id"], make_officer_headers("officer-a")))
        display = validate_success(api.display_list(lst["id"], CONSUMER))
        # The pinned record moved on (and was SUPERSEDED): staleness shows.
        assert display["stale_any"] is True
        assert display["entries"][0]["stale"] is True
        # The display keeps serving the pinned snapshot's figures.
        assert display["entries"][0]["package_price_cents"] == 40000

    def test_display_disabled_by_feature_flag(self, api):
        """PRD section 3.5: "It is served only for a `PUBLISHED` list (`ERR_LIST_NOT_PUBLISHED`) and only while the facility's `shoppable_display_enabled` flag is on (`ERR_DISPLAY_DISABLED`)."

        Design: Corner/cross_cutting_layers/display_disabled_by_feature_flag
        """
        ctx = setup_published_shoppable_list(
            facility_overrides={"name": "F",
                                "cms_certification_number": "CCN-X3L",
                                "bed_count": 50,
                                "shoppable_display_enabled": False})
        assert ctx["list"]["status"] == "PUBLISHED"
        resp = api.display_list(ctx["list"]["id"], CONSUMER)
        validate_error(resp, ApiErrorId.ERR_DISPLAY_DISABLED)
        assert resp.status_code == 422
