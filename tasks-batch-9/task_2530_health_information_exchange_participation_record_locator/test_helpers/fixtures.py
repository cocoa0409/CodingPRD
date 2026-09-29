"""Composite fixtures that build multi-step preconditions.

Every individual test runs against a freshly started server with an empty store,
so every precondition in this module is built from scratch through the PRD's own
endpoints. Nothing here reaches around the API.

The workhorse is :class:`HieHarness`, a thin orchestration layer over
``ApiClient`` exposing one method per recurring setup chain — register a
participant, drive it to conformance testing, certify it, give it an operational
document feed, contribute a record, open an emergency session, issue an invoice.
The pytest fixtures at the bottom of the file expose the harness itself plus the
most frequently needed end states.
"""

from typing import Any, Dict, List, Optional, Tuple

import pytest

from prd_bench_local_runner.testing import get_success_data, validate_success

from test_helpers.api_client import ApiClient, api_client
from test_helpers.constants import DEFAULT_CLOCK
from test_helpers.factories import (
    VALID_JUSTIFICATION,
    consent_policy_payload,
    conformance_result_payload,
    conformance_test_payload,
    invoice_payload,
    participant_payload,
    patient_record_payload,
    quality_sample_payload,
    subscription_payload,
    threshold_config_payload,
)
from test_helpers.test_users import (
    CLINICIAN_USER_ID,
    HIE_ADMIN_CERTIFIER_USER_ID,
    HIE_ADMIN_SIGNATORY_USER_ID,
    PRIVACY_OFFICER_USER_ID,
    make_clinician_headers,
    make_hie_admin_headers,
    make_participant_admin_headers,
    make_privacy_officer_headers,
)


class HieHarness:
    """Setup orchestration over the record locator API."""

    def __init__(self, client: ApiClient):
        self.client = client
        self.admin = make_hie_admin_headers()
        self.signatory = make_hie_admin_headers(HIE_ADMIN_SIGNATORY_USER_ID)
        self.certifier = make_hie_admin_headers(HIE_ADMIN_CERTIFIER_USER_ID)
        self.privacy_officer = make_privacy_officer_headers()
        self.clinician = make_clinician_headers()
        self._label_counter = 0

    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------

    def set_clock(self, to_iso8601: str) -> str:
        """Move the logical clock and return the newly effective instant."""
        response = self.client.set_logical_clock(self.admin, to_iso8601=to_iso8601)
        data = validate_success(response, 200)
        return data["current_utc"]

    def _next_label(self, stem: str) -> str:
        self._label_counter += 1
        return f"{stem}-{self._label_counter:03d}"

    # ------------------------------------------------------------------
    # Governance generations
    # ------------------------------------------------------------------

    def activate_threshold_config(self, **overrides) -> Dict[str, Any]:
        """Draft and activate a tuning generation; returns the activated row."""
        headers = overrides.pop("headers", self.privacy_officer)
        overrides.setdefault("config_label", self._next_label("REF-PROB"))
        draft = get_success_data(
            self.client.draft_match_threshold_config(
                headers, **threshold_config_payload(**overrides)
            )
        )
        return validate_success(
            self.client.activate_match_threshold_config(headers, draft["id"]), 200
        )

    def draft_threshold_config(self, **overrides) -> Dict[str, Any]:
        """Draft a tuning generation and leave it in DRAFT."""
        headers = overrides.pop("headers", self.privacy_officer)
        overrides.setdefault("config_label", self._next_label("DRAFT-PROB"))
        return get_success_data(
            self.client.draft_match_threshold_config(
                headers, **threshold_config_payload(**overrides)
            )
        )

    def activate_consent_policy(self, **overrides) -> Dict[str, Any]:
        """Draft and activate a statewide policy generation; returns the activated row."""
        headers = overrides.pop("headers", self.privacy_officer)
        overrides.setdefault("policy_version", self._next_label("SP-2026"))
        draft = get_success_data(
            self.client.draft_consent_policy(headers, **consent_policy_payload(**overrides))
        )
        return validate_success(self.client.activate_consent_policy(headers, draft["id"]), 200)

    def draft_consent_policy(self, **overrides) -> Dict[str, Any]:
        """Draft a statewide policy generation and leave it in DRAFT."""
        headers = overrides.pop("headers", self.privacy_officer)
        overrides.setdefault("policy_version", self._next_label("DRAFT-SP"))
        return get_success_data(
            self.client.draft_consent_policy(headers, **consent_policy_payload(**overrides))
        )

    def activate_governance(self) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """Both generations everything downstream needs: a policy and a tuning config."""
        return self.activate_consent_policy(), self.activate_threshold_config()

    # ------------------------------------------------------------------
    # Tier 1: participant state progression
    # ------------------------------------------------------------------

    def register_participant(self, **overrides) -> Dict[str, Any]:
        """Register a participant; it lands in APPLIED."""
        headers = overrides.pop("headers", self.admin)
        overrides.setdefault("legal_name", self._next_label("Participant Org"))
        overrides.setdefault(
            "primary_contact_email", f"hie@{self._label_counter:03d}.example"
        )
        return get_success_data(
            self.client.register_participant(headers, **participant_payload(**overrides))
        )

    def submit_for_legal_review(self, participant_id: str) -> Dict[str, Any]:
        """APPLIED -> LEGAL_REVIEW, driven by the participant's own administrator."""
        return validate_success(
            self.client.transition_onboarding(
                make_participant_admin_headers(participant_id),
                participant_id,
                action="SUBMIT_FOR_LEGAL_REVIEW",
            ),
            200,
        )

    def execute_agreement(
        self,
        participant_id: str,
        agreement_version: str = "MSA-2026.1",
        signed_at: str = "2026-07-15T00:00:00Z",
        headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """LEGAL_REVIEW -> AGREEMENT_EXECUTED, which continues to CONFORMANCE_TESTING."""
        return validate_success(
            self.client.transition_onboarding(
                headers or self.signatory,
                participant_id,
                action="EXECUTE_AGREEMENT",
                agreement_version=agreement_version,
                signed_at=signed_at,
            ),
            200,
        )

    def participant_in_conformance_testing(self, **overrides) -> Dict[str, Any]:
        """Register and drive a participant all the way to CONFORMANCE_TESTING."""
        signatory = overrides.pop("signatory_headers", None)
        participant = self.register_participant(**overrides)
        self.submit_for_legal_review(participant["id"])
        return self.execute_agreement(participant["id"], headers=signatory)

    def pass_profile(self, participant_id: str, profile: str) -> Dict[str, Any]:
        """Book a run for one profile and pass it outright."""
        run = get_success_data(
            self.client.schedule_conformance_test(
                self.admin, participant_id, **conformance_test_payload(profile=profile)
            )
        )
        return validate_success(
            self.client.submit_conformance_result(
                self.admin, run["id"], **conformance_result_payload()
            ),
            200,
        )

    def fail_profile(
        self, participant_id: str, profile: str, **result_overrides
    ) -> Dict[str, Any]:
        """Book a run for one profile and fail it on pass rate."""
        run = get_success_data(
            self.client.schedule_conformance_test(
                self.admin, participant_id, **conformance_test_payload(profile=profile)
            )
        )
        result_overrides.setdefault("assertions_total", 200)
        result_overrides.setdefault("assertions_passed", 100)
        return validate_success(
            self.client.submit_conformance_result(
                self.admin, run["id"], **conformance_result_payload(**result_overrides)
            ),
            200,
        )

    def certified_participant(self, **overrides) -> Dict[str, Any]:
        """A participant holding all three required profiles and certified."""
        certifier = overrides.pop("certifier_headers", None)
        participant = self.participant_in_conformance_testing(**overrides)
        for profile in ("ADT_PUBLISHER", "DOCUMENT_SOURCE", "QUERY_RESPONDER"):
            self.pass_profile(participant["id"], profile)
        return validate_success(
            self.client.transition_onboarding(
                certifier or self.certifier, participant["id"], action="CERTIFY"
            ),
            200,
        )

    def get_participant(self, participant_id: str) -> Dict[str, Any]:
        return validate_success(self.client.get_participant(self.admin, participant_id), 200)

    def participant_version(self, participant_id: str) -> int:
        return self.get_participant(participant_id)["version"]

    # ------------------------------------------------------------------
    # Tier 2: feeds, samples and the scorecard
    # ------------------------------------------------------------------

    def provision_feed(self, participant_id: str, feed_type: str = "CCDA") -> Dict[str, Any]:
        """Provision a feed, reading the participant's live version for the guard."""
        return get_success_data(
            self.client.provision_data_feed(
                self.admin,
                participant_id,
                feed_type=feed_type,
                expected_participant_version=self.participant_version(participant_id),
            )
        )

    def record_sample(self, data_feed_id: str, **overrides) -> Dict[str, Any]:
        """Record one immutable measurement window on a feed."""
        return get_success_data(
            self.client.record_quality_sample(
                self.admin, data_feed_id, **quality_sample_payload(**overrides)
            )
        )

    def operational_feed(
        self, participant_id: str, feed_type: str = "CCDA", **sample_overrides
    ) -> Dict[str, Any]:
        """A feed carrying one clean sample, so its status is MONITORED."""
        feed = self.provision_feed(participant_id, feed_type=feed_type)
        self.record_sample(feed["id"], **sample_overrides)
        return self.get_data_feed(feed["id"])

    def get_data_feed(self, data_feed_id: str) -> Dict[str, Any]:
        return validate_success(self.client.get_data_feed(self.admin, data_feed_id), 200)

    def get_scorecard(self, participant_id: str) -> Dict[str, Any]:
        return validate_success(
            self.client.get_participant_scorecard(self.admin, participant_id), 200
        )

    def certified_participant_with_document_feed(self, **overrides) -> Dict[str, Any]:
        """The precondition every locator query needs: CERTIFIED plus a live CCDA feed."""
        participant = self.certified_participant(**overrides)
        self.operational_feed(participant["id"], feed_type="CCDA")
        return self.get_participant(participant["id"])

    # ------------------------------------------------------------------
    # Tier 3: records, clusters and links
    # ------------------------------------------------------------------

    def contribute_record(self, participant_id: str, **overrides) -> Dict[str, Any]:
        """Contribute one patient record, scoring it against every eligible candidate."""
        headers = overrides.pop("headers", make_participant_admin_headers(participant_id))
        overrides.setdefault("source_mrn", self._next_label("MRN"))
        return get_success_data(
            self.client.contribute_patient_record(
                headers, participant_id, **patient_record_payload(**overrides)
            )
        )

    def get_record(self, record_id: str) -> Dict[str, Any]:
        return validate_success(self.client.get_patient_record(self.admin, record_id), 200)

    def get_cluster(self, cluster_id: str) -> Dict[str, Any]:
        return validate_success(self.client.get_identity_cluster(self.admin, cluster_id), 200)

    def cluster_version(self, cluster_id: str) -> int:
        return self.get_cluster(cluster_id)["version"]

    def list_links_for_record(self, record_id: str) -> List[Dict[str, Any]]:
        """Every link naming this record on either side, oldest first."""
        left = validate_success(
            self.client.list_match_links(self.admin, left_record_id=record_id, limit=100), 200
        )
        right = validate_success(
            self.client.list_match_links(self.admin, right_record_id=record_id, limit=100), 200
        )
        combined = {row["id"]: row for row in left + right}
        return sorted(combined.values(), key=lambda row: row["created_at"])

    def only_link_between(self, record_id: str) -> Dict[str, Any]:
        """The single link a two-record scenario produces."""
        links = self.list_links_for_record(record_id)
        assert len(links) == 1, f"expected exactly one link for {record_id}, got {len(links)}"
        return links[0]

    def two_participant_record_pair(
        self,
        left_overrides: Optional[Dict[str, Any]] = None,
        right_overrides: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Two certified participants, one record each, and the single link between them.

        Only cross-participant pairs are ever proposed, so a scored pair always
        needs two distinct contributors.
        """
        left_participant = self.certified_participant()
        right_participant = self.certified_participant()
        left_record = self.contribute_record(
            left_participant["id"], **(left_overrides or {})
        )
        right_record = self.contribute_record(
            right_participant["id"], **(right_overrides or {})
        )
        return {
            "left_participant": left_participant,
            "right_participant": right_participant,
            "left_record": left_record,
            "right_record": right_record,
            "link": self.only_link_between(right_record["id"]),
        }

    # ------------------------------------------------------------------
    # Tier 3: consent directives
    # ------------------------------------------------------------------

    def record_directive(self, cluster_id: str, **overrides) -> Dict[str, Any]:
        """Record a directive on a cluster, reading its live version for the guard."""
        headers = overrides.pop("headers", self.privacy_officer)
        overrides.setdefault("expected_cluster_version", self.cluster_version(cluster_id))
        payload: Dict[str, Any] = {
            "directive_type": overrides.pop("directive_type", "OPT_OUT"),
            "scope": overrides.pop("scope", "ALL_PARTICIPANTS"),
            "expected_cluster_version": overrides.pop("expected_cluster_version"),
        }
        payload.update(overrides)
        return get_success_data(
            self.client.record_consent_directive(headers, cluster_id, **payload)
        )

    # ------------------------------------------------------------------
    # Tier 4: emergency access, review and sanction accrual
    # ------------------------------------------------------------------

    def open_break_glass(
        self,
        cluster_id: str,
        invoking_participant_id: str,
        emergency_category: str = "UNCONSCIOUS_PATIENT",
        justification_text: str = VALID_JUSTIFICATION,
        clinician_user_id: str = CLINICIAN_USER_ID,
    ) -> Dict[str, Any]:
        """Open an emergency session; expires four hours after the logical clock."""
        return get_success_data(
            self.client.open_break_glass_access(
                make_clinician_headers(clinician_user_id),
                cluster_id=cluster_id,
                invoking_participant_id=invoking_participant_id,
                emergency_category=emergency_category,
                justification_text=justification_text,
            )
        )

    def get_break_glass(self, break_glass_id: str) -> Dict[str, Any]:
        return validate_success(
            self.client.get_break_glass_access(self.admin, break_glass_id), 200
        )

    def unjustified_review(
        self,
        break_glass_id: str,
        review_note: str,
        reviewer_user_id: str = PRIVACY_OFFICER_USER_ID,
    ) -> Dict[str, Any]:
        """Claim then decide a session UNJUSTIFIED, awarding the category's points."""
        reviewer = make_privacy_officer_headers(reviewer_user_id)
        validate_success(self.client.claim_break_glass_review(reviewer, break_glass_id), 200)
        return validate_success(
            self.client.decide_break_glass_review(
                reviewer, break_glass_id, outcome="UNJUSTIFIED", review_note=review_note
            ),
            200,
        )

    def justified_review(
        self,
        break_glass_id: str,
        review_note: str = "Emergency assertion matched the chart.",
        reviewer_user_id: str = PRIVACY_OFFICER_USER_ID,
    ) -> Dict[str, Any]:
        """Claim then decide a session JUSTIFIED, awarding zero points."""
        reviewer = make_privacy_officer_headers(reviewer_user_id)
        validate_success(self.client.claim_break_glass_review(reviewer, break_glass_id), 200)
        return validate_success(
            self.client.decide_break_glass_review(
                reviewer, break_glass_id, outcome="JUSTIFIED", review_note=review_note
            ),
            200,
        )

    # ------------------------------------------------------------------
    # Tier 4: subscriptions
    # ------------------------------------------------------------------

    def create_subscription(self, participant_id: str, **overrides) -> Dict[str, Any]:
        """Create a subscription for a participant; it lands in PENDING_ACTIVATION."""
        headers = overrides.pop("headers", make_participant_admin_headers(participant_id))
        return get_success_data(
            self.client.create_notification_subscription(
                headers, participant_id, **subscription_payload(**overrides)
            )
        )

    def active_subscription(self, participant_id: str, **overrides) -> Dict[str, Any]:
        """Create and activate a subscription, which needs a PASSED ADT_PUBLISHER run."""
        subscription = self.create_subscription(participant_id, **overrides)
        return validate_success(
            self.client.transition_subscription_lifecycle(
                make_participant_admin_headers(participant_id),
                subscription["id"],
                action="ACTIVATE",
            ),
            200,
        )

    # ------------------------------------------------------------------
    # Tier 5: invoicing and terminal states
    # ------------------------------------------------------------------

    def issue_invoice(self, participant_id: str, **overrides) -> Dict[str, Any]:
        """Issue an invoice over a fully elapsed period."""
        headers = overrides.pop("headers", self.admin)
        return get_success_data(
            self.client.issue_participation_invoice(
                headers, participant_id, **invoice_payload(**overrides)
            )
        )

    def delinquent_invoice(self, participant_id: str, **overrides) -> Dict[str, Any]:
        """Issue an invoice, move the clock past its due date and declare it delinquent."""
        overrides.setdefault("due_date", "2026-08-15T00:00:00Z")
        invoice = self.issue_invoice(participant_id, **overrides)
        self.set_clock("2026-08-16T00:00:00Z")
        return validate_success(
            self.client.administer_participation_invoice(
                self.admin, invoice["id"], action="DECLARE_DELINQUENT", reason="Unpaid past due"
            ),
            200,
        )

    def get_invoice(self, invoice_id: str) -> Dict[str, Any]:
        return validate_success(
            self.client.get_participation_invoice(self.admin, invoice_id), 200
        )

    def suspend_participant(self, participant_id: str, reason: str = "Operator action") -> Dict[str, Any]:
        """CERTIFIED -> SUSPENDED, firing the feed and subscription cascades."""
        return validate_success(
            self.client.transition_onboarding(
                self.admin, participant_id, action="SUSPEND", reason=reason
            ),
            200,
        )

    def terminate_participant(
        self, participant_id: str, reason: str = "Exchange exit"
    ) -> Dict[str, Any]:
        """Suspend then terminate, the exchange's final act on a participant."""
        self.suspend_participant(participant_id)
        return validate_success(
            self.client.transition_onboarding(
                self.admin, participant_id, action="TERMINATE", reason=reason
            ),
            200,
        )

    # ------------------------------------------------------------------
    # Locator queries
    # ------------------------------------------------------------------

    def submit_query(self, querying_participant_id: str, **overrides) -> Dict[str, Any]:
        """Submit a locator query as a Clinician asserting TREATMENT by default."""
        headers = overrides.pop("headers", self.clinician)
        payload: Dict[str, Any] = {
            "querying_participant_id": querying_participant_id,
            "purpose_of_use": overrides.pop("purpose_of_use", "TREATMENT"),
        }
        payload.update(overrides)
        return get_success_data(
            self.client.submit_record_locator_query(headers, **payload)
        )

    def audit_entries_for_query(self, query_id: str) -> List[Dict[str, Any]]:
        """The audit rows a query wrote, in the order the list read returns them."""
        return validate_success(
            self.client.list_access_audit_entries(
                self.privacy_officer, query_id=query_id, limit=100
            ),
            200,
        )


# ======================================================================
# pytest fixtures
# ======================================================================


@pytest.fixture
def client() -> ApiClient:
    """The shared API client."""
    return api_client


@pytest.fixture
def hie(client: ApiClient) -> HieHarness:
    """Setup orchestration for the record locator API."""
    return HieHarness(client)


@pytest.fixture
def hie_admin() -> Dict[str, str]:
    """Headers for the default `HieAdmin` operator."""
    return make_hie_admin_headers()


@pytest.fixture
def second_hie_admin() -> Dict[str, str]:
    """Headers for a second, distinct `HieAdmin` operator."""
    return make_hie_admin_headers(HIE_ADMIN_CERTIFIER_USER_ID)


@pytest.fixture
def privacy_officer() -> Dict[str, str]:
    """Headers for the default `PrivacyOfficer` operator."""
    return make_privacy_officer_headers()


@pytest.fixture
def clinician() -> Dict[str, str]:
    """Headers for the default `Clinician` operator."""
    return make_clinician_headers()


@pytest.fixture
def default_clock() -> str:
    """The instant the logical clock reads before it has ever been set."""
    return DEFAULT_CLOCK


@pytest.fixture
def governance(hie: HieHarness) -> Dict[str, Any]:
    """An ACTIVE consent policy generation and an ACTIVE tuning generation."""
    policy, config = hie.activate_governance()
    return {"policy": policy, "threshold_config": config}


@pytest.fixture
def applied_participant(hie: HieHarness) -> Dict[str, Any]:
    """A freshly registered participant in APPLIED."""
    return hie.register_participant()


@pytest.fixture
def testing_participant(hie: HieHarness) -> Dict[str, Any]:
    """A participant in CONFORMANCE_TESTING, ready to contribute data."""
    return hie.participant_in_conformance_testing()


@pytest.fixture
def certified_participant(hie: HieHarness) -> Dict[str, Any]:
    """A CERTIFIED participant holding all three required profiles."""
    return hie.certified_participant()


@pytest.fixture
def querying_participant(hie: HieHarness, governance: Dict[str, Any]) -> Dict[str, Any]:
    """A CERTIFIED participant with a MONITORED CCDA feed, able to submit queries."""
    return hie.certified_participant_with_document_feed()


@pytest.fixture
def record_pair(hie: HieHarness, governance: Dict[str, Any]) -> Dict[str, Any]:
    """Two contributors, one identical record each, and the single link between them."""
    return hie.two_participant_record_pair()
