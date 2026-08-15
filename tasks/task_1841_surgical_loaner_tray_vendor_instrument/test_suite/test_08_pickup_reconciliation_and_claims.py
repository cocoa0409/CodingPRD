"""Post-case pickup, reconciliation with segregation of duties, automatic
shortage/damage claims, and claim adjudication (apportion, dispute, settle)."""
from test_helpers import (
    COORD_1,
    COORD_2,
    ApiErrorId,
    assert_damage_loss_claim,
    check_in,
    coordinator,
    create_pickup,
    get_success_data,
    list_claims_of_request,
    reconcile,
    rep_headers,
    setup_approved_request,
    setup_auto_loss_claim,
    setup_case_completed_world,
    validate_error,
    validate_success,
    verify,
)
from test_helpers.factories import (
    apportion_claim_payload,
    create_claim_payload,
    dispute_claim_payload,
    dispute_pickup_payload,
    line_disposition,
    pickup_line,
)


def _claims_by_tray(request_id):
    return {c["tray_id"]: c for c in list_claims_of_request(request_id)}


def _quarantined_tray_world(api):
    """Standard world whose single tray was quarantined at verification."""
    world = setup_approved_request(priority_class="STANDARD",
                                   case_start="2026-08-05T09:00:00Z",
                                   case_end="2026-08-05T12:00:00Z")
    tray = world["trays"][0]
    ci = check_in(world)
    verify(world, ci,
           dispositions=[line_disposition(tray["id"], "QUARANTINE")],
           verifier_id=COORD_1)
    assert validate_success(
        api.get_tray(tray["id"], coordinator()))["status"] == "QUARANTINED"
    return world, tray


class TestPickupAndReconcile:
    def test_pickup_dispute_then_reconcile(self, api):
        """PRD: "Before reconciliation, the vendor's rep may dispute the
        pickup — moving it from `SUBMITTED` to `DISPUTED`, with an optional
        `reason` — provided the caller is a rep of the request's vendor, else
        `ERR_REP_VENDOR_MISMATCH`."
        PRD: "the pickup must be `SUBMITTED` or `DISPUTED` (else
        `ERR_PICKUP_INVALID_STATE` at 409)"

        Design: Corner/state_machines/pickup_dispute_then_reconcile
        """
        world = setup_case_completed_world()
        tray = world["trays"][0]
        pickup = create_pickup(world, [pickup_line(tray["id"], 50, "OK")])
        assert pickup["status"] == "SUBMITTED"

        disputed = validate_success(
            api.dispute_pickup(pickup["id"],
                               dispute_pickup_payload("counts contested"),
                               rep_headers(world["rep"])))
        assert disputed["status"] == "DISPUTED"

        reconciled = reconcile(world, pickup["id"], reconciler_id=COORD_2)
        assert reconciled["status"] == "RECONCILED", \
            "reconcile is accepted from DISPUTED"
        assert reconciled["discrepancy_count"] == 0
        tray_after = validate_success(api.get_tray(tray["id"], coordinator()))
        assert tray_after["status"] == "RECONCILED"
        request_after = validate_success(
            api.get_request(world["request"]["id"], coordinator()))
        assert request_after["status"] == "CLOSED"

    def test_pickup_reconcile_twice_rejected(self, api):
        """PRD: "the pickup must be `SUBMITTED` or `DISPUTED` (else
        `ERR_PICKUP_INVALID_STATE` at 409)"

        Design: Corner/state_machines/pickup_reconcile_twice_rejected
        """
        world = setup_case_completed_world()
        tray = world["trays"][0]
        pickup = create_pickup(world, [pickup_line(tray["id"], 49, "OK")])
        reconcile(world, pickup["id"], reconciler_id=COORD_2)
        assert len(list_claims_of_request(world["request"]["id"])) == 1

        resp = api.reconcile_pickup(pickup["id"], coordinator("coord-3"))
        validate_error(resp, ApiErrorId.ERR_PICKUP_INVALID_STATE)
        assert len(list_claims_of_request(world["request"]["id"])) == 1, \
            "a rejected re-reconcile must not duplicate auto-claims"

    def test_pickup_returned_count_exceeds_delivered_rejected(self, api):
        """PRD: "Every line's tray must belong to the path request
        (`ERR_TRAY_NOT_IN_REQUEST` at 422 otherwise) and must be
        `AWAITING_PICKUP`, else `ERR_TRAY_INVALID_STATE` (409); a line may not
        return more instruments than were verified at check-in —
        `instrument_count_returned` greater than the tray's
        `delivered_instrument_count` fails with
        `ERR_PICKUP_COUNT_EXCEEDS_DELIVERED` (422)."

        Design: Corner/validations/pickup_returned_count_exceeds_delivered_rejected
        """
        world = setup_case_completed_world()
        tray = world["trays"][0]
        # 51 returned against 50 verified at check-in: rejected.
        resp = api.create_pickup(
            world["request"]["id"],
            {"lines": [pickup_line(tray["id"], 51, "OK")]},
            rep_headers(world["rep"]))
        validate_error(resp, ApiErrorId.ERR_PICKUP_COUNT_EXCEEDS_DELIVERED)
        assert validate_success(
            api.get_tray(tray["id"], coordinator()))["status"] == "AWAITING_PICKUP"

        # Exactly the delivered count is the inclusive upper bound: accepted.
        pickup = validate_success(
            api.create_pickup(
                world["request"]["id"],
                {"lines": [pickup_line(tray["id"], 50, "OK")]},
                rep_headers(world["rep"])), 201)
        assert pickup["status"] == "SUBMITTED"
        assert validate_success(
            api.get_tray(tray["id"], coordinator()))["status"] == "PICKED_UP"

    def test_sod_reconcile_same_user_rejected(self, api):
        """PRD: "That same identifier is thereafter barred from two settlement
        operations on the same request: reconciling any pickup of that
        request, and waiving any amount on the penalty that the check-in's
        late delivery created. Either attempt is rejected with
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."
        PRD: "the reconciling coordinator's `X-User-ID` must differ from the
        `verified_by_user_id` of every `VERIFIED` or `PARTIALLY_VERIFIED`
        check-in on the same request, else `ERR_SEGREGATION_OF_DUTIES` (403)."

        Design: Corner/validations/sod_reconcile_same_user_rejected
        """
        # The check-in was verified by coord-1.
        world = setup_case_completed_world(verifier_id=COORD_1)
        tray = world["trays"][0]
        pickup = create_pickup(world, [pickup_line(tray["id"], 50, "OK")])

        resp = api.reconcile_pickup(pickup["id"], coordinator(COORD_1))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

        reconciled = reconcile(world, pickup["id"], reconciler_id=COORD_2)
        assert reconciled["status"] == "RECONCILED"
        assert reconciled["reconciled_by_user_id"] == COORD_2


class TestManualClaims:
    def test_manual_claim_zero_amount_rejected(self, api):
        """PRD: "Claims can also be filed manually by a `VendorCoordinator`,
        naming the `tray_id` the claim is filed against, the `request_id` —
        which must agree with the tray's own request, since the claim's
        request linkage is denormalized from its tray — a `damage_type` of
        `LOSS`, `DAMAGE`, or `CONTAMINATION`, and a `claimed_amount_cents`
        that must be greater than zero. A non-positive amount, or a claim
        against a tray that is not in a claim-eligible state — the tray must
        be `PICKED_UP`, `RECONCILED`, or `QUARANTINED` — is rejected with
        `ERR_CLAIM_AMOUNT_INVALID` (422)."
        PRD: "`provisional_vendor_share_cents` is the full claimed amount for
        a `LOSS`, half the claimed amount rounded half up for a `DAMAGE`, and
        zero for a `CONTAMINATION`."

        Design: Corner/validations/manual_claim_zero_amount_rejected
        """
        world, tray = _quarantined_tray_world(api)
        resp = api.create_claim(
            create_claim_payload(tray["id"], world["request"]["id"],
                                 "DAMAGE", 0),
            coordinator())
        validate_error(resp, ApiErrorId.ERR_CLAIM_AMOUNT_INVALID)

        claim = validate_success(
            api.create_claim(
                create_claim_payload(tray["id"], world["request"]["id"],
                                     "DAMAGE", 50000),
                coordinator()), 201)
        assert_damage_loss_claim(claim)
        assert claim["status"] == "FILED"
        assert claim["provisional_vendor_share_cents"] == 25000, \
            "DAMAGE presumptive share is half of 50000"

    def test_claim_dispute_before_apportion_rejected(self, api):
        """PRD: "a claim in any other state cannot be settled, apportioned, or
        disputed, and such attempts fail with `ERR_CLAIM_INVALID_STATE`
        (409)."

        Design: Corner/validations/claim_dispute_before_apportion_rejected
        """
        world, tray = _quarantined_tray_world(api)
        claim = get_success_data(
            api.create_claim(
                create_claim_payload(tray["id"], world["request"]["id"],
                                     "DAMAGE", 50000),
                coordinator()), 201)
        resp = api.dispute_claim(claim["id"],
                                 dispute_claim_payload("premature"),
                                 rep_headers(world["rep"]))
        validate_error(resp, ApiErrorId.ERR_CLAIM_INVALID_STATE)
        assert validate_success(
            api.get_claim(claim["id"], coordinator()))["status"] == "FILED"

    def test_claim_apportion_percent_out_of_range_rejected(self, api):
        """PRD: "The percent must lie between 0 and 100 inclusive, else
        `ERR_CLAIM_APPORTION_INVALID` (422)."
        PRD: "Apportionment moves a claim from `FILED` to `APPORTIONED`,
        computes `final_vendor_share_cents` as the claimed amount multiplied
        by the percent and divided by one hundred, rounded half up to whole
        cents, and sets `final_hospital_share_cents` to the remainder — the
        claimed amount minus the vendor share — so the two always sum to the
        claim."

        Design: Corner/validations/claim_apportion_percent_out_of_range_rejected
        """
        world, tray = _quarantined_tray_world(api)
        claim = get_success_data(
            api.create_claim(
                create_claim_payload(tray["id"], world["request"]["id"],
                                     "DAMAGE", 50000),
                coordinator()), 201)

        resp = api.apportion_claim(
            claim["id"],
            apportion_claim_payload(101, claim["version"]),
            coordinator())
        validate_error(resp, ApiErrorId.ERR_CLAIM_APPORTION_INVALID)
        assert validate_success(
            api.get_claim(claim["id"], coordinator()))["status"] == "FILED"

        # 100 is inside the inclusive bound: the hospital share is zero.
        apportioned = validate_success(
            api.apportion_claim(
                claim["id"],
                apportion_claim_payload(100, claim["version"]),
                coordinator()))
        assert apportioned["status"] == "APPORTIONED"
        assert apportioned["final_vendor_share_cents"] == 50000
        assert apportioned["final_hospital_share_cents"] == 0


class TestClaimAdjudication:
    def test_claim_settle_clears_liability_rollup(self, api):
        """PRD: "settling an `APPORTIONED` claim moves it to terminal
        `SETTLED` and subtracts its final vendor share from the liability
        rollup; a claim in any other state cannot be settled, apportioned, or
        disputed, and such attempts fail with `ERR_CLAIM_INVALID_STATE`
        (409)."
        PRD: "`outstanding_liability_cents` is the sum of
        `final_vendor_share_cents` over exactly that vendor's damage and loss
        claims whose status is `APPORTIONED`."

        Design: Corner/state_machines/claim_settle_clears_liability_rollup
        """
        world, claim = setup_auto_loss_claim(returned=47)
        apportioned = validate_success(
            api.apportion_claim(claim["id"],
                                apportion_claim_payload(60, claim["version"]),
                                coordinator()))
        assert apportioned["final_vendor_share_cents"] == 10800

        settled = validate_success(api.settle_claim(claim["id"], coordinator()))
        assert settled["status"] == "SETTLED"
        vendor = validate_success(api.get_vendor(world["vendor"]["id"],
                                                 coordinator()))
        assert vendor["outstanding_liability_cents"] == 0

        resp = api.settle_claim(claim["id"], coordinator())
        validate_error(resp, ApiErrorId.ERR_CLAIM_INVALID_STATE)

    def test_claim_apportion_stale_version_returns_412(self, api):
        """PRD: "An apportion request must carry `expected_claim_version`
        equal to the claim's current `version`."
        PRD: "Apportionment legitimately supersedes a prior apportionment —
        for example re-adjudication after a dispute — and moves money on the
        vendor's liability rollup, so a stale writer would double-move the
        rollup; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/complexity_layers/claim_apportion_stale_version_returns_412
        """
        _world, claim = setup_auto_loss_claim(returned=47)
        current_version = claim["version"]

        resp = api.apportion_claim(
            claim["id"],
            apportion_claim_payload(60, current_version - 1),
            coordinator())
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        assert validate_success(
            api.get_claim(claim["id"], coordinator()))["status"] == "FILED"

        apportioned = validate_success(
            api.apportion_claim(
                claim["id"],
                apportion_claim_payload(60, current_version),
                coordinator()))
        assert apportioned["status"] == "APPORTIONED"
        assert apportioned["final_vendor_share_cents"] == 10800


class TestShortageClaimRounding:
    """Difficulty instance: per-line round-half-up before summing."""

    def _two_tray_shortage_world(self):
        """Two trays (declared 8 each, value 100 each) delivered complete,
        used, and returned 5/8 and 3/8."""
        world = setup_case_completed_world(
            tray_specs=[
                dict(tray_code="TK-1", declared_instrument_count=8,
                     replacement_value_cents=100),
                dict(tray_code="TK-2", declared_instrument_count=8,
                     replacement_value_cents=100),
            ])
        t1, t2 = world["trays"]
        pickup = create_pickup(world, [pickup_line(t1["id"], 5, "OK"),
                                       pickup_line(t2["id"], 3, "OK")])
        reconcile(world, pickup["id"], reconciler_id=COORD_2)
        return world, t1, t2

    def test_shortage_claims_round_half_up_per_line(self, api):
        """PRD: "A line whose `shortage_count` is greater than zero
        auto-creates a claim in `FILED` with `damage_type` `LOSS`, whose
        `claimed_amount_cents` is the tray's `replacement_value_cents`
        multiplied by the shortage and divided by the tray's
        `declared_instrument_count`, rounded half up to whole cents."
        PRD: "All monetary amounts in this system are integer cents — never
        floats, never strings — and all division of money rounds half up to
        the nearest cent."

        Design: Difficulty/combinatorial_formula/reconciliation_shortage_per_line_rounding
        """
        world, t1, t2 = self._two_tray_shortage_world()
        claims = _claims_by_tray(world["request"]["id"])
        assert set(claims) == {t1["id"], t2["id"]}
        # round_half_up(100 * 3 / 8) = round_half_up(37.5) = 38.
        assert claims[t1["id"]]["claimed_amount_cents"] == 38
        assert claims[t1["id"]]["damage_type"] == "LOSS"
        # round_half_up(100 * 5 / 8) = round_half_up(62.5) = 63.
        assert claims[t2["id"]]["claimed_amount_cents"] == 63
        assert claims[t2["id"]]["damage_type"] == "LOSS"
        for claim in claims.values():
            assert claim["status"] == "FILED"

    def test_shortage_claims_sum_differs_from_round_once(self, api):
        """PRD: "Two kinds of automatic claims are filed from these lines, and
        the rounding order is pinned: each line is valued and rounded first,
        and the request-level claimed total is the sum of the per-line amounts
        — converting the total shortage and rounding once is non-conformant."

        Design: Difficulty/combinatorial_formula/reconciliation_shortage_per_line_rounding
        """
        world, t1, t2 = self._two_tray_shortage_world()
        claims = _claims_by_tray(world["request"]["id"])
        total = sum(c["claimed_amount_cents"] for c in claims.values())
        assert total == 101, \
            "38 + 63: rounding after summing (100.0 -> 100) is non-conformant"

        t1_after = validate_success(api.get_tray(t1["id"], coordinator()))
        t2_after = validate_success(api.get_tray(t2["id"], coordinator()))
        assert t1_after["shortage_count"] == 3
        assert t2_after["shortage_count"] == 5


class TestInstrumentConservation:
    """Difficulty instance: delivered == returned + shortage, exactly."""

    def _conservation_world(self):
        """Trays delivered 50 and 7, returned 47 and 5."""
        world = setup_case_completed_world(
            tray_specs=[
                dict(tray_code="TK-1", declared_instrument_count=50,
                     replacement_value_cents=300000),
                dict(tray_code="TK-2", declared_instrument_count=7,
                     replacement_value_cents=7000),
            ])
        t1, t2 = world["trays"]
        pickup = create_pickup(world, [pickup_line(t1["id"], 47, "OK"),
                                       pickup_line(t2["id"], 5, "OK")])
        reconciled = reconcile(world, pickup["id"], reconciler_id=COORD_2)
        return world, t1, t2, reconciled

    def test_instrument_count_conservation_per_tray(self, api):
        """PRD: "Each tray's `shortage_count` is computed as its
        `delivered_instrument_count` minus its `returned_instrument_count`,
        and the tray moves from `PICKED_UP` to terminal `RECONCILED`."

        Design: Difficulty/compensating_invariant/instrument_count_conservation_across_reconciliation
        """
        _world, t1, t2, _pk = self._conservation_world()
        t1_after = validate_success(api.get_tray(t1["id"], coordinator()))
        t2_after = validate_success(api.get_tray(t2["id"], coordinator()))
        assert t1_after["status"] == "RECONCILED"
        assert t2_after["status"] == "RECONCILED"
        # 50 == 47 + 3 and 7 == 5 + 2: conservation holds exactly per tray.
        assert t1_after["delivered_instrument_count"] == 50
        assert t1_after["returned_instrument_count"] == 47
        assert t1_after["shortage_count"] == 3
        assert t2_after["delivered_instrument_count"] == 7
        assert t2_after["returned_instrument_count"] == 5
        assert t2_after["shortage_count"] == 2
        assert (t1_after["delivered_instrument_count"]
                + t2_after["delivered_instrument_count"]) == 57
        assert (t1_after["returned_instrument_count"]
                + t2_after["returned_instrument_count"]
                + t1_after["shortage_count"]
                + t2_after["shortage_count"]) == 57

    def test_instrument_conservation_claims_and_request_closure(self, api):
        """PRD: "A line whose `shortage_count` is greater than zero
        auto-creates a claim in `FILED` with `damage_type` `LOSS`, whose
        `claimed_amount_cents` is the tray's `replacement_value_cents`
        multiplied by the shortage and divided by the tray's
        `declared_instrument_count`, rounded half up to whole cents."
        PRD: "The pickup's `discrepancy_count` counts its lines that have a
        shortage greater than zero or a `DAMAGED` condition."
        PRD: "when a pickup reconciliation leaves every tray of a request in a
        terminal state (`RECONCILED` or `CANCELLED`) and the linked case is
        `COMPLETED`, the request bubbles up from `APPROVED` to `CLOSED` and
        its `version` increments."

        Design: Difficulty/compensating_invariant/instrument_count_conservation_across_reconciliation
        """
        world, t1, t2, reconciled = self._conservation_world()
        claims = _claims_by_tray(world["request"]["id"])
        # 300000 * 3 / 50 = 18000; 7000 * 2 / 7 = 2000.
        assert claims[t1["id"]]["claimed_amount_cents"] == 18000
        assert claims[t2["id"]]["claimed_amount_cents"] == 2000
        assert reconciled["discrepancy_count"] == 2

        request_after = validate_success(
            api.get_request(world["request"]["id"], coordinator()))
        assert request_after["status"] == "CLOSED", \
            "all trays terminal and the case COMPLETED: the request closes"


class TestLiabilityVariants:
    """Difficulty instance: provisional presumption vs adjudicated final
    share on identical claim data."""

    def test_liability_provisional_presumption_on_filing(self, api):
        """PRD: "Every claim, manual or automatic, receives a `claim_seq` —
        its 1-based creation order within its request — and a presumptive
        vendor share computed at filing: `provisional_vendor_share_cents` is
        the full claimed amount for a `LOSS`, half the claimed amount rounded
        half up for a `DAMAGE`, and zero for a `CONTAMINATION`."
        PRD: "A line whose `shortage_count` is greater than zero auto-creates
        a claim in `FILED` with `damage_type` `LOSS`, whose
        `claimed_amount_cents` is the tray's `replacement_value_cents`
        multiplied by the shortage and divided by the tray's
        `declared_instrument_count`, rounded half up to whole cents."

        Design: Difficulty/dual_variant_calc/liability_provisional_vs_final_on_identical_claim
        """
        _world, claim = setup_auto_loss_claim(returned=47, declared=50,
                                              value=300000)
        assert_damage_loss_claim(claim)
        assert claim["status"] == "FILED"
        # 47 of 50 returned: shortage 3; round_half_up(300000 * 3 / 50).
        assert claim["claimed_amount_cents"] == 18000
        assert claim["damage_type"] == "LOSS"
        assert claim["provisional_vendor_share_cents"] == 18000, \
            "LOSS presumption is 100% of the claimed amount"
        assert claim["final_vendor_share_cents"] is None
        assert claim["final_hospital_share_cents"] is None

    def test_liability_final_apportionment_diverges_from_provisional(self, api):
        """PRD: "Apportionment moves a claim from `FILED` to `APPORTIONED`,
        computes `final_vendor_share_cents` as the claimed amount multiplied
        by the percent and divided by one hundred, rounded half up to whole
        cents, and sets `final_hospital_share_cents` to the remainder — the
        claimed amount minus the vendor share — so the two always sum to the
        claim."
        PRD: "`outstanding_liability_cents` is the sum of
        `final_vendor_share_cents` over exactly that vendor's damage and loss
        claims whose status is `APPORTIONED`."

        Design: Difficulty/dual_variant_calc/liability_provisional_vs_final_on_identical_claim
        """
        world, claim = setup_auto_loss_claim(returned=47, declared=50,
                                             value=300000)
        apportioned = validate_success(
            api.apportion_claim(claim["id"],
                                apportion_claim_payload(60, claim["version"]),
                                coordinator()))
        assert apportioned["status"] == "APPORTIONED"
        # round_half_up(18000 * 60 / 100) = 10800; the hospital takes the rest.
        assert apportioned["final_vendor_share_cents"] == 10800
        assert apportioned["final_hospital_share_cents"] == 7200
        assert apportioned["provisional_vendor_share_cents"] == 18000, \
            "the stored provisional presumption survives adjudication"
        assert apportioned["final_vendor_share_cents"] != \
            apportioned["provisional_vendor_share_cents"]

        vendor = validate_success(api.get_vendor(world["vendor"]["id"],
                                                 coordinator()))
        assert vendor["outstanding_liability_cents"] == 10800


class TestClaimDisputeCycle:
    """Difficulty instance: APPORTIONED -> DISPUTED -> APPORTIONED with the
    liability rollup tracking each hop."""

    def test_claim_dispute_removes_share_from_rollup(self, api):
        """PRD: "disputing an `APPORTIONED` claim moves it to `DISPUTED`,
        subtracts the final vendor share back off the liability rollup, and
        requires the caller to be a rep of the claim request's vendor, else
        `ERR_REP_VENDOR_MISMATCH`"

        Design: Difficulty/non_linear_state_machine/claim_dispute_reapportion_occ_cycle
        """
        world, claim = setup_auto_loss_claim(returned=47)
        apportioned = validate_success(
            api.apportion_claim(claim["id"],
                                apportion_claim_payload(60, claim["version"]),
                                coordinator()))
        assert apportioned["version"] == claim["version"] + 1
        vendor = validate_success(api.get_vendor(world["vendor"]["id"],
                                                 coordinator()))
        assert vendor["outstanding_liability_cents"] == 10800

        disputed = validate_success(
            api.dispute_claim(claim["id"],
                              dispute_claim_payload(
                                  "counts were verified at check-in"),
                              rep_headers(world["rep"])))
        assert disputed["status"] == "DISPUTED"
        vendor = validate_success(api.get_vendor(world["vendor"]["id"],
                                                 coordinator()))
        assert vendor["outstanding_liability_cents"] == 0, \
            "DISPUTED claims are excluded from the liability rollup"

    def test_claim_reapportion_after_dispute_computes_new_shares(self, api):
        """PRD: "A disputed claim can be apportioned again under the same OCC
        and percent guards, recomputing the final shares from the new percent
        and adding the new vendor share back onto the rollup — the same claim
        data under a different percent yields different cents than the
        provisional presumption."

        Design: Difficulty/non_linear_state_machine/claim_dispute_reapportion_occ_cycle
        """
        world, claim = setup_auto_loss_claim(returned=47)
        v1 = claim["version"]
        apportioned = validate_success(
            api.apportion_claim(claim["id"],
                                apportion_claim_payload(60, v1),
                                coordinator()))
        v2 = apportioned["version"]
        assert v2 == v1 + 1, "apportion increments the claim version"
        disputed = get_success_data(
            api.dispute_claim(claim["id"],
                              dispute_claim_payload(
                                  "counts were verified at check-in"),
                              rep_headers(world["rep"])))
        # The dispute itself modifies the claim, so the version increments
        # again; re-apportionment must carry the post-dispute version.
        v3 = disputed["version"]
        assert v3 == v2 + 1, "dispute increments the claim version"

        reapportioned = validate_success(
            api.apportion_claim(claim["id"],
                                apportion_claim_payload(50, v3),
                                coordinator()))
        assert reapportioned["status"] == "APPORTIONED"
        assert reapportioned["version"] == v3 + 1
        # Same claim data, new percent: round_half_up(18000 * 50 / 100).
        assert reapportioned["final_vendor_share_cents"] == 9000
        assert reapportioned["final_hospital_share_cents"] == 9000
        vendor = validate_success(api.get_vendor(world["vendor"]["id"],
                                                 coordinator()))
        assert vendor["outstanding_liability_cents"] == 9000
