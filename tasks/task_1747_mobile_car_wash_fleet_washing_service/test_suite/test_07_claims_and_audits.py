"""Damage claims and quality audits: claim fork, inspection gating, windows,
segregation of duties, audit scoring and rewash creation (PRD §3.8)."""
from test_helpers import (
    ApiErrorId, TEST_USERS, add_stop_to_route, approve_claim, create_confirmed_order,
    create_inspection_report_payload, create_route, create_technician, create_van,
    file_damage_claim, file_paid_claim, get_order, list_all_wash_orders,
    make_auditor_headers, make_customer_headers, make_technician_headers,
    order_event, pay_claim, record_audit, request_rewash, review_claim, route_event,
    set_clock, setup_completed_order, setup_customer_site_vehicles, stop_event,
    validate_error, validate_error_is_one_of, validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]


def _order_with_in_progress_report():
    """1-SEDAN order; report (EXTERIOR_BODY pre_existing_damage=true) filed DRAFT
    while the order is IN_PROGRESS; order then COMPLETED. Returns ctx."""
    ctx = setup_customer_site_vehicles(num_vehicles=1, vehicle_class="SEDAN")
    order = create_confirmed_order(ctx["customer"]["id"], ctx["site"]["id"],
                                   ctx["vehicle_ids"])
    van = create_van(load_gallons=96)
    tech = create_technician()
    route = create_route("2026-08-05", van["id"], tech["id"])
    stop = add_stop_to_route(route["id"], order["id"])
    route_event(route["id"], "PUBLISH")
    stop_event(route["id"], stop["id"], "ARRIVE", tech["id"])
    order_event(order["id"], "START", make_technician_headers(tech["id"]))
    report = validate_success(api_create_report(
        order["id"], tech["id"],
        [{"area": "EXTERIOR_BODY", "pre_existing_damage": True,
          "notes": "door ding present"}],
    ), expected_status=201)
    order = order_event(order["id"], "COMPLETE",
                        make_technician_headers(tech["id"]),
                        vehicles_washed_ids=ctx["vehicle_ids"])
    ctx.update({"order": order, "tech": tech, "report": report})
    return ctx


def api_create_report(order_id, technician_id, areas):
    from test_helpers import api_client  # local alias to keep signature tidy
    return api_client.create_inspection_report(
        {"wash_order_id": order_id, "areas": areas},
        make_technician_headers(technician_id),
    )


class TestDamageClaimBranchingFork:
    def test_approve_branch_caps_and_pays(self, api):
        """PRD §3.8: "`approved_amount_cents` defaults to the lesser of
        `claimed_amount_cents` and the class cap taken from the order's first
        vehicle's class — 25,000 cents for a `SEDAN`, 30,000 for an `SUV_PICKUP`,
        40,000 for a `VAN_BOXTRUCK`, and 60,000 for a `HEAVY_FLEET`"
        PRD §3.8: "A successful payment records `paid_by` and makes the claim eligible
        for the invoice claim credits of §3.9 in the wash order's completion period."

        Design: Difficulty/non_linear_state_machine/damage_claim_branching_fork
        """
        ctx = setup_completed_order(clock_pin="2026-08-05T10:00:00Z")
        claim = file_damage_claim(
            ctx["order"]["id"], ctx["customer"]["id"], area="EXTERIOR_BODY",
            claimed_amount_cents=30000, description="scratch",
        )
        review_claim(claim["id"], "auditor-1")
        approved = approve_claim(claim["id"], "auditor-1")
        assert approved["approved_amount_cents"] == 25000  # min(30000, SEDAN cap)
        assert approved["reviewed_by"] == "auditor-1"
        paid = pay_claim(claim["id"], "auditor-2")
        assert paid["status"] == "PAID"
        assert paid["paid_by"] == "auditor-2"

    def test_deny_branch_sets_reason_and_locks_terminal(self, api):
        """PRD §3.8: "Denial instead records the supplied `deny_reason`, sets
        `reviewed_by` the same way, moves the claim to `DENIED`, and creates no
        credit."
        PRD §2.6: "State eligibility — the target entity is in a valid from-state for
        the requested transition, else `ERR_INVALID_STATE`"

        Design: Difficulty/non_linear_state_machine/damage_claim_branching_fork
        """
        ctx = setup_completed_order(clock_pin="2026-08-05T10:00:00Z")
        claim = file_damage_claim(
            ctx["order"]["id"], ctx["customer"]["id"], area="GLASS",
            claimed_amount_cents=5000, description="chip",
        )
        review_claim(claim["id"], "auditor-1")
        denied = validate_success(api.damage_claim_event(
            claim["id"], {"event_type": "DENY", "deny_reason": "wear and tear"},
            make_auditor_headers("auditor-1"),
        ))
        assert denied["status"] == "DENIED"
        assert denied.get("approved_amount_cents") is None
        resp = api.damage_claim_event(
            claim["id"], {"event_type": "MARK_PAID"}, make_auditor_headers("auditor-2"),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestClaimApproveGatedBySubmittedInspection:
    def test_draft_report_does_not_block_approval(self, api):
        """PRD §3.8: "First, if any `SUBMITTED` InspectionReport for the order flags
        the claimed `area` with `pre_existing_damage`, approval is blocked with
        `ERR_PRE_EXISTING_CONDITION_DOCUMENTED`."

        Design: Difficulty/cross_entity_state_dependency/claim_approve_gated_by_submitted_inspection
        """
        ctx = _order_with_in_progress_report()
        claim = file_damage_claim(
            ctx["order"]["id"], ctx["customer"]["id"], area="EXTERIOR_BODY",
            claimed_amount_cents=30000, description="door dent",
        )
        review_claim(claim["id"], "auditor-1")
        approved = approve_claim(claim["id"], "auditor-1")
        # report still DRAFT: cap applies, approval succeeds
        assert approved["status"] == "APPROVED"
        assert approved["approved_amount_cents"] == 25000

    def test_submitted_report_blocks_same_area_approval(self, api):
        """PRD §3.8: "First, if any `SUBMITTED` InspectionReport for the order flags
        the claimed `area` with `pre_existing_damage`, approval is blocked with
        `ERR_PRE_EXISTING_CONDITION_DOCUMENTED`."
        PRD §3.5: "a `SUBMITTED` report is immutable. Its consequence lands later:
        submission blocks any future claim approval on an area it flags with
        `pre_existing_damage` (§3.8)."

        Design: Difficulty/cross_entity_state_dependency/claim_approve_gated_by_submitted_inspection
        """
        ctx = _order_with_in_progress_report()
        submitted = validate_success(api.inspection_report_event(
            ctx["report"]["id"], {"event_type": "SUBMIT"},
            make_technician_headers(ctx["tech"]["id"]),
        ))
        assert submitted["status"] == "SUBMITTED"
        claim = file_damage_claim(
            ctx["order"]["id"], ctx["customer"]["id"], area="EXTERIOR_BODY",
            claimed_amount_cents=20000, description="same door dent re-claimed",
        )
        review_claim(claim["id"], "auditor-1")
        resp = api.damage_claim_event(
            claim["id"], {"event_type": "APPROVE"}, make_auditor_headers("auditor-1"),
        )
        validate_error(resp, ApiErrorId.ERR_PRE_EXISTING_CONDITION_DOCUMENTED)
        remaining = validate_success(api.get_damage_claim(claim["id"], DISPATCHER))
        assert remaining["status"] == "UNDER_REVIEW"


class TestClaimWindowExactly72Hours:
    def _completed_at_pinned(self):
        return setup_completed_order(clock_pin="2026-08-05T10:00:00Z")

    def test_claim_at_exactly_72h_allowed(self, api):
        """PRD §3.8: "The owning customer files a claim against a `COMPLETED` order
        within 72 hours of its `completed_at` — exactly 72 hours is allowed; a later
        filing fails with `ERR_CLAIM_WINDOW_EXPIRED`"

        Design: Difficulty/boundary_precision_check/claim_window_exactly_72_hours
        """
        ctx = self._completed_at_pinned()
        set_clock("2026-08-08T10:00:00Z")  # completed_at + exactly 72h
        claim = file_damage_claim(
            ctx["order"]["id"], ctx["customer"]["id"], area="WHEELS",
            claimed_amount_cents=9000, description="rim scuff",
        )
        assert claim["status"] == "FILED"

    def test_claim_at_72h_records_filed_at_and_customer(self, api):
        """PRD §3.8: "The claim's `customer_id` is copied from the wash order,
        `filed_at` is stamped from the logical clock, and the claim starts `FILED`."
        PRD §2.4: "All datetime fields the API returns — for example `held_at`,
        `completed_at`, `filed_at`, `planned_start_at`, and `planned_end_at` — are
        serialized as ISO 8601 UTC with three fractional digits."

        Design: Difficulty/boundary_precision_check/claim_window_exactly_72_hours
        """
        ctx = self._completed_at_pinned()
        set_clock("2026-08-08T10:00:00Z")
        claim = file_damage_claim(
            ctx["order"]["id"], ctx["customer"]["id"], area="WHEELS",
            claimed_amount_cents=9000, description="rim scuff",
        )
        assert claim["filed_at"] == "2026-08-08T10:00:00.000Z"
        assert claim["customer_id"] == ctx["customer"]["id"]


class TestAuditFailCreatesRewashAndPending:
    def test_fail_audit_creates_waived_rewash(self, api):
        """PRD §3.8: "if no open rewash exists for the order — open meaning `DRAFT`,
        `SCHEDULED`, `ASSIGNED`, `IN_PROGRESS`, or `WEATHER_HELD` — the system creates
        a rewash order and moves the audited order `COMPLETED` → `REWASH_PENDING`,
        just as a customer-requested rewash would."
        PRD §3.8: "`billing_status` is `WAIVED`; `quote_cents` is 0; and the status is
        `SCHEDULED` with a window of the next day — the logical clock date plus one
        day — from 08:00:00 to 10:00:00 UTC."

        Design: Corner/state_machines/audit_fail_creates_rewash_and_pending
        """
        ctx = setup_completed_order(clock_pin="2026-08-05T10:00:00Z")
        audit = record_audit(
            ctx["order"]["id"], exterior_score=20, wheels_score=15, glass_score=20,
            trim_score=19, water_spotting_score=5,
        )
        assert audit["total_score"] == 79
        assert audit["result"] == "FAIL"
        rewashes = [
            o for o in list_all_wash_orders()
            if o.get("rewash_of_id") == ctx["order"]["id"]
        ]
        assert len(rewashes) == 1
        rewash = rewashes[0]
        assert rewash["status"] == "SCHEDULED"
        assert rewash["billing_status"] == "WAIVED"
        assert rewash["quote_cents"] == 0
        assert rewash["is_rewash"] is True
        assert rewash["scheduled_window_start"] == "2026-08-06T08:00:00.000Z"
        assert get_order(ctx["order"]["id"])["status"] == "REWASH_PENDING"


class TestAuditPassAtExactly80:
    def test_exactly_80_passes_without_rewash(self, api):
        """PRD §3.8: "The `total_score` is the plain sum of the five categories with
        equal weights, spanning 0 to 100, and the computed `result` is `PASS` when the
        total reaches 80 — 80 exactly passes — and `FAIL` below it."

        Design: Corner/calculations/audit_pass_at_exactly_80
        """
        ctx = setup_completed_order()
        audit = record_audit(
            ctx["order"]["id"], exterior_score=20, wheels_score=20, glass_score=20,
            trim_score=19, water_spotting_score=1,
        )
        assert audit["total_score"] == 80
        assert audit["result"] == "PASS"
        assert get_order(ctx["order"]["id"])["status"] == "COMPLETED"
        rewashes = [
            o for o in list_all_wash_orders()
            if o.get("rewash_of_id") == ctx["order"]["id"]
        ]
        assert len(rewashes) == 0


class TestQualityAuditImmutableRecord:
    def test_audit_carries_only_id_and_created_at(self, api):
        """PRD §2.4: "The QualityAudit resource is the single exception to this
        convention: it carries only `id` and `created_at`; both `updated_at` and
        `version` are absent."
        PRD §3.8: "The auditor's opaque `X-User-ID` is recorded as `auditor_id`."

        Design: Corner/entities/quality_audit_immutable_record
        """
        ctx = setup_completed_order()
        audit = record_audit(ctx["order"]["id"])
        assert audit["total_score"] == 100
        assert audit["result"] == "PASS"
        assert audit["wash_order_id"] == ctx["order"]["id"]
        assert audit["auditor_id"] == "auditor-1"
        assert "version" not in audit
        assert "updated_at" not in audit


class TestRewashAfterWindowExpired:
    def test_rewash_at_73h_rejected(self, api):
        """PRD §3.8: "Within 72 hours of an order's `completed_at` — exactly 72 hours
        is allowed; later requests fail with `ERR_REWASH_WINDOW_EXPIRED` — the
        customer may request a rewash of a `COMPLETED` order, provided no other rewash
        of that same order is still open (`ERR_REWASH_IN_PROGRESS`)."

        Design: Corner/validations/rewash_after_window_expired
        """
        ctx = setup_completed_order(clock_pin="2026-08-05T10:00:00Z")
        set_clock("2026-08-08T11:00:00Z")  # completed_at + 73h
        resp = api.rewash_wash_order(
            ctx["order"]["id"], make_customer_headers(ctx["customer"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_REWASH_WINDOW_EXPIRED)


class TestSecondRewashBlocked:
    def test_second_rewash_request_rejected_while_first_open(self, api):
        """PRD §3.8: "Within 72 hours of an order's `completed_at` — exactly 72 hours
        is allowed; later requests fail with `ERR_REWASH_WINDOW_EXPIRED` — the
        customer may request a rewash of a `COMPLETED` order, provided no other rewash
        of that same order is still open (`ERR_REWASH_IN_PROGRESS`)."

        Design: Corner/errors/second_rewash_blocked
        """
        ctx = setup_completed_order(clock_pin="2026-08-05T10:00:00Z")
        first = request_rewash(ctx["order"]["id"], ctx["customer"]["id"])
        assert first["status"] == "SCHEDULED"
        resp = api.rewash_wash_order(
            ctx["order"]["id"], make_customer_headers(ctx["customer"]["id"]),
        )
        # While the first rewash is open the original sits in REWASH_PENDING, so the
        # second request fails both §2.6 tier 6 (not COMPLETED -> ERR_INVALID_STATE)
        # and tier 9 (open rewash -> ERR_REWASH_IN_PROGRESS). §2.6's cascade ("the
        # request is rejected with the error from the earliest check") makes
        # ERR_INVALID_STATE the cascade-literal outcome while §3.8 names
        # ERR_REWASH_IN_PROGRESS for this condition; both are PRD-defensible.
        validate_error_is_one_of(
            resp,
            [ApiErrorId.ERR_REWASH_IN_PROGRESS.value,
             ApiErrorId.ERR_INVALID_STATE.value],
        )


class TestExplicitOvercapApprovalRejected:
    def test_overcap_amount_rejected_then_default_applies_cap(self, api):
        """PRD §3.8: "an explicit `approved_amount_cents` may be supplied only at or
        below that minimum, anything higher failing with `ERR_CLAIM_CAP_EXCEEDED`."

        Design: Corner/validations/explicit_overcap_approval_rejected
        """
        ctx = setup_completed_order()
        claim = file_damage_claim(
            ctx["order"]["id"], ctx["customer"]["id"], area="TRIM",
            claimed_amount_cents=30000, description="trim scratch",
        )
        review_claim(claim["id"], "auditor-1")
        resp = api.damage_claim_event(
            claim["id"], {"event_type": "APPROVE", "approved_amount_cents": 26000},
            make_auditor_headers("auditor-1"),
        )
        # 26000 > min(30000, SEDAN cap 25000)
        validate_error(resp, ApiErrorId.ERR_CLAIM_CAP_EXCEEDED)
        remaining = validate_success(api.get_damage_claim(claim["id"], DISPATCHER))
        assert remaining["status"] == "UNDER_REVIEW"
        approved = approve_claim(claim["id"], "auditor-1")
        assert approved["status"] == "APPROVED"
        assert approved["approved_amount_cents"] == 25000


class TestClaimWindow73hExpired:
    def test_claim_at_73h_rejected(self, api):
        """PRD §3.8: "The owning customer files a claim against a `COMPLETED` order
        within 72 hours of its `completed_at` — exactly 72 hours is allowed; a later
        filing fails with `ERR_CLAIM_WINDOW_EXPIRED`"

        Design: Corner/errors/claim_window_73h_expired
        """
        ctx = setup_completed_order(clock_pin="2026-08-05T10:00:00Z")
        set_clock("2026-08-08T11:00:00Z")  # completed_at + 73h
        resp = api.create_damage_claim(
            {"wash_order_id": ctx["order"]["id"], "area": "INTERIOR",
             "claimed_amount_cents": 5000, "description": "seat stain"},
            make_customer_headers(ctx["customer"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_CLAIM_WINDOW_EXPIRED)


class TestSodApproverCannotMarkPaid:
    def test_approver_cannot_pay_different_auditor_can(self, api):
        """PRD §3.8: "Marking an `APPROVED` claim `PAID` requires the paying auditor's
        `X-User-ID` to differ from the claim's `reviewed_by`; the same user attempting
        both steps is rejected with `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/rbac/sod_approver_cannot_mark_paid
        """
        ctx = setup_completed_order()
        claim = file_damage_claim(
            ctx["order"]["id"], ctx["customer"]["id"], area="GLASS",
            claimed_amount_cents=9000, description="chip",
        )
        review_claim(claim["id"], "auditor-1")
        approve_claim(claim["id"], "auditor-1")
        resp = api.damage_claim_event(
            claim["id"], {"event_type": "MARK_PAID"}, make_auditor_headers("auditor-1"),
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        paid = pay_claim(claim["id"], "auditor-2")
        assert paid["status"] == "PAID"
        assert paid["paid_by"] == "auditor-2"
