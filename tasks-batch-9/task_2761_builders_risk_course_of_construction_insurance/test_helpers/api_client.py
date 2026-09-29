"""API client: one method per endpoint defined in the PRD."""
import re

from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/builders-risk"

# The PRD fixes the *value* of every instant it specifies but pins the rendered
# fractional-second width only for `created_at`/`updated_at`; §2.5 states the
# governing comparison rule instead: "Datetimes are compared to whole-second
# precision." Responses are therefore canonicalised to whole-second precision
# here so a test may pin an instant by string without accidentally pinning a
# fractional-digit width the PRD never fixed.
_ISO_INSTANT_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.\d+)?(?:Z|\+00:00)$")


def _canonicalise_instants(value):
    """Recursively rewrite ISO 8601 UTC instants to whole-second precision."""
    if isinstance(value, str):
        match = _ISO_INSTANT_RE.match(value)
        return f"{match.group(1)}Z" if match else value
    if isinstance(value, list):
        return [_canonicalise_instants(item) for item in value]
    if isinstance(value, dict):
        return {key: _canonicalise_instants(item) for key, item in value.items()}
    return value


class ApiClient(GenericApiClient):
    def _request(self, *args, **kwargs):
        response = super()._request(*args, **kwargs)
        try:
            body = response.json()
        except ValueError:
            return response
        canonical = _canonicalise_instants(body)
        response.json = lambda **_kwargs: canonical
        return response

    # ---- ConstructionProject ------------------------------------------
    def create_project(self, payload, headers):
        return self._request("POST", f"{PREFIX}/projects", payload, headers)

    def screen_project(self, project_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/projects/{project_id}/screen", payload, headers)

    def declare_substantial_completion(self, project_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/projects/{project_id}/substantial-completion",
            payload, headers)

    def get_project(self, project_id, headers):
        return self._request("GET", f"{PREFIX}/projects/{project_id}", headers=headers)

    def list_projects(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/projects", headers=headers, params=params)

    def list_project_policies(self, project_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/projects/{project_id}/policies",
            headers=headers, params=params)

    def list_project_testing_notices(self, project_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/projects/{project_id}/testing-notices",
            headers=headers, params=params)

    # ---- BuildersRiskPolicy -------------------------------------------
    def create_policy(self, payload, headers):
        return self._request("POST", f"{PREFIX}/policies", payload, headers)

    def quote_policy(self, policy_id, headers):
        return self._request(
            "POST", f"{PREFIX}/policies/{policy_id}/quote", {}, headers)

    def referral_decision(self, policy_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/policies/{policy_id}/referral-decision", payload, headers)

    def reopen_policy(self, policy_id, headers):
        return self._request(
            "POST", f"{PREFIX}/policies/{policy_id}/reopen", {}, headers)

    def bind_policy(self, policy_id, headers):
        return self._request(
            "POST", f"{PREFIX}/policies/{policy_id}/bind", {}, headers)

    def incept_policy(self, policy_id, headers):
        return self._request(
            "POST", f"{PREFIX}/policies/{policy_id}/incept", {}, headers)

    def cancel_policy(self, policy_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/policies/{policy_id}/cancel", payload, headers)

    def get_policy(self, policy_id, headers):
        return self._request("GET", f"{PREFIX}/policies/{policy_id}", headers=headers)

    def list_policies(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/policies", headers=headers, params=params)

    def list_policy_coverage_parts(self, policy_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/policies/{policy_id}/coverage-parts",
            headers=headers, params=params)

    def list_policy_named_insured_interests(self, policy_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/policies/{policy_id}/named-insured-interests",
            headers=headers, params=params)

    def list_policy_extension_endorsements(self, policy_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/policies/{policy_id}/extension-endorsements",
            headers=headers, params=params)

    def list_policy_claims(self, policy_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/policies/{policy_id}/claims",
            headers=headers, params=params)

    def list_policy_premium_transactions(self, policy_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/policies/{policy_id}/premium-transactions",
            headers=headers, params=params)

    def list_policy_storage_assignments(self, policy_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/policies/{policy_id}/storage-assignments",
            headers=headers, params=params)

    def get_premium_summary(self, policy_id, headers):
        return self._request(
            "GET", f"{PREFIX}/policies/{policy_id}/premium-summary", headers=headers)

    # ---- CoveragePart -------------------------------------------------
    def create_coverage_part(self, payload, headers):
        return self._request("POST", f"{PREFIX}/coverage-parts", payload, headers)

    def patch_coverage_part(self, part_id, payload, headers):
        return self._request(
            "PATCH", f"{PREFIX}/coverage-parts/{part_id}", payload, headers)

    def get_coverage_part(self, part_id, headers):
        return self._request(
            "GET", f"{PREFIX}/coverage-parts/{part_id}", headers=headers)

    # ---- NamedInsuredInterest -----------------------------------------
    def create_named_insured_interest(self, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/named-insured-interests", payload, headers)

    def acknowledge_interest(self, interest_id, headers):
        return self._request(
            "POST", f"{PREFIX}/named-insured-interests/{interest_id}/acknowledge",
            {}, headers)

    def get_named_insured_interest(self, interest_id, headers):
        return self._request(
            "GET", f"{PREFIX}/named-insured-interests/{interest_id}", headers=headers)

    # ---- ExtensionEndorsement -----------------------------------------
    def create_extension_endorsement(self, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/extension-endorsements", payload, headers)

    def return_endorsement_for_info(self, endorsement_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/extension-endorsements/{endorsement_id}/return-for-info",
            payload, headers)

    def resubmit_endorsement(self, endorsement_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/extension-endorsements/{endorsement_id}/resubmit",
            payload, headers)

    def decide_endorsement(self, endorsement_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/extension-endorsements/{endorsement_id}/decision",
            payload, headers)

    def rescind_endorsement(self, endorsement_id, headers):
        return self._request(
            "POST", f"{PREFIX}/extension-endorsements/{endorsement_id}/rescind",
            {}, headers)

    def get_extension_endorsement(self, endorsement_id, headers):
        return self._request(
            "GET", f"{PREFIX}/extension-endorsements/{endorsement_id}", headers=headers)

    # ---- Claim --------------------------------------------------------
    def create_claim(self, payload, headers):
        return self._request("POST", f"{PREFIX}/claims", payload, headers)

    def adjust_claim(self, claim_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/claims/{claim_id}/adjust", payload, headers)

    def settle_claim(self, claim_id, headers):
        return self._request("POST", f"{PREFIX}/claims/{claim_id}/settle", {}, headers)

    def reopen_claim(self, claim_id, headers):
        return self._request("POST", f"{PREFIX}/claims/{claim_id}/reopen", {}, headers)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"{PREFIX}/claims/{claim_id}", headers=headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/claims", headers=headers, params=params)

    # ---- LossPayment --------------------------------------------------
    def create_loss_payment(self, payload, headers):
        return self._request("POST", f"{PREFIX}/loss-payments", payload, headers)

    def void_loss_payment(self, payment_id, headers):
        return self._request(
            "POST", f"{PREFIX}/loss-payments/{payment_id}/void", {}, headers)

    def list_loss_payments(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/loss-payments", headers=headers, params=params)

    def get_loss_payment(self, payment_id, headers):
        return self._request(
            "GET", f"{PREFIX}/loss-payments/{payment_id}", headers=headers)

    # ---- TestingCommissioningNotice -----------------------------------
    def create_testing_notice(self, payload, headers):
        return self._request("POST", f"{PREFIX}/testing-notices", payload, headers)

    def decide_testing_notice(self, notice_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/testing-notices/{notice_id}/decision", payload, headers)

    def get_testing_notice(self, notice_id, headers):
        return self._request(
            "GET", f"{PREFIX}/testing-notices/{notice_id}", headers=headers)

    # ---- StorageFacility ----------------------------------------------
    def create_facility(self, payload, headers):
        return self._request("POST", f"{PREFIX}/facilities", payload, headers)

    def patch_facility(self, facility_id, payload, headers):
        return self._request(
            "PATCH", f"{PREFIX}/facilities/{facility_id}", payload, headers)

    def get_facility(self, facility_id, headers):
        return self._request("GET", f"{PREFIX}/facilities/{facility_id}", headers=headers)

    def list_facilities(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/facilities", headers=headers, params=params)

    def list_facility_storage_assignments(self, facility_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/facilities/{facility_id}/storage-assignments",
            headers=headers, params=params)

    # ---- TemporaryStorageAssignment ------------------------------------
    def create_storage_assignment(self, payload, headers):
        return self._request("POST", f"{PREFIX}/storage-assignments", payload, headers)

    def release_storage_assignment(self, assignment_id, headers):
        return self._request(
            "POST", f"{PREFIX}/storage-assignments/{assignment_id}/release", {}, headers)

    def get_storage_assignment(self, assignment_id, headers):
        return self._request(
            "GET", f"{PREFIX}/storage-assignments/{assignment_id}", headers=headers)

    # ---- Logical clock -------------------------------------------------
    def set_clock(self, current_utc, headers):
        return self._request(
            "POST", f"{PREFIX}/_clock/set_current_utc", {"current_utc": current_utc},
            headers)

    # Raw variant for tests that must send a malformed clock payload.
    def set_clock_raw(self, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
