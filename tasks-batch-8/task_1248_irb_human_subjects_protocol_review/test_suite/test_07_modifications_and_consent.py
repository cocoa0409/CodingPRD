"""Modifications, consent-document waiver adjudication, the
single-approved-document invariant, and protocol-level OCC
(PRD §2.8, §3.3, §3.7, §3.8).
"""
from test_helpers import (
    ApiErrorId,
    approve_consent_document,
    create_draft_protocol,
    create_modification_ok,
    get_protocol,
    get_success_data,
    make_chair_headers,
    make_pi_headers,
    register_chair,
    register_investigator,
    setup_approved_protocol,
    suspend_protocol_via_confirmed_finding,
    unique_email,
    upload_consent,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS

COORDINATOR = TEST_USERS["coordinator_headers"]


class TestApprovedConsentCardinality:
    def _setup_modification_with_new_consent(self, api):
        """Protocol APPROVED with consent D1 APPROVED; D2 uploaded (SUBMITTED);
        MINOR modification referencing D2 filed at the current version."""
        scenario = setup_approved_protocol()
        inv, chair, proto = (
            scenario["investigator"], scenario["chair"], scenario["protocol"],
        )
        d1 = scenario["consent_document"]
        d2 = upload_consent(proto["id"], inv["id"], file_ref="s3://consent/study-v2.pdf")
        pv = get_protocol(proto["id"])["version"]
        mod = create_modification_ok(
            proto["id"], inv["id"], pv, scope="MINOR",
            description="update consent wording", new_consent_document_id=d2["id"],
        )
        return scenario, d1, d2, mod

    def test_approved_consent_cardinality_conserved_on_approval(self, api):
        """PRD §3.7: "on approval the named document moves to `APPROVED` and
        the protocol's previously `APPROVED` document moves to `SUPERSEDED`,
        conserving the single-approved-document invariant". PRD §2.10: "at most
        one consent document per protocol may be `APPROVED` at any moment, so
        approving a new document always supersedes the previously approved
        one."

        Design: Difficulty/compensating_invariant/approved_consent_cardinality_conserved
        """
        scenario, d1, d2, mod = self._setup_modification_with_new_consent(api)
        proto, chair = scenario["protocol"], scenario["chair"]

        data = validate_success(
            api.adjudicate_modification(
                mod["id"], {"outcome": "APPROVE"}, make_chair_headers(chair["id"])
            )
        )
        assert data["status"] == "APPROVED"

        d2_after = get_success_data(api.get_consent_document(d2["id"], COORDINATOR))
        d1_after = get_success_data(api.get_consent_document(d1["id"], COORDINATOR))
        assert d2_after["status"] == "APPROVED", "forward action approves D2"
        assert d1_after["status"] == "SUPERSEDED", "compensating action supersedes D1"

        rows, meta = validate_paginated(
            api.list_consent_documents(proto["id"], COORDINATOR,
                                       params={"status": "APPROVED"})
        )
        assert len(rows) == 1, (
            f"Exactly one APPROVED document per protocol, got {len(rows)}"
        )
        assert rows[0]["id"] == d2["id"]

    def test_approved_consent_version_seq_and_modification_status(self, api):
        """PRD §3.3: "The server assigns each upload a `version_seq` equal to
        one more than the highest existing sequence number on that protocol".
        PRD §3.7: "A `MINOR` modification may be adjudicated directly by the
        chair with an `outcome` of `APPROVE` or `DENY`".

        Design: Difficulty/compensating_invariant/approved_consent_cardinality_conserved
        """
        scenario, _d1, d2, mod = self._setup_modification_with_new_consent(api)
        chair = scenario["chair"]

        assert d2["version_seq"] == 2, (
            f"Second upload on the protocol must be version_seq 2, got {d2['version_seq']}"
        )

        data = validate_success(
            api.adjudicate_modification(
                mod["id"], {"outcome": "APPROVE"}, make_chair_headers(chair["id"])
            )
        )
        assert data["status"] == "APPROVED"
        mod_after = get_success_data(api.get_modification(mod["id"], COORDINATOR))
        assert mod_after["status"] == "APPROVED"


class TestWaiverCriteriaGate:
    def test_waiver_criteria_gate_on_consent_approval(self, api):
        """PRD §3.3: "Approval carries a safety condition: when the document's
        `waiver_type` is anything other than `NONE`, all four waiver-criterion
        flags must be true, and approving without them is rejected with
        `ERR_WAIVER_CRITERIA_NOT_MET`."

        Design: Corner/validations/waiver_criteria_gate_on_consent_approval
        """
        inv = register_investigator()
        chair = register_chair(email=unique_email("chair"))
        proto = create_draft_protocol(inv["id"], title="Waiver Study")

        d_bad = upload_consent(
            proto["id"], inv["id"], file_ref="s3://consent/wbad.pdf",
            waiver_type="WAIVER_OF_CONSENT",
            waiver_criterion_minimal_risk=True,
            waiver_criterion_rights_not_adversely_affected=True,
            waiver_criterion_impracticable_without_waiver=True,
            waiver_criterion_debrief_when_appropriate=False,
        )
        d_good = upload_consent(
            proto["id"], inv["id"], file_ref="s3://consent/wgood.pdf",
            waiver_type="WAIVER_OF_CONSENT",
            waiver_criterion_minimal_risk=True,
            waiver_criterion_rights_not_adversely_affected=True,
            waiver_criterion_impracticable_without_waiver=True,
            waiver_criterion_debrief_when_appropriate=True,
        )

        resp = api.review_consent_document(
            d_bad["id"], {"outcome": "APPROVE"}, make_chair_headers(chair["id"])
        )
        validate_error(resp, ApiErrorId.ERR_WAIVER_CRITERIA_NOT_MET)
        assert get_success_data(
            api.get_consent_document(d_bad["id"], COORDINATOR)
        )["status"] == "SUBMITTED"

        data = validate_success(
            api.review_consent_document(
                d_good["id"], {"outcome": "APPROVE"}, make_chair_headers(chair["id"])
            )
        )
        assert data["status"] == "APPROVED"


class TestModificationConsentReference:
    def test_modification_referencing_unsubmitted_consent_rejected(self, api):
        """PRD §3.7: "When `new_consent_document_id` is set, that document must
        currently be `SUBMITTED`, else `ERR_CONSENT_DOC_NOT_SUBMITTED`".

        Design: Corner/validations/modification_referencing_unsubmitted_consent_rejected
        """
        scenario = setup_approved_protocol()
        inv, chair, proto = (
            scenario["investigator"], scenario["chair"], scenario["protocol"],
        )
        d1 = scenario["consent_document"]

        d2 = upload_consent(proto["id"], inv["id"], file_ref="s3://consent/ucs2.pdf")
        # REQUIRE_CHANGES is terminal for that version: D2 is no longer SUBMITTED.
        validate_success(
            api.review_consent_document(
                d2["id"], {"outcome": "REQUIRE_CHANGES"},
                make_chair_headers(chair["id"]),
            )
        )

        pv = get_protocol(proto["id"])["version"]
        mod = create_modification_ok(
            proto["id"], inv["id"], pv, scope="MINOR", description="swap consent",
            new_consent_document_id=d2["id"],
        )
        resp = api.adjudicate_modification(
            mod["id"], {"outcome": "APPROVE"}, make_chair_headers(chair["id"])
        )
        validate_error(resp, ApiErrorId.ERR_CONSENT_DOC_NOT_SUBMITTED)

        mod_after = get_success_data(api.get_modification(mod["id"], COORDINATOR))
        assert mod_after["status"] == "SUBMITTED"
        d1_after = get_success_data(api.get_consent_document(d1["id"], COORDINATOR))
        assert d1_after["status"] == "APPROVED", (
            "The failed approval must leave the sole approved document in place"
        )


class TestModificationScopeGateOnSuspension:
    def test_modification_scope_gate_on_suspended_protocol(self, api):
        """PRD §3.7: "The protocol must be `APPROVED` — with one carve-out:
        while a protocol is `SUSPENDED`, only a `MINOR` safety amendment may be
        filed, and attempting a `MAJOR` one is rejected with
        `ERR_INVALID_STATE`."

        Design: Corner/state_machines/modification_scope_gate_on_suspended_protocol
        """
        scenario = setup_approved_protocol()
        inv, chair, proto = (
            scenario["investigator"], scenario["chair"], scenario["protocol"],
        )
        suspend_protocol_via_confirmed_finding(proto["id"], reason="safety audit")
        assert get_protocol(proto["id"])["status"] == "SUSPENDED"

        # MINOR safety amendment may be filed and chair-approved.
        pv = get_protocol(proto["id"])["version"]
        mod_minor = create_modification_ok(
            proto["id"], inv["id"], pv, scope="MINOR",
            description="safety wording fix",
        )
        data = validate_success(
            api.adjudicate_modification(
                mod_minor["id"], {"outcome": "APPROVE"},
                make_chair_headers(chair["id"]),
            )
        )
        assert data["status"] == "APPROVED"

        # A MAJOR amendment on the same SUSPENDED protocol is rejected.
        pv2 = get_protocol(proto["id"])["version"]
        resp = api.create_modification(
            proto["id"],
            {"scope": "MAJOR", "description": "add a cohort",
             "expected_protocol_version": pv2},
            make_pi_headers(inv["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_protocol(proto["id"])["status"] == "SUSPENDED"


class TestProtocolOptimisticConcurrency:
    def test_occ_stale_protocol_version_rejected(self, api):
        """PRD §2.8: "Because filing a modification itself advances the
        protocol's `version` — as does approving a modification and every other
        protocol mutation — a writer holding an older value is composing its
        amendment against a protocol state it has not observed. When
        `expected_protocol_version` does not match the protocol's current
        `version`, the filing is rejected with `ERR_STALE_PROTOCOL_VERSION`
        (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_stale_protocol_version_rejected
        """
        scenario = setup_approved_protocol()
        inv, proto = scenario["investigator"], scenario["protocol"]
        pv = get_protocol(proto["id"])["version"]

        mod1 = create_modification_ok(
            proto["id"], inv["id"], pv, scope="MINOR",
            description="first amendment",
        )
        assert mod1["status"] == "SUBMITTED"

        # The first filing bumped the protocol version; the stale value fails.
        resp = api.create_modification(
            proto["id"],
            {"scope": "MINOR", "description": "second amendment with stale version",
             "expected_protocol_version": pv},
            make_pi_headers(inv["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_STALE_PROTOCOL_VERSION)

        rows, _meta = validate_paginated(
            api.list_modifications(proto["id"], COORDINATOR)
        )
        assert len(rows) == 1, (
            f"Only the first filing may persist, got {len(rows)}"
        )
