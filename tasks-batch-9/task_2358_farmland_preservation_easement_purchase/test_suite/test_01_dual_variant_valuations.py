"""Ranking bases and easement-value bases: the two-variant valuations.

Both calculations in this file admit two legitimate bases over identical stored
data, and reaching for the wrong one produces a plausible but wrong number.
"""

import pytest
from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    application_version,
    create_application_payload,
    create_parcel,
    issue_offer_payload,
    make_landowner_headers,
    parcel_version,
    patch_parcel_payload,
    read_application,
    read_parcel,
    setup_filed_application,
    setup_ranked_application,
)

ADMIN = TEST_USERS["program_admin_headers"]
OFFICER = TEST_USERS["acquisition_officer_headers"]


def _patch_contiguity(parcel_id: str, acres: float) -> dict:
    return validate_success(
        api_client.patch_parcel(
            parcel_id,
            patch_parcel_payload(
                parcel_version(parcel_id), contiguous_preserved_acres=acres
            ),
            ADMIN,
        )
    )


def _rank(round_id: str, score_basis: str) -> dict:
    validate_success(api_client.set_clock("2026-10-01T00:00:00Z"))
    return validate_success(
        api_client.rank_funding_round(round_id, {"score_basis": score_basis}, ADMIN)
    )


class TestCompositeScoreBasis:
    """The contiguity component reads a frozen snapshot or the live parcel."""

    def test_receipt_basis_scores_on_the_frozen_contiguity_snapshot(self):
        """Under RECEIPT_BASIS the contiguity component reads the frozen snapshot.

        PRD §3.3: "Under `RECEIPT_BASIS` the component reads the application's
        frozen `contiguity_acres_at_receipt`."

        Design: Difficulty/dual_variant_calc/composite_score_receipt_basis_versus_round_close_basis
        """
        scenario = setup_filed_application()
        parcel_id = scenario["parcel"]["id"]
        assert scenario["application"]["contiguity_acres_at_receipt"] == pytest.approx(
            80.00, abs=0.01
        )

        # A neighbouring easement doubles the parcel's live contiguity mid-round.
        _patch_contiguity(parcel_id, 160.00)

        rank = _rank(scenario["round"]["id"], "RECEIPT_BASIS")
        assert rank["ranked_count"] == 1

        application = read_application(scenario["application"]["id"])
        # soil 84.00 x 0.35 = 29.40, size 80 x 0.15 = 12.00,
        # contiguity 100 x min(1, 80/160) x 0.25 = 12.50, pressure 78.00 x 0.25 = 19.50
        assert application["composite_score"] == pytest.approx(73.40, abs=0.01)
        assert application["status"] == "RANKED"
        assert application["contiguity_acres_at_receipt"] == pytest.approx(
            80.00, abs=0.01
        )

    def test_round_close_basis_scores_on_the_live_parcel_contiguity(self):
        """Under ROUND_CLOSE_BASIS the contiguity component reads the live parcel.

        PRD §3.3: "Under `ROUND_CLOSE_BASIS` it reads the parcel's live
        `contiguous_preserved_acres` as it stands at the moment of the ranking
        call, which will have moved upward for any parcel whose neighbour was
        preserved during the round."

        Design: Difficulty/dual_variant_calc/composite_score_receipt_basis_versus_round_close_basis
        """
        scenario = setup_filed_application()
        parcel_id = scenario["parcel"]["id"]

        _patch_contiguity(parcel_id, 160.00)
        _rank(scenario["round"]["id"], "ROUND_CLOSE_BASIS")

        application = read_application(scenario["application"]["id"])
        # The contiguity component rises from 12.50 to 25.00, so the composite
        # rises by exactly 12.50 over the receipt-basis figure of 73.40.
        assert application["composite_score"] == pytest.approx(85.90, abs=0.01)
        # The snapshot itself is never rewritten by the patch.
        assert application["contiguity_acres_at_receipt"] == pytest.approx(
            80.00, abs=0.01
        )
        assert read_parcel(parcel_id)["contiguous_preserved_acres"] == pytest.approx(
            160.00, abs=0.01
        )

    def test_round_close_basis_caps_the_contiguity_component_at_one_hundred(self):
        """The live basis still caps the contiguity ratio at 1.

        PRD §3.3: "The contiguity component is 100 multiplied by the lesser of 1
        and the contiguity acreage divided by the parcel's `acres`."

        Design: Difficulty/dual_variant_calc/composite_score_receipt_basis_versus_round_close_basis
        """
        scenario = setup_filed_application()

        # 240 preserved acres against a 160-acre parcel is a ratio of 1.5.
        _patch_contiguity(scenario["parcel"]["id"], 240.00)
        _rank(scenario["round"]["id"], "ROUND_CLOSE_BASIS")

        application = read_application(scenario["application"]["id"])
        assert application["composite_score"] == pytest.approx(85.90, abs=0.01)

    def test_the_chosen_basis_is_recorded_on_the_round(self):
        """The nominated basis is stamped on the round itself.

        PRD §3.3: "The chosen basis is recorded on the round as `score_basis`."

        Design: Difficulty/dual_variant_calc/composite_score_receipt_basis_versus_round_close_basis
        """
        scenario = setup_filed_application()
        assert scenario["round"]["score_basis"] is None

        _rank(scenario["round"]["id"], "ROUND_CLOSE_BASIS")
        funding_round = validate_success(
            api_client.get_funding_round(scenario["round"]["id"], ADMIN)
        )
        assert funding_round["score_basis"] == "ROUND_CLOSE_BASIS"
        assert funding_round["status"] == "SELECTED"


class TestEasementValueBasis:
    """The preliminary assessor proxy and the certified appraisal basis."""

    def test_filing_stamps_the_floored_preliminary_assessor_proxy(self):
        """The preliminary value takes 90 percent of the spread and floors it.

        PRD §3.3: "Subtract the parcel's `restricted_value_cents` from its
        `unrestricted_value_cents` to get the gross spread; take 90 percent of
        that spread; then floor the result down to a whole multiple of 100,000
        cents, that is, down to the nearest thousand dollars."

        Design: Difficulty/dual_variant_calc/easement_value_preliminary_assessor_versus_certified_appraisal_basis
        """
        scenario = setup_filed_application()
        # spread 175,550,000; 90 percent is 157,995,000; floored to 157,900,000.
        assert scenario["application"]["preliminary_easement_value_cents"] == 157_900_000
        assert scenario["application"]["certified_easement_value_cents"] is None

    def test_certification_stamps_the_half_up_certified_basis_alongside_it(self):
        """Certification writes the certified basis and leaves the proxy alone.

        PRD §3.4: "Take the lesser of the gross spread and that ceiling. Divide
        by 10,000 cents, round half up to a whole number, and multiply back by
        10,000: in other words, round half up to the nearest hundred dollars."

        Design: Difficulty/dual_variant_calc/easement_value_preliminary_assessor_versus_certified_appraisal_basis
        """
        scenario = setup_ranked_application()
        application = scenario["application"]
        # min(175,550,000 spread, 1,200,000 x 160 acres = 192,000,000) rounded
        # half up to the nearest 10,000 cents is 175,550,000.
        assert application["certified_easement_value_cents"] == 175_550_000
        assert application["preliminary_easement_value_cents"] == 157_900_000
        assert (
            application["certified_easement_value_cents"]
            - application["preliminary_easement_value_cents"]
            == 17_650_000
        )

    def test_the_proxy_basis_alone_bounds_the_requested_price(self):
        """The request ceiling is the proxy times 1.10, admitting the boundary.

        PRD §3.3: "The landowner's `requested_price_cents` may not exceed that
        figure multiplied by 1.10 and rounded half up — a ten percent ask above
        the assessor proxy — and a higher request is rejected with
        `ERR_REQUESTED_PRICE_ABOVE_PRELIMINARY_CEILING`."

        Design: Difficulty/dual_variant_calc/easement_value_preliminary_assessor_versus_certified_appraisal_basis
        """
        scenario = setup_filed_application(
            application_overrides={"requested_price_cents": 173_690_000}
        )
        # 157,900,000 x 1.10 rounded half up is exactly 173,690,000.
        assert scenario["application"]["requested_price_cents"] == 173_690_000

        landowner_headers = make_landowner_headers(scenario["landowner"]["id"])
        twin = create_parcel(scenario["landowner"]["id"], county="Berks")
        over = api_client.create_application(
            create_application_payload(
                scenario["round"]["id"],
                twin["id"],
                scenario["landowner"]["id"],
                requested_price_cents=173_690_001,
            ),
            landowner_headers,
        )
        validate_error(
            over, ApiErrorId.ERR_REQUESTED_PRICE_ABOVE_PRELIMINARY_CEILING.value
        )

    def test_the_certified_basis_alone_bounds_the_offer(self):
        """Offers are bounded by the certified value, never by the proxy.

        PRD §3.5: "A `CERTIFIED` appraisal must already exist on the
        application, and `offer_cents` may not exceed the application's
        `certified_easement_value_cents`; either failure is reported as
        `ERR_OFFER_EXCEEDS_CERTIFIED_VALUE`."

        Design: Difficulty/dual_variant_calc/easement_value_preliminary_assessor_versus_certified_appraisal_basis
        """
        scenario = setup_ranked_application()
        application_id = scenario["application"]["id"]
        validate_success(api_client.set_clock("2026-10-05T00:00:00Z"))

        # One cent above the certified value is refused; the ceiling is probed
        # first because §2.11 puts the state rung above the certified-value rung.
        rejected = api_client.issue_offer(
            application_id,
            issue_offer_payload(
                application_version(application_id), 175_550_001, "FULL_PURCHASE"
            ),
            OFFICER,
        )
        validate_error(rejected, ApiErrorId.ERR_OFFER_EXCEEDS_CERTIFIED_VALUE.value)

        # 175,550,000 sits far above the 157,900,000 proxy and is still admitted.
        accepted = validate_success(
            api_client.issue_offer(
                application_id,
                issue_offer_payload(
                    application_version(application_id), 175_550_000, "FULL_PURCHASE"
                ),
                OFFICER,
            )
        )
        assert accepted["current_offer_cents"] == 175_550_000
