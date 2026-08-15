"""Discrepancy intake and the segregation-of-duties correction pipeline."""
from test_helpers import (
    ApiErrorId,
    create_charge_record,
    create_cycle,
    create_facility,
    create_service_item,
    get_success_data,
    make_officer_headers,
    setup_confirmed_discrepancy,
    setup_correction_approved,
    setup_published_cycle,
    validate_error,
    validate_paginated,
)
from test_helpers.factories import create_discrepancy_payload
from test_helpers.fixtures import AUDITOR, CONSUMER, MANAGER, OFFICER


class TestDiscrepancyIntake:
    def test_discrepancy_create_unpublished_cycle_and_mismatched_record(
            self, api):
        """PRD section 3.7: "The referenced cycle must be `PUBLISHED` (`ERR_CYCLE_NOT_PUBLISHED`)."
        PRD section 2.9: "Requests are validated against a fixed priority ladder, and a request that fails several rungs is rejected with the error from the earliest failing rung."

        Design: Difficulty/priority_pair_validation_conflict/discrepancy_create_unpublished_cycle_and_mismatched_record
        """
        fac = create_facility(name="F", cms_certification_number="CCN-V2",
                              bed_count=100)
        item = create_service_item(fac["id"], code="70551", description="MRI",
                                   gross_charge_cents=100000)
        cy1 = create_cycle(fac["id"])  # [2026-08-01, 2026-09-01), OPEN
        cy2 = create_cycle(fac["id"], period_start="2026-09-01T00:00:00Z",
                           period_end="2026-10-01T00:00:00Z")
        r2 = create_charge_record(fac["id"], cy2["id"], item["id"],
                                  discounted_cash_cents=50000)
        # The cycle-state rung (cy1 is not PUBLISHED) fires before the
        # referential rung (R2 belongs to cy2, not cy1).
        resp = api.create_discrepancy(
            create_discrepancy_payload(cy1["id"], r2["id"],
                                       description="price looks wrong"),
            CONSUMER)
        err = validate_error(resp, ApiErrorId.ERR_CYCLE_NOT_PUBLISHED)
        assert resp.status_code == 409
        assert err["error_id"] != ApiErrorId.ERR_RECORD_CYCLE_MISMATCH

    def test_discrepancy_create_rejection_persists_nothing(self, api):
        """PRD section 3.7: "The referenced cycle must be `PUBLISHED` (`ERR_CYCLE_NOT_PUBLISHED`)."
        PRD section 3.7: "A new report is `SUBMITTED`."

        Design: Difficulty/priority_pair_validation_conflict/discrepancy_create_unpublished_cycle_and_mismatched_record
        """
        fac = create_facility(name="F", cms_certification_number="CCN-V2",
                              bed_count=100)
        item = create_service_item(fac["id"], code="70551", description="MRI",
                                   gross_charge_cents=100000)
        cy1 = create_cycle(fac["id"])
        cy2 = create_cycle(fac["id"], period_start="2026-09-01T00:00:00Z",
                           period_end="2026-10-01T00:00:00Z")
        r2 = create_charge_record(fac["id"], cy2["id"], item["id"],
                                  discounted_cash_cents=50000)
        resp = api.create_discrepancy(
            create_discrepancy_payload(cy1["id"], r2["id"]), CONSUMER)
        assert resp.status_code == 409
        # No SUBMITTED report was persisted by the rejected request.
        reports, meta = validate_paginated(api.list_discrepancies(CONSUMER))
        assert reports == []
        assert meta["total_count"] == 0

    def test_discrepancy_record_cycle_mismatch_isolated(self, api):
        """PRD section 3.7: "Two referential checks then run in a fixed order: first the disputed record must belong to the referenced cycle (`ERR_RECORD_CYCLE_MISMATCH`), and only then is the record's disputable status checked — it must be `PUBLISHED` or `FLAGGED`, otherwise the report is rejected with `ERR_RECORD_NOT_DISPUTABLE`."

        Design: Corner/validations/discrepancy_record_cycle_mismatch_isolated
        """
        ctx = setup_published_cycle(
            facility_overrides={"name": "F",
                                "cms_certification_number": "CCN-H6",
                                "bed_count": 50})
        fac = ctx["facility"]
        cy_b = create_cycle(fac["id"], period_start="2026-09-01T00:00:00Z",
                            period_end="2026-10-01T00:00:00Z")
        r_b = create_charge_record(fac["id"], cy_b["id"], ctx["item"]["id"],
                                   discounted_cash_cents=51000)
        # The referenced cycle IS published, so only the referential rule can
        # fire: R_B belongs to the other cycle.
        resp = api.create_discrepancy(
            create_discrepancy_payload(ctx["cycle"]["id"], r_b["id"],
                                       description="mismatch"),
            CONSUMER)
        validate_error(resp, ApiErrorId.ERR_RECORD_CYCLE_MISMATCH)

    def test_discrepancy_on_superseded_record_rejected(self, api):
        """PRD section 3.7: "Two referential checks then run in a fixed order: first the disputed record must belong to the referenced cycle (`ERR_RECORD_CYCLE_MISMATCH`), and only then is the record's disputable status checked — it must be `PUBLISHED` or `FLAGGED`, otherwise the report is rejected with `ERR_RECORD_NOT_DISPUTABLE`."

        Design: Corner/validations/discrepancy_on_superseded_record_rejected
        """
        ctx = setup_correction_approved(
            facility_overrides={"name": "F",
                                "cms_certification_number": "CCN-H18",
                                "bed_count": 50},
            proposal={"proposed_gross_charge_cents": 90000})
        # Apply the approved correction: R1 is now SUPERSEDED.
        get_success_data(api.apply_correction(
            ctx["discrepancy"]["id"], make_officer_headers("officer-a")))
        record = get_success_data(
            api.get_charge_record(ctx["record"]["id"], OFFICER))
        assert record["status"] == "SUPERSEDED"
        resp = api.create_discrepancy(
            create_discrepancy_payload(ctx["cycle"]["id"], record["id"],
                                       description="too late"),
            CONSUMER)
        validate_error(resp, ApiErrorId.ERR_RECORD_NOT_DISPUTABLE)

    def test_discrepancy_terminal_lockdown_and_wrong_step(self, api):
        """PRD section 3.7: "A `ComplianceAuditor` triages a `SUBMITTED` report with an `outcome` of `CONFIRMED` or `DISMISSED`; triage from any other status, and indeed any correction action attempted from a status where it is not defined, is rejected with `ERR_DISCREPANCY_NOT_ACTIONABLE`."
        PRD section 3.7: "A `DISMISSED` outcome simply closes the report."

        Design: Corner/state_machines/discrepancy_terminal_lockdown_and_wrong_step
        """
        ctx = setup_published_cycle(
            facility_overrides={"name": "F",
                                "cms_certification_number": "CCN-SM11",
                                "bed_count": 50})
        cycle_id, record_id = ctx["cycle"]["id"], ctx["record"]["id"]
        d1 = get_success_data(api.create_discrepancy(
            create_discrepancy_payload(cycle_id, record_id, description="d1"),
            CONSUMER))
        get_success_data(api.triage_discrepancy(
            d1["id"], {"outcome": "DISMISSED"}, AUDITOR))
        d2 = get_success_data(api.create_discrepancy(
            create_discrepancy_payload(cycle_id, record_id, description="d2",
                                       reporter_type="PAYER"),
            MANAGER))
        get_success_data(api.triage_discrepancy(
            d2["id"], {"outcome": "CONFIRMED"}, AUDITOR))
        # DISMISSED is terminal: no correction action exists from it.
        resp = api.propose_correction(
            d1["id"], {"proposed_gross_charge_cents": 90000},
            make_officer_headers("officer-a"))
        validate_error(resp, ApiErrorId.ERR_DISCREPANCY_NOT_ACTIONABLE)
        # Approve before propose is likewise undefined from CONFIRMED.
        resp = api.approve_correction(d2["id"], make_officer_headers(
            "officer-b"))
        validate_error(resp, ApiErrorId.ERR_DISCREPANCY_NOT_ACTIONABLE)


class TestProposalGuards:
    def test_propose_correction_requires_at_least_one_field(self, api):
        """PRD section 3.7: "A `TransparencyOfficer` proposes corrected figures on a `CONFIRMED` report, supplying at least one of `proposed_gross_charge_cents` or `proposed_discounted_cash_cents`; a payload with neither is a no-op and is rejected with `ERR_INVALID_REQUEST`."

        Design: Corner/validations/propose_correction_requires_at_least_one_field
        """
        ctx = setup_confirmed_discrepancy(
            facility_overrides={"name": "F",
                                "cms_certification_number": "CCN-H12",
                                "bed_count": 50})
        resp = api.propose_correction(ctx["discrepancy"]["id"], {},
                                      make_officer_headers("officer-a"))
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_propose_cash_above_effective_gross_rejected(self, api):
        """PRD section 3.7: "The effective proposed discounted cash price must not exceed the effective proposed gross charge — a supplied proposal overrides the record's current value on its side, and a side left unsupplied falls back to the record's current value — or the proposal is rejected with `ERR_CASH_EXCEEDS_GROSS`."

        Design: Corner/validations/propose_cash_above_effective_gross_rejected
        """
        ctx = setup_confirmed_discrepancy(
            facility_overrides={"name": "F",
                                "cms_certification_number": "CCN-H13",
                                "bed_count": 50},
            reporter_headers=MANAGER)
        # Effective gross 80000 (proposed), effective cash 90000 (proposed):
        # 90000 > 80000 violates the cross-field rule on effective values.
        resp = api.propose_correction(
            ctx["discrepancy"]["id"],
            {"proposed_gross_charge_cents": 80000,
             "proposed_discounted_cash_cents": 90000},
            make_officer_headers("officer-a"))
        validate_error(resp, ApiErrorId.ERR_CASH_EXCEEDS_GROSS)


class TestSegregationOfDuties:
    def test_sod_approver_must_differ_from_proposer(self, api):
        """PRD section 3.7: "Approval moves the report `CORRECTION_PROPOSED → CORRECTION_APPROVED` and stamps `approved_by_user_id`, but the approver must not be the proposer: an `X-User-ID` equal to `proposed_by_user_id` is rejected with `ERR_SOD_SAME_USER`."

        Design: Corner/validations/sod_approver_must_differ_from_proposer
        """
        ctx = _setup_correction_proposed(api, ccn="CCN-H8")
        d_id = ctx["discrepancy"]["id"]
        resp = api.approve_correction(d_id, make_officer_headers("officer-a"))
        validate_error(resp, ApiErrorId.ERR_SOD_SAME_USER)
        assert resp.status_code == 422
        approved = get_success_data(api.approve_correction(
            d_id, make_officer_headers("officer-b")))
        assert approved["status"] == "CORRECTION_APPROVED"
        assert approved["approved_by_user_id"] == "officer-b"

    def test_sod_applier_must_differ_from_approver(self, api):
        """PRD section 3.7: "Application moves the report `CORRECTION_APPROVED → CORRECTED` and stamps `applied_by_user_id`, and likewise the applier must not be the approver, on pain of `ERR_SOD_SAME_USER`."

        Design: Corner/validations/sod_applier_must_differ_from_approver
        """
        ctx = setup_correction_approved(
            proposer="officer-a", approver="officer-b",
            proposal={"proposed_discounted_cash_cents": 45000},
            facility_overrides={"name": "F",
                                "cms_certification_number": "CCN-H9",
                                "bed_count": 50},
            reporter_headers=OFFICER)
        d_id = ctx["discrepancy"]["id"]
        resp = api.apply_correction(d_id, make_officer_headers("officer-b"))
        validate_error(resp, ApiErrorId.ERR_SOD_SAME_USER)
        # The original proposer may apply: the constraint binds the approver,
        # not the whole chain.
        applied = get_success_data(api.apply_correction(
            d_id, make_officer_headers("officer-a")))
        assert applied["status"] == "CORRECTED"
        assert applied["applied_by_user_id"] == "officer-a"


class TestCorrectionInvariants:
    def test_correction_apply_conserves_cycle_record_count(self, api):
        """PRD section 3.7: "The owning cycle's aggregates adjust surgically in the same request: `validated_record_count` is conserved — the old record leaves the counted set as the new one enters — `total_gross_cents` shifts by exactly the difference between the new and old gross charges, and `derived_rollup_cents` recomputes; the cycle's `version` increments, as do the discrepancy's and both records'."

        Design: Difficulty/compensating_invariant/correction_apply_conserves_cycle_record_count
        """
        ctx = setup_correction_approved(
            proposer="officer-a", approver="officer-b",
            proposal={"proposed_gross_charge_cents": 80000},
            facility_overrides={"name": "F",
                                "cms_certification_number": "CCN-I1",
                                "bed_count": 100})
        cycle_id = ctx["cycle"]["id"]
        cycle_pre = get_success_data(api.get_cycle(cycle_id, OFFICER))
        assert cycle_pre["validated_record_count"] == 1
        assert cycle_pre["total_gross_cents"] == 100000
        discrepancy = get_success_data(api.apply_correction(
            ctx["discrepancy"]["id"], make_officer_headers("officer-a")))
        assert discrepancy["status"] == "CORRECTED"
        cycle_post = get_success_data(api.get_cycle(cycle_id, OFFICER))
        # The active-record count is conserved across the supersede pair and
        # the gross total moves by exactly the correction delta (-20000).
        assert cycle_post["validated_record_count"] == 1
        assert cycle_post["total_gross_cents"] == 80000

    def test_correction_apply_supersedes_and_replaces_record(self, api):
        """PRD section 3.7: "The disputed record moves `FLAGGED → SUPERSEDED`, and a brand-new `StandardChargeRecord` is created directly in `PUBLISHED` status with `supersedes_id` pointing at the disputed record, its `gross_charge_cents` set to `proposed_gross_charge_cents` when present and to the prior value otherwise, its `discounted_cash_cents` set to `proposed_discounted_cash_cents` when present and to the prior value otherwise, and its minima, maxima, and disclosure figure recomputed."

        Design: Difficulty/compensating_invariant/correction_apply_conserves_cycle_record_count
        """
        ctx = setup_correction_approved(
            proposer="officer-a", approver="officer-b",
            proposal={"proposed_gross_charge_cents": 80000},
            facility_overrides={"name": "F",
                                "cms_certification_number": "CCN-I1",
                                "bed_count": 100})
        get_success_data(api.apply_correction(
            ctx["discrepancy"]["id"], make_officer_headers("officer-a")))
        r1 = get_success_data(
            api.get_charge_record(ctx["record"]["id"], OFFICER))
        assert r1["status"] == "SUPERSEDED"
        replacements, meta = validate_paginated(api.list_charge_records(
            OFFICER, params={"supersedes_id": r1["id"]}))
        assert meta["total_count"] == 1
        r2 = replacements[0]
        assert r2["status"] == "PUBLISHED"
        assert r2["supersedes_id"] == r1["id"]
        assert r2["gross_charge_cents"] == 80000
        # Cash was not proposed: the prior value carries over.
        assert r2["discounted_cash_cents"] == 50000

    def test_compensating_corrections_restore_total_gross(self, api):
        """PRD section 3.7: "The owning cycle's aggregates adjust surgically in the same request: `validated_record_count` is conserved — the old record leaves the counted set as the new one enters — `total_gross_cents` shifts by exactly the difference between the new and old gross charges, and `derived_rollup_cents` recomputes; the cycle's `version` increments, as do the discrepancy's and both records'."

        Design: Difficulty/compensating_invariant/compensating_corrections_restore_total_gross
        """
        ctx = _apply_correction_chain(api)
        cycle = get_success_data(api.get_cycle(ctx["cycle"]["id"], OFFICER))
        # Forward correction 100000 -> 70000 then compensating 70000 ->
        # 100000: the original monetary total is restored exactly.
        assert cycle["total_gross_cents"] == 100000
        assert cycle["validated_record_count"] == 1

    def test_compensating_corrections_lineage_chain(self, api):
        """PRD section 3.7: "The disputed record moves `FLAGGED → SUPERSEDED`, and a brand-new `StandardChargeRecord` is created directly in `PUBLISHED` status with `supersedes_id` pointing at the disputed record, its `gross_charge_cents` set to `proposed_gross_charge_cents` when present and to the prior value otherwise, its `discounted_cash_cents` set to `proposed_discounted_cash_cents` when present and to the prior value otherwise, and its minima, maxima, and disclosure figure recomputed."

        Design: Difficulty/compensating_invariant/compensating_corrections_restore_total_gross
        """
        ctx = _apply_correction_chain(api)
        r1 = get_success_data(
            api.get_charge_record(ctx["record"]["id"], OFFICER))
        assert r1["status"] == "SUPERSEDED"
        r2 = get_success_data(api.get_charge_record(ctx["r2_id"], OFFICER))
        assert r2["status"] == "SUPERSEDED"
        r3s, _ = validate_paginated(api.list_charge_records(
            OFFICER, params={"supersedes_id": r2["id"]}))
        assert len(r3s) == 1
        r3 = r3s[0]
        assert r3["status"] == "PUBLISHED"
        assert r3["gross_charge_cents"] == 100000
        assert r3["supersedes_id"] == r2["id"]


def _setup_correction_proposed(api, ccn="CCN-H8"):
    """Published cycle + CONFIRMED discrepancy + correction proposed by
    officer-a (gross 90000)."""
    ctx = setup_confirmed_discrepancy(
        facility_overrides={"name": "F", "cms_certification_number": ccn,
                            "bed_count": 50})
    discrepancy = get_success_data(api.propose_correction(
        ctx["discrepancy"]["id"], {"proposed_gross_charge_cents": 90000},
        make_officer_headers("officer-a")))
    ctx["discrepancy"] = discrepancy
    return ctx


def _apply_correction_chain(api) -> dict:
    """Two-hop correction chain: R1 (gross 100000) -> R2 (70000) -> R3
    (100000), returning the scenario context with all record ids."""
    ctx = setup_correction_approved(
        proposer="officer-a", approver="officer-b",
        proposal={"proposed_gross_charge_cents": 70000},
        facility_overrides={"name": "F", "cms_certification_number": "CCN-I2",
                            "bed_count": 100},
        reporter_headers=MANAGER)
    get_success_data(api.apply_correction(
        ctx["discrepancy"]["id"], make_officer_headers("officer-a")))
    r2s, _ = validate_paginated(api.list_charge_records(
        OFFICER, params={"supersedes_id": ctx["record"]["id"]}))
    r2_id = r2s[0]["id"]
    ctx["r2_id"] = r2_id
    # Compensating correction against R2, restoring the original gross.
    d2 = get_success_data(api.create_discrepancy(
        create_discrepancy_payload(ctx["cycle"]["id"], r2_id,
                                   reporter_type="INTERNAL",
                                   description="original 100000 was correct"),
        OFFICER))
    get_success_data(api.triage_discrepancy(d2["id"],
                                            {"outcome": "CONFIRMED"}, AUDITOR))
    get_success_data(api.propose_correction(
        d2["id"], {"proposed_gross_charge_cents": 100000},
        make_officer_headers("officer-b")))
    get_success_data(api.approve_correction(
        d2["id"], make_officer_headers("officer-a")))
    get_success_data(api.apply_correction(
        d2["id"], make_officer_headers("officer-b")))
    return ctx
