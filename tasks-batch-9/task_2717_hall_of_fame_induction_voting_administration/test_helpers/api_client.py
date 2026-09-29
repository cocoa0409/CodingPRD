"""API client: one method per endpoint defined in the PRD.

Also hosts the single timestamp-canonicalisation helper used by the whole
suite. The PRD requires instants to be rendered in ISO-8601 UTC, but a
conforming implementation may render an instant either with or without
fractional seconds depending on the field, so instant *equality* checks go
through ``canonical_instant`` / ``same_instant`` rather than raw string
comparison. Responses themselves are never rewritten, so format assertions
still see exactly what the server sent.
"""

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


# --------------------------------------------------------------------------
# Timestamp canonicalisation (uniform across the suite)
# --------------------------------------------------------------------------
def canonical_instant(value: Any) -> Any:
    """Reduce an ISO-8601 UTC instant to a canonical comparable form.

    ``2026-08-01T00:00:00Z``, ``2026-08-01T00:00:00.000Z`` and
    ``2026-08-01T00:00:00+00:00`` all canonicalise to the same value.
    Non-string / unparseable values are returned unchanged.
    """
    if not isinstance(value, str):
        return value
    text = value.strip()
    normalised = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(normalised)
    except ValueError:
        return text
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def same_instant(left: Any, right: Any) -> bool:
    """True when two ISO-8601 instants denote the same point in time."""
    return canonical_instant(left) == canonical_instant(right)


class ApiClient(GenericApiClient):
    """One method per endpoint in the PRD's endpoint table."""

    # ---------------- logical clock ----------------
    def set_clock(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ---------------- induction cycles ----------------
    def create_induction_cycle(self, payload, headers):
        return self._request("POST", "/induction-cycles", payload, headers)

    def list_induction_cycles(self, headers, params=None):
        return self._request("GET", "/induction-cycles", headers=headers, params=params)

    def get_induction_cycle(self, cycle_id, headers):
        return self._request("GET", f"/induction-cycles/{cycle_id}", headers=headers)

    def open_nominations(self, cycle_id, headers, payload=None):
        return self._request(
            "POST", f"/induction-cycles/{cycle_id}/open-nominations", payload, headers
        )

    def close_nominations(self, cycle_id, headers, payload=None):
        return self._request(
            "POST", f"/induction-cycles/{cycle_id}/close-nominations", payload, headers
        )

    def certify_election(self, cycle_id, headers, payload=None):
        return self._request(
            "POST", f"/induction-cycles/{cycle_id}/certify-election", payload, headers
        )

    def patch_ceremony(self, cycle_id, payload, headers):
        return self._request(
            "PATCH", f"/induction-cycles/{cycle_id}/ceremony", payload, headers
        )

    def hold_ceremony(self, cycle_id, headers, payload=None):
        return self._request(
            "POST", f"/induction-cycles/{cycle_id}/hold-ceremony", payload, headers
        )

    # ---------------- eligibility rules ----------------
    def create_eligibility_rule(self, payload, headers):
        return self._request("POST", "/eligibility-rules", payload, headers)

    def list_eligibility_rules(self, headers, params=None):
        return self._request("GET", "/eligibility-rules", headers=headers, params=params)

    def get_eligibility_rule(self, rule_id, headers):
        return self._request("GET", f"/eligibility-rules/{rule_id}", headers=headers)

    # ---------------- voter blocs ----------------
    def create_voter_bloc(self, payload, headers):
        return self._request("POST", "/voter-blocs", payload, headers)

    def list_voter_blocs(self, headers, params=None):
        return self._request("GET", "/voter-blocs", headers=headers, params=params)

    def get_voter_bloc(self, bloc_id, headers):
        return self._request("GET", f"/voter-blocs/{bloc_id}", headers=headers)

    # ---------------- candidates ----------------
    def create_candidate(self, payload, headers):
        return self._request("POST", "/candidates", payload, headers)

    def list_candidates(self, headers, params=None):
        return self._request("GET", "/candidates", headers=headers, params=params)

    def get_candidate(self, candidate_id, headers):
        return self._request("GET", f"/candidates/{candidate_id}", headers=headers)

    def patch_candidate(self, candidate_id, payload, headers):
        return self._request("PATCH", f"/candidates/{candidate_id}", payload, headers)

    def declare_permanent_ineligibility(self, candidate_id, payload, headers):
        return self._request(
            "POST", f"/candidates/{candidate_id}/permanent-ineligibility", payload, headers
        )

    # ---------------- electors ----------------
    def create_elector(self, payload, headers):
        return self._request("POST", "/electors", payload, headers)

    def list_electors(self, headers, params=None):
        return self._request("GET", "/electors", headers=headers, params=params)

    def get_elector(self, elector_id, headers):
        return self._request("GET", f"/electors/{elector_id}", headers=headers)

    def credential_elector(self, elector_id, headers, payload=None):
        return self._request(
            "POST", f"/electors/{elector_id}/credential", payload, headers
        )

    def suspend_elector(self, elector_id, payload, headers):
        return self._request("POST", f"/electors/{elector_id}/suspend", payload, headers)

    def reinstate_elector(self, elector_id, headers, payload=None):
        return self._request(
            "POST", f"/electors/{elector_id}/reinstate", payload, headers
        )

    # ---------------- candidacies ----------------
    def create_candidacy(self, payload, headers):
        return self._request("POST", "/candidacies", payload, headers)

    def list_candidacies(self, headers, params=None):
        return self._request("GET", "/candidacies", headers=headers, params=params)

    def get_candidacy(self, candidacy_id, headers):
        return self._request("GET", f"/candidacies/{candidacy_id}", headers=headers)

    def create_screening_decision(self, candidacy_id, payload, headers):
        return self._request(
            "POST", f"/candidacies/{candidacy_id}/screening-decisions", payload, headers
        )

    def create_supplement(self, candidacy_id, payload, headers):
        return self._request(
            "POST", f"/candidacies/{candidacy_id}/supplements", payload, headers
        )

    # ---------------- ballots ----------------
    def create_ballot(self, payload, headers):
        return self._request("POST", "/ballots", payload, headers)

    def list_ballots(self, headers, params=None):
        return self._request("GET", "/ballots", headers=headers, params=params)

    def get_ballot(self, ballot_id, headers):
        return self._request("GET", f"/ballots/{ballot_id}", headers=headers)

    def certify_ballot(self, ballot_id, headers, payload=None):
        return self._request("POST", f"/ballots/{ballot_id}/certify", payload, headers)

    def close_ballot(self, ballot_id, headers, payload=None):
        return self._request("POST", f"/ballots/{ballot_id}/close", payload, headers)

    def tally_ballot(self, ballot_id, headers, payload=None):
        return self._request("POST", f"/ballots/{ballot_id}/tally", payload, headers)

    def create_audit_decision(self, ballot_id, payload, headers):
        return self._request(
            "POST", f"/ballots/{ballot_id}/audit-decision", payload, headers
        )

    # ---------------- ballot slots ----------------
    def list_ballot_slots(self, headers, params=None):
        return self._request("GET", "/ballot-slots", headers=headers, params=params)

    def get_ballot_slot(self, slot_id, headers):
        return self._request("GET", f"/ballot-slots/{slot_id}", headers=headers)

    # ---------------- vote submissions ----------------
    def create_vote_submission(self, payload, headers):
        return self._request("POST", "/vote-submissions", payload, headers)

    def list_vote_submissions(self, headers, params=None):
        return self._request("GET", "/vote-submissions", headers=headers, params=params)

    def get_vote_submission(self, submission_id, headers):
        return self._request("GET", f"/vote-submissions/{submission_id}", headers=headers)

    def withdraw_vote_submission(self, submission_id, headers, payload=None):
        return self._request(
            "POST", f"/vote-submissions/{submission_id}/withdraw", payload, headers
        )

    # ---------------- inductions ----------------
    def list_inductions(self, headers, params=None):
        return self._request("GET", "/inductions", headers=headers, params=params)

    def get_induction(self, induction_id, headers):
        return self._request("GET", f"/inductions/{induction_id}", headers=headers)

    def create_artifact_intake(self, induction_id, payload, headers):
        return self._request(
            "POST", f"/inductions/{induction_id}/artifact-intake", payload, headers
        )

    # ---------------- travel grants ----------------
    def create_travel_grant(self, payload, headers):
        return self._request("POST", "/travel-grants", payload, headers)

    def list_travel_grants(self, headers, params=None):
        return self._request("GET", "/travel-grants", headers=headers, params=params)

    def get_travel_grant(self, grant_id, headers):
        return self._request("GET", f"/travel-grants/{grant_id}", headers=headers)

    def approve_travel_grant(self, grant_id, headers, payload=None):
        return self._request(
            "POST", f"/travel-grants/{grant_id}/approve", payload, headers
        )

    def deny_travel_grant(self, grant_id, headers, payload=None):
        return self._request("POST", f"/travel-grants/{grant_id}/deny", payload, headers)

    def cancel_travel_grant(self, grant_id, payload, headers):
        return self._request(
            "POST", f"/travel-grants/{grant_id}/cancel", payload, headers
        )

    # ---------------- exhibit cases ----------------
    def create_exhibit_case(self, payload, headers):
        return self._request("POST", "/exhibit-cases", payload, headers)

    def list_exhibit_cases(self, headers, params=None):
        return self._request("GET", "/exhibit-cases", headers=headers, params=params)

    def get_exhibit_case(self, case_id, headers):
        return self._request("GET", f"/exhibit-cases/{case_id}", headers=headers)

    # ---------------- exhibit installations ----------------
    def create_exhibit_installation(self, payload, headers):
        return self._request("POST", "/exhibit-installations", payload, headers)

    def list_exhibit_installations(self, headers, params=None):
        return self._request(
            "GET", "/exhibit-installations", headers=headers, params=params
        )

    def get_exhibit_installation(self, installation_id, headers):
        return self._request(
            "GET", f"/exhibit-installations/{installation_id}", headers=headers
        )

    def withdraw_exhibit_installation(self, installation_id, headers, payload=None):
        return self._request(
            "POST", f"/exhibit-installations/{installation_id}/withdraw", payload, headers
        )

    # ---------------- raw helpers (for negative-path probes) ----------------
    def raw_post(self, path: str, payload: Optional[Dict[str, Any]], headers):
        return self._request("POST", path, payload, headers)

    def raw_get(self, path: str, headers, params=None):
        return self._request("GET", path, headers=headers, params=params)

    def raw_patch(self, path: str, payload: Optional[Dict[str, Any]], headers):
        return self._request("PATCH", path, payload, headers)


api_client = ApiClient()
