"""Immediate visibility of the selection cascade.

Selecting an option fans out across five rows in one request.  The response
body itself is the new engagement, and every sibling effect — the chosen option,
the losing option, the package and the inquiry — is readable in the very next
call, including through a derived listing.
"""

from test_helpers import (
    ADMIN_HEADERS,
    AGENT_HEADERS,
    is_valid_uuid,
    read_inquiry,
    read_option,
    read_proposal,
    select_option_payload,
    setup_presented_proposal_with_two_options,
    validate_paginated,
    validate_success,
)

CHOSEN_FEE_CENTS = 1_275_000
LOSING_FEE_CENTS = 1_150_000
EVENT_START_UTC = "2026-10-15T16:00:00Z"
EVENT_END_UTC = "2026-10-15T18:00:00Z"


def _select_the_top_ranked_option(api, bundle: dict) -> dict:
    return validate_success(
        api.select_proposal_option(
            bundle["proposal"]["id"],
            select_option_payload(bundle["option"]["id"]),
            bundle["client_headers"],
        ),
        expected_status=201,
    )


class TestSelectionCascadeIsVisibleImmediately:
    def test_the_response_body_is_already_the_minted_engagement(self, api):
        """No second read is needed to observe the write: the selection answers with the new snapshot.

        PRD: It records `inquiry_id`, `speaker_id` and `selected_option_id` for traceability, copies `owning_agent_user_id` from the inquiry so that segregation of duties has an anchor, copies `event_start_utc`, `event_end_utc` and `is_virtual` from the inquiry, and copies `quoted_fee_cents` and `travel_allowance_cents` from the selected option.
        Design: Corner/consistency_model/immediate_visibility_of_the_whole_selection_cascade
        """
        bundle = setup_presented_proposal_with_two_options(api)

        engagement = _select_the_top_ranked_option(api, bundle)

        assert is_valid_uuid(engagement["id"])
        assert engagement["inquiry_id"] == bundle["inquiry"]["id"]
        assert engagement["speaker_id"] == bundle["speaker"]["id"]
        assert engagement["selected_option_id"] == bundle["option"]["id"]
        assert engagement["quoted_fee_cents"] == CHOSEN_FEE_CENTS
        assert engagement["travel_allowance_cents"] == 0
        assert engagement["event_start_utc"] == EVENT_START_UTC
        assert engagement["event_end_utc"] == EVENT_END_UTC
        assert engagement["is_virtual"] is False

    def test_the_minted_engagement_starts_on_both_dimensions_unpriced(self, api):
        """The booking track opens and the settlement track waits, with no commission pinned yet.

        PRD: `commission_pct_snapshot`, `provisional_commission_cents`, `final_commission_cents`, `retention_net_cents` and `retention_commission_cents` are all null on a fresh engagement — indeed they stay null for any engagement in `OFFERED`, `CONFIRMED`, `DECLINED_BY_SPEAKER` or either cancelled booking state, because none of those states has an executed agreement to price against.
        Design: Corner/consistency_model/immediate_visibility_of_the_whole_selection_cascade
        """
        bundle = setup_presented_proposal_with_two_options(api)

        engagement = _select_the_top_ranked_option(api, bundle)

        assert engagement["booking_status"] == "OFFERED"
        assert engagement["settlement_status"] == "UNBILLED"
        assert engagement["commission_pct_snapshot"] is None
        assert engagement["provisional_commission_cents"] is None
        assert engagement["final_commission_cents"] is None
        assert engagement["travel_reimbursable_cents"] == 0
        assert engagement["commission_adjustment_count"] == 0
        assert engagement["cancelled_by"] is None

    def test_every_sibling_effect_is_readable_on_the_next_request(self, api):
        """One request moves four other rows, and each of them reads back already moved.

        PRD: On success the named option moves `OFFERED → SELECTED` while every sibling in `OFFERED` moves `OFFERED → REJECTED`, the package moves `PRESENTED → ACCEPTED`, the inquiry moves `PROPOSED → WON`, and a new `Engagement` is minted.
        Design: Corner/consistency_model/immediate_visibility_of_the_whole_selection_cascade
        """
        bundle = setup_presented_proposal_with_two_options(api)

        _select_the_top_ranked_option(api, bundle)

        proposal = read_proposal(api, bundle["proposal"]["id"])
        assert proposal["status"] == "ACCEPTED"
        assert proposal["options_count"] == 1
        assert read_option(api, bundle["option"]["id"])["status"] == "SELECTED"
        assert read_option(api, bundle["second_option"]["id"])["status"] == "REJECTED"
        assert read_inquiry(api, bundle["inquiry"]["id"])["status"] == "WON"

    def test_the_derived_listings_do_not_lag_behind_the_cascade(self, api):
        """The engagement listing and the option listing both reflect the fan-out in the same request cycle.

        PRD: Where §3 describes a secondary effect on a sibling or parent resource, that effect is mandatory and is performed inside the same request: each affected resource has its own `updated_at` refreshed and its own `version` incremented, and the response body is the resource named by the endpoint, not the cascade.
        Design: Corner/consistency_model/immediate_visibility_of_the_whole_selection_cascade
        """
        bundle = setup_presented_proposal_with_two_options(api)

        engagement = _select_the_top_ranked_option(api, bundle)

        rows, meta = validate_paginated(
            api.list_engagements(
                ADMIN_HEADERS, params={"inquiry_id": bundle["inquiry"]["id"]}
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == engagement["id"]
        assert rows[0]["quoted_fee_cents"] == CHOSEN_FEE_CENTS

        selected, selected_meta = validate_paginated(
            api.list_proposal_options(
                AGENT_HEADERS,
                params={"proposal_id": bundle["proposal"]["id"], "status": "SELECTED"},
            )
        )
        assert selected_meta["total_count"] == 1
        assert selected[0]["id"] == bundle["option"]["id"]
        assert selected[0]["quoted_fee_cents"] == CHOSEN_FEE_CENTS

        rejected, rejected_meta = validate_paginated(
            api.list_proposal_options(
                AGENT_HEADERS,
                params={"proposal_id": bundle["proposal"]["id"], "status": "REJECTED"},
            )
        )
        assert rejected_meta["total_count"] == 1
        assert rejected[0]["id"] == bundle["second_option"]["id"]
        assert rejected[0]["quoted_fee_cents"] == LOSING_FEE_CENTS
