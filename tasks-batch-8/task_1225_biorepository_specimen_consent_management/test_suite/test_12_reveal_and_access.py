"""Controlled re-identification: reveal gating on active grant windows."""
from test_helpers import (
    validate_error,
    ApiErrorId,
    create_donor_with_consent,
    create_returned_kit,
    accession_specimen,
    create_key_for_specimen,
    create_grant_for_key,
    get_key,
    make_quality_officer_headers,
)


def test_reveal_without_active_grant_forbidden(api):
    """PRD §3.8: "Third, the terminal gate: the key must be `ACTIVE` (failing otherwise
    with `ERR_KEY_NOT_ACTIVE`, HTTP 409), there must exist an `ACTIVE` grant on this
    key whose closed window contains the current time, and the consent under which the
    specimen was collected must have `allow_reidentification` set to true — failures of
    these reveal preconditions surface as `ERR_NO_ACTIVE_GRANT` (HTTP 403)."

    Design: Corner/validations/reveal_without_active_grant_forbidden
    """
    donor, consent = create_donor_with_consent(allow_reidentification=True)
    kit = create_returned_kit(donor["id"])
    specimen = accession_specimen(donor["id"], kit["id"], consent["id"],
                                  initial_volume_ml=10.0)
    key = create_key_for_specimen(specimen["id"])
    # Grant window is in the future relative to the default clock 2026-05-01.
    grant = create_grant_for_key(key["id"], grantee_user_id="officer-a",
                                 starts_at="2026-06-01T09:00:00Z",
                                 ends_at="2026-06-01T17:00:00Z",
                                 purpose="scheduled audit")
    # Revealing officer differs from the grantee, so dual control is satisfied; the
    # future window does not contain the current clock.
    resp = api.reveal_key(
        key["id"],
        {"grant_id": grant["id"], "justification": "regulatory investigation request"},
        make_quality_officer_headers("qo-9"),
    )
    validate_error(resp, ApiErrorId.ERR_NO_ACTIVE_GRANT)
    assert get_key(key["id"])["reveal_count"] == 0
