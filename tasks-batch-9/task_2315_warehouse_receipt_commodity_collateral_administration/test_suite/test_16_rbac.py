"""
Authentication, per-endpoint role authorization, entity-backed ownership and the
one per-user bar in the system: examination independence.
"""

import pytest
from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers import api_errors as E
from test_helpers import factories as f
from test_helpers.assertions import assert_fields_equal
from test_helpers.test_users import (
    NO_AUTH_HEADERS,
    REGISTRY_ADMIN_HEADERS,
    REGULATOR_HEADERS,
    REGULATOR_USER_ID,
    SECOND_REGULATOR_HEADERS,
    SECOND_REGULATOR_USER_ID,
    make_depositor_headers,
    make_headers,
    make_lender_headers,
    make_warehouse_operator_headers,
)

CLOCK_DAY_16 = "2026-08-20T09:00:00Z"


class TestAuthenticationPrecedesEverything:
    def test_a_warehouse_application_without_headers_is_unauthenticated(
        self, api, base_clock
    ):
        """
        The payload is complete and would license cleanly, but the two identifying
        headers are absent — so the request never reaches the licensing rules at
        all, and no warehouse row survives it.

        PRD: "Every request other than the logical-clock control endpoint must
        carry two headers: `X-User-ID`, identifying the acting principal, and
        `X-User-Role`, declaring the capacity in which it is acting."

        PRD: "A request that omits either header, or that supplies an
        `X-User-Role` value outside that set of five, is rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/rbac/missing_role_and_user_headers_return_unauthenticated
        """
        response = api.create_warehouse(
            f.warehouse_payload(
                name="Ghost Elevator", operator_name="Nobody Grain LLC"
            ),
            NO_AUTH_HEADERS,
        )

        validate_error(response, E.ERR_UNAUTHENTICATED, 401)

        rows, meta = validate_paginated(api.list_warehouses({}, REGULATOR_HEADERS))
        assert rows == []
        assert meta["total_count"] == 0

    def test_a_role_outside_the_five_is_unauthenticated_not_unauthorized(
        self, api, base_clock
    ):
        """
        `GrainInspector` is spelled like a role and carries a plausible user id,
        but it is not one of the five the system knows. That is an authentication
        failure, not an authorization one: the answer is 401 with
        `ERR_UNAUTHENTICATED`, never the 403 `ERR_UNAUTHORIZED` reserved for a
        recognised role that this endpoint does not list.

        PRD: "Exactly five roles exist, spelled as follows: `StateRegulator`,
        `WarehouseOperator`, `Depositor`, `Lender`, and `RegistryAdministrator`."

        PRD: "A request that omits either header, or that supplies an
        `X-User-Role` value outside that set of five, is rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401)."

        PRD: "A well-authenticated request whose role is not listed as authorized
        for the endpoint it addresses is rejected with `ERR_UNAUTHORIZED` (HTTP
        403)."

        Design: Corner/rbac/unknown_role_name_in_header_is_unauthenticated_not_unauthorized
        """
        response = api.create_warehouse(
            f.warehouse_payload(
                name="Ghost Elevator", operator_name="Nobody Grain LLC"
            ),
            make_headers("GrainInspector", "insp-001"),
        )

        error = validate_error(response, E.ERR_UNAUTHENTICATED, 401)
        assert error["error_id"] != E.ERR_UNAUTHORIZED

        rows, meta = validate_paginated(api.list_warehouses({}, REGULATOR_HEADERS))
        assert rows == []
        assert meta["total_count"] == 0


class TestReceiptIssuanceIsTheOperatorsAlone:
    def test_the_holder_to_be_cannot_issue_its_own_receipt(self, api, base_pre):
        """
        Every substantive precondition is satisfied — the ticket is ACCEPTED and
        the warehouse version supplied is the current one — yet the depositor who
        would hold the receipt is not a role listed on the issuance endpoint, so
        nothing is issued and the ticket stays where it was.

        PRD: "| POST | `/receipts` | Issue a warehouse receipt against an accepted
        ticket | WarehouseOperator |"

        PRD: "A well-authenticated request whose role is not listed as authorized
        for the endpoint it addresses is rejected with `ERR_UNAUTHORIZED` (HTTP
        403)."

        Design: Corner/rbac/depositor_cannot_issue_a_receipt
        """
        warehouse = get_success_data(
            api.get_warehouse(base_pre["warehouse_id"], base_pre["operator_headers"]),
            200,
        )

        response = api.create_receipt(
            f.receipt_payload(
                base_pre["ticket_id"],
                base_pre["depositor_id"],
                warehouse["version"],
                receipt_number="WR-0009",
            ),
            base_pre["depositor_headers"],
        )

        validate_error(response, E.ERR_UNAUTHORIZED, 403)

        rows, meta = validate_paginated(
            api.list_receipts(
                {"deposit_ticket_id": base_pre["ticket_id"]},
                base_pre["operator_headers"],
            )
        )
        assert rows == []
        assert meta["total_count"] == 0

        ticket = get_success_data(
            api.get_deposit_ticket(base_pre["ticket_id"], base_pre["operator_headers"]),
            200,
        )
        assert ticket["ticket_state"] == "ACCEPTED"


class TestExaminationIsTheRegulatorsAlone:
    def test_the_operator_that_filed_the_report_cannot_examine_it(
        self, api, licensed_warehouse, submitted_report
    ):
        """
        The operator legitimately opened and submitted the report, and its declared
        900 physical bushels against an empty facility overshoot the 500-bushel
        tolerance floor, so the filing did land under examination. Examining is a
        different matter: the operator is not a role listed on that endpoint, and
        the report keeps waiting with no result recorded.

        PRD: "`count_discrepancy_bushels` is the operator's declared
        `reported_physical_bushels` less the system physical figure."

        PRD: "The tolerance against which all three are judged is
        `examination_tolerance_bushels`: the greater of a 500-bushel floor and 50
        basis points — one half of one percent — of the obligation, rounded half up
        to a whole bushel."

        PRD: "`examination_required` is true when the absolute value of **any** of
        the three deltas is **strictly greater** than that tolerance; a delta
        exactly equal to the tolerance does not require examination."

        PRD: "When `examination_required` computes true, a `DRAFT` report goes to
        `UNDER_EXAMINATION` instead, and this branch additionally requires that no
        other report of the same warehouse already sit in `UNDER_EXAMINATION`; a
        second referral while another remains under examination is refused with
        `ERR_INVALID_STATE`."

        PRD: "| POST | `/position-reports/{report_id}/examine` | Record the
        examination result | StateRegulator |"

        PRD: "A well-authenticated request whose role is not listed as authorized
        for the endpoint it addresses is rejected with `ERR_UNAUTHORIZED` (HTTP
        403)."

        Design: Corner/rbac/warehouse_operator_cannot_examine_a_position_report
        """
        warehouse = licensed_warehouse()
        report = submitted_report(warehouse["id"], 900, 0)
        assert report["report_state"] == "UNDER_EXAMINATION"
        operator_headers = make_warehouse_operator_headers(warehouse["id"])

        response = api.examine_position_report(
            report["id"], f.examine_report_payload("PASS"), operator_headers
        )

        validate_error(response, E.ERR_UNAUTHORIZED, 403)

        current = get_success_data(
            api.get_position_report(report["id"], REGULATOR_HEADERS), 200
        )
        assert_fields_equal(
            current,
            {"report_state": "UNDER_EXAMINATION", "examination_result": None},
        )


class TestAdjudicationIsTheRegulatorsAlone:
    @pytest.fixture
    def lender_filed_claim(
        self, api, base_full, perfected_lien, claims_open_warehouse
    ):
        """
        A lender that took electronic control of WR-0001 — and is therefore an
        eligible claimant on it — has filed a 300000-cent claim against the
        declared warehouse.
        """
        perfected_lien(base_full["receipt_id"], base_full["lender_id"])
        receipt = get_success_data(
            api.get_receipt(base_full["receipt_id"], base_full["operator_headers"]), 200
        )
        assert receipt["registry_control_party_id"] == base_full["lender_id"]
        claims_open_warehouse(base_full["warehouse_id"])
        claim = get_success_data(
            api.create_indemnity_claim(
                f.indemnity_claim_payload(
                    base_full["warehouse_id"],
                    base_full["receipt_id"],
                    base_full["lender_id"],
                    300_000,
                ),
                base_full["lender_headers"],
            ),
            201,
        )
        return {"claim_id": claim["id"], "scenario": base_full}

    def test_a_lender_may_file_a_claim_but_not_decide_it(
        self, api, lender_filed_claim
    ):
        """
        Filing is a shared operation and the lender's own claim was accepted; the
        decision is not shared. The lender's attempt to allow its own claim is
        refused outright, so the claim keeps sitting in FILED with nothing allowed
        and nobody recorded as having adjudicated it.

        PRD: "| POST | `/indemnity-claims/{claim_id}/adjudicate` | Allow or
        disallow a filed claim | StateRegulator |"

        PRD: "A well-authenticated request whose role is not listed as authorized
        for the endpoint it addresses is rejected with `ERR_UNAUTHORIZED` (HTTP
        403)."

        PRD: "A new claim starts `FILED` with `entitlement_cents`,
        `allowed_cents`, `bond_share_cents`, `fund_share_cents` and `unpaid_cents`
        all zero or unset and `adjudicated_by_user_id` and `adjudication_note`
        null."

        Design: Corner/rbac/lender_cannot_adjudicate_an_indemnity_claim
        """
        scenario = lender_filed_claim["scenario"]

        response = api.adjudicate_indemnity_claim(
            lender_filed_claim["claim_id"],
            f.adjudicate_payload("ALLOW", adjudication_note="self-approved"),
            scenario["lender_headers"],
        )

        validate_error(response, E.ERR_UNAUTHORIZED, 403)

        claim = get_success_data(
            api.get_indemnity_claim(
                lender_filed_claim["claim_id"], REGULATOR_HEADERS
            ),
            200,
        )
        assert_fields_equal(
            claim,
            {
                "claim_state": "FILED",
                "allowed_cents": 0,
                "adjudicated_by_user_id": None,
                "adjudication_note": None,
            },
        )


class TestBinCreationIsTheOperatorsAlone:
    def test_the_registry_administrator_cannot_add_a_bin(
        self, api, licensed_warehouse
    ):
        """
        The registry administrator's identity is opaque, so no ownership test could
        ever apply to it — the refusal has to come from the role list on the
        endpoint itself, and the warehouse ends the request with no bins at all.

        PRD: "| POST | `/bins` | Add a storage bin | WarehouseOperator |"

        PRD: "A well-authenticated request whose role is not listed as authorized
        for the endpoint it addresses is rejected with `ERR_UNAUTHORIZED` (HTTP
        403)."

        Design: Corner/rbac/registry_administrator_cannot_create_a_bin
        """
        warehouse = licensed_warehouse()

        response = api.create_bin(
            f.bin_payload(warehouse["id"], bin_code="B9", capacity_bushels=10_000),
            REGISTRY_ADMIN_HEADERS,
        )

        validate_error(response, E.ERR_UNAUTHORIZED, 403)

        rows, meta = validate_paginated(
            api.list_bins({"warehouse_id": warehouse["id"]}, REGULATOR_HEADERS)
        )
        assert rows == []
        assert meta["total_count"] == 0


class TestCreditLineRestatementIsTheRegulatorsAlone:
    def test_the_operator_cannot_restate_a_lenders_line(
        self, api, licensed_warehouse, new_lender
    ):
        """
        The operator shares the warehouse-financials restatement with the
        regulator, which makes it easy to assume it shares the lender's line too.
        It does not: the line stays at the registered 50000000 cents, the whole of
        it still available, and the party row is not mutated at all.

        PRD: "| PATCH | `/parties/{party_id}/credit-line` | Restate a lender's
        credit line | StateRegulator |"

        PRD: "A well-authenticated request whose role is not listed as authorized
        for the endpoint it addresses is rejected with `ERR_UNAUTHORIZED` (HTTP
        403)."

        PRD: "A newly registered party starts with `committed_advance_cents` at
        zero and therefore `available_credit_cents` equal to its credit line."

        PRD: "A lender's credit line may later be restated by a regulator, which
        recomputes `available_credit_cents` and increments the party's `version` by
        one."

        Design: Corner/rbac/warehouse_operator_cannot_restate_a_lender_credit_line
        """
        warehouse = licensed_warehouse()
        lender = new_lender()

        response = api.patch_party_credit_line(
            lender["id"],
            f.credit_line_payload(99_000_000),
            make_warehouse_operator_headers(warehouse["id"]),
        )

        validate_error(response, E.ERR_UNAUTHORIZED, 403)

        current = get_success_data(api.get_party(lender["id"], REGULATOR_HEADERS), 200)
        assert_fields_equal(
            current,
            {
                "credit_line_cents": 50_000_000,
                "available_credit_cents": 50_000_000,
                "version": lender["version"],
            },
        )


class TestPerfectionIsTheLendersAlone:
    def test_the_pledgor_cannot_perfect_the_lien_over_its_own_receipt(
        self, api, base_full, set_clock, request_lien
    ):
        """
        The depositor is the pledgor and has every commercial interest in the
        advance closing, but perfection is the lender's act: the request stays in
        REQUESTED, the receipt stays unencumbered, and — since recording a request
        commits nothing — the lender's exposure is still zero.

        PRD: "| POST | `/collateral-liens/{lien_id}/perfect` | Perfect the
        lender's interest | Lender |"

        PRD: "A well-authenticated request whose role is not listed as authorized
        for the endpoint it addresses is rejected with `ERR_UNAUTHORIZED` (HTTP
        403)."

        PRD: "Recording the request captures `pledgor_party_id` from the receipt's
        current `holder_party_id`, so that release can later restore possession to
        whoever gave it up, and the lien lands in `lien_state` `REQUESTED` with
        `perfected_at`, `released_at` and `payoff_received_cents` all null."

        PRD: "**No credit is committed at this point** — recording a request costs
        the lender nothing against its line."

        PRD: "The collateral dimension, `encumbrance_state`, starts at
        `UNENCUMBERED`, cycles through `PLEDGED` and `RELEASED`, and has no
        terminal state at all — a released receipt can be pledged again."

        Design: Corner/rbac/depositor_cannot_perfect_a_lien_on_its_own_receipt
        """
        set_clock(CLOCK_DAY_16)
        lien = request_lien(base_full["receipt_id"], base_full["lender_id"])

        response = api.perfect_lien(
            lien["id"],
            f.perfect_payload(attestation_note="pledgor attests"),
            base_full["depositor_headers"],
        )

        validate_error(response, E.ERR_UNAUTHORIZED, 403)

        current_lien = get_success_data(
            api.get_collateral_lien(lien["id"], REGULATOR_HEADERS), 200
        )
        assert current_lien["lien_state"] == "REQUESTED"

        receipt = get_success_data(
            api.get_receipt(base_full["receipt_id"], REGULATOR_HEADERS), 200
        )
        assert receipt["encumbrance_state"] == "UNENCUMBERED"

        lender = get_success_data(
            api.get_party(base_full["lender_id"], REGULATOR_HEADERS), 200
        )
        assert lender["committed_advance_cents"] == 0


class TestExaminationIndependence:
    def test_the_licensing_regulator_is_barred_but_a_second_one_is_not(
        self, api, licensed_warehouse, submitted_report
    ):
        """
        Both callers are `StateRegulator`s, so the role gate cannot separate them —
        this bar is per user. reg-001 signed this licence and is recorded in
        `licensed_by_user_id`, so its examination is refused; the identical request
        from reg-002 is admitted and passes the report.

        PRD: "The server records it — as `licensed_by_user_id` on a `Warehouse`
        when a licensing decision is made, as `examined_by_user_id` on a
        `PositionReport` when an examination result is recorded, and as
        `adjudicated_by_user_id` on an `IndemnityClaim` when a claim is decided —
        but it is never compared to any entity's `id`."

        PRD: "It is admissible only from `UNDER_EXAMINATION`, and it is subject to
        **examination independence**: the examining regulator's `X-User-ID` must
        differ from the `licensed_by_user_id` recorded on the warehouse."

        PRD: "A regulator may not examine a facility whose licence that same
        regulator issued or denied, and an attempt to do so is refused with
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 403); a second regulator identity must
        record the result."

        PRD: "Every examination records `examination_result`,
        `examined_by_user_id` and `findings_note`, and increments the warehouse's
        `version` by one whenever the warehouse row is touched."

        PRD: "`PASS` moves the report to `ACCEPTED` and does nothing further."

        Design: Corner/rbac/licensing_regulator_cannot_examine_its_own_warehouses_report
        """
        warehouse = licensed_warehouse()
        report = submitted_report(warehouse["id"], 900, 0)
        assert report["report_state"] == "UNDER_EXAMINATION"
        assert warehouse["licensed_by_user_id"] == REGULATOR_USER_ID

        refused = api.examine_position_report(
            report["id"],
            f.examine_report_payload("PASS", findings_note="same regulator"),
            REGULATOR_HEADERS,
        )

        validate_error(refused, E.ERR_SEGREGATION_OF_DUTIES, 403)

        examined = get_success_data(
            api.examine_position_report(
                report["id"],
                f.examine_report_payload(
                    "PASS", findings_note="independent examiner"
                ),
                SECOND_REGULATOR_HEADERS,
            ),
            200,
        )

        assert_fields_equal(
            examined,
            {
                "examination_result": "PASS",
                "report_state": "ACCEPTED",
                "examined_by_user_id": SECOND_REGULATOR_USER_ID,
                "findings_note": "independent examiner",
            },
        )


class TestSingleReceiptReadsAreOwnershipGuarded:
    @pytest.fixture
    def two_producers(self, base_full, new_producer):
        """WR-0001 held by Ada Farms, with an unrelated producer Bo Farms beside it."""
        stranger = new_producer(name="Bo Farms")
        return {"scenario": base_full, "stranger_id": stranger["id"]}

    def test_a_stranger_depositor_is_refused_the_row_its_peer_may_read(
        self, api, two_producers
    ):
        """
        `Depositor` is a listed role on the single-receipt read, so the role gate
        lets Bo Farms through — and the ownership gate then stops it, because the
        holder is Ada Farms. The very same read by Ada Farms returns the row.

        PRD: "When `X-User-Role` is `Depositor`, `X-User-ID` is the `id` of the
        acting `Party`. Ownership checks compare it either to the addressed
        `StorageAgreement`'s depositor reference or to the addressed receipt's
        current holder reference."

        PRD: "A caller whose role is authorized for the endpoint but whose
        entity-backed identity does not match the addressed row is rejected with
        `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

        PRD: "This ownership rule guards every write and every single-resource
        read across warehouses, bins, storage agreements, deposit tickets,
        receipts, collateral liens, position reports and delivery orders."

        Design: Corner/rbac/depositor_cannot_read_a_receipt_it_does_not_hold
        """
        scenario = two_producers["scenario"]

        refused = api.get_receipt(
            scenario["receipt_id"],
            make_depositor_headers(two_producers["stranger_id"]),
        )

        validate_error(refused, E.ERR_NOT_RESOURCE_OWNER, 403)

        allowed = get_success_data(
            api.get_receipt(scenario["receipt_id"], scenario["depositor_headers"]), 200
        )
        assert_fields_equal(
            allowed,
            {
                "receipt_number": "WR-0001",
                "holder_party_id": scenario["depositor_id"],
            },
        )


class TestLienWriteOwnershipIsReadFromTheBody:
    def test_a_lender_cannot_name_another_lender_on_its_own_request(
        self, api, base_full, new_lender, set_clock
    ):
        """
        Nothing in the path identifies the lender here — the ownership test has to
        read `lender_party_id` out of the body. Thin Bank naming AgCredit Bank is
        refused before any valuation runs, so no lien exists on the receipt and
        neither lender has committed a cent.

        PRD: "When `X-User-Role` is `Lender`, `X-User-ID` is the `id` of the acting
        `Party`. Every lien write requires the lien's lender reference to equal
        `X-User-ID`."

        PRD: "A caller whose role is authorized for the endpoint but whose
        entity-backed identity does not match the addressed row is rejected with
        `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

        PRD: "A newly registered party starts with `committed_advance_cents` at
        zero and therefore `available_credit_cents` equal to its credit line."

        Design: Corner/rbac/lender_cannot_create_a_lien_naming_another_lender
        """
        stranger = new_lender(name="Thin Bank", credit_line_cents=100_000)
        set_clock(CLOCK_DAY_16)

        response = api.create_collateral_lien(
            f.collateral_lien_payload(
                base_full["receipt_id"], base_full["lender_id"]
            ),
            make_lender_headers(stranger["id"]),
        )

        validate_error(response, E.ERR_NOT_RESOURCE_OWNER, 403)

        rows, meta = validate_paginated(
            api.list_collateral_liens(
                {"receipt_id": base_full["receipt_id"]}, REGULATOR_HEADERS
            )
        )
        assert rows == []
        assert meta["total_count"] == 0

        named = get_success_data(
            api.get_party(base_full["lender_id"], REGULATOR_HEADERS), 200
        )
        assert named["committed_advance_cents"] == 0

        caller = get_success_data(
            api.get_party(stranger["id"], REGULATOR_HEADERS), 200
        )
        assert caller["committed_advance_cents"] == 0


class TestRegistryAdministratorSharedOperations:
    def test_it_registers_a_counterparty_and_moves_the_electronic_receipt(
        self, api, base_full
    ):
        """
        The two things the registry administrator may actually do, in sequence: it
        registers the transferee, then moves the electronic receipt to it on the
        `REGISTRY` channel that no other role may use. One record lands in the
        transfer log, and the receipt's lifecycle state is untouched by the change
        of hands.

        PRD: "| POST | `/parties` | Register a depositor or lender counterparty |
        StateRegulator, RegistryAdministrator |"

        PRD: "An `ELECTRONIC` receipt is transferred only by a
        `RegistryAdministrator` with `transfer_channel` `REGISTRY`, and only at a
        registry-participating warehouse."

        PRD: "A successful transfer moves `holder_party_id` to `to_party_id` and
        appends one record to `transfer_log` — an append-only, chronologically
        ordered array of objects each carrying `transfer_channel`,
        `from_party_id`, `to_party_id` and `effective_at`."

        PRD: "The lifecycle dimension, `receipt_state`, starts at `ISSUED` and has
        two terminal states, `CANCELLED` and `VOIDED`."

        Design: Corner/rbac/registry_administrator_shared_operations_succeed
        """
        transferee = get_success_data(
            api.create_party(
                f.commercial_depositor_payload(name="Cargo Trading Co"),
                REGISTRY_ADMIN_HEADERS,
            ),
            201,
        )
        assert transferee["party_kind"] == "COMMERCIAL_DEPOSITOR"

        get_success_data(
            api.transfer_receipt(
                base_full["receipt_id"],
                f.transfer_payload(transferee["id"], "REGISTRY"),
                REGISTRY_ADMIN_HEADERS,
            ),
            200,
        )

        receipt = get_success_data(
            api.get_receipt(base_full["receipt_id"], REGULATOR_HEADERS), 200
        )
        assert_fields_equal(
            receipt,
            {
                "holder_party_id": transferee["id"],
                "receipt_state": "ISSUED",
            },
        )
        assert len(receipt["transfer_log"]) == 1
        assert_fields_equal(
            receipt["transfer_log"][0],
            {
                "transfer_channel": "REGISTRY",
                "from_party_id": base_full["depositor_id"],
                "to_party_id": transferee["id"],
            },
        )


class TestLenderRevaluesItsOwnPerfectedLien:
    @pytest.fixture
    def perfected_at_four_fifty(self, base_full, set_clock, perfected_lien):
        """
        A 949-bushel US_NO_1 receipt pledged at 450 cents a bushel, perfected on
        the sixteenth inclusive storage day, committing 290482 cents of the
        lender's line.
        """
        set_clock(CLOCK_DAY_16)
        lien = perfected_lien(
            base_full["receipt_id"],
            base_full["lender_id"],
            mark_price_cents_per_bushel=450,
        )
        assert lien["advance_limit_cents"] == 290482
        return {"lien_id": lien["id"], "scenario": base_full}

    def test_the_re_mark_re_runs_all_seven_valuation_steps(
        self, api, perfected_at_four_fifty
    ):
        """
        Marking 949 bushels down from 450 to 400 cents grosses 379600, and US_NO_1
        attracts no grade discount, so that is the eligible value too. The quarter
        point fee on it is exactly 949, which joins the 5314 of provisional storage
        that sixteen days have accrued and the fixed 5694 receiving charge in an
        11957-cent prior lien. What is left, 367643, is far below the
        hundred-thousand-dollar tier, so seventy percent of it — 257350.1, rounded
        down to 257350 — is the new limit, still comfortably above the 250000
        principal.

        PRD: "`gross_value_cents` is the receipt's outstanding `quantity_bushels`
        multiplied by a price."

        PRD: "`eligible_value_cents` is the gross value reduced by the discount —
        the gross value multiplied by the complement of `grade_discount_bps` within
        ten thousand, divided by ten thousand — rounded half up to whole cents."

        PRD: "`admin_fee_cents` is 25 basis points, one quarter of one percent, of
        the **eligible** value from step 3, rounded half up to whole cents."

        PRD: "`warehouseman_lien_cents` is the sum of the receipt's
        `provisional_storage_charge_cents`, its `receiving_charge_cents` and the
        `admin_fee_cents` from step 4."

        PRD: "`advance_rate_bps` is 8000 basis points (eighty percent) when
        `net_collateral_cents` is at least 10,000,000 cents — one hundred thousand
        dollars — and 7000 basis points (seventy percent) otherwise."

        PRD: "`advance_limit_cents` is `net_collateral_cents` multiplied by
        `advance_rate_bps` and divided by ten thousand, rounded half up to whole
        cents."

        PRD: "`margin_deficiency_cents` is the amount by which `principal_cents`
        exceeds that limit, floored at zero, and `margin_status` is `SUFFICIENT`
        when the deficiency is exactly zero and `DEFICIENT` otherwise."

        PRD: "**Revaluation** re-marks a lien at a new
        `mark_price_cents_per_bushel`, re-runs the seven steps, and rewrites
        `advance_limit_cents`, `margin_deficiency_cents` and `margin_status`."

        Design: Corner/rbac/lender_revalues_its_own_perfected_lien_and_credit_moves_by_the_delta
        """
        scenario = perfected_at_four_fifty["scenario"]

        revalued = get_success_data(
            api.revalue_lien(
                perfected_at_four_fifty["lien_id"],
                f.revalue_payload(400),
                scenario["lender_headers"],
            ),
            200,
        )

        assert_fields_equal(
            revalued,
            {
                "lien_state": "PERFECTED",
                "eligible_value_cents": 379_600,
                "admin_fee_cents": 949,
                "warehouseman_lien_cents": 11_957,
                "net_collateral_cents": 367_643,
                "advance_rate_bps": 7000,
                "advance_limit_cents": 257_350,
                "margin_status": "SUFFICIENT",
            },
        )

    def test_the_lenders_committed_exposure_tracks_the_new_mark(
        self, api, perfected_at_four_fifty
    ):
        """
        The lien was already perfected when the mark moved, so the lender's
        committed exposure follows it down from 290482 to the new 257350 limit —
        a delta of 33132 cents handed straight back to the available line.

        PRD: "On a lien that is already `PERFECTED`, it also adjusts the lender's
        `committed_advance_cents` by the difference between the new and the old
        advance limit, so the lender's committed exposure tracks the mark."

        PRD: "`committed_advance_cents` is the sum of `advance_limit_cents` across
        every lien naming this party as lender whose `lien_state` is `PERFECTED`."

        PRD: "`available_credit_cents` is `credit_line_cents` less that committed
        advance — the conserved quantity of the perfect-and-release pair described
        in §3.6."

        Design: Corner/rbac/lender_revalues_its_own_perfected_lien_and_credit_moves_by_the_delta
        """
        scenario = perfected_at_four_fifty["scenario"]

        get_success_data(
            api.revalue_lien(
                perfected_at_four_fifty["lien_id"],
                f.revalue_payload(400),
                scenario["lender_headers"],
            ),
            200,
        )

        lender = get_success_data(
            api.get_party(scenario["lender_id"], REGULATOR_HEADERS), 200
        )
        assert_fields_equal(
            lender,
            {
                "committed_advance_cents": 257_350,
                "available_credit_cents": 49_742_650,
            },
        )
