"""Every derived field is already in the body of the request that changed it.

There is nothing to poll for and nothing to retry. The patch that lowers an assessment
returns the recomputed tax in its own response, and the screen that reserves a home
returns the whole deposit group while the very next read of the home already shows the
cascade.
"""

from test_helpers import fixtures as x
from test_helpers.assertions import (
    assert_fields,
    assert_money_group,
    assert_version,
    ok,
)
from test_helpers.constants import (
    APP_CONDITIONAL_APPROVED,
    CLOCK_AUG_01,
    OCC_RESERVED,
    POSTURE_RESTRICTED,
)


def test_the_patch_returns_the_new_tax_and_the_screen_returns_the_whole_deposit_group(api):
    """Two mutations, four reads, and not one figure that needed a second request to appear.

    PRD SS2.9: "The rule is that every cascade completes inside the originating request --
    consistency is immediate, never eventual -- and every row the cascade touches has its
    `updated_at` refreshed and its `version` incremented by 1."  PRD SS2.2 says where to look for
    it: "Unless otherwise noted, operations that create or modify a resource will return the created
    or updated resource object in the data field."  The recomputed tax is PRD SS3.1's: "Its
    `property_tax_annual_cents` is computed immediately as the home's `assessed_value_cents`
    multiplied by the market's `millage_bps`, divided by 10,000 and rounded half up, and it is
    recomputed whenever `assessed_value_cents` changes for any reason."  The screen's own figures are
    PRD SS3.8's worked example: "an applicant with a verified income of 560000, credit `B`, no
    evictions, a fraud score of 1093 and one pet has a `rent_to_income_bps` of 3839, misses clauses 1
    through 4 on the credit tier alone, and lands in clause 5 as `CONDITIONAL_APPROVED` with a
    multiplier of 15000, a `security_deposit_cents` of 322500, a `pet_deposit_cents` of 30000 and a
    `total_move_in_deposit_cents` of 352500."  The home moves in the same breath -- PRD SS3.8: "Both
    approval outcomes then cascade the home's `occupancy_status` `VACANT` -> `RESERVED`" -- while the
    posture is decided by clause 5 of PRD SS2.8: "if `asset_status` is `PIPELINE` or `ACQUIRED`, the
    posture is `RESTRICTED`."

    Design: Corner/consistency_model/mutation_responses_already_contain_every_derived_field
    """
    x.set_clock(api, CLOCK_AUG_01)
    market = x.create_market(api)
    home = x.create_home(api, market["id"])
    assert_money_group(
        home, assessed_value_cents=28000000, property_tax_annual_cents=350000
    )

    prospect = x.verified_prospect(api, market["id"])
    application = x.submitted_application(
        api, home["id"], prospect.prospect_id, requested_move_in_date="2026-10-01"
    )

    reassessed = ok(
        api.patch_home(home["id"], {"assessed_value_cents": 24800000}, x.ANALYST)
    )
    assert_money_group(
        reassessed, assessed_value_cents=24800000, property_tax_annual_cents=310000
    )
    assert_version(reassessed, 2)
    assert_money_group(
        ok(api.get_home(home["id"], x.ANALYST)), property_tax_annual_cents=310000
    )

    screened = ok(api.screen_rental_application(application["id"], {}, x.AGENT))
    assert_fields(
        screened,
        status=APP_CONDITIONAL_APPROVED,
        rent_to_income_bps=3839,
        risk_multiplier_bps=15000,
    )
    assert_money_group(
        screened,
        security_deposit_cents=322500,
        pet_deposit_cents=30000,
        total_move_in_deposit_cents=352500,
    )

    reserved = ok(api.get_home(home["id"], x.AGENT))
    assert_fields(
        reserved, occupancy_status=OCC_RESERVED, leasing_posture=POSTURE_RESTRICTED
    )
