"""Supplier lifecycle, quality agreements, and clock-driven expiry."""
from test_helpers import (
    ApiErrorId,
    add_component,
    create_agreement,
    create_lot,
    create_part,
    create_qualified_supplier,
    create_supplier,
    create_validated_stack,
    get_lot,
    get_part,
    get_supplier,
    set_clock,
    sqe,
    validate_error,
    validate_success,
    api_client,
)


class TestSupplierQualifyRequiresActiveAgreement:
    def test_qualify_rejected_with_only_draft_agreement(self, api):
        """PRD section 3.4: "With an `ACTIVE` agreement in place, a
        `SupplierQualityEngineer` qualifies the supplier: `PENDING_QUALIFICATION`
        to `QUALIFIED` is refused without one (`ERR_NO_ACTIVE_QUALITY_AGREEMENT`)."

        Design: Difficulty/cross_entity_state_dependency/supplier_qualify_requires_active_agreement
        """
        supplier = create_supplier("SUP-X1", "Xone")
        create_agreement(supplier, agreement_code="QA-X1")
        resp = api.qualify_supplier(supplier["id"], sqe())
        validate_error(resp, ApiErrorId.ERR_NO_ACTIVE_QUALITY_AGREEMENT)
        current = get_supplier(supplier["id"])
        assert current["status"] == "PENDING_QUALIFICATION"

    def test_qualify_succeeds_after_agreement_activation(self, api):
        """PRD section 3.4: "Activation moves an agreement from `DRAFT` to
        `ACTIVE`" and "With an `ACTIVE` agreement in place, a
        `SupplierQualityEngineer` qualifies the supplier".

        Design: Difficulty/cross_entity_state_dependency/supplier_qualify_requires_active_agreement
        """
        supplier = create_supplier("SUP-X1", "Xone")
        agreement = create_agreement(supplier, agreement_code="QA-X1")
        validate_success(api.activate_agreement(agreement["id"], sqe()))
        qualified = validate_success(api.qualify_supplier(supplier["id"], sqe()))
        assert qualified["status"] == "QUALIFIED"


class TestAgreementGates:
    def test_agreement_activate_outside_window_rejected(self, api):
        """PRD section 3.4: "Activation moves an agreement from `DRAFT` to
        `ACTIVE` and enforces its temporal window: now must be at or after
        `effective_from` and strictly before `effective_to`
        (`ERR_AGREEMENT_NOT_IN_EFFECT`)".

        Design: Corner/endpoints/agreement_activate_outside_window_rejected
        """
        supplier = create_supplier("SUP-AW", "AW Co")
        agreement = create_agreement(
            supplier,
            agreement_code="QA-AW",
            effective_from="2026-09-01T00:00:00Z",
            effective_to="2027-09-01T00:00:00Z",
        )
        resp = api.activate_agreement(agreement["id"], sqe())
        validate_error(resp, ApiErrorId.ERR_AGREEMENT_NOT_IN_EFFECT)
        current = validate_success(api.get_agreement(agreement["id"], sqe()))
        assert current["status"] == "DRAFT"
        assert get_supplier(supplier["id"])["status"] == "PENDING_QUALIFICATION"


def _suspended_setup(prefix, agreement_to="2027-07-01T00:00:00Z"):
    """Validated stack + qualified supplier (single ACTIVE agreement) + part +
    IN_PRODUCTION lot with that component."""
    stack = create_validated_stack(prefix)
    qs = create_qualified_supplier(
        f"SUP-{prefix.removeprefix('DEV-')}", f"{prefix} Co", effective_to=agreement_to
    )
    part = create_part(
        qs["supplier"]["id"], f"PN-{prefix.removeprefix('DEV-')}", receive_qty=100
    )
    lot = create_lot(
        f"LT-{prefix.removeprefix('DEV-')}", stack["dmr"]["id"], stack["protocol"]["id"]
    )
    add_component(lot["id"], part["id"], quantity_used=10, supplier_lot_number=f"SL-{prefix}")
    return stack, qs, part, lot


class TestSupplierSuspensionCascades:
    def test_agreement_terminate_suspends_supplier_cascade(self, api):
        """PRD section 3.4: "Termination moves an `ACTIVE` agreement to
        `TERMINATED`, and when that leaves the supplier with no `ACTIVE`
        agreement while the supplier is `QUALIFIED`, the supplier is suspended on
        the spot with the full cascade below" — "every `QUALIFIED` part of the
        supplier moves to `ON_HOLD`, and every lot in `IN_PRODUCTION` or
        `COMPLETED` whose recorded components include any of those parts is
        placed `ON_HOLD` with `hold_reason` `SUPPLIER_QUALITY`."

        Design: Corner/endpoints/agreement_terminate_suspends_supplier_cascade
        """
        _stack, qs, part, lot = _suspended_setup("DEV-TM")
        terminated = validate_success(api.terminate_agreement(qs["agreement"]["id"], sqe()))
        assert terminated["status"] == "TERMINATED"
        assert get_supplier(qs["supplier"]["id"])["status"] == "SUSPENDED"
        assert get_part(part["id"])["status"] == "ON_HOLD"
        held = get_lot(lot["id"])
        assert held["hold_status"] == "ON_HOLD"
        assert held["hold_reason"] == "SUPPLIER_QUALITY"

    def test_clock_sweep_expires_agreement_suspends_supplier(self, api):
        """PRD section 2.5: "Every quality agreement in `ACTIVE` whose
        `effective_to` has been reached or passed (that is, now is at or after
        `effective_to`) transitions to `EXPIRED`. When that leaves a `QUALIFIED`
        supplier with no remaining `ACTIVE` agreement, the supplier is suspended
        with the full part-and-lot cascade described in §3.4."

        Design: Corner/endpoints/clock_sweep_expires_agreement_suspends_supplier
        """
        _stack, qs, part, lot = _suspended_setup("DEV-CS", agreement_to="2026-09-01T00:00:00Z")
        set_clock("2026-09-01T00:00:00Z")

        agreement = validate_success(api.get_agreement(qs["agreement"]["id"], sqe()))
        assert agreement["status"] == "EXPIRED"
        assert get_supplier(qs["supplier"]["id"])["status"] == "SUSPENDED"
        assert get_part(part["id"])["status"] == "ON_HOLD"
        held = get_lot(lot["id"])
        assert held["hold_status"] == "ON_HOLD"
        assert held["hold_reason"] == "SUPPLIER_QUALITY"


class TestSupplierTerminalLockdown:
    def test_supplier_terminal_disqualified_lockdown(self, api):
        """PRD section 3.4: "Disqualification is terminal. From `QUALIFIED` or
        `SUSPENDED`, a `SupplierQualityEngineer` may disqualify a supplier: every
        part of the supplier in `QUALIFIED` or `ON_HOLD` becomes `DISQUALIFIED`,
        in-flight lots containing those parts are held `SUPPLIER_QUALITY`, and
        any `ACTIVE` quality agreement of the supplier is `TERMINATED`." — and
        PRD section 2.10 step 7: "terminal states accept nothing
        (`ERR_INVALID_STATE_TRANSITION`)".

        Design: Corner/state_machines/supplier_terminal_disqualified_lockdown
        """
        _stack, qs, part, lot = _suspended_setup("DEV-TL")
        disqualified = validate_success(api.disqualify_supplier(qs["supplier"]["id"], sqe()))
        assert disqualified["status"] == "DISQUALIFIED"
        assert get_part(part["id"])["status"] == "DISQUALIFIED"
        agreement = validate_success(api.get_agreement(qs["agreement"]["id"], sqe()))
        assert agreement["status"] == "TERMINATED"
        held = get_lot(lot["id"])
        assert held["hold_status"] == "ON_HOLD"
        assert held["hold_reason"] == "SUPPLIER_QUALITY"

        resp = api.reinstate_supplier(qs["supplier"]["id"], sqe())
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
