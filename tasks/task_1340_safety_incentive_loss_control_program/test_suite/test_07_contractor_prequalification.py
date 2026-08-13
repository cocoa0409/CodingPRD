"""Contractor prequalification: registration roundtrip, the weighted score and
its band edges, the remediation/re-review cycles, the insurance-certificate
gate, and role/ownership authorization."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_contractor_org,
    assert_iso_instant_equal,
    create_contractor_record,
    get_contractor,
    make_contractor_rep_headers,
    make_safety_manager_headers,
    set_clock,
    setup_contractor_under_review,
    setup_roster,
    submit_contractor_record,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["ehs_admin_headers"]
CARRIER = TEST_USERS["carrier_consultant_headers"]


class TestContractorRegistration:
    def test_contractor_create_retrieval_roundtrip(self, api):
        """PRD §3.6: "New organizations stand in `DRAFT`."
        PRD §3.6: "Submitting for review — the `ContractorRep`'s exclusive
        operation, permitted only when the caller's identity equals the
        organization's own `id` (`ERR_UNAUTHORIZED` otherwise) — moves the
        organization to `UNDER_REVIEW` and recomputes the qualification score."

        Design: Corner/entities/contractor_create_retrieval_roundtrip
        """
        set_clock("2026-06-01T00:00:00Z")
        created = create_contractor_record(emr=0.9, trir=1.5,
                                           safety_audit_pct=88)
        fetched = validate_success(api.get_contractor_org(created["id"], ADMIN))
        assert_contractor_org(fetched)
        assert fetched["status"] == "DRAFT"
        assert fetched["emr"] == pytest.approx(0.9, abs=1e-9)
        assert fetched["trir"] == pytest.approx(1.5, abs=1e-9)
        assert fetched["safety_audit_pct"] == pytest.approx(88, abs=1e-9)
        assert fetched["insurance_cert_expires_on"] == "2026-12-15"
        assert fetched.get("prequal_score") is None, \
            "the score is computed at submission, not at registration"


class TestPrequalScore:
    def test_prequal_score_weighted_band_selection(self, api):
        """PRD §3.6: "The `prequal_score` then weighs these — forty percent EMR
        component, thirty percent TRIR component, twenty percent
        `safety_audit_pct`, ten percent insurance component. The banded
        `computed_decision` follows from the rounded score: `APPROVE` at 80.00
        or better, `CONDITIONAL` at 65.00 or better, `REJECT` below 65.00 — and
        the comparison uses the rounded two-decimal score, so 79.99 does not
        approve."

        Design: Difficulty/combinatorial_formula/prequal_score_weighted_band_selection
        """
        set_clock("2026-09-01T00:00:00Z")
        # Components: emr 0.50 -> 60; trir 0.0 -> 100; audit 80; cert 105 days
        # out -> 100. Score: 0.4*60 + 0.3*100 + 0.2*80 + 0.1*100 == 80.00.
        submitted = setup_contractor_under_review()
        assert submitted["status"] == "UNDER_REVIEW"
        assert submitted["prequal_score"] == pytest.approx(80.00, abs=1e-9)
        assert submitted["computed_decision"] == "APPROVE"

    def test_prequal_conditional_band_upper_edge_79_99(self, api):
        """PRD §3.6: "the comparison uses the rounded two-decimal score, so
        79.99 does not approve."
        PRD §3.6: "The decision itself is the `SafetyManager`'s, and it is
        mechanical: the submitted `decision` must equal the computed band. Any
        other choice is rejected with `ERR_DECISION_CONTRADICTS_SCORE`"

        Design: Corner/calculations/prequal_conditional_band_upper_edge_79_99
        """
        set_clock("2026-09-01T00:00:00Z")
        _role, employees = setup_roster()
        manager = employees["Marta M"]
        # 24 + 30 + 0.2*79.95 + 10 == 79.99: one cent of score below APPROVE.
        submitted = setup_contractor_under_review(safety_audit_pct=79.95,
                                                  name="Beta Builders")
        assert submitted["prequal_score"] == pytest.approx(79.99, abs=1e-9)
        assert submitted["computed_decision"] == "CONDITIONAL"

        resp = api.decide_contractor(submitted["id"], {"decision": "APPROVE"},
                                     make_safety_manager_headers(manager["id"]))
        validate_error(resp, ApiErrorId.ERR_DECISION_CONTRADICTS_SCORE)
        assert get_contractor(submitted["id"])["status"] == "UNDER_REVIEW"

        decided = validate_success(api.decide_contractor(
            submitted["id"], {"decision": "CONDITIONAL"},
            make_safety_manager_headers(manager["id"])))
        assert decided["status"] == "CONDITIONAL"

    def test_prequal_band_exactly_80_approves(self, api):
        """PRD §3.6: "The banded `computed_decision` follows from the rounded
        score: `APPROVE` at 80.00 or better"
        PRD §3.6: "A successful `APPROVE` stamps `prequal_valid_until` at 365
        days from the decision, and the organization stands `APPROVED` until
        the sweep ages it to `EXPIRED` past that date (§3.7)."

        Design: Difficulty/boundary_precision_check/prequal_band_exactly_80_approves
        """
        set_clock("2026-09-01T00:00:00Z")
        _role, employees = setup_roster()
        manager = employees["Marta M"]
        submitted = setup_contractor_under_review()
        assert submitted["prequal_score"] == pytest.approx(80.00, abs=1e-9), \
            "80.00 sits on the inclusive APPROVE band edge"

        decided = validate_success(api.decide_contractor(
            submitted["id"], {"decision": "APPROVE"},
            make_safety_manager_headers(manager["id"])))
        assert decided["status"] == "APPROVED"
        assert_iso_instant_equal(decided["prequal_valid_until"],
                                 "2027-09-01T00:00:00Z")


class TestContractorCycles:
    def test_contractor_prequal_cycles(self, api):
        """PRD §3.6: "Submission is possible from `DRAFT`, from `CONDITIONAL`
        (the remediation cycle, which additionally requires that at least one
        of the four metric fields actually changes in the call, else
        `ERR_INVALID_REQUEST`), from `SUSPENDED` (re-review after suspension),
        and from `EXPIRED` (renewal after lapse)."
        PRD §3.6: "An `APPROVED` contractor may also be suspended — by a
        `SafetyManager` or `EHSAdmin` — moving to `SUSPENDED` with a required
        `suspension_reason` and an optional `suspension_claim_id`"

        Design: Difficulty/non_linear_state_machine/contractor_prequal_cycles
        """
        set_clock("2026-09-01T00:00:00Z")
        _role, employees = setup_roster()
        manager = employees["Marta M"]
        # emr 0.80 -> 36; trir 2.0 -> 75; audit 100; cert 105 days -> 100:
        # 0.4*36 + 0.3*75 + 0.2*100 + 0.1*100 == 66.90.
        contractor = create_contractor_record(emr=0.80, trir=2.0,
                                              safety_audit_pct=100)
        first = submit_contractor_record(contractor["id"])
        assert first["prequal_score"] == pytest.approx(66.90, abs=1e-9)
        assert first["computed_decision"] == "CONDITIONAL"

        conditional = validate_success(api.decide_contractor(
            contractor["id"], {"decision": "CONDITIONAL"},
            make_safety_manager_headers(manager["id"])))
        assert conditional["status"] == "CONDITIONAL"

        remediated = submit_contractor_record(
            contractor["id"],
            updates={"emr": 0.50, "trir": 0.0, "safety_audit_pct": 80})
        assert remediated["status"] == "UNDER_REVIEW", \
            "CONDITIONAL resubmission with changed metrics re-enters review"
        assert remediated["prequal_score"] == pytest.approx(80.00, abs=1e-9)

        approved = validate_success(api.decide_contractor(
            contractor["id"], {"decision": "APPROVE"},
            make_safety_manager_headers(manager["id"])))
        assert approved["status"] == "APPROVED"
        assert_iso_instant_equal(approved["prequal_valid_until"],
                                 "2027-09-01T00:00:00Z")

        suspended = validate_success(api.suspend_contractor(
            contractor["id"],
            {"suspension_reason": "recordable incident on site"},
            make_safety_manager_headers(manager["id"])))
        assert suspended["status"] == "SUSPENDED"

        re_review = submit_contractor_record(contractor["id"])
        assert re_review["status"] == "UNDER_REVIEW", \
            "SUSPENDED resubmission re-enters review"
        re_approved = validate_success(api.decide_contractor(
            contractor["id"], {"decision": "APPROVE"},
            make_safety_manager_headers(manager["id"])))
        assert re_approved["status"] == "APPROVED", "the full cycle closes"


class TestContractorGates:
    def test_contractor_submit_expired_cert_rejected(self, api):
        """PRD §3.6: "In every case the caller may fold updated metrics into
        the submission itself, and the insurance certificate — after applying
        any update carried in the same call — must not expire before the
        logical today (`ERR_INSURANCE_CERT_EXPIRED`)."

        Design: Corner/validations/contractor_submit_expired_cert_rejected
        """
        set_clock("2026-06-01T00:00:00Z")
        contractor = create_contractor_record(
            name="Rusty Rigs", contact_email="ops@rusty.example", emr=0.9,
            trir=1.0, safety_audit_pct=90,
            insurance_cert_expires_on="2026-05-01")

        resp = api.submit_contractor(
            contractor["id"], {}, make_contractor_rep_headers(contractor["id"]))
        validate_error(resp, ApiErrorId.ERR_INSURANCE_CERT_EXPIRED)
        assert get_contractor(contractor["id"])["status"] == "DRAFT"

    def test_carrier_consultant_cannot_decide_contractor_returns_unauthorized(
            self, api):
        """PRD §2.1: "A request whose role is not listed among the roles
        authorized for the target endpoint — or that fails an entity-backed
        ownership check — is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD §3.6: "The decision itself is the `SafetyManager`'s, and it is
        mechanical: the submitted `decision` must equal the computed band."

        Design: Corner/rbac/carrier_consultant_cannot_decide_contractor_returns_unauthorized
        """
        set_clock("2026-09-01T00:00:00Z")
        submitted = setup_contractor_under_review()

        resp = api.decide_contractor(submitted["id"], {"decision": "APPROVE"},
                                     CARRIER)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
        assert get_contractor(submitted["id"])["status"] == "UNDER_REVIEW"

    def test_contractor_rep_cannot_submit_other_org_returns_unauthorized(
            self, api):
        """PRD §3.6: "Submitting for review — the `ContractorRep`'s exclusive
        operation, permitted only when the caller's identity equals the
        organization's own `id` (`ERR_UNAUTHORIZED` otherwise)"

        Design: Corner/rbac/contractor_rep_cannot_submit_other_org_returns_unauthorized
        """
        set_clock("2026-06-01T00:00:00Z")
        org_a = create_contractor_record(name="Org A",
                                         contact_email="a@example.com", emr=0.9,
                                         trir=1.0, safety_audit_pct=90)
        org_b = create_contractor_record(name="Org B",
                                         contact_email="b@example.com", emr=1.1,
                                         trir=2.0, safety_audit_pct=70)

        resp = api.submit_contractor(org_b["id"], {},
                                     make_contractor_rep_headers(org_a["id"]))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
        assert get_contractor(org_b["id"])["status"] == "DRAFT", \
            "a representative may submit only its own organization"
