"""Complaints: conditional adjudication roles, credit routing, rescind
compensation, and unit watch standing (PRD 3.7)."""
from test_helpers import (
    ApiErrorId,
    base_scenario,
    create_complaint,
    create_complaint_payload,
    create_gown_stock,
    create_manifest,
    create_par,
    create_unit,
    fill_unit_to_par,
    make_manifest,
    make_unit_clerk_headers,
    read_complaint,
    read_facility,
    read_invoice,
    read_unit,
    set_clock,
    setup_finalized_invoice,
    setup_unit_with_collection,
    validate_error,
    validate_success,
)


def _setup_isolation_complaint(pieces_affected=3):
    """Manifest with an isolation-flagged gown line plus an OPEN
    ISOLATION_BREACH complaint against it."""
    ctx = base_scenario()
    gown = create_gown_stock(ctx["facility"]["id"])
    create_par(ctx["unit"]["id"], gown["id"], 30, "DAILY")
    ctx["gown"] = gown
    ctx["fill_run"] = fill_unit_to_par(ctx)
    manifest = create_manifest(
        ctx["facility"]["id"],
        [ctx["fill_run"]["id"]],
        [{"stock_id": gown["id"], "weight_lbs": 5.00, "isolation_flag": True}],
        isolation_protocol_ack=True,
    )
    ctx["manifest"] = manifest
    ctx["complaint"] = create_complaint(
        ctx["unit"]["id"], manifest["id"], gown["id"],
        complaint_type="ISOLATION_BREACH", pieces_affected=pieces_affected,
    )
    return ctx


def test_linen_manager_cannot_verify_isolation_breach(api, linen_manager_headers):
    """PRD 3.7: "Adjudication is role-split by complaint type: verifying or
    rejecting an `ISOLATION_BREACH` complaint is reserved for an
    `InfectionControlOfficer`, while all other complaint types are adjudicated
    by a `LinenManager`; the wrong role is rejected with
    `ERR_UNAUTHORIZED_ROLE`."

    Design: Corner/validations/linen_manager_cannot_verify_isolation_breach
    """
    ctx = _setup_isolation_complaint()
    res = api.verify_complaint(ctx["complaint"]["id"], linen_manager_headers)
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
    assert read_complaint(ctx["complaint"]["id"])["status"] == "OPEN"


def test_ico_verifies_isolation_breach_complaint(
    api, infection_control_officer_headers, linen_manager_headers
):
    """PRD 3.7: "Verification moves an `OPEN` complaint to `VERIFIED` and
    prices its credit: `credit_cents` is `pieces_affected` multiplied by the
    stock's per-piece rate computed from the facility's current contracted
    `rate_per_lb_cents` at verify time — deliberately independent of any
    invoice's computed totals, which breaks any circularity between credits
    and billing."
    PRD 3.7: "When the manifest sits on a `SETTLED` invoice or on no invoice
    at all, the facility's `credit_balance_cents` increases instead."

    Design: Corner/validations/ico_verifies_isolation_breach_complaint
    """
    ctx = _setup_isolation_complaint(pieces_affected=3)
    verified = validate_success(
        api.verify_complaint(
            ctx["complaint"]["id"], infection_control_officer_headers
        ),
        200,
    )
    assert verified["status"] == "VERIFIED"
    # per-piece rate: round_half_up(0.50 lbs * 40 c/lb) = 20 c; 3 x 20 = 60.
    assert verified["credit_cents"] == 60, (
        f"3 pieces x 20 cents = 60, got {verified['credit_cents']}"
    )
    facility = read_facility(ctx["facility"]["id"])
    assert facility["credit_balance_cents"] == 60


def test_ico_cannot_verify_stains_complaint(
    api, infection_control_officer_headers
):
    """PRD 3.7: "Adjudication is role-split by complaint type: verifying or
    rejecting an `ISOLATION_BREACH` complaint is reserved for an
    `InfectionControlOfficer`, while all other complaint types are adjudicated
    by a `LinenManager`; the wrong role is rejected with
    `ERR_UNAUTHORIZED_ROLE`."

    Design: Corner/rbac/ico_cannot_verify_stains_complaint
    """
    ctx = base_scenario()
    manifest = make_manifest(ctx, [], 16.00)
    complaint = create_complaint(
        ctx["unit"]["id"], manifest["id"], ctx["stock"]["id"],
        complaint_type="STAINS", pieces_affected=1,
    )
    res = api.verify_complaint(
        complaint["id"], infection_control_officer_headers
    )
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED_ROLE)


def test_verify_rejected_complaint_returns_already_terminal(
    api, linen_manager_headers
):
    """PRD 3.7: "Rejection moves an `OPEN` complaint to `REJECTED` — a
    terminal state — under the same conditional role rule, with an optional
    `reason`."
    PRD 2.9: "Seventh, state guards — the resource must be in a valid
    from-state for the requested transition (`ERR_INVALID_STATE`, or
    `ERR_ALREADY_TERMINAL` when the resource is already in a terminal state),
    unit-clerk ownership (`ERR_UNIT_OWNERSHIP`), surge-posture blocks
    (`ERR_FACILITY_IN_SURGE`), and invoice-creation manifest status."

    Design: Corner/state_machines/verify_rejected_complaint_returns_already_terminal
    """
    ctx = setup_unit_with_collection(soiled_pieces=8)
    manifest = make_manifest(ctx, [ctx["collect_run"]["id"]], 16.00)
    complaint = create_complaint(
        ctx["unit"]["id"], manifest["id"], ctx["stock"]["id"],
        complaint_type="STAINS", pieces_affected=2,
    )
    validate_success(
        api.reject_complaint(complaint["id"], {}, linen_manager_headers), 200
    )

    res = api.verify_complaint(complaint["id"], linen_manager_headers)
    validate_error(res, ApiErrorId.ERR_ALREADY_TERMINAL)


def test_isolation_breach_without_isolation_line_rejected(api):
    """PRD 3.7: "An `ISOLATION_BREACH` complaint additionally requires the
    referenced manifest to contain an isolation-flagged line for the
    referenced stock; without one the filing is rejected with
    `ERR_NO_ISOLATION_LINE`."

    Design: Corner/validations/isolation_breach_without_isolation_line_returns_no_isolation_line
    """
    ctx = setup_unit_with_collection(soiled_pieces=8)
    manifest = make_manifest(ctx, [ctx["collect_run"]["id"]], 16.00)

    res = api.create_complaint(
        create_complaint_payload(
            ctx["unit"]["id"], manifest["id"], ctx["stock"]["id"],
            complaint_type="ISOLATION_BREACH", pieces_affected=1,
        ),
        make_unit_clerk_headers(ctx["unit"]["id"]),
    )
    validate_error(res, ApiErrorId.ERR_NO_ISOLATION_LINE)


def test_clerk_cannot_file_complaint_for_other_unit(api):
    """PRD 3.7: "A `UnitClerk` files a **Complaint** for their own unit — the
    payload's `unit_id` must equal the clerk's `X-User-ID`, or the filing is
    rejected with `ERR_UNIT_OWNERSHIP` — by naming the `manifest_id` and
    `stock_id` the complaint refers to, a `complaint_type` of `STAINS`,
    `TEARS`, `FOREIGN_OBJECT`, `ODOR`, or `ISOLATION_BREACH`, and
    `pieces_affected`, which must be at least one."

    Design: Corner/rbac/clerk_cannot_file_complaint_for_other_unit
    """
    ctx = base_scenario()
    unit2 = create_unit(ctx["facility"]["id"], name="4 West", unit_tier="STANDARD")
    create_par(unit2["id"], ctx["stock"]["id"], 10, "DAILY")
    manifest = make_manifest(ctx, [], 16.00)

    res = api.create_complaint(
        create_complaint_payload(
            unit2["id"], manifest["id"], ctx["stock"]["id"],
            complaint_type="STAINS", pieces_affected=1,
        ),
        make_unit_clerk_headers(ctx["unit"]["id"]),  # clerk of unit 1
    )
    validate_error(res, ApiErrorId.ERR_UNIT_OWNERSHIP)


class TestVerifyRescindRoundTrip:
    """Verify then rescind must leave the routed invoice exactly as it was."""

    def test_verify_prices_and_routes_credit(self, api, linen_manager_headers):
        """PRD 3.7: "When the referenced manifest sits on an invoice that is
        `FINALIZED` or `DISPUTED`, the invoice's `credit_total_cents`
        increases by the credit and its `billed_total_cents` decreases by the
        same amount."
        PRD 3.7: "Either way, `routed_invoice_id` records the invoice
        containing the manifest at verify time, remaining null only when the
        manifest was not yet invoiced."

        Design: Difficulty/compensating_invariant/complaint_verify_rescind_restores_billed_total
        """
        ctx = setup_finalized_invoice()  # final 560, billed 560
        complaint = create_complaint(
            ctx["unit"]["id"], ctx["manifest"]["id"], ctx["stock"]["id"],
            complaint_type="STAINS", pieces_affected=2,
        )
        verified = validate_success(
            api.verify_complaint(complaint["id"], linen_manager_headers), 200
        )
        assert verified["credit_cents"] == 160
        assert verified["routed_invoice_id"] == ctx["invoice"]["id"]

        invoice = read_invoice(ctx["invoice"]["id"])
        assert invoice["credit_total_cents"] == 160
        assert invoice["billed_total_cents"] == 400, (
            f"560 - 160 = 400, got {invoice['billed_total_cents']}"
        )

    def test_rescind_exactly_reverses_the_credit(self, api, linen_manager_headers):
        """PRD 3.7: "A `LinenManager` may rescind a `VERIFIED` complaint,
        moving it to `RESCINDED` and applying the exact compensation of
        verification: if the credit was routed to an invoice, that invoice's
        `credit_total_cents` decreases and its `billed_total_cents` increases
        by the credit amount; otherwise the facility's `credit_balance_cents`
        decreases by the credit amount."

        Design: Difficulty/compensating_invariant/complaint_verify_rescind_restores_billed_total
        """
        ctx = setup_finalized_invoice()
        complaint = create_complaint(
            ctx["unit"]["id"], ctx["manifest"]["id"], ctx["stock"]["id"],
            complaint_type="STAINS", pieces_affected=2,
        )
        validate_success(
            api.verify_complaint(complaint["id"], linen_manager_headers), 200
        )

        rescinded = validate_success(
            api.rescind_complaint(complaint["id"], linen_manager_headers), 200
        )
        assert rescinded["status"] == "RESCINDED"

        invoice = read_invoice(ctx["invoice"]["id"])
        assert invoice["credit_total_cents"] == 0
        assert invoice["billed_total_cents"] == 560, (
            f"rescind must restore billed to exactly 560, got {invoice['billed_total_cents']}"
        )


def test_unit_quality_flag_watch_window(api, linen_manager_headers):
    """PRD 3.7: "A unit's `quality_flag` is `WATCH` whenever the count of that
    unit's complaints in `VERIFIED` or `RESOLVED` status created within the
    trailing 30 days of the logical clock reaches three or more, and `CLEAR`
    otherwise; the flag is evaluated on unit reads and at complaint
    verification."

    Design: Corner/calculations/unit_quality_flag_watch_window_boundary
    """
    ctx = setup_unit_with_collection(soiled_pieces=8)
    manifest = make_manifest(ctx, [ctx["collect_run"]["id"]], 16.00)
    set_clock("2026-08-05T00:00:00Z")

    complaints = [
        create_complaint(
            ctx["unit"]["id"], manifest["id"], ctx["stock"]["id"],
            complaint_type=ctype, pieces_affected=1,
        )
        for ctype in ("STAINS", "TEARS", "ODOR")
    ]
    for complaint in complaints[:2]:
        validate_success(
            api.verify_complaint(complaint["id"], linen_manager_headers), 200
        )
    assert read_unit(ctx["unit"]["id"])["quality_flag"] == "CLEAR", (
        "two verified complaints must not trip the watch threshold"
    )

    validate_success(
        api.verify_complaint(complaints[2]["id"], linen_manager_headers), 200
    )
    assert read_unit(ctx["unit"]["id"])["quality_flag"] == "WATCH", (
        "three verified complaints reach the threshold and flip the flag"
    )

    # 31 days later the complaints fall outside the trailing 30-day window.
    set_clock("2026-09-05T00:00:00Z")
    assert read_unit(ctx["unit"]["id"])["quality_flag"] == "CLEAR", (
        "complaints created 31 days ago are outside the trailing 30-day window"
    )

    facility = read_facility(ctx["facility"]["id"])
    assert facility["credit_balance_cents"] == 240, (
        "three uninvoiced credits of 80 cents each route to the facility "
        f"pool, got {facility['credit_balance_cents']}"
    )
