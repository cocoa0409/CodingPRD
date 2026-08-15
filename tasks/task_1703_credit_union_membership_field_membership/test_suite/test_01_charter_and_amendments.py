"""Charter creation, amendment filing (OCC), regulatory decision, and the
segment-retirement cascade."""
from test_helpers import (
    ApiErrorId,
    add_segment_amendment_payload,
    approve_amendment,
    assert_amendment_application,
    assert_charter,
    assert_member,
    assert_segment,
    create_charter_payload,
    create_member,
    file_add_segment_amendment,
    file_application,
    file_retire_segment_amendment,
    make_regulator_headers,
    set_clock,
    setup_charter,
    two_occupational_segments,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS

BOARD = TEST_USERS["board_director_headers"]
CO1 = TEST_USERS["compliance_officer_headers"]
REG = TEST_USERS["regulator_headers"]
FILER = TEST_USERS["membership_officer_headers"]
DECIDER = TEST_USERS["membership_officer_2_headers"]


class TestCharterCreation:
    def test_charter_creation_defaults_segment_order_and_singleton(self, api):
        """PRD §3.1: "The charter is a singleton with status always ACTIVE:
        exactly one may exist, and a second creation attempt is rejected with
        `ERR_CHARTER_ALREADY_EXISTS`."
        PRD §3.1: "One segment is created per array element, in array order,
        each beginning ACTIVE with `retired_at` null and a `charter_id` tying
        it to its charter."

        Design: Corner/entities/charter_creation_defaults_and_singleton_constraint
        """
        resp = api.create_charter(
            create_charter_payload(segments=[
                {"segment_type": "OCCUPATIONAL",
                 "descriptor": "ACME Corp employees",
                 "required_documents": ["GOVERNMENT_ID", "EMPLOYER_LETTER"]},
                {"segment_type": "COMMUNITY",
                 "descriptor": "Riverside County residents",
                 "required_documents": ["GOVERNMENT_ID", "ADDRESS_PROOF"]},
            ]),
            BOARD,
        )
        charter = validate_success(resp, 201)
        assert_charter(charter)
        assert charter["status"] == "ACTIVE", "The charter is born ACTIVE"
        assert isinstance(charter["version"], int) and charter["version"] >= 1

        segs, meta = validate_paginated(
            api.list_charter_segments(charter["id"], BOARD))
        assert meta["total_count"] == 2
        assert segs[0]["descriptor"] == "ACME Corp employees"
        assert segs[0]["status"] == "ACTIVE"
        assert segs[0]["retired_at"] is None
        assert segs[1]["descriptor"] == "Riverside County residents"
        for seg in segs:
            assert_segment(seg)
            assert seg["charter_id"] == charter["id"]

        dup = api.create_charter(
            create_charter_payload(bond_type="COMMUNITY", par_value_cents=250,
                                   segments=[]),
            BOARD,
        )
        validate_error(dup, ApiErrorId.ERR_CHARTER_ALREADY_EXISTS)


class TestAmendmentOcc:
    def test_occ_charter_stale_then_fresh_submission(self, api):
        """PRD §3.2: "A filing whose `expected_charter_version` no longer
        matches the charter is rejected with `ERR_STALE_CHARTER_VERSION` per
        §2.7 — and because every accepted submission immediately increments
        the charter's version, two filings built on the same baseline can
        never both succeed."
        PRD §3.2: "On acceptance the application begins SUBMITTED, the filer is
        recorded as `submitted_by_user_id`, and the accepted expected version
        is preserved as `baseline_charter_version`."

        Design: Corner/cross_cutting_layers/occ_charter_stale_then_fresh_submission
        """
        set_clock("2026-08-01")
        charter, _segs = setup_charter()
        v0 = charter["version"]

        amend_a = validate_success(
            api.create_amendment_application(
                add_segment_amendment_payload(charter["id"], v0), CO1), 201)
        assert_amendment_application(amend_a)
        assert amend_a["status"] == "SUBMITTED"
        assert amend_a["baseline_charter_version"] == v0
        assert amend_a["submitted_by_user_id"] == "co-1"

        charter_mid = validate_success(api.get_charter(charter["id"], CO1))
        assert charter_mid["version"] == v0 + 1, (
            "Every successful amendment submission increments the charter "
            "version by one")

        stale = api.create_amendment_application(
            add_segment_amendment_payload(
                charter["id"], v0, effective_date="2026-10-01",
                proposed_segment_type="ASSOCIATIONAL",
                proposed_segment_descriptor="Riverside Teachers Association members",
                proposed_segment_required_documents=["GOVERNMENT_ID",
                                                     "ASSOCIATION_CARD"]),
            CO1)
        validate_error(stale, ApiErrorId.ERR_STALE_CHARTER_VERSION)

        charter_now = validate_success(api.get_charter(charter["id"], CO1))
        amend_b = validate_success(
            api.create_amendment_application(
                add_segment_amendment_payload(
                    charter["id"], charter_now["version"],
                    effective_date="2026-10-01",
                    proposed_segment_type="ASSOCIATIONAL",
                    proposed_segment_descriptor="Riverside Teachers Association members",
                    proposed_segment_required_documents=["GOVERNMENT_ID",
                                                         "ASSOCIATION_CARD"]),
                CO1), 201)
        assert amend_b["baseline_charter_version"] == charter_now["version"]


class TestAmendmentValidationAndDecision:
    def test_bond_type_mismatch_on_add_segment(self, api):
        """PRD §3.2: "A single-bond charter accepts only its own segment type —
        `SINGLE_OCCUPATIONAL` admits only `OCCUPATIONAL` segments, `COMMUNITY`
        only `COMMUNITY`, `ASSOCIATIONAL` only `ASSOCIATIONAL` — while a
        `MULTIPLE_COMMON_BOND` charter accepts any of the three. A filing that
        proposes an incompatible segment type is rejected with
        `ERR_BOND_TYPE_MISMATCH`."

        Design: Corner/validations/bond_type_mismatch_on_add_segment
        """
        set_clock("2026-08-01")
        charter, _segs = setup_charter(bond_type="SINGLE_OCCUPATIONAL")
        resp = api.create_amendment_application(
            add_segment_amendment_payload(
                charter["id"], charter["version"],
                proposed_segment_type="ASSOCIATIONAL",
                proposed_segment_descriptor="Riverside Teachers Association members",
                proposed_segment_required_documents=["GOVERNMENT_ID",
                                                     "ASSOCIATION_CARD"]),
            CO1)
        validate_error(resp, ApiErrorId.ERR_BOND_TYPE_MISMATCH)

    def test_effective_date_must_be_future_at_approval(self, api):
        """PRD §3.2: "Approval requires the application to still be SUBMITTED —
        anything else yields `ERR_AMENDMENT_INVALID_STATE` — and requires the
        `effective_date` to remain strictly later than the current clock date
        at the moment of approval, otherwise `ERR_EFFECTIVE_DATE_NOT_FUTURE`;
        a successful approval records the deciding regulator as
        `decided_by_user_id` and moves the application to APPROVED."

        Design: Corner/validations/effective_date_must_be_future_at_approval
        """
        set_clock("2026-08-01")
        charter, _segs = setup_charter()
        amend = file_add_segment_amendment(charter["id"], charter["version"],
                                           effective_date="2026-08-10")
        set_clock("2026-08-12")
        resp = api.approve_amendment_application(amend["id"], REG)
        validate_error(resp, ApiErrorId.ERR_EFFECTIVE_DATE_NOT_FUTURE)

    def test_amendment_double_approve_rejected(self, api):
        """PRD §3.2: "Approval requires the application to still be SUBMITTED —
        anything else yields `ERR_AMENDMENT_INVALID_STATE`"

        Design: Corner/state_machines/amendment_double_approve_rejected
        """
        set_clock("2026-08-01")
        charter, _segs = setup_charter()
        amend = file_add_segment_amendment(
            charter["id"], charter["version"], effective_date="2026-09-01",
            proposed_segment_type="ASSOCIATIONAL",
            proposed_segment_descriptor="Riverside Teachers Association members",
        )
        approved = validate_success(
            api.approve_amendment_application(amend["id"], REG))
        assert approved["status"] == "APPROVED"
        assert approved["decided_by_user_id"] == "reg-1"

        second = api.approve_amendment_application(
            amend["id"], make_regulator_headers("reg-2"))
        validate_error(second, ApiErrorId.ERR_AMENDMENT_INVALID_STATE)


class TestSegmentRetirementCascade:
    def _setup_retirement(self, api):
        """Charter with ACME + BETA segments; m1 on ACME, m2 on BETA; a
        RETIRE_SEGMENT amendment for ACME approved, effective 2026-09-01."""
        set_clock("2026-07-01")
        charter, seg_ids = setup_charter(segments=two_occupational_segments())
        seg_acme, seg_beta = seg_ids[0], seg_ids[1]
        m1 = create_member(segment_id=seg_acme, name="Retiree Ray",
                           date_of_birth="1980-01-01")
        m2 = create_member(segment_id=seg_beta, name="Stable Sal",
                           date_of_birth="1981-02-02")
        amend = file_retire_segment_amendment(
            charter["id"], [seg_acme], charter["version"],
            effective_date="2026-09-01")
        approve_amendment(amend["id"])
        return charter, seg_acme, seg_beta, m1, m2, amend

    def test_amendment_effective_sweep_gating_and_charter_version(self, api):
        """PRD §3.2: "When the epoch sweep finds an APPROVED amendment whose
        `effective_date` has been reached, the amendment becomes EFFECTIVE; the
        sweep applies all maturing amendments in order of `effective_date`
        ascending, ties broken by `created_at` ascending, and each one
        increments the charter's `version` by one."
        PRD §3.1: "it increments by one on every successful amendment
        submission and by one again whenever an amendment becomes EFFECTIVE"

        Design: Difficulty/transitive_cascade/amendment_effective_retire_segment_cascade
        """
        charter, seg_acme, seg_beta, m1, m2, amend = self._setup_retirement(api)
        v_at_creation = charter["version"]

        set_clock("2026-08-31")
        rows, _meta = validate_paginated(
            api.list_charter_amendment_applications(charter["id"], CO1))
        assert rows[0]["status"] == "APPROVED", (
            "The day before effective_date the sweep has not applied the "
            "amendment")

        set_clock("2026-09-01")
        rows, _meta = validate_paginated(
            api.list_charter_amendment_applications(charter["id"], CO1))
        assert rows[0]["status"] == "EFFECTIVE"

        after = validate_success(api.get_charter(charter["id"], CO1))
        assert after["version"] == v_at_creation + 2, (
            "One increment for the accepted submission and one for the "
            "amendment becoming EFFECTIVE")

    def test_amendment_effective_retire_segment_member_cascade(self, api):
        """PRD §3.2: "An EFFECTIVE RETIRE_SEGMENT amendment moves every listed
        segment to RETIRED with `retired_at` set to the current date, and each
        retirement cascades: for every Member whose `segment_id` is the retired
        segment, whose `eligibility_basis` is SEGMENT_MATCH, and whose status
        is ACTIVE, the system opens an EligibilityReview in OPEN status with
        reason SEGMENT_RETIRED and `flagged_by_user_id` recorded as 'system',
        and moves that member to INELIGIBLE_UNDER_REVIEW."

        Design: Difficulty/transitive_cascade/amendment_effective_retire_segment_cascade
        """
        charter, seg_acme, seg_beta, m1, m2, amend = self._setup_retirement(api)
        set_clock("2026-09-01")

        segs, _meta = validate_paginated(
            api.list_charter_segments(charter["id"], CO1))
        assert segs[0]["id"] == seg_acme
        assert segs[0]["status"] == "RETIRED"
        assert segs[0]["retired_at"] == "2026-09-01"
        assert segs[1]["id"] == seg_beta
        assert segs[1]["status"] == "ACTIVE"

        member1 = validate_success(api.get_member(m1, CO1))
        assert_member(member1)
        assert member1["status"] == "INELIGIBLE_UNDER_REVIEW"

        reviews, rmeta = validate_paginated(
            api.list_member_eligibility_reviews(m1, CO1))
        assert rmeta["total_count"] == 1
        assert reviews[0]["reason"] == "SEGMENT_RETIRED"
        assert reviews[0]["status"] == "OPEN"
        assert reviews[0]["flagged_by_user_id"] == "system"

        member2 = validate_success(api.get_member(m2, CO1))
        assert member2["status"] == "ACTIVE", (
            "A member on the surviving segment is untouched by the cascade")

    def test_segment_retirement_invalidates_pending_application_approval(self, api):
        """PRD §3.3: "a SEGMENT_MATCH application's segment must be ACTIVE at
        approval time, otherwise `ERR_SEGMENT_NOT_ACTIVE`"
        PRD §3.3: "an application citing a segment that is not ACTIVE is
        rejected with `ERR_SEGMENT_NOT_ACTIVE`, and a FAMILY or HOUSEHOLD
        application whose sponsor member is not ACTIVE is rejected with
        `ERR_SPONSOR_NOT_ELIGIBLE`. Both checks are re-evaluated at approval
        time."

        Design: Corner/validations/segment_retirement_invalidates_pending_application_approval
        """
        set_clock("2026-08-01")
        charter, seg_ids = setup_charter()
        app = file_application(segment_id=seg_ids[0], name="Pending Pat")
        amend = file_retire_segment_amendment(
            charter["id"], [seg_ids[0]], charter["version"],
            effective_date="2026-08-10")
        approve_amendment(amend["id"])
        set_clock("2026-08-10")

        resp = api.approve_membership_application(app["id"], DECIDER)
        validate_error(resp, ApiErrorId.ERR_SEGMENT_NOT_ACTIVE)
