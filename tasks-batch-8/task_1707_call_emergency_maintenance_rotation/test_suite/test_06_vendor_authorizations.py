"""Vendor authorizations: rounding, layered caps, SoD, invoice settlement."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    authorize_vendor_authorization,
    create_invoice_payload,
    create_ticket,
    create_vendor_authorization_payload,
    create_work_order_payload,
    get_vendor_authorization,
    get_work_order,
    make_supervisor,
    make_supervisor_headers,
    make_technician,
    make_technician_headers,
    make_unit,
    make_vendor,
    make_vendor_headers,
    mitigated_ticket_with_work_order,
    propose_vendor_authorization,
    publish_shift,
    set_clock,
    start_shift,
    validate_error,
    validate_success,
)

TEST_DISPATCHER = TEST_USERS["dispatcher_headers"]


def _setup_ticket_wo_vendor(unit_number, vendor_limit=500000,
                            category="LEAK_MINOR", vendor_name="VendCo"):
    """Mitigated ticket + its auto work order + an ACTIVE vendor + supervisor.

    Returns (tech, sup, unit, vendor, ticket, work_order).
    """
    set_clock("2026-08-03T00:00:00Z")
    tech = make_technician()
    sup = make_supervisor()
    unit = make_unit(unit_number=unit_number)
    vendor = make_vendor(name=vendor_name,
                         per_incident_limit_cents=vendor_limit)
    shift = publish_shift(tech["id"], "2026-08-03T00:00:00Z",
                          "2026-08-03T08:00:00Z")
    start_shift(shift["id"])
    ticket, work_order = mitigated_ticket_with_work_order(
        unit["id"], tech["id"], category,
        dispatch_at="2026-08-03T00:00:00Z",
        arrive_at="2026-08-03T00:00:00Z",
        mitigate_at="2026-08-03T01:00:00Z",
    )
    return tech, sup, unit, vendor, ticket, work_order


class TestInvoiceLineRoundingOrder:
    def _setup_authorized_va(self):
        tech, sup, _unit, vendor, ticket, wo = _setup_ticket_wo_vendor(
            "U-301", vendor_name="Rapid Rooter"
        )
        va = propose_vendor_authorization(ticket["id"], wo["id"], vendor["id"],
                                          20000, tech["id"])
        authorize_vendor_authorization(va["id"], make_supervisor_headers(sup["id"]))
        return vendor, va

    def test_invoice_subtotal_rounds_per_line_before_summing(self, api):
        """PRD §3.6: "Settlement rounds in pinned order: each line total is
        `quantity` times `unit_cost_cents` rounded half-up to whole cents;
        `invoice_subtotal_cents` is the sum of those per-line rounded totals..."
        PRD §2.6: "vendor invoice lines are rounded per line before summing"

        Design: Difficulty/combinatorial_formula/vendor_invoice_line_rounding_order
        """
        vendor, va = self._setup_authorized_va()
        invoiced = validate_success(
            api.invoice_vendor_authorization(
                va["id"],
                create_invoice_payload(lines=[
                    {"description": "labor 1.5h", "quantity": 1.5,
                     "unit_cost_cents": 3333},
                    {"description": "labor 2.5h", "quantity": 2.5,
                     "unit_cost_cents": 3333},
                ], overhead_markup_bp=1000),
                make_vendor_headers(vendor["id"]),
            ),
            200,
        )
        # round_half_up(4999.5) = 5000 and round_half_up(8332.5) = 8333
        assert invoiced["invoice_subtotal_cents"] == 13333, (
            "per-line rounding then sum (sum-then-round would give 13332)"
        )

    def test_invoice_markup_on_rounded_subtotal_and_total(self, api):
        """PRD §3.6: "`invoice_markup_cents` is the rounded subtotal multiplied
        by `overhead_markup_bp` divided by ten thousand, rounded half-up; and
        `invoice_total_cents` is the subtotal plus the markup."
        PRD §3.6: "The invoice is accepted only when `invoice_total_cents` does
        not exceed the authorization's overage ceiling — `amount_cents`
        multiplied by 1.10, rounded half-up — with equality allowed..."

        Design: Difficulty/combinatorial_formula/vendor_invoice_line_rounding_order
        """
        vendor, va = self._setup_authorized_va()
        invoiced = validate_success(
            api.invoice_vendor_authorization(
                va["id"],
                create_invoice_payload(lines=[
                    {"description": "labor 1.5h", "quantity": 1.5,
                     "unit_cost_cents": 3333},
                    {"description": "labor 2.5h", "quantity": 2.5,
                     "unit_cost_cents": 3333},
                ], overhead_markup_bp=1000),
                make_vendor_headers(vendor["id"]),
            ),
            200,
        )
        assert invoiced["invoice_markup_cents"] == 1333, (
            "round_half_up(13333 x 0.10)"
        )
        assert invoiced["invoice_total_cents"] == 14666, "13333 + 1333"
        assert invoiced["status"] == "INVOICED", (
            "14666 <= round_half_up(20000 x 1.10) = 22000 ceiling"
        )


class TestVendorLimitBoundary:
    def _setup(self):
        return _setup_ticket_wo_vendor("U-702", vendor_limit=50000,
                                       vendor_name="CapExact")

    def test_authorize_at_exact_vendor_limit_allowed(self, api):
        """PRD §3.6: "Then the three money caps fire in order, each allowing
        equality: first `amount_cents` must not exceed the vendor's
        `per_incident_limit_cents` (else `ERR_VENDOR_LIMIT_EXCEEDED`)..."
        PRD §3.6: "an actor who is the `requested_by_technician_id` may
        authorize their own request only when `amount_cents` is no more than
        50000 cents ($500.00)..."

        Design: Difficulty/boundary_precision_check/vendor_limit_exact_cap_boundary
        """
        tech, _sup, _unit, _vendor, ticket, wo = self._setup()
        va1 = propose_vendor_authorization(ticket["id"], wo["id"],
                                           _vendor["id"], 50000, tech["id"])
        authorized = validate_success(
            api.authorize_vendor_authorization(
                va1["id"], make_technician_headers(tech["id"])
            ),
            200,
        )
        assert authorized["status"] == "AUTHORIZED", (
            "50000 == vendor cap is inclusive; self-authorization at exactly "
            "the 50000 self cap is also allowed"
        )

    def test_authorize_one_cent_over_vendor_limit_rejected(self, api):
        """PRD §3.6: "first `amount_cents` must not exceed the vendor's
        `per_incident_limit_cents` (else `ERR_VENDOR_LIMIT_EXCEEDED`)..."

        Design: Difficulty/boundary_precision_check/vendor_limit_exact_cap_boundary
        """
        tech, sup, _unit, vendor, ticket, wo = self._setup()
        va2 = propose_vendor_authorization(ticket["id"], wo["id"], vendor["id"],
                                           50001, tech["id"])
        resp = api.authorize_vendor_authorization(
            va2["id"], make_supervisor_headers(sup["id"])
        )
        validate_error(resp, ApiErrorId.ERR_VENDOR_LIMIT_EXCEEDED)
        assert get_vendor_authorization(va2["id"])["status"] == "PROPOSED"


class TestIncidentExposureInvariant:
    def _setup(self):
        tech, sup, unit, vendor, ticket, wo = _setup_ticket_wo_vendor(
            "U-1001", vendor_name="BigJobs"
        )
        va1 = propose_vendor_authorization(ticket["id"], wo["id"], vendor["id"],
                                           30000, tech["id"])
        authorize_vendor_authorization(va1["id"], make_supervisor_headers(sup["id"]))
        va2 = propose_vendor_authorization(ticket["id"], wo["id"], vendor["id"],
                                           20000, tech["id"])
        return tech, sup, unit, vendor, ticket, wo, va1, va2

    def test_void_releases_exposure_proven_by_cap_probe(
        self, api, property_admin_headers
    ):
        """PRD §3.6: "the incident aggregate, the sum of `amount_cents` over
        the ticket's sibling authorizations already in `AUTHORIZED`,
        `INVOICED`, or `PAID` plus this `amount_cents`, must not exceed 500000
        cents ($5,000.00) (else `ERR_INCIDENT_VENDOR_CAP_EXCEEDED`)."
        PRD §3.6: "A manual void moves `AUTHORIZED → VOIDED`..."

        Design: Difficulty/compensating_invariant/vendor_authorize_void_conserves_incident_exposure
        """
        tech, sup, _unit, vendor, ticket, wo, _va1, va2 = self._setup()
        authorize_vendor_authorization(va2["id"], make_supervisor_headers(sup["id"]))
        voided = validate_success(
            api.void_vendor_authorization(va2["id"],
                                          make_supervisor_headers(sup["id"])),
            200,
        )
        assert voided["status"] == "VOIDED"
        # Exposure is back to exactly 30000: 30000 + 470001 > 500000 must fail.
        va3 = propose_vendor_authorization(ticket["id"], wo["id"], vendor["id"],
                                           470001, tech["id"])
        resp = api.authorize_vendor_authorization(va3["id"], property_admin_headers)
        validate_error(resp, ApiErrorId.ERR_INCIDENT_VENDOR_CAP_EXCEEDED)

    def test_incident_cap_inclusive_and_void_keeps_work_order_engaged(
        self, api, property_admin_headers, dispatcher_headers
    ):
        """PRD §3.6: "Then the three money caps fire in order, each allowing
        equality: ... (else `ERR_INCIDENT_VENDOR_CAP_EXCEEDED`)."
        PRD §3.6: "as compensation, the linked work order is released
        `ASSIGNED → OPEN` — but only when no sibling authorization on the same
        work order remains in `AUTHORIZED` or `INVOICED`."

        Design: Difficulty/compensating_invariant/vendor_authorize_void_conserves_incident_exposure
        """
        tech, sup, _unit, vendor, ticket, wo, _va1, va2 = self._setup()
        authorize_vendor_authorization(va2["id"], make_supervisor_headers(sup["id"]))
        validate_success(
            api.void_vendor_authorization(va2["id"],
                                          make_supervisor_headers(sup["id"])),
            200,
        )
        # 30000 + 470000 == 500000 exactly: the inclusive cap admits it.
        va4 = propose_vendor_authorization(ticket["id"], wo["id"], vendor["id"],
                                           470000, tech["id"])
        authorized = validate_success(
            api.authorize_vendor_authorization(va4["id"], property_admin_headers),
            200,
        )
        assert authorized["status"] == "AUTHORIZED"
        assert get_work_order(wo["id"])["status"] == "ASSIGNED", (
            "VA1 remains engaged, so voiding VA2 must not release the order"
        )


def test_invoice_overage_ceiling_exact_vs_exceeded(api, dispatcher_headers):
    """PRD §3.6: "The invoice is accepted only when `invoice_total_cents` does
    not exceed the authorization's overage ceiling — `amount_cents` multiplied
    by 1.10, rounded half-up — with equality allowed; an over-ceiling invoice
    is rejected with `ERR_INVOICE_EXCEEDS_AUTHORIZATION` and nothing is
    recorded."

    Design: Corner/calculations/invoice_overage_ceiling_exact_vs_exceeded
    """
    tech, sup, _unit, vendor, ticket, wo = _setup_ticket_wo_vendor(
        "C-4", vendor_name="CeilTest"
    )
    sup_headers = make_supervisor_headers(sup["id"])
    va1 = propose_vendor_authorization(ticket["id"], wo["id"], vendor["id"],
                                       20000, tech["id"])
    authorize_vendor_authorization(va1["id"], sup_headers)
    va2 = propose_vendor_authorization(ticket["id"], wo["id"], vendor["id"],
                                       20000, tech["id"])
    authorize_vendor_authorization(va2["id"], sup_headers)

    invoiced = validate_success(
        api.invoice_vendor_authorization(
            va1["id"],
            create_invoice_payload(
                lines=[{"description": "job", "quantity": 1,
                        "unit_cost_cents": 20000}],
                overhead_markup_bp=1000,
            ),
            make_vendor_headers(vendor["id"]),
        ),
        200,
    )
    assert invoiced["invoice_total_cents"] == 22000, (
        "20000 + round_half_up(20000 x 0.10) == the exact 1.10x ceiling"
    )
    assert invoiced["status"] == "INVOICED"

    over = api.invoice_vendor_authorization(
        va2["id"],
        create_invoice_payload(
            lines=[{"description": "job", "quantity": 1,
                    "unit_cost_cents": 20001}],
            overhead_markup_bp=1000,
        ),
        make_vendor_headers(vendor["id"]),
    )
    validate_error(over, ApiErrorId.ERR_INVOICE_EXCEEDS_AUTHORIZATION)
    assert get_vendor_authorization(va2["id"])["status"] == "AUTHORIZED", (
        "an over-ceiling invoice records nothing"
    )


def test_role_cap_exceeded_on_supervisor_authorize(api):
    """PRD §3.6: "then `amount_cents` must not exceed the acting role's cap —
    50000 cents for an `OnCallTechnician`, 250000 cents ($2,500.00) for a
    `MaintenanceSupervisor`, and unlimited for a `PropertyAdmin` (else
    `ERR_ROLE_AUTH_LIMIT_EXCEEDED`)..."

    Design: Corner/validations/role_cap_exceeded_on_supervisor_authorize
    """
    tech, sup, _unit, vendor, ticket, wo = _setup_ticket_wo_vendor(
        "M-12", vendor_name="BigJobs"
    )
    va = propose_vendor_authorization(ticket["id"], wo["id"], vendor["id"],
                                      300000, tech["id"])
    resp = api.authorize_vendor_authorization(
        va["id"], make_supervisor_headers(sup["id"])
    )
    validate_error(resp, ApiErrorId.ERR_ROLE_AUTH_LIMIT_EXCEEDED)
    assert get_vendor_authorization(va["id"])["status"] == "PROPOSED"


def test_va_self_authorization_above_cap_rejected(api):
    """PRD §3.6: "The segregation-of-duties check comes before any fiscal cap:
    an actor who is the `requested_by_technician_id` may authorize their own
    request only when `amount_cents` is no more than 50000 cents ($500.00);
    self-authorization above that ceiling is rejected with
    `ERR_SELF_AUTHORIZATION_FORBIDDEN`."

    Design: Corner/rbac/va_self_authorization_above_cap_rejected
    """
    tech, sup, _unit, vendor, ticket, wo = _setup_ticket_wo_vendor(
        "R-4", vendor_name="SelfCo"
    )
    va = propose_vendor_authorization(ticket["id"], wo["id"], vendor["id"],
                                      60000, tech["id"])
    resp = api.authorize_vendor_authorization(
        va["id"], make_technician_headers(tech["id"])
    )
    validate_error(resp, ApiErrorId.ERR_SELF_AUTHORIZATION_FORBIDDEN)

    authorized = validate_success(
        api.authorize_vendor_authorization(
            va["id"], make_supervisor_headers(sup["id"])
        ),
        200,
    )
    assert authorized["status"] == "AUTHORIZED"


def test_vendor_invoice_ownership_enforced(api):
    """PRD §3.6: "The engaged vendor then invoices against the authorization —
    a self action, so `X-User-ID` must equal the authorization's `vendor_id`
    (else `ERR_VENDOR_MISMATCH`), and only from `AUTHORIZED` (else
    `ERR_VENDOR_AUTHORIZATION_INVALID_STATE`)."

    Design: Corner/rbac/vendor_invoice_ownership_enforced
    """
    tech, sup, _unit, vendor, ticket, wo = _setup_ticket_wo_vendor(
        "R-5", vendor_name="RightCo"
    )
    wrong_vendor = make_vendor(name="WrongCo", trade="HVAC",
                               per_incident_limit_cents=100000)
    va = propose_vendor_authorization(ticket["id"], wo["id"], vendor["id"],
                                      20000, tech["id"])
    authorize_vendor_authorization(va["id"], make_supervisor_headers(sup["id"]))

    payload = create_invoice_payload(
        lines=[{"description": "job", "quantity": 1, "unit_cost_cents": 10000}],
        overhead_markup_bp=0,
    )
    wrong = api.invoice_vendor_authorization(
        va["id"], payload, make_vendor_headers(wrong_vendor["id"])
    )
    validate_error(wrong, ApiErrorId.ERR_VENDOR_MISMATCH)
    assert get_vendor_authorization(va["id"])["status"] == "AUTHORIZED"

    invoiced = validate_success(
        api.invoice_vendor_authorization(
            va["id"], payload, make_vendor_headers(vendor["id"])
        ),
        200,
    )
    assert invoiced["status"] == "INVOICED"
    assert invoiced["invoice_total_cents"] == 10000, "zero markup passes through"


def test_vendor_suspended_blocks_proposal(api, property_admin_headers):
    """PRD §3.6: "...a `SUSPENDED` vendor blocks the proposal with
    `ERR_VENDOR_SUSPENDED`."
    PRD §3.1: "suspending one moves it to `SUSPENDED`, increments its
    `version`, and blocks both new spend proposals and authorizations
    involving that vendor with `ERR_VENDOR_SUSPENDED`."

    Design: Corner/validations/vendor_suspended_blocks_proposal
    """
    vendor = make_vendor(name="ShakyCo", trade="GENERAL",
                         per_incident_limit_cents=100000)
    validate_success(api.suspend_vendor(vendor["id"], property_admin_headers), 200)
    tech = make_technician()
    unit = make_unit(unit_number="M-7", building_code="BM")
    ticket = create_ticket(unit["id"], "LEAK_MINOR", description="leak")
    wo = validate_success(
        api.create_work_order(
            create_work_order_payload(call_ticket_id=ticket["id"], title="w",
                                      description="w"),
            TEST_DISPATCHER,
        ),
        201,
    )
    resp = api.create_vendor_authorization(
        ticket["id"],
        create_vendor_authorization_payload(
            work_order_id=wo["id"], vendor_id=vendor["id"], amount_cents=5000
        ),
        make_technician_headers(tech["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_VENDOR_SUSPENDED)


def test_va_work_order_ticket_mismatch_rejected(api, dispatcher_headers):
    """PRD §3.6: "The work order must actually belong to the ticket in the
    path — a mismatch is rejected with `ERR_REFERENTIAL_MISMATCH` (HTTP 422)..."

    Design: Corner/validations/va_work_order_ticket_mismatch_rejected
    """
    unit_a = make_unit(unit_number="M-1", building_code="BM")
    unit_b = make_unit(unit_number="M-2", building_code="BM")
    tech = make_technician()
    vendor = make_vendor(name="Vend", trade="GENERAL",
                         per_incident_limit_cents=100000)
    ticket_a = create_ticket(unit_a["id"], "LEAK_MINOR", description="ticket A")
    ticket_b = create_ticket(unit_b["id"], "LEAK_MINOR", description="ticket B")
    wo_b = validate_success(
        api.create_work_order(
            create_work_order_payload(call_ticket_id=ticket_b["id"],
                                      title="B work",
                                      description="belongs to ticket B"),
            dispatcher_headers,
        ),
        201,
    )
    resp = api.create_vendor_authorization(
        ticket_a["id"],
        create_vendor_authorization_payload(
            work_order_id=wo_b["id"], vendor_id=vendor["id"], amount_cents=1000
        ),
        make_technician_headers(tech["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_REFERENTIAL_MISMATCH)


class TestStatePrecedesFiscalOnAuthorize:
    def _setup_rejected_va(self, api):
        """300000 VA proposed by the technician, then REJECTED by supervisor."""
        tech, sup, _unit, vendor, ticket, wo = _setup_ticket_wo_vendor(
            "U-601", vendor_name="PowerPros"
        )
        va = propose_vendor_authorization(ticket["id"], wo["id"], vendor["id"],
                                          300000, tech["id"])
        validate_success(
            api.reject_vendor_authorization(
                va["id"], {"reason": "Quote too high"},
                make_supervisor_headers(sup["id"]),
            ),
            200,
        )
        return tech, sup, wo, va

    def test_authorize_rejected_authorization_reports_state_error(self, api):
        """PRD §2.9: "When several validations could reject the same request,
        the system evaluates them in a single global order, and the earliest
        failing tier determines the error returned:" — "5. **State and stale
        version** — the target resource must be in a state that permits the
        requested transition (the per-entity invalid-state errors, HTTP
        409)..." precedes "10. **Fiscal caps** — the vendor money limits in
        their pinned order..."
        PRD §3.6: "The authorization must be `PROPOSED` (else
        `ERR_VENDOR_AUTHORIZATION_INVALID_STATE`)."

        Design: Difficulty/priority_pair_validation_conflict/state_precedes_fiscal_on_authorize
        """
        _tech, sup, _wo, va = self._setup_rejected_va(api)
        resp = api.authorize_vendor_authorization(
            va["id"], make_supervisor_headers(sup["id"])
        )
        # 300000 also exceeds the 250000 supervisor cap; state must win.
        validate_error(resp, ApiErrorId.ERR_VENDOR_AUTHORIZATION_INVALID_STATE)

    def test_failed_authorize_with_state_violation_leaves_va_rejected(self, api):
        """PRD §3.6: "Rejection, available to `MaintenanceSupervisor` and
        `PropertyAdmin` with an optional `reason`, moves `PROPOSED → REJECTED`
        and is forbidden to the requesting technician themself
        (`ERR_SEGREGATION_OF_DUTIES`)."
        PRD §3.6: "The authorization must be `PROPOSED` (else
        `ERR_VENDOR_AUTHORIZATION_INVALID_STATE`)."

        Design: Difficulty/priority_pair_validation_conflict/state_precedes_fiscal_on_authorize
        """
        _tech, sup, wo, va = self._setup_rejected_va(api)
        validate_error(
            api.authorize_vendor_authorization(
                va["id"], make_supervisor_headers(sup["id"])
            ),
            ApiErrorId.ERR_VENDOR_AUTHORIZATION_INVALID_STATE,
        )
        assert get_vendor_authorization(va["id"])["status"] == "REJECTED"
        assert get_work_order(wo["id"])["status"] == "OPEN", (
            "no vendor engagement happened"
        )
