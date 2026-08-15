"""Filings and extensions: the reject/amend/refile cycle, the extension
deadline dimensions, filing gates (OCC, deadline, posture), and the
return-to-provision true-up with its payment re-spread cascade.
"""
from test_helpers import (
    ApiErrorId,
    approve_zero_allowance,
    create_filing_record,
    create_fy2026_tax_year,
    create_measured_position,
    create_us_ca_jurisdiction,
    create_us_fed_jurisdiction,
    current_tax_year_version,
    file_ready_filing,
    get_tax_year,
    mark_filing_ready_with_liability,
    set_logical_clock,
    setup_locked_year_with_filing,
    setup_rtp_respread_scenario,
    validate_error,
    validate_success,
)

REJECTION = "schedule M-1 mismatch"


class TestMarkReadyPosture:
    def test_mark_ready_before_lock_returns_tax_year_not_locked(
            self, api, tax_accountant_headers):
        """PRD §3.7: "From `PENDING`, the parent year must be
        `PROVISION_LOCKED`, otherwise `ERR_TAX_YEAR_NOT_LOCKED`."

        Design: Corner/validations/mark_ready_before_lock_returns_tax_year_not_locked
        """
        ty = create_fy2026_tax_year()
        jur = create_us_fed_jurisdiction()
        filing = create_filing_record(ty["id"], jur["id"])
        assert ty["status"] == "OPEN"

        res = api.mark_filing_ready(filing["id"], 21100000,
                                    tax_accountant_headers)
        validate_error(res, ApiErrorId.ERR_TAX_YEAR_NOT_LOCKED,
                       expected_status=409)

        after = validate_success(api.get_filing(filing["id"],
                                                tax_accountant_headers), 200)
        assert after["status"] == "PENDING"


class TestRejectAmendRefileCycle:
    def test_filing_cycles_through_reject_amend_refile(
            self, api, tax_manager_headers, tax_accountant_headers):
        """PRD §3.7: "Rejection moves the filing to `REJECTED` with a
        `rejection_reason`, drops it out of the filed set —
        `return_to_provision_adjustment_cents` and `actual_etr_bp` recompute
        and the year's `version` increments — and opens the amendment path: a
        `TaxAccountant` amends a `REJECTED` filing with a corrected positive
        `return_tax_liability_cents`, moving it to `AMENDED`, from which
        marking it ready again re-enters `READY`."
        PRD §3.7: "From `AMENDED` — the re-entry that completes the
        reject/amend/refile cycle — the parent year may be `PROVISION_LOCKED`
        or `RETURNS_FILED`."

        Design: Difficulty/non_linear_state_machine/filing_reject_amend_refile_cycle
        """
        scenario = setup_locked_year_with_filing(mark_ready_liability=21100000)
        ty = scenario["tax_year"]
        filing = scenario["filing"]
        file_ready_filing(filing["id"], ty["id"])

        st1 = validate_success(
            api.reject_filing(filing["id"], REJECTION, tax_manager_headers),
            200)
        assert st1["status"] == "REJECTED"

        st2 = validate_success(
            api.amend_filing(filing["id"], 21100000, tax_accountant_headers),
            200)
        assert st2["status"] == "AMENDED"

        st3 = validate_success(
            api.mark_filing_ready(filing["id"], 21100000,
                                  tax_accountant_headers), 200)
        assert st3["status"] == "READY"

        st4 = file_ready_filing(filing["id"], ty["id"])
        assert st4["status"] == "FILED"

    def test_extension_dimension_untouched_and_rtp_restored(
            self, api, tax_manager_headers, tax_accountant_headers):
        """PRD §3.7: "The filing starts in status `PENDING` with
        `extension_status` `NONE`"
        PRD §3.7: "hop 1 recomputes the year's
        `return_to_provision_adjustment_cents` as the sum, across the year's
        filings in `FILED` or `ACCEPTED`, of each filing's
        `return_tax_liability_cents` minus its `estimated_liability_cents` —
        a full recompute each time, idempotent across reject/amend/refile
        cycles"

        Design: Difficulty/non_linear_state_machine/filing_reject_amend_refile_cycle
        """
        scenario = setup_locked_year_with_filing(mark_ready_liability=21100000)
        ty = scenario["tax_year"]
        filing = scenario["filing"]
        assert filing["extension_status"] == "NONE"
        # estimate stamped at lock: 100,000,000 * 2100/10000 = 21,000,000
        assert filing["estimated_liability_cents"] == 21000000

        file_ready_filing(filing["id"], ty["id"])
        validate_success(
            api.reject_filing(filing["id"], REJECTION, tax_manager_headers),
            200)
        validate_success(
            api.amend_filing(filing["id"], 21100000, tax_accountant_headers),
            200)
        validate_success(
            api.mark_filing_ready(filing["id"], 21100000,
                                  tax_accountant_headers), 200)
        refiled = file_ready_filing(filing["id"], ty["id"])
        assert refiled["extension_status"] == "NONE", \
            "the parallel extension dimension is untouched by the cycle"

        year = get_tax_year(ty["id"])
        assert year["return_to_provision_adjustment_cents"] == 100000


class TestRtpConservation:
    def test_rtp_drops_to_zero_on_reject(self, api, tax_manager_headers):
        """PRD §3.7: "hop 1 recomputes the year's
        `return_to_provision_adjustment_cents` as the sum, across the year's
        filings in `FILED` or `ACCEPTED`, of each filing's
        `return_tax_liability_cents` minus its `estimated_liability_cents` —
        a full recompute each time, idempotent across reject/amend/refile
        cycles"
        PRD §3.7: "Rejection moves the filing to `REJECTED` with a
        `rejection_reason`, drops it out of the filed set"

        Design: Difficulty/compensating_invariant/filing_refill_cycle_conserves_rtp
        """
        scenario = setup_locked_year_with_filing(mark_ready_liability=21100000)
        ty = scenario["tax_year"]
        filing = scenario["filing"]

        file_ready_filing(filing["id"], ty["id"])
        year_after_file = get_tax_year(ty["id"])
        # 21,100,000 filed - 21,000,000 estimate
        assert year_after_file["return_to_provision_adjustment_cents"] == 100000

        validate_success(
            api.reject_filing(filing["id"], REJECTION, tax_manager_headers),
            200)
        year_after_reject = get_tax_year(ty["id"])
        assert year_after_reject["return_to_provision_adjustment_cents"] == 0

    def test_rtp_restored_exactly_on_refile(self, api, tax_manager_headers,
                                            tax_accountant_headers):
        """PRD §3.7: "hop 1 recomputes the year's
        `return_to_provision_adjustment_cents` as the sum, across the year's
        filings in `FILED` or `ACCEPTED`, of each filing's
        `return_tax_liability_cents` minus its `estimated_liability_cents` —
        a full recompute each time, idempotent across reject/amend/refile
        cycles"

        Design: Difficulty/compensating_invariant/filing_refill_cycle_conserves_rtp
        """
        scenario = setup_locked_year_with_filing(mark_ready_liability=21100000)
        ty = scenario["tax_year"]
        filing = scenario["filing"]

        file_ready_filing(filing["id"], ty["id"])
        validate_success(
            api.reject_filing(filing["id"], REJECTION, tax_manager_headers),
            200)
        validate_success(
            api.amend_filing(filing["id"], 21100000, tax_accountant_headers),
            200)
        validate_success(
            api.mark_filing_ready(filing["id"], 21100000,
                                  tax_accountant_headers), 200)
        file_ready_filing(filing["id"], ty["id"])

        year = get_tax_year(ty["id"])
        # Identical liability re-filed: the conserved quantity is restored
        # exactly, no double-count.
        assert year["return_to_provision_adjustment_cents"] == 100000


class TestRtpPaymentRespread:
    def test_file_recomputes_rtp_adjustment(self, api):
        """PRD §3.7: "Filing fires the return-to-provision cascade: hop 1
        recomputes the year's `return_to_provision_adjustment_cents` as the
        sum, across the year's filings in `FILED` or `ACCEPTED`, of each
        filing's `return_tax_liability_cents` minus its
        `estimated_liability_cents` — a full recompute each time, idempotent
        across reject/amend/refile cycles — and recomputes `actual_etr_bp`."

        Design: Difficulty/transitive_cascade/filing_file_triggers_rtp_and_payment_respread
        """
        scenario = setup_rtp_respread_scenario()
        year = get_tax_year(scenario["tax_year"]["id"])
        # (20,800,000 - 20,946,618) + (2,300,000 - 2,254,200)
        assert year["return_to_provision_adjustment_cents"] == -100818

    def test_file_respreads_remaining_annualized_quarters(self, api,
                                                          auditor_headers):
        """PRD §3.7: "when that set is non-empty, a base delta is the filing's
        delta divided by the number of such payments, rounded half up; every
        payment except the last receives the base delta, and the last payment
        — the highest `quarter_index` — receives the delta minus the base
        delta times one less than the count, so the spread sums exactly to the
        delta; each affected payment's `scheduled_amount_cents` is recomputed
        **from base** as `base_scheduled_amount_cents` plus its assigned
        delta, keeping the operation idempotent. Quarters on the
        `PRIOR_YEAR_SAFE_HARBOR` method and quarters already `PARTIALLY_PAID`,
        `LATE`, or `PAID` are never re-spread."

        Design: Difficulty/transitive_cascade/filing_file_triggers_rtp_and_payment_respread
        """
        scenario = setup_rtp_respread_scenario()
        ids = scenario["ca_payment_ids"]

        # CA delta = 2,300,000 - 2,254,200 = +45,800 over Q2..Q4 (Q1 is PAID)
        # base_delta = round_half_up(45,800 / 3) = 15,267; last takes 15,266.
        q1 = validate_success(api.get_estimated_payment(ids[0],
                                                        auditor_headers), 200)
        q2 = validate_success(api.get_estimated_payment(ids[1],
                                                        auditor_headers), 200)
        q3 = validate_success(api.get_estimated_payment(ids[2],
                                                        auditor_headers), 200)
        q4 = validate_success(api.get_estimated_payment(ids[3],
                                                        auditor_headers), 200)

        assert q1["scheduled_amount_cents"] == 552500, \
            "PAID quarters are never re-spread"
        assert q1["paid_amount_cents"] == 552500
        assert q2["scheduled_amount_cents"] == 567767
        assert q3["scheduled_amount_cents"] == 567767
        assert q4["scheduled_amount_cents"] == 567766

        deltas = [q["scheduled_amount_cents"] - q["base_scheduled_amount_cents"]
                  for q in (q2, q3, q4)]
        assert sum(deltas) == 45800, "the spread sums exactly to the delta"


class TestExtensionDimensions:
    def test_extension_granted_shifts_filing_deadline(
            self, api, tax_accountant_headers, tax_director_headers):
        """PRD §3.7: "`extension_status` becomes the decision, and when
        granted, `extended_due_date` is computed by adding the jurisdiction's
        `extension_months` to `original_due_date`."
        PRD §3.7: "a deadline check against the effective due date —
        `extended_due_date` when the extension is `GRANTED`, else
        `original_due_date` — past which filing is rejected with
        `ERR_FILING_DEADLINE_PASSED`"
        PRD §3.7: "`is_late` is computed as true exactly when `filed_on` is
        after the effective due date."

        Design: Corner/state_machines/extension_granted_shifts_deadline
        """
        scenario = setup_locked_year_with_filing(mark_ready_liability=21000000)
        ty = scenario["tax_year"]
        filing = scenario["filing"]

        set_logical_clock("2027-04-10T00:00:00Z")
        validate_success(api.request_extension(filing["id"],
                                               tax_accountant_headers), 200)
        resolved = validate_success(
            api.resolve_extension(filing["id"], "GRANTED",
                                  tax_director_headers), 200)
        assert resolved["extension_status"] == "GRANTED"
        # 2027-04-15 + extension_months(6) = 2027-10-15
        assert resolved["extended_due_date"] == "2027-10-15"

        # 2027-06-01 is past the original due date but within the extension.
        set_logical_clock("2027-06-01T00:00:00Z")
        filed = file_ready_filing(filing["id"], ty["id"])
        assert filed["status"] == "FILED"
        assert filed["filed_on"] == "2027-06-01"
        assert filed["is_late"] is False

    def test_extension_denied_keeps_original_deadline(
            self, api, tax_accountant_headers, tax_director_headers):
        """PRD §3.7: "`filed_on` and `extended_due_date` are null until their
        respective events."
        PRD §3.7: "a deadline check against the effective due date —
        `extended_due_date` when the extension is `GRANTED`, else
        `original_due_date` — past which filing is rejected with
        `ERR_FILING_DEADLINE_PASSED`"

        Design: Corner/state_machines/extension_denied_keeps_original_deadline
        """
        scenario = setup_locked_year_with_filing(mark_ready_liability=21000000)
        ty = scenario["tax_year"]
        filing = scenario["filing"]

        validate_success(api.request_extension(filing["id"],
                                               tax_accountant_headers), 200)
        resolved = validate_success(
            api.resolve_extension(filing["id"], "DENIED",
                                  tax_director_headers), 200)
        assert resolved["extension_status"] == "DENIED"
        assert resolved.get("extended_due_date") is None

        set_logical_clock("2027-04-20T00:00:00Z")
        version = current_tax_year_version(ty["id"])
        res = api.file_filing(filing["id"], version, tax_director_headers)
        validate_error(res, ApiErrorId.ERR_FILING_DEADLINE_PASSED,
                       expected_status=422)

        after = validate_success(api.get_filing(filing["id"],
                                                tax_director_headers), 200)
        assert after["status"] == "READY"

    def test_extension_request_after_original_due_rejected(
            self, api, tax_accountant_headers):
        """PRD §3.7: "A `TaxAccountant` requests an extension on or before
        `original_due_date` — after it, `ERR_EXTENSION_WINDOW_MISSED` —
        provided `extension_status` is still `NONE`, moving it to
        `REQUESTED`."

        Design: Corner/validations/extension_request_after_original_due_rejected
        """
        scenario = setup_locked_year_with_filing()
        filing = scenario["filing"]

        set_logical_clock("2027-04-16T00:00:00Z")
        res = api.request_extension(filing["id"], tax_accountant_headers)
        validate_error(res, ApiErrorId.ERR_EXTENSION_WINDOW_MISSED,
                       expected_status=422)

        after = validate_success(api.get_filing(filing["id"],
                                                tax_accountant_headers), 200)
        assert after["extension_status"] == "NONE"


class TestFilingGates:
    def test_file_after_deadline_with_undisclosed_utp_reports_deadline(
            self, api, tax_director_headers):
        """PRD §2.6: "When a single request violates more than one rule, the
        lowest priority number wins and determines the response's `error_id`."
        PRD §2.6: "**Deadline discipline and date-range sanity** — extension
        window missed (`ERR_EXTENSION_WINDOW_MISSED`), filing deadline passed
        (`ERR_FILING_DEADLINE_PASSED`), and malformed date ranges
        (`ERR_DATE_RANGE_INVALID`)."
        PRD §2.6: "**Cross-entity readiness** — lock-provision's unresolved
        items (`ERR_UNRESOLVED_PROVISION_ITEMS`), unfiled returns at
        mark-returns-filed (`ERR_UNFILED_RETURNS`), undisclosed UTPs at file
        time (`ERR_UTP_UNDISCLOSED`), the return-not-ready gate on disclosure
        (`ERR_RETURN_NOT_READY`), and unresolved notices at audit close
        (`ERR_UNRESOLVED_NOTICES`)."

        Design: Difficulty/priority_pair_validation_conflict/filing_deadline_beats_utp_referential
        """
        scenario = setup_locked_year_with_filing(mark_ready_liability=21100000)
        ty = scenario["tax_year"]
        jur = scenario["jurisdiction"]
        filing = scenario["filing"]
        # Measured sub-threshold UTP (liability 1,000,000, disclosure
        # required) left un-disclosed: the UTP gate is also violated.
        create_measured_position(ty["id"], jur["id"],
                                 position_amount_cents=1000000,
                                 cumulative_probability_bp=4000)

        set_logical_clock("2027-04-16T00:00:00Z")  # one day past the due date
        version = current_tax_year_version(ty["id"])
        res = api.file_filing(filing["id"], version, tax_director_headers)
        error = validate_error(res, ApiErrorId.ERR_FILING_DEADLINE_PASSED,
                               expected_status=422)
        assert error["error_id"] != "ERR_UTP_UNDISCLOSED"

    def test_deadline_rejection_leaves_filing_ready(self, api,
                                                    tax_director_headers):
        """PRD §3.7: "a deadline check against the effective due date —
        `extended_due_date` when the extension is `GRANTED`, else
        `original_due_date` — past which filing is rejected with
        `ERR_FILING_DEADLINE_PASSED`"
        PRD §3.7: "a UTP gate requiring every disclosure-required position
        sharing the filing's `tax_year_id` and `jurisdiction_id` to be in
        `DISCLOSED`, `SETTLED`, or `LAPSED`, else `ERR_UTP_UNDISCLOSED`."

        Design: Difficulty/priority_pair_validation_conflict/filing_deadline_beats_utp_referential
        """
        scenario = setup_locked_year_with_filing(mark_ready_liability=21100000)
        ty = scenario["tax_year"]
        jur = scenario["jurisdiction"]
        filing = scenario["filing"]
        utp = create_measured_position(ty["id"], jur["id"],
                                       position_amount_cents=1000000,
                                       cumulative_probability_bp=4000)

        set_logical_clock("2027-04-16T00:00:00Z")
        version = current_tax_year_version(ty["id"])
        validate_error(api.file_filing(filing["id"], version,
                                       tax_director_headers),
                       ApiErrorId.ERR_FILING_DEADLINE_PASSED,
                       expected_status=422)

        after = validate_success(api.get_filing(filing["id"],
                                                tax_director_headers), 200)
        assert after["status"] == "READY", \
            "the rejected file attempt leaves the filing untouched"
        utp_after = validate_success(
            api.get_uncertain_tax_position(utp["id"], tax_director_headers),
            200)
        assert utp_after["status"] == "MEASURED"

    def test_second_file_with_stale_year_version_rejected(
            self, api, tax_director_headers):
        """PRD §2.8: "**Filing a return** requires the request to carry
        `expected_tax_year_version` matching the parent year's current
        `version`. Filing legitimately recomputes the return-to-provision
        adjustment and re-spreads remaining estimated payments, so a filer
        working from a stale year view would compute downstream amounts from
        superseded inputs; the stale-version check forces a re-read first. A
        mismatch is likewise rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/filing_file_stale_version_412
        """
        set_logical_clock("2026-01-05T00:00:00Z")
        ty = create_fy2026_tax_year()
        jur_fed = create_us_fed_jurisdiction()
        jur_ca = create_us_ca_jurisdiction()
        fil_fed = create_filing_record(ty["id"], jur_fed["id"])
        fil_ca = create_filing_record(ty["id"], jur_ca["id"])

        approve_zero_allowance(ty["id"])
        validate_success(api.lock_provision(ty["id"], tax_director_headers),
                         200)
        mark_filing_ready_with_liability(fil_fed["id"], 21100000)
        mark_filing_ready_with_liability(fil_ca["id"], 2200000)

        # One version observed before either filing lands.
        observed_version = current_tax_year_version(ty["id"])
        filed = validate_success(
            api.file_filing(fil_fed["id"], observed_version,
                            tax_director_headers), 200)
        assert filed["status"] == "FILED"

        # The first file bumped the year's version; the second file with the
        # stale version is rejected and leaves the CA filing untouched.
        res = api.file_filing(fil_ca["id"], observed_version,
                              tax_director_headers)
        validate_error(res, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

        ca_after = validate_success(api.get_filing(fil_ca["id"],
                                                   tax_director_headers), 200)
        assert ca_after["status"] == "READY"
