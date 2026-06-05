"""Corner — cross_cutting_complexity_layers and consistency_model sections.

Non-stub:
  - corner_occ_stale_chapter_version_on_bid_create (OCC stale-version)
  - corner_immediate_consistency_chapter_version_after_put

Stubs (excluded_because cites a difficulty instance — NO test emitted here):
  - corner_derived_field_chapter_pledged_count_already_covered
  - corner_cascade_party_complete_marks_no_show_already_covered
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    set_clock,
    create_chapter,
    create_round,
    register_and_activate_pnm,
    create_and_open_party,
    create_invitation,
    accept_invitation,
    complete_party,
    advance_round,
    create_bid_match_payload,
    update_chapter_payload,
    make_chapter_officer_headers,
    ApiErrorId,
    TEST_USERS,
)


class TestOccStaleChapterVersionOnBidCreate:
    """Two sequential POST /bid-matches both quote the pre-bump Chapter.version.
    The first succeeds and bumps version; the second is rejected with
    ERR_STALE_VERSION (412) because of the OCC mismatch."""

    def test_second_bid_with_stale_chapter_version_returns_stale_version(self, api):
        """PRD §2.5: "Two write paths that touch chapter quota are guarded by optimistic concurrency control, both gated on the parent `Chapter`'s `version`. The first guard sits on the manual / override bid-creation endpoint: the request body must carry `expected_chapter_version` set to whatever the client last observed as the chapter's `version`. If the chapter's current `version` does not equal that supplied value, the create is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/corner_occ_stale_chapter_version_on_bid_create
        """
        # Two ACTIVE PNMs against a chapter on BID_DAY; the first manual bid
        # succeeds and bumps Chapter.version; the second — quoting the SAME
        # pre-bump expected_chapter_version — is rejected with 412 OCC.
        set_clock("2026-09-02T00:00:00Z")
        ch = create_chapter(
            name="OccChap",
            greek_type="FRATERNITY",
            quota_total=2,
            dues_per_member_cents=10000,
            legacy_priority_slots=0,
        )
        rnd = create_round(cycle_label="Fall 2026 occ")
        oa = register_and_activate_pnm(full_name="OA", gpa=3.50)
        ob = register_and_activate_pnm(full_name="OB", gpa=3.50)
        # Both PNMs ATTEND a party so they remain ACTIVE after PARTY->MUTUAL.
        party = create_and_open_party(
            rnd["id"], ch["id"], scheduled_start_utc="2026-09-05T18:00:00Z"
        )
        i_oa = create_invitation(party["id"], oa["id"], ch["id"])
        i_ob = create_invitation(party["id"], ob["id"], ch["id"])
        accept_invitation(i_oa["id"], oa["id"])
        accept_invitation(i_ob["id"], ob["id"])
        complete_party(party["id"], ch["id"])
        advance_round(rnd["id"])  # PARTY -> MUTUAL_SELECTION
        # No preferences filed: matcher input is empty, so no auto-bids; both
        # PNMs stay ACTIVE on the BID_DAY advance. The MUTUAL_SELECTION->
        # BID_DAY precondition (every chapter with a PNM_TO_CHAPTER pref has
        # also filed CHAPTER_TO_PNM) is vacuously satisfied.
        advance_round(rnd["id"])  # MUTUAL_SELECTION -> BID_DAY
        ch_pre = get_success_data(
            api_client.get_chapter(
                ch["id"], TEST_USERS["panhellenic_admin_headers"]
            )
        )
        observed_v = ch_pre["version"]
        first_res = api.create_bid_match(
            create_bid_match_payload(
                round_id=rnd["id"],
                chapter_id=ch["id"],
                pnm_id=oa["id"],
                expected_chapter_version=observed_v,
            ),
            make_chapter_officer_headers(ch["id"]),
        )
        first_bid = validate_success(first_res, 201)
        assert first_bid["status"] == "PROPOSED"
        # Second manual bid quotes the now-stale expected_chapter_version.
        second_res = api.create_bid_match(
            create_bid_match_payload(
                round_id=rnd["id"],
                chapter_id=ch["id"],
                pnm_id=ob["id"],
                expected_chapter_version=observed_v,
            ),
            make_chapter_officer_headers(ch["id"]),
        )
        validate_error(second_res, ApiErrorId.ERR_STALE_VERSION)


class TestImmediateConsistencyChapterVersionAfterPut:
    """A sequential GET after PUT shows the new value and incremented version."""

    def test_get_after_put_returns_new_dues_and_incremented_version(self, api):
        """PRD §3.1: "A subsequent admin update may change `dues_per_member_cents`, `quota_total`, or `legacy_priority_slots`, and bumps `Chapter.version`"
        PRD §2.4: "every resource additionally carries an `updated_at` timestamp refreshed on every mutation and a `version` integer initialized to 1 and incremented by exactly 1 on every mutation that changes the row."

        Design: Corner/consistency_model/corner_immediate_consistency_chapter_version_after_put
        """
        ch = create_chapter(
            name="ImmCons",
            greek_type="SORORITY",
            quota_total=3,
            dues_per_member_cents=10000,
            legacy_priority_slots=0,
        )
        assert ch["version"] == 1
        api.update_chapter(
            ch["id"],
            update_chapter_payload(dues_per_member_cents=25000),
            TEST_USERS["panhellenic_admin_headers"],
        )
        got = validate_success(
            api.get_chapter(ch["id"], TEST_USERS["panhellenic_admin_headers"]),
            200,
        )
        assert got["dues_per_member_cents"] == 25000
        assert got["version"] == 2
