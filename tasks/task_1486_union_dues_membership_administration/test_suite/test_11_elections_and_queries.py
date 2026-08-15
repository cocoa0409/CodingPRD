"""Elections, eligibility snapshots, pagination, and reverse-lookup lists."""
import pytest

from test_helpers import (
    ST,
    ApiErrorId,
    assert_election,
    assert_election_eligibility,
    create_election_payload,
    get_success_data,
    is_valid_uuid,
    make_assessment_run,
    make_election,
    make_local,
    make_member,
    make_member_headers,
    make_objector_case,
    make_payment,
    make_transfer,
    run_period,
    send_notice,
    set_clock,
    setup_flat_local_with_journeyman,
    setup_pct_local_with_journeyman,
    sweep_delinquency,
    list_member_notices,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestElectionWindowOverlap:
    """Nomination windows are closed intervals; touching endpoints count as
    overlapping, a one-second gap does not."""

    def test_touching_window_rejected(self, api, local_admin_headers):
        """PRD section on elections: "Nomination windows of one local are
        closed intervals and never overlap, and touching endpoints count as
        overlapping: a new election whose window so much as shares a boundary
        instant with an existing election of the same local is rejected with
        `ERR_ELECTION_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/election_closed_interval_touch_overlap
        """
        local = make_local("PCT", name="Local 100")
        make_election(
            local["id"],
            title="Officers 2026",
            nomination_open_at="2026-09-01T00:00:00Z",
            nomination_close_at="2026-09-15T00:00:00Z",
            eligibility_cutoff_at="2026-09-20T00:00:00Z",
        )
        resp = api.create_election(
            local["id"],
            create_election_payload(
                title="Delegates 2026",
                nomination_open_at="2026-09-15T00:00:00Z",
                nomination_close_at="2026-09-30T00:00:00Z",
                eligibility_cutoff_at="2026-10-05T00:00:00Z",
            ),
            local_admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_ELECTION_WINDOW_OVERLAP)

    def test_one_second_gap_accepted(self, api, local_admin_headers):
        """PRD section on elections: "Nomination windows of one local are
        closed intervals and never overlap, and touching endpoints count as
        overlapping". A window opening one second after the prior close shares
        no instant, so creation succeeds; "A new election starts `SCHEDULED`".

        Design: Difficulty/resource_temporal_overlap/election_closed_interval_touch_overlap
        """
        local = make_local("PCT", name="Local 100")
        make_election(
            local["id"],
            title="Officers 2026",
            nomination_open_at="2026-09-01T00:00:00Z",
            nomination_close_at="2026-09-15T00:00:00Z",
            eligibility_cutoff_at="2026-09-20T00:00:00Z",
        )
        resp = api.create_election(
            local["id"],
            create_election_payload(
                title="Delegates 2026",
                nomination_open_at="2026-09-15T00:00:01Z",
                nomination_close_at="2026-09-30T00:00:00Z",
                eligibility_cutoff_at="2026-10-05T00:00:00Z",
            ),
            local_admin_headers,
        )
        election = validate_success(resp, 201)
        assert_election(election)
        assert election["status"] == "SCHEDULED"


class TestElectionLifecycleGuards:
    def test_election_open_before_window_rejected(self, api, local_admin_headers):
        """PRD section on elections: "Opening nominations requires the election
        to be `SCHEDULED` and the logical clock to have reached
        `nomination_open_at`; violations surface as
        `ERR_ELECTION_STATE_FORBIDDEN`."

        Design: Corner/validations/election_open_before_window_rejected
        """
        local = make_local("PCT", name="Local 100")
        set_clock("2026-08-01T00:00:00Z")
        election = make_election(local["id"], title="Officers 2026")
        resp = api.open_nominations(election["id"], local_admin_headers)
        validate_error(resp, ApiErrorId.ERR_ELECTION_STATE_FORBIDDEN)


class TestEligibilitySnapshot:
    """The freeze pins one snapshot per electorate member, with the inclusive
    standing-months boundary and the pinned reason ordering."""

    def test_election_eligibility_snapshot_with_reasons_and_standing_boundary(self, api, local_admin_headers):
        """PRD section on eligibility: "If the member's status is not `ACTIVE`,
        the reason `NOT_ACTIVE` is recorded. If `arrears_cents` is not zero,
        `ARREARS_OUTSTANDING` is recorded." And "The standing window is
        inclusive — a suspension that ended exactly
        `required_good_standing_months` calendar months before the cutoff date
        satisfies the requirement — and the comparison is at date granularity,
        ignoring time of day."

        Design: Corner/calculations/election_eligibility_snapshot_with_reasons_and_standing_boundary
        """
        local, cls = setup_flat_local_with_journeyman()
        set_clock("2025-05-01T00:00:00Z")
        ma = make_member(local["id"], cls["id"], full_name="Edge Ann", member_number="M-A", joined_at="2024-01-15")
        mb = make_member(local["id"], cls["id"], full_name="Late Bob", member_number="M-B", joined_at="2024-01-15")
        mc = make_member(local["id"], cls["id"], full_name="Cold Carl", member_number="M-C", joined_at="2024-01-15")
        make_assessment_run(local["id"], "2025-05")
        run_period(local["id"], "2025-06")
        set_clock("2025-08-01T00:00:00Z")
        sweep_delinquency(local["id"])
        for m in (ma, mb, mc):
            notice = list_member_notices(m["id"])[0]
            send_notice(m["id"], notice["id"])
        set_clock("2025-08-12T00:00:00Z")
        sweep_delinquency(local["id"])
        # MA reinstated 2025-08-15 (exactly 12 months before the cutoff date);
        # MB one day later; MC never reinstated (SUSPENDED at freeze).
        set_clock("2025-08-15T00:00:00Z")
        validate_success(api.reinstate_member(ma["id"], {"amount_cents": 12500}, ST), 200)
        set_clock("2025-08-16T00:00:00Z")
        validate_success(api.reinstate_member(mb["id"], {"amount_cents": 12500}, ST), 200)
        set_clock("2026-07-01T00:00:00Z")
        md = make_member(local["id"], cls["id"], full_name="Clean Dana", member_number="M-D", joined_at="2026-07-01")
        election = make_election(
            local["id"],
            title="Officers 2026",
            nomination_open_at="2026-08-01T00:00:00Z",
            nomination_close_at="2026-08-10T00:00:00Z",
            eligibility_cutoff_at="2026-08-15T00:00:00Z",
        )
        set_clock("2026-08-15T00:00:00Z")
        validate_success(api.open_nominations(election["id"], local_admin_headers), 200)
        validate_success(api.freeze_eligibility(election["id"], local_admin_headers), 200)

        snaps_a = get_success_data(
            api.list_election_eligibilities(election["id"], local_admin_headers, params={"member_id": ma["id"]})
        )
        assert len(snaps_a) == 1
        assert_election_eligibility(snaps_a[0])
        assert snaps_a[0]["eligible"] is True and snaps_a[0]["ineligibility_reasons"] == [], (
            "suspension ended exactly 12 months before the cutoff satisfies the requirement"
        )

        snaps_b = get_success_data(
            api.list_election_eligibilities(election["id"], local_admin_headers, params={"member_id": mb["id"]})
        )
        assert len(snaps_b) == 1
        assert snaps_b[0]["eligible"] is False
        assert snaps_b[0]["ineligibility_reasons"] == ["INSUFFICIENT_STANDING_MONTHS"], (
            "one day short of twelve months is insufficient"
        )

        snaps_d = get_success_data(
            api.list_election_eligibilities(election["id"], local_admin_headers, params={"member_id": md["id"]})
        )
        assert len(snaps_d) == 1
        assert snaps_d[0]["eligible"] is True and snaps_d[0]["ineligibility_reasons"] == []

        body_c = api.list_election_eligibilities(
            election["id"], local_admin_headers, params={"member_id": mc["id"]}
        )
        data_c, meta_c = validate_paginated(body_c)
        assert data_c == [] and meta_c["total_count"] == 0, (
            "a SUSPENDED member is outside the electorate and has no snapshot"
        )


class TestListEndpoints:
    def test_list_pagination_envelope(self, api, secretary_treasurer_headers):
        """PRD section on pagination: "Every list response includes `limit`,
        `offset`, `total_count`, and `has_more` in the `meta` object of the
        envelope", and on the envelope: "The `response_type` is either
        "object" for a single resource or "array" for a list of resources."

        Design: Corner/endpoints/list_pagination_envelope
        """
        local, cls = setup_pct_local_with_journeyman()
        set_clock("2026-08-01T00:00:00Z")
        for name, number in (("Page One", "M-001"), ("Page Two", "M-002"), ("Page Three", "M-003")):
            make_member(local["id"], cls["id"], full_name=name, member_number=number)
        page1 = api.list_members(secretary_treasurer_headers, params={"local_id": local["id"], "limit": 2, "offset": 0})
        data1, meta1 = validate_paginated(page1)
        assert page1.json()["response_type"] == "array"
        assert isinstance(page1.json()["meta"]["api_request_id"], str)
        assert meta1["total_count"] == 3 and meta1["has_more"] is True
        assert len(data1) == 2
        page2 = api.list_members(secretary_treasurer_headers, params={"local_id": local["id"], "limit": 2, "offset": 2})
        data2, meta2 = validate_paginated(page2)
        assert page2.json()["response_type"] == "array"
        assert meta2["has_more"] is False
        assert len(data2) == 1
        assert data1[0]["id"] != data2[0]["id"]

    def test_reverse_reachability_filtered_lists(self, api, secretary_treasurer_headers):
        """PRD section on members: "A member's assessments can be listed with
        `period` and `status` filters, the ledger with `period` and
        `entry_type` filters"; on transfers: "Transfers can be browsed with
        `member_id`, `from_local_id`, `to_local_id`, and `status` filters";
        on objector cases: "Cases can be browsed with `member_id` and `status`
        filters."

        Design: Corner/endpoints/reverse_reachability_filtered_lists
        """
        local1, cls = setup_flat_local_with_journeyman(local_name="Local 200")
        local2 = make_local("FLAT", name="Local 400", default_flat_dues_cents=1000)
        set_clock("2026-08-01T00:00:00Z")
        member = make_member(local1["id"], cls["id"], full_name="Linked Liam", member_number="M-001")
        case = make_objector_case(member["id"])
        transfer = make_transfer(member["id"], local2["id"], "2026-09")
        make_assessment_run(local1["id"], "2026-08")
        make_payment(member["id"], 1000)

        assessments = get_success_data(api.list_member_assessments(member["id"], secretary_treasurer_headers))
        assert len(assessments) == 1 and is_valid_uuid(assessments[0]["id"])
        ledger = get_success_data(api.list_member_ledger(member["id"], secretary_treasurer_headers))
        assert ledger[0]["entry_type"] == "ASSESSMENT_CHARGE", (
            "the charge precedes the payment credit chronologically"
        )
        transfers = get_success_data(api.list_transfers(secretary_treasurer_headers, params={"member_id": member["id"]}))
        assert len(transfers) == 1 and transfers[0]["id"] == transfer["id"]
        cases = get_success_data(api.list_objector_cases(secretary_treasurer_headers, params={"member_id": member["id"]}))
        assert len(cases) == 1 and cases[0]["id"] == case["id"]
