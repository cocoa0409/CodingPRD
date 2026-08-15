"""Staff registration, badge allocation, extras purchase, and issuance gates."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_staff_member,
    create_staff_member,
    get_application,
    get_exhibitor,
    issue_badge,
    make_exhibitor_headers,
    record_guilty_issue,
    setup_decided_application,
    setup_placed_application,
    setup_placed_in_logistics,
    validate_error,
    validate_success,
)


def _register_five_staff(convention_id, exhibitor_id):
    return [
        create_staff_member(convention_id, exhibitor_id, f"Staff {n}")
        for n in ("One", "Two", "Three", "Four", "Five")
    ]


class TestStaffRegistration:
    def test_staff_registration_before_contract_rejected(self, api):
        """PRD §3.7: "Registration requires the exhibitor's application in that
        convention to be `CONTRACTED` or `PLACED`
        (`ERR_STAFF_NOT_ALLOWED_YET`), and each new staff member starts with
        `badge_status` `NONE`."

        Design: Corner/validations/staff_registration_before_contract_rejected
        """
        bundle = setup_decided_application(
            decision="ACCEPTED",
            category_quotas=[
                {"category": "DEALER", "max_accepted": 1, "max_waitlisted": 1}
            ],
            dock_doors=[],
        )
        # JURIED_ACCEPTED is not yet CONTRACTED or PLACED.
        resp = api.create_staff_member(
            {
                "convention_id": bundle["convention"]["id"],
                "full_name": "Staff One",
            },
            make_exhibitor_headers(bundle["exhibitor"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_STAFF_NOT_ALLOWED_YET)


class TestBadgeExtras:
    def test_badge_extras_beyond_included_rejected(self, api):
        """PRD §3.7: "Beyond the included allotment, a `PLACED` exhibitor may
        purchase extra badges by specifying a `quantity`; the purchase is capped
        so that `purchased_extra_badges` plus the requested quantity may not
        exceed `included_badges` (`ERR_BADGE_EXTRA_LIMIT`)."

        Design: Corner/validations/badge_extras_beyond_included_rejected
        """
        bundle = setup_placed_application(
            category_quotas=[
                {"category": "DEALER", "max_accepted": 1, "max_waitlisted": 1}
            ],
            dock_doors=[],
        )
        app_id = bundle["application"]["id"]
        assert bundle["application"]["included_badges"] == 4
        resp = api.purchase_badge_extras(
            app_id,
            {"quantity": 5},
            make_exhibitor_headers(bundle["exhibitor"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_BADGE_EXTRA_LIMIT)
        assert get_application(app_id)["purchased_extra_badges"] == 0

    def test_badge_fees_reconcile_into_balance_due(self, api):
        """PRD §3.7: "Each extra badge costs 7,500 cents, added to
        `badge_fees_cents`, and the `balance_due_cents` is recomputed to include
        the new fees."
        PRD §3.5: "On success the application becomes `CONTRACTED`: the invoice
        and deposit are persisted, `amount_paid_cents` is set to the deposit,
        and `balance_due_cents` opens at the invoice minus the amount paid plus
        any `badge_fees_cents` (zero at this point, since badge extras only
        become purchasable after placement)."

        Design: Corner/cross_cutting_layers/badge_fees_reconcile_into_balance_due
        """
        bundle = setup_placed_application(
            category_quotas=[
                {"category": "DEALER", "max_accepted": 1, "max_waitlisted": 1}
            ],
            dock_doors=[],
        )
        app_id = bundle["application"]["id"]
        # invoice 90000, deposit paid 22500 -> balance 67500 before extras.
        assert bundle["application"]["balance_due_cents"] == 67500
        resp = api.purchase_badge_extras(
            app_id,
            {"quantity": 2},
            make_exhibitor_headers(bundle["exhibitor"]["id"]),
        )
        app = validate_success(resp)
        assert app["purchased_extra_badges"] == 2
        assert app["badge_fees_cents"] == 15000  # 2 x 7500
        assert app["balance_due_cents"] == 82500  # 90000 - 22500 + 15000


class TestBadgeIssuance:
    def test_staff_badge_revoke_restores_allocation(self, api, ops_headers):
        """PRD §3.7: "Revoking a badge moves `ISSUED` → `REVOKED` and is
        available to `OperationsStaff` and the `ShowDirector`; revocation frees
        one unit of allocation, dropping the derived issued count by one."
        PRD §3.7: "The allocation gate requires the number of currently
        `ISSUED` badges for the exhibitor in the convention to be below
        `included_badges` plus `purchased_extra_badges`
        (`ERR_BADGE_ALLOCATION_EXHAUSTED`)."

        Design: Corner/state_machines/staff_badge_revoke_restores_allocation
        """
        bundle = setup_placed_in_logistics(
            category_quotas=[
                {"category": "DEALER", "max_accepted": 1, "max_waitlisted": 1}
            ],
            dock_doors=[],
        )
        conv_id = bundle["convention"]["id"]
        ex_id = bundle["exhibitor"]["id"]
        staff = _register_five_staff(conv_id, ex_id)
        for member in staff[:4]:  # included_badges == 4 (BOOTH_10X10)
            issued = issue_badge(member["id"], ex_id)
            assert issued["badge_status"] == "ISSUED"

        revoked = validate_success(api.revoke_badge(staff[0]["id"], ops_headers))
        assert_staff_member(revoked)
        assert revoked["badge_status"] == "REVOKED"

        # The freed unit lets the fifth staff member be issued a badge.
        fifth = issue_badge(staff[4]["id"], ex_id)
        assert fifth["badge_status"] == "ISSUED"

    def test_badge_issue_compliance_hold_precedes_capacity(self, api):
        """PRD §3.7: "Issuance is double-gated, compliance first and allocation
        second. The compliance gate requires the exhibitor's `standing` to be
        neither `SUSPENDED` nor `EVICTED` and no unresolved `CRITICAL` issue —
        one in `OPEN`, `TRIAGED`, or `ESCALATED` — to exist for that exhibitor
        in that convention (`ERR_COMPLIANCE_HOLD`). The allocation gate requires
        the number of currently `ISSUED` badges for the exhibitor in the
        convention to be below `included_badges` plus `purchased_extra_badges`
        (`ERR_BADGE_ALLOCATION_EXHAUSTED`)."

        Design: Difficulty/priority_pair_validation_conflict/badge_issue_safety_precedes_capacity
        """
        bundle = setup_placed_in_logistics(
            category_quotas=[
                {"category": "DEALER", "max_accepted": 1, "max_waitlisted": 1}
            ],
            dock_doors=[],
        )
        conv_id = bundle["convention"]["id"]
        ex_id = bundle["exhibitor"]["id"]
        staff = _register_five_staff(conv_id, ex_id)
        for member in staff[:4]:  # exhaust the included allotment of 4
            issue_badge(member["id"], ex_id)

        # Two CRITICAL guilty findings: 6 strike points -> SUSPENDED. Both the
        # compliance gate (standing) and the allocation gate (issued 4 ==
        # included 4 + extras 0) now fail; compliance must win.
        record_guilty_issue(conv_id, ex_id, "CRITICAL", "Incident one")
        record_guilty_issue(conv_id, ex_id, "CRITICAL", "Incident two")
        assert get_exhibitor(ex_id)["standing"] == "SUSPENDED"

        resp = api.issue_badge(staff[4]["id"], make_exhibitor_headers(ex_id))
        validate_error(resp, ApiErrorId.ERR_COMPLIANCE_HOLD)

    def test_failed_badge_issue_leaves_badge_unissued(self, api):
        """PRD §3.7: "Issuing a badge moves a staff member `NONE` → `ISSUED` and
        may be performed by the exhibitor or by `OperationsStaff`."
        PRD §3.7: "The compliance gate requires the exhibitor's `standing` to be
        neither `SUSPENDED` nor `EVICTED` and no unresolved `CRITICAL` issue —
        one in `OPEN`, `TRIAGED`, or `ESCALATED` — to exist for that exhibitor
        in that convention (`ERR_COMPLIANCE_HOLD`)."

        Design: Difficulty/priority_pair_validation_conflict/badge_issue_safety_precedes_capacity
        """
        bundle = setup_placed_in_logistics(
            category_quotas=[
                {"category": "DEALER", "max_accepted": 1, "max_waitlisted": 1}
            ],
            dock_doors=[],
        )
        conv_id = bundle["convention"]["id"]
        ex_id = bundle["exhibitor"]["id"]
        staff = _register_five_staff(conv_id, ex_id)
        for member in staff[:4]:
            issue_badge(member["id"], ex_id)
        record_guilty_issue(conv_id, ex_id, "CRITICAL", "Incident one")
        record_guilty_issue(conv_id, ex_id, "CRITICAL", "Incident two")

        resp = api.issue_badge(staff[4]["id"], make_exhibitor_headers(ex_id))
        validate_error(resp, ApiErrorId.ERR_COMPLIANCE_HOLD)

        fifth = validate_success(
            api.get_staff_member(staff[4]["id"], TEST_USERS["director_headers"])
        )
        assert fifth["badge_status"] == "NONE"
        # The four previously issued badges are untouched by the rejection.
        for member in staff[:4]:
            current = validate_success(
                api.get_staff_member(member["id"], TEST_USERS["director_headers"])
            )
            assert current["badge_status"] == "ISSUED"
