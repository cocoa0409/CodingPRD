"""Reachability of the malformed-request refusal on list-read query parameters."""

from test_helpers import (
    ApiErrorId,
    CampaignStatus,
    assert_status,
    assert_total_count,
    validate_error,
    validate_paginated,
)


class TestPaginationBoundsRefusal:
    """A limit outside the accepted range is refused rather than clamped."""

    def test_01_limit_above_the_maximum_is_refused_with_the_error_envelope(
        self, api, world
    ):
        """A limit of 101 exceeds the declared maximum, so the list read fails instead of
        silently reducing the page size, while a limit of 100 is accepted.

        PRD 2.3: "The `limit` parameter caps how many items come back; when it is omitted
        it defaults to 10, its minimum accepted value is 1 and its maximum is 100. A
        `limit` outside that inclusive range is a malformed request and is refused with
        `ERR_INVALID_REQUEST` (HTTP 400)."

        PRD 2.2: "The `error_id` is a unique, machine-readable string that identifies the
        specific error."

        Design: Corner/errors/pagination_limit_above_the_maximum_returns_the_error_envelope
        """
        world.set_clock("2026-08-03T00:00:00Z")

        refusal = api.list_complaints(world.officer, {"limit": 101})
        error = validate_error(refusal, ApiErrorId.INVALID_REQUEST)
        assert error["message"].strip(), "the refusal must explain itself"

        rows, meta = validate_paginated(
            api.list_complaints(world.officer, {"limit": 100})
        )
        assert rows == []
        assert_total_count(meta, 0)
        assert meta["has_more"] is False
        assert meta["limit"] == 100


class TestListFilterEnumMembership:
    """Enum membership is enforced on filter inputs, not only on bodies."""

    def test_02_unknown_status_filter_value_is_refused_as_a_malformed_request(
        self, api, world, draft_campaign
    ):
        """A campaign status filter naming a value outside the declared set is rejected
        rather than treated as a filter that simply matches nothing.

        PRD 2.8: "Request well-formedness on every endpoint — body parses, every required
        field present, every enum value a member of its declared set, every number inside
        its declared range, phone numbers in E.164 form, timestamps and dates parseable,
        `limit` within 1 to 100 — `ERR_INVALID_REQUEST`."

        PRD 3.7: "A new campaign has `status` `DRAFT`, `latest_scrub_status` and
        `measurement_date` and `suspension_reason` and `launch_certified_by_user_id` and
        `pinned_script_version` all null"

        Design: Corner/errors/unknown_enum_value_on_a_list_filter_returns_invalid_request
        """
        campaign = draft_campaign["campaign"]
        assert_status(campaign, CampaignStatus.DRAFT)

        refusal = api.list_campaigns(world.manager, {"status": "RETIRED"})
        validate_error(refusal, ApiErrorId.INVALID_REQUEST)

        rows, meta = validate_paginated(
            api.list_campaigns(world.manager, {"status": CampaignStatus.DRAFT})
        )
        assert_total_count(meta, 1)
        assert [row["id"] for row in rows] == [campaign["id"]]
