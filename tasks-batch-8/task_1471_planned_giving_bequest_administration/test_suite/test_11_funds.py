"""Donor-intent funds: uniqueness per agreement and the activation minimum."""
from test_helpers import (
    ApiErrorId,
    assert_fund,
    make_active_rate_table,
    make_donor,
    make_draft_agreement,
    make_fund,
    validate_error,
    validate_success,
)


def _draft_bequest():
    donor = make_donor(full_name="Fund Donor")
    make_active_rate_table()
    return make_draft_agreement(
        donor["id"], vehicle_type="BEQUEST", gift_amount_cents=5000000
    )


class TestFundUniqueness:
    def test_fund_already_exists_rejected(self, api, finance_steward_headers):
        """PRD §3.8: "A fund is born `PROPOSED` with a zero balance, and at
        most one non-`CLOSED` fund may exist per agreement — a duplicate is
        rejected with `ERR_FUND_ALREADY_EXISTS` (HTTP 409)."

        Design: Corner/validations/fund_already_exists_rejected
        """
        agreement = _draft_bequest()
        first = validate_success(
            api.create_fund(
                {
                    "name": "First",
                    "restriction_type": "RESEARCH",
                    "gift_agreement_id": agreement["id"],
                },
                finance_steward_headers,
            ),
            201,
        )
        assert_fund(first)
        assert first["status"] == "PROPOSED"
        assert first["balance_cents"] == 0

        resp = api.create_fund(
            {
                "name": "Second",
                "restriction_type": "CAPITAL",
                "gift_agreement_id": agreement["id"],
            },
            finance_steward_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FUND_ALREADY_EXISTS)
        assert resp.status_code == 409


class TestFundActivationMinimum:
    def test_fund_minimum_not_met_rejected(self, api, finance_steward_headers):
        """PRD §3.8: "`ACTIVATE` moves a `PROPOSED` or `ENDOWED` fund to
        `ACTIVE` and requires the balance to meet the endowment minimum, else
        `ERR_FUND_MINIMUM_NOT_MET` (HTTP 409)".
        PRD §3.8: "an optional `minimum_endowment_cents` defaulting to 2500000
        cents (twenty-five thousand dollars)".

        Design: Corner/validations/fund_minimum_not_met_rejected
        """
        agreement = _draft_bequest()
        fund = make_fund(agreement["id"], name="Below Min", restriction_type="RESEARCH")
        assert fund["minimum_endowment_cents"] == 2500000
        assert fund["balance_cents"] == 0

        resp = api.transition_fund(fund["id"], {"action": "ACTIVATE"}, finance_steward_headers)
        validate_error(resp, ApiErrorId.ERR_FUND_MINIMUM_NOT_MET)
        assert resp.status_code == 409
        after = validate_success(api.get_fund(fund["id"], finance_steward_headers))
        assert after["status"] == "PROPOSED"
