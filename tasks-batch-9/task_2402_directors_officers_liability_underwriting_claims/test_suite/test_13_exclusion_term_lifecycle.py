"""Where a wording negotiation starts, and where it stops for good.

Every term opens on the insurer's side of the cycle, which is what makes the next
move belong to the other party; and once a term is agreed it is closed to both of
them, whichever of the two guards the acting role would otherwise clear.
"""

import pytest
from prd_bench_local_runner.testing import (
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ApiErrorId,
    UNDERWRITER,
    assert_exclusion_term,
    assert_money,
    counter_exclusion_term_payload,
    create_exclusion_term_payload,
    find_term,
    make_risk_manager_headers,
    read_exclusion_terms,
    read_quote,
    resolve_exclusion_term_payload,
    resolve_term_as_insured,
    setup_offered_quote,
)


def test_a_newly_opened_term_starts_proposed_on_the_insurer_side(api):
    """PRD 3.3: "Each newly opened term starts in `PROPOSED` with `round_count` 1 and
    both `proposed_by_role` and `last_actor_role` set to `Underwriter`." PRD 3.3:
    "Issuing a quote automatically opens one term for the insurer: `exclusion_type`
    `CONDUCT`, `wording_variant` `BROAD`, `premium_impact_pct` 0.00,
    `proposed_by_role` and `last_actor_role` both `Underwriter`, `status` `PROPOSED`
    and `round_count` 1." PRD 3.3: "`AGREE` moves the term to `AGREED` and freezes
    `agreed_variant` to whatever `wording_variant` was outstanding at that moment".

    Design: Corner/state_machines/exclusion_term_created_starts_proposed_round_one
    """
    scenario = setup_offered_quote()
    quote = scenario["quote"]
    insured_id = scenario["insured"]["id"]

    data = validate_success(
        api.create_exclusion_term(
            quote["id"],
            create_exclusion_term_payload(exclusion_type="INSURED_VS_INSURED",
                                          wording_variant="BROAD",
                                          premium_impact_pct=0.05),
            UNDERWRITER,
        ),
        201,
    )

    assert_exclusion_term(data)
    assert data["status"] == "PROPOSED"
    assert data["round_count"] == 1
    assert data["agreed_variant"] is None, "nothing is frozen until a resolve"
    assert data["version"] == 1
    assert data["proposed_by_role"] == "Underwriter"
    assert data["last_actor_role"] == "Underwriter", (
        "the next move has to come from the other party"
    )
    assert data["quote_id"] == quote["id"]
    assert data["premium_impact_pct"] == pytest.approx(0.05)

    terms, meta = validate_paginated(
        api.list_exclusion_terms(quote["id"], make_risk_manager_headers(insured_id),
                                 params={"limit": 10, "offset": 0})
    )
    assert meta["total_count"] == 2
    conduct = find_term(terms, "CONDUCT")
    assert conduct["wording_variant"] == "BROAD"
    assert conduct["premium_impact_pct"] == pytest.approx(0.00)
    assert conduct["status"] == "PROPOSED"
    assert conduct["round_count"] == 1
    assert conduct["last_actor_role"] == "Underwriter"
    assert find_term(terms, "INSURED_VS_INSURED")["id"] == data["id"]

    # The impact is only outstanding, so it reaches the premium at binding, not now.
    still_offered = read_quote(quote["id"])
    assert still_offered["status"] == "OFFERED"
    assert_money(still_offered["gross_premium_usd"], 236_468.57, "gross_premium_usd")
    assert_money(still_offered["gross_premium_usd"], quote["gross_premium_usd"],
                 "the quoted gross premium")


def test_an_agreed_term_is_closed_to_both_sides(api):
    """PRD 3.3: "A term may only be countered or resolved while its `status` is
    `PROPOSED` or `COUNTERED`; a term in `AGREED`, `REJECTED` or `IMPASSE` is terminal
    and any further action on it is refused with `ERR_INVALID_TERM_STATE`." The sibling
    guard may answer first on the same request: PRD 3.3 also requires that "the acting
    role must differ from `last_actor_role`", and PRD 2.7 ranks "Negotiation
    alternation — `ERR_TERM_ACTOR_SEQUENCE`" ahead of "Exclusion term state —
    `ERR_INVALID_TERM_STATE`". PRD 3.3 states which acts write `last_actor_role` — a
    counter "sets `last_actor_role` to the acting role", and the impasse counter sets
    it too — but says nothing about a resolve, so which of the two 409 rungs answers a
    post-resolve attempt is not fixed by the document; what is fixed is that the term
    is closed and that neither refusal writes anything.

    Design: Corner/state_machines/agreed_exclusion_term_rejects_further_counter
    """
    scenario = setup_offered_quote()
    insured_id = scenario["insured"]["id"]
    term_id = scenario["conduct_term"]["id"]

    agreed = resolve_term_as_insured(term_id, insured_id, "AGREE")
    assert agreed["status"] == "AGREED"
    assert agreed["agreed_variant"] == "BROAD"
    assert agreed["round_count"] == 1

    countered = api.counter_exclusion_term(
        term_id,
        counter_exclusion_term_payload(wording_variant="FINAL_ADJUDICATION",
                                       premium_impact_pct=0.03),
        UNDERWRITER,
    )
    validate_error_is_one_of(
        countered,
        [ApiErrorId.ERR_INVALID_TERM_STATE, ApiErrorId.ERR_TERM_ACTOR_SEQUENCE],
    )
    assert countered.status_code == 409

    resolved = api.resolve_exclusion_term(
        term_id, resolve_exclusion_term_payload("REJECT"), UNDERWRITER
    )
    validate_error_is_one_of(
        resolved,
        [ApiErrorId.ERR_INVALID_TERM_STATE, ApiErrorId.ERR_TERM_ACTOR_SEQUENCE],
    )
    assert resolved.status_code == 409

    after = find_term(read_exclusion_terms(scenario["quote"]["id"]), "CONDUCT")
    assert after["status"] == "AGREED", "an agreed term cannot be flipped to REJECTED"
    assert after["agreed_variant"] == "BROAD"
    assert after["wording_variant"] == "BROAD", "the refused counter left no wording"
    assert after["premium_impact_pct"] == pytest.approx(0.00)
    assert after["round_count"] == 1
    assert after["version"] == agreed["version"], "neither refusal was a write"
