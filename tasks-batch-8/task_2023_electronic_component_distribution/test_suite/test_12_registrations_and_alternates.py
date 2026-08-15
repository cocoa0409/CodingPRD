"""Design registrations: window-overlap geometry, supplier decisions, and the
expiry sweep; alternate-approval state gates (PRD §3.2, §3.8, §2.4)."""
from test_helpers import (
    ADMIN,
    SALES,
    SUPPLIER,
    ApiErrorId,
    advance_clock,
    approve_registration,
    create_customer,
    create_line,
    create_part,
    get_success_data,
    make_customer_buyer_headers,
    propose_alternate,
    setup_catalog,
    submit_registration,
    validate_error,
)


class TestRegistrationWindowOverlap:
    def test_registration_window_touching_conflicts(self, api):
        """PRD §3.2: "The window is a closed interval on both ends, and windows
        for the same customer and part may not overlap among registrations in
        `SUBMITTED` or `APPROVED` — because the intervals are closed, a new
        window whose `valid_from` lands exactly on an existing window's
        `valid_to` already conflicts and is rejected with
        `ERR_REGISTRATION_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/registration_window_touching_conflicts
        """
        line, part = setup_catalog(line_code="LIN-W")
        customer = create_customer(name="Cust W")
        reg1 = submit_registration(customer["id"], part["id"],
                                   registered_cost_cents=700, max_registered_qty=20,
                                   valid_from="2026-08-01", valid_to="2026-12-31")

        resp = api.create_design_registration(
            {"customer_id": customer["id"], "part_id": part["id"],
             "end_customer_name": "EndCo", "registered_cost_cents": 710,
             "max_registered_qty": 10,
             "valid_from": "2026-12-31", "valid_to": "2027-03-31"},
            SALES)
        validate_error(resp, ApiErrorId.ERR_REGISTRATION_WINDOW_OVERLAP)
        assert get_success_data(
            api.get_design_registration(reg1["id"], ADMIN))["status"] == "SUBMITTED"

    def test_registration_window_disjoint_allowed(self, api):
        """PRD §3.2: "The window is a closed interval on both ends, and windows
        for the same customer and part may not overlap among registrations in
        `SUBMITTED` or `APPROVED` — because the intervals are closed, a new
        window whose `valid_from` lands exactly on an existing window's
        `valid_to` already conflicts and is rejected with
        `ERR_REGISTRATION_WINDOW_OVERLAP`."
        PRD §3.2: "A registration is born `SUBMITTED` with
        `registered_qty_remaining` at zero; it covers nothing until the
        supplier acts."

        Design: Difficulty/resource_temporal_overlap/registration_window_touching_conflicts
        """
        line, part = setup_catalog(line_code="LIN-W")
        customer = create_customer(name="Cust W")
        reg1 = submit_registration(customer["id"], part["id"],
                                   registered_cost_cents=700, max_registered_qty=20,
                                   valid_from="2026-08-01", valid_to="2026-12-31")

        reg2 = submit_registration(customer["id"], part["id"],
                                   registered_cost_cents=720, max_registered_qty=10,
                                   valid_from="2027-01-01", valid_to="2027-06-30")
        assert reg2["status"] == "SUBMITTED", (
            "2027-01-01 is one day past the existing window's 2026-12-31 end — "
            "disjoint under closed-interval semantics"
        )
        assert reg2["registered_qty_remaining"] == 0
        assert get_success_data(
            api.get_design_registration(reg1["id"], ADMIN))["status"] == "SUBMITTED"


class TestRegistrationDecision:
    def test_registration_decide_twice_rejected(self, api):
        """PRD §3.2: "A decision attempted on a registration that has left
        `SUBMITTED` is rejected with `ERR_REGISTRATION_NOT_SUBMITTED`."

        Design: Corner/errors/registration_decide_twice_rejected
        """
        line, part = setup_catalog(line_code="LIN-RD")
        customer = create_customer(name="Cust RD")
        registration = submit_registration(customer["id"], part["id"],
                                           registered_cost_cents=700,
                                           max_registered_qty=10)
        approved = approve_registration(registration["id"])
        assert approved["status"] == "APPROVED"
        assert approved["registered_qty_remaining"] == 10

        resp = api.decide_design_registration(
            registration["id"], {"decision": "REJECT", "reason": "second thought"},
            SUPPLIER)
        validate_error(resp, ApiErrorId.ERR_REGISTRATION_NOT_SUBMITTED)
        after = get_success_data(
            api.get_design_registration(registration["id"], ADMIN))
        assert after["status"] == "APPROVED", "The rejected decision changed nothing"


class TestRegistrationExpirySweep:
    def test_registration_expiry_sweep(self, api):
        """PRD §2.4: "Advancing the clock triggers the system sweep, which runs
        two reconciliations in sequence. First, every design registration in
        `SUBMITTED` or `APPROVED` whose `valid_to` is earlier than the new
        `now` is transitioned to `EXPIRED`."

        Design: Corner/calculations/registration_expiry_sweep
        """
        line, part = setup_catalog(line_code="LIN-XP")
        customer = create_customer(name="Cust XP")
        reg1 = submit_registration(customer["id"], part["id"],
                                   valid_from="2026-08-01", valid_to="2026-08-31",
                                   max_registered_qty=10)
        reg2 = submit_registration(customer["id"], part["id"],
                                   valid_from="2026-09-01", valid_to="2026-12-31",
                                   max_registered_qty=10)

        advance_clock("2026-09-01T00:00:00Z")

        reg1_after = get_success_data(api.get_design_registration(reg1["id"], ADMIN))
        assert reg1_after["status"] == "EXPIRED", "valid_to 2026-08-31 < now"
        reg2_after = get_success_data(api.get_design_registration(reg2["id"], ADMIN))
        assert reg2_after["status"] == "SUBMITTED", (
            "valid_to 2026-12-31 is past the new now; the sweep filtered it out"
        )


class TestAlternateApprovalStates:
    def test_alternate_revoke_from_proposed_rejected(self, api):
        """PRD §3.8: "Acting from the wrong state — anything but `PROPOSED` for
        approve or reject, anything but `APPROVED` for revoke — is
        `ERR_ALTERNATE_APPROVAL_INVALID_STATE`, and a decision may carry an
        optional `reason`."

        Design: Corner/errors/alternate_revoke_from_proposed_rejected
        """
        line = create_line(line_code="LIN-AR")
        primary = create_part(line["id"], part_number="PAR-1A")
        alternate = create_part(line["id"], part_number="PAR-1B",
                                standard_cost_cents=900, book_price_cents=1400)
        customer = create_customer(name="Cust AR")
        approval = propose_alternate(customer["id"], primary["id"], alternate["id"])

        resp = api.decide_alternate_approval(
            approval["id"], {"decision": "REVOKE"},
            make_customer_buyer_headers(customer["id"]))
        validate_error(resp, ApiErrorId.ERR_ALTERNATE_APPROVAL_INVALID_STATE)
        after = get_success_data(api.get_alternate_approval(approval["id"], ADMIN))
        assert after["status"] == "PROPOSED"
