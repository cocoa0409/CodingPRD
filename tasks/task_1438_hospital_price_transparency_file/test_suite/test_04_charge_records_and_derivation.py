"""Standard charge extraction: snapshot semantics, extrema, derivation
variants, and record-level validation guards."""
from test_helpers import (
    ApiErrorId,
    create_charge_record,
    create_cycle,
    create_facility,
    create_payer,
    create_contract,
    create_rate,
    create_service_item,
    freeze_cycle,
    get_success_data,
    setup_frozen_cycle,
    setup_open_cycle_with_record,
    setup_published_cycle,
    validate_error,
    validate_paginated,
    validate_record,
)
from test_helpers.fixtures import MANAGER, OFFICER


class TestChargeRecordCreate:
    def test_charge_record_create_snapshots_gross_and_computes_fields(
            self, api):
        """PRD section 3.3: "At creation the record snapshots the item's current `gross_charge_cents` and computes three derived figures."
        PRD section 3.3: "Across that includible set, `min_negotiated_cents` is the smallest `negotiated_amount_cents` and `max_negotiated_cents` the largest; when the includible set is empty, both are null."
        PRD section 3.3: "When no `DERIVED_ONLY` contract contributes and no includible `AGGREGATE_ONLY` contract contributes, the method is `EXACT_MIN` and `derived_disclosure_cents` is exactly `min_negotiated_cents` (null when the disclosable set is empty)."

        Design: Corner/entities/charge_record_create_snapshots_gross_and_computes_fields
        """
        ctx = setup_open_cycle_with_record(
            facility_overrides={"name": "F",
                                "cms_certification_number": "CCN-E4",
                                "bed_count": 50},
            item_overrides={"code": "70551", "description": "MRI",
                            "gross_charge_cents": 100000},
            cash=50000)
        record = ctx["record"]
        # gross_charge_cents is a server-side snapshot of the item (100000);
        # the single ACTIVE DISCLOSE_ALLOWED 40% rate materializes to 40000.
        assert record["gross_charge_cents"] == 100000
        assert record["min_negotiated_cents"] == 40000
        assert record["max_negotiated_cents"] == 40000
        assert record["derived_disclosure_cents"] == 40000
        assert record["derivation_method"] == "EXACT_MIN"
        assert record["status"] == "DRAFT"

    def test_extrema_null_without_rates_and_validate_blocked(self, api):
        """PRD section 3.3: "Across that includible set, `min_negotiated_cents` is the smallest `negotiated_amount_cents` and `max_negotiated_cents` the largest; when the includible set is empty, both are null."
        PRD section 3.3: "When no `DERIVED_ONLY` contract contributes and no includible `AGGREGATE_ONLY` contract contributes, the method is `EXACT_MIN` and `derived_disclosure_cents` is exactly `min_negotiated_cents` (null when the disclosable set is empty)."
        PRD section 3.3: "Validation additionally requires that at least one includible rate exists — a null `min_negotiated_cents` is rejected with `ERR_NO_NEGOTIATED_RATES` — and that `discounted_cash_cents` does not exceed `gross_charge_cents` (`ERR_CASH_EXCEEDS_GROSS`)."

        Design: Corner/calculations/extrema_null_without_rates_and_validate_blocked
        """
        fac = create_facility(name="F", cms_certification_number="CCN-K3",
                              bed_count=50)
        item = create_service_item(fac["id"], code="70551",
                                   description="MRI", gross_charge_cents=100000)
        cycle = create_cycle(fac["id"])
        record = create_charge_record(fac["id"], cycle["id"], item["id"],
                                      discounted_cash_cents=50000)
        # No contracts exist at all: the includible set is empty, so the
        # extrema and the disclosure figure are null (not zero). With no
        # DERIVED_ONLY or includible AGGREGATE_ONLY contribution the method
        # is EXACT_MIN per the PRD variant-selection rule.
        assert record["min_negotiated_cents"] is None
        assert record["max_negotiated_cents"] is None
        assert record["derived_disclosure_cents"] is None
        assert record["derivation_method"] == "EXACT_MIN"
        resp = api.validate_charge_record(record["id"], OFFICER)
        validate_error(resp, ApiErrorId.ERR_NO_NEGOTIATED_RATES)
        record_after = get_success_data(
            api.get_charge_record(record["id"], OFFICER))
        assert record_after["status"] == "DRAFT"

    def test_aggregate_only_excluded_below_deidentification_threshold(
            self, api):
        """PRD section 3.3: "The de-identification floor is three distinct payers: a count of exactly three passes, a count of two fails."
        PRD section 3.3: "An `AGGREGATE_ONLY` contract's rate contributes only when that payer count meets the floor of three; otherwise it is excluded entirely."
        PRD section 3.3: "Rates in `DRAFT`, `INACTIVE`, or `SUPERSEDED`, and rates under `DERIVED_ONLY` or `AGGREGATE_ONLY` contracts, never enter the extrema."

        Design: Corner/calculations/aggregate_only_excluded_below_deidentification_threshold
        """
        fac = create_facility(name="F", cms_certification_number="CCN-K4",
                              bed_count=50)
        pa = create_payer(name="PA")
        pb = create_payer(name="PB")
        ca = create_contract(fac["id"], pa["id"], annual_volume=100,
                             confidentiality_clause="DISCLOSE_ALLOWED")
        cb = create_contract(fac["id"], pb["id"], annual_volume=300,
                             confidentiality_clause="AGGREGATE_ONLY")
        item = create_service_item(fac["id"], code="70551",
                                   description="MRI", gross_charge_cents=100000)
        create_rate(ca["id"], item["id"], rate_percent=40)   # 40000
        create_rate(cb["id"], item["id"], rate_percent=60)   # 60000
        get_success_data(api.activate_contract(ca["id"], MANAGER))
        get_success_data(api.activate_contract(cb["id"], MANAGER))
        cycle = create_cycle(fac["id"])
        record = create_charge_record(fac["id"], cycle["id"], item["id"],
                                      discounted_cash_cents=50000)
        # Two distinct payers fall below the de-identification floor of three,
        # so the AGGREGATE_ONLY rate is excluded entirely: the extrema see
        # only the DISCLOSE_ALLOWED rate and the method stays EXACT_MIN.
        assert record["min_negotiated_cents"] == 40000
        assert record["max_negotiated_cents"] == 40000
        assert record["derivation_method"] == "EXACT_MIN"
        assert record["derived_disclosure_cents"] == 40000


class TestDerivedDisclosureVariants:
    def _setup_two_clause_universe(self, api):
        """DISCLOSE_ALLOWED contract (vol 100, 40% -> 40000) plus DERIVED_ONLY
        contract (vol 300, 60% -> 60000), both ACTIVE, one item, one cycle."""
        fac = create_facility(name="F", cms_certification_number="CCN-F1",
                              bed_count=100)
        pa = create_payer(name="PA")
        pb = create_payer(name="PB")
        ca = create_contract(fac["id"], pa["id"], annual_volume=100,
                             confidentiality_clause="DISCLOSE_ALLOWED")
        cb = create_contract(fac["id"], pb["id"], annual_volume=300,
                             confidentiality_clause="DERIVED_ONLY")
        item = create_service_item(fac["id"], code="70551",
                                   description="MRI brain",
                                   gross_charge_cents=100000)
        create_rate(ca["id"], item["id"], rate_percent=40)
        create_rate(cb["id"], item["id"], rate_percent=60)
        get_success_data(api.activate_contract(ca["id"], MANAGER))
        get_success_data(api.activate_contract(cb["id"], MANAGER))
        cycle = create_cycle(fac["id"])
        return fac, cb, item, cycle

    def test_derived_disclosure_mix_weighted_with_derived_only(self, api):
        """PRD section 3.3: "Otherwise the method is `MIX_WEIGHTED`: the pool is the disclosable rates plus the `DERIVED_ONLY` rates plus any includible `AGGREGATE_ONLY` rates, and the figure is the volume-weighted mean — each rate's `negotiated_amount_cents` multiplied by its contract's `annual_volume`, those products summed, divided by the sum of the pool's `annual_volume` values, and truncated down to a whole cent."
        PRD section 3.3: "Rates in `DRAFT`, `INACTIVE`, or `SUPERSEDED`, and rates under `DERIVED_ONLY` or `AGGREGATE_ONLY` contracts, never enter the extrema."

        Design: Difficulty/dual_variant_calc/derived_disclosure_exact_min_vs_mix_weighted
        """
        fac, _cb, item, cycle = self._setup_two_clause_universe(api)
        record = create_charge_record(fac["id"], cycle["id"], item["id"],
                                      discounted_cash_cents=50000)
        # floor((40000*100 + 60000*300) / 400) = 55000
        assert record["derivation_method"] == "MIX_WEIGHTED"
        assert record["derived_disclosure_cents"] == 55000
        # The DERIVED_ONLY rate never enters the exact extrema.
        assert record["min_negotiated_cents"] == 40000
        assert record["max_negotiated_cents"] == 40000

    def test_derived_disclosure_exact_min_after_termination(self, api):
        """PRD section 3.8: "Termination moves an `ACTIVE` contract to `TERMINATED` and drives its `ACTIVE` rates to `INACTIVE`, with the same record-and-cycle recompute under the reduced inclusion set."
        PRD section 3.3: "When no `DERIVED_ONLY` contract contributes and no includible `AGGREGATE_ONLY` contract contributes, the method is `EXACT_MIN` and `derived_disclosure_cents` is exactly `min_negotiated_cents` (null when the disclosable set is empty)."
        PRD section 3.3: "For identical rate data, the weighted variant deliberately produces a different number than the exact minimum whenever volumes and amounts differ."

        Design: Difficulty/dual_variant_calc/derived_disclosure_exact_min_vs_mix_weighted
        """
        fac, cb, item, cycle = self._setup_two_clause_universe(api)
        record = create_charge_record(fac["id"], cycle["id"], item["id"],
                                      discounted_cash_cents=50000)
        assert record["derived_disclosure_cents"] == 55000
        # Removing the DERIVED_ONLY contract flips the same record's
        # derivation to the exact variant over the remaining rate universe.
        get_success_data(api.terminate_contract(cb["id"], MANAGER))
        record = get_success_data(
            api.get_charge_record(record["id"], OFFICER))
        assert record["derivation_method"] == "EXACT_MIN"
        assert record["derived_disclosure_cents"] == 40000
        assert record["min_negotiated_cents"] == 40000


class TestContractTerminateCascade:
    def _setup_two_disclose_universe(self, api):
        """Two ACTIVE DISCLOSE_ALLOWED contracts: 40% -> 40000 (vol 100) and
        60% -> 60000 (vol 300); one OPEN cycle with one DRAFT record."""
        fac = create_facility(name="F", cms_certification_number="CCN-C2",
                              bed_count=100)
        pa = create_payer(name="PA")
        pb = create_payer(name="PB")
        ca = create_contract(fac["id"], pa["id"], annual_volume=100,
                             confidentiality_clause="DISCLOSE_ALLOWED")
        cb = create_contract(fac["id"], pb["id"], annual_volume=300,
                             confidentiality_clause="DISCLOSE_ALLOWED")
        item = create_service_item(fac["id"], code="70551",
                                   description="MRI", gross_charge_cents=100000)
        create_rate(ca["id"], item["id"], rate_percent=40)
        rb = create_rate(cb["id"], item["id"], rate_percent=60)
        get_success_data(api.activate_contract(ca["id"], MANAGER))
        get_success_data(api.activate_contract(cb["id"], MANAGER))
        cycle = create_cycle(fac["id"])
        return fac, cb, rb, item, cycle

    def test_terminate_flips_rate_inactive(self, api):
        """PRD section 3.8: "Termination moves an `ACTIVE` contract to `TERMINATED` and drives its `ACTIVE` rates to `INACTIVE`, with the same record-and-cycle recompute under the reduced inclusion set."

        Design: Difficulty/transitive_cascade/contract_terminate_cascades_to_record_extrema
        """
        fac, cb, rb, item, cycle = self._setup_two_disclose_universe(api)
        record = create_charge_record(fac["id"], cycle["id"], item["id"],
                                      discounted_cash_cents=50000)
        # Both DISCLOSE_ALLOWED rates are in the extrema input set.
        assert record["max_negotiated_cents"] == 60000
        assert record["min_negotiated_cents"] == 40000
        get_success_data(api.terminate_contract(cb["id"], MANAGER))
        rb_after = get_success_data(api.get_rate(rb["id"], OFFICER))
        assert rb_after["status"] == "INACTIVE"

    def test_terminate_collapses_record_extrema(self, api):
        """PRD section 3.8: "Termination moves an `ACTIVE` contract to `TERMINATED` and drives its `ACTIVE` rates to `INACTIVE`, with the same record-and-cycle recompute under the reduced inclusion set."
        PRD section 3.3: "Across that includible set, `min_negotiated_cents` is the smallest `negotiated_amount_cents` and `max_negotiated_cents` the largest; when the includible set is empty, both are null."

        Design: Difficulty/transitive_cascade/contract_terminate_cascades_to_record_extrema
        """
        fac, cb, _rb, item, cycle = self._setup_two_disclose_universe(api)
        record = create_charge_record(fac["id"], cycle["id"], item["id"],
                                      discounted_cash_cents=50000)
        assert record["max_negotiated_cents"] == 60000
        get_success_data(api.terminate_contract(cb["id"], MANAGER))
        record = get_success_data(
            api.get_charge_record(record["id"], OFFICER))
        # The terminated payer's rate left the input set: the maximum
        # collapses onto the single remaining rate (EXACT_MIN over it).
        assert record["max_negotiated_cents"] == 40000
        assert record["min_negotiated_cents"] == 40000
        assert record["derived_disclosure_cents"] == 40000
        assert record["derivation_method"] == "EXACT_MIN"


class TestRecordValidationGuards:
    def test_cash_exceeds_gross_rejected_at_record_create(self, api):
        """PRD section 3.3: "The discounted cash price may never exceed the gross charge, at creation or later at validation, or the request fails with `ERR_CASH_EXCEEDS_GROSS`."

        Design: Corner/validations/cash_exceeds_gross_rejected_at_record_create
        """
        ctx = setup_open_cycle_with_record(
            facility_overrides={"name": "F",
                                "cms_certification_number": "CCN-H2",
                                "bed_count": 50})
        resp = api.create_charge_record(
            {"facility_id": ctx["facility"]["id"],
             "publication_cycle_id": ctx["cycle"]["id"],
             "service_item_id": ctx["item"]["id"],
             "discounted_cash_cents": 150000},  # > gross snapshot 100000
            OFFICER)
        validate_error(resp, ApiErrorId.ERR_CASH_EXCEEDS_GROSS)

    def test_record_create_cross_facility_rejected(self, api):
        """PRD section 3.3: "The target cycle must be `OPEN` (`ERR_CYCLE_NOT_OPEN`), the item must be `ACTIVE` (`ERR_ITEM_RETIRED`), and the three references must agree: the record's `facility_id` must match the facility of both its cycle and its item, or the create is rejected with `ERR_CROSS_FACILITY_REFERENCE`."

        Design: Corner/validations/record_create_cross_facility_rejected
        """
        f1 = create_facility(name="F1", cms_certification_number="CCN-H5A",
                             bed_count=50)
        f2 = create_facility(name="F2", cms_certification_number="CCN-H5B",
                             bed_count=50)
        item = create_service_item(f1["id"], code="70551", description="MRI",
                                   gross_charge_cents=100000)
        cycle2 = create_cycle(f2["id"])  # OPEN, but belongs to F2
        resp = api.create_charge_record(
            {"facility_id": f1["id"], "publication_cycle_id": cycle2["id"],
             "service_item_id": item["id"], "discounted_cash_cents": 50000},
            OFFICER)
        validate_error(resp, ApiErrorId.ERR_CROSS_FACILITY_REFERENCE)

    def test_supersede_target_must_be_published_or_flagged(self, api):
        """PRD section 3.3: "When `supersedes_id` is present it must reference an existing record of the same facility whose status is `PUBLISHED` or `FLAGGED`; a missing, cross-facility, or wrongly-stated target is rejected with `ERR_SUPERSEDE_TARGET_INVALID`."

        Design: Corner/validations/supersede_target_must_be_published_or_flagged
        """
        fac = create_facility(name="F", cms_certification_number="CCN-H7",
                              bed_count=50)
        item = create_service_item(fac["id"], code="70551", description="MRI",
                                   gross_charge_cents=100000)
        cycle = create_cycle(fac["id"])
        r1 = create_charge_record(fac["id"], cycle["id"], item["id"],
                                  discounted_cash_cents=50000)
        # R1 is DRAFT, not PUBLISHED or FLAGGED.
        resp = api.create_charge_record(
            {"facility_id": fac["id"], "publication_cycle_id": cycle["id"],
             "service_item_id": item["id"], "discounted_cash_cents": 49000,
             "supersedes_id": r1["id"]}, OFFICER)
        validate_error(resp, ApiErrorId.ERR_SUPERSEDE_TARGET_INVALID)

    def test_record_create_blocked_when_cycle_frozen(self, api):
        """PRD section 3.3: "The target cycle must be `OPEN` (`ERR_CYCLE_NOT_OPEN`), the item must be `ACTIVE` (`ERR_ITEM_RETIRED`), and the three references must agree: the record's `facility_id` must match the facility of both its cycle and its item, or the create is rejected with `ERR_CROSS_FACILITY_REFERENCE`."

        Design: Difficulty/cross_entity_state_dependency/record_create_blocked_when_cycle_not_open
        """
        ctx = setup_frozen_cycle(
            facility_overrides={"name": "F",
                                "cms_certification_number": "CCN-X1",
                                "bed_count": 100})
        assert ctx["cycle"]["status"] == "FROZEN"
        resp = api.create_charge_record(
            {"facility_id": ctx["facility"]["id"],
             "publication_cycle_id": ctx["cycle"]["id"],
             "service_item_id": ctx["item"]["id"],
             "discounted_cash_cents": 51000}, OFFICER)
        validate_error(resp, ApiErrorId.ERR_CYCLE_NOT_OPEN)
        assert resp.status_code == 409

    def test_record_create_blocked_when_cycle_published(self, api):
        """PRD section 3.3: "The target cycle must be `OPEN` (`ERR_CYCLE_NOT_OPEN`), the item must be `ACTIVE` (`ERR_ITEM_RETIRED`), and the three references must agree: the record's `facility_id` must match the facility of both its cycle and its item, or the create is rejected with `ERR_CROSS_FACILITY_REFERENCE`."

        Design: Difficulty/cross_entity_state_dependency/record_create_blocked_when_cycle_not_open
        """
        ctx = setup_published_cycle(
            facility_overrides={"name": "F",
                                "cms_certification_number": "CCN-X1",
                                "bed_count": 100})
        assert ctx["cycle"]["status"] == "PUBLISHED"
        resp = api.create_charge_record(
            {"facility_id": ctx["facility"]["id"],
             "publication_cycle_id": ctx["cycle"]["id"],
             "service_item_id": ctx["item"]["id"],
             "discounted_cash_cents": 51000}, OFFICER)
        validate_error(resp, ApiErrorId.ERR_CYCLE_NOT_OPEN)

    def test_record_create_on_retired_item_rejected(self, api):
        """PRD section 3.3: "The target cycle must be `OPEN` (`ERR_CYCLE_NOT_OPEN`), the item must be `ACTIVE` (`ERR_ITEM_RETIRED`), and the three references must agree: the record's `facility_id` must match the facility of both its cycle and its item, or the create is rejected with `ERR_CROSS_FACILITY_REFERENCE`."
        PRD section 3.8: "Retirement is terminal, and a retired item reverberates through the rest of the workflow: it blocks record creation and validation (`ERR_ITEM_RETIRED`), and it surfaces during file validation as a `RETIRED_ITEM_PRESENT` violation."

        Design: Corner/errors/record_create_on_retired_item_rejected
        """
        fac = create_facility(name="F", cms_certification_number="CCN-ER5",
                              bed_count=50)
        item = create_service_item(fac["id"], code="70551", description="MRI",
                                   gross_charge_cents=100000)
        get_success_data(api.patch_service_item(
            item["id"], {"status": "RETIRED",
                         "expected_service_item_version": item["version"]},
            OFFICER))
        cycle = create_cycle(fac["id"])
        resp = api.create_charge_record(
            {"facility_id": fac["id"], "publication_cycle_id": cycle["id"],
             "service_item_id": item["id"], "discounted_cash_cents": 50000},
            OFFICER)
        validate_error(resp, ApiErrorId.ERR_ITEM_RETIRED)

    def test_record_validate_twice_rejected(self, api):
        """PRD section 3.3: "A `TransparencyOfficer` validates a record that is still `DRAFT` (`ERR_RECORD_NOT_DRAFT` otherwise) while its cycle remains `OPEN` (`ERR_CYCLE_NOT_OPEN`) and its item remains `ACTIVE` (`ERR_ITEM_RETIRED`)."
        PRD section 3.3: "On success the record transitions `DRAFT → VALIDATED`, both the record's and the cycle's `version` increment, and the cycle's aggregates recompute: `validated_record_count` counts the cycle's records in `VALIDATED`, `PUBLISHED`, or `FLAGGED`; `total_gross_cents` sums their `gross_charge_cents`; and `derived_rollup_cents` sums their `derived_disclosure_cents`, with records whose disclosure figure is null contributing zero."

        Design: Corner/state_machines/record_validate_twice_rejected
        """
        ctx = setup_open_cycle_with_record(
            facility_overrides={"name": "F",
                                "cms_certification_number": "CCN-SM10",
                                "bed_count": 50})
        validate_record(ctx["record"]["id"])
        resp = api.validate_charge_record(ctx["record"]["id"], OFFICER)
        validate_error(resp, ApiErrorId.ERR_RECORD_NOT_DRAFT)
        cycle = get_success_data(api.get_cycle(ctx["cycle"]["id"], OFFICER))
        assert cycle["validated_record_count"] == 1, \
            "the rejected second validation must not double-count"
