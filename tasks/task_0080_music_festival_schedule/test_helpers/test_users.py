"""Pre-built role header bundles for every role the PRD §2.1 declares.

Per the PRD §2.1 prose, every request carries two headers:
  - `X-User-ID` is the opaque actor identifier
  - `X-User-Role` is one of the eight declared role names

The PRD §2.1 also names that the role identities are opaque: there is no
"the acting Artist's id must equal the resource's artist_id" ownership
check anywhere in the API.  Consequently, the per-role `X-User-ID` is a
fixed opaque string per role — a stable test-user id distinct across the
seven concrete roles — and there is no per-instance ownership builder.
The eighth label `Any` from the §4 endpoint table is the catch-all open
to every authenticated role and is not a value any real request puts in
its `X-User-Role` header.

The synthetic system actor — the audit log's `actor_user_id == "system"`
literal that the PRD §2.1 names for clock-tick cascades, the festival
close cascade, and the post-event sweep — is exposed via a separate
helper for tests that want to filter the audit log on actor.
"""
from __future__ import annotations

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# The seven concrete role names from the PRD §2.1 prose.  The synthetic
# 'Any' label is the §4 endpoint-table shorthand for "open to every
# authenticated role" and is not a value any real request puts in
# X-User-Role; tests targeting an Any endpoint pick any of the seven
# concrete roles below.
_ROLE_NAMES = [
    "FestivalProducer",
    "ArtistLiaison",
    "StageManager",
    "TicketingAdmin",
    "SponsorshipAdmin",
    "AuditViewer",
    "PlatformAdmin",
]


def _role_user_id(role_name: str) -> str:
    """Per-role stable opaque X-User-ID string.  Distinct across roles so
    audit-log filtering on actor_user_id discriminates which operator
    performed which action."""
    # Lower-case the role and prefix with the literal "test-user-" so the
    # ids are easy to recognise in audit-log dumps.
    return f"test-user-{role_name.lower()}"


TEST_USERS: Dict[str, Dict[str, str]] = {
    f"{role.lower()}_headers": build_user_headers(_role_user_id(role), role)
    for role in _ROLE_NAMES
}

# Friendly aliases for the most-used roles.
PRODUCER_HEADERS = TEST_USERS["festivalproducer_headers"]
LIAISON_HEADERS = TEST_USERS["artistliaison_headers"]
STAGE_HEADERS = TEST_USERS["stagemanager_headers"]
TICKETING_HEADERS = TEST_USERS["ticketingadmin_headers"]
SPONSOR_HEADERS = TEST_USERS["sponsorshipadmin_headers"]
AUDIT_HEADERS = TEST_USERS["auditviewer_headers"]
ADMIN_HEADERS = TEST_USERS["platformadmin_headers"]


# A header bundle whose X-User-Role is the literal string "Unknown" — used
# by the negative test that asserts the role-name-recognition gate of
# §2.1.  The token must not match any of the seven concrete role names.
UNKNOWN_ROLE_HEADERS: Dict[str, str] = {
    "X-User-ID": "test-user-unknown",
    "X-User-Role": "UnknownRoleNotInMatrix",
}


# A header bundle that is missing the X-User-Role header entirely — for
# the "header presence" gate of §2.1 which surfaces
# ERR_MISSING_USER_CONTEXT_HEADER.  We send an empty dict.
NO_HEADERS: Dict[str, str] = {}


# The role-to-endpoint-allowlist mapping the PRD §2.1 prose declares,
# encoded here for the matrix-completeness tests.  Each entry names the
# canonical owner role for an endpoint family.  A test that wants the
# negative permission case picks a role NOT in the listed set.
ROLE_ALLOWLISTS: Dict[str, Dict[str, str]] = {
    # The mapping is consulted by the §3 RBAC matrix test.  Each value is
    # a comma-separated set of role names the PRD §2.1 prose names as the
    # endpoint's owners.  The keys are the natural-language operation
    # identifiers used in the test's docstrings.
    "festival_create":           {"FestivalProducer", "PlatformAdmin"},
    "festival_cancel":           {"FestivalProducer", "PlatformAdmin"},
    "open_scheduling":           {"FestivalProducer"},
    "exposure_catalog_write":    {"FestivalProducer"},
    "program_version_create":    {"FestivalProducer"},
    "program_version_submit":    {"FestivalProducer"},
    "program_version_return":    {"ArtistLiaison"},
    "program_version_publish":   {"FestivalProducer"},
    "program_version_withdraw":  {"FestivalProducer"},
    "stage_create":              {"FestivalProducer", "StageManager"},
    "stage_patch":               {"StageManager"},
    "equipment_kit_create":      {"StageManager", "FestivalProducer"},
    "equipment_kit_patch":       {"StageManager", "FestivalProducer"},
    "artist_create":             {"ArtistLiaison", "PlatformAdmin"},
    "artist_patch":              {"ArtistLiaison", "PlatformAdmin"},
    "program_item_create":       {"ArtistLiaison", "FestivalProducer"},
    "program_item_patch":        {"ArtistLiaison", "FestivalProducer"},
    "program_item_confirm":      {"ArtistLiaison", "FestivalProducer"},
    "program_item_announce":     {"ArtistLiaison"},
    "program_item_cancel":       {"ArtistLiaison", "FestivalProducer"},
    "program_item_recompute":    {"FestivalProducer", "PlatformAdmin"},
    "program_item_waive":        {"StageManager", "FestivalProducer"},
    "rider_create":               {"ArtistLiaison"},
    "rider_fulfil":               {"ArtistLiaison"},
    "team_create":                {"StageManager"},
    "team_withdraw":              {"StageManager"},
    "sound_check_create":         {"StageManager"},
    "sound_check_patch":          {"StageManager"},
    "sound_check_complete":       {"StageManager"},
    "sound_check_cancel":         {"StageManager"},
    "rehearsal_create":           {"StageManager"},
    "rehearsal_cancel":           {"StageManager"},
    "ticket_type_create":         {"TicketingAdmin"},
    "ticket_type_issue":          {"TicketingAdmin"},
    "ticket_type_suspend":        {"TicketingAdmin"},
    "ticket_type_resume":         {"TicketingAdmin"},
    "sponsor_tier_create":        {"SponsorshipAdmin", "FestivalProducer"},
    "exposure_allocation_create": {"SponsorshipAdmin"},
    "exposure_deliver":           {"SponsorshipAdmin"},
    "exposure_void":              {"SponsorshipAdmin"},
    "sponsor_sweep":              {"SponsorshipAdmin", "FestivalProducer"},
    "schedule_change_create":     {"FestivalProducer"},
    "schedule_change_apply":      {"FestivalProducer"},
    "schedule_change_reject":     {"FestivalProducer"},
    "schedule_change_revert":     {"FestivalProducer"},
    "audit_log_read":             {"AuditViewer", "FestivalProducer", "PlatformAdmin"},
    "fulfilment_report_read":     {"SponsorshipAdmin", "FestivalProducer", "AuditViewer"},
    "clock_advance":              {"PlatformAdmin"},
    "clock_read":                 {"PlatformAdmin", "AuditViewer"},
    "sync_ack":                   {"PlatformAdmin"},
    "refund_confirmed":           {"PlatformAdmin"},
    "sweep_run":                  {"PlatformAdmin", "SponsorshipAdmin"},
}


def header_bundle_for_role(role: str) -> Dict[str, str]:
    """Return the {X-User-ID, X-User-Role} bundle for a role name."""
    key = f"{role.lower()}_headers"
    assert key in TEST_USERS, f"Unknown role: {role!r}"
    return TEST_USERS[key]


def header_bundle_outside_set(allowed_roles: set) -> Dict[str, str]:
    """Return a header bundle for a role whose name is NOT in the allowed
    set.  Used by the negative permission tests.  Prefers AuditViewer
    (read-only on most things) and falls back to the first non-matching
    role from the seven-role list."""
    for candidate in ("AuditViewer", "TicketingAdmin", "SponsorshipAdmin",
                      "ArtistLiaison", "StageManager", "FestivalProducer",
                      "PlatformAdmin"):
        if candidate not in allowed_roles:
            return header_bundle_for_role(candidate)
    raise AssertionError(
        f"Every concrete role is on the allowlist {allowed_roles}; no negative "
        f"counter-example exists.  Tests for endpoints with universal allowlists "
        f"such as the 'Any' open-read endpoints in the PRD §4 table should be "
        f"only-positive."
    )


__all__ = [
    "TEST_USERS",
    "PRODUCER_HEADERS", "LIAISON_HEADERS", "STAGE_HEADERS",
    "TICKETING_HEADERS", "SPONSOR_HEADERS", "AUDIT_HEADERS", "ADMIN_HEADERS",
    "UNKNOWN_ROLE_HEADERS", "NO_HEADERS",
    "ROLE_ALLOWLISTS",
    "header_bundle_for_role", "header_bundle_outside_set",
]
