"""One execution whose response already carries every derived change it caused."""

from test_helpers import constants as C
from test_helpers import fixtures as S
from test_helpers.api_client import ApiClient
from test_helpers.assertions import assert_fields, assert_instant, assert_money, ok

AGREED_MONTHLY_RENT_USD = 2512.50
PROVISIONAL_TOTAL_USD = 160070.45
FINAL_TOTAL_USD = 588795.12


def test_the_execute_response_already_shows_the_final_rent_and_the_derived_states(
    api: ApiClient,
) -> None:
    """Execution returns the updated lease, and the reads behind it agree at once.

    PRD: "Unless otherwise noted, operations that create or modify a resource will return
    the created or updated resource object in the data field."

    PRD: "On success the supplied `execution_date` is stored, the final committed-rent
    variant is computed into `committed_rent_final_usd`, the lease moves `ACCEPTED →
    EXECUTED`, the candidate's `acquisition_status` advances `LANDLORD_ENGAGED →
    LEASE_EXECUTED`, and the landlord's `executed_lease_count` is recomputed."

    PRD: "The **final** variant, written to `committed_rent_final_usd` at execution,
    assumes every renewal option is exercised: its horizon is `initial_term_years` plus
    `renewal_option_count` multiplied by `renewal_term_years`, it sums the rounded years 1
    through that horizon and rounds the sum to two decimal places to obtain a base total,
    then computes a revenue-share uplift as that base total multiplied by
    `revenue_share_pct` rounded half up to two decimal places, and finally stores the base
    total plus the uplift, again rounded half up to two decimal places."

    PRD: "On acceptance the agreed figure becomes the lease's economics —
    `base_monthly_rent_usd` is overwritten with `last_counter_rent_usd` — and the
    provisional variant of the committed rent is computed and stored in
    `committed_rent_provisional_usd`."

    PRD: "A landlord's `standing` starts at `ACTIVE` and its `executed_lease_count` at 0."

    Design: Corner/consistency model/corner_execute_response_reflects_all_derived_changes_immediately
    """
    chain = S.engaged_candidate(api)
    lease = S.create_lease(
        api,
        chain["cand_id"],
        chain["ll_id"],
        base_monthly_rent_usd=AGREED_MONTHLY_RENT_USD,
    )
    accepted = S.accept_lease(api, lease["id"], opening_counter=AGREED_MONTHLY_RENT_USD)
    assert_fields(accepted, status="ACCEPTED", escalation_type=C.LEASE_ESCALATION_TYPE)
    assert_money(
        accepted["committed_rent_provisional_usd"],
        PROVISIONAL_TOTAL_USD,
        "committed_rent_provisional_usd",
    )

    executed = ok(
        api.execute_lease(
            lease["id"], {"execution_date": C.CLOCK_DEFAULT}, headers=S.director()
        )
    )
    assert_fields(executed, status="EXECUTED")
    assert_money(
        executed["committed_rent_final_usd"], FINAL_TOTAL_USD, "committed_rent_final_usd"
    )
    assert_money(
        executed["committed_rent_provisional_usd"],
        PROVISIONAL_TOTAL_USD,
        "committed_rent_provisional_usd",
    )
    assert_instant(executed["execution_date"], C.CLOCK_DEFAULT, "execution_date")

    candidate = ok(api.get_candidate(chain["cand_id"], headers=S.director()))
    assert_fields(candidate, acquisition_status="LEASE_EXECUTED")

    landlord = ok(api.get_landlord(chain["ll_id"], headers=S.director()))
    assert_fields(landlord, executed_lease_count=1, standing="ACTIVE")
