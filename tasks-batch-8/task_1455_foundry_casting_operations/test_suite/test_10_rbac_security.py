"""Role-based access control: authentication, exclusive operations, ownership,
action scoping on claim review, and both segregation-of-duties rules."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    create_customer,
    create_foundry,
    create_furnace,
    create_order,
    create_pattern_payload,
    file_claim,
    make_customer_headers,
    record_inspection,
    review,
    setup_approved_claim,
    setup_casting_at_final_inspection,
    setup_fulfilled_order,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["foundry_admin_headers"]
PM = TEST_USERS["pattern_maker_headers"]
SPECTRO_1 = TEST_USERS["spectro_1_headers"]
QI = TEST_USERS["qi_1_headers"]
WM_1 = TEST_USERS["wm_1_headers"]
WM_2 = TEST_USERS["wm_2_headers"]


class TestAuthentication:
    def test_missing_auth_headers_unauthenticated(self, api):
        """PRD §2.1: "A request missing either header, or presenting a role that
        is not one of the declared roles below, is rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/missing_auth_headers_unauthenticated
        """
        res = api.create_foundry({"name": "F1"}, headers={})
        validate_error(res, "ERR_UNAUTHENTICATED", expected_status=401)


class TestExistenceBeforeState:
    def test_existence_404_beats_state_check(self, api):
        """PRD §2.10: "Third, existence: path identifiers and body foreign-key
        references must resolve (`ERR_NOT_FOUND`, including the cross-foundry
        rule of §2.11). Fourth, state feasibility: the target resource must be
        in a state from which the requested transition exists"

        Design: Corner/validations/existence_404_beats_state_check
        """
        res = api.retire_pattern(NON_EXISTENT_UUID, PM)
        validate_error(res, "ERR_NOT_FOUND", expected_status=404)


class TestExclusiveOperations:
    def test_spectrographer_cannot_create_heat(self, api):
        """PRD §2.1: "A request whose role is not permitted on the target
        endpoint — including the per-action scoping on the warranty review
        capability, where the permitted action set differs by role — is rejected
        with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)." PRD §4: "POST | /api/heats |
        Open a melt heat with a pinned chemistry spec | MeltSupervisor".

        Design: Corner/rbac/spectrographer_cannot_create_heat
        """
        foundry = create_foundry()
        furnace = create_furnace(foundry["id"])
        res = api.create_heat(
            {"foundry_id": foundry["id"], "furnace_id": furnace["id"],
             "alloy_grade": "GJS-400-15",
             "chemistry_spec": {"elements": {"C": {"min": 3.2, "max": 3.6}}}},
            SPECTRO_1)
        validate_error(res, "ERR_UNAUTHORIZED_ROLE", expected_status=403)

    def test_customer_cannot_disposition_inspection(self, api):
        """PRD §2.1: "A request whose role is not permitted on the target
        endpoint — including the per-action scoping on the warranty review
        capability, where the permitted action set differs by role — is rejected
        with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)." PRD §4: "POST |
        /api/inspections/{id}/disposition | MRB disposition: ACCEPT, USE_AS_IS,
        REWORK, or SCRAP | QualityInspector".

        Design: Corner/rbac/customer_cannot_disposition_inspection
        """
        foundry = create_foundry()
        customer = create_customer(foundry["id"])
        # Role gate (authorization, second) precedes existence (third).
        res = api.disposition_inspection(
            NON_EXISTENT_UUID, {"disposition": "ACCEPT"},
            make_customer_headers(customer["id"]))
        validate_error(res, "ERR_UNAUTHORIZED_ROLE", expected_status=403)


class TestOwnership:
    def test_customer_cannot_claim_other_customers_order(self, api):
        """PRD §2.1: "When `X-User-Role` is `Customer`, `X-User-ID` is the `id`
        of the acting `Customer` record; ownership checks on any resource that
        references a `Customer` compare the resource's `customer_id` field to
        `X-User-ID`, and a mismatch is `ERR_FORBIDDEN_OWNER`." and PRD §3.9:
        "The filer must own the order (`ERR_FORBIDDEN_OWNER`)".

        Design: Corner/rbac/customer_cannot_claim_other_customers_order
        """
        foundry = create_foundry()
        cust_a = create_customer(foundry["id"], company_name="A Corp")
        cust_b = create_customer(foundry["id"], company_name="B Corp")
        pattern = validate_success(api.create_pattern(
            create_pattern_payload(foundry["id"]), PM), expected_status=201)
        order_b = create_order(foundry["id"], cust_b["id"], pattern["id"])
        res = api.create_claim(
            {"order_id": order_b["id"], "claim_type": "DEFECT", "claim_qty": 1,
             "claimed_amount_cents": 1000},
            make_customer_headers(cust_a["id"]))
        validate_error(res, "ERR_FORBIDDEN_OWNER", expected_status=403)


class TestSegregationOfDuties:
    def test_sod_spectro_certifier_cannot_disposition_own_heat_casting(self, api):
        """PRD §3.6: "the dispositioning inspector's `X-User-ID` must differ
        from the `certified_by_user_id` of the heat that poured the casting,
        traced through the casting's `mold_id` to the mold's `pour_slot_id` to
        the slot's `heat_id`; a violation is `ERR_SEGREGATION_OF_DUTIES`
        (HTTP 403)."

        Design: Corner/rbac/sod_spectro_certifier_cannot_disposition_own_heat_casting
        """
        # The production fixture certifies the heat as spectro_1.
        ctx = setup_casting_at_final_inspection()
        casting_id = ctx["castings"][0][0]["id"]
        insp = record_inspection(casting_id)
        # The heat's certifier holding a QualityInspector badge is still barred.
        res = api.disposition_inspection(
            insp["id"], {"disposition": "ACCEPT"},
            TEST_USERS["qi_as_spectro_1_headers"])
        validate_error(res, "ERR_SEGREGATION_OF_DUTIES", expected_status=403)
        # A different inspector dispositions the same report successfully.
        ok = validate_success(api.disposition_inspection(
            insp["id"], {"disposition": "ACCEPT"}, QI))
        assert ok["status"] == "DISPOSITIONED"

    def test_sod_claim_approver_cannot_settle(self, api):
        """PRD §3.9: "the settling `WarrantyManager`'s `X-User-ID` must differ
        from the claim's `reviewed_by_user_id` (`ERR_SEGREGATION_OF_DUTIES`)"
        and "Under the `STANDARD` variant — selected by `claim_type` `DEFECT` —
        the credit is the lesser of `claimed_amount_cents` and
        `unit_price_cents` multiplied by `claim_qty`".

        Design: Corner/rbac/sod_claim_approver_cannot_settle
        """
        ctx = setup_approved_claim(claim_type="DEFECT", claim_qty=1,
                                   claimed_amount_cents=5000)
        # wm_1 approved the claim and may not settle it.
        res = api.settle_claim(ctx["claim"]["id"], WM_1)
        validate_error(res, "ERR_SEGREGATION_OF_DUTIES", expected_status=403)
        # A different manager settles: min(5000, 100000 * 1) = 5000.
        settled = validate_success(api.settle_claim(ctx["claim"]["id"], WM_2))
        assert settled["status"] == "SETTLED"
        assert settled["settled_credit_cents"] == 5000


class TestReviewActionScoping:
    def test_claim_review_action_scope_by_role(self, api):
        """PRD §3.9: "The action set is scoped by role, and crossing the scope
        is `ERR_UNAUTHORIZED_ROLE`: the manager may `START` review (`FILED →
        UNDER_REVIEW`), `APPROVE` (`UNDER_REVIEW → APPROVED`), `DENY`
        (`UNDER_REVIEW → DENIED`), or `REQUEST_INFO` (`UNDER_REVIEW →
        INFO_REQUESTED`); the owning customer may `RESPOND` to an information
        request (`INFO_REQUESTED → UNDER_REVIEW`) or `APPEAL` a denial (`DENIED
        → UNDER_REVIEW`), with either customer action rejected as
        `ERR_FORBIDDEN_OWNER` when the caller's `X-User-ID` differs from the
        claim's `customer_id`."

        Design: Corner/rbac/claim_review_action_scope_by_role
        """
        ctx = setup_fulfilled_order()
        claim = file_claim(ctx, claim_type="DEFECT", claim_qty=1,
                           claimed_amount_cents=5000)
        review(claim["id"], "START", WM_1)
        review(claim["id"], "REQUEST_INFO", WM_1)

        # RESPOND is a Customer action: the WarrantyManager may not send it.
        res = api.review_claim(claim["id"], {"action": "RESPOND"}, WM_1)
        validate_error(res, "ERR_UNAUTHORIZED_ROLE", expected_status=403)

        # APPROVE is a WarrantyManager action: the Customer may not send it.
        res2 = api.review_claim(
            claim["id"], {"action": "APPROVE"},
            make_customer_headers(ctx["customer"]["id"]))
        validate_error(res2, "ERR_UNAUTHORIZED_ROLE", expected_status=403)
