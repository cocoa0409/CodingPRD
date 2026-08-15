"""Transitive cascades: case completion -> assignments/claims/findings/audit
scores, and credential shortening -> findings -> audit scores (PRD §2.7,
§3.6, §3.7, §3.9)."""
from test_helpers import (
    AUDITOR,
    SCHED,
    assert_version_incremented,
    create_case,
    create_crna,
    create_fee_schedule,
    create_physician,
    create_published_roster,
    create_site,
    get_success_data,
    list_audits,
    list_claims,
    list_findings,
    propose_and_confirm,
    propose_assignment,
    run_case_clock,
    setup_credential_lapse_audit,
    setup_site_fee_roster,
    api_client,
)


def _directed_case_without_attestation(api):
    """CRNA primary CONFIRMED + directing physician CONFIRMED, NO attestation;
    case started at 09:00, clock at 11:00."""
    site = create_site()
    create_fee_schedule("P100", 5)
    director = create_physician("Dr. Direct")
    crna = create_crna("Crna One")
    roster = create_published_roster(site["id"], required_primary_slots=1,
                                     scheduled_day_end_minute=1020)
    case = create_case(roster["id"], scheduled_start_minute=540,
                       scheduled_end_minute=660)
    prim = propose_and_confirm(case["id"], crna["id"], "CRNA", "CASE_PRIMARY")
    directing = propose_and_confirm(case["id"], director["id"],
                                    "ANESTHESIOLOGIST", "CASE_DIRECTING")
    run_case_clock(case["id"], "2026-08-10T09:00:00Z", "2026-08-10T11:00:00Z")
    return {"site": site, "roster": roster, "case": case, "director": director,
            "primary": crna, "primary_assignment": prim,
            "directing_assignment": directing}


class TestCaseCompletionCascade:
    def test_completion_cascades_to_claims_finding_and_scores(self, api):
        """PRD §3.6: "One `DRAFT` billing claim is auto-created per assignment
        that was `CONFIRMED` at the moment of completion — assignments still
        `PROPOSED` at completion generate no claim at all."
        PRD §3.6: "If a `CASE_DIRECTING` assignment was `CONFIRMED` at
        completion and the attestation matching that case and directing
        physician is not `VERIFIED` (missing, `IN_PROGRESS`, `SUBMITTED`, or
        `REJECTED` all count as not verified), the system raises a `TEFRA_GAP`
        finding (severity `MAJOR`) on the roster's `OPEN` compliance audit,
        creating an `OPEN` audit first if none exists".

        Design: Difficulty/transitive_cascade/case_completion_cascade_to_audit_scores
        """
        ctx = _directed_case_without_attestation(api)
        case_id = ctx["case"]["id"]
        completed = get_success_data(api.complete_case(case_id, SCHED))
        # Hop 1: both CONFIRMED assignments close out COMPLETED.
        prim_after = get_success_data(
            api.get_assignment(ctx["primary_assignment"]["id"], SCHED))
        dir_after = get_success_data(
            api.get_assignment(ctx["directing_assignment"]["id"], SCHED))
        assert prim_after["status"] == "COMPLETED"
        assert dir_after["status"] == "COMPLETED"
        # Hop 2a: attestation missing -> primary QZ at 7500; physician AD flat.
        prim_claims = list_claims({"case_id": case_id,
                                   "provider_id": ctx["primary"]["id"]})
        phys_claims = list_claims({"case_id": case_id,
                                   "provider_id": ctx["director"]["id"]})
        assert len(prim_claims) == 1 and len(phys_claims) == 1
        assert prim_claims[0]["modifier_code"] == "QZ"
        assert prim_claims[0]["charge_cents"] == 97500  # 13.0 units x 7500
        assert phys_claims[0]["modifier_code"] == "AD"
        assert phys_claims[0]["units_total"] == 3.0
        assert phys_claims[0]["charge_cents"] == 12000  # 3.0 x 4000
        # Hop 2b: final charge is the claim sum.
        assert completed["final_charge_cents"] == 109500
        # Hop 3+4: TEFRA_GAP finding on an auto-created OPEN audit; scores.
        audits = list_audits({"roster_id": ctx["roster"]["id"]})
        assert len(audits) == 1, "completion must auto-create the OPEN audit"
        findings = list_findings({"audit_id": audits[0]["id"]})
        assert len(findings) == 1
        assert findings[0]["finding_type"] == "TEFRA_GAP"
        assert findings[0]["severity"] == "MAJOR"
        assert findings[0]["status"] == "OPEN"
        assert findings[0]["case_id"] == case_id
        assert audits[0]["period_score"] == 30
        assert audits[0]["realtime_score"] == 0
        assert audits[0]["risk_band"] == "ELEVATED"

    def test_completion_sets_final_charge_to_claim_sum(self, api):
        """PRD §3.6: "The case's `final_charge_cents` is set to the sum of the
        created claims' `charge_cents`."
        PRD §3.7: "the physician's claim bills `AD` at a flat three units (no
        time units at all), charged as three units times 4,000 cents per unit."

        Design: Difficulty/transitive_cascade/case_completion_cascade_to_audit_scores
        """
        ctx = _directed_case_without_attestation(api)
        case_id = ctx["case"]["id"]
        completed = get_success_data(api.complete_case(case_id, SCHED))
        claims = list_claims({"case_id": case_id})
        assert len(claims) == 2
        modifiers = sorted(c["modifier_code"] for c in claims)
        assert modifiers == ["AD", "QZ"], (
            f"unverified direction must collapse to AD + QZ, got {modifiers}")
        assert sum(c["charge_cents"] for c in claims) == \
            completed["final_charge_cents"]


class TestCredentialShortenCascade:
    def test_shortening_expiry_raises_one_finding_per_exposed_assignment(self, api):
        """PRD §2.7: "When a credential patch leaves any of the provider's
        `PROPOSED` or `CONFIRMED` case assignments with a roster `service_date`
        strictly later than the earlier of the two new expiry dates, the system
        raises a `CREDENTIAL_LAPSE` finding (severity `MINOR`) on that roster's
        `OPEN` compliance audit, creating the audit if none exists, and the
        audit's scores recompute as described in §3.9."

        Design: Difficulty/transitive_cascade/credential_shorten_cascade_to_audit_scores
        """
        ctx = setup_credential_lapse_audit(num_cases=2)
        audit = ctx["audit"]
        assert audit is not None, "credential shortening must auto-create the audit"
        assert audit["status"] == "OPEN"
        findings = list_findings({"audit_id": audit["id"],
                                  "finding_type": "CREDENTIAL_LAPSE"})
        assert len(findings) == 2, (
            f"one finding per exposed PROPOSED assignment, got {len(findings)}")
        finding_assignment_ids = {f["assignment_id"] for f in findings}
        assert finding_assignment_ids == {a["id"] for a in ctx["assignments"]}
        # Both cases still SCHEDULED -> realtime bucket; period empty.
        assert audit["realtime_score"] == 20
        assert audit["period_score"] == 0
        assert audit["risk_band"] == "LOW"

    def test_patch_increments_provider_version_once_without_suspension(self, api):
        """PRD §2.7: "If the patch leaves either expiry still before the clock
        date, the provider remains `SUSPENDED`, but the patch itself still
        succeeds and still increments `version`."
        PRD §2.5: "`version`, an integer that starts at its initial value on
        creation and increments by exactly one on every mutation of that
        resource".

        Design: Difficulty/transitive_cascade/credential_shorten_cascade_to_audit_scores
        """
        ctx = setup_credential_lapse_audit(num_cases=1)
        patched = ctx["patched_provider"]
        # Shortened expiries (2026-08-08) are still >= the default clock date
        # (2026-08-01), so the provider is NOT suspended by this patch.
        assert patched["status"] == "ACTIVE"
        assert_version_incremented(ctx["provider"]["version"],
                                   patched["version"], "credential patch")
