"""One method per endpoint the API exposes.

Each method takes only what its endpoint needs and returns the raw
``requests.Response`` so tests can assert on both status and body.
"""
from typing import Any, Dict, Optional

import requests
from prd_bench_local_runner.testing import GenericApiClient

from .constants import API_PREFIX


class ApiClient(GenericApiClient):
    """Typed access to every documented endpoint."""

    def set_clock(
        self,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        """Pin the logical clock to a specific UTC instant."""
        return self.post(f"{API_PREFIX}/_clock/set_current_utc", json=payload, headers=headers)

    def create_insurer(
        self,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        """Register a participating insurer."""
        return self.post(f"{API_PREFIX}/insurers", json=payload, headers=headers)

    def get_insurer(
        self,
        resource_id: str,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        """Read one participating insurer."""
        return self.get(f"{API_PREFIX}/insurers/{resource_id}", headers=headers)

    def list_insurers(
        self,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        """List participating insurers."""
        return self.get(f"{API_PREFIX}/insurers", headers=headers, params=params)

    def insurer_compliance_action(
        self,
        resource_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        """Sanction, reinstate or withdraw a participating insurer."""
        return self.post(
            f"{API_PREFIX}/insurers/{resource_id}/compliance-action",
            json=payload if payload is not None else {},
            headers=headers,
        )

    def insurer_take_up_evaluation(
        self,
        resource_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        """Evaluate an insurer's mandatory-offer take-up rate."""
        return self.post(
            f"{API_PREFIX}/insurers/{resource_id}/take-up-evaluation",
            json=payload if payload is not None else {},
            headers=headers,
        )

    def create_policyholder(
        self,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        """Register a policyholder."""
        return self.post(f"{API_PREFIX}/policyholders", json=payload, headers=headers)

    def get_policyholder(
        self,
        resource_id: str,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        """Read one policyholder."""
        return self.get(f"{API_PREFIX}/policyholders/{resource_id}", headers=headers)

    def list_policyholders(
        self,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        """List policyholders."""
        return self.get(f"{API_PREFIX}/policyholders", headers=headers, params=params)

    def create_dwelling(
        self,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        """Register a dwelling for a policyholder."""
        return self.post(f"{API_PREFIX}/dwellings", json=payload, headers=headers)

    def get_dwelling(
        self,
        resource_id: str,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        """Read one dwelling."""
        return self.get(f"{API_PREFIX}/dwellings/{resource_id}", headers=headers)

    def list_dwellings(
        self,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        """List dwellings."""
        return self.get(f"{API_PREFIX}/dwellings", headers=headers, params=params)

    def declare_retrofit(
        self,
        resource_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        """Declare an unverified retrofit on a dwelling."""
        return self.post(
            f"{API_PREFIX}/dwellings/{resource_id}/declare-retrofit",
            json=payload if payload is not None else {},
            headers=headers,
        )

    def create_mandatory_offer(
        self,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        """Record a mandatory earthquake coverage offer."""
        return self.post(f"{API_PREFIX}/mandatory-offers", json=payload, headers=headers)

    def respond_to_offer(
        self,
        resource_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        """Record the policyholder's response to an offer."""
        return self.post(
            f"{API_PREFIX}/mandatory-offers/{resource_id}/respond",
            json=payload if payload is not None else {},
            headers=headers,
        )

    def reoffer(
        self,
        resource_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        """Issue a further round of an expired offer."""
        return self.post(
            f"{API_PREFIX}/mandatory-offers/{resource_id}/reoffer",
            json=payload if payload is not None else {},
            headers=headers,
        )

    def expire_offer(
        self,
        resource_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        """Administratively expire an outstanding offer."""
        return self.post(
            f"{API_PREFIX}/mandatory-offers/{resource_id}/expire",
            json=payload if payload is not None else {},
            headers=headers,
        )

    def get_mandatory_offer(
        self,
        resource_id: str,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        """Read one mandatory offer."""
        return self.get(f"{API_PREFIX}/mandatory-offers/{resource_id}", headers=headers)

    def list_mandatory_offers(
        self,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        """List mandatory offers."""
        return self.get(f"{API_PREFIX}/mandatory-offers", headers=headers, params=params)

    def create_policy(
        self,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        """Quote a policy against an accepted offer."""
        return self.post(f"{API_PREFIX}/policies", json=payload, headers=headers)

    def bind_policy(
        self,
        resource_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        """Bind a quoted policy so cover incepts."""
        return self.post(
            f"{API_PREFIX}/policies/{resource_id}/bind",
            json=payload if payload is not None else {},
            headers=headers,
        )

    def renew_policy(
        self,
        resource_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        """Renew a policy into its next term."""
        return self.post(
            f"{API_PREFIX}/policies/{resource_id}/renew",
            json=payload if payload is not None else {},
            headers=headers,
        )

    def cancel_policy(
        self,
        resource_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        """Cancel a policy."""
        return self.post(
            f"{API_PREFIX}/policies/{resource_id}/cancel",
            json=payload if payload is not None else {},
            headers=headers,
        )

    def policy_lifecycle_action(
        self,
        resource_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        """Drive a policy lifecycle transition such as lapse or quote expiry."""
        return self.post(
            f"{API_PREFIX}/policies/{resource_id}/lifecycle-action",
            json=payload if payload is not None else {},
            headers=headers,
        )

    def revoke_mitigation_discount(
        self,
        resource_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        """Withdraw a mitigation discount already applied to a policy."""
        return self.post(
            f"{API_PREFIX}/policies/{resource_id}/revoke-mitigation-discount",
            json=payload if payload is not None else {},
            headers=headers,
        )

    def get_policy(
        self,
        resource_id: str,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        """Read one policy."""
        return self.get(f"{API_PREFIX}/policies/{resource_id}", headers=headers)

    def list_policies(
        self,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        """List policies."""
        return self.get(f"{API_PREFIX}/policies", headers=headers, params=params)

    def create_grant_cycle(
        self,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        """Open a retrofit grant funding cycle."""
        return self.post(f"{API_PREFIX}/grant-cycles", json=payload, headers=headers)

    def close_grant_cycle(
        self,
        resource_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        """Close a grant funding cycle."""
        return self.post(
            f"{API_PREFIX}/grant-cycles/{resource_id}/close",
            json=payload if payload is not None else {},
            headers=headers,
        )

    def get_grant_cycle(
        self,
        resource_id: str,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        """Read one grant cycle."""
        return self.get(f"{API_PREFIX}/grant-cycles/{resource_id}", headers=headers)

    def list_grant_cycles(
        self,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        """List grant cycles."""
        return self.get(f"{API_PREFIX}/grant-cycles", headers=headers, params=params)

    def create_retrofit_grant(
        self,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        """Submit a retrofit grant application."""
        return self.post(f"{API_PREFIX}/retrofit-grants", json=payload, headers=headers)

    def begin_grant_review(
        self,
        resource_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        """Take a submitted grant application under review."""
        return self.post(
            f"{API_PREFIX}/retrofit-grants/{resource_id}/begin-review",
            json=payload if payload is not None else {},
            headers=headers,
        )

    def review_grant(
        self,
        resource_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        """Approve, deny or return a grant application for changes."""
        return self.post(
            f"{API_PREFIX}/retrofit-grants/{resource_id}/review",
            json=payload if payload is not None else {},
            headers=headers,
        )

    def resubmit_grant(
        self,
        resource_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        """Resubmit a grant application that was returned for changes."""
        return self.post(
            f"{API_PREFIX}/retrofit-grants/{resource_id}/resubmit",
            json=payload if payload is not None else {},
            headers=headers,
        )

    def reserve_grant_funds(
        self,
        resource_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        """Reserve cycle funds against an approved grant."""
        return self.post(
            f"{API_PREFIX}/retrofit-grants/{resource_id}/reserve-funds",
            json=payload if payload is not None else {},
            headers=headers,
        )

    def withdraw_grant(
        self,
        resource_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        """Withdraw a grant application."""
        return self.post(
            f"{API_PREFIX}/retrofit-grants/{resource_id}/withdraw",
            json=payload if payload is not None else {},
            headers=headers,
        )

    def get_retrofit_grant(
        self,
        resource_id: str,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        """Read one retrofit grant."""
        return self.get(f"{API_PREFIX}/retrofit-grants/{resource_id}", headers=headers)

    def list_retrofit_grants(
        self,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        """List retrofit grants."""
        return self.get(f"{API_PREFIX}/retrofit-grants", headers=headers, params=params)

    def create_contractor(
        self,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        """Register a retrofit contractor."""
        return self.post(f"{API_PREFIX}/contractors", json=payload, headers=headers)

    def set_contractor_certification(
        self,
        resource_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        """Change a contractor's certification standing."""
        return self.post(
            f"{API_PREFIX}/contractors/{resource_id}/certification",
            json=payload if payload is not None else {},
            headers=headers,
        )

    def get_contractor(
        self,
        resource_id: str,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        """Read one contractor."""
        return self.get(f"{API_PREFIX}/contractors/{resource_id}", headers=headers)

    def list_contractors(
        self,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        """List contractors."""
        return self.get(f"{API_PREFIX}/contractors", headers=headers, params=params)

    def create_retrofit_project(
        self,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        """Open a retrofit project against a funded grant."""
        return self.post(f"{API_PREFIX}/retrofit-projects", json=payload, headers=headers)

    def start_project_work(
        self,
        resource_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        """Mark retrofit work as under way."""
        return self.post(
            f"{API_PREFIX}/retrofit-projects/{resource_id}/start-work",
            json=payload if payload is not None else {},
            headers=headers,
        )

    def request_project_inspection(
        self,
        resource_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        """Move a project into the awaiting-inspection state."""
        return self.post(
            f"{API_PREFIX}/retrofit-projects/{resource_id}/request-inspection",
            json=payload if payload is not None else {},
            headers=headers,
        )

    def abandon_project(
        self,
        resource_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        """Abandon a retrofit project."""
        return self.post(
            f"{API_PREFIX}/retrofit-projects/{resource_id}/abandon",
            json=payload if payload is not None else {},
            headers=headers,
        )

    def get_retrofit_project(
        self,
        resource_id: str,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        """Read one retrofit project."""
        return self.get(f"{API_PREFIX}/retrofit-projects/{resource_id}", headers=headers)

    def list_retrofit_projects(
        self,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        """List retrofit projects."""
        return self.get(f"{API_PREFIX}/retrofit-projects", headers=headers, params=params)

    def create_inspection(
        self,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        """Schedule a retrofit inspection window."""
        return self.post(f"{API_PREFIX}/inspections", json=payload, headers=headers)

    def record_inspection_result(
        self,
        resource_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        """Record the outcome of a scheduled inspection."""
        return self.post(
            f"{API_PREFIX}/inspections/{resource_id}/record-result",
            json=payload if payload is not None else {},
            headers=headers,
        )

    def get_inspection(
        self,
        resource_id: str,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        """Read one inspection."""
        return self.get(f"{API_PREFIX}/inspections/{resource_id}", headers=headers)

    def list_inspections(
        self,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        """List inspections."""
        return self.get(f"{API_PREFIX}/inspections", headers=headers, params=params)

    def create_catastrophe_event(
        self,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        """Record a catastrophe event."""
        return self.post(f"{API_PREFIX}/catastrophe-events", json=payload, headers=headers)

    def declare_event(
        self,
        resource_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        """Declare a catastrophe event."""
        return self.post(
            f"{API_PREFIX}/catastrophe-events/{resource_id}/declare",
            json=payload if payload is not None else {},
            headers=headers,
        )

    def levy_assessment(
        self,
        resource_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        """Levy a post-event assessment across assessable insurers."""
        return self.post(
            f"{API_PREFIX}/catastrophe-events/{resource_id}/levy-assessment",
            json=payload if payload is not None else {},
            headers=headers,
        )

    def close_event(
        self,
        resource_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        """Close a catastrophe event."""
        return self.post(
            f"{API_PREFIX}/catastrophe-events/{resource_id}/close",
            json=payload if payload is not None else {},
            headers=headers,
        )

    def get_catastrophe_event(
        self,
        resource_id: str,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        """Read one catastrophe event."""
        return self.get(f"{API_PREFIX}/catastrophe-events/{resource_id}", headers=headers)

    def list_catastrophe_events(
        self,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        """List catastrophe events."""
        return self.get(f"{API_PREFIX}/catastrophe-events", headers=headers, params=params)

    def create_reinsurance_layer(
        self,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        """Register a reinsurance layer for a treaty year."""
        return self.post(f"{API_PREFIX}/reinsurance-layers", json=payload, headers=headers)

    def set_reinsurance_layer_status(
        self,
        resource_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        """Change a reinsurance layer's status."""
        return self.post(
            f"{API_PREFIX}/reinsurance-layers/{resource_id}/status",
            json=payload if payload is not None else {},
            headers=headers,
        )

    def get_reinsurance_layer(
        self,
        resource_id: str,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        """Read one reinsurance layer."""
        return self.get(f"{API_PREFIX}/reinsurance-layers/{resource_id}", headers=headers)

    def list_reinsurance_layers(
        self,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        """List reinsurance layers."""
        return self.get(f"{API_PREFIX}/reinsurance-layers", headers=headers, params=params)

    def create_claim(
        self,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        """File a first notice of loss."""
        return self.post(f"{API_PREFIX}/claims", json=payload, headers=headers)

    def adjust_claim_provisional(
        self,
        resource_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        """Produce the provisional settlement figure for a claim."""
        return self.post(
            f"{API_PREFIX}/claims/{resource_id}/adjust-provisional",
            json=payload if payload is not None else {},
            headers=headers,
        )

    def finalize_claim_adjustment(
        self,
        resource_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        """Produce the final settlement figure for a claim."""
        return self.post(
            f"{API_PREFIX}/claims/{resource_id}/finalize-adjustment",
            json=payload if payload is not None else {},
            headers=headers,
        )

    def record_claim_payment(
        self,
        resource_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        """Record a payment against a settled claim."""
        return self.post(
            f"{API_PREFIX}/claims/{resource_id}/record-payment",
            json=payload if payload is not None else {},
            headers=headers,
        )

    def deny_claim(
        self,
        resource_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        """Deny a claim."""
        return self.post(
            f"{API_PREFIX}/claims/{resource_id}/deny",
            json=payload if payload is not None else {},
            headers=headers,
        )

    def reopen_claim(
        self,
        resource_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        """Reopen a closed claim."""
        return self.post(
            f"{API_PREFIX}/claims/{resource_id}/reopen",
            json=payload if payload is not None else {},
            headers=headers,
        )

    def close_claim(
        self,
        resource_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        """Close a claim."""
        return self.post(
            f"{API_PREFIX}/claims/{resource_id}/close",
            json=payload if payload is not None else {},
            headers=headers,
        )

    def get_claim(
        self,
        resource_id: str,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        """Read one claim."""
        return self.get(f"{API_PREFIX}/claims/{resource_id}", headers=headers)

    def list_claims(
        self,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        """List claims."""
        return self.get(f"{API_PREFIX}/claims", headers=headers, params=params)

    def get_assessment_allocation(
        self,
        resource_id: str,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        """Read one assessment allocation."""
        return self.get(f"{API_PREFIX}/assessment-allocations/{resource_id}", headers=headers)

    def list_assessment_allocations(
        self,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        """List assessment allocations."""
        return self.get(f"{API_PREFIX}/assessment-allocations", headers=headers, params=params)


# Shared client instance every test module uses.
api_client = ApiClient()
