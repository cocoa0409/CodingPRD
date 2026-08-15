"""Title reviews and exceptions: the FATAL cascade, the exception-count
invariant under cure/supersede, posture reconciliation, and certify gate
ordering."""
from test_helpers import (
    ApiErrorId,
    complete_all_open_milestones,
    create_estoppel_payload,
    create_title_review_under_review,
    cure_exception,
    get_deal,
    raise_title_exception,
    setup_psa_executed,
    validate_error,
    validate_success,
)


def _setup_under_review(deal_name="CascadeDeal", **kwargs):
    """Deal at PSA_EXECUTED plus a title review in UNDER_REVIEW."""
    defaults = dict(purchase_price_cents=18000000,
                    lease_rent_cents=1100000, lease_type="ABSOLUTE_NET",
                    lease_expiration="2034-06-01T00:00:00Z",
                    dd_period_days=40, financing_contingency_days=30,
                    property_overrides={"address": "7 Cascade Rd",
                                        "property_type": "MEDICAL",
                                        "rentable_sqft": 15000,
                                        "year_built": 2008})
    defaults.update(kwargs)
    ctx = setup_psa_executed(deal_name=deal_name, **defaults)
    review = create_title_review_under_review(ctx["deal"]["id"],
                                              "CascadeTitle")
    return ctx, review


class TestFatalExceptionCascade:
    def test_fatal_title_exception_cascade_depth3_from_exception_raise(
            self, api, dd_officer_headers):
        """PRD §3.6: "Raising the first exception flips the review to
        `EXCEPTIONS_RAISED`, increments the review's `exception_count` —
        which counts linked exceptions in any non-resolved state — and, when
        the severity is `FATAL`, drops the deal posture to `DD_BLOCKED`."

        Design: Difficulty/transitive_cascade/fatal_title_exception_cascade_depth3_from_exception_raise
        """
        ctx, review = _setup_under_review()
        deal_id = ctx["deal"]["id"]
        assert get_deal(deal_id)["posture"] == "DD_OPEN"

        exception = validate_success(api.create_title_exception(
            deal_id, review["id"],
            {"exception_code": "B2-104", "severity": "FATAL",
             "description": "Unreleased prior mortgage lien",
             "cure_cost_cents": 5000000},
            dd_officer_headers), 201)
        assert exception["status"] == "OPEN"

        review_after = validate_success(
            api.get_title_review(deal_id, review["id"], dd_officer_headers))
        assert review_after["status"] == "EXCEPTIONS_RAISED", (
            "Link 1: raising the exception mutates the review")
        assert review_after["exception_count"] == 1

        deal_after = get_deal(deal_id)
        assert deal_after["posture"] == "DD_BLOCKED", (
            "Link 2: the review mutation recomputes the deal posture")

    def test_fatal_exception_blocks_certify_clear_to_close(
            self, api, committee_headers, dd_officer_headers):
        """PRD §3.10: "no title exception may sit in `OPEN` or
        `CURE_PROPOSED` with severity `FATAL` (else
        `ERR_FATAL_TITLE_EXCEPTION`)"

        Design: Difficulty/transitive_cascade/fatal_title_exception_cascade_depth3_from_exception_raise
        """
        ctx, review = _setup_under_review()
        deal_id = ctx["deal"]["id"]
        raise_title_exception(deal_id, review["id"], exception_code="B2-104",
                              severity="FATAL",
                              description="Unreleased prior mortgage lien",
                              cure_cost_cents=5000000)

        # Link 3: with every milestone satisfied, the open FATAL exception is
        # the surviving gate and blocks certification.
        complete_all_open_milestones(deal_id)
        resp = api.certify_clear_to_close(deal_id, committee_headers)
        validate_error(resp, ApiErrorId.ERR_FATAL_TITLE_EXCEPTION)


class TestExceptionCountInvariant:
    def _setup_standard_exception(self):
        ctx, review = _setup_under_review(deal_name="InvariantDeal1")
        exception = raise_title_exception(
            ctx["deal"]["id"], review["id"], exception_code="B2-301",
            severity="STANDARD", description="Minor utility easement",
            cure_cost_cents=10000)
        return ctx, review, exception

    def test_raise_then_cure_restores_exception_count(
            self, api, dd_officer_headers):
        """PRD §3.6: "Raising the first exception flips the review to
        `EXCEPTIONS_RAISED`, increments the review's `exception_count`"
        PRD §3.6: "A confirmed cure moves the exception to `CURED`,
        decrements the review's `exception_count`"

        Design: Difficulty/compensating_invariant/title_exception_count_invariant_under_cure_and_supersede
        """
        ctx, review, exception = self._setup_standard_exception()
        deal_id = ctx["deal"]["id"]

        after_raise = validate_success(api.get_title_review(
            deal_id, review["id"], dd_officer_headers))
        assert after_raise["exception_count"] == 1, (
            "Forward action: raising the exception increments the count")

        cured = cure_exception(deal_id, review["id"], exception["id"])
        assert cured["status"] == "CURED"
        after_cure = validate_success(api.get_title_review(
            deal_id, review["id"], dd_officer_headers))
        assert after_cure["exception_count"] == 0, (
            "Compensating action: the cure restores the count to zero")

    def test_supersede_cycle_preserves_exception_count(
            self, api, dd_officer_headers):
        """PRD §3.6: "When `cured_by_exception_id` is supplied and names a
        `CURED` exception, that referenced exception is superseded to
        `SUPERSEDED` as the new one opens."

        Design: Difficulty/compensating_invariant/title_exception_count_invariant_under_cure_and_supersede
        """
        ctx, review, ex1 = self._setup_standard_exception()
        deal_id = ctx["deal"]["id"]
        cure_exception(deal_id, review["id"], ex1["id"])

        ex2 = raise_title_exception(
            deal_id, review["id"], exception_code="B2-301-R",
            severity="STANDARD", description="Revised utility easement",
            cure_cost_cents=12000, cured_by_exception_id=ex1["id"])
        assert ex2["status"] == "OPEN"

        ex1_after = validate_success(api.get_title_exception(
            deal_id, review["id"], ex1["id"], dd_officer_headers))
        assert ex1_after["status"] == "SUPERSEDED"
        review_mid = validate_success(api.get_title_review(
            deal_id, review["id"], dd_officer_headers))
        assert review_mid["exception_count"] == 1, (
            "The superseded exception is resolved; only the revision counts")

        cure_exception(deal_id, review["id"], ex2["id"])
        review_final = validate_success(api.get_title_review(
            deal_id, review["id"], dd_officer_headers))
        assert review_final["exception_count"] == 0, (
            "The forward+compensating pair leaves the count unchanged")


class TestPostureReconciliation:
    def test_derived_field_reconciliation_posture_recompute(
            self, api, dd_officer_headers):
        """PRD §2.7: "Posture is never set directly by a client; it is
        recomputed whenever a contributing artifact changes state."
        PRD §3.6: "A confirmed cure moves the exception to `CURED`,
        decrements the review's `exception_count`, recomputes the deal
        posture — curing the last `FATAL` exception may lift the deal out of
        `DD_BLOCKED`"
        PRD §3.6: "Confirming a cure on a `MATERIAL` or `FATAL` exception
        whose `cure_cost_cents` exceeds 100,000 cents requires committee
        sign-off"

        Design: Corner/cross_cutting_layers/derived_field_reconciliation_posture_recompute
        """
        ctx, review = _setup_under_review(deal_name="DerivedDeal")
        deal_id = ctx["deal"]["id"]

        # 80,000 <= 100,000, so this FATAL cure needs no committee sign-off.
        exception = raise_title_exception(
            deal_id, review["id"], exception_code="B2-400", severity="FATAL",
            description="Access easement cuts through parcel",
            cure_cost_cents=80000)
        assert get_deal(deal_id)["posture"] == "DD_BLOCKED"

        cure_exception(deal_id, review["id"], exception["id"])
        assert get_deal(deal_id)["posture"] == "DD_OPEN", (
            "Clearing the blocking condition returns the posture to DD_OPEN")
        review_after = validate_success(api.get_title_review(
            deal_id, review["id"], dd_officer_headers))
        assert review_after["exception_count"] == 0


class TestCertifyGateSubOrdering:
    def test_fatal_exception_reported_before_estoppel_incompleteness(
            self, api, committee_headers, dd_officer_headers):
        """PRD §3.10: "every milestone must be `SATISFIED` or `WAIVED` (else
        `ERR_MILESTONES_OUTSTANDING`); no title exception may sit in `OPEN`
        or `CURE_PROPOSED` with severity `FATAL` (else
        `ERR_FATAL_TITLE_EXCEPTION`); every non-waived environmental
        assessment must be `CLEARED` or `CONDITIONAL` (else
        `ERR_ENVIRONMENTAL_UNRESOLVED`); all required estoppel certificates
        must be `CERTIFIED` (else `ERR_ESTOPPEL_INCOMPLETE`)"

        Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_referential_pair_on_estoppel_certify
        """
        ctx, review = _setup_under_review(deal_name="PriorityDeal2b")
        deal_id = ctx["deal"]["id"]
        raise_title_exception(deal_id, review["id"], exception_code="B2-201",
                              severity="FATAL",
                              description="Easement through building "
                                          "footprint",
                              cure_cost_cents=200000)
        # An estoppel is requested but never certified — both the title gate
        # and the estoppel gate are violated simultaneously.
        validate_success(api.create_estoppel(
            deal_id,
            create_estoppel_payload(ctx["lease"]["id"], ctx["tenant"]["id"],
                                    rent_confirmed_cents=1100000),
            dd_officer_headers), 201)

        complete_all_open_milestones(deal_id)
        resp = api.certify_clear_to_close(deal_id, committee_headers)
        validate_error(resp, ApiErrorId.ERR_FATAL_TITLE_EXCEPTION)
