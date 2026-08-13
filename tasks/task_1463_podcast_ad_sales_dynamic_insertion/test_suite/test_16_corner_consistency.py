"""Corner queue B — consistency_model section (1 non-stub instance)."""

from test_helpers import (
    ADOPS,
    add_line_item,
    get_show,
    setup_selling_scenario,
    validate_success,
)


def test_mutation_visible_in_same_response_and_next_read(api):
    """PRD §2.2: "The `data` field contains the resource object or an array of resource objects. For 2xx responses with no data, it contains an empty object. Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field."
    PRD §3.4: "A successful activation debits the pool it sells against: a run-of-show item adds its `reserved_impressions` to the show's `reserved_impressions` and recomputes `available_impressions`"

    Design: Corner/consistency_model/mutation_visible_in_same_response_and_next_read
    """
    ctx = setup_selling_scenario(
        advertiser_name="ImmCo", category="FINTECH", booked_impressions=100,
        cpm_cents=1000, episode_publish_at="2026-08-05T00:00:00Z",
    )
    line_item = add_line_item(ctx, target="show", position="MID_ROLL",
                              reserved_impressions=100, priority=1,
                              activate=False)
    resp = api.transition_line_item(line_item["id"], {"action": "ACTIVATE"}, ADOPS)
    activated = validate_success(resp)
    assert activated["status"] == "ACTIVE", (
        "The transition response body itself must carry the mutated state"
    )
    # The immediately following read reflects the debited pool.
    show = get_show(ctx["show"]["id"])
    assert show["reserved_impressions"] == 100
    assert show["available_impressions"] == 9400
