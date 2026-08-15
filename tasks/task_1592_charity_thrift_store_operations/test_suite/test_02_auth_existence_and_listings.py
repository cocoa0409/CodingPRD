"""Authentication, authorization, existence ordering, and FK reverse listings."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    INTAKE,
    MGR,
    PRICER,
    add_item,
    assign_worker,
    begin_sort,
    complete_sort,
    create_batch,
    create_donor,
    create_shift,
    create_vendor,
    create_worker,
    find_accumulating_bale,
    seal_bale,
    triage_item,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestAuthentication:
    def test_missing_auth_headers_returns_unauthenticated(self, api):
        """PRD 2.1: "A request missing either header, or presenting an `X-User-Role`
        value outside this list, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/missing_auth_headers_returns_unauthenticated
        """
        resp = api.create_donor({"full_name": "Nobody"}, headers=None)
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, 401)


class TestAuthorization:
    def test_pricer_cannot_create_guideline(self, api):
        """PRD 2.1: "A request whose role is not on the target endpoint's
        authorization list is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD 4: POST /api/pricing-guidelines is authorized for StoreManager only.

        Design: Corner/validations/pricer_cannot_create_guideline
        """
        resp = api.create_guideline({"category": "TOYS", "base_cents": 100}, PRICER)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, 403)


class TestExistenceOrdering:
    def test_get_item_not_found_returns_404(self, api):
        """PRD 2.9: "path identifiers resolve left to right, then body references
        (`donor_id`, `worker_id`, `till_session_id`, every element of `item_ids`,
        `vendor_id`, `target_route_id`, every adjustment's `item_id`); the first
        unresolvable identifier yields `ERR_NOT_FOUND`."

        Design: Corner/entities/get_item_not_found_returns_404
        """
        resp = api.get_item(NON_EXISTENT_UUID, MGR)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND, 404)

    def test_existence_checked_before_state(self, api):
        """PRD 2.9: "When a request violates several rules at once, a fixed priority
        order decides which rejection the client sees — lower tiers are evaluated
        before higher ones" with "4. **Existence** — path identifiers resolve left
        to right ... the first unresolvable identifier yields `ERR_NOT_FOUND`."
        listed ahead of "6. **State preconditions**".

        Design: Corner/validations/existence_checked_before_state
        """
        # Triage against a non-existent item: existence (tier 4) precedes any
        # state evaluation (tier 6), so the outcome is the 404, never a state error.
        resp = api.triage_item(NON_EXISTENT_UUID, {"decision": "SALABLE"}, INTAKE)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND, 404)


class TestForeignKeyReverseListings:
    def test_fk_reverse_reachability_lists(self, api):
        """PRD 3.5: "The bale list supports filtering by `category`, `status`,
        `vendor_id`, or `settled_cycle_id`."
        PRD 3.8: "The assignment list supports filtering by `shift_id`, `worker_id`,
        or `status`."
        PRD 3.9: "The receipt list supports filtering by `batch_id`, `donor_id`, or
        `status`."

        Design: Corner/endpoints/fk_reverse_reachability_lists
        """
        # Sealed bale carrying vendor V.
        vendor = create_vendor("T Co", [{
            "category": "TEXTILES",
            "brackets": [{"up_to_lbs": None, "rate_cents_per_lb": 12}],
        }])
        donor = create_donor("D Fk", address_line="1 Main")
        batch = create_batch(donor["id"], receipt_requested=True)
        recycle_item = add_item(batch["id"], "CLOTHING", "FAIR", weight_lbs=100.0)
        salable_item = add_item(batch["id"], "TOYS", "GOOD")
        begin_sort(batch["id"])
        triage_item(recycle_item["id"], "RECYCLE", salvage_category="TEXTILES")
        triage_item(salable_item["id"], "SALABLE")
        complete_sort(batch["id"])
        bale = find_accumulating_bale("TEXTILES")
        sealed = seal_bale(bale["id"], vendor["id"])
        assert sealed["status"] == "SEALED"

        # ISSUED receipt for the donor's batch.
        receipt = validate_success(api.issue_receipt(batch["id"], INTAKE), 201)

        # Assignment of worker W to shift SH.
        worker = create_worker("W Fk", "VOLUNTEER")
        shift = create_shift("FLOOR", "2026-08-10T09:00:00Z", "2026-08-10T12:00:00Z",
                             required_headcount=3)
        assignment = assign_worker(shift["id"], worker["id"])

        bales, meta_b = validate_paginated(
            api.list_bales(MGR, params={"vendor_id": vendor["id"]})
        )
        assert [b["id"] for b in bales] == [bale["id"]]

        assignments, meta_a = validate_paginated(
            api.list_assignments(MGR, params={"worker_id": worker["id"],
                                              "shift_id": shift["id"]})
        )
        assert [a["id"] for a in assignments] == [assignment["id"]]

        receipts, meta_r = validate_paginated(
            api.list_receipts(INTAKE, params={"donor_id": donor["id"]})
        )
        assert [r["id"] for r in receipts] == [receipt["id"]]
