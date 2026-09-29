"""API client: one method per endpoint defined in the PRD (§4)."""

from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/installations"


class ApiClient(GenericApiClient):
    """Typed access to every operation in the endpoint table of PRD §4."""

    # -- escape hatch for header-ladder tests -----------------------------
    def request(self, method, path, payload=None, headers=None, params=None):
        """Send an arbitrary request, e.g. with deliberately absent headers."""
        return self._request(method, path, payload, headers, params)

    # -- the logical clock ------------------------------------------------
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # -- plants -----------------------------------------------------------
    def create_plant(self, payload, headers):
        return self._request("POST", f"{PREFIX}/plants", payload, headers)

    def get_plant(self, plant_id, headers):
        return self._request("GET", f"{PREFIX}/plants/{plant_id}", headers=headers)

    def list_plants(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/plants", headers=headers, params=params)

    # -- haulers ----------------------------------------------------------
    def create_hauler(self, payload, headers):
        return self._request("POST", f"{PREFIX}/haulers", payload, headers)

    def get_hauler(self, hauler_id, headers):
        return self._request("GET", f"{PREFIX}/haulers/{hauler_id}", headers=headers)

    def list_haulers(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/haulers", headers=headers, params=params)

    # -- escort crews -----------------------------------------------------
    def create_escort_crew(self, payload, headers):
        return self._request("POST", f"{PREFIX}/escort-crews", payload, headers)

    def get_escort_crew(self, crew_id, headers):
        return self._request(
            "GET", f"{PREFIX}/escort-crews/{crew_id}", headers=headers
        )

    def list_escort_crews(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/escort-crews", headers=headers, params=params
        )

    # -- set crews --------------------------------------------------------
    def create_set_crew(self, payload, headers):
        return self._request("POST", f"{PREFIX}/set-crews", payload, headers)

    def get_set_crew(self, crew_id, headers):
        return self._request("GET", f"{PREFIX}/set-crews/{crew_id}", headers=headers)

    def list_set_crews(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/set-crews", headers=headers, params=params
        )

    # -- installation orders ---------------------------------------------
    def create_order(self, payload, headers):
        return self._request("POST", f"{PREFIX}/orders", payload, headers)

    def get_order(self, order_id, headers):
        return self._request("GET", f"{PREFIX}/orders/{order_id}", headers=headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/orders", headers=headers, params=params)

    def get_order_summary(self, order_id, headers):
        return self._request(
            "GET", f"{PREFIX}/orders/{order_id}/summary", headers=headers
        )

    # -- home sections ----------------------------------------------------
    def create_section(self, payload, headers):
        return self._request("POST", f"{PREFIX}/sections", payload, headers)

    def amend_section(self, section_id, payload, headers):
        return self._request(
            "PATCH", f"{PREFIX}/sections/{section_id}", payload, headers
        )

    def get_section(self, section_id, headers):
        return self._request("GET", f"{PREFIX}/sections/{section_id}", headers=headers)

    def list_sections(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/sections", headers=headers, params=params
        )

    def measure_section(self, section_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/sections/{section_id}/measure", payload, headers
        )

    def release_section(self, section_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/sections/{section_id}/release", payload, headers
        )

    # -- sites ------------------------------------------------------------
    def create_site(self, payload, headers):
        return self._request("POST", f"{PREFIX}/sites", payload, headers)

    def get_site(self, site_id, headers):
        return self._request("GET", f"{PREFIX}/sites/{site_id}", headers=headers)

    def list_sites(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/sites", headers=headers, params=params)

    def inspect_site_readiness(self, site_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/sites/{site_id}/readiness-inspection",
            payload,
            headers,
        )

    # -- transport permits ------------------------------------------------
    def create_permit(self, payload, headers):
        return self._request("POST", f"{PREFIX}/permits", payload, headers)

    def get_permit(self, permit_id, headers):
        return self._request("GET", f"{PREFIX}/permits/{permit_id}", headers=headers)

    def list_permits(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/permits", headers=headers, params=params)

    def pay_permit_fee(self, permit_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/permits/{permit_id}/pay-fee", payload, headers
        )

    def issue_permit(self, permit_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/permits/{permit_id}/issue", payload, headers
        )

    def revoke_permit(self, permit_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/permits/{permit_id}/revoke", payload, headers
        )

    # -- route legs -------------------------------------------------------
    def create_route_leg(self, payload, headers):
        return self._request("POST", f"{PREFIX}/route-legs", payload, headers)

    def get_route_leg(self, leg_id, headers):
        return self._request("GET", f"{PREFIX}/route-legs/{leg_id}", headers=headers)

    def list_route_legs(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/route-legs", headers=headers, params=params
        )

    def depart_route_leg(self, leg_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/route-legs/{leg_id}/depart", payload, headers
        )

    def arrive_route_leg(self, leg_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/route-legs/{leg_id}/arrive", payload, headers
        )

    # -- escort assignments -----------------------------------------------
    def create_escort_assignment(self, payload, headers):
        return self._request("POST", f"{PREFIX}/escort-assignments", payload, headers)

    def get_escort_assignment(self, assignment_id, headers):
        return self._request(
            "GET", f"{PREFIX}/escort-assignments/{assignment_id}", headers=headers
        )

    def list_escort_assignments(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/escort-assignments", headers=headers, params=params
        )

    def release_escort_assignment(self, assignment_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/escort-assignments/{assignment_id}/release",
            payload,
            headers,
        )

    # -- set jobs ---------------------------------------------------------
    def create_set_job(self, payload, headers):
        return self._request("POST", f"{PREFIX}/set-jobs", payload, headers)

    def get_set_job(self, job_id, headers):
        return self._request("GET", f"{PREFIX}/set-jobs/{job_id}", headers=headers)

    def list_set_jobs(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/set-jobs", headers=headers, params=params
        )

    def dispatch_set_job(self, job_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/set-jobs/{job_id}/dispatch", payload, headers
        )

    def record_scope_split(self, job_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/set-jobs/{job_id}/scope-split", payload, headers
        )

    def record_utility_crossover(self, job_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/set-jobs/{job_id}/utility-crossover", payload, headers
        )

    def close_marriage_line(self, job_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/set-jobs/{job_id}/close-marriage-line", payload, headers
        )

    def final_inspection(self, job_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/set-jobs/{job_id}/final-inspection", payload, headers
        )

    # -- marriage joints --------------------------------------------------
    def create_marriage_joint(self, payload, headers):
        return self._request("POST", f"{PREFIX}/marriage-joints", payload, headers)

    def get_marriage_joint(self, joint_id, headers):
        return self._request(
            "GET", f"{PREFIX}/marriage-joints/{joint_id}", headers=headers
        )

    def list_marriage_joints(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/marriage-joints", headers=headers, params=params
        )

    # -- anchoring certifications -----------------------------------------
    def create_anchor_certification(self, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/anchor-certifications", payload, headers
        )

    def get_anchor_certification(self, cert_id, headers):
        return self._request(
            "GET", f"{PREFIX}/anchor-certifications/{cert_id}", headers=headers
        )

    def list_anchor_certifications(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/anchor-certifications", headers=headers, params=params
        )

    def review_anchor_certification(self, cert_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/anchor-certifications/{cert_id}/review",
            payload,
            headers,
        )

    def resubmit_anchor_certification(self, cert_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/anchor-certifications/{cert_id}/resubmit",
            payload,
            headers,
        )

    # -- damage claims ----------------------------------------------------
    def create_damage_claim(self, payload, headers):
        return self._request("POST", f"{PREFIX}/damage-claims", payload, headers)

    def get_damage_claim(self, claim_id, headers):
        return self._request(
            "GET", f"{PREFIX}/damage-claims/{claim_id}", headers=headers
        )

    def list_damage_claims(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/damage-claims", headers=headers, params=params
        )

    def review_damage_claim(self, claim_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/damage-claims/{claim_id}/review", payload, headers
        )

    def dispute_damage_claim(self, claim_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/damage-claims/{claim_id}/dispute", payload, headers
        )

    def adjudicate_damage_claim(self, claim_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/damage-claims/{claim_id}/adjudicate", payload, headers
        )

    def reverse_damage_claim(self, claim_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/damage-claims/{claim_id}/reverse", payload, headers
        )


api_client = ApiClient()
