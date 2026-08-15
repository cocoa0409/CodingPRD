"""Invoice lifecycle guards: state gates, segregation of duties, the
contract cap, and validation-order precedence (PRD 2.9, 3.6)."""
from test_helpers import (
    LM,
    LM2,
    ApiErrorId,
    create_facility,
    create_invoice,
    create_manifest,
    create_stock,
    make_manifest,
    read_invoice,
    reconcile_manifest,
    return_manifest,
    setup_provisional_invoice,
    setup_unit_with_collection,
    validate_error,
    validate_success,
)


def _setup_invoice_over_returned_manifest(cap=None):
    """Manifest (16.00 lbs, 8 expected, 7 returned) in RETURNED status plus a
    PROVISIONAL invoice over it created by lm-1. Optional facility cap."""
    facility_overrides = {}
    if cap is not None:
        facility_overrides["monthly_cap_cents"] = cap
    ctx = setup_unit_with_collection(
        soiled_pieces=8, facility_overrides=facility_overrides
    )
    manifest = make_manifest(ctx, [ctx["collect_run"]["id"]], 16.00)
    ctx["manifest"] = return_manifest(
        manifest["id"],
        [{"stock_id": ctx["stock"]["id"], "pieces": 7, "condemned_pieces": 0}],
    )
    ctx["invoice"] = create_invoice(
        ctx["facility"]["id"], [ctx["manifest"]["id"]]
    )
    return ctx


def test_settle_provisional_invoice_rejected(api, linen_manager_headers):
    """PRD 3.6: "From `FINALIZED`, a `LaundryVendor` may dispute the invoice —
    moving it to `DISPUTED` with an optional `reason` — and a `LinenManager`
    may record payment, moving it to `SETTLED`, which is terminal."
    PRD 2.9: "Seventh, state guards — the resource must be in a valid
    from-state for the requested transition (`ERR_INVALID_STATE`, or
    `ERR_ALREADY_TERMINAL` when the resource is already in a terminal state),
    unit-clerk ownership (`ERR_UNIT_OWNERSHIP`), surge-posture blocks
    (`ERR_FACILITY_IN_SURGE`), and invoice-creation manifest status."

    Design: Corner/state_machines/settle_provisional_invoice_rejected
    """
    ctx = _setup_invoice_over_returned_manifest()
    res = api.settle_invoice(ctx["invoice"]["id"], linen_manager_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)
    assert read_invoice(ctx["invoice"]["id"])["status"] == "PROVISIONAL"


def test_invoice_over_dispatched_manifest_rejected(api, linen_manager_headers):
    """PRD 3.6: "Every element of `manifest_ids` must exist and belong to the
    given facility (`ERR_NOT_FOUND`); each referenced manifest must be in
    `RETURNED` or `RECONCILED` status (a manifest in any other status rejects
    creation with `ERR_INVALID_STATE`); and no referenced manifest may already
    belong to another invoice (`ERR_MANIFEST_ALREADY_INVOICED`)."

    Design: Corner/validations/invoice_over_dispatched_manifest_rejected
    """
    facility = create_facility()
    stock = create_stock(facility["id"])
    manifest = create_manifest(
        facility["id"],
        [],
        [{"stock_id": stock["id"], "weight_lbs": 16.00,
          "isolation_flag": False}],
    )
    res = api.create_invoice(
        {
            "facility_id": facility["id"],
            "manifest_ids": [manifest["id"]],
            "period_start": "2026-08-01T00:00:00Z",
            "period_end": "2026-08-07T00:00:00Z",
            "period_adjusted_patient_days": 50,
        },
        linen_manager_headers,
    )
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)


def test_manifest_already_invoiced_returns_conflict(api, linen_manager_headers):
    """PRD 3.6: "Every element of `manifest_ids` must exist and belong to the
    given facility (`ERR_NOT_FOUND`); each referenced manifest must be in
    `RETURNED` or `RECONCILED` status (a manifest in any other status rejects
    creation with `ERR_INVALID_STATE`); and no referenced manifest may already
    belong to another invoice (`ERR_MANIFEST_ALREADY_INVOICED`)."

    Design: Corner/validations/manifest_already_invoiced_returns_conflict
    """
    ctx = _setup_invoice_over_returned_manifest()
    res = api.create_invoice(
        {
            "facility_id": ctx["facility"]["id"],
            "manifest_ids": [ctx["manifest"]["id"]],
            "period_start": "2026-08-08T00:00:00Z",
            "period_end": "2026-08-14T00:00:00Z",
            "period_adjusted_patient_days": 50,
        },
        linen_manager_headers,
    )
    validate_error(res, ApiErrorId.ERR_MANIFEST_ALREADY_INVOICED)


def test_cap_exceeded_at_finalize_returns_contract_cap(api):
    """PRD 3.6: "It is permitted from `PROVISIONAL` and again from `DISPUTED`,
    but three guards apply first: segregation of duties requires the
    finalizing user's `X-User-ID` to differ from `created_by_user_id`
    (`ERR_SEGREGATION_OF_DUTIES`); every linked manifest must be `RECONCILED`
    (`ERR_MANIFEST_NOT_RECONCILED`); and when the facility's
    `monthly_cap_cents` is set, the computed final total must not exceed it
    (`ERR_CONTRACT_CAP_EXCEEDED`)."

    Design: Corner/validations/cap_exceeded_at_finalize_returns_contract_cap
    """
    ctx = setup_provisional_invoice(facility_overrides={"monthly_cap_cents": 500})
    res = api.finalize_invoice(ctx["invoice"]["id"], LM2)
    # 7 returned x 80 cents per-piece rate = 560 > cap 500.
    validate_error(res, ApiErrorId.ERR_CONTRACT_CAP_EXCEEDED)
    assert read_invoice(ctx["invoice"]["id"])["status"] == "PROVISIONAL"


def test_cap_absent_allows_finalize(api):
    """PRD 3.1: "and optionally `monthly_cap_cents`, a contract cap on a
    single invoice's final total — when omitted it is null and no cap is
    enforced."

    Design: Corner/validations/cap_absent_allows_finalize
    """
    ctx = setup_provisional_invoice()
    finalized = validate_success(
        api.finalize_invoice(ctx["invoice"]["id"], LM2), 200
    )
    assert finalized["status"] == "FINALIZED"
    assert finalized["final_total_cents"] == 560, (
        f"7 returned x 80 cents per-piece rate = 560, got "
        f"{finalized['final_total_cents']}"
    )


def test_vendor_cannot_finalize_invoice(api, laundry_vendor_headers):
    """PRD 2.1: "Access to each operation is restricted by role as enumerated
    in §4; an attempt to perform an operation outside the caller's role is
    rejected with `ERR_UNAUTHORIZED_ROLE`."

    Design: Corner/validations/vendor_cannot_finalize_invoice_returns_unauthorized
    """
    ctx = _setup_invoice_over_returned_manifest()
    res = api.finalize_invoice(ctx["invoice"]["id"], laundry_vendor_headers)
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
    assert read_invoice(ctx["invoice"]["id"])["status"] == "PROVISIONAL"


def test_same_user_finalize_returns_segregation_of_duties(api):
    """PRD 2.1: "Two further role-adjacent rules exist: a `UnitClerk` acting
    on a resource belonging to a different unit is rejected with
    `ERR_UNIT_OWNERSHIP`, and invoice finalization attempted by the same user
    who created the invoice is rejected with `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/validations/same_user_finalize_returns_segregation_of_duties
    """
    ctx = _setup_invoice_over_returned_manifest()
    res = api.finalize_invoice(ctx["invoice"]["id"], LM)  # creator lm-1
    validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
    assert read_invoice(ctx["invoice"]["id"])["status"] == "PROVISIONAL"


class TestFinalizeBlockedByUnreconciledManifest:
    """Finalize requires every linked manifest RECONCILED; reconciling the
    manifest clears the gate."""

    def test_finalize_over_returned_manifest_rejected(self, api):
        """PRD 3.6: "It is permitted from `PROVISIONAL` and again from
        `DISPUTED`, but three guards apply first: segregation of duties
        requires the finalizing user's `X-User-ID` to differ from
        `created_by_user_id` (`ERR_SEGREGATION_OF_DUTIES`); every linked
        manifest must be `RECONCILED` (`ERR_MANIFEST_NOT_RECONCILED`); and
        when the facility's `monthly_cap_cents` is set, the computed final
        total must not exceed it (`ERR_CONTRACT_CAP_EXCEEDED`)."

        Design: Difficulty/cross_entity_state_dependency/finalize_blocked_by_unreconciled_manifest
        """
        ctx = _setup_invoice_over_returned_manifest()
        res = api.finalize_invoice(ctx["invoice"]["id"], LM2)
        validate_error(res, ApiErrorId.ERR_MANIFEST_NOT_RECONCILED)
        assert read_invoice(ctx["invoice"]["id"])["status"] == "PROVISIONAL"

    def test_finalize_succeeds_after_manifest_reconcile(self, api):
        """PRD 3.5: "Reconciliation closes the loop. A `LinenManager`
        reconciles a `RETURNED` manifest, moving it to `RECONCILED` — the
        manifest's terminal state."
        PRD 3.6: "It is permitted from `PROVISIONAL` and again from
        `DISPUTED`, but three guards apply first: segregation of duties
        requires the finalizing user's `X-User-ID` to differ from
        `created_by_user_id` (`ERR_SEGREGATION_OF_DUTIES`); every linked
        manifest must be `RECONCILED` (`ERR_MANIFEST_NOT_RECONCILED`); and
        when the facility's `monthly_cap_cents` is set, the computed final
        total must not exceed it (`ERR_CONTRACT_CAP_EXCEEDED`)."

        Design: Difficulty/cross_entity_state_dependency/finalize_blocked_by_unreconciled_manifest
        """
        ctx = _setup_invoice_over_returned_manifest()
        reconcile_manifest(ctx["manifest"]["id"])

        finalized = validate_success(
            api.finalize_invoice(ctx["invoice"]["id"], LM2), 200
        )
        assert finalized["status"] == "FINALIZED"
        assert finalized["final_total_cents"] == 560


class TestStateGuardBeatsFiscalCap:
    """With both an unreconciled manifest and a breached cap, the state
    guard surfaces first (PRD 2.9 ordering)."""

    def test_unreconciled_manifest_beats_cap(self, api):
        """PRD 2.9: "Seventh, state guards — the resource must be in a valid
        from-state for the requested transition (`ERR_INVALID_STATE`, or
        `ERR_ALREADY_TERMINAL` when the resource is already in a terminal
        state), unit-clerk ownership (`ERR_UNIT_OWNERSHIP`), surge-posture
        blocks (`ERR_FACILITY_IN_SURGE`), and invoice-creation manifest
        status."
        PRD 2.9: "Eleventh and last, fiscal and count guards
        (`ERR_COUNT_EXCEEDS_ON_HAND`, `ERR_NEGATIVE_INVENTORY`,
        `ERR_CONTRACT_CAP_EXCEEDED`)."

        Design: Difficulty/priority_pair_validation_conflict/finalize_conflict_state_manifest_beats_fiscal_cap
        """
        ctx = _setup_invoice_over_returned_manifest(cap=500)
        # Final would be 560 > cap 500, and the manifest is only RETURNED.
        res = api.finalize_invoice(ctx["invoice"]["id"], LM2)
        validate_error(res, ApiErrorId.ERR_MANIFEST_NOT_RECONCILED)
        assert read_invoice(ctx["invoice"]["id"])["status"] == "PROVISIONAL"

    def test_cap_surfaces_once_state_guard_passes(self, api):
        """PRD 3.6: "It is permitted from `PROVISIONAL` and again from
        `DISPUTED`, but three guards apply first: segregation of duties
        requires the finalizing user's `X-User-ID` to differ from
        `created_by_user_id` (`ERR_SEGREGATION_OF_DUTIES`); every linked
        manifest must be `RECONCILED` (`ERR_MANIFEST_NOT_RECONCILED`); and
        when the facility's `monthly_cap_cents` is set, the computed final
        total must not exceed it (`ERR_CONTRACT_CAP_EXCEEDED`)."

        Design: Difficulty/priority_pair_validation_conflict/finalize_conflict_state_manifest_beats_fiscal_cap
        """
        ctx = _setup_invoice_over_returned_manifest(cap=500)
        reconcile_manifest(ctx["manifest"]["id"])

        res = api.finalize_invoice(ctx["invoice"]["id"], LM2)
        validate_error(res, ApiErrorId.ERR_CONTRACT_CAP_EXCEEDED)
        assert read_invoice(ctx["invoice"]["id"])["status"] == "PROVISIONAL"
