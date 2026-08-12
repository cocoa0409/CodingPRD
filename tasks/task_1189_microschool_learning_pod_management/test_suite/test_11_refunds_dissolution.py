"""Refund-claim and dissolution claims: segregation of duties, amount
bounds, the dissolution waterfall ordering, and the depth-4 dissolution
cascade."""
from test_helpers import (
    ApiErrorId,
    create_refund_claim_payload,
    get_success_data,
    make_family_headers,
    make_registrar_headers,
    validate_error,
    validate_paginated,
    validate_success,
    TEST_USERS,
)
from test_helpers.fixtures import (
    create_issued_invoice,
    decide_all_claims,
    enroll_seat,
    get_pod,
    get_pod_version,
    list_dissolution_claims,
    post_and_clear_payment,
    set_clock,
    setup_active_pod_with_enrolled_seats,
    setup_dissolved_pod,
    setup_dissolving_pod,
    setup_enrolled_seat,
    setup_pod_active,
    withdraw_seat,
)

ADMIN = TEST_USERS["platform_admin_headers"]
OPERATOR = TEST_USERS["pod_operator_headers"]
OFFICER = TEST_USERS["compliance_officer_headers"]
REGISTRAR = TEST_USERS["registrar_headers"]

FILER_ID = "test-registrar-filer-1"
REVIEWER_ID = "test-registrar-reviewer-1"


def _filed_overpayment_claim(api, pod_id, seat_id, filer_id=FILER_ID):
    return get_success_data(api.create_refund_claim(
        pod_id, create_refund_claim_payload(seat_id), make_registrar_headers(filer_id)
    ))


class TestSegregationOfDuties:
    def _setup_under_review_claim(self, api, filer_id=FILER_ID):
        set_clock("2026-09-01T00:00:00Z")
        pod, *_ = setup_pod_active()
        family, student, seat = setup_enrolled_seat(pod)
        claim = _filed_overpayment_claim(api, pod["id"], seat["id"], filer_id)
        get_success_data(api.begin_review_refund_claim(
            pod["id"], claim["id"], make_registrar_headers(REVIEWER_ID)
        ))
        claim = get_success_data(api.get_refund_claim(claim["id"], REGISTRAR))
        return pod, seat, claim

    def test_segregation_of_duties_reviewer_equals_filer(self, api):
        """PRD 3.9: "The decision then enforces, in order, the
        reviewer-versus-filer separation — the reviewer's `X-User-ID` must
        differ from `filed_by_user_id`, or the decision is rejected with
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 422) — and the amount bounds."

        Design: Corner/validations/segregation_of_duties_reviewer_equals_filer
        """
        pod, seat, claim = self._setup_under_review_claim(api)
        resp = api.decide_refund_claim(
            pod["id"], claim["id"],
            {"decision": "APPROVED", "approved_amount_cents": 10000},
            make_registrar_headers(FILER_ID),
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
                       expected_status=422)

    def test_err_segregation_of_duties_triggerable(self, api):
        """PRD 3.9: "The decision then enforces, in order, the
        reviewer-versus-filer separation — the reviewer's `X-User-ID` must
        differ from `filed_by_user_id`, or the decision is rejected with
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 422) — and the amount bounds."

        Design: Corner/errors/err_segregation_of_duties_triggerable
        """
        pod, seat, claim = self._setup_under_review_claim(api)
        resp = api.decide_refund_claim(
            pod["id"], claim["id"],
            {"decision": "APPROVED", "approved_amount_cents": 100},
            make_registrar_headers(FILER_ID),
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
                       expected_status=422)


class TestRefundAmountBounds:
    def test_refund_exceeds_claim_rejected(self, api):
        """PRD 3.9: "A decision of `APPROVED` requires the payload's
        `approved_amount_cents` to be no greater than `claimed_amount_cents`
        and no less than zero, violations rejected as
        `ERR_REFUND_EXCEEDS_CLAIM` (HTTP 422); it records
        `approved_amount_cents` on the claim, stamps `reviewed_by_user_id`
        with the reviewer's identity, and sets the seat's `refund_due_cents`
        to the approved amount."

        Design: Corner/validations/refund_exceeds_claim_rejected
        """
        set_clock("2026-09-01T00:00:00Z")
        pod, *_ = setup_pod_active()
        family, student, seat = setup_enrolled_seat(pod)
        claim = _filed_overpayment_claim(api, pod["id"], seat["id"])
        get_success_data(api.begin_review_refund_claim(
            pod["id"], claim["id"], make_registrar_headers(REVIEWER_ID)
        ))
        claim = get_success_data(api.get_refund_claim(claim["id"], REGISTRAR))
        claimed = claim["claimed_amount_cents"]
        resp = api.decide_refund_claim(
            pod["id"], claim["id"],
            {"decision": "APPROVED", "approved_amount_cents": claimed + 10000},
            make_registrar_headers(REVIEWER_ID),
        )
        validate_error(resp, ApiErrorId.ERR_REFUND_EXCEEDS_CLAIM,
                       expected_status=422)


class TestDissolutionCascade:
    def test_dissolve_then_finalize_reaches_depth_four(self, api):
        """PRD 3.9: "Entering `DISSOLVING` records the `dissolution_reason`,
        sets the pod's `posture` to `CLOSED`, and fires a five-fold cascade
        in a single request: every `ENROLLED` seat moves to `WITHDRAWN` with
        `withdrawn_on` set to the current date; every guide assignment in
        `SCHEDULED` or `ACTIVE` moves to `TERMINATED_EARLY`; every
        `APPROVED` curriculum plan moves to `SUPERSEDED` — carrying the
        conference cancellations of §3.8 with it; a refund claim of kind
        `DISSOLUTION` is created for each withdrawn seat; and every voucher
        account linked to a withdrawn student is frozen to `FROZEN`, held
        pending refund reconciliation."
        PRD 3.9: "Finalization stamps `dissolved_at` with the current UTC
        instant, keeps the pod's `posture` at `CLOSED`, moves every
        `WITHDRAWN` seat to `RELEASED`, moves every family left with zero
        enrolled students to `INACTIVE`, increments the pod's `version`, and
        lands the pod in the terminal `DISSOLVED` state."

        Design: Difficulty/transitive_cascade/pod_dissolution_cascade_depth_4
        """
        ctx = setup_dissolving_pod(num_seats=1, clock="2026-09-01T00:00:00Z")
        pod = ctx["pod"]
        (family, student, seat) = ctx["seats"][0]
        assert pod["status"] == "DISSOLVING"
        assert pod["posture"] == "CLOSED"
        assert seat["seat_status"] == "WITHDRAWN", (
            f"cascade must withdraw enrolled seats, got {seat['seat_status']}"
        )
        assert student["student_status"] == "WITHDRAWN"
        # The family cascade is deferred to finalization.
        assert family["family_status"] == "ACTIVE"
        assert len(ctx["claims"]) == 1
        assert ctx["claims"][0]["claim_kind"] == "DISSOLUTION"

        decide_all_claims(pod["id"], ctx["claims"])
        finalized = validate_success(api.finalize_dissolution(pod["id"], ADMIN))
        assert finalized["status"] == "DISSOLVED"
        assert finalized["dissolved_at"] is not None

        seat_now = get_success_data(api.get_seat(seat["id"], REGISTRAR))
        assert seat_now["seat_status"] == "RELEASED", (
            f"finalization must release withdrawn seats, got "
            f"{seat_now['seat_status']}"
        )
        family_now = get_success_data(
            api.get_family(family["id"], make_family_headers(family["id"]))
        )
        assert family_now["family_status"] == "INACTIVE", (
            f"family with zero enrolled students must go INACTIVE, got "
            f"{family_now['family_status']}"
        )

    def test_dissolve_creates_one_dissolution_claim_per_seat(self, api):
        """PRD 3.9: "Entering `DISSOLVING` records the `dissolution_reason`,
        sets the pod's `posture` to `CLOSED`, and fires a five-fold cascade
        in a single request: every `ENROLLED` seat moves to `WITHDRAWN` with
        `withdrawn_on` set to the current date; every guide assignment in
        `SCHEDULED` or `ACTIVE` moves to `TERMINATED_EARLY`; every
        `APPROVED` curriculum plan moves to `SUPERSEDED` — carrying the
        conference cancellations of §3.8 with it; a refund claim of kind
        `DISSOLUTION` is created for each withdrawn seat; and every voucher
        account linked to a withdrawn student is frozen to `FROZEN`, held
        pending refund reconciliation."

        Design: Difficulty/transitive_cascade/pod_dissolution_cascade_depth_4
        """
        ctx = setup_dissolving_pod(num_seats=3, clock="2026-09-01T00:00:00Z")
        pod = ctx["pod"]
        assert pod["status"] == "DISSOLVING"
        claims = ctx["claims"]
        assert len(claims) == 3, (
            f"one DISSOLUTION claim per withdrawn seat: expected 3, got "
            f"{len(claims)}"
        )
        claim_seats = {c["seat_id"] for c in claims}
        seat_ids = {seat["id"] for (_, _, seat) in ctx["seats"]}
        assert claim_seats == seat_ids
        for (_, student, seat) in ctx["seats"]:
            assert seat["seat_status"] == "WITHDRAWN"
            assert student["student_status"] == "WITHDRAWN"


class TestDissolutionRefundWaterfall:
    def _setup_waterfall_pod(self, api):
        """ACTIVE pod with three seats enrolled at term start, each paid its
        full-year tuition: seat_V via VOUCHER (verified account), seats F1
        and F2 via FAMILY. Dissolution runs at clock day 2027-03-09 (day 250
        of the 304-day term), so the refund pool is positive but smaller
        than the total voucher-paid bucket."""
        set_clock("2026-08-01T00:00:00Z")
        pod, site, policy, plan, det, guide, assignment = setup_pod_active()

        # Voucher-funded seat.
        from test_helpers.fixtures import (
            create_family, create_student, create_voucher_account,
        )
        fam_v = create_family()
        stu_v = create_student(fam_v["id"])
        tuition = pod["tuition_full_year_cents"]
        # The award must cover the full-tuition voucher disbursement
        # (PRD 3.7 voucher-funds check), and each invoice's total must cover
        # the full-tuition payment (PRD 3.7 overpayment ceiling on cleared
        # payments), so invoices are priced at the full-year tuition.
        tuition_lines = [{
            "description": "Full-year tuition", "quantity": 1,
            "unit_amount_cents": tuition, "kind": "TUITION",
        }]
        voucher = create_voucher_account(
            stu_v["id"], awarded_annual_cents=2 * tuition,
        )
        voucher = get_success_data(api.verify_voucher_account(voucher["id"], OFFICER))
        seat_v = get_success_data(api.create_seat(
            pod["id"], {"student_id": stu_v["id"], "enrolled_on": "2026-08-01"},
            REGISTRAR,
        ))
        seat_v = enroll_seat(pod["id"], seat_v, fam_v["id"])

        inv_v = create_issued_invoice(
            pod["id"], seat_v["id"], line_items=tuition_lines,
        )
        post_and_clear_payment(
            pod["id"], seat_v["id"], inv_v["id"], amount_cents=tuition,
            source_kind="VOUCHER", voucher_account_id=voucher["id"],
        )

        # Two family-funded seats.
        seats_f = []
        for _ in range(2):
            fam = create_family()
            stu = create_student(fam["id"])
            seat = get_success_data(api.create_seat(
                pod["id"],
                {"student_id": stu["id"], "enrolled_on": "2026-08-01"},
                REGISTRAR,
            ))
            seat = enroll_seat(pod["id"], seat, fam["id"])
            inv = create_issued_invoice(
                pod["id"], seat["id"], line_items=tuition_lines,
            )
            post_and_clear_payment(
                pod["id"], seat["id"], inv["id"], amount_cents=tuition,
                source_kind="FAMILY",
            )
            seats_f.append(seat)

        return pod, seat_v, voucher, seats_f

    def test_voucher_bucket_fills_before_family_bucket(self, api):
        """PRD 3.9: "Distribution follows a fixed waterfall, each bucket
        filling before overflow reaches the next: first, voucher-program
        reimbursements, shared pro-rata by voucher-paid cents and capped at
        the total voucher-paid amount; then family direct-paid refunds,
        shared pro-rata by family-paid cents; finally scholarship fund
        returns."

        Design: Difficulty/combinatorial_formula/dissolution_refund_pool_waterfall
        """
        pod, seat_v, voucher, seats_f = self._setup_waterfall_pod(api)
        set_clock("2027-03-09T00:00:00Z")
        pod_v = get_pod_version(pod["id"])
        pod = validate_success(api.dissolve_pod(
            pod["id"],
            {"expected_pod_version": pod_v,
             "dissolution_reason": "operator withdrawal"},
            OPERATOR,
        ))
        assert pod["status"] == "DISSOLVING"
        assert pod["posture"] == "CLOSED"

        claims = list_dissolution_claims(pod["id"])
        assert len(claims) == 3, (
            f"expected exactly 3 DISSOLUTION claims, got {len(claims)}"
        )
        by_seat = {c["seat_id"]: c for c in claims}
        voucher_claim = by_seat[seat_v["id"]]
        family_claims = [by_seat[s["id"]] for s in seats_f]

        # The pool is positive but smaller than the voucher-paid bucket, so
        # the waterfall fills bucket 1 first and leaves nothing for bucket 2.
        assert voucher_claim["claimed_amount_cents"] > 0
        for fc in family_claims:
            assert fc["claimed_amount_cents"] == 0, (
                "voucher bucket must be filled in full before any "
                f"family-direct refund; got {fc['claimed_amount_cents']}"
            )

        # The cascade freezes the linked voucher account.
        va = get_success_data(api.get_voucher_account(voucher["id"], OFFICER))
        assert va["funding_status"] == "FROZEN"

    def test_dissolution_creates_one_claim_per_withdrawn_seat(self, api):
        """PRD 3.9: "Entering `DISSOLVING` records the `dissolution_reason`,
        sets the pod's `posture` to `CLOSED`, and fires a five-fold cascade
        in a single request: every `ENROLLED` seat moves to `WITHDRAWN` with
        `withdrawn_on` set to the current date; every guide assignment in
        `SCHEDULED` or `ACTIVE` moves to `TERMINATED_EARLY`; every
        `APPROVED` curriculum plan moves to `SUPERSEDED` — carrying the
        conference cancellations of §3.8 with it; a refund claim of kind
        `DISSOLUTION` is created for each withdrawn seat; and every voucher
        account linked to a withdrawn student is frozen to `FROZEN`, held
        pending refund reconciliation."

        Design: Difficulty/combinatorial_formula/dissolution_refund_pool_waterfall
        """
        pod, seat_v, voucher, seats_f = self._setup_waterfall_pod(api)
        set_clock("2027-03-09T00:00:00Z")
        pod_v = get_pod_version(pod["id"])
        pod = validate_success(api.dissolve_pod(
            pod["id"],
            {"expected_pod_version": pod_v,
             "dissolution_reason": "operator withdrawal"},
            OPERATOR,
        ))
        assert pod["status"] == "DISSOLVING"
        assert pod["posture"] == "CLOSED"

        claims = list_dissolution_claims(pod["id"])
        assert len(claims) == 3, (
            f"one DISSOLUTION claim per withdrawn seat: expected 3, got "
            f"{len(claims)}"
        )
        expected_seats = {seat_v["id"]} | {s["id"] for s in seats_f}
        assert {c["seat_id"] for c in claims} == expected_seats
        for c in claims:
            assert c["claim_kind"] == "DISSOLUTION"
            assert c["claim_status"] == "FILED"
        # Every claim amount is a non-negative integer number of cents (the
        # pool is floored at zero).
        for c in claims:
            assert isinstance(c["claimed_amount_cents"], int)
            assert c["claimed_amount_cents"] >= 0

    def test_dissolution_claim_pricing_and_voucher_freeze(self, api):
        """PRD 3.9: "The gross collected is the sum of `paid_cents` across
        the seats the cascade withdrew. The earned-through-dissolution
        figure is the sum, over those same seats, of each seat's prorated
        tuition measured from its `enrolled_on` through the pod's
        `dissolved_at` date under the daily convention. The pool is the
        excess of gross collected over earned, floored at zero."

        Design: Corner/calculations/dissolution_refund_pool_waterfall_order
        """
        pod, seat_v, voucher, seats_f = self._setup_waterfall_pod(api)
        set_clock("2027-03-09T00:00:00Z")
        pod_v = get_pod_version(pod["id"])
        validate_success(api.dissolve_pod(
            pod["id"],
            {"expected_pod_version": pod_v,
             "dissolution_reason": "operator withdrawal"},
            OPERATOR,
        ))
        claims = list_dissolution_claims(pod["id"])
        by_seat = {c["seat_id"]: c for c in claims}
        total_claimed = sum(c["claimed_amount_cents"] for c in claims)

        # The pool is capped below the voucher-paid total by construction,
        # so every claim cent lands in the voucher bucket.
        assert total_claimed == by_seat[seat_v["id"]]["claimed_amount_cents"]
        assert total_claimed > 0
        # And the pool cannot exceed the voucher-paid cap (the whole pool is
        # smaller than the voucher bucket), hence equals the voucher claim.
        va = get_success_data(api.get_voucher_account(voucher["id"], OFFICER))
        assert va["funding_status"] == "FROZEN", (
            "every voucher account linked to a withdrawn student is frozen "
            f"to FROZEN, got {va['funding_status']}"
        )
