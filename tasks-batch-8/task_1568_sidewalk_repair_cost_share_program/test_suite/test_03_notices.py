"""Repair notice drafting, issuance, defaults, and composition rules."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    issue_notice,
    make_defect,
    make_draft_notice,
    make_owner,
    make_owner_headers,
    make_parcel,
    make_segment,
    setup_inventory,
    validate_error,
    validate_paginated,
    validate_success,
)

COORD = TEST_USERS["coordinator_headers"]
INSP1 = TEST_USERS["inspector_headers"]
HEARING = TEST_USERS["hearing_headers"]


class TestNoticeDefaults:
    def test_base_deadline_defaults_to_45_days(self, api):
        """PRD §3.3: "An optional `base_deadline_days` sets the compliance
        window, defaulting to 45 days when omitted"
        PRD §3.3: "then computes the `compliance_deadline`: the `issued_at`
        instant plus `base_deadline_days` days, extended by a further 30 days
        whenever the parcel's owner holds a `hardship_tier` other than `NONE`."

        Design: Corner/entities/notice_defaults_base_deadline_45
        """
        bundle = setup_inventory(parcel_number="P-E3", segment_code="S-E3-1",
                                 owner_name="Quinn Quail",
                                 street_address="42 Quail St")
        notice = validate_success(api.create_repair_notice(
            {"parcel_id": bundle["parcel"]["id"],
             "defect_ids": [bundle["defect"]["id"]]}, COORD), 201)
        assert notice["base_deadline_days"] == 45

        issued = validate_success(api.issue_repair_notice(notice["id"], COORD))
        assert issued["issued_at"] == "2026-08-01T00:00:00Z"
        assert issued["compliance_deadline"] == "2026-09-15T00:00:00Z"


class TestImmediateConsistency:
    def test_issue_response_and_reads_reflect_cascade(self, api):
        """PRD §3.3: "Issuance cascades: every referenced defect in `OPEN`
        moves to `UNDER_REPAIR`, while defects still waiting on forestry remain
        `AWAITING_FORESTRY` until their review clears; and each referenced
        defect's segment moves from `FLAGGED` to `UNDER_NOTICE`."

        Design: Corner/consistency_model/immediate_visibility_after_issue
        """
        bundle = setup_inventory(parcel_number="P-X6", segment_code="S-X6-1",
                                 owner_name="Nia Nutsedge",
                                 street_address="121 Nutsedge St")
        notice = make_draft_notice(bundle["parcel"]["id"],
                                   [bundle["defect"]["id"]])
        issued = validate_success(api.issue_repair_notice(notice["id"], COORD))
        assert issued["status"] == "ISSUED"
        assert issued["compliance_deadline"] == "2026-09-15T00:00:00Z"
        assert issued["version"] == 2

        defect = validate_success(api.get_defect(bundle["defect"]["id"], COORD))
        assert defect["status"] == "UNDER_REPAIR"
        segment = validate_success(
            api.get_segment(bundle["segment"]["id"], COORD))
        assert segment["status"] == "UNDER_NOTICE"


class TestPriorNoticeChain:
    def test_reissue_links_void_prior(self, api):
        """PRD §3.3: "an optional `prior_notice_id` chains the draft to an
        earlier notice it re-issues; the referenced notice must be in `VOID`
        status on the same parcel, else the draft is rejected with
        `ERR_INVALID_NOTICE_REFERENCE`"
        PRD §3.4: "A voided notice can later be re-issued through a fresh draft
        chained by `prior_notice_id`, as §3.3 describes."

        Design: Corner/endpoints/notice_reissue_links_void_prior
        """
        bundle = setup_inventory(parcel_number="P-N2", segment_code="S-N2-1",
                                 owner_name="Gus Ginkgo",
                                 street_address="84 Ginkgo St")
        notice1 = issue_notice(make_draft_notice(
            bundle["parcel"]["id"], [bundle["defect"]["id"]])["id"])
        validate_success(api.appeal_repair_notice(
            notice1["id"], {"grounds": "wrong parcel"},
            make_owner_headers(bundle["owner"]["id"])))
        reversed_notice = validate_success(api.decide_appeal(
            notice1["id"], {"decision": "REVERSED"}, HEARING))
        assert reversed_notice["status"] == "VOID"

        notice2 = validate_success(api.create_repair_notice(
            {"parcel_id": bundle["parcel"]["id"],
             "defect_ids": [bundle["defect"]["id"]],
             "prior_notice_id": notice1["id"]}, COORD), 201)
        assert notice2["status"] == "DRAFT"
        assert notice2["prior_notice_id"] == notice1["id"]

        issued2 = validate_success(api.issue_repair_notice(notice2["id"], COORD))
        assert issued2["status"] == "ISSUED"

        rows, _ = validate_paginated(api.list_repair_notices(
            COORD, params={"prior_notice_id": notice1["id"]}))
        assert len(rows) == 1 and rows[0]["id"] == notice2["id"]


class TestNoticeCompositionRules:
    def test_defect_fk_and_membership(self, api):
        """PRD §3.3: "every listed defect must belong to a segment of the
        notice's parcel (else `ERR_DEFECT_NOT_IN_PARCEL`)"
        PRD §2.7: "Path identifiers and body foreign keys must reference
        existing resources, validated left-to-right: path parameters first, then
        body fields in their declaration order."

        Design: Corner/errors/notice_create_defect_fk_and_membership
        """
        owner = make_owner("Hal Hakea", "85 Hakea St")
        parcel_a = make_parcel(owner["id"], "P-R1A", "85 Hakea St", "LOCAL")
        parcel_b = make_parcel(owner["id"], "P-R1B", "86 Hakea St", "LOCAL")
        segment = make_segment(parcel_a["id"], "S-R1A-1")
        defect = make_defect(segment["id"], "SPALLING", 20)

        resp = api.create_repair_notice(
            {"parcel_id": parcel_a["id"], "defect_ids": [NON_EXISTENT_UUID]},
            COORD)
        validate_error(resp, ApiErrorId.ERR_DEFECT_NOT_FOUND)

        resp = api.create_repair_notice(
            {"parcel_id": parcel_b["id"], "defect_ids": [defect["id"]]}, COORD)
        validate_error(resp, ApiErrorId.ERR_DEFECT_NOT_IN_PARCEL)

    def test_defect_under_active_notice_rejected(self, api):
        """PRD §3.3: "no listed defect may already be covered by another
        non-terminal notice (else `ERR_DEFECT_UNDER_ACTIVE_NOTICE`)"

        Design: Corner/errors/defect_under_active_notice_rejected
        """
        bundle = setup_inventory(parcel_number="P-R2", segment_code="S-R2-1",
                                 owner_name="Ida Ilama",
                                 street_address="87 Ilama St")
        notice1 = make_draft_notice(bundle["parcel"]["id"],
                                    [bundle["defect"]["id"]])
        assert notice1["status"] == "DRAFT"

        resp = api.create_repair_notice(
            {"parcel_id": bundle["parcel"]["id"],
             "defect_ids": [bundle["defect"]["id"]]}, COORD)
        validate_error(resp, ApiErrorId.ERR_DEFECT_UNDER_ACTIVE_NOTICE)

    def test_empty_defect_ids_rejected(self, api):
        """PRD §3.3: "the list must be non-empty (else
        `ERR_NO_ELIGIBLE_DEFECTS`)"

        Design: Corner/errors/empty_defect_ids_rejected
        """
        owner = make_owner("Jon Jojoba", "88 Jojoba St")
        parcel = make_parcel(owner["id"], "P-R3", "88 Jojoba St", "LOCAL")
        resp = api.create_repair_notice(
            {"parcel_id": parcel["id"], "defect_ids": []}, COORD)
        validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_DEFECTS)

    def test_city_owned_parcel_not_noticable(self, api):
        """PRD §3.3: "the parcel must be noticable, meaning its
        `owner_responsibility_pct` is greater than zero — attempting to notice
        a city-owned parcel fails with `ERR_CITY_PARCEL_NOT_NOTICABLE`."

        Design: Corner/errors/city_owned_parcel_not_noticable
        """
        bundle = setup_inventory(parcel_number="P-R4", segment_code="S-R4-1",
                                 owner_name="City of Oaks",
                                 street_address="1 Civic Center",
                                 is_city_owned=True)
        assert bundle["parcel"]["owner_responsibility_pct"] == 0
        resp = api.create_repair_notice(
            {"parcel_id": bundle["parcel"]["id"],
             "defect_ids": [bundle["defect"]["id"]]}, COORD)
        validate_error(resp, ApiErrorId.ERR_CITY_PARCEL_NOT_NOTICABLE)

    def test_prior_notice_reference_must_be_void(self, api):
        """PRD §3.3: "an optional `prior_notice_id` chains the draft to an
        earlier notice it re-issues; the referenced notice must be in `VOID`
        status on the same parcel, else the draft is rejected with
        `ERR_INVALID_NOTICE_REFERENCE`."

        Design: Corner/errors/prior_notice_reference_must_be_void
        """
        owner = make_owner("Mae Mahua", "91 Mahua St")
        parcel = make_parcel(owner["id"], "P-R7", "91 Mahua St", "LOCAL")
        segment = make_segment(parcel["id"], "S-R7-1")
        defect1 = make_defect(segment["id"], "SPALLING", 20)
        defect2 = make_defect(segment["id"], "SETTLEMENT", 12)
        notice1 = issue_notice(
            make_draft_notice(parcel["id"], [defect1["id"]])["id"])
        assert notice1["status"] == "ISSUED"

        resp = api.create_repair_notice(
            {"parcel_id": parcel["id"], "defect_ids": [defect2["id"]],
             "prior_notice_id": notice1["id"]}, COORD)
        validate_error(resp, ApiErrorId.ERR_INVALID_NOTICE_REFERENCE)
