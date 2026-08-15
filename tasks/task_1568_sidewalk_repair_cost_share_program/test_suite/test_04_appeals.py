"""Appeal lifecycle: cyclic re-issuance, reversal compensation, and gates."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    make_owner,
    make_owner_headers,
    set_clock,
    setup_inventory,
    setup_issued_notice,
    setup_two_defect_issued_notice,
    validate_error,
    validate_success,
)

COORD = TEST_USERS["coordinator_headers"]
HEARING = TEST_USERS["hearing_headers"]


class TestAppealCycleRecomputesDeadline:
    def _setup(self):
        bundle = setup_issued_notice(
            parcel_number="P-600", segment_code="S-600-1",
            owner_name="Gail Gale", street_address="7 Gale St",
            defect_type="SETTLEMENT", area_sqft=12)
        return bundle

    def test_upheld_replaces_deadline(self, api):
        """PRD §3.4: "A `decision` of `UPHELD` returns the notice to `ISSUED`,
        sets `appeal_status` to `UPHELD`, and **replaces** the deadline: the new
        `compliance_deadline` is the decision instant plus 15 days, superseding
        rather than extending the prior deadline."

        Design: Difficulty/non_linear_state_machine/notice_appeal_cycle_recomputes_deadline
        """
        bundle = self._setup()
        notice_id = bundle["notice"]["id"]
        owner_id = bundle["owner"]["id"]
        assert bundle["notice"]["compliance_deadline"] == \
            "2026-09-15T00:00:00Z"

        set_clock("2026-08-10T00:00:00Z")
        appealed = validate_success(api.appeal_repair_notice(
            notice_id, {"grounds": "defect predates ownership"},
            make_owner_headers(owner_id)))
        assert appealed["status"] == "UNDER_APPEAL"
        assert appealed["appeal_status"] == "PENDING"

        set_clock("2026-08-21T00:00:00Z")
        decided = validate_success(api.decide_appeal(
            notice_id, {"decision": "UPHELD"}, HEARING))
        assert decided["status"] == "ISSUED"
        assert decided["appeal_status"] == "UPHELD"
        assert decided["compliance_deadline"] == "2026-09-05T00:00:00Z", \
            "decision instant 2026-08-21 + 15 days replaces the old deadline"

    def test_cycle_traversed_second_time(self, api):
        """PRD §3.4: "The cycle is genuinely cyclic — a re-issued notice may be
        appealed again while the clock remains within its new deadline."

        Design: Difficulty/non_linear_state_machine/notice_appeal_cycle_recomputes_deadline
        """
        bundle = self._setup()
        notice_id = bundle["notice"]["id"]
        owner_id = bundle["owner"]["id"]

        set_clock("2026-08-10T00:00:00Z")
        validate_success(api.appeal_repair_notice(
            notice_id, {"grounds": "defect predates ownership"},
            make_owner_headers(owner_id)))
        set_clock("2026-08-21T00:00:00Z")
        validate_success(api.decide_appeal(notice_id, {"decision": "UPHELD"},
                                           HEARING))

        set_clock("2026-08-25T00:00:00Z")
        appealed2 = validate_success(api.appeal_repair_notice(
            notice_id, {"grounds": "second appeal within new deadline"},
            make_owner_headers(owner_id)))
        assert appealed2["status"] == "UNDER_APPEAL"
        assert appealed2["appeal_status"] == "PENDING"


class TestAppealReversalRestoresDefectPool:
    def _setup(self):
        return setup_two_defect_issued_notice(
            parcel_number="P-2300", segment_code="S-2300-1")

    def test_issue_keeps_defects_in_nonverified_pool(self, api):
        """PRD §3.3: "Issuance cascades: every referenced defect in `OPEN`
        moves to `UNDER_REPAIR`, while defects still waiting on forestry remain
        `AWAITING_FORESTRY` until their review clears; and each referenced
        defect's segment moves from `FLAGGED` to `UNDER_NOTICE`."

        Design: Difficulty/compensating_invariant/issue_then_appeal_reversal_restores_defect_pool
        """
        bundle = self._setup()
        segment = validate_success(
            api.get_segment(bundle["segment"]["id"], COORD))
        assert segment["open_defect_count"] == 2
        assert segment["status"] == "UNDER_NOTICE"

    def test_reversal_restores_pool_and_segment(self, api):
        """PRD §3.4: "A `decision` of `REVERSED` instead voids the notice
        (`UNDER_APPEAL → VOID`), sets `appeal_status` to `REVERSED`, releases
        every covered defect from `UNDER_REPAIR` back to `OPEN`, and returns
        each segment with no remaining `UNDER_REPAIR` defects from
        `UNDER_NOTICE` to `FLAGGED`."

        Design: Difficulty/compensating_invariant/issue_then_appeal_reversal_restores_defect_pool
        """
        bundle = self._setup()
        notice_id = bundle["notice"]["id"]
        owner_id = bundle["owner"]["id"]
        validate_success(api.appeal_repair_notice(
            notice_id, {"grounds": "defects are pre-existing city damage"},
            make_owner_headers(owner_id)))

        decided = validate_success(api.decide_appeal(
            notice_id, {"decision": "REVERSED"}, HEARING))
        assert decided["status"] == "VOID"
        assert decided["appeal_status"] == "REVERSED"

        for defect in bundle["defects"]:
            d = validate_success(api.get_defect(defect["id"], COORD))
            assert d["status"] == "OPEN", "defect returned to the open pool"

        segment = validate_success(
            api.get_segment(bundle["segment"]["id"], COORD))
        assert segment["open_defect_count"] == 2, \
            "cardinality conserved across the issue/reversal pair"
        assert segment["status"] == "FLAGGED"


class TestAppealPreconditions:
    def test_appeal_on_draft_notice_rejected(self, api):
        """PRD §3.4: "the notice must be `ISSUED` (else
        `ERR_INVALID_NOTICE_STATE`)"

        Design: Corner/state_machines/appeal_on_draft_notice_rejected
        """
        bundle = setup_inventory(parcel_number="P-S2", segment_code="S-S2-1",
                                 owner_name="Ada Aspen",
                                 street_address="52 Aspen St")
        from test_helpers import make_draft_notice
        notice = make_draft_notice(bundle["parcel"]["id"],
                                   [bundle["defect"]["id"]])
        assert notice["status"] == "DRAFT"

        resp = api.appeal_repair_notice(
            notice["id"], {"grounds": "too early"},
            make_owner_headers(bundle["owner"]["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_NOTICE_STATE)

    def test_appeal_by_non_owner_rejected(self, api):
        """PRD §2.1: "Acting on a resource outside one's ownership scope — an
        owner appealing a notice on someone else's parcel, a contractor
        withdrawing a bid it did not submit — is rejected with
        `ERR_OWNERSHIP_MISMATCH` (HTTP 403)."
        PRD §3.4: "the acting owner must own the notice's parcel (else
        `ERR_OWNERSHIP_MISMATCH`)"

        Design: Corner/validations/appeal_by_non_owner_rejected
        """
        bundle = setup_issued_notice(parcel_number="P-V2",
                                     segment_code="S-V2-1",
                                     owner_name="Ann Acer",
                                     street_address="77 Acer St")
        other_owner = make_owner("Bob Balsa", "78 Balsa St")
        resp = api.appeal_repair_notice(
            bundle["notice"]["id"], {"grounds": "not mine to appeal"},
            make_owner_headers(other_owner["id"]))
        validate_error(resp, ApiErrorId.ERR_OWNERSHIP_MISMATCH)

    def test_appeal_after_window_closed_rejected(self, api):
        """PRD §3.4: "the logical clock must not be past the
        `compliance_deadline`, with an appeal landing exactly on the deadline
        still timely (else `ERR_APPEAL_WINDOW_CLOSED`)"

        Design: Corner/errors/appeal_after_window_closed_rejected
        """
        bundle = setup_issued_notice(parcel_number="P-T1",
                                     segment_code="S-T1-1",
                                     owner_name="Quince Q",
                                     street_address="98 Quince St")
        assert bundle["notice"]["compliance_deadline"] == \
            "2026-09-15T00:00:00Z"
        set_clock("2026-09-16T00:00:00Z")
        resp = api.appeal_repair_notice(
            bundle["notice"]["id"], {"grounds": "late"},
            make_owner_headers(bundle["owner"]["id"]))
        validate_error(resp, ApiErrorId.ERR_APPEAL_WINDOW_CLOSED)

    def test_void_notice_terminal_lockdown(self, api):
        """PRD §3.4: "A `decision` of `REVERSED` instead voids the notice
        (`UNDER_APPEAL → VOID`)"
        PRD §3.4: "the notice must be `ISSUED` (else
        `ERR_INVALID_NOTICE_STATE`)"
        PRD §3.3: "Issuing the notice — `DRAFT → ISSUED`, by a coordinator"

        Design: Corner/state_machines/void_notice_terminal_lockdown
        """
        bundle = setup_issued_notice(parcel_number="P-S8",
                                     segment_code="S-S8-1",
                                     owner_name="Gil Gum",
                                     street_address="58 Gum St")
        notice_id = bundle["notice"]["id"]
        validate_success(api.appeal_repair_notice(
            notice_id, {"grounds": "not my tree"},
            make_owner_headers(bundle["owner"]["id"])))
        decided = validate_success(api.decide_appeal(
            notice_id, {"decision": "REVERSED"}, HEARING))
        assert decided["status"] == "VOID"

        resp = api.appeal_repair_notice(
            notice_id, {"grounds": "again"},
            make_owner_headers(bundle["owner"]["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_NOTICE_STATE)

        resp = api.issue_repair_notice(notice_id, COORD)
        validate_error(resp, ApiErrorId.ERR_INVALID_NOTICE_STATE)
