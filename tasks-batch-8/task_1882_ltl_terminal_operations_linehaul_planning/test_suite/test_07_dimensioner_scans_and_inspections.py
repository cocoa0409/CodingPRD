"""Dimensioner scans and re-class inspections: GROSS vs DIM rating variants,
the re-inspection cycle, and the reject-path compensation invariant."""
from test_helpers import (
    ApiErrorId,
    TEST_USER_IDS,
    TEST_USERS,
    create_inspection_payload,
    get_success_data,
    make_dimensioner_scan,
    make_rated_shipment,
    make_shipment,
    make_terminal_pair,
    open_inspection,
    set_clock,
    validate_error,
    validate_success,
)

CLERK = TEST_USERS["rating_clerk_headers"]


def _rated_450_class70(origin_id, dest_id):
    """CLASS_70 450 lbs with LIFTGATE+NOTIFY; GROSS-rated to 24725 cents."""
    return make_rated_shipment(
        origin_id, dest_id, nmfc_class="CLASS_70", actual_weight_lbs=450,
        length_in=48, width_in=40, height_in=48, service_standard="STANDARD",
        accessorial_codes=["LIFTGATE", "NOTIFY"])


class TestGrossVsDimDivergence:
    def _setup_through_confirm(self, api):
        origin, dest = make_terminal_pair()
        shipment = _rated_450_class70(origin["id"], dest["id"])
        assert shipment["rated_amount_cents"] == 24725, (
            "GROSS baseline: 11250 + 2475 + 7500 + 3500"
        )
        scan = make_dimensioner_scan(
            shipment["id"], measured_length_in=60, measured_width_in=48,
            measured_height_in=50, measured_weight_lbs=430)
        inspection = open_inspection(shipment["id"], scan["id"], "CLASS_70")
        confirmed = validate_success(
            api.confirm_inspection(inspection["id"], headers=CLERK))
        return shipment, scan, inspection, confirmed

    def test_gross_rating_then_dim_rerate_amounts(self, api):
        """PRD §3.4: "**Confirming** the re-class — legal only while `outcome`
        is `PENDING` — stamps `outcome` `CONFIRMED_RECLASS`, rewrites the
        shipment's `nmfc_class` to the `claimed_nmfc_class`, and re-runs freight
        rating under the DIM variant: the chargeable weight is the larger of
        `measured_weight_lbs` and the ceiling of the measured-dimension product
        over 194, the class rate is the (new) class's tariff, and the line-haul
        → fuel → accessorial pipeline from §3.2 reruns with the same pinned
        rounding order. The shipment's `rated_amount_cents` is replaced by the
        DIM-variant result, `rating_status` advances to `RERATED`, and the
        inspection's `adjustment_cents` records the signed delta — the new rated
        amount minus the rated amount the shipment carried before the inspection
        opened (positive means an upcharge to the shipper)."

        Design: Difficulty/dual_variant_calc/freight_rating_gross_vs_dim_divergence
        """
        shipment, _, inspection, confirmed = self._setup_through_confirm(api)
        assert confirmed["outcome"] == "CONFIRMED_RECLASS"
        # DIM: chargeable = max(430, ceil(144000/194)=743) = 743;
        # linehaul 743/100*2500 = 18575; fuel round(18575*0.22)=4087;
        # accessorials 11000 -> 33662; adjustment 33662 - 24725 = 8937.
        assert confirmed["adjustment_cents"] == 8937
        after = get_success_data(api.get_shipment(shipment["id"], headers=CLERK))
        assert after["rated_amount_cents"] == 33662
        assert after["rating_status"] == "RERATED"

    def test_dim_rerate_weight_basis(self, api):
        """PRD §3.4: "Opening the inspection moves the shipment's `rating_status`
        to `INSPECTION_PENDING` and immediately rebases its weight fields from
        the scan evidence: `dim_weight_lbs` becomes the measured length times
        width times height in inches, divided by the dimensional divisor 194 and
        rounded up to a whole pound; and `chargeable_weight_lbs` becomes the
        larger of the scan's `measured_weight_lbs` and that computed
        `dim_weight_lbs`."

        Design: Difficulty/dual_variant_calc/freight_rating_gross_vs_dim_divergence
        """
        origin, dest = make_terminal_pair()
        shipment = _rated_450_class70(origin["id"], dest["id"])
        scan = make_dimensioner_scan(
            shipment["id"], measured_length_in=60, measured_width_in=48,
            measured_height_in=50, measured_weight_lbs=430)
        inspection = open_inspection(shipment["id"], scan["id"], "CLASS_70")
        assert inspection["outcome"] == "PENDING"
        assert inspection["adjustment_cents"] == 0
        pending = get_success_data(api.get_shipment(shipment["id"],
                                                    headers=CLERK))
        assert pending["rating_status"] == "INSPECTION_PENDING"
        assert pending["dim_weight_lbs"] == 743, "ceil(60*48*50 / 194)"
        assert pending["chargeable_weight_lbs"] == 743, "max(430, 743)"


class TestReinspectionCycle:
    def _setup_rerated(self, api):
        origin, dest = make_terminal_pair()
        shipment = make_rated_shipment(origin["id"], dest["id"],
                                       nmfc_class="CLASS_70",
                                       actual_weight_lbs=450, length_in=48,
                                       width_in=40, height_in=48)
        scan1 = make_dimensioner_scan(
            shipment["id"], measured_length_in=60, measured_width_in=48,
            measured_height_in=50, measured_weight_lbs=430)
        insp1 = open_inspection(shipment["id"], scan1["id"], "CLASS_70")
        validate_success(api.confirm_inspection(insp1["id"], headers=CLERK))
        # Advance the logical clock so the second scan's created_at ordering is
        # newer regardless of which clock the server stamps scans from.
        set_clock("2026-08-01T01:00:00Z")
        scan2 = make_dimensioner_scan(
            shipment["id"], measured_length_in=48, measured_width_in=40,
            measured_height_in=48, measured_weight_lbs=455)
        return shipment, scan2

    def test_rerated_shipment_accepts_fresh_inspection(self, api):
        """PRD §3.4: "A `RERATED` shipment may cycle back to
        `INSPECTION_PENDING` through a fresh inspection with a newer scan,
        repeating the same rebasing side effects; there is no limit on the
        number of cycles."
        PRD §3.4: "First, the shipment's `rating_status` must be `RATED` — or
        `RERATED` for a re-inspection cycle — else `ERR_INVALID_STATE`."

        Design: Difficulty/non_linear_state_machine/shipment_rating_reinspection_cycle
        """
        shipment, scan2 = self._setup_rerated(api)
        insp2 = open_inspection(shipment["id"], scan2["id"], "CLASS_85")
        assert insp2["outcome"] == "PENDING"
        pending = get_success_data(api.get_shipment(shipment["id"],
                                                    headers=CLERK))
        assert pending["rating_status"] == "INSPECTION_PENDING", (
            "the rating axis re-enters INSPECTION_PENDING from RERATED"
        )
        # Same rebasing side effects: ceil(48*40*48/194) = 476; max(455,476)=476.
        assert pending["dim_weight_lbs"] == 476
        assert pending["chargeable_weight_lbs"] == 476

    def test_reject_after_reinspection_restores_declared_basis(self, api):
        """PRD §3.4: "**Rejecting** the inspection — likewise only from `PENDING`
        — stamps `outcome` `REJECTED`, sets `adjustment_cents` to 0, restores
        the shipment's `chargeable_weight_lbs` to the declared
        `actual_weight_lbs`, resets `dim_weight_lbs` to 0, and returns
        `rating_status` to `RATED`."

        Design: Difficulty/non_linear_state_machine/shipment_rating_reinspection_cycle
        """
        shipment, scan2 = self._setup_rerated(api)
        insp2 = open_inspection(shipment["id"], scan2["id"], "CLASS_85")
        rejected = validate_success(api.reject_inspection(insp2["id"],
                                                          headers=CLERK))
        assert rejected["outcome"] == "REJECTED"
        assert rejected["adjustment_cents"] == 0
        after = get_success_data(api.get_shipment(shipment["id"], headers=CLERK))
        assert after["rating_status"] == "RATED", "the reject loop closes"
        assert after["chargeable_weight_lbs"] == 450, (
            "declared basis restored, not the scan's 455/476 values"
        )
        assert after["dim_weight_lbs"] == 0


class TestRejectCompensation:
    def test_open_then_reject_preserves_rating_basis(self, api):
        """PRD §3.4: "**Rejecting** the inspection — likewise only from `PENDING`
        — stamps `outcome` `REJECTED`, sets `adjustment_cents` to 0, restores
        the shipment's `chargeable_weight_lbs` to the declared
        `actual_weight_lbs`, resets `dim_weight_lbs` to 0, and returns
        `rating_status` to `RATED`."

        Design: Difficulty/compensating_invariant/inspection_confirm_reject_preserves_billed_amount
        """
        origin, dest = make_terminal_pair()
        shipment = _rated_450_class70(origin["id"], dest["id"])
        pre_rated = shipment["rated_amount_cents"]
        assert pre_rated == 24725
        scan = make_dimensioner_scan(
            shipment["id"], measured_length_in=60, measured_width_in=48,
            measured_height_in=50, measured_weight_lbs=430)
        inspection = open_inspection(shipment["id"], scan["id"], "CLASS_85")
        rejected = validate_success(
            api.reject_inspection(inspection["id"], headers=CLERK))
        assert rejected["outcome"] == "REJECTED"
        assert rejected["adjustment_cents"] == 0
        after = get_success_data(api.get_shipment(shipment["id"], headers=CLERK))
        assert after["rated_amount_cents"] == pre_rated, (
            "open-then-reject must leave the billed basis byte-identical"
        )
        assert after["nmfc_class"] == "CLASS_70", "class unchanged by a reject"
        assert after["chargeable_weight_lbs"] == 450
        assert after["dim_weight_lbs"] == 0

    def test_resolved_inspection_is_terminal(self, api):
        """PRD §3.4: "**Confirming** the re-class — legal only while `outcome` is
        `PENDING` — stamps `outcome` `CONFIRMED_RECLASS`"
        PRD §3.4: "Both outcomes are terminal for the inspection."
        PRD §2.8: "5. Entity state preconditions for the requested transition
        (e.g. trailer must be `LOADING` to accept a manifest entry, a stop must
        be `ARRIVED` to complete, a leg must be `EN_ROUTE` to arrive) →
        `ERR_INVALID_STATE`."

        Design: Difficulty/compensating_invariant/inspection_confirm_reject_preserves_billed_amount
        """
        origin, dest = make_terminal_pair()
        shipment = _rated_450_class70(origin["id"], dest["id"])
        scan = make_dimensioner_scan(
            shipment["id"], measured_length_in=60, measured_width_in=48,
            measured_height_in=50, measured_weight_lbs=430)
        inspection = open_inspection(shipment["id"], scan["id"], "CLASS_85")
        validate_success(api.reject_inspection(inspection["id"], headers=CLERK))
        resp = api.confirm_inspection(inspection["id"], headers=CLERK)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        resp2 = api.reject_inspection(inspection["id"], headers=CLERK)
        validate_error(resp2, ApiErrorId.ERR_INVALID_STATE)


class TestScanEvidence:
    def test_inspection_scan_must_belong_to_shipment(self, api):
        """PRD §3.4: "Second, the scan named by `scan_id` must belong to this
        shipment; a scan recorded against a different shipment is rejected with
        `ERR_SCAN_SHIPMENT_MISMATCH` (HTTP 422)."

        Design: Corner/validations/error_scan_shipment_mismatch
        """
        origin, dest = make_terminal_pair()
        s_a = make_rated_shipment(origin["id"], dest["id"], nmfc_class="CLASS_70",
                                  actual_weight_lbs=450)
        s_b = make_rated_shipment(origin["id"], dest["id"], nmfc_class="CLASS_70",
                                  actual_weight_lbs=900)
        scan = make_dimensioner_scan(s_a["id"], measured_length_in=60,
                                     measured_width_in=48, measured_height_in=50,
                                     measured_weight_lbs=430)
        resp = api.create_inspection(
            create_inspection_payload(s_b["id"], scan["id"], "CLASS_85"),
            headers=CLERK,
        )
        validate_error(resp, ApiErrorId.ERR_SCAN_SHIPMENT_MISMATCH)

    def test_dimensioner_scan_is_append_only(self, api):
        """PRD §2.4: "Two resource types deliberately omit `updated_at` and
        `version` and carry only `id` and `created_at`: **DimensionerScan** (a
        measurement, once recorded, is an immutable evidentiary fact) and
        **ServiceStandardReport** (a report is a point-in-time snapshot)."
        PRD §3.4: "The scan is append-only: it carries `id` and `created_at` but
        no `updated_at` or `version`, and the server stamps `scanned_by` with
        the clerk's `X-User-ID`."

        Design: Corner/entities/dimensioner_scan_immutable_no_update_endpoint
        """
        origin, dest = make_terminal_pair()
        shipment = make_shipment(origin["id"], dest["id"], nmfc_class="CLASS_70",
                                 actual_weight_lbs=450)
        scan = make_dimensioner_scan(
            shipment["id"], measured_length_in=60, measured_width_in=48,
            measured_height_in=50, measured_weight_lbs=430)
        assert "version" not in scan, "an append-only scan carries no version"
        assert "updated_at" not in scan, "an append-only scan carries no updated_at"
        assert scan["scanned_by"] == TEST_USER_IDS["RatingClerk"], (
            "the acting clerk's X-User-ID is persisted as scanned_by"
        )
        fetched = get_success_data(api.get_dimensioner_scan(scan["id"],
                                                            headers=CLERK))
        assert "version" not in fetched
        assert fetched["scanned_by"] == TEST_USER_IDS["RatingClerk"]
