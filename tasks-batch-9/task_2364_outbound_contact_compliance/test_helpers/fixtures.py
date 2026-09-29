"""Composite state builders and pytest fixtures.

Every test starts against an empty database, so all preconditions are built here
from scratch through the documented endpoints. ``ComplianceWorld`` exposes one
builder per step and a few whole-chain shortcuts for the recurring path
"policy -> contact -> approved script -> consent -> approved dialer profile ->
suppression list -> campaign -> scrub -> launch".
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pytest

from . import factories
from .api_client import ApiClient
from .assertions import assert_created, assert_ok
from .constants import (
    PHONE_C1,
    PHONE_C2,
    PHONE_NATIONAL_DNC,
    STATE_CA,
    TZ_LOS_ANGELES,
    UTC_OFFSET_LOS_ANGELES,
)
from .test_users import (
    make_campaign_manager_headers,
    make_compliance_officer_headers,
    make_dialer_operator_headers,
    make_platform_admin_headers,
    OFFICER_LAUNCHER_USER_ID,
    OFFICER_PROFILE_APPROVER_USER_ID,
    OFFICER_SCRIPT_APPROVER_USER_ID,
)
from .types import (
    AttemptOutcome,
    CampaignPurpose,
    Channel,
    ConsentType,
    CaptureMethod,
    DialerMode,
    Headers,
    ListType,
    RecordingConsentMode,
    RecordingConsentRegime,
    SuppressionSource,
)

# The canonical working instant used by the recipes: a Monday inside the CA
# policy period, with the logical clock at UTC midnight.
DEFAULT_CLOCK = "2026-08-03T00:00:00Z"
DEFAULT_WAIVER_REFERENCE = "WVR-2026-0142"


class ComplianceWorld:
    """Builder over the documented endpoints, one method per setup step."""

    def __init__(self, api: ApiClient):
        self.api = api
        self.admin = make_platform_admin_headers()
        self.manager = make_campaign_manager_headers()
        self.operator = make_dialer_operator_headers()
        self.officer = make_compliance_officer_headers()
        self.script_approver = make_compliance_officer_headers(
            OFFICER_SCRIPT_APPROVER_USER_ID
        )
        self.profile_approver = make_compliance_officer_headers(
            OFFICER_PROFILE_APPROVER_USER_ID
        )
        self.launcher = make_compliance_officer_headers(OFFICER_LAUNCHER_USER_ID)

    # ------------------------------------------------------------------
    # Clock
    # ------------------------------------------------------------------

    def set_clock(self, to_iso8601: str) -> None:
        """Move the logical clock to an exact instant."""
        response = self.api.set_current_utc(to_iso8601, self.admin)
        assert response.status_code in (200, 201, 204), (
            "clock move to %s failed: %s %s"
            % (to_iso8601, response.status_code, response.text)
        )

    def seed_rnd(self, phone_number: str, reassigned_on: str) -> None:
        """Seed the reassigned-numbers database with one disconnect date."""
        response = self.api.seed_rnd_record(phone_number, reassigned_on, self.admin)
        assert response.status_code in (200, 201, 204), (
            "rnd seed failed: %s %s" % (response.status_code, response.text)
        )

    # ------------------------------------------------------------------
    # Calling window policy
    # ------------------------------------------------------------------

    def create_policy(self, **kwargs: Any) -> Dict[str, Any]:
        """Publish one calling window policy for one state and period."""
        return assert_created(
            self.api.create_calling_window_policy(
                factories.calling_window_policy_payload(**kwargs), self.admin
            )
        )

    def create_ca_policy(self, **kwargs: Any) -> Dict[str, Any]:
        """Publish the standard 08:00-21:00 one-party CA policy."""
        defaults: Dict[str, Any] = {
            "state_code": STATE_CA,
            "window_start_local": "08:00",
            "window_end_local": "21:00",
            "recording_consent_regime": RecordingConsentRegime.ONE_PARTY,
            "effective_from": "2026-07-01T00:00:00Z",
            "effective_to": "2027-01-01T00:00:00Z",
        }
        defaults.update(kwargs)
        return self.create_policy(**defaults)

    def declare_emergency(self, policy_id: str, **kwargs: Any) -> Dict[str, Any]:
        """Declare a calling emergency on an active policy."""
        return assert_ok(
            self.api.declare_policy_emergency(
                policy_id, factories.declare_emergency_payload(**kwargs), self.admin
            )
        )

    # ------------------------------------------------------------------
    # Contact
    # ------------------------------------------------------------------

    def create_contact(self, **kwargs: Any) -> Dict[str, Any]:
        """Import one contact."""
        return assert_created(
            self.api.create_contact(factories.contact_payload(**kwargs), self.admin)
        )

    def create_ca_contact(self, **kwargs: Any) -> Dict[str, Any]:
        """Import the standard Los Angeles wireless contact."""
        defaults: Dict[str, Any] = {
            "phone_number": PHONE_C1,
            "state_code": STATE_CA,
            "utc_offset_minutes": UTC_OFFSET_LOS_ANGELES,
            "time_zone_label": TZ_LOS_ANGELES,
        }
        defaults.update(kwargs)
        return self.create_contact(**defaults)

    def create_second_ca_contact(self, **kwargs: Any) -> Dict[str, Any]:
        """Import a second Los Angeles contact on a distinct number."""
        defaults: Dict[str, Any] = {"phone_number": PHONE_C2}
        defaults.update(kwargs)
        return self.create_ca_contact(**defaults)

    def read_contact(self, contact_id: str, headers: Optional[Headers] = None):
        """Read one contact back."""
        return assert_ok(
            self.api.get_contact(contact_id, headers or self.officer)
        )

    def contact_version(self, contact_id: str) -> int:
        """Read the contact's current optimistic-concurrency counter."""
        return self.read_contact(contact_id)["version"]

    def number_status_check(self, contact_id: str, **kwargs: Any) -> Dict[str, Any]:
        """Run the reassigned-numbers check for one contact."""
        return assert_ok(
            self.api.number_status_check(
                contact_id, factories.number_status_check_payload(**kwargs), self.operator
            )
        )

    # ------------------------------------------------------------------
    # Agent script
    # ------------------------------------------------------------------

    def create_script(self, **kwargs: Any) -> Dict[str, Any]:
        """Draft one agent script."""
        return assert_created(
            self.api.create_agent_script(
                factories.agent_script_payload(**kwargs), self.manager
            )
        )

    def submit_script(self, script_id: str) -> Dict[str, Any]:
        """Move a drafted script into review."""
        return assert_ok(self.api.submit_agent_script_review(script_id, self.manager))

    def approve_script(
        self, script_id: str, headers: Optional[Headers] = None, **kwargs: Any
    ) -> Dict[str, Any]:
        """Approve a script in review."""
        return assert_ok(
            self.api.approve_agent_script(
                script_id,
                factories.agent_script_approve_payload(**kwargs),
                headers or self.script_approver,
            )
        )

    def request_script_changes(self, script_id: str, **kwargs: Any) -> Dict[str, Any]:
        """Send a script in review back to its author."""
        return assert_ok(
            self.api.request_agent_script_changes(
                script_id,
                factories.agent_script_request_changes_payload(**kwargs),
                self.script_approver,
            )
        )

    def approved_script(
        self, approver_headers: Optional[Headers] = None, **kwargs: Any
    ) -> Dict[str, Any]:
        """Draft, submit and approve one script in a single step."""
        script = self.create_script(**kwargs)
        self.submit_script(script["id"])
        return self.approve_script(script["id"], approver_headers)

    # ------------------------------------------------------------------
    # Consent record
    # ------------------------------------------------------------------

    def create_consent(
        self,
        contact_id: str,
        script_id: str,
        expected_contact_version: Optional[int] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Capture one consent record, re-reading the contact version first."""
        version = (
            self.contact_version(contact_id)
            if expected_contact_version is None
            else expected_contact_version
        )
        return assert_created(
            self.api.create_consent_record(
                factories.consent_record_payload(
                    contact_id=contact_id,
                    disclosure_script_id=script_id,
                    expected_contact_version=version,
                    **kwargs,
                ),
                self.officer,
            )
        )

    def suspend_consent(self, consent_record_id: str, **kwargs: Any) -> Dict[str, Any]:
        """Suspend an active consent record."""
        return assert_ok(
            self.api.suspend_consent_record(
                consent_record_id, factories.consent_suspend_payload(**kwargs), self.officer
            )
        )

    def reinstate_consent(self, consent_record_id: str, **kwargs: Any) -> Dict[str, Any]:
        """Reinstate a suspended or revoked consent record."""
        return assert_ok(
            self.api.reinstate_consent_record(
                consent_record_id,
                factories.consent_reinstate_payload(**kwargs),
                self.officer,
            )
        )

    # ------------------------------------------------------------------
    # Revocation request
    # ------------------------------------------------------------------

    def create_revocation(self, contact_id: str, **kwargs: Any) -> Dict[str, Any]:
        """Record one revocation request at intake."""
        return assert_created(
            self.api.create_revocation_request(
                factories.revocation_request_payload(contact_id=contact_id, **kwargs),
                self.officer,
            )
        )

    def validate_revocation(self, revocation_id: str, **kwargs: Any) -> Dict[str, Any]:
        """Validate a received revocation request."""
        return assert_ok(
            self.api.validate_revocation_request(
                revocation_id, factories.revocation_validate_payload(**kwargs), self.officer
            )
        )

    def propagate_revocation(self, revocation_id: str, **kwargs: Any) -> Dict[str, Any]:
        """Mark a validated revocation request propagated to downstream systems."""
        return assert_ok(
            self.api.propagate_revocation_request(
                revocation_id,
                factories.revocation_propagate_payload(**kwargs),
                self.officer,
            )
        )

    # ------------------------------------------------------------------
    # Suppression entries
    # ------------------------------------------------------------------

    def create_suppression(self, phone_number: str, **kwargs: Any) -> Dict[str, Any]:
        """Add one suppression entry."""
        return assert_created(
            self.api.create_suppression_entry(
                factories.suppression_entry_payload(phone_number=phone_number, **kwargs),
                self.officer,
            )
        )

    def create_fresh_national_list(
        self, phone_number: str = PHONE_NATIONAL_DNC, **kwargs: Any
    ) -> Dict[str, Any]:
        """Seed a national suppression row so the national list is non-empty and fresh."""
        defaults: Dict[str, Any] = {
            "list_type": ListType.NATIONAL,
            "source": SuppressionSource.FTC_DNC_DOWNLOAD,
            "source_refreshed_at": "2026-08-01T00:00:00Z",
        }
        defaults.update(kwargs)
        return self.create_suppression(phone_number, **defaults)

    def remove_suppression(self, entry_id: str, **kwargs: Any) -> Dict[str, Any]:
        """Withdraw one suppression entry."""
        return assert_ok(
            self.api.remove_suppression_entry(
                entry_id, factories.suppression_remove_payload(**kwargs), self.officer
            )
        )

    # ------------------------------------------------------------------
    # Dialer profile
    # ------------------------------------------------------------------

    def create_dialer_profile(self, **kwargs: Any) -> Dict[str, Any]:
        """Draft one dialer profile."""
        return assert_created(
            self.api.create_dialer_profile(
                factories.dialer_profile_payload(**kwargs), self.operator
            )
        )

    def approve_dialer_profile(
        self,
        dialer_profile_id: str,
        waiver_reference: Optional[str] = DEFAULT_WAIVER_REFERENCE,
        headers: Optional[Headers] = None,
    ) -> Dict[str, Any]:
        """Approve a drafted dialer profile, supplying a waiver when required."""
        return assert_ok(
            self.api.approve_dialer_profile(
                dialer_profile_id,
                factories.dialer_profile_approve_payload(
                    waiver_reference=waiver_reference
                ),
                headers or self.profile_approver,
            )
        )

    def approved_dialer_profile(
        self, waiver_reference: Optional[str] = DEFAULT_WAIVER_REFERENCE, **kwargs: Any
    ) -> Dict[str, Any]:
        """Draft and approve one dialer profile in a single step."""
        profile = self.create_dialer_profile(**kwargs)
        return self.approve_dialer_profile(profile["id"], waiver_reference)

    # ------------------------------------------------------------------
    # Campaign
    # ------------------------------------------------------------------

    def create_campaign(
        self, dialer_profile_id: str, agent_script_id: str, **kwargs: Any
    ) -> Dict[str, Any]:
        """Draft one campaign."""
        return assert_created(
            self.api.create_campaign(
                factories.campaign_payload(
                    dialer_profile_id=dialer_profile_id,
                    agent_script_id=agent_script_id,
                    **kwargs,
                ),
                self.manager,
            )
        )

    def read_campaign(
        self, campaign_id: str, headers: Optional[Headers] = None
    ) -> Dict[str, Any]:
        """Read one campaign back."""
        return assert_ok(
            self.api.get_campaign(campaign_id, headers or self.manager)
        )

    def campaign_version(self, campaign_id: str) -> int:
        """Read the campaign's current optimistic-concurrency counter."""
        return self.read_campaign(campaign_id)["version"]

    def create_scrub_job(
        self,
        campaign_id: str,
        list_types: Optional[List[str]] = None,
        expected_campaign_version: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Queue one scrub job, re-reading the campaign version first."""
        version = (
            self.campaign_version(campaign_id)
            if expected_campaign_version is None
            else expected_campaign_version
        )
        return assert_created(
            self.api.create_scrub_job(
                factories.scrub_job_payload(
                    campaign_id=campaign_id,
                    expected_campaign_version=version,
                    list_types=list_types,
                ),
                self.manager,
            )
        )

    def execute_scrub_job(self, scrub_job_id: str) -> Dict[str, Any]:
        """Run a queued scrub job."""
        return assert_ok(self.api.execute_scrub_job(scrub_job_id, self.manager))

    def scrub_campaign(
        self, campaign_id: str, list_types: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """Queue and run one scrub job for a campaign."""
        job = self.create_scrub_job(campaign_id, list_types=list_types)
        return self.execute_scrub_job(job["id"])

    def launch_campaign(
        self,
        campaign_id: str,
        headers: Optional[Headers] = None,
        expected_campaign_version: Optional[int] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Certify and launch a campaign, re-reading its version first."""
        version = (
            self.campaign_version(campaign_id)
            if expected_campaign_version is None
            else expected_campaign_version
        )
        return assert_ok(
            self.api.launch_campaign(
                campaign_id,
                factories.campaign_launch_payload(
                    expected_campaign_version=version, **kwargs
                ),
                headers or self.launcher,
            )
        )

    def suspend_campaign(self, campaign_id: str, **kwargs: Any) -> Dict[str, Any]:
        """Suspend a running campaign."""
        return assert_ok(
            self.api.suspend_campaign(
                campaign_id, factories.campaign_suspend_payload(**kwargs), self.officer
            )
        )

    def resume_campaign(self, campaign_id: str, **kwargs: Any) -> Dict[str, Any]:
        """Resume a suspended campaign."""
        return assert_ok(
            self.api.resume_campaign(
                campaign_id, factories.campaign_resume_payload(**kwargs), self.officer
            )
        )

    def close_campaign(self, campaign_id: str, **kwargs: Any) -> Dict[str, Any]:
        """Close a campaign."""
        return assert_ok(
            self.api.close_campaign(
                campaign_id, factories.campaign_close_payload(**kwargs), self.manager
            )
        )

    # ------------------------------------------------------------------
    # Contact attempts
    # ------------------------------------------------------------------

    def create_attempt(
        self, campaign_id: str, contact_id: str, channel: str = Channel.VOICE
    ) -> Dict[str, Any]:
        """Place one contact attempt."""
        return assert_created(
            self.api.create_contact_attempt(
                factories.contact_attempt_payload(
                    campaign_id=campaign_id, contact_id=contact_id, channel=channel
                ),
                self.operator,
            )
        )

    def record_outcome(self, attempt_id: str, **kwargs: Any) -> Dict[str, Any]:
        """Record the outcome of a pending attempt."""
        return assert_ok(
            self.api.record_attempt_outcome(
                attempt_id, factories.attempt_outcome_payload(**kwargs), self.operator
            )
        )

    def connected_attempt(
        self, campaign_id: str, contact_id: str, channel: str = Channel.VOICE
    ) -> Dict[str, Any]:
        """Place one attempt and record it as a live answer."""
        attempt = self.create_attempt(campaign_id, contact_id, channel)
        return self.record_outcome(
            attempt["id"],
            outcome=AttemptOutcome.CONNECTED_LIVE,
            agent_connect_seconds=1,
        )

    def abandoned_attempt(
        self, campaign_id: str, contact_id: str, channel: str = Channel.VOICE
    ) -> Dict[str, Any]:
        """Place one attempt and record it as abandoned with the message played."""
        attempt = self.create_attempt(campaign_id, contact_id, channel)
        return self.record_outcome(
            attempt["id"],
            outcome=AttemptOutcome.ABANDONED,
            abandon_message_played=True,
        )

    def void_attempt(self, attempt_id: str, **kwargs: Any) -> Dict[str, Any]:
        """Void one attempt."""
        return assert_ok(
            self.api.void_contact_attempt(
                attempt_id, factories.attempt_void_payload(**kwargs), self.officer
            )
        )

    # ------------------------------------------------------------------
    # Complaints
    # ------------------------------------------------------------------

    def create_complaint(
        self, contact_id: str, campaign_id: str, **kwargs: Any
    ) -> Dict[str, Any]:
        """Register one complaint."""
        return assert_created(
            self.api.create_complaint(
                factories.complaint_payload(
                    contact_id=contact_id, campaign_id=campaign_id, **kwargs
                ),
                self.officer,
            )
        )

    def substantiate_complaint(self, complaint_id: str, **kwargs: Any) -> Dict[str, Any]:
        """Substantiate an open complaint."""
        return assert_ok(
            self.api.substantiate_complaint(
                complaint_id,
                factories.complaint_substantiate_payload(**kwargs),
                make_compliance_officer_headers("officer-adjudicator"),
            )
        )

    def dismiss_complaint(self, complaint_id: str, **kwargs: Any) -> Dict[str, Any]:
        """Dismiss an open complaint."""
        return assert_ok(
            self.api.dismiss_complaint(
                complaint_id,
                factories.complaint_dismiss_payload(**kwargs),
                make_compliance_officer_headers("officer-adjudicator"),
            )
        )

    # ------------------------------------------------------------------
    # Whole-chain shortcuts
    # ------------------------------------------------------------------

    def build(
        self,
        clock: str = DEFAULT_CLOCK,
        state_code: str = STATE_CA,
        channel: str = Channel.VOICE,
        campaign_purpose: str = CampaignPurpose.MARKETING,
        consent_type: str = ConsentType.EXPRESS_WRITTEN,
        capture_method: str = CaptureMethod.WEB_FORM,
        recording_consent_mode: str = RecordingConsentMode.ONE_PARTY,
        recording_consent_regime: str = RecordingConsentRegime.ONE_PARTY,
        attempt_budget_total: int = 3,
        mode: str = DialerMode.PREDICTIVE,
        agents_available: int = 5,
        abandonment_limit_pct: float = 50.0,
        amd_enabled: bool = True,
        amd_abandon_on_machine: bool = False,
        abandon_message_seconds: int = 2,
        waiver_reference: Optional[str] = DEFAULT_WAIVER_REFERENCE,
        window_start_local: str = "08:00",
        window_end_local: str = "21:00",
        policy_effective_from: str = "2026-07-01T00:00:00Z",
        policy_effective_to: str = "2027-01-01T00:00:00Z",
        holiday_dates: Optional[List[str]] = None,
        contact_phone: str = PHONE_C1,
        utc_offset_minutes: int = UTC_OFFSET_LOS_ANGELES,
        time_zone_label: str = TZ_LOS_ANGELES,
        blocks: Optional[List[Dict[str, str]]] = None,
        covered_state_codes: Optional[List[str]] = None,
        target_state_codes: Optional[List[str]] = None,
        list_types: Optional[List[str]] = None,
        suppression_refreshed_at: str = "2026-08-01T00:00:00Z",
        run_number_status_check: bool = True,
        claimed_consent_date: str = "2026-07-15",
        campaign_name: str = "CA Aug Outreach",
        stop_after: str = "launch",
    ) -> Dict[str, Any]:
        """Build the recurring precondition chain up to a chosen stop point.

        ``stop_after`` is one of ``"campaign"`` (campaign left in DRAFT),
        ``"scrub"`` (scrub executed, campaign awaiting certification) or
        ``"launch"`` (campaign running). The returned mapping carries every
        entity created along the way.
        """
        self.set_clock(clock)

        policy = self.create_policy(
            state_code=state_code,
            window_start_local=window_start_local,
            window_end_local=window_end_local,
            recording_consent_regime=recording_consent_regime,
            effective_from=policy_effective_from,
            effective_to=policy_effective_to,
            holiday_dates=holiday_dates,
        )

        contact = self.create_contact(
            phone_number=contact_phone,
            state_code=state_code,
            utc_offset_minutes=utc_offset_minutes,
            time_zone_label=time_zone_label,
            attempt_budget_total=attempt_budget_total,
        )

        script = self.approved_script(
            name=campaign_name + " Script",
            channel=channel,
            blocks=blocks,
            recording_consent_mode=recording_consent_mode,
            covered_state_codes=[state_code]
            if covered_state_codes is None
            else covered_state_codes,
        )

        if run_number_status_check:
            contact = self.number_status_check(
                contact["id"], claimed_consent_date=claimed_consent_date
            )

        consent = self.create_consent(
            contact["id"],
            script["id"],
            channel=channel,
            consent_type=consent_type,
            capture_method=capture_method,
        )

        profile = self.create_dialer_profile(
            mode=mode,
            agents_available=agents_available,
            abandonment_limit_pct=abandonment_limit_pct,
            amd_enabled=amd_enabled,
            amd_abandon_on_machine=amd_abandon_on_machine,
            abandon_message_seconds=abandon_message_seconds,
        )
        profile = self.approve_dialer_profile(profile["id"], waiver_reference)

        national_entry = self.create_fresh_national_list(
            source_refreshed_at=suppression_refreshed_at
        )

        campaign = self.create_campaign(
            dialer_profile_id=profile["id"],
            agent_script_id=script["id"],
            name=campaign_name,
            channel=channel,
            campaign_purpose=campaign_purpose,
            target_state_codes=[state_code]
            if target_state_codes is None
            else target_state_codes,
        )

        world: Dict[str, Any] = {
            "policy": policy,
            "contact": contact,
            "script": script,
            "consent": consent,
            "profile": profile,
            "national_entry": national_entry,
            "campaign": campaign,
            "scrub_job": None,
        }

        if stop_after == "campaign":
            return world

        scrub_job = self.create_scrub_job(campaign["id"], list_types=list_types)
        scrub_job = self.execute_scrub_job(scrub_job["id"])
        world["scrub_job"] = scrub_job
        world["campaign"] = self.read_campaign(campaign["id"])

        if stop_after == "scrub":
            return world

        world["campaign"] = self.launch_campaign(campaign["id"])
        world["contact"] = self.read_contact(contact["id"])
        return world


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def api() -> ApiClient:
    """A client pointed at the service under test."""
    return ApiClient()


@pytest.fixture
def world(api: ApiClient) -> ComplianceWorld:
    """A builder over the documented endpoints, against an empty database."""
    return ComplianceWorld(api)


@pytest.fixture
def clocked_world(world: ComplianceWorld) -> ComplianceWorld:
    """A builder whose logical clock already sits on the canonical instant."""
    world.set_clock(DEFAULT_CLOCK)
    return world


@pytest.fixture
def draft_campaign(world: ComplianceWorld) -> Dict[str, Any]:
    """The full precondition chain with the campaign still in DRAFT."""
    return world.build(stop_after="campaign")


@pytest.fixture
def scrubbed_campaign(world: ComplianceWorld) -> Dict[str, Any]:
    """The full precondition chain with a completed scrub, awaiting certification."""
    return world.build(stop_after="scrub")


@pytest.fixture
def active_campaign(world: ComplianceWorld) -> Dict[str, Any]:
    """The full precondition chain with the campaign running."""
    return world.build(stop_after="launch")
