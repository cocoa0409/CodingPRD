"""Immediate consistency: the response body of a write already carries every
figure the write's cascade recomputed, with no follow-up read required."""

from test_helpers import (
    approx2,
    approx4,
    create_cycle,
    create_matter,
    create_partner,
    create_verified_billable_hours,
    make_cycle_admin_headers,
    matter_financials_payload,
    matter_version,
    read_matter,
    read_partner,
    validate_success,
)


def test_every_cascade_is_visible_in_the_same_response_body(api):
    """PRD 2.9: "Consistency in this service is immediate, not eventual." "Every
    write that changes an input to a derived figure recomputes that figure, and
    every figure derived from *it*, before the response is produced."

    Design: Corner/consistency_model/every_cascade_is_visible_in_the_same_response_body
    """
    cycle = create_cycle(api)
    partner = create_partner(api, full_name="Ada Origin")
    matter = create_matter(api, billing_attorney_id=partner["id"])
    create_verified_billable_hours(
        api,
        partner_id=partner["id"],
        cycle_id=cycle["id"],
        matter_id=matter["id"],
        hours=10.00,
    )

    posted = validate_success(
        api.post_matter_financials(
            matter["id"],
            matter_financials_payload(
                matter_version(api, matter["id"]),
                billed_delta_cents=500_000,
                collected_delta_cents=400_000,
                direct_cost_delta_cents=100_000,
            ),
            make_cycle_admin_headers(),
        ),
        200,
    )
    assert posted["billed_cents"] == 500_000
    assert posted["collected_cents"] == 400_000
    assert posted["verified_billable_hours"] == approx2(10.00)
    assert posted["realization_pct"] == approx4(0.8000)
    assert posted["profitability_index_contribution"] == approx4(0.7500)
    assert posted["profitability_index_fully_loaded"] == approx4(0.5250)

    reread = read_matter(api, matter["id"])
    assert reread["realization_pct"] == approx4(0.8000)
    assert reread["profitability_index_contribution"] == approx4(0.7500)
    assert reread["profitability_index_fully_loaded"] == approx4(0.5250)
    assert reread["version"] == posted["version"]

    credited = read_partner(api, partner["id"])
    assert credited["credited_collection_provisional_cents"] == 240_000
    assert credited["verified_billable_hours"] == approx2(10.00)
