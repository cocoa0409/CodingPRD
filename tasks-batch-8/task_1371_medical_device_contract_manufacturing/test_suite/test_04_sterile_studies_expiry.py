"""Sterile-barrier studies and the shelf-life expiry ladder."""
from test_helpers import (
    ApiErrorId,
    assert_instant_equal,
    complete_study,
    create_approved_dmr,
    create_lot,
    create_protocol,
    create_study,
    create_validated_stack,
    get_lot,
    qe,
    qm,
    validate_error,
    validate_success,
    api_client,
)


class TestLotExpiryProvisionalVsFinal:
    def _setup(self):
        stack = create_validated_stack("DEV-E1", claim_months=20)
        lot = create_lot(
            "LT-E1", stack["dmr"]["id"], stack["protocol"]["id"],
            quantity=10, manufactured_at="2026-08-02T00:00:00Z",
        )
        return stack, lot

    def test_provisional_variant_before_study_passes(self, api):
        """PRD section 3.2: "While the lot's DMR has no `PASSED` study, the
        **provisional** variant applies: the expiry month count is half of
        `shelf_life_claim_months` rounded up to a whole month, capped at twelve
        months, and the lot's `expiry_basis` is `PROVISIONAL`." — claim 20 yields
        10 months on a 2026-08-02 manufacture date.

        Design: Difficulty/dual_variant_calc/lot_expiry_provisional_vs_final
        """
        _stack, lot = self._setup()
        assert lot["expiry_basis"] == "PROVISIONAL"
        assert_instant_equal(lot["expiry_date"], "2027-06-02T00:00:00Z", "expiry_date")

    def test_final_variant_recomputed_when_study_passes(self, api):
        """PRD section 3.2: "Once a study has passed, the **final** variant
        applies: the month count is `confirmed_shelf_life_months` capped at sixty
        months, and the basis is `FINAL`." and "the DMR's
        `confirmed_shelf_life_months` is set to `result_months_confirmed`, and the
        expiry of every lot of that DMR still in `IN_PRODUCTION` or `COMPLETED` is
        recomputed under the final variant below, flipping each such lot's
        `expiry_basis` to `FINAL`."

        Design: Difficulty/dual_variant_calc/lot_expiry_provisional_vs_final
        """
        stack, lot = self._setup()
        study = create_study(stack["dmr"]["id"], study_type="ACCELERATED", claimed_months=20)
        complete_study(study["id"], passed=True, result_months_confirmed=24)

        reloaded_lot = get_lot(lot["id"])
        assert reloaded_lot["expiry_basis"] == "FINAL"
        assert_instant_equal(
            reloaded_lot["expiry_date"], "2028-08-02T00:00:00Z", "recomputed expiry_date"
        )
        reloaded_dmr = validate_success(api.get_dmr(stack["dmr"]["id"], qm()))
        assert reloaded_dmr["confirmed_shelf_life_months"] == 24


class TestStudyConstraints:
    def test_second_active_study_per_dmr_rejected(self, api):
        """PRD section 3.2: "At most one study may be `IN_PROGRESS` per DMR at a
        time; a second attempt is refused with `ERR_STUDY_ALREADY_ACTIVE`." and
        "`PASSED`, `FAILED`, and `INVALIDATED` are all terminal."

        Design: Corner/entities/study_second_active_per_dmr_rejected
        """
        from test_helpers import create_study_payload

        dmr = create_approved_dmr(device_code="DEV-ST")
        study1 = create_study(dmr["id"], study_type="ACCELERATED", claimed_months=20)

        resp = api.create_study(
            create_study_payload(dmr["id"], study_type="REAL_TIME", claimed_months=24), qe()
        )
        validate_error(resp, ApiErrorId.ERR_STUDY_ALREADY_ACTIVE)

        complete_study(study1["id"], passed=False)
        study2 = validate_success(
            api.create_study(
                create_study_payload(dmr["id"], study_type="REAL_TIME", claimed_months=24), qe()
            ),
            expected_status=201,
        )
        assert study2["status"] == "IN_PROGRESS"

    def test_study_on_non_sterile_dmr_rejected(self, api):
        """PRD section 3.2: "The target revision must be `APPROVED`
        (`ERR_DMR_NOT_APPROVED`) and must be a sterile device — a study against a
        non-sterile DMR is rejected with `ERR_DMR_NOT_STERILE`."

        Design: Corner/entities/study_on_non_sterile_dmr_rejected
        """
        from test_helpers import create_study_payload

        dmr = create_approved_dmr(device_code="DEV-NS", sterile=False)
        resp = api.create_study(
            create_study_payload(dmr["id"], study_type="REAL_TIME", claimed_months=20), qe()
        )
        validate_error(resp, ApiErrorId.ERR_DMR_NOT_STERILE)
