"""List-endpoint filter composition and reverse FK reads (PRD §3.1, §3.3,
§3.7, §4)."""
from test_helpers import (
    BILLING,
    SCHED,
    create_case,
    create_crna,
    create_fee_schedule,
    create_physician,
    create_published_roster,
    create_roster,
    create_site,
    get_success_data,
    propose_and_confirm,
    propose_assignment,
    setup_completed_solo_case,
    validate_paginated,
    api_client,
)


class TestRosterListFilters:
    def test_filters_by_site_and_lifecycle(self, api):
        """PRD §3.1: "Roster lists may be filtered by `site_id`,
        `service_date`, or `lifecycle`."
        PRD §2.3: "`total_count` (the full count of matching records, not just
        the page)".

        Design: Corner/endpoints/roster_list_filters_by_site_and_lifecycle
        """
        s1 = create_site("General Hospital")
        s2 = create_site("Surgery Center")
        create_roster(s1["id"], service_date="2026-08-10")  # DRAFT
        r2 = create_roster(s1["id"], service_date="2026-08-11")
        get_success_data(api.publish_roster(r2["id"], SCHED))
        r3 = create_roster(s2["id"], service_date="2026-08-10")
        get_success_data(api.publish_roster(r3["id"], SCHED))

        _, meta_site = validate_paginated(
            api.list_rosters(SCHED, params={"site_id": s1["id"]}))
        assert meta_site["total_count"] == 2
        rows_both, meta_both = validate_paginated(
            api.list_rosters(SCHED, params={"site_id": s1["id"],
                                            "lifecycle": "PUBLISHED"}))
        assert meta_both["total_count"] == 1
        assert rows_both[0]["service_date"] == "2026-08-11"
        _, meta_pub = validate_paginated(
            api.list_rosters(SCHED, params={"lifecycle": "PUBLISHED"}))
        assert meta_pub["total_count"] == 2


class TestReverseFkReads:
    def test_cases_by_roster_and_assignments_by_case(self, api):
        """PRD §3.2: "Case lists may be filtered by `roster_id` or `status`."
        PRD §3.3: "Assignment lists may be filtered by `case_id`,
        `provider_id`, `roster_id`, `status`, or `assignment_role`."

        Design: Corner/endpoints/children_reverse_reachable_via_filtered_lists
        """
        site = create_site()
        create_fee_schedule("P100", 5)
        physician = create_physician("Dr. Avery")
        crna = create_crna("Crna One")
        roster = create_published_roster(site["id"], required_primary_slots=2,
                                         scheduled_day_end_minute=1200)
        case_a = create_case(roster["id"], scheduled_start_minute=540,
                             scheduled_end_minute=600)
        propose_assignment(case_a["id"], physician["id"], "CASE_PRIMARY")
        case_b = create_case(roster["id"], scheduled_start_minute=660,
                             scheduled_end_minute=720)
        propose_assignment(case_b["id"], crna["id"], "CASE_PRIMARY")
        propose_assignment(case_b["id"], physician["id"], "CASE_DIRECTING")

        cases, meta_cases = validate_paginated(
            api.list_cases(SCHED, params={"roster_id": roster["id"]}))
        assert meta_cases["total_count"] == 2
        assignments_b, meta_b = validate_paginated(
            api.list_assignments(SCHED, params={"case_id": case_b["id"]}))
        assert meta_b["total_count"] == 2
        directing, meta_dir = validate_paginated(
            api.list_assignments(SCHED, params={"provider_id": physician["id"],
                                                "assignment_role": "CASE_DIRECTING"}))
        assert meta_dir["total_count"] == 1
        assert directing[0]["case_id"] == case_b["id"]


class TestClaimFilters:
    def test_claims_filtered_by_status_and_modifier(self, api):
        """PRD §3.7: "Claim lists may be filtered by `case_id`, `provider_id`,
        `status`, or `modifier_code`."
        PRD §3.7: "An `ANESTHESIOLOGIST` primary with no directing assignment
        bills `PERSONAL` at 8,000 cents per unit, taking 100 percent of the
        charge."

        Design: Corner/endpoints/claims_filtered_by_status_and_modifier
        """
        ctx = setup_completed_solo_case(provider_type="ANESTHESIOLOGIST")
        case_id = ctx["case"]["id"]
        rows, meta = validate_paginated(api.list_claims(
            BILLING, params={"case_id": case_id, "modifier_code": "PERSONAL",
                             "status": "DRAFT"}))
        assert meta["total_count"] == 1
        assert rows[0]["charge_cents"] == 72000
        rows_qy, meta_qy = validate_paginated(api.list_claims(
            BILLING, params={"case_id": case_id, "modifier_code": "QY"}))
        assert meta_qy["total_count"] == 0
        assert rows_qy == []
        assert meta_qy["has_more"] is False
