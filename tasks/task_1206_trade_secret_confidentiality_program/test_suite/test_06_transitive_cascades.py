"""Transitive cascades: audit -> measure lapse -> posture -> disclosure return;
policy publish -> ack supersede -> reissue; counterparty bar -> NDA terminate ->
obligation anchor + disclosure reject (PRD §3.9, §3.3, §3.2)."""
import pytest

from test_helpers import (
    validate_success,
    assert_same_instant,
    ApiErrorId,
    create_counterparty,
    create_active_nda,
    create_obligation_payload,
    create_registered_asset,
    add_verified_measure,
    create_employee_record,
    create_active_employee,
    create_under_review_disclosure,
    create_clean_desk_audit_payload,
    get_pending_ack_id,
    make_employee_headers,
    TEST_USERS,
)

IP = TEST_USERS["ip_counsel_headers"]
HR = TEST_USERS["hr_partner_headers"]
SEC = TEST_USERS["security_officer_headers"]


def _setup_audit_cascade(api):
    """Asset with TECHNICAL(25)+POLICY(10)+PHYSICAL(15) VERIFIED (score 50,
    ADEQUATE); ACTIVE NDA; disclosure UNDER_REVIEW on the asset."""
    asset = create_registered_asset(
        title="Annealing schedule", description="furnace recipe",
        classification="RESTRICTED", owner_department="MFG",
        exposure_estimate_cents=700000,
    )
    m_tech = add_verified_measure(asset["id"], "TECHNICAL", title="SCADA lockdown",
                                  evidence_uri="s3://ev/scada.pdf")
    m_pol = add_verified_measure(asset["id"], "POLICY", title="Floor policy",
                                 evidence_uri="s3://ev/pol.pdf")
    m_phy = add_verified_measure(asset["id"], "PHYSICAL", title="Cage locks",
                                 evidence_uri="s3://ev/cage.pdf")
    cp = create_counterparty(legal_name="Zeta Furnaces", counterparty_type="VENDOR")
    nda = create_active_nda(
        cp["id"], template_version="t6", governing_law="OH",
        effective_date="2026-01-01T00:00:00Z", expiry_date="2027-01-01T00:00:00Z",
        survival_months=6, classification_ceiling="CROWN_JEWEL",
    )
    emp = create_employee_record(
        full_name="Kara Plant", email="kara@x.com", department="MFG",
        role_title="Lead", access_clearance="ELEVATED",
        hired_at="2026-05-01T00:00:00Z",
    )
    disc = create_under_review_disclosure(
        emp["id"], asset["id"], nda["id"],
        purpose="Maintenance support", marking_protocol="STAMPED_CONFIDENTIAL",
        planned_disclosure_date="2026-07-01T00:00:00Z",
    )
    resp = api.create_clean_desk_audit(
        create_clean_desk_audit_payload(
            department="MFG",
            window_start="2026-06-01T00:00:00Z",
            window_end="2026-06-02T00:00:00Z",
        ), SEC
    )
    audit = validate_success(resp, expected_status=201)
    return asset, m_tech, m_pol, m_phy, disc, audit


class TestAuditCriticalFindingCascade:
    def test_conduct_lapses_linked_measure_and_recomputes_posture(self, api):
        """PRD §3.9: "When critical findings exist, the conduct step cascades:
        every measure whose `id` appears in `linked_measure_ids` and whose status
        is `IMPLEMENTED` or `VERIFIED` moves to `LAPSED` in `created_at`
        ascending order, each lapse recomputes its asset's scores and posture as
        in §3.1."

        Design: Difficulty/transitive_cascade/audit_critical_finding_lapses_measure_returns_disclosure
        """
        asset, m_tech, m_pol, m_phy, _disc, audit = _setup_audit_cascade(api)
        validate_success(api.transition_clean_desk_audit(
            audit["id"],
            {"to_status": "CONDUCTED", "findings_count": 3, "critical_findings": 1,
             "linked_measure_ids": [m_phy["id"]]},
            SEC,
        ))
        measure = validate_success(api.get_measure(m_phy["id"], IP))
        assert measure["status"] == "LAPSED"
        asset_now = validate_success(api.get_asset(asset["id"], IP))
        assert asset_now["score_operational"] == pytest.approx(35.0, abs=0.01), \
            f"expected 25 + 10 + 0 = 35, got {asset_now['score_operational']}"
        assert asset_now["protection_posture"] == "DEFICIENT"
        untouched_1 = validate_success(api.get_measure(m_tech["id"], IP))
        untouched_2 = validate_success(api.get_measure(m_pol["id"], IP))
        assert untouched_1["status"] == "VERIFIED" and untouched_2["status"] == "VERIFIED", \
            "unlinked measures must be untouched"

    def test_deficient_posture_returns_under_review_disclosure(self, api):
        """PRD §3.1: "if that recompute drops the asset's posture to `DEFICIENT`,
        every disclosure request for that asset sitting in `UNDER_REVIEW` is
        returned to `RETURNED` in `created_at` ascending order."

        Design: Difficulty/transitive_cascade/audit_critical_finding_lapses_measure_returns_disclosure
        """
        asset, _m_tech, _m_pol, m_phy, disc, audit = _setup_audit_cascade(api)
        validate_success(api.transition_clean_desk_audit(
            audit["id"],
            {"to_status": "CONDUCTED", "findings_count": 3, "critical_findings": 1,
             "linked_measure_ids": [m_phy["id"]]},
            SEC,
        ))
        disc_now = validate_success(api.get_disclosure(disc["id"], IP))
        assert disc_now["status"] == "RETURNED", \
            "posture drop to DEFICIENT must auto-return the UNDER_REVIEW disclosure"


class TestPolicyPublishCascade:
    def _setup_signed_employee(self, api):
        return create_active_employee(
            complete_training=False,
            full_name="Liam Hires", email="liam@x.com", department="HR",
            role_title="Coordinator", access_clearance="STANDARD",
            hired_at="2026-05-01T00:00:00Z",
        )

    def test_publish_supersedes_signed_ack_and_reissues(self, api):
        """PRD §3.3: "On publish, every `SIGNED` acknowledgment whose
        `policy_version` differs from the new version moves to `SUPERSEDED` in
        `created_at` ascending order."
        PRD §3.3: "For every employee in `PREBOARDING`, `ACTIVE`, or `NOTICE` —
        again in `created_at` ascending order — a fresh `PENDING` acknowledgment
        is created at the new version, due ten days from the publish moment. The
        publish response reports the new `current_policy_version`, the
        `superseded_count`, and the `reissued_count`."

        Design: Difficulty/transitive_cascade/policy_publish_supersedes_and_reissues_acks
        """
        emp = self._setup_signed_employee(api)
        ack_v1 = get_pending_ack_id(emp["id"], policy_version="v1") if False else None
        # locate the SIGNED v1 ack
        resp = api.list_acknowledgments(HR, params={"employee_id": emp["id"], "status": "SIGNED"})
        ack_v1 = validate_success(resp)[0]["id"]
        pub = validate_success(api.publish_policy({"new_version": "v2"}, IP))
        assert pub["superseded_count"] == 1 and pub["reissued_count"] == 1
        old = validate_success(api.get_acknowledgment(ack_v1, HR))
        assert old["status"] == "SUPERSEDED"
        resp = api.list_acknowledgments(
            HR, params={"employee_id": emp["id"], "status": "PENDING"}
        )
        rows = validate_success(resp)
        assert len(rows) == 1
        assert rows[0]["policy_version"] == "v2" and rows[0]["status"] == "PENDING"

    def test_publish_does_not_deactivate_employee(self, api):
        """PRD §3.3: "Activation of the employee — `PREBOARDING → ACTIVE` —
        requires a `SIGNED` acknowledgment on the current policy version to
        exist, otherwise `ERR_ACK_REQUIRED`."

        Design: Difficulty/transitive_cascade/policy_publish_supersedes_and_reissues_acks
        """
        emp = self._setup_signed_employee(api)
        validate_success(api.publish_policy({"new_version": "v2"}, IP))
        emp_now = validate_success(api.get_employee(emp["id"], HR))
        assert emp_now["status"] == "ACTIVE", \
            "publish supersedes acks but does not deactivate the employee"


def _setup_counterparty_bar(api):
    """ACTIVE counterparty with ACTIVE NDA carrying a PENDING RETURN_OR_DESTROY
    obligation (due_at null) and an UNDER_REVIEW disclosure; clock pinned at
    2026-06-15."""
    cp = create_counterparty(legal_name="Theta Recycling", counterparty_type="VENDOR")
    nda = create_active_nda(
        cp["id"], template_version="t7", governing_law="IL",
        effective_date="2026-01-01T00:00:00Z", expiry_date="2027-06-01T00:00:00Z",
        survival_months=12, classification_ceiling="RESTRICTED",
    )
    resp = api.create_obligation(
        create_obligation_payload(nda["id"], obligation_type="RETURN_OR_DESTROY"), IP
    )
    ob = validate_success(resp, expected_status=201)
    asset = create_registered_asset(
        title="Solvent blend ratios", description="chemistry",
        classification="RESTRICTED", owner_department="CHEM",
        exposure_estimate_cents=600000,
    )
    emp = create_employee_record(
        full_name="Mona Chemist", email="mona@x.com", department="CHEM",
        role_title="Chemist", access_clearance="ELEVATED",
        hired_at="2026-05-01T00:00:00Z",
    )
    disc = create_under_review_disclosure(
        emp["id"], asset["id"], nda["id"],
        purpose="Disposal quoting", marking_protocol="ENCRYPTED_DELIVERY",
        planned_disclosure_date="2026-08-01T00:00:00Z",
    )
    api.set_clock({"to_iso8601": "2026-06-15T00:00:00Z"}, IP)
    return cp, nda, ob, disc


class TestCounterpartyBarCascade:
    def test_bar_terminates_nda_and_anchors_return_obligation(self, api):
        """PRD §3.2: "Barring — `ACTIVE → BARRED` or `SUSPENDED → BARRED` — is
        the decisive break: every NDA of the counterparty in `DRAFT`, `SENT`,
        `EXECUTED`, `ACTIVE`, or `BREACH_ALLEGED` is terminated with its
        `terminated_at` stamped at the current clock, processed in `created_at`
        ascending order."
        PRD §3.2: "when an agreement terminates, each of its `PENDING`
        return-or-destroy obligations with an empty `due_at` receives
        `terminated_at` plus thirty days."

        Design: Difficulty/transitive_cascade/counterparty_bar_terminates_nda_anchors_obligation
        """
        cp, nda, ob, _disc = _setup_counterparty_bar(api)
        validate_success(api.transition_counterparty(cp["id"], {"to_status": "BARRED"}, IP))
        nda_now = validate_success(api.get_nda(nda["id"], IP))
        assert nda_now["status"] == "TERMINATED"
        assert_same_instant(nda_now["terminated_at"], "2026-06-15T00:00:00Z",
                            label="terminated_at")
        ob_now = validate_success(api.get_obligation(ob["id"], IP))
        assert_same_instant(ob_now["due_at"], "2026-07-15T00:00:00Z",
                            label=f"terminated_at + 30 days = 2026-07-15, got {ob_now['due_at']}")
        assert ob_now["status"] == "PENDING", "anchoring does not change status"

    def test_bar_rejects_open_disclosures(self, api):
        """PRD §3.2: "every disclosure request governed by one of those NDAs in
        `DRAFT`, `SUBMITTED`, or `UNDER_REVIEW` is rejected outright, moving to
        `REJECTED`."

        Design: Difficulty/transitive_cascade/counterparty_bar_terminates_nda_anchors_obligation
        """
        cp, _nda, _ob, disc = _setup_counterparty_bar(api)
        validate_success(api.transition_counterparty(cp["id"], {"to_status": "BARRED"}, IP))
        disc_now = validate_success(api.get_disclosure(disc["id"], IP))
        assert disc_now["status"] == "REJECTED"
