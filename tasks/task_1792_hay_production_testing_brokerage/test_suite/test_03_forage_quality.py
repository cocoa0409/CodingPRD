"""Forage testing and quality certification: tier thresholds, moisture cap,
retest cycle, and segregation of duties.

Covers PRD §3.4 (forage testing pipeline and tier assignment).
"""
from test_helpers import (
    TEST_USERS,
    api_client,
    get_lot,
    make_tech_headers,
    setup_certified_lot,
    setup_lot,
    validate_error,
    validate_success,
)
from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import TECH_CERTIFIER, TECH_RECORDER
from test_helpers.factories import (
    create_forage_test_payload,
    record_result_payload,
    submit_forage_test_payload,
)

OPS = TEST_USERS["ops_headers"]


# ===========================================================================
# combinatorial_formula / quality_tier_moisture_cap_interaction
# ===========================================================================

class TestQualityTierMoistureCapInteraction:
    def test_moisture_above_cap_drags_supreme_to_fair(self, api):
        """PRD §3.4: "A moisture cap then applies: when the certified
        `moisture_pct` exceeds 16.0 and the base tier was `SUPREME`,
        `PREMIUM`, or `GOOD`, the tier is dragged down to `FAIR`".

        rfv 190.0 yields a SUPREME base, but moisture 16.5 exceeds the cap,
        so the certified lot lands at FAIR.

        Design: Difficulty/combinatorial_formula/quality_tier_moisture_cap_interaction
        """
        ctx = setup_certified_lot(rfv=190.0, protein_pct=21.5, moisture_pct=16.5)
        assert get_lot(ctx["lot"]["id"])["quality_tier"] == "FAIR"

    def test_moisture_exactly_at_cap_keeps_supreme(self, api):
        """PRD §3.4: "a moisture of exactly 16.0 does not trigger the cap."
        PRD §3.4: "the lot's `quality_tier` becomes the tier derived from the
        certified numbers, and its `certified_protein_pct` becomes the
        certified `protein_pct`."

        rfv 190.0 with moisture exactly 16.0 stays SUPREME; the lot also
        carries certified_protein_pct 21.5 (protein is recorded but does not
        lift the cap).

        Design: Difficulty/combinatorial_formula/quality_tier_moisture_cap_interaction
        """
        ctx = setup_certified_lot(rfv=190.0, protein_pct=21.5, moisture_pct=16.0)
        lot = get_lot(ctx["lot"]["id"])
        assert lot["quality_tier"] == "SUPREME"
        assert lot["certified_protein_pct"] == 21.5


# ===========================================================================
# boundary_precision_check / rfv_tier_boundary_exactly_170
# ===========================================================================

class TestRfvTierBoundaryExactly170:
    def test_rfv_exactly_170_lands_premium(self, api):
        """PRD §3.4: "at least 170 but below 185 yields `PREMIUM`, with an
        `rfv` of exactly 170.0 landing on `PREMIUM`".

        Design: Difficulty/boundary_precision_check/rfv_tier_boundary_exactly_170
        """
        ctx = setup_certified_lot(rfv=170.0, protein_pct=18.0, moisture_pct=14.0)
        assert get_lot(ctx["lot"]["id"])["quality_tier"] == "PREMIUM"

    def test_rfv_just_below_170_falls_to_good(self, api):
        """PRD §3.4: "at least 150 yields `GOOD`". PRD §3.4: "A relative feed
        value of at least 185 yields a base tier of `SUPREME`; at least 170
        but below 185 yields `PREMIUM`".

        rfv 169.9 misses the 170 boundary by one tenth and certifies GOOD.

        Design: Difficulty/boundary_precision_check/rfv_tier_boundary_exactly_170
        """
        ctx = setup_certified_lot(rfv=169.9, protein_pct=18.0, moisture_pct=14.0)
        assert get_lot(ctx["lot"]["id"])["quality_tier"] == "GOOD"


# ===========================================================================
# non_linear_state_machine / forage_test_retest_cycle
# ===========================================================================

class TestForageTestRetestCycle:
    def _collect_and_result(self, rfv, protein, moisture):
        """Lot + test driven COLLECTED -> SUBMITTED -> RESULTED by tech-1."""
        ctx = setup_lot()
        test = validate_success(api_client.create_forage_test(
            create_forage_test_payload(ctx["lot"]["id"]), OPS,
        ), expected_status=201)
        validate_success(api_client.submit_forage_test(
            test["id"], submit_forage_test_payload(),
            make_tech_headers(TECH_RECORDER),
        ))
        validate_success(api_client.record_forage_result(
            test["id"],
            record_result_payload(
                rfv=rfv, protein_pct=protein, moisture_pct=moisture,
            ),
            make_tech_headers(TECH_RECORDER),
        ))
        return ctx, test

    def test_resubmission_clears_prior_result(self, api):
        """PRD §3.4: "When a test is resubmitted from `RESULTED`, its prior
        result fields — `rfv`, `protein_pct`, `moisture_pct`, and
        `resulted_by_user_id` — are cleared to null, because the old numbers
        no longer describe a sample still at the lab."

        Design: Difficulty/non_linear_state_machine/forage_test_retest_cycle
        """
        _ctx, test = self._collect_and_result(140.0, 16.0, 14.0)
        resubmitted = validate_success(api_client.submit_forage_test(
            test["id"], submit_forage_test_payload(),
            make_tech_headers(TECH_RECORDER),
        ))
        assert resubmitted["status"] == "SUBMITTED"
        assert resubmitted["rfv"] is None
        assert resubmitted["protein_pct"] is None
        assert resubmitted["moisture_pct"] is None
        assert resubmitted["resulted_by_user_id"] is None

    def test_retest_certify_writes_second_result_tier(self, api):
        """PRD §3.4: "submission is permitted from `COLLECTED` or from
        `RESULTED` (the retest loop)". PRD §3.4: "the lot's `quality_tier`
        becomes the tier derived from the certified numbers".

        The first result (rfv 140.0 -> FAIR base) is discarded through
        resubmission; the second result (rfv 176.0 -> PREMIUM) is certified
        and the lot takes PREMIUM, not the first attempt's tier.

        Design: Difficulty/non_linear_state_machine/forage_test_retest_cycle
        """
        ctx, test = self._collect_and_result(140.0, 16.0, 14.0)
        validate_success(api_client.submit_forage_test(
            test["id"], submit_forage_test_payload(),
            make_tech_headers(TECH_RECORDER),
        ))
        validate_success(api_client.record_forage_result(
            test["id"],
            record_result_payload(rfv=176.0, protein_pct=19.5, moisture_pct=13.0),
            make_tech_headers(TECH_RECORDER),
        ))
        certified = validate_success(api_client.certify_forage_test(
            test["id"], make_tech_headers(TECH_CERTIFIER),
        ))
        assert certified["status"] == "CERTIFIED"
        assert get_lot(ctx["lot"]["id"])["quality_tier"] == "PREMIUM"


# ===========================================================================
# Corner/state_machines / certify_from_submitted_rejected
# ===========================================================================

def test_certify_from_submitted_rejected(api):
    """PRD §3.4: "Certification then moves a `RESULTED` test to `CERTIFIED`
    under two further guards". PRD §2.6: "State-machine guards, including
    the optimistic-concurrency stale-version check: the from-state must
    match the attempted transition". Every forage-test transition names the
    same from-state rejection — e.g. submit "from any other state is
    rejected with `ERR_TEST_WRONG_STATE`" (PRD §3.4).

    A SUBMITTED test has no recorded result, so certification fails and the
    test stays SUBMITTED.

    Design: Corner/state_machines/certify_from_submitted_rejected
    """
    ctx = setup_lot()
    test = validate_success(api_client.create_forage_test(
        create_forage_test_payload(ctx["lot"]["id"]), OPS,
    ), expected_status=201)
    validate_success(api_client.submit_forage_test(
        test["id"], submit_forage_test_payload(), make_tech_headers(TECH_RECORDER),
    ))
    resp = api_client.certify_forage_test(
        test["id"], make_tech_headers(TECH_CERTIFIER),
    )
    validate_error(resp, ApiErrorId.ERR_TEST_WRONG_STATE)
    read = validate_success(api_client.get_forage_test(test["id"], OPS))
    assert read["status"] == "SUBMITTED"


# ===========================================================================
# Corner/validations / segregation_of_duties_enforced
# ===========================================================================

def test_segregation_of_duties_enforced(api):
    """PRD §3.4: "the segregation-of-duties rule forbids the certifier from
    being the same user who recorded the result — the acting `X-User-ID` must
    differ from the test's `resulted_by_user_id`, otherwise the certification
    is rejected with `ERR_SEGREGATION_OF_DUTIES`."

    The recording technician's certification attempt is rejected; a different
    technician certifies successfully.

    Design: Corner/validations/segregation_of_duties_enforced
    """
    ctx = setup_lot()
    test = validate_success(api_client.create_forage_test(
        create_forage_test_payload(ctx["lot"]["id"]), OPS,
    ), expected_status=201)
    validate_success(api_client.submit_forage_test(
        test["id"], submit_forage_test_payload(), make_tech_headers(TECH_RECORDER),
    ))
    validate_success(api_client.record_forage_result(
        test["id"], record_result_payload(rfv=160.0, protein_pct=18.0,
                                          moisture_pct=14.0),
        make_tech_headers(TECH_RECORDER),
    ))
    resp = api_client.certify_forage_test(
        test["id"], make_tech_headers(TECH_RECORDER),
    )
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
    certified = validate_success(api_client.certify_forage_test(
        test["id"], make_tech_headers(TECH_CERTIFIER),
    ))
    assert certified["status"] == "CERTIFIED"
